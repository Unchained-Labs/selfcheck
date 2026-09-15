"""Review CRUD, sync, diff, blobs, per-file state, export."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

from .. import exporting, service
from ..models import AddReview, FileViewed, ReviewFlags
from ..providers import UnsupportedUrl

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


@router.get("", summary="List every tracked pull/merge request")
def list_reviews(include_archived: bool = False) -> dict[str, Any]:
    return {"reviews": service.list_reviews(include_archived)}


@router.post("", status_code=201, summary="Track a PR/MR by URL")
async def add_review(body: AddReview) -> dict[str, Any]:
    try:
        review = service.create_or_get_review(body.url)
    except UnsupportedUrl as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        review = await service.sync_review(review["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=502,
            detail=f"tracked {review['id']}, but fetching it from the forge failed: {exc}",
        ) from exc

    if body.watch:
        review = service.set_flags(review["id"], watch=True)

    run = None
    if body.review_now:
        run = service.create_run(review["id"], trigger="api")
    return {"review": review, "run": run}


@router.get("/{review_id}", summary="One review, with notes, files and the latest run")
async def get_review(review_id: str) -> dict[str, Any]:
    try:
        review = service.get_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "review": review,
        "counts": service.note_counts(review_id),
        "notes": service.list_notes(review_id),
        "file_states": service.file_states(review_id),
        "latest_run": service.latest_run(review_id),
        "runs": service.list_runs(review_id),
    }


@router.delete("/{review_id}", summary="Stop tracking a review and drop its notes")
def delete_review(review_id: str) -> dict[str, Any]:
    try:
        service.delete_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"deleted": review_id}


@router.patch("/{review_id}/flags", summary="Toggle watch / pinned / archived")
def patch_flags(review_id: str, body: ReviewFlags) -> dict[str, Any]:
    try:
        return {"review": service.set_flags(review_id, **body.model_dump(exclude_none=True))}
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{review_id}/sync", summary="Refetch metadata; reports whether the head moved")
async def sync(review_id: str) -> dict[str, Any]:
    try:
        review = await service.sync_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"review": review, "head_changed": review.get("head_changed", False)}


@router.get("/{review_id}/diff", summary="Structured diff: files → hunks → lines")
async def get_diff(review_id: str, refresh: bool = False) -> dict[str, Any]:
    try:
        return await service.fetch_diff_payload(review_id, refresh=refresh)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{review_id}/blob", response_class=PlainTextResponse,
            summary="Whole file at head or base, for expanding diff context")
async def get_blob(
    review_id: str,
    path: str = Query(..., description="Repo-relative file path"),
    side: str = Query("new", pattern="^(new|old)$"),
) -> PlainTextResponse:
    try:
        content = await service.read_blob(review_id, path, side)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if content is None:
        raise HTTPException(
            status_code=404,
            detail="file not available — the repo cache has no checkout for this review yet",
        )
    return PlainTextResponse(content)


@router.post("/{review_id}/files/viewed", summary="Mark a file viewed / unviewed")
def mark_viewed(review_id: str, body: FileViewed) -> dict[str, Any]:
    try:
        review = service.get_review(review_id)
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return service.set_file_viewed(review_id, body.path, body.viewed, review["head_sha"])


@router.get("/{review_id}/export.md", response_class=PlainTextResponse,
            summary="Review notes as markdown, for you to paste wherever you like")
def export_markdown(review_id: str, include_resolved: bool = False) -> PlainTextResponse:
    try:
        return PlainTextResponse(exporting.review_markdown(review_id, include_resolved))
    except service.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
