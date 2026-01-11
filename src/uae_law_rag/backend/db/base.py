# src/uae_law_rag/backend/db/base.py
"""
[职责] SQLAlchemy Declarative Base：为所有 ORM Models 提供统一的 metadata 与声明基类。
[边界] 仅包含 Base 定义；不包含 engine/session 创建（由 engine.py 负责）。
[上游关系] 无（基础设施层）。
[下游关系] backend.db.models.* 全部依赖 Base 进行 ORM 声明；alembic/engine 依赖 Base.metadata。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
