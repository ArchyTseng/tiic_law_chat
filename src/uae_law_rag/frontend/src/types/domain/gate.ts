//docstring
// 职责: 定义 gate 状态的前端 domain 结构。
// 边界: 不推断 gate 逻辑，仅承载服务端摘要。
// 上游关系: services/chat_service.ts。
// 下游关系: UI 解释层。
export type GateStatus = 'pass' | 'partial' | 'fail' | 'skipped'

export type GateDecision = {
  status?: GateStatus | string
  passed?: boolean
  reasons?: string[]
}

export type GateSummary = {
  retrieval?: GateDecision
  generation?: GateDecision
  evaluator?: GateDecision
}
