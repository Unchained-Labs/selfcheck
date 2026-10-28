"""Settings the app can change at runtime, and per-engine model lists."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from fastapi import APIRouter, Body, HTTPException

from .. import service, settings_store
from ..config import get_settings
from ..models import RepoRulesIn
from ..engines import ENGINE_IDS, describe_engines
from ..subproc import CliNotFound

router = APIRouter(prefix="/api", tags=["settings"])

settings_store.on_change(
    lambda key, value: service.resize_slots(value) if key == "max_concurrent_runs" else None
)


@router.get("/settings", summary="Editable settings: current values, .env defaults, overrides")
async def get_settings_view() -> dict[str, Any]:
    return {**settings_store.snapshot(), "engines": await describe_engines()}


@router.patch("/settings", summary="Change settings now; a null value resets to the .env default")
async def patch_settings(changes: dict[str, Any] = Body(...)) -> dict[str, Any]:
    try:
        snap = settings_store.update(changes)
    except settings_store.InvalidSetting as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {**snap, "engines": await describe_engines()}


@router.get("/repo-rules", summary="Review rules for one repository (?repo=host/ns/project), or all")
def repo_rules(repo: str | None = None) -> dict[str, Any]:
    if repo:
        try:
            return {"rules": service.get_repo_rules(*service.split_repo_key(repo))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = service.db.get_conn().execute("SELECT * FROM repo_rules ORDER BY namespace, project").fetchall()
    return {"rules": [dict(r) for r in rows]}


@router.put("/repo-rules", summary="Set a repository's review rules and whether it learns")
def put_repo_rules(body: RepoRulesIn) -> dict[str, Any]:
    try:
        host, ns, project = service.split_repo_key(body.repo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"rules": service.set_repo_rules(host, ns, project, rules=body.rules, learn=body.learn)}


@router.get("/budget", summary="Spend today and this month against the caps")
def budget() -> dict[str, Any]:
    return service.budget_state()


@router.get("/engines/{engine_id}/models",
            summary="Models an engine offers, when it can list them (no tokens spent)")
async def engine_models(engine_id: str) -> dict[str, Any]:
    if engine_id not in ENGINE_IDS:
        raise HTTPException(status_code=404, detail=f"unknown engine {engine_id!r}")
    try:
        models = await _list_models(engine_id)
    except Exception as exc:  # noqa: BLE001
        return {"models": [], "error": f"{type(exc).__name__}: {exc}"}
    return {"models": models, "error": None}


async def _list_models(engine_id: str) -> list[str]:
    s = get_settings()
    if engine_id == "openai":
        headers = {"Authorization": f"Bearer {s.openai_key}"} if s.openai_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{s.openai_base_url.rstrip('/')}/models", headers=headers)
            resp.raise_for_status()
            return sorted(m.get("id", "") for m in resp.json().get("data", []) if m.get("id"))
    if engine_id == "anthropic":
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=s.anthropic_api_key or None)
        try:
            return [m.id async for m in client.models.list(limit=100)]
        finally:
            await client.close()
    if engine_id == "cursor":
        from ..engines.cursor import resolve_cursor_bin

        proc = await asyncio.create_subprocess_exec(
            resolve_cursor_bin(), "--list-models",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return _parse_model_lines(out.decode(errors="replace"))
    # Claude Code and Codex have no listing command; their model is free text.
    return []


def _parse_model_lines(text: str) -> list[str]:
    """`cursor-agent --list-models` prints a human list; keep the ids."""
    ids = []
    for line in text.splitlines():
        token = line.strip().lstrip("-*•").strip().split(" ")[0] if line.strip() else ""
        if token and not token.endswith(":") and token[0].isalnum() and token.lower() not in (
            "available", "models", "model", "current", "tip"
        ):
            ids.append(token)
    return list(dict.fromkeys(ids))


__all__ = ["router", "CliNotFound"]
