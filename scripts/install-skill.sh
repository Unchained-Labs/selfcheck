#!/usr/bin/env bash
# Install the selfcheck skill so Claude Code can drive this app.
#   scripts/install-skill.sh            -> ~/.claude/skills/selfcheck   (all projects)
#   scripts/install-skill.sh --project  -> .claude/skills/selfcheck     (this repo only)
#   scripts/install-skill.sh --link     -> symlink instead of copy
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/skill/selfcheck"

dest_base="$HOME/.claude/skills"
mode="copy"
for arg in "$@"; do
  case "$arg" in
    --project) dest_base="$ROOT/.claude/skills" ;;
    --link)    mode="link" ;;
    -h|--help) sed -n '2,5p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

DEST="$dest_base/selfcheck"
mkdir -p "$dest_base"
rm -rf "$DEST"

if [ "$mode" = "link" ]; then
  ln -s "$SRC" "$DEST"
  echo "linked $DEST -> $SRC"
else
  cp -r "$SRC" "$DEST"
  echo "installed $DEST"
fi

echo
echo "Start a new Claude Code session, then try:"
echo "  \"selfcheck this: https://github.com/owner/repo/pull/123\""
