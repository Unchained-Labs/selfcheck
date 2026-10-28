"""SQLite persistence. Single file, WAL, no ORM."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from .config import get_settings

_local = threading.local()

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS reviews (
    id              TEXT PRIMARY KEY,
    provider        TEXT NOT NULL,           -- github | gitlab
    host            TEXT NOT NULL,
    namespace       TEXT NOT NULL,           -- owner or group/subgroup
    project         TEXT NOT NULL,
    number          INTEGER NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT DEFAULT '',
    description     TEXT DEFAULT '',
    author          TEXT DEFAULT '',
    state           TEXT DEFAULT 'unknown',  -- open | merged | closed
    draft           INTEGER DEFAULT 0,
    base_ref        TEXT DEFAULT '',
    head_ref        TEXT DEFAULT '',
    base_sha        TEXT DEFAULT '',
    head_sha        TEXT DEFAULT '',
    clone_url       TEXT DEFAULT '',
    head_clone_url  TEXT DEFAULT '',
    changed_files   INTEGER DEFAULT 0,
    additions       INTEGER DEFAULT 0,
    deletions       INTEGER DEFAULT 0,
    watch           INTEGER DEFAULT 0,       -- auto re-review on head change
    archived        INTEGER DEFAULT 0,
    pinned          INTEGER DEFAULT 0,
    provider_updated_at TEXT DEFAULT '',
    last_synced_at  TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (host, namespace, project, number)
);

CREATE TABLE IF NOT EXISTS runs (
    id            TEXT PRIMARY KEY,
    review_id     TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    status        TEXT NOT NULL,             -- queued|preparing|analyzing|done|failed|cancelled
    trigger       TEXT NOT NULL DEFAULT 'manual',  -- manual|watch|api
    phase         TEXT DEFAULT '',
    progress      TEXT DEFAULT '',
    base_sha      TEXT DEFAULT '',
    head_sha      TEXT DEFAULT '',
    summary       TEXT DEFAULT '',
    verdict       TEXT DEFAULT '',           -- looks_good|comments|needs_work
    confidence    TEXT DEFAULT '',
    risk_areas    TEXT DEFAULT '[]',
    checklist     TEXT DEFAULT '[]',
    test_gaps     TEXT DEFAULT '[]',
    questions     TEXT DEFAULT '[]',
    error         TEXT DEFAULT '',
    model         TEXT DEFAULT '',
    cost_usd      REAL DEFAULT 0,
    duration_ms   INTEGER DEFAULT 0,
    num_turns     INTEGER DEFAULT 0,
    log_path      TEXT DEFAULT '',
    used_worktree INTEGER DEFAULT 0,
    incremental_from TEXT DEFAULT '',        -- previous head_sha, when incremental
    created_at    TEXT NOT NULL,
    finished_at   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_review ON runs(review_id, created_at DESC);

CREATE TABLE IF NOT EXISTS notes (
    id           TEXT PRIMARY KEY,
    review_id    TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    run_id       TEXT DEFAULT '',
    file_path    TEXT DEFAULT '',            -- empty = general note
    line_start   INTEGER,
    line_end     INTEGER,
    side         TEXT DEFAULT 'new',         -- new | old
    severity     TEXT NOT NULL DEFAULT 'minor',
    category     TEXT NOT NULL DEFAULT 'correctness',
    title        TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL DEFAULT '',
    suggestion   TEXT DEFAULT '',
    confidence   TEXT DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'open',  -- open|resolved|dismissed|wontfix
    origin       TEXT NOT NULL DEFAULT 'claude', -- claude|human
    anchor_sha   TEXT DEFAULT '',
    stale        INTEGER DEFAULT 0,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notes_review ON notes(review_id);
CREATE INDEX IF NOT EXISTS idx_notes_file ON notes(review_id, file_path);

CREATE TABLE IF NOT EXISTS file_state (
    review_id  TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    file_path  TEXT NOT NULL,
    viewed     INTEGER DEFAULT 0,
    viewed_sha TEXT DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (review_id, file_path)
);

CREATE TABLE IF NOT EXISTS diff_cache (
    review_id  TEXT NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    base_sha   TEXT NOT NULL,
    head_sha   TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (review_id, base_sha, head_sha)
);

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id  TEXT NOT NULL,
    run_id     TEXT DEFAULT '',
    kind       TEXT NOT NULL,
    message    TEXT DEFAULT '',
    data       TEXT DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, id);

-- A repository selfcheck wakes up for on a schedule, to pick up new PRs/MRs.
CREATE TABLE IF NOT EXISTS repo_watches (
    id               TEXT PRIMARY KEY,
    provider         TEXT NOT NULL,
    host             TEXT NOT NULL,
    namespace        TEXT NOT NULL,
    project          TEXT NOT NULL,
    url              TEXT NOT NULL,
    enabled          INTEGER DEFAULT 1,
    interval_minutes INTEGER DEFAULT 1440,
    daily_at         TEXT DEFAULT '',         -- HH:MM server-local, daily cadence only
    mode             TEXT DEFAULT '',         -- '' = the global default
    engine           TEXT DEFAULT '',
    include_drafts   INTEGER DEFAULT 0,
    rereview_on_push INTEGER DEFAULT 0,
    target_branch    TEXT DEFAULT '',         -- '' = any
    authors          TEXT DEFAULT '',         -- comma-separated; '' = anyone
    max_per_check    INTEGER DEFAULT 3,
    baseline_at      TEXT DEFAULT '',         -- PRs opened before this are left alone
    last_checked_at  TEXT DEFAULT '',
    next_check_at    TEXT DEFAULT '',
    last_result      TEXT DEFAULT '',
    last_error       TEXT DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (host, namespace, project)
);

-- A conversation about one finding: you ask, the engine answers from the checkout.
CREATE TABLE IF NOT EXISTS note_messages (
    id          TEXT PRIMARY KEY,
    note_id     TEXT NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    review_id   TEXT NOT NULL,
    role        TEXT NOT NULL,                 -- user | assistant
    body        TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'done',  -- pending | done | failed
    engine      TEXT DEFAULT '',
    model       TEXT DEFAULT '',
    cost_usd    REAL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_note_messages ON note_messages(note_id, created_at);

-- Instructions for every review in one repository, written in the app.
CREATE TABLE IF NOT EXISTS repo_rules (
    host        TEXT NOT NULL,
    namespace   TEXT NOT NULL,
    project     TEXT NOT NULL,
    rules       TEXT NOT NULL DEFAULT '',
    learn       INTEGER DEFAULT 1,             -- feed this repo's dismissals back in
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (host, namespace, project)
);
"""

