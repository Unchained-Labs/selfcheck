import { useEffect, useMemo, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { engineLabel, isRunning, MODE_LABEL } from '../lib/labels'
import type { Comparison, EngineId, Finding, Mode, Note, Review, Run, Status } from '../lib/types'
import { Icon, Spinner } from './Icon'

const loc = (f: { file_path: string; line_start: number | null }) =>
  f.file_path ? `${f.file_path}${f.line_start ? `:${f.line_start}` : ''}` : 'general'

/** Another engine reviews the same PR. Its findings never replace yours;
 *  they are lined up against them, so agreement is visible and anything
 *  only it noticed can be adopted with one click. */
export function SecondOpinion({
  review, status, runs, current, onChanged,
}: {
  review: Review
  status: Status | null
  runs: Run[]
  current: Run
  onChanged: () => void
}) {
  const others = useMemo(
    () => (status?.engines ?? []).filter((e) => e.available && e.id !== current.engine),
    [status, current.engine],
  )
  const [engine, setEngine] = useState<EngineId | ''>('')
  const [mode, setMode] = useState<Mode>((current.mode as Mode) || 'normal')
  const [cmp, setCmp] = useState<Comparison | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [adopted, setAdopted] = useState<Set<number>>(new Set())

  const latest = runs.find((r) => r.kind === 'second_opinion')
  const running = isRunning(latest?.status)
  const chosen = engine || others[0]?.id || ''

  useEffect(() => {
    api.compare(review.id).then(setCmp).catch(() => setCmp(null))
  }, [review.id, latest?.id, latest?.status])

  useEffect(() => {
    if (!running) return
    const t = window.setInterval(onChanged, 4000)
    return () => window.clearInterval(t)
  }, [running, onChanged])

  const start = async () => {
    if (!chosen) return
    setBusy(true)
    setError('')
    try {
      await api.secondOpinion(review.id, { engine: chosen as EngineId, mode })
      onChanged()
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const adopt = async (f: Finding, i: number) => {
    await api.addNote(review.id, {
      file: f.file_path, line_start: f.line_start, line_end: f.line_end, side: f.side,
      severity: f.severity, category: f.category, title: f.title,
      body: `${f.body}\n\n_Raised by a second opinion (${engineLabel(cmp?.run?.engine ?? '', status)})._`,
    })
    setAdopted((s) => new Set(s).add(i))
    onChanged()
  }

  const result = cmp?.run && cmp.run.status === 'done' ? cmp : null
  const primary = engineLabel(current.engine, status)
  const second = result ? engineLabel(result.run!.engine, status) : ''

  return (
    <div className="card second-opinion">
      <h3><Icon name="cpu" size={14} /> Second opinion</h3>
      <p className="muted so-intro">
        Have another engine review the same change. Findings both engines raise are rarely noise;
        anything only one of them noticed is worth a second look.
      </p>

      <div className="so-controls">
        {others.length ? (
          <>
            <select className="input sm" value={chosen} onChange={(e) => setEngine(e.target.value as EngineId)} aria-label="Engine">
              {others.map((e) => <option key={e.id} value={e.id}>{e.label}</option>)}
            </select>
            <div className="seg sm">
              {(['light', 'normal', 'thorough'] as Mode[]).map((m) => (
                <button key={m} className={mode === m ? 'on' : ''} onClick={() => setMode(m)}>{MODE_LABEL[m]}</button>
              ))}
            </div>
            <button className="btn sm primary" disabled={busy || running} onClick={start}>
              {running || busy ? <Spinner size={12} /> : <Icon name="play" size={12} />}
              {running ? 'Running…' : result ? 'Run again' : 'Get a second opinion'}
            </button>
          </>
        ) : (
          <span className="faint">Set up a second engine in Settings to compare against {primary}.</span>
        )}
      </div>
      {error && <div className="inline-err">{error}</div>}
      {latest?.status === 'failed' && !running && <div className="inline-err">The last second opinion failed: {latest.error}</div>}

      {result && (
        <div className="so-result">
          <div className="so-meter" title={`${Math.round((result.agreement ?? 0) * 100)}% of all distinct findings were raised by both`}>
            <span className="so-meter-label"><strong>{Math.round((result.agreement ?? 0) * 100)}%</strong> agreement</span>
            <span className="so-bar">
              <span className="so-both" style={{ flex: result.agreed?.length ?? 0 }} />
              <span className="so-ours" style={{ flex: result.only_ours?.length ?? 0 }} />
              <span className="so-theirs" style={{ flex: result.only_theirs?.length ?? 0 }} />
            </span>
            <span className="viz-legend">
              <span className="viz-legend-item"><span className="viz-swatch so-both" />Both · {result.agreed?.length}</span>
              <span className="viz-legend-item"><span className="viz-swatch so-ours" />Only {primary} · {result.only_ours?.length}</span>
              <span className="viz-legend-item"><span className="viz-swatch so-theirs" />Only {second} · {result.only_theirs?.length}</span>
            </span>
          </div>

          {!!result.agreed?.length && (
            <details open>
              <summary>Both found ({result.agreed.length})</summary>
              <ul className="so-list">
                {result.agreed.map((a) => (
                  <li key={a.ours.id}><span className={`sev-pill sev-${a.ours.severity}`}>{a.ours.severity}</span> {a.ours.title} <span className="faint mono">{loc(a.ours)}</span></li>
                ))}
              </ul>
            </details>
          )}
          {!!result.only_theirs?.length && (
            <details open>
              <summary>Only {second} found ({result.only_theirs.length})</summary>
              <ul className="so-list">
                {result.only_theirs.map((f, i) => (
                  <li key={i}>
                    <span className={`sev-pill sev-${f.severity}`}>{f.severity}</span> {f.title} <span className="faint mono">{loc(f)}</span>
                    {adopted.has(i)
                      ? <span className="clean"><Icon name="check" size={11} /> added</span>
                      : <button className="btn xs" onClick={() => void adopt(f, i)} title="Add this finding to your notes">Add to notes</button>}
                    {f.body && <p className="so-body">{f.body.split('\n')[0].replace(/\*\*/g, '').slice(0, 220)}</p>}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {!!result.only_ours?.length && (
            <details>
              <summary>Only {primary} found ({result.only_ours.length})</summary>
              <ul className="so-list">
                {result.only_ours.map((n: Note) => (
                  <li key={n.id}><span className={`sev-pill sev-${n.severity}`}>{n.severity}</span> {n.title} <span className="faint mono">{loc(n)}</span></li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  )
}
