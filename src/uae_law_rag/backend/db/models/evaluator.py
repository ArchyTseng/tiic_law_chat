# src/uae_law_rag/backend/db/models/evaluator.py

"""
[职责] EvaluationRecordModel：持久化一次在线评估的结果（config/checks/scores/status），用于前端展示与回归审计。
[边界] 不存储 retrieval hits 全量、不存储生成 prompt 全量；仅存评估摘要与规则检查明细（JSON）。
[上游关系] evaluator pipeline 依据 RetrievalRecord + GenerationRecord 生成 EvaluationResult 并落库。
[下游关系] chat/debug UI 查询最近评估结果；后续分析/报表可聚合 status 与 scores。
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, String, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base, TimestampMixin

if TYPE_CHECKING:
    from .conversation import ConversationModel
    from .generation import GenerationRecordModel
    from .message import MessageModel
    from .retrieval import RetrievalRecordModel


class EvaluationRecordModel(Base, TimestampMixin):
    __tablename__ = "evaluation_record"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="Evaluation record ID (UUID str)",  # docstring: 评估记录主键
    )

    # --- ownership / linkage ---
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Conversation ID",  # docstring: 归属会话（便于列表/聚合）
    )
    message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("message.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="Message ID (1 message -> 1 evaluation)",  # docstring: 一致化：单轮消息唯一评估
    )
    retrieval_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("retrieval_record.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="RetrievalRecord ID",  # docstring: 评估对应的检索记录
    )
    generation_record_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("generation_record.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="GenerationRecord ID (optional)",  # docstring: 评估对应的生成记录（可选）
    )

    # --- evaluation result snapshot ---
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pass",
        comment="Evaluation status: pass/fail/partial/skipped",  # docstring: 评估总状态
    )
    rule_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="v0",
        comment="Evaluator rule version",  # docstring: 规则版本（回放/回归关键）
    )

    config: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="EvaluatorConfig snapshot (JSON)",  # docstring: 配置快照（可回放）
    )
    checks: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Evaluation checks list snapshot (JSON)",  # docstring: checks 明细（结构化）
    )
    scores: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Evaluation scores snapshot (JSON)",  # docstring: scores 汇总（结构化）
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        String(1024),
        nullable=True,
        comment="Evaluator error message (if any)",  # docstring: evaluator 异常信息
    )

    meta: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Extra meta (trace_id/request_id/timing summary)",  # docstring: 扩展元信息
    )

    # --- relationships ---
    conversation: Mapped["ConversationModel"] = relationship(
        "ConversationModel",
        back_populates="evaluation_records",
    )  # docstring: 会话 -> 评估记录（一对多）
    message: Mapped["MessageModel"] = relationship(
        "MessageModel",
        back_populates="evaluation_record",
    )  # docstring: 消息 -> 评估记录（一对一）
    retrieval_record: Mapped["RetrievalRecordModel"] = relationship(
        "RetrievalRecordModel",
        back_populates="evaluation_record",
    )  # docstring: 检索记录 -> 评估记录（一对一）
    generation_record: Mapped[Optional["GenerationRecordModel"]] = relationship(
        "GenerationRecordModel",
        back_populates="evaluation_record",
    )  # docstring: 生成记录 -> 评估记录（可选一对一）
