# src/uae_law_rag/backend/kb/client.py

"""
[职责] Milvus 客户端薄封装：负责建立连接、健康检查、collection 生命周期管理（create/drop/exists）。
[边界] 不包含索引管理、不包含向量 upsert/search 业务语义；仅对 pymilvus SDK 做最小、安全的封装。
[上游关系] kb/schema.py 提供 MilvusCollectionSpec 契约；环境变量提供 Milvus 连接信息。
[下游关系] kb/index.py 依赖本客户端创建索引/加载 collection；kb/repo.py 依赖本客户端执行数据操作。
"""

from __future__ import annotations

import os
import inspect
from typing import Any

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from .schema import MilvusCollectionSpec, MilvusFieldSpec


class MilvusClient:
    """
    Thin Milvus client wrapper.

    Design principles:
      - Explicit lifecycle (connect once, reuse).
      - Fail fast on misconfiguration.
      - Keep SDK-specific logic isolated here.
    """

    def __init__(self, *, alias: str = "default") -> None:
        self._alias = alias  # docstring: pymilvus 连接别名（支持多连接场景）

    def disconnect(self) -> None:
        """
        Disconnect current alias (best-effort).

        Notes:
          - pymilvus connections are global within the process.
          - This is mainly used by CLI scripts / tests to release alias between runs.
        """  # docstring: 脚本/测试收尾释放连接，避免同进程重复运行别名残留
        try:
            connections.disconnect(alias=self._alias)
        except Exception:
            # docstring: best-effort；disconnect 失败不影响主流程
            pass

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, *, force_reconnect: bool = False) -> "MilvusClient":
        """
        Create client from environment variables.

        Supported:
          - MILVUS_URI (preferred, e.g. http://localhost:19530)
          - or MILVUS_HOST + MILVUS_PORT
        """  # docstring: gate tests / 本地开发的标准入口
        uri = os.getenv("MILVUS_URI")
        host = os.getenv("MILVUS_HOST")
        port = os.getenv("MILVUS_PORT")

        # docstring: 同进程幂等复用：若 alias 已存在连接则直接复用；force_reconnect=True 时强制断开再重连
        try:
            if hasattr(connections, "has_connection") and connections.has_connection(alias="default"):
                if force_reconnect:
                    try:
                        connections.disconnect(alias="default")
                    except Exception:
                        pass
                else:
                    return cls(alias="default")
        except Exception:
            # docstring: has_connection 不可用或异常则继续走 connect 流程
            pass

        if uri:
            connections.connect(alias="default", uri=uri)
        elif host and port:
            connections.connect(alias="default", host=host, port=port)
        else:
            raise RuntimeError("Milvus connection not configured. " "Set MILVUS_URI or MILVUS_HOST + MILVUS_PORT.")

        return cls(alias="default")

    async def healthcheck(self) -> None:
        """
        Health check Milvus service.

        Raises:
          RuntimeError if Milvus is not reachable.
        """  # docstring: milvus_gate 的首要断言
        try:
            # list_collections will fail fast if connection is broken
            _ = await self._maybe_await(utility.list_collections(using=self._alias))
        except Exception as e:  # pragma: no cover - 直接暴露错误
            raise RuntimeError(f"Milvus healthcheck failed: {e}") from e

    # ------------------------------------------------------------------
    # Collection lifecycle
    # ------------------------------------------------------------------

    async def has_collection(self, name: str) -> bool:
        """Check if collection exists."""  # docstring: create/drop 的前置判断
        res = await self._maybe_await(utility.has_collection(name, using=self._alias))
        return bool(res)

    async def drop_collection(self, name: str) -> None:
        """Drop collection if exists."""  # docstring: gate tests / 重建 schema 使用
        if await self.has_collection(name):
            await self._maybe_await(utility.drop_collection(name, using=self._alias))

    async def create_collection(
        self,
        spec: MilvusCollectionSpec,
        *,
        drop_if_exists: bool = False,
    ) -> Collection:
        """
        Create collection according to schema spec.

        Args:
          spec: MilvusCollectionSpec
          drop_if_exists: whether to drop existing collection first
        """  # docstring: 严格按照 schema 契约创建 collection
        if drop_if_exists and await self.has_collection(spec.name):
            await self.drop_collection(spec.name)

        if await self.has_collection(spec.name):
            return Collection(name=spec.name, using=self._alias)

        fields = [self._to_field_schema(f) for f in spec.fields]

        schema = CollectionSchema(
            fields=fields,
            description=spec.description,
        )

        collection = Collection(
            name=spec.name,
            schema=schema,
            using=self._alias,
            consistency_level=spec.consistency_level,
        )
        return collection

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def get_collection(self, name: str) -> Collection:
        """
        Get an existing collection.

        Raises:
          RuntimeError if collection does not exist.
        """  # docstring: index/repo 层安全获取 collection
        if not await self.has_collection(name):
            raise RuntimeError(f"Milvus collection not found: {name}")
        return Collection(name=name, using=self._alias)

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        """
        Normalize pymilvus calls across versions: some return plain values, others return awaitables.
        """  # docstring: 解决 pymilvus sync/async API 与 type stubs 不一致问题
        if inspect.isawaitable(value):
            return await value
        return value

    @staticmethod
    def _to_field_schema(field: MilvusFieldSpec) -> FieldSchema:
        """
        Convert MilvusFieldSpec to pymilvus FieldSchema.
        """  # docstring: schema 契约 -> SDK 对象的唯一转换点
        dtype_map = {
            "VARCHAR": DataType.VARCHAR,
            "INT64": DataType.INT64,
            "FLOAT_VECTOR": DataType.FLOAT_VECTOR,
        }

        if field.dtype not in dtype_map:
            raise ValueError(f"Unsupported Milvus field dtype: {field.dtype}")

        kwargs = {}
        if field.max_length is not None:
            kwargs["max_length"] = field.max_length
        if field.dim is not None:
            kwargs["dim"] = field.dim

        return FieldSchema(
            name=field.name,
            dtype=dtype_map[field.dtype],
            is_primary=field.is_primary,
            auto_id=field.auto_id,
            description=field.description,
            **kwargs,
        )
