# playground/milvus_gate/test_kb_schema_gate.py

"""
[职责] kb/schema gate：验证 schema 契约层（无 Milvus 依赖）输出稳定、字段约定一致。
[边界] 不连接 Milvus；只测试纯函数与常量契约。
[上游关系] 无（纯契约层）。
[下游关系] kb/client.py、kb/index.py、kb/repo.py 将严格依赖这些字段/expr/payload 契约。
"""

from __future__ import annotations

import pytest

from uae_law_rag.backend.kb.schema import (
    ARTICLE_ID_FIELD,
    DOCUMENT_ID_FIELD,
    EMBEDDING_FIELD,
    FILE_ID_FIELD,
    KB_ID_FIELD,
    NODE_ID_FIELD,
    PAGE_FIELD,
    SECTION_PATH_FIELD,
    VECTOR_ID_FIELD,
    build_collection_spec,
    build_expr_for_scope,
    build_payload,
    default_fields,
    default_index,
    default_search,
)


pytestmark = pytest.mark.milvus_gate


def test_schema_constants_stable() -> None:
    """Field name conventions must be stable to avoid storage drift."""  # docstring: 契约常量锁死
    assert VECTOR_ID_FIELD == "vector_id"
    assert EMBEDDING_FIELD == "embedding"
    assert NODE_ID_FIELD == "node_id"
    assert KB_ID_FIELD == "kb_id"
    assert FILE_ID_FIELD == "file_id"
    assert DOCUMENT_ID_FIELD == "document_id"
    assert PAGE_FIELD == "page"
    assert ARTICLE_ID_FIELD == "article_id"
    assert SECTION_PATH_FIELD == "section_path"


def test_default_fields_contains_primary_vector_payload() -> None:
    """Default field specs must include PK + vector + required payload."""  # docstring: 防止漏字段导致写入失败
    fields = default_fields(embed_dim=1024)
    names = {f.name for f in fields}
    assert VECTOR_ID_FIELD in names
    assert EMBEDDING_FIELD in names
    assert NODE_ID_FIELD in names
    assert KB_ID_FIELD in names
    assert FILE_ID_FIELD in names
    assert DOCUMENT_ID_FIELD in names
    assert PAGE_FIELD in names
    assert ARTICLE_ID_FIELD in names
    assert SECTION_PATH_FIELD in names

    pk = [f for f in fields if f.is_primary]
    assert len(pk) == 1
    assert pk[0].name == VECTOR_ID_FIELD
    assert pk[0].auto_id is False

    vec = [f for f in fields if f.name == EMBEDDING_FIELD][0]
    assert vec.dim == 1024


def test_default_index_and_search_contract() -> None:
    """Index/search spec should be coherent and have expected keys."""  # docstring: 反推 index.py/repo.py 所需参数
    idx = default_index(metric_type="COSINE", index_type="HNSW")
    assert idx.field_name == EMBEDDING_FIELD
    assert idx.index_type in ("HNSW", "IVF_FLAT", "IVF_SQ8", "AUTOINDEX")
    assert idx.metric_type in ("IP", "L2", "COSINE")
    assert isinstance(idx.params, dict)

    srch = default_search(metric_type="COSINE", limit=50)
    assert srch.metric_type == "COSINE"
    assert srch.limit == 50
    assert EMBEDDING_FIELD not in srch.output_fields  # output_fields 只包含 payload
    for key in [NODE_ID_FIELD, KB_ID_FIELD, FILE_ID_FIELD, DOCUMENT_ID_FIELD]:
        assert key in srch.output_fields


def test_build_collection_spec_smoke() -> None:
    """Collection spec must carry coherent fields + index + search."""  # docstring: 反推 client/index/repo 构造入口
    spec = build_collection_spec(
        name="kb_test_collection",
        embed_dim=768,
        metric_type="COSINE",
        index_type="HNSW",
        default_top_k=25,
    )
    assert spec.name == "kb_test_collection"
    assert spec.vector_field == EMBEDDING_FIELD
    assert spec.index.field_name == EMBEDDING_FIELD
    assert spec.search.limit == 25
    # fields must include embedding dim
    vec = [f for f in spec.fields if f.name == EMBEDDING_FIELD][0]
    assert vec.dim == 768


def test_build_expr_for_scope() -> None:
    """Scope expression must always include kb_id and optionally file/document."""  # docstring: 防止跨 KB 混检
    expr = build_expr_for_scope(kb_id="KB1")
    assert 'kb_id == "KB1"' in expr

    expr2 = build_expr_for_scope(kb_id="KB1", file_id="F1")
    assert 'kb_id == "KB1"' in expr2
    assert 'file_id == "F1"' in expr2

    expr3 = build_expr_for_scope(kb_id="KB1", file_id="F1", document_id="D1")
    assert 'document_id == "D1"' in expr3


def test_build_payload_shape() -> None:
    """Payload dict keys must match schema fields and be JSON-serializable."""  # docstring: 反推 repo.upsert API
    payload = build_payload(
        vector_id="V1",
        embedding=[0.1, 0.2],
        node_id="N1",
        kb_id="KB1",
        file_id="F1",
        document_id="D1",
        page=2,
        article_id="Article 2",
        section_path="Chapter 1",
    )
    assert payload[VECTOR_ID_FIELD] == "V1"
    assert payload[EMBEDDING_FIELD] == [0.1, 0.2]
    assert payload[NODE_ID_FIELD] == "N1"
    assert payload[KB_ID_FIELD] == "KB1"
    assert payload[FILE_ID_FIELD] == "F1"
    assert payload[DOCUMENT_ID_FIELD] == "D1"
    assert payload[PAGE_FIELD] == 2
    assert payload[ARTICLE_ID_FIELD] == "Article 2"
    assert payload[SECTION_PATH_FIELD] == "Chapter 1"
