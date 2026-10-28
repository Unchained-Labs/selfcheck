export type Severity = 'blocker' | 'major' | 'minor' | 'nit' | 'question' | 'praise'
export type Category =
  | 'correctness' | 'security' | 'performance' | 'tests' | 'style' | 'docs' | 'design' | 'api'
export type NoteStatus = 'open' | 'resolved' | 'dismissed' | 'wontfix'
export type Verdict = 'looks_good' | 'comments' | 'needs_work'
export type Mode = 'light' | 'normal' | 'thorough'
export type EngineId = 'claude' | 'codex' | 'cursor' | 'anthropic' | 'openai'

export interface Review {
  id: string
  provider: 'github' | 'gitlab' | 'local'
  host: string
  namespace: string
  project: string
  number: number
  url: string
  title: string
  description: string
  author: string
  state: string
  draft: number
  base_ref: string
  head_ref: string
  base_sha: string
  head_sha: string
  changed_files: number
  additions: number
  deletions: number
  watch: number
  archived: number
  pinned: number
  /** Default depth / engine for this PR's runs; '' = the global default. */
  mode: Mode | ''
  engine: EngineId | ''
  repo_watch_id: string
  last_synced_at: string
  created_at: string
  updated_at: string
  counts?: NoteCounts
  latest_run?: Run | null
}

export interface NoteCounts extends Record<string, number> {
  blocker: number; major: number; minor: number; nit: number
  question: number; praise: number
  open: number; resolved: number; dismissed: number; wontfix: number; total: number
}

export interface Note {
  id: string
  review_id: string
  run_id: string
  file_path: string
  line_start: number | null
  line_end: number | null
  side: 'new' | 'old'
  severity: Severity
  category: Category
  title: string
  body: string
  suggestion: string
  confidence: string
  status: NoteStatus
  origin: 'claude' | 'human'
  anchor_sha: string
  stale: number
  created_at: string
  updated_at: string
}

export interface ChecklistItem { item: string; state: string; note?: string }

export interface Run {
  id: string
  review_id: string
  status: 'queued' | 'preparing' | 'analyzing' | 'done' | 'failed' | 'cancelled'
  trigger: string
  phase: string
  progress: string
  base_sha: string
  head_sha: string
  summary: string
  verdict: Verdict | ''
  confidence: string
  risk_areas: string[]
  checklist: ChecklistItem[]
  test_gaps: string[]
  questions: string[]
  error: string
  model: string
  cost_usd: number
  duration_ms: number
  num_turns: number
  used_worktree: number
  mode: Mode
  /** 'agent' when an outside agent (the skill) wrote the review through the API. */
  engine: EngineId | 'agent'
  kind: 'review' | 'second_opinion'
  findings: Finding[]
  context: { repo_rules?: boolean; repo_file?: boolean; dismissed?: number; wontfix?: number }
  created_at: string
  finished_at: string
}

export type LineKind = 'context' | 'add' | 'del' | 'meta'

export interface DiffLine {
  kind: LineKind
  content: string
  old_line: number | null
  new_line: number | null
  no_newline: boolean
}

export interface Hunk {
  header: string
  section: string
  old_start: number
  old_count: number
  new_start: number
  new_count: number
  lines: DiffLine[]
}

export interface DiffFile {
  old_path: string
  new_path: string
  path: string
  status: 'added' | 'deleted' | 'renamed' | 'modified' | 'binary'
  is_binary: boolean
  additions: number
  deletions: number
  hunks: Hunk[]
  truncated: boolean
}

export interface DiffPayload {
  files: DiffFile[]
  stats: { files: number; additions: number; deletions: number }
  base_sha: string
  head_sha: string
}

export interface FileState { file_path: string; viewed: number; viewed_sha: string }

export interface ReviewDetail {
  review: Review
  counts: NoteCounts
  notes: Note[]
  file_states: Record<string, FileState>
  latest_run: Run | null
  runs: Run[]
}

