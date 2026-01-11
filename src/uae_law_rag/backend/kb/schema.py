# src/uae_law_rag/backend/kb/schema.py

"""
[职责] Milvus Schema 契约定义：声明向量库 collection 的字段结构、索引参数、以及与 SQL 层 Node/KB 的映射规则。
[边界] 仅定义“结构与参数”（schema/index/search params）；不负责连接 Milvus、不负责创建 collection、不负责 upsert/search。
[上游关系] ingest pipeline 产出 NodeModel/NodeVectorMapModel；KnowledgeBaseModel 提供 embed_dim/embed_model/milvus_collection 等配置。
[下游关系] kb/client.py 与 kb/index.py 使用本模块创建 collection/index；kb/repo.py 使用本模块生成插入 payload 与 search filter。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional

# NOTE:
# 本模块不直接 import pymilvus，以保持“纯契约层”可在无 milvus 依赖环境下被导入。
# kb/client.py 才是 pymilvus 依赖入口。


MetricType = Literal["IP", "L2", "COSINE"]  # docstring: 向量距离度量（Milvus 常用三类）
IndexType = Literal["HNSW", "IVF_FLAT", "IVF_SQ8", "AUTOINDEX"]  # docstring: 最小覆盖的索引类型集合


@dataclass(frozen=True)
class MilvusFieldSpec:
    """Field specification for Milvus collection."""  # docstring: 纯字段契约（不依赖 SDK）

    name: str  # docstring: 字段名
    dtype: str  # docstring: 字段类型（统一用字符串表达以避免 SDK 依赖）
    is_primary: bool = False  # docstring: 是否主键
    auto_id: bool = False  # docstring: 主键是否自动生成（本系统禁用，使用显式 vector_id）
    dim: Optional[int] = None  # docstring: 向量维度（仅对 FLOAT_VECTOR 有意义）
    max_length: Optional[int] = None  # docstring: VARCHAR 最大长度（仅对 VARCHAR 有意义)
    description: str = ""  # docstring: 字段用途说明（非运行时依赖，仅文档与调试）


@dataclass(frozen=True)
class MilvusIndexSpec:
    """Index specification for Milvus vector field."""  # docstring: 向量索引契约（不依赖 SDK）

    field_name: str  # docstring: 索引字段名（通常为向量字段）
    index_type: IndexType  # docstring: 索引类型（HNSW/IVF_FLAT/...）
    metric_type: MetricType  # docstring: 距离度量（IP/L2/COSINE）
    params: Dict[str, Any]  # docstring: 索引参数（如 HNSW: M/efConstruction；IVF: nlist）


@dataclass(frozen=True)
class MilvusSearchSpec:
    """Search specification for vector query."""  # docstring: 向量检索参数契约

    metric_type: MetricType  # docstring: 距离度量（应与 index metric 对齐）
    params: Dict[str, Any]  # docstring: search params（如 HNSW: ef；IVF: nprobe）
    limit: int  # docstring: top_k
    output_fields: List[str]  # docstring: 返回的 payload 字段列表（用于 evidence 与审计）


@dataclass(frozen=True)
class MilvusCollectionSpec:
    """Collection contract: fields + index + search defaults."""  # docstring: collection 的完整契约定义

    name: str  # docstring: collection 名称（通常来自 KnowledgeBaseModel.milvus_collection）
    fields: List[MilvusFieldSpec]  # docstring: 字段列表（主键/向量/payload）
    vector_field: str  # docstring: 向量字段名（约定：embedding）
    index: MilvusIndexSpec  # docstring: 向量索引配置
    search: MilvusSearchSpec  # docstring: 默认 search 配置
    consistency_level: str = "Session"  # docstring: 一致性级别（Milvus SDK 取值字符串化表示）
    description: str = ""  # docstring: collection 用途说明（文档/调试）


# -----------------------------
# System conventions (契约常量)
# -----------------------------

VECTOR_ID_FIELD = "vector_id"  # docstring: Milvus 主键字段（显式，便于与 NodeVectorMapModel.vector_id 对齐）
NODE_ID_FIELD = "node_id"  # docstring: 业务节点ID字段（UUID str），用于回查 SQL NodeModel.id
EMBEDDING_FIELD = "embedding"  # docstring: 向量字段名（FLOAT_VECTOR）

KB_ID_FIELD = "kb_id"  # docstring: payload: KB 作用域（与 KnowledgeBaseModel.id 对齐）
FILE_ID_FIELD = "file_id"  # docstring: payload: 文件作用域（与 KnowledgeFileModel.id 对齐）
DOCUMENT_ID_FIELD = "document_id"  # docstring: payload: 文档作用域（与 DocumentModel.id 对齐）

PAGE_FIELD = "page"  # docstring: payload: 页码（可用于过滤/证据展示）
ARTICLE_ID_FIELD = "article_id"  # docstring: payload: 法条编号（证据展示/过滤）
SECTION_PATH_FIELD = "section_path"  # docstring: payload: 结构路径（证据展示/过滤）

# VARCHAR 长度上限：Milvus 需要显式 max_length
ID_MAXLEN = 64  # docstring: UUID str / short id 的安全上限
PATH_MAXLEN = 512  # docstring: section_path 等路径字段安全上限
ARTICLE_MAXLEN = 128  # docstring: article_id 安全上限


def default_fields(*, embed_dim: int) -> List[MilvusFieldSpec]:
    """
    Build default field specs.

    Primary key:
      - vector_id: VARCHAR primary key (explicit, not auto_id)
    Vector:
      - embedding: FLOAT_VECTOR(embed_dim)
    Payload:
      - node_id/kb_id/file_id/document_id/page/article_id/section_path
    """  # docstring: 统一 collection 字段结构，保证 ingestion/search/record 可回放
    return [
        MilvusFieldSpec(
            name=VECTOR_ID_FIELD,
            dtype="VARCHAR",
            is_primary=True,
            auto_id=False,
            max_length=ID_MAXLEN,
            description="Milvus primary key; aligns with NodeVectorMapModel.vector_id",  # docstring: 映射主键
        ),
        MilvusFieldSpec(
            name=EMBEDDING_FIELD,
            dtype="FLOAT_VECTOR",
            dim=int(embed_dim),
            description="Embedding vector field",  # docstring: 向量字段
        ),
        MilvusFieldSpec(
            name=NODE_ID_FIELD,
            dtype="VARCHAR",
            max_length=ID_MAXLEN,
            description="Business node id (SQL NodeModel.id)",  # docstring: 回查 SQL 证据所需
        ),
        MilvusFieldSpec(
            name=KB_ID_FIELD,
            dtype="VARCHAR",
            max_length=ID_MAXLEN,
            description="KB scope id (SQL KnowledgeBaseModel.id)",  # docstring: KB 作用域过滤
        ),
        MilvusFieldSpec(
            name=FILE_ID_FIELD,
            dtype="VARCHAR",
            max_length=ID_MAXLEN,
            description="File scope id (SQL KnowledgeFileModel.id)",  # docstring: 文件级过滤/删除
        ),
        MilvusFieldSpec(
            name=DOCUMENT_ID_FIELD,
            dtype="VARCHAR",
            max_length=ID_MAXLEN,
            description="Document scope id (SQL DocumentModel.id)",  # docstring: 文档级过滤/删除
        ),
        MilvusFieldSpec(
            name=PAGE_FIELD,
            dtype="INT64",
            description="Page number snapshot",  # docstring: 页码
        ),
        MilvusFieldSpec(
            name=ARTICLE_ID_FIELD,
            dtype="VARCHAR",
            max_length=ARTICLE_MAXLEN,
            description="Article identifier (for legal evidence)",  # docstring: 法条标识
        ),
        MilvusFieldSpec(
            name=SECTION_PATH_FIELD,
            dtype="VARCHAR",
            max_length=PATH_MAXLEN,
            description="Section path / hierarchy (for legal evidence)",  # docstring: 结构路径
        ),
    ]


def default_index(*, metric_type: MetricType = "COSINE", index_type: IndexType = "HNSW") -> MilvusIndexSpec:
    """
    Default vector index spec.

    HNSW default params are conservative for MVP.
    """  # docstring: MVP 默认索引（后续可根据规模与召回/延迟调参）
    if index_type == "HNSW":
        params = {"M": 16, "efConstruction": 200}  # docstring: HNSW 常用默认值
    elif index_type == "IVF_FLAT":
        params = {"nlist": 1024}  # docstring: IVF 典型默认值（规模小也可用）
    elif index_type == "IVF_SQ8":
        params = {"nlist": 1024}  # docstring: SQ8 压缩索引
    else:
        params = {}  # docstring: AUTOINDEX 由 Milvus 自行选择
    return MilvusIndexSpec(
        field_name=EMBEDDING_FIELD,
        index_type=index_type,
        metric_type=metric_type,
        params=params,
    )


def default_search(*, metric_type: MetricType = "COSINE", limit: int = 50) -> MilvusSearchSpec:
    """
    Default search spec.

    For HNSW:
      - ef controls recall/latency tradeoff.
    """  # docstring: MVP 默认向量检索参数（后续可按 KB 配置覆盖）
    params = {"ef": 128, "nprobe": 16}  # docstring: 同时兼容 HNSW(ef) 与 IVF(nprobe) 的常用键
    return MilvusSearchSpec(
        metric_type=metric_type,
        params=params,
        limit=int(limit),
        output_fields=[
            NODE_ID_FIELD,  # docstring: 回查证据
            KB_ID_FIELD,  # docstring: 作用域
            FILE_ID_FIELD,  # docstring: 过滤/删除
            DOCUMENT_ID_FIELD,  # docstring: 过滤/删除
            PAGE_FIELD,  # docstring: 证据展示
            ARTICLE_ID_FIELD,  # docstring: 证据展示
            SECTION_PATH_FIELD,  # docstring: 证据展示
        ],
    )


def build_collection_spec(
    *,
    name: str,
    embed_dim: int,
    metric_type: MetricType = "COSINE",
    index_type: IndexType = "HNSW",
    default_top_k: int = 50,
    description: str = "UAE Law RAG KB collection",
) -> MilvusCollectionSpec:
    """
    Build the minimal collection spec for a KB.

    Caller typically passes:
      - name = KnowledgeBaseModel.milvus_collection
      - embed_dim = KnowledgeBaseModel.embed_dim
    """  # docstring: KB 配置 -> collection 契约 的唯一入口
    fields = default_fields(embed_dim=embed_dim)
    index = default_index(metric_type=metric_type, index_type=index_type)
    search = default_search(metric_type=metric_type, limit=default_top_k)
    return MilvusCollectionSpec(
        name=name,
        fields=fields,
        vector_field=EMBEDDING_FIELD,
        index=index,
        search=search,
        consistency_level="Session",
        description=description,
    )


def build_expr_for_scope(
    *,
    kb_id: str,
    file_id: Optional[str] = None,
    document_id: Optional[str] = None,
) -> str:
    """
    Build Milvus boolean expression for scope filtering.

    Examples:
      kb_id == "..." and file_id == "..."
    """  # docstring: 向量检索过滤表达式（与 payload 字段对齐）
    expr = f'{KB_ID_FIELD} == "{kb_id}"'  # docstring: KB 必选过滤，避免跨 KB 混检
    if file_id:
        expr += f' and {FILE_ID_FIELD} == "{file_id}"'  # docstring: 文件级过滤（可选）
    if document_id:
        expr += f' and {DOCUMENT_ID_FIELD} == "{document_id}"'  # docstring: 文档级过滤（可选）
    return expr


def build_payload(
    *,
    vector_id: str,
    embedding: List[float],
    node_id: str,
    kb_id: str,
    file_id: str,
    document_id: str,
    page: Optional[int] = None,
    article_id: Optional[str] = None,
    section_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a Milvus insert payload dict (one entity).

    Returned dict keys match MilvusCollectionSpec.fields.
    """  # docstring: ingest/persist_milvus 写入实体的唯一结构化入口
    return {
        VECTOR_ID_FIELD: vector_id,  # docstring: Milvus 主键（显式）
        EMBEDDING_FIELD: embedding,  # docstring: 向量
        NODE_ID_FIELD: node_id,  # docstring: 回查 SQL Node
        KB_ID_FIELD: kb_id,  # docstring: KB 作用域
        FILE_ID_FIELD: file_id,  # docstring: 文件作用域
        DOCUMENT_ID_FIELD: document_id,  # docstring: 文档作用域
        PAGE_FIELD: int(page) if page is not None else None,  # docstring: 页码
        ARTICLE_ID_FIELD: article_id or "",  # docstring: 法条编号（空串避免 None 类型差异）
        SECTION_PATH_FIELD: section_path or "",  # docstring: 结构路径（空串避免 None 类型差异）
    }
