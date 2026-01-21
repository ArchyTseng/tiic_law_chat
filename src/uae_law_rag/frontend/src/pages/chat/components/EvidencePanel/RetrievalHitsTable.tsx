//docstring
// 职责: 检索命中列表的展示容器。
// 边界: 不执行外拉查询，不自行排序。
// 上游关系: Evidence Drawer。
// 下游关系: NodePreview 联动由上层实现。
import type { HitRow } from '@/types/ui'

type LoadStatus = 'idle' | 'loading' | 'failed' | 'loaded'

type RetrievalHitsTableProps = {
  items: HitRow[]
  total: number
  source?: string
  availableSources: string[]
  status: LoadStatus
  onSelectRow: (nodeId: string) => void
  onChangeSource: (source: string) => void
}

const renderExcerpt = (excerpt?: string) => {
  if (!excerpt) return '-'
  return excerpt.length > 120 ? `${excerpt.slice(0, 120)}...` : excerpt
}

const RetrievalHitsTable = ({
  items,
  total,
  source,
  availableSources,
  status,
  onSelectRow,
  onChangeSource,
}: RetrievalHitsTableProps) => {
  const sourceValue = source ?? 'all'
  const sources = ['all', ...availableSources]

  return (
    <section className="retrieval-hits-table">
      <div className="retrieval-hits-table__header">
        <div className="retrieval-hits-table__meta">
          total {total} / source {sourceValue}
        </div>
        <label className="retrieval-hits-table__filter">
          <span>Source</span>
          <select value={sourceValue} onChange={(event) => onChangeSource(event.target.value)}>
            {sources.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
      </div>
      {status === 'loading' && <div className="retrieval-hits-table__state">Loading hits...</div>}
      {status === 'failed' && <div className="retrieval-hits-table__state">Failed to load hits.</div>}
      {status !== 'loading' && status !== 'failed' && items.length === 0 && (
        <div className="retrieval-hits-table__state">No retrieval hits.</div>
      )}
      {status !== 'loading' && status !== 'failed' && items.length > 0 && (
        <div className="retrieval-hits-table__table-wrapper">
          <table className="retrieval-hits-table__table">
            <thead>
              <tr>
                <th>nodeId</th>
                <th>source</th>
                <th>rank</th>
                <th>score</th>
                <th>page</th>
                <th>excerpt</th>
              </tr>
            </thead>
            <tbody>
              {items.map((row) => (
                <tr
                  key={row.nodeId}
                  className="retrieval-hits-table__row"
                  onClick={() => onSelectRow(row.nodeId)}
                >
                  <td>{row.nodeId}</td>
                  <td>{row.source ?? '-'}</td>
                  <td>{row.rank ?? '-'}</td>
                  <td>{row.score ?? '-'}</td>
                  <td>{row.page ?? '-'}</td>
                  <td>
                    <span className="retrieval-hits-table__excerpt">{renderExcerpt(row.excerpt)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

export default RetrievalHitsTable
