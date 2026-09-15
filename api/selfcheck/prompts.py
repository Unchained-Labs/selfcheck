"""Prompt construction for a review run."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_APPEND = """\
You are the review engine inside selfcheck, a local read-only review workbench.

Hard rules:
- You are reviewing, not fixing. Never modify any file. You have no write tools.
- Never contact the forge (GitHub/GitLab). Never suggest posting the review.
- The checkout you are given is read-only and detached. Treat it as evidence.
- Every claim you make must be checkable from the diff or the checkout. If you
  are guessing, say so in the note body and lower its confidence.

Review quality bar:
- Prefer a small number of findings that are demonstrably real over broad
  speculation. A reviewer who cries wolf gets ignored.
- Anchor each finding to the narrowest line range that shows the problem.
- Judge the change against the code around it: match existing patterns, naming,
  error handling and test conventions rather than importing your own taste.
- Say what breaks and under what input/state. "This could be a problem" is not
  a finding; "if `items` is empty, line 42 raises IndexError" is.
"""

OUTPUT_CONTRACT = """\
## Output contract

End your reply with exactly one fenced ```json block and nothing after it. The
block must parse as this object:

{
  "summary": "markdown; 3-8 sentences: what the change does, then how sound it looks",
  "verdict": "looks_good" | "comments" | "needs_work",
  "confidence": "high" | "medium" | "low",
  "risk_areas": ["short phrases naming the parts most likely to bite"],
  "test_gaps": ["behaviour that changed but is not covered by a test"],
  "questions": ["things only the author can answer"],
  "checklist": [
    {"item": "Errors handled", "state": "pass"|"fail"|"na"|"unknown", "note": "one line"}
  ],
  "notes": [
    {
      "file": "path/relative/to/repo/root",
      "line_start": 42,
      "line_end": 45,
      "side": "new" | "old",
      "severity": "blocker" | "major" | "minor" | "nit" | "question" | "praise",
      "category": "correctness" | "security" | "performance" | "tests"
                | "style" | "docs" | "design" | "api",
      "title": "one line, imperative or declarative",
      "body": "markdown; what is wrong, the concrete failure, why it matters",
      "suggestion": "optional replacement code, no fences",
      "confidence": "high" | "medium" | "low"
    }
  ]
}

Line numbers: use the number printed in the diff gutter. Those are real file
line numbers on the `new` side. For a note about a deleted line, set
"side": "old" and use the old file's numbering. For a note that is not about a
specific place, set "file" to "" and omit the line fields.

Severity means:
- blocker  : merging this ships a bug, a security hole, or data loss.
- major    : wrong in a real scenario, or a design choice that will hurt soon.
- minor    : genuine but bounded; the author may reasonably disagree.
- nit      : cosmetic. Use sparingly; zero nits is a fine outcome.
- question : you cannot tell whether it is correct without the author's intent.
- praise   : worth calling out. At most one or two.
"""


def _fmt_commits(commits: list[dict[str, Any]], limit: int = 30) -> str:
    if not commits:
        return "(commit list unavailable)"
    rows = []
    for c in commits[:limit]:
        subject = (c.get("message") or "").splitlines()[0] if c.get("message") else ""
        rows.append(f"- {(c.get('sha') or '')[:8]} {subject}  — {c.get('author', '')}")
    if len(commits) > limit:
        rows.append(f"- … and {len(commits) - limit} more")
    return "\n".join(rows)


def _fmt_prev_notes(notes: list[dict[str, Any]], limit: int = 60) -> str:
    if not notes:
        return ""
    rows = []
    for n in notes[:limit]:
        loc = n.get("file_path") or "(general)"
        if n.get("line_start"):
            loc += f":{n['line_start']}"
        rows.append(
            f"- [{n.get('severity')}/{n.get('status')}] {loc} — {n.get('title')}\n"
            f"    {(n.get('body') or '').strip().splitlines()[0][:200] if n.get('body') else ''}"
        )
    return "\n".join(rows)


def build_review_prompt(
    *,
    meta: dict[str, Any],
    diff_text: str,
    diff_truncated: bool,
    worktree: str | None,
    file_list: list[dict[str, Any]],
    previous: dict[str, Any] | None = None,
    changed_since: list[str] | None = None,
    guidance: str = "",
) -> str:
    parts: list[str] = []

    parts.append(
        f"# Review request\n\n"
        f"**{meta.get('provider', '')} {'PR' if meta.get('provider') == 'github' else 'MR'} "
        f"#{meta.get('number')}** in `{meta.get('namespace')}/{meta.get('project')}` "
        f"on `{meta.get('host')}`\n\n"
        f"- Title: {meta.get('title') or '(none)'}\n"
        f"- Author: {meta.get('author') or '(unknown)'}\n"
        f"- State: {meta.get('state')}{' (draft)' if meta.get('draft') else ''}\n"
        f"- Target branch: `{meta.get('base_ref')}`  ←  source: `{meta.get('head_ref')}`\n"
        f"- Head commit: `{(meta.get('head_sha') or '')[:12]}`\n"
        f"- Size: {meta.get('changed_files')} files, +{meta.get('additions')} / -{meta.get('deletions')}\n"
    )

    desc = (meta.get("description") or "").strip()
    parts.append(
        "## Author's description\n\n"
        + (desc[:8000] if desc else "_(the author left the description empty — "
           "note that if the change is non-trivial)_")
    )

    parts.append("## Commits\n\n" + _fmt_commits(meta.get("commits") or []))

    if file_list:
        rows = "\n".join(
            f"- `{f['path']}` [{f['status']}] +{f['additions']} -{f['deletions']}"
            for f in file_list[:400]
        )
        parts.append(f"## Files changed ({len(file_list)})\n\n{rows}")

    if worktree:
        parts.append(
            "## Repository checkout\n\n"
            f"A read-only checkout of the head commit is your working directory:\n\n"
            f"`{worktree}`\n\n"
            "Use Read, Grep and Glob there whenever the diff alone is not enough — "
            "to see a whole function rather than a hunk, to find every caller of a "
            "changed signature, to check whether a test already covers the new path, "
            "or to confirm the surrounding code's conventions. Paths in the diff are "
            "relative to this directory. Files are chmod'ed read-only; that is "
            "deliberate, do not try to work around it."
        )
    else:
        parts.append(
            "## Repository checkout\n\n"
            "_Not available for this run — you are working from the diff alone. "
            "Be correspondingly careful about claims that depend on code you "
            "cannot see, and lower confidence on them._"
        )

    if previous and previous.get("notes"):
        parts.append(
            "## Your previous review of this PR\n\n"
            f"It was written against `{(previous.get('head_sha') or '')[:12]}`; the head is now "
            f"`{(meta.get('head_sha') or '')[:12]}`.\n\n"
            f"Previous summary: {(previous.get('summary') or '')[:1500]}\n\n"
            "Previous findings:\n"
            + _fmt_prev_notes(previous["notes"])
            + "\n\nRe-issue any finding that is still valid, with the same title so it can be "
            "matched up, and updated line numbers. Drop the ones the new commits fixed, and "
            "say so in the summary. Findings the author marked resolved or dismissed should "
            "only come back if they are demonstrably still broken."
        )

    if changed_since:
        rows = "\n".join(f"- `{p}`" for p in changed_since[:200])
        parts.append(
            "## Changed since your last review\n\n"
            f"{rows}\n\nSpend your effort here first, but keep the whole change in view."
        )

    if guidance.strip():
        parts.append(f"## Reviewer's instructions\n\n{guidance.strip()}")

    parts.append(
        "## Diff\n\n"
        "The left gutter is the line number in the new file. `+` added, `-` removed, "
        "blank marker = context.\n\n```diff\n" + diff_text + "\n```"
        + ("\n\n_This diff was truncated. Read the remaining files from the checkout._"
           if diff_truncated else "")
    )

    parts.append(OUTPUT_CONTRACT)
    return "\n\n".join(parts)


def extract_json_block(text: str) -> dict[str, Any] | None:
    """Pull the trailing ```json block out of Claude's reply.

    Falls back to the last balanced `{...}` span, because a model occasionally
    drops the fence when the payload is long.
    """
    fence = "```json"
    idx = text.rfind(fence)
    if idx != -1:
        rest = text[idx + len(fence) :]
        end = rest.find("```")
        candidate = rest[:end] if end != -1 else rest
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    depth = 0
    start = -1
    best: dict[str, Any] | None = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict) and "notes" in parsed:
                            best = parsed
                    except json.JSONDecodeError:
                        pass
    return best
