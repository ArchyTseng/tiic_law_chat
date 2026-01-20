// src/api/endpoints/records_page.ts
//docstring
// 职责: page replay HTTP endpoint 调用。
// 边界: 仅负责请求与响应，不做业务映射。
// 上游关系: services/evidence_service.ts（后续接入）。
// 下游关系: src/api/http.ts。
import { requestJson } from '../http.ts'
import type { PageRecordViewDTO } from '../../types/http/records_page_response.ts'

export type PageRecordQuery = {
  documentId: string
  page: number
  kbId?: string
  maxChars?: number
}

export type PageRecordByNodeQuery = {
  kbId?: string
  maxChars?: number
}

const buildPageQuery = (query: PageRecordQuery): string => {
  const params = new URLSearchParams()
  params.set('document_id', query.documentId)
  params.set('page', String(query.page))

  if (query.kbId) {
    params.set('kb_id', query.kbId)
  }

  if (query.maxChars !== undefined) {
    params.set('max_chars', String(query.maxChars))
  }

  return params.toString()
}

const buildPageByNodeQuery = (query: PageRecordByNodeQuery = {}): string => {
  const params = new URLSearchParams()

  if (query.kbId) {
    params.set('kb_id', query.kbId)
  }

  if (query.maxChars !== undefined) {
    params.set('max_chars', String(query.maxChars))
  }

  return params.toString()
}

export const getPageRecord = (query: PageRecordQuery) => {
  const queryString = buildPageQuery(query)
  const path = `/records/page?${queryString}`
  return requestJson<PageRecordViewDTO>(path, { method: 'GET' })
}

export const getPageRecordByNode = (nodeId: string, query: PageRecordByNodeQuery = {}) => {
  const queryString = buildPageByNodeQuery(query)
  const suffix = queryString ? `?${queryString}` : ''
  const path = `/records/page/by_node/${encodeURIComponent(nodeId)}${suffix}`
  return requestJson<PageRecordViewDTO>(path, { method: 'GET' })
}
