import {
  Fragment, memo, useCallback, useEffect, useMemo, useRef, useState,
} from 'react'
import { api } from '../lib/api'
import { highlightFile, highlightLines, type Line } from '../lib/highlight'
import { pairReplacements, wordDiff, type Segment } from '../lib/worddiff'
import type { DiffFile, DiffLine, Hunk, Note } from '../lib/types'
import { NoteCard } from './NoteCard'
import { NoteComposer } from './NoteComposer'

export interface DiffViewOptions {
  split: boolean
  ignoreWhitespace: boolean
  wordDiff: boolean
  onlyWithNotes: boolean
}

interface Props {
  reviewId: string
  files: DiffFile[]
  notes: Note[]
  viewed: Record<string, boolean>
  options: DiffViewOptions
  theme: 'light' | 'dark'
  activeFile: string | null
  /** Path whose rows must be shown even if the file is marked viewed. Set when
   *  jumping to a finding, so the target is never hidden behind a collapsed
   *  header or filtered out of the list. */
  forceOpenFile?: string | null
  onToggleViewed: (path: string, viewed: boolean) => void
  onNotesChanged: () => void
}

const EXPAND_STEP = 20

/* ── helpers ───────────────────────────────────────────────────────────── */

function sameIgnoringWhitespace(a: string, b: string): boolean {
  return a.replace(/\s+/g, '') === b.replace(/\s+/g, '')
}

/** Build a per-character "this part changed" mask from word-diff segments. */
function maskFrom(segments: Segment[] | null, length: number): Uint8Array | null {
  if (!segments) return null
  const mask = new Uint8Array(length)
  let at = 0
  for (const seg of segments) {
    if (seg.changed) mask.fill(1, at, at + seg.text.length)
    at += seg.text.length
  }
  return mask
}

/** Render one code line: Shiki tokens, split further wherever the word-diff
 *  mask flips, so syntax colour and intra-line highlight compose instead of
 *  fighting each other. */
function renderCode(
  content: string,
  tokens: Line | null,
  mask: Uint8Array | null,
  kind: DiffLine['kind'],
): React.ReactNode {
  const wdClass = kind === 'add' ? 'wd-add' : 'wd-del'
  const pieces: React.ReactNode[] = []
  let key = 0

  const emit = (text: string, color: string | undefined, changed: boolean) => {
    if (!text) return
    pieces.push(
      <span
        key={key++}
        className={changed ? wdClass : undefined}
        style={color ? { color } : undefined}
      >
        {text}
      </span>,
    )
  }

  const walk = (text: string, color: string | undefined, offset: number) => {
    if (!mask) return emit(text, color, false)
    let start = 0
    let flag = mask[offset] === 1
    for (let i = 1; i <= text.length; i++) {
      const next = i < text.length ? mask[offset + i] === 1 : !flag
      if (next !== flag || i === text.length) {
        emit(text.slice(start, i), color, flag)
        start = i
        flag = next
      }
    }
  }

  if (tokens && tokens.length) {
    let offset = 0
    for (const t of tokens) {
      walk(t.content, t.color, offset)
      offset += t.content.length
    }
    if (offset < content.length) walk(content.slice(offset), undefined, offset)
  } else {
    walk(content, undefined, 0)
  }

  return pieces.length ? pieces : ' '
}

/* ── in-view gate ──────────────────────────────────────────────────────── */

/** Render a file's rows only once it is near the viewport, so a 200-file pull
 *  request does not build 200 tables up front.
 *
 *  This measures directly rather than using IntersectionObserver: an observer
 *  reports asynchronously, which leaves the first screen blank for a frame (and
 *  in some headless/embedded browsers never fires at all). A rect check on
 *  mount is synchronous and cannot miss files that are already on screen. Once
 *  a file has opened it stays open, so this runs at most once per file. */
