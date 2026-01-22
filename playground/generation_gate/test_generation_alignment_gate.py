#!/usr/bin/env python3
# playground/generation_gate/test_generation_alignment_gate.py

"""
[职责] generation_alignment_gate：验证 generation 输出与 prompt evidence 的对齐不变式（M1 可解释闭环硬门槛）。
[边界] 不追求答案质量；只检查“引用必须来自 prompt 允许集合 + quote 可复现 + answer 显式引用 rank”。
[上游关系] 依赖 retrieval+generation 已实现且 /api/chat 可用；依赖 debug payload 中 prompt_debug/valid_node_ids。
[下游关系] 保障 EvidencePanel/NodePreview/PageReplay 的可解释性一致性，避免“答用A，引B”的审计缺陷。
"""

from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Set, Optional
from urllib.request import Request, urlopen
import pytest
import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:18000"
DEFAULT_USER_ID = "dev-user"
DEFAULT_KB_ID = "default"
DEFAULT_QUERY = "Financing"
DEFAULT_TIMEOUT_S = 120


def _env(name: str, default: str = "") -> str:
    v = str(os.getenv(name, default) or "").strip()
    return v


def _http_json(
    url: str,
    *,
    method: str,
    headers: Dict[str, str],
    payload: Optional[Dict[str, Any]],
    timeout_s: int,
) -> Dict[str, Any]:
    data = None
    req_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = Request(
        url,
        data=data,
        method=str(method).upper(),
        headers=req_headers,
    )
    with urlopen(req, timeout=int(timeout_s)) as resp:
        body = resp.read().decode("utf-8")
        return json.loads(body)


def _assert_has_keys(obj: Dict[str, Any], keys: List[str]) -> None:
    for k in keys:
        assert k in obj, f"missing key: {k}"


def _as_list(x: Any) -> List[Any]:
    return list(x) if isinstance(x, list) else []


def _collect_valid_node_ids(debug_payload: Dict[str, Any]) -> Set[str]:
    """
    Prefer messages_snapshot.valid_node_ids if present (post-patch),
    fallback to prompt_debug.context_items node_id list.
    """
    # 1) Try direct valid_node_ids (most deterministic)
    # debug.prompt_debug is extracted from generation_bundle; typical shape:
    # debug["prompt_debug"] = {"context_items":[{"node_id":...},...], ...}
    prompt_debug = debug_payload.get("prompt_debug") or {}
    v = prompt_debug.get("valid_node_ids")
    if isinstance(v, list) and v:
        return {str(i).strip() for i in v if str(i or "").strip()}

    # 2) Fallback: context_items
    ctx_items = _as_list(prompt_debug.get("context_items"))
    out: Set[str] = set()
    for it in ctx_items:
        if isinstance(it, dict):
            nid = str(it.get("node_id") or "").strip()
            if nid:
                out.add(nid)
    return out


def _collect_used_node_ids(prompt_debug: Dict[str, Any]) -> Set[str]:
    """
    Used nodes (prompt context) from prompt_debug.context_items.
    """
    ctx_items = _as_list(prompt_debug.get("context_items"))
    out: Set[str] = set()
    for it in ctx_items:
        if isinstance(it, dict):
            nid = str(it.get("node_id") or "").strip()
            if nid:
                out.add(nid)
    return out


