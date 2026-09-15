"""Unified-diff parser.

Produces a structure the web UI can render directly as either a unified or a
split view, without re-parsing text in the browser.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

_HUNK_HEADER = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? \+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@(?P<section>.*)$"
)
_DIFF_GIT = re.compile(r"^diff --git (?:a/)?(?P<a>.+?) (?:b/)?(?P<b>.+)$")


@dataclass(slots=True)
class DiffLine:
    kind: str           # context | add | del | meta
    content: str
    old_line: int | None = None
    new_line: int | None = None
    no_newline: bool = False


@dataclass(slots=True)
class Hunk:
    header: str
    section: str
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass(slots=True)
class DiffFile:
    old_path: str
    new_path: str
    status: str = "modified"    # added | deleted | renamed | modified | binary
    is_binary: bool = False
    additions: int = 0
    deletions: int = 0
    old_mode: str = ""
    new_mode: str = ""
    hunks: list[Hunk] = field(default_factory=list)
    truncated: bool = False

    @property
    def path(self) -> str:
        return self.new_path if self.new_path != "/dev/null" else self.old_path


def _strip_prefix(p: str) -> str:
    if p in ("/dev/null", ""):
        return p
    for pre in ("a/", "b/", "i/", "w/", "c/", "o/"):
        if p.startswith(pre):
            return p[len(pre) :]
    return p


def parse_unified_diff(text: str, max_lines_per_file: int = 8000) -> list[DiffFile]:
    files: list[DiffFile] = []
    current: DiffFile | None = None
    hunk: Hunk | None = None
    old_no = new_no = 0

    for raw in text.splitlines():
        m = _DIFF_GIT.match(raw)
        if m:
            current = DiffFile(
                old_path=_strip_prefix(m.group("a")),
                new_path=_strip_prefix(m.group("b")),
            )
            files.append(current)
            hunk = None
            continue

        if current is None:
            continue

        if raw.startswith("new file mode "):
            current.status = "added"
            current.new_mode = raw[len("new file mode ") :].strip()
            continue
        if raw.startswith("deleted file mode "):
            current.status = "deleted"
            current.old_mode = raw[len("deleted file mode ") :].strip()
            continue
        if raw.startswith("rename from "):
            current.status = "renamed"
            current.old_path = raw[len("rename from ") :].strip()
            continue
        if raw.startswith("rename to "):
            current.status = "renamed"
            current.new_path = raw[len("rename to ") :].strip()
            continue
        if raw.startswith("old mode "):
            current.old_mode = raw[len("old mode ") :].strip()
            continue
        if raw.startswith("new mode "):
            current.new_mode = raw[len("new mode ") :].strip()
            continue
        if raw.startswith("Binary files") or raw.startswith("GIT binary patch"):
            current.is_binary = True
            if current.status == "modified":
                current.status = "binary"
            continue
        if raw.startswith("--- "):
            p = _strip_prefix(raw[4:].strip())
            if p == "/dev/null":
                current.status = "added"
            else:
                current.old_path = p
            continue
        if raw.startswith("+++ "):
            p = _strip_prefix(raw[4:].strip())
            if p == "/dev/null":
                current.status = "deleted"
            else:
                current.new_path = p
            continue
        if raw.startswith("index ") or raw.startswith("similarity index "):
            continue

        hm = _HUNK_HEADER.match(raw)
        if hm:
            hunk = Hunk(
                header=raw,
                section=(hm.group("section") or "").strip(),
                old_start=int(hm.group("old_start")),
                old_count=int(hm.group("old_count") or 1),
                new_start=int(hm.group("new_start")),
                new_count=int(hm.group("new_count") or 1),
            )
            current.hunks.append(hunk)
            old_no = hunk.old_start
            new_no = hunk.new_start
            continue

        if hunk is None:
            continue

        if len(hunk.lines) >= max_lines_per_file:
            current.truncated = True
            continue

        if raw.startswith("\\"):  # "\ No newline at end of file"
            if hunk.lines:
                hunk.lines[-1].no_newline = True
            continue

        marker, content = (raw[:1], raw[1:]) if raw else (" ", "")
        if marker == "+":
            hunk.lines.append(DiffLine("add", content, None, new_no))
            new_no += 1
            current.additions += 1
        elif marker == "-":
            hunk.lines.append(DiffLine("del", content, old_no, None))
            old_no += 1
            current.deletions += 1
        elif marker == " ":
            hunk.lines.append(DiffLine("context", content, old_no, new_no))
            old_no += 1
            new_no += 1
        else:
            # Defensive: unexpected marker inside a hunk.
            hunk.lines.append(DiffLine("context", raw, old_no, new_no))
            old_no += 1
            new_no += 1

    for f in files:
        if f.old_path == "/dev/null":
            f.status = "added"
        elif f.new_path == "/dev/null":
            f.status = "deleted"

    return files


def to_payload(files: list[DiffFile]) -> dict[str, Any]:
    out_files = []
    for f in files:
        d = asdict(f)
        d["path"] = f.path
        out_files.append(d)
    return {
        "files": out_files,
        "stats": {
            "files": len(files),
            "additions": sum(f.additions for f in files),
            "deletions": sum(f.deletions for f in files),
        },
    }


def render_for_prompt(files: list[DiffFile], max_chars: int = 400_000) -> tuple[str, bool]:
    """Re-render the parsed diff with absolute line numbers in the gutter.

    Claude anchors notes to `new` line numbers, so handing it a diff where each
    line already carries its file line number removes the main source of
    off-by-N mis-anchoring.
    """
    out: list[str] = []
    size = 0
    truncated = False
    for f in files:
        head = f"\n=== {f.path} [{f.status}] +{f.additions} -{f.deletions} ==="
        if f.status == "renamed":
            head = f"\n=== {f.old_path} -> {f.new_path} [renamed] +{f.additions} -{f.deletions} ==="
        out.append(head)
        size += len(head)
        if f.is_binary:
            out.append("  (binary file, contents not shown)")
            continue
        for h in f.hunks:
            hh = f"  @@ {h.section or ''} (new lines {h.new_start}..{h.new_start + h.new_count - 1})"
            out.append(hh)
            size += len(hh)
            for ln in h.lines:
                if ln.kind == "add":
                    prefix = f"  {ln.new_line:>6} +"
                elif ln.kind == "del":
                    prefix = f"  {'':>6} -"
                else:
                    prefix = f"  {ln.new_line:>6}  "
                row = f"{prefix}{ln.content}"
                if size + len(row) > max_chars:
                    truncated = True
                    break
                out.append(row)
                size += len(row) + 1
            if truncated:
                break
        if truncated:
            out.append("\n[diff truncated — use Read/Grep in the worktree for the rest]")
            break
    return "\n".join(out), truncated