function useInView<T extends HTMLElement>(margin = 800) {
  const ref = useRef<T | null>(null)
  const [seen, setSeen] = useState(false)

  useEffect(() => {
    if (seen) return
    let frame = 0

    const check = () => {
      frame = 0
      const el = ref.current
      if (!el) return
      const rect = el.getBoundingClientRect()
      if (rect.top < window.innerHeight + margin && rect.bottom > -margin) setSeen(true)
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(check)
    }

    check()
    // Capture phase, so scrolling inside the diff pane is caught too.
    window.addEventListener('scroll', schedule, true)
    window.addEventListener('resize', schedule)
    return () => {
      if (frame) cancelAnimationFrame(frame)
      window.removeEventListener('scroll', schedule, true)
      window.removeEventListener('resize', schedule)
    }
  }, [seen, margin])

  return [ref, seen] as const
}

/* ── blocks: hunks with the gaps between them ──────────────────────────── */

interface Gap {
  kind: 'gap'
  /** 1-indexed line numbers in the new file, inclusive. */
  newFrom: number
  newTo: number
  /** Matching first line number on the old side. */
  oldFrom: number
}

interface HunkBlock {
  kind: 'hunk'
  hunk: Hunk
}

type Block = Gap | HunkBlock

/** Work out the unchanged stretches between hunks so they can be revealed on
 *  demand. Inside a gap the two sides advance in lockstep, which is what makes
 *  reconstructing the old line numbers from the new ones safe. */
function buildBlocks(file: DiffFile, newLineCount: number | null): Block[] {
  const blocks: Block[] = []
  let prevNewEnd = 0
  let prevOldEnd = 0

  for (const hunk of file.hunks) {
    const gapLines = hunk.new_start - prevNewEnd - 1
    if (gapLines > 0) {
      blocks.push({
        kind: 'gap',
        newFrom: prevNewEnd + 1,
        newTo: hunk.new_start - 1,
        oldFrom: prevOldEnd + 1,
      })
    }
    blocks.push({ kind: 'hunk', hunk })
    prevNewEnd = hunk.new_start + hunk.new_count - 1
    prevOldEnd = hunk.old_start + hunk.old_count - 1
  }

  if (newLineCount != null && newLineCount > prevNewEnd) {
    blocks.push({
      kind: 'gap',
      newFrom: prevNewEnd + 1,
      newTo: newLineCount,
      oldFrom: prevOldEnd + 1,
    })
  }
  return blocks
}

/** How much of a gap is currently revealed, from each end. */
interface Reveal { top: number; bottom: number }

function gapSlices(gap: Gap, reveal: Reveal): { from: number; to: number }[] {
  const total = gap.newTo - gap.newFrom + 1
  const shown = Math.min(total, reveal.top + reveal.bottom)
  if (shown >= total) return [{ from: gap.newFrom, to: gap.newTo }]
  const slices: { from: number; to: number }[] = []
  if (reveal.top > 0) slices.push({ from: gap.newFrom, to: gap.newFrom + reveal.top - 1 })
  if (reveal.bottom > 0) slices.push({ from: gap.newTo - reveal.bottom + 1, to: gap.newTo })
  return slices
}

/* ── row models ────────────────────────────────────────────────────────── */

interface Row {
  left: DiffLine | null
  right: DiffLine | null
  leftIdx: number
  rightIdx: number
}

/** Pair deletions with additions for the split view. */
function buildRows(lines: DiffLine[]): Row[] {
  const rows: Row[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (line.kind === 'context') {
      rows.push({ left: line, right: line, leftIdx: i, rightIdx: i })
      i++
      continue
    }
    let d = i
    while (d < lines.length && lines[d].kind === 'del') d++
    let a = d
    while (a < lines.length && lines[a].kind === 'add') a++
    const dels = lines.slice(i, d)
    const adds = lines.slice(d, a)
    for (let k = 0; k < Math.max(dels.length, adds.length); k++) {
      rows.push({ left: dels[k] ?? null, right: adds[k] ?? null, leftIdx: i + k, rightIdx: d + k })
    }
    i = a > i ? a : i + 1
  }
  return rows
}

/* ── shared render context ─────────────────────────────────────────────── */

interface RenderCtx {
  options: DiffViewOptions
  tokensFor: (side: 'new' | 'old', line: number | null) => Line | null
  notesByAnchor: Map<string, Note[]>
  onNotesChanged: () => void
  setComposeAt: (v: { line: number; side: 'new' | 'old' } | null) => void
}

