"""Provider abstraction + URL parsing for GitHub PRs and GitLab MRs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import unquote, urlparse


class UnsupportedUrl(ValueError):
    pass


@dataclass(slots=True)
class PullRef:
    """A forge-agnostic pointer to one pull/merge request."""

    provider: str          # "github" | "gitlab"
    host: str              # github.com, gitlab.com, gitlab.mycorp.com
    namespace: str         # owner, or group/subgroup for GitLab
    project: str           # repo name
    number: int

    @property
    def full_path(self) -> str:
        return f"{self.namespace}/{self.project}"

    @property
    def slug(self) -> str:
        return f"{self.host}/{self.full_path}#{self.number}"


@dataclass(slots=True)
class PullMeta:
    """Metadata for a pull/merge request. All fields are read from the forge."""

    title: str = ""
    description: str = ""
    author: str = ""
    state: str = "unknown"          # open | merged | closed
    draft: bool = False
    base_ref: str = ""
    head_ref: str = ""
    base_sha: str = ""
    head_sha: str = ""
    clone_url: str = ""             # target repo, https
    head_clone_url: str = ""        # source repo (fork-aware), https
    changed_files: int = 0
    additions: int = 0
    deletions: int = 0
    provider_updated_at: str = ""
    web_url: str = ""
    commits: list[dict] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    reviewers: list[str] = field(default_factory=list)   # requested, not yet reviewed


@dataclass(slots=True)
class RepoRef:
    """A forge-agnostic pointer to one repository."""

    provider: str
    host: str
    namespace: str
    project: str

    @property
    def full_path(self) -> str:
        return f"{self.namespace}/{self.project}"

    @property
    def web_url(self) -> str:
        return f"https://{self.host}/{self.full_path}"

    def pull_url(self, number: int) -> str:
        sep = "pull" if self.provider == "github" else "-/merge_requests"
        return f"{self.web_url}/{sep}/{number}"


@dataclass(slots=True)
class PullSummary:
    """One open PR/MR as a repository listing reports it."""

    number: int
    title: str = ""
    author: str = ""
    draft: bool = False
    base_ref: str = ""
    head_sha: str = ""
    created_at: str = ""
    updated_at: str = ""
    web_url: str = ""


class Provider(Protocol):
    name: str

    async def fetch_meta(self, ref: PullRef) -> PullMeta: ...
    async def fetch_diff(self, ref: PullRef, meta: PullMeta) -> str: ...
    async def list_open_pulls(self, repo: RepoRef, limit: int = 50) -> list[PullSummary]: ...
    def authenticated_clone_url(self, host: str, clone_url: str) -> str: ...
    async def aclose(self) -> None: ...


# ── URL parsing ────────────────────────────────────────────────────────────

_GITHUB_PATH = re.compile(r"^/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pulls?/(?P<num>\d+)")
_GITLAB_PATH = re.compile(
    r"^/(?P<path>.+?)/-/merge_requests/(?P<num>\d+)"
)
# Older GitLab (pre-`/-/`) and some proxies: /group/project/merge_requests/12
_GITLAB_LEGACY_PATH = re.compile(r"^/(?P<path>.+?)/merge_requests/(?P<num>\d+)")
# Shorthand accepted in the "add review" box, e.g. `gh:owner/repo#12`.
_SHORTHAND = re.compile(
    r"^(?P<kind>gh|github|gl|gitlab):(?P<path>[\w./~-]+?)(?:#|!|/)(?P<num>\d+)$",
    re.IGNORECASE,
)

_GITHUB_HOSTS = {"github.com", "www.github.com"}


def parse_pull_url(raw: str) -> PullRef:
    """Turn a pasted PR/MR link (or shorthand) into a :class:`PullRef`."""
    text = raw.strip()
    if not text:
        raise UnsupportedUrl("empty url")

    short = _SHORTHAND.match(text)
    if short:
        kind = short.group("kind").lower()
        path = short.group("path").strip("/")
        if "/" not in path:
            raise UnsupportedUrl(f"shorthand needs owner/repo: {text!r}")
        namespace, _, project = path.rpartition("/")
        provider = "github" if kind in ("gh", "github") else "gitlab"
        host = "github.com" if provider == "github" else "gitlab.com"
        return PullRef(provider, host, namespace, project, int(short.group("num")))

    if "://" not in text:
        text = "https://" + text

    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsupportedUrl(f"could not read a host from {raw!r}")
    path = unquote(parsed.path.rstrip("/"))

    gh = _GITHUB_PATH.match(path)
    if gh and (host in _GITHUB_HOSTS or "github" in host):
        return PullRef("github", host, gh.group("owner"), gh.group("repo"), int(gh.group("num")))

    gl = _GITLAB_PATH.match(path) or _GITLAB_LEGACY_PATH.match(path)
    if gl:
        full = gl.group("path").strip("/")
        if "/" not in full:
            raise UnsupportedUrl(f"gitlab url needs namespace/project: {raw!r}")
        namespace, _, project = full.rpartition("/")
        return PullRef("gitlab", host, namespace, project, int(gl.group("num")))

    # A GitHub-shaped path on an unknown host is almost certainly GH Enterprise.
    if gh:
        return PullRef("github", host, gh.group("owner"), gh.group("repo"), int(gh.group("num")))

    raise UnsupportedUrl(
        f"{raw!r} is not a recognised GitHub pull request or GitLab merge request URL"
    )


_REPO_SHORTHAND = re.compile(
    r"^(?P<kind>gh|github|gl|gitlab):(?P<path>[\w./~-]+?)/?$", re.IGNORECASE
)
# Everything after these segments is a page inside the repo, not part of its path.
_REPO_PAGE = re.compile(r"/(?:-|pulls?|merge_requests|tree|blob|issues|commits?)(?:/|$).*$")


def parse_repo_url(raw: str, provider: str = "") -> RepoRef:
    """Turn a pasted repository link (or a PR/MR link, or shorthand) into a
    :class:`RepoRef`. `provider` settles a self-hosted host that names neither forge."""
    text = raw.strip()
    if not text:
        raise UnsupportedUrl("empty url")

    try:
        pr = parse_pull_url(text)
        return RepoRef(pr.provider, pr.host, pr.namespace, pr.project)
    except UnsupportedUrl:
        pass

    short = _REPO_SHORTHAND.match(text)
    if short:
        path = short.group("path").strip("/")
        if "/" not in path:
            raise UnsupportedUrl(f"shorthand needs owner/repo: {text!r}")
        namespace, _, project = path.rpartition("/")
        if short.group("kind").lower() in ("gh", "github"):
            return RepoRef("github", "github.com", namespace, project)
        return RepoRef("gitlab", "gitlab.com", namespace, project)

    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsupportedUrl(f"could not read a host from {raw!r}")
    path = _REPO_PAGE.sub("", unquote(parsed.path)).strip("/")
    path = path.removesuffix(".git")
    if path.count("/") < 1:
        raise UnsupportedUrl(f"{raw!r} does not name a repository (owner/repo)")

    kind = provider.lower()
    if not kind:
        if host in _GITHUB_HOSTS or "github" in host:
            kind = "github"
        elif "gitlab" in host:
            kind = "gitlab"
        else:
            raise UnsupportedUrl(
                f"cannot tell whether {host} is GitHub or GitLab; say which"
            )
    if kind not in ("github", "gitlab"):
        raise UnsupportedUrl(f"unknown provider {provider!r}")
    if kind == "github":
        owner, _, rest = path.partition("/")
        return RepoRef("github", host, owner, rest.split("/")[0])
    namespace, _, project = path.rpartition("/")
    return RepoRef("gitlab", host, namespace, project)
