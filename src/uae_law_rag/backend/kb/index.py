# src/uae_law_rag/backend/kb/index.py

"""
[职责] Milvus 索引与加载生命周期管理：为 collection 的向量字段创建索引，并负责 load/release 以保证可检索。
[边界] 不负责连接初始化（由 kb/client.py 负责）；不负责 upsert/search/delete（由 kb/repo.py 负责）。
[上游关系] kb/schema.py 提供 MilvusCollectionSpec（包含 index/search 契约）；kb/client.py 提供 MilvusClient。
[下游关系] milvus_gate 集成测试依赖 ensure_index/load/release；retrieval/vector.py 在检索前可确保 collection 已 load。
"""

from __future__ import annotations

import inspect
from typing import Any


from .client import MilvusClient
from .schema import MilvusCollectionSpec


class MilvusIndexManager:
    """
    Index lifecycle controller for Milvus collections.
    """

    def __init__(self, client: MilvusClient) -> None:
        self._client = client  # docstring: MilvusClient（封装连接与 collection 生命周期）

    async def ensure_index(self, spec: MilvusCollectionSpec) -> None:
        """
        Ensure vector index exists for spec.index.field_name.

        This is idempotent: if an index already exists, it will be kept.
        """  # docstring: MVP 只保证索引存在，不做复杂重建策略
        col = await self._client.get_collection(spec.name)  # docstring: 获取 collection 句柄
        # pymilvus: Collection.indexes returns list (sync)
        indexes = getattr(col, "indexes", []) or []  # docstring: 现有索引列表
        if indexes:
            return

        # create_index may be sync or async depending on pymilvus version
        call = col.create_index(
            field_name=spec.index.field_name,  # docstring: 向量字段名（embedding）
            index_params={
                "index_type": spec.index.index_type,  # docstring: 索引类型
                "metric_type": spec.index.metric_type,  # docstring: 距离度量
                "params": spec.index.params,  # docstring: 索引参数
            },
        )
        await self._maybe_await(call)

    async def load_collection(self, name: str) -> None:
        """
        Load collection into memory to make it searchable.
        """  # docstring: search 前必须 load；否则可能出现空结果或报错
        col = await self._client.get_collection(name)  # docstring: 获取 collection
        await self._maybe_await(col.load())

    async def release_collection(self, name: str) -> None:
        """
        Release collection from memory.
        """  # docstring: 测试/资源管理需要
        col = await self._client.get_collection(name)  # docstring: 获取 collection
        await self._maybe_await(col.release())

    @staticmethod
    async def _maybe_await(value: Any) -> Any:
        """
        Normalize pymilvus calls across versions: some return plain values, others return awaitables.
        """  # docstring: 兼容不同 pymilvus sync/async 形态
        if inspect.isawaitable(value):
            return await value
        return value
