# PIPELINES_DEVELOP_GUIDE

## 0. 写在前面（本文件的定位）

本指南不是“如何把 pipeline 跑起来”的说明文档，而是 **Tiic‑RAG / UAE Law RAG 在 Pipeline 层的最高设计准则与工程执行规范**。

目标受众只有两类：

1. **系统的长期维护者与扩展者（包括未来的你）**
2. **对检索质量、证据可追溯性、审计可信度有极高要求的 AI 系统工程师**

如果某个实现方案“可以跑，但削弱了证据链、可复现性或检索质量”，**该方案在本项目中视为不可接受**。

---

## 1. 总体目标与硬性要求（Non‑Negotiable Goals）

### 1.1 总体目标

Pipeline 层的唯一目标是：

> **为用户提供一次即可建立信任的问答体验** —— 每一个回答都能被解释、被回放、被审计、被质疑。

这意味着：

* 检索不是“命中即可”，而是**高召回 + 可解释排序**
* 生成不是“语言流畅即可”，而是**证据充分 + 引用可靠**
* 评估不是“跑个分数”，而是**可定位失败原因 + 可回放上下文**

### 1.2 Pipeline 层的硬性工程要求

**任何 Pipeline 实现都必须满足以下 8 条硬要求：**

1. **Contract‑First**：所有输入/输出必须由 `schemas/*` 明确定义
2. **DB‑First**：任何中间结果，必须能稳定映射到 DB schema（或明确说明为何不落库）
3. **Evidence‑First**：任何生成输出，必须可回指到 node 级证据
4. **Recall‑First**：检索阶段优先保证召回率，再谈精排
5. **Reproducible**：相同 KB + 相同配置 + 相同 query → 行为可解释、可近似回放
6. **Observable**：每个 pipeline 必须输出 timing / provider_snapshot / trace
7. **Composable**：pipeline 内部组件可替换，但 contract 不可漂移
8. **Gate‑Driven**：每一个 pipeline 必须有对应 gate test 锁死行为边界

---

## 2. 核心检索诉求的实现路径（关键词 + 向量 + Fusion + Rerank）

### 2.1 为什么这是不可拆分的整体

在法律场景中：

* **关键词检索** → 保证 *全量召回*（Recall）
* **向量检索** → 保证 *语义相关性*（Semantic Recall）
* **Fusion** → 防止任一检索方式的系统性偏差
* **Rerank** → 在高召回前提下，提升 Top‑K 的精度与可读性

任何只实现其中一部分的系统，在真实法律查询中都会 **系统性失败**。

### 2.2 目标检索行为（产品视角）

| 用户输入      | 系统必须做到               |
| ------------- | -------------------------- |
| 精确关键词    | 返回所有相关条文，顺序合理 |
| 模糊/拼写错误 | 仍能命中语义相关条文       |
| 停用词/弱查询 | 返回合理 fallback 或拒答   |
| 恶意/越权     | 明确拒绝并可审计           |

---

## 3. LlamaIndex 的使用原则（深度绑定但不被绑死）

### 3.1 核心原则

> **LlamaIndex 是算法与语义执行层，不是事实存储层**。

* **事实（Facts）**：SQL / Milvus
* **算法（How to retrieve / rank）**：LlamaIndex
* **审计（Why this answer）**：你自己的 schemas + DB

### 3.2 LlamaIndex 在各阶段的职责边界

| 阶段          | 是否必须使用 LlamaIndex | 原因                           |
| ------------- | ----------------------- | ------------------------------ |
| PDF Parse     | ❌（仅用 pymupdf4llm）   | LlamaIndex 不负责版面还原      |
| Chunk / Split | ✅                       | 结构化切分是质量核心           |
| Embedding     | ✅                       | provider/batch/一致性          |
| Retrieval     | ✅                       | 内置 Keyword / Vector / Fusion |
| Rerank        | ✅                       | Cross‑Encoder / LLM Rerank     |
| Generation    | ⚠️（部分）               | Prompt/Response 仍由你控制     |
| Evaluator     | ⚠️（辅助）               | 指标可用，结论由你定义         |

### 3.3 推荐深度使用的 LlamaIndex 内置组件（非穷举）

#### 文档与节点

* `Document`
* `TextNode`
* `NodeWithScore`

