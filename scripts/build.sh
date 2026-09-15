#!/usr/bin/env bash
# Build the web UI so the API can serve everything as one process.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=_node.sh
source "$ROOT/scripts/_node.sh"
cd "$ROOT/web"
[ -d node_modules ] || pnpm install
pnpm build
echo "built -> $ROOT/web/dist   (scripts/serve.sh now serves the UI too)"
