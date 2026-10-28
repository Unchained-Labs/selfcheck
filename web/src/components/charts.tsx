/** Small, dependency-free SVG charts for the overview.
 *
 *  Conventions: thin marks with 4px rounded data ends anchored to the
 *  baseline, a 2px surface gap between adjacent fills, recessive grid, text in
 *  text tokens (never the series colour), a legend whenever there is more than
 *  one series, and a hover tooltip on every mark. */

import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { dayKey, daysBetween, startOfDay } from '../lib/analytics'

/* ── plumbing ──────────────────────────────────────────────────────────── */

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(el.clientWidth)
    const ro = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, width] as const
}

interface Tip { x: number; y: number; content: ReactNode }

/** Hover tooltip positioned inside `box`, the chart's container. */
function useTip(box: React.RefObject<HTMLDivElement | null>) {
  const [tip, setTip] = useState<Tip | null>(null)
  const show = (e: React.MouseEvent, content: ReactNode) => {
    const r = box.current?.getBoundingClientRect()
    if (!r) return
    setTip({ x: e.clientX - r.left, y: e.clientY - r.top, content })
  }
  const hide = () => setTip(null)
  const el = tip && (
    <div
      className="viz-tip"
      style={{
        left: Math.min(tip.x + 12, (box.current?.clientWidth ?? 0) - 180),
        top: tip.y + 14,
      }}
    >
      {tip.content}
    </div>
  )
  return { show, hide, el }
}

export function Legend({ items }: { items: { label: string; color: string; value?: ReactNode }[] }) {
  return (
    <div className="viz-legend">
      {items.map((i) => (
        <span key={i.label} className="viz-legend-item">
          <span className="viz-swatch" style={{ background: i.color }} />
          {i.label}
          {i.value !== undefined && <strong>{i.value}</strong>}
        </span>
      ))}
    </div>
  )
}

/** A rect whose top corners are rounded and bottom sits square on the baseline. */
function topRounded(x: number, y: number, w: number, h: number, r = 4) {
  const rr = Math.max(0, Math.min(r, w / 2, h))
  return `M${x},${y + h}V${y + rr}Q${x},${y} ${x + rr},${y}H${x + w - rr}Q${x + w},${y} ${x + w},${y + rr}V${y + h}Z`
}

function niceMax(v: number) {
  if (v <= 4) return Math.max(1, Math.ceil(v))
  const p = 10 ** Math.floor(Math.log10(v))
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p
  return 10 * p
}

const fmtDay = (key: string, opts: Intl.DateTimeFormatOptions = { month: 'short', day: 'numeric' }) =>
  new Date(`${key}T00:00:00`).toLocaleDateString(undefined, opts)

/* ── sparkline ─────────────────────────────────────────────────────────── */

