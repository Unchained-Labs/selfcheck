"""OpenAI Codex CLI, driven through `codex exec` in its read-only sandbox."""

from __future__ import annotations

import time
from typing import Any

from ..config import get_settings
from ..subproc import CliNotFound, child_env, probe_version, resolve_bin, run_cli
from .base import ReviewTask, RunResult

# selfcheck mode -> Codex `model_reasoning_effort`.
EFFORT = {"light": "low", "normal": "medium", "thorough": "high"}


def resolve_codex_bin() -> str:
    return resolve_bin(get_settings().codex_bin, what="Codex", env_var="SELFCHECK_CODEX_BIN")


def build_argv(*, cwd: str, model: str, mode: str, last_message: str) -> list[str]:
    argv = [
        resolve_codex_bin(), "exec",
        "--json",
        # The OS-level sandbox: shell commands may read, but cannot write
        # anywhere or reach the network.
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "--color", "never",
        "--cd", cwd,
        "--output-last-message", last_message,
        "-c", f"model_reasoning_effort={EFFORT.get(mode, 'medium')}",
    ]
    if model:
        argv += ["--model", model]
    argv.append("-")  # read the prompt from stdin; a big diff overflows argv
    return argv


def _summarise(item: dict[str, Any]) -> dict[str, Any] | None:
    kind = item.get("type") or ""
    if kind == "command_execution":
        return {"tool": "shell", "detail": str(item.get("command") or "")[:200]}
    if kind in ("file_change", "mcp_tool_call", "web_search"):
        return {"tool": kind, "detail": str(item.get("path") or item.get("query") or "")}
    return None


class CodexEngine:
    id = "codex"
    label = "Codex"
    kind = "cli"
    read_only = (
        "codex exec --sandbox read-only: commands can read but not write or reach "
        "the network; chmod read-only checkout."
    )

    def model(self) -> str:
        return get_settings().codex_model

    async def probe(self) -> dict[str, Any]:
        try:
            return await probe_version(resolve_codex_bin())
        except CliNotFound as exc:
            return {"available": False, "error": str(exc)}

    async def review(self, task: ReviewTask) -> RunResult:
        assert task.work_dir is not None
        last_message = task.work_dir / "last-message.md"
        cwd = str(task.cwd or task.work_dir)
        argv = build_argv(cwd=cwd, model=self.model(), mode=task.mode,
                          last_message=str(last_message))
        result = RunResult(ok=False, model=self.model() or "codex default",
                           log_path=str(task.log_path))
        texts: list[str] = []
        failure: list[str] = []
        started = time.monotonic()
        await task.on_event({"kind": "start", "model": result.model})

        async def handle(msg: dict[str, Any]) -> None:
            mtype = msg.get("type") or (msg.get("msg") or {}).get("type") or ""
            item = msg.get("item") or {}
            if mtype == "item.started":
                summary = _summarise(item)
                if summary:
                    result.tool_calls.append(summary)
                    await task.on_event({"kind": "tool", **summary})
            elif mtype == "item.completed" and item.get("type") == "agent_message":
                texts.append(str(item.get("text") or ""))
            elif mtype == "turn.completed":
                result.num_turns += 1
            elif mtype in ("turn.failed", "error"):
                err = msg.get("error") or {}
                failure.append(str(err.get("message") if isinstance(err, dict) else err)
                               or str(msg.get("message") or "codex reported an error"))

        outcome = await run_cli(
            argv,
            # Codex has no separate system-prompt flag, so selfcheck's standing
            # instructions lead the prompt.
            stdin_text=f"{task.system}\n\n---\n\n{task.prompt}",
            cwd=task.cwd or task.work_dir, env=child_env(), log_path=task.log_path,
            on_message=handle, timeout=task.timeout, label="codex",
        )
        result.duration_ms = int((time.monotonic() - started) * 1000)
        if last_message.is_file():
            result.text = last_message.read_text(encoding="utf-8", errors="replace")
        result.text = result.text or (texts[-1] if texts else "")

        if outcome.error:
            result.error = outcome.error
        elif failure:
            result.error = failure[-1]
        elif outcome.returncode != 0:
            result.error = outcome.stderr or f"codex exited with code {outcome.returncode}"
        else:
            result.ok = bool(result.text)
            result.error = "" if result.ok else "codex finished without a reply"
        await task.on_event({"kind": "result", "ok": result.ok,
                             "duration_ms": result.duration_ms, "num_turns": result.num_turns})
        return result