# Columns added after the first release. CREATE TABLE IF NOT EXISTS leaves an
# existing table alone, so an older database gets these through ALTER TABLE.
MIGRATIONS: dict[str, dict[str, str]] = {
    "reviews": {
        "mode": "TEXT DEFAULT ''",            # preferred mode for this PR; '' = default
        "engine": "TEXT DEFAULT ''",
        "repo_watch_id": "TEXT DEFAULT ''",   # set when a wakeup started tracking it
        "assignees": "TEXT DEFAULT '[]'",
        "reviewers": "TEXT DEFAULT '[]'",
    },
    "runs": {
        "mode": "TEXT DEFAULT 'normal'",
        "engine": "TEXT DEFAULT 'claude'",
        # Findings this run raised, by severity. Kept on the run because a
        # re-review replaces the notes themselves.
        "note_counts": "TEXT DEFAULT ''",
        # review | second_opinion. A second opinion never replaces the notes;
        # its findings are kept here and compared against them.
        "kind": "TEXT DEFAULT 'review'",
        "findings": "TEXT DEFAULT ''",
        # What went into the prompt beyond the diff: repo rules, learned
        # dismissals. Shown on the summary so a review is explainable.
        "context": "TEXT DEFAULT ''",
    },
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, columns in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns.items():
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    conn = sqlite3.connect(settings.db_path, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db() -> None:
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()


# ── helpers ───────────────────────────────────────────────────────────────

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def jload(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def jdump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def log_event(review_id: str, run_id: str, kind: str, message: str = "", data: Any = None) -> None:
    with tx() as conn:
        conn.execute(
            "INSERT INTO events (review_id, run_id, kind, message, data, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (review_id, run_id, kind, message, jdump(data or {}), now()),
        )
