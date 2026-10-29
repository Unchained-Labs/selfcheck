#!/usr/bin/env python3
"""Build selfcheck's identity from numbers: the mark, its variants, the palette.

    python3 branding/build.py        # writes branding/logo/*.svg, palette.*, tokens.*

Nothing in branding/ is drawn by hand. The mark's geometry, the colour scales
and the contrast table all come out of this file, so changing a number here
and re-running is the only way the identity changes. Standard library only.
PNG renders (lockups, the social card) come from render.sh, which screenshots
the SVGs with headless Chrome.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOGO = HERE / "logo"

# ── colour: OKLCH scales, gamut-mapped into sRGB ──────────────────────────

# Lightness per step. 50 is nearly white, 950 nearly black; 500 sits where a
# saturated colour reads on both light and dark surfaces.
STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950]
L = [0.975, 0.945, 0.885, 0.815, 0.74, 0.66, 0.575, 0.49, 0.405, 0.32, 0.235]

# (hue, peak chroma, role). The neutrals are a true graphite, so the emerald
# brand is the only colour on a quiet page; the status hues sit at the same
# weight so none shouts louder than its meaning.
FAMILIES: dict[str, tuple[float, float, str]] = {
    "emerald": (158, 0.15, "brand, focus, links, the check, pass"),
    "graphite": (0, 0.0, "text, surfaces, borders"),
    "coral": (22, 0.17, "blocker, failure, deletions"),
    "apricot": (55, 0.15, "major, warning"),
    "honey": (92, 0.14, "minor, caution"),
    "lavender": (295, 0.13, "question, merged"),
}


def _oklch_to_linear(lum: float, c: float, h: float) -> tuple[float, float, float]:
    a, b = c * math.cos(math.radians(h)), c * math.sin(math.radians(h))
    l_ = lum + 0.3963377774 * a + 0.2158037573 * b
    m_ = lum - 0.1055613458 * a - 0.0638541728 * b
    s_ = lum - 0.0894841775 * a - 1.2914855480 * b
    l3, m3, s3 = l_**3, m_**3, s_**3
    return (
        4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
        -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
        -0.0041960863 * l3 - 0.7034186147 * m3 + 1.7076147010 * s3,
    )


def _in_gamut(rgb: tuple[float, float, float]) -> bool:
    return all(-1e-4 <= x <= 1 + 1e-4 for x in rgb)


def oklch_hex(lum: float, c: float, h: float) -> tuple[str, float]:
    """Hex for an OKLCH colour, lowering chroma until it fits sRGB."""
    while c > 0 and not _in_gamut(_oklch_to_linear(lum, c, h)):
        c -= 0.002
    rgb = _oklch_to_linear(lum, max(c, 0), h)

    def enc(x: float) -> int:
        x = min(1.0, max(0.0, x))
        v = 1.055 * x ** (1 / 2.4) - 0.055 if x > 0.0031308 else 12.92 * x
        return round(v * 255)

    return "#%02x%02x%02x" % tuple(enc(x) for x in rgb), round(max(c, 0), 3)


def chroma_at(step_index: int, peak: float) -> float:
    """Full chroma in the middle of the scale, tapering towards white and black."""
    t = step_index / (len(STEPS) - 1)
    return peak * (0.35 + 0.65 * math.sin(math.pi * min(1.0, 0.15 + t * 0.85)))


def scales() -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    for name, (hue, peak, _role) in FAMILIES.items():
        fam = {}
        for i, step in enumerate(STEPS):
            hexv, c = oklch_hex(L[i], chroma_at(i, peak), hue)
            fam[str(step)] = {"hex": hexv, "oklch": f"oklch({L[i]:.3f} {c:.3f} {hue})"}
        out[name] = fam
    return out


def luminance(hexv: str) -> float:
    r, g, b = (int(hexv[i : i + 2], 16) / 255 for i in (1, 3, 5))

    def lin(v: float) -> float:
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ── the mark ──────────────────────────────────────────────────────────────
#
# A check, a horizon, and the check's reflection fading below it: the code
# looking at itself. On a 64-unit tile, corner radius 15. The check is the
# only full-strength element; the reflection never exceeds 24% opacity, so
# at favicon sizes it falls away and a plain check is what remains.

CHECK = [(17.5, 28.5), (27, 38), (46.5, 17)]
HORIZON_Y = 42.5
STROKE = 7.2


def _mirror(points):
    return [(x, 2 * HORIZON_Y - y) for x, y in points]


def _path(points) -> str:
    return "M" + " L".join(f"{x:g} {y:g}" for x, y in points)


def mark_svg(*, tile: str | None, check_from: str, check_to: str, horizon: str,
             reflection: bool = True, size: int = 64) -> str:
    tile_el = f'<rect width="64" height="64" rx="15" fill="{tile}"/>' if tile else ""
    refl = ""
    if reflection:
        refl = (
            f'<path d="{_path(_mirror(CHECK))}" fill="none" stroke="url(#g)" stroke-width="{STROKE}" '
            f'stroke-linecap="round" stroke-linejoin="round" mask="url(#fade)" opacity="0.24"/>'
            f'<line x1="13" y1="{HORIZON_Y}" x2="51" y2="{HORIZON_Y}" stroke="{horizon}" '
            f'stroke-width="1.6" stroke-linecap="round" opacity="0.55"/>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}" role="img" aria-label="selfcheck">
  <defs>
    <linearGradient id="g" x1="14" y1="40" x2="50" y2="12" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{check_from}"/><stop offset="1" stop-color="{check_to}"/>
    </linearGradient>
    <linearGradient id="f" x1="0" y1="{HORIZON_Y}" x2="0" y2="64" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fff"/><stop offset="0.6" stop-color="#fff" stop-opacity="0"/>
    </linearGradient>
    <mask id="fade"><rect x="0" y="{HORIZON_Y}" width="64" height="{64 - HORIZON_Y}" fill="url(#f)"/></mask>
    <clipPath id="tile"><rect width="64" height="64" rx="15"/></clipPath>
  </defs>
  {tile_el}
  <g clip-path="url(#tile)">
    {refl}
    <path d="{_path(CHECK)}" fill="none" stroke="url(#g)" stroke-width="{STROKE}" stroke-linecap="round" stroke-linejoin="round"/>
  </g>
</svg>
"""


