"""Background work: re-review watched PRs when the head moves, and fire
repository wakeups when they are due."""

from __future__ import annotations

import asyncio
import contextlib
import time

from . import db, service, watches
from .config import get_settings

TICK_SECONDS = 30

_task: asyncio.Task | None = None


async def _tick() -> None:
    """Watched PRs: sync each one and re-review when its head moved."""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT id, head_sha, state FROM reviews WHERE watch = 1 AND archived = 0"
    ).fetchall()
    for row in rows:
        review_id = row["id"]
        try:
            updated = await service.sync_review(review_id)
        except Exception as exc:  # noqa: BLE001
            db.log_event(review_id, "", "watch_error", f"{type(exc).__name__}: {exc}")
            continue

        if updated["state"] in ("merged", "closed"):
            service.set_flags(review_id, watch=False)
            db.log_event(review_id, "", "watch_off", f"pull request is {updated['state']}")
            continue

        if not updated.get("head_changed"):
            continue

        if service.active_run(review_id):
            continue

        try:
            service.create_run(review_id, trigger="watch")
        except service.BudgetExceeded as exc:
            db.log_event(review_id, "", "watch_paused", str(exc))
            continue
        db.log_event(review_id, "", "watch_trigger", f"head -> {updated['head_sha'][:8]}")


async def _loop() -> None:
    interval = max(30, get_settings().watch_interval_seconds)
    last_pr_tick = 0.0
    while True:
        try:
            # Wakeups are cheap to check for (one indexed query), so they run
            # every tick; the per-PR sync hits the forge, so it keeps its interval.
            await watches.run_due()
            if time.monotonic() - last_pr_tick >= interval:
                last_pr_tick = time.monotonic()
                await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(TICK_SECONDS)


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    global _task
    if _task is not None:
        _task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _task
        _task = None
