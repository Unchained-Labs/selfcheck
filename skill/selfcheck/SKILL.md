---
name: selfcheck
description: Review a GitHub pull request or GitLab merge request through the locally running selfcheck server — pull the PR's diff and a read-only checkout, read the code, and write structured review notes back into selfcheck's UI. Use when the user pastes a PR/MR link and asks for a review, says "selfcheck this", asks to re-review after new commits, or asks about notes already recorded in selfcheck. selfcheck is strictly read-only against GitHub and GitLab; it never posts, approves, merges, or comments.
---

# selfcheck

selfcheck is a local review workbench. It tracks pull/merge requests, keeps a
read-only checkout of each one, and stores review notes in a local database that
its web UI renders next to the diff.

Your job in this skill is to be the reviewer: pull the context, read the code
properly, and write notes back.

## Hard rules

- **Never write to GitHub or GitLab.** No comments, no approvals, no merges, no
  labels, no `gh pr review`, no `glab mr note`. selfcheck has no endpoint that
  does this and neither do you, for this task. Notes live in selfcheck only.
- **Never modify the checkout.** It is chmod'ed read-only on purpose. Do not
  work around that. You are reviewing, not fixing.
- If the user wants the review posted somewhere, hand them the markdown from
  `export.md` and let them paste it.

## Finding the server

Default base URL: `http://127.0.0.1:7777`. Check it is up:

```bash
curl -sf http://127.0.0.1:7777/api/health
```

If that fails, tell the user to start it with `scripts/serve.sh` from the
selfcheck checkout rather than trying to start it yourself. If they run it on
another port, use that instead.

`curl -s http://127.0.0.1:7777/api/agent/guide` prints the live endpoint
reference — read it if anything below looks out of date.

## Reviewing a PR

### 1. Track it

```bash
curl -s -X POST http://127.0.0.1:7777/api/reviews \
  -H 'content-type: application/json' \
  -d '{"url": "<the PR or MR link>"}'
```

Returns `{"review": {"id": "rev_...", ...}}`. Idempotent — posting a URL that is
already tracked returns the existing review. Shorthand works too:
`gh:owner/repo#123`, `gl:group/project#45`.

### 2. Pull the context

```bash
curl -s "http://127.0.0.1:7777/api/reviews/<id>/context?worktree=1" > /tmp/ctx.json
```

One response with everything:

| field | what it is |
| --- | --- |
| `review` | title, description, author, state, branches, `head_sha` |
| `commits` | commit list |
| `files` | per-file status and +/− counts |
| `diff` | the whole diff, re-rendered with **real new-file line numbers in the left gutter** |
| `worktree` | absolute path to a read-only checkout of the head commit, or `null` |
| `existing_notes` | what is already recorded — do not duplicate it |
| `changed_since_last_review` | files touched since your last pass, on a re-review |

The file is large; read it with `jq` rather than dumping it whole:

```bash
jq -r .diff /tmp/ctx.json          # the diff
jq -r .worktree /tmp/ctx.json      # the checkout path
jq -r '.review.title, .review.description' /tmp/ctx.json
jq -r '.existing_notes[] | "\(.severity) \(.file_path):\(.line_start) \(.title)"' /tmp/ctx.json
```

### 3. Actually read the code

This is the part that makes the review worth having. The diff shows you hunks;
the checkout shows you the program. Go into `worktree` and use Read, Grep and
Glob to settle anything the diff cannot:

- Read the **whole function** a hunk sits in, not just the changed lines.
- Grep for **every caller** of a changed signature, and check each one.
- Check whether a test **already covers** the new branch, and whether the new
  tests actually exercise what they claim to.
- Match the change against the **conventions of the code around it** — error
  handling, naming, logging, how similar cases are already handled here.
- Look for the thing that is *missing*: the unhandled error, the case the new
  `if` does not cover, the caller that was not updated.

### 4. Write the notes

```bash
curl -s -X POST http://127.0.0.1:7777/api/reviews/<id>/notes \
  -H 'content-type: application/json' \
  -d @notes.json
```

with `notes.json`:

```json
{
  "origin": "claude",
  "notes": [
    {
      "file": "src/thing.py",
      "line_start": 42,
      "line_end": 45,
      "side": "new",
      "severity": "major",
      "category": "correctness",
      "title": "One line: what is wrong",
      "body": "Markdown. The concrete failure: which input or state, and what goes wrong.",
      "suggestion": "optional replacement code, no fences",
      "confidence": "high"
    }
  ]
}
```

- `line_start`/`line_end` are the numbers printed in the diff's left gutter —
  real `new`-side file line numbers. For a note about a deleted line, set
  `"side": "old"` and use the old numbering.
- For a note that is not about one place, set `"file": ""` and omit the lines.

**Severity**

