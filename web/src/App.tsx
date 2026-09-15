import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './lib/api'
import type {
  DiffPayload, Note, Review, ReviewDetail, Status,
} from './lib/types'
import { DiffView, type DiffViewOptions } from './components/DiffView'
import { FilePane } from './components/FilePane'
import { NoteCard } from './components/NoteCard'
import { NoteComposer } from './components/NoteComposer'
import { RunBar } from './components/RunBar'
import { Sidebar } from './components/Sidebar'
import { SummaryPane } from './components/SummaryPane'

type Tab = 'summary' | 'diff' | 'notes'

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
  const diffScroller = useRef<HTMLDivElement>(null)

  const flash = useCallback((text: string, err = false) => {
    setToast({ text, err })
    setTimeout(() => setToast(null), err ? 6000 : 2600)
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

  /* ── actions ─────────────────────────────────────────────────────────── */
  const review = detail?.review ?? null
  const latestRun = detail?.latest_run ?? null
  const running = latestRun && ['queued', 'preparing', 'analyzing'].includes(latestRun.status)

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
  }, [activeId, loadDetail, flash])

  const toggleWatch = useCallback(async () => {
    if (!review) return
    await api.setFlags(review.id, { watch: !review.watch })
    refreshDetail()
  }, [review, refreshDetail])

  const doExport = useCallback(async () => {
    if (!activeId) return
    try {
      const md = await api.exportMarkdown(activeId)
      await navigator.clipboard.writeText(md)
      flash('Review notes copied to the clipboard')
    } catch {
      window.open(api.exportUrl(activeId), '_blank')
    }
  }, [activeId, flash])

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
    try {
      await fetch(`/api/reviews/${activeId}/files/viewed`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ path, viewed: isViewed }),
      })
    } catch {
      flash('Could not save the viewed state', true)
    }
  }, [activeId, flash])

  /* ── derived ─────────────────────────────────────────────────────────── */
  const notes: Note[] = detail?.notes ?? []
  const openNotes = useMemo(() => notes.filter((n) => n.status === 'open'), [notes])
  const viewedMap = useMemo(() => {
    const out: Record<string, boolean> = {}
    for (const [path, st] of Object.entries(detail?.file_states ?? {})) out[path] = !!st.viewed
    return out
  }, [detail])

  const anchoredNotes = useMemo(
    () => [...openNotes].sort((a, b) => {
      const rank = { blocker: 0, major: 1, minor: 2, question: 3, nit: 4, praise: 5 } as const
      return rank[a.severity] - rank[b.severity] || a.file_path.localeCompare(b.file_path)
    }),
    [openNotes],
  )

  /* ── keyboard ────────────────────────────────────────────────────────── */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return
      if (e.metaKey || e.ctrlKey || e.altKey) return

      switch (e.key) {
        case 'u':
          setOption({ split: !options.split })
          break
        case 'w':
          setOption({ ignoreWhitespace: !options.ignoreWhitespace })
          break
        case 'f':
          setOption({ onlyWithNotes: !options.onlyWithNotes })
          break
        case '1': setTab('summary'); break
        case '2': setTab('diff'); break
        case '3': setTab('notes'); break
        case 'r':
          if (!running) void doReview()
          break
        case 's':
          void doSync()
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
  }, [options, diff, activeFile, running, doReview, doSync, setOption])

  /* ── render ──────────────────────────────────────────────────────────── */
  return (
    <div className="app">
      <Sidebar
        reviews={reviews}
        activeId={activeId}
        status={status}
        theme={theme}
        onSelect={select}
        onChanged={refreshList}
        onToggleTheme={toggleTheme}
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
            <p className="faint">
              Nothing is ever posted back to the forge — selfcheck only reads.
            </p>
            <p className="faint" style={{ fontSize: 11 }}>
              <kbd>1</kbd>/<kbd>2</kbd>/<kbd>3</kbd> tabs · <kbd>j</kbd>/<kbd>k</kbd> files ·{' '}
              <kbd>u</kbd> unified · <kbd>w</kbd> whitespace · <kbd>r</kbd> review · <kbd>s</kbd> sync
            </p>
          </div>
        )}

        {review && (
          <>
            <header className="rev-head">
              <div className="row">
                <span className="rev-title truncate" title={review.title}>{review.title || review.url}</span>
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
                <span className="spacer" />
                <button className="btn sm" disabled={!!busy} onClick={doSync}>
                  {busy === 'sync' ? 'Syncing…' : 'Sync'}
                </button>
                <button className="btn sm primary" disabled={!!busy || !!running} onClick={doReview}>
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
                <button className="btn sm" onClick={doExport} title="Copy review notes as markdown">
                  Copy notes
                </button>
                <button className="btn sm ghost danger" onClick={doDelete} title="Stop tracking">
                  ✕
                </button>
              </div>
            </header>

            {running && latestRun && (
              <RunBar run={latestRun} onFinished={refreshDetail} />
            )}

            {!status?.claude.available && status && (
              <div className="banner err">
                Claude Code CLI not available: {status.claude.error ?? 'unknown error'}
              </div>
            )}

            <nav className="tabs">
              <button className={`tab ${tab === 'summary' ? 'active' : ''}`} onClick={() => setTab('summary')}>
                Summary
              </button>
              <button className={`tab ${tab === 'diff' ? 'active' : ''}`} onClick={() => setTab('diff')}>
                Files
                <span className="n">{diff?.files.length ?? review.changed_files}</span>
              </button>
              <button className={`tab ${tab === 'notes' ? 'active' : ''}`} onClick={() => setTab('notes')}>
                Notes
                <span className="n">{openNotes.length}</span>
              </button>
              <span className="spacer" />
              {tab === 'diff' && (
                <div className="row" style={{ padding: '4px 0' }}>
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
                    title="Highlight what changed within a line"
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
                <SummaryPane run={latestRun} notes={notes.filter((n) => n.status === 'open')} onNotesChanged={refreshDetail} />
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
                <div className="scroller" ref={diffScroller}>
                  {diff ? (
                    <DiffView
                      reviewId={review.id}
                      files={diff.files}
                      notes={notes}
                      viewed={viewedMap}
                      options={options}
                      theme={theme}
                      activeFile={activeFile}
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
                <div className="pane">
                  <div className="row" style={{ marginBottom: 12 }}>
                    <h3 style={{ margin: 0 }}>{openNotes.length} open notes</h3>
                    <span className="spacer" />
                    <button className="btn sm" onClick={() => setGeneralComposer(true)}>
                      Add a note
                    </button>
                  </div>
                  {anchoredNotes.map((n) => (
                    <NoteCard key={n.id} note={n} onChanged={refreshDetail} showLocation />
                  ))}
                  {!anchoredNotes.length && (
                    <p className="muted">
                      No open notes. Resolved and dismissed ones stay in the export if you ask for them.
                    </p>
                  )}
                  {notes.some((n) => n.status !== 'open') && (
                    <>
                      <h3 style={{ marginTop: 24 }}>Closed</h3>
                      {notes.filter((n) => n.status !== 'open').map((n) => (
                        <NoteCard key={n.id} note={n} onChanged={refreshDetail} showLocation />
                      ))}
                    </>
                  )}
                </div>
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

      {toast && <div className={`toast ${toast.err ? 'err' : ''}`}>{toast.text}</div>}
    </div>
  )
}
