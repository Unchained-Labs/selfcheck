"""Render a review as markdown you can paste anywhere yourself.

selfcheck deliberately stops here: it produces text for a human to copy. It has
no code path that sends anything back to a forge.
"""

from __future__ import annotations

from typing import Any

from . import service

SEVERITY_LABEL = {
    "blocker": "Blocker",
    "major": "Major",
    "minor": "Minor",
    "nit": "Nit",
    "question": "Question",
    "praise": "Praise",
}
VERDICT_LABEL = {
    "looks_good": "Looks good",
    "comments": "Comments",
    "needs_work": "Needs work",
}


def review_markdown(review_id: str, include_resolved: bool = False) -> str:
    review = service.get_review(review_id)
    run = service.latest_run(review_id)
    notes = service.list_notes(review_id)
    if not include_resolved:
        notes = [n for n in notes if n["status"] == "open"]

    kind = "PR" if review["provider"] == "github" else "MR"
    out: list[str] = [
        f"# Review notes — {review['namespace']}/{review['project']} {kind} #{review['number']}",
        "",
        f"**{review['title'] or '(untitled)'}** by {review['author'] or 'unknown'}  ",
        f"`{review['head_ref']}` → `{review['base_ref']}` at `{(review['head_sha'] or '')[:12]}`  ",
        f"<{review['url']}>",
        "",
    ]

    if run and run["status"] == "done":
        out += [
            f"**Verdict:** {VERDICT_LABEL.get(run['verdict'], run['verdict'] or '—')}"
            + (f" (confidence: {run['confidence']})" if run["confidence"] else ""),
            "",
            run["summary"] or "",
            "",
        ]
        if run["risk_areas"]:
            out += ["**Riskiest parts:**", ""]
            out += [f"- {r}" for r in run["risk_areas"]] + [""]
        if run["test_gaps"]:
            out += ["**Test gaps:**", ""]
            out += [f"- {t}" for t in run["test_gaps"]] + [""]
        if run["questions"]:
            out += ["**Questions for the author:**", ""]
            out += [f"- {q}" for q in run["questions"]] + [""]

    general = [n for n in notes if not n["file_path"]]
    by_file: dict[str, list[dict[str, Any]]] = {}
    for n in notes:
        if n["file_path"]:
            by_file.setdefault(n["file_path"], []).append(n)

    order = {s: i for i, s in enumerate(service.SEVERITY_ORDER)}

    if general:
        out += ["## General", ""]
        for n in sorted(general, key=lambda x: order.get(x["severity"], 99)):
            out += _note_md(n, "")

    for path in sorted(by_file):
        out += [f"## `{path}`", ""]
        for n in sorted(
            by_file[path], key=lambda x: (x["line_start"] or 0, order.get(x["severity"], 99))
        ):
            out += _note_md(n, path)

    if not notes:
        out += ["_No open notes._", ""]

    return "\n".join(out).rstrip() + "\n"


def _note_md(note: dict[str, Any], path: str) -> list[str]:
    loc = ""
    if path and note["line_start"]:
        loc = (
            f"L{note['line_start']}"
            if note["line_end"] in (None, note["line_start"])
            else f"L{note['line_start']}–L{note['line_end']}"
        )
    head = f"### {SEVERITY_LABEL.get(note['severity'], note['severity'])}"
    if loc:
        head += f" · {loc}"
    head += f" · {note['category']}"
    if note["stale"]:
        head += " · _(written against an older commit)_"
    lines = [head, "", f"**{note['title']}**", "", note["body"] or "", ""]
    if note["suggestion"]:
        lines += ["```", note["suggestion"], "```", ""]
    return lines
