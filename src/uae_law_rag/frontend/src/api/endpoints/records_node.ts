// src/api/endpoints/records_node.ts
//docstring
// 职责: node record HTTP endpoint 调用。
// 边界: 仅负责请求与响应，不做业务映射。
// 上游关系: services/evidence_service.ts（后续接入）。
// 下游关系: src/api/http.ts。
import { requestJson } from '../http.ts'
import type { NodeRecordViewDTO } from '../../types/http/records_node_response.ts'

export type NodeRecordQuery = {
  kbId?: string
  maxChars?: number
}

const buildNodeQuery = (query: NodeRecordQuery = {}): string => {
  const params = new URLSearchParams()

  if (query.kbId) {
    params.set('kb_id', query.kbId)
  }

  if (query.maxChars !== undefined) {
    params.set('max_chars', String(query.maxChars))
  }

  return params.toString()
}

export const getNodeRecord = (nodeId: string, query: NodeRecordQuery = {}) => {
  const queryString = buildNodeQuery(query)
  const suffix = queryString ? `?${queryString}` : ''
  const path = `/records/node/${encodeURIComponent(nodeId)}${suffix}`
  return requestJson<NodeRecordViewDTO>(path, { method: 'GET' })
}
