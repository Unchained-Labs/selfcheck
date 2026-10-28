# Contributing to selfcheck

Thanks for helping. selfcheck is small on purpose, and its one hard rule is
that it **never writes to a forge**. Every contribution keeps that true.

## Set up

```bash
git clone https://github.com/Unchained-Labs/selfcheck && cd selfcheck
cp .env.example .env      # optional: tokens for the forges you use
make setup                # Python and web dependencies
make dev                  # API with reload + Vite on :5173
```

You need Python 3.11+, [`uv`](https://docs.astral.sh/uv/), Node 20+ with
corepack, and `git`. A review engine (Claude Code, Codex, Cursor Agent, or an
API key) is only needed to run real reviews; the test suite needs none.

## Before you open a pull request

```bash
make check                          # tests and typecheck
make lint
make smoke                          # optional: browser smoke test against a running instance
```

- **Tests.** Add or update tests for behaviour you change. Anything touching
  the read-only promise (forge HTTP, git, engine sandboxes, file tools) needs a
  test that asserts the promise still holds — see the existing ones in
  `api/tests/test_selfcheck.py`.
- **Style.** Match the code around you: naming, comment density, error
  handling. Comments explain *why*, not what.
- **Changelog.** Add a line under `## [Unreleased]` in `CHANGELOG.md`.
- **Prompts.** If you change review prompts, try them on real diffs and say
  what changed in the notes, not just that they still parse.

## Releases

**Every pull request merged into `main` releases a new version.** The
*Release preview* check on your pull request says which one. How much it bumps:

1. A label, if there is one: `release:major`, `release:minor` or
   `release:patch` (at most one).
2. Otherwise the title: `feat: …` is a minor release, `feat!: …` or anything
   mentioning `BREAKING` is a major one.
3. Otherwise a patch.

On merge, CI writes the new version everywhere, dates the changelog, tags
`vX.Y.Z`, publishes a GitHub release and pushes a Docker image to
`ghcr.io/unchained-labs/selfcheck`. Nothing to do by hand.

## Reporting bugs and ideas

Use the issue templates. For anything security-related — especially a way to
make selfcheck write to a forge or outside its checkout — follow
[SECURITY.md](SECURITY.md) instead of opening an issue.

By contributing you agree your work is released under the
[BSD 3-Clause License](LICENSE) and that you follow the
[Code of Conduct](CODE_OF_CONDUCT.md).
