import { useEffect, useState } from 'react'
import { api, ApiError } from '../lib/api'
import { MODE_ICON, MODE_LABEL, nsLabel, repoKey } from '../lib/labels'
import * as notify from '../lib/notify'
import type { EngineInfo, Mode, RepoRules, Review, SettingsSnapshot, SettingsValues, Status } from '../lib/types'
import { Icon, Spinner } from './Icon'

const MODEL_KEY: Record<string, keyof SettingsValues> = {
  claude: 'claude_model',
  codex: 'codex_model',
  cursor: 'cursor_model',
  anthropic: 'anthropic_model',
  openai: 'openai_model',
}

const SETUP_HINT: Record<string, string> = {
  claude: 'Install Claude Code and log in: `claude --version` should work.',
  codex: 'Install the Codex CLI and log in: `codex --version` should work.',
  cursor: 'Install the Cursor Agent CLI and log in: `cursor-agent --version` should work.',
  anthropic: 'Put ANTHROPIC_API_KEY in .env (or run `ant auth login`), then restart selfcheck.',
  openai: 'Pick an endpoint and a model below. A remote endpoint also needs SELFCHECK_OPENAI_API_KEY in .env.',
}

const ENDPOINTS: { label: string; url: string }[] = [
  { label: 'OpenAI', url: 'https://api.openai.com/v1' },
  { label: 'Ollama', url: 'http://localhost:11434/v1' },
  { label: 'LM Studio', url: 'http://localhost:1234/v1' },
  { label: 'OpenRouter', url: 'https://openrouter.ai/api/v1' },
]

