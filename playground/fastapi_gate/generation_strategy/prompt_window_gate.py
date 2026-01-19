"""
[职责] prompt_window_gate：验证 prompt render 使用 window 优先的证据文本选择。
[边界] 仅测试 prompt.build_messages；不访问 DB/HTTP。
[上游关系] generation/prompt.py。
[下游关系] Step5-2 gate 验收。
"""

from __future__ import annotations

from uae_law_rag.backend.pipelines.generation import prompt as prompt_mod
from uae_law_rag.backend.schemas.ids import NodeId, new_uuid
from uae_law_rag.backend.schemas.retrieval import RetrievalHit


def _make_hit(node_id: NodeId, *, excerpt: str) -> RetrievalHit:
    return RetrievalHit(
        retrieval_record_id=new_uuid(),
        node_id=node_id,
        source="reranked",
        rank=1,
        score=0.9,
        excerpt=excerpt,
        page=1,
        start_offset=10,
        end_offset=20,
    )


def test_prompt_window_prefers_window() -> None:
    node_id = NodeId(str(new_uuid()))
    hits = [_make_hit(node_id, excerpt="hit excerpt")]
    node_snapshots = {
        str(node_id): {
            "meta": {
                "window": "  window text \n for prompt  ",
                "original_text": "original text",
            },
            "text_excerpt": "snapshot excerpt",
        }
    }
    messages = prompt_mod.build_messages(
        query="Q",
        hits=hits,
        prompt_name="uae_law_grounded",
        node_snapshots=node_snapshots,
        max_excerpt_chars=200,
    )
    evidence = messages.get("evidence") or []
    assert evidence and evidence[0]["excerpt"] == "window text for prompt"


def test_prompt_window_fallback_original() -> None:
    node_id = NodeId(str(new_uuid()))
    hits = [_make_hit(node_id, excerpt="hit excerpt")]
    node_snapshots = {
        str(node_id): {
            "meta": {
                "window": "   ",
                "original_text": "original text",
            },
        }
    }
    messages = prompt_mod.build_messages(
        query="Q",
        hits=hits,
        prompt_name="uae_law_grounded",
        node_snapshots=node_snapshots,
        max_excerpt_chars=200,
    )
    evidence = messages.get("evidence") or []
    assert evidence and evidence[0]["excerpt"] == "original text"


def test_prompt_window_fallback_hit_excerpt() -> None:
    node_id = NodeId(str(new_uuid()))
    hits = [_make_hit(node_id, excerpt="hit excerpt")]
    messages = prompt_mod.build_messages(
        query="Q",
        hits=hits,
        prompt_name="uae_law_grounded",
        node_snapshots={},
        max_excerpt_chars=200,
    )
    evidence = messages.get("evidence") or []
    assert evidence and evidence[0]["excerpt"] == "hit excerpt"
