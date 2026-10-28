"""The release scripts decide what ships; they get the same scrutiny as the app."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "release" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("title", "labels", "expected"),
    [
        ("Fix the sidebar", [], "patch"),
        ("docs: typo", [], "patch"),
        ("feat: wakeups", [], "minor"),
        ("feat(ui): tabs", [], "minor"),
        ("feat!: drop the old API", [], "major"),
        ("refactor(api)!: rename routes", [], "major"),
        ("Remove v1 endpoints — BREAKING", [], "major"),
        ("feat: big thing", ["release:patch"], "patch"),
        ("Fix", ["release:major", "bug"], "major"),
        ("Anything", ["release:minor"], "minor"),
    ],
)
def test_every_merge_releases_and_labels_win(title, labels, expected):
    assert _load("plan").plan(title, labels)[0] == expected


def test_two_release_labels_are_refused():
    with pytest.raises(ValueError):
        _load("plan").plan("x", ["release:minor", "release:patch"])


def test_bump_updates_every_version_and_dates_the_changelog(tmp_path, monkeypatch):
    bump = _load("bump")
    for rel in ("api/selfcheck/__init__.py", "api/pyproject.toml", "web/package.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n### Added\n\n- A thing.\n\n## [0.1.0] - 2026-01-01\n\n"
        "[Unreleased]: https://example/compare/v0.1.0...HEAD\n"
    )
    for attr, rel in (("INIT", "api/selfcheck/__init__.py"), ("PYPROJECT", "api/pyproject.toml"),
                      ("PACKAGE", "web/package.json"), ("CHANGELOG", "CHANGELOG.md")):
        monkeypatch.setattr(bump, attr, tmp_path / rel)

    old = bump.current()["init"]
    assert bump.main(["bump", "minor"]) == 0
    major, minor, _ = map(int, old.split("."))
    new = f"{major}.{minor + 1}.0"
    assert set(bump.current().values()) == {new}
    assert json.loads((tmp_path / "web/package.json").read_text())["version"] == new

    log = (tmp_path / "CHANGELOG.md").read_text()
    assert log.index("## [Unreleased]") < log.index(f"## [{new}] - ") < log.index("- A thing.")
    assert f"compare/v{new}...HEAD" in log and f"compare/v{old}...v{new}" in log


def test_repository_versions_agree():
    assert _load("bump").main(["bump", "--check"]) == 0
