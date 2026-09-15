#!/usr/bin/env bash
# Browser smoke test against an already-running selfcheck.
# Needs Chrome; set CHROME_PATH if it is not at /usr/bin/google-chrome.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=_node.sh
source "$ROOT/scripts/_node.sh"
cd "$ROOT/web"
[ -d node_modules ] || pnpm install
exec node smoke/ui.mjs "$@"
