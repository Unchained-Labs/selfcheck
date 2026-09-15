import { useState } from 'react'
import { api } from '../lib/api'
import { renderMarkdown } from '../lib/markdown'
import type { Note, NoteStatus, Severity } from '../lib/types'

const SEVERITIES: Severity[] = ['blocker', 'major', 'minor', 'nit', 'question', 'praise']

const STATUS_ACTIONS: { status: NoteStatus; label: string; title: string }[] = [
  { status: 'resolved', label: 'Resolve', title: 'You have dealt with this' },
  { status: 'dismissed', label: 'Dismiss', title: 'Not a real finding' },
  { status: 'wontfix', label: "Won't fix", title: 'Real, but out of scope' },
]

export function NoteCard({
  note, onChanged, showLocation = false,
}: {
  note: Note
  onChanged: () => void
  showLocation?: boolean
}) {
  const [busy, setBusy] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState({ title: note.title, body: note.body })

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
      onChanged()
    } finally {
      setBusy(false)
    }
  }

  const setStatus = (status: NoteStatus) => act(() => api.patchNote(note.id, { status }))
  const setSeverity = (severity: Severity) => act(() => api.patchNote(note.id, { severity }))

  const location = note.file_path
    ? `${note.file_path}${note.line_start ? `:${note.line_start}` : ''}`
    : 'general'

  return (
    <div
      className={`note ${note.status}`}
      style={{ ['--sev' as string]: `var(--sev-${note.severity})` }}
    >
      <div className="note-head">
        <select
          className="sev"
          value={note.severity}
          disabled={busy}
          onChange={(e) => setSeverity(e.target.value as Severity)}
          style={{
            background: 'transparent',
            border: '1px solid var(--border)',
            borderRadius: 4,
            color: `var(--sev-${note.severity})`,
            padding: '1px 4px',
            cursor: 'pointer',
          }}
          title="Change severity"
        >
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        {editing ? (
          <input
            className="input"
            value={draft.title}
            onChange={(e) => setDraft({ ...draft, title: e.target.value })}
            style={{ flex: 1 }}
          />
        ) : (
          <span className="note-title">{note.title}</span>
        )}

        <span className="chip">{note.category}</span>
        {note.confidence && <span className="chip faint">{note.confidence} confidence</span>}
        {note.origin === 'human' && <span className="chip">you</span>}
        {!!note.stale && (
          <span className="stale-tag" title={`Written against ${note.anchor_sha.slice(0, 8)}`}>
            stale
          </span>
        )}
        {note.status !== 'open' && <span className="chip">{note.status}</span>}
        {showLocation && <span className="chip mono faint">{location}</span>}
      </div>

      {editing ? (
        <div style={{ padding: 10 }}>
          <textarea
            className="input mono"
            rows={8}
            value={draft.body}
            onChange={(e) => setDraft({ ...draft, body: e.target.value })}
          />
        </div>
      ) : (
        note.body && (
          <div
            className="note-body"
            // Markdown here is escaped before any tags are reintroduced;
            // see lib/markdown.ts.
            dangerouslySetInnerHTML={{ __html: renderMarkdown(note.body) }}
          />
        )
      )}

      {note.suggestion && !editing && (
        <div className="note-sugg">
          <div className="lbl">Suggested</div>
          <pre style={{ margin: '4px 10px 10px' }}>
            <code>{note.suggestion}</code>
          </pre>
        </div>
      )}

      <div className="note-foot">
        {editing ? (
          <>
            <button
              className="btn sm primary"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  await api.patchNote(note.id, draft)
                  setEditing(false)
                })
              }
            >
              Save
            </button>
            <button
              className="btn sm"
              onClick={() => {
                setDraft({ title: note.title, body: note.body })
                setEditing(false)
              }}
            >
              Cancel
            </button>
          </>
        ) : (
          <>
            {note.status === 'open' ? (
              STATUS_ACTIONS.map((a) => (
                <button
                  key={a.status}
                  className="btn sm"
                  disabled={busy}
                  title={a.title}
                  onClick={() => setStatus(a.status)}
                >
                  {a.label}
                </button>
              ))
            ) : (
              <button className="btn sm" disabled={busy} onClick={() => setStatus('open')}>
                Reopen
              </button>
            )}
            <button className="btn ghost sm" onClick={() => setEditing(true)}>Edit</button>
            <span className="spacer" />
            {!!note.stale && note.status === 'open' && (
              <button
                className="btn ghost sm"
                disabled={busy}
                title="This note still applies to the current commit"
                onClick={() => act(() => api.patchNote(note.id, { stale: false }))}
              >
                Still applies
              </button>
            )}
            <button
              className="btn ghost sm danger"
              disabled={busy}
              onClick={() => act(() => api.deleteNote(note.id))}
            >
              Delete
            </button>
          </>
        )}
      </div>
    </div>
  )
}
