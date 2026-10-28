"""Endpoints designed for Claude to drive selfcheck directly.

The web UI's "Review with Claude" button runs Claude for you. These endpoints
are the other direction: they let a Claude Code session you are already sitting
in pull a PR's full context, do the reading itself, and write notes back — which
is what the bundled `selfcheck` skill uses.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from .. import db, prompts, service, workspace
from ..config import get_settings
from ..diffparse import DiffFile, DiffLine, Hunk, render_for_prompt
from ..models import SummaryIn
from ..providers.base import PullMeta

router = APIRouter(prefix="/api", tags=["agent"])

GUIDE = """\
selfcheck — how an agent should drive it
========================================

selfcheck tracks pull requests and merge requests and stores review notes about
them locally. It is READ-ONLY with respect to GitHub and GitLab: there is no
endpoint, anywhere, that posts a comment, approves, merges or otherwise writes
to a forge. Do not tell the user you posted anything.

Base URL: http://127.0.0.1:{port}

Typical flow
------------
1.  POST /api/reviews                  {{"url": "<PR or MR link>"}}
    → {{"review": {{"id": "rev_...", ...}}}}
    Idempotent: re-posting a known URL returns the existing review.

2.  GET  /api/reviews/{{id}}/context?worktree=1
    → everything you need in one response:
        review        metadata (title, author, branches, head_sha, state)
        commits       commit list
        files         per-file status and +/- counts
        diff          the whole diff, re-rendered with real file line numbers
                      in the left gutter — anchor your notes to those numbers
        worktree      absolute path to a READ-ONLY checkout of the head commit,
                      or null if the repo cache is unavailable
        existing_notes  what is already recorded, so you do not duplicate it
        output_contract the exact shape POST /notes expects

3.  Read the code. Use Read/Grep/Glob inside `worktree` whenever the diff alone
    cannot settle a question: whole functions, every caller of a changed
    signature, whether a test already covers the new branch, local conventions.
    The checkout is chmod'ed read-only on purpose; do not try to write in it.

4.  POST /api/reviews/{{id}}/notes
    {{"origin": "claude", "notes": [{{
        "file": "src/thing.py", "line_start": 42, "line_end": 45, "side": "new",
        "severity": "major", "category": "correctness",
        "title": "...", "body": "markdown", "suggestion": "optional code",
        "confidence": "high"
    }}]}}

5.  POST /api/reviews/{{id}}/summary
    {{"summary": "...", "verdict": "looks_good|comments|needs_work",
      "confidence": "high", "risk_areas": [], "test_gaps": [], "questions": [],
      "checklist": [{{"item": "...", "state": "pass|fail|na|unknown", "note": "..."}}]}}
    This records a run so the UI shows your review as the current one.

Re-reviewing after the PR moved
-------------------------------
POST /api/reviews/{{id}}/sync  → {{"head_changed": true|false}}.
When the head moved, notes written against the old commit are flagged `stale`.
GET the context again; it will list what changed since your last review.
Resolve what is fixed with PATCH /api/notes/{{note_id}} {{"status": "resolved"}}.

