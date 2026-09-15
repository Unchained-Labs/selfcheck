import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Run, RunEvent } from '../lib/types'

const PHASE_LABEL: Record<string, string> = {
  queued: 'Queued',
  sync: 'Fetching pull request metadata',
  diff: 'Fetching the diff',
  clone: 'Preparing the read-only checkout',
  analyzing: 'Claude is reading the change',
  done: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
}

/** Live progress for an in-flight run, fed by the server's SSE stream. */
export function RunBar({ run, onFinished }: { run: Run; onFinished: () => void }) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [phase, setPhase] = useState(run.phase || run.status)
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

  return (
    <div className="runbar">
      <div className="row">
        <span className="spin">◴</span>
        <strong>{PHASE_LABEL[phase] ?? phase}</strong>
        {tools.length > 0 && (
          <span className="faint">· {tools.length} file lookups</span>
        )}
        <span className="spacer" />
        <button className="btn ghost sm" onClick={() => void api.cancelRun(run.id).then(onFinished)}>
          Cancel
        </button>
      </div>
      <div className="bar"><i /></div>
      {warns.map((w, i) => (
        <div key={i} className="banner warn" style={{ border: 0, padding: '2px 0' }}>{w.message}</div>
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
