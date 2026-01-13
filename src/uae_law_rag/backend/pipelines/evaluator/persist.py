# src/uae_law_rag/backend/pipelines/evaluator/persist.py

"""
[职责] evaluator persist：将评估结果快照写入 DB，形成可回放 EvaluationRecord。
[边界] 不执行规则裁决；不提交事务；仅做入参规范化与落库映射。
[上游关系] evaluator pipeline 产出 EvaluationResult 或 record_params。
[下游关系] EvaluatorRepo 写入 EvaluationRecordModel；服务层/审计读取回放。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Sequence, get_args

from uae_law_rag.backend.db.repo.evaluator_repo import EvaluatorRepo
from uae_law_rag.backend.schemas.evaluator import EvaluationStatus


_ALLOWED_STATUS = set(get_args(EvaluationStatus))  # docstring: 允许的 EvaluationStatus

__all__ = ["persist_evaluation"]


def _coerce_str(value: Any) -> str:
    """
    [职责] 将 value 转为字符串（去空白）。
    [边界] 空值返回空字符串。
    [上游关系] _normalize_record_params 调用。
    [下游关系] ID/status/rule_version 字段规范化。
    """
    return str(value or "").strip()  # docstring: 字符串兜底


def _coerce_optional_str(value: Any) -> Optional[str]:
    """
    [职责] 将 value 转为可选字符串（空值返回 None）。
    [边界] 仅做空值处理，不做格式校验。
    [上游关系] _normalize_record_params 调用。
    [下游关系] generation_record_id/error_message。
    """
    text = _coerce_str(value)  # docstring: 规范化字符串
    return text or None  # docstring: 空值转 None


def _json_safe(value: Any) -> Any:
    """
    [职责] 将 value 转为可 JSON 序列化结构（dict/list/str/num/bool/None）。
    [边界] 不做业务解释；仅做类型降级与兜底。
    [上游关系] _normalize_record_params 调用。
    [下游关系] config/checks/scores/meta 落库稳定性。
    """
    if value is None:
        return None  # docstring: None 直接返回
    if isinstance(value, (str, int, float, bool)):
        return value  # docstring: 基础类型直接返回
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in dict(value).items()}  # docstring: mapping 递归转 dict
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_json_safe(v) for v in list(value)]  # docstring: 序列递归转 list
    if hasattr(value, "model_dump"):
        try:
            return _json_safe(value.model_dump())  # type: ignore[attr-defined]  # docstring: 兼容 pydantic v2
        except Exception:
            return None  # docstring: model_dump 失败兜底
    if hasattr(value, "dict"):
        try:
            return _json_safe(value.dict())  # type: ignore[call-arg]  # docstring: 兼容 pydantic v1
        except Exception:
            return None  # docstring: dict 失败兜底
    return str(value)  # docstring: 最终兜底为字符串（避免静默丢失）


def _normalize_checks(checks: Any) -> Dict[str, Any]:
    """
    [职责] 规范化 checks 为 JSON dict（推荐结构为 {"items": [...]}）。
    [边界] 不校验 check 内容；仅做结构转换。
    [上游关系] _normalize_record_params 调用。
    [下游关系] EvaluationRecordModel.checks 落库。
    """
    if checks is None:
        return {"items": []}  # docstring: 缺失 checks 回退空列表
    if isinstance(checks, Mapping):
        safe = _json_safe(checks)  # docstring: mapping 转 JSON-safe
        if isinstance(safe, Mapping):
            safe_dict = dict(safe)
            # docstring: 若不是标准 {"items":[...]}，则包装为 items 列表以保持结构稳定
            if "items" not in safe_dict:
                return {"items": [safe_dict]}
            return safe_dict
        return {"items": []}  # docstring: 非 mapping 回退
    if isinstance(checks, Sequence) and not isinstance(checks, (str, bytes, bytearray)):
        items = [_json_safe(item) for item in list(checks)]  # docstring: 序列转为 items
        return {"items": items}  # docstring: 标准化为 items
    safe = _json_safe(checks)  # docstring: 兜底 JSON-safe
    if isinstance(safe, Mapping):
        return dict(safe)  # docstring: 兜底 mapping
    return {"items": []}  # docstring: 无法解析则回退


def _normalize_record_params(record_params: Mapping[str, Any]) -> Dict[str, Any]:
    """
    [职责] 规范化 EvaluationRecord 入参（必填字段校验 + 类型转换）。
    [边界] 仅做最小校验；业务策略由 pipeline 保证。
    [上游关系] persist_evaluation 调用。
    [下游关系] EvaluatorRepo.create 写入。
    """
    required = [
        "conversation_id",
        "message_id",
        "retrieval_record_id",
        "status",
        "config",
        "checks",
        "scores",
    ]
    missing = [k for k in required if k not in record_params]
    if missing:
        raise ValueError(f"record_params missing: {', '.join(missing)}")  # docstring: 必填字段缺失

    def _require_nonempty(key: str) -> str:
        v = _coerce_str(record_params.get(key))
        if not v:
            raise ValueError(f"record_params empty: {key}")  # docstring: 必填字段不可为空
        return v

    config_raw = record_params.get("config")  # docstring: 原始 config
    config_safe = _json_safe(config_raw)  # docstring: config JSON-safe
    if not isinstance(config_safe, Mapping):
        config_safe = {}  # docstring: 非 mapping 回退空 dict

    rule_version = _coerce_str(
        record_params.get("rule_version") or config_safe.get("rule_version")
    )  # docstring: 规则版本
    if not rule_version:
        raise ValueError("record_params empty: rule_version")  # docstring: rule_version 必填

    status = _require_nonempty("status").lower()  # docstring: status 归一化
    if status not in _ALLOWED_STATUS:
        raise ValueError(f"record_params invalid: status={status}")  # docstring: status 强约束

    scores_raw = record_params.get("scores")  # docstring: 原始 scores
    scores_safe = _json_safe(scores_raw)  # docstring: scores JSON-safe
    if not isinstance(scores_safe, Mapping):
        scores_safe = {}  # docstring: scores 非 dict 回退

    meta_raw = record_params.get("meta") or {}  # docstring: 原始 meta
    meta_safe = _json_safe(meta_raw)  # docstring: meta JSON-safe
    if not isinstance(meta_safe, Mapping):
        meta_safe = {}  # docstring: meta 非 dict 回退

    return {
        "conversation_id": _require_nonempty("conversation_id"),  # docstring: 归属会话
        "message_id": _require_nonempty("message_id"),  # docstring: 归属消息
        "retrieval_record_id": _require_nonempty("retrieval_record_id"),  # docstring: 检索记录 ID
        "generation_record_id": _coerce_optional_str(
            record_params.get("generation_record_id")
        ),  # docstring: 生成记录 ID
        "status": status,  # docstring: 评估状态（已归一化与校验）
        "rule_version": rule_version,  # docstring: 规则版本
        "config": dict(config_safe),  # docstring: 配置快照
        "checks": _normalize_checks(record_params.get("checks")),  # docstring: 检查明细快照
        "scores": dict(scores_safe),  # docstring: 分数快照
        "error_message": _coerce_optional_str(record_params.get("error_message")),  # docstring: 错误信息
        "meta": dict(meta_safe),  # docstring: 扩展元信息
    }


async def persist_evaluation(
    *,
    evaluator_repo: EvaluatorRepo,
    record_params: Mapping[str, Any],
) -> str:
    """
    [职责] persist_evaluation：写入 EvaluationRecord 并返回 record_id。
    [边界] 不提交事务；不做规则裁决；仅按输入快照写入。
    [上游关系] evaluator pipeline 产出 record_params。
    [下游关系] EvaluatorRepo.create 落库，供审计与回放使用。
    """
    params = _normalize_record_params(record_params)  # docstring: 规范化 record 入参
    record = await evaluator_repo.create(**params)  # docstring: 写入评估记录
    return str(record.id)  # docstring: 返回 EvaluationRecord ID
