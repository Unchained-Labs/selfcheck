import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './lib/api'
import { copyText } from './lib/clipboard'
import { notesToMarkdown } from './lib/noteText'
import { timeAgo } from './lib/time'
import { apply, loadPref, onSystemChange, resolve, savePref, type Theme, type ThemePref } from './lib/theme'
import { effectiveChoice, engineLabel, findEngine, forgeName, isRunning } from './lib/labels'
import type {
  DiffPayload, EngineId, Mode, Note, Review, ReviewDetail, Severity, Status, Wakeup,
} from './lib/types'
import { AddDialog } from './components/AddBar'
import { CopyButton } from './components/CopyButton'
import { DiffView, type DiffViewOptions } from './components/DiffView'
import { FilePane } from './components/FilePane'
import { Icon } from './components/Icon'
import { NoteComposer } from './components/NoteComposer'
import { NotesPane } from './components/NotesPane'
import { Overview } from './components/Overview'
import { ReviewButton } from './components/ReviewButton'
import { RunBar } from './components/RunBar'
import { ShortcutsOverlay } from './components/ShortcutsOverlay'
import { ReviewsPage } from './components/ReviewsPage'
import { SettingsPage } from './components/SettingsPage'
import { Sidebar, type Page, type View } from './components/Sidebar'
import { fromQuery, toQuery, type ReviewFilters } from './lib/filters'
import * as notify from './lib/notify'
import { SummaryPane } from './components/SummaryPane'
import { WakeupsPage } from './components/Wakeups'

type Tab = 'summary' | 'diff' | 'notes'

const SEVERITY_ORDER: Severity[] = ['blocker', 'major', 'minor', 'question', 'nit', 'praise']

const DEFAULT_OPTIONS: DiffViewOptions = {
  split: true,
  ignoreWhitespace: false,
  wordDiff: true,
  onlyWithNotes: false,
}

function loadOptions(): DiffViewOptions {
  try {
    const raw = localStorage.getItem('selfcheck.diffOptions')
    return raw ? { ...DEFAULT_OPTIONS, ...JSON.parse(raw) } : DEFAULT_OPTIONS
  } catch {
    return DEFAULT_OPTIONS
  }
}

const TABS: Tab[] = ['summary', 'diff', 'notes']

interface Route { view: View; id: string | null; tab: Tab; repo: string | null; filters: ReviewFilters }

/** Route shapes, so every page is linkable and survives a reload:
 *    #/                      home
 *    #/reviews?author=…      the review list, filtered
 *    #/wakeups[?repo=…]      wakeups, optionally focused on one repo
 *    #/settings
 *    #/r/<review id>[/<tab>] one review — a tab survives a reload, which
 *                            matters half way through a long diff */
