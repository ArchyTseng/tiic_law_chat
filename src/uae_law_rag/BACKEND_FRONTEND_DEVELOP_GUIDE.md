# BACKEND_FRONTEND_DEVELOP_GUIDE.md

> 本文在体系层级上高于 services/api/frontend 的具体实现，是 **PIPELINES_DEVELOP_GUIDE.md** 与四大 pipeline guide 的 *工程落地桥梁*。
>
> 目标：把已冻结的 **schemas/db/kb/pipelines** 作为“事实地盘（ground truth）”，给出 **Backend API + Services + Frontend** 的一致化开发指南，使后续实现顺滑、可控、可审计、可迭代。

---

## 0. 总体目标（产品级）

系统的最终交付不是“能问答”，而是：

> 用户输入任意问题，系统能给出 **可信回答 + 可解释证据链 + 可回放记录**，并在不可信时 **明确拒答或降级**。

Backend/Frontend 的使命是把这一可信链路“可用化”，并让用户在体验上感知到可信：

* 能看到命中清单与原文片段
* 能看到引用定位（page/article/section）
* 能看到 retrieval/generation/evaluator 的记录与状态
* 能理解系统拒答/警告的原因

---

## 1. 冻结边界与分层原则（强制）

### 1.1 已冻结的事实地盘（不可改动的中心）

以下模块被视为“平台地基”，**后续开发只能依赖、不能绕开**：

* `backend/schemas/*`（内部合同）
* `backend/db/*`（SQL 事实）
* `backend/kb/*`（Milvus 事实）
* `backend/pipelines/*`（业务闭环与 gate 约束）

任何 API/Service/Frontend 需求如果与这些事实冲突：

* 优先调整 API/Service/Frontend
* 不允许为了 UI 便利而破坏审计与证据链

### 1.2 Backend 的三层结构（强制）

```
routers (HTTP)  →  纯输入输出映射，不写业务逻辑
services        →  业务编排：调用 pipelines + repos + 事务控制
pipelines       →  领域闭环：ingest/retrieval/generation/evaluator（已冻结）
```

### 1.3 前端与后端的契约分裂（强制）

* `backend/schemas/*`：内部 pipeline 合同（严禁漂移）
* `backend/api/schemas_http/*`：HTTP 输入输出合同（允许演进，但必须映射到内部合同）

---

## 2. Backend 模块设计指南

### 2.1 api/deps.py（依赖注入）

职责：

* 注入 AsyncSession
* 注入 repos（IngestRepo/RetrievalRepo/GenerationRepo/EvaluatorRepo）
* 注入 kb client/repo（MilvusClient/MilvusRepo）
* 注入 pipeline context（trace_id/request_id）

边界：

* deps 只负责“创建依赖”，不做业务逻辑

建议公开依赖：

* `get_session()`
* `get_repos()`（可拆为多个）
* `get_milvus_repo()`
* `get_trace_context()`

### 2.2 api/routers/*（路由层）

路由层必须遵守：

* 不做任何数据处理（例如 chunk/embedding/检索）
* 不直接操作 db.session
* 只调用 service

#### 2.2.1 routers/ingest.py

Endpoints（建议稳定）：

* `POST /ingest`：触发 ingest pipeline
* `GET /ingest/{file_id}`：查看导入状态（ingest_status/node_count）

输入（schemas_http/ingest.py）：

* kb_id
* source_uri / upload reference（未来）
* file_name
* ingest_profile（parser/splitter/embed）

输出：

* file_id
* ingest_status
* node_count
* timings

#### 2.2.2 routers/chat.py

Endpoints（建议稳定）：

* `POST /chat`：主链路（message → retrieval → generation → evaluator）
* `GET /chat/{conversation_id}`：拉取对话消息（含 status / evidence）

输入：

* conversation_id（可选：无则新建）
* query
* chat_type
* context overrides（top_k/rerank/prompt）

输出：

* conversation_id
* message_id
* kb_id
* answer
* citations（可选：完整 locator）
* debug（可选：retrieval_record_id/generation_record_id/evaluation_record_id）

#### 2.2.3 routers/admin.py

MVP 仅保留：

* 列出 KB / files / docs
* 触发重建/删除（受限权限）

#### 2.2.4 routers/health.py

* `GET /health`：

  * db ok
  * milvus ok（可选）

### 2.3 services/*（业务编排层）

services 是“将 pipelines 产品化”的唯一入口。

#### 2.3.1 ingest_service.py

职责：

* 校验 kb_id
* 文件幂等：sha256 判重（已有 repo 支持）
* 调用 ingest pipeline
* 更新 knowledge_file.ingest_status

输出必须包含：

* file_id
* status
* node_count
* timing
* trace_id

#### 2.3.2 chat_service.py

职责（核心）：

1. conversation/message 创建与状态管理
2. 调用 retrieval pipeline（落库 RetrievalRecord + Hits）
3. 调用 generation pipeline（落库 GenerationRecord）
4. 调用 evaluator pipeline（落库 EvaluationRecord）
5. 根据 evaluator status 决定：

   * 返回 answer
   * 返回 answer + warning
   * 返回拒答
