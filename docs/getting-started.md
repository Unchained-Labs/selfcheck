# Install

selfcheck is one process: a FastAPI server that also serves the UI, with a
SQLite file for its data. It listens on `127.0.0.1:7777` and has no
authentication, so keep it on loopback.

=== "Docker"

    ```bash
    docker run --rm -p 127.0.0.1:7777:7777 \
      -v ./data:/app/data --env-file .env \
      ghcr.io/unchained-labs/selfcheck:latest
    ```

    The image includes the Claude Code CLI. To use it, mount your
    credentials (`-v ~/.claude:/home/app/.claude`) or set `ANTHROPIC_API_KEY`
    and choose the **Anthropic API** engine. Codex and Cursor are not in the
    image; use them from a source install.

=== "Release tarball"

    Download `selfcheck-X.Y.Z.tar.gz` from the
    [releases](https://github.com/Unchained-Labs/selfcheck/releases). The UI
    is prebuilt, so only Python 3.11+ and [`uv`](https://docs.astral.sh/uv/)
    are needed:

    ```bash
    tar xzf selfcheck-*.tar.gz && cd selfcheck-*/
    cp .env.example .env
    make serve
    ```

=== "From source"

    ```bash
    git clone https://github.com/Unchained-Labs/selfcheck && cd selfcheck
    cp .env.example .env
    make setup        # Python + web dependencies (Node 20+ with corepack)
    make build serve  # http://127.0.0.1:7777
    ```

## Tokens

selfcheck reads `GITHUB_TOKEN` / `GITLAB_TOKEN` from the environment or
`.env`. Public repositories work without one. Read scopes are enough:

| forge | scopes |
| --- | --- |
| GitHub | classic PAT with `repo` (read), or fine-grained *Pull requests: Read* + *Contents: Read* |
| GitLab | `read_api` + `read_repository` |

Self-hosted instances take `SELFCHECK_HOST_TOKENS={"gitlab.corp.io":"glpat-…"}`.
Nothing ever prints a token; `/api/status` only says whether one is set.

## An engine

At least one of: [Claude Code](https://claude.com/claude-code),
[Codex](https://github.com/openai/codex) or Cursor Agent installed and logged
in, an `ANTHROPIC_API_KEY`, or an OpenAI-compatible endpoint such as a local
Ollama. See [Review engines](engines.md). The first-run guide on the home
page ticks each step off as you do it.
