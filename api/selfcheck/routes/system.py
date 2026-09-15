"""Health, capability probe, cache maintenance."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import claude_runner, workspace
from ..config import get_settings

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health", summary="Liveness")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/status", summary="What selfcheck can and cannot currently do")
async def status() -> dict[str, Any]:
    settings = get_settings()
    tokens = settings.host_tokens
    usage = await workspace.cache_usage_bytes()
    return {
        "read_only": True,
        "claude": await claude_runner.probe(),
        "model": settings.claude_model or "(CLI default)",
        "providers": [
            {"host": host, "token_configured": bool(token)}
            for host, token in sorted(tokens.items())
        ],
        "clone_enabled": settings.clone_enabled,
        "cache": {
            "path": str(settings.repo_cache_dir),
            "used_bytes": usage,
            "cap_bytes": int(settings.cache_max_gb * 1024**3),
        },
        "watch_interval_seconds": settings.watch_interval_seconds,
        "data_dir": str(settings.data_dir),
    }


@router.post("/cache/prune", summary="Evict least-recently-used repo mirrors")
async def prune() -> dict[str, Any]:
    return await workspace.prune_cache()
