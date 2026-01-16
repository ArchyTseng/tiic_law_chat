# src/uae_law_rag/backend/services/evaluator_service.py

"""
[职责] evaluator_service：封装 evaluator pipeline 执行与裁决汇总，输出可审计评估快照。
[边界] 不修改 message/status；不触发 generation；不提交事务。
[上游关系] chat_service 调用 execute_evaluator。
[下游关系] chat_service/debug 使用评估结果与 gate/summary。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Sequence, cast

from sqlalchemy.ext.asyncio import AsyncSession

from uae_law_rag.backend.db.repo.evaluator_repo import EvaluatorRepo
from uae_law_rag.backend.pipelines.base.context import PipelineContext
from uae_law_rag.backend.pipelines.evaluator import checks as evaluator_checks
from uae_law_rag.backend.pipelines.evaluator.pipeline import run_evaluator_pipeline
from uae_law_rag.backend.schemas.evaluator import EvaluatorConfig, EvaluationResult
from uae_law_rag.backend.schemas.generation import GenerationBundle
from uae_law_rag.backend.schemas.retrieval import RetrievalBundle
from uae_law_rag.backend.utils.constants import TIMING_MS_KEY

__all__ = [
    "EvaluatorGateDecision",
    "EvaluatorServiceResult",
    "_build_evaluator_summary",
    "execute_evaluator",
]


@dataclass(frozen=True)
class EvaluatorGateDecision:
    """
    [职责] EvaluatorGateDecision：封装 evaluator 裁决状态与原因。
    [边界] 仅记录 evaluator 判定，不负责 message.status 映射。
    [上游关系] execute_evaluator 在 pipeline 完成后调用。
    [下游关系] message.status 映射与 debug 输出。
    """

    status: str
    reasons: Sequence[str]


@dataclass(frozen=True)
class EvaluatorServiceResult:
    """
    [职责] EvaluatorServiceResult：评估阶段输出汇总（结果 + gate + summary）。
    [边界] 不包含 message/status 写回；仅提供审计快照。
    [上游关系] execute_evaluator 返回。
    [下游关系] chat_service 组装 debug/状态机。
    """

    evaluation_result: EvaluationResult
    record_id: str
    timing_ms: Dict[str, Any]
    gate: EvaluatorGateDecision
    summary: Dict[str, Any]
    mapped_message_status: str


def _evaluate_evaluator_gate(result: EvaluationResult) -> EvaluatorGateDecision:
    """
    [职责] 解析 evaluator 结果并生成 gate 决策（status + reasons）。
    [边界] 仅基于 checks/warnings；不改变 evaluator status。
    [上游关系] execute_evaluator 在 pipeline 后调用。
    [下游关系] message.status 映射与 debug 输出。
    """
    status = str(result.status or "skipped")  # docstring: evaluator status
    reasons: list[str] = []  # docstring: 原因列表
    for check in list(result.checks or []):
        check_status = str(getattr(check, "status", "") or "")
        if check_status in {"fail", "warn"}:
            # NOTE: EvaluatorCheck MVP contract uses `reason` as the primary human-readable field.
            # Keep backward-compat with `message` if legacy objects exist.
            reason_text = str(
                getattr(check, "reason", "") or getattr(check, "message", "") or getattr(check, "name", "") or ""
            ).strip()
            reasons.append(reason_text or "check_failed")  # docstring: 兜底原因
    return EvaluatorGateDecision(status=status, reasons=tuple([r for r in reasons if r]))


def _map_evaluation_status(status: str, *, generation_status: str | None = None) -> str:
    """
    [职责] 将 EvaluationStatus 映射为 message.status（最终裁决）。
    [边界] 仅处理 pass/partial/fail/skipped；未知回退 failed。
    [上游关系] execute_evaluator 调用。
    [下游关系] chat_service 写回 message.status。
    """
    # docstring: generation 被判定 blocked 时，优先透传为 message.blocked（“有证据但不可验证引用”）
    if (generation_status or "").strip().lower() == "blocked":
        return "blocked"
    if status == "pass":
        return "success"  # docstring: evaluator pass -> success
    if status == "partial":
        return "partial"  # docstring: evaluator partial -> partial
    return "failed"  # docstring: fail/skipped -> failed


def _build_evaluator_summary(
    *,
    evaluator: EvaluationResult | None,
    fallback_status: str,
    fallback_rule_version: str,
    fallback_reasons: Sequence[str],
) -> Dict[str, Any]:
    """
    [职责] 组装 evaluator 摘要（status/rule_version/warnings）。
    [边界] evaluator 为空时回退到 fallback；不输出完整 checks。
    [上游关系] chat_service/execute_evaluator 调用。
    [下游关系] response.evaluator 供前端展示。
    """
    if evaluator is None:
        return {
            "status": fallback_status,
            "rule_version": fallback_rule_version,
            "warnings": list(fallback_reasons),
        }  # docstring: evaluator 缺失兜底
    warnings = []
    for check in list(evaluator.checks or []):
        if str(getattr(check, "status", "")) in {"warn", "fail"}:
            msg = str(
                getattr(check, "reason", "") or getattr(check, "message", "") or getattr(check, "name", "") or ""
            ).strip()
            if msg:
                warnings.append(msg)  # docstring: 收集 warn/fail 消息
    return {
        "status": str(evaluator.status),
        "rule_version": str(evaluator.config.rule_version),
        "warnings": [w for w in warnings if w],
    }  # docstring: evaluator 摘要


async def execute_evaluator(
    *,
    session: AsyncSession,
    evaluator_repo: EvaluatorRepo,
    conversation_id: str,
    message_id: str,
    retrieval_bundle: RetrievalBundle,
    generation_bundle: GenerationBundle,
    evaluator_config: EvaluatorConfig,
    ctx: PipelineContext,
) -> EvaluatorServiceResult:
    """
    [职责] 执行 evaluator pipeline 并汇总结果快照。
    [边界] 不提交事务；不创建 message；不触发 generation。
    [上游关系] chat_service 调用。
    [下游关系] chat_service 获取 evaluation_result/gate/summary。
    """
    evaluator_input = {
        "conversation_id": conversation_id,
        "message_id": message_id,
        "retrieval_bundle": retrieval_bundle,
        "generation_bundle": generation_bundle,
        "config": evaluator_config,
    }  # docstring: evaluator 输入快照
    evaluator_input_typed = cast(
        evaluator_checks.EvaluatorInput, evaluator_input
    )  # docstring: 类型收窄以匹配 EvaluatorInput

    evaluation_result = await run_evaluator_pipeline(
        session=session,
        evaluator_repo=evaluator_repo,
        input=evaluator_input_typed,
        ctx=ctx,
    )  # docstring: 执行 evaluator pipeline

    record_id = str(evaluation_result.id)  # docstring: evaluation_record_id 快照
    timing_ms = dict((evaluation_result.meta or {}).get(TIMING_MS_KEY, {}) or {})  # docstring: timing_ms 快照
    gate = _evaluate_evaluator_gate(evaluation_result)  # docstring: gate 裁决
    summary = _build_evaluator_summary(
        evaluator=evaluation_result,
        fallback_status="skipped",
        fallback_rule_version=str(evaluator_config.rule_version),
        fallback_reasons=(),
    )  # docstring: evaluator 摘要
    mapped_message_status = _map_evaluation_status(
        str(evaluation_result.status),
        generation_status=str(getattr(generation_bundle.record, "status", "") or ""),
    )  # docstring: 映射最终状态

    return EvaluatorServiceResult(
        evaluation_result=evaluation_result,
        record_id=record_id,
        timing_ms=timing_ms,
        gate=gate,
        summary=summary,
        mapped_message_status=mapped_message_status,
    )  # docstring: 返回结果快照
