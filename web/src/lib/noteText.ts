/** Turning notes into text you can paste into a review.
 *
 * Two shapes matter, and they are not the same:
 *
 *   inline  — you are already on the line in GitHub/GitLab's comment box, so a
 *             `file:line` header is noise. Lead with the finding.
 *   standalone — a summary comment, a chat message, a ticket. The location is
 *             the first thing the reader needs.
 */
import type { Note, Review, Run } from './types'

const SEVERITY_LABEL: Record<string, string> = {
  blocker: 'Blocker',
  major: 'Major',
  minor: 'Minor',
  nit: 'Nit',
  question: 'Question',
  praise: 'Praise',
}

const VERDICT_LABEL: Record<string, string> = {
  looks_good: 'Looks good',
  comments: 'Comments',
  needs_work: 'Needs work',
}

export function noteLocation(note: Note): string {
  if (!note.file_path) return ''
  if (!note.line_start) return note.file_path
  const range =
    note.line_end && note.line_end !== note.line_start
      ? `${note.line_start}-${note.line_end}`
      : `${note.line_start}`
  return `${note.file_path}:${range}`
}

/** A suggestion block only applies cleanly to a single line on the new side.
 *  Both GitHub and GitLab understand ```suggestion; anywhere else it still
 *  renders as a code block, so this is never worse than a plain fence. */
function suggestionFence(note: Note): string {
  const single = note.line_start != null && note.line_end === note.line_start
  return single && note.side === 'new' ? 'suggestion' : ''
}

export function noteToMarkdown(note: Note, opts: { withLocation?: boolean } = {}): string {
  const out: string[] = []
  const severity = SEVERITY_LABEL[note.severity] ?? note.severity

  if (opts.withLocation) {
    const loc = noteLocation(note)
    if (loc) out.push(`\`${loc}\``)
  }

  out.push(`**${severity} — ${note.category}**${note.title ? ` ${note.title}` : ''}`)

  if (note.body.trim()) {
    out.push('')
    out.push(note.body.trim())
  }

  if (note.suggestion.trim()) {
    out.push('')
    out.push('```' + suggestionFence(note))
    out.push(note.suggestion.replace(/\s+$/, ''))
    out.push('```')
  }

  return out.join('\n') + '\n'
}

export function notesToMarkdown(
  notes: Note[],
  opts: { heading?: string } = {},
): string {
  if (!notes.length) return ''

  const general = notes.filter((n) => !n.file_path)
  const byFile = new Map<string, Note[]>()
  for (const n of notes) {
    if (!n.file_path) continue
    const list = byFile.get(n.file_path)
    if (list) list.push(n)
    else byFile.set(n.file_path, [n])
  }

  const out: string[] = []
  if (opts.heading) {
    out.push(opts.heading, '')
  }

  const emit = (n: Note) => {
    const loc = n.line_start ? `L${n.line_start}` : ''
    const severity = SEVERITY_LABEL[n.severity] ?? n.severity
    out.push(`- **${severity}**${loc ? ` \`${loc}\`` : ''} — ${n.title}`)
    if (n.body.trim()) {
      out.push(
        n.body
          .trim()
          .split('\n')
          .map((l) => `  ${l}`)
          .join('\n'),
      )
    }
    if (n.suggestion.trim()) {
      out.push('  ```')
      out.push(n.suggestion.replace(/\s+$/, '').split('\n').map((l) => `  ${l}`).join('\n'))
      out.push('  ```')
    }
    out.push('')
  }

  if (general.length) {
    out.push('**General**', '')
    general.forEach(emit)
  }

  for (const [path, list] of [...byFile].sort(([a], [b]) => a.localeCompare(b))) {
    out.push(`**\`${path}\`**`, '')
    list
      .slice()
      .sort((a, b) => (a.line_start ?? 0) - (b.line_start ?? 0))
      .forEach(emit)
  }

  return out.join('\n').replace(/\n{3,}/g, '\n\n').trim() + '\n'
}

export function summaryToMarkdown(run: Run | null, review: Review | null): string {
  if (!run) return ''
  const out: string[] = []

  if (review) {
    const kind = review.provider === 'github' ? 'PR' : 'MR'
    out.push(
      `**Review of ${review.namespace}/${review.project} ${kind} #${review.number}** ` +
        `at \`${(review.head_sha || '').slice(0, 12)}\``,
      '',
    )
  }

  if (run.verdict) {
    out.push(
      `**Verdict:** ${VERDICT_LABEL[run.verdict] ?? run.verdict}` +
        (run.confidence ? ` (confidence: ${run.confidence})` : ''),
      '',
    )
  }

  if (run.summary.trim()) out.push(run.summary.trim(), '')

  const list = (title: string, items: string[]) => {
    if (!items?.length) return
    out.push(`**${title}**`, '')
    out.push(...items.map((i) => `- ${i}`))
    out.push('')
  }
  list('Riskiest parts', run.risk_areas)
  list('Test gaps', run.test_gaps)
  list('Questions for the author', run.questions)

  if (run.checklist?.length) {
    out.push('**Checklist**', '')
    for (const c of run.checklist) {
      const mark = c.state === 'pass' ? 'x' : ' '
      out.push(`- [${mark}] ${c.item}${c.note ? ` — ${c.note}` : ''}`)
    }
    out.push('')
  }

  return out.join('\n').trim() + '\n'
}

export function fullReviewMarkdown(
  run: Run | null,
  review: Review | null,
  notes: Note[],
): string {
  const parts = [summaryToMarkdown(run, review)]
  const body = notesToMarkdown(notes, { heading: '## Findings' })
  if (body) parts.push(body)
  return parts.filter(Boolean).join('\n').trim() + '\n'
}
