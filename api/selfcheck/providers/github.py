"""GitHub / GitHub Enterprise provider. Read-only."""

from __future__ import annotations

from urllib.parse import quote

from ..config import get_settings
from .base import PullMeta, PullRef, PullSummary, RepoRef
from .http import ReadOnlyClient


def _api_base(host: str) -> str:
    if host in ("github.com", "www.github.com"):
        return "https://api.github.com"
    return f"https://{host}/api/v3"


class GitHubProvider:
    name = "github"

    def __init__(self, host: str) -> None:
        self.host = host
        token = get_settings().token_for(host)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "selfcheck/0.1 (read-only)",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = ReadOnlyClient(_api_base(host), headers)
        self._token = token

    async def fetch_meta(self, ref: PullRef) -> PullMeta:
        path = f"/repos/{quote(ref.namespace)}/{quote(ref.project)}/pulls/{ref.number}"
        pr = await self._client.get_json(path)

        state = "merged" if pr.get("merged_at") else pr.get("state", "unknown")
        base = pr.get("base") or {}
        head = pr.get("head") or {}

        commits: list[dict] = []
        try:
            raw_commits = await self._client.get_json(f"{path}/commits", params={"per_page": 100})
            for c in raw_commits:
                commit = c.get("commit") or {}
                author = commit.get("author") or {}
                commits.append(
                    {
                        "sha": c.get("sha", ""),
                        "message": commit.get("message", ""),
                        "author": author.get("name", ""),
                        "date": author.get("date", ""),
                    }
                )
        except Exception:
            pass

        return PullMeta(
            title=pr.get("title") or "",
            description=pr.get("body") or "",
            author=((pr.get("user") or {}).get("login")) or "",
            state=state,
            draft=bool(pr.get("draft")),
            base_ref=base.get("ref", ""),
            head_ref=head.get("ref", ""),
            base_sha=base.get("sha", ""),
            head_sha=head.get("sha", ""),
            clone_url=((base.get("repo") or {}).get("clone_url")) or "",
            head_clone_url=((head.get("repo") or {}).get("clone_url")) or "",
            changed_files=int(pr.get("changed_files") or 0),
            additions=int(pr.get("additions") or 0),
            deletions=int(pr.get("deletions") or 0),
            provider_updated_at=pr.get("updated_at") or "",
            web_url=pr.get("html_url") or "",
            commits=commits,
            labels=[lbl.get("name", "") for lbl in (pr.get("labels") or [])],
            assignees=[u.get("login", "") for u in (pr.get("assignees") or []) if u],
            reviewers=[u.get("login", "") for u in (pr.get("requested_reviewers") or []) if u],
        )

    async def fetch_diff(self, ref: PullRef, meta: PullMeta) -> str:
        path = f"/repos/{quote(ref.namespace)}/{quote(ref.project)}/pulls/{ref.number}"
        resp = await self._client.get(path, headers={"Accept": "application/vnd.github.v3.diff"})
        resp.raise_for_status()
        return resp.text

    async def list_open_pulls(self, repo: RepoRef, limit: int = 50) -> list[PullSummary]:
        pulls = await self._client.get_json(
            f"/repos/{quote(repo.namespace)}/{quote(repo.project)}/pulls",
            params={"state": "open", "sort": "created", "direction": "desc",
                    "per_page": min(limit, 100)},
        )
        return [
            PullSummary(
                number=int(p["number"]),
                title=p.get("title") or "",
                author=((p.get("user") or {}).get("login")) or "",
                draft=bool(p.get("draft")),
                base_ref=((p.get("base") or {}).get("ref")) or "",
                head_sha=((p.get("head") or {}).get("sha")) or "",
                created_at=p.get("created_at") or "",
                updated_at=p.get("updated_at") or "",
                web_url=p.get("html_url") or repo.pull_url(int(p["number"])),
            )
            for p in pulls
        ]

    def authenticated_clone_url(self, host: str, clone_url: str) -> str:
        if not clone_url or not self._token:
            return clone_url
        return clone_url.replace("https://", f"https://x-access-token:{self._token}@", 1)

    async def aclose(self) -> None:
        await self._client.aclose()
