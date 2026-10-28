"""Usage analytics for the overview page.

Returns compact rows rather than finished aggregates: the browser buckets them
by day in the viewer's own timezone and re-slices them per date range without a
round trip. A busy install has a few thousand runs and notes, which is small.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import db

router = APIRouter(prefix="/api", tags=["analytics"])


def _rows(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in db.get_conn().execute(sql, args).fetchall()]


@router.get("/analytics", summary="Rows for the usage dashboard: reviews, runs, notes")
def analytics() -> dict[str, Any]:
    reviews = _rows(
        "SELECT id, provider, host, namespace, project, number, title, author, assignees,"
        " reviewers, state, draft, additions, deletions, changed_files, archived,"
        " repo_watch_id, created_at, updated_at FROM reviews"
    )
    for r in reviews:
        r["assignees"] = db.jload(r["assignees"], [])
        r["reviewers"] = db.jload(r["reviewers"], [])

    runs = _rows(
        "SELECT id, review_id, status, trigger, mode, engine, model, verdict, cost_usd,"
        " duration_ms, num_turns, used_worktree, note_counts, COALESCE(kind, 'review') AS kind,"
        " created_at, finished_at FROM runs ORDER BY created_at"
    )
    # Runs from before note_counts existed: recover what the notes table still
    # holds for them (exact for the latest run of each PR, absent for older ones).
    fallback: dict[str, dict[str, int]] = {}
    for row in _rows(
        "SELECT run_id, severity, COUNT(*) AS n FROM notes WHERE run_id != ''"
        " AND origin='claude' GROUP BY run_id, severity"
    ):
        fallback.setdefault(row["run_id"], {})[row["severity"]] = row["n"]
    for run in runs:
        counts = db.jload(run.pop("note_counts"), None)
        run["notes"] = counts if isinstance(counts, dict) else fallback.get(run["id"], {})

    notes = _rows(
        "SELECT review_id, run_id, severity, category, status, origin, stale, created_at,"
        " updated_at FROM notes"
    )
    return {"reviews": reviews, "runs": runs, "notes": notes, "generated_at": db.now()}