#### Splitter / Parser（法律文本强烈推荐）

* `MarkdownElementNodeParser`
* `SentenceWindowNodeParser`
* `HierarchicalNodeParser`

#### Retrieval

* `KeywordTableSimpleRetriever`
* `BM25Retriever`
* `VectorIndexRetriever`
* `QueryFusionRetriever`
* `RecursiveRetriever`

#### Rerank

* `SentenceTransformerRerank`
* `LLMRerank`
* 自定义 Cross‑Encoder Rerank

---

## 4. Schemas / DB 与 LlamaIndex 的数据管道打通原则

### 4.1 单一事实源（Single Source of Truth）

| 数据类型  | 权威来源               |
| --------- | ---------------------- |
| 文本证据  | SQL NodeModel          |
| 向量      | Milvus + NodeVectorMap |
| 排名/分数 | RetrievalHitModel      |
| 生成输出  | GenerationRecordModel  |

LlamaIndex 的 `NodeWithScore` **必须可逆映射** 回：

* `node_id`
* `page / offsets / article_id / section_path`

### 4.2 Mapping / Merging / 透传规则

* **Mapping**：LlamaIndex Node → DB node_id
* **Merging**：keyword/vector/fusion/rerank 的 score 合并写入 `score_details`
* **透传**：LlamaIndex metadata → DB `meta_data`（不可丢失）

任何 metadata 在 pipeline 中被“吞掉”，都视为严重缺陷。

---

## 5. 各 Pipeline 的详细设计指南

### 5.1 Ingest Pipeline

**目标**：生成 *高质量、可追溯、可多策略检索* 的 Node 与向量。

必须产出：

* 结构化 Markdown（还原顺序）
* 多粒度 Node（primary / window）
* 完整 metadata（article / section / page / offsets）

关键组件：

* `pdf_parse.py`：pymupdf4llm → Markdown + 页映射
* `segment.py`：LlamaIndex splitter
* `embed.py`：LlamaIndex BaseEmbedding
* `persist_db.py / persist_milvus.py`

### 5.2 Retrieval Pipeline

**目标**：在 Recall 最大化前提下，构建可解释排序。

步骤：

1. Keyword 全量召回（FTS / LlamaIndex Keyword Retriever）
2. Vector 语义召回（Milvus / VectorIndexRetriever）
3. Fusion（Union / RRF / Weighted）
4. Rerank（Cross‑Encoder / LLM）

所有阶段必须落库为 `RetrievalRecord + RetrievalHit`。

### 5.3 Generation Pipeline

**目标**：在严格证据约束下生成回答。

要求：

* 上下文只来自 RetrievalHit
* 引用必须可回查
* output_structured 与 citations 一致

### 5.4 Evaluator Pipeline

**目标**：判断“这次回答是否可信”。

评估维度示例：

* citation_coverage
* min_answer_length
* unsupported_claims

Evaluator **不是打分机器，而是审计工具**。

---

## 6. Gate Tests 设计指南（*_gate.py）

### 6.1 Gate 的哲学

Gate Test 不是单元测试，而是：

> **系统行为的宪法级约束**

### 6.2 各 Gate 的最低要求

| Gate            | 锁死内容            |
| --------------- | ------------------- |
| schema_gate     | 字段 / extra 策略   |
| sql_gate        | 外键 / 1‑1 关系     |
| ingest_gate     | 结构产物 + 可观测性 |
| retrieval_gate  | 召回存在性 + 落库   |
| generation_gate | 引用一致性          |
| evaluator_gate  | 规则行为            |

Gate 中 **宁可断言少，也不要断言错**，但断言的一定是系统不可退让的底线。

---

## 7. 额外但关键的设计补充

### 7.1 拒答是能力，不是失败

* 没有证据 → 必须拒答
* evaluator fail → 必须拒答
* 拒答本身必须可审计

### 7.2 Pipeline ≠ LlamaIndex Workflow

你构建的是 **平台级 RAG 系统**，不是 demo。

* LlamaIndex 是工具箱
* Pipeline 是你定义的法律级流程

---

## 8. 最终原则（必须牢记）

> **我们不是在“让模型回答问题”，而是在“构建一个值得信任的法律信息系统”。**

任何一步，如果牺牲了可信度、可解释性或可复现性，即使短期提升效果，也必须被否决。
