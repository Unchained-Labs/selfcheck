"""Background watcher: polls watched reviews and re-reviews when the head moves."""

from __future__ import annotations

import asyncio
import contextlib

from . import db, service
from .config import get_settings

_task: asyncio.Task | None = None


async def _tick() -> None:
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

        active = conn.execute(
            "SELECT 1 FROM runs WHERE review_id=? AND status IN"
            " ('queued','preparing','analyzing') LIMIT 1",
            (review_id,),
        ).fetchone()
        if active:
            continue

        db.log_event(review_id, "", "watch_trigger", f"head -> {updated['head_sha'][:8]}")
        service.create_run(review_id, trigger="watch")


async def _loop() -> None:
    interval = max(30, get_settings().watch_interval_seconds)
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            pass
        await asyncio.sleep(interval)


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
