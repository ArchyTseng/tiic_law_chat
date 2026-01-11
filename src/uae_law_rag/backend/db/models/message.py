# src/uae_law_rag/backend/db/models/message.py

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .conversation import ConversationModel
    from .retrieval import RetrievalRecordModel
    from .generation import GenerationRecordModel


class MessageModel(Base):
    """
    [职责] 消息实体：一次用户提问与系统回答的持久化单元（含反馈与链路指针）。
    [边界] 不承载检索/生成明细内容；通过 retrieval_record_id / generation_record_id 指向可回放记录。
    [上游关系] Chat API 创建 message（query），随后执行检索与生成，并在回调中写回 response 与指针。
    [下游关系] RetrievalRecordModel / GenerationRecordModel 以 message_id 关联；UI/评估读取消息链与反馈。
    """

    __tablename__ = "message"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="消息ID（UUID字符串）",  # docstring: 消息全局唯一标识
    )

    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="会话ID（外键）",  # docstring: 消息归属的会话
    )

    chat_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="chat",
        comment="聊天类型（与会话保持一致）",  # docstring: 便于多模式并行
    )

    query: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="用户问题原文",  # docstring: 用户输入（不截断）
    )

    response: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="模型回答原文（可为空，生成后回写）",  # docstring: LLM 输出全文/结构化文本
    )

    meta_data: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="扩展元数据（UI/实验字段；避免存核心外键）",  # docstring: 轻量扩展，不承载关键关系
    )

    # --- white-box pointers (结构化指针，避免只靠 meta_data) ---
    request_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        comment="链路请求ID（日志/回放对齐）",  # docstring: 一次 /chat 调用的 trace id
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        comment="消息处理状态（pending/success/failed/partial）",  # docstring: gate tests 断言入口
    )

    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="失败原因（可空）",  # docstring: 便于排查与 UI 展示
    )

    # --- feedback ---
    feedback_score: Mapped[int] = mapped_column(
        Integer,
        default=-1,
        nullable=False,
        comment="用户评分（0-100；-1 表示未评分）",  # docstring: 人工反馈信号
    )

    feedback_reason: Mapped[str] = mapped_column(
        String(255),
        default="",
        nullable=False,
        comment="用户评分理由",  # docstring: 反馈文本
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间",  # docstring: 消息写入时间戳
    )

    conversation: Mapped["ConversationModel"] = relationship(
        "ConversationModel",
        back_populates="messages",
    )

    retrieval_record: Mapped[Optional["RetrievalRecordModel"]] = relationship(
        "RetrievalRecordModel",
        back_populates="message",
        uselist=False,
    )

    generation_record: Mapped[Optional["GenerationRecordModel"]] = relationship(
        "GenerationRecordModel",
        back_populates="message",
        uselist=False,
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<MessageModel id={self.id} conversation_id={self.conversation_id} status={self.status!r}>"
