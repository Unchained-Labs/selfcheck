from __future__ import annotations

from .base import (
    Provider,
    PullMeta,
    PullRef,
    PullSummary,
    RepoRef,
    UnsupportedUrl,
    parse_pull_url,
    parse_repo_url,
)
from .github import GitHubProvider
from .gitlab import GitLabProvider
from .local import LocalProvider
from .http import WriteAttemptBlocked

__all__ = [
    "Provider",
    "PullMeta",
    "PullRef",
    "PullSummary",
    "RepoRef",
    "UnsupportedUrl",
    "WriteAttemptBlocked",
    "parse_pull_url",
    "parse_repo_url",
    "get_provider",
]


def get_provider(ref: PullRef | RepoRef, url: str = "") -> Provider:
    if ref.provider == "local":
        # A local review carries its path and branches in its URL.
        return LocalProvider(url)  # type: ignore[return-value]
    if ref.provider == "github":
        return GitHubProvider(ref.host)
    if ref.provider == "gitlab":
        return GitLabProvider(ref.host)
    raise UnsupportedUrl(f"unknown provider {ref.provider!r}")