/** Engine, model and run settings, applied the moment you change them. */
export function SettingsPage({
  reviews, status, onChanged, flash,
}: {
  reviews: Review[]
  status: Status | null
  onChanged: () => void
  flash: (text: string, err?: boolean) => void
}) {
  const [snap, setSnap] = useState<SettingsSnapshot | null>(null)
  const [saving, setSaving] = useState('')

  useEffect(() => {
    api.settings().then(setSnap).catch((e) => flash(`Could not load settings: ${e.message ?? e}`, true))
  }, [flash])

  const save = async (changes: Partial<Record<keyof SettingsValues, unknown>>, message: string) => {
    const key = Object.keys(changes)[0]
    setSaving(key)
    try {
      setSnap(await api.updateSettings(changes))
      onChanged()
      flash(message)
    } catch (e) {
      flash(e instanceof ApiError ? e.message : String(e), true)
    } finally {
      setSaving('')
    }
  }

  if (!snap) return <div className="page"><div className="blank"><Spinner /> Loading settings…</div></div>

  const v = snap.values
  const isOverridden = (k: keyof SettingsValues) => snap.overridden.includes(k)
  const reset = (k: keyof SettingsValues, what: string) => (
    isOverridden(k) && (
      <button className="btn ghost xs" onClick={() => save({ [k]: null }, `${what} reset to the .env default`)}
        title={`Back to the .env default: ${String(snap.defaults[k]) || '(empty)'}`}>
        Reset
      </button>
    )
  )

  return (
    <div className="page settings">
      <header className="page-head">
        <div>
          <h1><Icon name="settings" size={20} /> Settings</h1>
          <p className="muted">
            Changes apply immediately, to the next review that starts, and are kept across restarts.
            <code>.env</code> still holds the defaults and every secret; <em>Reset</em> goes back to it.
          </p>
        </div>
      </header>

      <section className="dcard">
        <header className="dcard-head">
          <div>
            <h2>Review engines</h2>
            <p>The default is what a review uses unless you pick another from the arrow on the Review button, or a PR or wakeup has its own.</p>
          </div>
          {reset('engine', 'Default engine')}
        </header>
        <div className="engine-cards">
          {snap.engines.map((e) => (
            <EngineCard
              key={e.id}
              engine={e}
              isDefault={v.engine === e.id}
              model={String(v[MODEL_KEY[e.id]] ?? '')}
              modelOverridden={isOverridden(MODEL_KEY[e.id])}
              saving={saving}
              secret={e.id === 'anthropic' ? snap.secrets.anthropic_api_key : e.id === 'openai' ? snap.secrets.openai_api_key : undefined}
              onDefault={() => save({ engine: e.id }, `${e.label} is now the default engine`)}
              onModel={(m) => save({ [MODEL_KEY[e.id]]: m }, m ? `${e.label} will use ${m}` : `${e.label} will use its default model`)}
              onResetModel={() => save({ [MODEL_KEY[e.id]]: null }, `${e.label} model reset to the .env default`)}
              baseUrl={e.id === 'openai' ? v.openai_base_url : undefined}
              onBaseUrl={(url) => save({ openai_base_url: url }, `OpenAI-compatible endpoint set to ${url}`)}
            />
          ))}
        </div>
      </section>

      <section className="dcard">
        <header className="dcard-head">
          <div>
            <h2>Defaults for every review</h2>
            <p>Per-PR and per-wakeup choices still win over these.</p>
          </div>
        </header>
        <div className="settings-rows">
          <div className="setting">
            <div className="setting-label">
              <strong>Depth</strong>
              <span className="muted">How deep a review goes when nothing else says.</span>
            </div>
            <div className="setting-control">
              <div className="seg">
                {(['light', 'normal', 'thorough'] as Mode[]).map((m) => (
                  <button key={m} className={v.default_mode === m ? 'on' : ''}
                    onClick={() => save({ default_mode: m }, `Default depth is now ${MODE_LABEL[m]}`)}>
                    <Icon name={MODE_ICON[m]} size={13} /> {MODE_LABEL[m]}
                  </button>
                ))}
              </div>
              {reset('default_mode', 'Default depth')}
            </div>
          </div>

          <NumberSetting
            label="Reviews at once"
            help="The rest queue. Keeps a wakeup that finds many PRs from spending on all of them at once."
            value={v.max_concurrent_runs} min={1} max={8}
            onSave={(n) => save({ max_concurrent_runs: n }, `Up to ${n} reviews at once`)}
            resetButton={reset('max_concurrent_runs', 'Concurrency')}
          />
          <NumberSetting
            label="Time limit (seconds)"
            help="For a normal review. Light gets half, thorough gets double."
            value={v.run_timeout_seconds} min={60} max={7200} step={60}
            onSave={(n) => save({ run_timeout_seconds: n }, `Reviews now stop after ${n}s`)}
            resetButton={reset('run_timeout_seconds', 'Time limit')}
          />
        </div>
      </section>

      <section className="dcard">
        <header className="dcard-head">
          <div>
            <h2>Spend</h2>
            <p>
              Caps stop <em>automatic</em> reviews — wakeups and watches — once reached. A review you start
              by hand still runs. 0 means no cap. Local CLI engines on a subscription may report $0.
            </p>
          </div>
        </header>
        {status?.budget && (
          <div className="budget-meters">
            <BudgetMeter label="Today" spent={status.budget.today_usd} cap={status.budget.daily_cap_usd} />
            <BudgetMeter label="This month" spent={status.budget.month_usd} cap={status.budget.monthly_cap_usd} />
          </div>
        )}
        {status?.budget.blocked && <div className="inline-err">Automatic reviews are paused: {status.budget.reason}.</div>}
        <div className="settings-rows">
          <NumberSetting
            label="Daily cap (USD)" help="Automatic reviews pause for the rest of the day."
            value={v.daily_budget_usd} min={0} max={100000} step={0.5} decimal
            onSave={(n) => save({ daily_budget_usd: n }, n ? `Daily cap set to $${n}` : 'No daily cap')}
            resetButton={reset('daily_budget_usd', 'Daily cap')}
          />
          <NumberSetting
            label="Monthly cap (USD)" help="Automatic reviews pause until the month turns over."
            value={v.monthly_budget_usd} min={0} max={100000} step={5} decimal
            onSave={(n) => save({ monthly_budget_usd: n }, n ? `Monthly cap set to $${n}` : 'No monthly cap')}
            resetButton={reset('monthly_budget_usd', 'Monthly cap')}
          />
        </div>
      </section>

      <section className="dcard">
        <header className="dcard-head">
          <div>
            <h2>Learning and rules</h2>
            <p>
              Findings you dismiss in a repository are fed back into its next reviews as “don't raise this
              again”; won't-fix ones as “known, out of scope”. Rules add your own instructions per repository,
              on top of any <code>.selfcheck.md</code> the repository has at its root.
            </p>
          </div>
        </header>
        <div className="settings-rows">
          <div className="setting">
            <div className="setting-label">
              <strong>Learn from dismissals</strong>
              <span className="muted">Everywhere. Each repository can also opt out below.</span>
            </div>
            <div className="setting-control">
              <Toggle on={v.learn_from_dismissals}
                onChange={(on) => save({ learn_from_dismissals: on }, on ? 'Reviews now learn from dismissals' : 'Learning from dismissals is off')} />
              {reset('learn_from_dismissals', 'Learning')}
            </div>
          </div>
        </div>
        <RepoRulesEditor reviews={reviews} flash={flash} />
      </section>

      <Notifications flash={flash} />
    </div>
  )
}

