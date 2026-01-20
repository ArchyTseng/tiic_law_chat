// src/api/endpoints/index.ts
//docstring
// 职责: API endpoints 出口（仅 transport 层）。
// 边界: 仅做 re-export；不得引入 domain/ui/stores/pages。
// 上游关系: api/client.ts。
// 下游关系: services/*。
export * from './chat'
export * from './ingest'
export * from './records_node'
export * from './records_page'
export * from './records_retrieval'
