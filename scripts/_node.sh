# Put a modern node and the project's pnpm on PATH. Sourced by the other
# scripts, so it must not assume anything about the caller's shell setup.

if ! node -e 'process.exit(process.versions.node.split(".")[0] >= 20 ? 0 : 1)' 2>/dev/null; then
  if [ -s "$HOME/.nvm/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.nvm/nvm.sh"
    nvm use 22 >/dev/null 2>&1 || nvm use --lts >/dev/null 2>&1 || true
  fi
fi

if ! node -e 'process.exit(process.versions.node.split(".")[0] >= 20 ? 0 : 1)' 2>/dev/null; then
  echo "node 20+ is required; found $(node --version 2>/dev/null || echo 'no node')" >&2
  exit 1
fi

corepack enable >/dev/null 2>&1 || true

# Route pnpm through corepack so the version pinned in web/package.json's
# packageManager field is the one that runs. A standalone pnpm earlier on PATH
# would otherwise win, and the versions disagree enough to reject the workspace
# file or interactively offer to wipe node_modules mid-build.
if command -v corepack >/dev/null 2>&1; then
  pnpm() { corepack pnpm "$@"; }
elif ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm not found. Enable corepack (corepack enable) or install pnpm." >&2
  exit 1
fi
