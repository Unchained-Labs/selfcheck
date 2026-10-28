import { useEffect, useMemo, useRef, useState } from 'react'
import { engineLabel, isRunning, repoKey, scheduleLabel } from '../lib/labels'
import { timeAgo } from '../lib/time'
import type { ThemePref } from '../lib/theme'
import type { Review, Severity, Status, Wakeup } from '../lib/types'
import { Icon, Spinner } from './Icon'

const SEV_ORDER: Severity[] = ['blocker', 'major', 'minor', 'question', 'nit', 'praise']

export type View = 'home' | 'reviews' | 'wakeups' | 'settings' | 'review'
export type Page = Exclude<View, 'review'>

function stateClass(r: Review) {
  if (r.draft) return 'draft'
  return r.state === 'open' ? 'open' : r.state === 'merged' ? 'merged' : 'closed'
}

function SevPills({ r }: { r: Review }) {
  const c = r.counts
  if (!c || !c.open) return null
  return (
    <span className="sev-pills">
      {SEV_ORDER.filter((s) => c[s] > 0).slice(0, 3).map((s) => (
        <span key={s} className={`sev-pill sev-${s}`} title={`${c[s]} open ${s}`}>
          {c[s]}
        </span>
      ))}
    </span>
  )
}

interface Group {
  key: string
  namespace: string
  project: string
  host: string
  reviews: Review[]
  wakeup?: Wakeup
  latest: string
}

function loadCollapsed(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem('selfcheck.collapsedRepos') ?? '[]'))
  } catch {
    return new Set()
  }
}

const THEMES: { pref: ThemePref; icon: string; label: string }[] = [
  { pref: 'system', icon: 'monitor', label: 'Follow the system' },
  { pref: 'light', icon: 'sun', label: 'Light' },
  { pref: 'dark', icon: 'moon', label: 'Dark' },
]

/** When a PR was last reviewed, or added if never. Not `updated_at`: every
 *  background sync bumps that, which would make everything "just now". */
const lastUsed = (r: Review) => r.latest_run?.created_at || r.created_at || r.updated_at

