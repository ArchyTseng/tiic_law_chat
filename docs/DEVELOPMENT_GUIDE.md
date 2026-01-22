# DEVELOPMENT_GUIDE — UAE Law RAG

本指南面向开发者，覆盖从零环境到完整链路运行的全部步骤：依赖 → 配置 → 初始化 → 启动 → ingest/chat → 回放 → 重置 → 测试记录 → Docker 部署。

> 所有 Python 命令统一加：`PYTHONPATH=src`

---

## 0. 仓库结构速览

- `src/uae_law_rag/backend/`: FastAPI + pipelines（ingest/retrieval/generation/evaluator）
- `src/uae_law_rag/frontend/`: Vite + React 前端
- `infra/milvus/`: Milvus + Attu Docker Compose
- `playground/`: pytest gate 测试
- `docs/DEV_QUICKSTART_M1.md`: M1 最小闭环验证（已验证可用命令）

---

## 1. 运行依赖（必须）

### 1.1 系统依赖

- Python 3.11+（见 `pyproject.toml`）
- Node.js + pnpm（前端）
- Docker + Docker Compose（Milvus + Attu）
- `sqlite3` CLI（可选，便于验证 DB）

### 1.2 Python 依赖安装

推荐在虚拟环境内安装（最小可用闭环）：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[backend,db,llamaindex-basic,parsing]"
```

可选扩展（按需）：

- `llamaindex-advance`：高级检索/本地模型
- `eval`：评估相关工具

### 1.3 前端依赖安装

```bash
cd src/uae_law_rag/frontend
pnpm install
```

---

## 2. Docker 依赖（Milvus + Attu）

项目内置 Milvus Compose：

```bash
cd infra/milvus
docker compose up -d
```

验证：

```bash
docker ps | grep milvus
nc -vz 127.0.0.1 19530
```

Attu UI（可选）：

- http://localhost:8000
- 连接地址：`host.docker.internal:19530`（非容器内时）

---

## 3. System Config（重点）

本系统存在多层配置来源，需要明确 **注入方式与优先级**。

### 3.1 配置优先级（Chat 相关）

Chat 服务的关键配置读取顺序（`chat_service._resolve_value`）：

1) **Request context**（`POST /api/chat` 的 `context` 字段）  
2) **KB 配置**（数据库表 `knowledge_base`）  
3) **Conversation settings**（`conversation.settings`）  
4) **默认值**（代码内默认）

### 3.2 `.env`（项目根目录）

`src/uae_law_rag/config.py` 会读取 **项目根目录** 下的 `.env`（仅作用于 Settings）：

关键字段（部分）：

- `LOCAL_MODELS`：是否默认使用本地模型（影响 LLM 默认 provider）
- `DEBUG`
- `PROJECT_ROOT`
- `UAE_LAW_RAG_DATABASE_URL`
- `UAE_LAW_RAG_DATA_RAW_PATH`
- `UAE_LAW_RAG_DATA_PARSED_PATH`
- `UAE_LAW_RAG_SAMPLE_PDF`
- `OPENAI_API_KEY`, `OPENAI_API_BASE`
- `DASHSCOPE_API_KEY`, `DASHSCOPE_BASE_URL`
- `QWEN_CHAT_MODEL`, `QWEN_MULTI_MODEL`, `QWEN_EMBED_MODEL`
- `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_CHAT_MODEL`, `DEEPSEEK_REASONER_MODEL`
- `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL`, `OLLAMA_REQUEST_TIMEOUT_S`
- `DEVICE`

注意：

- Settings 只会读取 **自己定义的字段**。  
- **Milvus/Debug 等环境变量不会自动从 `.env` 注入到 `os.environ`**。需要显式 `export`。

### 3.3 运行时环境变量（进程级）

以下变量通过 `os.getenv` 读取，必须在启动前显式 `export`：

- Milvus 连接：
  - `MILVUS_URI`（推荐，例如 `http://127.0.0.1:19530`）
  - 或 `MILVUS_HOST` + `MILVUS_PORT`
