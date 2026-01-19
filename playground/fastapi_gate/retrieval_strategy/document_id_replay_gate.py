# playground/fastapi_gate/retrieval_strategy/document_id_replay_gate.py

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "http://127.0.0.1:18000"
DEFAULT_USER_ID = "dev-user"
DEFAULT_KB_ID = "default"
DEFAULT_QUERY = "Financing"
DEFAULT_TIMEOUT_S = 60


def _http_json(
    url: str, *, method: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]], timeout_s: int
) -> Any:
    body = None
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers = dict(headers)
        headers["Content-Type"] = "application/json"
    req = Request(url=url, method=method, headers=headers, data=body)
    try:
        with urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except HTTPError as e:
        # IMPORTANT: print FastAPI 422 body for diagnosis
        try:
            raw = e.read().decode("utf-8")
        except Exception:
            raw = ""
        print(f"[document_id_replay_gate] HTTPError {getattr(e, 'code', None)} url={url}", file=sys.stderr)
        if raw:
            print(f"[document_id_replay_gate] body={raw}", file=sys.stderr)
        raise


def _call_chat(base_url: str, *, user_id: str, kb_id: str, query: str, timeout_s: int) -> Any:
    """
    Call /api/chat with backward-compatible payload keys.
    Tries multiple common request schemas to avoid 422 when ChatRequest evolves.
    """
    url = f"{str(base_url).rstrip('/')}/api/chat"
    headers = {"x-user-id": str(user_id)}
    payload = {"kb_id": str(kb_id), "query": str(query)}
    return _http_json(url, method="POST", headers=headers, payload=payload, timeout_s=timeout_s)


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="FastAPI gate: document_id/page alignment via by_node replay.")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--user-id", default=DEFAULT_USER_ID)
    p.add_argument("--kb-id", default=DEFAULT_KB_ID)
    p.add_argument("--query", default=DEFAULT_QUERY)
    p.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    try:
        # 1) chat -> citation node_id
        chat = _call_chat(
            str(args.base_url),
            user_id=str(args.user_id),
            kb_id=str(args.kb_id),
            query=str(args.query),
            timeout_s=int(args.timeout_s),
        )
        citations = (chat or {}).get("citations") or []
        node_id = None
        if isinstance(citations, list) and citations:
            first = citations[0]
            if isinstance(first, dict):
                node_id = str(first.get("node_id") or "").strip()

        if not node_id:
            print("[document_id_replay_gate] ERROR: no node_id from chat citations", file=sys.stderr)
            return 2

        # 2) node preview -> document_id + page
        url_node = f"{str(args.base_url).rstrip('/')}/api/records/node/{node_id}"
        node = _http_json(
            url_node,
            method="GET",
            headers={"x-user-id": str(args.user_id)},
            payload=None,
            timeout_s=int(args.timeout_s),
        )
        document_id = str((node or {}).get("document_id") or "").strip()
        page = (node or {}).get("page")
        if not document_id or not page:
            print("[document_id_replay_gate] ERROR: node missing document_id/page", file=sys.stderr)
            return 2
        page_i = int(page)

        # 3) by_node replay (must align)
        url_page = f"{str(args.base_url).rstrip('/')}/api/records/page/by_node/{node_id}?kb_id={str(args.kb_id)}&max_chars=8000"
        page_resp = _http_json(
            url_page,
            method="GET",
            headers={"x-user-id": str(args.user_id)},
            payload=None,
            timeout_s=int(args.timeout_s),
        )

        doc2 = str((page_resp or {}).get("document_id") or "").strip()
        page2 = int((page_resp or {}).get("page") or 0)
        content = str((page_resp or {}).get("content") or "")
        ok = bool(doc2 == document_id and page2 == page_i and f"page: {page_i}" in content.lower())

        print(f"[document_id_replay_gate] node_id={node_id}")
        print(f"[document_id_replay_gate] node.document_id={document_id} node.page={page_i}")
        print(f"[document_id_replay_gate] replay.document_id={doc2} replay.page={page2}")
        print(f"[document_id_replay_gate] content_len={len(content)} ok={ok}")
        print(f"[document_id_replay_gate] gate={'PASS' if ok else 'FAIL'}")

        if bool(args.json):
            print(
                json.dumps(
                    {"ok": ok, "node_id": node_id, "document_id": document_id, "page": page_i}, ensure_ascii=False
                )
            )

        return 0 if ok else 2

    except (HTTPError, URLError) as e:
        print(f"[document_id_replay_gate] ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[document_id_replay_gate] ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