export function Sparkline({ values, height = 28 }: { values: number[]; height?: number }) {
  const w = 100
  const max = Math.max(1, ...values)
  const step = values.length > 1 ? w / (values.length - 1) : w
  const pts = values.map((v, i) => `${(i * step).toFixed(2)},${(height - 2 - (v / max) * (height - 4)).toFixed(2)}`)
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${height}`} preserveAspectRatio="none" aria-hidden="true">
      <polygon points={`0,${height} ${pts.join(' ')} ${w},${height}`} className="spark-fill" />
      <polyline points={pts.join(' ')} className="spark-line" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}

/* ── contribution heatmap ──────────────────────────────────────────────── */

export function Heatmap({ perDay, noun, onDay }: {
  perDay: Map<string, number>; noun: string; onDay?: (day: Date) => void
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const tip = useTip(ref)
  const today = startOfDay(new Date())
  // 53 weeks ending this week, Monday-first columns.
  const lastMonday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - ((today.getDay() + 6) % 7))
  const first = new Date(lastMonday.getFullYear(), lastMonday.getMonth(), lastMonday.getDate() - 52 * 7)
  const days = daysBetween(first, today)
  const values = days.map((d) => perDay.get(dayKey(d)) ?? 0)
  const max = Math.max(0, ...values)
  const level = (v: number) => (v <= 0 ? 0 : max <= 4 ? Math.min(4, v) : Math.min(4, Math.ceil((v / max) * 4)))

  const labelW = 28
  const cols = 53
  const gap = 3
  const cell = Math.max(6, Math.min(20, Math.floor((Math.max(width, 360) - labelW) / cols) - gap))
  const pitch = cell + gap
  const total = values.reduce((a, b) => a + b, 0)

  const months: { x: number; label: string }[] = []
  days.forEach((d, i) => {
    if (d.getDate() === 1 || i === 0) {
      const x = labelW + Math.floor(i / 7) * pitch
      if (!months.length || x - months[months.length - 1].x > 30) {
        months.push({ x, label: d.toLocaleDateString(undefined, { month: 'short' }) })
      }
    }
  })

  return (
    <div className="viz heatmap" ref={ref}>
      <svg width={labelW + cols * pitch} height={18 + 7 * pitch} role="img"
        aria-label={`${total} ${noun} in the last year`}>
        {months.map((m) => (
          <text key={m.x} x={m.x} y={11} className="viz-axis">{m.label}</text>
        ))}
        {['Mon', '', 'Wed', '', 'Fri', '', ''].map((l, i) => l && (
          <text key={l} x={0} y={18 + i * pitch + cell - 1} className="viz-axis">{l}</text>
        ))}
        {days.map((d, i) => {
          const v = values[i]
          return (
            <rect
              key={i}
              x={labelW + Math.floor(i / 7) * pitch}
              y={18 + (i % 7) * pitch}
              width={cell}
              height={cell}
              rx={2.5}
              className={`heat heat-${level(v)} ${onDay && v > 0 ? 'clickable' : ''}`}
              onClick={onDay && v > 0 ? () => onDay(d) : undefined}
              onMouseMove={(e) => tip.show(e, (
                <>
                  <strong>{v} {noun}</strong>
                  <span>{d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' })}</span>
                </>
              ))}
              onMouseLeave={tip.hide}
            />
          )
        })}
      </svg>
      <div className="heat-legend">
        <span>Less</span>
        {[0, 1, 2, 3, 4].map((l) => <span key={l} className={`heat-swatch heat-${l}`} />)}
        <span>More</span>
      </div>
      {tip.el}
    </div>
  )
}

/* ── stacked bars over time ────────────────────────────────────────────── */

export interface Series { key: string; label: string; color: string }

export function StackedBars({
  buckets, series, weekly, height = 200, unit,
}: {
  buckets: { key: string; values: Record<string, number> }[]
  series: Series[]
  weekly: boolean
  height?: number
  unit: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const tip = useTip(ref)
  const padL = 30
  const padB = 22
  const plotH = height - padB - 8
  const totals = buckets.map((b) => series.reduce((a, s) => a + (b.values[s.key] ?? 0), 0))
  const yMax = niceMax(Math.max(1, ...totals))
  const plotW = Math.max(0, width - padL)
  const slot = buckets.length ? plotW / buckets.length : plotW
  const barW = Math.max(2, Math.min(28, slot - 2))
  const y = (v: number) => 8 + plotH - (v / yMax) * plotH
  const ticks = [0, yMax / 2, yMax]
  const labelEvery = Math.max(1, Math.ceil(buckets.length / Math.max(2, Math.floor(plotW / 70))))

  return (
    <div className="viz" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`${unit} per ${weekly ? 'week' : 'day'}`}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={padL} x2={width} y1={y(t)} y2={y(t)} className="viz-grid" />
              <text x={padL - 6} y={y(t) + 3} textAnchor="end" className="viz-axis">{Math.round(t)}</text>
            </g>
          ))}
          {buckets.map((b, i) => {
            const x = padL + i * slot + (slot - barW) / 2
            let acc = 0
            const segs = series.filter((s) => (b.values[s.key] ?? 0) > 0)
            return (
              <g key={b.key}
                onMouseMove={(e) => tip.show(e, (
                  <>
                    <strong>{weekly ? `Week of ${fmtDay(b.key)}` : fmtDay(b.key, { weekday: 'short', month: 'short', day: 'numeric' })}</strong>
                    {series.map((s) => (b.values[s.key] ?? 0) > 0 && (
                      <span key={s.key} className="tip-row">
                        <span className="viz-swatch" style={{ background: s.color }} />{s.label}<b>{b.values[s.key]}</b>
                      </span>
                    ))}
                    <span className="tip-total">{totals[i]} {unit}</span>
                  </>
                ))}
                onMouseLeave={tip.hide}
              >
                <rect x={padL + i * slot} y={8} width={slot} height={plotH} className="viz-hit" />
                {segs.map((s, si) => {
                  const v = b.values[s.key] ?? 0
                  const top = y(acc + v)
                  const h = y(acc) - top
                  acc += v
                  const isTop = si === segs.length - 1
                  // 2px surface gap between stacked segments.
                  const gapH = isTop ? h : Math.max(0, h - 2)
                  return isTop
                    ? <path key={s.key} d={topRounded(x, top, barW, gapH, Math.min(4, barW / 2))} style={{ fill: s.color }} />
                    : <rect key={s.key} x={x} y={top + 2} width={barW} height={gapH} style={{ fill: s.color }} />
                })}
              </g>
            )
          })}
          {buckets.map((b, i) => i % labelEvery === 0 && (
            <text key={b.key} x={padL + i * slot + slot / 2} y={height - 6} textAnchor="middle" className="viz-axis">
              {fmtDay(b.key)}
            </text>
          ))}
        </svg>
      )}
      {tip.el}
    </div>
  )
}

/* ── single-series area line (cumulative) ──────────────────────────────── */

export function AreaLine({
  points, height = 200, unit,
}: {
  points: { key: string; value: number }[]
  height?: number
  unit: string
}) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const tip = useTip(ref)
  const [hover, setHover] = useState<number | null>(null)
  const padL = 36
  const padB = 22
  const plotH = height - padB - 8
  const plotW = Math.max(1, width - padL - 6)
  const yMax = niceMax(Math.max(1, ...points.map((p) => p.value)))
  const x = (i: number) => padL + (points.length > 1 ? (i / (points.length - 1)) * plotW : plotW / 2)
  const y = (v: number) => 8 + plotH - (v / yMax) * plotH
  const line = points.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join('')
  const area = points.length ? `${line}L${x(points.length - 1)},${y(0)}L${x(0)},${y(0)}Z` : ''
  const labelEvery = Math.max(1, Math.ceil(points.length / Math.max(2, Math.floor(plotW / 70))))

  const onMove = (e: React.MouseEvent<SVGRectElement>) => {
    const r = (e.currentTarget as SVGRectElement).getBoundingClientRect()
    const i = Math.round(((e.clientX - r.left) / r.width) * (points.length - 1))
    const p = points[Math.max(0, Math.min(points.length - 1, i))]
    if (!p) return
    setHover(points.indexOf(p))
    tip.show(e, <><strong>{p.value.toLocaleString()} {unit}</strong><span>by {fmtDay(p.key, { month: 'short', day: 'numeric', year: 'numeric' })}</span></>)
  }

  return (
    <div className="viz" ref={ref}>
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label={`Cumulative ${unit}`}>
          {[0, yMax / 2, yMax].map((t) => (
            <g key={t}>
              <line x1={padL} x2={width} y1={y(t)} y2={y(t)} className="viz-grid" />
              <text x={padL - 6} y={y(t) + 3} textAnchor="end" className="viz-axis">{Math.round(t).toLocaleString()}</text>
            </g>
          ))}
          <path d={area} className="viz-area" />
          <path d={line} className="viz-line" />
          {hover !== null && points[hover] && (
            <g>
              <line x1={x(hover)} x2={x(hover)} y1={8} y2={8 + plotH} className="viz-cross" />
              <circle cx={x(hover)} cy={y(points[hover].value)} r={4.5} className="viz-dot" />
            </g>
          )}
          {points.map((p, i) => i % labelEvery === 0 && (
            <text key={p.key} x={x(i)} y={height - 6} textAnchor="middle" className="viz-axis">{fmtDay(p.key)}</text>
          ))}
          <rect x={padL} y={8} width={plotW} height={plotH} className="viz-hit"
            onMouseMove={onMove} onMouseLeave={() => { setHover(null); tip.hide() }} />
        </svg>
      )}
      {tip.el}
    </div>
  )
}

/* ── horizontal bars (ranked categories) ───────────────────────────────── */

export function HBars({
  rows, unit, onPick,
}: {
  rows: { key: string; label: ReactNode; value: number; className?: string; hint?: string }[]
  unit: string
  /** Makes each non-empty row a button. */
  onPick?: (key: string) => void
}) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  const total = rows.reduce((a, r) => a + r.value, 0)
  if (!total) return <p className="viz-empty">Nothing in this period.</p>
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div key={r.key} className={`hbar-row ${onPick && r.value ? 'clickable' : ''}`}
          title={`${r.value} ${unit} · ${Math.round((r.value / total) * 100)}%${r.hint ? ` — ${r.hint}` : ''}${onPick && r.value ? ' — click to see them' : ''}`}
          role={onPick && r.value ? 'button' : undefined} tabIndex={onPick && r.value ? 0 : undefined}
          onClick={onPick && r.value ? () => onPick(r.key) : undefined}
          onKeyDown={onPick && r.value ? (e) => e.key === 'Enter' && onPick(r.key) : undefined}>
          <span className="hbar-label">{r.label}</span>
          <span className="hbar-track">
            <span className={`hbar-fill ${r.className ?? ''}`} style={{ width: `${(r.value / max) * 100}%` }} />
          </span>
          <span className="hbar-value">{r.value.toLocaleString()}</span>
          <span className="hbar-pct">{Math.round((r.value / total) * 100)}%</span>
        </div>
      ))}
    </div>
  )
}

/* ── weekday × hour punch card ─────────────────────────────────────────── */

export function PunchCard({ grid, noun }: { grid: number[][]; noun: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const tip = useTip(ref)
  const max = Math.max(0, ...grid.flat())
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  const level = (v: number) => (v <= 0 ? 0 : Math.min(4, Math.ceil((v / max) * 4)))
  const peak = useMemo(() => {
    let best = { d: 0, h: 0, v: -1 }
    grid.forEach((row, d) => row.forEach((v, h) => { if (v > best.v) best = { d, h, v } }))
    return best
  }, [grid])
  return (
    <div className="viz punch" ref={ref}>
      <div className="punch-grid">
        <span />
        {Array.from({ length: 24 }, (_, h) => (
          <span key={h} className="punch-hour">{h % 6 === 0 ? `${String(h).padStart(2, '0')}` : ''}</span>
        ))}
        {grid.map((row, d) => (
          <div key={d} style={{ display: 'contents' }}>
            <span className="punch-day">{days[d]}</span>
            {row.map((v, h) => (
              <span
                key={h}
                className={`punch-cell heat-bg-${level(v)}`}
                onMouseMove={(e) => tip.show(e, <><strong>{v} {noun}</strong><span>{days[d]} {String(h).padStart(2, '0')}:00–{String(h + 1).padStart(2, '0')}:00</span></>)}
                onMouseLeave={tip.hide}
              />
            ))}
          </div>
        ))}
      </div>
      {max > 0 && (
        <p className="viz-note">Busiest: <strong>{days[peak.d]} around {String(peak.h).padStart(2, '0')}:00</strong> ({peak.v} {noun})</p>
      )}
      {tip.el}
    </div>
  )
}
