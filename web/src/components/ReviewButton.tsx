import { useEffect, useRef, useState } from 'react'
import { effectiveChoice, ENGINE_SHORT, MODE_ICON, MODE_LABEL } from '../lib/labels'
import type { EngineId, Mode, Review, Status } from '../lib/types'
import { Icon, Spinner } from './Icon'

const MODES: Mode[] = ['light', 'normal', 'thorough']

/** "Review" as a split button: the main half runs with this PR's usual depth
 *  and engine, the caret opens a picker for a one-off choice — which can also
 *  be saved as this PR's default. */
export function ReviewButton({
  review, status, running, busy, hasRun, onRun, onSaveDefaults,
}: {
  review: Review
  status: Status | null
  running: boolean
  busy: boolean
  hasRun: boolean
  onRun: (choice: { mode: Mode; engine: EngineId }) => void
  onSaveDefaults: (choice: { mode: Mode | ''; engine: EngineId | '' }) => void
}) {
  const current = effectiveChoice(review, status)
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<Mode>(current.mode)
  const [engine, setEngine] = useState<EngineId>(current.engine)
  const [remember, setRemember] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    setMode(current.mode)
    setEngine(current.engine)
    setRemember(false)
    const onDown = (e: MouseEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    window.addEventListener('mousedown', onDown)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onDown)
      window.removeEventListener('keydown', onKey)
    }
    // Reset the picker to the PR's current choice each time it opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const label = running ? 'Reviewing…' : hasRun ? 'Re-review' : 'Review'
  const disabled = busy || running
  const engines = status?.engines ?? []
  const chosen = engines.find((e) => e.id === engine)

  const go = () => {
    if (remember) {
      onSaveDefaults({
        mode: mode === status?.default_mode ? '' : mode,
        engine: engine === status?.default_engine ? '' : engine,
      })
    }
    setOpen(false)
    onRun({ mode, engine })
  }

  return (
    <div className="split" ref={wrap}>
      <button
        className="btn primary split-main"
        disabled={disabled}
        onClick={() => onRun(current)}
        title={`${label} — ${MODE_LABEL[current.mode]}, ${ENGINE_SHORT[current.engine]} (r)`}
      >
        {running ? <Spinner /> : <Icon name="sparkle" />}
        <span>{label}</span>
        <span className="split-meta">{MODE_LABEL[current.mode]} · {ENGINE_SHORT[current.engine]}</span>
      </button>
      <button
        className="btn primary split-caret"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        aria-label="Choose review depth and engine"
        aria-expanded={open}
        title="Choose depth and engine"
      >
        <Icon name="chevron-down" />
      </button>

      {open && (
        <div className="popover review-picker" role="dialog" aria-label="Review options">
          <div className="pop-section">
            <div className="pop-label">Depth</div>
            <div className="mode-cards">
              {MODES.map((m) => {
                const info = status?.modes.find((x) => x.id === m)
                return (
                  <button
                    key={m}
                    className={`mode-card ${mode === m ? 'on' : ''}`}
                    onClick={() => setMode(m)}
                    aria-pressed={mode === m}
                  >
                    <span className="mode-card-head">
                      <Icon name={MODE_ICON[m]} size={14} /> {MODE_LABEL[m]}
                    </span>
                    <span className="mode-card-desc">{info?.description}</span>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="pop-section">
            <div className="pop-label">Engine</div>
            <div className="engine-list">
              {engines.map((e) => (
                <button
                  key={e.id}
                  className={`engine-row ${engine === e.id ? 'on' : ''}`}
                  disabled={!e.available}
                  onClick={() => setEngine(e.id)}
                  aria-pressed={engine === e.id}
                  title={e.available ? e.read_only : e.error}
                >
                  <span className={`status-dot ${e.available ? 'ok' : ''}`} />
                  <span className="engine-name">{e.label}</span>
                  <span className="engine-kind">{e.kind === 'cli' ? 'local CLI' : e.local ? 'local API' : 'API'}</span>
                  <span className="engine-model mono">
                    {e.available ? (e.model || 'default model') : 'not set up'}
                  </span>
                </button>
              ))}
            </div>
            {chosen && (
              <p className="pop-note">
                <Icon name="shield" size={13} /> {chosen.read_only}
              </p>
            )}
          </div>

          <div className="pop-foot">
            <label className="check-label">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
              Make this the default for this {review.provider === 'github' ? 'PR' : 'MR'}
            </label>
            <span className="spacer" />
            <button className="btn primary" disabled={!chosen?.available} onClick={go}>
              <Icon name="play" size={13} /> Run
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
