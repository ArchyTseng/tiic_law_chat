# src/uae_law_rag/backend/db/models/conversation.py

from __future__ import annotations

import uuid
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base, TimestampMixin

if TYPE_CHECKING:
    from .user import UserModel
    from .message import MessageModel
    from .doc import KnowledgeBaseModel
    from .evaluator import EvaluationRecordModel


class ConversationModel(Base, TimestampMixin):
    """
    [职责] 会话实体：承载一次持续对话的上下文边界（消息序列、默认KB配置、会话级策略）。
    [边界] 不存储检索/生成明细（这些进入 RetrievalRecord/GenerationRecord）；仅存对话容器信息。
    [上游关系] UserModel 创建会话；Chat 请求携带 conversation_id 进入对话。
    [下游关系] MessageModel（1-N）挂在会话；默认KB与会话级 settings 影响下游检索与生成。
    """

    __tablename__ = "conversation"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="会话ID（UUID字符串）",  # docstring: 会话全局唯一标识
    )

    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="用户ID（外键）",  # docstring: 会话归属用户
    )

    name: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="对话框名称",  # docstring: UI 展示用会话名称
    )

    chat_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="chat",
        comment="聊天类型（chat/agent_chat等）",  # docstring: 便于未来扩展不同对话模式
    )

    default_kb_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("knowledge_base.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="会话默认KB（可空）",  # docstring: 未显式指定 KB 时使用的默认知识库
    )

    settings: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
        comment="会话级策略快照（history_len/rerank等）",  # docstring: 会话默认参数，可回放
    )

    user: Mapped["UserModel"] = relationship(
        "UserModel",
        back_populates="conversations",
    )

    messages: Mapped[List["MessageModel"]] = relationship(
        "MessageModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="MessageModel.created_at",
    )

    default_kb: Mapped[Optional["KnowledgeBaseModel"]] = relationship(
        "KnowledgeBaseModel",
    )

    evaluation_records: Mapped[list["EvaluationRecordModel"]] = relationship(
        "EvaluationRecordModel",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )  # docstring: 会话的评估记录集合

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ConversationModel id={self.id} user_id={self.user_id} chat_type={self.chat_type!r}>"
