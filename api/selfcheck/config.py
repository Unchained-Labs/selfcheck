"""Runtime configuration, loaded from environment / .env."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", Path.cwd() / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = Field(default="127.0.0.1", alias="SELFCHECK_HOST")
    port: int = Field(default=7777, alias="SELFCHECK_PORT")
    data_dir: Path = Field(default=REPO_ROOT / "data", alias="SELFCHECK_DATA_DIR")

    github_token: str = Field(default="", alias="GITHUB_TOKEN")
    gitlab_token: str = Field(default="", alias="GITLAB_TOKEN")
    host_tokens_raw: str = Field(default="", alias="SELFCHECK_HOST_TOKENS")

    claude_bin: str = Field(default="claude", alias="SELFCHECK_CLAUDE_BIN")
    claude_model: str = Field(default="", alias="SELFCHECK_CLAUDE_MODEL")
    run_timeout_seconds: int = Field(default=900, alias="SELFCHECK_RUN_TIMEOUT_SECONDS")

    clone_enabled: bool = Field(default=True, alias="SELFCHECK_CLONE_ENABLED")
    cache_max_gb: float = Field(default=10.0, alias="SELFCHECK_CACHE_MAX_GB")

    watch_interval_seconds: int = Field(default=300, alias="SELFCHECK_WATCH_INTERVAL_SECONDS")

    # Comma-separated list of extra origins allowed to call the API.
    extra_cors_origins: str = Field(default="", alias="SELFCHECK_CORS_ORIGINS")

    @field_validator("data_dir", mode="after")
    @classmethod
    def _abs(cls, v: Path) -> Path:
        return v if v.is_absolute() else (REPO_ROOT / v).resolve()

    @property
    def host_tokens(self) -> dict[str, str]:
        """host -> token, merging the dedicated GitHub/GitLab vars."""
        out: dict[str, str] = {}
        if self.host_tokens_raw.strip():
            try:
                parsed = json.loads(self.host_tokens_raw)
                if isinstance(parsed, dict):
                    out.update({str(k).lower(): str(v) for k, v in parsed.items()})
            except json.JSONDecodeError:
                pass
        if self.github_token:
            out.setdefault("github.com", self.github_token)
        if self.gitlab_token:
            out.setdefault("gitlab.com", self.gitlab_token)
        return out

    def token_for(self, host: str) -> str:
        return self.host_tokens.get(host.lower(), "")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "selfcheck.db"

    @property
    def repo_cache_dir(self) -> Path:
        return self.data_dir / "repos"

    @property
    def worktree_dir(self) -> Path:
        return self.data_dir / "worktrees"

    @property
    def log_dir(self) -> Path:
        return self.data_dir / "logs"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.repo_cache_dir, self.worktree_dir, self.log_dir):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()  # type: ignore[call-arg]
    s.ensure_dirs()
    return s
