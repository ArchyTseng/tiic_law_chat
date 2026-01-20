//docstring
// 职责: 定义 pipeline step 的 domain 结构。
// 边界: 不固化 step 顺序，仅描述结构。
// 上游关系: services/* 的 DTO 映射。
// 下游关系: EvidencePanel 与调试视图。
export type StepName = 'retrieval' | 'generation' | 'evaluator'

export type StepStatus = 'success' | 'degraded' | 'error'

export type StepRecord = {
  step: StepName
  status: StepStatus
  reasons: string[]
  timingMs?: number
}
