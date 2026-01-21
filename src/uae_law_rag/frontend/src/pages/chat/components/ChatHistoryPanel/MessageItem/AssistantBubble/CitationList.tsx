//docstring
// 职责: 引用列表的容器占位。
// 边界: 不合并、不重排 citation。
// 上游关系: AssistantBubble。
// 下游关系: EvidencePanel 联动由上层实现。
import type { CitationView } from '@/types/ui'

type CitationListProps = {
  citations: CitationView[]
  onClickCitation: (nodeId: string) => void
}

const CitationList = ({ citations, onClickCitation }: CitationListProps) => {
  const items =
    citations.length > 0
      ? citations
      : [
          { nodeId: 'nodeA', locator: {} },
          { nodeId: 'nodeB', locator: {} },
        ]

  const isResolvable = (citation: CitationView) => {
    const hasNodeId = Boolean(citation.nodeId && citation.nodeId.trim().length > 0)
    const locator = citation.locator
    const hasLocator = Boolean(locator && (locator.documentId || locator.page !== undefined))
    return hasNodeId && hasLocator
  }

  return (
    <div className="citation-list">
      <div className="citation-list__divider" aria-hidden="true" />
      <div className="citation-list__label">Citation List</div>
      <div className="citation-list__items">
        {items.map((citation, index) => {
          const resolvable = isResolvable(citation)
          const label = citation.nodeId?.trim() ? citation.nodeId : 'citation'
          return (
            <button
              key={`${citation.nodeId || 'citation'}-${index}`}
              type="button"
              className={`citation-list__item ${resolvable ? '' : 'citation-list__item--disabled'}`}
              aria-disabled={!resolvable}
              onClick={() => onClickCitation(citation.nodeId)}
            >
              {label}
              {!resolvable ? ' (unresolvable)' : ''}
            </button>
          )
        })}
      </div>
      <div className="citation-list__metrics">
        <div className="citation-list__metrics-title">Evaluation Metrics</div>
        <div className="citation-list__metrics-grid">
          <div className="citation-list__metric">
            <span>Recall</span>
            <span>-</span>
          </div>
          <div className="citation-list__metric">
            <span>Precision</span>
            <span>-</span>
          </div>
          <div className="citation-list__metric">
            <span>Relevance</span>
            <span>-</span>
          </div>
          <div className="citation-list__metric">
            <span>Accuracy</span>
            <span>-</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default CitationList
