export type Severity = 'blocker' | 'major' | 'minor' | 'nit' | 'question' | 'praise'
export type Category =
  | 'correctness' | 'security' | 'performance' | 'tests' | 'style' | 'docs' | 'design' | 'api'
export type NoteStatus = 'open' | 'resolved' | 'dismissed' | 'wontfix'
export type Verdict = 'looks_good' | 'comments' | 'needs_work'

export interface Review {
  id: string
  provider: 'github' | 'gitlab'
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
  last_synced_at: string
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

export interface Status {
  read_only: boolean
  claude: { available: boolean; version?: string; path?: string; error?: string }
  model: string
  providers: { host: string; token_configured: boolean }[]
  clone_enabled: boolean
  cache: { path: string; used_bytes: number; cap_bytes: number }
  watch_interval_seconds: number
  data_dir: string
}
