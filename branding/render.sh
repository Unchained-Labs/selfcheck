#!/usr/bin/env bash
# Render the PNGs in branding/logo from the SVGs build.py writes, with headless
# Chrome so the wordmark is set in Inter exactly as on the web. Needs Chrome
# (CHROME=/path/to/chrome to override) and a network connection for the fonts.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CHROME="${CHROME:-$(command -v google-chrome || command -v chromium || command -v chromium-browser)}"
OUT="$HERE/logo"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

FONTS='<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;650;700&family=JetBrains+Mono:wght@500&display=block" rel="stylesheet">'

shot() { # name width height html
  printf '%s' "$4" > "$TMP/$1.html"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=2 \
    --virtual-time-budget=6000 --window-size="$2,$3" \
    --screenshot="$OUT/$1.png" "file://$TMP/$1.html" >/dev/null 2>&1
  echo "  $1.png"
}

page() { # background, body
  printf '<!doctype html><meta charset="utf-8">%s<style>html,body{margin:0;background:%s;width:100%%;height:100%%;overflow:hidden}body{display:grid;place-items:center;font-family:Inter,system-ui,sans-serif}</style><body>%s' "$FONTS" "$1" "$2"
}

echo "rendering into $OUT"
shot mark 256 256 "$(page transparent "$(cat "$OUT/mark.svg" | sed 's/viewBox="0 0 64 64" width="64" height="64"/viewBox="0 0 64 64" width="256" height="256"/')")"
shot lockup-dark 420 120 "$(page transparent "$(cat "$OUT/lockup-dark.svg")")"
shot lockup-light 420 120 "$(page transparent "$(cat "$OUT/lockup-light.svg")")"

MARK="$(sed 's/viewBox="0 0 64 64" width="64" height="64"/viewBox="0 0 64 64" width="148" height="148"/' "$OUT/mark.svg")"
shot og-card 1200 630 "$(page '#1b1410' "
<div style=\"width:1200px;height:630px;box-sizing:border-box;padding:84px 96px;display:grid;grid-template-columns:auto 1fr;gap:44px;align-content:center;
  background:radial-gradient(900px 500px at 85% 15%, rgba(242,140,92,.16), transparent 60%), radial-gradient(700px 420px at 10% 100%, rgba(247,215,114,.10), transparent 60%), #1b1410\">
  <div style=\"padding-top:6px\">$MARK</div>
  <div style=\"display:grid;gap:22px\">
    <div style=\"font-size:84px;font-weight:700;letter-spacing:-3px;color:#fef5ee;line-height:1\">self<span style=\"color:#f28c5c\">check</span></div>
    <div style=\"font-size:34px;font-weight:500;line-height:1.3;color:#cfbfb5;max-width:820px\">Review pull requests and local branches with the coding agent you already have. Read-only, local, yours.</div>
    <div style=\"display:flex;gap:12px;flex-wrap:wrap;margin-top:6px\">
      $(for t in 'Claude Code' 'Codex' 'Cursor' 'Anthropic API' 'Ollama'; do printf '<span style="font:500 22px JetBrains Mono,monospace;color:#f28c5c;border:1.5px solid rgba(242,140,92,.4);border-radius:999px;padding:6px 16px">%s</span>' "$t"; done)
    </div>
  </div>
</div>")"
echo done
