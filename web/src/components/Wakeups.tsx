import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../lib/api'
import {
  engineLabel, forgeName, MODE_LABEL, prWord, repoKey, scheduleLabel, timeUntil,
} from '../lib/labels'
import { timeAgo } from '../lib/time'
import type { EngineId, Mode, OpenPull, Review, Status, Wakeup, WakeupSettings } from '../lib/types'
import { Icon, Spinner } from './Icon'

const CADENCES: { minutes: number; label: string }[] = [
  { minutes: 60, label: 'Hourly' },
  { minutes: 360, label: 'Every 6 hours' },
  { minutes: 720, label: 'Every 12 hours' },
  { minutes: 1440, label: 'Daily' },
  { minutes: 10080, label: 'Weekly' },
]

export function WakeupsPage({
  wakeups, reviews, status, focusRepo, onChanged, onOpenReview, flash,
}: {
  wakeups: Wakeup[]
  reviews: Review[]
  status: Status | null
  focusRepo: string | null
  onChanged: () => void
  onOpenReview: (id: string) => void
  flash: (text: string, err?: boolean) => void
}) {
  const [editing, setEditing] = useState<Wakeup | 'new' | null>(null)
  const [prefill, setPrefill] = useState('')

  // Arriving from a repo's alarm icon: open its wakeup, or offer to make one.
  useEffect(() => {
    if (!focusRepo) return
    const existing = wakeups.find((w) => repoKey(w) === focusRepo)
    if (existing) {
      document.getElementById(`wake-${existing.id}`)?.scrollIntoView({ block: 'center' })
    } else {
      setPrefill(`https://${focusRepo}`)
      setEditing('new')
    }
    // Only when the focus changes, not on every refresh of the list.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusRepo])

  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1><Icon name="alarm" size={20} /> Wakeups</h1>
          <p className="muted">
            selfcheck checks these repositories on a schedule and reviews new pull requests as
            they appear. It only reads from the forge: nothing is ever posted back.
          </p>
        </div>
        <button className="btn primary" onClick={() => { setPrefill(''); setEditing('new') }}>
          <Icon name="plus" size={14} /> New wakeup
        </button>
      </header>

      {!wakeups.length && (
        <div className="empty-card">
          <Icon name="alarm" size={28} />
          <h2>No wakeups yet</h2>
          <p className="muted">
            Point one at a repository and pick a time — say, daily at 09:00 — and every new pull
            request is waiting for you already reviewed.
          </p>
          <button className="btn primary" onClick={() => { setPrefill(''); setEditing('new') }}>
            <Icon name="plus" size={14} /> Set one up
          </button>
        </div>
      )}

      <div className="wake-list">
        {wakeups.map((w) => (
          <WakeupCard
            key={w.id}
            wakeup={w}
            reviews={reviews}
            status={status}
            highlighted={focusRepo === repoKey(w)}
            onEdit={() => setEditing(w)}
            onChanged={onChanged}
            onOpenReview={onOpenReview}
            flash={flash}
          />
        ))}
      </div>

      {editing && (
        <WakeupForm
          wakeup={editing === 'new' ? null : editing}
          prefillUrl={prefill}
          status={status}
          onClose={() => setEditing(null)}
          onSaved={(msg) => { setEditing(null); onChanged(); flash(msg) }}
        />
      )}
    </div>
  )
}

function WakeupCard({
  wakeup: w, reviews, status, highlighted, onEdit, onChanged, onOpenReview, flash,
}: {
  wakeup: Wakeup
  reviews: Review[]
  status: Status | null
  highlighted: boolean
  onEdit: () => void
  onChanged: () => void
  onOpenReview: (id: string) => void
  flash: (text: string, err?: boolean) => void
}) {
  const [busy, setBusy] = useState('')
  const [pulls, setPulls] = useState<OpenPull[] | null>(null)
  const [showPulls, setShowPulls] = useState(false)

  const repoReviews = useMemo(
    () => reviews.filter((r) => repoKey(r) === repoKey(w)),
    [reviews, w],
  )

  const loadPulls = async () => {
    setBusy('pulls')
    try {
      setPulls(await api.wakeupPulls(w.id))
    } catch (e) {
      flash(`Could not list open ${prWord(w.provider)}s: ${e instanceof Error ? e.message : e}`, true)
    } finally {
      setBusy('')
    }
  }

  const togglePulls = () => {
    const next = !showPulls
    setShowPulls(next)
    if (next) void loadPulls()
  }

  const checkNow = async () => {
    setBusy('check')
    try {
      const res = await api.checkWakeup(w.id)
      onChanged()
      if (res.errors.length) flash(res.errors[0], true)
      else flash(res.started.length
        ? `Started ${res.started.length} review${res.started.length === 1 ? '' : 's'}`
        : `${res.open} open, nothing new to review`)
      if (showPulls) void loadPulls()
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true)
    } finally {
      setBusy('')
    }
  }

  const togglePaused = async () => {
    await api.updateWakeup(w.id, { enabled: !w.enabled })
    onChanged()
  }

  const remove = async () => {
    if (!window.confirm(`Stop waking up for ${w.namespace}/${w.project}? Reviews it already started are kept.`)) return
    await api.deleteWakeup(w.id)
    onChanged()
  }

  const track = async (p: OpenPull) => {
    setBusy(`track-${p.number}`)
    try {
      const { review } = await api.addReview(p.web_url, {
        review_now: true,
        mode: (w.mode || undefined) as Mode | undefined,
        engine: (w.engine || undefined) as EngineId | undefined,
      })
      onChanged()
      onOpenReview(review.id)
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true)
    } finally {
      setBusy('')
    }
  }

  const state = w.checking || busy === 'check' ? 'checking' : w.enabled ? 'active' : 'paused'

  return (
    <article id={`wake-${w.id}`} className={`wake-card ${highlighted ? 'highlight' : ''} ${w.enabled ? '' : 'paused'}`}>
      <div className="wake-top">
        <span className="wake-repo">
          <Icon name="repo" />
          <a href={w.url} target="_blank" rel="noreferrer">
<strong>{w.project}</strong>
          </a>
          <span className="faint truncate">{w.namespace} · {forgeName(w.provider)}{w.host.includes('.com') ? '' : ` · ${w.host}`}</span>
        </span>
        <span className={`pill pill-${state}`}>
          {state === 'checking' ? <Spinner size={11} /> : <span className="status-dot" />}
          {state}
        </span>
      </div>

      <div className="wake-schedule">
        <div className="wake-when">
          <Icon name="alarm" size={15} />
          <strong>{scheduleLabel(w)}</strong>
          {w.enabled && w.next_check_at && (
            <span className="muted" title={new Date(w.next_check_at).toLocaleString()}>
              · next {timeUntil(w.next_check_at)}
            </span>
          )}
        </div>
        <div className="muted wake-last">
          {w.last_checked_at
            ? <>Last checked {timeAgo(w.last_checked_at)} — {w.last_result || 'no result'}</>
            : 'Not checked yet'}
        </div>
        {w.last_error && <div className="inline-err mono">{w.last_error}</div>}
      </div>

      <div className="wake-chips">
        <span className="chip"><Icon name="gauge" size={12} /> {w.mode ? MODE_LABEL[w.mode] : `Default (${MODE_LABEL[status?.default_mode ?? 'normal']})`}</span>
        <span className="chip"><Icon name="cpu" size={12} /> {w.engine ? engineLabel(w.engine, status) : `Default (${engineLabel(status?.default_engine ?? 'claude', status)})`}</span>
        <span className="chip">max {w.max_per_check} per check</span>
        {!!w.rereview_on_push && <span className="chip"><Icon name="sync" size={12} /> re-review on push</span>}
        {!!w.include_drafts && <span className="chip">includes drafts</span>}
        {w.target_branch && <span className="chip"><Icon name="branch" size={12} /> into {w.target_branch}</span>}
        {w.authors && <span className="chip">by {w.authors}</span>}
        <span className="chip faint">{repoReviews.length} tracked</span>
      </div>

      <div className="wake-actions">
        <button className="btn sm" disabled={!!busy || w.checking} onClick={checkNow}>
          {busy === 'check' ? <Spinner size={12} /> : <Icon name="sync" size={13} />} Check now
        </button>
        <button className={`btn sm ${showPulls ? 'on' : ''}`} onClick={togglePulls}>
          <Icon name="pr" size={13} /> Open {prWord(w.provider)}s
        </button>
        <button className="btn sm" onClick={togglePaused}>
          <Icon name={w.enabled ? 'pause' : 'play'} size={13} /> {w.enabled ? 'Pause' : 'Resume'}
        </button>
        <button className="btn sm" onClick={onEdit}><Icon name="settings" size={13} /> Edit</button>
        <span className="spacer" />
        <button className="icon-btn danger" onClick={remove} title="Delete this wakeup" aria-label="Delete this wakeup">
          <Icon name="trash" size={14} />
        </button>
      </div>

      {showPulls && (
        <div className="pull-list">
          {busy === 'pulls' && !pulls && <div className="faint pull-empty"><Spinner /> Asking {forgeName(w.provider)}…</div>}
          {pulls && !pulls.length && <div className="faint pull-empty">No open {prWord(w.provider)}s.</div>}
          {pulls?.map((p) => (
            <div key={p.number} className="pull-row">
              <span className="mono faint">#{p.number}</span>
              <span className="truncate pull-title" title={p.title}>
                {p.draft && <span className="chip xs">draft</span>} {p.title}
              </span>
              <span className="faint pull-author">{p.author}</span>
              {p.review_id ? (
                <button className="btn xs" onClick={() => onOpenReview(p.review_id!)}>
                  Open <Icon name="arrow" size={11} />
                </button>
              ) : p.skip ? (
                <>
                  <span className="faint pull-skip">{p.skip}</span>
                  <button className="btn xs" disabled={!!busy} onClick={() => track(p)} title="Track and review it now anyway">
                    {busy === `track-${p.number}` ? <Spinner size={11} /> : 'Review'}
                  </button>
                </>
              ) : (
                <span className="pill pill-active xs">next check</span>
              )}
            </div>
          ))}
        </div>
      )}
    </article>
  )
}

