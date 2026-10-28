# Review engines

An engine is whatever reads the change and writes the notes. Pick the default
in **Settings** or from the sidebar footer; override it per pull request, per
wakeup, or for one run from the arrow on the **Review** button.

| engine | kind | needs | held read-only by |
| --- | --- | --- | --- |
| **Claude Code** | local CLI | `claude`, logged in | an allowlist of `Read`/`Grep`/`Glob`, every write and shell tool denied, `--restricted`, no MCP servers |
| **Codex** | local CLI | `codex`, logged in | `codex exec --sandbox read-only`: commands may read, never write or reach the network |
| **Cursor Agent** | local CLI | `cursor-agent`, logged in | `--mode ask`, sandbox on, MCP servers never approved |
| **Anthropic API** | API | `ANTHROPIC_API_KEY` | selfcheck runs the loop; the model only has `read_file`, `search`, `list_files` |
| **OpenAI-compatible** | API | a base URL and a model | the same three tools |

In every case the checkout itself is `chmod`'ed read-only, forge tokens are
stripped from the engine's environment, and the run is killed on cancel or
timeout.

## Models

Each engine's model is set in **Settings**. Where the engine can list its
models without spending tokens — the OpenAI-compatible endpoint, the
Anthropic API, Cursor — the search button fills a picker. The Anthropic engine
defaults to `claude-opus-5-5` with adaptive thinking, prompt caching, and the
API's refusal fallback.

## Local models

Point the OpenAI-compatible engine at Ollama (`http://localhost:11434/v1`) or
LM Studio (`http://localhost:1234/v1`) — presets for both are in Settings — and
nothing leaves the machine. A model without tool calling still works: it
reviews from the diff alone and the run says so.

## Depth

| depth | asks for | effort |
| --- | --- | --- |
| **Light** | blockers and majors only, mostly from the diff, at most five notes | low, short turn budget, half the time limit |
| **Normal** | a full review | high |
| **Thorough** | every changed function read in full, every caller checked, tests and failure paths walked | highest, long turn budget, double the time limit |

The writing rules — conclusion first, short, one finding per note — apply at
every depth: thorough means more checking, not longer notes.
