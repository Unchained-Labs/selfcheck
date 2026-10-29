#!/usr/bin/env bash
# Turn record.mjs's WebM segments into MP4 featurettes and the promo.
#
#   bash branding/video/build.sh [segments-dir] [output-dir]
#
# Featurettes: one MP4 per scene, its segments joined, a short fade at each
# end. The promo: a title card, every scene in order, an end card. Cards are
# rendered from HTML with headless Chrome so they use the brand fonts. H.264,
# 1280x800, 30 fps, no audio — small enough to embed. Needs ffmpeg and Chrome.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEG="${1:-$HERE/out}"
OUT="${2:-$HERE/../../docs/assets/media}"
CHROME="${CHROME:-$(command -v google-chrome || command -v chromium)}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$OUT"

SCENES=(dashboard review ask second wakeups engines)
ENC=(-c:v libx264 -preset slow -crf 26 -pix_fmt yuv420p -r 30 -movflags +faststart -an)
SCALE="scale=1280:800:flags=lanczos,setsar=1"

clip() { # in out — scale, normalise frame rate, fade in and out
  local d; d="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null || echo 0)"
  if [ "$d" = "N/A" ] || [ -z "$d" ]; then
    ffmpeg -v error -y -i "$1" -c copy "$TMP/probe.mkv"
    d="$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$TMP/probe.mkv")"
  fi
  local fo; fo="$(python3 -c "print(max(0.0, float('$d') - 0.35))")"
  ffmpeg -v error -y -i "$1" -vf "$SCALE,fps=30,fade=t=in:st=0:d=0.3,fade=t=out:st=$fo:d=0.35" "${ENC[@]}" "$2"
}

join() { # out in...
  local out="$1"; shift
  local list="$TMP/list-$(basename "$out").txt"; : > "$list"
  for f in "$@"; do echo "file '$f'" >> "$list"; done
  ffmpeg -v error -y -f concat -safe 0 -i "$list" -c copy -movflags +faststart "$out"
}

card() { # name seconds html
  printf '%s' "$3" > "$TMP/$1.html"
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --virtual-time-budget=6000 --window-size=1280,800 --screenshot="$TMP/$1.png" "file://$TMP/$1.html" >/dev/null 2>&1
  ffmpeg -v error -y -loop 1 -t "$2" -i "$TMP/$1.png" \
    -vf "$SCALE,fps=30,fade=t=in:st=0:d=0.4,fade=t=out:st=$(python3 -c "print($2 - 0.4)"):d=0.4" "${ENC[@]}" "$TMP/$1.mp4"
}

MARK="$(sed 's/viewBox="0 0 64 64" width="64" height="64"/viewBox="0 0 64 64" width="132" height="132"/' "$HERE/../logo/mark.svg")"
STYLE='<link href="https://fonts.googleapis.com/css2?family=Inter:wght@500;650;700&display=block" rel="stylesheet"><style>html,body{margin:0;width:1280px;height:800px;overflow:hidden;font-family:Inter,sans-serif;background:radial-gradient(900px 520px at 80% 10%,rgba(62,207,142,.16),transparent 60%),radial-gradient(700px 420px at 10% 100%,rgba(110,231,183,.10),transparent 60%),#171717;color:#ededed}main{height:100%;display:grid;place-content:center;justify-items:center;gap:26px;text-align:center}h1{margin:0;font-size:96px;font-weight:700;letter-spacing:-3.5px;line-height:1}h1 span{color:#3ecf8e}p{margin:0;font-size:32px;font-weight:500;color:#b4b4b4;max-width:900px;line-height:1.35}code{font:500 26px "JetBrains Mono",monospace;color:#3ecf8e;background:rgba(62,207,142,.08);border:1px solid rgba(62,207,142,.35);padding:10px 18px;border-radius:12px}</style>'

echo "featurettes"
for s in "${SCENES[@]}"; do
  parts=()
  for seg in "$SEG/$s"-*.webm; do
    [ -e "$seg" ] || continue
    clip "$seg" "$TMP/$(basename "$seg" .webm).mp4"
    parts+=("$TMP/$(basename "$seg" .webm).mp4")
  done
  [ "${#parts[@]}" -gt 0 ] || { echo "  no segments for $s, skipped"; continue; }
  join "$OUT/selfcheck-$s.mp4" "${parts[@]}"
  echo "  selfcheck-$s.mp4"
done

echo "promo"
card title 3.2 "<!doctype html>$STYLE<main>$MARK<h1>self<span>check</span></h1><p>Review pull requests and local branches with the coding agent you already have.</p></main>"
card end 4.5 "<!doctype html>$STYLE<main>$MARK<h1>self<span>check</span></h1><p>Read-only. Local. Yours.</p><code>docker run -p 127.0.0.1:7777:7777 ghcr.io/unchained-labs/selfcheck</code></main>"
promo=("$TMP/title.mp4")
for s in "${SCENES[@]}"; do [ -e "$OUT/selfcheck-$s.mp4" ] && promo+=("$OUT/selfcheck-$s.mp4"); done
promo+=("$TMP/end.mp4")
join "$OUT/selfcheck-promo.mp4" "${promo[@]}"
ffmpeg -v error -y -ss 6 -i "$OUT/selfcheck-promo.mp4" -frames:v 1 -vf "scale=1280:-1" "$OUT/selfcheck-promo.jpg"
du -h "$OUT"/*.mp4 | sed 's#.*/##; s#^#  #'
