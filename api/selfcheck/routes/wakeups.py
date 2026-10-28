"""Repository wakeups: scheduled checks that review new PRs/MRs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from .. import service, watches
from ..models import AddWakeup, WakeupSettings
from ..providers import UnsupportedUrl

router = APIRouter(prefix="/api/wakeups", tags=["wakeups"])


def _get(watch_id: str) -> dict[str, Any]:
    try:
        return watches.get_watch(watch_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("", summary="Every repository wakeup")
def list_wakeups() -> dict[str, Any]:
    return {"wakeups": watches.list_watches()}


@router.post("", status_code=201, summary="Wake up for a repository on a schedule")
async def add_wakeup(body: AddWakeup) -> dict[str, Any]:
    fields = body.model_dump(exclude={"url", "provider", "include_existing"}, exclude_none=True)
    try:
        watch = await watches.create_watch(
            body.url, provider=body.provider, include_existing=body.include_existing, **fields
        )
    except (UnsupportedUrl, watches.WatchError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502, detail=f"could not list that repository's pull requests: {exc}"
        ) from exc
    return {"wakeup": watch}


@router.get("/{watch_id}", summary="One wakeup")
def get_wakeup(watch_id: str) -> dict[str, Any]:
    return {"wakeup": _get(watch_id)}


@router.patch("/{watch_id}", summary="Change a wakeup's schedule, depth, engine or filters")
def patch_wakeup(watch_id: str, body: WakeupSettings) -> dict[str, Any]:
    _get(watch_id)
    try:
        return {"wakeup": watches.update_watch(watch_id, body.model_dump(exclude_none=True))}
    except watches.WatchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/{watch_id}", summary="Stop waking up for a repository")
def delete_wakeup(watch_id: str) -> dict[str, Any]:
    _get(watch_id)
    watches.delete_watch(watch_id)
    return {"deleted": watch_id}


@router.post("/{watch_id}/check", summary="Check the repository now instead of waiting")
async def check_now(watch_id: str) -> dict[str, Any]:
    _get(watch_id)
    try:
        return await watches.check(watch_id, trigger="manual")
    except watches.WatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{watch_id}/pulls", summary="Open PRs now, and which this wakeup would review")
async def open_pulls(watch_id: str) -> dict[str, Any]:
    _get(watch_id)
    try:
        return {"pulls": await watches.preview(watch_id)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
