"""Review engines: what actually reads the change and writes the notes.

Two kinds:

- **cli** — a coding agent already installed and logged in on this machine
  (Claude Code, Codex, Cursor Agent). selfcheck launches it headless, in its
  most restrictive mode, against the read-only checkout.
- **api** — a model behind an HTTP API (Anthropic, or anything that speaks the
  OpenAI chat-completions dialect, local servers included). selfcheck runs the
  tool loop itself and offers only read-only tools.

Imports are lazy so that a missing optional dependency only disables the one
engine that needs it.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .base import Engine, ReviewTask, RunResult

__all__ = ["ENGINE_IDS", "Engine", "ReviewTask", "RunResult", "UnknownEngine",
           "describe_engines", "get_engine"]

ENGINE_IDS = ("claude", "codex", "cursor", "anthropic", "openai")


class UnknownEngine(ValueError):
    pass


def get_engine(engine_id: str) -> Engine:
    if engine_id == "claude":
        from .claude import ClaudeCodeEngine
        return ClaudeCodeEngine()
    if engine_id == "codex":
        from .codex import CodexEngine
        return CodexEngine()
    if engine_id == "cursor":
        from .cursor import CursorEngine
        return CursorEngine()
    if engine_id == "anthropic":
        from .anthropic_api import AnthropicEngine
        return AnthropicEngine()
    if engine_id == "openai":
        from .openai_api import OpenAICompatibleEngine
        return OpenAICompatibleEngine()
    raise UnknownEngine(f"unknown engine {engine_id!r}; choose one of {', '.join(ENGINE_IDS)}")


async def describe_engines() -> list[dict[str, Any]]:
    """Every engine with whether it can run right now, for /api/status."""
    engines = [get_engine(e) for e in ENGINE_IDS]
    probes = await asyncio.gather(*(e.probe() for e in engines), return_exceptions=True)
    out = []
    for engine, probe in zip(engines, probes):
        if isinstance(probe, BaseException):
            probe = {"available": False, "error": f"{type(probe).__name__}: {probe}"}
        out.append({
            "id": engine.id,
            "label": engine.label,
            "kind": engine.kind,
            "model": engine.model(),
            "read_only": engine.read_only,
            **probe,
        })
    return out