- DB 连接：
  - `UAE_LAW_RAG_DATABASE_URL` 或 `DATABASE_URL`
- 第三方模型 Key（remote provider）：
  - `OPENAI_API_KEY`
  - `DASHSCOPE_API_KEY`
  - `DEEPSEEK_API_KEY`
- 调试：
  - `UAE_LAW_RAG_DEBUG_DB=1`（打印 PRAGMA database_list）
  - `UAE_LAW_RAG_DEBUG_TRACEBACK=1`（500 错误时打印 traceback）
  - `SQL_ECHO=1`（SQLAlchemy echo）
- 数据目录：
  - `UAE_LAW_RAG_DATA_DIR`（覆盖 `.data` 根目录）

示例（本地 Milvus + SQLite）：

```bash
export MILVUS_URI="http://127.0.0.1:19530"
export UAE_LAW_RAG_DATABASE_URL="sqlite+aiosqlite:////absolute/path/to/.Local/uae_law_rag.db"
```

### 3.4 前端 Vite 配置

前端只读取 `src/uae_law_rag/frontend` 目录下 `.env.*`：

- `VITE_API_BASE`（默认 `/api`）
- `VITE_BACKEND_TARGET`（Vite proxy 目标，默认 `http://127.0.0.1:18000`）
- `VITE_SERVICE_MODE`（默认 `live`）

### 3.5 Provider / 模型切换方式

#### 3.5.1 Embedding Provider（检索向量）

来源：`knowledge_base` 表字段

- `embed_provider`
- `embed_model`
- `embed_dim`

默认 KB（`init_db --seed`）：

- `embed_provider=local`（本地 hash embedding）
- `embed_model=bge-small`
- `embed_dim=384`

切换示例（SQLite）：

```bash
sqlite3 .Local/uae_law_rag.db <<'SQL'
update knowledge_base
set embed_provider='ollama',
    embed_model='YOUR_EMBED_MODEL',
    embed_dim=YOUR_EMBED_DIM
where id='default';
SQL
```

Embedding provider allowlist（服务端硬编码）：

```
hash | local | mock | ollama | openai
```

#### 3.5.2 LLM Provider（生成模型）

默认值：

- `LOCAL_MODELS=true` → `model_provider=ollama`，`model_name=OLLAMA_CHAT_MODEL`
- `LOCAL_MODELS=false` → `model_provider=dashscope`，`model_name=qwen3-max`

可在 `POST /api/chat` 的 `context` 中覆盖：

```bash
curl -sS -X POST http://127.0.0.1:18000/api/chat \
  -H 'Content-Type: application/json' \
  -H 'x-user-id: dev-user' \
  --data-binary @- <<'JSON' | python -m json.tool
{
  "query": "Explain rental rules",
  "kb_id": "default",
  "context": {
    "model_provider": "ollama",
    "model_name": "qwen2.5:1.5b",
    "generation_config": {
      "temperature": 0.2,
      "top_p": 0.9
    }
  },
  "debug": true
}
JSON
```

LLM provider allowlist（服务端硬编码）：

```
ollama | openai | dashscope | qwen | huggingface | hf | deepseek
openai_like | openai-like | mock | local | hash
```

本地模型说明：

- `ollama` 依赖本机 Ollama 服务（默认端口 11434）
- `local/hash/mock` 为本地确定性输出，仅用于离线/测试

#### 3.5.3 可覆盖的 Chat Context 字段（HTTP）

`ChatRequest.context` 支持（见 `schemas_http/chat.py`）：

- 检索：`keyword_top_k`, `vector_top_k`, `fusion_top_k`, `rerank_top_k`
- 策略：`fusion_strategy`, `rerank_strategy`
- Embed：`embed_provider`, `embed_model`, `embed_dim`
- LLM：`model_provider`, `model_name`
- Prompt：`prompt_name`, `prompt_version`
- Evaluator：`evaluator_config`

