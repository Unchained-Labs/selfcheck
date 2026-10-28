#!/usr/bin/env python3
"""Seed a demo instance for recording: public pull requests and local demo branches.

    SELFCHECK_DATA_DIR=/tmp/demo SELFCHECK_PORT=7778 make serve   # an empty instance
    python3 branding/video/seed.py --base http://127.0.0.1:7778 --repos /tmp/demo-repos

Everything shown in the promo is real output from a real run, against public
repositories (pallets/click) and two small local repositories this script
creates — never anyone's private code. Reviews run at light depth to keep the
cost to a few cents each. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from pathlib import Path

PUBLIC_PRS = [
    "https://github.com/pallets/click/pull/3896",
    "https://github.com/pallets/click/pull/3878",
    "https://github.com/pallets/click/pull/2731",
]

# (repo, base files, branch, commit message, changed files) — each change has
# one real bug for the review to find.
DEMO_REPOS = {
    "acme/stats-lib": (
        {"stats.py": "def average(xs):\n    return sum(xs) / len(xs)\n\n\ndef spread(xs):\n    return max(xs) - min(xs)\n"},
        "feature/no-builtins",
        "Average and spread without builtins",
        {"stats.py": (
            "def average(xs):\n    total = 0\n    for i in range(1, len(xs)):\n        total += xs[i]\n"
            "    return total / len(xs)\n\n\ndef spread(xs):\n    lo, hi = xs[0], xs[0]\n    for x in xs:\n"
            "        lo = min(lo, x)\n        hi = max(hi, x)\n    return hi - lo\n"
        )},
    ),
    "acme/inventory": (
        {"stock.py": (
            "class Stock:\n    def __init__(self):\n        self.items = {}\n\n"
            "    def add(self, sku, qty):\n        self.items[sku] = self.items.get(sku, 0) + qty\n"
        )},
        "fix/restock",
        "Restock removes items that sell out",
        {"stock.py": (
            "class Stock:\n    def __init__(self):\n        self.items = {}\n\n"
            "    def add(self, sku, qty):\n        self.items[sku] = self.items.get(sku, 0) + qty\n\n"
            "    def remove(self, sku, qty):\n        self.items[sku] -= qty\n        if self.items[sku] == 0:\n"
            "            del self.items[sku]\n\n    def restock(self, levels):\n"
            "        for sku, qty in levels.items():\n            if self.items[sku] < qty:\n"
            "                self.add(sku, qty - self.items[sku])\n"
        )},
    ),
}


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=Ada Example", "-c", "user.email=ada@example.com", *args],
                   cwd=repo, check=True, capture_output=True)


def make_repo(root: Path, name: str) -> Path:
    base, branch, message, changed = DEMO_REPOS[name]
    repo = root / name
    if repo.exists():
        return repo
    repo.mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    for path, text in base.items():
        (repo / path).write_text(text)
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Initial version")
    git(repo, "checkout", "-qb", branch)
    for path, text in changed.items():
        (repo / path).write_text(text)
    git(repo, "commit", "-qam", message)
    return repo


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def __call__(self, method: str, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            self.base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"content-type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.load(resp)

    def wait_run(self, run_id: str, limit: float = 600) -> dict:
        end = time.time() + limit
        while time.time() < end:
            run = self("GET", f"/api/runs/{run_id}")["run"]
            if run["status"] in ("done", "failed", "cancelled"):
                return run
            time.sleep(4)
        raise TimeoutError(run_id)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:7778")
    ap.add_argument("--repos", required=True, help="where to create the local demo repositories")
    ap.add_argument("--second-engine", default="cursor")
    args = ap.parse_args()
    api, root = Api(args.base), Path(args.repos)

    stats = make_repo(root, "acme/stats-lib")
    make_repo(root, "acme/inventory")  # left untracked: the recording adds it live

    runs = []
    for url in [*PUBLIC_PRS, str(stats)]:
        out = api("POST", "/api/reviews", {"url": url, "review_now": True, "mode": "light"})
        print("tracking", out["review"]["project"], out["review"]["number"])
        runs.append(out["run"]["id"])
    for run_id in runs:
        run = api.wait_run(run_id)
        print("  ", run_id, run["status"], run.get("error", "")[:120])

    review = next(r for r in api("GET", "/api/reviews")["reviews"] if r["project"] == "stats-lib")
    detail = api("GET", f"/api/reviews/{review['id']}")
    if detail["notes"]:
        note = detail["notes"][0]
        api("POST", f"/api/notes/{note['id']}/ask",
            {"question": "Does this really hold? What does average([2, 4]) return?"})
    second = api("POST", f"/api/reviews/{review['id']}/second-opinion",
                 {"engine": args.second_engine, "mode": "light"})["run"]
    print("second opinion", api.wait_run(second["id"])["status"])

    try:
        api("POST", "/api/wakeups", {"url": "https://github.com/pallets/click", "mode": "light",
                                     "daily_at": "09:00", "interval_minutes": 1440})
    except Exception as exc:  # noqa: BLE001 - an existing wakeup is fine
        print("wakeup:", exc)
    print("seeded")


if __name__ == "__main__":
    main()
