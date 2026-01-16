# src/uae_law_rag/backend/db/models/generation.py

from __future__ import annotations

import uuid
from typing import Optional, TYPE_CHECKING

from sqlalchemy import ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from uae_law_rag.backend.utils.constants import MESSAGE_ID_KEY

from ..base import Base, TimestampMixin

if TYPE_CHECKING:
    from .message import MessageModel
    from .retrieval import RetrievalRecordModel
    from .evaluator import EvaluationRecordModel


class GenerationRecordModel(Base, TimestampMixin):
    """
    [职责] 生成记录：一次 LLM 生成（prompt + messages + evidence）的可回放审计单元。
    [边界] 不做评估打分；评估进入 evaluator 体系或单独表（后续可扩展）。
    [上游关系] Generation pipeline 在构建 evidence（来自 RetrievalRecord）后调用 LLM 并写入本表。
    [下游关系] MessageModel 通过 generation_record_id 指向本记录；UI/评估读取 prompt/messages/citations 做白箱解释。
    """

    __tablename__ = "generation_record"
    __table_args__ = (UniqueConstraint(MESSAGE_ID_KEY, name="uq_generation_record_message"),)

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="生成记录ID（UUID字符串）",  # docstring: 一次生成的唯一标识
    )

    message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="消息ID（可选外键）",  # docstring: 生成归属的消息（若先建 message）
    )

    retrieval_record_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("retrieval_record.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="检索记录ID（外键）",  # docstring: 生成所依据的证据集合
    )

    prompt_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="prompt 名称",  # docstring: 对齐 prompts 资产选择
    )

    prompt_version: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        comment="prompt 版本（可选）",  # docstring: prompt 迭代可追溯
    )

    model_provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="ollama",
        comment="模型 provider",  # docstring: openai/ollama/...
    )

    model_name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="模型名称",  # docstring: 具体模型名（可回放）
    )

    messages_snapshot: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="最终输入 messages 快照（system/user/context）",  # docstring: 回放生成输入
    )

    output_raw: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="LLM 原始输出文本",  # docstring: 未解析/未清洗的输出
    )

    output_structured: Mapped[Optional[dict]] = mapped_column(
        JSON,
        nullable=True,
        comment="结构化输出（JSON，可选）",  # docstring: postprocess 成功后写入
    )

    citations: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="引用信息（node_id -> spans/quotes/positions）",  # docstring: 白箱证据链核心
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="success",
        comment="生成状态（success/partial/blocked/failed）",  # docstring: 与 schemas/generation.py 对齐
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="失败原因（可选）",  # docstring: 生成失败时记录原因
    )

    retrieval_record: Mapped["RetrievalRecordModel"] = relationship(
        "RetrievalRecordModel",
    )

    message: Mapped[Optional["MessageModel"]] = relationship(
        "MessageModel",
        back_populates="generation_record",
        uselist=False,
    )

    evaluation_record: Mapped[Optional["EvaluationRecordModel"]] = relationship(
        "EvaluationRecordModel",
        back_populates="generation_record",
        uselist=False,
    )  # docstring: 本次生成的评估记录（可选一对一）