function parseRoute(): Route {
  const hash = window.location.hash
  const base = { id: null, tab: 'summary' as Tab, repo: null, filters: {} }
  const w = /^#\/wakeups(?:\?repo=(.+))?$/.exec(hash)
  if (w) return { ...base, view: 'wakeups', repo: w[1] ? decodeURIComponent(w[1]) : null }
  const list = /^#\/reviews(\?.*)?$/.exec(hash)
  if (list) return { ...base, view: 'reviews', filters: fromQuery(list[1] ?? '') }
  if (/^#\/settings/.test(hash)) return { ...base, view: 'settings' }
  const m = /^#\/r\/([^/]+)(?:\/(\w+))?$/.exec(hash)
  if (!m) return { ...base, view: 'home' }
  const tab = TABS.includes(m[2] as Tab) ? (m[2] as Tab) : 'summary'
  return { ...base, view: 'review', id: decodeURIComponent(m[1]), tab }
}

/** "Since you were last here" means since your previous session ended — not
 *  since the last reload. A session ends after 30 minutes away. */
const SINCE_MARK = 'selfcheck.sinceMark'
const LAST_ACTIVE = 'selfcheck.lastActive'
const SESSION_GAP_MS = 30 * 60_000

function sessionMark(): string {
  try {
    const lastActive = localStorage.getItem(LAST_ACTIVE) ?? ''
    let mark = localStorage.getItem(SINCE_MARK) ?? ''
    if (!lastActive || Date.now() - Date.parse(lastActive) > SESSION_GAP_MS) {
      mark = lastActive          // a new session: changes since you last left
      localStorage.setItem(SINCE_MARK, mark)
    }
    localStorage.setItem(LAST_ACTIVE, new Date().toISOString())
    return mark
  } catch {
    return ''
  }
}

export function App() {
  const [reviews, setReviews] = useState<Review[]>([])
  const [wakeups, setWakeups] = useState<Wakeup[]>([])
  const [status, setStatus] = useState<Status | null>(null)
  const [view, setView] = useState<View>(() => parseRoute().view)
  const [focusRepo, setFocusRepo] = useState<string | null>(() => parseRoute().repo)
  const [filters, setFiltersState] = useState<ReviewFilters>(() => parseRoute().filters)
  const [lastSeen, setLastSeen] = useState<string>(sessionMark)
  const [activeId, setActiveId] = useState<string | null>(() => parseRoute().id)
  const [detail, setDetail] = useState<ReviewDetail | null>(null)
  const [diff, setDiff] = useState<DiffPayload | null>(null)
  const [tab, setTabState] = useState<Tab>(() => parseRoute().tab)
  const [options, setOptions] = useState<DiffViewOptions>(loadOptions)
  const [themePref, setThemePrefState] = useState<ThemePref>(loadPref)
  const [theme, setTheme] = useState<Theme>(() => resolve(loadPref()))
  const [activeFile, setActiveFile] = useState<string | null>(null)
  const [busy, setBusy] = useState('')
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null)
  const [generalComposer, setGeneralComposer] = useState(false)
  const [showShortcuts, setShowShortcuts] = useState(false)
  const [showAdd, setShowAdd] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const [pendingJump, setPendingJump] = useState<Note | null>(null)
  const [forceOpenFile, setForceOpenFile] = useState<string | null>(null)
  const findingIndex = useRef(-1)

  const flash = useCallback((text: string, err = false) => {
    setToast({ text, err })
    setTimeout(() => setToast(null), err ? 6000 : 2400)
  }, [])

  /* ── routing ─────────────────────────────────────────────────────────── */
  useEffect(() => {
    const onHash = () => {
      const r = parseRoute()
      setView(r.view)
      setFocusRepo(r.repo)
      setFiltersState(r.filters)
      setActiveId(r.id)
      setTabState(r.tab)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const refreshListRef = useRef<() => Promise<void>>(async () => undefined)
  const activeIdRef = useRef(activeId)
  activeIdRef.current = activeId

  const setTab = useCallback((next: Tab) => {
    setTabState(next)
    const id = activeIdRef.current
    if (id) {
      const target = `#/r/${encodeURIComponent(id)}${next === 'summary' ? '' : `/${next}`}`
      if (window.location.hash !== target) window.history.replaceState(null, '', target)
    }
  }, [])

  const select = useCallback((id: string) => {
    window.location.hash = `#/r/${encodeURIComponent(id)}`
    setView('review')
    setActiveId(id)
    setTabState('summary')
    setSidebarOpen(false)
  }, [])

  const navigate = useCallback((to: Page, repo?: string) => {
    window.location.hash = to === 'home' ? '#/'
      : to === 'wakeups' ? `#/wakeups${repo ? `?repo=${encodeURIComponent(repo)}` : ''}`
        : `#/${to}`
    setView(to)
    setFocusRepo(repo ?? null)
    if (to === 'reviews') setFiltersState({})
    setActiveId(null)
    setSidebarOpen(false)
  }, [])

  /** A review was just added from the bar or the dialog: show it. */
  const onAdded = useCallback((added: Review) => {
    void refreshListRef.current()
    select(added.id)
  }, [select])

  /** The Reviews tab with these filters — what every clickable number opens. */
  const openReviews = useCallback((next: ReviewFilters) => {
    window.location.hash = `#/reviews${toQuery(next)}`
    setView('reviews')
    setFiltersState(next)
    setActiveId(null)
    setSidebarOpen(false)
  }, [])

  // Typing in the search box should not stack history entries.
  const setFilters = useCallback((next: ReviewFilters) => {
    setFiltersState(next)
    window.history.replaceState(null, '', `#/reviews${toQuery(next)}`)
  }, [])

  // Keep "last active" current while the tab is open, so the next session
  // knows when this one ended.
  useEffect(() => {
    const touch = () => {
      try { localStorage.setItem(LAST_ACTIVE, new Date().toISOString()) } catch { /* private mode */ }
    }
    const t = window.setInterval(() => document.visibilityState === 'visible' && touch(), 60_000)
    window.addEventListener('pagehide', touch)
    return () => { window.clearInterval(t); window.removeEventListener('pagehide', touch) }
  }, [])

  const markSeen = useCallback(() => {
    const now = new Date().toISOString()
    try { localStorage.setItem(SINCE_MARK, now) } catch { /* private mode */ }
    setLastSeen(now)
  }, [])

  /* ── data ────────────────────────────────────────────────────────────── */
  const refreshList = useCallback(async () => {
    try {
      // Wakeups are secondary: an older server without them must not cost
      // you the review list.
      const [list, wakes] = await Promise.all([
        api.listReviews(),
        api.listWakeups().catch(() => [] as Wakeup[]),
      ])
      setReviews(list)
      setWakeups(wakes)
    } catch (e) {
      flash(`Could not list reviews: ${e instanceof Error ? e.message : e}`, true)
    }
  }, [flash])

  refreshListRef.current = refreshList

  useEffect(() => {
    void refreshList()
    void api.status().then(setStatus).catch(() => undefined)
  }, [refreshList])

  // Desktop notifications ride on the list refresh: a run seen in progress
  // that is now finished raises one (see lib/notify).
  useEffect(() => {
    notify.checkForNotifications(reviews, notify.loadLevel(), select)
  }, [reviews, select])

  // Status carries the spend against the caps; keep it fresh with the list.
  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.visibilityState === 'visible') void api.status().then(setStatus).catch(() => undefined)
    }, 60000)
    return () => window.clearInterval(t)
  }, [])

  // Wakeups and watches start runs on their own, so keep the list current
  // without a reload. Quiet while the tab is hidden.
  useEffect(() => {
    const t = window.setInterval(() => {
      if (document.visibilityState === 'visible') void refreshList()
    }, 20000)
    return () => window.clearInterval(t)
  }, [refreshList])

  const loadDetail = useCallback(async (id: string) => {
    try {
      const d = await api.getReview(id)
      setDetail(d)
      return d
    } catch (e) {
      flash(`Could not load review: ${e instanceof Error ? e.message : e}`, true)
      return null
    }
  }, [flash])

  useEffect(() => {
    if (!activeId) {
      setDetail(null)
      setDiff(null)
      return
    }
    setDetail(null)
    setDiff(null)
    setActiveFile(null)
    findingIndex.current = -1
    void loadDetail(activeId)
    void api.diff(activeId).then(setDiff).catch((e) => {
      flash(`Could not load diff: ${e instanceof Error ? e.message : e}`, true)
    })
  }, [activeId, loadDetail, flash])

  const refreshDetail = useCallback(() => {
    if (activeId) {
      void loadDetail(activeId)
      void refreshList()
    }
  }, [activeId, loadDetail, refreshList])

  /* ── options + theme ─────────────────────────────────────────────────── */
  const setOption = useCallback((patch: Partial<DiffViewOptions>) => {
    setOptions((prev) => {
      const next = { ...prev, ...patch }
      localStorage.setItem('selfcheck.diffOptions', JSON.stringify(next))
      return next
    })
  }, [])

  const setThemePref = useCallback((pref: ThemePref) => {
    setThemePrefState(pref)
    savePref(pref)
    const next = resolve(pref)
    apply(next)
    setTheme(next)
  }, [])

  // Following the OS: track it when it changes, e.g. at sunset.
  useEffect(() => {
    if (themePref !== 'system') return
    return onSystemChange(() => {
      const next = resolve('system')
      apply(next)
      setTheme(next)
    })
  }, [themePref])

  /** `t`: flip to the other theme and pin it. */
  const toggleTheme = useCallback(() => {
    setThemePref(theme === 'dark' ? 'light' : 'dark')
  }, [theme, setThemePref])

  /* ── derived ─────────────────────────────────────────────────────────── */
  const review = detail?.review ?? null
  const latestRun = detail?.latest_run ?? null
  const running = isRunning(latestRun?.status)
  const choice = effectiveChoice(review, status)
  const chosenEngine = findEngine(status, choice.engine)
  const notes: Note[] = useMemo(() => detail?.notes ?? [], [detail])
  const openNotes = useMemo(() => notes.filter((n) => n.status === 'open'), [notes])

  const viewedMap = useMemo(() => {
    const out: Record<string, boolean> = {}
    for (const [path, st] of Object.entries(detail?.file_states ?? {})) out[path] = !!st.viewed
    return out
  }, [detail])

  /** Findings in the order you would walk them: file order from the diff,
   *  then line order inside each file. */
  const findings = useMemo(() => {
    const order = new Map((diff?.files ?? []).map((f, i) => [f.path, i]))
    return openNotes
      .filter((n) => n.file_path)
      .slice()
      .sort((a, b) =>
        (order.get(a.file_path) ?? 1e9) - (order.get(b.file_path) ?? 1e9) ||
        (a.line_start ?? 0) - (b.line_start ?? 0))
  }, [openNotes, diff])

  const severityCounts = useMemo(() => {
    const out = {} as Record<Severity, number>
    for (const s of SEVERITY_ORDER) out[s] = 0
    for (const n of openNotes) out[n.severity] = (out[n.severity] ?? 0) + 1
    return out
  }, [openNotes])

  /* ── jumping to a finding ────────────────────────────────────────────── */
  const jumpToNote = useCallback((note: Note) => {
    setTab('diff')
    if (note.file_path) {
      setForceOpenFile(note.file_path)
      setActiveFile(note.file_path)
    }
    setPendingJump(note)
  }, [setTab])

  // The target file may not be rendered yet (rows mount lazily), so poll
  // briefly for the note's element rather than assuming it is already there.
  useEffect(() => {
    if (!pendingJump) return
    let cancelled = false
    let tries = 0
    const tick = () => {
      if (cancelled) return
      const el = document.getElementById(`note-${pendingJump.id}`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        el.classList.add('flash')
        window.setTimeout(() => el.classList.remove('flash'), 1400)
        setPendingJump(null)
        return
      }
      if (tries++ < 40) window.setTimeout(tick, 60)
      else setPendingJump(null)
    }
    tick()
    return () => { cancelled = true }
  }, [pendingJump])

  const stepFinding = useCallback((delta: number) => {
    if (!findings.length) {
      flash('No open findings')
      return
    }
    const next = (findingIndex.current + delta + findings.length * 2) % findings.length
    findingIndex.current = next
    jumpToNote(findings[next])
  }, [findings, jumpToNote, flash])

  /* ── actions ─────────────────────────────────────────────────────────── */
  const doSync = useCallback(async () => {
    if (!activeId) return
    setBusy('sync')
    try {
      const { head_changed } = await api.sync(activeId)
      await loadDetail(activeId)
      setDiff(await api.diff(activeId, head_changed))
      await refreshList()
      flash(head_changed ? 'New commits — existing notes marked stale' : 'Already up to date')
    } catch (e) {
      flash(`Sync failed: ${e instanceof Error ? e.message : e}`, true)
    } finally {
      setBusy('')
    }
  }, [activeId, loadDetail, refreshList, flash])

  const doReview = useCallback(async (pick?: { mode: Mode; engine: EngineId }) => {
    if (!activeId) return
    setBusy('run')
    try {
      await api.startRun(activeId, pick ?? {})
      await loadDetail(activeId)
      void refreshList()
      setTab('summary')
    } catch (e) {
      flash(`Could not start the review: ${e instanceof Error ? e.message : e}`, true)
    } finally {
      setBusy('')
    }
  }, [activeId, loadDetail, refreshList, flash, setTab])

  const saveDefaults = useCallback(async (pick: { mode: Mode | ''; engine: EngineId | '' }) => {
    if (!activeId) return
    try {
      await api.setFlags(activeId, pick)
      refreshDetail()
    } catch (e) {
      flash(`Could not save the defaults: ${e instanceof Error ? e.message : e}`, true)
    }
  }, [activeId, refreshDetail, flash])

  const toggleWatch = useCallback(async () => {
    if (!review) return
    await api.setFlags(review.id, { watch: !review.watch })
    refreshDetail()
  }, [review, refreshDetail])

  const copyAll = useCallback(async () => {
    if (!openNotes.length) {
      flash('No open notes to copy')
      return
    }
    const ok = await copyText(notesToMarkdown(openNotes))
    flash(ok === 'ok'
      ? `Copied ${openNotes.length} note${openNotes.length === 1 ? '' : 's'}`
      : 'The browser blocked the clipboard — use the Notes tab and copy manually', ok !== 'ok')
  }, [openNotes, flash])

  const doDelete = useCallback(async () => {
    if (!review) return
    if (!window.confirm(`Stop tracking ${review.project} #${review.number} and delete its notes?`)) return
    await api.deleteReview(review.id)
    window.location.hash = ''
    setActiveId(null)
    await refreshList()
  }, [review, refreshList])

  const toggleViewed = useCallback(async (path: string, isViewed: boolean) => {
    if (!activeId) return
    setDetail((d) => (d
      ? {
          ...d,
          file_states: {
            ...d.file_states,
            [path]: { file_path: path, viewed: isViewed ? 1 : 0, viewed_sha: d.review.head_sha },
          },
        }
      : d))
    if (isViewed && forceOpenFile === path) setForceOpenFile(null)
    try {
      await api.setFileViewed(activeId, path, isViewed)
    } catch {
      flash('Could not save the viewed state', true)
    }
  }, [activeId, flash, forceOpenFile])

  /* ── keyboard ────────────────────────────────────────────────────────── */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (/^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName) || el.isContentEditable)) return
      if (e.metaKey || e.ctrlKey || e.altKey) return

      if (e.key === 'Escape') {
        setShowShortcuts(false)
        setSidebarOpen(false)
        return
      }
      if (e.key === '?') { setShowShortcuts((s) => !s); e.preventDefault(); return }
      if (e.key === 'a') { setShowAdd(true); e.preventDefault(); return }
      if (!review) return

      switch (e.key) {
        case '1': setTab('summary'); break
        case '2': setTab('diff'); break
        case '3': setTab('notes'); break
        case 'u': setOption({ split: !options.split }); break
        case 'w': setOption({ ignoreWhitespace: !options.ignoreWhitespace }); break
        case 'd': setOption({ wordDiff: !options.wordDiff }); break
        case 'f': setOption({ onlyWithNotes: !options.onlyWithNotes }); break
        case 't': toggleTheme(); break
        case 'c': void copyAll(); break
        case 'n': stepFinding(1); break
        case 'p': stepFinding(-1); break
        case 'r': if (!running) void doReview(); break
        case 's': void doSync(); break
        case 'v':
          if (activeFile) void toggleViewed(activeFile, !viewedMap[activeFile])
          break
        case 'j':
        case 'k': {
          if (!diff?.files.length) return
          const idx = activeFile ? diff.files.findIndex((f) => f.path === activeFile) : -1
          const next = e.key === 'j'
            ? Math.min(diff.files.length - 1, idx + 1)
            : Math.max(0, idx - 1)
          setTab('diff')
          setActiveFile(diff.files[next]?.path ?? null)
          break
        }
        default:
          return
      }
      e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [
    options, diff, activeFile, running, review, viewedMap,
    doReview, doSync, setOption, setTab, toggleTheme, copyAll, stepFinding, toggleViewed,
  ])

  /* ── render ──────────────────────────────────────────────────────────── */
  const tabButton = (id: Tab, icon: string, label: string, count?: number) => (
    <button className={`tab ${tab === id ? 'active' : ''}`} onClick={() => setTab(id)}>
      <Icon name={icon} size={14} />
      {label}
      {count !== undefined && <span className="n">{count}</span>}
    </button>
  )

  return (
    <div className={`app ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <Sidebar
        reviews={reviews}
        wakeups={wakeups}
        activeId={activeId}
        status={status}
        themePref={themePref}
        view={view}
        onSelect={select}
        onThemePref={setThemePref}
        onNewReview={() => { setSidebarOpen(false); setShowAdd(true) }}
        onNavigate={navigate}
        onEngine={async (engine) => {
          try {
            await api.updateSettings({ engine })
            setStatus(await api.status())
            flash(`${engineLabel(engine, status)} is now the default engine`)
          } catch (e) {
            flash(`Could not switch engine: ${e instanceof Error ? e.message : e}`, true)
          }
        }}
      />
      <div
        className="sidebar-scrim"
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />

      <main className="main">
        {view !== 'review' && (
          <div className="mobile-bar">
            <button
              className="icon-btn"
              onClick={() => setSidebarOpen((s) => !s)}
              aria-label="Show tracked reviews"
            >
              <Icon name="menu" />
            </button>
            <span className="brand-name">selfcheck</span>
          </div>
        )}

        {view === 'home' && (
          <div className="scroller">
            <Overview
              reviews={reviews}
              wakeups={wakeups}
              status={status}
              lastSeen={lastSeen}
              onSeen={markSeen}
              onOpen={select}
              onFilter={openReviews}
              onNavigate={navigate}
              onAdded={onAdded}
              onShortcuts={() => setShowShortcuts(true)}
            />
          </div>
        )}

        {view === 'reviews' && (
          <div className="scroller">
            <ReviewsPage
              reviews={reviews}
              status={status}
              filters={filters}
              onFilters={setFilters}
              onOpen={select}
              onAdded={onAdded}
              onWakeup={(key) => navigate('wakeups', key)}
            />
          </div>
        )}

        {view === 'settings' && (
          <div className="scroller">
            <SettingsPage
              // Remount when the default changes elsewhere (the footer switcher).
              key={status?.default_engine}
              reviews={reviews}
              status={status}
              onChanged={() => void api.status().then(setStatus).catch(() => undefined)}
              flash={flash}
            />
          </div>
        )}

        {view === 'wakeups' && (
          <div className="scroller">
            <WakeupsPage
              wakeups={wakeups}
              reviews={reviews}
              status={status}
              focusRepo={focusRepo}
              onChanged={refreshList}
              onOpenReview={select}
              flash={flash}
            />
          </div>
        )}

        {view === 'review' && !review && (
          <div className="blank"><span className="spinner-wrap"><Icon name="pr" size={22} /></span> Loading…</div>
        )}

        {view === 'review' && review && (
          <>
            <header className="rev-head">
              <div className="crumbs">
                <button
                  className="icon-btn sidebar-toggle"
                  onClick={() => setSidebarOpen((s) => !s)}
                  aria-label="Show tracked reviews"
                  title="Tracked reviews"
                >
                  <Icon name="menu" />
                </button>
                <Icon name="repo" size={14} />
                <span className="crumb-repo truncate">
                  <span className="repo-ns">{review.namespace}/</span>{review.project}
                </span>
                <Icon name="chevron-right" size={12} className="faint" />
                <span className="mono">{review.provider === 'gitlab' ? '!' : '#'}{review.number}</span>
                <span className="spacer" />
                {review.provider === 'local' ? (
                  <span className="chip" title={review.url}><Icon name="branch" size={12} /> local branch</span>
                ) : (
                  <a className="btn ghost sm" href={review.url} target="_blank" rel="noreferrer">
                    {forgeName(review.provider)} <Icon name="external" size={12} />
                  </a>
                )}
              </div>

              <h1 className="rev-title" title={review.title}>{review.title || review.url}</h1>

              <div className="rev-meta">
                <span className={`state-pill ${review.draft ? 'draft' : review.state}`}>
                  <Icon name="pr" size={12} />
                  {review.draft ? 'draft' : review.state}
                </span>
                <span className="branches">
                  <span className="branch">{review.head_ref}</span>
                  <Icon name="arrow" size={12} className="faint" />
                  <span className="branch">{review.base_ref}</span>
                </span>
                <span>by <strong>{review.author}</strong></span>
                <span className="fstat">
                  <span className="a">+{review.additions}</span>{' '}
                  <span className="d">−{review.deletions}</span>{' '}
                  <span className="faint">· {review.changed_files} files</span>
                </span>
                <span className="mono faint" title="Head commit">{review.head_sha.slice(0, 8)}</span>
                {review.last_synced_at && (
                  <span className="faint" title={review.last_synced_at}>
                    synced {timeAgo(review.last_synced_at)}
                  </span>
                )}
              </div>

              <div className="rev-actions">
                {openNotes.length > 0 && (
                  <div className="row sev-summary" title="Open findings by severity">
                    {SEVERITY_ORDER.filter((s) => severityCounts[s] > 0).map((s) => (
                      <button
                        key={s}
                        className={`sev-chip sev-${s}`}
                        onClick={() => setTab('notes')}
                        title={`${severityCounts[s]} ${s} — open the Notes tab`}
                      >
                        <span className="dot" />{severityCounts[s]} {s}
                      </button>
                    ))}
                  </div>
                )}
                <span className="spacer" />
                <button
                  className="btn sm"
                  disabled={!!busy}
                  onClick={doSync}
                  title="Refetch from the forge (s)"
                >
                  <Icon name="sync" size={13} className={busy === 'sync' ? 'spinning' : ''} />
                  {busy === 'sync' ? 'Syncing…' : 'Sync'}
                </button>
                <button
                  className={`btn sm ${review.watch ? 'on' : ''}`}
                  onClick={toggleWatch}
                  title={review.watch
                    ? 'Watching: selfcheck re-reviews automatically when new commits land'
                    : 'Watch for new commits and re-review automatically'}
                >
                  <Icon name="eye" size={13} />
                  {review.watch ? 'Watching' : 'Watch'}
                </button>
                <CopyButton
                  className="btn sm"
                  label={`Copy ${openNotes.length} note${openNotes.length === 1 ? '' : 's'}`}
                  title="Copy every open note as markdown, grouped by file (c)"
                  text={() => notesToMarkdown(openNotes)}
                />
                <ReviewButton
                  review={review}
                  status={status}
                  running={running}
                  busy={!!busy}
                  hasRun={!!latestRun}
                  onRun={(pick) => void doReview(pick)}
                  onSaveDefaults={(pick) => void saveDefaults(pick)}
                />
                <button
                  className="icon-btn"
                  onClick={() => setShowShortcuts(true)}
                  title="Keyboard shortcuts (?)"
                  aria-label="Keyboard shortcuts"
                >
                  <Icon name="keyboard" />
                </button>
                <button
                  className="icon-btn danger"
                  onClick={doDelete}
                  title="Stop tracking this review"
                  aria-label="Stop tracking this review"
                >
                  <Icon name="trash" />
                </button>
              </div>
            </header>

            {running && latestRun && (
              <RunBar
                run={latestRun}
                engineName={engineLabel(latestRun.engine, status)}
                onFinished={refreshDetail}
              />
            )}

            {status && chosenEngine && !chosenEngine.available && !running && (
              <div className="banner err">
                <Icon name="alert" size={14} />
                {chosenEngine.label} is not available: {chosenEngine.error ?? 'unknown error'}.
                Pick another engine from the arrow on the Review button.
              </div>
            )}

            <nav className="tabs">
              {tabButton('summary', 'doc', 'Summary')}
              {tabButton('diff', 'file', 'Files', diff?.files.length ?? review.changed_files)}
              {tabButton('notes', 'note', 'Notes', openNotes.length)}
              <span className="spacer" />
              {tab === 'diff' && (
                <div className="row diff-opts">
                  {findings.length > 0 && (
                    <>
                      <span className="faint" style={{ fontSize: 11.5 }}>
                        {findings.length} finding{findings.length === 1 ? '' : 's'}
                      </span>
                      <button
                        className="icon-btn"
                        onClick={() => stepFinding(-1)}
                        title="Previous finding (p)"
                        aria-label="Previous finding"
                      >
                        <Icon name="arrow-up" size={14} />
                      </button>
                      <button
                        className="icon-btn"
                        onClick={() => stepFinding(1)}
                        title="Next finding (n)"
                        aria-label="Next finding"
                      >
                        <Icon name="arrow-down" size={14} />
                      </button>
                      <span className="divider" />
                    </>
                  )}
                  <div className="seg sm" role="group" aria-label="Diff layout">
                    <button className={options.split ? 'on' : ''} onClick={() => setOption({ split: true })} title="Split (u)">
                      Split
                    </button>
                    <button className={!options.split ? 'on' : ''} onClick={() => setOption({ split: false })} title="Unified (u)">
                      Unified
                    </button>
                  </div>
                  <button
                    className={`btn ghost sm ${options.wordDiff ? 'on' : ''}`}
                    onClick={() => setOption({ wordDiff: !options.wordDiff })}
                    title="Highlight what changed within a line (d)"
                  >
                    Word diff
                  </button>
                  <button
                    className={`btn ghost sm ${options.ignoreWhitespace ? 'on' : ''}`}
                    onClick={() => setOption({ ignoreWhitespace: !options.ignoreWhitespace })}
                    title="Hide whitespace-only changes (w)"
                  >
                    Ignore ws
                  </button>
                  <button
                    className={`btn ghost sm ${options.onlyWithNotes ? 'on' : ''}`}
                    onClick={() => setOption({ onlyWithNotes: !options.onlyWithNotes })}
                    title="Only files with open notes (f)"
                  >
                    Only flagged
                  </button>
                </div>
              )}
            </nav>

            {tab === 'summary' && (
              <div className="scroller">
                <SummaryPane
                  run={latestRun}
                  runs={detail?.runs ?? []}
                  review={review}
                  status={status}
                  notes={openNotes}
                  onNotesChanged={refreshDetail}
                  onReview={running ? undefined : () => void doReview()}
                />
              </div>
            )}

            {tab === 'diff' && (
              <div className="body">
                <FilePane
                  files={diff?.files ?? []}
                  notes={notes}
                  viewed={viewedMap}
                  activeFile={activeFile}
                  onPick={setActiveFile}
                  onToggleViewed={toggleViewed}
                />
                <div className="scroller">
                  {diff ? (
                    <DiffView
                      reviewId={review.id}
                      files={diff.files}
                      notes={notes}
                      viewed={viewedMap}
                      options={options}
                      theme={theme}
                      activeFile={activeFile}
                      forceOpenFile={forceOpenFile}
                      onToggleViewed={toggleViewed}
                      onNotesChanged={refreshDetail}
                    />
                  ) : (
                    <div className="blank">Loading diff…</div>
                  )}
                </div>
              </div>
            )}

            {tab === 'notes' && (
              <div className="scroller">
                <NotesPane
                  notes={notes}
                  onChanged={refreshDetail}
                  onJump={jumpToNote}
                  onAdd={() => setGeneralComposer(true)}
                />
              </div>
            )}

            {generalComposer && (
              <NoteComposer
                reviewId={review.id}
                file=""
                line={null}
                side="new"
                onClose={() => setGeneralComposer(false)}
                onSaved={() => { setGeneralComposer(false); refreshDetail() }}
              />
            )}
          </>
        )}
      </main>

      {showShortcuts && <ShortcutsOverlay onClose={() => setShowShortcuts(false)} />}
      {showAdd && (
        <AddDialog
          onClose={() => setShowAdd(false)}
          onAdded={onAdded}
          onWakeup={(key) => navigate('wakeups', key)}
        />
      )}
      {toast && (
        <div className={`toast ${toast.err ? 'err' : ''}`} role="status">
          <Icon name={toast.err ? 'alert' : 'check'} size={14} />
          {toast.text}
        </div>
      )}
    </div>
  )
}
