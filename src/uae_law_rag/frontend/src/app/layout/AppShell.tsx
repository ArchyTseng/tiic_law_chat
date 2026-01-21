//docstring
// 职责: 应用布局骨架，承载页面编排入口。
// 边界: 不包含业务请求与状态逻辑。
// 上游关系: src/app/App.tsx。
// 下游关系: 无（F0 工程壳占位）。

import ChatPageContainer, { type ChatTopbarActions } from '@/pages/chat/containers/ChatPageContainer'
import { useMemo, useState } from 'react'

const DEFAULT_NAV_ITEMS = [
  { id: 'project:tiic_law_chat', label: 'tiic_law_chat', group: 'Projects' },
  { id: 'project:tiic-rag', label: 'tiic-rag', group: 'Projects' },
  { id: 'workspace:git-version-guide', label: 'Git version guide', group: 'Workspace' },
  { id: 'workspace:system-innovation-notes', label: 'System innovation notes', group: 'Workspace' },
]
const DEFAULT_NAV_ID = 'project:tiic_law_chat'
const FALLBACK_NAV_ITEM = { id: 'fallback', label: 'Project', group: 'Projects' }

const AppShell = () => {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [navItems, setNavItems] = useState(DEFAULT_NAV_ITEMS)
  const [selectedNavId, setSelectedNavId] = useState(DEFAULT_NAV_ID)
  const [topbarActions, setTopbarActions] = useState<ChatTopbarActions | null>(null)
  const selectedNavItem = useMemo(
    () => navItems.find((item) => item.id === selectedNavId) ?? navItems[0] ?? FALLBACK_NAV_ITEM,
    [navItems, selectedNavId],
  )
  const conversationItems = navItems.filter((item) => item.group === 'Conversations')
  const projectItems = navItems.filter((item) => item.group === 'Projects')
  const workspaceItems = navItems.filter((item) => item.group === 'Workspace')

  const handleNewChat = () => {
    const nextIndex = navItems.filter((item) => item.group === 'Conversations').length + 1
    const nextItem = {
      id: `new:${Date.now()}`,
      label: `New chat ${nextIndex}`,
      group: 'Conversations',
    }
    setNavItems((prev) => [nextItem, ...prev])
    setSelectedNavId(nextItem.id)
  }

  return (
    <div className="app-shell" data-collapsed={sidebarCollapsed}>
      <aside className="app-shell__sidebar">
        <div className="sidebar__header">
          <button
            className="sidebar__toggle"
            type="button"
            aria-label="Toggle sidebar"
            onClick={() => setSidebarCollapsed((prev) => !prev)}
          >
            {sidebarCollapsed ? '>' : '<'}
          </button>
          <span className="sidebar__logo">UAE LAW RAG</span>
        </div>
        <div className="sidebar__search">
          <input className="sidebar__search-input" placeholder="Search" />
        </div>
        <button className="sidebar__new-chat" type="button" onClick={handleNewChat}>
          + New Chat
        </button>
        {conversationItems.length > 0 ? (
          <div className="sidebar__section">
            <div className="sidebar__label">Conversations</div>
            {conversationItems.map((item) => (
              <button
                key={item.id}
                className={`sidebar__item ${selectedNavId === item.id ? 'sidebar__item--active' : ''}`}
                type="button"
                onClick={() => setSelectedNavId(item.id)}
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null}
        <div className="sidebar__section">
          <div className="sidebar__label">Projects</div>
          {projectItems.map((item) => (
            <button
              key={item.id}
              className={`sidebar__item ${selectedNavId === item.id ? 'sidebar__item--active' : ''}`}
              type="button"
              onClick={() => setSelectedNavId(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div className="sidebar__section">
          <div className="sidebar__label">Workspace</div>
          {workspaceItems.map((item) => (
            <button
              key={item.id}
              className={`sidebar__item ${selectedNavId === item.id ? 'sidebar__item--active' : ''}`}
              type="button"
              onClick={() => setSelectedNavId(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </aside>
      <main className="app-shell__main">
        <header className="app-shell__topbar">
          <div>
            <div className="app-shell__title">{selectedNavItem.label}</div>
            <div className="app-shell__subtitle">{selectedNavItem.group}</div>
          </div>
          {topbarActions ? (
            <div className="app-shell__topbar-actions">
              <label className="chat-page__mode">
                <span>Mock Mode</span>
                <select
                  value={topbarActions.mockMode}
                  onChange={(event) =>
                    topbarActions.onChangeMockMode(
                      event.target.value as ChatTopbarActions['mockMode'],
                    )
                  }
                >
                  <option value="ok">Loaded</option>
                  <option value="no_debug">No debug</option>
                  <option value="empty">No run</option>
                  <option value="error">Service error</option>
                </select>
              </label>
              <button className="chat-page__action" type="button" onClick={topbarActions.onInjectError}>
                Inject Error
              </button>
              <button
                className="chat-page__action chat-page__action--primary"
                type="button"
                onClick={topbarActions.onToggleEvidence}
              >
                {topbarActions.drawerOpen ? 'Close Evidence' : 'Open Evidence'}
              </button>
            </div>
          ) : null}
        </header>
        <section className="app-shell__content">
          <div className="app-shell__window">
            <ChatPageContainer
              conversationId={selectedNavId}
              onTopbarActionsChange={setTopbarActions}
            />
          </div>
        </section>
      </main>
    </div>
  )
}

export default AppShell
