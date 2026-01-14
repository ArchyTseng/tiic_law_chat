# src/uae_law_rag/backend/services/_shared.py

"""
[职责] services/_shared：提供服务层可复用的纯函数（配置解析/归一化/模式判断）。
[边界] 不访问 DB/网络；不执行 pipeline；仅处理数据与规则映射。
[上游关系] chat_service/retrieval_service 等调用。
[下游关系] 服务编排层依赖该模块的解析结果。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Sequence, Tuple

from uae_law_rag.config import settings

__all__ = [
    "_normalize_context",
    "_resolve_value",
    "_resolve_mapping_value",
    "_resolve_int_value",
    "_resolve_provider_mode",
]


def _normalize_context(context: Any | None) -> Dict[str, Any]:
    """
    [职责] 归一化 context 为 dict（兼容 pydantic/model_dump）。
    [边界] 不做字段校验；仅处理数据形态。
    [上游关系] chat_service 调用。
    [下游关系] embed/retrieval 配置解析。
    """
    if context is None:
        return {}  # docstring: 空值回退空 dict
    if isinstance(context, Mapping):
        return dict(context)  # docstring: Mapping 直接转换
    if hasattr(context, "model_dump"):
        return dict(context.model_dump())  # docstring: 兼容 pydantic v2
    if hasattr(context, "dict"):
        return dict(context.dict())  # docstring: 兼容 pydantic v1
    try:
        return dict(vars(context))  # docstring: 兜底对象属性
    except Exception:
        return {}  # docstring: 不可转换回退空 dict


def _resolve_value(
    *,
    key: str,
    context: Mapping[str, Any],
    kb: Mapping[str, Any],
    settings: Mapping[str, Any],
    default: Any,
) -> Tuple[Any, str]:
    """
    [职责] 按优先级解析配置值（context > kb > settings > default）。
    [边界] 不校验类型；调用方负责类型转换。
    [上游关系] 服务层配置解析调用。
    [下游关系] 返回值与来源标签。
    """
    if key in context and context.get(key) is not None:
        return context.get(key), "context"  # docstring: request/context 覆盖
    if key in kb and kb.get(key) is not None:
        return kb.get(key), "kb"  # docstring: KB 默认
    if key in settings and settings.get(key) is not None:
        return settings.get(key), "conversation"  # docstring: conversation settings 覆盖
    return default, "default"  # docstring: 最终兜底（不得散落硬编码）


def _resolve_mapping_value(
    *,
    keys: Sequence[str],
    context: Mapping[str, Any],
    kb: Mapping[str, Any],
    settings: Mapping[str, Any],
) -> Tuple[Dict[str, Any], str]:
    """
    [职责] 解析 Mapping 配置值（context > kb > settings）。
    [边界] 非 Mapping 回退空 dict；不做字段校验。
    [上游关系] service 配置构造调用。
    [下游关系] pipeline 入参映射。
    """
    for key in keys:
        value = context.get(key) if key in context else None
        if isinstance(value, Mapping):
            return dict(value), "context"  # docstring: context 覆盖
    for key in keys:
        value = kb.get(key) if key in kb else None
        if isinstance(value, Mapping):
            return dict(value), "kb"  # docstring: KB 覆盖
    for key in keys:
        value = settings.get(key) if key in settings else None
        if isinstance(value, Mapping):
            return dict(value), "conversation"  # docstring: conversation settings 覆盖
    return {}, "default"  # docstring: 缺省回退空 dict


def _resolve_int_value(
    *,
    key: str,
    context: Mapping[str, Any],
    kb: Mapping[str, Any],
    settings: Mapping[str, Any],
    default: int,
) -> int:
    """
    [职责] 解析整型配置值（保留 0）。
    [边界] 仅做 int 转换；不做范围校验。
    [上游关系] service 配置解析调用。
    [下游关系] retrieval 配置与 gate 判定。
    """
    value, _source = _resolve_value(
        key=key,
        context=context,
        kb=kb,
        settings=settings,
        default=default,
    )
    if value is None:
        return int(default)  # docstring: None 回退默认值
    return int(value)  # docstring: 转为 int


def _resolve_provider_mode(provider: str) -> str:
    """
    [职责] 根据 provider 推断运行模式（local/remote）。
    [边界] 仅基于 settings.LOCAL_MODELS 与 provider 名称判断。
    [上游关系] service 构造 provider_snapshot。
    [下游关系] debug/provider_snapshot 审计输出。
    """
    if settings.LOCAL_MODELS:
        local_providers = {"ollama", "mock", "local", "hash"}  # docstring: 本地 provider 集合
        if str(provider or "").strip().lower() in local_providers:
            return "local"  # docstring: local 模式
    return "remote"  # docstring: 兜底 remote
