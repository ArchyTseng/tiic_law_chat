# src/uae_law_rag/backend/pipelines/retrieval/rerank.py

"""
[职责] rerank：对融合候选进行精排（none/llm/bge_reranker），输出可解释的 rerank_score。
[边界] 仅对已有候选重排；不做检索与落库；可在依赖缺失时降级为 none。
[上游关系] fusion 输出 Candidate 列表；pipeline 传入 query/strategy/top_k。
[下游关系] persist 写入 RetrievalHitModel；generation/evaluator 消费 reranked hits。
"""

from __future__ import annotations

import inspect
from typing import Any, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, cast

from uae_law_rag.backend.pipelines.retrieval.types import Candidate


RerankStrategy = Literal["none", "llm", "bge_reranker"]  # docstring: rerank 策略枚举

_TEXT_KEYS = (
    "text",
    "content",
    "node_text",
    "chunk_text",
    "raw_text",
    "page_text",
)  # docstring: 候选文本来源的常见 key


def _normalize_strategy(strategy: str) -> Tuple[RerankStrategy, bool]:
    """
    [职责] 归一化 rerank 策略名称。
    [边界] 未知策略回退为 none。
    [上游关系] rerank 调用。
    [下游关系] 策略选择与降级标记。
    """
    s = str(strategy or "").strip().lower()  # docstring: 统一小写
    if s in {"none", "llm", "bge_reranker"}:
        return cast(RerankStrategy, s), False  # docstring: 合法策略
    return "none", True  # docstring: 未知策略回退


