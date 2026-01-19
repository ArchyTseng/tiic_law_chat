# playground/fastapi_gate/retrieval_strategy/evidence_grouping_gate.py

"""
[Responsibility] evidence_grouping_gate: validate evidence grouping output and caps.
[Boundary] No DB/HTTP; only input hits, grouping, and assertions.
[Upstream] Run manually or in gate workflows.
[Downstream] Locks minimal behavior for EvidencePanel/debug.evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from uae_law_rag.backend.utils.evidence import group_evidence_hits


DEFAULT_MAX_DOCUMENTS = 2
DEFAULT_MAX_NODES_PER_DOCUMENT = 4
DEFAULT_MAX_PAGES_PER_DOCUMENT = 2


@dataclass(frozen=True)
class GateResult:
    ok: bool
    evidence: Dict[str, Any]
    errors: List[str]


def _build_hits() -> List[Dict[str, Any]]:
    # docstring: build hits with 2 docs, multi-page, multi-node, two sources
    return [
        {"node_id": "n1", "document_id": "doc1", "page": 1, "source": "keyword", "file_id": "f1"},
        {"node_id": "n2", "document_id": "doc1", "page": 1, "source": "keyword", "file_id": "f1"},
        {"node_id": "n2", "document_id": "doc1", "page": 1, "source": "keyword", "file_id": "f1"},
        {"node_id": "n3", "document_id": "doc1", "page": 2, "source": "keyword", "file_id": "f1"},
        {"node_id": "n8", "document_id": "doc1", "page": None, "source": "keyword", "file_id": "f1"},
        {"node_id": "n9", "document_id": "doc1", "page": 2, "source": "keyword", "file_id": "f1"},
        {"node_id": "n4", "document_id": "doc2", "page": 1, "source": "reranked", "file_id": "f2"},
        {"node_id": "n5", "document_id": "doc2", "page": 2, "source": "reranked", "file_id": "f2"},
        {"node_id": "n6", "document_id": "doc2", "page": 3, "source": "reranked", "file_id": "f2"},
        {"node_id": "n7", "document_id": "doc3", "page": 1, "source": "keyword", "file_id": "f3"},
        {"node_id": "n_missing_doc", "document_id": "", "page": 1, "source": "keyword", "file_id": "f1"},
        {"node_id": "", "document_id": "doc1", "page": 1, "source": "keyword", "file_id": "f1"},
    ]


def _has_forbidden_keys(payload: Any, forbidden: Sequence[str]) -> bool:
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in forbidden:
                return True
            if _has_forbidden_keys(v, forbidden):
                return True
    elif isinstance(payload, list):
        for item in payload:
            if _has_forbidden_keys(item, forbidden):
                return True
    return False


def run_gate(
    *,
    max_documents: int,
    max_nodes_per_document: int,
    max_pages_per_document: int,
) -> GateResult:
    hits = _build_hits()
    evidence = group_evidence_hits(
        hits,
        max_documents=max_documents,
        max_nodes_per_document=max_nodes_per_document,
        max_pages_per_document=max_pages_per_document,
    )

    errors: List[str] = []
    document_ids = evidence.get("document_ids") or []
    by_source = evidence.get("by_source") or {}

    if document_ids != ["doc1", "doc2"]:
        errors.append(f"document_ids mismatch: {document_ids!r}")

    if not isinstance(by_source, dict) or not by_source:
        errors.append("by_source missing or not a dict")
    else:
        if "keyword" not in by_source or "reranked" not in by_source:
            errors.append(f"by_source missing expected sources: keys={sorted(by_source.keys())}")

    if _has_forbidden_keys(evidence, ("excerpt", "content")):
        errors.append("evidence contains forbidden keys: excerpt/content")

    reranked_doc2 = ((by_source.get("reranked") or {}).get("by_document") or {}).get("doc2") or {}
    pages_doc2 = reranked_doc2.get("pages") or {}
    if len(pages_doc2) > max_pages_per_document:
        errors.append(f"pages cap not enforced: pages={list(pages_doc2.keys())}")
    if "3" in pages_doc2:
        errors.append("page 3 should be capped out for doc2")

    keyword_doc1 = ((by_source.get("keyword") or {}).get("by_document") or {}).get("doc1") or {}
    pages_doc1 = keyword_doc1.get("pages") or {}
    if pages_doc1.get("1") != ["n1", "n2"]:
        errors.append(f"node order mismatch for doc1/page1: {pages_doc1.get('1')!r}")
    if pages_doc1.get("2") != ["n3"]:
        errors.append(f"node cap not enforced for doc1/page2: {pages_doc1.get('2')!r}")
    if pages_doc1.get("_") != ["n8"]:
        errors.append(f"unknown page bucket mismatch: {pages_doc1.get('_')!r}")
    if "doc3" in ((by_source.get("keyword") or {}).get("by_document") or {}):
        errors.append("max_documents cap not enforced: doc3 still present")

    stats = (evidence.get("meta") or {}).get("stats") or {}
    if stats.get("dropped_missing_document_id") != 1:
        errors.append(f"dropped_missing_document_id mismatch: {stats.get('dropped_missing_document_id')!r}")
    if stats.get("dropped_missing_node_id") != 1:
        errors.append(f"dropped_missing_node_id mismatch: {stats.get('dropped_missing_node_id')!r}")
    if stats.get("unknown_page_count") != 1:
        errors.append(f"unknown_page_count mismatch: {stats.get('unknown_page_count')!r}")
    if stats.get("deduped_node_count") != 1:
        errors.append(f"deduped_node_count mismatch: {stats.get('deduped_node_count')!r}")
    if stats.get("total_hits_in") != 12:
        errors.append(f"total_hits_in mismatch: {stats.get('total_hits_in')!r}")
    if stats.get("total_hits_used") != 6:
        errors.append(f"total_hits_used mismatch: {stats.get('total_hits_used')!r}")

    ok = not errors
    return GateResult(ok=ok, evidence=evidence, errors=errors)


def test_evidence_grouping_gate() -> None:
    res = run_gate(
        max_documents=DEFAULT_MAX_DOCUMENTS,
        max_nodes_per_document=DEFAULT_MAX_NODES_PER_DOCUMENT,
        max_pages_per_document=DEFAULT_MAX_PAGES_PER_DOCUMENT,
    )
    assert res.ok, f"evidence_grouping_gate failed: {res.errors}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Gate: evidence grouping pure function.")
    p.add_argument("--max-documents", type=int, default=DEFAULT_MAX_DOCUMENTS)
    p.add_argument("--max-nodes-per-document", type=int, default=DEFAULT_MAX_NODES_PER_DOCUMENT)
    p.add_argument("--max-pages-per-document", type=int, default=DEFAULT_MAX_PAGES_PER_DOCUMENT)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    res = run_gate(
        max_documents=int(args.max_documents),
        max_nodes_per_document=int(args.max_nodes_per_document),
        max_pages_per_document=int(args.max_pages_per_document),
    )

    print(f"[evidence_grouping_gate] ok={res.ok}")
    if res.errors:
        for err in res.errors:
            print(f"[evidence_grouping_gate] ERROR: {err}", file=sys.stderr)

    if bool(args.json):
        print(json.dumps({"ok": res.ok, "errors": res.errors, "evidence": res.evidence}, ensure_ascii=False))

    return 0 if res.ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
