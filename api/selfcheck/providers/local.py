"""A branch in a git repository on this machine, reviewed before it is pushed.

There is no forge here, so nothing to post to either. selfcheck reads the
repository through the same git allowlist as everything else — `rev-parse`,
`log`, `diff`, `merge-base` — and the review itself runs in a read-only
worktree of selfcheck's own mirror, never in your working copy. Only committed
work is reviewed: the head is a commit, not your uncommitted edits.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlparse

from .base import PullMeta, PullRef, UnsupportedUrl

LOCAL_HOST = "local"
_SPEC = re.compile(r"^(?P<path>[^@]+?)(?:@(?P<head>[^.@][^@]*?))?(?:\.\.(?P<base>[^@]+))?$")


def looks_local(raw: str) -> bool:
    text = raw.strip()
    return text.startswith(("/", "~", "local:", "file://"))


def local_url(path: Path, head: str, base: str) -> str:
    return f"local://{quote(str(path))}?{urlencode({'head': head, 'base': base})}"


def parse_local_url(url: str) -> tuple[Path, str, str]:
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    return Path(parsed.path), (q.get("head") or [""])[0], (q.get("base") or [""])[0]


def parse_local_spec(raw: str) -> tuple[Path, str, str]:
    """`~/src/app`, `~/src/app@feature`, `~/src/app@feature..main`, or a
    `local://` URL selfcheck wrote itself."""
    text = raw.strip()
    if text.startswith("local://"):
        return parse_local_url(text)
    text = text.removeprefix("local:").removeprefix("file://")
    m = _SPEC.match(text)
    if not m:
        raise UnsupportedUrl(f"could not read a repository path from {raw!r}")
    path = Path(m.group("path").strip()).expanduser().resolve()
    if not (path / ".git").exists():
        raise UnsupportedUrl(f"{path} is not a git repository (no .git there)")
    return path, (m.group("head") or "").strip(), (m.group("base") or "").strip()


def ref_for(path: Path, number: int) -> PullRef:
    parent = str(path.parent).strip("/") or "root"
    return PullRef("local", LOCAL_HOST, parent, path.name, number)


async def _git(args: list[str], repo: Path) -> str:
    from .. import workspace  # lazy: workspace imports this package

    return (await workspace.git(args, repo, timeout=120)).strip()


async def resolve_branches(path: Path, head: str, base: str) -> tuple[str, str]:
    """Fill in the current branch and the repository's default base."""
    if not head:
        head = await _git(["rev-parse", "--abbrev-ref", "HEAD"], path)
        if head == "HEAD":
            raise UnsupportedUrl(f"{path} is on a detached HEAD; name the branch: {path}@<branch>")
    if not base:
        for candidate in ("origin/HEAD", "origin/main", "origin/master", "main", "master"):
            try:
                resolved = await _git(["rev-parse", "--abbrev-ref", candidate], path)
            except Exception:  # noqa: BLE001
                continue
            if resolved and resolved != head:
                base = resolved
                break
        if not base:
            raise UnsupportedUrl(f"could not find a base branch in {path}; use {path}@{head}..<base>")
    return head, base


class LocalProvider:
    name = "local"

    def __init__(self, url: str) -> None:
        self.path, self.head, self.base = parse_local_url(url)

    async def fetch_meta(self, ref: PullRef) -> PullMeta:
        repo = self.path
        head_sha = await _git(["rev-parse", f"{self.head}^{{commit}}"], repo)
        base_tip = await _git(["rev-parse", f"{self.base}^{{commit}}"], repo)
        merge_base = await _git(["merge-base", base_tip, head_sha], repo)
        log = await _git(
            ["log", "--no-color", "--format=%H%x1f%an%x1f%aI%x1f%B%x1e", f"{merge_base}..{head_sha}"],
            repo,
        )
        commits = []
        for entry in log.split("\x1e"):
            fields = entry.strip().split("\x1f")
            if len(fields) == 4:
                commits.append({"sha": fields[0], "author": fields[1], "date": fields[2],
                                "message": fields[3].strip()})
        subjects = [c["message"].splitlines()[0] for c in commits if c["message"]]
        title = subjects[-1] if len(subjects) == 1 else (
            f"{self.head} ({len(commits)} commits)" if commits else f"{self.head} (no new commits)"
        )
        return PullMeta(
            title=title,
            description="\n".join(f"- {s}" for s in reversed(subjects)),
            author=commits[0]["author"] if commits else "",
            state="open",
            base_ref=self.base,
            head_ref=self.head,
            base_sha=merge_base,
            head_sha=head_sha,
            clone_url=str(repo),
            head_clone_url=str(repo),
            changed_files=0,
            web_url="",
            commits=commits,
        )

    async def fetch_diff(self, ref: PullRef, meta: PullMeta) -> str:
        return await _git(
            ["diff", "--no-color", "--no-ext-diff", "--find-renames", meta.base_sha, meta.head_sha],
            self.path,
        ) + "\n"

    def authenticated_clone_url(self, host: str, clone_url: str) -> str:
        return clone_url

    async def aclose(self) -> None:
        return None