6. 写回 message.response 与 message.status

强制：

* message.status 是单一事实源
* retrieval/generation/evaluator 记录 id 必须回传到 debug

---

## 3. HTTP Schemas 设计指南（schemas_http）

### 3.1 schemas_http 的职责

* 适配 UI 需要（更简洁、更友好）
* 不暴露内部 schema 的全部字段
* 但必须可映射到内部 schema

### 3.2 Debug 模式（强烈建议）

`POST /chat` 支持 query param：`debug=true`

当 debug=true 时，响应中额外包含：

* retrieval_record_id
* generation_record_id
* evaluation_record_id
* hits summary（top 10）

这对“建立信任”至关重要。

---

## 4. 错误处理与状态机（Backend）

### 4.1 错误分类（utils/errors.py）

建议定义：

* `BadRequestError`
* `NotFoundError`
* `PipelineError`
* `ExternalDependencyError`（Milvus/LLM）

### 4.2 状态机统一

* ingest_status：pending/success/failed
* message.status：pending/success/failed/blocked
* generation.status：success/partial/failed
* evaluation.status：pass/partial/fail/skipped

**任何状态变化必须可在 DB 中观察**。

---

## 5. Logging / Observability 指南

### 5.1 统一 Trace Context

所有 request 必须：

* trace_id
* request_id

写入：

* logs
* retrieval_record.provider_snapshot/timing
* generation_record.messages_snapshot/provider
* evaluation_record.meta

### 5.2 logging_.py 的要求

* 结构化日志（JSON）
* 每条关键日志都包含 trace_id

---

## 6. Frontend 设计指南（以“可信体验”为核心）

前端目录当前为空，因此这里给出必须实现的最低信息架构与页面结构。

### 6.1 最低信息架构（IA）

1. **Chat 页面（核心）**
2. **Ingest 页面（管理）**
3. **Records 页面（调试/审计，可选但强烈建议）**

### 6.2 Chat 页面必须包含的体验能力

* 输入框 + 发送
* 消息列表（user/assistant）
* 每条 assistant 消息：

  * answer
  * status badge（pass/partial/fail）
  * citations（可展开）

#### Citations 展示要求（强制）

* 显示 node_id 的短形式
* 显示 page/article/section
* 点击可展开：

  * excerpt
  * 原文上下文（可再请求 node.text）

### 6.3 命中清单（Retrieval Debug）

当 debug=true 或开启“开发者模式”时：

* 展示 Top-K hits

  * rank
  * score
  * source
  * page/article
  * excerpt

这将极大增强用户信任。

### 6.4 Ingest 页面

* 选择 KB
* 上传/选择文件（MVP 可以用 file path / uri）
* 查看 ingest_status
* 查看 node_count

---

## 7. 后端-前端契约建议（最少返工）

### 7.1 API Response 的稳定字段

ChatResponse（建议）：

```json
{
  "conversation_id": "...",
  "message_id": "...",
  "kb_id": "...",
  "answer": "...",
  "status": "success|blocked|failed",
  "evaluator": {
    "status": "pass|partial|fail|skipped",
    "rule_version": "v0",
    "warnings": []
  },
  "citations": [
    {"node_id": "...", "page": 2, "article_id": "Article 2", "section_path": "Chapter 1", "quote": "..."}
  ],
  "debug": {
    "retrieval_record_id": "...",
    "generation_record_id": "...",
    "evaluation_record_id": "..."
  }
}
```

IngestResponse（建议）：

```json
{
  "kb_id": "...",
  "file_id": "...",
  "ingest_status": "pending|success|failed",
  "node_count": 123,
  "timing_ms": {"parse": 10, "segment": 20, "embed": 100, "milvus": 50, "db": 30}
}
```

---

## 8. 与 PIPELINES Gate 的协作方式

### 8.1 后端必须尊重 Gate 裁决

* ingest_gate 失败 → ingest_service 返回 failed，并阻止 retrieval
* retrieval_gate 失败 → chat_service 返回 blocked（no_evidence）
* generation_gate 失败 → evaluator 仍执行，最终 status fail
* evaluator_gate 失败 → 必须拒绝返回 answer

### 8.2 前端必须展示裁决原因

* pass：正常展示
* partial：展示警告（例如“证据不足，谨慎使用”）
* fail：展示拒答文案 + 建议用户改写 query

---

## 9. 开发顺序建议（最小返工、最大可控）

1. 完成 pipelines + gate 全绿（已规划）
2. 实现 services：ingest_service / chat_service
3. 实现 routers：/ingest /chat /health
4. 再实现 frontend：

   * Chat 页面（含 debug 模式）
   * Ingest 页面

---

## 10. 关键补充（未显式要求但必须纳入）

### 10.1 安全与越权

* API 层必须预留：

  * user_id 认证
  * kb 权限校验

### 10.2 配置与版本

* prompt_version / rule_version 必须对外可见（debug 模式）
* 未来可用于回归对比

---

> **Backend/Frontend 的价值，是把 pipeline 的可信性“变成用户能感知的体验”。**
>
> 如果用户看不到证据链、状态与解释，
> 即使后端做到了审计与门禁，用户也不会信任系统。
