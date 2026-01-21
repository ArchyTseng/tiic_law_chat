//docstring
// 职责: 证据树展示容器，支持折叠/展开。
// 边界: 不请求数据，不推断证据关系。
// 上游关系: ChatPage。
// 下游关系: 无。
import type { EvidenceView } from '@/types/ui'
import type { EvidenceTreeNode } from '@/types/domain/evidence'
import { useState } from 'react'

type EvidencePanelProps = {
  evidence: EvidenceView
  onSelectNode: (nodeId: string) => void
}

const renderTree = (nodes: EvidenceTreeNode[], onSelectNode: (nodeId: string) => void) => {
  return (
    <ul className="evidence-tree">
      {nodes.map((node) => {
        const isLeaf = !node.children || node.children.length === 0
        return (
          <li key={node.id} className="evidence-tree__node">
            {isLeaf ? (
              <button
                type="button"
                className="evidence-tree__leaf"
                onClick={() => onSelectNode(node.id)}
              >
                {node.label}
              </button>
            ) : (
              <div className="evidence-tree__branch">{node.label}</div>
            )}
            {node.children && node.children.length > 0 && renderTree(node.children, onSelectNode)}
          </li>
        )
      })}
    </ul>
  )
}

const EvidencePanel = ({ evidence, onSelectNode }: EvidencePanelProps) => {
  const [treeOpen, setTreeOpen] = useState(false)
  const hasTree = Boolean(evidence.evidenceTree && evidence.evidenceTree.length > 0)

  return (
    <div className="evidence-panel__section">
      <button
        className="evidence-panel__toggle"
        type="button"
        onClick={() => setTreeOpen((prev) => !prev)}
      >
        Evidence Tree {treeOpen ? 'v' : '>'}
      </button>
      {treeOpen ? (
        hasTree ? (
          renderTree(evidence.evidenceTree ?? [], onSelectNode)
        ) : (
          <div className="evidence-panel__empty">No evidence tree available.</div>
        )
      ) : (
        <div className="evidence-panel__collapsed">Collapsed</div>
      )}
    </div>
  )
}

export default EvidencePanel
