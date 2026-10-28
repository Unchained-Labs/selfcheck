import type { EngineId, EngineInfo, Mode, Review, Status, Wakeup } from './types'

export const MODE_LABEL: Record<Mode, string> = {
  light: 'Light',
  normal: 'Normal',
  thorough: 'Thorough',
}

export const MODE_ICON: Record<Mode, string> = {
  light: 'bolt',
  normal: 'gauge',
  thorough: 'search',
}

export const ENGINE_SHORT: Record<string, string> = {
  claude: 'Claude Code',
  codex: 'Codex',
  cursor: 'Cursor',
  anthropic: 'Anthropic API',
  openai: 'OpenAI-compatible',
  agent: 'agent',
}

export function engineLabel(id: string, status?: Status | null): string {
  return status?.engines.find((e) => e.id === id)?.label ?? ENGINE_SHORT[id] ?? id
}

export function findEngine(status: Status | null, id: string): EngineInfo | undefined {
  return status?.engines.find((e) => e.id === id)
}

/** The mode and engine the next run of this PR would use. */
export function effectiveChoice(review: Review | null, status: Status | null): {
  mode: Mode
  engine: EngineId
} {
  return {
    mode: (review?.mode || status?.default_mode || 'normal') as Mode,
    engine: (review?.engine || status?.default_engine || 'claude') as EngineId,
  }
}

export function repoKey(r: { host: string; namespace: string; project: string }): string {
  return `${r.host}/${r.namespace}/${r.project}`
}

export function forgeName(provider: string): string {
  return provider === 'github' ? 'GitHub' : provider === 'local' ? 'Local' : 'GitLab'
}

export function prWord(provider: string): string {
  return provider === 'github' ? 'PR' : 'MR'
}

/** "Daily at 09:00", "Every 6 hours", … */
export function scheduleLabel(w: Pick<Wakeup, 'interval_minutes' | 'daily_at'>): string {
  const m = w.interval_minutes
  if (m % 1440 === 0) {
    const days = m / 1440
    const every = days === 1 ? 'Daily' : days === 7 ? 'Weekly' : `Every ${days} days`
    return w.daily_at ? `${every} at ${w.daily_at}` : every
  }
  if (m % 60 === 0) return m === 60 ? 'Hourly' : `Every ${m / 60} hours`
  return `Every ${m} min`
}

export function timeUntil(iso: string): string {
  if (!iso) return ''
  const s = Math.round((new Date(iso).getTime() - Date.now()) / 1000)
  if (Number.isNaN(s)) return ''
  if (s <= 60) return 'any moment'
  if (s < 3600) return `in ${Math.round(s / 60)} min`
  if (s < 86400) return `in ${Math.round(s / 3600)} h`
  return `in ${Math.round(s / 86400)} d`
}

export function isRunning(status?: string): boolean {
  return !!status && ['queued', 'preparing', 'analyzing'].includes(status)
}
