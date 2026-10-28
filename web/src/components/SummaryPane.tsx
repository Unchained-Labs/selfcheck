import { renderMarkdown } from '../lib/markdown'
import { fullReviewMarkdown, summaryToMarkdown } from '../lib/noteText'
import { duration, timeAgo } from '../lib/time'
import { engineLabel, MODE_LABEL } from '../lib/labels'
import type { Note, Review, Run, Status } from '../lib/types'
import { CopyButton } from './CopyButton'
import { Icon } from './Icon'
import { NoteCard } from './NoteCard'
import { SecondOpinion } from './SecondOpinion'

const VERDICT_LABEL: Record<string, string> = {
  looks_good: 'Looks good',
  comments: 'Comments',
  needs_work: 'Needs work',
}

const VERDICT_ICON: Record<string, string> = {
  looks_good: 'check',
  comments: 'note',
  needs_work: 'alert',
}

const TRIGGER_LABEL: Record<string, string> = {
  watch: 'auto re-review',
  schedule: 'wakeup',
  manual: 'manual',
  api: 'api',
}

function List({ title, icon, items }: { title: string; icon: string; items: string[] }) {
  if (!items?.length) return null
  return (
    <div className="card">
      <h3><Icon name={icon} size={14} /> {title}</h3>
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

function RunHistory({ runs, current, status }: { runs: Run[]; current: Run; status: Status | null }) {
  const past = runs.filter((r) => r.id !== current.id && r.status !== 'queued')
  if (!past.length) return null
  return (
    <div className="card">
      <h3><Icon name="sync" size={14} /> Earlier runs</h3>
      <div className="history">
        {past.slice(0, 8).map((r) => (
          <div key={r.id} className="history-row">
            <span className={`verdict-dot ${r.verdict || r.status}`} />
            <span className="mono faint">{(r.head_sha || '').slice(0, 8) || '—'}</span>
            <span>{r.status === 'done' ? (VERDICT_LABEL[r.verdict] ?? r.verdict) : r.status}</span>
            <span className="faint">{r.kind === 'second_opinion' ? 'second opinion' : TRIGGER_LABEL[r.trigger] ?? r.trigger}</span>
            <span className="chip xs">{MODE_LABEL[r.mode] ?? r.mode}</span>
            <span className="chip xs">{engineLabel(r.engine, status)}</span>
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
  run, runs, review, status, notes, onNotesChanged, onReview,
}: {
  run: Run | null
  runs: Run[]
  review: Review | null
  status: Status | null
  notes: Note[]
  onNotesChanged: () => void
  onReview?: () => void
}) {
  if (!run) {
    return (
      <div className="blank">
        <span className="blank-icon"><Icon name="sparkle" size={24} /></span>
        <h2>No review yet</h2>
        <p>
          The engine reads the change against a read-only checkout and writes its notes here.
          <br />
          Pick a depth and engine from the arrow on the Review button, or just run the default.
        </p>
        {onReview && (
          <button className="btn primary" onClick={onReview}><Icon name="sparkle" size={14} /> Review now</button>
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
        <div className="card failed-card">
          <h3><Icon name="alert" size={14} /> Run failed</h3>
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
        <RunHistory runs={runs} current={run} status={status} />
      </div>
    )
  }

  const general = notes.filter((n) => !n.file_path)
  const openNotes = notes.filter((n) => n.status === 'open')

  const checklist = !!run.checklist?.length && (
    <div className="card">
      <h3><Icon name="check" size={14} /> Checklist</h3>
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
  )

  // Two columns when there is room: what the review says on the left, the
  // checklist and run history beside it, so a wide window is not mostly margin.
  return (
    <div className="pane summary-layout">
      <div className="summary-main">
      <div className={`card verdict-card ${run.verdict}`}>
        <div className="row" style={{ marginBottom: 12, flexWrap: 'wrap' }}>
          {run.verdict && (
            <span className={`verdict ${run.verdict}`}>
              <Icon name={VERDICT_ICON[run.verdict] ?? 'note'} size={13} />
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
        <div className="run-meta">
          <span className="chip"><Icon name="cpu" size={12} /> {engineLabel(run.engine, status)}</span>
          <span className="chip"><Icon name="gauge" size={12} /> {MODE_LABEL[run.mode] ?? run.mode}</span>
          {run.model && <span className="mono">{run.model}</span>}
          {run.duration_ms > 0 && <span>· {duration(run.duration_ms)}</span>}
          {run.cost_usd > 0 && <span>· ${run.cost_usd.toFixed(3)}</span>}
          <span>· {run.used_worktree ? 'read the repo' : 'diff only'}</span>
          <span>· {TRIGGER_LABEL[run.trigger] ?? run.trigger}</span>
          <span>· {timeAgo(run.created_at)}</span>
          {run.head_sha && <span className="mono">· {run.head_sha.slice(0, 8)}</span>}
        </div>
        {(run.context?.repo_rules || run.context?.repo_file || !!run.context?.dismissed || !!run.context?.wontfix) && (
          <div className="run-context" title="What this review was told beyond the diff">
            <span className="faint">Shaped by</span>
            {run.context.repo_rules && <span className="chip xs"><Icon name="doc" size={11} /> repo rules</span>}
            {run.context.repo_file && <span className="chip xs"><Icon name="doc" size={11} /> .selfcheck.md</span>}
            {!!run.context.dismissed && <span className="chip xs"><Icon name="x" size={11} /> {run.context.dismissed} past dismissals</span>}
            {!!run.context.wontfix && <span className="chip xs">{run.context.wontfix} won't-fix decisions</span>}
          </div>
        )}
        <div
          className="prose"
          dangerouslySetInnerHTML={{ __html: renderMarkdown(run.summary) }}
        />
      </div>

      <div className="card-grid">
        <List title="Riskiest parts" icon="alert" items={run.risk_areas} />
        <List title="Test gaps" icon="search" items={run.test_gaps} />
        <List title="Questions for the author" icon="note" items={run.questions} />
      </div>

      {!!general.length && (
        <div className="card">
          <h3><Icon name="note" size={14} /> General notes</h3>
          {general.map((n) => (
            <NoteCard key={n.id} note={n} onChanged={onNotesChanged} />
          ))}
        </div>
      )}
      </div>

      <aside className="summary-side">
        {review && <SecondOpinion review={review} status={status} runs={runs} current={run} onChanged={onNotesChanged} />}
        {checklist}
        <RunHistory runs={runs} current={run} status={status} />
      </aside>
    </div>
  )
}
