# playground/sql_gate/test_sql_gate.py

"""
[职责] sql_gate：验证 DB schema + 关键约束 + repo 最小写入闭环。
[边界] 不调用 Milvus/LLM；只覆盖 SQLAlchemy Models/Repo 的“可用性与一致性”。
[上游关系] 依赖 db.models 与 db.repo 的实现。
[下游关系] 保障后续 ingest/retrieval/generation/fastapi gate tests 的数据库底座稳定。
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from uae_law_rag.backend.db.base import Base
from uae_law_rag.backend.db.repo import (
    ConversationRepo,
    GenerationRepo,
    IngestRepo,
    MessageRepo,
    RetrievalRepo,
    UserRepo,
)


pytestmark = pytest.mark.sql_gate


@pytest.mark.asyncio
async def test_sql_gate_tables_registered() -> None:
    """DDL sanity: ensure core tables are registered."""  # docstring: 防止 models 未被正确 import 导致缺表
    expected = {
        "user",
        "conversation",
        "message",
        "knowledge_base",
        "knowledge_file",
        "document",
        "node",
        "node_vector_map",
        "retrieval_record",
        "retrieval_hit",
        "generation_record",
    }
    assert expected.issubset(set(Base.metadata.tables.keys()))


@pytest.mark.asyncio
async def test_sql_gate_repo_happy_path(session: AsyncSession) -> None:
    """
    Repo happy path: user -> kb -> conversation -> message -> retrieval record/hits -> generation record.
    """  # docstring: 最小闭环写入，验证外键与 Repo API 可用
    user_repo = UserRepo(session)
    conv_repo = ConversationRepo(session)
    msg_repo = MessageRepo(session)
    ingest_repo = IngestRepo(session)
    retrieval_repo = RetrievalRepo(session)
    gen_repo = GenerationRepo(session)

    # 1) user
    u = await user_repo.create(username="u1", password_hash=None, is_active=True)
    assert u.id  # docstring: UUID default 生效
    assert u.username == "u1"

    # 2) kb
    kb = await ingest_repo.create_kb(
        user_id=u.id,
        kb_name="kb1",
        milvus_collection="kb1_collection",
        embed_model="bge-m3",
        embed_dim=1024,
        chunking_config={"chunk_size": 800, "overlap": 100},
    )
    assert kb.id
    assert kb.user_id == u.id

    # 3) conversation
    c = await conv_repo.create(
        user_id=u.id,
        name="conv1",
        chat_type="chat",
        default_kb_id=kb.id,
        settings={"history_len": 6},
    )
    assert c.id
    assert c.user_id == u.id
    assert c.default_kb_id == kb.id

    # 4) message (pending)
    m = await msg_repo.create_user_message(
        conversation_id=c.id,
        chat_type="chat",
        query="What is the regulation scope?",
        request_id="req-001",
        meta_data={"ui": "test"},
    )
    assert m.id
    assert m.status == "pending"
    assert m.response is None

    # 5) file/document/nodes + node_vector_map (ingest minimal)
    f = await ingest_repo.create_file(
        kb_id=kb.id,
        file_name="law.pdf",
        file_ext="pdf",
        sha256="a" * 64,
        source_uri="file://law.pdf",
        file_version=1,
        file_mtime=0.0,
        file_size=123,
        pages=10,
        ingest_profile={"parser": "pymupdf4llm"},
    )
    doc = await ingest_repo.create_document(
        kb_id=kb.id,
        file_id=f.id,
        title="Cabinet Resolution No. (109) of 2023",
        source_name="law.pdf",
        meta_data={"lang": "en"},
    )
    nodes = await ingest_repo.bulk_create_nodes(
        document_id=doc.id,
        nodes=[
            {
                "node_index": 0,
                "text": "Article 1: Definitions ...",
                "page": 1,
                "start_offset": 0,
                "end_offset": 100,
                "article_id": "Article 1",
                "section_path": "Chapter 1",
                "meta_data": {"kind": "article"},
            },
            {
                "node_index": 1,
                "text": "Article 2: Scope ...",
                "page": 2,
                "start_offset": 0,
                "end_offset": 80,
                "article_id": "Article 2",
                "section_path": "Chapter 1",
                "meta_data": {"kind": "article"},
            },
        ],
    )
    assert len(nodes) == 2
    maps = await ingest_repo.bulk_create_node_vector_maps(
        kb_id=kb.id,
        file_id=f.id,
        maps=[
            {"node_id": nodes[0].id, "vector_id": "v1"},
            {"node_id": nodes[1].id, "vector_id": "v2"},
        ],
    )
    assert len(maps) == 2

    # 6) retrieval record + hits (message_id is the single owner)
    rec = await retrieval_repo.create_record(
        message_id=m.id,
        kb_id=kb.id,
        query_text=m.query,
        keyword_top_k=200,
        vector_top_k=50,
        fusion_top_k=50,
        rerank_top_k=10,
        fusion_strategy="union",
        rerank_strategy="none",
        provider_snapshot={"embed": {"provider": "ollama", "model": "bge-m3"}},
        timing_ms={"keyword": 5, "vector": 12, "fusion": 1, "rerank": 0},
    )
    assert rec.id
    hits = await retrieval_repo.bulk_create_hits(
        retrieval_record_id=rec.id,
        hits=[
            {
                "node_id": nodes[1].id,
                "source": "fused",
                "rank": 1,
                "score": 0.9,
                "score_details": {"vector_score": 0.9},
                "excerpt": "Article 2: Scope ...",
                "page": 2,
                "start_offset": 0,
                "end_offset": 80,
            },
            {
                "node_id": nodes[0].id,
                "source": "fused",
                "rank": 2,
                "score": 0.8,
                "score_details": {"keyword_score": 0.8},
                "excerpt": "Article 1: Definitions ...",
                "page": 1,
                "start_offset": 0,
                "end_offset": 100,
            },
        ],
    )
    assert len(hits) == 2

    # 7) generation record (owned by message_id, links to retrieval_record_id)
    gen = await gen_repo.create_record(
        message_id=m.id,
        retrieval_record_id=rec.id,
        prompt_name="uae_law_default",
        prompt_version="v1",
        model_provider="ollama",
        model_name="llama3",
        messages_snapshot={"system": "You are a UAE law assistant", "user": m.query},
        output_raw='{"answer":"...","citations":[...]}',
        output_structured={"answer": "..."},
        citations={"nodes": [nodes[1].id, nodes[0].id]},
    )
    assert gen.id
    assert gen.retrieval_record_id == rec.id

    # 8) message writeback
    ok = await msg_repo.set_response(
        m.id,
        response="Answer ...",
        status="success",
    )
    assert ok is True
    m2 = await msg_repo.get_by_id(m.id)
    assert m2 is not None
    assert m2.status == "success"
    assert m2.response == "Answer ..."


@pytest.mark.asyncio
async def test_sql_gate_one_to_one_constraints(session: AsyncSession) -> None:
    """
    Ensure 1-1 constraints hold:
    - one message can have at most one retrieval_record
    - one message can have at most one generation_record
    """  # docstring: 一致化策略的核心防漂移断言
    user_repo = UserRepo(session)
    conv_repo = ConversationRepo(session)
    msg_repo = MessageRepo(session)
    ingest_repo = IngestRepo(session)
    retrieval_repo = RetrievalRepo(session)
    gen_repo = GenerationRepo(session)

    u = await user_repo.create(username="u2")
    kb = await ingest_repo.create_kb(
        user_id=u.id,
        kb_name="kb2",
        milvus_collection="kb2_collection",
        embed_model="bge-m3",
        embed_dim=1024,
    )
    c = await conv_repo.create(user_id=u.id, chat_type="chat", default_kb_id=kb.id, settings={})
    m = await msg_repo.create_user_message(conversation_id=c.id, chat_type="chat", query="Q?")

    # first retrieval record ok
    rec1 = await retrieval_repo.create_record(
        message_id=m.id,
        kb_id=kb.id,
        query_text="Q?",
        keyword_top_k=10,
        vector_top_k=10,
        fusion_top_k=10,
        rerank_top_k=5,
        fusion_strategy="union",
        rerank_strategy="none",
    )
    assert rec1.id

    # second retrieval record should violate uq_retrieval_record_message
    with pytest.raises(IntegrityError):
        await retrieval_repo.create_record(
            message_id=m.id,
            kb_id=kb.id,
            query_text="Q?",
            keyword_top_k=10,
            vector_top_k=10,
            fusion_top_k=10,
            rerank_top_k=5,
            fusion_strategy="union",
            rerank_strategy="none",
        )
    await session.rollback()

    # After rollback, previous inserts are gone in the current transaction.
    # Re-create minimal prerequisites for generation FK and 1-1 tests.
    u = await user_repo.create(username="u2_re", password_hash=None, is_active=True)
    kb = await ingest_repo.create_kb(
        user_id=u.id,
        kb_name="kb2_re",
        milvus_collection="kb2_collection_re",
        embed_model="bge-m3",
        embed_dim=1024,
    )
    c = await conv_repo.create(user_id=u.id, chat_type="chat", default_kb_id=kb.id, settings={})
    m = await msg_repo.create_user_message(conversation_id=c.id, chat_type="chat", query="Q?")
    rec1 = await retrieval_repo.create_record(
        message_id=m.id,
        kb_id=kb.id,
        query_text="Q?",
        keyword_top_k=10,
        vector_top_k=10,
        fusion_top_k=10,
        rerank_top_k=5,
        fusion_strategy="union",
        rerank_strategy="none",
    )

    # first generation record ok
    gen1 = await gen_repo.create_record(
        message_id=m.id,
        retrieval_record_id=rec1.id,
        prompt_name="p",
        model_provider="ollama",
        model_name="llama3",
        output_raw="A",
    )
    assert gen1.id

    # second generation record should violate uq_generation_record_message
    with pytest.raises(IntegrityError):
        await gen_repo.create_record(
            message_id=m.id,
            retrieval_record_id=rec1.id,
            prompt_name="p",
            model_provider="ollama",
            model_name="llama3",
            output_raw="A2",
        )
    await session.rollback()


@pytest.mark.asyncio
async def test_sql_gate_kb_unique_per_user(session: AsyncSession) -> None:
    """Ensure (user_id, kb_name) unique constraint holds."""  # docstring: 防止同用户重复 KB 名称
    user_repo = UserRepo(session)
    ingest_repo = IngestRepo(session)

    u = await user_repo.create(username="u3")

    _ = await ingest_repo.create_kb(
        user_id=u.id,
        kb_name="same",
        milvus_collection="c1",
        embed_model="bge-m3",
        embed_dim=1024,
    )

    with pytest.raises(IntegrityError):
        await ingest_repo.create_kb(
            user_id=u.id,
            kb_name="same",  # duplicate
            milvus_collection="c2",
            embed_model="bge-m3",
            embed_dim=1024,
        )
