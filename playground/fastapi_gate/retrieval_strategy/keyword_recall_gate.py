#!/usr/bin/env python3
"""
[职责] keyword_recall_gate：对单次 query 的 retrieval 四路命中（keyword/vector/fused/reranked）做白箱审计，
      并对“关键词全量召回覆盖率”进行 gate 判定（默认检查 keyword 命中是否被 fused/reranked 覆盖）。
[边界] 依赖 FastAPI 服务已启动；不直连 DB/Milvus；只通过 HTTP API 回放。
[上游关系] /api/chat 产出 retrieval_record_id；/api/records/retrieval/{rid} 提供 hits 明细。
[下游关系] 为前端 EvidencePanel/策略调参提供可量化依据；为 recall>=99% 的目标提供 gate。
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Set
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


DEFAULT_BASE_URL = "http://127.0.0.1:18000"
DEFAULT_USER_ID = "dev-user"
DEFAULT_KB_ID = "default"
DEFAULT_QUERY = "Financing"

# 默认与当前系统配置一致
DEFAULT_KEYWORD_TOP_K = 200
DEFAULT_VECTOR_TOP_K = 50
DEFAULT_FUSION_TOP_K = 50
DEFAULT_RERANK_TOP_K = 10

DEFAULT_MIN_COVERAGE = 0.99  # 99% gate
DEFAULT_TIMEOUT_S = 60


@dataclass(frozen=True)
class GateResult:
    ok: bool
    rid: str
    query: str
    kb_id: str
    coverage_kw_to_fused: float
    coverage_kw_to_reranked: float
    counts_by_source: Dict[str, int]
    unique_nodes_by_source: Dict[str, int]
    missing_kw_in_fused: List[str]
    missing_kw_in_reranked: List[str]


def _http_json(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Mapping[str, str]] = None,
    payload: Optional[Mapping[str, Any]] = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
) -> Dict[str, Any]:
    body: Optional[bytes] = None
    req_headers = {"Accept": "application/json"}
    if headers:
        req_headers.update(dict(headers))
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = Request(url=url, data=body, method=method, headers=req_headers)
    try:
        with urlopen(req, timeout=int(timeout_s)) as resp:
            raw = resp.read()
    except HTTPError as e:
        raw = e.read() if hasattr(e, "read") else b""
        text = raw.decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTPError {e.code} for {url}: {text[:300]}")
    except URLError as e:
        raise RuntimeError(f"URLError for {url}: {e}")
    except Exception as e:
        raise RuntimeError(f"Request failed for {url}: {e}")

    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as e:
        text = raw.decode("utf-8", errors="replace")
        raise RuntimeError(f"JSON decode failed for {url}: {e}; body_head={text[:200]!r}")


def _extract_rid_from_chat(chat_resp: Mapping[str, Any]) -> str:
    debug = chat_resp.get("debug") or {}
    records = debug.get("records") or {}
    rid = records.get("retrieval_record_id")
    rid = str(rid or "").strip()
    if not rid:
        raise RuntimeError(f"missing retrieval_record_id in chat debug.records: keys={sorted(records.keys())}")
    return rid


def _coerce_hits(record_resp: Mapping[str, Any]) -> List[Dict[str, Any]]:
    hits = record_resp.get("hits")
    if hits is None:
        # 兼容你曾经的热修复输出字段：hits_by_source / hit_counts（如果未来又演进）
        hbs = record_resp.get("hits_by_source") or {}
        merged: List[Dict[str, Any]] = []
        if isinstance(hbs, dict):
            for _src, seq in hbs.items():
                if isinstance(seq, list):
                    merged.extend([dict(x) for x in seq if isinstance(x, dict)])
        hits = merged

    if not isinstance(hits, list):
        return []
    return [dict(h) for h in hits if isinstance(h, dict)]


def _node_ids(hits: Sequence[Mapping[str, Any]]) -> Set[str]:
    out: Set[str] = set()
    for h in hits:
        nid = str(h.get("node_id") or "").strip()
        if nid:
            out.add(nid)
    return out


def _by_source(hits: Sequence[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for h in hits:
        src = str(h.get("source") or "unknown").strip() or "unknown"
        buckets[src].append(dict(h))
    return dict(buckets)


def _coverage(a: Set[str], b: Set[str]) -> float:
    # coverage: how many from a are included in b
    if not a:
        return 1.0
    return len(a & b) / float(len(a))


def run_gate(
    *,
    base_url: str,
    user_id: str,
    kb_id: str,
    query: str,
    keyword_top_k: int,
    vector_top_k: int,
    fusion_top_k: int,
    rerank_top_k: int,
    min_coverage: float,
    timeout_s: int,
    print_top_missing: int,
    send_retrieval_config: bool,
) -> GateResult:
    chat_url = f"{base_url.rstrip('/')}/api/chat"
    rec_url_tpl = f"{base_url.rstrip('/')}/api/records/retrieval" + "/{rid}"

    chat_payload: Dict[str, Any] = {
        "query": query,
        "kb_id": kb_id,
        "debug": True,
    }

    # Only inject if explicitly enabled (backend must allow it)
    if bool(send_retrieval_config):
        chat_payload["retrieval_config"] = {
            "keyword_top_k": int(keyword_top_k),
            "vector_top_k": int(vector_top_k),
            "fusion_top_k": int(fusion_top_k),
            "rerank_top_k": int(rerank_top_k),
        }
    headers = {"x-user-id": str(user_id)}

    chat_resp = _http_json(
        chat_url,
        method="POST",
        headers=headers,
        payload=chat_payload,
        timeout_s=timeout_s,
    )
    rid = _extract_rid_from_chat(chat_resp)

    record_resp = _http_json(
        rec_url_tpl.format(rid=rid),
        method="GET",
        headers=headers,
        payload=None,
        timeout_s=timeout_s,
    )

    hits = _coerce_hits(record_resp)
    buckets = _by_source(hits)

    counts_by_source = {k: len(v) for k, v in buckets.items()}
    unique_nodes_by_source = {k: len(_node_ids(v)) for k, v in buckets.items()}

    kw_ids = _node_ids(buckets.get("keyword", []))
    fused_ids = _node_ids(buckets.get("fused", []))
    reranked_ids = _node_ids(buckets.get("reranked", []))

    cov_kw_to_fused = _coverage(kw_ids, fused_ids)
    cov_kw_to_reranked = _coverage(kw_ids, reranked_ids)

    missing_kw_in_fused = sorted(list(kw_ids - fused_ids))
    missing_kw_in_reranked = sorted(list(kw_ids - reranked_ids))

    ok = (cov_kw_to_fused >= float(min_coverage)) and (cov_kw_to_reranked >= float(min_coverage))

    # pretty print (developer view)
    print(f"[keyword_recall_gate] rid={rid}")
    print(f"[keyword_recall_gate] query={query!r} kb_id={kb_id} user_id={user_id}")
    print(f"[keyword_recall_gate] counts_by_source={counts_by_source}")
    print(f"[keyword_recall_gate] unique_nodes_by_source={unique_nodes_by_source}")
    print(f"[keyword_recall_gate] coverage(keyword -> fused)    = {cov_kw_to_fused:.4f}")
    print(f"[keyword_recall_gate] coverage(keyword -> reranked) = {cov_kw_to_reranked:.4f}")

    if print_top_missing > 0:
        if missing_kw_in_fused:
            print(f"[keyword_recall_gate] missing keyword nodes in fused (top {print_top_missing}):")
            for nid in missing_kw_in_fused[: int(print_top_missing)]:
                print(f"  - {nid}")
        if missing_kw_in_reranked:
            print(f"[keyword_recall_gate] missing keyword nodes in reranked (top {print_top_missing}):")
            for nid in missing_kw_in_reranked[: int(print_top_missing)]:
                print(f"  - {nid}")

    status = "PASS" if ok else "FAIL"
    print(f"[keyword_recall_gate] gate={status} (min_coverage={float(min_coverage):.2f})")

    return GateResult(
        ok=ok,
        rid=rid,
        query=query,
        kb_id=kb_id,
        coverage_kw_to_fused=cov_kw_to_fused,
        coverage_kw_to_reranked=cov_kw_to_reranked,
        counts_by_source=counts_by_source,
        unique_nodes_by_source=unique_nodes_by_source,
        missing_kw_in_fused=missing_kw_in_fused,
        missing_kw_in_reranked=missing_kw_in_reranked,
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="FastAPI gate: keyword recall coverage vs fused/reranked.")
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--user-id", default=DEFAULT_USER_ID)
    p.add_argument("--kb-id", default=DEFAULT_KB_ID)
    p.add_argument("--query", default=DEFAULT_QUERY)

    p.add_argument("--keyword-top-k", type=int, default=DEFAULT_KEYWORD_TOP_K)
    p.add_argument("--vector-top-k", type=int, default=DEFAULT_VECTOR_TOP_K)
    p.add_argument("--fusion-top-k", type=int, default=DEFAULT_FUSION_TOP_K)
    p.add_argument("--rerank-top-k", type=int, default=DEFAULT_RERANK_TOP_K)

    p.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE)
    p.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--print-top-missing", type=int, default=10)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--send-retrieval-config",
        action="store_true",
        help="Send retrieval_config in /api/chat body (requires backend schema support).",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        res = run_gate(
            base_url=str(args.base_url),
            user_id=str(args.user_id),
            kb_id=str(args.kb_id),
            query=str(args.query),
            keyword_top_k=int(args.keyword_top_k),
            vector_top_k=int(args.vector_top_k),
            fusion_top_k=int(args.fusion_top_k),
            rerank_top_k=int(args.rerank_top_k),
            min_coverage=float(args.min_coverage),
            timeout_s=int(args.timeout_s),
            print_top_missing=int(args.print_top_missing),
            send_retrieval_config=bool(args.send_retrieval_config),
        )
        if args.json:
            print(json.dumps(res.__dict__, ensure_ascii=False, default=str))
        return 0 if res.ok else 2
    except Exception as e:
        print(f"[keyword_recall_gate] ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
