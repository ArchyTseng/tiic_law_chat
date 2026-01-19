"""
[职责] prompt_window_select gate：验证 window 优先的证据文本选择器。
[边界] 仅测试纯函数；不访问 DB/HTTP；不引入 pipeline 依赖。
[上游关系] prompt.py 选择器函数。
[下游关系] Step5-2 prompt render 接入。
"""

from __future__ import annotations

from uae_law_rag.backend.pipelines.generation.prompt import (
    select_generation_context_text,
    select_quote_anchor_text,
)


def test_select_generation_context_text_prefers_window() -> None:
    node = {
        "meta": {
            "window": "  window text \n\n for test  ",
            "original_text": "original text",
        },
        "text_excerpt": "excerpt text",
    }
    out = select_generation_context_text(node, max_chars=200)
    assert out == "window text for test"


def test_select_generation_context_text_fallback_original() -> None:
    node = {
        "meta": {
            "window": "   ",
            "original_text": "original text",
        },
        "text_excerpt": "excerpt text",
    }
    out = select_generation_context_text(node, max_chars=200)
    assert out == "original text"


def test_select_generation_context_text_fallback_excerpt_and_cap() -> None:
    node = {"text_excerpt": "  alpha beta gamma delta  "}
    out = select_generation_context_text(node, max_chars=10)
    assert out.startswith("alpha")
    assert out.endswith("...")
    assert len(out) <= 10


def test_select_quote_anchor_text_prefers_original_over_window() -> None:
    node = {
        "meta": {
            "window": "window text",
            "original_text": "original text",
        },
        "text_excerpt": "excerpt text",
    }
    out = select_quote_anchor_text(node, max_chars=200)
    assert out == "original text"


def test_select_quote_anchor_text_fallback_excerpt() -> None:
    node = {"text_excerpt": "excerpt text"}
    out = select_quote_anchor_text(node, max_chars=200)
    assert out == "excerpt text"
