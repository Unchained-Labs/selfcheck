import { useMemo, useState } from 'react'
import { notesToMarkdown } from '../lib/noteText'
import type { Note, Severity } from '../lib/types'
import { CopyButton } from './CopyButton'
import { NoteCard } from './NoteCard'

const SEVERITIES: Severity[] = ['blocker', 'major', 'minor', 'nit', 'question', 'praise']
const RANK: Record<Severity, number> = {
  blocker: 0, major: 1, minor: 2, question: 3, nit: 4, praise: 5,
}

type Scope = 'open' | 'all'

export function NotesPane({
  notes, onChanged, onJump, onAdd,
}: {
  notes: Note[]
  onChanged: () => void
  onJump: (note: Note) => void
  onAdd: () => void
}) {
  const [scope, setScope] = useState<Scope>('open')
  const [severities, setSeverities] = useState<Set<Severity>>(new Set())
  const [query, setQuery] = useState('')

  const scoped = useMemo(
    () => (scope === 'open' ? notes.filter((n) => n.status === 'open') : notes),
    [notes, scope],
  )

  const counts = useMemo(() => {
    const out = {} as Record<Severity, number>
    for (const s of SEVERITIES) out[s] = 0
    for (const n of scoped) out[n.severity] = (out[n.severity] ?? 0) + 1
    return out
  }, [scoped])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    return scoped
      .filter((n) => (severities.size ? severities.has(n.severity) : true))
      .filter((n) =>
        !q ||
        n.title.toLowerCase().includes(q) ||
        n.body.toLowerCase().includes(q) ||
        n.file_path.toLowerCase().includes(q))
      .sort((a, b) =>
        RANK[a.severity] - RANK[b.severity] ||
        a.file_path.localeCompare(b.file_path) ||
        (a.line_start ?? 0) - (b.line_start ?? 0))
  }, [scoped, severities, query])

  const toggle = (s: Severity) =>
    setSeverities((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })

  const filtered = severities.size > 0 || query.trim().length > 0

  return (
    <div className="pane notes-pane">
      <div className="notes-toolbar">
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <div className="seg" role="group" aria-label="Which notes to show">
            <button
              className={scope === 'open' ? 'on' : ''}
              onClick={() => setScope('open')}
            >
              Open
            </button>
            <button
              className={scope === 'all' ? 'on' : ''}
              onClick={() => setScope('all')}
            >
              All
            </button>
          </div>

          <input
            className="input"
            style={{ maxWidth: 260 }}
            placeholder="Search notes…"
            value={query}
            aria-label="Search notes"
            onChange={(e) => setQuery(e.target.value)}
          />

          <span className="spacer" />

          <CopyButton
            className="btn sm primary"
            label={filtered ? `Copy ${shown.length} shown` : `Copy all ${shown.length}`}
            title="Copy these notes as markdown, grouped by file, ready to paste"
            text={() => notesToMarkdown(shown)}
          />
          <button className="btn sm" onClick={onAdd}>Add a note</button>
        </div>

        <div className="row sev-filters" style={{ flexWrap: 'wrap' }}>
          {SEVERITIES.filter((s) => counts[s] > 0).map((s) => (
            <button
              key={s}
              className={`sev-chip sev-${s} ${severities.has(s) ? 'on' : ''}`}
              onClick={() => toggle(s)}
              aria-pressed={severities.has(s)}
              title={`Show only ${s}`}
            >
              <span className="dot" />
              {s} <b>{counts[s]}</b>
            </button>
          ))}
          {severities.size > 0 && (
            <button className="btn ghost sm" onClick={() => setSeverities(new Set())}>
              clear
            </button>
          )}
        </div>
      </div>

      {shown.map((n) => (
        <NoteCard key={n.id} note={n} onChanged={onChanged} showLocation onJump={onJump} />
      ))}

      {!shown.length && (
        <div className="blank" style={{ height: 'auto', padding: '48px 20px' }}>
          <h2>{filtered ? 'Nothing matches those filters' : 'No notes here'}</h2>
          <p className="muted">
            {filtered
              ? 'Clear the filters to see the rest.'
              : scope === 'open'
                ? 'Every note has been resolved or dismissed. Switch to All to see them.'
                : 'Run a review, or add a note yourself from any line in the diff.'}
          </p>
        </div>
      )}
    </div>
  )
}