function noteRows(
  ctx: RenderCtx, side: 'new' | 'old', line: number | null, colSpan: number, keyPrefix: string,
): React.ReactNode {
  if (line == null) return null
  const list = ctx.notesByAnchor.get(`${side}:${line}`)
  if (!list?.length) return null
  return (
    <tr className="note-row" key={`${keyPrefix}-notes`}>
      <td colSpan={colSpan}>
        {list.map((n) => <NoteCard key={n.id} note={n} onChanged={ctx.onNotesChanged} />)}
      </td>
    </tr>
  )
}

function Gutter({ n, side, ctx }: { n: number | null; side: 'new' | 'old'; ctx: RenderCtx }) {
  return (
    <td
      className={n != null ? 'gut clickable' : 'gut empty-half'}
      onClick={n != null ? () => ctx.setComposeAt({ line: n, side }) : undefined}
      title={n != null ? 'Add a note on this line' : undefined}
    >
      {n ?? ''}
    </td>
  )
}

function renderUnified(lines: DiffLine[], ctx: RenderCtx, keyBase: string): React.ReactNode[] {
  const pairs = ctx.options.wordDiff ? pairReplacements(lines) : new Map<number, number>()
  const reverse = new Map<number, number>()
  for (const [d, a] of pairs) reverse.set(a, d)

  const masks = new Map<number, Uint8Array | null>()
  for (const [di, ai] of pairs) {
    const [l, r] = wordDiff(lines[di].content, lines[ai].content)
    masks.set(di, maskFrom(l, lines[di].content.length))
    masks.set(ai, maskFrom(r, lines[ai].content.length))
  }

  const out: React.ReactNode[] = []
  lines.forEach((line, idx) => {
    if (ctx.options.ignoreWhitespace && line.kind !== 'context') {
      const partner = pairs.get(idx) ?? reverse.get(idx)
      if (partner != null && sameIgnoringWhitespace(line.content, lines[partner].content)) return
    }
    const side = line.kind === 'del' ? 'old' : 'new'
    const lineNo = line.kind === 'del' ? line.old_line : line.new_line
    out.push(
      <tr key={`${keyBase}-${idx}`} className={line.kind}>
        <Gutter n={line.old_line} side="old" ctx={ctx} />
        <Gutter n={line.new_line} side="new" ctx={ctx} />
        <td className="mark">{line.kind === 'add' ? '+' : line.kind === 'del' ? '−' : ' '}</td>
        <td className="code">
          {renderCode(line.content, ctx.tokensFor(side, lineNo), masks.get(idx) ?? null, line.kind)}
        </td>
      </tr>,
    )
    const notes = noteRows(ctx, side, lineNo, 4, `${keyBase}-${idx}`)
    if (notes) out.push(notes)
  })
  return out
}

function renderSplit(lines: DiffLine[], ctx: RenderCtx, keyBase: string): React.ReactNode[] {
  const rows = buildRows(lines)
  const masks = new Map<number, Uint8Array | null>()
  if (ctx.options.wordDiff) {
    for (const row of rows) {
      if (row.left?.kind === 'del' && row.right?.kind === 'add') {
        const [l, r] = wordDiff(row.left.content, row.right.content)
        masks.set(row.leftIdx, maskFrom(l, row.left.content.length))
        masks.set(row.rightIdx, maskFrom(r, row.right.content.length))
      }
    }
  }

  const out: React.ReactNode[] = []
  rows.forEach((row, idx) => {
    if (
      ctx.options.ignoreWhitespace &&
      row.left?.kind === 'del' && row.right?.kind === 'add' &&
      sameIgnoringWhitespace(row.left.content, row.right.content)
    ) return

    out.push(
      <tr key={`${keyBase}-${idx}`}>
        <Gutter n={row.left?.old_line ?? null} side="old" ctx={ctx} />
        <td className={`mark ${row.left?.kind ?? 'empty-half'}`}>
          {row.left?.kind === 'del' ? '−' : ' '}
        </td>
        <td className={`code ${row.left ? row.left.kind : 'empty-half'}`}>
          {row.left
            ? renderCode(
                row.left.content,
                ctx.tokensFor(
                  row.left.kind === 'del' ? 'old' : 'new',
                  row.left.kind === 'del' ? row.left.old_line : row.left.new_line,
                ),
                masks.get(row.leftIdx) ?? null,
                row.left.kind,
              )
            : ''}
        </td>
        <Gutter n={row.right?.new_line ?? null} side="new" ctx={ctx} />
        <td className={`mark ${row.right?.kind ?? 'empty-half'}`}>
          {row.right?.kind === 'add' ? '+' : ' '}
        </td>
        <td className={`code ${row.right ? row.right.kind : 'empty-half'}`}>
          {row.right
            ? renderCode(
                row.right.content,
                ctx.tokensFor('new', row.right.new_line),
                masks.get(row.rightIdx) ?? null,
                row.right.kind,
              )
            : ''}
        </td>
      </tr>,
    )

    if (row.left?.kind === 'del') {
      const n = noteRows(ctx, 'old', row.left.old_line, 6, `${keyBase}-l${idx}`)
      if (n) out.push(n)
    }
    const rn = noteRows(ctx, 'new', row.right?.new_line ?? row.left?.new_line ?? null, 6, `${keyBase}-r${idx}`)
    if (rn) out.push(rn)
  })
  return out
}

