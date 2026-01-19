#!/usr/bin/env python3
# playground/fastapi_gate/retrieval_strategy/offset_replay_gate.py

"""
[职责] offset_replay_gate：验证“页内 offset”闭环可回放：
  chat -> citations -> node -> page replay -> (content[start:end]) 与 quote/excerpt 一致性校验

[边界]
- 不做 OCR/bbox。
- 依赖 /api/chat、/api/records/node/{node_id}、/api/records/page 可用。
- 以“页内 offset”作为强约束：start_offset/end_offset 必须在 page content 内有效。

[判定]
PASS 当且仅当：
- 找到至少 1 条可用 evidence（node_id + page + start_offset + end_offset）
- page replay content 存在
- 0 <= start < end <= len(content)
- content[start:end] 与 quote（优先）或 node.text_excerpt（兜底）存在显著文本重合（宽松匹配）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, Optional, Sequence, Tuple, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:18000"
DEFAULT_USER_ID = "dev-user"
DEFAULT_KB_ID = "default"
DEFAULT_QUERY = "Financing"
DEFAULT_TIMEOUT_S = 60


_WS_RE = re.compile(r"\s+")


def _norm_text(s: str) -> str:
    """Normalize text for fuzzy substring checks."""
    s2 = str(s or "").strip().lower()
    s2 = _WS_RE.sub(" ", s2)
    return s2


def _coerce_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _http_json(
    url: str,
    *,
    method: str,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]],
    timeout_s: int,
) -> Any:
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers = dict(headers)
        headers["Content-Type"] = "application/json"
    req = Request(url=url, method=method, headers=headers, data=body)
    with urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw)


def _pick_evidence_from_chat(
    chat: Dict[str, Any]
) -> Tuple[Optional[str], Optional[str], Optional[int], Optional[int], Optional[int], Optional[str]]:
    """
    Return: (node_id, document_id, page, start_offset, end_offset, quote_or_excerpt)
    """
    citations = chat.get("citations") or []
    if isinstance(citations, list):
        for c in citations:
            if not isinstance(c, dict):
                continue
            node_id = str(c.get("node_id") or "").strip() or None
            quote = str(c.get("quote") or "").strip() or None

            # prefer top-level fields; fallback locator
            page = _coerce_int(c.get("page"))
            loc = c.get("locator") if isinstance(c.get("locator"), dict) else {}
            loc = cast(dict, loc)
            if page is None:
                page = _coerce_int(loc.get("page"))

            start_offset = _coerce_int(loc.get("start_offset"))
            end_offset = _coerce_int(loc.get("end_offset"))

            # chat may not include document_id; we'll fetch from node endpoint
            if node_id and page and start_offset is not None and end_offset is not None and end_offset > start_offset:
                return node_id, None, page, start_offset, end_offset, quote

    # If citations missing offsets, return None to trigger fallback path
    return None, None, None, None, None, None


def _pick_hit_from_retrieval_record(
    rec: Dict[str, Any]
) -> Tuple[Optional[str], Optional[int], Optional[int], Optional[int], Optional[str]]:
    """
    Return: (node_id, page, start_offset, end_offset, excerpt)
    """
    hits = rec.get("hits") or []
    if not isinstance(hits, list):
        return None, None, None, None, None

    for h in hits:
        if not isinstance(h, dict):
            continue
        node_id = str(h.get("node_id") or "").strip() or None
        excerpt = str(h.get("excerpt") or "").strip() or None
        loc = h.get("locator") if isinstance(h.get("locator"), dict) else {}
        loc = cast(dict, loc)

        page = _coerce_int(loc.get("page"))
        start_offset = _coerce_int(loc.get("start_offset"))
        end_offset = _coerce_int(loc.get("end_offset"))

        if node_id and page and start_offset is not None and end_offset is not None and end_offset > start_offset:
            return node_id, page, start_offset, end_offset, excerpt

    return None, None, None, None, None


def _fuzzy_match(slice_text: str, ref_text: str) -> bool:
    """
    宽松匹配：
        - 先做 normalize whitespace + lower
        - 判定 ref 是否是 slice 的子串（或 slice 是 ref 的子串）
        - 再做 token overlap（至少 3 个 token 命中）兜底
    """
    a = _norm_text(slice_text)
    b = _norm_text(ref_text)
    if not a or not b:
        return False
    if b in a or a in b:
        return True

    # token overlap fallback
    toks_a = set(t for t in a.split(" ") if len(t) >= 4)
    toks_b = set(t for t in b.split(" ") if len(t) >= 4)
    inter = toks_a.intersection(toks_b)
    return len(inter) >= 3


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="FastAPI gate: offset replay (page-local offsets).")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--user-id", default=DEFAULT_USER_ID)
    p.add_argument("--kb-id", default=DEFAULT_KB_ID)
    p.add_argument("--query", default=DEFAULT_QUERY)
    p.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    base = str(args.base_url).rstrip("/")
    headers = {"x-user-id": str(args.user_id)}

    try:
        # 1) chat (need citations and debug.records.retrieval_record_id fallback)
        url_chat = f"{base}/api/chat"
        chat = _http_json(
            url_chat,
            method="POST",
            headers=headers,
            payload={"query": str(args.query), "kb_id": str(args.kb_id), "debug": True},
            timeout_s=int(args.timeout_s),
        )

        # 2) try evidence from chat.citations first
        node_id, _doc_id, page, start_off, end_off, ref_text = _pick_evidence_from_chat(chat)

        # 3) fallback: retrieval_record -> pick first hit with offsets
        retrieval_record_id = None
        debug = chat.get("debug") if isinstance(chat.get("debug"), dict) else {}
        recs = debug.get("records") if isinstance(debug.get("records"), dict) else {}
        recs = cast(dict, recs)
        retrieval_record_id = str(recs.get("retrieval_record_id") or "").strip() or None

        if node_id is None or page is None or start_off is None or end_off is None:
            if not retrieval_record_id:
                print("[offset_replay_gate] ERROR: missing retrieval_record_id for fallback", file=sys.stderr)
                return 2

            url_rec = f"{base}/api/records/retrieval/{retrieval_record_id}"
            rec = _http_json(
                url_rec,
                method="GET",
                headers=headers,
                payload=None,
                timeout_s=int(args.timeout_s),
            )
            node_id2, page2, s2, e2, excerpt2 = _pick_hit_from_retrieval_record(rec)
            node_id, page, start_off, end_off = node_id2, page2, s2, e2
            if not ref_text:
                ref_text = excerpt2

        if not node_id or page is None or start_off is None or end_off is None:
            print("[offset_replay_gate] ERROR: no evidence with offsets found", file=sys.stderr)
            return 2

        # 4) node preview (document_id + excerpt fallback)
        url_node = f"{base}/api/records/node/{node_id}"
        node = _http_json(
            url_node,
            method="GET",
            headers=headers,
            payload=None,
            timeout_s=int(args.timeout_s),
        )
        document_id = str((node or {}).get("document_id") or "").strip() or None
        node_excerpt = str((node or {}).get("text_excerpt") or "").strip() or None
        if not ref_text:
            ref_text = node_excerpt

        if not document_id:
            print("[offset_replay_gate] ERROR: node missing document_id", file=sys.stderr)
            return 2

        # 5) page replay
        url_page = (
            f"{base}/api/records/page"
            f"?document_id={document_id}&page={int(page)}&kb_id={str(args.kb_id)}&max_chars=200000"
        )
        page_resp = _http_json(
            url_page,
            method="GET",
            headers=headers,
            payload=None,
            timeout_s=int(args.timeout_s),
        )
        content = str((page_resp or {}).get("content") or "")
        clen = len(content)

        ok_bounds = 0 <= int(start_off) < int(end_off) <= clen
        slice_text = content[int(start_off) : int(end_off)] if ok_bounds else ""
        ok_match = _fuzzy_match(slice_text, str(ref_text or "")) if ok_bounds else False
        ok = bool(content.strip()) and ok_bounds and ok_match

        print(f"[offset_replay_gate] node_id={node_id}")
        print(f"[offset_replay_gate] document_id={document_id} page={int(page)}")
        print(
            f"[offset_replay_gate] offsets start={int(start_off)} end={int(end_off)} content_len={clen} bounds_ok={ok_bounds}"
        )
        print(
            f"[offset_replay_gate] ref_len={len(str(ref_text or ''))} slice_len={len(slice_text)} match_ok={ok_match}"
        )
        print(f"[offset_replay_gate] gate={'PASS' if ok else 'FAIL'}")

        if bool(args.json):
            print(
                json.dumps(
                    {
                        "ok": ok,
                        "node_id": node_id,
                        "document_id": document_id,
                        "page": int(page),
                        "start_offset": int(start_off),
                        "end_offset": int(end_off),
                        "content_len": clen,
                    },
                    ensure_ascii=False,
                )
            )

        return 0 if ok else 2

    except (HTTPError, URLError) as e:
        print(f"[offset_replay_gate] ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[offset_replay_gate] ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
