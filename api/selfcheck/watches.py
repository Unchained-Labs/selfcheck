"""Repository wakeups: check a repo on a schedule and review new PRs/MRs.

A wakeup lists the repository's open pull requests (a GET, like everything
else selfcheck sends to a forge), starts tracking the ones it has not seen, and
queues a review of each in the wakeup's mode and engine. With
`rereview_on_push`, a tracked PR whose head moved since its last review is
reviewed again at the same cadence.

Spending is bounded on purpose: `max_per_check` caps the reviews one check
starts (the rest wait for the next one), PRs opened before the wakeup existed
are left alone unless you ask for them, and runs queue behind
SELFCHECK_MAX_CONCURRENT_RUNS.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from . import db, prompts, service
from .engines import ENGINE_IDS
from .providers import PullSummary, RepoRef, get_provider, parse_repo_url

MIN_INTERVAL = 15
_DAILY_AT = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_checking: set[str] = set()


class WatchError(ValueError):
    pass


# ── schedule ──────────────────────────────────────────────────────────────

def _parse_ts(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        ts = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def next_check(watch: dict[str, Any], after: datetime | None = None) -> str:
    """When this wakeup should next fire, as a UTC ISO timestamp.

    A daily wakeup with `daily_at` fires at that wall-clock time in the
    server's timezone; anything else fires `interval_minutes` after `after`.
    """
    after = after or datetime.now(UTC)
    interval = max(MIN_INTERVAL, int(watch.get("interval_minutes") or 1440))
    m = _DAILY_AT.match(watch.get("daily_at") or "")
    if m and interval % 1440 == 0:
        local = after.astimezone()
        target = local.replace(hour=int(m[1]), minute=int(m[2]), second=0, microsecond=0)
        if target <= local:
            target += timedelta(days=1)
        target += timedelta(days=interval // 1440 - 1)
        return target.astimezone(UTC).isoformat(timespec="seconds")
    return (after + timedelta(minutes=interval)).isoformat(timespec="seconds")


# ── CRUD ──────────────────────────────────────────────────────────────────

def _clean(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "interval_minutes" in fields and fields["interval_minutes"] is not None:
        out["interval_minutes"] = max(MIN_INTERVAL, int(fields["interval_minutes"]))
    if "daily_at" in fields and fields["daily_at"] is not None:
        daily = str(fields["daily_at"]).strip()
        if daily and not _DAILY_AT.match(daily):
            raise WatchError(f"daily_at must be HH:MM, got {daily!r}")
        out["daily_at"] = daily
    if fields.get("mode") is not None:
        if fields["mode"] and fields["mode"] not in prompts.MODES:
            raise WatchError(f"unknown mode {fields['mode']!r}")
        out["mode"] = fields["mode"]
    if fields.get("engine") is not None:
        if fields["engine"] and fields["engine"] not in ENGINE_IDS:
            raise WatchError(f"unknown engine {fields['engine']!r}")
        out["engine"] = fields["engine"]
    for flag in ("enabled", "include_drafts", "rereview_on_push"):
        if fields.get(flag) is not None:
            out[flag] = int(bool(fields[flag]))
    for text in ("target_branch", "authors"):
        if fields.get(text) is not None:
            out[text] = str(fields[text]).strip()
    if fields.get("max_per_check") is not None:
        out["max_per_check"] = min(25, max(1, int(fields["max_per_check"])))
    return out


def _hydrate(row: dict[str, Any]) -> dict[str, Any]:
    conn = db.get_conn()
    stats = conn.execute(
        "SELECT COUNT(*) AS n, SUM(CASE WHEN repo_watch_id=? THEN 1 ELSE 0 END) AS auto"
        " FROM reviews WHERE host=? AND namespace=? AND project=? AND archived=0",
        (row["id"], row["host"], row["namespace"], row["project"]),
    ).fetchone()
    row["tracked"] = stats["n"] or 0
    row["auto_tracked"] = stats["auto"] or 0
    row["checking"] = row["id"] in _checking
    return row


def list_watches() -> list[dict[str, Any]]:
    rows = db.get_conn().execute(
        "SELECT * FROM repo_watches ORDER BY namespace, project"
    ).fetchall()
    return [_hydrate(dict(r)) for r in rows]


def get_watch(watch_id: str) -> dict[str, Any]:
    row = db.get_conn().execute("SELECT * FROM repo_watches WHERE id=?", (watch_id,)).fetchone()
    if row is None:
        raise service.NotFound(f"no wakeup {watch_id!r}")
    return _hydrate(dict(row))


def repo_of(watch: dict[str, Any]) -> RepoRef:
    return RepoRef(watch["provider"], watch["host"], watch["namespace"], watch["project"])


async def list_open(repo: RepoRef) -> list[PullSummary]:
    provider = get_provider(repo)
    try:
        return await provider.list_open_pulls(repo)
    finally:
        await provider.aclose()


async def create_watch(
    url: str, *, provider: str = "", include_existing: bool = False, **fields: Any
) -> dict[str, Any]:
    repo = parse_repo_url(url, provider)
    conn = db.get_conn()
    existing = conn.execute(
        "SELECT id FROM repo_watches WHERE host=? AND namespace=? AND project=?",
        (repo.host, repo.namespace, repo.project),
    ).fetchone()
    if existing:
        raise WatchError(f"{repo.full_path} already has a wakeup")

    # Fail now, with the forge's own error, rather than at 3am.
    await list_open(repo)

    values = {
        "interval_minutes": 1440, "daily_at": "09:00", "mode": "", "engine": "",
        "include_drafts": 0, "rereview_on_push": 0, "target_branch": "", "authors": "",
        "max_per_check": 3, "enabled": 1,
        **_clean(fields),
    }
    wid = db.new_id("wake")
    ts = db.now()
    values["next_check_at"] = next_check(values)
    with db.tx() as c:
        c.execute(
            "INSERT INTO repo_watches (id, provider, host, namespace, project, url, enabled,"
            " interval_minutes, daily_at, mode, engine, include_drafts, rereview_on_push,"
            " target_branch, authors, max_per_check, baseline_at, next_check_at,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                wid, repo.provider, repo.host, repo.namespace, repo.project, repo.web_url,
                values["enabled"], values["interval_minutes"], values["daily_at"],
                values["mode"], values["engine"], values["include_drafts"],
                values["rereview_on_push"], values["target_branch"], values["authors"],
                values["max_per_check"], "" if include_existing else ts,
                values["next_check_at"], ts, ts,
            ),
        )
    return get_watch(wid)


def update_watch(watch_id: str, fields: dict[str, Any]) -> dict[str, Any]:
    watch = get_watch(watch_id)
    values = _clean(fields)
    if not values:
        return watch
    merged = {**watch, **values}
    if {"interval_minutes", "daily_at", "enabled"} & values.keys():
        values["next_check_at"] = next_check(merged)
    sets = ", ".join(f"{k}=?" for k in values)
    with db.tx() as c:
        c.execute(f"UPDATE repo_watches SET {sets}, updated_at=? WHERE id=?",
                  [*values.values(), db.now(), watch_id])
    return get_watch(watch_id)


def delete_watch(watch_id: str) -> None:
    get_watch(watch_id)
    with db.tx() as c:
        c.execute("DELETE FROM repo_watches WHERE id=?", (watch_id,))
        # The reviews it started stay; they are just no longer anyone's.
        c.execute("UPDATE reviews SET repo_watch_id='' WHERE repo_watch_id=?", (watch_id,))


# ── checking ──────────────────────────────────────────────────────────────

def _tracked(repo: RepoRef) -> dict[int, dict[str, Any]]:
    rows = db.get_conn().execute(
        "SELECT * FROM reviews WHERE host=? AND namespace=? AND project=?",
        (repo.host, repo.namespace, repo.project),
    ).fetchall()
    return {int(r["number"]): dict(r) for r in rows}


async def preview(watch_id: str) -> list[dict[str, Any]]:
    """Open PRs right now, with what this wakeup would do about each."""
    watch = get_watch(watch_id)
    repo = repo_of(watch)
    tracked = _tracked(repo)
    out = []
    for pr in await list_open(repo):
        review = tracked.get(pr.number)
        out.append({
            "number": pr.number, "title": pr.title, "author": pr.author, "draft": pr.draft,
            "base_ref": pr.base_ref, "created_at": pr.created_at, "web_url": pr.web_url,
            "review_id": review["id"] if review else None,
            "skip": _skip_reason(watch, pr, tracked_review=review),
        })
    return out


def _skip_reason(
    watch: dict[str, Any], pr: PullSummary, *, tracked_review: dict[str, Any] | None
) -> str:
    if pr.draft and not watch["include_drafts"]:
        return "draft"
    if watch["target_branch"] and pr.base_ref != watch["target_branch"]:
        return f"targets {pr.base_ref}"
    authors = {a.strip().lower() for a in (watch["authors"] or "").split(",") if a.strip()}
    if authors and pr.author.lower() not in authors:
        return "author not in the list"
    if tracked_review is None:
        baseline, created = _parse_ts(watch["baseline_at"]), _parse_ts(pr.created_at)
        if baseline and created and created < baseline:
            return "opened before the wakeup"
    elif tracked_review["archived"]:
        return "archived"
    return ""


async def check(watch_id: str, *, trigger: str = "schedule") -> dict[str, Any]:
    """Run one wakeup now. Returns what it found and what it started."""
    watch = get_watch(watch_id)
    if watch_id in _checking:
        raise WatchError("this wakeup is already checking")
    _checking.add(watch_id)
    repo = repo_of(watch)
    started: list[dict[str, Any]] = []
    deferred = 0
    errors: list[str] = []
    paused = ""  # set when a spend cap stops this check
    try:
        pulls = await list_open(repo)
        tracked = _tracked(repo)
        # Oldest first, so a backlog drains in the order it arrived.
        for pr in sorted(pulls, key=lambda p: p.created_at):
            review = tracked.get(pr.number)
            if _skip_reason(watch, pr, tracked_review=review):
                continue
            if review is not None:
                moved = (watch["rereview_on_push"] and pr.head_sha
                         and review["head_sha"] and pr.head_sha != review["head_sha"])
                if not moved or service.active_run(review["id"]):
                    continue
            if len(started) >= watch["max_per_check"]:
                deferred += 1
                continue
            paused = paused or service.budget_blocked()
            if paused:
                deferred += 1
                continue
            try:
                started.append(await _review_pull(watch, repo, pr, review))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"#{pr.number}: {type(exc).__name__}: {exc}")
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{type(exc).__name__}: {exc}")
        pulls = []
    finally:
        _checking.discard(watch_id)

    parts = [f"{len(pulls)} open"]
    if started:
        parts.append(f"{len(started)} review{'s' if len(started) != 1 else ''} started")
    if deferred:
        parts.append(f"{deferred} waiting for the next check")
    if paused:
        parts.append(f"paused: {paused}")
    if not started and not deferred and not errors:
        parts.append("nothing new")
    ts = db.now()
    with db.tx() as c:
        c.execute(
            "UPDATE repo_watches SET last_checked_at=?, next_check_at=?, last_result=?,"
            " last_error=?, updated_at=? WHERE id=?",
            (ts, next_check(watch), " · ".join(parts), "\n".join(errors)[:2000], ts, watch_id),
        )
    return {
        "watch": get_watch(watch_id),
        "trigger": trigger,
        "open": len(pulls),
        "started": started,
        "deferred": deferred,
        "paused": paused,
        "errors": errors,
    }


async def _review_pull(
    watch: dict[str, Any], repo: RepoRef, pr: PullSummary, review: dict[str, Any] | None
) -> dict[str, Any]:
    rereview = review is not None
    if review is None:
        review = service.create_or_get_review(pr.web_url or repo.pull_url(pr.number))
        with db.tx() as c:
            c.execute(
                "UPDATE reviews SET repo_watch_id=?, mode=?, engine=? WHERE id=?",
                (watch["id"], watch["mode"], watch["engine"], review["id"]),
            )
    await service.sync_review(review["id"])
    run = service.create_run(
        review["id"], trigger="schedule",
        mode=watch["mode"] or None, engine=watch["engine"] or None,
    )
    db.log_event(review["id"], run["id"], "wakeup", f"{repo.full_path} #{pr.number}")
    return {"review_id": review["id"], "run_id": run["id"], "number": pr.number,
            "title": pr.title, "rereview": rereview}


async def run_due() -> None:
    now = db.now()
    rows = db.get_conn().execute(
        "SELECT id FROM repo_watches WHERE enabled=1 AND next_check_at != ''"
        " AND next_check_at <= ?",
        (now,),
    ).fetchall()
    for row in rows:
        if row["id"] not in _checking:
            await check(row["id"])
