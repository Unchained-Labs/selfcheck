"""Settings you can change from the app, without editing .env or restarting.

`.env` and the environment still set the defaults. A value saved here
overrides one for as long as it is saved; clearing it falls back to the
default again. Overrides are applied onto the live Settings object, so every
reader of get_settings() sees them on its next call — the next run picks up a
new engine or model with nothing restarted.

Secrets are deliberately not editable here: API keys and forge tokens stay in
.env, and the app only reports whether one is set.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from . import db, prompts
from .config import Settings, get_settings
from .engines import ENGINE_IDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class InvalidSetting(ValueError):
    pass


def _choice(options: tuple[str, ...] | list[str]) -> Callable[[Any], Any]:
    def check(v: Any) -> str:
        if v not in options:
            raise InvalidSetting(f"must be one of {', '.join(options)}")
        return v
    return check


def _int(lo: int, hi: int) -> Callable[[Any], int]:
    def check(v: Any) -> int:
        try:
            n = int(v)
        except (TypeError, ValueError) as exc:
            raise InvalidSetting("must be a whole number") from exc
        if not lo <= n <= hi:
            raise InvalidSetting(f"must be between {lo} and {hi}")
        return n
    return check


def _text(max_len: int = 200) -> Callable[[Any], str]:
    def check(v: Any) -> str:
        s = str(v or "").strip()
        if len(s) > max_len or any(c in s for c in "\n\r\0"):
            raise InvalidSetting("must be a single short line")
        return s
    return check


def _bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if v in (0, 1, "0", "1", "true", "false"):
        return v in (1, "1", "true")
    raise InvalidSetting("must be true or false")


def _money(v: Any) -> float:
    try:
        n = round(float(v), 2)
    except (TypeError, ValueError) as exc:
        raise InvalidSetting("must be an amount in USD") from exc
    if not 0 <= n <= 100_000:
        raise InvalidSetting("must be between 0 and 100000")
    return n


def _url(v: Any) -> str:
    s = str(v or "").strip().rstrip("/")
    parsed = urlparse(s)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise InvalidSetting("must be an http(s) URL")
    return s


# key -> validator. Keys are Settings attribute names.
EDITABLE: dict[str, Callable[[Any], Any]] = {
    "engine": _choice(ENGINE_IDS),
    "default_mode": _choice(tuple(prompts.MODES)),
    "max_concurrent_runs": _int(1, 8),
    "run_timeout_seconds": _int(60, 7200),
    "claude_model": _text(),
    "codex_model": _text(),
    "cursor_model": _text(),
    "anthropic_model": _text(),
    "openai_model": _text(),
    "openai_base_url": _url,
    "learn_from_dismissals": _bool,
    "daily_budget_usd": _money,
    "monthly_budget_usd": _money,
}

# What .env / the environment said, captured before any override is applied.
_defaults: dict[str, Any] = {}
_listeners: list[Callable[[str, Any], None]] = []


def on_change(fn: Callable[[str, Any], None]) -> None:
    """Call `fn(key, value)` whenever a setting changes (e.g. resize the run pool)."""
    _listeners.append(fn)


def _set_live(settings: Settings, key: str, value: Any) -> None:
    object.__setattr__(settings, key, value)
    for fn in _listeners:
        fn(key, value)


def init() -> None:
    """Create the table and apply saved overrides. Called once at startup."""
    settings = get_settings()
    for key in EDITABLE:
        _defaults.setdefault(key, getattr(settings, key))
    conn = db.get_conn()
    conn.executescript(SCHEMA)
    for row in conn.execute("SELECT key, value FROM app_settings").fetchall():
        if row["key"] not in EDITABLE:
            continue
        try:
            _set_live(settings, row["key"], EDITABLE[row["key"]](db.jload(row["value"], None)))
        except InvalidSetting:
            pass  # a stale value from an older version: ignore it, keep the default


def snapshot() -> dict[str, Any]:
    settings = get_settings()
    overrides = {
        r["key"]: db.jload(r["value"], None)
        for r in db.get_conn().execute("SELECT key, value FROM app_settings").fetchall()
        if r["key"] in EDITABLE
    }
    return {
        "values": {k: getattr(settings, k) for k in EDITABLE},
        "defaults": {k: _defaults.get(k, getattr(settings, k)) for k in EDITABLE},
        "overridden": sorted(overrides),
        "secrets": {
            "anthropic_api_key": bool(settings.anthropic_api_key),
            "openai_api_key": bool(settings.openai_key),
        },
    }


def update(changes: dict[str, Any]) -> dict[str, Any]:
    """Validate everything first, then apply: a bad value changes nothing."""
    settings = get_settings()
    for key in EDITABLE:
        _defaults.setdefault(key, getattr(settings, key))
    cleaned: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for key, value in changes.items():
        if key not in EDITABLE:
            errors[key] = "not a setting the app can change"
            continue
        if value is None:
            cleaned[key] = None  # reset to the .env default
            continue
        try:
            cleaned[key] = EDITABLE[key](value)
        except InvalidSetting as exc:
            errors[key] = str(exc)
    if errors:
        raise InvalidSetting("; ".join(f"{k}: {v}" for k, v in errors.items()))

    ts = db.now()
    with db.tx() as c:
        for key, value in cleaned.items():
            if value is None:
                c.execute("DELETE FROM app_settings WHERE key=?", (key,))
            else:
                c.execute(
                    "INSERT INTO app_settings (key, value, updated_at) VALUES (?,?,?)"
                    " ON CONFLICT(key) DO UPDATE SET value=excluded.value,"
                    " updated_at=excluded.updated_at",
                    (key, db.jdump(value), ts),
                )
    for key, value in cleaned.items():
        _set_live(settings, key, _defaults[key] if value is None else value)
    return snapshot()