/* ── file ──────────────────────────────────────────────────────────────── */

interface FileProps {
  reviewId: string
  file: DiffFile
  notes: Note[]
  viewed: boolean
  options: DiffViewOptions
  theme: 'light' | 'dark'
  forceOpen: boolean
  onToggleViewed: (path: string, viewed: boolean) => void
  onNotesChanged: () => void
}

const DiffFileView = memo(function DiffFileView({
  reviewId, file, notes, viewed, options, theme, forceOpen, onToggleViewed, onNotesChanged,
}: FileProps) {
  const [wrapRef, inView] = useInView<HTMLDivElement>()
  const [collapsed, setCollapsed] = useState(viewed)
  const [newTokens, setNewTokens] = useState<Line[] | null>(null)
  const [oldTokens, setOldTokens] = useState<Line[] | null>(null)
  const [newLines, setNewLines] = useState<string[] | null>(null)
  const [reveals, setReveals] = useState<Record<number, Reveal>>({})
  const [composeAt, setComposeAt] = useState<{ line: number; side: 'new' | 'old' } | null>(null)

  useEffect(() => { setCollapsed(viewed) }, [viewed])
  useEffect(() => { if (forceOpen) setCollapsed(false) }, [forceOpen])

  const open = inView && !collapsed && !file.is_binary
  const colSpan = options.split ? 6 : 4

  // Highlight against the whole file, so multi-line strings and block comments
  // stay correct — and keep the text around, which makes expanding context a
  // local slice instead of another round trip.
  useEffect(() => {
    if (!open) return
    let cancelled = false

    const load = async (side: 'new' | 'old', set: (v: Line[] | null) => void) => {
      const path = side === 'new' ? file.new_path : file.old_path
      if (!path || path === '/dev/null') return
      try {
        const text = await api.blob(reviewId, path, side)
        if (side === 'new' && !cancelled) setNewLines(text.split('\n'))
        const tokens = await highlightFile(text, path, theme)
        if (!cancelled) set(tokens)
      } catch {
        // No checkout for this review: fall back to tokenizing hunk lines
        // alone, and leave context expansion unavailable.
        const relevant = file.hunks.flatMap((h) =>
          h.lines.filter((l) => (side === 'new' ? l.new_line : l.old_line) !== null),
        )
        if (!relevant.length) return
        const maxLine = Math.max(
          ...relevant.map((l) => (side === 'new' ? l.new_line! : l.old_line!)),
        )
        const buf = new Array<string>(maxLine).fill('')
        for (const l of relevant) buf[(side === 'new' ? l.new_line! : l.old_line!) - 1] = l.content
        const tokens = await highlightLines(buf, path, theme)
        if (!cancelled) set(tokens)
      }
    }

    void load('new', setNewTokens)
    if (file.status !== 'added') void load('old', setOldTokens)
    return () => { cancelled = true }
  }, [open, reviewId, file, theme])

  const notesByAnchor = useMemo(() => {
    const map = new Map<string, Note[]>()
    for (const n of notes) {
      const line = n.line_end ?? n.line_start
      if (line == null) continue
      const key = `${n.side}:${line}`
      const list = map.get(key)
      if (list) list.push(n)
      else map.set(key, [n])
    }
    return map
  }, [notes])

  const tokensFor = useCallback(
    (side: 'new' | 'old', lineNo: number | null): Line | null => {
      if (lineNo == null) return null
      return (side === 'new' ? newTokens : oldTokens)?.[lineNo - 1] ?? null
    },
    [newTokens, oldTokens],
  )

  const ctx: RenderCtx = {
    options, tokensFor, notesByAnchor, onNotesChanged, setComposeAt,
  }

  const blocks = useMemo(
    () => buildBlocks(file, newLines ? newLines.length : null),
    [file, newLines],
  )

  const expand = (gapIdx: number, where: 'top' | 'bottom' | 'all', total: number) => {
    setReveals((prev) => {
      const cur = prev[gapIdx] ?? { top: 0, bottom: 0 }
      if (where === 'all') return { ...prev, [gapIdx]: { top: total, bottom: 0 } }
      return {
        ...prev,
        [gapIdx]: where === 'top'
          ? { ...cur, top: Math.min(total - cur.bottom, cur.top + EXPAND_STEP) }
          : { ...cur, bottom: Math.min(total - cur.top, cur.bottom + EXPAND_STEP) },
      }
    })
  }

  const renderGap = (gap: Gap, gapIdx: number, isLast: boolean): React.ReactNode[] => {
    const total = gap.newTo - gap.newFrom + 1
    const reveal = reveals[gapIdx] ?? { top: 0, bottom: 0 }
    const rows: React.ReactNode[] = []
    const canExpand = !!newLines
    const remaining = total - Math.min(total, reveal.top + reveal.bottom)

    const contextRows = (from: number, to: number) => {
      const lines: DiffLine[] = []
      for (let n = from; n <= to; n++) {
        lines.push({
          kind: 'context',
          content: newLines?.[n - 1] ?? '',
          new_line: n,
          old_line: gap.oldFrom + (n - gap.newFrom),
          no_newline: false,
        })
      }
      return options.split
        ? renderSplit(lines, ctx, `g${gapIdx}-${from}`)
        : renderUnified(lines, ctx, `g${gapIdx}-${from}`)
    }

    const slices = gapSlices(gap, reveal)
    const bar = (key: string, label: string, actions: React.ReactNode) => (
      <tr className="hunk-sep" key={key}>
        <td colSpan={colSpan}>
          {actions}
          <span className="faint">{label}</span>
        </td>
      </tr>
    )

    if (remaining === 0) {
      for (const s of slices) rows.push(...contextRows(s.from, s.to))
      return rows
    }

    if (reveal.top > 0) rows.push(...contextRows(gap.newFrom, gap.newFrom + reveal.top - 1))

    rows.push(
      bar(
        `gap-${gapIdx}`,
        `${remaining} unchanged line${remaining === 1 ? '' : 's'}`,
        canExpand ? (
          <>
            <button className="expand" title="Show 20 more below" onClick={() => expand(gapIdx, 'top', total)}>
              ↓ 20
            </button>
            {!isLast && (
              <button className="expand" title="Show 20 more above" onClick={() => expand(gapIdx, 'bottom', total)}>
                ↑ 20
              </button>
            )}
            {remaining <= 200 && (
              <button className="expand" onClick={() => expand(gapIdx, 'all', total)}>
                show all
              </button>
            )}
          </>
        ) : null,
      ),
    )

    if (reveal.bottom > 0) rows.push(...contextRows(gap.newTo - reveal.bottom + 1, gap.newTo))
    return rows
  }

  const openCount = notes.filter((n) => n.status === 'open').length
  const worst = notes.find((n) => n.status === 'open')?.severity

  let gapCounter = 0

  return (
    <div className="diff-file" ref={wrapRef} id={`file-${encodeURIComponent(file.path)}`}>
      <div className="dhead">
        <button
          className="btn ghost sm"
          onClick={() => setCollapsed((c) => !c)}
          title={collapsed ? 'Expand' : 'Collapse'}
        >
          {collapsed ? '▸' : '▾'}
        </button>
        <span className="path" title={file.path}>
          {file.status === 'renamed' ? `${file.old_path} → ${file.new_path}` : file.path}
        </span>
        {file.status !== 'modified' && <span className="badge">{file.status}</span>}
        {openCount > 0 && (
          <span className={`chip sev-${worst}`} title={`${openCount} open note(s)`}>
            <span className="dot" />
            {openCount}
          </span>
        )}
        <span className="spacer" />
        <span className="fstat">
          <span className="a">+{file.additions}</span> <span className="d">−{file.deletions}</span>
        </span>
        <label className="row faint" style={{ fontSize: 11, cursor: 'pointer', gap: 4 }}>
          <input
            type="checkbox"
            checked={viewed}
            onChange={(e) => onToggleViewed(file.path, e.target.checked)}
          />
          viewed
        </label>
      </div>

      {file.is_binary && <div className="binary">Binary file — no textual diff.</div>}

      {!file.is_binary && collapsed && (
        <div className="binary">
          Collapsed.{' '}
          <button className="btn ghost sm" onClick={() => setCollapsed(false)}>Show diff</button>
        </div>
      )}

      {open && (
        <table className="dtable">
          <tbody>
            {blocks.map((block, bi) => {
              if (block.kind === 'gap') {
                const idx = gapCounter++
                return (
                  <Fragment key={`b${bi}`}>
                    {renderGap(block, idx, bi === blocks.length - 1)}
                  </Fragment>
                )
              }
              const { hunk } = block
              return (
                <Fragment key={`b${bi}`}>
                  <tr className="hunk-sep">
                    <td colSpan={colSpan}>
                      @@ −{hunk.old_start},{hunk.old_count} +{hunk.new_start},{hunk.new_count} @@
                      {hunk.section ? `  ${hunk.section}` : ''}
                    </td>
                  </tr>
                  {options.split
                    ? renderSplit(hunk.lines, ctx, `h${bi}`)
                    : renderUnified(hunk.lines, ctx, `h${bi}`)}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      )}

      {file.truncated && (
        <div className="truncated">This file's diff was truncated — it is very large.</div>
      )}

      {composeAt && (
        <NoteComposer
          reviewId={reviewId}
          file={file.path}
          line={composeAt.line}
          side={composeAt.side}
          onClose={() => setComposeAt(null)}
          onSaved={() => { setComposeAt(null); onNotesChanged() }}
        />
      )}
    </div>
  )
})

/* ── top level ─────────────────────────────────────────────────────────── */

export function DiffView({
  reviewId, files, notes, viewed, options, theme, activeFile, forceOpenFile,
  onToggleViewed, onNotesChanged,
}: Props) {
  const byFile = useMemo(() => {
    const map = new Map<string, Note[]>()
    for (const n of notes) {
      if (!n.file_path) continue
      const list = map.get(n.file_path)
      if (list) list.push(n)
      else map.set(n.file_path, [n])
    }
    return map
  }, [notes])

  const shown = useMemo(
    () => (options.onlyWithNotes
      ? files.filter((f) =>
          f.path === forceOpenFile ||
          (byFile.get(f.path) ?? []).some((n) => n.status === 'open'))
      : files),
    [files, options.onlyWithNotes, byFile, forceOpenFile],
  )

  useEffect(() => {
    if (!activeFile) return
    document
      .getElementById(`file-${encodeURIComponent(activeFile)}`)
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [activeFile])

  if (!shown.length) {
    return (
      <div className="blank">
        <h2>{options.onlyWithNotes ? 'No files have open notes' : 'No changes'}</h2>
        {options.onlyWithNotes && (
          <p className="muted">Turn off “only flagged” to see the whole diff.</p>
        )}
      </div>
    )
  }

  return (
    <div>
      {shown.map((f) => (
        <DiffFileView
          key={f.path}
          reviewId={reviewId}
          file={f}
          notes={byFile.get(f.path) ?? []}
          viewed={!!viewed[f.path]}
          options={options}
          theme={theme}
          forceOpen={forceOpenFile === f.path}
          onToggleViewed={onToggleViewed}
          onNotesChanged={onNotesChanged}
        />
      ))}
    </div>
  )
}
