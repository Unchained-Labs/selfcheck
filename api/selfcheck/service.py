"""Orchestration: resolve URLs, sync metadata, cache diffs, run reviews."""

from __future__ import annotations

import asyncio
import contextlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import db, prompts, workspace
from .config import get_settings
from .engines import ENGINE_IDS, ReviewTask, UnknownEngine, get_engine
from .engines.base import noop_event
from .diffparse import parse_unified_diff, render_for_prompt, to_payload
from .events import bus
from .providers import PullRef, get_provider, parse_pull_url
from .providers.base import PullMeta

SEVERITY_ORDER = ["blocker", "major", "minor", "nit", "question", "praise"]
VALID_SEVERITY = set(SEVERITY_ORDER)
VALID_CATEGORY = {
    "correctness", "security", "performance", "tests", "style", "docs", "design", "api",
}
VALID_STATUS = {"open", "resolved", "dismissed", "wontfix"}

ACTIVE_STATUSES = ("queued", "preparing", "analyzing")

_running: dict[str, asyncio.Task] = {}
_loop: asyncio.AbstractEventLoop | None = None
_slots: asyncio.Semaphore | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Remember the app's event loop so runs can be started from a worker thread."""
    global _loop
    _loop = loop
    resize_slots(get_settings().max_concurrent_runs)


def resize_slots(n: int) -> None:
    """A new pool for runs that start from now on. Runs already holding a slot
    in the old pool finish there; nothing in flight is interrupted."""
    global _slots
    _slots = asyncio.Semaphore(max(1, int(n)))


def recover_interrupted_runs() -> int:
    """A run lives in this process, so one still marked active at startup was
    cut off by a restart. Say so, rather than showing "Reviewing…" forever."""
    with db.tx() as c:
        cur = c.execute(
            "UPDATE runs SET status='failed', phase='failed', finished_at=?,"
            " error='interrupted: selfcheck restarted while this run was in progress'"
            f" WHERE status IN ({','.join('?' * len(ACTIVE_STATUSES))})",
            (db.now(), *ACTIVE_STATUSES),
        )
    return cur.rowcount


def resolve_mode(requested: str | None, review: dict[str, Any] | None = None) -> str:
    for candidate in (requested, (review or {}).get("mode"), get_settings().default_mode):
        if candidate in prompts.MODES:
            return candidate
    return "normal"


def resolve_engine(requested: str | None, review: dict[str, Any] | None = None) -> str:
    if requested and requested not in ENGINE_IDS:
        raise UnknownEngine(f"unknown engine {requested!r}; choose one of {', '.join(ENGINE_IDS)}")
    for candidate in (requested, (review or {}).get("engine"), get_settings().engine):
        if candidate in ENGINE_IDS:
            return candidate
    return "claude"


class NotFound(Exception):
    pass


# ── reviews ───────────────────────────────────────────────────────────────

def review_ref(review: dict[str, Any]) -> PullRef:
    return PullRef(
        provider=review["provider"],
        host=review["host"],
        namespace=review["namespace"],
        project=review["project"],
        number=int(review["number"]),
    )


def get_review(review_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if row is None:
        raise NotFound(f"no review {review_id!r}")
    return dict(row)


def list_reviews(include_archived: bool = False) -> list[dict[str, Any]]:
    conn = db.get_conn()
    clause = "" if include_archived else "WHERE archived = 0"
    rows = conn.execute(
        f"SELECT * FROM reviews {clause} ORDER BY pinned DESC, updated_at DESC"
    ).fetchall()
    out = []
    for row in rows:
        r = dict(row)
        r["counts"] = note_counts(r["id"])
        r["latest_run"] = latest_run(r["id"])
        out.append(r)
    return out


def create_or_get_review(url: str) -> dict[str, Any]:
    ref = parse_pull_url(url)
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM reviews WHERE host=? AND namespace=? AND project=? AND number=?",
        (ref.host, ref.namespace, ref.project, ref.number),
    ).fetchone()
    if row is not None:
        existing = dict(row)
        if existing["archived"]:
            with db.tx() as c:
                c.execute(
                    "UPDATE reviews SET archived=0, updated_at=? WHERE id=?",
                    (db.now(), existing["id"]),
                )
            existing["archived"] = 0
        return existing

    rid = db.new_id("rev")
    ts = db.now()
    with db.tx() as c:
        c.execute(
            "INSERT INTO reviews (id, provider, host, namespace, project, number, url,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (rid, ref.provider, ref.host, ref.namespace, ref.project, ref.number,
             url.strip(), ts, ts),
        )
    return get_review(rid)


