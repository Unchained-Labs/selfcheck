"""Review runs, live progress streams, and note CRUD."""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from .. import service
from ..events import bus
from ..models import NotePatch, NotesIn, StartRun

router = APIRouter(prefix="/api", tags=["runs"])


def _sse(event: dict[str, Any]) -> str:
    return f"data: {json.dumps(event, separators=(',', ':'))}\n\n"


async def _stream(topic: str, request: Request) -> AsyncIterator[str]:
    queue, replay = await bus.subscribe(topic)
    try:
        for ev in replay:
            yield _sse(ev)
        while True:
            if await request.is_disconnected():
                break
            try:
                ev = await asyncio.wait_for(queue.get(), timeout=20)
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
                continue
            yield _sse(ev)
            if ev.get("kind") in ("done", "failed", "cancelled") and topic.startswith("run_"):
                break
    finally:
        await bus.unsubscribe(topic, queue)


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"}


@router.get("/reviews/{review_id}/runs", summary="Every review run for this PR")
def list_runs(review_id: str) -> dict[str, Any]:
    try:
        service.get_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"runs": service.list_runs(review_id)}


@router.post("/reviews/{review_id}/runs", status_code=202,
             summary="Ask Claude to review (or re-review) this PR")
async def start_run(review_id: str, body: StartRun | None = None) -> dict[str, Any]:
    body = body or StartRun()
    try:
        run = service.create_run(review_id, trigger=body.trigger, guidance=body.guidance)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"run": run}


@router.get("/runs/{run_id}", summary="Run status and results")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        return {"run": service.get_run(run_id)}
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel", summary="Stop a run in progress")
def cancel_run(run_id: str) -> dict[str, Any]:
    try:
        return {"run": service.cancel_run(run_id)}
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/runs/{run_id}/events", summary="Server-sent events for one run")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    return StreamingResponse(
        _stream(run_id, request), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.get("/reviews/{review_id}/stream", summary="Server-sent events for a review")
async def review_events(review_id: str, request: Request) -> StreamingResponse:
    return StreamingResponse(
        _stream(f"review:{review_id}", request),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


# ── notes ─────────────────────────────────────────────────────────────────

@router.get("/reviews/{review_id}/notes", summary="All notes on a review")
def list_notes(review_id: str, run_id: str | None = None) -> dict[str, Any]:
    try:
        service.get_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "notes": service.list_notes(review_id, run_id),
        "counts": service.note_counts(review_id),
    }


@router.post("/reviews/{review_id}/notes", status_code=201,
             summary="Add notes (used by the selfcheck skill and by hand)")
def add_notes(review_id: str, body: NotesIn) -> dict[str, Any]:
    try:
        review = service.get_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    created = service.add_notes(
        review_id,
        [{**n.model_dump(), "file": n.file} for n in body.notes],
        run_id=body.run_id,
        origin=body.origin,
        anchor_sha=review["head_sha"],
    )
    return {"notes": created, "counts": service.note_counts(review_id)}


@router.patch("/notes/{note_id}", summary="Change a note's status, severity or text")
def patch_note(note_id: str, body: NotePatch) -> dict[str, Any]:
    try:
        return {"note": service.update_note(note_id, body.model_dump(exclude_none=True))}
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/notes/{note_id}", summary="Delete a note")
def delete_note(note_id: str) -> dict[str, Any]:
    try:
        service.delete_note(note_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": note_id}
