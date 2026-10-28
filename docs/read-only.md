# The read-only promise

"It only reads" is easy to say and easy to get wrong, so here is how it is
kept. The test suite asserts each point.

1. **Forge traffic.** Every GitHub and GitLab call — metadata, diffs, PR lists
   for wakeups — goes through `ReadOnlyClient`, which raises on any verb other
   than `GET`/`HEAD`. There is no code path that can POST to a forge.
2. **Git.** `workspace._git` refuses any subcommand outside a fixed allowlist;
   `push`, `commit`, `tag` and friends are not on it. Every mirror's push URL
   is pinned to `selfcheck://read-only`.
3. **Credentials.** Tokens reach git through `GIT_ASKPASS`, never a URL, and
   are stripped from every engine's environment.
4. **The engines.** Each runs in its most restrictive mode
   ([table](engines.md)); the API engines only get three read-only tools that
   refuse any path outside the checkout, symlinks included.
5. **The checkout.** Worktrees are `chmod`'ed read-only before an engine sees
   them.
6. **Local branches.** Read with `rev-parse`, `log`, `diff`, `merge-base`;
   reviewed from selfcheck's own mirror. The source repository is not written.
7. **Export.** A note leaves selfcheck only when you copy it.

Found a way around any of this? Please report it privately — see
[SECURITY.md](https://github.com/Unchained-Labs/selfcheck/blob/main/SECURITY.md).
