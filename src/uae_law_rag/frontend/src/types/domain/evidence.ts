//docstring
// 职责: 定义证据、回放与索引的 domain 结构。
// 边界: 不包含证据生成逻辑，仅承载数据。
// 上游关系: services/* 的 DTO 映射。
// 下游关系: EvidencePanel/NodePreview。
export type EvidenceLocator = {
  documentId?: string
  page?: number
  start?: number
  end?: number
  source?: string
  articleId?: string
  sectionPath?: string
  [key: string]: unknown
}

export type EvidenceCitation = {
  nodeId: string
  locator: EvidenceLocator
}

export type EvidenceTreeNode = {
  id: string
  label: string
  locator?: EvidenceLocator
  children?: EvidenceTreeNode[]
}

export type RetrievalHit = {
  nodeId: string
  source?: string
  rank?: number
  score?: number
  locator?: EvidenceLocator
}

export type RetrievalHitsPaged = {
  items: RetrievalHit[]
  page: number
  pageSize: number
  total: number
  source?: string
}

export type EvidenceIndex = {
  citations: EvidenceCitation[]
  debugEvidenceTree?: EvidenceTreeNode[]
  retrievalHitsPaged?: RetrievalHitsPaged
}

export type NodePreview = {
  nodeId: string
  documentId: string
  page?: number
  startOffset?: number
  endOffset?: number
  pageStartOffset?: number
  pageEndOffset?: number
  meta: {
    window?: string
    originalText?: string
  }
  textExcerpt: string
}

export type PageReplay = {
  documentId: string
  page: number
  kbId?: string
  content: string
}
