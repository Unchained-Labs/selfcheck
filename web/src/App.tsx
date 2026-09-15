import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './lib/api'
import { copyText } from './lib/clipboard'
import { notesToMarkdown } from './lib/noteText'
import { timeAgo } from './lib/time'
import type { DiffPayload, Note, Review, ReviewDetail, Severity, Status } from './lib/types'
import { CopyButton } from './components/CopyButton'
import { DiffView, type DiffViewOptions } from './components/DiffView'
import { FilePane } from './components/FilePane'
import { NoteComposer } from './components/NoteComposer'
import { NotesPane } from './components/NotesPane'
import { RunBar } from './components/RunBar'
import { ShortcutsOverlay } from './components/ShortcutsOverlay'
import { Sidebar } from './components/Sidebar'
import { SummaryPane } from './components/SummaryPane'

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

/** Route shape: #/r/<review id>[/<tab>] — so a tab is linkable and survives a
 *  reload, which matters when you are half way through a long diff. */
function parseRoute(): { id: string | null; tab: Tab } {
  const m = /^#\/r\/([^/]+)(?:\/(\w+))?$/.exec(window.location.hash)
  if (!m) return { id: null, tab: 'summary' }
  const tab = TABS.includes(m[2] as Tab) ? (m[2] as Tab) : 'summary'
  return { id: decodeURIComponent(m[1]), tab }
}

