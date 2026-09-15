/** Short relative timestamps. Reviews are a "how fresh is this?" tool, and
 *  "4m ago" answers that faster than an ISO string. */
export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return ''
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return ''
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 0) return 'just now'
  if (seconds < 45) return 'just now'
  const units: [number, string][] = [
    [60, 's'],
    [3600, 'm'],
    [86400, 'h'],
    [604800, 'd'],
  ]
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`
  if (seconds < 604800) return `${Math.round(seconds / 86400)}d ago`
  void units
  return new Date(then).toLocaleDateString()
}

export function duration(ms: number): string {
  if (!ms) return ''
  if (ms < 1000) return `${ms}ms`
  const s = ms / 1000
  if (s < 90) return `${s.toFixed(0)}s`
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`
}
