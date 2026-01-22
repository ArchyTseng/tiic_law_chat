// src/services/chat_service.ts
//docstring
// 职责: Chat 用例层，负责调用 API 并映射为 domain 结果。
// 边界: 不读写 stores，不直接渲染 UI；仅负责 Domain Input <-> HTTP DTO 映射与传输层调用编排。
// 上游关系: stores/chat_store.ts（由 store 调用本 service）。
// 下游关系: api/endpoints/chat.ts。
import { apiClient } from '@/api/client'
import { normalizeChatResponse } from '@/services/normalize_chat'
import type { ChatNormalizedResult, ChatSendInput } from '@/types/domain/chat'
import type { EvidenceCitation, EvidenceLocator } from '@/types/domain/evidence'
import type { EvaluatorSummary } from '@/types/domain/message'
import type { EvaluatorStatus, ChatRequestDTO } from '@/types/http/chat_response'
import type { ChatHistoryMessageDTO } from '@/types/http/chat_history'
import type {
  ActiveRunView,
  ChatDebugView,
  ChatMessageView,
  ChatSessionView,
  CitationView,
  EvidenceView,
  EvaluatorBadgeView,
  RetrievalHitsView,
} from '@/types/ui'
import { toJsonRecord } from '@/utils/json'

const toChatRequestDTO = (input: ChatSendInput): ChatRequestDTO => {
  return {
    query: input.query,
    conversation_id: input.conversationId,
    kb_id: input.kbId,
    debug: input.debug,
    context: input.context
      ? {
        keyword_top_k: input.context.keywordTopK,
        vector_top_k: input.context.vectorTopK,
        fusion_top_k: input.context.fusionTopK,
        rerank_top_k: input.context.rerankTopK,
        fusion_strategy: input.context.fusionStrategy,
        rerank_strategy: input.context.rerankStrategy,
        embed_provider: input.context.embedProvider,
        embed_model: input.context.embedModel,
        embed_dim: input.context.embedDim,
        model_provider: input.context.modelProvider,
        model_name: input.context.modelName,
        prompt_name: input.context.promptName,
        prompt_version: input.context.promptVersion,
        evaluator_config: input.context.evaluatorConfig
          ? toJsonRecord(input.context.evaluatorConfig, 'context.evaluatorConfig')
          : undefined,
        return_records: input.context.returnRecords,
        return_hits: input.context.returnHits,
        extra: input.context.extra ? toJsonRecord(input.context.extra, 'context.extra') : undefined,
      }
      : undefined,
  } as ChatRequestDTO
}

export const sendChat = async (input: ChatSendInput): Promise<ChatNormalizedResult> => {
  const payload = toChatRequestDTO(input)
  const response = await apiClient.postChat(payload)
  return normalizeChatResponse(response)
}

type LiveSendOptions = {
  conversationId?: string
  kbId?: string
  debug?: boolean
  history?: ChatMessageView[]
}

type ChatServiceSnapshot = {
  chat: ChatSessionView
  evidence: EvidenceView
}

const mapEvaluatorBadge = (status?: EvaluatorStatus): EvaluatorBadgeView | undefined => {
  if (!status) return undefined
  if (status === 'pass') return { level: 'pass', label: 'pass' }
  if (status === 'partial') return { level: 'partial', label: 'degraded' }
  if (status === 'skipped') return { level: 'skipped', label: 'skipped' }
  return { level: 'fail', label: 'error' }
}

const mapActiveRun = (result: ChatNormalizedResult, evaluatorStatus?: EvaluatorStatus): ActiveRunView => {
  return {
    runId: result.run.runId,
    conversationId: result.run.conversationId,
    status: result.run.status,
    answer: result.answer,
    evaluatorBadge: mapEvaluatorBadge(evaluatorStatus),
    evaluatorSummary: result.evaluator,
    records: result.run.records,
    steps: result.run.steps,
    timing: result.run.timing,
    providerSnapshot: result.run.providerSnapshot,
  }
}

