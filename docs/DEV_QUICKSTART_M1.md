# DEV_QUICKSTART_M1 — 开发者最小闭环快速启动指南

> **目标（M1 Gate）**：
> 在本地完成一次完整的 **ingest → retrieval → generation → citations → records 可回放** 的最小可信闭环。
>
> 本文档假定你已经完成代码编译、依赖安装与基础配置，仅关注**从零环境到一次可解释对话**的最短路径。

---

## 0. 前置条件

* Milvus 已启动（Docker / 本机均可），Attu 可选。
* 仓库根目录：`uae_law_rag/`
* **所有 Python 命令统一加：** `PYTHONPATH=src`
* 本地 SQLite 路径固定为：`.Local/uae_law_rag.db`

---

## 1. 初始化 DB（含 default KB + SQLite FTS）

### 1.1 执行初始化

```bash
PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_db --drop --seed --seed-fts
```

可选：当你怀疑 node 已存在但 FTS 是后补的（或 triggers 曾缺失），执行重建：

```bash
PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_db --seed-fts --rebuild-fts
```

### 1.2 预期信号

* 输出 `status=ok`
* DB URL 指向 `.Local/uae_law_rag.db`
* `seed_status` 不为 error

### 1.3 校验 default KB 已存在

```bash
sqlite3 .Local/uae_law_rag.db "select kb_name, milvus_collection, embed_dim from knowledge_base;"
```

预期至少一行：

* `kb_name = default`
* `milvus_collection = kb_default`
* `embed_dim = 384`

---

## 2. 初始化 Milvus Collection（与 default KB 对齐）

```bash
PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_milvus \
  --collection kb_default \
  --embed-dim 384 \
  --metric-type COSINE \
  --drop
```

### 2.1 预期信号

* `status=ok`
* `created=True`
* `index_ensured=True`
* `loaded=True`

---

## 3. 启动后端（FastAPI）

```bash
PYTHONPATH=src uvicorn uae_law_rag.backend.main:app --host 127.0.0.1 --port 18000 --reload
```

### 3.1 Health Check

```bash
curl -sS http://127.0.0.1:18000/api/health | python -m json.tool
```

预期：

* `status: ok`
* `db.ok: true`
* `milvus.ok: true | optional`

### 3.2 校验 Admin 可见 default KB

```bash
curl -sS http://127.0.0.1:18000/api/admin/kbs -H "x-user-id: dev-user" | python -m json.tool
```

预期：

* 返回数组
* 至少一项 `kb_id == "default"`

---

## 4. 启动前端（Vite + Proxy）

```bash
cd src/uae_law_rag/frontend
pnpm dev
```

