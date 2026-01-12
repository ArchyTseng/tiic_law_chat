# RETRIEVAL_PIPELINE_GUIDE.md

> 本文是 **PIPELINES_DEVELOP_GUIDE.md** 的 *Retrieval Pipeline 专项实施指南*，用于约束和指导 **Query →（Keyword Recall + Vector Recall）→ Fusion → Rerank → 可审计落库** 的全链路实现。
>
> Retrieval 是本系统可信度的第一道闸门：若检索召回、排序解释、落库审计做不好，Generation 与 Evaluator 都无法挽救系统的可信性。

---

## 0. Retrieval Pipeline 的总体目标（不可妥协）

Retrieval Pipeline 必须同时满足以下目标：

1. **Recall-First（高召回优先）**

   * 对法律文本：关键词检索必须尽可能接近“全量召回”
   * 向量检索必须覆盖语义相关但不共享关键词的证据

2. **Explainable Ranking（可解释排序）**

   * 每个命中必须能解释：来自 keyword/vector/fusion/rerank 哪个阶段
   * 每个命中必须有可追溯的 score 组成（score_details）

3. **Reproducible Audit（可回放审计）**

   * 必须落库：RetrievalRecord + RetrievalHit
   * 必须保存：策略快照、参数快照、provider_snapshot、timing_ms

4. **Downstream-Ready（为生成与评估准备）**

   * Top-K hits 必须能直接用于 prompt context 构建
   * 每条 hit 必须能回查 NodeModel 原文与定位信息

---

## 1. Pipeline 目录结构与分层职责

```
src/uae_law_rag/backend/pipelines/retrieval
├── __init__.py
├── keyword.py     # keyword recall（FTS/BM25/模糊匹配扩展）
├── vector.py      # vector recall（Milvus / LlamaIndex Vector Retriever）
├── fusion.py      # fusion（union/RRF/weighted + 去重 + 归一化）
├── rerank.py      # rerank（cross-encoder / LLM rerank）
├── persist.py     # DB 落库（RetrievalRecord + RetrievalHit）
└── pipeline.py    # 编排（ctx/timing/provider_snapshot/错误策略）
```

**强制规则**：

* keyword/vector/fusion/rerank 只做算法与数据处理
* persist 只做落库
* pipeline 只做编排与可观测性

---

## 2. 数据合同（Schemas/DB 与 Pipeline 内部对象）

### 2.1 DB 事实与 Schema 合同对齐

**RetrievalRecordModel（事实）** 字段：

* message_id, kb_id, query_text
* keyword_top_k, vector_top_k, fusion_top_k, rerank_top_k
* fusion_strategy, rerank_strategy
* provider_snapshot (dict)
* timing_ms (dict)

**RetrievalHitModel（事实）** 字段：

* retrieval_record_id
* node_id
* source
* rank
* score
* score_details
* excerpt
* page
* start_offset
* end_offset

**Schema（contract）必须完全覆盖 DB**：

* 不改 DB，schema 必须贴合（字段名/默认值语义）

### 2.2 Retrieval Pipeline 内部统一中间对象（强制）

为避免 LlamaIndex 与 DB 脱节，Retrieval Pipeline 使用一个内部标准结构：

```python
class Candidate:
    node_id: str
    stage: Literal["keyword","vector","fusion","rerank"]
    score: float
    score_details: dict
    excerpt: str | None
    page: int | None
    start_offset: int | None
    end_offset: int | None
    meta: dict  # node/article/section 等透传
```

* Candidate 必须可从：

  * FTS hit
  * Milvus hit
  * LlamaIndex NodeWithScore
    映射得到

* Candidate 必须可逆映射回：

  * NodeModel（证据原文）
  * RetrievalHitModel（落库审计）

---

## 3. Keyword Recall（keyword.py）设计指南

### 3.1 目标与行为标准

Keyword Recall 的目标是：

> **对合法关键词实现尽可能接近全量召回，同时保留可解释的 bm25/score。**

必须支持：

* 精确关键词召回（FTS5 bm25）
* 短 query 的稳定行为（防止只命中停用词）
* 未来扩展：拼写纠错 / 模糊匹配（不要求 MVP 立即实现，但 contract 必须预留）

### 3.2 推荐实现路径

**主路径（DB-First）：**

* 使用现有 `backend.db.fts.search_nodes(session, kb_id, query, top_k)`

**增强路径（LlamaIndex-First，可选开关）：**

* `BM25Retriever`（若引入本地索引缓存）
* `KeywordTableSimpleRetriever`（适合结构化节点，但需要 index 构建策略）

MVP 推荐：

* DB FTS 作为权威 keyword recall
* LlamaIndex keyword retriever 作为未来可插拔增强

### 3.3 暴露接口（建议）

```python
async def keyword_recall(
    *,
    session: AsyncSession,
    kb_id: str,
    query: str,
    top_k: int,
) -> list[Candidate]
```

输出 Candidate：

* stage = "keyword"
* score 使用 bm25（注意 bm25 越小越好，需要转换为“越大越好”的统一分数）

---

## 4. Vector Recall（vector.py）设计指南

### 4.1 目标与行为标准

Vector Recall 的目标是：

> **召回语义相关证据，并能严格限制在 kb_id scope 内。**

必须保证：

* expr 必含 kb_id
* 结果能回指 node_id
* score 可解释（距离/相似度 + 归一化策略）

### 4.2 推荐实现路径（强制 DB/Milvus 事实，算法用 LlamaIndex）

**两条路径必须兼容：**

1. **MilvusRepo 直接 search（事实优先）**

* 输入：query_vector
* 输出：[{vector_id, score, payload{node_id,...}}]