function Toggle({ on, onChange, label }: { on: boolean; onChange: (on: boolean) => void; label?: string }) {
  return (
    <button className={`toggle ${on ? 'on' : ''}`} role="switch" aria-checked={on} aria-label={label}
      onClick={() => onChange(!on)}>
      <span className="toggle-knob" />
    </button>
  )
}

function BudgetMeter({ label, spent, cap }: { label: string; spent: number; cap: number }) {
  const pct = cap ? Math.min(100, (spent / cap) * 100) : 0
  return (
    <div className="budget">
      <div className="budget-head">
        <span className="muted">{label}</span>
        <strong>${spent.toFixed(2)}</strong>
        <span className="faint">{cap ? `of $${cap.toFixed(2)}` : 'no cap'}</span>
      </div>
      {cap > 0 && (
        <span className={`budget-bar ${pct >= 100 ? 'over' : pct >= 80 ? 'near' : ''}`}>
          <span style={{ width: `${pct}%` }} />
        </span>
      )}
    </div>
  )
}

const RULES_EXAMPLE = [
  'For example:',
  '- Every migration needs a down step.',
  '- Logging goes through utils.log, never print().',
  '- Be strict about thread safety in src/runtime/.',
].join('\n')

function RepoRulesEditor({ reviews, flash }: { reviews: Review[]; flash: (t: string, e?: boolean) => void }) {
  const repos = [...new Map(reviews.map((r) => [repoKey(r), r])).values()]
    .sort((a, b) => `${a.namespace}/${a.project}`.localeCompare(`${b.namespace}/${b.project}`))
  const [repo, setRepo] = useState(repos[0] ? repoKey(repos[0]) : '')
  const [rules, setRules] = useState<RepoRules | null>(null)
  const [draft, setDraft] = useState('')
  const [withRules, setWithRules] = useState<Set<string>>(new Set())

  useEffect(() => {
    api.allRepoRules().then((all) => setWithRules(new Set(
      all.filter((r) => r.rules.trim() || !r.learn).map((r) => `${r.host}/${r.namespace}/${r.project}`),
    ))).catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!repo) return
    api.repoRules(repo).then((r) => { setRules(r); setDraft(r.rules) }).catch(() => undefined)
  }, [repo])

  if (!repos.length) return <p className="viz-empty">Rules can be set once a repository is tracked.</p>

  const save = async (change: { rules?: string; learn?: boolean }, message: string) => {
    try {
      const r = await api.saveRepoRules(repo, change)
      setRules(r)
      setDraft(r.rules)
      setWithRules((s) => {
        const next = new Set(s)
        if (r.rules.trim() || !r.learn) next.add(repo); else next.delete(repo)
        return next
      })
      flash(message)
    } catch (e) {
      flash(e instanceof Error ? e.message : String(e), true)
    }
  }

  return (
    <div className="rules-editor">
      <div className="field">
        <label htmlFor="rules-repo">Repository</label>
        <select id="rules-repo" className="input" value={repo} onChange={(e) => setRepo(e.target.value)}>
          {repos.map((r) => {
            const key = repoKey(r)
            return <option key={key} value={key}>{nsLabel(r)}/{r.project}{withRules.has(key) ? '  •  customised' : ''}</option>
          })}
        </select>
      </div>
      {rules && (
        <>
          <div className="field">
            <label htmlFor="rules-text">Review rules for this repository</label>
            <textarea id="rules-text" className="input mono" rows={7} value={draft}
              placeholder={RULES_EXAMPLE}
              onChange={(e) => setDraft(e.target.value)} />
            <span className="hint">Plain text or markdown, up to 8000 characters. Sent with every review of this repository.</span>
          </div>
          <div className="row" style={{ justifyContent: 'space-between', flexWrap: 'wrap' }}>
            <label className="check-label">
              <Toggle on={!!rules.learn} label="Learn from this repository's dismissals"
                onChange={(on) => void save({ learn: on }, on ? 'This repository learns from dismissals' : 'This repository no longer learns from dismissals')} />
              Learn from this repository's dismissals
            </label>
            <button className="btn sm primary" disabled={draft === rules.rules}
              onClick={() => void save({ rules: draft }, 'Rules saved — the next review will follow them')}>
              Save rules
            </button>
          </div>
        </>
      )}
    </div>
  )
}

