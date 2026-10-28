"""GitLab (SaaS or self-managed) provider. Read-only."""

from __future__ import annotations

from urllib.parse import quote

from ..config import get_settings
from .base import PullMeta, PullRef, PullSummary, RepoRef
from .http import ReadOnlyClient


class GitLabProvider:
    name = "gitlab"

    def __init__(self, host: str) -> None:
        self.host = host
        token = get_settings().token_for(host)
        headers = {"User-Agent": "selfcheck/0.1 (read-only)"}
        if token:
            # PRIVATE-TOKEN covers PATs; project/group tokens work the same way.
            headers["PRIVATE-TOKEN"] = token
        self._client = ReadOnlyClient(f"https://{host}/api/v4", headers)
        self._token = token

    def _project_path(self, ref: PullRef) -> str:
        return quote(f"{ref.namespace}/{ref.project}", safe="")

    async def _optional_json(self, path: str, *, default=None, **kwargs):
        """GET something we can do without.

        Fine-grained GitLab tokens grant permissions per resource, so a token
        that reads merge requests fine may still 403 on the project or commit
        endpoints. Those are enrichment, not essentials.
        """
        try:
            return await self._client.get_json(path, **kwargs)
        except Exception:
            return {} if default is None else default

    async def fetch_meta(self, ref: PullRef) -> PullMeta:
        proj = self._project_path(ref)
        mr = await self._client.get_json(f"/projects/{proj}/merge_requests/{ref.number}")

        diff_refs = mr.get("diff_refs") or {}
        state = mr.get("state", "unknown")
        if state == "opened":
            state = "open"

        # `/projects/:id` is a separate permission on a fine-grained token, and
        # plenty of tokens that can read a merge request cannot read it. The
        # only thing we want from it is the clone URL, which the host and path
        # already determine — so never let it fail the whole fetch.
        fallback_clone = f"https://{self.host}/{ref.full_path}.git"
        target_repo = await self._optional_json(f"/projects/{proj}")
        target_clone = target_repo.get("http_url_to_repo") or fallback_clone

        # The source may be a fork. If we cannot see it, the target clone is
        # still correct: both forges publish the MR head as a ref on the target
        # repo, which is what workspace.py fetches.
        head_clone = target_clone
        source_id = mr.get("source_project_id")
        if source_id and source_id != mr.get("target_project_id"):
            src = await self._optional_json(f"/projects/{source_id}")
            head_clone = src.get("http_url_to_repo") or head_clone

        raw_commits = await self._optional_json(
            f"/projects/{proj}/merge_requests/{ref.number}/commits",
            params={"per_page": 100},
            default=[],
        )
        commits = [
            {
                "sha": c.get("id", ""),
                "message": c.get("message", "") or c.get("title", ""),
                "author": c.get("author_name", ""),
                "date": c.get("created_at", ""),
            }
            for c in raw_commits
        ]

        return PullMeta(
            title=mr.get("title") or "",
            description=mr.get("description") or "",
            author=((mr.get("author") or {}).get("username")) or "",
            state=state,
            draft=bool(mr.get("draft") or mr.get("work_in_progress")),
            base_ref=mr.get("target_branch", ""),
            head_ref=mr.get("source_branch", ""),
            base_sha=diff_refs.get("base_sha", "") or diff_refs.get("start_sha", ""),
            head_sha=diff_refs.get("head_sha", "") or mr.get("sha", ""),
            clone_url=target_clone,
            head_clone_url=head_clone,
            changed_files=int((mr.get("changes_count") or "0").rstrip("+") or 0)
            if isinstance(mr.get("changes_count"), str)
            else int(mr.get("changes_count") or 0),
            provider_updated_at=mr.get("updated_at") or "",
            web_url=mr.get("web_url") or "",
            commits=commits,
            labels=list(mr.get("labels") or []),
            assignees=[u.get("username", "") for u in (mr.get("assignees") or []) if u],
            reviewers=[u.get("username", "") for u in (mr.get("reviewers") or []) if u],
        )

    async def fetch_diff(self, ref: PullRef, meta: PullMeta) -> str:
        """GitLab has no plain-diff endpoint, so rebuild a unified diff from
        the JSON `changes` payload."""
        proj = self._project_path(ref)
        payload = await self._client.get_json(
            f"/projects/{proj}/merge_requests/{ref.number}/changes",
            params={"access_raw_diffs": "true"},
        )
        chunks: list[str] = []
        for change in payload.get("changes") or []:
            old_path = change.get("old_path") or change.get("new_path") or ""
            new_path = change.get("new_path") or old_path
            a = "/dev/null" if change.get("new_file") else f"a/{old_path}"
            b = "/dev/null" if change.get("deleted_file") else f"b/{new_path}"
            header = [f"diff --git a/{old_path} b/{new_path}"]
            if change.get("new_file"):
                header.append("new file mode " + (change.get("b_mode") or "100644"))
            elif change.get("deleted_file"):
                header.append("deleted file mode " + (change.get("a_mode") or "100644"))
            elif change.get("renamed_file"):
                header.append(f"rename from {old_path}")
                header.append(f"rename to {new_path}")
            body = change.get("diff") or ""
            if not body.strip():
                # Binary or otherwise diff-less change.
                chunks.append("\n".join(header) + "\nBinary files differ\n")
                continue
            header.append(f"--- {a}")
            header.append(f"+++ {b}")
            chunks.append("\n".join(header) + "\n" + (body if body.endswith("\n") else body + "\n"))
        return "".join(chunks)

    async def list_open_pulls(self, repo: RepoRef, limit: int = 50) -> list[PullSummary]:
        proj = quote(repo.full_path, safe="")
        mrs = await self._client.get_json(
            f"/projects/{proj}/merge_requests",
            params={"state": "opened", "order_by": "created_at", "sort": "desc",
                    "per_page": min(limit, 100)},
        )
        return [
            PullSummary(
                number=int(m["iid"]),
                title=m.get("title") or "",
                author=((m.get("author") or {}).get("username")) or "",
                draft=bool(m.get("draft") or m.get("work_in_progress")),
                base_ref=m.get("target_branch") or "",
                head_sha=m.get("sha") or "",
                created_at=m.get("created_at") or "",
                updated_at=m.get("updated_at") or "",
                web_url=m.get("web_url") or repo.pull_url(int(m["iid"])),
            )
            for m in mrs
        ]

    def authenticated_clone_url(self, host: str, clone_url: str) -> str:
        if not clone_url or not self._token:
            return clone_url
        return clone_url.replace("https://", f"https://oauth2:{self._token}@", 1)

    async def aclose(self) -> None:
        await self._client.aclose()