export function App() {
  const [reviews, setReviews] = useState<Review[]>([])
  const [status, setStatus] = useState<Status | null>(null)
  const [activeId, setActiveId] = useState<string | null>(() => parseRoute().id)
  const [detail, setDetail] = useState<ReviewDetail | null>(null)
  const [diff, setDiff] = useState<DiffPayload | null>(null)
  const [tab, setTabState] = useState<Tab>(() => parseRoute().tab)
  const [options, setOptions] = useState<DiffViewOptions>(loadOptions)
  const [theme, setTheme] = useState<'light' | 'dark'>(
    () => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'),
  )
  const [activeFile, setActiveFile] = useState<string | null>(null)
  const [busy, setBusy] = useState('')
  const [toast, setToast] = useState<{ text: string; err?: boolean } | null>(null)
  const [generalComposer, setGeneralComposer] = useState(false)
  const [showShortcuts, setShowShortcuts] = useState(false)
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
      setActiveId(r.id)
      setTabState(r.tab)
    }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

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
    setActiveId(id)
    setTabState('summary')
    setSidebarOpen(false)
  }, [])

  /* ── data ────────────────────────────────────────────────────────────── */
  const refreshList = useCallback(async () => {
    try {
      setReviews(await api.listReviews())
    } catch (e) {
      flash(`Could not list reviews: ${e instanceof Error ? e.message : e}`, true)
    }
  }, [flash])

  useEffect(() => {
    void refreshList()
    void api.status().then(setStatus).catch(() => undefined)
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

  const toggleTheme = useCallback(() => {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark'
      document.documentElement.dataset.theme = next
      localStorage.setItem('selfcheck.theme', next)
      return next
    })
  }, [])

  /* ── derived ─────────────────────────────────────────────────────────── */
  const review = detail?.review ?? null
  const latestRun = detail?.latest_run ?? null
  const running = !!latestRun && ['queued', 'preparing', 'analyzing'].includes(latestRun.status)
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

  const doReview = useCallback(async () => {
    if (!activeId) return
    setBusy('run')
    try {
      await api.startRun(activeId)
      await loadDetail(activeId)
      setTab('summary')
    } catch (e) {
      flash(`Could not start the review: ${e instanceof Error ? e.message : e}`, true)
    } finally {
      setBusy('')
    }
  }, [activeId, loadDetail, flash, setTab])

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
  return (
    <div className={`app ${sidebarOpen ? 'sidebar-open' : ''}`}>
      <Sidebar
        reviews={reviews}
        activeId={activeId}
        status={status}
        theme={theme}
        onSelect={select}
        onChanged={refreshList}
        onToggleTheme={toggleTheme}
      />
      <div
        className="sidebar-scrim"
        onClick={() => setSidebarOpen(false)}
        aria-hidden="true"
      />

      <main className="main">
        {!review && (
          <div className="blank">
            <h2>selfcheck</h2>
            <p>
              Paste a GitHub pull request or GitLab merge request link on the left.
              <br />
              Claude reads the change against a read-only checkout and writes review notes here.
            </p>
            <p className="faint">Nothing is ever posted back to the forge — selfcheck only reads.</p>
            <button className="btn" onClick={() => setShowShortcuts(true)}>
              Keyboard shortcuts <kbd>?</kbd>
            </button>
          </div>
        )}

        {review && (
          <>
            <header className="rev-head">
              <div className="row">
                <button
                  className="btn ghost sm sidebar-toggle"
                  onClick={() => setSidebarOpen((s) => !s)}
                  aria-label="Show tracked reviews"
                  title="Tracked reviews"
                >
                  ☰
                </button>
                <span className="rev-title truncate" title={review.title}>
                  {review.title || review.url}
                </span>
                <span className="spacer" />
                <a className="btn sm" href={review.url} target="_blank" rel="noreferrer">
                  Open on {review.provider === 'github' ? 'GitHub' : 'GitLab'} ↗
                </a>
              </div>

              <div className="rev-meta">
                <span className={`chip ${review.state === 'open' ? 'open' : review.state === 'merged' ? 'merged' : 'closed'}`}>
                  {review.draft ? 'draft' : review.state}
                </span>
                <span className="mono">{review.namespace}/{review.project} #{review.number}</span>
                <span>
                  <span className="branch">{review.head_ref}</span>
                  {' → '}
                  <span className="branch">{review.base_ref}</span>
                </span>
                <span className="mono faint" title="Head commit">{review.head_sha.slice(0, 8)}</span>
                <span>by {review.author}</span>
                <span className="fstat">
                  <span className="a">+{review.additions}</span>{' '}
                  <span className="d">−{review.deletions}</span>{' '}
                  <span className="faint">in {review.changed_files} files</span>
                </span>
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
                <button className="btn sm" disabled={!!busy} onClick={doSync} title="Refetch from the forge (s)">
                  {busy === 'sync' ? 'Syncing…' : 'Sync'}
                </button>
                <button
                  className="btn sm primary"
                  disabled={!!busy || running}
                  onClick={doReview}
                  title="Have Claude read the change (r)"
                >
                  {running ? 'Reviewing…' : latestRun ? 'Re-review' : 'Review with Claude'}
                </button>
                <button
                  className={`btn sm ${review.watch ? 'on' : ''}`}
                  onClick={toggleWatch}
                  title={review.watch
                    ? 'Watching: selfcheck re-reviews automatically when new commits land'
                    : 'Watch for new commits and re-review automatically'}
                >
                  {review.watch ? '👁 Watching' : 'Watch'}
                </button>
                <CopyButton
                  className="btn sm"
                  label={`Copy ${openNotes.length} note${openNotes.length === 1 ? '' : 's'}`}
                  title="Copy every open note as markdown, grouped by file (c)"
                  text={() => notesToMarkdown(openNotes)}
                />
                <button
                  className="btn sm ghost"
                  onClick={() => setShowShortcuts(true)}
                  title="Keyboard shortcuts (?)"
                  aria-label="Keyboard shortcuts"
                >
                  ?
                </button>
                <button
                  className="btn sm ghost danger"
                  onClick={doDelete}
                  title="Stop tracking this review"
                  aria-label="Stop tracking this review"
                >
                  ✕
                </button>
              </div>
            </header>

            {running && latestRun && <RunBar run={latestRun} onFinished={refreshDetail} />}

            {status && !status.claude.available && (
              <div className="banner err">
                Claude Code CLI not available: {status.claude.error ?? 'unknown error'}
              </div>
            )}

            <nav className="tabs">
              <button className={`tab ${tab === 'summary' ? 'active' : ''}`} onClick={() => setTab('summary')}>
                Summary
              </button>
              <button className={`tab ${tab === 'diff' ? 'active' : ''}`} onClick={() => setTab('diff')}>
                Files<span className="n">{diff?.files.length ?? review.changed_files}</span>
              </button>
              <button className={`tab ${tab === 'notes' ? 'active' : ''}`} onClick={() => setTab('notes')}>
                Notes<span className="n">{openNotes.length}</span>
              </button>
              <span className="spacer" />
              {tab === 'diff' && (
                <div className="row diff-opts">
                  {findings.length > 0 && (
                    <>
                      <span className="faint" style={{ fontSize: 11 }}>
                        {findings.length} finding{findings.length === 1 ? '' : 's'}
                      </span>
                      <button
                        className="btn ghost sm"
                        onClick={() => stepFinding(-1)}
                        title="Previous finding (p)"
                        aria-label="Previous finding"
                      >
                        ↑
                      </button>
                      <button
                        className="btn ghost sm"
                        onClick={() => stepFinding(1)}
                        title="Next finding (n)"
                        aria-label="Next finding"
                      >
                        ↓
                      </button>
                      <span className="divider" />
                    </>
                  )}
                  <button
                    className={`btn ghost sm ${options.split ? 'on' : ''}`}
                    onClick={() => setOption({ split: !options.split })}
                    title="Split / unified (u)"
                  >
                    {options.split ? 'Split' : 'Unified'}
                  </button>
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
                  notes={openNotes}
                  onNotesChanged={refreshDetail}
                  onReview={running ? undefined : doReview}
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
                    <div className="blank"><span className="spin">◴</span> Loading diff…</div>
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
      {toast && <div className={`toast ${toast.err ? 'err' : ''}`}>{toast.text}</div>}
    </div>
  )
}
