"""Read-only file tools for the API engines.

With a CLI engine the agent brings its own tools and selfcheck restricts them.
With an API engine selfcheck runs the tool loop itself, so it gets to define
exactly three tools, none of which can write, and every path they touch is
resolved and checked to stay inside the checkout — symlinks included.
"""

from __future__ import annotations

import asyncio
import fnmatch
import os
import re
from pathlib import Path
from typing import Any

MAX_READ_LINES = 400
MAX_FILE_BYTES = 1_000_000
MAX_LIST = 300
MAX_MATCHES = 120
MAX_SCANNED = 20_000
SKIP_DIRS = {".git"}

TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Read a text file from the read-only checkout of the PR's head commit. "
            f"Returns up to {MAX_READ_LINES} lines, each prefixed with its line number. "
            "Use start_line to page through a longer file."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Repo-relative path"},
                "start_line": {"type": "integer", "description": "1-based; default 1"},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search",
        "description": (
            "Search file contents in the checkout with a regular expression (Python "
            "syntax). Use it to find every caller of a function, where a symbol is "
            f"defined, or whether a test exists. Returns at most {MAX_MATCHES} matches "
            "as path:line: text."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string", "description": "Directory to limit the search to"},
                "glob": {"type": "string", "description": "File name filter, e.g. *.py"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_files",
        "description": (
            "List files in the checkout under a directory, optionally filtered by a "
            f"glob such as **/*_test.go. Returns at most {MAX_LIST} paths."
        ),
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory; default the repo root"},
                "glob": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
]


class OutsideCheckout(ValueError):
    pass


class RepoTools:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def _resolve(self, rel: str) -> Path:
        candidate = (self.root / (rel or ".").lstrip("/")).resolve()
        if not candidate.is_relative_to(self.root):
            raise OutsideCheckout(f"{rel!r} is outside the checkout")
        return candidate

    def _rel(self, p: Path) -> str:
        return str(p.relative_to(self.root))

    def _walk(self, base: Path):
        scanned = 0
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            for name in sorted(filenames):
                scanned += 1
                if scanned > MAX_SCANNED:
                    return
                p = Path(dirpath) / name
                # A symlink pointing out of the checkout is skipped, not followed.
                if p.resolve().is_relative_to(self.root):
                    yield p

    def read_file(self, path: str, start_line: int = 1) -> str:
        p = self._resolve(path)
        if not p.is_file():
            return f"error: {path} is not a file"
        if p.stat().st_size > MAX_FILE_BYTES:
            return f"error: {path} is larger than {MAX_FILE_BYTES} bytes"
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line or 1))
        chunk = lines[start - 1 : start - 1 + MAX_READ_LINES]
        out = "\n".join(f"{start + i:>6}  {line}" for i, line in enumerate(chunk))
        end = start + len(chunk) - 1
        if end < len(lines):
            out += f"\n… {len(lines) - end} more lines; continue with start_line={end + 1}"
        return out or "(empty file)"

    def search(self, pattern: str, path: str = "", glob: str = "") -> str:
        try:
            rx = re.compile(pattern)
        except re.error as exc:
            return f"error: invalid regex: {exc}"
        base = self._resolve(path)
        hits: list[str] = []
        for p in self._walk(base):
            if glob and not fnmatch.fnmatch(p.name, glob):
                continue
            try:
                if p.stat().st_size > MAX_FILE_BYTES:
                    continue
                data = p.read_bytes()
            except OSError:
                continue
            if b"\0" in data[:8192]:
                continue
            for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{self._rel(p)}:{n}: {line.strip()[:200]}")
                    if len(hits) >= MAX_MATCHES:
                        return "\n".join(hits) + f"\n… stopped at {MAX_MATCHES} matches"
        return "\n".join(hits) or "no matches"

    def list_files(self, path: str = "", glob: str = "") -> str:
        base = self._resolve(path)
        out: list[str] = []
        for p in self._walk(base):
            rel = self._rel(p)
            if glob and not (fnmatch.fnmatch(rel, glob) or fnmatch.fnmatch(p.name, glob)):
                continue
            out.append(rel)
            if len(out) >= MAX_LIST:
                return "\n".join(out) + f"\n… stopped at {MAX_LIST} paths"
        return "\n".join(out) or "no files"

    async def call(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        """Run a tool; returns (output, is_error)."""
        fn = {"read_file": self.read_file, "search": self.search,
              "list_files": self.list_files}.get(name)
        if fn is None:
            return f"error: unknown tool {name!r}", True
        try:
            allowed = {k: v for k, v in (args or {}).items()
                       if k in ("path", "start_line", "pattern", "glob")}
            out = await asyncio.to_thread(fn, **allowed)
            return out, out.startswith("error:")
        except (OutsideCheckout, TypeError, ValueError, OSError) as exc:
            return f"error: {exc}", True


def summarise_call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    detail = args.get("path") or ""
    if name == "search":
        detail = f"{args.get('pattern', '')}  {args.get('path', '') or ''}".strip()
    elif name == "list_files":
        detail = args.get("glob") or args.get("path") or "."
    return {"tool": name, "detail": str(detail)[:200]}


TURN_BUDGET_SPENT = (
    "You have used your file-reading budget for this review. Do not call any more "
    "tools: write the review now, ending with the JSON block the output contract asks for."
)
