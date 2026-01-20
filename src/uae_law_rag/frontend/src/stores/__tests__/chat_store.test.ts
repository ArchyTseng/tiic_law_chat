import { chatStore } from '@/stores/chat_store'
import { sendChat } from '@/services/chat_service'
import { loadNodePreview, loadRetrievalHits } from '@/services/evidence_service'
import type { ChatNormalizedResult } from '@/types/domain/chat'
import type { NodePreview, RetrievalHitsPaged } from '@/types/domain/evidence'

vi.mock('@/services/chat_service', () => ({
  sendChat: vi.fn(),
}))

vi.mock('@/services/evidence_service', () => ({
  loadNodePreview: vi.fn(),
  loadRetrievalHits: vi.fn(),
  loadPageReplay: vi.fn(),
  loadPageReplayByNode: vi.fn(),
}))

describe('chatStore replay stability', () => {
  const sendChatMock = vi.mocked(sendChat)
  const loadNodePreviewMock = vi.mocked(loadNodePreview)
  const loadRetrievalHitsMock = vi.mocked(loadRetrievalHits)

  beforeEach(() => {
    chatStore.reset()
    vi.clearAllMocks()
  })

  it('keeps runs and cache when toggling debug', async () => {
    const normalized: ChatNormalizedResult = {
      run: {
        runId: 'run-1',
        status: 'success',
        timing: {},
        steps: [],
      },
      evidence: {
        citations: [],
      },
      answer: 'hello',
      debug: {
        available: true,
      },
    }

    const nodePreview: NodePreview = {
      nodeId: 'node-1',
      documentId: 'doc-1',
      meta: {},
      textExcerpt: 'excerpt',
    }

    const retrievalHits: RetrievalHitsPaged = {
      items: [],
      page: 1,
      pageSize: 10,
      total: 0,
    }

    sendChatMock.mockResolvedValue(normalized)
    loadNodePreviewMock.mockResolvedValue(nodePreview)
    loadRetrievalHitsMock.mockResolvedValue(retrievalHits)

    await chatStore.send('hello', { debug: true })
    chatStore.selectNode('node-1')
    await chatStore.fetchNodePreview('node-1')
    await chatStore.fetchRetrievalHits('retrieval-1', {
      source: ['keyword'],
      offset: 0,
      limit: 10,
    })

    const snapshot = chatStore.getState()
    chatStore.toggleDebug()
    const next = chatStore.getState()

    expect(next.activeRunId).toBe(snapshot.activeRunId)
    expect(next.runsById).toEqual(snapshot.runsById)
    expect(next.cache).toEqual(snapshot.cache)
    expect(next.evidence.selectedNodeId).toBe(snapshot.evidence.selectedNodeId)
    expect(next.messages).toEqual(snapshot.messages)
    expect(next.ui.debugOpen).toBe(!snapshot.ui.debugOpen)
  })

  it('uses cache for retrieval hits', async () => {
    const normalized: ChatNormalizedResult = {
      run: {
        runId: 'run-2',
        status: 'success',
        timing: {},
        steps: [],
      },
      evidence: {
        citations: [],
      },
      answer: 'cached',
      debug: {
        available: true,
      },
    }

    const retrievalHits: RetrievalHitsPaged = {
      items: [],
      page: 1,
      pageSize: 10,
      total: 0,
    }

    sendChatMock.mockResolvedValue(normalized)
    loadRetrievalHitsMock.mockResolvedValue(retrievalHits)

    await chatStore.send('cache test')
    await chatStore.fetchRetrievalHits('retrieval-1', {
      source: ['keyword'],
      offset: 0,
      limit: 10,
    })
    await chatStore.fetchRetrievalHits('retrieval-1', {
      source: ['keyword'],
      offset: 0,
      limit: 10,
    })

    expect(loadRetrievalHitsMock).toHaveBeenCalledTimes(1)
  })
})