export function Sidebar({
  reviews, wakeups, activeId, status, themePref, view,
  onSelect, onThemePref, onNavigate, onEngine, onNewReview,
}: {
  reviews: Review[]
  wakeups: Wakeup[]
  activeId: string | null
  status: Status | null
  themePref: ThemePref
  view: View
  onSelect: (id: string) => void
  onThemePref: (pref: ThemePref) => void
  onNavigate: (to: Page, focusRepo?: string) => void
  onEngine: (engine: string) => Promise<void>
  onNewReview: () => void
}) {
  const [filter, setFilter] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(loadCollapsed)

  const groups = useMemo(() => {
    const q = filter.trim().toLowerCase()
    const byKey = new Map<string, Group>()
    for (const r of reviews) {
      if (q && !`${r.title} ${r.namespace}/${r.project} #${r.number} ${r.author}`
        .toLowerCase().includes(q)) continue
      const key = repoKey(r)
      let g = byKey.get(key)
      if (!g) {
        g = { key, namespace: r.namespace, project: r.project, host: r.host, reviews: [], latest: '' }
        byKey.set(key, g)
      }
      g.reviews.push(r)
      if (lastUsed(r) > g.latest) g.latest = lastUsed(r)
    }
    for (const w of wakeups) {
      const g = byKey.get(repoKey(w))
      if (g) g.wakeup = w
    }
    // Repos and the PRs inside them both rank by last use.
    for (const g of byKey.values()) g.reviews.sort((a, b) => lastUsed(b).localeCompare(lastUsed(a)))
    return [...byKey.values()].sort((a, b) => b.latest.localeCompare(a.latest))
  }, [reviews, wakeups, filter])

  const toggleGroup = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      try { localStorage.setItem('selfcheck.collapsedRepos', JSON.stringify([...next])) } catch { /* private mode */ }
      return next
    })

  const activeWakeups = wakeups.filter((w) => w.enabled).length
  const defaultEngine = status?.engines.find((e) => e.id === status.default_engine)
  const readyEngines = status?.engines.filter((e) => e.available).length ?? 0

  return (
    <aside className="sidebar">
      <div className="sidebar-head">
        <div className="brand">
          <span className="logo" aria-hidden="true"><Icon name="check" size={14} /></span>
          <span className="brand-name">selfcheck</span>
          <span className="ro" title="selfcheck never writes to GitHub or GitLab">
            <Icon name="shield" size={11} /> read-only
          </span>
        </div>

        <button className="btn primary new-review" onClick={onNewReview} title="Review a PR, MR or local branch (a)">
          <Icon name="plus" size={14} /> New review <kbd>a</kbd>
        </button>

        <nav className="side-nav" aria-label="Main">
          <button className={`nav-item ${view === 'home' ? 'active' : ''}`} onClick={() => onNavigate('home')}
            aria-current={view === 'home' ? 'page' : undefined}>
            <Icon name="grid" /> Home
          </button>
          <button className={`nav-item ${view === 'reviews' ? 'active' : ''}`} onClick={() => onNavigate('reviews')}
            aria-current={view === 'reviews' ? 'page' : undefined}>
            <Icon name="pr" /> Reviews
            {reviews.length > 0 && <span className="nav-count muted-count">{reviews.length}</span>}
          </button>
          <button className={`nav-item ${view === 'wakeups' ? 'active' : ''}`} onClick={() => onNavigate('wakeups')}
            aria-current={view === 'wakeups' ? 'page' : undefined}>
            <Icon name="alarm" /> Wakeups
            {activeWakeups > 0 && <span className="nav-count">{activeWakeups}</span>}
          </button>
          <button className={`nav-item ${view === 'settings' ? 'active' : ''}`} onClick={() => onNavigate('settings')}
            aria-current={view === 'settings' ? 'page' : undefined}>
            <Icon name="settings" /> Settings
          </button>
        </nav>

      </div>

      {reviews.length > 4 && (
        <div className="side-filter">
          <div className="input-icon">
            <Icon name="search" size={14} />
            <input
              className="input sm"
              placeholder="Filter reviews…"
              value={filter}
              aria-label="Filter tracked reviews"
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
        </div>
      )}

      <div className="sidebar-list">
        {!reviews.length && (
          <p className="side-empty">
            Nothing tracked yet. Start with <strong>New review</strong> above, or set up a wakeup
            to pick new pull requests up from a repository.
          </p>
        )}
        {reviews.length > 0 && !groups.length && (
          <p className="side-empty">No tracked review matches “{filter}”.</p>
        )}

        {groups.map((g) => {
          const isCollapsed = collapsed.has(g.key) && !filter
          const busyCount = g.reviews.filter((r) => isRunning(r.latest_run?.status)).length
          return (
            <section key={g.key} className="repo-group">
              <div className="repo-head">
                <button
                  className="repo-toggle"
                  onClick={() => toggleGroup(g.key)}
                  aria-expanded={!isCollapsed}
                  title={`${g.host}/${g.namespace}/${g.project}`}
                >
                  <Icon name={isCollapsed ? 'chevron-right' : 'chevron-down'} size={13} />
                  <span className="repo-name">
                    <span className="repo-proj">{g.project}</span>
                    <span className="repo-ns">{g.namespace}</span>
                  </span>
                  {busyCount > 0 ? <Spinner size={11} /> : <span className="repo-count">{g.reviews.length}</span>}
                </button>
                <button
                  className={`icon-btn xs ${g.wakeup?.enabled ? 'wake-on' : ''}`}
                  onClick={() => onNavigate('wakeups', g.key)}
                  title={g.wakeup
                    ? `${g.wakeup.enabled ? 'Wakeup' : 'Paused wakeup'}: ${scheduleLabel(g.wakeup)}`
                    : 'Wake up for this repository on a schedule'}
                  aria-label="Repository wakeup"
                >
                  <Icon name="alarm" size={13} />
                </button>
              </div>

              {!isCollapsed && g.reviews.map((r) => (
                <button
                  key={r.id}
                  className={`rev-item ${r.id === activeId ? 'active' : ''}`}
                  onClick={() => onSelect(r.id)}
                >
                  <span className={`state-dot ${stateClass(r)}`} title={r.draft ? 'draft' : r.state} />
                  <span className="rev-body">
                    <span className="rev-line">
                      <span className="rev-num mono">#{r.number}</span>
                      <span className="t truncate" title={r.title}>{r.title || r.url}</span>
                    </span>
                    <span className="rev-sub">
                      <SevPills r={r} />
                      {!r.counts?.open && r.latest_run?.status === 'done' && (
                        <span className="clean"><Icon name="check" size={11} /> clean</span>
                      )}
                      {!r.latest_run && <span className="faint">not reviewed</span>}
                      {!!r.watch && <Icon name="eye" size={11} className="faint" title="Watching for new commits" />}
                      <span className="spacer" />
                      {isRunning(r.latest_run?.status) ? (
                        <span className="running"><Spinner size={11} /> reviewing</span>
                      ) : (
                        <span className="faint" title={`Last reviewed ${lastUsed(r)} · synced ${r.last_synced_at || 'never'}`}>
                          {timeAgo(lastUsed(r))}
                        </span>
                      )}
                    </span>
                  </span>
                </button>
              ))}
            </section>
          )
        })}
      </div>

      <div className="theme-row">
        <span className="faint">Theme</span>
        <div className="seg xs" role="radiogroup" aria-label="Theme">
          {THEMES.map((t) => (
            <button
              key={t.pref}
              role="radio"
              aria-checked={themePref === t.pref}
              className={themePref === t.pref ? 'on' : ''}
              onClick={() => onThemePref(t.pref)}
              title={`${t.label}${t.pref === 'system' ? '' : ' (t toggles)'}`}
            >
              <Icon name={t.icon} size={13} />
              <span>{t.pref === 'system' ? 'Auto' : t.label}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="sidebar-foot">
        {status ? (
          <EngineSwitcher status={status} onEngine={onEngine} onSettings={() => onNavigate('settings')}>
            <span className={`status-dot ${defaultEngine?.available ? 'ok' : 'bad'}`} />
            <span className="truncate" title={defaultEngine?.available ? defaultEngine.version : defaultEngine?.error}>
              {engineLabel(status.default_engine, status)}
              <span className="faint"> · {defaultEngine?.available ? 'default' : 'unavailable'}</span>
            </span>
            <span className="spacer" />
            <span className="faint">{readyEngines}/{status.engines.length}</span>
            <Icon name="chevron-up" size={12} className="faint" />
          </EngineSwitcher>
        ) : (
          <span className="faint">connecting…</span>
        )}
      </div>
    </aside>
  )
}

/** The default engine, switchable from anywhere: the footer opens a list. */
function EngineSwitcher({
  status, onEngine, onSettings, children,
}: {
  status: Status
  onEngine: (engine: string) => Promise<void>
  onSettings: () => void
  children: React.ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState('')
  const wrap = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false) }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => { window.removeEventListener('mousedown', onDown); window.removeEventListener('keydown', onKey) }
  }, [open])

  const pick = async (id: string) => {
    setBusy(id)
    try { await onEngine(id) } finally { setBusy(''); setOpen(false) }
  }

  return (
    <div className="engine-switch" ref={wrap}>
      <button className="engine-switch-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open}
        title="Switch the default review engine">
        {children}
      </button>
      {open && (
        <div className="popover up engine-menu" role="menu" aria-label="Default engine">
          <div className="pop-label">Default engine</div>
          {status.engines.map((e) => (
            <button key={e.id} role="menuitemradio" aria-checked={status.default_engine === e.id}
              className={`engine-row ${status.default_engine === e.id ? 'on' : ''}`}
              disabled={!e.available || !!busy} onClick={() => pick(e.id)}
              title={e.available ? e.read_only : e.error}>
              <span className={`status-dot ${e.available ? 'ok' : ''}`} />
              <span className="engine-name">{e.label}</span>
              <span className="engine-kind">{busy === e.id ? <Spinner size={11} /> : status.default_engine === e.id ? 'default' : ''}</span>
              <span className="engine-model mono">{e.available ? (e.model || 'default model') : 'not set up'}</span>
            </button>
          ))}
          <button className="btn ghost sm menu-foot" onClick={() => { setOpen(false); onSettings() }}>
            <Icon name="settings" size={13} /> Models and more in Settings
          </button>
        </div>
      )}
    </div>
  )
}
