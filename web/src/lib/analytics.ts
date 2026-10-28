/** Aggregations for the overview dashboard. Everything here is a pure
 *  function over the rows /api/analytics returns, bucketed in the viewer's
 *  local timezone so "today" means the reader's today. */

import type { Severity } from './types'

export interface ARev {
  id: string
  provider: string
  host: string
  namespace: string
  project: string
  number: number
  title: string
  author: string
  assignees: string[]
  reviewers: string[]
  state: string
  draft: number
  additions: number
  deletions: number
  changed_files: number
  archived: number
  repo_watch_id: string
  created_at: string
  updated_at: string
}

export interface ARun {
  id: string
  review_id: string
  status: string
  trigger: string
  mode: string
  engine: string
  model: string
  verdict: string
  cost_usd: number
  duration_ms: number
  num_turns: number
  used_worktree: number
  notes: Partial<Record<Severity, number>>
  kind: 'review' | 'second_opinion'
  created_at: string
  finished_at: string
}

export interface ANote {
  review_id: string
  run_id: string
  severity: Severity
  category: string
  status: string
  origin: string
  stale: number
  created_at: string
  updated_at: string
}

export interface AnalyticsData {
  reviews: ARev[]
  runs: ARun[]
  notes: ANote[]
  generated_at: string
}

export const SEVERITIES: Severity[] = ['blocker', 'major', 'minor', 'question', 'nit', 'praise']
const DAY = 86_400_000

/* ── dates ─────────────────────────────────────────────────────────────── */

