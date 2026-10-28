# syntax=docker/dockerfile:1

# selfcheck in a container.
#
# The awkward part is that the review engine shells out to the Claude Code CLI,
# so the container needs both the CLI and your Claude credentials. The CLI is
# installed here; the credentials are mounted at run time (see compose.yaml) —
# they are deliberately not baked into the image.
#
# Node is the base rather than Python because the Claude CLI needs it anyway,
# and Debian bookworm's Python 3.11 satisfies the API's floor.

# ── build the web UI ───────────────────────────────────────────────────────
FROM node:25-bookworm-slim AS web

WORKDIR /build
RUN corepack enable
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY web/ ./
RUN pnpm build

# ── runtime ────────────────────────────────────────────────────────────────
FROM node:25-bookworm-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-venv git ca-certificates curl tini \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code && npm cache clean --force

ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies against a stub package first, so editing the source does
# not re-resolve every dependency on each rebuild. The editable install picks up
# the real source when it is copied in below.
COPY api/pyproject.toml /app/api/pyproject.toml
RUN mkdir -p /app/api/selfcheck \
    && touch /app/api/selfcheck/__init__.py \
    && python3 -m venv "$VIRTUAL_ENV" \
    && pip install --no-cache-dir -e /app/api

COPY api/ /app/api/
COPY --from=web /build/dist /app/web/dist
COPY skill/ /app/skill/

# The container runs as the host user (see compose.yaml) so that files written
# into the mounted data/ and ~/.claude keep the right ownership. That uid has no
# passwd entry, so HOME is set explicitly and made writable for anyone.
ENV HOME=/home/app
RUN mkdir -p /home/app /app/data && chmod 1777 /home/app /app/data

# Bind to all interfaces *inside* the container; compose publishes it only to
# the host's loopback, so it is still not reachable from the network.
ENV SELFCHECK_HOST=0.0.0.0 \
    SELFCHECK_PORT=7777 \
    SELFCHECK_DATA_DIR=/app/data

EXPOSE 7777

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:7777/api/health || exit 1

# tini reaps the claude processes the reviewer spawns; without an init, killed
# or finished CLI runs would pile up as zombies under PID 1.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python3", "-m", "selfcheck"]
