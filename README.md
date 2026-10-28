# selfcheck

A local, self-hosted review workbench for GitHub pull requests and GitLab merge
requests. Paste a link — or let a wakeup pick new ones up from a repository —
and a coding agent you already have (Claude Code, Codex, Cursor Agent) or a
model behind an API reads the change against a read-only checkout and writes
structured review notes next to the diff.

Built for reviewing your own work before you ask for eyes on it, and for getting
oriented in someone else's PR faster.

**selfcheck never writes to a forge.** No comments, no approvals, no merges, no
labels. Notes live in a local SQLite file, and the only way one leaves is you
copying markdown out of it.

![The review summary](docs/screenshot-review.png)

▶ **[Watch the 95-second demo](docs/demo.mp4)** — adding a PR, the review, the
diff UI, adding your own notes, a live re-review, and the light theme.

---

## What it does

- **Track PRs and MRs** by URL — github.com, gitlab.com, GitHub Enterprise, and
  self-managed GitLab.
- **Review with the engine you have** — Claude Code, Codex or Cursor Agent on
  this machine, or the Anthropic API or any OpenAI-compatible endpoint
  (including Ollama and LM Studio, so the code never has to leave the box).
  Whichever it is gets the diff *and* a read-only checkout of the head commit,
  so it can read whole functions, find every caller of a changed signature,
  and check whether a test already covers the new path.
- **Three depths** — *light* (blockers and majors only, mostly from the diff),
  *normal*, and *thorough* (traces callers, tests and failure paths). Pick per
  run from the arrow on the Review button, or save a default per PR.
- **Wakeups** — point selfcheck at a repository and a time ("daily at 09:00")
  and every new PR is reviewed before you get to it. Filters for target
  branch, authors and drafts; optional re-review when new commits land; a cap
  on reviews per check so a busy morning does not become a big bill.
- **Organised by repository** — the sidebar groups reviews by repo; the Home
  dashboard shows activity, findings, engine performance and the developers
  you review, and every number on it opens the matching reviews.
- **Review a branch before you push** — paste a local repository path
  (`~/src/app`, `~/src/app@feature..main`) and the committed work on that
  branch is reviewed like a PR, without anything being written to your repo.
- **Ask about a finding** — "does this really hold?" gets checked against the
  code by the same engine, in a thread under the note.
- **Second opinion** — have another engine review the same change; see what
  both found, what only one did, and adopt any finding with one click.
- **It learns** — findings you dismiss in a repository are fed back into its
  next reviews, alongside your own per-repository rules and any
  `.selfcheck.md` the repository carries.
- **Spend caps and notifications** — daily/monthly caps pause automatic
  reviews; optional desktop notifications for blockers and failures.
- **A diff UI that earns its keep** — split or unified, real syntax highlighting
  (whole-file, so multi-line strings are not mis-coloured), word-level
  intra-line diffs, context expansion without a round trip, per-file viewed
  state, and findings rendered inline on the line they are about.
- **Re-review when the PR moves** — manually, or automatically via a watch that
  polls for new commits. Notes written against an older commit are flagged
  stale, and the re-review is told what changed since last time.
- **Your own notes too** — click any line number to add one, edit or re-triage
  Claude's, resolve/dismiss/won't-fix.
- **An API designed for Claude to drive** — plus a bundled skill, so you can do
  the review from a Claude Code session instead of from the web UI.

![Findings anchored inline in the diff](docs/screenshot-diff.png)

## Requirements

- Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
- Node 20+ with corepack (only to build the UI)
- `git`, and `make` if you want the shortcuts
- Docker with Compose v2, if you would rather run it in a container
- At least one review engine:
  - [Claude Code](https://claude.com/claude-code), installed and logged in
    (`claude --version` should work) — the default;
  - [Codex](https://github.com/openai/codex) (`codex --version`);
  - [Cursor Agent](https://cursor.com/cli) (`cursor-agent --version`);
  - an `ANTHROPIC_API_KEY`, or any OpenAI-compatible endpoint (see
    [Review engines](#review-engines)).
- A read-scoped token for each forge you use

## Setup

```bash
git clone <this repo> selfcheck && cd selfcheck
cp .env.example .env     # then fill in tokens, or export them in your shell
make setup               # install Python and web dependencies
make build serve         # http://127.0.0.1:7777
```

`make` is a thin wrapper over `scripts/`; `make help` lists every target, and
each one runs a script you could just as well run by hand.

| | |
| --- | --- |
| `make dev` | API with reload + the Vite dev server on `:5173` |
| `make build serve` | build the UI and serve everything as one process |
| `make check` | tests and typecheck |
| `make smoke` | browser smoke test against a running instance |
| `make status` | ask a running instance what it can currently do |
| `make skill` | install the Claude skill |
| `make up` / `make down` | the same stack in Docker |

### Docker

```bash
make up          # build and start, on http://127.0.0.1:7777
make logs        # follow it
make down        # stop it
```

Two things are mounted from the host rather than baked into the image:

- **`./data`** — the database, repo mirrors and worktrees, so a rebuild never
  costs you your reviews or a re-clone.
- **`~/.claude`** — your Claude Code credentials. The review engine runs the
  real CLI, so it needs real auth. **This mounts your actual credentials into
  the container.** If you would rather not, comment out the two `~/.claude`
  lines in `compose.yaml` and set `ANTHROPIC_API_KEY` in `.env` instead.

The container runs as your uid (the Makefile passes it through), so files it
writes into `./data` stay yours. The port is published to `127.0.0.1` only —
selfcheck has no authentication, so do not widen that without putting something
in front of it.

Node and pnpm are pinned (`packageManager` in `web/package.json`, routed
through corepack by `scripts/_node.sh`). Without that, whichever pnpm happens to
be first on your PATH wins, and pnpm 10 and 11 disagree enough to reject the
workspace file or interactively offer to wipe `node_modules` mid-build.

### Tokens

selfcheck reads `GITHUB_TOKEN` / `GITLAB_TOKEN` from the environment or from
`.env` (the environment wins). Ambient tokens already exported in your shell are
picked up with no configuration.

| forge | scopes needed |
| --- | --- |
| GitHub | classic PAT with `repo` (read), or fine-grained with **Pull requests: Read-only** + **Contents: Read-only** |
| GitLab | `read_api` + `read_repository` |

GitLab's newer fine-grained tokens grant permissions per resource, and one that
reads merge requests may still be refused on `/projects/:id` or `/user`. That is
fine: selfcheck treats those as enrichment and falls back to deriving the clone
URL from the host and path. Adding **Project: Read** just gets you the project's
canonical clone URL, which matters only if the project has been renamed.

For self-hosted instances, use `SELFCHECK_HOST_TOKENS` — a JSON map of host to
token:

```bash
SELFCHECK_HOST_TOKENS={"gitlab.corp.io":"glpat-…","ghe.corp.io":"ghp_…"}
```

`GET /api/status` reports which hosts have a token and which review engines are
ready; the sidebar footer and the Review button's picker show the same thing.

Nothing in selfcheck ever prints a token: `/api/status` reports a boolean per
host, and git is handed credentials through `GIT_ASKPASS` rather than a config
file. Be careful with the tools around it, though — `docker compose config`
interpolates `.env` and prints every secret in it in cleartext, so read
`compose.yaml` directly instead. If a token does reach your scrollback, treat it
as leaked and regenerate it; both forges make that a two-click operation.

### Review engines

| engine | `SELFCHECK_ENGINE` | what it needs | how it is kept read-only |
| --- | --- | --- | --- |
| Claude Code | `claude` | the `claude` CLI, logged in | `Read`/`Grep`/`Glob` only, every write and shell tool denied, `--restricted`, no MCP servers |
| Codex | `codex` | the `codex` CLI, logged in | `codex exec --sandbox read-only`: commands may read but cannot write or reach the network |
| Cursor Agent | `cursor` | the `cursor-agent` CLI, logged in | `--mode ask` (Cursor's read-only mode), sandbox on, MCP servers never approved |
| Anthropic API | `anthropic` | `ANTHROPIC_API_KEY` (or `ant auth login`) | selfcheck runs the tool loop and offers only `read_file`, `search`, `list_files` |
| OpenAI-compatible | `openai` | `SELFCHECK_OPENAI_BASE_URL` + `SELFCHECK_OPENAI_MODEL` (+ key if remote) | the same three read-only tools |

`SELFCHECK_ENGINE` is only the default. Each run can use a different engine,
each PR can keep its own default, and each wakeup has its own too. The picker
greys out an engine that is not set up and says why.

For the API engines selfcheck owns the tools, so they are the most tightly
bounded of all: three functions that cannot write, with every path resolved
and checked to stay inside the checkout, symlinks included. For a local model,
point the OpenAI-compatible engine at Ollama (`http://localhost:11434/v1`) or LM
Studio (`http://localhost:1234/v1`). A model without tool calling still works;
it reviews from the diff alone and the run says so.

The Anthropic engine defaults to `claude-opus-5-5` with adaptive thinking,
effort mapped from the review depth (`low` / `high` / `xhigh`), prompt caching,
and the API's server-side refusal fallback where the model supports it.

### Wakeups

The **Wakeups** page (alarm icon on any repo in the sidebar) checks a
repository on a schedule — hourly, every 6 or 12 hours, daily or weekly, at a
time of day in the server's timezone — and reviews new PRs/MRs as they appear.
Each wakeup has its own depth and engine, and can filter by target branch,
author and draft state.

It is deliberately conservative about spending:

- PRs already open when you create the wakeup are left alone unless you tick
  *also review the ones already open*.
- `max per check` (default 3) caps the reviews one check starts; the rest are
  picked up next time, oldest first.
- Runs queue behind `SELFCHECK_MAX_CONCURRENT_RUNS` (default 2).
- *Re-review on push* is off by default; with it on, a tracked PR whose head
  moved is reviewed again at the wakeup's cadence, not on every commit.

Listing a repository's open PRs is a `GET`, through the same read-only client
as everything else. A wakeup missed while selfcheck was not running fires as
soon as it starts again. **Check now** runs one immediately; **Open PRs** shows
what the next check would do with each, and why it would skip the rest.

### Asking, second opinions, learning

**Ask** on any note opens a thread: your question goes to the engine with the
finding, the hunk it is about and the read-only checkout, and the answer cites
`path:line`. Good for "does this really hold?" before you act on it.

**Second opinion** (on the Summary tab) runs another engine on the same
change. Its findings are kept on that run, never replacing yours, and lined up
against the current review: what both found, what only one did, and an
agreement score. *Add to notes* adopts anything only the second engine raised.

**Learning.** A review of a repository is told which findings you have
already *dismissed* there (don't raise again) and marked *won't fix* (known,
out of scope). Turn it off globally or per repository in Settings.

**Rules.** Per-repository instructions, written in Settings, go into every
review of that repository, as does a `.selfcheck.md` at the repository root.
They shape what is checked; they cannot loosen the read-only rules. Each
review's summary shows what shaped it.

### Local branches

Paste a path instead of a link: `~/src/app` (current branch against the
default base), `~/src/app@feature`, or `~/src/app@feature..main`. selfcheck
reads the repository with `rev-parse`, `log`, `diff` and `merge-base` only,
fetches its branches into its own mirror, and reviews a read-only worktree of
that — your working copy and its `.git` are never written to. Committed work
is what gets reviewed; uncommitted edits are not.

### Spend caps

Settings → Spend sets a daily and a monthly cap in USD. Once one is reached,
**automatic** reviews (wakeups, watches) stop until the period turns over; a
review you start yourself still runs. Spend is what the engines report: the
Claude Code CLI and the API engines report cost, a CLI on a flat subscription
may report $0.

### Getting the notes out

selfcheck never posts anything, so copying is the handoff. There are four
places to copy from, and they produce different text on purpose:

| where | gives you |
| --- | --- |
| **Copy** on a note in the diff | just the finding — paste straight into an inline review comment |
| **Copy** on a note in the Notes tab | the same, prefixed with `file:line`, for a comment that is not anchored |
| **Copy N shown** in the Notes tab | every note matching the current filter, grouped by file |
| **Copy summary** / **Copy everything** | the verdict and summary, optionally with all findings |

A note with a suggestion on a single line is copied with a ```` ```suggestion ````
fence, which both GitHub and GitLab turn into an applicable suggestion. The
clipboard falls back to a hidden-textarea copy when the async API is blocked,
and the button tells you if even that failed so nothing is silently lost.

### Keyboard

Press <kbd>?</kbd> in the app for this list.

| key | does |
| --- | --- |
| `1` `2` `3` | Summary / Files / Notes |
| `j` `k` | next / previous file |
| `n` `p` | next / previous finding — jumps to it in the diff |
| `u` | split ↔ unified |
| `w` | ignore whitespace-only changes |
| `d` | word-level intra-line diff |
| `f` | only files with open notes |
| `v` | mark the current file viewed |
| `c` | copy every open note |
| `t` | light ↔ dark |
| `r` | review (or re-review) |
| `s` | sync with the forge |
| `?` | shortcuts |

## Using it from Claude Code

`scripts/install-skill.sh` installs a `selfcheck` skill into
`~/.claude/skills/` (`--project` scopes it to this repo, `--link` symlinks
instead of copying). After that, in any Claude Code session:

> selfcheck this: https://github.com/owner/repo/pull/123

Claude tracks the PR, pulls the context, reads the code in the checkout, and
writes notes back into the UI. `GET /api/agent/guide` prints the same
instructions as plain text if you want to point some other agent at it.

## How the read-only promise is kept

This is the part worth being specific about, because "it only reads" is easy to
say and easy to get wrong.

1. **Forge traffic.** Every GitHub/GitLab call goes through `ReadOnlyClient`,
   which raises `WriteAttemptBlocked` on any verb other than `GET`/`HEAD`. There
   is no code path that can issue a POST to a forge, including by mistake.
2. **Git.** `workspace._git` refuses any subcommand outside a fixed allowlist —
   `push`, `commit`, `tag` and friends are not on it. Every mirror also has
   `remote.origin.pushurl` pinned to `selfcheck://read-only`, so even a
   hand-typed `git push` inside the cache fails before it reaches the network.
3. **Credentials.** Tokens reach git through `GIT_ASKPASS`, never embedded in a
   remote URL, so they are not written into `.git/config` and do not persist in
   the cache. The Claude subprocess gets an environment with forge tokens
   stripped out entirely — it reads a checkout, so it has no use for them.
4. **The review agent.** Claude runs with `--restricted`, an allowlist of
   `Read`/`Grep`/`Glob`, an explicit denylist covering `Write`, `Edit`, `Bash`,
   `WebFetch` and `WebSearch`, and `--strict-mcp-config` with no MCP servers, so
   no MCP tool can smuggle in a write or a network call. Codex runs in its
   `read-only` sandbox and Cursor in its read-only `ask` mode; the API engines
   get three read-only tools confined to the checkout. Every CLI engine goes
   through one subprocess helper that strips forge tokens from its environment
   and kills it on cancel or timeout. See [Review engines](#review-engines) —
   Claude Code's lockdown is the most explicit of the CLIs, which is why it is
   the default.
5. **The checkout.** Worktrees are `chmod`-ed read-only before Claude is pointed
   at them, so a write would fail at the filesystem even if everything above
   were bypassed.
6. **Export.** The only way a note leaves selfcheck is you copying markdown from
   `Copy notes` or `GET /api/reviews/<id>/export.md`.

`scripts/test.sh` runs a suite that asserts each of these.
`scripts/smoke-ui.sh` drives a real browser against a running instance to
check what the copy buttons actually put on the clipboard.

## Architecture

```
selfcheck/
  api/            FastAPI + SQLite. No ORM, one schema, WAL.
    selfcheck/
      providers/  github.py, gitlab.py, and the read-only HTTP client
      workspace.py   fetch-only mirror cache + chmod-read-only worktrees
      engines/       claude, codex, cursor, anthropic_api, openai_api, and the
                     read-only file tools the API engines use
      subproc.py     runs an agent CLI: env scrubbing, timeout, cancel, log
      claude_runner.py  drives `claude -p --output-format stream-json`
      diffparse.py   unified diff -> files/hunks/lines with absolute line numbers
      prompts.py     the review prompt and its JSON output contract
      service.py     orchestration: sync, diff cache, runs, notes
      scheduler.py   background loop: watched PRs and due wakeups
      watches.py     repository wakeups: schedule, filters, per-check cap
      routes/        reviews, runs+notes, agent-facing, system
    tests/
  web/            React 19 + Vite + Shiki. No UI framework, no router.
  skill/selfcheck/  the Claude Code skill
  scripts/        serve, dev, build, test, smoke-ui, install-skill
  Makefile        thin wrappers over the above; `make help`
  Dockerfile      multi-stage: node builds the UI, runtime adds the Claude CLI
                  (Codex and Cursor are not in the image; use an API engine there)
  compose.yaml    the stack, with ./data and ~/.claude mounted in
  data/           SQLite db, repo mirrors, worktrees, run logs  (gitignored)
```

### How a review run works

1. Sync metadata from the forge (`GET` only).
2. Fetch the diff. GitHub serves one directly; for GitLab a unified diff is
   rebuilt from the JSON `changes` payload.
3. Parse it into files → hunks → lines, keeping **absolute file line numbers**.
   This is what lets Claude anchor a note to a line that actually exists, which
   is the usual failure mode of LLM review tools.
4. Fetch-only mirror (`--filter=blob:none`) and a detached worktree at the head
   commit, then `chmod -R a-w`.
5. Run the chosen engine in that worktree, at the chosen depth, with the diff
   re-rendered so every line carries its real line number in the gutter.
6. Parse the JSON block out of the reply, store the notes, stream progress to
   the UI over SSE.

### How the notes are written

The prompt specifies the prose, not just the analysis: conclusion first and
bolded, plain words and active voice, three to six short sentences, one finding
per note, a line or two teaching the underlying idea in ordinary language, and a
closing sentence saying what to do. Polite about the author, never vague about
the facts.

Adjectives alone did not work. Measured across re-reviews of the same pull
request, telling the model to be concise made notes 26% *longer*; adding numeric
limits (900 characters a note, 250 a paragraph, one bolded span) and a worked
example of a good note brought the median body from 763 to 644 characters and
the longest paragraph from 358 to 261, with nothing over budget. If you retune
this, re-measure rather than trusting the wording.

On a re-review, the previous run's notes and the list of files touched since
then go into the prompt, so findings that still hold keep their titles and the
summary can say what changed.

A completed run then **replaces** the previous run's findings rather than adding
a second copy of each. Two things survive that: notes you wrote yourself, which
are never touched, and any decision you already made — resolved, dismissed,
won't fix — which carries across to the re-issued finding by title, so a
re-review cannot resurrect something you have dealt with. A finding the new run
drops simply goes away; earlier verdicts and summaries stay in the run history.

## API

`GET /docs` has the full interactive schema. The endpoints an agent needs:

| method | path | |
| --- | --- | --- |
| `POST` | `/api/reviews` | track a PR/MR by URL (idempotent) |
| `GET` | `/api/reviews/{id}/context` | diff + checkout path + existing notes, in one call |
| `POST` | `/api/reviews/{id}/notes` | write notes |
| `POST` | `/api/reviews/{id}/summary` | write the summary and verdict |
| `POST` | `/api/reviews/{id}/sync` | refetch; reports `head_changed` |
| `PATCH` | `/api/notes/{id}` | re-triage: status, severity, text |
| `GET` | `/api/reviews/{id}/export.md` | notes as markdown |
| `POST` | `/api/reviews/{id}/runs` | run selfcheck's own reviewer; `{"mode", "engine"}` optional |
| `PATCH` | `/api/reviews/{id}/flags` | watch, pin, archive, or this PR's default `mode` / `engine` |
| `GET` `POST` | `/api/wakeups` | list / create repository wakeups |
| `PATCH` `DELETE` | `/api/wakeups/{id}` | change or remove one |
| `POST` | `/api/wakeups/{id}/check` | check now |
| `GET` | `/api/wakeups/{id}/pulls` | open PRs and what the wakeup would do with each |
| `GET` | `/api/runs/{id}/events` | SSE progress |
| `POST` | `/api/reviews/{id}/second-opinion` | another engine, same change; notes untouched |
| `GET` | `/api/reviews/{id}/compare` | second opinion vs the review |
| `POST` | `/api/notes/{id}/ask` | a question about a finding |
| `GET` `PUT` | `/api/repo-rules` | per-repository review rules and learning |
| `GET` `PATCH` | `/api/settings` | engine, models, depth, caps — applied without a restart |
| `GET` | `/api/analytics` | rows behind the dashboard |
| `GET` | `/api/status` | engines, modes, budget, tokens, cache |

## Configuration

Everything in `.env.example`, with the defaults that matter:

| variable | default | |
| --- | --- | --- |
| `SELFCHECK_HOST` / `SELFCHECK_PORT` | `127.0.0.1` / `7777` | keep it on loopback |
| `SELFCHECK_DATA_DIR` | `./data` | db, mirrors, worktrees, logs |
| `SELFCHECK_ENGINE` | `claude` | default engine: `claude` `codex` `cursor` `anthropic` `openai` |
| `SELFCHECK_DEFAULT_MODE` | `normal` | default depth: `light` `normal` `thorough` |
| `SELFCHECK_MAX_CONCURRENT_RUNS` | `2` | reviews at once; the rest queue |
| `SELFCHECK_CLAUDE_MODEL` | CLI default | e.g. `claude-opus-5-5` |
| `SELFCHECK_CODEX_MODEL` / `SELFCHECK_CURSOR_MODEL` | CLI default | |
| `SELFCHECK_ANTHROPIC_MODEL` | `claude-opus-5-5` | with `ANTHROPIC_API_KEY` |
| `SELFCHECK_OPENAI_BASE_URL` | `https://api.openai.com/v1` | any OpenAI-compatible endpoint |
| `SELFCHECK_OPENAI_MODEL` / `SELFCHECK_OPENAI_API_KEY` | — | key optional for a local endpoint |
| `SELFCHECK_RUN_TIMEOUT_SECONDS` | `900` | per normal run; light ×0.5, thorough ×2 |
| `SELFCHECK_LEARN_FROM_DISMISSALS` | `1` | feed dismissed findings into later reviews |
| `SELFCHECK_DAILY_BUDGET_USD` / `SELFCHECK_MONTHLY_BUDGET_USD` | `0` | caps for automatic reviews; 0 = none |

Everything in that table except tokens and keys can also be changed in the
app, under **Settings**, and takes effect on the next review without a
restart. `.env` stays the default; *Reset* in the app goes back to it.
| `SELFCHECK_CLONE_ENABLED` | `1` | `0` reviews from the diff alone |
| `SELFCHECK_CACHE_MAX_GB` | `10` | LRU eviction of repo mirrors |
| `SELFCHECK_WATCH_INTERVAL_SECONDS` | `300` | poll interval for watched PRs |

## Limitations

- Single user, no auth. Bind it to loopback.
- Watching and wakeups poll; there are no webhooks (registering one would mean
  writing to the forge).
- Codex and Cursor are held read-only by their own sandbox and mode, which
  selfcheck selects but cannot inspect the way it can Claude Code's tool
  allowlist. The chmod-read-only checkout still applies underneath.
- Very large diffs are truncated in the prompt — Claude is told to read the rest
  from the checkout, but a 10,000-line PR is still a 10,000-line PR.
- The first review of a big repository pays for the initial fetch. It is cached
  after that.