2. **LlamaIndex Vector Retriever（算法层）**

* 将 Milvus 作为 vector store 适配
* 输出 NodeWithScore

MVP 推荐：

* 先走 MilvusRepo（你已有 gate 锁定 API）
* 同时设计 LlamaIndex 适配层，保证后续可切换

### 4.3 暴露接口（建议）

```python
async def vector_recall(
    *,
    milvus_repo: MilvusRepo,
    kb_scope: dict,  # {kb_id, file_id?, document_id?}
    query_vector: list[float],
    top_k: int,
    output_fields: list[str],
) -> list[Candidate]
```

输出 Candidate：

* stage = "vector"
* node_id 从 payload 提取
* score_details 必包含 raw_score + metric_type

---

## 5. Fusion（fusion.py）设计指南

### 5.1 目标

Fusion 的目标是：

> **在不牺牲召回的前提下合并两路候选，并形成稳定去重后的 Top-K。**

### 5.2 必须支持的策略

* union（MVP 必须）
* RRF（推荐尽快实现）
* weighted（为可调权重预留）

### 5.3 去重规则（强制）

* 去重键：node_id
* 若同一 node 同时出现在 keyword 与 vector：

  * score_details 必记录两路得分
  * score 必为融合后的统一分数

### 5.4 暴露接口

```python
def fuse_candidates(
    *,
    keyword: list[Candidate],
    vector: list[Candidate],
    strategy: str,
    top_k: int,
) -> list[Candidate]
```

输出 Candidate：

* stage = "fusion"
* score_details 包含 fusion_strategy + components

---

## 6. Rerank（rerank.py）设计指南

### 6.1 目标

Rerank 的目标是：

> **在 Top-K 候选上提升精度与可读性，并提供可解释的 rerank_score。**

### 6.2 推荐 rerank 技术路径（强烈建议使用 LlamaIndex）

* `SentenceTransformerRerank`（本地 cross-encoder）
* `LLMRerank`（更贵，但可选）

MVP 推荐：

* 先支持 `none`
* 同时提供 cross-encoder rerank 的插拔实现（开关）

### 6.3 暴露接口

```python
async def rerank(
    *,
    query: str,
    candidates: list[Candidate],
    strategy: str,
    top_k: int,
) -> list[Candidate]
```

输出 Candidate：

* stage = "rerank"
* score_details 必含 rerank_score + model

---

## 7. persist.py（落库）设计指南

### 7.1 目标

> **把 RetrievalRecord 与最终 hits（以及可选的中间阶段 hits）稳定写入 DB，形成可回放审计单元。**

### 7.2 写入策略（强制）

* 必写：RetrievalRecord（message_id 1-1）
* 必写：最终 hits（来源 fused / reranked）
* 可选写：keyword / vector 阶段中间 hits（若写入，必须区分 source）

### 7.3 暴露接口

```python
async def persist_retrieval(
    *,
    retrieval_repo: RetrievalRepo,
    record_params: dict,
    hits: list[Candidate],
) -> tuple[str, int]  # (retrieval_record_id, hit_count)
```

persist 需负责：

* Candidate → RetrievalHitModel 字段映射
* excerpt/page/offset 快照优先从 Candidate 写入

---

## 8. pipeline.py（编排）设计指南

### 8.1 pipeline.py 需要负责的内容

* ctx 注入（trace_id/request_id）
* timing 记录（keyword/vector/fusion/rerank/total）
* provider_snapshot 聚合（embed/rerank/metric）
* 失败策略：

  * keyword 失败但 vector 成功 → 允许继续
  * 两者都失败 → 明确 no_evidence

### 8.2 公开入口（建议）

```python
async def run_retrieval_pipeline(
    *,
    session: AsyncSession,
    milvus_repo: MilvusRepo,
    retrieval_repo: RetrievalRepo,
    message_id: str,
    kb_id: str,
    query_text: str,
    query_vector: list[float],
    config: dict,
    ctx: PipelineContext,
) -> RetrievalBundle
```

---

## 9. Gate Test 设计指南（playground/retrieval_gate/test_retrieval_gate.py）

### 9.1 必须断言（最小宪法）

1. keyword hits > 0（对固定 query）
2. vector hits > 0（对固定 query_vector）
3. fusion hits > 0
4. hits 去重：node_id 唯一
5. hits 已落库：

   * retrieval_record 存在
   * retrieval_hit 数量正确

### 9.2 推荐增强断言（强烈建议）

* score_details 包含 keyword_score / vector_score / fusion_score / rerank_score
* provider_snapshot 含 embed/rerank
* timing_ms 至少包含 keyword/vector/fusion/total

---

## 10. 体验视角验收（必须能解释）

Retrieval 的最终输出必须支撑以下 UI/产品体验：

* 命中清单可展示：rank/score/page/article/section
* 命中可回看原文窗口：excerpt + offsets
* 用户可查看完整 retrieval record：参数、策略、耗时、provider

---

## 11. 关键补充（强烈建议纳入实现）

### 11.1 停用词与弱查询处理

* 若 query 仅包含停用词：

  * keyword 可能召回异常
  * 应在 pipeline 层检测并降级为：

    * 返回提示性回答（不进入 generation）
    * 或强制走 vector（若允许）

### 11.2 敏感/恶意 query（拒答前置）

* retrieval 层可标记 meta：

  * is_sensitive
  * is_out_of_scope
* evaluator 将据此做最终拒答

---

> **Retrieval Pipeline 是系统可信度的核心。**
>
> 我们追求的不是“召回一些东西”，而是“召回正确的证据，并能解释为什么这些证据排在前面”。
