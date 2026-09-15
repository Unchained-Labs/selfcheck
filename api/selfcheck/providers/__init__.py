from __future__ import annotations

from .base import Provider, PullMeta, PullRef, UnsupportedUrl, parse_pull_url
from .github import GitHubProvider
from .gitlab import GitLabProvider
from .http import WriteAttemptBlocked

__all__ = [
    "Provider",
    "PullMeta",
    "PullRef",
    "UnsupportedUrl",
    "WriteAttemptBlocked",
    "parse_pull_url",
    "get_provider",
]


def get_provider(ref: PullRef) -> Provider:
    if ref.provider == "github":
        return GitHubProvider(ref.host)
    if ref.provider == "gitlab":
        return GitLabProvider(ref.host)
    raise UnsupportedUrl(f"unknown provider {ref.provider!r}")
