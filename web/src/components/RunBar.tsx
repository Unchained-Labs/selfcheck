import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { MODE_LABEL } from '../lib/labels'
import type { Run, RunEvent } from '../lib/types'
import { Icon, Spinner } from './Icon'

const STEPS: { id: string; label: string }[] = [
  { id: 'sync', label: 'Metadata' },
  { id: 'diff', label: 'Diff' },
  { id: 'clone', label: 'Checkout' },
  { id: 'analyzing', label: 'Reading' },
]

/** Live progress for an in-flight run, fed by the server's SSE stream. */
export function RunBar({
  run, engineName, onFinished,
}: {
  run: Run
  engineName: string
  onFinished: () => void
}) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [phase, setPhase] = useState(run.phase || run.status)
  const [message, setMessage] = useState(run.progress)
  const logRef = useRef<HTMLDivElement>(null)
  const finishedRef = useRef(false)

  useEffect(() => {
    finishedRef.current = false
    const es = new EventSource(`/api/runs/${run.id}/events`)

    es.onmessage = (msg) => {
      let ev: RunEvent
      try {
        ev = JSON.parse(msg.data)
      } catch {
        return
      }
      if (ev.phase) setPhase(ev.phase)
      if (ev.kind === 'phase' && ev.message) setMessage(ev.message)
      setEvents((prev) => [...prev.slice(-80), ev])
      if (ev.kind === 'done' || ev.kind === 'failed' || ev.kind === 'cancelled') {
        if (!finishedRef.current) {
          finishedRef.current = true
          es.close()
          onFinished()
        }
      }
    }

    es.onerror = () => {
      // The stream ends when the run ends; fall back to a single poll so we
      // never leave the UI showing "analyzing" for a run that already stopped.
      es.close()
      void api.getRun(run.id).then(({ run: fresh }) => {
        if (['done', 'failed', 'cancelled'].includes(fresh.status) && !finishedRef.current) {
          finishedRef.current = true
          onFinished()
        }
      }).catch(() => undefined)
    }

    return () => es.close()
  }, [run.id, onFinished])

  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
  }, [events])

  const tools = events.filter((e) => e.kind === 'tool')
  const warns = events.filter((e) => e.kind === 'warn')
  const current = STEPS.findIndex((s) => s.id === phase)
  const queued = phase === 'queued'

  return (
    <div className="runbar">
      <div className="runbar-top">
        <Spinner size={15} />
        <strong>{queued ? 'Queued' : message || 'Working'}</strong>
        <span className="chip"><Icon name="cpu" size={12} /> {engineName}</span>
        <span className="chip"><Icon name="gauge" size={12} /> {MODE_LABEL[run.mode] ?? run.mode}</span>
        {tools.length > 0 && <span className="faint">{tools.length} file lookups</span>}
        <span className="spacer" />
        <button className="btn ghost sm" onClick={() => void api.cancelRun(run.id).then(onFinished)}>
          <Icon name="x" size={13} /> Cancel
        </button>
      </div>

      <ol className="steps" aria-label="Progress">
        {STEPS.map((s, i) => {
          const state = queued || current < i ? 'todo' : current === i ? 'now' : 'done'
          return (
            <li key={s.id} className={`step ${state}`}>
              <span className="step-mark">
                {state === 'done' ? <Icon name="check" size={11} /> : state === 'now' ? <span className="pulse" /> : null}
              </span>
              {s.label}
            </li>
          )
        })}
      </ol>

      {warns.map((w, i) => (
        <div key={i} className="run-warn"><Icon name="alert" size={13} /> {w.message}</div>
      ))}
      {tools.length > 0 && (
        <div className="runlog" ref={logRef}>
          {tools.slice(-30).map((t, i) => (
            <div key={i}>
              <span className="t">{t.tool}</span> {t.detail}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
