# PIPELINES_GATE_BLUEPRINT.md

> 本文是 **PIPELINES_DEVELOP_GUIDE.md** 的 *Gate Tests 总蓝图*，用于定义 **Ingest / Retrieval / Generation / Evaluator** 四大 pipeline 的 **最小可信门槛（Minimum Trust Bar）**。
>
> Gate Tests 不是回归测试，也不是实现验证，而是：
>
> **系统是否允许“继续向前”的法律条款。**

---

## 0. Gate Tests 的总体哲学

### 0.1 Gate 的本质

Gate Test 的本质不是：

* “代码是否能跑”

而是：

> **“在这一阶段，系统是否仍然值得被信任？”**

因此 Gate Tests 的职责是：

* ❌ 阻止不可信的数据进入下游
* ❌ 阻止 silent failure
* ❌ 阻止 schema / contract 漂移

而不是：

* ❌ 覆盖所有 edge case
* ❌ 测性能
* ❌ 测 UI

---

## 1. 四级 Gate 结构总览

```
Ingest Gate     → 证据是否可信？
Retrieval Gate  → 证据是否被正确召回与排序？
Generation Gate → 回答是否被证据约束？
Evaluator Gate  → 系统是否知道自己是否可信？
```

**原则：任一 Gate 失败，必须阻断后续 pipeline。**

---

## 2. Ingest Gate Blueprint

### 2.1 Gate 目标

> **确保导入后的知识库，是一个“可检索、可回查、可审计”的证据集合。**

### 2.2 必须覆盖的 Gate 断言（硬门槛）

#### A. 文件与结构层

* knowledge_file 已创建
* ingest_status == "success"
* pages > 0

#### B. Node 结构完整性

* node_count > 0
* 每个 Node:

  * text 非空
  * text 长度 > 最小阈值（防止空节点）
  * node_index 连续

#### C. Keyword 可召回性（FTS）

* 对至少一个已知关键词：

  * FTS hits > 0
  * 命中 node_id 属于本 file

#### D. Vector 可召回性

* node_vector_map 数量 == node_count（或 embedding 数量）
* 对 sample query_vector：

  * Milvus search hits > 0

#### E. 映射一致性

* node_vector_map.node_id ∈ node.id
* vector payload.kb_id == knowledge_file.kb_id

### 2.3 强烈建议的增强 Gate

* Node.meta_data 含 article_id / section_path（法律文本）
* Markdown 结构被保留（title / list / table）

---

## 3. Retrieval Gate Blueprint

### 3.1 Gate 目标

> **确保系统在“给模型证据之前”，已经完成了高召回、可解释、可回放的检索。**

### 3.2 必须覆盖的 Gate 断言（硬门槛）

#### A. RetrievalRecord 创建

* retrieval_record 存在
* retrieval_record.message_id 唯一（1-1）

#### B. Keyword Recall

* keyword hits > 0（对固定测试 query）
* 每个 hit:

  * node_id 有效
  * score 数值合法

#### C. Vector Recall

* vector hits > 0（对固定 query_vector）
* 每个 hit:

  * payload.node_id 存在
  * payload.kb_id 正确

#### D. Fusion 结果

* fusion hits > 0
* 去重后 node_id 唯一

#### E. 落库一致性

* retrieval_hit 数量 == fusion / rerank 输出数量
* source 字段 ∈ {keyword, vector, fused, reranked}

### 3.3 强烈建议的增强 Gate

* score_details 包含 keyword_score / vector_score
* timing_ms 含 keyword / vector / fusion / total
* provider_snapshot 含 embed provider 信息

---

## 4. Generation Gate Blueprint

### 4.1 Gate 目标

> **确保生成结果不是 hallucination，而是“被证据约束的回答”。**

### 4.2 必须覆盖的 Gate 断言（硬门槛）

#### A. GenerationRecord 创建

* generation_record 存在
* generation_record.message_id 唯一（1-1）

#### B. 输出基本有效性

* output_raw 非空
* status ∈ {success, partial, failed}

#### C. Citation 合法性

* citations 数量 ≥ 1（法律 QA 默认）
* 每个 citation.node_id ∈ retrieval hits

#### D. 落库一致性

* retrieval_record_id 对齐
* citations 已 JSON 持久化

### 4.3 强烈建议的增强 Gate

* output_structured JSON 可解析
* citations 含 page / article / section
* timing_ms 含 llm / postprocess / total

---

## 5. Evaluator Gate Blueprint

### 5.1 Gate 目标

> **确保系统明确知道：这一次回答是否可信。**

### 5.2 必须覆盖的 Gate 断言（硬门槛）

#### A. EvaluationRecord 创建

* evaluation_record 存在
* message_id / retrieval_record_id / generation_record_id 对齐

#### B. 总体裁决合法

* status ∈ {pass, fail, partial, skipped}

#### C. Checks 完整性

* checks 非空（除非 skipped）
* 每个 check:

  * name 非空
  * status ∈ {pass, fail, warn, skipped}

### 5.3 强烈建议的增强 Gate

* citation_coverage ∈ [0, 1]
* require_citations fail → overall fail
* rule_version 稳定

---

## 6. Gate 之间的强制因果关系

```
Ingest Gate FAIL     → Retrieval 不允许执行
Retrieval Gate FAIL  → Generation 不允许执行
Generation Gate FAIL → Evaluator 仍执行（给出 fail 裁决）
Evaluator Gate FAIL  → API 必须拒绝向用户返回结果
```

---

## 7. Gate Tests 的工程红线

* Gate Tests 必须：

  * deterministic
  * 可重复
  * 不依赖外部网络（除非明确标注 integration gate）

* Gate Tests 禁止：

  * 隐式跳过
  * try/except 吞异常
  * 仅断言“不报错”

---

## 8. 终极原则（必须牢记）

> **Gate Tests 是系统对“可信性”的最低承诺。**
>
> 如果一个系统无法通过自己的 Gate Tests，
> 那么它也不配要求用户信任它。
