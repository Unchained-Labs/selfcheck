"""Drives the locally installed Claude Code CLI in headless, read-only mode."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .config import get_settings
from .engines.base import RunResult
from .subproc import STRIPPED_ENV, CliNotFound, child_env, probe_version, resolve_bin, run_cli
from .subproc import terminate as _terminate

__all__ = [
    "ALLOWED_TOOLS", "DENIED_TOOLS", "STRIPPED_ENV", "ClaudeNotFound", "RunResult",
    "build_argv", "build_env", "probe", "resolve_claude_bin", "run_claude", "_terminate",
]

# Tools the review agent may use. Everything else is denied, twice over:
# once by the allowlist, once by --restricted + the explicit denylist.
ALLOWED_TOOLS = ["Read", "Grep", "Glob"]
DENIED_TOOLS = [
    "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch",
    "Task", "Agent", "TodoWrite", "KillShell", "BashOutput", "SlashCommand",
]

ClaudeNotFound = CliNotFound


def resolve_claude_bin() -> str:
    return resolve_bin(
        get_settings().claude_bin, what="Claude Code", env_var="SELFCHECK_CLAUDE_BIN"
    )


def build_argv(*, cwd: Path | None, extra_dirs: list[Path], model: str) -> list[str]:
    argv = [
        resolve_claude_bin(),
        "--print",
        "--output-format", "stream-json",
        "--verbose",
        "--restricted",
        "--permission-prompts", "none",
        "--allowed-tools", *ALLOWED_TOOLS,
        "--disallowed-tools", *DENIED_TOOLS,
        # No MCP servers: an MCP tool could write or call out to the network.
        "--strict-mcp-config",
        "--mcp-config", '{"mcpServers":{}}',
    ]
    if model:
        argv += ["--model", model]
    for d in extra_dirs:
        argv += ["--add-dir", str(d)]
    return argv


def build_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the Claude subprocess, with forge credentials removed."""
    return child_env(base, CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1")


def _summarise_tool_use(block: dict[str, Any]) -> dict[str, Any]:
    name = block.get("name", "")
    inp = block.get("input") or {}
    detail = ""
    if name == "Read":
        detail = str(inp.get("file_path", ""))
    elif name == "Grep":
        detail = f"{inp.get('pattern', '')}  {inp.get('path', '') or ''}".strip()
    elif name == "Glob":
        detail = str(inp.get("pattern", ""))
    return {"tool": name, "detail": detail}


async def run_claude(
    prompt: str,
    *,
    cwd: Path | None,
    extra_dirs: list[Path] | None = None,
    log_path: Path | None = None,
    on_event: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    timeout: int | None = None,
    system_append: str = "",
    model: str | None = None,
) -> RunResult:
    settings = get_settings()
    timeout = timeout or settings.run_timeout_seconds
    argv = build_argv(
        cwd=cwd, extra_dirs=extra_dirs or [],
        model=settings.claude_model if model is None else model,
    )
    if system_append:
        argv += ["--append-system-prompt", system_append]

    result = RunResult(ok=False, log_path=str(log_path) if log_path else "")
    text_chunks: list[str] = []

    async def handle(msg: dict[str, Any]) -> None:
        mtype = msg.get("type")
        if mtype == "system" and msg.get("subtype") == "init":
            result.model = msg.get("model", "") or result.model
            if on_event:
                await on_event({"kind": "start", "model": result.model})
            return

        if mtype == "assistant":
            for block in (msg.get("message") or {}).get("content") or []:
                btype = block.get("type")
                if btype == "text":
                    text_chunks.append(block.get("text", ""))
                elif btype == "tool_use":
                    summary = _summarise_tool_use(block)
                    result.tool_calls.append(summary)
                    if on_event:
                        await on_event({"kind": "tool", **summary})
            return

        if mtype == "result":
            result.cost_usd = float(msg.get("total_cost_usd") or 0.0)
            result.duration_ms = int(msg.get("duration_ms") or 0)
            result.num_turns = int(msg.get("num_turns") or 0)
            result.ok = msg.get("subtype") == "success"
            if not result.ok:
                result.error = msg.get("subtype") or "claude run failed"
            result.text = msg.get("result") or "".join(text_chunks)
            if on_event:
                await on_event({
                    "kind": "result", "ok": result.ok, "cost_usd": result.cost_usd,
                    "duration_ms": result.duration_ms, "num_turns": result.num_turns,
                })

    outcome = await run_cli(
        argv, stdin_text=prompt, cwd=cwd, env=build_env(), log_path=log_path,
        on_message=handle, timeout=timeout, label="claude",
    )
    if outcome.error:
        result.ok = False
        result.error = outcome.error
    if not result.text:
        result.text = "".join(text_chunks)
    if not result.ok and not result.error:
        result.error = outcome.stderr or f"claude exited with code {outcome.returncode}"
    return result


async def probe() -> dict[str, Any]:
    """Cheap health check for the CLI: version + whether it is on PATH."""
    try:
        binpath = resolve_claude_bin()
    except ClaudeNotFound as exc:
        return {"available": False, "error": str(exc)}
    return await probe_version(binpath)
