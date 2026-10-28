# API

`GET /docs` on a running instance has the full interactive schema. An agent
driving selfcheck should start with `GET /api/agent/guide`; the bundled Claude
Code skill does.

| method | path | |
| --- | --- | --- |
| `POST` | `/api/reviews` | track a PR/MR by URL, or a local branch by path (idempotent) |
| `GET` | `/api/reviews/{id}/context` | diff + checkout path + existing notes, in one call |
| `POST` | `/api/reviews/{id}/notes` | write notes |
| `POST` | `/api/reviews/{id}/summary` | write the summary and verdict |
| `POST` | `/api/reviews/{id}/sync` | refetch; reports `head_changed` |
| `POST` | `/api/reviews/{id}/runs` | run a review; `{"mode", "engine"}` optional |
| `POST` | `/api/reviews/{id}/second-opinion` | another engine, same change |
| `GET` | `/api/reviews/{id}/compare` | second opinion vs the review |
| `PATCH` | `/api/notes/{id}` | re-triage: status, severity, text |
| `POST` | `/api/notes/{id}/ask` | a question about a finding |
| `GET` `POST` | `/api/wakeups` | repository wakeups |
| `POST` | `/api/wakeups/{id}/check` | check now |
| `GET` `PATCH` | `/api/settings` | runtime settings |
| `GET` `PUT` | `/api/repo-rules` | per-repository rules and learning |
| `GET` | `/api/analytics` | rows behind the dashboard |
| `GET` | `/api/status` | engines, budget, tokens, cache |
| `GET` | `/api/runs/{id}/events` | server-sent events for a run |
| `GET` | `/api/reviews/{id}/export.md` | notes as markdown |
