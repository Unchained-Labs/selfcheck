# Settings and spend

Most settings can be changed in the app, under **Settings**, and take effect
on the next review without a restart. `.env` holds the defaults and every
secret; **Reset** in the app returns to it.

| variable | default | in the app |
| --- | --- | --- |
| `SELFCHECK_ENGINE` | `claude` | ✓ |
| `SELFCHECK_DEFAULT_MODE` | `normal` | ✓ |
| `SELFCHECK_MAX_CONCURRENT_RUNS` | `2` | ✓ |
| `SELFCHECK_RUN_TIMEOUT_SECONDS` | `900` | ✓ |
| `SELFCHECK_{CLAUDE,CODEX,CURSOR}_MODEL` | CLI default | ✓ |
| `SELFCHECK_ANTHROPIC_MODEL` | `claude-opus-5-5` | ✓ |
| `SELFCHECK_OPENAI_BASE_URL` / `_MODEL` | OpenAI / — | ✓ |
| `SELFCHECK_LEARN_FROM_DISMISSALS` | `1` | ✓ |
| `SELFCHECK_DAILY_BUDGET_USD` / `_MONTHLY_` | `0` (none) | ✓ |
| `ANTHROPIC_API_KEY`, `SELFCHECK_OPENAI_API_KEY` | — | presence only |
| `GITHUB_TOKEN`, `GITLAB_TOKEN`, `SELFCHECK_HOST_TOKENS` | — | presence only |
| `SELFCHECK_HOST` / `SELFCHECK_PORT` | `127.0.0.1` / `7777` | — |
| `SELFCHECK_DATA_DIR` | `./data` | — |
| `SELFCHECK_CLONE_ENABLED` | `1` | — |
| `SELFCHECK_CACHE_MAX_GB` | `10` | — |
| `SELFCHECK_WATCH_INTERVAL_SECONDS` | `300` | — |

## Spend caps

A daily and a monthly cap in USD. Once one is reached, **automatic** reviews —
wakeups and watches — stop until the period turns over; a review you start
yourself still runs. Spend is what the engines report: the Claude Code CLI and
the API engines report cost; a CLI on a flat subscription may report $0.

## Notifications

**Settings → Desktop notifications** raises a browser notification when a
review finishes with blockers or majors (or every review), and when one fails.
It is entirely in the browser, saved per browser, and only fires while
selfcheck is open in a tab.

## Theme

Auto (follows the system), Light or Dark, from the sidebar. ++t++ toggles.
