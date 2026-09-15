#!/usr/bin/env bash
# API with reload + the Vite dev server. Ctrl-C stops both.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=_node.sh
source "$ROOT/scripts/_node.sh"
mkdir -p "$ROOT/data"

cd "$ROOT/api"
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install -q -e . --python .venv/bin/python
.venv/bin/python -m uvicorn selfcheck.main:app \
  --host 127.0.0.1 --port "${SELFCHECK_PORT:-7777}" --reload &
API_PID=$!
echo "$API_PID" > "$ROOT/data/api.pid"

cd "$ROOT/web"
[ -d node_modules ] || pnpm install
pnpm dev &
WEB_PID=$!
echo "$WEB_PID" > "$ROOT/data/web.pid"

trap 'kill $API_PID $WEB_PID 2>/dev/null; rm -f "$ROOT"/data/*.pid' INT TERM EXIT
printf '\n  UI   http://127.0.0.1:5173\n  API  http://127.0.0.1:%s/docs\n\n' "${SELFCHECK_PORT:-7777}"
wait
