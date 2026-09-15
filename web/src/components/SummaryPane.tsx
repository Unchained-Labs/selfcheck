import { renderMarkdown } from '../lib/markdown'
import type { Note, Run } from '../lib/types'
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
          <li key={i} dangerouslySetInnerHTML={{ __html: renderMarkdown(x).replace(/^<p>|<\/p>$/g, '') }} />
        ))}
      </ul>
    </div>
  )
}

export function SummaryPane({ run, notes, onNotesChanged }: {
  run: Run | null
  notes: Note[]
  onNotesChanged: () => void
}) {
  if (!run) {
    return (
      <div className="blank">
        <h2>No review yet</h2>
        <p>Hit <strong>Review with Claude</strong> to have it read the change.</p>
      </div>
    )
  }

  if (run.status === 'failed') {
    return (
      <div className="pane">
        <div className="card" style={{ borderColor: 'var(--sev-blocker)' }}>
          <h3 style={{ color: 'var(--sev-blocker)' }}>Run failed</h3>
          <p className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>{run.error}</p>
          {run.summary && (
            <>
              <h3 style={{ marginTop: 16 }}>Partial output</h3>
              <pre style={{ whiteSpace: 'pre-wrap', fontSize: 11 }}>{run.summary}</pre>
            </>
          )}
        </div>
      </div>
    )
  }

  const general = notes.filter((n) => !n.file_path)

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
          <span className="faint mono" style={{ fontSize: 11 }}>
            {run.model}
            {run.duration_ms ? ` · ${(run.duration_ms / 1000).toFixed(0)}s` : ''}
            {run.cost_usd ? ` · $${run.cost_usd.toFixed(3)}` : ''}
            {run.used_worktree ? ' · read the repo' : ' · diff only'}
          </span>
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
    </div>
  )
}
