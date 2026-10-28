import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { api } from '../lib/api'
import {
  buildModel, delta, ENGINE_ORDER, RANGES, streaks, type AnalyticsData, type DevRow, type GroupRow,
  type Range,
} from '../lib/analytics'
import type { ReviewFilters } from '../lib/filters'
import { engineLabel, isRunning, MODE_LABEL, scheduleLabel } from '../lib/labels'
import { duration, timeAgo } from '../lib/time'
import type { Review, Status, Wakeup } from '../lib/types'
import type { Page } from './Sidebar'
import { AddBar } from './AddBar'
import { AreaLine, Heatmap, HBars, Legend, PunchCard, Sparkline, StackedBars } from './charts'
import { Icon, Spinner } from './Icon'

/** Colour follows the engine, never its rank: each engine owns a slot. */
const ENGINE_COLOR: Record<string, string> = {
  claude: 'var(--series-1)',
  codex: 'var(--series-2)',
  cursor: 'var(--series-3)',
  anthropic: 'var(--series-4)',
  openai: 'var(--series-5)',
  agent: 'var(--series-other)',
}

const TRIGGER_LABEL: Record<string, string> = {
  manual: 'Manual', watch: 'Watch (new commits)', schedule: 'Wakeup', api: 'API / skill',
}

const CATEGORY_LABEL: Record<string, string> = {
  correctness: 'Correctness', security: 'Security', performance: 'Performance', tests: 'Tests',
  style: 'Style', docs: 'Docs', design: 'Design', api: 'API',
}

type HeatMetric = 'runs' | 'findings' | 'prs'
type GroupBy = 'engine' | 'mode' | 'trigger'

