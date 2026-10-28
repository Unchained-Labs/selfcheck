"""Read-only git workspace: a fetch-only mirror cache plus throwaway worktrees.

Guarantees, in order of how much they matter:

1.  The only git subcommands this module ever runs are in ``ALLOWED_GIT``.
    ``push``, ``commit``, ``tag`` and friends are not in it.
2.  Every mirror has ``remote.origin.pushurl`` pinned to a non-URL, so even a
    hand-run ``git push`` inside the cache fails before touching the network.
3.  Credentials are handed to git through ``GIT_ASKPASS`` rather than baked into
    a remote URL, so tokens never land in ``.git/config`` or in a stored URL.
4.  Worktrees are chmod'ed read-only before Claude is pointed at them.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .config import get_settings
from .providers.base import PullMeta, PullRef

ALLOWED_GIT = frozenset(
    {
        "init", "config", "remote", "fetch", "worktree", "show",
        "cat-file", "rev-parse", "merge-base", "diff", "log", "count-objects",
    }
)


class GitError(RuntimeError):
    pass


class DisallowedGitCommand(RuntimeError):
    pass


@dataclass(slots=True)
class Workspace:
    mirror: Path
    worktree: Path
    head_sha: str
    base_sha: str
    merge_base: str


# ── credential plumbing ────────────────────────────────────────────────────

def _askpass_script() -> Path:
    settings = get_settings()
    path = settings.data_dir / ".git-askpass.sh"
    if not path.exists():
        path.write_text(
            "#!/bin/sh\n"
            "# Written by selfcheck. Echoes the token handed in via env.\n"
            'printf "%s" "$SELFCHECK_GIT_TOKEN"\n'
        )
        path.chmod(0o700)
    return path


def _git_env(token: str) -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GCM_INTERACTIVE"] = "never"
    if token:
        env["GIT_ASKPASS"] = str(_askpass_script())
        env["SELFCHECK_GIT_TOKEN"] = token
    else:
        env.pop("GIT_ASKPASS", None)
        env.pop("SELFCHECK_GIT_TOKEN", None)
    return env


def _url_with_username(clone_url: str, username: str) -> str:
    """Put the username (but never the token) into the URL, so git knows which
    credential to ask GIT_ASKPASS for."""
    if not clone_url.startswith("https://"):
        return clone_url
    parts = urlsplit(clone_url)
    netloc = parts.netloc.split("@", 1)[-1]
    return urlunsplit((parts.scheme, f"{username}@{netloc}", parts.path, "", ""))


def _git(args: list[str], cwd: Path | None, token: str = "", timeout: int = 600) -> str:
    sub = next((a for a in args if not a.startswith("-")), "")
    if sub not in ALLOWED_GIT:
        raise DisallowedGitCommand(f"selfcheck refuses to run `git {sub}`")
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        env=_git_env(token),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


async def git(args: list[str], cwd: Path | None, token: str = "", timeout: int = 600) -> str:
    return await asyncio.to_thread(_git, args, cwd, token, timeout)


# ── file-mode helpers ──────────────────────────────────────────────────────

def _chmod_tree(root: Path, *, writable: bool) -> None:
    add = stat.S_IWUSR
    for path in [root, *root.rglob("*")]:
        try:
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                continue
            if writable:
                path.chmod(stat.S_IMODE(mode) | add)
            else:
                path.chmod(stat.S_IMODE(mode) & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        except OSError:
            continue


def _force_rmtree(path: Path) -> None:
    if not path.exists():
        return
    _chmod_tree(path, writable=True)
    shutil.rmtree(path, ignore_errors=True)


# ── mirror + worktree ──────────────────────────────────────────────────────

def mirror_path(ref: PullRef) -> Path:
    settings = get_settings()
    safe_ns = ref.namespace.replace("/", "__")
    return settings.repo_cache_dir / ref.host / safe_ns / f"{ref.project}.git"


def _fetch_refspecs(ref: PullRef, meta: PullMeta) -> list[str]:
    """Refspecs that resolve the PR head even when it lives in a fork.

    Both forges publish a server-side ref for the merge request head, which is
    why selfcheck never needs to add the fork as a second remote.
    """
    n = ref.number
    specs: list[str] = []
    if ref.provider == "local":
        # The source is a repository on this machine: take its branches and
        # remote-tracking refs, then check out the head by commit.
        return ["+refs/heads/*:refs/selfcheck/local/heads/*",
                "+refs/remotes/*:refs/selfcheck/local/remotes/*"]
    if ref.provider == "github":
        specs.append(f"+refs/pull/{n}/head:refs/selfcheck/{n}/head")
    else:
        specs.append(f"+refs/merge-requests/{n}/head:refs/selfcheck/{n}/head")
    if meta.base_ref:
        specs.append(f"+refs/heads/{meta.base_ref}:refs/selfcheck/{n}/base")
    return specs


async def ensure_mirror(ref: PullRef, meta: PullMeta, token: str) -> Path:
    mirror = mirror_path(ref)
    clone_url = meta.clone_url or f"https://{ref.host}/{ref.full_path}.git"
    username = "x-access-token" if ref.provider == "github" else "oauth2"
    remote_url = _url_with_username(clone_url, username)

    if not (mirror / "HEAD").exists():
        mirror.parent.mkdir(parents=True, exist_ok=True)
        await git(["init", "--bare", "--quiet", str(mirror)], None)
        await git(["remote", "add", "origin", remote_url], mirror)
    else:
        await git(["remote", "set-url", "origin", remote_url], mirror)

    # Belt and braces: make pushing from this cache impossible.
    await git(["config", "remote.origin.pushurl", "selfcheck://read-only"], mirror)
    await git(["config", "gc.auto", "0"], mirror)

    # A partial clone needs a server that supports filters; a local path is
    # cheap to fetch in full anyway.
    partial = [] if ref.provider == "local" else ["--filter=blob:none"]
    await git(
        ["fetch", "--no-tags", "--prune", "--quiet", *partial, "origin", *_fetch_refspecs(ref, meta)],
        mirror,
        token=token,
    )
    return mirror


async def prepare_workspace(ref: PullRef, meta: PullMeta, token: str) -> Workspace:
    settings = get_settings()
    mirror = await ensure_mirror(ref, meta, token)

    head_sha = meta.head_sha or (
        await git(["rev-parse", f"refs/selfcheck/{ref.number}/head"], mirror)
    ).strip()
    base_sha = meta.base_sha
    merge_base = base_sha
    try:
        base_ref = f"refs/selfcheck/{ref.number}/base"
        merge_base = (await git(["merge-base", base_ref, head_sha], mirror, token=token)).strip()
        base_sha = base_sha or merge_base
    except GitError:
        pass

    wt = settings.worktree_dir / f"{ref.host}__{ref.namespace.replace('/', '__')}__{ref.project}__{ref.number}"
    if wt.exists():
        current = ""
        try:
            current = (await git(["rev-parse", "HEAD"], wt)).strip()
        except GitError:
            current = ""
        if current == head_sha:
            _chmod_tree(wt, writable=False)
            return Workspace(mirror, wt, head_sha, base_sha, merge_base)
        await remove_worktree(mirror, wt)

    wt.parent.mkdir(parents=True, exist_ok=True)
    await git(
        ["worktree", "add", "--detach", "--force", str(wt), head_sha],
        mirror,
        token=token,
        timeout=900,
    )
    _chmod_tree(wt, writable=False)
    return Workspace(mirror, wt, head_sha, base_sha, merge_base)


async def remove_worktree(mirror: Path, wt: Path) -> None:
    _chmod_tree(wt, writable=True)
    try:
        await git(["worktree", "remove", "--force", str(wt)], mirror)
    except (GitError, DisallowedGitCommand):
        _force_rmtree(wt)
    try:
        await git(["worktree", "prune"], mirror)
    except GitError:
        pass


async def show_blob(mirror: Path, sha: str, path: str, token: str = "") -> str | None:
    """Read one file at one commit straight out of the mirror."""
    try:
        return await git(["show", f"{sha}:{path}"], mirror, token=token, timeout=120)
    except GitError:
        return None


async def cache_usage_bytes() -> int:
    settings = get_settings()
    total = 0
    for p in settings.repo_cache_dir.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


async def prune_cache() -> dict[str, object]:
    """Drop least-recently-used mirrors once the cache exceeds the cap."""
    settings = get_settings()
    cap = int(settings.cache_max_gb * 1024**3)
    used = await cache_usage_bytes()
    removed: list[str] = []
    if used <= cap:
        return {"used_bytes": used, "cap_bytes": cap, "removed": removed}

    mirrors = sorted(
        (p for p in settings.repo_cache_dir.rglob("*.git") if p.is_dir()),
        key=lambda p: p.stat().st_mtime,
    )
    for m in mirrors:
        if used <= cap:
            break
        size = sum(f.stat().st_size for f in m.rglob("*") if f.is_file())
        _force_rmtree(m)
        removed.append(str(m))
        used -= size
    return {"used_bytes": used, "cap_bytes": cap, "removed": removed}
