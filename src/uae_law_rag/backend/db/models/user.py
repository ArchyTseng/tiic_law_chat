# src/uae_law_rag/backend/db/models/user.py

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base

if TYPE_CHECKING:
    from .conversation import ConversationModel
    from .doc import KnowledgeBaseModel


class UserModel(Base):
    """
    [职责] 用户实体：系统身份与归属边界（会话、知识库归属到用户）。
    [边界] 不承担鉴权流程与密码校验逻辑；仅持久化最小用户信息。
    [上游关系] API/Admin 可创建用户；Chat/ingest 请求会引用 user_id。
    [下游关系] ConversationModel / KnowledgeBaseModel 通过 user_id 外键归属；删除策略由上层控制。
    """

    __tablename__ = "user"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="用户ID（UUID字符串）",  # docstring: 用户全局唯一标识
    )

    username: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
        comment="用户名（唯一）",  # docstring: 登录/识别用用户名
    )

    password_hash: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        comment="密码哈希（MVP可为空）",  # docstring: 仅存储哈希，不存明文；MVP可暂不启用鉴权
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="用户是否启用",  # docstring: 便于禁用账户而不删除数据
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        nullable=False,
        comment="创建时间",  # docstring: 用户创建时间戳
    )

    conversations: Mapped[List["ConversationModel"]] = relationship(
        "ConversationModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    knowledge_bases: Mapped[List["KnowledgeBaseModel"]] = relationship(
        "KnowledgeBaseModel",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<UserModel id={self.id} username={self.username!r} active={self.is_active}>"
