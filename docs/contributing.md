# Contributing

Issues and pull requests are welcome. The full guide is
[CONTRIBUTING.md](https://github.com/Unchained-Labs/selfcheck/blob/main/CONTRIBUTING.md);
the short version:

```bash
git clone https://github.com/Unchained-Labs/selfcheck && cd selfcheck
make setup && make dev     # API with reload + Vite on :5173
make check                 # lint, tests and typecheck, as CI runs them
```

- Add or update tests; anything touching the read-only promise needs a test
  that asserts the promise still holds.
- Add a line under **Unreleased** in `CHANGELOG.md`.
- **Every merged pull request releases.** The *Release preview* check says
  which version: a `release:major` / `release:minor` / `release:patch` label
  wins, else `feat:` in the title is a minor release, `!` or `BREAKING` a major
  one, anything else a patch.

Security problems — above all, any way around the read-only promise — go
through a [private advisory](https://github.com/Unchained-Labs/selfcheck/security/advisories/new),
not an issue. The project follows its
[code of conduct](https://github.com/Unchained-Labs/selfcheck/blob/main/CODE_OF_CONDUCT.md)
and is released under the
[BSD 3-Clause License](https://github.com/Unchained-Labs/selfcheck/blob/main/LICENSE).