async def sync_review(review_id: str) -> dict[str, Any]:
    """Refetch metadata from the forge. Detects a new head and stales notes."""
    review = get_review(review_id)
    ref = review_ref(review)
    provider = get_provider(ref, review["url"])
    try:
        meta: PullMeta = await provider.fetch_meta(ref)
    finally:
        await provider.aclose()

    previous_head = review["head_sha"]
    ts = db.now()
    # GitLab's merge-request payload has no line totals, so it reports 0/0.
    # Keep what the last parsed diff said rather than zeroing it; the next diff
    # fetch corrects it if the change moved.
    if not (meta.additions or meta.deletions):
        meta.additions, meta.deletions = review["additions"], review["deletions"]
    if not meta.changed_files:
        meta.changed_files = review["changed_files"]
    with db.tx() as c:
        c.execute(
            "UPDATE reviews SET title=?, description=?, author=?, state=?, draft=?,"
            " base_ref=?, head_ref=?, base_sha=?, head_sha=?, clone_url=?, head_clone_url=?,"
            " changed_files=?, additions=?, deletions=?, provider_updated_at=?,"
            " assignees=?, reviewers=?,"
            " last_synced_at=?, updated_at=?, url=COALESCE(NULLIF(?,''), url) WHERE id=?",
            (
                meta.title, meta.description, meta.author, meta.state, int(meta.draft),
                meta.base_ref, meta.head_ref, meta.base_sha, meta.head_sha,
                meta.clone_url, meta.head_clone_url, meta.changed_files,
                meta.additions, meta.deletions, meta.provider_updated_at,
                db.jdump(meta.assignees), db.jdump(meta.reviewers),
                ts, ts, meta.web_url, review_id,
            ),
        )
        if previous_head and meta.head_sha and previous_head != meta.head_sha:
            c.execute(
                "UPDATE notes SET stale=1, updated_at=? WHERE review_id=? AND status='open'"
                " AND anchor_sha != ?",
                (ts, review_id, meta.head_sha),
            )

    db.log_event(
        review_id, "", "sync",
        "head unchanged" if previous_head == meta.head_sha else f"head -> {meta.head_sha[:8]}",
        {"previous_head": previous_head, "head_sha": meta.head_sha},
    )
    updated = get_review(review_id)
    updated["head_changed"] = bool(previous_head and previous_head != meta.head_sha)
    updated["commits"] = meta.commits
    updated["labels"] = meta.labels
    return updated


def delete_review(review_id: str) -> None:
    review = get_review(review_id)
    with db.tx() as c:
        c.execute("DELETE FROM reviews WHERE id=?", (review_id,))
    db.log_event(review_id, "", "deleted", review["url"])


def set_flags(review_id: str, **flags: Any) -> dict[str, Any]:
    allowed = {"watch", "archived", "pinned"}
    sets, vals = [], []
    for k, v in flags.items():
        if k in allowed and v is not None:
            sets.append(f"{k}=?")
            vals.append(int(bool(v)))
    # Per-PR defaults for the next run; '' falls back to the global default.
    if flags.get("mode") is not None:
        if flags["mode"] and flags["mode"] not in prompts.MODES:
            raise ValueError(f"unknown mode {flags['mode']!r}")
        sets.append("mode=?")
        vals.append(flags["mode"])
    if flags.get("engine") is not None:
        if flags["engine"]:
            resolve_engine(flags["engine"])
        sets.append("engine=?")
        vals.append(flags["engine"])
    if sets:
        vals += [db.now(), review_id]
        with db.tx() as c:
            c.execute(f"UPDATE reviews SET {', '.join(sets)}, updated_at=? WHERE id=?", vals)
    return get_review(review_id)


# ── diff ──────────────────────────────────────────────────────────────────

async def fetch_diff_payload(review_id: str, refresh: bool = False) -> dict[str, Any]:
    review = get_review(review_id)
    if not review["head_sha"]:
        review = await sync_review(review_id)

    base_sha, head_sha = review["base_sha"] or "", review["head_sha"] or ""
    conn = db.get_conn()
    if not refresh:
        row = conn.execute(
            "SELECT payload FROM diff_cache WHERE review_id=? AND base_sha=? AND head_sha=?",
            (review_id, base_sha, head_sha),
        ).fetchone()
        if row is not None:
            return db.jload(row["payload"], {})

    ref = review_ref(review)
    provider = get_provider(ref, review["url"])
    try:
        meta = PullMeta(base_sha=base_sha, head_sha=head_sha, base_ref=review["base_ref"])
        raw = await provider.fetch_diff(ref, meta)
    finally:
        await provider.aclose()

    files = parse_unified_diff(raw)
    payload = to_payload(files)
    payload["base_sha"] = base_sha
    payload["head_sha"] = head_sha
    stats = payload["stats"]
    with db.tx() as c:
        c.execute(
            "INSERT OR REPLACE INTO diff_cache (review_id, base_sha, head_sha, payload,"
            " created_at) VALUES (?,?,?,?,?)",
            (review_id, base_sha, head_sha, db.jdump(payload), db.now()),
        )
        # GitLab's merge-request payload carries no line totals, so take them
        # from the diff we just parsed rather than showing the user +0 / -0.
        c.execute(
            "UPDATE reviews SET changed_files=?, additions=?, deletions=? WHERE id=?",
            (stats["files"], stats["additions"], stats["deletions"], review_id),
        )
    return payload


async def read_blob(review_id: str, path: str, side: str = "new") -> str | None:
    """Full file content from the mirror, for expanding context around a hunk."""
    review = get_review(review_id)
    ref = review_ref(review)
    mirror = workspace.mirror_path(ref)
    if not (mirror / "HEAD").exists():
        return None
    sha = review["head_sha"] if side == "new" else review["base_sha"]
    if not sha:
        return None
    token = get_settings().token_for(review["host"])
    return await workspace.show_blob(mirror, sha, path, token=token)


# ── notes ─────────────────────────────────────────────────────────────────

def note_counts(review_id: str) -> dict[str, int]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT severity, status, COUNT(*) AS n FROM notes WHERE review_id=?"
        " GROUP BY severity, status",
        (review_id,),
    ).fetchall()
    counts = {s: 0 for s in SEVERITY_ORDER}
    counts.update({"open": 0, "resolved": 0, "dismissed": 0, "wontfix": 0, "total": 0})
    for r in rows:
        counts["total"] += r["n"]
        counts[r["status"]] = counts.get(r["status"], 0) + r["n"]
        if r["status"] == "open":
            counts[r["severity"]] = counts.get(r["severity"], 0) + r["n"]
    return counts


