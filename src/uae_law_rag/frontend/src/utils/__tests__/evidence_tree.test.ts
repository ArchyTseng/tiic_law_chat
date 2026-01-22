import { describe, expect, it } from 'vitest'
import { buildEvidenceTreeFromHits } from '@/utils/evidence_tree'

describe('buildEvidenceTreeFromHits', () => {
  it('groups hits by source, document, and page', () => {
    const tree = buildEvidenceTreeFromHits([
      { nodeId: 'node-1', source: 'vector', documentId: 'doc-1', page: 2 },
      { nodeId: 'node-2', source: 'vector', documentId: 'doc-1', page: 2 },
      { nodeId: 'node-3', source: 'keyword', documentId: 'doc-2', page: 1 },
    ])

    expect(tree).toBeDefined()
    expect(tree?.length).toBe(2)
    const vectorNode = tree?.find((node) => node.id === 'source:vector')
    expect(vectorNode?.children?.[0]?.id).toBe('doc:doc-1')
    expect(vectorNode?.children?.[0]?.children?.[0]?.children?.length).toBe(2)
  })
})