function Notifications({ flash }: { flash: (t: string, e?: boolean) => void }) {
  const [level, setLevel] = useState<notify.NotifyLevel>(notify.loadLevel)
  const permission = notify.supported() ? Notification.permission : 'denied'
  const choose = async (next: notify.NotifyLevel) => {
    if (next !== 'off') {
      const p = await notify.requestPermission()
      if (p !== 'granted') {
        flash('The browser blocked notifications for this page — allow them in its site settings.', true)
        return
      }
    }
    notify.saveLevel(next)
    setLevel(next)
    if (next !== 'off') notify.testNotification()
  }
  return (
    <section className="dcard">
      <header className="dcard-head">
        <div>
          <h2>Desktop notifications</h2>
          <p>Raised by this browser while selfcheck is open in a tab. Nothing is sent anywhere. Saved per browser.</p>
        </div>
      </header>
      <div className="seg">
        {([['off', 'Off'], ['serious', 'Blockers, majors and failures'], ['all', 'Every finished review']] as const).map(([k, label]) => (
          <button key={k} className={level === k ? 'on' : ''} onClick={() => void choose(k)}>{label}</button>
        ))}
      </div>
      {!notify.supported() && <p className="hint">This browser does not support notifications.</p>}
      {notify.supported() && permission === 'denied' && <p className="hint sev-major">Notifications are blocked for this page in the browser's site settings.</p>}
    </section>
  )
}

function EngineCard({
  engine: e, isDefault, model, modelOverridden, saving, secret, onDefault, onModel, onResetModel,
  baseUrl, onBaseUrl,
}: {
  engine: EngineInfo
  isDefault: boolean
  model: string
  modelOverridden: boolean
  saving: string
  secret?: boolean
  onDefault: () => void
  onModel: (m: string) => void
  onResetModel: () => void
  baseUrl?: string
  onBaseUrl: (url: string) => void
}) {
  const [draft, setDraft] = useState(model)
  const [url, setUrl] = useState(baseUrl ?? '')
  const [models, setModels] = useState<string[] | null>(null)
  const [listing, setListing] = useState(false)
  const [listError, setListError] = useState('')
  useEffect(() => setDraft(model), [model])
  useEffect(() => setUrl(baseUrl ?? ''), [baseUrl])

  const canList = ['openai', 'anthropic', 'cursor'].includes(e.id)
  const listModels = async () => {
    setListing(true)
    setListError('')
    try {
      const r = await api.engineModels(e.id)
      setModels(r.models)
      if (r.error) setListError(r.error)
      else if (!r.models.length) setListError('The engine returned no models.')
    } finally {
      setListing(false)
    }
  }

  return (
    <article className={`engine-card ${isDefault ? 'default' : ''} ${e.available ? '' : 'unavailable'}`}>
      <div className="engine-card-head">
        <span className={`status-dot ${e.available ? 'ok' : 'bad'}`} />
        <strong>{e.label}</strong>
        <span className="engine-kind">{e.kind === 'cli' ? 'local CLI' : e.local ? 'local API' : 'API'}</span>
        <span className="spacer" />
        {isDefault ? (
          <span className="pill pill-active xs"><Icon name="check" size={10} /> default</span>
        ) : (
          <button className="btn xs" disabled={!e.available || !!saving} onClick={onDefault}
            title={e.available ? 'Use this engine by default' : 'Set it up first'}>
            Make default
          </button>
        )}
      </div>

      <p className="engine-status">
        {e.available
          ? <span className="muted">{e.version || 'ready'}</span>
          : <span className="sev-major">{e.error || 'not available'}</span>}
      </p>
      {!e.available && <p className="hint">{SETUP_HINT[e.id]}</p>}

      {baseUrl !== undefined && (
        <div className="field">
          <label htmlFor={`url-${e.id}`}>Endpoint</label>
          <div className="row">
            <input id={`url-${e.id}`} className="input sm mono" value={url} onChange={(ev) => setUrl(ev.target.value)}
              onKeyDown={(ev) => ev.key === 'Enter' && url !== baseUrl && onBaseUrl(url)} />
            <button className="btn sm" disabled={url === baseUrl || !!saving} onClick={() => onBaseUrl(url)}>Save</button>
          </div>
          <div className="presets">
            {ENDPOINTS.map((p) => (
              <button key={p.label} className={`chip-btn ${baseUrl === p.url ? 'on' : ''}`} onClick={() => onBaseUrl(p.url)}>
                {p.label}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="field">
        <label htmlFor={`model-${e.id}`}>Model</label>
        <div className="row">
          <input
            id={`model-${e.id}`}
            className="input sm mono"
            list={`models-${e.id}`}
            value={draft}
            placeholder={e.kind === 'cli' ? 'the CLI’s default' : 'model id'}
            onChange={(ev) => setDraft(ev.target.value)}
            onKeyDown={(ev) => ev.key === 'Enter' && draft !== model && onModel(draft.trim())}
          />
          <datalist id={`models-${e.id}`}>
            {(models ?? []).map((m) => <option key={m} value={m} />)}
          </datalist>
          <button className="btn sm" disabled={draft === model || !!saving} onClick={() => onModel(draft.trim())}>
            {saving === MODEL_KEY[e.id] ? <Spinner size={12} /> : 'Save'}
          </button>
          {canList && (
            <button className="icon-btn" onClick={listModels} disabled={listing} title="Ask the engine which models it offers (spends no tokens)" aria-label="List models">
              {listing ? <Spinner size={13} /> : <Icon name="search" size={14} />}
            </button>
          )}
          {modelOverridden && <button className="btn ghost xs" onClick={onResetModel}>Reset</button>}
        </div>
        {models && models.length > 0 && <span className="hint">{models.length} models available — start typing to pick one.</span>}
        {listError && <span className="hint sev-major">{listError}</span>}
      </div>

      {secret !== undefined && (
        <p className="hint">
          <Icon name={secret ? 'check' : 'x'} size={12} /> API key {secret ? 'set in .env' : 'not set in .env'}
        </p>
      )}
      <p className="engine-guard"><Icon name="shield" size={12} /> {e.read_only}</p>
    </article>
  )
}

function NumberSetting({
  label, help, value, min, max, step = 1, decimal = false, onSave, resetButton,
}: {
  label: string; help: string; value: number; min: number; max: number; step?: number
  decimal?: boolean; onSave: (n: number) => void; resetButton: React.ReactNode
}) {
  const [draft, setDraft] = useState(String(value))
  useEffect(() => setDraft(String(value)), [value])
  const n = Number(draft)
  const valid = Number.isFinite(n) && (decimal || Number.isInteger(n)) && n >= min && n <= max
  return (
    <div className="setting">
      <div className="setting-label">
        <strong>{label}</strong>
        <span className="muted">{help}</span>
      </div>
      <div className="setting-control">
        <input type="number" className="input sm num-wide" min={min} max={max} step={step} value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && valid && n !== value && onSave(n)} />
        <button className="btn sm" disabled={!valid || n === value} onClick={() => onSave(n)}>Save</button>
        {resetButton}
      </div>
    </div>
  )
}
