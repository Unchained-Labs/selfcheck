import { useMemo, useState } from 'react'
import type { DiffFile, Note, Severity } from '../lib/types'

const SEV_RANK: Record<Severity, number> = {
  blocker: 0, major: 1, minor: 2, question: 3, nit: 4, praise: 5,
}

type Filter = 'all' | 'notes' | 'unviewed'

export function FilePane({
  files, notes, viewed, activeFile, onPick, onToggleViewed,
}: {
  files: DiffFile[]
  notes: Note[]
  viewed: Record<string, boolean>
  activeFile: string | null
  onPick: (path: string) => void
  onToggleViewed: (path: string, viewed: boolean) => void
}) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState<Filter>('all')

  const worstByFile = useMemo(() => {
    const map = new Map<string, { severity: Severity; count: number }>()
    for (const n of notes) {
      if (!n.file_path || n.status !== 'open') continue
      const cur = map.get(n.file_path)
      if (!cur) map.set(n.file_path, { severity: n.severity, count: 1 })
      else {
        cur.count += 1
        if (SEV_RANK[n.severity] < SEV_RANK[cur.severity]) cur.severity = n.severity
      }
    }
    return map
  }, [notes])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return files.filter((f) => {
      if (q && !f.path.toLowerCase().includes(q)) return false
      if (filter === 'notes' && !worstByFile.has(f.path)) return false
      if (filter === 'unviewed' && viewed[f.path]) return false
      return true
    })
  }, [files, query, filter, worstByFile, viewed])

  const viewedCount = files.filter((f) => viewed[f.path]).length

  return (
    <div className="filepane">
      <div className="filepane-head">
        <input
          className="input"
          placeholder="Filter files…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="row" style={{ gap: 4 }}>
          {(['all', 'notes', 'unviewed'] as Filter[]).map((f) => (
            <button
              key={f}
              className={`btn ghost sm ${filter === f ? 'on' : ''}`}
              onClick={() => setFilter(f)}
            >
              {f === 'all' ? 'All' : f === 'notes' ? 'With notes' : 'Unviewed'}
            </button>
          ))}
        </div>
        <div className="faint" style={{ fontSize: 11 }}>
          {viewedCount}/{files.length} viewed
        </div>
      </div>

      {shown.map((f) => {
        const worst = worstByFile.get(f.path)
        return (
          <button
            key={f.path}
            className={`fitem ${activeFile === f.path ? 'active' : ''} ${viewed[f.path] ? 'viewed' : ''}`}
            onClick={() => onPick(f.path)}
            title={f.path}
          >
            <input
              type="checkbox"
              checked={!!viewed[f.path]}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => onToggleViewed(f.path, e.target.checked)}
              title="Mark viewed"
            />
            {worst && (
              <span className={`sev-${worst.severity}`} title={`${worst.count} open note(s)`}>
                <span className="dot" />
              </span>
            )}
            <span className="fname" title={f.path}>
              {f.path.includes('/') && (
                <span className="fdir">{f.path.slice(0, f.path.lastIndexOf('/') + 1)}</span>
              )}
              <span className="fbase">{f.path.slice(f.path.lastIndexOf('/') + 1)}</span>
            </span>
            {worst && <span className="fcount">{worst.count}</span>}
            <span className="fstat">
              <span className="a">+{f.additions}</span> <span className="d">−{f.deletions}</span>
            </span>
          </button>
        )
      })}

      {!shown.length && (
        <p className="faint" style={{ padding: 12, fontSize: 12, textAlign: 'center' }}>
          No files match.
        </p>
      )}
    </div>
  )
}
