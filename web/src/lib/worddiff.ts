/** Word-level diff between a removed line and its paired added line.
 *
 * GitHub shows this; GitLab mostly does not. It is the single biggest
 * readability win on lines that changed one identifier out of forty. */

export interface Segment { text: string; changed: boolean }

const TOKEN = /(\w+|\s+|[^\w\s])/g

function tokenize(s: string): string[] {
  return s.match(TOKEN) ?? []
}

/** Longest common subsequence over tokens, bounded so a pathological pair of
 *  very long lines cannot lock up the render. */
export function wordDiff(before: string, after: string): [Segment[], Segment[]] {
  const a = tokenize(before)
  const b = tokenize(after)
  if (a.length * b.length > 40000) {
    return [[{ text: before, changed: true }], [{ text: after, changed: true }]]
  }

  const dp: number[][] = Array.from({ length: a.length + 1 }, () => new Array(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }

  const left: Segment[] = []
  const right: Segment[] = []
  const push = (arr: Segment[], text: string, changed: boolean) => {
    const last = arr[arr.length - 1]
    if (last && last.changed === changed) last.text += text
    else arr.push({ text, changed })
  }

  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      push(left, a[i], false)
      push(right, b[j], false)
      i++; j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      push(left, a[i], true); i++
    } else {
      push(right, b[j], true); j++
    }
  }
  while (i < a.length) push(left, a[i++], true)
  while (j < b.length) push(right, b[j++], true)

  // If nearly everything changed, the highlight is noise rather than signal.
  const changedRatio = (segs: Segment[]) => {
    const total = segs.reduce((n, s) => n + s.text.length, 0) || 1
    return segs.filter((s) => s.changed).reduce((n, s) => n + s.text.length, 0) / total
  }
  if (changedRatio(left) > 0.75 && changedRatio(right) > 0.75) {
    return [[{ text: before, changed: false }], [{ text: after, changed: false }]]
  }
  return [left, right]
}

/** Pair up deletions with additions inside a hunk so word-diff has something
 *  to compare. Only balanced runs are paired; a 3-for-1 replacement is not. */
export function pairReplacements<T extends { kind: string }>(lines: T[]): Map<number, number> {
  const pairs = new Map<number, number>()
  let i = 0
  while (i < lines.length) {
    if (lines[i].kind !== 'del') { i++; continue }
    let d = i
    while (d < lines.length && lines[d].kind === 'del') d++
    let a = d
    while (a < lines.length && lines[a].kind === 'add') a++
    const dels = d - i
    const adds = a - d
    if (dels > 0 && dels === adds) {
      for (let k = 0; k < dels; k++) pairs.set(i + k, d + k)
    }
    i = a > i ? a : i + 1
  }
  return pairs
}