额外支持（`extra="allow"`），如：

- `temperature`, `generation_config`, `prompt_config`, `postprocess_config`
- `output_fields`, `metric_type`, `file_id`, `document_id`
- `no_evidence_use_llm`

特殊说明：

- `vector_top_k=0` 会禁用向量检索（仅关键词检索）

#### 3.5.4 Ingest 配置快照（KB / Request）

- KB 侧：`knowledge_base.chunking_config`
  - 常用字段：`window_size`, `window_metadata_key`, `original_text_metadata_key`
- Request 侧：`IngestRequest.ingest_profile`
  - `parser`（仅支持 `pymupdf4llm`）
  - `parse_version`
  - `segment_version`

---

## 4. 初始化系统（DB + Milvus）

### 4.1 初始化 SQLite（含默认 KB + FTS）

默认 DB 位置：`.Local/uae_law_rag.db`（可通过 `UAE_LAW_RAG_DATABASE_URL` 覆盖）

```bash
PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_db --drop --seed --seed-fts
```

校验：

```bash
sqlite3 .Local/uae_law_rag.db "select kb_name, milvus_collection, embed_dim from knowledge_base;"
```

### 4.2 初始化 Milvus Collection

```bash
PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_milvus \
  --collection kb_default \
  --embed-dim 384 \
  --metric-type COSINE \
  --drop
```

> `embed_dim` 必须与 KB 配置一致。

---

## 5. 启动后端与前端

### 5.1 启动后端（FastAPI）

```bash
PYTHONPATH=src uvicorn uae_law_rag.backend.main:app --host 127.0.0.1 --port 18000 --reload
```

健康检查：

```bash
curl -sS http://127.0.0.1:18000/api/health | python -m json.tool
```

### 5.2 启动前端（Vite）

```bash
cd src/uae_law_rag/frontend
pnpm dev
```

访问：http://localhost:5173/

---

## 6. Ingest Pipeline（导入）

说明：

- 当前 parser 仅支持 `pymupdf4llm`（需安装 `pymupdf` + `pymupdf4llm`，已包含在 `parsing` extra 中）
- `source_uri` 必须是后端可访问的 **绝对路径**

### 6.1 Dry Run

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

### 6.2 真正写入

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

### 6.3 DB 校验

```bash
sqlite3 .Local/uae_law_rag.db "select count(*) from node;"
sqlite3 .Local/uae_law_rag.db "select count(*) from node_vector_map;"
```

---

## 7. Chat Pipeline（检索 → 生成 → 评估）

```bash
curl -sS -X POST http://127.0.0.1:18000/api/chat \
  -H 'Content-Type: application/json' \
  -H 'x-user-id: dev-user' \
  --data-binary @- <<'JSON' | python -m json.tool
{
  "query": "YOUR QUERY",
  "kb_id": "default",
  "debug": true
}
JSON
```

预期：

- `status` 为 `success/partial/blocked`
- `citations` 有值（blocked 可能为 0）
- `debug` 中包含 `retrieval_record_id / generation_record_id / evaluation_record_id`

---

## 8. Records 回放

```bash
curl -sS http://127.0.0.1:18000/api/records/retrieval/<RETRIEVAL_RECORD_ID> | python -m json.tool
curl -sS http://127.0.0.1:18000/api/records/generation/<GENERATION_RECORD_ID> | python -m json.tool
curl -sS http://127.0.0.1:18000/api/records/evaluation/<EVALUATION_RECORD_ID> | python -m json.tool
```

---

## 9. 重置数据库（全链路）

```bash
# reset db
PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_db --drop --seed --rebuild-fts

# reset milvus
PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_milvus \
  --collection kb_default --embed-dim 384 --metric-type COSINE --drop
```

如需清空 Milvus Docker volumes：