export function dayKey(d: Date | string): string {
  const x = typeof d === 'string' ? new Date(d) : d
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`
}

export function startOfDay(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

/** Every local day from `from` to `to` inclusive. */
export function daysBetween(from: Date, to: Date): Date[] {
  const out: Date[] = []
  for (let d = startOfDay(from); d <= to; d = new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1)) {
    out.push(d)
  }
  return out
}

export interface Range { days: number | null; label: string }

export const RANGES: Range[] = [
  { days: 7, label: '7d' },
  { days: 30, label: '30d' },
  { days: 90, label: '90d' },
  { days: 365, label: '1y' },
  { days: null, label: 'All' },
]

/** The window a range covers, and the same-length window before it. */
export function rangeWindow(range: Range, data: AnalyticsData, now = new Date()) {
  const end = now
  let start: Date
  if (range.days) {
    start = startOfDay(new Date(now.getTime() - (range.days - 1) * DAY))
  } else {
    const first = [...data.runs.map((r) => r.created_at), ...data.reviews.map((r) => r.created_at)]
      .filter(Boolean).sort()[0]
    start = startOfDay(first ? new Date(first) : now)
  }
  const span = end.getTime() - start.getTime()
  return { start, end, prevStart: new Date(start.getTime() - span), prevEnd: start }
}

const within = (iso: string, a: Date, b: Date) => {
  const t = new Date(iso).getTime()
  return t >= a.getTime() && t <= b.getTime()
}

/* ── stats helpers ─────────────────────────────────────────────────────── */

export function quantile(values: number[], q: number): number {
  if (!values.length) return 0
  const s = [...values].sort((a, b) => a - b)
  const pos = (s.length - 1) * q
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  return s[lo] + (s[hi] - s[lo]) * (pos - lo)
}

export const findingsOf = (run: ARun) =>
  Object.values(run.notes ?? {}).reduce((a, b) => a + (b ?? 0), 0)

export const seriousOf = (run: ARun) => (run.notes?.blocker ?? 0) + (run.notes?.major ?? 0)

export function delta(cur: number, prev: number): number | null {
  if (!prev) return cur ? null : 0
  return (cur - prev) / prev
}

/* ── the dashboard model ───────────────────────────────────────────────── */

export function buildModel(data: AnalyticsData, range: Range) {
  const { start, end, prevStart, prevEnd } = rangeWindow(range, data)
  const reviewById = new Map(data.reviews.map((r) => [r.id, r]))
  const runById = new Map(data.runs.map((r) => [r.id, r]))

  const runs = data.runs.filter((r) => within(r.created_at, start, end))
  const prevRuns = data.runs.filter((r) => within(r.created_at, prevStart, prevEnd))
  const finished = runs.filter((r) => ['done', 'failed', 'cancelled'].includes(r.status))
  // Findings come from reviews; a second opinion's are a comparison, not new findings.
  const isReview = (r: ARun) => r.kind !== 'second_opinion'
  const done = runs.filter((r) => r.status === 'done' && isReview(r))
  const prevDone = prevRuns.filter((r) => r.status === 'done' && isReview(r))
  const addedPrs = data.reviews.filter((r) => within(r.created_at, start, end))
  const prevAddedPrs = data.reviews.filter((r) => within(r.created_at, prevStart, prevEnd))

  // Notes judged in the window: what happened to the findings you saw.
  const decided = data.notes.filter((n) => n.origin === 'claude' && n.status !== 'open')
  const decidedIn = decided.filter((n) => within(n.updated_at, start, end))
  const outcomes = { open: 0, resolved: 0, wontfix: 0, dismissed: 0 } as Record<string, number>
  for (const n of data.notes.filter((x) => x.origin === 'claude')) {
    if (n.status === 'open' || within(n.updated_at, start, end)) outcomes[n.status] = (outcomes[n.status] ?? 0) + 1
  }
  const judged = decidedIn.length
  const dismissed = decidedIn.filter((n) => n.status === 'dismissed').length

  const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0)
  const findings = sum(done.map(findingsOf))
  const prevFindings = sum(prevDone.map(findingsOf))
  const spend = sum(runs.map((r) => r.cost_usd || 0))
  const prevSpend = sum(prevRuns.map((r) => r.cost_usd || 0))
  const durations = done.map((r) => r.duration_ms).filter((d) => d > 0)
  const prevDurations = prevDone.map((r) => r.duration_ms).filter((d) => d > 0)

  // Daily series across the window (bucketed weekly for long windows).
  const days = daysBetween(start, end)
  const weekly = days.length > 120
  const bucketOf = (iso: string) => {
    const d = startOfDay(new Date(iso))
    if (!weekly) return dayKey(d)
    const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7))
    return dayKey(monday)
  }
  const buckets: string[] = []
  for (const d of days) {
    const k = bucketOf(d.toISOString())
    if (buckets[buckets.length - 1] !== k) buckets.push(k)
  }
  const engines = [...new Set(data.runs.map((r) => r.engine || 'claude'))]
    .sort((a, b) => ENGINE_ORDER.indexOf(a) - ENGINE_ORDER.indexOf(b))
  const perBucket = buckets.map((key) => ({ key, byEngine: {} as Record<string, number>, total: 0, findings: 0 }))
  const bucketIndex = new Map(buckets.map((k, i) => [k, i]))
  for (const r of runs) {
    const b = perBucket[bucketIndex.get(bucketOf(r.created_at)) ?? -1]
    if (!b) continue
    const e = r.engine || 'claude'
    b.byEngine[e] = (b.byEngine[e] ?? 0) + 1
    b.total += 1
    if (r.status === 'done') b.findings += findingsOf(r)
  }

  // Cumulative, from the very first activity so the line starts at its true level.
  const before = (iso: string) => new Date(iso).getTime() < start.getTime()
  let cumRuns = data.runs.filter((r) => before(r.created_at)).length
  let cumFindings = sum(data.runs.filter((r) => before(r.created_at) && r.status === 'done').map(findingsOf))
  let cumPrs = data.reviews.filter((r) => before(r.created_at)).length
  const prsByBucket = new Map<string, number>()
  for (const r of addedPrs) prsByBucket.set(bucketOf(r.created_at), (prsByBucket.get(bucketOf(r.created_at)) ?? 0) + 1)
  const cumulative = perBucket.map((b) => {
    cumRuns += b.total
    cumFindings += b.findings
    cumPrs += prsByBucket.get(b.key) ?? 0
    return { key: b.key, runs: cumRuns, findings: cumFindings, prs: cumPrs }
  })

  // Severity / category of findings currently on record.
  const severity = Object.fromEntries(SEVERITIES.map((s) => [s, 0])) as Record<Severity, number>
  for (const r of done) for (const s of SEVERITIES) severity[s] += r.notes?.[s] ?? 0
  const categories: Record<string, number> = {}
  for (const n of data.notes) {
    if (n.origin !== 'claude' || !within(n.created_at, start, end)) continue
    categories[n.category] = (categories[n.category] ?? 0) + 1
  }

  return {
    start, end, weekly, buckets: perBucket, cumulative, engines,
    kpis: {
      runs: { cur: runs.length, prev: prevRuns.length },
      findings: { cur: findings, prev: prevFindings },
      prs: { cur: addedPrs.length, prev: prevAddedPrs.length },
      medianMs: { cur: quantile(durations, 0.5), prev: quantile(prevDurations, 0.5) },
      spend: { cur: spend, prev: prevSpend },
      success: { cur: finished.length ? done.length / finished.length : null },
      noise: { cur: judged ? dismissed / judged : null, judged },
      perRun: { cur: done.length ? findings / done.length : 0 },
    },
    severity, categories, outcomes,
    groups: {
      engine: groupStats(runs, (r) => r.engine || 'claude', data.notes, runById),
      mode: groupStats(runs, (r) => r.mode || 'normal', data.notes, runById),
      trigger: groupStats(runs, (r) => r.trigger || 'manual', data.notes, runById),
    },
    developers: developerStats(data, runs, start, end, reviewById),
    people: peopleStats(data.reviews.filter((r) =>
      within(r.created_at, start, end) || runs.some((x) => x.review_id === r.id))),
    punch: punchCard(runs),
    repos: repoActivity(data, reviewById),
    daily: dailyTotals(data),
  }
}

export const ENGINE_ORDER = ['claude', 'codex', 'cursor', 'anthropic', 'openai', 'agent']

export interface GroupRow {
  key: string
  runs: number
  done: number
  failed: number
  success: number | null
  p50: number
  p90: number
  avgCost: number
  findingsPerRun: number
  seriousPerRun: number
  noise: number | null
  judged: number
}

function groupStats(
  runs: ARun[], keyOf: (r: ARun) => string, notes: ANote[], runById: Map<string, ARun>,
): GroupRow[] {
  const groups = new Map<string, ARun[]>()
  for (const r of runs) groups.set(keyOf(r), [...(groups.get(keyOf(r)) ?? []), r])
  // Noise: of the findings you made a call on, how many you dismissed.
  const judged = new Map<string, { all: number; dismissed: number }>()
  for (const n of notes) {
    if (n.origin !== 'claude' || n.status === 'open') continue
    const run = runById.get(n.run_id)
    if (!run) continue
    const k = keyOf(run)
    const j = judged.get(k) ?? { all: 0, dismissed: 0 }
    j.all += 1
    if (n.status === 'dismissed') j.dismissed += 1
    judged.set(k, j)
  }
  return [...groups.entries()].map(([key, rs]) => {
    const done = rs.filter((r) => r.status === 'done')
    const failed = rs.filter((r) => r.status === 'failed').length
    const durations = done.map((r) => r.duration_ms).filter((d) => d > 0)
    const j = judged.get(key)
    return {
      key,
      runs: rs.length,
      done: done.length,
      failed,
      success: done.length + failed ? done.length / (done.length + failed) : null,
      p50: quantile(durations, 0.5),
      p90: quantile(durations, 0.9),
      avgCost: rs.length ? rs.reduce((a, r) => a + (r.cost_usd || 0), 0) / rs.length : 0,
      findingsPerRun: done.length ? done.reduce((a, r) => a + findingsOf(r), 0) / done.length : 0,
      seriousPerRun: done.length ? done.reduce((a, r) => a + seriousOf(r), 0) / done.length : 0,
      noise: j?.all ? j.dismissed / j.all : null,
      judged: j?.all ?? 0,
    }
  }).sort((a, b) => b.runs - a.runs)
}

export interface DevRow {
  author: string
  prs: number
  runs: number
  findings: number
  serious: number
  needsWork: number
  reviewed: number
  churn: number
  last: string
  repos: number
}

function developerStats(
  data: AnalyticsData, runs: ARun[], start: Date, end: Date, reviewById: Map<string, ARev>,
): DevRow[] {
  const latestDone = new Map<string, ARun>()
  for (const r of data.runs) if (r.status === 'done' && r.kind !== 'second_opinion') latestDone.set(r.review_id, r)  // runs are ordered
  const active = new Set(runs.map((r) => r.review_id))
  const rows = new Map<string, DevRow & { repoSet: Set<string> }>()
  for (const rev of data.reviews) {
    if (!active.has(rev.id) && !within(rev.created_at, start, end)) continue
    const who = rev.author || 'unknown'
    const row = rows.get(who) ?? {
      author: who, prs: 0, runs: 0, findings: 0, serious: 0, needsWork: 0, reviewed: 0,
      churn: 0, last: '', repos: 0, repoSet: new Set<string>(),
    }
    row.prs += 1
    row.churn += (rev.additions || 0) + (rev.deletions || 0)
    row.repoSet.add(`${rev.namespace}/${rev.project}`)
    const last = latestDone.get(rev.id)
    if (last) {
      row.reviewed += 1
      row.findings += findingsOf(last)
      row.serious += seriousOf(last)
      if (last.verdict === 'needs_work') row.needsWork += 1
    }
    const touched = [rev.created_at, last?.created_at ?? ''].sort().pop() ?? ''
    if (touched > row.last) row.last = touched
    rows.set(who, row)
  }
  for (const r of runs) {
    const rev = reviewById.get(r.review_id)
    const row = rev && rows.get(rev.author || 'unknown')
    if (row) row.runs += 1
  }
  return [...rows.values()].map(({ repoSet, ...r }) => ({ ...r, repos: repoSet.size }))
    .sort((a, b) => b.prs - a.prs || b.findings - a.findings)
}

export interface PersonRow { name: string; authored: number; assigned: number; requested: number }

function peopleStats(reviews: ARev[]): PersonRow[] {
  const rows = new Map<string, PersonRow>()
  const get = (name: string) => {
    const r = rows.get(name) ?? { name, authored: 0, assigned: 0, requested: 0 }
    rows.set(name, r)
    return r
  }
  for (const rev of reviews) {
    if (rev.author) get(rev.author).authored += 1
    for (const a of rev.assignees ?? []) if (a) get(a).assigned += 1
    for (const a of rev.reviewers ?? []) if (a) get(a).requested += 1
  }
  return [...rows.values()]
    .filter((r) => r.assigned || r.requested)
    .sort((a, b) => b.assigned + b.requested - (a.assigned + a.requested))
}

function punchCard(runs: ARun[]): number[][] {
  const grid = Array.from({ length: 7 }, () => Array<number>(24).fill(0))
  for (const r of runs) {
    const d = new Date(r.created_at)
    grid[(d.getDay() + 6) % 7][d.getHours()] += 1   // Monday first
  }
  return grid
}

export interface RepoActivity {
  key: string
  namespace: string
  project: string
  provider: string
  lastUsed: string
  prs: number
  open: number
  runs30: number[]
  latestReviewId: string
}

/** Repositories ranked by when you last did anything in them. */
function repoActivity(data: AnalyticsData, reviewById: Map<string, ARev>): RepoActivity[] {
  const today = startOfDay(new Date())
  const map = new Map<string, RepoActivity>()
  const ensure = (r: ARev) => {
    const key = `${r.host}/${r.namespace}/${r.project}`
    let row = map.get(key)
    if (!row) {
      row = { key, namespace: r.namespace, project: r.project, provider: r.provider, lastUsed: '',
        prs: 0, open: 0, runs30: Array(30).fill(0), latestReviewId: r.id }
      map.set(key, row)
    }
    return row
  }
  // Last use is the last review run (or when the PR was added), never a
  // background sync, which touches every PR on its own schedule.
  for (const r of data.reviews) {
    const row = ensure(r)
    row.prs += 1
    if (r.state === 'open') row.open += 1
    if (r.created_at > row.lastUsed) { row.lastUsed = r.created_at; row.latestReviewId = r.id }
  }
  for (const run of data.runs) {
    const rev = reviewById.get(run.review_id)
    if (!rev) continue
    const row = ensure(rev)
    if (run.created_at > row.lastUsed) { row.lastUsed = run.created_at; row.latestReviewId = rev.id }
    const ago = Math.floor((today.getTime() - startOfDay(new Date(run.created_at)).getTime()) / DAY)
    if (ago >= 0 && ago < 30) row.runs30[29 - ago] += 1
  }
  return [...map.values()].sort((a, b) => b.lastUsed.localeCompare(a.lastUsed))
}

/** Per-day totals over the last 53 weeks, for the contribution heatmap. */
function dailyTotals(data: AnalyticsData) {
  const runs = new Map<string, number>()
  const findings = new Map<string, number>()
  const prs = new Map<string, number>()
  const bump = (m: Map<string, number>, k: string, v = 1) => m.set(k, (m.get(k) ?? 0) + v)
  for (const r of data.runs) {
    bump(runs, dayKey(r.created_at))
    if (r.status === 'done') bump(findings, dayKey(r.created_at), findingsOf(r))
  }
  for (const r of data.reviews) bump(prs, dayKey(r.created_at))
  return { runs, findings, prs }
}

export function streaks(perDay: Map<string, number>) {
  let current = 0
  let best = 0
  let run = 0
  const today = startOfDay(new Date())
  const days = daysBetween(new Date(today.getTime() - 370 * DAY), today)
  for (const d of days) {
    if ((perDay.get(dayKey(d)) ?? 0) > 0) { run += 1; best = Math.max(best, run) } else run = 0
  }
  // Today not being active yet does not break a streak that ran to yesterday.
  for (let i = days.length - 1; i >= 0; i--) {
    const v = perDay.get(dayKey(days[i])) ?? 0
    if (v > 0) current += 1
    else if (i !== days.length - 1) break
  }
  return { current, best }
}

export type Model = ReturnType<typeof buildModel>