def _filter_kwargs(fn: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """
    [职责] 过滤参数，仅保留目标函数支持的关键字。
    [边界] 不做值校验；只做参数名过滤。
    [上游关系] _build_reranker 调用。
    [下游关系] reranker 构造函数。
    """
    try:
        sig = inspect.signature(fn)  # docstring: 读取可用参数
    except (TypeError, ValueError):
        return {}  # docstring: 无法获取签名时回退为空
    return {k: v for k, v in kwargs.items() if k in sig.parameters}  # docstring: 保留受支持参数


def _extract_text(candidate: Candidate) -> Tuple[str, Optional[str]]:
    """
    [职责] 从 Candidate 中提取可用于 rerank 的文本。
    [边界] 不拼接多段文本；优先 excerpt，其次 meta 字段。
    [上游关系] rerank 构建 LlamaIndex nodes 时调用。
    [下游关系] reranker 输入文本。
    """
    if candidate.excerpt and str(candidate.excerpt).strip():
        return str(candidate.excerpt), "excerpt"  # docstring: 优先使用 excerpt
    meta = candidate.meta or {}  # docstring: 透传 meta
    for key in _TEXT_KEYS:
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val, f"meta.{key}"  # docstring: 使用 meta 中的文本字段
    return "", None  # docstring: 无文本可用


def _load_llama_index() -> Dict[str, Any]:
    """
    [职责] 延迟加载 LlamaIndex rerank 组件（TextNode/NodeWithScore/SentenceTransformerRerank/LLMRerank）。
    [边界] 仅负责 import；不处理 rerank 逻辑。
    [上游关系] _build_reranker 调用。
    [下游关系] rerank 使用返回的类对象。
    """
    try:
        from llama_index.core.postprocessor import (  # type: ignore
            LLMRerank,
            SentenceTransformerRerank,
        )
        from llama_index.core.schema import NodeWithScore, TextNode  # type: ignore
    except Exception as exc:  # pragma: no cover - 依赖缺失场景
        raise ImportError("llama_index is required for rerank strategy") from exc  # docstring: 强制依赖
    return {
        "LLMRerank": LLMRerank,
        "SentenceTransformerRerank": SentenceTransformerRerank,
        "TextNode": TextNode,
        "NodeWithScore": NodeWithScore,
    }


def _build_reranker(
    *,
    strategy: RerankStrategy,
    model: Optional[str],
    top_k: int,
    rerank_config: Optional[Dict[str, Any]],
) -> Tuple[Any, str]:
    """
    [职责] 构造 reranker 实例（LLM 或 cross-encoder）。
    [边界] 仅封装构造；不执行 rerank。
    [上游关系] rerank 调用。
    [下游关系] _run_rerank 执行 postprocess。
    """
    li = _load_llama_index()  # docstring: 加载 LlamaIndex 组件
    cfg = rerank_config or {}  # docstring: 额外配置透传

    if strategy == "bge_reranker":
        SentenceTransformerRerank = li["SentenceTransformerRerank"]
        model_name = str(model or "BAAI/bge-reranker-large")  # docstring: 默认模型
        kwargs = {"model": model_name, "model_name": model_name, "top_n": int(top_k), **cfg}  # docstring: 参数快照
        reranker = SentenceTransformerRerank(
            **_filter_kwargs(SentenceTransformerRerank.__init__, kwargs)
        )  # docstring: 构造 cross-encoder reranker
        return reranker, model_name

    if strategy == "llm":
        LLMRerank = li["LLMRerank"]
        model_name = str(model or "llm")  # docstring: LLM rerank 标识
        kwargs = {"top_n": int(top_k), **cfg}  # docstring: LLM rerank 参数快照
        reranker = LLMRerank(**_filter_kwargs(LLMRerank.__init__, kwargs))  # docstring: 构造 LLM reranker
        return reranker, model_name

    return None, "none"  # docstring: none 策略占位


async def _maybe_await(value: Any) -> Any:
    """
    [职责] 兼容同步/异步 reranker 调用。
    [边界] 仅判断 awaitable；不捕获 rerank 异常。
    [上游关系] _run_rerank 调用。
    [下游关系] 返回 rerank 结果。
    """
    if inspect.isawaitable(value):
        return await value  # docstring: 异步结果
    return value  # docstring: 同步结果


async def _run_rerank(
    *,
    query: str,
    candidates: Sequence[Candidate],
    reranker: Any,
) -> Dict[int, float]:
    """
    [职责] 执行 rerank 并返回 {candidate_index: rerank_score}。
    [边界] 仅对有文本的候选 rerank；无文本候选不在返回中。
    [上游关系] rerank 调用。
    [下游关系] rerank 结果映射到 Candidate。
    """
    li = _load_llama_index()  # docstring: 加载 LlamaIndex 组件
    TextNode = li["TextNode"]
    NodeWithScore = li["NodeWithScore"]

    nodes: List[Any] = []
    for idx, cand in enumerate(candidates):
        text, source = _extract_text(cand)  # docstring: 提取 rerank 文本
        if not text:
            continue  # docstring: 无文本不参与 rerank
        node = TextNode(text=text, id_=f"cand-{idx}")  # docstring: 构造 TextNode
        node.metadata = {"candidate_idx": idx, "text_source": source, "node_id": cand.node_id}  # docstring: 追踪映射
        nodes.append(NodeWithScore(node=node, score=float(cand.score)))  # docstring: 初始分数透传

    if not nodes:
        return {}  # docstring: 无可 rerank 文本

    res = await _maybe_await(reranker.postprocess_nodes(nodes, query_str=query))  # docstring: 执行 rerank

    scores: Dict[int, float] = {}
    for item in res or []:
        node = getattr(item, "node", None)  # docstring: NodeWithScore.node
        meta = getattr(node, "metadata", {}) or {}  # docstring: 读取 metadata
        idx = meta.get("candidate_idx")
        if isinstance(idx, int):
            scores[idx] = float(getattr(item, "score", 0.0))  # docstring: 记录 rerank 分数
    return scores


def _stable_sort(candidates: Sequence[Candidate]) -> List[Tuple[int, Candidate]]:
    """
    [职责] 按 score 单调性稳定排序候选。
    [边界] 仅依赖 score；不做跨候选归一化。
    [上游关系] rerank none/兜底时调用。
    [下游关系] 排序后的候选序列。
    """
    indexed = list(enumerate(candidates))  # docstring: 保留原索引
    return sorted(indexed, key=lambda x: (-float(x[1].score), str(x[1].node_id)))  # docstring: 稳定排序


def _apply_rerank_result(
    *,
    ordered: Iterable[Tuple[int, Candidate]],
    scores: Dict[int, float],
    strategy: RerankStrategy,
    model: str,
    fallback: bool,
    fallback_reason: Optional[str],
    top_k: int,
) -> List[Candidate]:
    """
    [职责] 根据 rerank 结果生成新的 Candidate 列表（stage=rerank）。
    [边界] 不修改原候选对象；仅复制必要字段并写入 score_details。
    [上游关系] rerank 调用。
    [下游关系] persist/generation 使用 reranked 候选。
    """
    out: List[Candidate] = []
    for rank, (idx, cand) in enumerate(ordered, start=1):
        if len(out) >= int(top_k):
            break  # docstring: 截断 top_k
        applied = idx in scores  # docstring: 是否被 rerank 覆盖
        rerank_score = float(scores[idx]) if applied else float(cand.score)  # docstring: 未覆盖则继承原 score
        details = dict(cand.score_details or {})  # docstring: 复制分数细节
        details.update(
            {
                "rerank_applied": applied,
                "rerank_score": float(scores[idx]) if applied else None,
                "rerank_strategy": strategy,
                "rerank_model": model,
                "rerank_rank": rank,
                "rerank_fallback": fallback,
                "rerank_fallback_reason": fallback_reason,
            }
        )  # docstring: 写入 rerank 细节
        out.append(
            Candidate(
                node_id=str(cand.node_id),  # docstring: 节点ID
                stage="rerank",  # docstring: 标记 rerank 阶段
                score=rerank_score,  # docstring: rerank 分数
                score_details=details,  # docstring: 分数细节快照
                excerpt=cand.excerpt,  # docstring: 透传 excerpt
                page=cand.page,  # docstring: 透传 page
                start_offset=cand.start_offset,  # docstring: 透传起始偏移
                end_offset=cand.end_offset,  # docstring: 透传结束偏移
                meta=dict(cand.meta or {}),  # docstring: 透传 meta
            )
        )
    return out


async def rerank(
    *,
    query: str,
    candidates: Sequence[Candidate],
    strategy: str,
    top_k: int,
    model: Optional[str] = None,
    rerank_config: Optional[Dict[str, Any]] = None,
) -> List[Candidate]:
    """
    [职责] rerank：对候选集合执行精排并输出 rerank 候选列表。
    [边界] 仅重排已有候选；无可用依赖时可降级为 none。
    [上游关系] fusion 输出候选；pipeline 传入 query/strategy/top_k。
    [下游关系] persist/generation 消费 rerank 结果。
    """
    if int(top_k) <= 0 or not candidates:
        return []  # docstring: 空候选或非法 top_k 直接返回空

    normalized, fallback = _normalize_strategy(strategy)  # docstring: 归一化策略
    fallback_reason: Optional[str] = None

    if normalized == "none":
        ordered = _stable_sort(candidates)  # docstring: 按原 score 稳定排序
        return _apply_rerank_result(
            ordered=ordered,
            scores={},
            strategy=normalized,
            model=str(model or "none"),
            fallback=fallback,
            fallback_reason=fallback_reason,
            top_k=top_k,
        )  # docstring: none 策略直接返回

    try:
        reranker, model_name = _build_reranker(
            strategy=normalized,
            model=model,
            top_k=int(top_k),
            rerank_config=rerank_config,
        )  # docstring: 构造 reranker
    except Exception as exc:  # pragma: no cover - 依赖缺失场景
        ordered = _stable_sort(candidates)  # docstring: 依赖缺失时回退排序
        return _apply_rerank_result(
            ordered=ordered,
            scores={},
            strategy="none",
            model=str(model or "none"),
            fallback=True,
            fallback_reason=f"rerank_import_error:{exc.__class__.__name__}",
            top_k=top_k,
        )

    if reranker is None:
        ordered = _stable_sort(candidates)  # docstring: 无 reranker 回退排序
        return _apply_rerank_result(
            ordered=ordered,
            scores={},
            strategy="none",
            model=str(model or "none"),
            fallback=True,
            fallback_reason="reranker_unavailable",
            top_k=top_k,
        )

    scores = await _run_rerank(
        query=query,
        candidates=candidates,
        reranker=reranker,
    )  # docstring: 执行 rerank

    if not scores:
        fallback_reason = "rerank_no_text"  # docstring: 无可用文本
        ordered = _stable_sort(candidates)  # docstring: 回退排序
        return _apply_rerank_result(
            ordered=ordered,
            scores={},
            strategy="none",
            model=str(model or model_name),
            fallback=True,
            fallback_reason=fallback_reason,
            top_k=top_k,
        )

    reranked_idx = set(scores.keys())  # docstring: rerank 覆盖的候选索引
    reranked = [(idx, candidates[idx]) for idx in reranked_idx]  # docstring: rerank 候选子集
    reranked_sorted = sorted(
        reranked, key=lambda x: (-float(scores.get(x[0], 0.0)), str(x[1].node_id))
    )  # docstring: rerank 分数排序

    remaining = [(idx, cand) for idx, cand in enumerate(candidates) if idx not in reranked_idx]  # docstring: 未覆盖候选
    remaining_sorted = sorted(
        remaining, key=lambda x: (-float(x[1].score), str(x[1].node_id))
    )  # docstring: 未覆盖候选稳定排序

    # Rebuild ordered list: reranked first, then remaining
    ordered: List[Tuple[int, Candidate]] = []
    ordered.extend(reranked_sorted)  # docstring: 先加入 rerank 覆盖候选
    ordered.extend(remaining_sorted)  # docstring: 再加入未覆盖候选

    return _apply_rerank_result(
        ordered=ordered,
        scores=scores,
        strategy=normalized,
        model=str(model or model_name),
        fallback=fallback,
        fallback_reason=fallback_reason,
        top_k=top_k,
    )
