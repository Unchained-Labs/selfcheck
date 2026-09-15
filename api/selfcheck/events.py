"""In-process pub/sub so the UI can watch a run live over SSE."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self._history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, topic: str, event: dict[str, Any]) -> None:
        async with self._lock:
            hist = self._history[topic]
            hist.append(event)
            if len(hist) > 500:
                del hist[: len(hist) - 500]
            targets = list(self._subs.get(topic, ()))
        for q in targets:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def subscribe(self, topic: str) -> tuple[asyncio.Queue, list[dict[str, Any]]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        async with self._lock:
            self._subs[topic].add(q)
            replay = list(self._history.get(topic, ()))
        return q, replay

    async def unsubscribe(self, topic: str, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subs.get(topic, set()).discard(q)
            if not self._subs.get(topic):
                self._subs.pop(topic, None)

    async def clear(self, topic: str) -> None:
        async with self._lock:
            self._history.pop(topic, None)


bus = EventBus()
