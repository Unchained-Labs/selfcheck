# Reviewing

## Re-reviews

When a pull request moves, **Sync** (++s++) fetches it and flags notes written
against the old head as *stale*. A re-review (++r++) is told what changed
since the last one and replaces its findings rather than stacking a second
copy. Your own notes survive, and so does every decision you made: a finding
you dismissed comes back dismissed.

**Watch** re-reviews a pull request by itself when new commits land.

## Ask about a finding

**Ask** on any note opens a thread. Your question goes to the engine with the
finding, the hunk it is about and the read-only checkout; the answer leads
with *yes, it holds* / *no, it does not* and cites `path:line`.

## Second opinion

On the **Summary** tab, pick another engine and run a second opinion. Its
findings are kept on that run — your notes are untouched — and lined up
against the review: what both found, what only one did, and an agreement
score. Findings both engines raise are rarely noise; **Add to notes** adopts
anything only the second engine noticed.

## Learning from your decisions

A review of a repository is told which findings you already **dismissed**
there (not real — do not raise again) and marked **won't fix** (real, out of
scope). It may still raise one again if it is sure, but it has to say why. Turn
learning off globally or per repository in **Settings**.

## Repository rules

Per-repository instructions written in **Settings** go into every review of
that repository, together with a `.selfcheck.md` at the repository root if it
has one:

```markdown title=".selfcheck.md"
- Every migration needs a down step.
- Logging goes through utils.log, never print().
- Be strict about thread safety in src/runtime/.
```

Rules shape *what* gets checked. They cannot loosen the read-only rules.

## Getting notes out

| where | gives you |
| --- | --- |
| **Copy** on a note in the diff | the finding, ready for an inline comment |
| **Copy** in the Notes tab | the same, prefixed with `file:line` |
| **Copy N shown** | every note matching the filter, grouped by file |
| **Copy summary** / **Copy everything** | the verdict and summary, optionally with all findings |

A single-line suggestion is copied as a ```` ```suggestion ```` block, which
GitHub and GitLab both turn into an applicable change.
