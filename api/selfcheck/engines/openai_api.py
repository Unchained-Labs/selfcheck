"""Any OpenAI-compatible chat-completions endpoint.

That covers OpenAI itself, OpenRouter, and the local servers — Ollama
(`http://localhost:11434/v1`), LM Studio (`http://localhost:1234/v1`), vLLM,
llama.cpp — so a review can run without the code leaving the machine.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from ..prompts import MODES, normalise_mode
from .base import ReviewTask, RunResult
from .tools import TOOL_SPECS, TURN_BUDGET_SPENT, RepoTools, summarise_call

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal", "0.0.0.0"}


def is_local(base_url: str) -> bool:
    return (urlparse(base_url).hostname or "") in LOCAL_HOSTS


class OpenAICompatibleEngine:
    id = "openai"
    label = "OpenAI-compatible API"
    kind = "api"
    read_only = (
        "selfcheck runs the loop and exposes only read_file/search/list_files, "
        "confined to the checkout."
    )

    def model(self) -> str:
        return get_settings().openai_model

    async def probe(self) -> dict[str, Any]:
        s = get_settings()
        if not s.openai_model:
            return {"available": False, "error": "set SELFCHECK_OPENAI_MODEL"}
        if not s.openai_key and not is_local(s.openai_base_url):
            return {"available": False,
                    "error": f"set SELFCHECK_OPENAI_API_KEY for {s.openai_base_url}"}
        return {"available": True, "version": s.openai_base_url,
                "local": is_local(s.openai_base_url)}

    async def review(self, task: ReviewTask) -> RunResult:
        s = get_settings()
        model = self.model()
        mode = MODES[normalise_mode(task.mode)]
        result = RunResult(ok=False, model=model, log_path=str(task.log_path))
        if not model:
            result.error = "no model configured: set SELFCHECK_OPENAI_MODEL"
            return result
        tools = RepoTools(task.cwd) if task.cwd else None
        tool_defs = [
            {"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["schema"]}}
            for t in TOOL_SPECS
        ] if tools else None
        headers = {"Authorization": f"Bearer {s.openai_key}"} if s.openai_key else {}
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": task.system},
            {"role": "user", "content": task.prompt},
        ]
        started = time.monotonic()
        await task.on_event({"kind": "start", "model": model})

        log = task.log_path.open("w", encoding="utf-8")
        async with httpx.AsyncClient(
            base_url=s.openai_base_url.rstrip("/"), headers=headers,
            timeout=httpx.Timeout(600.0, connect=15.0),
        ) as client:
            try:
                for turn in range(mode["max_turns"] + 1):
                    body: dict[str, Any] = {"model": model, "messages": messages}
                    if tool_defs and turn < mode["max_turns"]:
                        body["tools"] = tool_defs
                    resp = await client.post("/chat/completions", json=body)
                    if resp.status_code == 400 and tool_defs and "tool" in resp.text.lower():
                        # Plenty of local models have no tool calling. Review from
                        # the diff alone rather than failing outright.
                        await task.on_event({
                            "kind": "warn",
                            "message": f"{model} does not support tools; reviewing from the diff alone",
                        })
                        tool_defs = None
                        resp = await client.post("/chat/completions",
                                                 json={"model": model, "messages": messages})
                    if resp.status_code >= 400:
                        result.error = f"{s.openai_base_url} {resp.status_code}: {resp.text[:500]}"
                        break
                    data = resp.json()
                    log.write(json.dumps(data) + "\n")
                    result.num_turns += 1
                    result.model = data.get("model") or model
                    choice = (data.get("choices") or [{}])[0]
                    msg = choice.get("message") or {}
                    calls = msg.get("tool_calls") or []

                    if not calls or not tools:
                        result.text = msg.get("content") or ""
                        result.ok = bool(result.text)
                        if not result.ok:
                            result.error = f"empty reply (finish_reason={choice.get('finish_reason')})"
                        break

                    messages.append({"role": "assistant", "content": msg.get("content"),
                                     "tool_calls": calls})
                    for call in calls:
                        fn = call.get("function") or {}
                        try:
                            args = json.loads(fn.get("arguments") or "{}")
                        except json.JSONDecodeError:
                            args = {}
                        summary = summarise_call(fn.get("name", ""), args)
                        result.tool_calls.append(summary)
                        await task.on_event({"kind": "tool", **summary})
                        output, _ = await tools.call(fn.get("name", ""), args)
                        messages.append({"role": "tool", "tool_call_id": call.get("id"),
                                         "content": output})
                    if turn + 1 == mode["max_turns"]:
                        messages.append({"role": "user", "content": TURN_BUDGET_SPENT})
            except httpx.HTTPError as exc:
                result.error = f"could not reach {s.openai_base_url}: {exc}"
            finally:
                log.close()

        result.duration_ms = int((time.monotonic() - started) * 1000)
        await task.on_event({"kind": "result", "ok": result.ok,
                             "duration_ms": result.duration_ms, "num_turns": result.num_turns})
        return result