def _extract_citations(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    cits = resp.get("citations")
    if not isinstance(cits, list):
        return []
    out: List[Dict[str, Any]] = []
    for c in cits:
        if isinstance(c, dict):
            out.append(c)
    return out


def _extract_rank(cit: Dict[str, Any]) -> int:
    r = cit.get("rank")
    if r is None:
        return -1
    try:
        return int(r)
    except (TypeError, ValueError):
        return -1


def _extract_first_conversation_id(resp: Any) -> str | None:
    """
    Try best-effort parsing across common response shapes:
    - list[{"id":...}, ...]
    - {"items":[{"id":...}, ...]}
    - {"data":[{"id":...}, ...]}
    - {"conversations":[{"id":...}, ...]}
    """

    def _pick_id(x: Any) -> str | None:
        if isinstance(x, dict):
            cid = x.get("id") or x.get("conversation_id")
            return str(cid) if cid else None
        return None

    if isinstance(resp, list):
        for item in resp:
            cid = _pick_id(item)
            if cid:
                return cid
        return None
    if isinstance(resp, dict):
        for key in ("items", "data", "conversations"):
            arr = resp.get(key)
            if isinstance(arr, list):
                for item in arr:
                    cid = _pick_id(item)
                    if cid:
                        return cid
    return None


def _get_any_conversation_id(base_url: str, *, headers: dict[str, str], timeout_s: int) -> str:
    """
    The /api/chat endpoint requires conversation_id (router forbids body.user_id),
    so the gate must reuse an existing conversation.
    """
    # Try a few plausible endpoints (your frontend already lists conversations, so one of these exists).
    candidates = [
        f"{base_url}/api/conversations",
        f"{base_url}/api/conversation",
        f"{base_url}/api/chat/conversations",
    ]
    last_err: Exception | None = None
    for url in candidates:
        try:
            resp = _http_json(url, method="GET", headers=headers, payload=None, timeout_s=timeout_s)
            cid = _extract_first_conversation_id(resp)
            if cid:
                return cid
        except Exception as e:
            last_err = e
            continue
    raise RuntimeError(
        "cannot resolve any conversation_id via known endpoints; "
        "please ensure there is at least one conversation in DB and an endpoint exists. "
        f"last_err={last_err}"
    )


@pytest.mark.asyncio
async def test_generation_alignment_gate() -> None:
    """
    Gate conditions (success/partial):
    1) citations count >= 3
    2) each citation.node_id must be within valid_node_ids (prompt-allowed)
    3) each citation.quote must be non-empty
    4) answer must contain rank markers for each citation: e.g. "[1]"
    """
    base_url = _env("UAE_LAW_RAG_BASE_URL", "http://127.0.0.1:18000").rstrip("/")
    endpoint = f"{base_url}/api/chat"
    timeout_s = int(_env("UAE_LAW_RAG_TEST_TIMEOUT_S", "120"))

    headers = {"x-user-id": _env("UAE_LAW_RAG_TEST_USER_ID", "dev-user")}

    conversation_id = _env("UAE_LAW_RAG_CONVERSATION_ID", "").strip()
    if not conversation_id:
        conversation_id = _get_any_conversation_id(base_url, headers=headers, timeout_s=timeout_s)

    query = _env("UAE_LAW_RAG_TEST_QUERY", "Financing")

    payload: Dict[str, Any] = {
        "conversation_id": conversation_id,
        "query": query,
        "kb_id": _env("UAE_LAW_RAG_TEST_KB_ID", "default"),
        "debug": True,
    }
    conv_id = _env("UAE_LAW_RAG_TEST_CONVERSATION_ID", "")
    if conv_id:
        payload["conversation_id"] = conv_id

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        r = await client.post(endpoint, json=payload, headers=headers)
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
        resp = r.json()

    # Basic shape
    _assert_has_keys(resp, ["status", "answer", "citations"])
    status = str(resp.get("status") or "").strip().lower()

    # If blocked/failed, this gate should fail: generation must produce verifiable aligned citations.
    # We intentionally require success/partial for the alignment contract.
    assert status in {"success", "partial"}, f"unexpected status for alignment gate: {status} (resp={resp})"

    debug_payload = resp.get("debug")
    assert isinstance(debug_payload, dict), "debug payload missing; run with debug=true"

    prompt_debug = debug_payload.get("prompt_debug")
    assert isinstance(prompt_debug, dict), "debug.prompt_debug missing"

    valid_node_ids = _collect_valid_node_ids(debug_payload)
    used_node_ids = _collect_used_node_ids(prompt_debug)

    # valid_node_ids should not be empty if evidence exists
    assert valid_node_ids, "valid_node_ids empty; prompt did not expose allowed evidence ids"

    # Optional sanity: used nodes should be subset of valid_node_ids (or equal)
    if used_node_ids:
        assert used_node_ids.issubset(valid_node_ids) or valid_node_ids.issubset(
            used_node_ids
        ), f"used_node_ids and valid_node_ids mismatch (used={len(used_node_ids)}, valid={len(valid_node_ids)})"

    answer = str(resp.get("answer") or "")
    citations = _extract_citations(resp)

    # Gate 1: citations >= 3
    assert len(citations) >= 3, f"citations too few: {len(citations)} (need >=3). citations={citations}"

    # Gate 2/3/4: each citation must be allowed + quote non-empty + answer has marker
    bad: List[str] = []
    for c in citations:
        node_id = str(c.get("node_id") or "").strip()
        quote = str(c.get("quote") or "")
        rank = _extract_rank(c)

        if not node_id:
            bad.append("citation missing node_id")
            continue
        if node_id not in valid_node_ids:
            bad.append(f"citation node_id not allowed by prompt: {node_id}")
        if not quote.strip():
            bad.append(f"citation quote empty for node_id={node_id} rank={rank}")
        if rank < 1:
            bad.append(f"citation rank invalid for node_id={node_id}: {rank}")
        else:
            marker = f"[{rank}]"
            if marker not in answer:
                bad.append(f"answer missing rank marker {marker} for node_id={node_id}")

    assert not bad, "alignment gate failed:\n- " + "\n- ".join(bad)
