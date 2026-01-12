# EVALUATOR_PIPELINE_GUIDE.md

> 本文是 **PIPELINES_DEVELOP_GUIDE.md** 的 *Evaluator Pipeline 专项实施指南*，用于约束和指导 **Retrieval / Generation 结果的质量评估、门禁判定与审计落库**。
>
> Evaluator 不是“打分工具”，而是：**系统可信度的最终裁决者（Judge）**。

---

## 0. Evaluator Pipeline 的总体定位（不可妥协）

Evaluator Pipeline 的职责不是优化模型，而是回答一个更重要的问题：

> **“这一次回答，系统是否值得相信？”**

因此 Evaluator 必须同时满足：

1. **Deterministic（确定性）**

   * 相同 Retrieval + Generation 输入，Evaluator 输出必须稳定
   * 不依赖随机性或模型采样

2. **Evidence-Centric（证据中心）**

   * 所有评估都围绕 evidence（retrieval hits / citations）展开
   * 不允许“脱证据”的主观判断

3. **Gate-Oriented（门禁导向）**

   * Evaluator 的核心输出是：`pass / fail / partial / skipped`
   * 用于决定是否：

     * 向用户展示回答
     * 附带警告
     * 直接拒答

4. **Audit-Ready（审计可回放）**

   * 每一条评估结果必须可回放、可解释
   * 必须完整落库（EvaluationRecordModel）

---

## 1. Pipeline 目录结构与分层职责

```
src/uae_law_rag/backend/pipelines/evaluator
├── __init__.py
├── checks.py     # 规则检查（纯函数、确定性）
├── utils.py      # 通用评估工具（coverage / matching / helpers）
└── pipeline.py   # 编排（config → checks → 聚合 → 落库）
```

**强制规则**：

* checks 不访问 DB
* utils 不产生业务语义
* pipeline 负责配置驱动、聚合与状态裁决

---

## 2. 数据合同（Schema / DB 对齐）

### 2.1 DB 与 Schema 事实来源

**EvaluationRecordModel（事实）**：

* conversation_id
* message_id
* retrieval_record_id
* generation_record_id
* status
* rule_version
* config
* checks
* scores
* meta

**Schema.EvaluationResult / EvaluationCheck（合同）**：

* 必须完整覆盖 DB 字段
* checks / scores / meta 必须 JSON-serializable

---

## 3. Evaluator 的核心输入

Evaluator Pipeline 的输入必须明确、完整：

```python
EvaluatorInput = {
    "conversation_id": str,
    "message_id": str,
    "retrieval_record": RetrievalRecord,
    "retrieval_hits": list[RetrievalHit],
    "generation_record": GenerationRecord,
    "generation_output": {
        "answer": str,
        "citations": list[Citation],
    },
    "config": EvaluatorConfig,
}
```

**Evaluator 不得自行调用 retrieval / generation**。

---

## 4. checks.py 设计指南（评估规则层）

### 4.1 checks 的设计哲学

> 每一个 check，都是一条**可解释的质量断言**。

每个 check 必须：

* 输入确定
* 输出确定
* 无副作用

### 4.2 推荐的基础 Checks（MVP 必须）

1. **require_citations**

   * 回答是否包含 citations

2. **citation_coverage**

   * citations.node_id 是否 ⊆ retrieval hits

3. **min_answer_length**

   * answer 是否达到最小长度

4. **no_empty_answer**

   * 防止空字符串或模板输出

### 4.3 Check 输出数据合同

```python
EvaluationCheck = {
    "name": str,
    "status": "pass" | "fail" | "warn" | "skipped",
    "detail": dict,
}
```

checks.py 中的函数签名建议：

```python
def check_xxx(*, input: EvaluatorInput) -> EvaluationCheck
```

---

## 5. utils.py 设计指南（工具层）

utils.py 只允许出现：

* 覆盖率计算
* 集合关系判断
* 字符串规范化

### 5.1 推荐工具函数

* `compute_citation_coverage(citations, hits) -> float`
* `normalize_text(text) -> str`
* `extract_node_ids(...) -> set[str]`

**utils 不产生 pass/fail 语义**。

---

## 6. pipeline.py 设计指南（裁决层）

### 6.1 pipeline.py 的唯一职责

> **根据 EvaluatorConfig 执行 checks，并给出最终裁决。**

### 6.2 裁决逻辑（强制）

1. 执行所有 enabled checks

2. 汇总：

   * failures → fail
   * warnings → partial
   * all pass → pass
   * skipped only → skipped

3. 生成：

   * overall status
   * scores（如 coverage 数值）

### 6.3 pipeline.py 对外接口（建议）

```python
async def run_evaluator_pipeline(
    *,
    evaluator_repo: EvaluatorRepo,
    input: EvaluatorInput,
    ctx: PipelineContext,
) -> EvaluationResult
```

pipeline 必须负责：

* rule_version 写入
* config 快照写入
* meta（trace_id / timing）

---

## 7. Gate Test 设计指南（playground/evaluator_gate/test_evaluator_gate.py）

### 7.1 必须断言（可信门槛）

1. EvaluationRecord 已创建
2. status ∈ {pass, fail, partial, skipped}
3. checks 非空（除非 skipped）
4. retrieval_record_id / generation_record_id 对齐

### 7.2 强烈建议的增强断言

* citation_coverage ∈ [0,1]
* require_citations fail → overall fail
* rule_version 稳定

---

## 8. 与系统其他 Pipeline 的关系

* **Retrieval**：提供 evidence 边界
* **Generation**：提供被评估对象
* **Evaluator**：裁决是否可信
* **Service/API**：依据裁决决定是否展示/警告/拒答

Evaluator 永远是最后一道门。

---

## 9. 体验与产品视角验收

Evaluator 的存在，必须让用户与开发者都感到：

* 系统知道自己什么时候不确定
* 系统知道什么时候应该拒答
* 系统的每一次判断都有理由

---

> **Evaluator Pipeline 是系统“自知之明”的体现。**
>
> 一个没有 Evaluator 的 RAG 系统，只是在制造看似合理的文本。