function WakeupForm({
  wakeup, prefillUrl, status, onClose, onSaved,
}: {
  wakeup: Wakeup | null
  prefillUrl: string
  status: Status | null
  onClose: () => void
  onSaved: (message: string) => void
}) {
  const [url, setUrl] = useState(prefillUrl)
  const [provider, setProvider] = useState('')
  const [interval, setIntervalMinutes] = useState(wakeup?.interval_minutes ?? 1440)
  const [dailyAt, setDailyAt] = useState(wakeup ? wakeup.daily_at : '09:00')
  const [mode, setMode] = useState<Mode | ''>(wakeup?.mode ?? 'light')
  const [engine, setEngine] = useState<EngineId | ''>(wakeup?.engine ?? '')
  const [includeDrafts, setIncludeDrafts] = useState(!!wakeup?.include_drafts)
  const [rereview, setRereview] = useState(!!wakeup?.rereview_on_push)
  const [includeExisting, setIncludeExisting] = useState(false)
  const [branch, setBranch] = useState(wakeup?.target_branch ?? '')
  const [authors, setAuthors] = useState(wakeup?.authors ?? '')
  const [maxPer, setMaxPer] = useState(wakeup?.max_per_check ?? 3)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const daily = interval % 1440 === 0

  const save = async () => {
    setBusy(true)
    setError('')
    const settings: WakeupSettings = {
      interval_minutes: interval,
      daily_at: daily ? dailyAt : '',
      mode, engine,
      include_drafts: includeDrafts,
      rereview_on_push: rereview,
      target_branch: branch.trim(),
      authors: authors.trim(),
      max_per_check: maxPer,
    }
    try {
      if (wakeup) {
        await api.updateWakeup(wakeup.id, settings)
        onSaved('Wakeup updated')
      } else {
        const { wakeup: created } = await api.addWakeup(url.trim(), {
          ...settings, provider, include_existing: includeExisting,
        })
        onSaved(`Waking up for ${created.namespace}/${created.project} — ${scheduleLabel(created).toLowerCase()}`)
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide" role="dialog" aria-label={wakeup ? 'Edit wakeup' : 'New wakeup'}>
        <h2>
          <Icon name="alarm" size={16} />
          {wakeup ? <>Wakeup for <span className="mono">{wakeup.namespace}/{wakeup.project}</span></> : 'New wakeup'}
        </h2>
        <div className="content">
          {error && <div className="banner err">{error}</div>}

          {!wakeup && (
            <div className="field">
              <label htmlFor="wk-url">Repository</label>
              <div className="row">
                <input
                  id="wk-url"
                  className="input"
                  autoFocus
                  value={url}
                  placeholder="https://github.com/owner/repo  or  gl:group/project"
                  onChange={(e) => setUrl(e.target.value)}
                />
                <select className="input" style={{ width: 130 }} value={provider} onChange={(e) => setProvider(e.target.value)} aria-label="Forge">
                  <option value="">Auto-detect</option>
                  <option value="github">GitHub</option>
                  <option value="gitlab">GitLab</option>
                </select>
              </div>
              <span className="hint">A pull request link works too. Pick the forge only for a self-hosted host whose name says neither.</span>
            </div>
          )}

          <div className="form-grid">
            <div className="field">
              <label htmlFor="wk-cadence">How often</label>
              <select id="wk-cadence" className="input" value={interval} onChange={(e) => setIntervalMinutes(Number(e.target.value))}>
                {CADENCES.map((c) => <option key={c.minutes} value={c.minutes}>{c.label}</option>)}
                {!CADENCES.some((c) => c.minutes === interval) && <option value={interval}>Every {interval} min</option>}
              </select>
            </div>
            <div className="field">
              <label htmlFor="wk-at">At (server time)</label>
              <input
                id="wk-at"
                type="time"
                className="input"
                disabled={!daily}
                value={daily ? dailyAt : ''}
                onChange={(e) => setDailyAt(e.target.value)}
              />
            </div>
          </div>

          <div className="field">
            <label>Depth</label>
            <div className="seg full">
              {(['light', 'normal', 'thorough'] as Mode[]).map((m) => (
                <button key={m} className={mode === m ? 'on' : ''} onClick={() => setMode(m)}>{MODE_LABEL[m]}</button>
              ))}
              <button className={mode === '' ? 'on' : ''} onClick={() => setMode('')}>Default</button>
            </div>
            <span className="hint">{status?.modes.find((m) => m.id === (mode || status.default_mode))?.description}</span>
          </div>

          <div className="field">
            <label htmlFor="wk-engine">Engine</label>
            <select id="wk-engine" className="input" value={engine} onChange={(e) => setEngine(e.target.value as EngineId | '')}>
              <option value="">Default ({engineLabel(status?.default_engine ?? 'claude', status)})</option>
              {status?.engines.map((e) => (
                <option key={e.id} value={e.id} disabled={!e.available}>
                  {e.label}{e.available ? '' : ' — not set up'}
                </option>
              ))}
            </select>
          </div>

          <div className="form-grid">
            <div className="field">
              <label htmlFor="wk-branch">Only into branch</label>
              <input id="wk-branch" className="input" value={branch} placeholder="any" onChange={(e) => setBranch(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="wk-authors">Only by authors</label>
              <input id="wk-authors" className="input" value={authors} placeholder="anyone — or alice, bob" onChange={(e) => setAuthors(e.target.value)} />
            </div>
          </div>

          <div className="toggles">
            <label className="check-label">
              <input type="checkbox" checked={rereview} onChange={(e) => setRereview(e.target.checked)} />
              Re-review a tracked {prWord(wakeup?.provider ?? 'github')} when new commits land
            </label>
            <label className="check-label">
              <input type="checkbox" checked={includeDrafts} onChange={(e) => setIncludeDrafts(e.target.checked)} />
              Include drafts
            </label>
            {!wakeup && (
              <label className="check-label">
                <input type="checkbox" checked={includeExisting} onChange={(e) => setIncludeExisting(e.target.checked)} />
                Also review the ones already open (otherwise only new ones from now on)
              </label>
            )}
            <label className="check-label">
              At most
              <input
                type="number"
                className="input num"
                min={1}
                max={25}
                value={maxPer}
                onChange={(e) => setMaxPer(Math.max(1, Math.min(25, Number(e.target.value) || 1)))}
              />
              reviews per check — the rest wait for the next one
            </label>
          </div>
        </div>
        <div className="foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy || (!wakeup && !url.trim())} onClick={save}>
            {busy ? <Spinner size={12} /> : <Icon name="check" size={13} />}
            {wakeup ? 'Save' : 'Create wakeup'}
          </button>
        </div>
      </div>
    </div>
  )
}
