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


class AddReview(BaseModel):
    url: str = Field(description="GitHub PR or GitLab MR URL, or shorthand like gh:owner/repo#12")
    watch: bool = Field(default=False, description="Auto re-review when the head commit changes")
    review_now: bool = Field(default=False, description="Kick off a review run immediately")


class ReviewFlags(BaseModel):
    watch: bool | None = None
    archived: bool | None = None
    pinned: bool | None = None


class StartRun(BaseModel):
    guidance: str = Field(
        default="",
        description="Extra instructions for this run, e.g. 'focus on the migration path'",
    )
    trigger: Literal["manual", "api", "watch"] = "manual"


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
