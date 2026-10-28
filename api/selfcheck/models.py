"""Request/response bodies for the HTTP API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Severity = Literal["blocker", "major", "minor", "nit", "question", "praise"]
Category = Literal[
    "correctness", "security", "performance", "tests", "style", "docs", "design", "api"
]
NoteStatus = Literal["open", "resolved", "dismissed", "wontfix"]
Verdict = Literal["looks_good", "comments", "needs_work"]
Mode = Literal["light", "normal", "thorough"]
EngineId = Literal["claude", "codex", "cursor", "anthropic", "openai"]


class AddReview(BaseModel):
    url: str = Field(description="GitHub PR or GitLab MR URL, or shorthand like gh:owner/repo#12")
    watch: bool = Field(default=False, description="Auto re-review when the head commit changes")
    review_now: bool = Field(default=False, description="Kick off a review run immediately")
    mode: Mode | None = Field(default=None, description="Depth for the first run")
    engine: EngineId | None = Field(default=None, description="Engine for the first run")


class ReviewFlags(BaseModel):
    watch: bool | None = None
    archived: bool | None = None
    pinned: bool | None = None
    mode: Literal["light", "normal", "thorough", ""] | None = Field(
        default=None, description="Default depth for this PR's runs; '' = global default")
    engine: Literal["claude", "codex", "cursor", "anthropic", "openai", ""] | None = Field(
        default=None, description="Default engine for this PR's runs; '' = global default")


class StartRun(BaseModel):
    guidance: str = Field(
        default="",
        description="Extra instructions for this run, e.g. 'focus on the migration path'",
    )
    trigger: Literal["manual", "api", "watch", "schedule"] = "manual"
    mode: Mode | None = Field(default=None, description="light | normal | thorough")
    engine: EngineId | None = Field(default=None, description="Which engine reviews")


class NoteIn(BaseModel):
    file: str = Field(default="", description="Repo-relative path; empty for a general note")
    line_start: int | None = None
    line_end: int | None = None
    side: Literal["new", "old"] = "new"
    severity: Severity = "minor"
    category: Category = "correctness"
    title: str = ""
    body: str = ""
    suggestion: str = ""
    confidence: Literal["high", "medium", "low", ""] = ""


class NotesIn(BaseModel):
    notes: list[NoteIn]
    run_id: str = ""
    origin: Literal["claude", "human"] = "human"


class NotePatch(BaseModel):
    status: NoteStatus | None = None
    severity: Severity | None = None
    category: Category | None = None
    title: str | None = None
    body: str | None = None
    suggestion: str | None = None
    stale: bool | None = None


class SummaryIn(BaseModel):
    summary: str = ""
    verdict: Verdict = "comments"
    confidence: Literal["high", "medium", "low", ""] = ""
    risk_areas: list[str] = Field(default_factory=list)
    test_gaps: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    run_id: str = ""


class FileViewed(BaseModel):
    path: str
    viewed: bool = True


class WakeupSettings(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = Field(
        default=None, ge=15, description="How often to check; 1440 = daily")
    daily_at: str | None = Field(
        default=None, description="HH:MM (server time) for a daily check; '' = every interval")
    mode: Literal["light", "normal", "thorough", ""] | None = None
    engine: Literal["claude", "codex", "cursor", "anthropic", "openai", ""] | None = None
    include_drafts: bool | None = None
    rereview_on_push: bool | None = Field(
        default=None, description="Also re-review tracked PRs whose head moved")
    target_branch: str | None = Field(default=None, description="Only PRs into this branch")
    authors: str | None = Field(default=None, description="Comma-separated usernames")
    max_per_check: int | None = Field(default=None, ge=1, le=25)


class AddWakeup(WakeupSettings):
    url: str = Field(description="Repository URL (a PR link works too), or gh:owner/repo")
    provider: Literal["github", "gitlab", ""] = Field(
        default="", description="Needed only for a self-hosted host named neither")
    include_existing: bool = Field(
        default=False, description="Also review PRs that are already open now")


class SecondOpinion(BaseModel):
    engine: EngineId | None = Field(default=None, description="Which engine gives the second opinion")
    mode: Mode | None = None


class AskNote(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    engine: EngineId | None = None


class RepoRulesIn(BaseModel):
    repo: str = Field(description="host/namespace/project")
    rules: str | None = Field(default=None, max_length=8000)
    learn: bool | None = Field(default=None, description="Feed this repo's dismissals back in")
