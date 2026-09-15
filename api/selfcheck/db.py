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
"""


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