def lockup_svg(*, mark: str, text: str, accent: str, bg: str | None) -> str:
    inner = mark.split("\n", 1)[1].rsplit("</svg>", 1)[0]
    bg_el = f'<rect width="420" height="120" rx="20" fill="{bg}"/>' if bg else ""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 420 120" width="420" height="120" role="img" aria-label="selfcheck">
  {bg_el}
  <svg x="24" y="24" width="72" height="72" viewBox="0 0 64 64">{inner}</svg>
  <text x="114" y="75" font-family="Inter, 'Inter Variable', system-ui, sans-serif" font-size="46" font-weight="650" letter-spacing="-1.4" fill="{text}">self<tspan fill="{accent}">check</tspan></text>
</svg>
"""


def main() -> None:
    LOGO.mkdir(exist_ok=True)
    pal = scales()
    emerald, graphite = pal["emerald"], pal["graphite"]
    ink, chalk = graphite["950"]["hex"], graphite["50"]["hex"]

    variants = {
        # The default: an emerald check on the graphite tile. Also the app icon.
        "mark.svg": mark_svg(tile=ink, check_from=emerald["400"]["hex"], check_to=emerald["200"]["hex"],
                             horizon=graphite["500"]["hex"]),
        # For light pages that want a tile.
        "mark-light.svg": mark_svg(tile=chalk, check_from=emerald["600"]["hex"], check_to=emerald["400"]["hex"],
                                   horizon=graphite["300"]["hex"]),
        # No tile, for dark and light surfaces.
        "mark-bare-dark.svg": mark_svg(tile=None, check_from=emerald["400"]["hex"], check_to=emerald["200"]["hex"],
                                       horizon=graphite["500"]["hex"]),
        "mark-bare-light.svg": mark_svg(tile=None, check_from=emerald["600"]["hex"], check_to=emerald["400"]["hex"],
                                        horizon=graphite["300"]["hex"]),
        # 16-32 px: no reflection, which would only be noise at that size.
        "favicon.svg": mark_svg(tile=ink, check_from=emerald["400"]["hex"], check_to=emerald["200"]["hex"],
                                horizon=graphite["500"]["hex"], reflection=False, size=32),
    }
    for name, svg in variants.items():
        (LOGO / name).write_text(svg)
    (LOGO / "lockup-dark.svg").write_text(
        lockup_svg(mark=variants["mark.svg"], text=graphite["50"]["hex"], accent=emerald["400"]["hex"], bg=ink))
    (LOGO / "lockup-light.svg").write_text(
        lockup_svg(mark=variants["mark-light.svg"], text=graphite["900"]["hex"], accent=emerald["600"]["hex"], bg=chalk))

    # ── tokens ──
    (HERE / "tokens.json").write_text(json.dumps(
        {name: {step: v["hex"] for step, v in fam.items()} for name, fam in pal.items()}, indent=2) + "\n")
    css = ["/* Generated by branding/build.py. Do not edit by hand. */", ":root {"]
    for name, fam in pal.items():
        for step, v in fam.items():
            css.append(f"  --{name}-{step}: {v['hex']};  /* {v['oklch']} */")
    css.append("}")
    (HERE / "tokens.css").write_text("\n".join(css) + "\n")

    # ── palette sheet ──
    sw, gap, label_w = 56, 6, 110
    rows = []
    for r, (name, fam) in enumerate(pal.items()):
        y = 40 + r * (sw + 28)
        rows.append(f'<text x="0" y="{y + sw / 2 + 5}" class="n">{name}</text>')
        for i, step in enumerate(STEPS):
            x = label_w + i * (sw + gap)
            hexv = fam[str(step)]["hex"]
            txt = "#fff" if luminance(hexv) < 0.3 else "#11181c"
            rows.append(f'<rect x="{x}" y="{y}" width="{sw}" height="{sw}" rx="8" fill="{hexv}"/>'
                        f'<text x="{x + sw / 2}" y="{y + sw / 2 + 4}" class="s" fill="{txt}">{step}</text>'
                        f'<text x="{x + sw / 2}" y="{y + sw + 14}" class="h">{hexv}</text>')
    width = label_w + len(STEPS) * (sw + gap)
    height = 40 + len(pal) * (sw + 28)
    (HERE / "palette.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="-20 0 {width + 40} {height + 10}" width="{width + 40}" '
        f'height="{height + 10}"><style>.n{{font:600 15px Inter,system-ui,sans-serif;fill:#5a6273}}'
        f'.s{{font:600 11px Inter,system-ui,sans-serif;text-anchor:middle}}'
        f'.h{{font:10px "JetBrains Mono",monospace;fill:#8b93a3;text-anchor:middle}}</style>'
        f'<rect x="-20" width="{width + 40}" height="{height + 10}" fill="#fcfdfd"/>'
        f'<text x="0" y="22" class="n" style="fill:#171a21">selfcheck palette — OKLCH, gamut-mapped to sRGB</text>'
        + "".join(rows) + "</svg>\n")

    # ── contrast table: the pairings the UI actually uses ──
    pairs = [
        ("Body text on the dark surface", graphite["50"]["hex"], graphite["900"]["hex"], 7.0),
        ("Muted text on the dark surface", graphite["300"]["hex"], graphite["900"]["hex"], 4.5),
        ("Body text on the light surface", graphite["900"]["hex"], graphite["50"]["hex"], 7.0),
        ("Muted text on the light surface", graphite["700"]["hex"], graphite["50"]["hex"], 4.5),
        ("Link / accent on dark", emerald["300"]["hex"], graphite["900"]["hex"], 4.5),
        ("Link / accent on light", emerald["700"]["hex"], graphite["50"]["hex"], 4.5),
        ("Text on the primary button", graphite["950"]["hex"], emerald["300"]["hex"], 4.5),
        ("Blocker on dark", coral := pal["coral"]["300"]["hex"], graphite["900"]["hex"], 4.5),
        ("Blocker on light", pal["coral"]["700"]["hex"], graphite["50"]["hex"], 4.5),
        ("Pass on dark", emerald["300"]["hex"], graphite["900"]["hex"], 4.5),
        ("Pass on light", emerald["700"]["hex"], graphite["50"]["hex"], 4.5),
    ]
    del coral
    table = ["| Pairing | Foreground | Background | Ratio | Needs | |", "| --- | --- | --- | --- | --- | --- |"]
    failures = []
    for label, fg, bg, need in pairs:
        ratio = contrast(fg, bg)
        ok = ratio >= need
        if not ok:
            failures.append(label)
        table.append(f"| {label} | `{fg}` | `{bg}` | {ratio:.2f} | {need} | {'✓' if ok else '✗'} |")
    (HERE / "contrast.md").write_text(
        "# Contrast\n\nGenerated by `build.py`: the text pairings the UI uses, checked against "
        "WCAG 2.2 (7:1 for body text we want comfortable, 4.5:1 for the rest).\n\n" + "\n".join(table) + "\n")
    if failures:
        raise SystemExit(f"contrast below target: {', '.join(failures)}")
    print(f"wrote {len(variants) + 2} logo files, palette.svg, tokens.json, tokens.css, contrast.md")


if __name__ == "__main__":
    main()
