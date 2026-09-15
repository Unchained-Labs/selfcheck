#!/usr/bin/env bash
# Start selfcheck. Serves the built UI too, if web/dist exists.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/api"
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install -q -e . --python .venv/bin/python
exec .venv/bin/python -m selfcheck