const mapHistoryRunStatus = (status?: string): ActiveRunView['status'] => {
  const normalized = (status ?? '').toLowerCase()
  if (normalized === 'failed') return 'error'
  if (normalized === 'partial' || normalized === 'blocked') return 'degraded'
  return 'success'
}

const mapHistoryEvaluatorSummary = (
  evaluator?: ChatHistoryMessageDTO['evaluator'] | null,
): EvaluatorSummary | undefined => {
  if (!evaluator) return undefined
  return {
    status: evaluator.status,
    ruleVersion: evaluator.rule_version,
    warnings: evaluator.warnings ?? [],
  }
}

const mapCitations = (citations: EvidenceCitation[]): CitationView[] => {
  return citations.map((citation) => ({
    nodeId: citation.nodeId,
    locator: citation.locator,
    onClickRef: {
      nodeId: citation.nodeId,
      documentId: citation.locator.documentId,
      page: citation.locator.page,
      start: citation.locator.start,
      end: citation.locator.end,
    },
  }))
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

const mapHistoryCitationLocator = (
  citation: NonNullable<ChatHistoryMessageDTO['citations']>[number],
): EvidenceLocator => {
  const rawLocator = isRecord(citation.locator) ? citation.locator : {}
  const page = typeof citation.page === 'number' ? citation.page : readNumber(rawLocator, 'page')
  const start = readNumber(rawLocator, 'start_offset') ?? readNumber(rawLocator, 'start')
  const end = readNumber(rawLocator, 'end_offset') ?? readNumber(rawLocator, 'end')
  const documentId = readString(rawLocator, 'document_id')
  const locator: EvidenceLocator = {}

  if (documentId) locator.documentId = documentId
  if (page !== undefined) locator.page = page
  if (start !== undefined) locator.start = start
  if (end !== undefined) locator.end = end

  const source = readString(rawLocator, 'source')
  if (source) locator.source = source

  const articleId =
    typeof citation.article_id === 'string' ? citation.article_id : readString(rawLocator, 'article_id')
  if (articleId) locator.articleId = articleId

  const sectionPath =
    typeof citation.section_path === 'string'
      ? citation.section_path
      : readString(rawLocator, 'section_path')
  if (sectionPath) locator.sectionPath = sectionPath

  return locator
}

const mapHistoryCitations = (citations?: ChatHistoryMessageDTO['citations']): CitationView[] => {
  if (!citations || citations.length === 0) return []
  return citations.map((citation) => {
    const locator = mapHistoryCitationLocator(citation)
    return {
      nodeId: citation.node_id,
      locator,
      onClickRef: {
        nodeId: citation.node_id,
        documentId: locator.documentId,
        page: locator.page,
        start: locator.start,
        end: locator.end,
      },
    }
  })
}

const mapDebug = (result: ChatNormalizedResult): ChatDebugView => {
  return {
    enabled: result.debug.available,
    promptDebug: result.debug.promptDebug,
    keywordStats: result.debug.keywordStats,
    providerSnapshot: result.run.providerSnapshot,
  }
}

const buildRetrievalView = (hits?: ChatNormalizedResult['evidence']['retrievalHitsPaged']): RetrievalHitsView => {
  if (!hits) {
    return { items: [], page: 1, pageSize: 0, total: 0 }
  }
  return {
    items: hits.items.map((item) => ({
      nodeId: item.nodeId,
      source: item.source,
      rank: item.rank,
      score: item.score,
      documentId: item.locator?.documentId,
      page: item.locator?.page,
      articleId: item.locator?.articleId,
      sectionPath: item.locator?.sectionPath,
      excerpt: item.locator?.start !== undefined ? `Offsets ${item.locator.start}-${item.locator.end}` : undefined,
    })),
    page: hits.page,
    pageSize: hits.pageSize,
    total: hits.total,
    source: hits.source,
  }
}

const buildEvidenceView = (result: ChatNormalizedResult): EvidenceView => {
  return {
    retrievalHits: buildRetrievalView(result.evidence.retrievalHitsPaged),
    evidenceTree: result.evidence.debugEvidenceTree,
    nodePreview: undefined,
  }
}

const buildEmptyEvidenceView = (): EvidenceView => {
  return {
    retrievalHits: { items: [], page: 1, pageSize: 0, total: 0, availableSources: [] },
    evidenceTree: undefined,
    nodePreview: undefined,
  }
}

const buildHistory = (history: ChatMessageView[], result: ChatNormalizedResult, text: string): ChatMessageView[] => {
  const base: ChatMessageView[] = history.length
    ? history
    : [
        {
          id: `user_${Date.now().toString(36)}`,
          role: 'user',
          content: text,
        },
      ]
  const assistantMessage: ChatMessageView = {
    id: `assistant_${result.run.runId}`,
    role: 'assistant',
    content: result.answer || '',
    runId: result.run.runId,
    citations: mapCitations(result.evidence.citations),
    evaluatorBadge: mapEvaluatorBadge(result.evaluator?.status),
  }
  return [...base, assistantMessage]
}

const buildSnapshot = (
  result: ChatNormalizedResult,
  options: LiveSendOptions,
  text: string,
): ChatServiceSnapshot => {
  const history = buildHistory(options.history ?? [], result, text)
  return {
    chat: {
      history: { items: history },
      activeRun: mapActiveRun(result, result.evaluator?.status),
      citations: mapCitations(result.evidence.citations),
      debug: mapDebug(result),
    },
    evidence: buildEvidenceView(result),
  }
}

const buildHistoryFromRecords = (records: ChatHistoryMessageDTO[]): ChatMessageView[] => {
  const items: ChatMessageView[] = []
  for (const record of records) {
    items.push({
      id: `user_${record.message_id}`,
      role: 'user',
      content: record.query,
    })
    if (record.answer) {
      items.push({
        id: `assistant_${record.message_id}`,
        role: 'assistant',
        content: record.answer,
        runId: record.message_id,
        citations: mapHistoryCitations(record.citations),
        evaluatorBadge: mapEvaluatorBadge(record.evaluator?.status),
      })
    }
  }
  return items
}

const buildActiveRunFromHistory = (records: ChatHistoryMessageDTO[]): ActiveRunView | undefined => {
  for (let index = records.length - 1; index >= 0; index -= 1) {
    const record = records[index]
    if (!record) continue
    if (
      !record.retrieval_record_id &&
      !record.generation_record_id &&
      (!record.citations || record.citations.length === 0) &&
      !record.answer
    ) {
      continue
    }
    return {
      runId: record.message_id,
      conversationId: record.conversation_id,
      status: mapHistoryRunStatus(record.status),
      answer: record.answer,
      evaluatorBadge: mapEvaluatorBadge(record.evaluator?.status),
      evaluatorSummary: mapHistoryEvaluatorSummary(record.evaluator),
      records: {
        retrievalRecordId: record.retrieval_record_id ?? undefined,
        generationRecordId: record.generation_record_id ?? undefined,
        evaluationRecordId: record.evaluation_record_id ?? undefined,
      },
      steps: [],
    }
  }
  return undefined
}

const buildHistorySnapshot = (records: ChatHistoryMessageDTO[]): ChatServiceSnapshot => {
  const historyItems = buildHistoryFromRecords(records)
  const activeRun = buildActiveRunFromHistory(records)
  const activeRecord = activeRun
    ? records.find((record) => record.message_id === activeRun.runId)
    : undefined
  return {
    chat: {
      history: { items: historyItems },
      citations: activeRecord ? mapHistoryCitations(activeRecord.citations) : [],
      activeRun,
      debug: { enabled: false },
    },
    evidence: buildEmptyEvidenceView(),
  }
}

export const createLiveChatService = () => {
  return {
    sendMessage: async (text: string, options: LiveSendOptions = {}): Promise<ChatServiceSnapshot> => {
      const result = await sendChat({
        query: text,
        conversationId: options.conversationId,
        kbId: options.kbId,
        debug: options.debug,
      })
      return buildSnapshot(result, { ...options, history: options.history ?? [] }, text)
    },
    getHistory: async (conversationId: string): Promise<ChatServiceSnapshot> => {
      const records = await apiClient.getChatMessages(conversationId)
      return buildHistorySnapshot(records)
    },
  }
}
