import { useMemo, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { timeAgo } from '../lib/time'
import type { Review, Status } from '../lib/types'

function stateChip(r: Review) {
  if (r.draft) return <span className="chip draft">draft</span>
  const cls = r.state === 'open' ? 'open' : r.state === 'merged' ? 'merged' : 'closed'
  return <span className={`chip ${cls}`}>{r.state}</span>
}

function severityDots(r: Review) {
  const c = r.counts
  if (!c || !c.open) return null
  const order = ['blocker', 'major', 'minor', 'nit', 'question', 'praise'] as const
  return (
    <span className="row" style={{ gap: 4 }}>
      {order
        .filter((s) => c[s] > 0)
        .map((s) => (
          <span key={s} className={`sev-${s}`} style={{ fontSize: 11 }} title={`${c[s]} ${s}`}>
            <span className="dot" /> {c[s]}
          </span>
        ))}
    </span>
  )
}

export function Sidebar({
  reviews, activeId, status, theme, onSelect, onChanged, onToggleTheme,
}: {
  reviews: Review[]
  activeId: string | null
  status: Status | null
  theme: 'light' | 'dark'
  onSelect: (id: string) => void
  onChanged: () => void
  onToggleTheme: () => void
}) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [reviewNow, setReviewNow] = useState(true)
  const [filter, setFilter] = useState('')

  const shown = useMemo(() => {
    const q = filter.trim().toLowerCase()
    if (!q) return reviews
    return reviews.filter((r) =>
      `${r.title} ${r.namespace}/${r.project} #${r.number} ${r.author}`.toLowerCase().includes(q))
  }, [reviews, filter])

  const add = async () => {
    const value = url.trim()
    if (!value) return
    setBusy(true)
    setError('')
    try {
      const { review } = await api.addReview(value, { review_now: reviewNow, watch: false })
      setUrl('')
      onChanged()
      onSelect(review.id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <div className="brand">
          selfcheck
          <span className="ro" title="selfcheck never writes to GitHub or GitLab">read only</span>
          <span className="spacer" />
          <button
            className="btn ghost sm"
            onClick={onToggleTheme}
            title="Toggle light / dark (t)"
            aria-label="Toggle light or dark theme"
          >
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </div>
        <input
          className="input"
          placeholder="Paste a PR or MR link…"
          value={url}
          disabled={busy}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && add()}
        />
        <div className="row">
          <label className="row faint" style={{ fontSize: 11, gap: 4, cursor: 'pointer' }}>
            <input
              type="checkbox"
              checked={reviewNow}
              onChange={(e) => setReviewNow(e.target.checked)}
            />
            review immediately
          </label>
          <span className="spacer" />
          <button className="btn primary sm" disabled={busy || !url.trim()} onClick={add}>
            {busy ? 'Adding…' : 'Add'}
          </button>
        </div>
        {error && <div className="banner err" style={{ borderRadius: 4, padding: '6px 8px' }}>{error}</div>}
      </div>

      {reviews.length > 5 && (
        <div style={{ padding: '6px 12px 0' }}>
          <input
            className="input"
            placeholder="Filter tracked reviews…"
            value={filter}
            aria-label="Filter tracked reviews"
            onChange={(e) => setFilter(e.target.value)}
          />
        </div>
      )}

      <div className="sidebar-list">
        {!reviews.length && (
          <p className="faint" style={{ padding: 12, textAlign: 'center', fontSize: 12 }}>
            Nothing tracked yet. Paste a pull request or merge request link above.
          </p>
        )}
        {reviews.length > 0 && !shown.length && (
          <p className="faint" style={{ padding: 12, textAlign: 'center', fontSize: 12 }}>
            No tracked review matches “{filter}”.
          </p>
        )}
        {shown.map((r) => (
          <button
            key={r.id}
            className={`rev-item ${r.id === activeId ? 'active' : ''}`}
            onClick={() => onSelect(r.id)}
          >
            <span className="t truncate" title={r.title}>{r.title || r.url}</span>
            <span className="s">
              <span className="mono truncate" title={`${r.namespace}/${r.project}`}>
                {r.project} #{r.number}
              </span>
              {stateChip(r)}
              {!!r.watch && <span title="Watching for new commits">👁</span>}
            </span>
            <span className="s">
              {severityDots(r) ?? <span className="faint">no notes yet</span>}
              <span className="spacer" />
              {r.latest_run && ['queued', 'preparing', 'analyzing'].includes(r.latest_run.status) ? (
                <span className="spin" title="Reviewing now">◴</span>
              ) : (
                <span className="faint" title={`Last synced ${r.last_synced_at || 'never'}`}>
                  {timeAgo(r.last_synced_at)}
                </span>
              )}
            </span>
          </button>
        ))}
      </div>

      <div className="sidebar-foot faint">
        {status ? (
          <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
            <span title={status.claude.version ?? status.claude.error}>
              {status.claude.available ? '● claude ready' : '○ claude unavailable'}
            </span>
            <span className="spacer" />
            {status.providers.filter((p) => p.token_configured).map((p) => (
              <span key={p.host} title={`${p.host}: token configured`}>{p.host.split('.')[0]}</span>
            ))}
          </div>
        ) : (
          <span>connecting…</span>
        )}
      </div>
    </aside>
  )
}
