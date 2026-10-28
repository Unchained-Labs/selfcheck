#!/usr/bin/env python3
"""Bump selfcheck's version everywhere it is written, and date the changelog.

    python3 scripts/release/bump.py patch|minor|major   # prints the new version
    python3 scripts/release/bump.py --check             # versions agree? exit 0/1

The version lives in three files that must agree: the API package, its
pyproject, and the web app's package.json. CHANGELOG.md's [Unreleased]
section becomes the new version's section, dated today, and a fresh empty
[Unreleased] goes on top. Standard library only, so CI needs nothing installed.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INIT = ROOT / "api" / "selfcheck" / "__init__.py"
PYPROJECT = ROOT / "api" / "pyproject.toml"
PACKAGE = ROOT / "web" / "package.json"
CHANGELOG = ROOT / "CHANGELOG.md"
REPO = "https://github.com/Unchained-Labs/selfcheck"

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def current() -> dict[str, str]:
    return {
        "init": re.search(r'^__version__ = "([^"]+)"', INIT.read_text(), re.M).group(1),
        "pyproject": re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M).group(1),
        "package": json.loads(PACKAGE.read_text())["version"],
    }


def bumped(version: str, part: str) -> str:
    major, minor, patch = map(int, SEMVER.match(version).groups())
    if part == "major":
        return f"{major + 1}.0.0"
    if part == "minor":
        return f"{major}.{minor + 1}.0"
    if part == "patch":
        return f"{major}.{minor}.{patch + 1}"
    raise SystemExit(f"unknown part {part!r}; use patch, minor or major")


def write_version(new: str) -> None:
    INIT.write_text(re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{new}"', INIT.read_text(), flags=re.M))
    PYPROJECT.write_text(re.sub(r'^version = "[^"]+"', f'version = "{new}"', PYPROJECT.read_text(), count=1, flags=re.M))
    # Edit the line rather than re-dumping the JSON, so formatting is untouched.
    PACKAGE.write_text(re.sub(r'("version":\s*)"[^"]+"', rf'\g<1>"{new}"', PACKAGE.read_text(), count=1))


def date_changelog(old: str, new: str) -> None:
    text = CHANGELOG.read_text()
    today = dt.date.today().isoformat()
    if "## [Unreleased]" not in text:
        raise SystemExit("CHANGELOG.md has no [Unreleased] section")
    text = text.replace("## [Unreleased]", f"## [Unreleased]\n\n## [{new}] - {today}", 1)
    link = re.compile(r"^\[Unreleased\]: .*$", re.M)
    links = f"[Unreleased]: {REPO}/compare/v{new}...HEAD\n[{new}]: {REPO}/compare/v{old}...v{new}"
    text = link.sub(links, text, count=1) if link.search(text) else text.rstrip() + "\n\n" + links + "\n"
    CHANGELOG.write_text(text)


def main(argv: list[str]) -> int:
    versions = current()
    if argv[1:] == ["--check"]:
        if len(set(versions.values())) != 1:
            print(f"versions disagree: {versions}", file=sys.stderr)
            return 1
        print(versions["init"])
        return 0
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    if len(set(versions.values())) != 1:
        print(f"versions disagree, fix them first: {versions}", file=sys.stderr)
        return 1
    old = versions["init"]
    new = bumped(old, argv[1])
    write_version(new)
    date_changelog(old, new)
    print(new)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
