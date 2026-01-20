// src/services/normalize_chat.ts
//docstring
// Responsibility: Map ChatResponseDTO into minimal Domain shape for tests and later normalize work.
// Boundary: Pure function only; no IO; no store/UI dependencies.
import type {
  ChatGateDecisionDTO,
  ChatResponseDTO,
  DebugEvidenceDTO,
  PromptDebugDTO,
} from '@/types/http/chat_response'
import type { EvidenceIndex, EvidenceLocator, EvidenceTreeNode } from '@/types/domain/evidence'
import type { RunRecord, RunStatus, RunTiming } from '@/types/domain/run'
import type { StepName, StepRecord, StepStatus } from '@/types/domain/step'

export type NormalizedChat = {
  run: RunRecord
  evidence: EvidenceIndex
  debug?: {
    evidence?: DebugEvidenceDTO
    promptDebug?: PromptDebugDTO
  }
}

const isRecord = (value: unknown): value is Record<string, unknown> => {
  return typeof value === 'object' && value !== null
}

const readNumber = (record: Record<string, unknown>, key: string): number | undefined => {
  const value = record[key]
  return typeof value === 'number' ? value : undefined
}

const readString = (record: Record<string, unknown>, key: string): string | undefined => {
  const value = record[key]
  return typeof value === 'string' ? value : undefined
}

const normalizeDecisionStatus = (decision?: ChatGateDecisionDTO): StepStatus => {
  if (!decision) return 'success'
  if (decision.passed === true) return 'success'
  if (decision.passed === false) return 'degraded'
  const raw = (decision.status ?? '').toLowerCase()
  if (raw === 'pass' || raw === 'success') return 'success'
  if (raw === 'fail' || raw === 'failed' || raw === 'error') return 'error'
  if (raw) return 'degraded'
  return 'degraded'
}

const normalizeStep = (step: StepName, decision?: ChatGateDecisionDTO): StepRecord => {
  return {
    step,
    status: normalizeDecisionStatus(decision),
    reasons: Array.isArray(decision?.reasons) ? decision?.reasons : [],
  }
}

const deriveRunStatus = (chatStatus: ChatResponseDTO['status'], steps: StepRecord[]): RunStatus => {
  if (steps.some((item) => item.status === 'error')) return 'error'
  if (steps.some((item) => item.status === 'degraded')) return 'degraded'
  if (chatStatus === 'failed') return 'error'
  if (chatStatus === 'partial' || chatStatus === 'blocked') return 'degraded'
  return 'success'
}

const buildTiming = (timing: ChatResponseDTO['timing_ms']): RunTiming => {
  const stages: Record<string, number> = {}
  for (const [key, value] of Object.entries(timing)) {
    if (key === 'total_ms') continue
    if (typeof value === 'number') stages[key] = value
  }

  return {
    totalMs: typeof timing.total_ms === 'number' ? timing.total_ms : undefined,
    stages: Object.keys(stages).length ? stages : undefined,
  }
}

const buildLocator = (citation: ChatResponseDTO['citations'][number]): EvidenceLocator => {
  const rawLocator = isRecord(citation.locator) ? citation.locator : {}
  const page = typeof citation.page === 'number' ? citation.page : readNumber(rawLocator, 'page')
  const start = readNumber(rawLocator, 'start_offset') ?? readNumber(rawLocator, 'start')
  const end = readNumber(rawLocator, 'end_offset') ?? readNumber(rawLocator, 'end')

  return {
    ...rawLocator,
    page,
    start,
    end,
    source: readString(rawLocator, 'source'),
    articleId: typeof citation.article_id === 'string'
      ? citation.article_id
      : readString(rawLocator, 'article_id'),
    sectionPath: typeof citation.section_path === 'string'
      ? citation.section_path
      : readString(rawLocator, 'section_path'),
  }
}

const buildEvidenceTree = (evidence?: DebugEvidenceDTO): EvidenceTreeNode[] | undefined => {
  if (!evidence) return undefined
  return evidence.document_ids.map((docId) => ({
    id: docId,
    label: docId,
  }))
}

export const normalizeChatResponse = (response: ChatResponseDTO): NormalizedChat => {
  const gate = response.debug?.gate
  const steps: StepRecord[] = gate
    ? [
      normalizeStep('retrieval', gate.retrieval),
      normalizeStep('generation', gate.generation),
      normalizeStep('evaluator', gate.evaluator),
    ]
    : []

  const run: RunRecord = {
    runId: response.message_id,
    conversationId: response.conversation_id,
    messageId: response.message_id,
    kbId: response.kb_id,
    status: deriveRunStatus(response.status, steps),
    timing: buildTiming(response.timing_ms),
    providerSnapshot: response.debug?.provider_snapshot,
    records: response.debug?.records
      ? {
        retrievalRecordId: response.debug.records.retrieval_record_id,
        generationRecordId: response.debug.records.generation_record_id,
        evaluationRecordId: response.debug.records.evaluation_record_id,
        documentId: response.debug.records.document_id,
      }
      : undefined,
    steps,
  }

  const evidence: EvidenceIndex = {
    citations: response.citations.map((citation) => ({
      nodeId: citation.node_id,
      locator: buildLocator(citation),
    })),
    debugEvidenceTree: buildEvidenceTree(response.debug?.evidence),
  }

  return {
    run,
    evidence,
    debug: response.debug
      ? {
        evidence: response.debug.evidence,
        promptDebug: response.debug.prompt_debug,
      }
      : undefined,
  }
}
