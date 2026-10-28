import { useMemo, useState } from 'react'
import { applyFilters, describe, type ReviewFilters } from '../lib/filters'
import { engineLabel, isRunning, MODE_LABEL, nsLabel } from '../lib/labels'
import { timeAgo } from '../lib/time'
import type { Review, Severity, Status } from '../lib/types'
import { AddBar } from './AddBar'
import { Icon, Spinner } from './Icon'

const SEVS: Severity[] = ['blocker', 'major', 'minor', 'question', 'nit', 'praise']
const VERDICT: Record<string, string> = { looks_good: 'Looks good', comments: 'Comments', needs_work: 'Needs work' }
const TRIGGER: Record<string, string> = { manual: 'manual', watch: 'watch', schedule: 'wakeup', api: 'API / skill' }

type SortKey = 'reviewed' | 'added' | 'open' | 'serious' | 'repo' | 'author'

const reviewedAt = (r: Review) => r.latest_run?.created_at || ''

/** Every tracked PR, filterable. The dashboard links here with filters set. */
export function ReviewsPage({
  reviews, status, filters, onFilters, onOpen, onAdded, onWakeup,
}: {
  reviews: Review[]
  status: Status | null
  filters: ReviewFilters
  onFilters: (f: ReviewFilters) => void
  onOpen: (id: string) => void
  onAdded: (review: Review) => void
  onWakeup: (repoKey: string) => void
}) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: 'reviewed', desc: true })

  const shown = useMemo(() => {
    const val = (r: Review): string | number => {
      switch (sort.key) {
        case 'reviewed': return reviewedAt(r) || r.created_at
        case 'added': return r.created_at
        case 'open': return r.counts?.open ?? 0
        case 'serious': return (r.counts?.blocker ?? 0) * 100 + (r.counts?.major ?? 0)
        case 'repo': return `${r.namespace}/${r.project}#${String(r.number).padStart(8, '0')}`
        case 'author': return r.author.toLowerCase()
      }
    }
    return applyFilters(reviews, filters).sort((a, b) => {
      const x = val(a)
      const y = val(b)
      const c = typeof x === 'number' ? x - (y as number) : String(x).localeCompare(String(y))
      return sort.desc ? -c : c
    })
  }, [reviews, filters, sort])

  const chips = describe(filters, (k, v) => {
    switch (k) {
      case 'repo': return `repo ${v.split('/').slice(1).join('/')}`
      case 'author': return `by ${v}`
      case 'person': return `assigned or requested: ${v}`
      case 'severity': return `has open ${v}`
      case 'engine': return `engine ${engineLabel(v, status)}`
      case 'mode': return `depth ${MODE_LABEL[v as 'light'] ?? v}`
      case 'trigger': return `started by ${TRIGGER[v] ?? v}`
      case 'verdict': return VERDICT[v] ?? v
      case 'state': return v
      case 'source': return v === 'wakeup' ? 'brought in by a wakeup' : 'added by hand'
      case 'since': {
        const what = filters.event === 'added' ? 'added' : filters.event === 'reviewed' ? 'reviewed' : 'active'
        const from = new Date(v).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
        return filters.until
          ? `${what} on ${new Date(v).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}`
          : `${what} since ${from}`
      }
      default: return v
    }
  })

  const drop = (key: keyof ReviewFilters) => {
    const next = { ...filters }
    delete next[key]
    if (key === 'since') { delete next.until; delete next.event }
    onFilters(next)
  }

  const th = (key: SortKey, label: string, cls = '') => (
    <th className={`sortable ${cls} ${sort.key === key ? 'sorted' : ''}`}
      onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))}
      aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
      {label}{sort.key === key && <Icon name={sort.desc ? 'chevron-down' : 'chevron-up'} size={11} />}
    </th>
  )

  const quick: { label: string; f: ReviewFilters }[] = [
    { label: 'Open', f: { state: 'open' } },
    { label: 'Has blockers', f: { severity: 'blocker' } },
    { label: 'Needs work', f: { verdict: 'needs_work' } },
    { label: 'From wakeups', f: { source: 'wakeup' } },
  ]

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1><Icon name="pr" size={20} /> Reviews</h1>
          <p className="muted">Every pull request selfcheck tracks. Filter, sort, and open one to read its review.</p>
        </div>
      </header>

      <AddBar compact onAdded={onAdded} onWakeup={onWakeup} />

      <div className="filter-bar">
        <div className="input-icon search">
          <Icon name="search" size={14} />
          <input
            className="input"
            placeholder="Search title, repo, number or author…"
            value={filters.q ?? ''}
            onChange={(e) => onFilters({ ...filters, q: e.target.value || undefined })}
          />
        </div>
        <div className="quick-filters">
          {quick.map((q) => {
            const on = Object.entries(q.f).every(([k, v]) => filters[k as keyof ReviewFilters] === v)
            return (
              <button key={q.label} className={`btn sm ${on ? 'on' : ''}`}
                onClick={() => onFilters(on
                  ? Object.fromEntries(Object.entries(filters).filter(([k]) => !(k in q.f)))
                  : { ...filters, ...q.f })}>
                {q.label}
              </button>
            )
          })}
        </div>
      </div>

      {chips.length > 0 && (
        <div className="filter-chips">
          {chips.map((c) => (
            <button key={c.key} className="fchip" onClick={() => drop(c.key)} title="Remove this filter">
              {c.text} <Icon name="x" size={11} />
            </button>
          ))}
          <button className="btn ghost xs" onClick={() => onFilters({})}>Clear all</button>
        </div>
      )}

      <div className="dcard flush">
        <div className="list-count">
          <strong>{shown.length}</strong> of {reviews.length} pull request{reviews.length === 1 ? '' : 's'}
        </div>
        {shown.length ? (
          <div className="table-scroll">
            <table className="dtab rows">
              <thead>
                <tr>
                  <th />
                  {th('repo', 'Pull request')}
                  {th('author', 'Author')}
                  <th>Verdict</th>
                  {th('serious', 'Open findings')}
                  <th>Last run</th>
                  {th('reviewed', 'Reviewed', 'num')}
                  {th('added', 'Added', 'num')}
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => {
                  const run = r.latest_run
                  return (
                    <tr key={r.id} onClick={() => onOpen(r.id)} tabIndex={0}
                      onKeyDown={(e) => e.key === 'Enter' && onOpen(r.id)}>
                      <td><span className={`state-dot ${r.draft ? 'draft' : r.state}`} title={r.draft ? 'draft' : r.state} /></td>
                      <td className="pr-cell">
                        <span className="truncate pr-title">{r.title || r.url}</span>
                        <span className="faint pr-sub">{nsLabel(r)}/<b>{r.project}</b> #{r.number}{r.repo_watch_id && <> · <Icon name="alarm" size={11} /></>}</span>
                      </td>
                      <td>{r.author}</td>
                      <td>
                        {run && isRunning(run.status)
                          ? <span className="running-tag"><Spinner size={11} /> reviewing</span>
                          : run?.verdict ? <span className={`verdict-tag ${run.verdict}`}>{VERDICT[run.verdict]}</span>
                            : run?.status === 'failed' ? <span className="faint">failed</span>
                              : <span className="faint">—</span>}
                      </td>
                      <td>
                        {r.counts?.open ? (
                          <span className="sev-pills">
                            {SEVS.filter((s) => (r.counts?.[s] ?? 0) > 0).map((s) => (
                              <span key={s} className={`sev-pill sev-${s}`} title={`${r.counts![s]} ${s}`}>{r.counts![s]}</span>
                            ))}
                          </span>
                        ) : run?.status === 'done' ? <span className="clean"><Icon name="check" size={11} /> clean</span> : <span className="faint">—</span>}
                      </td>
                      <td className="faint">{run ? `${engineLabel(run.engine, status)} · ${MODE_LABEL[run.mode] ?? run.mode}` : '—'}</td>
                      <td className="num faint">{run ? timeAgo(run.created_at) : 'never'}</td>
                      <td className="num faint">{timeAgo(r.created_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="empty-inline">
            <Icon name="search" size={20} />
            <span>No pull request matches these filters.</span>
            <button className="btn sm" onClick={() => onFilters({})}>Clear filters</button>
          </div>
        )}
      </div>
    </div>
  )
}
