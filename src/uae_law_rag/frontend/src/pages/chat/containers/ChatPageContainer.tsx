// src/pages/chat/containers/ChatPageContainer.tsx
//docstring
// 职责: Chat 页面容器，读取 store 并向展示层传递 props。
// 边界: 不渲染具体 UI；仅负责数据与交互桥接。
// 上游关系: src/app/layout/AppShell.tsx。
// 下游关系: src/pages/chat/ChatPage.tsx。
import ChatPage from '@/pages/chat/ChatPage'
import { createMockChatService } from '@/pages/chat/mock/mock_chat_service'
import { createMockEvidenceService, type RetrievalHitsResult } from '@/pages/chat/mock/mock_evidence_service'
import { createChatStore } from '@/stores/chat_store'
import { useChatStore } from '@/stores/use_chat_store'
import { useCallback, useEffect, useMemo, useState } from 'react'

const USE_MOCK = true
type ChatScenario = 'ok' | 'no_debug' | 'empty' | 'error'

export type ChatTopbarActions = {
  mockMode: 'ok' | 'no_debug' | 'empty' | 'error'
  drawerOpen: boolean
  onChangeMockMode: (mode: 'ok' | 'no_debug' | 'empty' | 'error') => void
  onInjectError: () => void
  onToggleEvidence: () => void
}

type ChatPageContainerProps = {
  conversationId?: string
  onTopbarActionsChange?: (actions: ChatTopbarActions) => void
}

const conversationModeMap: Record<string, ChatScenario> = {
  'project:tiic_law_chat': 'ok',
  'project:tiic-rag': 'no_debug',
  'workspace:git-version-guide': 'empty',
  'workspace:system-innovation-notes': 'no_debug',
}

