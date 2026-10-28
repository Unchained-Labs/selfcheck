/** Filters for the Reviews tab. They live in the URL (#/reviews?author=…), so
 *  any number on the dashboard can link to exactly the PRs behind it. */

import { repoKey } from './labels'
import type { Review, Severity } from './types'

export interface ReviewFilters {
  q?: string
  repo?: string          // host/namespace/project
  author?: string
  person?: string        // assignee or requested reviewer
  severity?: Severity    // has open findings of this severity
  engine?: string        // engine of the latest run
  mode?: string          // depth of the latest run
  trigger?: string       // what started the latest run
  verdict?: string
  state?: string         // open | merged | closed | draft
  source?: 'wakeup' | 'manual'
  since?: string         // ISO; with `event`, when it happened
  until?: string
  event?: 'added' | 'reviewed'
}

const KEYS: (keyof ReviewFilters)[] = [
  'q', 'repo', 'author', 'person', 'severity', 'engine', 'mode', 'trigger', 'verdict', 'state',
  'source', 'since', 'until', 'event',
]

export function toQuery(f: ReviewFilters): string {
  const p = new URLSearchParams()
  for (const k of KEYS) if (f[k]) p.set(k, String(f[k]))
  const s = p.toString()
  return s ? `?${s}` : ''
}

export function fromQuery(query: string): ReviewFilters {
  const p = new URLSearchParams(query.replace(/^\?/, ''))
  const out: Record<string, string> = {}
  for (const k of KEYS) {
    const v = p.get(k)
    if (v) out[k] = v
  }
  return out as ReviewFilters
}

function names(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map(String)
  if (typeof raw === 'string' && raw.startsWith('[')) {
    try { return (JSON.parse(raw) as unknown[]).map(String) } catch { return [] }
  }
  return []
}

export const peopleOf = (r: Review) => [
  ...names((r as unknown as Record<string, unknown>).assignees),
  ...names((r as unknown as Record<string, unknown>).reviewers),
]

/** When the PR was added, and when it was last reviewed. */
const addedAt = (r: Review) => r.created_at || r.updated_at
const reviewedAt = (r: Review) => r.latest_run?.finished_at || r.latest_run?.created_at || ''

export function applyFilters(reviews: Review[], f: ReviewFilters): Review[] {
  const q = f.q?.trim().toLowerCase()
  return reviews.filter((r) => {
    if (q && !`${r.title} ${r.namespace}/${r.project} #${r.number} ${r.author}`.toLowerCase().includes(q)) return false
    if (f.repo && repoKey(r) !== f.repo) return false
    if (f.author && r.author !== f.author) return false
    if (f.person && !peopleOf(r).includes(f.person)) return false
    if (f.severity && !((r.counts?.[f.severity] ?? 0) > 0)) return false
    if (f.engine && r.latest_run?.engine !== f.engine) return false
    if (f.mode && r.latest_run?.mode !== f.mode) return false
    if (f.trigger && r.latest_run?.trigger !== f.trigger) return false
    if (f.verdict && r.latest_run?.verdict !== f.verdict) return false
    if (f.state && (f.state === 'draft' ? !r.draft : r.state !== f.state || !!r.draft)) return false
    if (f.source === 'wakeup' && !r.repo_watch_id) return false
    if (f.source === 'manual' && r.repo_watch_id) return false
    if (f.since || f.until) {
      const times = f.event === 'added' ? [addedAt(r)] : f.event === 'reviewed' ? [reviewedAt(r)] : [addedAt(r), reviewedAt(r)]
      // Compare instants, not strings: the server writes +00:00, browsers write Z.
      const lo = f.since ? Date.parse(f.since) : -Infinity
      const hi = f.until ? Date.parse(f.until) : Infinity
      const hit = times.some((t) => t && Date.parse(t) >= lo && Date.parse(t) < hi)
      if (!hit) return false
    }
    return true
  })
}

/** Human labels for the chips above the list. */
export function describe(f: ReviewFilters, label: (k: keyof ReviewFilters, v: string) => string): { key: keyof ReviewFilters; text: string }[] {
  const out: { key: keyof ReviewFilters; text: string }[] = []
  for (const k of KEYS) {
    const v = f[k]
    if (!v || k === 'event' || k === 'until' || k === 'q') continue
    out.push({ key: k, text: label(k, String(v)) })
  }
  return out
}
