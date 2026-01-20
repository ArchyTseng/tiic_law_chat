import { strict as assert } from 'node:assert'

const { HttpError } = await import('../src/api/http.ts')
const { buildRetrievalQuery, getRetrievalRecord } = await import('../src/api/endpoints/records_retrieval.ts')
const { getNodeRecord } = await import('../src/api/endpoints/records_node.ts')
const { getPageRecord, getPageRecordByNode } = await import('../src/api/endpoints/records_page.ts')

assert.ok(HttpError, '[gate:f2] HttpError must be importable')

const ensureHttpError = async (label, task) => {
  try {
    await task()
  } catch (error) {
    if (error instanceof HttpError) {
      return
    }
    throw new Error(`[gate:f2] ${label} threw non-HttpError`)
  }
  throw new Error(`[gate:f2] ${label} did not throw`)
}

const query = buildRetrievalQuery({
  source: ['keyword', 'vector'],
  limit: 10,
  offset: 5,
  group: true,
})

const sourceMatches = query.match(/source=/g) ?? []
assert.equal(sourceMatches.length, 2, '[gate:f2] retrieval query must use repeatable source=')
assert.ok(query.includes('source=keyword'), '[gate:f2] missing source=keyword')
assert.ok(query.includes('source=vector'), '[gate:f2] missing source=vector')

await ensureHttpError('getRetrievalRecord', () =>
  getRetrievalRecord('missing', { source: ['keyword'], limit: 1, offset: 0, group: true }),
)
await ensureHttpError('getNodeRecord', () => getNodeRecord('missing', { kbId: 'kb', maxChars: 200 }))
await ensureHttpError('getPageRecord', () =>
  getPageRecord({ documentId: 'doc', page: 1, kbId: 'kb', maxChars: 200 }),
)
await ensureHttpError('getPageRecordByNode', () =>
  getPageRecordByNode('missing', { kbId: 'kb', maxChars: 200 }),
)

console.log('[gate:f2] OK: endpoints throw HttpError on failure and queries are encoded.')