const ChatPageContainer = ({ conversationId, onTopbarActionsChange }: ChatPageContainerProps) => {
  const services = useMemo(() => {
    if (USE_MOCK) {
      return {
        chatService: createMockChatService('ok'),
        evidenceService: createMockEvidenceService('ok'),
      }
    }

    return {
      chatService: createMockChatService('ok'),
      evidenceService: createMockEvidenceService('ok'),
    }
  }, [])

  const store = useMemo(() => createChatStore(services), [services])
  const state = useChatStore(store)
  const errorDrawerOpen = state.ui.notice?.level === 'error'
  const activeConversationId = conversationId ?? 'project:tiic_law_chat'
  const [unresolvableByConversation, setUnresolvableByConversation] = useState<
    Record<string, string | undefined>
  >({})
  const [hitsSourceByConversation, setHitsSourceByConversation] = useState<Record<string, string>>({})
  const [pageReplayOpenByConversation, setPageReplayOpenByConversation] = useState<Record<string, boolean>>({})

  const conversationMode = useMemo<ChatScenario>(() => {
    if (activeConversationId.startsWith('new:')) return 'empty'
    return conversationModeMap[activeConversationId] ?? 'ok'
  }, [activeConversationId])

  const activeHitsSource = hitsSourceByConversation[activeConversationId] ?? 'all'
  const activeUnresolvableCitation = unresolvableByConversation[activeConversationId]
  const activePageReplayOpen = pageReplayOpenByConversation[activeConversationId] ?? false

  useEffect(() => {
    store.toggleDrawer(false)
    void store.setMockMode(conversationMode)
  }, [conversationMode, store])

  const handleChangeHitsSource = useCallback(
    (source: string) => {
      setHitsSourceByConversation((prev) => ({ ...prev, [activeConversationId]: source }))
    },
    [activeConversationId],
  )

  const handleSelectCitation = useCallback(
    (nodeId: string) => {
      if (!nodeId || nodeId.trim().length === 0) {
        setUnresolvableByConversation((prev) => ({
          ...prev,
          [activeConversationId]: 'Citation locator unavailable.',
        }))
        store.toggleDrawer(true)
        const current = store.getState()
        store.setState({
          evidence: { ...current.evidence, nodePreview: undefined },
          evidenceState: {
            ...current.evidenceState,
            selectedNodeId: undefined,
            nodePreviewStatus: 'idle',
          },
        })
        return
      }
      setUnresolvableByConversation((prev) => ({ ...prev, [activeConversationId]: undefined }))
      store.selectCitation(nodeId)
    },
    [activeConversationId, store],
  )

  const handleChangeMockMode = useCallback(
    async (mode: ChatScenario) => {
      setHitsSourceByConversation((prev) => ({ ...prev, [activeConversationId]: 'all' }))
      setUnresolvableByConversation((prev) => ({ ...prev, [activeConversationId]: undefined }))
      setPageReplayOpenByConversation((prev) => ({ ...prev, [activeConversationId]: false }))
      await store.setMockMode(mode)
    },
    [activeConversationId, store],
  )

  const handleToggleEvidenceDrawer = useCallback(
    (open?: boolean) => {
      const nextOpen = open ?? !state.ui.drawerOpen
      if (!nextOpen) {
        setPageReplayOpenByConversation((prev) => ({ ...prev, [activeConversationId]: false }))
      }
      store.toggleDrawer(nextOpen)
    },
    [activeConversationId, state.ui.drawerOpen, store],
  )

  const handleOpenPageReplay = useCallback(() => {
    const preview = state.evidence.nodePreview
    if (!preview || preview.page === undefined) return
    setPageReplayOpenByConversation((prev) => ({ ...prev, [activeConversationId]: true }))
    void store.fetchPageReplay(preview.documentId, preview.page)
  }, [activeConversationId, state.evidence.nodePreview, store])

  const handleClosePageReplay = useCallback(() => {
    setPageReplayOpenByConversation((prev) => ({ ...prev, [activeConversationId]: false }))
  }, [activeConversationId])

  const handleInjectError = useCallback(() => {
    store.raiseNotice(new Error('Injected error'))
  }, [store])

  const topbarActions = useMemo<ChatTopbarActions>(
    () => ({
      mockMode: state.ui.mockMode,
      drawerOpen: state.ui.drawerOpen,
      onChangeMockMode: handleChangeMockMode,
      onInjectError: handleInjectError,
      onToggleEvidence: handleToggleEvidenceDrawer,
    }),
    [handleChangeMockMode, handleInjectError, handleToggleEvidenceDrawer, state.ui.drawerOpen, state.ui.mockMode],
  )

  useEffect(() => {
    onTopbarActionsChange?.(topbarActions)
  }, [onTopbarActionsChange, topbarActions])

  const baseHits = state.evidence.retrievalHits
  const baseAvailableSources = baseHits.availableSources ?? []
  const baseSource = activeHitsSource === 'all' ? undefined : activeHitsSource
  const baseFiltered = baseSource ? baseHits.items.filter((item) => item.source === baseSource) : baseHits.items
  const resolvedHits: RetrievalHitsResult = {
    items: baseFiltered,
    total: baseFiltered.length,
    offset: 0,
    limit: baseFiltered.length,
    source: baseSource,
    availableSources: baseAvailableSources,
  }
  const resolvedStatus = baseHits.items.length > 0 ? 'loaded' : 'idle'

  return (
    <ChatPage
      chat={state.chat}
      evidence={state.evidence}
      retrievalHits={{
        items: resolvedHits.items,
        total: resolvedHits.total,
        source: resolvedHits.source,
        availableSources: resolvedHits.availableSources,
        status: resolvedStatus,
      }}
      ui={{
        drawerOpen: state.ui.drawerOpen,
        errorDrawerOpen,
        notice: state.ui.notice,
        selectedNodeId: state.evidenceState.selectedNodeId,
        nodePreviewStatus: state.evidenceState.nodePreviewStatus,
        pageReplayStatus: state.evidenceState.pageReplayStatus,
        pageReplay: state.evidenceState.pageReplay,
        pageReplayOpen: activePageReplayOpen && state.ui.drawerOpen,
        unresolvableCitation: activeUnresolvableCitation,
      }}
      onSend={store.sendUserMessage}
      onToggleDrawer={handleToggleEvidenceDrawer}
      onSelectCitation={handleSelectCitation}
      onSelectNode={store.fetchNodePreview}
      onChangeHitsSource={handleChangeHitsSource}
      onOpenPageReplay={handleOpenPageReplay}
      onClosePageReplay={handleClosePageReplay}
      onDismissNotice={store.dismissNotice}
    />
  )
}

export default ChatPageContainer
