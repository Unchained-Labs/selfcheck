"""Drives the locally installed Claude Code CLI in headless, read-only mode."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Awaitable

from .config import get_settings

# Tools the review agent may use. Everything else is denied, twice over:
# once by the allowlist, once by --restricted + the explicit denylist.
ALLOWED_TOOLS = ["Read", "Grep", "Glob"]
DENIED_TOOLS = [
    "Bash", "Write", "Edit", "MultiEdit", "NotebookEdit", "WebFetch", "WebSearch",
    "Task", "Agent", "TodoWrite", "KillShell", "BashOutput", "SlashCommand",
]


class ClaudeNotFound(RuntimeError):
    pass


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


def resolve_claude_bin() -> str:
    settings = get_settings()
    candidate = settings.claude_bin
    found = shutil.which(candidate)
    if found:
        return found
    if Path(candidate).is_file() and os.access(candidate, os.X_OK):
        return candidate
    raise ClaudeNotFound(
        f"could not find the Claude Code CLI at {candidate!r}. "
        "Install it, or set SELFCHECK_CLAUDE_BIN to its full path."
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


# Secrets the review agent has no business holding. It reads a checkout; it
# never talks to a forge, so a leaked token could only ever be a liability.
STRIPPED_ENV = ("GITHUB_TOKEN", "GITLAB_TOKEN", "GH_TOKEN", "SELFCHECK_GIT_TOKEN")


def build_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the Claude subprocess, with forge credentials removed."""
    env = dict(os.environ if base is None else base)
    for key in STRIPPED_ENV:
        env.pop(key, None)
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    return env


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
) -> RunResult:
    settings = get_settings()
    timeout = timeout or settings.run_timeout_seconds
    argv = build_argv(cwd=cwd, extra_dirs=extra_dirs or [], model=settings.claude_model)
    if system_append:
        argv += ["--append-system-prompt", system_append]

    env = build_env()

    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    result = RunResult(ok=False)
    tool_calls: list[dict[str, Any]] = []
    text_chunks: list[str] = []
    log_fh = log_path.open("w", encoding="utf-8") if log_path else None
    if log_path:
        result.log_path = str(log_path)

    async def pump_stdout() -> None:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            raw = line.decode("utf-8", errors="replace").strip()
            if not raw:
                continue
            if log_fh:
                log_fh.write(raw + "\n")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            await _handle_message(msg)

    async def _handle_message(msg: dict[str, Any]) -> None:
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
                    tool_calls.append(summary)
                    if on_event:
                        await on_event({"kind": "tool", **summary})
            return

        if mtype == "result":
            result.cost_usd = float(msg.get("total_cost_usd") or 0.0)
            result.duration_ms = int(msg.get("duration_ms") or 0)
            result.num_turns = int(msg.get("num_turns") or 0)
            if msg.get("subtype") == "success":
                result.ok = True
                result.text = msg.get("result") or "".join(text_chunks)
            else:
                result.ok = False
                result.error = msg.get("subtype") or "claude run failed"
                result.text = msg.get("result") or "".join(text_chunks)
            if on_event:
                await on_event(
                    {
                        "kind": "result",
                        "ok": result.ok,
                        "cost_usd": result.cost_usd,
                        "duration_ms": result.duration_ms,
                        "num_turns": result.num_turns,
                    }
                )

    stderr_buf: list[str] = []

    async def pump_stderr() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_buf.append(line.decode("utf-8", errors="replace"))

    try:
        assert proc.stdin is not None
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()

        await asyncio.wait_for(
            asyncio.gather(pump_stdout(), pump_stderr(), proc.wait()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        await _terminate(proc)
        result.ok = False
        result.error = f"claude run exceeded {timeout}s and was killed"
    except asyncio.CancelledError:
        # Cancelling the run must actually stop the work. CancelledError is a
        # BaseException, so without this the subprocess would outlive the task
        # and keep burning tokens after the user hit Cancel.
        await _terminate(proc)
        raise
    except Exception as exc:  # noqa: BLE001
        await _terminate(proc)
        result.ok = False
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if log_fh:
            log_fh.close()

    result.tool_calls = tool_calls
    if not result.text:
        result.text = "".join(text_chunks)
    if not result.ok and not result.error:
        tail = "".join(stderr_buf)[-2000:].strip()
        result.error = tail or f"claude exited with code {proc.returncode}"
    return result


async def _terminate(proc: asyncio.subprocess.Process) -> None:
    """Stop the CLI, politely then not."""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=5)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        # Shielded: we are often already being cancelled, and still need to reap.
        with contextlib.suppress(asyncio.TimeoutError, asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=5)


async def probe() -> dict[str, Any]:
    """Cheap health check for the CLI: version + whether it is on PATH."""
    try:
        binpath = resolve_claude_bin()
    except ClaudeNotFound as exc:
        return {"available": False, "error": str(exc)}
    try:
        proc = await asyncio.create_subprocess_exec(
            binpath, "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        return {
            "available": proc.returncode == 0,
            "path": binpath,
            "version": out.decode().strip(),
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "path": binpath, "error": str(exc)}
