"""Cursor Agent CLI (`cursor-agent`), in its read-only "ask" mode."""

from __future__ import annotations

import time
from typing import Any

from ..config import get_settings
from ..subproc import CliNotFound, child_env, probe_version, resolve_bin, run_cli
from .base import ReviewTask, RunResult

BRIEF_NAME = "selfcheck-review-brief.md"


def resolve_cursor_bin() -> str:
    return resolve_bin(
        get_settings().cursor_bin, what="Cursor Agent", env_var="SELFCHECK_CURSOR_BIN"
    )


def build_argv(*, workspace: str, brief_dir: str, model: str) -> list[str]:
    argv = [
        resolve_cursor_bin(),
        "--print",
        "--output-format", "stream-json",
        # "ask" is Cursor's read-only Q&A mode: no edits, no shell.
        "--mode", "ask",
        "--sandbox", "enabled",
        "--trust",
        "--workspace", workspace,
        "--add-dir", brief_dir,
        # Deliberately no --approve-mcps: MCP servers stay unapproved, so none load.
    ]
    if model:
        argv += ["--model", model]
    return argv


def _summarise(call: dict[str, Any]) -> dict[str, Any]:
    """`{"readToolCall": {"args": {...}}}` -> `{"tool": "read", "detail": path}`."""
    for key, body in call.items():
        args = (body or {}).get("args") or {}
        detail = args.get("path") or args.get("pattern") or args.get("globPattern") or ""
        return {"tool": key.removesuffix("ToolCall"), "detail": str(detail)[:200]}
    return {"tool": "tool", "detail": ""}


class CursorEngine:
    id = "cursor"
    label = "Cursor Agent"
    kind = "cli"
    read_only = (
        "--mode ask (Cursor's read-only mode), sandbox enabled, no MCP approval, "
        "chmod read-only checkout."
    )

    def model(self) -> str:
        return get_settings().cursor_model

    async def probe(self) -> dict[str, Any]:
        try:
            return await probe_version(resolve_cursor_bin())
        except CliNotFound as exc:
            return {"available": False, "error": str(exc)}

    async def review(self, task: ReviewTask) -> RunResult:
        assert task.work_dir is not None
        # The prompt goes in a file rather than argv: a large diff is past the
        # kernel's per-argument limit, and cursor-agent takes its prompt as one.
        brief = task.work_dir / BRIEF_NAME
        brief.write_text(f"{task.system}\n\n---\n\n{task.prompt}", encoding="utf-8")
        workspace = str(task.cwd or task.work_dir)
        argv = build_argv(workspace=workspace, brief_dir=str(task.work_dir), model=self.model())
        argv.append(
            f"Read {brief} in full and carry out the code review it describes. "
            "It ends with the output contract; follow it exactly. Do not edit any file."
        )

        result = RunResult(ok=False, model=self.model(), log_path=str(task.log_path))
        texts: list[str] = []
        started = time.monotonic()

        async def handle(msg: dict[str, Any]) -> None:
            mtype = msg.get("type")
            if mtype == "system" and msg.get("subtype") == "init":
                result.model = msg.get("model") or result.model or "cursor default"
                await task.on_event({"kind": "start", "model": result.model})
            elif mtype == "assistant":
                for block in (msg.get("message") or {}).get("content") or []:
                    if block.get("type") == "text":
                        texts.append(block.get("text", ""))
            elif mtype == "tool_call" and msg.get("subtype") == "started":
                summary = _summarise(msg.get("tool_call") or {})
                result.tool_calls.append(summary)
                await task.on_event({"kind": "tool", **summary})
            elif mtype == "result":
                result.ok = msg.get("subtype") == "success" and not msg.get("is_error")
                result.text = msg.get("result") or "".join(texts)
                result.duration_ms = int(msg.get("duration_ms") or 0)
                if not result.ok:
                    result.error = str(msg.get("result") or msg.get("subtype") or "failed")

        outcome = await run_cli(
            argv, stdin_text=None, cwd=task.cwd or task.work_dir, env=child_env(),
            log_path=task.log_path, on_message=handle, timeout=task.timeout, label="cursor-agent",
        )
        result.duration_ms = result.duration_ms or int((time.monotonic() - started) * 1000)
        result.num_turns = len(result.tool_calls)
        result.text = result.text or "".join(texts)
        if outcome.error:
            result.ok, result.error = False, outcome.error
        elif not result.ok and not result.error:
            result.error = outcome.stderr or f"cursor-agent exited with code {outcome.returncode}"
        await task.on_event({"kind": "result", "ok": result.ok, "duration_ms": result.duration_ms})
        return result
