# Put a modern node + pnpm on PATH. Sourced by the other scripts.
if ! node -e 'process.exit(process.versions.node.split(".")[0] >= 20 ? 0 : 1)' 2>/dev/null; then
  if [ -s "$HOME/.nvm/nvm.sh" ]; then
    # shellcheck disable=SC1091
    . "$HOME/.nvm/nvm.sh"
    nvm use 22 >/dev/null 2>&1 || nvm use --lts >/dev/null 2>&1 || true
  fi
fi
command -v pnpm >/dev/null 2>&1 || corepack enable >/dev/null 2>&1 || true
if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm not found. Try: corepack enable" >&2
  exit 1
fi
