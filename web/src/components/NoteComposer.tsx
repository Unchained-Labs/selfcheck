import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import type { Category, Severity } from '../lib/types'

const SEVERITIES: Severity[] = ['blocker', 'major', 'minor', 'nit', 'question', 'praise']
const CATEGORIES: Category[] = [
  'correctness', 'security', 'performance', 'tests', 'style', 'docs', 'design', 'api',
]

export function NoteComposer({
  reviewId, file, line, side, onClose, onSaved,
}: {
  reviewId: string
  file: string
  line: number | null
  side: 'new' | 'old'
  onClose: () => void
  onSaved: () => void
}) {
  const [title, setTitle] = useState('')
  const [bodyText, setBodyText] = useState('')
  const [severity, setSeverity] = useState<Severity>('minor')
  const [category, setCategory] = useState<Category>('correctness')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const titleRef = useRef<HTMLInputElement>(null)

  useEffect(() => { titleRef.current?.focus() }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void save()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const save = async () => {
    if (!title.trim() && !bodyText.trim()) return
    setBusy(true)
    setError('')
    try {
      await api.addNote(reviewId, {
        file,
        line_start: line,
        line_end: line,
        side,
        severity,
        category,
        title: title.trim() || bodyText.trim().split('\n')[0].slice(0, 120),
        body: bodyText,
      })
      onSaved()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <h2>
          Note on <span className="mono">{file || '(general)'}</span>
          {line != null && <span className="mono faint"> :{line} ({side})</span>}
        </h2>
        <div className="content">
          {error && <div className="banner err">{error}</div>}
          <div className="field">
            <label htmlFor="nc-title">Title</label>
            <input
              id="nc-title"
              ref={titleRef}
              className="input"
              value={title}
              placeholder="What is wrong, in one line"
              onChange={(e) => setTitle(e.target.value)}
            />
          </div>
          <div className="row" style={{ gap: 12 }}>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="nc-sev">Severity</label>
              <select
                id="nc-sev"
                className="input"
                value={severity}
                onChange={(e) => setSeverity(e.target.value as Severity)}
              >
                {SEVERITIES.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>
            </div>
            <div className="field" style={{ flex: 1 }}>
              <label htmlFor="nc-cat">Category</label>
              <select
                id="nc-cat"
                className="input"
                value={category}
                onChange={(e) => setCategory(e.target.value as Category)}
              >
                {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>
          <div className="field">
            <label htmlFor="nc-body">Body (markdown)</label>
            <textarea
              id="nc-body"
              className="input"
              rows={7}
              value={bodyText}
              placeholder="The concrete failure: which input or state, and what goes wrong."
              onChange={(e) => setBodyText(e.target.value)}
            />
          </div>
        </div>
        <div className="foot">
          <span className="faint" style={{ marginRight: 'auto', fontSize: 11 }}>
            ⌘/Ctrl + Enter to save
          </span>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" disabled={busy} onClick={save}>
            {busy ? 'Saving…' : 'Add note'}
          </button>
        </div>
      </div>
    </div>
  )
}
