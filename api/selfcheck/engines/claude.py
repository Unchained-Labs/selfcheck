"""Claude Code CLI — the original engine, and still the most locked down."""

from __future__ import annotations

from typing import Any

from .. import claude_runner
from ..config import get_settings
from .base import ReviewTask, RunResult


class ClaudeCodeEngine:
    id = "claude"
    label = "Claude Code"
    kind = "cli"
    read_only = (
        "Read/Grep/Glob only, every write and shell tool denied, --restricted, "
        "no MCP servers, chmod read-only checkout."
    )

    def model(self) -> str:
        return get_settings().claude_model

    async def probe(self) -> dict[str, Any]:
        return await claude_runner.probe()

    async def review(self, task: ReviewTask) -> RunResult:
        return await claude_runner.run_claude(
            task.prompt,
            cwd=task.cwd,
            extra_dirs=[],
            log_path=task.log_path,
            on_event=task.on_event,
            timeout=task.timeout,
            system_append=task.system,
        )
