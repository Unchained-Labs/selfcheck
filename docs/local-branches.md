# Local branches

Review your work before you push it. Paste a path instead of a link:

| you type | reviews |
| --- | --- |
| `~/src/app` | the current branch against the repository's default base |
| `~/src/app@feature` | `feature` against the default base |
| `~/src/app@feature..main` | `feature` against `main` |

The base is found from `origin/HEAD`, then `origin/main`, `origin/master`,
`main` or `master`.

## What happens to your repository

Nothing. selfcheck reads it with `rev-parse`, `log`, `diff` and `merge-base`
only — the same git allowlist as everything else — then fetches its branches
into selfcheck's own mirror and reviews a read-only worktree of *that*. Your
working copy and its `.git` are never written to; the test suite asserts it.

!!! note "Committed work only"
    The head is a commit, so uncommitted edits are not reviewed. Commit (or
    stash and commit to a scratch branch) first.

Sync picks up new commits on the branch, so **Watch** works too.