const money = (v: number) => (v >= 100 ? `$${v.toFixed(0)}` : v >= 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(3)}`)
const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

function loadRange(): Range {
  try {
    const label = localStorage.getItem('selfcheck.range')
    return RANGES.find((r) => r.label === label) ?? RANGES[2]
  } catch {
    return RANGES[2]
  }
}

export function Overview({
  reviews, wakeups, status, lastSeen, onSeen, onOpen, onFilter, onNavigate, onAdded, onShortcuts,
}: {
  reviews: Review[]
  wakeups: Wakeup[]
  status: Status | null
  lastSeen: string
  onSeen: () => void
  onOpen: (id: string) => void
  onFilter: (f: ReviewFilters) => void
  onNavigate: (to: Page, focusRepo?: string) => void
  onAdded: (review: Review) => void
  onShortcuts: () => void
}) {
  const onWakeups = (repo?: string) => onNavigate('wakeups', repo)
  const addBar = <AddBar onAdded={onAdded} onWakeup={(key) => onNavigate('wakeups', key)} />
  const [data, setData] = useState<AnalyticsData | null>(null)
  const [error, setError] = useState('')
  const [range, setRangeState] = useState<Range>(loadRange)
  const [heatMetric, setHeatMetric] = useState<HeatMetric>('runs')
  const [cumMetric, setCumMetric] = useState<HeatMetric>('runs')
  const [groupBy, setGroupBy] = useState<GroupBy>('engine')

  const setRange = (r: Range) => {
    setRangeState(r)
    try { localStorage.setItem('selfcheck.range', r.label) } catch { /* private mode */ }
  }

  const load = useCallback(() => {
    api.analytics().then(setData).catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [])

  // Refetch whenever the review list changes shape (a run finished, a PR was added).
  const listSignature = reviews.map((r) => `${r.id}:${r.updated_at}:${r.latest_run?.status}`).join('|')
  useEffect(() => { load() }, [load, listSignature])

  const model = useMemo(() => (data ? buildModel(data, range) : null), [data, range])
  const running = reviews.filter((r) => isRunning(r.latest_run?.status))

  if (!reviews.length) {
    return (
      <div className="page">
        <GettingStarted status={status} wakeups={wakeups} addBar={addBar} onNavigate={onNavigate} />
      </div>
    )
  }

  if (!model) {
    return (
      <div className="page">
        <div className="blank">{error ? <span className="inline-err">{error}</span> : <><Spinner /> Crunching numbers…</>}</div>
      </div>
    )
  }

  const k = model.kpis
  const rangeNoun = range.days ? `the last ${range.days === 365 ? 'year' : `${range.days} days`}` : 'all time'
  const heatData = model.daily[heatMetric]
  const streak = streaks(model.daily.runs)
  const yearTotal = [...heatData.values()].reduce((a, b) => a + b, 0)
  const series = model.engines.map((e) => ({
    key: e, label: engineLabel(e, status), color: ENGINE_COLOR[e] ?? 'var(--series-other)',
  }))
  const groupRows = model.groups[groupBy]

  return (
    <div className="page dash">
      <header className="page-head">
        <div>
          <h1>Overview</h1>
          <p className="muted">How selfcheck has been used over {rangeNoun}: what was reviewed, what it found, how the engines performed, and who the work came from.</p>
        </div>
        <div className="row head-tools">
          <div className="seg" role="group" aria-label="Date range">
            {RANGES.map((r) => (
              <button key={r.label} className={range.label === r.label ? 'on' : ''} onClick={() => setRange(r)}>{r.label}</button>
            ))}
          </div>
          <button className="icon-btn" onClick={onShortcuts} title="Keyboard shortcuts (?)" aria-label="Keyboard shortcuts">
            <Icon name="keyboard" />
          </button>
        </div>
      </header>

      {addBar}

      <SinceStrip reviews={reviews} lastSeen={lastSeen} onSeen={onSeen} onFilter={onFilter} onOpen={onOpen} />

      {/* ── headline numbers ── */}
      <div className="kpis">
        <Kpi icon="sparkle" label="Reviews run" value={k.runs.cur.toLocaleString()} d={delta(k.runs.cur, k.runs.prev)}
          spark={model.buckets.map((b) => b.total)} hint="Review runs started, by any engine or trigger."
          onClick={() => onFilter({ since: model.start.toISOString(), event: 'reviewed' })} />
        <Kpi icon="note" label="Findings raised" value={k.findings.cur.toLocaleString()} d={delta(k.findings.cur, k.findings.prev)}
          spark={model.buckets.map((b) => b.findings)} hint="Findings in completed runs, counted per run." />
        <Kpi icon="pr" label="PRs tracked" value={k.prs.cur.toLocaleString()} d={delta(k.prs.cur, k.prs.prev)}
          hint="Pull/merge requests added in this period."
          onClick={() => onFilter({ since: model.start.toISOString(), event: 'added' })} />
        <Kpi icon="gauge" label="Findings per review" value={k.perRun.cur.toFixed(1)}
          hint="Average findings in a completed run." />
        <Kpi icon="alarm" label="Median review time" value={k.medianMs.cur ? duration(k.medianMs.cur) : '—'}
          d={k.medianMs.prev ? delta(k.medianMs.cur, k.medianMs.prev) : null} invert
          hint="Wall-clock time of a completed run, median." />
        <Kpi icon="check" label="Success rate" value={pct(k.success.cur)}
          hint="Completed ÷ (completed + failed). Cancelled runs are left out." />
        <Kpi icon="x" label="Noise" value={pct(k.noise.cur)} sub={`${k.noise.judged} findings judged`}
          hint="Of the findings you resolved, dismissed or marked won't-fix in this period, the share you dismissed as not real." />
        <Kpi icon="cpu" label="Spend" value={money(k.spend.cur)} d={delta(k.spend.cur, k.spend.prev)} invert
          hint="Reported by the engine; local CLI subscriptions may report $0." />
      </div>

      {/* ── activity heatmap ── */}
      <Card
        title="Activity"
        subtitle="Every day of the last year. Darker is busier."
        tools={
          <div className="seg sm" role="group" aria-label="Heatmap metric">
            {(['runs', 'findings', 'prs'] as HeatMetric[]).map((m) => (
              <button key={m} className={heatMetric === m ? 'on' : ''} onClick={() => setHeatMetric(m)}>
                {m === 'runs' ? 'Reviews' : m === 'findings' ? 'Findings' : 'PRs added'}
              </button>
            ))}
          </div>
        }
      >
        <div className="activity">
          <Heatmap
            perDay={heatData}
            noun={heatMetric === 'runs' ? 'reviews' : heatMetric === 'findings' ? 'findings' : 'PRs added'}
            onDay={(d) => onFilter({
              since: d.toISOString(),
              until: new Date(d.getFullYear(), d.getMonth(), d.getDate() + 1).toISOString(),
              event: heatMetric === 'prs' ? 'added' : 'reviewed',
            })}
          />
          <dl className="activity-stats">
            <div><dt>Last 12 months</dt><dd>{yearTotal.toLocaleString()}</dd></div>
            <div><dt>Current streak</dt><dd>{streak.current} day{streak.current === 1 ? '' : 's'}</dd></div>
            <div><dt>Longest streak</dt><dd>{streak.best} day{streak.best === 1 ? '' : 's'}</dd></div>
            <div><dt>Active days</dt><dd>{[...heatData.values()].filter((v) => v > 0).length}</dd></div>
          </dl>
        </div>
      </Card>

      {/* ── over time ── */}
      <div className="dash-grid two">
        <Card title={`Reviews per ${model.weekly ? 'week' : 'day'}`} subtitle="Stacked by engine.">
          <Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />
          <StackedBars
            buckets={model.buckets.map((b) => ({ key: b.key, values: b.byEngine }))}
            series={series}
            weekly={model.weekly}
            unit="reviews"
          />
        </Card>
        <Card
          title="Cumulative"
          subtitle="Running total since the first review."
          tools={
            <div className="seg sm" role="group" aria-label="Cumulative metric">
              {(['runs', 'findings', 'prs'] as HeatMetric[]).map((m) => (
                <button key={m} className={cumMetric === m ? 'on' : ''} onClick={() => setCumMetric(m)}>
                  {m === 'runs' ? 'Reviews' : m === 'findings' ? 'Findings' : 'PRs'}
                </button>
              ))}
            </div>
          }
        >
          <AreaLine
            points={model.cumulative.map((c) => ({ key: c.key, value: c[cumMetric] }))}
            unit={cumMetric === 'runs' ? 'reviews' : cumMetric === 'findings' ? 'findings' : 'PRs'}
          />
        </Card>
      </div>

      {/* ── what it finds ── */}
      <div className="dash-grid three">
        <Card title="Severity" subtitle="Findings raised in this period. Click one for the PRs that still have it open.">
          <HBars
            onPick={(sev) => onFilter({ severity: sev as ReviewFilters['severity'] })}
            unit="findings"
            rows={(['blocker', 'major', 'minor', 'question', 'nit', 'praise'] as const).map((s) => ({
              key: s, label: <><span className={`dot sev-${s}`} /> {s}</>, value: model.severity[s], className: `fill-${s}`,
            }))}
          />
        </Card>
        <Card title="Category" subtitle="What the findings are about.">
          <HBars
            unit="findings"
            rows={Object.entries(model.categories).sort((a, b) => b[1] - a[1]).map(([c, v]) => ({
              key: c, label: CATEGORY_LABEL[c] ?? c, value: v,
            }))}
          />
        </Card>
        <Card title="What happened to them" subtitle="Your calls on the findings, and what is still open.">
          <HBars
            unit="findings"
            rows={[
              { key: 'open', label: 'Still open', value: model.outcomes.open ?? 0, className: 'fill-open' },
              { key: 'resolved', label: 'Resolved', value: model.outcomes.resolved ?? 0, className: 'fill-resolved', hint: 'fixed or dealt with' },
              { key: 'wontfix', label: "Won't fix", value: model.outcomes.wontfix ?? 0, className: 'fill-wontfix', hint: 'real, but out of scope' },
              { key: 'dismissed', label: 'Dismissed', value: model.outcomes.dismissed ?? 0, className: 'fill-dismissed', hint: 'not a real finding' },
            ]}
          />
        </Card>
      </div>

      {/* ── tool performance ── */}
      <Card
        title="Performance"
        subtitle="How each engine, depth and trigger did in this period. Noise is the share of judged findings you dismissed — lower is better."
        tools={
          <div className="seg sm" role="group" aria-label="Group by">
            {(['engine', 'mode', 'trigger'] as GroupBy[]).map((g) => (
              <button key={g} className={groupBy === g ? 'on' : ''} onClick={() => setGroupBy(g)}>
                {g === 'engine' ? 'Engine' : g === 'mode' ? 'Depth' : 'Trigger'}
              </button>
            ))}
          </div>
        }
      >
        <PerfTable rows={groupRows}
          onPick={(key) => onFilter(groupBy === 'engine' ? { engine: key } : groupBy === 'mode' ? { mode: key } : { trigger: key })}
          labelOf={(key) => groupBy === 'engine'
          ? <><span className="viz-swatch" style={{ background: ENGINE_COLOR[key] ?? 'var(--series-other)' }} />{engineLabel(key, status)}</>
          : groupBy === 'mode' ? (MODE_LABEL[key as 'light'] ?? key) : (TRIGGER_LABEL[key] ?? key)} />
      </Card>

      {/* ── people ── */}
      <div className="dash-grid wide-narrow">
        <Card title="Developers" subtitle="Authors of the PRs reviewed in this period, from their latest review. Click a column to sort.">
          <DevTable rows={model.developers} onPick={(author) => onFilter({ author })} />
        </Card>
        <Card title="Who gets the reviews" subtitle="Assignees and requested reviewers on those PRs.">
          {model.people.length ? (
            <div className="table-scroll">
            <table className="dtab compact">
              <thead><tr><th>Person</th><th className="num">Assigned</th><th className="num">Requested</th><th className="num">Authored</th></tr></thead>
              <tbody>
                {model.people.slice(0, 12).map((p) => (
                  <tr key={p.name} className="clickable" onClick={() => onFilter({ person: p.name })}
                    title={`PRs where ${p.name} is an assignee or a requested reviewer`}>
                    <td><span className="avatar">{p.name.slice(0, 1).toUpperCase()}</span>{p.name}</td>
                    <td className="num">{p.assigned || '—'}</td>
                    <td className="num">{p.requested || '—'}</td>
                    <td className="num faint">{p.authored || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          ) : (
            <p className="viz-empty">
              No assignees or reviewers recorded yet. They are read on each sync, so they fill in as
              PRs are synced or re-reviewed.
            </p>
          )}
        </Card>
      </div>

      {/* ── where things are ── */}
      <div className="dash-grid three">
        <Card title="When you review" subtitle="Reviews started, by weekday and hour (your time).">
          <PunchCard grid={model.punch} noun="reviews" />
        </Card>
        <Card title="Recently used repositories" subtitle="Ranked by last activity. The rest are in the sidebar.">
          <div className="recent-repos">
            {model.repos.slice(0, 5).map((r) => {
              const wake = wakeups.find((w) => `${w.host}/${w.namespace}/${w.project}` === r.key)
              return (
                <button key={r.key} className="recent-repo" onClick={() => onFilter({ repo: r.key })} title="All reviews in this repository">
                  <span className="recent-name">
                    <strong className="truncate">{r.project}</strong>
                    <span className="faint truncate">{r.namespace}</span>
                  </span>
                  <span className="recent-spark" title="Reviews per day, last 30 days"><Sparkline values={r.runs30} height={22} /></span>
                  <span className="recent-meta">
                    <span>{r.prs} PR{r.prs === 1 ? '' : 's'}</span>
                    <span className="faint">{timeAgo(r.lastUsed)}</span>
                  </span>
                  {wake?.enabled ? (
                    <span className="wake-badge on" title={scheduleLabel(wake)}><Icon name="alarm" size={11} /></span>
                  ) : <span />}
                </button>
              )
            })}
            {!model.repos.length && <p className="viz-empty">No repositories yet.</p>}
          </div>
          <button className="btn ghost sm" onClick={() => onWakeups()}><Icon name="alarm" size={13} /> Manage wakeups</button>
        </Card>
        <Card title="In progress" subtitle={`Up to ${status?.max_concurrent_runs ?? '…'} reviews run at once; the rest queue.`}>
          {running.length ? (
            <div className="recent-repos">
              {running.map((r) => (
                <button key={r.id} className="recent-repo" onClick={() => onOpen(r.id)}>
                  <Spinner />
                  <span className="recent-name">
                    <strong className="truncate">#{r.number} {r.title}</strong>
                    <span className="faint truncate">{r.project} · {engineLabel(r.latest_run!.engine, status)} · {MODE_LABEL[r.latest_run!.mode] ?? r.latest_run!.mode}</span>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <p className="viz-empty">Nothing running right now.</p>
          )}
        </Card>
      </div>
    </div>
  )
}

function Card({ title, subtitle, tools, children }: {
  title: string; subtitle?: string; tools?: ReactNode; children: ReactNode
}) {
  return (
    <section className="dcard">
      <header className="dcard-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {tools}
      </header>
      {children}
    </section>
  )
}

function Kpi({ icon, label, value, d, spark, hint, sub, invert = false, onClick }: {
  icon: string; label: string; value: string; d?: number | null; spark?: number[]
  hint: string; sub?: string; invert?: boolean; onClick?: () => void
}) {
  // For time and spend, going down is the good direction.
  const good = d === undefined || d === null || d === 0 ? null : invert ? d < 0 : d > 0
  return (
    <div className={`kpi ${onClick ? 'clickable' : ''}`} title={onClick ? `${hint} Click to see them.` : hint}
      role={onClick ? 'button' : undefined} tabIndex={onClick ? 0 : undefined} onClick={onClick}
      onKeyDown={onClick ? (e) => e.key === 'Enter' && onClick() : undefined}>
      <span className="kpi-label"><Icon name={icon} size={13} /> {label}</span>
      <span className="kpi-value">{value}</span>
      <span className="kpi-foot">
        {d !== undefined && (
          d === null
            ? <span className="faint">new this period</span>
            : <span className={`kpi-delta ${good === null ? '' : good ? 'up' : 'down'}`}>
                <Icon name={d >= 0 ? 'arrow-up' : 'arrow-down'} size={11} />
                {Math.abs(Math.round(d * 100))}% <span className="faint">vs previous</span>
              </span>
        )}
        {sub && <span className="faint">{sub}</span>}
      </span>
      {spark && spark.some((v) => v > 0)
        ? <span className="kpi-spark"><Sparkline values={spark} /></span>
        : <span className="kpi-spark-blank" />}
    </div>
  )
}

function PerfTable({ rows, labelOf, onPick }: {
  rows: GroupRow[]; labelOf: (key: string) => ReactNode; onPick: (key: string) => void
}) {
  if (!rows.length) return <p className="viz-empty">No reviews ran in this period.</p>
  const maxRuns = Math.max(...rows.map((r) => r.runs))
  return (
    <div className="table-scroll">
      <table className="dtab">
        <thead>
          <tr>
            <th>Name</th><th>Reviews</th><th className="num">Success</th><th className="num">Median time</th>
            <th className="num">p90 time</th><th className="num">Findings / review</th>
            <th className="num">Serious / review</th><th className="num">Noise</th><th className="num">Avg cost</th>
          </tr>
        </thead>
        <tbody>
          {rows.sort((a, b) => ENGINE_ORDER.indexOf(a.key) - ENGINE_ORDER.indexOf(b.key) || b.runs - a.runs).map((r) => (
            <tr key={r.key} className="clickable" onClick={() => onPick(r.key)} title="PRs whose latest review used this">
              <td className="name-cell">{labelOf(r.key)}</td>
              <td>
                <span className="inline-bar"><span style={{ width: `${(r.runs / maxRuns) * 100}%` }} /></span>
                <span className="num-inline">{r.runs}</span>
                {r.failed > 0 && <span className="faint"> · {r.failed} failed</span>}
              </td>
              <td className="num">{pct(r.success)}</td>
              <td className="num">{r.p50 ? duration(r.p50) : '—'}</td>
              <td className="num">{r.p90 ? duration(r.p90) : '—'}</td>
              <td className="num">{r.done ? r.findingsPerRun.toFixed(1) : '—'}</td>
              <td className="num">{r.done ? r.seriousPerRun.toFixed(1) : '—'}</td>
              <td className="num" title={`${r.judged} findings judged`}>{pct(r.noise)}</td>
              <td className="num">{r.avgCost ? money(r.avgCost) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type DevKey = keyof DevRow | 'perPr' | 'needsRate'

function DevTable({ rows, onPick }: { rows: DevRow[]; onPick: (author: string) => void }) {
  const [sort, setSort] = useState<{ key: DevKey; desc: boolean }>({ key: 'prs', desc: true })
  const value = (r: DevRow, key: DevKey): number | string =>
    key === 'perPr' ? (r.reviewed ? r.findings / r.reviewed : -1)
      : key === 'needsRate' ? (r.reviewed ? r.needsWork / r.reviewed : -1)
        : key === 'serious' ? (r.reviewed ? r.serious / r.reviewed : -1)
          : r[key]
  const sorted = [...rows].sort((a, b) => {
    const va = value(a, sort.key)
    const vb = value(b, sort.key)
    const c = typeof va === 'string' ? String(va).localeCompare(String(vb)) : (va as number) - (vb as number)
    return sort.desc ? -c : c
  })
  if (!rows.length) return <p className="viz-empty">No PRs in this period.</p>
  const th = (key: DevKey, label: string, num = true) => (
    <th className={`${num ? 'num' : ''} sortable ${sort.key === key ? 'sorted' : ''}`}
      onClick={() => setSort((s) => ({ key, desc: s.key === key ? !s.desc : true }))}
      aria-sort={sort.key === key ? (sort.desc ? 'descending' : 'ascending') : 'none'}>
      {label}{sort.key === key && <Icon name={sort.desc ? 'chevron-down' : 'chevron-up'} size={11} />}
    </th>
  )
  return (
    <div className="table-scroll">
      <table className="dtab">
        <thead>
          <tr>
            {th('author', 'Developer', false)}{th('prs', 'PRs')}{th('runs', 'Reviews')}
            {th('perPr', 'Findings / PR')}{th('serious', 'Serious / PR')}{th('needsRate', 'Needs work')}
            {th('churn', 'Lines changed')}{th('repos', 'Repos')}{th('last', 'Last active')}
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, 15).map((r) => (
            <tr key={r.author} className="clickable" onClick={() => onPick(r.author)} title={`PRs by ${r.author}`}>
              <td><span className="avatar">{r.author.slice(0, 1).toUpperCase()}</span>{r.author}</td>
              <td className="num">{r.prs}</td>
              <td className="num">{r.runs}</td>
              <td className="num">{r.reviewed ? (r.findings / r.reviewed).toFixed(1) : '—'}</td>
              <td className="num">{r.reviewed ? <span className={r.serious / r.reviewed >= 2 ? 'sev-major' : ''}>{(r.serious / r.reviewed).toFixed(1)}</span> : '—'}</td>
              <td className="num">{r.reviewed ? pct(r.needsWork / r.reviewed) : '—'}</td>
              <td className="num">{r.churn.toLocaleString()}</td>
              <td className="num">{r.repos}</td>
              <td className="num faint">{r.last ? timeAgo(r.last) : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** What changed since you last looked: new PRs (and how many a wakeup
 *  brought), finished reviews, and the serious findings they raised. */
function SinceStrip({
  reviews, lastSeen, onSeen, onFilter, onOpen,
}: {
  reviews: Review[]
  lastSeen: string
  onSeen: () => void
  onFilter: (f: ReviewFilters) => void
  onOpen: (id: string) => void
}) {
  if (!lastSeen) return null
  const since = Date.parse(lastSeen)
  const after = (iso?: string) => !!iso && Date.parse(iso) > since
  const added = reviews.filter((r) => after(r.created_at))
  const fromWakeups = added.filter((r) => r.repo_watch_id)
  const finished = reviews.filter((r) => r.latest_run && ['done', 'failed'].includes(r.latest_run.status)
    && after(r.latest_run.finished_at || r.latest_run.created_at))
  const failed = finished.filter((r) => r.latest_run!.status === 'failed')
  const blockers = finished.reduce((n, r) => n + (r.counts?.blocker ?? 0), 0)
  const majors = finished.reduce((n, r) => n + (r.counts?.major ?? 0), 0)
  if (!added.length && !finished.length) return null

  const when = new Date(lastSeen).toLocaleString(undefined, { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
  const item = (n: number, text: string, f: ReviewFilters, tone = '', only?: Review[]) => n > 0 && (
    <button className={`since-item ${tone}`}
      onClick={() => (only?.length === 1 ? onOpen(only[0].id) : onFilter(f))}>
      <strong>{n}</strong> {text}
    </button>
  )
  return (
    <div className="since-strip" role="status">
      <span className="since-label"><Icon name="sparkle" size={14} /> Since you were last here <span className="faint">({when})</span></span>
      <div className="since-items">
        {item(added.length, `new PR${added.length === 1 ? '' : 's'}${fromWakeups.length ? ` · ${fromWakeups.length} from wakeups` : ''}`,
          { since: lastSeen, event: 'added' }, '', added)}
        {item(finished.length - failed.length, `review${finished.length - failed.length === 1 ? '' : 's'} finished`,
          { since: lastSeen, event: 'reviewed' }, '', finished.filter((r) => r.latest_run!.status === 'done'))}
        {item(blockers, `blocker${blockers === 1 ? '' : 's'}`, { since: lastSeen, event: 'reviewed', severity: 'blocker' }, 'sev-blocker')}
        {item(majors, `major${majors === 1 ? '' : 's'}`, { since: lastSeen, event: 'reviewed', severity: 'major' }, 'sev-major')}
        {item(failed.length, `failed`, { since: lastSeen, event: 'reviewed' }, 'sev-blocker', failed)}
      </div>
      <button className="btn ghost xs" onClick={onSeen} title="Mark all of this as seen">Got it</button>
    </div>
  )
}

/** First run: what to set up, in order, with each step ticking itself off. */
function GettingStarted({
  status, wakeups, addBar, onNavigate,
}: {
  status: Status | null
  wakeups: Wakeup[]
  addBar: ReactNode
  onNavigate: (to: Page) => void
}) {
  const engine = status?.engines.find((e) => e.id === status.default_engine)
  const anyEngine = status?.engines.some((e) => e.available) ?? false
  const tokens = status?.providers.filter((p) => p.token_configured) ?? []
  const steps: { done: boolean; title: string; body: ReactNode; action?: ReactNode }[] = [
    {
      done: !!engine?.available,
      title: 'Pick a review engine',
      body: engine?.available
        ? <>Reviews will run on <strong>{engine.label}</strong>{engine.model ? <> with <code>{engine.model}</code></> : ''}. You can switch any time from the sidebar footer.</>
        : anyEngine
          ? <>The default engine isn’t set up, but another one is. Make it the default.</>
          : <>None is set up yet: install Claude Code, Codex or Cursor Agent, or add an API key to <code>.env</code>.</>,
      action: <button className="btn sm" onClick={() => onNavigate('settings')}><Icon name="settings" size={13} /> Open Settings</button>,
    },
    {
      done: tokens.length > 0,
      title: 'Connect GitHub or GitLab',
      body: tokens.length
        ? <>Read-only tokens found for {tokens.map((t) => <code key={t.host}>{t.host}</code>).reduce<ReactNode[]>((a, c, i) => (i ? [...a, ', ', c] : [c]), [])}.</>
        : <>Put a read-scoped <code>GITHUB_TOKEN</code> or <code>GITLAB_TOKEN</code> in <code>.env</code> and restart. Public repos work without one.</>,
    },
    {
      done: false,
      title: 'Review your first pull request',
      body: <>Paste a pull request or merge request link — or a local repository path, to check a branch before you push. It is reviewed against a read-only checkout; nothing is posted back.</>,
      action: undefined,
    },
    {
      done: wakeups.length > 0,
      title: 'Optional: wake up for a repository',
      body: <>Pick a repo and a time, like daily at 09:00, and new PRs are reviewed before you get to them.</>,
      action: <button className="btn sm" onClick={() => onNavigate('wakeups')}><Icon name="alarm" size={13} /> Set up a wakeup</button>,
    },
  ]
  return (
    <div className="getting-started">
      <span className="blank-icon"><Icon name="sparkle" size={24} /></span>
      <h1>Welcome to selfcheck</h1>
      <p className="muted">Four steps and you are reviewing. Your dashboard appears here once there is something to show.</p>
      <div className="gs-add">{addBar}</div>
      <ol className="gs-steps">
        {steps.map((st, i) => (
          <li key={st.title} className={`gs-step ${st.done ? 'done' : ''}`}>
            <span className="gs-mark">{st.done ? <Icon name="check" size={13} /> : i + 1}</span>
            <div className="gs-body">
              <strong>{st.title}</strong>
              <p>{st.body}</p>
            </div>
            {st.action && !st.done && <div className="gs-action">{st.action}</div>}
          </li>
        ))}
      </ol>
    </div>
  )
}
