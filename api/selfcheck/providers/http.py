"""HTTP client that is structurally incapable of mutating a remote forge.

Every provider call goes through :class:`ReadOnlyClient`. It refuses any verb
other than GET/HEAD, so a bug elsewhere in selfcheck cannot turn into a comment,
approval, merge, or label change on someone's pull request.
"""

from __future__ import annotations

from typing import Any

import httpx

SAFE_METHODS = frozenset({"GET", "HEAD"})


class WriteAttemptBlocked(RuntimeError):
    """Raised when something tries to send a mutating request to a forge."""


class ReadOnlyClient:
    def __init__(self, base_url: str, headers: dict[str, str], timeout: float = 30.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    async def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        verb = method.upper()
        if verb not in SAFE_METHODS:
            raise WriteAttemptBlocked(
                f"selfcheck is read-only; refused to send {verb} {url}"
            )
        return await self._client.request(verb, url, **kwargs)

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def get_json(self, url: str, **kwargs: Any) -> Any:
        resp = await self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    async def get_text(self, url: str, **kwargs: Any) -> str:
        resp = await self.get(url, **kwargs)
        resp.raise_for_status()
        return resp.text

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ReadOnlyClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()
