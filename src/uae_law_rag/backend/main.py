# src/uae_law_rag/backend/main.py
"""
[职责] FastAPI 应用入口：创建 app、挂载 routers、提供最小健康检查。
[边界] 不包含业务编排细节；不直接实现 pipelines；仅做路由聚合与基础中间件装配。
[上游关系] uvicorn / ASGI server 作为启动器。
[下游关系] backend/api/routers/* 提供具体端点；frontend 通过 /api/* 调用。
"""

from __future__ import annotations

from fastapi import FastAPI

from uae_law_rag.backend.api.routers.admin import router as admin_router
from uae_law_rag.backend.api.routers.chat import router as chat_router
from uae_law_rag.backend.api.routers.health import router as health_router
from uae_law_rag.backend.api.routers.ingest import router as ingest_router
from uae_law_rag.backend.api.routers.records import router as records_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="uae_law_rag",
        version="0.1.0",
    )

    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(chat_router, prefix="/api", tags=["chat"])
    app.include_router(ingest_router, prefix="/api", tags=["ingest"])
    app.include_router(records_router, prefix="/api", tags=["records"])
    app.include_router(admin_router, prefix="/api", tags=["admin"])

    return app


app = create_app()
