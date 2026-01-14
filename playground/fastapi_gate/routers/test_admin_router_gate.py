# playground/fastapi_gate/routers/test_admin_router_gate.py

"""
[职责] Admin router gate：验证 /admin 列表接口输出字段与过滤。
[边界] 使用 SQLite fixture；不触发业务 pipeline。
[上游关系] backend/api/routers/admin.py。
[下游关系] 确保运营/审计接口契约稳定。
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SRC_ROOT = _REPO_ROOT / "src"
if str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))  # docstring: ensure local src import

from uae_law_rag.backend.api.deps import get_session
from uae_law_rag.backend.api.middleware import TraceContextMiddleware
from uae_law_rag.backend.api.routers.admin import router as admin_router
from uae_law_rag.backend.db.models.doc import DocumentModel, KnowledgeBaseModel, KnowledgeFileModel, NodeModel
from uae_law_rag.backend.db.models.user import UserModel
from uae_law_rag.backend.schemas.ids import new_uuid


pytestmark = pytest.mark.fastapi_gate


@pytest.mark.asyncio
async def test_admin_router_gate(session: AsyncSession) -> None:
    """
    [职责] 验证 admin 列表接口输出字段与过滤逻辑。
    [边界] 不依赖外部服务；仅使用本地 SQLite。
    [上游关系] /admin 路由。
    [下游关系] 运营/审计系统依赖该结构。
    """
    user_id = str(new_uuid())
    kb_id = str(new_uuid())
    file_id = str(new_uuid())
    document_id = str(new_uuid())

    user = UserModel(id=user_id, username="admin_gate_user")  # docstring: 创建用户
    session.add(user)  # docstring: 写入用户

    kb = KnowledgeBaseModel(
        id=kb_id,
        user_id=user_id,
        kb_name="kb_admin",
        kb_info="kb for admin test",
        milvus_collection="kb_admin_collection",
        embed_model="test-embed",
        embed_dim=32,
    )  # docstring: 创建 KB
    session.add(kb)  # docstring: 写入 KB

    last_ingested_at = datetime.now(timezone.utc)  # docstring: 文件导入完成时间
    kb_file = KnowledgeFileModel(
        id=file_id,
        kb_id=kb_id,
        file_name="admin.pdf",
        file_ext="pdf",
        source_uri="file:///tmp/admin.pdf",
        sha256="0" * 64,
        file_version=1,
        file_mtime=0.0,
        file_size=123,
        pages=1,
        ingest_profile={"parser": "pymupdf4llm"},
        node_count=1,
        ingest_status="success",
        last_ingested_at=last_ingested_at,
    )  # docstring: 创建文件
    session.add(kb_file)  # docstring: 写入文件

    doc = DocumentModel(
        id=document_id,
        kb_id=kb_id,
        file_id=file_id,
        title="Admin Doc",
        source_name="Admin Source",
        meta_data={"lang": "en"},
    )  # docstring: 创建文档
    session.add(doc)  # docstring: 写入文档

    node = NodeModel(
        document_id=document_id,
        node_index=0,
        text="admin node",
    )  # docstring: 创建节点
    session.add(node)  # docstring: 写入节点

    await session.commit()  # docstring: 提交测试数据

    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session  # docstring: reuse test session

    app = FastAPI()
    app.add_middleware(TraceContextMiddleware)  # docstring: inject trace/request headers
    app.include_router(admin_router)  # docstring: mount admin router
    app.dependency_overrides[get_session] = _override_session  # docstring: override session dep

    trace_id = str(new_uuid())
    request_id = str(new_uuid())
    headers = {
        "x-trace-id": trace_id,
        "x-request-id": request_id,
    }  # docstring: explicit trace/request headers

    transport = ASGITransport(app=app)  # docstring: ASGI transport for httpx
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        kbs_resp = await client.get(f"/admin/kbs?user_id={user_id}", headers=headers)
        files_resp = await client.get(f"/admin/files?kb_id={kb_id}", headers=headers)
        docs_resp = await client.get(f"/admin/documents?kb_id={kb_id}", headers=headers)

    assert kbs_resp.status_code == 200
    kbs = kbs_resp.json()
    assert len(kbs) == 1
    assert kbs[0]["kb_id"] == kb_id
    assert kbs[0]["kb_name"] == "kb_admin"

    assert files_resp.status_code == 200
    files = files_resp.json()
    assert len(files) == 1
    assert files[0]["file_id"] == file_id
    assert files[0]["ingest_status"] == "success"
    assert files[0]["last_ingested_at"] is not None

    assert docs_resp.status_code == 200
    docs = docs_resp.json()
    assert len(docs) == 1
    assert docs[0]["document_id"] == document_id
    assert docs[0]["node_count"] == 1

    assert kbs_resp.headers["x-trace-id"] == trace_id  # docstring: trace_id must propagate
    assert kbs_resp.headers["x-request-id"] == request_id  # docstring: request_id must propagate
