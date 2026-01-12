# INGEST_PIPELINE_GUIDE.md

> 本文是 **PIPELINES_DEVELOP_GUIDE.md** 的 *Ingest Pipeline 专项实施指南*，用于约束和指导 **PDF → 结构化知识 → 可检索证据** 的整个导入链路。
>
> 本指南不是实现说明书，而是 **设计与质量红线文档**。任何 ingest 相关代码，都必须能在本文件中找到设计依据。

---

## 0. Pipeline 总体目标（必须同时满足）

Ingest Pipeline 的目标不是“把 PDF 变成文本”，而是：

> **把法律文件转化为：可回放、可审计、可解释、可多路检索（keyword + vector）的高质量证据节点集合**。

具体必须同时满足：

1. **最大程度还原法律文件原始结构与顺序**

   * 章节 / 条款 / 段落顺序不可乱
   * 语义连续性必须保留
   * 表格、标题、列表不得被简单打散

2. **为 Keyword FTS 提供“全量可召回”的文本底座**

   * Node.text 必须覆盖所有正文语义
   * 不得因为切分或清洗丢失关键词

3. **为 Vector Retrieval / Rerank 提供“高语义密度”的节点**

   * 节点粒度要利于 embedding
   * metadata 必须完整透传（page / article / section）

4. **为 Generation / Evaluator 提供稳定、可回查、可复现的证据链**

   * node_id 必须能反查原文
   * 引用必须有 page / article / section 语义锚点

---

## 1. Ingest Pipeline 的标准分层结构

```
PDF / Image
   ↓
[pdf_parse.py]        ← 文档结构还原（Markdown 级）
   ↓
[segment.py]          ← 法律友好的 Node 切分
   ↓
[embed.py]            ← LlamaIndex Embedding（语义向量）
   ↓
[persist_milvus.py]   ← 向量持久化（Milvus）
   ↓
[persist_db.py]       ← 结构化落库（SQL）
   ↓
[pipeline.py]         ← 编排 / ctx / timing / 幂等
```

**禁止合并这些步骤**。每一层都是未来可替换、可优化、可评估的独立单元。

---

## 2. pdf_parse.py 设计指南（最高要求）

### 2.1 设计原则

**pdf_parse 的唯一目标：**

> **在不做 OCR 的前提下，最大程度还原 PDF 的原始阅读顺序与结构层次。**

因此：

* ❌ 禁止：手写 PyMuPDF text extraction

* ❌ 禁止：自行拼接 page.text

* ❌ 禁止：直接输出纯字符串

* ✅ 必须：**直接使用 `pymupdf4llm`**

* ✅ 必须：**输出 Markdown（md）**

* ✅ 必须：章节 / 标题 / 列表 / 表格显式表达

### 2.2 推荐技术路径（强制）

* 核心依赖：

  * `pymupdf4llm`

* 输出形态：

  ```python
  ParsedDocument = {
      "markdown": str,          # 完整 Markdown
      "pages": int,
      "meta": {
          "parser": "pymupdf4llm",
          "version": "x.y.z"
      }
  }
  ```

### 2.3 为什么必须是 Markdown

* Markdown 天然表达：

  * 标题层级（# Article 1）
  * 列表（法律条款枚举）
  * 表格（法律附件 / 条款表）
* 为 **LlamaIndex MarkdownElementNodeParser** 提供最佳输入
* 为 UI / 审计保留结构可视性

---

## 3. segment.py 设计指南（法律友好切分）

### 3.1 切分目标

Segment 的目标不是“分得越细越好”，而是：

> **生成既利于检索，又利于引用的法律证据节点（Node）**。

### 3.2 强制使用的 LlamaIndex 能力

* `MarkdownElementNodeParser`
* `SentenceWindowNodeParser`

推荐组合：

1. MarkdownElementNodeParser

   * 保留标题 / 表格 / 列表语义
2. SentenceWindowNodeParser（window=2~3）

   * 保留上下文连续性

### 3.3 Node 内部数据合同（必须）

```python
NodePayload = {
    "node_index": int,
    "text": str,
    "page": int | None,
    "article_id": str | None,
    "section_path": str | None,
    "start_offset": int | None,
    "end_offset": int | None,
    "meta_data": {
        "source": "markdown",
        "element_type": "paragraph/title/table",
    }
}
```

这些字段 **必须能直接映射到 NodeModel**，不允许后补。

---

## 4. embed.py 设计指南（必须使用 LlamaIndex）

### 4.1 设计立场（强制）

> **Embedding 是 ingest 中“最不允许手写”的环节。**

原因：

* embedding 的 batch / pooling / truncation 极易出错
* 直接影响向量召回质量
* LlamaIndex 已提供成熟抽象

### 4.2 必须使用的抽象

* `BaseEmbedding`
* `TextNode`
* `NodeWithScore`

### 4.3 embed.py 的职责边界

* 输入：NodeModel.text + metadata

* 输出：

  ```python
  EmbeddingResult = {
      "node_id": str,
      "vector": List[float],
      "dim": int,
      "model": str,
      "provider": str,
  }
  ```

* ❌ 不负责 Milvus

* ❌ 不负责 DB

---

## 5. persist_milvus.py 设计指南

### 5.1 唯一职责

> **把 embedding 结果转化为 Milvus 中可检索、可过滤、可审计的向量实体。**

### 5.2 Payload 必须包含（与 kb/schema 对齐）

```python
{
  "vector_id": UUID,
  "embedding": [...],
  "node_id": UUID,
  "kb_id": UUID,
  "file_id": UUID,
  "document_id": UUID,
  "page": int,
  "article_id": str,
  "section_path": str,
}
```

这些字段将直接决定：

* Retrieval scope
* Citation 质量
* Evaluator 可解释性

---

## 6. persist_db.py 设计指南

### 6.1 DB 是最终真相源

* SQL Node / NodeVectorMap 是：

  * Keyword FTS
  * 向量一致性校验
  * 审计回放

### 6.2 必须完成的落库闭环

* KnowledgeFile (pending → success/failed)
* Document
* Node
* NodeVectorMap

任何 ingest 失败，都必须在 DB 中可观察。

---

## 7. ingest/pipeline.py 编排红线

pipeline.py 必须：

1. **显式 ctx（trace_id / request_id）**
2. **显式 timing（parse / segment / embed / milvus / db）**
3. **幂等保护（sha256）**
4. **失败可回滚 / 可标记**

禁止：

* 隐式状态
* 隐式 commit
* 吞异常

---

## 8. ingest_gate 设计指南（测试即法律）

### ingest_gate 必须断言：

1. PDF → node 数量 > 0
2. Node.text 非空
3. 每个 node：

   * 可 keyword 搜索
   * 可 vector 搜索
4. node_vector_map 数量 == embedding 数量
5. knowledge_file.ingest_status == success

如果 ingest_gate 失败：

> **说明系统已经不可信，不允许进入 retrieval。**

---

## 9. 设计补充（你未显式要求，但必须）

* 必须支持：

  * 多语言（至少 schema 不中断）
  * 法律表格
  * 长文档（>200页）

* ingest 的任何一步都必须：

  * 可单独 profiling
  * 可单独替换
  * 可单独回放

---

> **Ingest Pipeline 的质量，决定了整个系统是否值得被信任。**

如果 ingest 不可信，后面的 Retrieval / Generation / Evaluator 都只是幻觉制造器。
