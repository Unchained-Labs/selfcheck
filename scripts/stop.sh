#!/usr/bin/env bash
# Stop servers started by scripts/dev.sh.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
shopt -s nullglob
for pidfile in "$ROOT"/data/*.pid; do
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" && echo "stopped $(basename "$pidfile" .pid) ($pid)"
  fi
  rm -f "$pidfile"
done