```bash
cd infra/milvus
docker compose down -v
```

---

## 10. 测试与 Gate

### 10.1 Backend Pytest

```bash
PYTHONPATH=src pytest
```

### 10.2 Frontend PNPM

```bash
cd src/uae_law_rag/frontend
pnpm lint
pnpm typecheck
pnpm test
```

---

## 11. Pytest Record

未运行（未要求）。

---

## 12. PNPM Record

未运行（未要求）。

---

## 13. Docker 部署（整体打包）

当前仓库未提供完整 Dockerfile。以下为 **推荐最小化方案**（需自行创建文件）。

### 13.1 Backend Dockerfile（建议：`infra/docker/Dockerfile.backend`）

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml uv.lock /app/
COPY src /app/src
RUN pip install --no-cache-dir -e ".[backend,db,llamaindex-basic,parsing]"
ENV PYTHONPATH=/app/src
EXPOSE 18000
CMD ["uvicorn", "uae_law_rag.backend.main:app", "--host", "0.0.0.0", "--port", "18000"]
```

### 13.2 Frontend Dockerfile（建议：`infra/docker/Dockerfile.frontend`）

```dockerfile
FROM node:20-slim

WORKDIR /app
COPY src/uae_law_rag/frontend/package.json /app/
COPY src/uae_law_rag/frontend/pnpm-lock.yaml /app/
RUN corepack enable && pnpm install

COPY src/uae_law_rag/frontend /app
ENV VITE_BACKEND_TARGET=http://backend:18000
RUN pnpm build

EXPOSE 5173
CMD ["pnpm", "preview", "--host", "0.0.0.0", "--port", "5173"]
```

### 13.3 全量 Compose（建议：`infra/docker/docker-compose.full.yml`）

```yaml
name: uae-law-rag-full

services:
  milvus:
    extends:
      file: ../milvus/docker-compose.yml
      service: milvus

  etcd:
    extends:
      file: ../milvus/docker-compose.yml
      service: etcd

  minio:
    extends:
      file: ../milvus/docker-compose.yml
      service: minio

  attu:
    extends:
      file: ../milvus/docker-compose.yml
      service: attu

  backend:
    build:
      context: ../..
      dockerfile: infra/docker/Dockerfile.backend
    environment:
      - MILVUS_URI=http://milvus:19530
      - UAE_LAW_RAG_DATABASE_URL=sqlite+aiosqlite:////app/.Local/uae_law_rag.db
    volumes:
      - ../../.Local:/app/.Local
      - ../../.data:/app/.data
    ports:
      - "18000:18000"
    depends_on:
      milvus:
        condition: service_healthy

  frontend:
    build:
      context: ../..
      dockerfile: infra/docker/Dockerfile.frontend
    ports:
      - "5173:5173"
    depends_on:
      - backend
```

> 如果你的 Docker Compose 版本不支持 `extends`，请将 `infra/milvus/docker-compose.yml` 中的相关服务复制到该文件内。

### 13.4 Docker 启动步骤（给其他开发者）

```bash
git clone <your-repo>
cd uae_law_rag

# 1) 创建 Dockerfile/compose（按本节模板）
# 2) 启动全量服务
docker compose -f infra/docker/docker-compose.full.yml up -d

# 3) 初始化 DB + Milvus
docker compose -f infra/docker/docker-compose.full.yml exec backend \
  bash -lc "PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_db --drop --seed --seed-fts"

docker compose -f infra/docker/docker-compose.full.yml exec backend \
  bash -lc "PYTHONPATH=src python -m uae_law_rag.backend.scripts.init_milvus --collection kb_default --embed-dim 384 --metric-type COSINE --drop"

# 4) 访问
# frontend: http://localhost:5173/
# backend:  http://localhost:18000/api/health
```

> Docker 环境中 ingest 的 `source_uri` 必须是容器可访问的路径（例如挂载到 `/app/.data/raw`）。
