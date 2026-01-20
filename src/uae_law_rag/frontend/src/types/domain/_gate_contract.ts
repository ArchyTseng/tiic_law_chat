// src/types/domain/_gate_contract.ts
//docstring
// 职责: F1-2 Domain Gate 结构自检（仅用于 typecheck，禁止运行时依赖）。
// 边界: 不导入 http DTO，不依赖 services/stores/pages。
// 上游关系: pnpm typecheck 执行。
// 下游关系: 无（仅用于类型约束）。
import type { EvidenceIndex, EvidenceTreeNode, NodePreview, PageReplay } from '@/types/domain/evidence'
import type { Citation } from '@/types/domain/message'
import type { RunRecord } from '@/types/domain/run'
import type { StepRecord } from '@/types/domain/step'

export const gateStepsSample: StepRecord[] = [
  { step: 'retrieval', status: 'success', reasons: [], timingMs: 40 },
  { step: 'generation', status: 'degraded', reasons: ['no_evidence'], timingMs: 55 },
  { step: 'evaluator', status: 'success', reasons: [], timingMs: 12 },
]

export const gateRunSample: RunRecord = {
  runId: 'run_001',
  conversationId: 'conv_001',
  messageId: 'msg_001',
  kbId: 'kb_default',
  queryText: 'example query',
  status: 'degraded',
  timing: {
    totalMs: 120,
    stages: { retrieval: 40, generation: 55, evaluator: 12 },
  },
  steps: gateStepsSample,
}

export const gateEvidenceTreeSample: EvidenceTreeNode[] = [
  {
    id: 'source:keyword',
    label: 'keyword',
    children: [
      {
        id: 'doc:doc_001',
        label: 'doc_001',
        children: [
          {
            id: 'page:1',
            label: 'page 1',
            locator: { documentId: 'doc_001', page: 1 },
            children: [],
          },
        ],
      },
    ],
  },
]

export const gateEvidenceSample: EvidenceIndex = {
  citations: [
    {
      nodeId: 'node_001',
      locator: {
        documentId: 'doc_001',
        page: 1,
        start: 10,
        end: 120,
        source: 'keyword',
      },
    },
  ],
  debugEvidenceTree: gateEvidenceTreeSample,
  retrievalHitsPaged: {
    items: [
      {
        nodeId: 'node_001',
        source: 'keyword',
        rank: 1,
        score: 0.98,
        locator: { documentId: 'doc_001', page: 1, start: 10, end: 120 },
      },
    ],
    page: 1,
    pageSize: 10,
    total: 1,
    source: 'keyword',
  },
}

export const gateNodePreviewSample: NodePreview = {
  nodeId: 'node_001',
  documentId: 'doc_001',
  page: 1,
  startOffset: 10,
  endOffset: 120,
  pageStartOffset: 10,
  pageEndOffset: 120,
  meta: {
    window: 'window text',
    originalText: 'original text',
  },
  textExcerpt: 'excerpt text',
}

export const gatePageReplaySample: PageReplay = {
  documentId: 'doc_001',
  page: 1,
  kbId: 'kb_default',
  content: 'page content',
}

export const gateCitationsSample: Citation[] = [
  {
    nodeId: gateEvidenceSample.citations[0]!.nodeId,
    locator: gateEvidenceSample.citations[0]!.locator,
  },
]

export const gateNoAnswerSample = {
  run: gateRunSample,
  evidence: gateEvidenceSample,
  citations: gateCitationsSample,
  nodePreview: gateNodePreviewSample,
}
