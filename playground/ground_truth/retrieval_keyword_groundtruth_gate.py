#!/usr/bin/env python3
# playground/retrieval_groundtruth_gate/keyword_groundtruth_gate.py

"""
[职责] keyword_groundtruth_gate：验证“PDF/KB 级关键词全量召回（L0）”。
[边界] 不依赖 retrieval pipeline 的融合/重排；Ground Truth 通过 DB node 文本物理扫描构造。
[上游关系] ingest 已完成，node/document 已落库；可选依赖已有 retrieval_record（来源于 /api/chat）。
[下游关系] 用于评估 keyword_recall 是否达到“全量召回”目标（如 >= 0.99），为 P0-P4 强化提供度量基线。

定义（默认）：
- GroundTruth(GT): 在 node.text 或 node.content 中做物理包含（LIKE）匹配得到的 node 集合（可选 word-boundary）。
- KeywordHits(KW): retrieval_hit 表中 source='keyword' 且 retrieval_record_id=rid 的 node 集合。
- Recall = |KW ∩ GT| / |GT|。

注意：
- 这不是“keyword_hits ⊆ fused_hits”的系统一致性验证；这是“知识源级别全量覆盖”验证。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple


# ----------------------------
# Utils
# ----------------------------


def _eprint(*a: Any) -> None:
    print(*a, file=sys.stderr)


def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    return con


def _table_columns(con: sqlite3.Connection, table: str) -> List[str]:
    rows = con.execute(f"PRAGMA table_info({table});").fetchall()
    return [r["name"] for r in rows]


def _has_table(con: sqlite3.Connection, table: str) -> bool:
    r = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=? LIMIT 1;",
        (table,),
    ).fetchone()
    return bool(r)


def _pick_node_text_column(con: sqlite3.Connection) -> str:
    cols = set(_table_columns(con, "node"))
    # 你项目中 NodeModel 常见字段：text / content；优先 text
    if "text" in cols:
        return "text"
    if "content" in cols:
        return "content"
    # fallback：尝试一些常见命名
    for cand in ("node_text", "chunk_text", "raw_text"):
        if cand in cols:
            return cand
    raise RuntimeError("node table has no usable text column (expected text/content/...)")


def _build_like_pattern(keyword: str, *, case_insensitive: bool) -> Tuple[str, str]:
    """
    Returns (expr_sql, param_value) where expr_sql is something like:
      lower(col) LIKE lower(?)
    """
    kw = str(keyword or "")
    if not kw.strip():
        raise ValueError("keyword is empty")
    if case_insensitive:
        return "lower({col}) LIKE lower(?)", f"%{kw.strip()}%"
    return "{col} LIKE ?", f"%{kw.strip()}%"


def _word_boundary_regex(keyword: str) -> re.Pattern:
    # \b 在英文语境可用；若含非字母数字字符，依然可工作但可能不完美
    kw = re.escape(keyword.strip())
    return re.compile(rf"\b{kw}\b", flags=re.IGNORECASE)


@dataclass
class GateResult:
    ok: bool
    db_path: str
    kb_id: str
    keyword: str
    rid: str
    gt_total: int
    kw_total: int
    overlap: int
    recall: float
    missing_in_kw: List[str]
    extra_in_kw: List[str]


# ----------------------------
# Core Queries
# ----------------------------


def _resolve_latest_rid(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT id FROM retrieval_record ORDER BY created_at DESC LIMIT 1;").fetchone()
    if not row:
        raise RuntimeError("no retrieval_record found; run /api/chat once to create one")
    return str(row["id"])


def _load_keyword_hits(con: sqlite3.Connection, rid: str) -> Set[str]:
    if not _has_table(con, "retrieval_hit"):
        raise RuntimeError("missing table retrieval_hit")
    rows = con.execute(
        """
        SELECT DISTINCT node_id
        FROM retrieval_hit
        WHERE retrieval_record_id = ?
          AND source = 'keyword'
        """,
        (rid,),
    ).fetchall()
    return {str(r["node_id"]) for r in rows if r["node_id"]}


def _nodes_in_kb_clause(con: sqlite3.Connection) -> Tuple[str, str]:
    """
    返回 (sql_from_and_where, mode)：
    - mode='join_document'：node JOIN document 过滤 kb_id
    - mode='node_has_kb_id'：node.kb_id 过滤
    """
    node_cols = set(_table_columns(con, "node"))
    if "kb_id" in node_cols:
        return "FROM node n WHERE n.kb_id = ?", "node_has_kb_id"

    # 常规：node 有 document_id，document 有 kb_id
    if not _has_table(con, "document"):
        raise RuntimeError("cannot scope nodes by kb_id: missing document table and node.kb_id")
    doc_cols = set(_table_columns(con, "document"))
    if "kb_id" not in doc_cols:
        raise RuntimeError("document table missing kb_id; cannot scope nodes by kb_id")

    return "FROM node n JOIN document d ON d.id = n.document_id WHERE d.kb_id = ?", "join_document"


def _load_ground_truth_nodes(
    con: sqlite3.Connection,
    *,
    kb_id: str,
    keyword: str,
    case_insensitive: bool,
    word_boundary: bool,
    limit_scan: Optional[int] = None,
) -> Set[str]:
    """
    GT 默认用 LIKE 做物理包含；若 word_boundary=True，则以“先粗筛 LIKE 再 Python regex 精筛”的方式实现。
    """
    text_col = _pick_node_text_column(con)
    from_where, _mode = _nodes_in_kb_clause(con)

    like_tpl, like_param = _build_like_pattern(keyword, case_insensitive=case_insensitive)
    like_expr = like_tpl.format(col=f"n.{text_col}")

    sql = f"""
        SELECT n.id AS node_id, n.{text_col} AS node_text
        {from_where}
          AND {like_expr}
    """
    params: List[Any] = [str(kb_id), like_param]
    if limit_scan is not None and int(limit_scan) > 0:
        sql += " LIMIT ?"
        params.append(int(limit_scan))

    rows = con.execute(sql, tuple(params)).fetchall()

    if not word_boundary:
        return {str(r["node_id"]) for r in rows if r["node_id"]}

    # word-boundary 精筛（针对英文关键词场景）
    rx = _word_boundary_regex(keyword)
    out: Set[str] = set()
    for r in rows:
        nid = str(r["node_id"])
        txt = r["node_text"]
        if not nid or txt is None:
            continue
        if rx.search(str(txt)):
            out.add(nid)
    return out


def _preview_nodes(
    con: sqlite3.Connection,
    node_ids: Sequence[str],
    *,
    max_items: int = 8,
) -> List[Dict[str, Any]]:
    """
    方便你快速人工 spot-check：输出 node_id/page + excerpt head。
    """
    if not node_ids:
        return []
    text_col = _pick_node_text_column(con)
    cols = set(_table_columns(con, "node"))
    page_col = "page" if "page" in cols else None

    picked = list(dict.fromkeys([str(x) for x in node_ids if x]))[:max_items]
    qmarks = ",".join(["?"] * len(picked))
    sel_cols = ["id", text_col]
    if page_col:
        sel_cols.append(page_col)
    sql = f"SELECT {', '.join('n.' + c for c in sel_cols)} FROM node n WHERE n.id IN ({qmarks})"
    rows = con.execute(sql, tuple(picked)).fetchall()

    out: List[Dict[str, Any]] = []
    for r in rows:
        txt = str(r[text_col] or "")
        out.append(
            {
                "node_id": str(r["id"]),
                "page": int(r[page_col]) if page_col and r[page_col] is not None else None,
                "text_head": " ".join(txt.split())[:200],
            }
        )
    return out


# ----------------------------
# Gate
# ----------------------------


def run_gate(
    *,
    db_path: str,
    kb_id: str,
    keyword: str,
    rid: Optional[str],
    min_recall: float,
    case_insensitive: bool,
    word_boundary: bool,
    limit_scan: Optional[int],
    show_preview: bool,
) -> GateResult:
    con = _connect(db_path)
    try:
        effective_rid = str(rid or "").strip() or _resolve_latest_rid(con)

        gt = _load_ground_truth_nodes(
            con,
            kb_id=kb_id,
            keyword=keyword,
            case_insensitive=case_insensitive,
            word_boundary=word_boundary,
            limit_scan=limit_scan,
        )
        kw = _load_keyword_hits(con, effective_rid)

        overlap = len(gt & kw)
        recall = (overlap / len(gt)) if gt else 1.0

        missing = sorted(list(gt - kw))
        extra = sorted(list(kw - gt))

        ok = (recall >= float(min_recall)) if gt else True

        # print human summary
        print(f"[keyword_groundtruth_gate] db={db_path}")
        print(f"[keyword_groundtruth_gate] rid={effective_rid}")
        print(f"[keyword_groundtruth_gate] kb_id={kb_id} keyword={keyword!r}")
        print(f"[keyword_groundtruth_gate] GT_total={len(gt)} KW_total={len(kw)} overlap={overlap}")
        print(
            f"[keyword_groundtruth_gate] recall={recall:.4f} gate={'PASS' if ok else 'FAIL'} (min_recall={min_recall})"
        )
        if missing:
            print(f"[keyword_groundtruth_gate] missing_in_keyword_hits n={len(missing)} (top 20):")
            for nid in missing[:20]:
                print(f"  - {nid}")
        if show_preview and missing:
            pv = _preview_nodes(con, missing, max_items=8)
            if pv:
                print("[keyword_groundtruth_gate] preview_missing_nodes:")
                for item in pv:
                    print(f"  - node_id={item['node_id']} page={item['page']} head={item['text_head']!r}")

        return GateResult(
            ok=ok,
            db_path=db_path,
            kb_id=kb_id,
            keyword=keyword,
            rid=effective_rid,
            gt_total=len(gt),
            kw_total=len(kw),
            overlap=overlap,
            recall=recall,
            missing_in_kw=missing,
            extra_in_kw=extra,
        )
    finally:
        con.close()


# ----------------------------
# CLI
# ----------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Keyword GroundTruth Recall Gate (L0)")
    p.add_argument("--db", dest="db_path", default=os.environ.get("UAE_LAW_RAG_DB", ".Local/uae_law_rag.db"))
    p.add_argument("--kb-id", dest="kb_id", default="default")
    p.add_argument("--keyword", dest="keyword", required=True)
    p.add_argument("--rid", dest="rid", default=None, help="retrieval_record_id; default=latest")
    p.add_argument("--min-recall", dest="min_recall", type=float, default=0.99)
    p.add_argument("--case-insensitive", dest="case_insensitive", action="store_true", default=True)
    p.add_argument("--case-sensitive", dest="case_insensitive", action="store_false")
    p.add_argument(
        "--word-boundary", action="store_true", help="apply word-boundary filtering (regex) after LIKE prefilter"
    )
    p.add_argument(
        "--limit-scan", type=int, default=None, help="limit GT scan rows (debug only; do not use for real gate)"
    )
    p.add_argument("--preview", action="store_true", help="print preview of missing nodes")
    p.add_argument("--json", action="store_true", help="print json result")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)

    try:
        res = run_gate(
            db_path=str(args.db_path),
            kb_id=str(args.kb_id),
            keyword=str(args.keyword),
            rid=str(args.rid) if args.rid else None,
            min_recall=float(args.min_recall),
            case_insensitive=bool(args.case_insensitive),
            word_boundary=bool(args.word_boundary),
            limit_scan=int(args.limit_scan) if args.limit_scan is not None else None,
            show_preview=bool(args.preview),
        )
    except Exception as exc:
        _eprint(f"[keyword_groundtruth_gate] ERROR: {exc.__class__.__name__}: {exc}")
        if args.json:
            print(json.dumps({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}))
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "ok": res.ok,
                    "db": res.db_path,
                    "kb_id": res.kb_id,
                    "keyword": res.keyword,
                    "rid": res.rid,
                    "gt_total": res.gt_total,
                    "kw_total": res.kw_total,
                    "overlap": res.overlap,
                    "recall": res.recall,
                    "missing_in_kw": res.missing_in_kw,
                    "extra_in_kw": res.extra_in_kw,
                },
                ensure_ascii=False,
            )
        )
    return 0 if res.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