export interface RunEvent {
  kind: 'start' | 'phase' | 'tool' | 'log' | 'warn' | 'result' | 'done' | 'failed' | 'cancelled'
  run_id: string
  review_id: string
  ts: string
  phase?: string
  message?: string
  tool?: string
  detail?: string
  error?: string
  model?: string
  notes?: number
  verdict?: string
}

export interface EngineInfo {
  id: EngineId
  label: string
  kind: 'cli' | 'api'
  model: string
  read_only: string
  available: boolean
  version?: string
  error?: string
  local?: boolean
}

export interface ModeInfo { id: Mode; label: string; description: string }

export interface Status {
  read_only: boolean
  claude: { available: boolean; version?: string; path?: string; error?: string }
  model: string
  engines: EngineInfo[]
  default_engine: EngineId
  default_mode: Mode
  modes: ModeInfo[]
  max_concurrent_runs: number
  budget: Budget
  learn_from_dismissals: boolean
  providers: { host: string; token_configured: boolean }[]
  clone_enabled: boolean
  cache: { path: string; used_bytes: number; cap_bytes: number }
  watch_interval_seconds: number
  data_dir: string
}

export interface Wakeup {
  id: string
  provider: 'github' | 'gitlab'
  host: string
  namespace: string
  project: string
  url: string
  enabled: number
  interval_minutes: number
  /** HH:MM, server time; only meaningful on a daily cadence. */
  daily_at: string
  mode: Mode | ''
  engine: EngineId | ''
  include_drafts: number
  rereview_on_push: number
  target_branch: string
  authors: string
  max_per_check: number
  baseline_at: string
  last_checked_at: string
  next_check_at: string
  last_result: string
  last_error: string
  created_at: string
  tracked: number
  auto_tracked: number
  checking: boolean
}

export interface WakeupSettings {
  enabled?: boolean
  interval_minutes?: number
  daily_at?: string
  mode?: Mode | ''
  engine?: EngineId | ''
  include_drafts?: boolean
  rereview_on_push?: boolean
  target_branch?: string
  authors?: string
  max_per_check?: number
}

export interface OpenPull {
  number: number
  title: string
  author: string
  draft: boolean
  base_ref: string
  created_at: string
  web_url: string
  review_id: string | null
  /** Why the wakeup would leave it alone; '' means it would review it. */
  skip: string
}

export interface CheckResult {
  watch: Wakeup
  open: number
  started: { review_id: string; run_id: string; number: number; title: string; rereview: boolean }[]
  deferred: number
  errors: string[]
}

export interface SettingsValues {
  engine: EngineId
  default_mode: Mode
  max_concurrent_runs: number
  run_timeout_seconds: number
  claude_model: string
  codex_model: string
  cursor_model: string
  anthropic_model: string
  openai_model: string
  openai_base_url: string
  learn_from_dismissals: boolean
  daily_budget_usd: number
  monthly_budget_usd: number
}

export interface SettingsSnapshot {
  values: SettingsValues
  defaults: SettingsValues
  overridden: (keyof SettingsValues)[]
  secrets: { anthropic_api_key: boolean; openai_api_key: boolean }
  engines: EngineInfo[]
}

export interface Budget {
  today_usd: number
  month_usd: number
  daily_cap_usd: number
  monthly_cap_usd: number
  blocked: boolean
  reason: string
}

/** A finding as a second opinion raised it (not stored as a note). */
export interface Finding {
  file_path: string
  line_start: number | null
  line_end: number | null
  side: 'new' | 'old'
  severity: Severity
  category: Category
  title: string
  body: string
  suggestion: string
  confidence: string
}

export interface Comparison {
  run: Run | null
  primary_run?: Run | null
  agreed?: { ours: Note; theirs: Finding; score: number }[]
  only_ours?: Note[]
  only_theirs?: Finding[]
  agreement?: number
}

export interface NoteMessage {
  id: string
  note_id: string
  role: 'user' | 'assistant'
  body: string
  status: 'pending' | 'done' | 'failed'
  engine: string
  model: string
  cost_usd: number
  created_at: string
}

export interface RepoRules {
  host: string
  namespace: string
  project: string
  rules: string
  learn: number
  updated_at: string
}
