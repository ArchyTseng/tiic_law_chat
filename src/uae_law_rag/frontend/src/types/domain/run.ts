//docstring
// 职责: 定义 run 与 debug 记录的 domain 结构。
// 边界: 不引入服务端内部实现字段。
// 上游关系: services/* 的 DTO 映射。
// 下游关系: UI 审计与证据展示。
import type { GateSummary } from '@/types/domain/gate'
import type { StepRecord } from '@/types/domain/step'

export type RunRecords = {
  retrievalRecordId?: string
  generationRecordId?: string
  evaluationRecordId?: string
  documentId?: string
}

export type RunTiming = {
  totalMs?: number
  stages?: Record<string, number>
}

export type DebugEnvelope = {
  traceId: string
  requestId: string
  records: RunRecords
  timingMs?: Record<string, unknown>
  gate?: GateSummary
  providerSnapshot?: Record<string, unknown>
  hitsCount?: number
}

export type RunStatus = 'success' | 'degraded' | 'error'

export type RunRecord = {
  runId: string
  conversationId?: string
  messageId?: string
  kbId?: string
  queryText?: string
  status: RunStatus
  timing: RunTiming
  providerSnapshot?: Record<string, unknown>
  records?: RunRecords
  steps: StepRecord[]
}
