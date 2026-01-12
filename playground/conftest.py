# playground/conftest.py

"""
[职责] pytest 公共 fixture：提供可隔离的 AsyncSession + 临时 SQLite 数据库，并完成建表/清库。
[边界] 不引入任何业务 pipeline；只负责数据库层的可测试环境。
[上游关系] pytest runner 调用 fixture 初始化。
[下游关系] playground/test_sql/* 使用该 fixture 做 sql_gate 断言。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))  # docstring: 优先使用本地源码而非 site-packages

from uae_law_rag.backend.db.base import Base
from uae_law_rag.backend.db import models  # noqa: F401  # docstring: 强制导入以注册全部表到 Base.metadata


@pytest.fixture(scope="session")
def _sqlite_db_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Return a temp sqlite file path."""  # docstring: 使用文件库而非 :memory:，避免多连接时丢失schema
    root = tmp_path_factory.mktemp("sql_gate")
    return root / "test.db"


@pytest_asyncio.fixture(scope="session")
async def async_engine(_sqlite_db_path: Path) -> AsyncIterator[AsyncEngine]:
    """
    Create an async SQLite engine with foreign keys enabled.
    """  # docstring: 给所有测试复用的 engine（session 级）
    url = f"sqlite+aiosqlite:///{_sqlite_db_path}"
    engine = create_async_engine(url, echo=False, future=True)

    # Enable SQLite FK constraints
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _conn_record) -> None:  # type: ignore[no-redef]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()

    # Create tables once
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    try:
        yield engine
    finally:
        await engine.dispose()
        # best-effort cleanup
        try:
            os.remove(_sqlite_db_path)
        except OSError:
            pass


@pytest_asyncio.fixture()
async def session(async_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """
    Provide a per-test transaction-like session.
    """  # docstring: 每个 test 使用独立 session，避免状态串扰
    SessionLocal = async_sessionmaker(async_engine, expire_on_commit=False, class_=AsyncSession)
    async with SessionLocal() as s:
        yield s
        await s.rollback()
