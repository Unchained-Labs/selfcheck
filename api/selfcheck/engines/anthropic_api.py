"""Claude through the Anthropic API, with selfcheck running the tool loop.

Use this when there is an API key but no Claude Code login — in a container,
say. The model only ever sees the three read-only tools in tools.py.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..prompts import MODES, normalise_mode
from .base import ReviewTask, RunResult
from .tools import TOOL_SPECS, TURN_BUDGET_SPENT, RepoTools, summarise_call

MAX_TOKENS = 32_000

# Server-side refusal fallback: on a policy decline the API re-runs the request
# on a fallback model within the same call. Only some models accept it.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5")

# $ per million tokens: input, output, cache read. Cache writes bill at 1.25x
# input. An unknown model reports no cost rather than a wrong one.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-fable-5": (10.0, 50.0, 1.0),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
}


def cost_usd(model: str, usage: dict[str, int]) -> float:
    price = PRICES.get(model)
    if not price:
        return 0.0
    inp, out, read = price
    return (
        usage.get("input_tokens", 0) * inp
        + usage.get("cache_creation_input_tokens", 0) * inp * 1.25
        + usage.get("cache_read_input_tokens", 0) * read
        + usage.get("output_tokens", 0) * out
    ) / 1_000_000


def _has_credentials(key: str) -> bool:
    return bool(
        key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        or (Path.home() / ".config" / "anthropic").is_dir()
    )


class AnthropicEngine:
    id = "anthropic"
    label = "Anthropic API"
    kind = "api"
    read_only = (
        "selfcheck runs the loop and exposes only read_file/search/list_files, "
        "confined to the checkout."
    )

    def model(self) -> str:
        return get_settings().anthropic_model or "claude-opus-5-5"

    async def probe(self) -> dict[str, Any]:
        try:
            import anthropic
        except ImportError:
            return {"available": False, "error": "the anthropic package is not installed"}
        if not _has_credentials(get_settings().anthropic_api_key):
            return {"available": False,
                    "error": "set ANTHROPIC_API_KEY (or run `ant auth login`)"}
        return {"available": True, "version": f"anthropic {anthropic.__version__}"}

    async def review(self, task: ReviewTask) -> RunResult:
        import anthropic

        settings = get_settings()
        model = self.model()
        mode = MODES[normalise_mode(task.mode)]
        result = RunResult(ok=False, model=model, log_path=str(task.log_path))
        tools = RepoTools(task.cwd) if task.cwd else None
        usage: dict[str, int] = {}
        started = time.monotonic()

        client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key or None, max_retries=3,
        )
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": MAX_TOKENS,
            # Stable first, so the prefix caches across turns of the loop.
            "system": task.system,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": mode["effort"]},
            "cache_control": {"type": "ephemeral"},
        }
        if tools:
            params["tools"] = [
                {"name": t["name"], "description": t["description"],
                 "input_schema": t["schema"]}
                for t in TOOL_SPECS
            ]
        if model in FALLBACK_MODELS:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"

        messages: list[dict[str, Any]] = [{"role": "user", "content": task.prompt}]
        await task.on_event({"kind": "start", "model": model})
        log = task.log_path.open("w", encoding="utf-8")
        try:
            for turn in range(mode["max_turns"] + 1):
                last_turn = turn == mode["max_turns"]
                extra = {"tool_choice": {"type": "none"}} if last_turn and tools else {}
                async with client.beta.messages.stream(
                    **params, **extra, messages=messages,
                ) as stream:
                    resp = await stream.get_final_message()
                log.write(resp.model_dump_json() + "\n")
                result.num_turns += 1
                for key, value in (resp.usage.model_dump() if resp.usage else {}).items():
                    if isinstance(value, int):
                        usage[key] = usage.get(key, 0) + value
                result.model = resp.model or model

                if resp.stop_reason == "pause_turn":
                    messages.append({"role": "assistant", "content": resp.content})
                    continue
                if resp.stop_reason == "refusal":
                    details = getattr(resp, "stop_details", None)
                    category = getattr(details, "category", None) if details else None
                    result.error = f"the model declined to review this ({category or 'refusal'})"
                    break
                if resp.stop_reason == "max_tokens":
                    result.error = f"the reply hit max_tokens ({MAX_TOKENS}) before finishing"
                    result.text = _text(resp.content)
                    break

                calls = [b for b in resp.content if b.type == "tool_use"]
                if resp.stop_reason != "tool_use" or not calls or not tools:
                    result.text = _text(resp.content)
                    result.ok = bool(result.text)
                    if not result.ok:
                        result.error = "the model finished without a reply"
                    break

                messages.append({"role": "assistant", "content": resp.content})
                tool_results: list[dict[str, Any]] = []
                for call in calls:
                    args = call.input if isinstance(call.input, dict) else {}
                    summary = summarise_call(call.name, args)
                    result.tool_calls.append(summary)
                    await task.on_event({"kind": "tool", **summary})
                    output, is_error = await tools.call(call.name, args)
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": call.id,
                        "content": output, "is_error": is_error,
                    })
                content: list[dict[str, Any]] = tool_results
                if turn + 1 == mode["max_turns"]:
                    content = [*tool_results, {"type": "text", "text": TURN_BUDGET_SPENT}]
                # Every result goes back in one message, so parallel calls stay parallel.
                messages.append({"role": "user", "content": content})
        except anthropic.APIStatusError as exc:
            result.error = f"Anthropic API {exc.status_code}: {exc.message}"
        except anthropic.APIConnectionError as exc:
            result.error = f"could not reach the Anthropic API: {exc}"
        finally:
            log.close()
            await client.close()

        result.cost_usd = cost_usd(model, usage)
        result.duration_ms = int((time.monotonic() - started) * 1000)
        await task.on_event({"kind": "result", "ok": result.ok, "cost_usd": result.cost_usd,
                             "duration_ms": result.duration_ms, "num_turns": result.num_turns})
        return result


def _text(content: list[Any]) -> str:
    return "".join(getattr(b, "text", "") for b in content if getattr(b, "type", "") == "text")