def list_notes(review_id: str, run_id: str | None = None) -> list[dict[str, Any]]:
    conn = db.get_conn()
    if run_id:
        rows = conn.execute(
            "SELECT * FROM notes WHERE review_id=? AND run_id=? ORDER BY file_path, line_start",
            (review_id, run_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM notes WHERE review_id=? ORDER BY file_path, line_start",
            (review_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _clean_note(raw: dict[str, Any]) -> dict[str, Any]:
    sev = str(raw.get("severity", "minor")).lower()
    cat = str(raw.get("category", "correctness")).lower()
    side = str(raw.get("side", "new")).lower()
    start = raw.get("line_start") or raw.get("line") or None
    end = raw.get("line_end") or start
    with contextlib.suppress(TypeError, ValueError):
        start = int(start) if start is not None else None
    with contextlib.suppress(TypeError, ValueError):
        end = int(end) if end is not None else None
    return {
        "file_path": str(raw.get("file") or raw.get("file_path") or "").lstrip("./"),
        "line_start": start if isinstance(start, int) else None,
        "line_end": end if isinstance(end, int) else None,
        "side": side if side in ("new", "old") else "new",
        "severity": sev if sev in VALID_SEVERITY else "minor",
        "category": cat if cat in VALID_CATEGORY else "correctness",
        "title": str(raw.get("title") or "").strip()[:300],
        "body": str(raw.get("body") or "").strip(),
        "suggestion": str(raw.get("suggestion") or "").strip(),
        "confidence": str(raw.get("confidence") or "").lower(),
    }


def normalise_title(title: str) -> str:
    """Loose key for matching a finding across runs. The prompt asks the model
    to re-issue a still-valid finding under the same title, so whitespace and
    case are the only drift worth absorbing."""
    return " ".join(str(title or "").lower().split())


def supersede_claude_notes(review_id: str) -> dict[str, str]:
    """Clear the previous run's findings, returning the decisions you had
    already made on them.

    A re-review replaces the last review rather than piling a second copy of
    every finding on top of it. Two things survive: notes you wrote yourself,
    which are never touched, and any verdict you reached — resolved, dismissed,
    won't fix — which carries across to the re-issued finding so a re-review
    cannot resurrect something you have already dealt with.
    """
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT title, status FROM notes WHERE review_id=? AND origin='claude'",
        (review_id,),
    ).fetchall()
    decided = {
        normalise_title(r["title"]): r["status"]
        for r in rows
        if r["status"] != "open" and r["title"]
    }
    with db.tx() as c:
        c.execute("DELETE FROM notes WHERE review_id=? AND origin='claude'", (review_id,))
    return decided


def add_notes(
    review_id: str,
    raw_notes: list[dict[str, Any]],
    *,
    run_id: str = "",
    origin: str = "claude",
    anchor_sha: str = "",
    carry_status: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    get_review(review_id)  # existence check
    ts = db.now()
    created: list[str] = []
    carry_status = carry_status or {}
    with db.tx() as c:
        for raw in raw_notes:
            n = _clean_note(raw)
            if not n["title"] and not n["body"]:
                continue
            status = carry_status.get(normalise_title(n["title"]), "open")
            nid = db.new_id("note")
            created.append(nid)
            c.execute(
                "INSERT INTO notes (id, review_id, run_id, file_path, line_start, line_end,"
                " side, severity, category, title, body, suggestion, confidence, status,"
                " origin, anchor_sha, stale, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
                (
                    nid, review_id, run_id, n["file_path"], n["line_start"], n["line_end"],
                    n["side"], n["severity"], n["category"], n["title"], n["body"],
                    n["suggestion"], n["confidence"], status, origin, anchor_sha, ts, ts,
                ),
            )
    conn = db.get_conn()
    if not created:
        return []
    marks = ",".join("?" * len(created))
    rows = conn.execute(f"SELECT * FROM notes WHERE id IN ({marks})", created).fetchall()
    return [dict(r) for r in rows]


def update_note(note_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    if row is None:
        raise NotFound(f"no note {note_id!r}")
    fields = {
        "status": VALID_STATUS,
        "severity": VALID_SEVERITY,
        "category": VALID_CATEGORY,
    }
    sets, vals = [], []
    for key, valid in fields.items():
        if key in patch and patch[key] is not None:
            v = str(patch[key]).lower()
            if v not in valid:
                raise ValueError(f"invalid {key}: {patch[key]!r}")
            sets.append(f"{key}=?")
            vals.append(v)
    for key in ("title", "body", "suggestion"):
        if key in patch and patch[key] is not None:
            sets.append(f"{key}=?")
            vals.append(str(patch[key]))
    if "stale" in patch and patch["stale"] is not None:
        sets.append("stale=?")
        vals.append(int(bool(patch["stale"])))
    if not sets:
        return dict(row)
    vals += [db.now(), note_id]
    with db.tx() as c:
        c.execute(f"UPDATE notes SET {', '.join(sets)}, updated_at=? WHERE id=?", vals)
    return dict(conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone())


def delete_note(note_id: str) -> None:
    with db.tx() as c:
        cur = c.execute("DELETE FROM notes WHERE id=?", (note_id,))
    if cur.rowcount == 0:
        raise NotFound(f"no note {note_id!r}")


def set_file_viewed(review_id: str, path: str, viewed: bool, sha: str = "") -> dict[str, Any]:
    with db.tx() as c:
        c.execute(
            "INSERT INTO file_state (review_id, file_path, viewed, viewed_sha, updated_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(review_id, file_path) DO UPDATE SET"
            " viewed=excluded.viewed, viewed_sha=excluded.viewed_sha,"
            " updated_at=excluded.updated_at",
            (review_id, path, int(viewed), sha, db.now()),
        )
    return {"file_path": path, "viewed": viewed, "viewed_sha": sha}


def file_states(review_id: str) -> dict[str, dict[str, Any]]:
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM file_state WHERE review_id=?", (review_id,)).fetchall()
    return {r["file_path"]: dict(r) for r in rows}


# ── runs ──────────────────────────────────────────────────────────────────

REVIEW_KIND = "COALESCE(kind, 'review') = 'review'"


def latest_run(review_id: str) -> dict[str, Any] | None:
    """The current review. A second opinion is beside it, never instead of it."""
    conn = db.get_conn()
    row = conn.execute(
        f"SELECT * FROM runs WHERE review_id=? AND {REVIEW_KIND} ORDER BY created_at DESC LIMIT 1",
        (review_id,),
    ).fetchone()
    return _hydrate_run(dict(row)) if row else None


def get_run(run_id: str) -> dict[str, Any]:
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise NotFound(f"no run {run_id!r}")
    return _hydrate_run(dict(row))


def list_runs(review_id: str) -> list[dict[str, Any]]:
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM runs WHERE review_id=? ORDER BY created_at DESC", (review_id,)
    ).fetchall()
    return [_hydrate_run(dict(r)) for r in rows]


def _hydrate_run(run: dict[str, Any]) -> dict[str, Any]:
    for key in ("risk_areas", "checklist", "test_gaps", "questions"):
        run[key] = db.jload(run.get(key), [])
    run["findings"] = db.jload(run.get("findings"), [])
    run["context"] = db.jload(run.get("context"), {})
    run["kind"] = run.get("kind") or "review"
    return run


def _set_run(run_id: str, **fields: Any) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k}=?" for k in fields)
    with db.tx() as c:
        c.execute(f"UPDATE runs SET {sets} WHERE id=?", [*fields.values(), run_id])


async def _emit(review_id: str, run_id: str, event: dict[str, Any]) -> None:
    payload = {**event, "run_id": run_id, "review_id": review_id, "ts": db.now()}
    await bus.publish(run_id, payload)
    await bus.publish(f"review:{review_id}", payload)


def active_run(review_id: str) -> dict[str, Any] | None:
    row = db.get_conn().execute(
        f"SELECT * FROM runs WHERE review_id=? AND status IN"
        f" ({','.join('?' * len(ACTIVE_STATUSES))}) ORDER BY created_at DESC LIMIT 1",
        (review_id, *ACTIVE_STATUSES),
    ).fetchone()
    return _hydrate_run(dict(row)) if row else None


def create_run(
    review_id: str,
    trigger: str = "manual",
    guidance: str = "",
    *,
    mode: str | None = None,
    engine: str | None = None,
    kind: str = "review",
) -> dict[str, Any]:
    review = get_review(review_id)
    if trigger in AUTOMATIC_TRIGGERS:
        reason = budget_blocked()
        if reason:
            raise BudgetExceeded(reason)
    run_mode = resolve_mode(mode, review)
    run_engine = resolve_engine(engine, review)
    rid = db.new_id("run")
    with db.tx() as c:
        c.execute(
            "INSERT INTO runs (id, review_id, status, trigger, phase, base_sha, head_sha,"
            " mode, engine, kind, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (rid, review_id, "queued", trigger, "queued", review["base_sha"],
             review["head_sha"], run_mode, run_engine, kind, db.now()),
        )
    _spawn_run(rid, guidance)
    return get_run(rid)


def _spawn_run(rid: str, guidance: str) -> None:
    coro = _execute_run(rid, guidance)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = _loop
    if loop is None:
        raise RuntimeError("selfcheck has no event loop bound; is the server running?")
    if loop.is_running() and loop is not _current_loop():
        # Called from a threadpool worker (a sync FastAPI route).
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        _running[rid] = future  # type: ignore[assignment]
        future.add_done_callback(lambda _f: _running.pop(rid, None))
        return
    task = loop.create_task(coro)
    _running[rid] = task
    task.add_done_callback(lambda _t: _running.pop(rid, None))


def _current_loop() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def cancel_run(run_id: str) -> dict[str, Any]:
    task = _running.get(run_id)
    if task and not task.done():
        task.cancel()
    _set_run(run_id, status="cancelled", phase="cancelled", finished_at=db.now())
    return get_run(run_id)


async def _execute_run(run_id: str, guidance: str = "") -> None:
    run = get_run(run_id)
    review_id = run["review_id"]
    try:
        slots = _slots
        if slots is not None and slots.locked():
            _set_run(run_id, progress="waiting for another review to finish")
            await _emit(review_id, run_id, {
                "kind": "phase", "phase": "queued",
                "message": "waiting for another review to finish",
            })
        async with slots if slots is not None else contextlib.nullcontext():
            await _review(run_id, run, guidance)
    except asyncio.CancelledError:
        _set_run(run_id, status="cancelled", phase="cancelled", finished_at=db.now())
        await _emit(review_id, run_id, {"kind": "cancelled"})
        raise
    except Exception as exc:  # noqa: BLE001
        _set_run(run_id, status="failed", phase="failed",
                 error=f"{type(exc).__name__}: {exc}", finished_at=db.now())
        await _emit(review_id, run_id,
                    {"kind": "failed", "error": f"{type(exc).__name__}: {exc}"})


async def _review(run_id: str, run: dict[str, Any], guidance: str) -> None:
    settings = get_settings()
    review_id = run["review_id"]
    mode = prompts.normalise_mode(run.get("mode"))
    engine = get_engine(run.get("engine") or settings.engine)

    async def phase(name: str, message: str = "") -> None:
        _set_run(run_id, phase=name, progress=message)
        await _emit(review_id, run_id, {"kind": "phase", "phase": name, "message": message})

    _set_run(run_id, status="preparing")
    await phase("sync", "fetching pull request metadata")
    review = await sync_review(review_id)
    ref = review_ref(review)

    await phase("diff", "fetching diff")
    diff_payload = await fetch_diff_payload(review_id, refresh=True)
    files = diff_payload.get("files", [])

    wt_path = None
    if settings.clone_enabled:
        await phase("clone", "preparing read-only checkout")
        try:
            wt_path = await prepare_checkout(review)
            await _emit(review_id, run_id,
                        {"kind": "log", "message": f"checkout ready at {wt_path}"})
        except Exception as exc:  # noqa: BLE001
            await _emit(review_id, run_id, {
                "kind": "warn",
                "message": f"checkout unavailable ({type(exc).__name__}: {exc}); "
                           "reviewing from the diff alone",
            })

    kind = run.get("kind") or "review"
    prev_run = None
    conn = db.get_conn()
    prev_row = conn.execute(
        f"SELECT * FROM runs WHERE review_id=? AND status='done' AND id != ? AND {REVIEW_KIND}"
        " ORDER BY created_at DESC LIMIT 1",
        (review_id, run_id),
    ).fetchone()
    previous = None
    # A second opinion starts fresh: shown the last review, it would mostly agree with it.
    if prev_row is not None and kind == "review":
        prev_run = _hydrate_run(dict(prev_row))
        previous = {
            "head_sha": prev_run["head_sha"],
            "summary": prev_run["summary"],
            "notes": list_notes(review_id, prev_run["id"]),
        }

    # Reconstruct the parsed diff so the prompt gets real line numbers.
    from .diffparse import DiffFile, DiffLine, Hunk  # local import: dataclass rehydrate

    rehydrated: list[DiffFile] = []
    for f in files:
        df = DiffFile(
            old_path=f["old_path"], new_path=f["new_path"], status=f["status"],
            is_binary=f["is_binary"], additions=f["additions"], deletions=f["deletions"],
        )
        for h in f["hunks"]:
            hunk = Hunk(
                header=h["header"], section=h["section"], old_start=h["old_start"],
                old_count=h["old_count"], new_start=h["new_start"],
                new_count=h["new_count"],
            )
            hunk.lines = [
                DiffLine(l["kind"], l["content"], l["old_line"], l["new_line"])
                for l in h["lines"]
            ]
            df.hunks.append(hunk)
        rehydrated.append(df)

    diff_text, truncated = render_for_prompt(rehydrated)

    changed_since = None
    if previous and previous["head_sha"] and previous["head_sha"] != review["head_sha"]:
        changed_since = await _files_changed_between(
            ref, previous["head_sha"], review["head_sha"], review["host"]
        )

    rules = get_repo_rules(review["host"], review["namespace"], review["project"])
    file_rules = read_repo_rules_file(wt_path)
    learned = learned_decisions(review) if settings.learn_from_dismissals and rules["learn"] else {}

    prompt = prompts.build_review_prompt(
        meta={**review, "commits": review.get("commits") or []},
        diff_text=diff_text,
        diff_truncated=truncated,
        worktree=str(wt_path) if wt_path else None,
        file_list=[
            {"path": f["path"], "status": f["status"],
             "additions": f["additions"], "deletions": f["deletions"]}
            for f in files
        ],
        previous=previous,
        changed_since=changed_since,
        guidance=guidance,
        mode=mode,
        repo_rules=rules["rules"],
        repo_file_rules=file_rules,
        learned=learned,
    )
    context = {
        "repo_rules": bool(rules["rules"].strip()),
        "repo_file": bool(file_rules.strip()),
        "dismissed": len(learned.get("dismissed", [])),
        "wontfix": len(learned.get("wontfix", [])),
    }

    _set_run(run_id, status="analyzing", used_worktree=int(bool(wt_path)),
             incremental_from=(previous or {}).get("head_sha", ""), context=db.jdump(context))
    await phase("analyzing", f"{engine.label} is reading the change")

    log_path = settings.log_dir / f"{run_id}.jsonl"
    # Scratch space outside the read-only checkout, for engines that need to
    # hand the agent a file. It holds a copy of the diff, so it goes afterwards.
    work_dir = settings.data_dir / "runs" / run_id
    work_dir.mkdir(parents=True, exist_ok=True)

    async def on_event(ev: dict[str, Any]) -> None:
        await _emit(review_id, run_id, ev)

    try:
        result = await engine.review(ReviewTask(
            prompt=prompt,
            system=prompts.SYSTEM_APPEND,
            cwd=wt_path,
            mode=mode,
            timeout=int(settings.run_timeout_seconds * prompts.MODES[mode]["timeout_factor"]),
            log_path=log_path,
            on_event=on_event,
            work_dir=work_dir,
        ))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    if not result.ok:
        _set_run(run_id, status="failed", phase="failed", error=result.error,
                 finished_at=db.now(), log_path=str(log_path),
                 cost_usd=result.cost_usd, duration_ms=result.duration_ms,
                 model=result.model, num_turns=result.num_turns)
        await _emit(review_id, run_id, {"kind": "failed", "error": result.error})
        return

    parsed = prompts.extract_json_block(result.text)
    if not parsed:
        _set_run(run_id, status="failed", phase="failed",
                 error=f"{engine.label}'s reply did not contain a parseable JSON block",
                 summary=result.text[:4000], finished_at=db.now(),
                 log_path=str(log_path), cost_usd=result.cost_usd,
                 duration_ms=result.duration_ms, model=result.model,
                 num_turns=result.num_turns)
        await _emit(review_id, run_id,
                    {"kind": "failed", "error": "unparseable review output"})
        return

    notes = parsed.get("notes") or []
    if kind == "second_opinion":
        # Kept on the run and compared against the review; your notes stay as they are.
        _set_run(run_id, findings=db.jdump([_clean_note(n) for n in notes
                                            if n.get("title") or n.get("body")]))
    else:
        # This run is the review now; the previous one's findings step aside.
        carried = supersede_claude_notes(review_id)
        add_notes(review_id, notes, run_id=run_id, origin="claude",
                  anchor_sha=review["head_sha"], carry_status=carried)

    verdict = str(parsed.get("verdict") or "").lower()
    if verdict not in ("looks_good", "comments", "needs_work"):
        verdict = "comments"
    by_severity: dict[str, int] = {}
    for n in notes:
        sev = _clean_note(n)["severity"]
        by_severity[sev] = by_severity.get(sev, 0) + 1

    _set_run(
        run_id,
        status="done", phase="done",
        summary=str(parsed.get("summary") or ""),
        verdict=verdict,
        confidence=str(parsed.get("confidence") or ""),
        risk_areas=db.jdump(parsed.get("risk_areas") or []),
        checklist=db.jdump(parsed.get("checklist") or []),
        test_gaps=db.jdump(parsed.get("test_gaps") or []),
        questions=db.jdump(parsed.get("questions") or []),
        note_counts=db.jdump(by_severity),
        model=result.model, cost_usd=result.cost_usd,
        duration_ms=result.duration_ms, num_turns=result.num_turns,
        log_path=str(log_path), base_sha=review["base_sha"],
        head_sha=review["head_sha"], finished_at=db.now(),
    )
    if kind == "review":
        with db.tx() as c:
            c.execute("UPDATE reviews SET updated_at=? WHERE id=?", (db.now(), review_id))
    db.log_event(review_id, run_id, "run_done", f"{len(notes)} notes ({kind})")
    await _emit(review_id, run_id, {"kind": "done", "notes": len(notes), "verdict": verdict})


async def _files_changed_between(
    ref: PullRef, old_sha: str, new_sha: str, host: str
) -> list[str] | None:
    mirror = workspace.mirror_path(ref)
    if not (mirror / "HEAD").exists():
        return None
    token = get_settings().token_for(host)
    try:
        out = await workspace.git(
            ["diff", "--name-only", f"{old_sha}..{new_sha}"], mirror, token=token
        )
    except workspace.GitError:
        return None
    return [line for line in out.splitlines() if line.strip()]


# ── checkout ──────────────────────────────────────────────────────────────

async def prepare_checkout(review: dict[str, Any]) -> Path:
    """A read-only worktree of the head commit, from selfcheck's own mirror."""
    settings = get_settings()
    meta = PullMeta(
        base_ref=review["base_ref"],
        base_sha=review["base_sha"],
        head_sha=review["head_sha"],
        clone_url=review["clone_url"],
        head_clone_url=review["head_clone_url"],
    )
    ws = await workspace.prepare_workspace(review_ref(review), meta, settings.token_for(review["host"]))
    return ws.worktree


# ── per-repository rules and learned decisions ────────────────────────────

def split_repo_key(key: str) -> tuple[str, str, str]:
    """`host/group/sub/project` -> (host, group/sub, project)."""
    parts = key.strip("/").split("/")
    if len(parts) < 3:
        raise ValueError(f"not a repository key: {key!r}")
    return parts[0], "/".join(parts[1:-1]), parts[-1]


def get_repo_rules(host: str, namespace: str, project: str) -> dict[str, Any]:
    row = db.get_conn().execute(
        "SELECT * FROM repo_rules WHERE host=? AND namespace=? AND project=?",
        (host, namespace, project),
    ).fetchone()
    if row is None:
        return {"host": host, "namespace": namespace, "project": project,
                "rules": "", "learn": 1, "updated_at": ""}
    return dict(row)


def set_repo_rules(host: str, namespace: str, project: str, *,
                   rules: str | None = None, learn: bool | None = None) -> dict[str, Any]:
    current = get_repo_rules(host, namespace, project)
    new_rules = current["rules"] if rules is None else rules[: prompts.RULES_LIMIT]
    new_learn = current["learn"] if learn is None else int(bool(learn))
    with db.tx() as c:
        c.execute(
            "INSERT INTO repo_rules (host, namespace, project, rules, learn, updated_at)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(host, namespace, project) DO UPDATE SET"
            " rules=excluded.rules, learn=excluded.learn, updated_at=excluded.updated_at",
            (host, namespace, project, new_rules, new_learn, db.now()),
        )
    return get_repo_rules(host, namespace, project)


def read_repo_rules_file(worktree: Path | None) -> str:
    """`.selfcheck.md` at the root of the checkout, if the repository has one."""
    if not worktree:
        return ""
    path = Path(worktree) / prompts.REPO_RULES_FILE
    try:
        if path.is_file() and path.stat().st_size <= 64_000:
            return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return ""


def learned_decisions(review: dict[str, Any], limit: int = 25) -> dict[str, list[dict[str, Any]]]:
    """Findings already judged in this repository: dismissed ones (not real) and
    won't-fix ones (real, out of scope). Most recent first, one per title."""
    rows = db.get_conn().execute(
        "SELECT n.* FROM notes n JOIN reviews r ON r.id = n.review_id"
        " WHERE r.host=? AND r.namespace=? AND r.project=? AND n.origin='claude'"
        " AND n.status IN ('dismissed', 'wontfix') ORDER BY n.updated_at DESC",
        (review["host"], review["namespace"], review["project"]),
    ).fetchall()
    out: dict[str, list[dict[str, Any]]] = {"dismissed": [], "wontfix": []}
    seen: set[str] = set()
    for r in rows:
        key = normalise_title(r["title"])
        if key in seen or len(out[r["status"]]) >= limit:
            continue
        seen.add(key)
        out[r["status"]].append(dict(r))
    return out


# ── second opinions ───────────────────────────────────────────────────────

def _tokens(text: str) -> set[str]:
    return {w for w in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if len(w) > 2}


def _same_finding(a: dict[str, Any], b: dict[str, Any]) -> float:
    """How likely two findings are the same point: 0 (no) to ~2 (certainly)."""
    if (a.get("file_path") or "") != (b.get("file_path") or ""):
        return 0.0
    score = 0.0
    la, lb = a.get("line_start"), b.get("line_start")
    if la and lb:
        ea, eb = a.get("line_end") or la, b.get("line_end") or lb
        if la <= eb + 3 and lb <= ea + 3:
            score += 1.0
        elif abs(la - lb) <= 10:
            score += 0.4
    elif not la and not lb:
        score += 0.5
    ta, tb = _tokens(a.get("title", "")), _tokens(b.get("title", ""))
    if ta and tb:
        score += len(ta & tb) / len(ta | tb)
    return score


def compare_opinion(review_id: str, run_id: str | None = None) -> dict[str, Any]:
    """Where a second opinion agrees with the current review, and where not."""
    conn = db.get_conn()
    if run_id:
        run = get_run(run_id)
    else:
        row = conn.execute(
            "SELECT * FROM runs WHERE review_id=? AND kind='second_opinion'"
            " ORDER BY created_at DESC LIMIT 1", (review_id,),
        ).fetchone()
        if row is None:
            return {"run": None}
        run = _hydrate_run(dict(row))
    primary = latest_run(review_id)
    ours = [n for n in list_notes(review_id) if n["origin"] == "claude"]
    theirs = run.get("findings") or []

    pairs = sorted(
        ((_same_finding(o, t), i, j) for i, o in enumerate(ours) for j, t in enumerate(theirs)),
        reverse=True,
    )
    used_o: set[int] = set()
    used_t: set[int] = set()
    agreed = []
    for score, i, j in pairs:
        if score < 0.9 or i in used_o or j in used_t:
            continue
        used_o.add(i)
        used_t.add(j)
        agreed.append({"ours": ours[i], "theirs": theirs[j], "score": round(score, 2)})
    union = len(ours) + len(theirs) - len(agreed)
    return {
        "run": run,
        "primary_run": primary,
        "agreed": agreed,
        "only_ours": [n for i, n in enumerate(ours) if i not in used_o],
        "only_theirs": [t for j, t in enumerate(theirs) if j not in used_t],
        "agreement": round(len(agreed) / union, 3) if union else 1.0,
    }


# ── questions about a finding ─────────────────────────────────────────────

def list_messages(note_id: str) -> list[dict[str, Any]]:
    rows = db.get_conn().execute(
        "SELECT * FROM note_messages WHERE note_id=? ORDER BY created_at, rowid", (note_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def ask_about_note(note_id: str, question: str, engine: str | None = None) -> list[dict[str, Any]]:
    note = db.get_conn().execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    if note is None:
        raise NotFound(f"no note {note_id!r}")
    question = question.strip()
    if not question:
        raise ValueError("ask something")
    review = get_review(note["review_id"])
    engine_id = resolve_engine(engine, review)
    ts = db.now()
    asked, answer = db.new_id("msg"), db.new_id("msg")
    with db.tx() as c:
        c.execute(
            "INSERT INTO note_messages (id, note_id, review_id, role, body, status, created_at)"
            " VALUES (?,?,?,?,?,?,?)", (asked, note_id, review["id"], "user", question, "done", ts),
        )
        c.execute(
            "INSERT INTO note_messages (id, note_id, review_id, role, body, status, engine,"
            " created_at) VALUES (?,?,?,?,?,?,?,?)",
            (answer, note_id, review["id"], "assistant", "", "pending", engine_id, ts),
        )
    _spawn(_answer(answer, dict(note), question, engine_id), answer)
    return list_messages(note_id)


def _spawn(coro: Any, key: str) -> None:
    loop = _current_loop() or _loop
    if loop is None:
        raise RuntimeError("selfcheck has no event loop bound; is the server running?")
    if loop is not _current_loop():
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        _running[key] = fut  # type: ignore[assignment]
        fut.add_done_callback(lambda _f: _running.pop(key, None))
        return
    task = loop.create_task(coro)
    _running[key] = task
    task.add_done_callback(lambda _t: _running.pop(key, None))


def _hunk_around(payload: dict[str, Any], path: str, line: int | None, side: str) -> str:
    for f in payload.get("files", []):
        if f.get("path") != path:
            continue
        for h in f.get("hunks", []):
            key = "new_line" if side == "new" else "old_line"
            nums = [ln[key] for ln in h["lines"] if ln.get(key)]
            if line and nums and min(nums) - 5 <= line <= max(nums) + 5:
                rows = [h["header"]]
                for ln in h["lines"][:160]:
                    mark = {"add": "+", "del": "-"}.get(ln["kind"], " ")
                    rows.append(f"{ln.get('new_line') or '':>5} {mark}{ln['content']}")
                return "\n".join(rows)
    return ""


async def _answer(message_id: str, note: dict[str, Any], question: str, engine_id: str) -> None:
    settings = get_settings()
    try:
        async with _slots if _slots is not None else contextlib.nullcontext():
            review = get_review(note["review_id"])
            wt = None
            if settings.clone_enabled:
                with contextlib.suppress(Exception):
                    wt = await prepare_checkout(review)
            hunk = ""
            if note.get("file_path"):
                with contextlib.suppress(Exception):
                    payload = await fetch_diff_payload(review["id"])
                    hunk = _hunk_around(payload, note["file_path"], note.get("line_start"),
                                        note.get("side") or "new")
            thread = [m for m in list_messages(note["id"]) if m["id"] != message_id
                      and m["status"] == "done"][:-1]  # the last done message is this question
            prompt = prompts.build_question_prompt(
                review=review, note=note, thread=thread, question=question,
                worktree=str(wt) if wt else None, hunk=hunk,
            )
            engine = get_engine(engine_id)
            work_dir = settings.data_dir / "runs" / message_id
            work_dir.mkdir(parents=True, exist_ok=True)
            try:
                result = await engine.review(ReviewTask(
                    prompt=prompt, system=prompts.QUESTION_SYSTEM, cwd=wt, mode="light",
                    timeout=max(120, settings.run_timeout_seconds // 2),
                    log_path=settings.log_dir / f"{message_id}.jsonl",
                    on_event=noop_event, work_dir=work_dir,
                ))
            finally:
                shutil.rmtree(work_dir, ignore_errors=True)
        body = result.text.strip() if result.ok else f"Could not answer: {result.error}"
        status = "done" if result.ok and body else "failed"
        fields = (body or "The engine returned nothing.", status, result.model, result.cost_usd)
    except Exception as exc:  # noqa: BLE001
        fields = (f"Could not answer: {type(exc).__name__}: {exc}", "failed", "", 0.0)
    with db.tx() as c:
        c.execute("UPDATE note_messages SET body=?, status=?, model=?, cost_usd=? WHERE id=?",
                  (*fields, message_id))


# ── spend caps ────────────────────────────────────────────────────────────

AUTOMATIC_TRIGGERS = ("watch", "schedule")


class BudgetExceeded(RuntimeError):
    pass


def _spend_since(start: datetime) -> float:
    iso = start.astimezone(timezone.utc).isoformat(timespec="seconds")
    conn = db.get_conn()
    runs = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM runs WHERE created_at >= ?",
                        (iso,)).fetchone()[0]
    asks = conn.execute("SELECT COALESCE(SUM(cost_usd), 0) FROM note_messages WHERE created_at >= ?",
                        (iso,)).fetchone()[0]
    return float(runs or 0) + float(asks or 0)


def budget_state() -> dict[str, Any]:
    """Spend today and this month (server's local calendar) against the caps."""
    s = get_settings()
    now = datetime.now().astimezone()
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    today, this_month = _spend_since(day), _spend_since(month)
    reason = ""
    if s.daily_budget_usd and today >= s.daily_budget_usd:
        reason = f"daily budget reached (${today:.2f} of ${s.daily_budget_usd:.2f})"
    elif s.monthly_budget_usd and this_month >= s.monthly_budget_usd:
        reason = f"monthly budget reached (${this_month:.2f} of ${s.monthly_budget_usd:.2f})"
    return {
        "today_usd": round(today, 4), "month_usd": round(this_month, 4),
        "daily_cap_usd": s.daily_budget_usd, "monthly_cap_usd": s.monthly_budget_usd,
        "blocked": bool(reason), "reason": reason,
    }


def budget_blocked() -> str:
    """Why automatic reviews are paused, or '' when they may run."""
    return budget_state()["reason"]


# ── local branches ────────────────────────────────────────────────────────

async def create_local_review(raw: str) -> dict[str, Any]:
    """Track a branch of a repository on this machine, idempotently."""
    from .providers.local import local_url, parse_local_spec, ref_for, resolve_branches

    path, head, base = parse_local_spec(raw)
    head, base = await resolve_branches(path, head, base)
    url = local_url(path, head, base)
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM reviews WHERE url=?", (url,)).fetchone()
    if row is not None:
        if row["archived"]:
            with db.tx() as c:
                c.execute("UPDATE reviews SET archived=0 WHERE id=?", (row["id"],))
        return get_review(row["id"])
    probe = ref_for(path, 0)
    number = 1 + (conn.execute(
        "SELECT COALESCE(MAX(number), 0) FROM reviews WHERE host=? AND namespace=? AND project=?",
        (probe.host, probe.namespace, probe.project),
    ).fetchone()[0] or 0)
    ref = ref_for(path, number)
    rid = db.new_id("rev")
    ts = db.now()
    with db.tx() as c:
        c.execute(
            "INSERT INTO reviews (id, provider, host, namespace, project, number, url, head_ref,"
            " base_ref, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (rid, ref.provider, ref.host, ref.namespace, ref.project, ref.number, url,
             head, base, ts, ts),
        )
    return get_review(rid)
