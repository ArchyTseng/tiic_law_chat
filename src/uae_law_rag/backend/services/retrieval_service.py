# src/uae_law_rag/backend/services/retrieval_service.py

"""
[职责] retrieval_service：封装 retrieval pipeline 执行与 gate 裁决，产出可复用检索结果快照。
[边界] 不创建/更新 message；不提交事务；不触发 generation/evaluator。
[上游关系] chat_service 调用 execute_retrieval。
[下游关系] generation/evaluator 使用 RetrievalBundle 与 gate 结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from uae_law_rag.backend.db.repo.retrieval_repo import RetrievalRepo
from uae_law_rag.backend.kb.repo import MilvusRepo
from uae_law_rag.backend.pipelines.base.context import PipelineContext
from uae_law_rag.backend.pipelines.retrieval.pipeline import run_retrieval_pipeline
from uae_law_rag.backend.schemas.retrieval import RetrievalBundle

__all__ = ["RetrievalGateDecision", "RetrievalServiceResult", "execute_retrieval"]


@dataclass(frozen=True)
class RetrievalGateDecision:
    """
    [职责] RetrievalGateDecision：封装 retrieval gate 裁决结果（是否通过 + 原因）。
    [边界] 仅表达 gate 结果，不负责 DB 写回。
    [上游关系] execute_retrieval 在 pipeline 完成后调用。
    [下游关系] chat_service 根据裁决决定 blocked/继续。
    """

    passed: bool
    reasons: Sequence[str]


@dataclass(frozen=True)
class RetrievalServiceResult:
    """
    [职责] RetrievalServiceResult：检索阶段输出汇总（bundle + 记录快照 + gate）。
    [边界] 不包含 message/status 写回；仅提供审计快照。
    [上游关系] execute_retrieval 返回。
    [下游关系] chat_service 组装 debug/状态机。
    """

    bundle: RetrievalBundle
    record_id: str
    provider_snapshot: Dict[str, Any]
    timing_ms: Dict[str, Any]
    hits_count: int
    gate: RetrievalGateDecision


def _evaluate_retrieval_gate(*, hits_count: int) -> RetrievalGateDecision:
    """
    [职责] 执行最小 retrieval gate 裁决（必须有命中）。
    [边界] 仅基于 hits_count；不做 coverage/quality 判断。
    [上游关系] execute_retrieval 在 pipeline 后调用。
    [下游关系] blocked/继续 的服务层决策。
    """
    if hits_count <= 0:
        return RetrievalGateDecision(passed=False, reasons=("no_evidence",))  # docstring: 无证据阻断
    return RetrievalGateDecision(passed=True, reasons=())  # docstring: 命中通过


async def execute_retrieval(
    *,
    session: AsyncSession,
    milvus_repo: MilvusRepo,
    retrieval_repo: RetrievalRepo,
    message_id: str,
    kb_id: str,
    query_text: str,
    query_vector: Optional[Sequence[float]],
    config: Mapping[str, Any],
    ctx: PipelineContext,
) -> RetrievalServiceResult:
    """
    [职责] 执行 retrieval pipeline 并汇总结果快照。
    [边界] 不提交事务；不创建 message；不处理 generation/evaluator。
    [上游关系] chat_service 调用。
    [下游关系] chat_service 获取 bundle/gate/provider_snapshot。
    """
    bundle = await run_retrieval_pipeline(
        session=session,
        milvus_repo=milvus_repo,
        retrieval_repo=retrieval_repo,
        message_id=message_id,
        kb_id=kb_id,
        query_text=query_text,
        query_vector=list(query_vector) if query_vector is not None else None,
        config=dict(config),
        ctx=ctx,
    )  # docstring: 执行 retrieval pipeline

    record_id = str(bundle.record.id)  # docstring: retrieval_record_id 快照
    provider_snapshot = dict(getattr(bundle.record, "provider_snapshot", {}) or {})  # docstring: provider_snapshot 快照
    timing_ms = dict(getattr(bundle.record, "timing_ms", {}) or {})  # docstring: timing_ms 快照
    hits_count = len(bundle.hits or [])  # docstring: 命中数量
    gate = _evaluate_retrieval_gate(hits_count=hits_count)  # docstring: gate 裁决

    return RetrievalServiceResult(
        bundle=bundle,
        record_id=record_id,
        provider_snapshot=provider_snapshot,
        timing_ms=timing_ms,
        hits_count=hits_count,
        gate=gate,
    )  # docstring: 返回结果快照
