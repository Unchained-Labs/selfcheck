"""What every review engine takes and returns."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

EventSink = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass
class RunResult:
    ok: bool
    text: str = ""
    model: str = ""
    cost_usd: float = 0.0
    duration_ms: int = 0
    num_turns: int = 0
    error: str = ""
    log_path: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ReviewTask:
    prompt: str                 # the review request: PR, diff, contract
    system: str                 # selfcheck's standing instructions
    cwd: Path | None            # read-only checkout, or None for diff-only
    mode: str                   # light | normal | thorough
    timeout: int
    log_path: Path
    on_event: EventSink
    work_dir: Path | None = None  # scratch space outside the checkout, per run


class Engine(Protocol):
    id: str
    label: str
    kind: str                   # "cli" (a local agent) or "api" (selfcheck runs the loop)
    # One sentence on how this engine is kept from writing — shown in the UI.
    read_only: str

    def model(self) -> str: ...
    async def probe(self) -> dict[str, Any]: ...
    async def review(self, task: ReviewTask) -> RunResult: ...


async def noop_event(_event: dict[str, Any]) -> None:
    return None
