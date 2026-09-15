import { renderMarkdown } from '../lib/markdown'
import { fullReviewMarkdown, summaryToMarkdown } from '../lib/noteText'
import { duration, timeAgo } from '../lib/time'
import type { Note, Review, Run } from '../lib/types'
import { CopyButton } from './CopyButton'
import { NoteCard } from './NoteCard'

const VERDICT_LABEL: Record<string, string> = {
  looks_good: 'Looks good',
  comments: 'Comments',
  needs_work: 'Needs work',
}

function List({ title, items }: { title: string; items: string[] }) {
  if (!items?.length) return null
  return (
    <div className="card">
      <h3>{title}</h3>
      <ul>
        {items.map((x, i) => (
          <li
            key={i}
            dangerouslySetInnerHTML={{ __html: renderMarkdown(x).replace(/^<p>|<\/p>$/g, '') }}
          />
        ))}
      </ul>
    </div>
  )
}

function RunHistory({ runs, current }: { runs: Run[]; current: Run }) {
  const past = runs.filter((r) => r.id !== current.id && r.status !== 'queued')
  if (!past.length) return null
  return (
    <div className="card">
      <h3>Earlier runs</h3>
      <div className="history">
        {past.slice(0, 8).map((r) => (
          <div key={r.id} className="history-row">
            <span className={`verdict-dot ${r.verdict || r.status}`} />
            <span className="mono faint">{(r.head_sha || '').slice(0, 8) || '—'}</span>
            <span>{r.status === 'done' ? (VERDICT_LABEL[r.verdict] ?? r.verdict) : r.status}</span>
            <span className="faint">{r.trigger === 'watch' ? 'auto' : r.trigger}</span>
            <span className="spacer" />
            <span className="faint">{duration(r.duration_ms)}</span>
            <span className="faint">{timeAgo(r.created_at)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export function SummaryPane({
  run, runs, review, notes, onNotesChanged, onReview,
}: {
  run: Run | null
  runs: Run[]
  review: Review | null
  notes: Note[]
  onNotesChanged: () => void
  onReview?: () => void
}) {
  if (!run) {
    return (
      <div className="blank">
        <h2>No review yet</h2>
        <p>Claude reads the change against a read-only checkout and writes its notes here.</p>
        {onReview && (
          <button className="btn primary" onClick={onReview}>Review with Claude</button>
        )}
        <p className="faint" style={{ fontSize: 11 }}>
          or press <kbd>r</kbd>
        </p>
      </div>
    )
  }

  if (run.status === 'failed') {
    return (
      <div className="pane">
        <div className="card" style={{ borderColor: 'var(--sev-blocker)' }}>
          <h3 style={{ color: 'var(--sev-blocker)' }}>Run failed</h3>
          <p className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{run.error}</p>
          {onReview && (
            <button className="btn sm" style={{ marginTop: 10 }} onClick={onReview}>
              Try again
            </button>
          )}
          {run.summary && (
            <>
              <h3 style={{ marginTop: 16 }}>Partial output</h3>
              <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{run.summary}</pre>
            </>
          )}
        </div>
        <RunHistory runs={runs} current={run} />
      </div>
    )
  }

  const general = notes.filter((n) => !n.file_path)
  const openNotes = notes.filter((n) => n.status === 'open')

  return (
    <div className="pane">
      <div className="card">
        <div className="row" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
          {run.verdict && (
            <span className={`verdict ${run.verdict}`}>
              {VERDICT_LABEL[run.verdict] ?? run.verdict}
            </span>
          )}
          {run.confidence && <span className="chip">{run.confidence} confidence</span>}
          <span className="spacer" />
          <CopyButton
            className="btn sm"
            label="Copy summary"
            title="Copy the verdict and summary, ready to paste as a review comment"
            text={() => summaryToMarkdown(run, review)}
          />
          <CopyButton
            className="btn sm"
            label="Copy everything"
            title="Copy the summary plus every open finding"
            text={() => fullReviewMarkdown(run, review, openNotes)}
          />
        </div>
        <div className="row faint" style={{ fontSize: 11, marginBottom: 12, flexWrap: 'wrap' }}>
          <span className="mono">{run.model}</span>
          {run.duration_ms > 0 && <span>· {duration(run.duration_ms)}</span>}
          {run.cost_usd > 0 && <span>· ${run.cost_usd.toFixed(3)}</span>}
          <span>· {run.used_worktree ? 'read the repo' : 'diff only'}</span>
          <span>· {run.trigger === 'watch' ? 'auto re-review' : run.trigger}</span>
          <span>· {timeAgo(run.created_at)}</span>
          {run.head_sha && <span className="mono">· {run.head_sha.slice(0, 8)}</span>}
        </div>
        <div
          className="prose"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(run.summary) }}
        />
      </div>

      <List title="Riskiest parts" items={run.risk_areas} />
      <List title="Test gaps" items={run.test_gaps} />
      <List title="Questions for the author" items={run.questions} />

      {!!run.checklist?.length && (
        <div className="card">
          <h3>Checklist</h3>
          <div className="check">
            {run.checklist.map((c, i) => (
              <div key={i} style={{ display: 'contents' }}>
                <span className={`st ${c.state}`}>{c.state}</span>
                <span>
                  <strong>{c.item}</strong>
                  {c.note && <span className="muted"> — {c.note}</span>}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {!!general.length && (
        <div className="card">
          <h3>General notes</h3>
          {general.map((n) => (
            <NoteCard key={n.id} note={n} onChanged={onNotesChanged} />
          ))}
        </div>
      )}

      <RunHistory runs={runs} current={run} />
    </div>
  )
}
