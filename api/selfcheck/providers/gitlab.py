"""GitLab (SaaS or self-managed) provider. Read-only."""

from __future__ import annotations

from urllib.parse import quote

from ..config import get_settings
from .base import PullMeta, PullRef
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

    async def fetch_meta(self, ref: PullRef) -> PullMeta:
        proj = self._project_path(ref)
        mr = await self._client.get_json(f"/projects/{proj}/merge_requests/{ref.number}")

        diff_refs = mr.get("diff_refs") or {}
        state = mr.get("state", "unknown")
        if state == "opened":
            state = "open"

        # The target project always exists; the source may be a fork.
        target_repo = await self._client.get_json(f"/projects/{proj}")
        head_clone = target_repo.get("http_url_to_repo", "")
        source_id = mr.get("source_project_id")
        if source_id and source_id != mr.get("target_project_id"):
            try:
                src = await self._client.get_json(f"/projects/{source_id}")
                head_clone = src.get("http_url_to_repo", head_clone)
            except Exception:
                pass

        commits: list[dict] = []
        try:
            raw = await self._client.get_json(
                f"/projects/{proj}/merge_requests/{ref.number}/commits",
                params={"per_page": 100},
            )
            for c in raw:
                commits.append(
                    {
                        "sha": c.get("id", ""),
                        "message": c.get("message", "") or c.get("title", ""),
                        "author": c.get("author_name", ""),
                        "date": c.get("created_at", ""),
                    }
                )
        except Exception:
            pass

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
            clone_url=target_repo.get("http_url_to_repo", ""),
            head_clone_url=head_clone,
            changed_files=int((mr.get("changes_count") or "0").rstrip("+") or 0)
            if isinstance(mr.get("changes_count"), str)
            else int(mr.get("changes_count") or 0),
            provider_updated_at=mr.get("updated_at") or "",
            web_url=mr.get("web_url") or "",
            commits=commits,
            labels=list(mr.get("labels") or []),
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

    def authenticated_clone_url(self, host: str, clone_url: str) -> str:
        if not clone_url or not self._token:
            return clone_url
        return clone_url.replace("https://", f"https://oauth2:{self._token}@", 1)

    async def aclose(self) -> None:
        await self._client.aclose()