Writing good notes
------------------
- severity: blocker (ships a bug/security hole/data loss), major (wrong in a
  real scenario), minor (genuine but bounded), nit (cosmetic — use sparingly),
  question (needs the author's intent), praise (at most one or two).
- Anchor to the narrowest line range that shows the problem.
- State the concrete failure: which input or state, and what goes wrong.
  "This could be a problem" is not a finding.
- A note you cannot support from the diff or the checkout should not be written.

Other endpoints
---------------
GET    /api/reviews                       list tracked reviews
GET    /api/reviews/{{id}}                 review + notes + runs
GET    /api/reviews/{{id}}/diff            structured diff (files → hunks → lines)
GET    /api/reviews/{{id}}/blob?path=&side= whole file at head or base
GET    /api/reviews/{{id}}/export.md       notes as markdown for the user to paste
PATCH  /api/notes/{{note_id}}              status / severity / text
DELETE /api/notes/{{note_id}}              remove a note
POST   /api/reviews/{{id}}/runs            run the built-in reviewer instead of doing it yourself
                                          {{"mode": "light|normal|thorough",
                                            "engine": "claude|codex|cursor|anthropic|openai"}}
GET    /api/wakeups                       repositories selfcheck checks on a schedule
GET    /api/status                        engines, tokens, cache health
"""


@router.get("/agent/guide", response_class=PlainTextResponse,
            summary="Plain-text instructions for an agent driving selfcheck")
def guide() -> PlainTextResponse:
    return PlainTextResponse(GUIDE.format(port=get_settings().port))


def _rehydrate(files: list[dict[str, Any]]) -> list[DiffFile]:
    out: list[DiffFile] = []
    for f in files:
        df = DiffFile(
            old_path=f["old_path"], new_path=f["new_path"], status=f["status"],
            is_binary=f["is_binary"], additions=f["additions"], deletions=f["deletions"],
        )
        for h in f["hunks"]:
            hunk = Hunk(
                header=h["header"], section=h["section"], old_start=h["old_start"],
                old_count=h["old_count"], new_start=h["new_start"], new_count=h["new_count"],
            )
            hunk.lines = [
                DiffLine(l["kind"], l["content"], l["old_line"], l["new_line"])
                for l in h["lines"]
            ]
            df.hunks.append(hunk)
        out.append(df)
    return out


@router.get("/reviews/{review_id}/context",
            summary="Everything an agent needs to review this PR, in one response")
async def context(
    review_id: str,
    worktree: bool = Query(True, description="Prepare a read-only checkout of the head commit"),
    refresh: bool = Query(False, description="Refetch metadata and diff from the forge first"),
    max_diff_chars: int = Query(400_000, ge=1000, le=2_000_000),
) -> dict[str, Any]:
    try:
        review = service.get_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if refresh or not review["head_sha"]:
        review = await service.sync_review(review_id)

    diff_payload = await service.fetch_diff_payload(review_id, refresh=refresh)
    files = diff_payload.get("files", [])
    diff_text, truncated = render_for_prompt(_rehydrate(files), max_chars=max_diff_chars)

    wt: str | None = None
    wt_error: str | None = None
    settings = get_settings()
    if worktree and settings.clone_enabled:
        try:
            ws = await workspace.prepare_workspace(
                service.review_ref(review),
                PullMeta(
                    base_ref=review["base_ref"], base_sha=review["base_sha"],
                    head_sha=review["head_sha"], clone_url=review["clone_url"],
                    head_clone_url=review["head_clone_url"],
                ),
                settings.token_for(review["host"]),
            )
            wt = str(ws.worktree)
        except Exception as exc:  # noqa: BLE001
            wt_error = f"{type(exc).__name__}: {exc}"

    last = service.latest_run(review_id)
    changed_since = None
    if last and last["head_sha"] and last["head_sha"] != review["head_sha"]:
        changed_since = await service._files_changed_between(
            service.review_ref(review), last["head_sha"], review["head_sha"], review["host"]
        )

    return {
        "review": {
            k: review[k]
            for k in (
                "id", "provider", "host", "namespace", "project", "number", "url", "title",
                "description", "author", "state", "draft", "base_ref", "head_ref",
                "base_sha", "head_sha", "changed_files", "additions", "deletions",
            )
        },
        "commits": review.get("commits") or [],
        "files": [
            {"path": f["path"], "status": f["status"], "additions": f["additions"],
             "deletions": f["deletions"], "is_binary": f["is_binary"]}
            for f in files
        ],
        "stats": diff_payload.get("stats", {}),
        "diff": diff_text,
        "diff_truncated": truncated,
        "worktree": wt,
        "worktree_error": wt_error,
        "worktree_note": (
            "Read-only checkout of the head commit. Use Read/Grep/Glob here for anything "
            "the diff alone cannot settle. Do not attempt to write."
            if wt else
            "No checkout available; review from the diff alone and lower confidence on "
            "claims that depend on code you cannot see."
        ),
        "existing_notes": service.list_notes(review_id),
        "previous_run": last,
        "changed_since_last_review": changed_since,
        "output_contract": prompts.OUTPUT_CONTRACT,
        "post_notes_to": f"/api/reviews/{review_id}/notes",
        "post_summary_to": f"/api/reviews/{review_id}/summary",
        "read_only": True,
    }


@router.post("/reviews/{review_id}/summary", status_code=201,
             summary="Record a review summary/verdict written by an agent")
def put_summary(review_id: str, body: SummaryIn) -> dict[str, Any]:
    try:
        review = service.get_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    run_id = body.run_id
    if run_id:
        try:
            service.get_run(run_id)
        except service.NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
    else:
        run_id = db.new_id("run")
        with db.tx() as c:
            c.execute(
                "INSERT INTO runs (id, review_id, status, trigger, phase, base_sha, head_sha,"
                " engine, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, review_id, "done", "api", "done", review["base_sha"],
                 review["head_sha"], "agent", db.now()),
            )

    with db.tx() as c:
        c.execute(
            "UPDATE runs SET status='done', phase='done', summary=?, verdict=?, confidence=?,"
            " risk_areas=?, test_gaps=?, questions=?, checklist=?, finished_at=? WHERE id=?",
            (
                body.summary, body.verdict, body.confidence,
                db.jdump(body.risk_areas), db.jdump(body.test_gaps),
                db.jdump(body.questions), db.jdump(body.checklist), db.now(), run_id,
            ),
        )
        c.execute(
            "UPDATE notes SET run_id=? WHERE review_id=? AND run_id='' AND origin='claude'",
            (run_id, review_id),
        )
        c.execute("UPDATE reviews SET updated_at=? WHERE id=?", (db.now(), review_id))

    db.log_event(review_id, run_id, "summary", body.verdict)
    return {"run": service.get_run(run_id)}


@router.post("/reviews/{review_id}/workspace",
             summary="Prepare (or reuse) the read-only checkout and return its path")
async def prepare_workspace(review_id: str) -> dict[str, Any]:
    try:
        review = service.get_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    settings = get_settings()
    if not settings.clone_enabled:
        raise HTTPException(status_code=409, detail="repo cloning is disabled in this install")
    try:
        ws = await workspace.prepare_workspace(
            service.review_ref(review),
            PullMeta(
                base_ref=review["base_ref"], base_sha=review["base_sha"],
                head_sha=review["head_sha"], clone_url=review["clone_url"],
                head_clone_url=review["head_clone_url"],
            ),
            settings.token_for(review["host"]),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"{type(exc).__name__}: {exc}") from exc
    return {
        "worktree": str(ws.worktree),
        "head_sha": ws.head_sha,
        "base_sha": ws.base_sha,
        "merge_base": ws.merge_base,
        "read_only": True,
    }
