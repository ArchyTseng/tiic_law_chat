# src/uae_law_rag/backend/pipelines/evaluator/keyword_recall.py

"""
[职责] keyword_recall evaluator：计算 GT(全文 substring) 与 KW(FTS keyword_recall) 的 recall/precision，并返回前端可展示的 metrics。
[边界] 不写库；不触发 generation；仅依赖 node 表与 keyword_recall 逻辑。
[上游关系] api/routers/evaluator.py；playground gates。
[下游关系] 前端 EvaluatorPanel 可直接消费 metrics。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from uae_law_rag.backend.api.schemas_http.evaluator import KeywordRecallMetricView  # type: ignore
from uae_law_rag.backend.db.models.doc import DocumentModel, NodeModel  # type: ignore
from uae_law_rag.backend.pipelines.retrieval import keyword as keyword_mod  # type: ignore


@dataclass(frozen=True)
class _MetricRaw:
    keyword: str
    gt_nodes: Set[str]
    kw_nodes: Set[str]
    keyword_top_k: int


def _norm_keyword(k: str) -> str:
    return " ".join(str(k or "").strip().split())


def _sample(sorted_ids: Sequence[str], n: int) -> List[str]:
    if n <= 0:
        return []
    return list(sorted_ids[:n])


async def _compute_gt_nodes(
    *,
    session: AsyncSession,
    kb_id: str,
    keyword: str,
    case_sensitive: bool,
) -> Set[str]:
    """
    [职责] 计算 GT：node.text substring 出现的 node_id 集合（kb_id 作用域内）。
    [边界] 不使用 FTS；刻意贴近“前端展示原文片段”的产品定义。
    """
    kw = _norm_keyword(keyword)
    if not kw:
        return set()

    # docstring: SQLite LIKE 默认大小写行为依赖 collation；这里显式做 lower() 以保证一致性
    if case_sensitive:
        cond = func.coalesce(NodeModel.text, "").like(f"%{kw}%")
    else:
        cond = func.lower(func.coalesce(NodeModel.text, "")).like(f"%{kw.lower()}%")

    # docstring: 通过 document.kb_id 约束作用域（NodeModel 本身不应等于 kb_id）
    q = (
        select(NodeModel.id)
        .join(DocumentModel, DocumentModel.id == NodeModel.document_id)
        .where(DocumentModel.kb_id == str(kb_id))
        .where(cond)
    )
    res = await session.execute(q)
    rows = res.all()
    return {str(r[0]) for r in rows if r and r[0] is not None}


async def _compute_kw_nodes(
    *,
    session: AsyncSession,
    kb_id: str,
    keyword: str,
    top_k: int,
    allow_fallback: bool,
) -> Set[str]:
    """
    [职责] 计算 KW：调用现有 keyword_recall(FTS) 输出 node_id 集合（unique）。
    [边界] KW 与 GT 的“token/substring”定义不同是刻意的：KW 是系统实际 recall 行为。
    """
    kw = _norm_keyword(keyword)
    if not kw:
        return set()

    cands = await keyword_mod.keyword_recall(
        session=session,
        kb_id=str(kb_id),
        query=str(kw),
        top_k=int(top_k),
        file_id=None,
        allow_fallback=bool(allow_fallback),
    )
    out: Set[str] = set()
    for c in cands or []:
        nid = str(getattr(c, "node_id", "") or "").strip()
        if nid:
            out.add(nid)
    return out


def _calc_metric(*, raw: _MetricRaw, sample_n: int) -> KeywordRecallMetricView:
    gt_total = len(raw.gt_nodes)
    kw_total = len(raw.kw_nodes)
    overlap = len(raw.gt_nodes & raw.kw_nodes)

    recall: Optional[float]
    precision: Optional[float]

    if gt_total == 0:
        recall = None
        precision = None if kw_total == 0 else 0.0
    else:
        recall = float(overlap) / float(gt_total)
        precision = None if kw_total == 0 else float(overlap) / float(kw_total)

    capped = bool(kw_total >= int(raw.keyword_top_k) and gt_total > kw_total)

    missing = sorted(list(raw.gt_nodes - raw.kw_nodes))
    extra = sorted(list(raw.kw_nodes - raw.gt_nodes))

    return KeywordRecallMetricView(
        keyword=raw.keyword,
        gt_mode="substring",
        keyword_top_k=int(raw.keyword_top_k),
        gt_total=int(gt_total),
        kw_total=int(kw_total),
        overlap=int(overlap),
        recall=recall,
        precision=precision,
        capped=capped,
        missing_sample=_sample(missing, int(sample_n)),
        extra_sample=_sample(extra, int(sample_n)),
    )


async def evaluate_keyword_recall(
    *,
    session: AsyncSession,
    kb_id: str,
    raw_query: str,
    keywords: Sequence[str],
    keyword_top_k: Optional[int] = None,
    allow_fallback: bool = True,
    case_sensitive: bool = False,
    sample_n: int = 20,
    trace_id: str = "",
    request_id: str = "",
) -> Dict[str, Any]:
    """
    [职责] 针对一组 keywords 计算 keyword recall metrics（GT=substring, KW=FTS recall）。
    [边界] 不写库；只读；metrics 面向前端展示与解释。
    """
    t0 = time.perf_counter() * 1000.0
    metrics: List[KeywordRecallMetricView] = []

    kb_id = str(kb_id or "").strip()
    if not kb_id:
        raise ValueError("kb_id is required")

    top_k_eff = int(keyword_top_k) if keyword_top_k is not None else 200  # docstring: 与现有默认保持一致

    # docstring: 去重但保持顺序（便于前端稳定展示）
    seen: Set[str] = set()
    kws: List[str] = []
    for k in list(keywords or []):
        kk = _norm_keyword(k)
        if not kk or kk in seen:
            continue
        seen.add(kk)
        kws.append(kk)

    gt_ms = 0.0
    kw_ms = 0.0

    for kw in kws:
        t_gt0 = time.perf_counter() * 1000.0
        gt_nodes = await _compute_gt_nodes(session=session, kb_id=kb_id, keyword=kw, case_sensitive=case_sensitive)
        gt_ms += time.perf_counter() * 1000.0 - t_gt0

        t_kw0 = time.perf_counter() * 1000.0
        kw_nodes = await _compute_kw_nodes(
            session=session,
            kb_id=kb_id,
            keyword=kw,
            top_k=top_k_eff,
            allow_fallback=allow_fallback,
        )
        kw_ms += time.perf_counter() * 1000.0 - t_kw0

        metrics.append(
            _calc_metric(
                raw=_MetricRaw(keyword=kw, gt_nodes=gt_nodes, kw_nodes=kw_nodes, keyword_top_k=top_k_eff),
                sample_n=int(sample_n),
            )
        )

    total_ms = round(time.perf_counter() * 1000.0 - t0, 2)
    timing: Dict[str, Optional[float]] = {
        "total_ms": float(total_ms),
        "gt_ms": float(round(gt_ms, 2)),
        "kw_ms": float(round(kw_ms, 2)),
    }

    # docstring: meta 留作前端/审计扩展（trace/request）
    meta: Dict[str, Any] = {
        "raw_query": str(raw_query or ""),
        "keywords_n": len(metrics),
    }
    if trace_id:
        meta["trace_id"] = trace_id
    if request_id:
        meta["request_id"] = request_id

    return {
        "metrics": metrics,
        "timing_ms": timing,
        "meta": meta,
    }
