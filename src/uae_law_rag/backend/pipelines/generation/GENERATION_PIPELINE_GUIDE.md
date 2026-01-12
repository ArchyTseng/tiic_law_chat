# GENERATION_PIPELINE_GUIDE.md

> 本文是 **PIPELINES_DEVELOP_GUIDE.md** 的 *Generation Pipeline 专项实施指南*，用于约束和指导 **Evidence → Prompt → LLM → Postprocess → 可审计生成记录** 的全链路实现。
>
> Generation 不是“写答案”，而是：**在严格证据约束下，生成可解释、可回放、可评估的法律回答**。

---

## 0. Generation Pipeline 的总体目标（不可妥协）

Generation Pipeline 必须同时满足以下目标：

1. **Evidence-Grounded（证据强约束）**

   * 所有回答内容必须可追溯到 retrieval hits
   * 不允许“无证据自由发挥”

2. **Reproducible（可回放）**

   * 同一 GenerationRecord + RetrievalRecord + Prompt 组合，理论上应可重现输出
   * messages_snapshot / provider_snapshot 必须完整保存

3. **Structured-First（结构化优先）**

   * 优先引导模型输出结构化 JSON
   * raw output 只是兜底与调试材料

4. **Evaluator-Ready（评估友好）**

   * 输出必须稳定、可解析、字段可预测
   * citations 必须与 RetrievalHit / NodeModel 对齐

---

## 1. Pipeline 目录结构与分层职责

```
src/uae_law_rag/backend/pipelines/generation
├── __init__.py
├── prompt.py        # Prompt 模板与渲染（强约束证据输入）
├── generator.py     # LLM 调用（LlamaIndex 抽象）
├── postprocess.py  # 输出解析 / citation 对齐 / JSON 校验
├── persist.py      # DB 落库（GenerationRecord）
└── pipeline.py     # 编排（ctx/timing/provider_snapshot/失败策略）
```

**强制规则**：

* prompt ≠ generator ≠ postprocess
* persist 不做任何业务判断
* pipeline 不写 prompt 细节、不解析输出

---

## 2. 核心数据合同（Schema / DB / Pipeline 对齐）

### 2.1 DB 与 Schema 的事实来源

**GenerationRecordModel（事实）**：

* message_id (1-1)
* retrieval_record_id
* prompt_name / prompt_version
* model_provider / model_name
* messages_snapshot
* output_raw / output_structured
* citations (JSON)
* status / error_message

**Schema.GenerationRecord（合同）**：

* 必须 100% 覆盖以上字段
* 不得引入 DB 不存在字段

---

## 3. Prompt 层（prompt.py）设计指南

### 3.1 Prompt 的角色定位

Prompt 的目标不是“写得像人”，而是：

> **把 retrieval hits 转换为“模型不可忽略的证据输入约束”。**

### 3.2 Prompt 必须包含的要素（强制）

1. **System 指令**

   * 明确法律角色（UAE Law Assistant）
   * 明确证据约束（只能基于给定材料回答）

2. **Evidence Context（结构化）**

   * 每个证据必须带：

     * node_id
     * page / article / section
     * excerpt

3. **Query 明确注入**

### 3.3 推荐 Prompt 组织方式

```text
SYSTEM:
  Role + Constraints

EVIDENCE:
  [1] (node_id=..., page=..., article=...)
      "excerpt..."
  [2] ...

QUESTION:
  {{user_query}}

OUTPUT FORMAT (JSON):
  {
    "answer": string,
    "citations": [{"node_id": "...", "rank": 1}]
  }
```

### 3.4 prompt.py 对外接口（建议）

```python
def build_messages(
    *,
    query: str,
    hits: list[Candidate],
    prompt_name: str,
    prompt_version: str | None,
) -> dict  # messages_snapshot
```

---

## 4. Generator 层（generator.py）设计指南

### 4.1 设计立场（强制）

> **所有 LLM 调用必须通过 LlamaIndex 抽象。**

禁止：

* 直接调用 openai / ollama client

### 4.2 推荐使用的 LlamaIndex 抽象

* `LLM` / `ChatLLM`
* `Response` / `StructuredResponse`
* `OutputParser`（JSON schema 驱动）

### 4.3 Generator 的职责边界

* 输入：messages_snapshot

* 输出：

  ```python
  GenerationRawResult = {
      "raw_text": str,
      "provider": str,
      "model": str,
      "usage": dict | None,
  }
  ```

* ❌ 不解析 citations

* ❌ 不校验 JSON

### 4.4 generator.py 对外接口（建议）

```python
async def run_generation(
    *,
    messages_snapshot: dict,
    model_provider: str,
    model_name: str,
    generation_config: dict,
) -> GenerationRawResult
```

---

## 5. Postprocess 层（postprocess.py）设计指南

### 5.1 Postprocess 的关键职责

> **把 LLM 输出变成系统可用、可评估、可落库的事实数据。**

### 5.2 必须完成的步骤

1. JSON 解析（严格）
2. schema 校验（answer / citations）
3. citation 对齐：

   * citation.node_id 必须存在于 retrieval hits
4. citation rank / locator 补全

### 5.3 输出数据合同

```python
PostprocessResult = {
    "answer": str,
    "citations": list[Citation],
    "output_structured": dict,
    "status": "success" | "partial" | "failed",
    "error_message": str | None,
}
```

---

## 6. persist.py（落库）设计指南

### 6.1 落库原则

* DB 是最终真相源
* GenerationRecord 必须完整
* 不因 evaluator 失败而回滚 generation

### 6.2 persist.py 对外接口（建议）

```python
async def persist_generation(
    *,
    generation_repo: GenerationRepo,
    record_params: dict,
) -> str  # generation_record_id
```

persist 负责：

* 写入 GenerationRecordModel
* 保证 message_id 的 1-1 约束

---

## 7. pipeline.py（编排）设计指南

### 7.1 pipeline.py 必须承担的责任

* ctx 注入（trace_id / request_id）
* timing（prompt / llm / postprocess / total）
* provider_snapshot 聚合
* 错误策略：

  * JSON 解析失败 → partial
  * citation 缺失 → fail or partial（配置驱动）

### 7.2 公开入口（建议）

```python
async def run_generation_pipeline(
    *,
    message_id: str,
    retrieval_bundle: RetrievalBundle,
    generation_repo: GenerationRepo,
    config: dict,
    ctx: PipelineContext,
) -> GenerationBundle
```

---

## 8. Gate Test 设计指南（playground/generation_gate/test_generation_gate.py）

### 8.1 必须断言（最低可信门槛）

1. generation_record 已创建
2. output_raw 非空
3. status ∈ {success, partial, failed}
4. citations.node_id ⊆ retrieval hits

### 8.2 强烈建议的增强断言

* output_structured JSON 可解析
* citations 数量 > 0（对法律 QA）
* provider_snapshot 含 model/provider
* timing_ms 含 llm / postprocess / total

---

## 9. 体验视角验收（产品级）

Generation 输出必须支持：

* UI 高亮引用（node → page/article）
* 用户可展开查看证据上下文
* 审计人员可回放 prompt + evidence + 输出

---

## 10. 关键补充（必须考虑）

### 10.1 拒答与兜底

* 若 retrieval hits 为空：

  * generation 不应直接 hallucinate
  * 应返回明确的 no_evidence 响应

### 10.2 多模型 / 多 provider

* prompt / postprocess 不得绑定具体模型
* provider 差异只存在于 generator 层

---

> **Generation Pipeline 的使命不是“回答问题”，而是“在证据约束下生成可信结论”。**