| value | means |
| --- | --- |
| `blocker` | merging ships a bug, a security hole, or data loss |
| `major` | wrong in a real scenario, or a design choice that will hurt soon |
| `minor` | genuine but bounded; the author may reasonably disagree |
| `nit` | cosmetic — use sparingly; zero nits is a fine outcome |
| `question` | you cannot tell if it is correct without the author's intent |
| `praise` | worth calling out; at most one or two |

**Categories**: `correctness`, `security`, `performance`, `tests`, `style`,
`docs`, `design`, `api`.

**The bar for a note**: state the concrete failure — which input or state, and
what breaks. "This could be a problem" is not a finding; "if `items` is empty,
line 42 raises IndexError" is. A handful of demonstrably real findings beats
twenty speculative ones. If you are guessing, say so in the body and set
`confidence` to `low`.

**How to write it.** Your reader is a competent engineer, short on time, who may
not know this corner of the codebase and is skimming:

- **Conclusion first.** The opening sentence says what is wrong. No preamble, no
  restating the diff back.
- **One finding per note.** If you are writing "also", that is a second note.
- **Three to six short sentences**, ordered so that stopping after the first
  line still leaves the reader correctly informed.
- **Break it up.** Two or three sentences per paragraph, blank lines between.
  Bullets for anything enumerable. Bold the words that carry the finding so a
  skim lands on them. Never a wall of text.
- **Plain words, active voice.** "This leaks the file handle" beats "the file
  handle is not released in the event that an exception propagates". Expand an
  acronym the first time.
- **Teach briefly.** One or two ordinary-language sentences on why it matters
  and what the underlying rule is, the first time it comes up. Name the concept
  so it can be looked up, then get back to the line. Explain without talking
  down, and never imply it is obvious.
- **End with the move** — what to do instead.
- **Be polite the way a good colleague is.** Critique the code, not the person:
  "this path misses the empty case", not "you forgot". Assume there was a
  reason; ask when you cannot tell. No sarcasm, no exclamation marks, no
  compliment sandwiches.
- **Politeness is tone, never facts.** Do not soften a real finding into
  vagueness or hedge on something you verified. "This might possibly be a small
  concern" is not kind, it is unusable.

### 5. Write the summary

```bash
curl -s -X POST http://127.0.0.1:7777/api/reviews/<id>/summary \
  -H 'content-type: application/json' \
  -d '{
    "summary": "markdown, short paragraphs, conclusion first: what the change does, then how sound it looks",
    "verdict": "comments",
    "confidence": "high",
    "risk_areas": ["the parts most likely to bite"],
    "test_gaps": ["behaviour that changed but is not covered"],
    "questions": ["things only the author can answer"],
    "checklist": [{"item": "Errors handled", "state": "pass", "note": "one line"}]
  }'
```

`verdict` is one of `looks_good`, `comments`, `needs_work`. Checklist `state` is
`pass`, `fail`, `na`, or `unknown`. This records a run, so the UI shows your
review as the current one — do it last, after the notes.

Then tell the user what you found and point them at
`http://127.0.0.1:7777/#/r/<id>`.

## Re-reviewing after new commits

```bash
curl -s -X POST http://127.0.0.1:7777/api/reviews/<id>/sync
```

Returns `{"head_changed": true|false}`. When the head moved, notes written
against the old commit are flagged `stale`. Fetch the context again — it will
include `changed_since_last_review`.

- Re-issue findings that still hold, keeping the same `title` so they line up,
  with updated line numbers.
- Resolve what the new commits fixed:
  `curl -X PATCH .../api/notes/<note_id> -H 'content-type: application/json' -d '{"status":"resolved"}'`
- Say in the summary what changed since last time.

## Other things you may be asked

| ask | call |
| --- | --- |
| "what's tracked?" | `GET /api/reviews` |
| "show me the notes" | `GET /api/reviews/<id>/notes` |
| "give me the review to paste" | `GET /api/reviews/<id>/export.md` |
| "resolve/dismiss that one" | `PATCH /api/notes/<note_id>` with `status` |
| "drop that note" | `DELETE /api/notes/<note_id>` |
| "watch this PR" | `PATCH /api/reviews/<id>/flags` with `{"watch": true}` |
| "just let selfcheck do it" | `POST /api/reviews/<id>/runs` — runs selfcheck's own reviewer instead of you |
| "is it set up right?" | `GET /api/status` — Claude CLI, tokens, cache |

## When something is wrong

- **`worktree` is `null`** with a `worktree_error`: the repo cache could not be
  built (missing or unscoped token, private repo, network). Review from the diff
  alone, say so, and lower confidence on anything that depends on code you
  cannot see.
- **502 on add or sync**: the forge rejected the read. Usually a missing or
  under-scoped token — GitHub needs `repo` read (or fine-grained
  "Pull requests: Read-only" + "Contents: Read-only"); GitLab needs `read_api` +
  `read_repository`. Tell the user which host is failing.
- **`diff_truncated: true`**: the diff was too big to inline. Read the remaining
  files from the checkout.
