#!/usr/bin/env python3
"""Decide how much a merged pull request bumps the version.

    python3 scripts/release/plan.py --title "feat: thing" --labels "release:minor,docs"

Every merged pull request releases. What it releases:

1. A label wins: `release:major`, `release:minor` or `release:patch`. More than
   one is an error, so a PR cannot be ambiguous about what it ships.
2. Otherwise the title decides, conventional-commit style: a `!` before the
   colon (`feat!:`) or "BREAKING" anywhere means major, a `feat` prefix means
   minor.
3. Anything else is a patch.

Prints `major`, `minor` or `patch`, and the reason on stderr.
"""

from __future__ import annotations

import argparse
import re
import sys

PARTS = ("major", "minor", "patch")
_BREAKING = re.compile(r"^\s*\w+(\([^)]*\))?!:|\bBREAKING\b")
_FEATURE = re.compile(r"^\s*feat(\([^)]*\))?:", re.IGNORECASE)


def plan(title: str, labels: list[str]) -> tuple[str, str]:
    chosen = [lbl.split(":", 1)[1] for lbl in labels if lbl.strip() in {f"release:{p}" for p in PARTS}]
    if len(chosen) > 1:
        raise ValueError(f"more than one release label: {', '.join('release:' + c for c in chosen)}")
    if chosen:
        return chosen[0], f"label release:{chosen[0]}"
    if _BREAKING.search(title):
        return "major", "breaking change in the title"
    if _FEATURE.search(title):
        return "minor", "feat in the title"
    return "patch", "every merged pull request releases at least a patch"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="")
    ap.add_argument("--labels", default="", help="comma- or newline-separated")
    args = ap.parse_args()
    labels = [x.strip() for x in re.split(r"[,\n]", args.labels) if x.strip()]
    try:
        part, why = plan(args.title, labels)
    except ValueError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1
    print(part)
    print(f"release: {part} ({why})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
