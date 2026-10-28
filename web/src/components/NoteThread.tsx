import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { renderMarkdown } from '../lib/markdown'
import type { NoteMessage } from '../lib/types'
import { Icon, Spinner } from './Icon'

const STARTERS = [
  'Does this really hold? Check the code.',
  'Which code path reaches this?',
  'What would the fix look like?',
]

/** A short conversation about one finding. The engine answers from the same
 *  read-only checkout the review used, so "is this real?" gets checked. */
export function NoteThread({ noteId }: { noteId: string }) {
  const [messages, setMessages] = useState<NoteMessage[] | null>(null)
  const [draft, setDraft] = useState('')
  const [error, setError] = useState('')
  const [sending, setSending] = useState(false)
  const box = useRef<HTMLTextAreaElement>(null)

  const load = useCallback(() => {
    api.noteMessages(noteId).then(setMessages).catch((e) => setError(String(e?.message ?? e)))
  }, [noteId])

  useEffect(() => { load() }, [load])

  const pending = messages?.some((m) => m.status === 'pending')
  // Poll only while an answer is on its way.
  useEffect(() => {
    if (!pending) return
    const t = window.setInterval(load, 2500)
    return () => window.clearInterval(t)
  }, [pending, load])

  const ask = async (question: string) => {
    const q = question.trim()
    if (!q) return
    setSending(true)
    setError('')
    try {
      setMessages(await api.askNote(noteId, q))
      setDraft('')
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="thread">
      {messages === null && <div className="faint thread-empty"><Spinner size={12} /> Loading…</div>}
      {messages?.length === 0 && (
        <div className="thread-starters">
          <span className="faint">Ask the engine about this finding — it reads the checkout to answer.</span>
          <div className="row" style={{ flexWrap: 'wrap', gap: 6 }}>
            {STARTERS.map((q) => (
              <button key={q} className="chip-btn" disabled={sending} onClick={() => void ask(q)}>{q}</button>
            ))}
          </div>
        </div>
      )}
      {messages?.map((m) => (
        <div key={m.id} className={`msg ${m.role} ${m.status}`}>
          <span className="msg-who">
            {m.role === 'user' ? 'You' : <><Icon name="sparkle" size={12} /> {m.model || m.engine || 'engine'}</>}
          </span>
          {m.status === 'pending' ? (
            <span className="msg-body faint"><Spinner size={12} /> Reading the code…</span>
          ) : (
            <div className="msg-body prose" dangerouslySetInnerHTML={{ __html: renderMarkdown(m.body) }} />
          )}
        </div>
      ))}
      {error && <div className="inline-err">{error}</div>}
      <div className="thread-input">
        <textarea
          ref={box}
          className="input"
          rows={2}
          value={draft}
          placeholder="Ask a follow-up… (⌘/Ctrl + Enter)"
          aria-label="Question about this finding"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void ask(draft) }
          }}
        />
        <button className="btn sm primary" disabled={sending || pending || !draft.trim()} onClick={() => void ask(draft)}>
          {sending ? <Spinner size={12} /> : <Icon name="arrow" size={13} />} Ask
        </button>
      </div>
    </div>
  )
}
