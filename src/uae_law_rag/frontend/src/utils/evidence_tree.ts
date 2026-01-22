import type { EvidenceTreeNode } from '@/types/domain/evidence'

type EvidenceTreeHit = {
  nodeId: string
  source?: string
  documentId?: string
  page?: number
}

export const buildEvidenceTreeFromHits = (hits: EvidenceTreeHit[]): EvidenceTreeNode[] | undefined => {
  const sourceBuckets = new Map<string, Map<string, Map<string, string[]>>>()
  const seen = new Set<string>()

  for (const hit of hits) {
    if (!hit.nodeId) continue
    const docId = hit.documentId
    if (!docId) continue
    const source = hit.source || 'unknown'
    const pageKey = hit.page && hit.page > 0 ? String(hit.page) : '_'
    const uniqueKey = `${source}:${docId}:${pageKey}:${hit.nodeId}`
    if (seen.has(uniqueKey)) continue
    seen.add(uniqueKey)

    let docMap = sourceBuckets.get(source)
    if (!docMap) {
      docMap = new Map()
      sourceBuckets.set(source, docMap)
    }

    let pageMap = docMap.get(docId)
    if (!pageMap) {
      pageMap = new Map()
      docMap.set(docId, pageMap)
    }

    let nodes = pageMap.get(pageKey)
    if (!nodes) {
      nodes = []
      pageMap.set(pageKey, nodes)
    }
    nodes.push(hit.nodeId)
  }

  if (sourceBuckets.size === 0) return undefined

  const nodes: EvidenceTreeNode[] = []
  for (const [source, docs] of sourceBuckets) {
    const sourceNode: EvidenceTreeNode = {
      id: `source:${source}`,
      label: source,
      children: [],
    }
    for (const [docId, pages] of docs) {
      const docNode: EvidenceTreeNode = {
        id: `doc:${docId}`,
        label: docId,
        children: [],
      }
      for (const [pageKey, nodeIds] of pages) {
        docNode.children?.push({
          id: `page:${docId}:${pageKey}`,
          label: `page ${pageKey}`,
          children: nodeIds.map((nodeId) => ({
            id: nodeId,
            label: nodeId,
          })),
        })
      }
      sourceNode.children?.push(docNode)
    }
    nodes.push(sourceNode)
  }

  return nodes
}
