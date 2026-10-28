import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { MODE_LABEL } from '../lib/labels'
import type { Mode, Review } from '../lib/types'
import { Icon, Spinner } from './Icon'

export interface AddBarHandle { focus: () => void }

const EXAMPLES = [
  'https://github.com/owner/repo/pull/12',
  'gl:group/project!34',
  '~/src/app@feature',
]

/** What the input looks like it holds, so the button can say what it will do. */
function kindOf(text: string): 'local' | 'pr' | 'repo' | '' {
  const t = text.trim()
  if (!t) return ''
  if (/^(~|\/|local:|file:\/\/)/.test(t)) return 'local'
  if (/\/pulls?\/\d+|merge_requests\/\d+|^(gh|github|gl|gitlab):.+[#!/]\d+$/i.test(t)) return 'pr'
  if (/^(https?:\/\/)?[^/\s]+\.[^/\s]+\/[^/\s]+\/[^\s]+$/.test(t) || /^(gh|gl):[^#!]+$/i.test(t)) return 'repo'
  return 'pr'
}

/** The main way into selfcheck: paste a pull request, a merge request or a
 *  local branch, and it is tracked (and reviewed, by default). Paste a
 *  repository instead and it offers a wakeup. */
export const AddBar = forwardRef<AddBarHandle, {
  onAdded: (review: Review) => void
  onWakeup: (repoKey: string) => void
  compact?: boolean
  autoFocus?: boolean
}>(function AddBar({ onAdded, onWakeup, compact = false, autoFocus = false }, ref) {
  const input = useRef<HTMLInputElement>(null)
  const [value, setValue] = useState('')
  const [reviewNow, setReviewNow] = useState(true)
  const [mode, setMode] = useState<Mode | ''>('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useImperativeHandle(ref, () => ({ focus: () => input.current?.focus() }), [])
  useEffect(() => { if (autoFocus) input.current?.focus() }, [autoFocus])

  const kind = kindOf(value)

  const repoKeyFrom = (text: string) => {
    const t = text.trim().replace(/^(https?:\/\/)/, '').replace(/\.git$/, '').replace(/\/$/, '')
    if (/^gh:/i.test(t)) return `github.com/${t.slice(3)}`
    if (/^gl:/i.test(t)) return `gitlab.com/${t.slice(3)}`
    return t.split('/-/')[0]
  }

  const submit = async () => {
    const text = value.trim()
    if (!text) return
    if (kind === 'repo') {
      onWakeup(repoKeyFrom(text))
      return
    }
    setBusy(true)
    setError('')
    try {
      const { review } = await api.addReview(text, { review_now: reviewNow, ...(mode ? { mode } : {}) })
      setValue('')
      onAdded(review)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const action = kind === 'repo' ? 'Set up a wakeup' : reviewNow ? 'Review' : 'Track'

  return (
    <div className={`addbar ${compact ? 'compact' : ''}`}>
      <div className="addbar-row">
        <div className="addbar-input">
          <Icon name={kind === 'local' ? 'branch' : kind === 'repo' ? 'repo' : 'pr'} size={16} />
          <input
            ref={input}
            className="input"
            value={value}
            disabled={busy}
            placeholder="Paste a pull request, merge request, or a local repo path…"
            aria-label="Pull request, merge request or local repository"
            onChange={(e) => { setValue(e.target.value); setError('') }}
            onKeyDown={(e) => e.key === 'Enter' && void submit()}
          />
          {kind && <span className="addbar-kind">{kind === 'local' ? 'local branch' : kind === 'repo' ? 'repository' : 'pull request'}</span>}
        </div>
        <button className="btn primary addbar-go" disabled={busy || !value.trim()} onClick={() => void submit()}>
          {busy ? <Spinner size={14} /> : <Icon name={kind === 'repo' ? 'alarm' : 'sparkle'} size={14} />}
          {action}
        </button>
      </div>
      <div className="addbar-opts">
        {kind !== 'repo' && (
          <>
            <label className="check-label">
              <input type="checkbox" checked={reviewNow} onChange={(e) => setReviewNow(e.target.checked)} />
              review right away
            </label>
            {reviewNow && (
              <div className="seg xs" role="group" aria-label="Depth">
                <button className={mode === '' ? 'on' : ''} onClick={() => setMode('')}>Default</button>
                {(['light', 'normal', 'thorough'] as Mode[]).map((m) => (
                  <button key={m} className={mode === m ? 'on' : ''} onClick={() => setMode(m)}>{MODE_LABEL[m]}</button>
                ))}
              </div>
            )}
          </>
        )}
        {kind === 'repo' && (
          <span className="muted">That's a repository, not a single change — a wakeup will review its new PRs on a schedule.</span>
        )}
        {kind === 'local' && (
          <span className="muted">Committed work on that branch is compared with its base; add <code>@branch..base</code> to choose.</span>
        )}
        {!kind && !compact && (
          <span className="faint addbar-examples">
            e.g. {EXAMPLES.map((x) => (
              <button key={x} className="example" onClick={() => { setValue(x); input.current?.focus() }}>
                {x}
              </button>
            ))}
          </span>
        )}
      </div>
      {error && <div className="inline-err">{error}</div>}
    </div>
  )
})

/** The same bar in a dialog, for adding from any page (`a`, or the sidebar button). */
export function AddDialog({
  onClose, onAdded, onWakeup,
}: {
  onClose: () => void
  onAdded: (review: Review) => void
  onWakeup: (repoKey: string) => void
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal wide add-dialog" role="dialog" aria-label="New review">
        <h2><Icon name="plus" size={16} /> New review</h2>
        <div className="content">
          <AddBar autoFocus onAdded={(r) => { onClose(); onAdded(r) }} onWakeup={(k) => { onClose(); onWakeup(k) }} />
        </div>
      </div>
    </div>
  )
}