* 访问：[http://localhost:5173/](http://localhost:5173/)
* 前端请求路径：`/api/*` → proxy → `http://127.0.0.1:18000/api/*`

---

## 5. Ingest PDF（写入 DB + Milvus）

### 5.1 Dry Run（仅验证）

```bash
curl -sS -X POST "http://127.0.0.1:18000/api/ingest?debug=true" \
  -H "Content-Type: application/json" \
  -H "x-user-id: dev-user" \
  --data-binary @- <<'JSON' | python -m json.tool
{
  "kb_id": "default",
  "source_uri": "/ABSOLUTE/PATH/TO/demo.pdf",
  "file_name": "demo.pdf",
  "dry_run": true,
  "ingest_profile": { "parser": "pymupdf4llm" }
}
JSON
```

### 5.2 真正写入（Dry Run = false）

```bash
curl -sS -X POST "http://127.0.0.1:18000/api/ingest?debug=true" \
  -H "Content-Type: application/json" \
  -H "x-user-id: dev-user" \
  --data-binary @- <<'JSON' | python -m json.tool
{
  "kb_id": "default",
  "source_uri": "/ABSOLUTE/PATH/TO/demo.pdf",
  "file_name": "demo.pdf",
  "dry_run": false,
  "ingest_profile": { "parser": "pymupdf4llm" }
}
JSON
```

### 5.3 必验（DB 侧）

```bash
sqlite3 .Local/uae_law_rag.db "select count(*) from node;"
sqlite3 .Local/uae_law_rag.db "select count(*) from node_vector_map;"
sqlite3 .Local/uae_law_rag.db "select name,type from sqlite_master where name like 'node_fts%' order by name;"
```

预期：

* 两者均 > 0

---

## 6. Chat（最小可解释对话）

```bash
curl -sS -X POST http://127.0.0.1:18000/api/chat \
  -H 'Content-Type: application/json' \
  -H 'x-user-id: dev-user' \
  --data-binary @- <<'JSON' | python -m json.tool
{
  "query": "YOU QUERY TEXT",
  "kb_id": "default",
  "debug": true
}
JSON
```

### 6.1 M1 判定信号

* `status ∈ {success, partial, blocked}`
* `debug.hits_count > 0`
* `citations`：

  * success / partial：≥ 1
  * blocked：允许为 0（但 retrieval 必须存在）
* 返回 `retrieval_record_id / generation_record_id / evaluation_record_id`

---

## 7. Records 回放（Evidence Panel 数据源）

### 7.1 Retrieval Record

```bash
curl -sS http://127.0.0.1:18000/api/records/retrieval/<RETRIEVAL_RECORD_ID> | python -m json.tool
```

### 7.2 Generation Record

```bash
curl -sS http://127.0.0.1:18000/api/records/generation/<GENERATION_RECORD_ID> | python -m json.tool
```

### 7.3 Evaluator：Keyword Recall（全文片段召回评估，用于 EvaluatorPanel）

> **产品定义**：对每个 keyword，计算
> - **GT（Ground Truth）**：在 `node.text` 中 substring 出现的节点集合（更贴近“前端展示原文片段”）
> - **KW（System）**：系统实际 `keyword_recall(FTS)` 返回的节点集合
> - 输出 `recall / precision / capped / missing_sample / extra_sample`（可直接驱动前端指标与抽样展示）

#### 7.3.1 单关键词评估（最小可用）

```bash
curl -sS -X POST "http://127.0.0.1:18000/api/evaluator/keyword_recall" \
  -H "Content-Type: application/json" \
  --data-binary @- \
| python -c 'import sys,json; d=json.load(sys.stdin); print("top-level keys:", sorted(d.keys())); m=(d.get("metrics") or []); print"metrics_n:", len(m));\
kw=m[0] if m else {}; print(kw.get("keyword"), "gt=", kw.get("gt_total"), "kw=", kw.get("kw_total"), "recall=", kw.get("recall"), precision=", kw.get("precision"), "capped=", kw.get("capped"));\
print("timing_ms:", d.get("timing_ms"));' <<'JSON'
{
  "kb_id": "default",
  "raw_query": "Financing",
  "keywords_list": ["Financing"],
  "keyword_top_k": 200,
  "allow_fallback": true,
  "case_sensitive": false,
  "sample_n": 10
}
JSON
```

#### 7.3.2 多关键词评估（EvaluatorPanel 批量模式）

```bash
curl -sS -X POST "http://127.0.0.1:18000/api/evaluator/keyword_recall" \
  -H "Content-Type: application/json" \
  --data-binary @- \
| python -c 'import sys,json; d=json.load(sys.stdin); ms=d.get("metrics") or [];\
print("metrics_n:", len(ms));\
for m in ms:\
  print(m.get("keyword"), "recall=", m.get("recall"), "precision=", m.get("precision"), "gt=", m.get("gt_total"), "kw=", m.get"kw_total"), "capped=", m.get("capped"));' <<'JSON'
{
  "kb_id": "default",
  "raw_query": "I want to learn Abu Dhabi rental laws",
  "keywords_list": ["Abu Dhabi", "rental", "real estate", "lease", "tenant", "landlord"],
  "keyword_top_k": 200,
  "allow_fallback": true,
  "case_sensitive": false,
  "sample_n": 5
}
JSON
```

#### 7.3.3 判定信号（建议门槛）

* `metrics[].recall`：
  * 对“知识库内存在的意义关键词”，期望 `≥ 0.99`
* `metrics[].capped`：
  * `true` 表示 `keyword_top_k` 可能截断导致 recall 假低（需要提高 top_k 或缩小 scope）
* `missing_sample / extra_sample`：
  * 用于前端抽样展示：哪些 GT 片段未被 FTS 找到 / 哪些 FTS 命中不属于 GT（token/substring 定义差异）

---

## 8. 一键重置套路（推荐）

```bash
# reset db
PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_db --drop --seed --rebuild-fts

# reset milvus
PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_milvus \
  --collection kb_default --embed-dim 384 --metric-type COSINE --drop

# restart backend
PYTHONPATH=src uvicorn uae_law_rag.backend.main:app --host 127.0.0.1 --port 18000 --reload
```

---

## 9. M1 完成定义（Gate）

M1 被视为 **完成**，当且仅当：

1. `ingest` 成功写入 node + vector
2. `chat` 能返回一次完整 response
3. `retrieval_record` 可回放
4. `generation` 输出与 citations 对齐（或被明确判定为 blocked）
5. 前端 ChatPage 能展示 Answer + EvidencePanel

---

> 下一步：
> 在此基础上，我们将进入 **P0–P4 阶段闭环强化**：
>
> * P0：结构化 Evidence 合同冻结
> * P1：Retriever Recall / Coverage Gate
> * P2：Citation Alignment Gate
> * P3：Answer–Evidence Consistency Gate
> * P4：Evaluator 稳定性与回归防护
