"""Run a headless agent CLI and stream its JSON-lines output.

Shared by every CLI engine, so the parts that are easy to get wrong — killing
the process on timeout and on cancel, draining both pipes so neither fills and
deadlocks, keeping a raw log — are written once.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Secrets a review agent has no business holding. It reads a checkout; it
# never talks to a forge, so a leaked token could only ever be a liability.
STRIPPED_ENV = ("GITHUB_TOKEN", "GITLAB_TOKEN", "GH_TOKEN", "SELFCHECK_GIT_TOKEN")


class CliNotFound(RuntimeError):
    pass


def resolve_bin(candidate: str, *, what: str, env_var: str) -> str:
    found = shutil.which(candidate)
    if found:
        return found
    if Path(candidate).is_file() and os.access(candidate, os.X_OK):
        return candidate
    raise CliNotFound(
        f"could not find the {what} CLI at {candidate!r}. "
        f"Install it, or set {env_var} to its full path."
    )


def child_env(base: dict[str, str] | None = None, **extra: str) -> dict[str, str]:
    """Environment for an agent subprocess, with forge credentials removed."""
    env = dict(os.environ if base is None else base)
    for key in STRIPPED_ENV:
        env.pop(key, None)
    env.update(extra)
    return env


@dataclass
class CliOutcome:
    returncode: int | None
    stderr: str = ""
    error: str = ""          # set when selfcheck had to stop the process


async def run_cli(
    argv: list[str],
    *,
    stdin_text: str | None,
    cwd: Path | None,
    env: dict[str, str],
    log_path: Path | None,
    on_message: Callable[[dict[str, Any]], Awaitable[None]],
    timeout: int,
    label: str = "agent",
) -> CliOutcome:
    """Run `argv`, feeding `stdin_text`, and hand every JSON line to `on_message`."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        stdin=asyncio.subprocess.PIPE if stdin_text is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    log_fh = log_path.open("w", encoding="utf-8") if log_path else None
    stderr_buf: list[str] = []
    outcome = CliOutcome(returncode=None)

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
            if isinstance(msg, dict):
                await on_message(msg)

    async def pump_stderr() -> None:
        assert proc.stderr is not None
        while True:
            line = await proc.stderr.readline()
            if not line:
                break
            stderr_buf.append(line.decode("utf-8", errors="replace"))

    try:
        if stdin_text is not None:
            assert proc.stdin is not None
            proc.stdin.write(stdin_text.encode("utf-8"))
            await proc.stdin.drain()
            proc.stdin.close()

        await asyncio.wait_for(
            asyncio.gather(pump_stdout(), pump_stderr(), proc.wait()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        await terminate(proc)
        outcome.error = f"{label} run exceeded {timeout}s and was killed"
    except asyncio.CancelledError:
        # Cancelling the run must actually stop the work. CancelledError is a
        # BaseException, so without this the subprocess would outlive the task
        # and keep burning tokens after the user hit Cancel.
        await terminate(proc)
        raise
    except Exception as exc:  # noqa: BLE001
        await terminate(proc)
        outcome.error = f"{type(exc).__name__}: {exc}"
    finally:
        if log_fh:
            log_fh.close()

    outcome.returncode = proc.returncode
    outcome.stderr = "".join(stderr_buf)[-2000:].strip()
    return outcome


async def terminate(proc: asyncio.subprocess.Process) -> None:
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


async def probe_version(binpath: str, *args: str) -> dict[str, Any]:
    """`<bin> --version`, as a cheap is-it-installed check."""
    try:
        proc = await asyncio.create_subprocess_exec(
            binpath, *(args or ("--version",)),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
        text = (out or err).decode(errors="replace").strip().splitlines()
        return {
            "available": proc.returncode == 0,
            "path": binpath,
            "version": text[0] if text else "",
        }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "path": binpath, "error": str(exc)}
