// src/api/endpoints/records_retrieval.ts
//docstring
// 职责: retrieval records HTTP endpoint 调用。
// 边界: 仅负责请求与响应，不做业务映射。
// 上游关系: services/evidence_service.ts（后续接入）。
// 下游关系: src/api/http.ts。
import { requestJson } from '../http.ts'
import type { RetrievalRecordViewDTO } from '../../types/http/records_retrieval_response.ts'

export type RetrievalRecordQuery = {
  source?: string[]
  limit?: number
  offset?: number
  group?: boolean
}

export const buildRetrievalQuery = (query: RetrievalRecordQuery = {}): string => {
  const params = new URLSearchParams()

  if (query.source) {
    for (const value of query.source) {
      if (value) {
        params.append('source', value)
      }
    }
  }

  if (query.limit !== undefined) {
    params.set('limit', String(query.limit))
  }

  if (query.offset !== undefined) {
    params.set('offset', String(query.offset))
  }

  if (query.group !== undefined) {
    params.set('group', query.group ? 'true' : 'false')
  }

  return params.toString()
}

export const getRetrievalRecord = (
  retrievalRecordId: string,
  query: RetrievalRecordQuery = {},
) => {
  const queryString = buildRetrievalQuery(query)
  const suffix = queryString ? `?${queryString}` : ''
  const path = `/records/retrieval/${encodeURIComponent(retrievalRecordId)}${suffix}`
  return requestJson<RetrievalRecordViewDTO>(path, { method: 'GET' })
}
