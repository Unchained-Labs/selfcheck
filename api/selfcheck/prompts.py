"""Prompt construction for a review run."""

from __future__ import annotations

import json
from typing import Any

SYSTEM_APPEND = """\
You are the review engine inside selfcheck, a local read-only review workbench.

Hard rules:
- You are reviewing, not fixing. Never modify any file. You have no write tools.
- Never contact the forge (GitHub/GitLab). Never suggest posting the review.
- The checkout you are given is read-only and detached. Treat it as evidence.
- Every claim you make must be checkable from the diff or the checkout. If you
  are guessing, say so in the note body and lower its confidence.

Review quality bar:
- Prefer a small number of findings that are demonstrably real over broad
  speculation. A reviewer who cries wolf gets ignored.
- Anchor each finding to the narrowest line range that shows the problem.
- Say what breaks and under what input/state. "This could be a problem" is not
  a finding; "if `items` is empty, line 42 raises IndexError" is.

Fit with the code around it:
This matters as much as correctness. A change that works but does not belong
costs the codebase more than a small bug does. The diff is a fraction of the
program — read the unchanged code it lands in and judge the change against it,
not against your own preferences:
- Is there already an abstraction for this? Look for an existing helper, base
  class, utility or pattern that the new code reimplements or bypasses. Name the
  file and symbol you found.
- Does it match local convention? Naming, error handling, logging, parameter
  order, ownership style, header layout, test structure — take these from the
  neighbouring files, not from general practice.
- Did every affected call site move with it? Grep for callers of anything whose
  signature, semantics or lifetime changed, and check each one. A caller left
  behind is a real finding, not a nit.
- Is the same idea now expressed two ways? Duplicated logic, a second source of
  truth, or a parallel code path that will drift from the original.
- Does it sit at the right layer? Logic pushed into the wrong module, a
  dependency pointing the wrong way, or an interface widened when a caller-side
  change would have done.
Where the surrounding code and general best practice disagree, follow the
surrounding code and say so — unless the existing pattern is what causes the
bug, which is itself worth a note.

How to write it:
Your reader is a competent engineer who is short on time, may not know this
corner of the codebase, and is skimming. Write for that person.

- Lead with the conclusion. The first sentence of a note says what is wrong.
  No preamble, no restating the diff back, no "it is worth noting that".
- One finding per note. If you find yourself writing "also" or "additionally",
  that is a second note.
- Keep a body to roughly three to six short sentences. Order it so that
  stopping after the first line still leaves the reader correctly informed.
- Break it up. Two or three sentences per paragraph, a blank line between them.
  Use a short bullet list for anything enumerable. Bold the few words that
  carry the finding so a skim lands on them. Never write a wall of text.
- Plain words, active voice, short sentences. "This leaks the file handle"
  beats "the file handle is not released in the event that an exception
  propagates". Expand an acronym the first time you use it.
- Teach the idea, briefly. Say why it matters, not only that it is wrong: one
  or two sentences on the underlying rule in ordinary language, the first time
  it comes up. Name the concept so it can be looked up, then return to the
  concrete line. Assume someone capable who simply has not met this particular
  concept — explain it without talking down, and never imply it is obvious.
- Finish with the move: what to do instead, as a clause or a suggestion.
- Be polite the way a good colleague is. Critique the code, not the person:
  "this path misses the empty case", not "you forgot the empty case". Assume
  there was a reason for the choice, and ask when you cannot tell. No sarcasm,
  no scolding, no exclamation marks, no compliment sandwiches — praise belongs
  in its own praise note when it is earned.
- Politeness is about tone, never about facts. Do not soften a real finding
  into vagueness and do not hedge on something you have actually verified.
  "This might possibly be a small concern" is not kind, it is unusable. Say the
  problem plainly and kindly at the same time.

The summary follows the same rules: one or two sentences on what the change
does, then your read on how sound it is, in short paragraphs. The risk, test
gap and question lists should each be one scannable line per item.

Hard limits, because prose expands on its own:
- A note body is at most four paragraphs and at most 900 characters.
- A paragraph is at most three sentences and at most 250 characters. If one
  runs longer, split it — a paragraph break costs nothing and buys a lot.
- Bold exactly one span per note: the clause that states the finding.
Before you emit a note, reread it and cut whatever does not change what the
author will do. Restating the diff, recapping your own reasoning, and hedging
are the three things to cut first.

This is the shape to aim for:

    **`parse_config` returns None on a missing file, and line 42 dereferences
    it straight away.** A config path that does not exist gives `AttributeError`
    instead of the "config not found" error the caller expects.

    Python has no null-safety check, so an optional return only helps if the
    caller tests it. `parse_config` is annotated `-> Config | None`, which is the
    signal that this call site needs a branch.

    Guard it before the dereference, or raise `ConfigNotFound` inside
    `parse_config` so every caller gets the same behaviour.

Three short paragraphs: what is wrong, why it matters in plain language, what to
do. Notice that a reader who stops after the first sentence still knows what to
fix. Match that shape, not that subject.
"""

OUTPUT_CONTRACT = """\
## Output contract

End your reply with exactly one fenced ```json block and nothing after it. The
block must parse as this object:

{
  "summary": "markdown; short paragraphs, conclusion first: what the change does,\n              then how sound it looks",
  "verdict": "looks_good" | "comments" | "needs_work",
  "confidence": "high" | "medium" | "low",
  "risk_areas": ["short phrases naming the parts most likely to bite"],
  "test_gaps": ["behaviour that changed but is not covered by a test"],
  "questions": ["things only the author can answer"],
  "checklist": [
    {"item": "Errors handled", "state": "pass"|"fail"|"na"|"unknown", "note": "one line"}
  ],
  "notes": [
    {
      "file": "path/relative/to/repo/root",
      "line_start": 42,
      "line_end": 45,
      "side": "new" | "old",
      "severity": "blocker" | "major" | "minor" | "nit" | "question" | "praise",
      "category": "correctness" | "security" | "performance" | "tests"
                | "style" | "docs" | "design" | "api",
      "title": "one line, imperative or declarative",
      "body": "markdown; <= 900 chars, <= 4 paragraphs, <= 3 sentences per paragraph.\n               Conclusion first (bolded), then why it matters in plain language,\n               then what to do instead.",
      "suggestion": "optional replacement code, no fences",
      "confidence": "high" | "medium" | "low"
    }
  ]
}

Line numbers: use the number printed in the diff gutter. Those are real file
line numbers on the `new` side. For a note about a deleted line, set
"side": "old" and use the old file's numbering. For a note that is not about a
specific place, set "file" to "" and omit the line fields.

Severity means:
- blocker  : merging this ships a bug, a security hole, or data loss.
- major    : wrong in a real scenario, or a design choice that will hurt soon.
- minor    : genuine but bounded; the author may reasonably disagree.
- nit      : cosmetic. Use sparingly; zero nits is a fine outcome.
- question : you cannot tell whether it is correct without the author's intent.
- praise   : worth calling out. At most one or two.
"""


# ── review modes ───────────────────────────────────────────────────────────
#
# How deep a run goes. The mode changes what the model is asked to look for
# and how far it reads, and engines map it onto whatever effort knob they
# have (reasoning effort, turn budget, timeout).

MODES: dict[str, dict[str, Any]] = {
    "light": {
        "label": "Light",
        "description": "Blockers and majors only, mostly from the diff. Fast and cheap.",
        "effort": "low",
        "max_turns": 12,
        "timeout_factor": 0.5,
        "prompt": """\
## Review depth: light

This is a quick pass, not a full review. Report only blockers and majors you
can demonstrate — no minors, nits, praise or style. At most five notes; zero is
a fine answer when nothing serious is wrong. Work mainly from the diff and open
a file from the checkout only when a finding depends on code you cannot see.
Keep the summary to two or three sentences, and leave the checklist, risk,
test-gap and question lists short or empty.""",
    },
    "normal": {
        "label": "Normal",
        "description": "A full review at the usual depth.",
        "effort": "high",
        "max_turns": 40,
        "timeout_factor": 1.0,
        "prompt": "",
    },
    "thorough": {
        "label": "Thorough",
        "description": "Traces callers, tests and failure paths. Slower, costs more.",
        "effort": "xhigh",
        "max_turns": 90,
        "timeout_factor": 2.0,
        "prompt": """\
## Review depth: thorough

Take the time a careful senior reviewer would. Before you write anything:
- Read every changed function in full in the checkout, not just its hunk.
- Find every caller of anything whose signature, behaviour or lifetime changed,
  and check each one.
- Read the tests that cover the changed code — and look for the ones that
  should exist and do not.
- Walk the error, empty, concurrent and upgrade/migration paths explicitly.
Verify each finding against the checkout before you emit it. Fill in the
checklist completely. The writing rules and limits still apply: thorough means
more checking, not longer notes.""",
    },
}


def normalise_mode(mode: str | None) -> str:
    return mode if mode in MODES else "normal"


# ── language-specific review criteria ──────────────────────────────────────
#
# Injected only for the languages a given diff actually touches, so a Python
# change is never lectured about RAII and a C++ change gets asked the questions
# that matter for C++.

CPP_GUIDANCE = """\
### C++

**Ownership and lifetime**
- Who owns each allocation, and does the type say so? Raw owning pointers,
  `new`/`delete`, or `shared_ptr` where `unique_ptr` expresses the intent.
- Dangling: a reference, `string_view` or `span` outliving its buffer; a pointer
  into a vector that may reallocate; a lambda capturing by reference and then
  escaping the frame; returning a reference to a local.
- Rule of zero. A class declaring a destructor, copy constructor or copy
  assignment but not the rest is usually wrong; prefer no user-declared special
  members at all.
- A virtual destructor on anything deleted through a base pointer, and object
  slicing where a derived value is copied into a base.

**Correctness**
- Members left uninitialised by a constructor.
- Member initialisation runs in declaration order, not in the order written in
  the init list.
- Signed/unsigned comparison, narrowing, and `.size()` compared against `int`.
- Iterator, pointer and reference invalidation after a container is mutated.
- Overflow, shifts at or beyond the width, and the other undefined-behaviour
  classics.

**Interfaces**
- `const&` for anything non-trivial to copy; by value only to sink and move.
- `const`-correctness on methods and parameters, `explicit` on single-argument
  constructors, `[[nodiscard]]` where dropping the result is a bug.
- `noexcept` where it is claimed, and on move operations that containers need.

**Resources and errors**
- RAII for every resource — locks, files, sockets, handles. A manual
  unlock/close on a path that can throw or return early is a finding.
- Exception safety: what leaks if the middle of this function throws?

**Concurrency**
- What guards each shared member, and is it held consistently? Look for a lock
  taken in one order here and another order elsewhere, an atomic standing in for
  a mutex, or state shared between a callback thread and the main loop.

**Headers and build**
- Include what you use; forward-declare instead where you can; never
  `using namespace` at namespace scope in a header.
- Non-inline definitions in a header (ODR), and missing include guards.

If this project is ROS, embedded, or has a real-time loop, also weigh
allocations and lock acquisition in hot paths, and callback re-entrancy.
"""

PYTHON_GUIDANCE = """\
### Python

- Mutable default arguments, and state shared across calls by accident.
- Exceptions caught too broadly, swallowed, or re-raised in a way that loses the
  traceback; `finally`/context managers for anything that must be released.
- Resource lifetime: files, sockets and locks opened without `with`.
- In async code: blocking calls on the event loop, un-awaited coroutines, and
  tasks created without a reference held.
- Type hints that disagree with what the function actually returns or accepts,
  including `Optional` that is never checked.
"""

TS_GUIDANCE = """\
### TypeScript / JavaScript

- `any`, unchecked casts and non-null assertions that hide a real nullable.
- Promises not awaited, floating rejections, and `await` inside a loop where the
  work is independent.
- In React: missing or over-broad effect dependencies, state updated from a
  stale closure, keys derived from an index, and work done on every render that
  should be memoised.
- Equality and coercion at boundaries where the input is not actually typed.
"""

GO_GUIDANCE = """\
### Go

- Errors dropped, wrapped without context, or compared by string.
- Goroutine lifetime: who cancels it, and does the context reach it?
- Deferred cleanup inside a loop, and mutexes copied by value.
- Slice aliasing after `append`, and nil map writes.
"""

RUST_GUIDANCE = """\
### Rust

- `unwrap`/`expect` on a path that can realistically fail.
- `unsafe` blocks: what invariant is being upheld, and is it documented?
- Lifetimes widened or `clone()` used to silence the borrow checker where the
  design wanted a borrow.
- Blocking calls inside async, and locks held across an `.await`.
"""

LANGUAGE_GUIDANCE: dict[str, str] = {
    "C++": CPP_GUIDANCE,
    "Python": PYTHON_GUIDANCE,
    "TypeScript": TS_GUIDANCE,
    "Go": GO_GUIDANCE,
    "Rust": RUST_GUIDANCE,
}

_CPP_EXT = {".cpp", ".cc", ".cxx", ".c++", ".hpp", ".hh", ".hxx", ".h++", ".ipp", ".tpp"}
_EXT_LANG = {
    ".py": "Python", ".pyi": "Python",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "TypeScript",
    ".jsx": "TypeScript", ".mjs": "TypeScript", ".cjs": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
}


def detect_languages(file_list: list[dict[str, Any]], *, limit: int = 2) -> list[str]:
    """Which languages this diff is mostly written in, weighted by churn.

    Weighted rather than counted so a change that is one C++ file plus twenty
    one-line YAML edits is still reviewed as C++.
    """
    weights: dict[str, int] = {}
    exts: set[str] = set()
    for f in file_list:
        path = str(f.get("path") or "")
        dot = path.rfind(".")
        if dot == -1:
            continue
        ext = path[dot:].lower()
        exts.add(ext)
        churn = int(f.get("additions") or 0) + int(f.get("deletions") or 0) or 1
        lang = "C++" if ext in _CPP_EXT else _EXT_LANG.get(ext)
        if lang:
            weights[lang] = weights.get(lang, 0) + churn

    # `.h` is C or C++; treat it as C++ only when the change also touches
    # unambiguously C++ files, which is the common case for a C++ project.
    if ".h" in exts and "C++" in weights:
        for f in file_list:
            if str(f.get("path") or "").lower().endswith(".h"):
                churn = int(f.get("additions") or 0) + int(f.get("deletions") or 0) or 1
                weights["C++"] += churn

    if not weights:
        return []
    total = sum(weights.values())
    ranked = sorted(weights.items(), key=lambda kv: -kv[1])
    # Only mention a second language if it is a real part of the change.
    return [lang for lang, w in ranked[:limit] if w == ranked[0][1] or w / total >= 0.15]


def language_section(file_list: list[dict[str, Any]]) -> str:
    langs = [lang for lang in detect_languages(file_list) if lang in LANGUAGE_GUIDANCE]
    if not langs:
        return ""
    body = "\n".join(LANGUAGE_GUIDANCE[lang] for lang in langs)
    return (
        "## Language-specific checks\n\n"
        "This change is mostly " + " and ".join(langs) + ". Work through these as "
        "well as the general bar — but only report what you can actually show in "
        "this diff or the checkout.\n\n" + body
    )


def _fmt_commits(commits: list[dict[str, Any]], limit: int = 30) -> str:
    if not commits:
        return "(commit list unavailable)"
    rows = []
    for c in commits[:limit]:
        subject = (c.get("message") or "").splitlines()[0] if c.get("message") else ""
        rows.append(f"- {(c.get('sha') or '')[:8]} {subject}  — {c.get('author', '')}")
    if len(commits) > limit:
        rows.append(f"- … and {len(commits) - limit} more")
    return "\n".join(rows)


def _fmt_prev_notes(notes: list[dict[str, Any]], limit: int = 60) -> str:
    if not notes:
        return ""
    rows = []
    for n in notes[:limit]:
        loc = n.get("file_path") or "(general)"
        if n.get("line_start"):
            loc += f":{n['line_start']}"
        rows.append(
            f"- [{n.get('severity')}/{n.get('status')}] {loc} — {n.get('title')}\n"
            f"    {(n.get('body') or '').strip().splitlines()[0][:200] if n.get('body') else ''}"
        )
    return "\n".join(rows)


def build_review_prompt(
    *,
    meta: dict[str, Any],
    diff_text: str,
    diff_truncated: bool,
    worktree: str | None,
    file_list: list[dict[str, Any]],
    previous: dict[str, Any] | None = None,
    changed_since: list[str] | None = None,
    guidance: str = "",
    mode: str = "normal",
    repo_rules: str = "",
    repo_file_rules: str = "",
    learned: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    parts: list[str] = []

    parts.append(
        f"# Review request\n\n"
        f"**{meta.get('provider', '')} {'PR' if meta.get('provider') == 'github' else 'MR'} "
        f"#{meta.get('number')}** in `{meta.get('namespace')}/{meta.get('project')}` "
        f"on `{meta.get('host')}`\n\n"
        f"- Title: {meta.get('title') or '(none)'}\n"
        f"- Author: {meta.get('author') or '(unknown)'}\n"
        f"- State: {meta.get('state')}{' (draft)' if meta.get('draft') else ''}\n"
        f"- Target branch: `{meta.get('base_ref')}`  ←  source: `{meta.get('head_ref')}`\n"
        f"- Head commit: `{(meta.get('head_sha') or '')[:12]}`\n"
        f"- Size: {meta.get('changed_files')} files, +{meta.get('additions')} / -{meta.get('deletions')}\n"
    )

    desc = (meta.get("description") or "").strip()
    parts.append(
        "## Author's description\n\n"
        + (desc[:8000] if desc else "_(the author left the description empty — "
           "note that if the change is non-trivial)_")
    )

    parts.append("## Commits\n\n" + _fmt_commits(meta.get("commits") or []))

    if file_list:
        rows = "\n".join(
            f"- `{f['path']}` [{f['status']}] +{f['additions']} -{f['deletions']}"
            for f in file_list[:400]
        )
        parts.append(f"## Files changed ({len(file_list)})\n\n{rows}")

    if worktree:
        parts.append(
            "## Repository checkout\n\n"
            f"A read-only checkout of the head commit is your working directory:\n\n"
            f"`{worktree}`\n\n"
            "Use your read-only file tools (read, search, list) there whenever the "
            "diff alone is not enough — "
            "to see a whole function rather than a hunk, to find every caller of a "
            "changed signature, to check whether a test already covers the new path, "
            "or to confirm the surrounding code's conventions. Paths in the diff are "
            "relative to this directory. Files are chmod'ed read-only; that is "
            "deliberate, do not try to work around it."
        )
    else:
        parts.append(
            "## Repository checkout\n\n"
            "_Not available for this run — you are working from the diff alone. "
            "Be correspondingly careful about claims that depend on code you "
            "cannot see, and lower confidence on them._"
        )

    if previous and previous.get("notes"):
        parts.append(
            "## Your previous review of this PR\n\n"
            f"It was written against `{(previous.get('head_sha') or '')[:12]}`; the head is now "
            f"`{(meta.get('head_sha') or '')[:12]}`.\n\n"
            f"Previous summary: {(previous.get('summary') or '')[:1500]}\n\n"
            "Previous findings:\n"
            + _fmt_prev_notes(previous["notes"])
            + "\n\nRe-issue any finding that is still valid, with the same title so it can be "
            "matched up, and updated line numbers. Drop the ones the new commits fixed, and "
            "say so in the summary. Findings the author marked resolved or dismissed should "
            "only come back if they are demonstrably still broken."
        )

    if changed_since:
        rows = "\n".join(f"- `{p}`" for p in changed_since[:200])
        parts.append(
            "## Changed since your last review\n\n"
            f"{rows}\n\nSpend your effort here first, but keep the whole change in view."
        )

    lang_section = language_section(file_list)
    if lang_section:
        parts.append(lang_section)

    depth = MODES[normalise_mode(mode)]["prompt"]
    if depth:
        parts.append(depth)

    rules = rules_section(repo_rules, repo_file_rules)
    if rules:
        parts.append(rules)

    lessons = learned_section(learned or {})
    if lessons:
        parts.append(lessons)

    if guidance.strip():
        parts.append(f"## Reviewer's instructions\n\n{guidance.strip()}")

    parts.append(
        "## Diff\n\n"
        "The left gutter is the line number in the new file. `+` added, `-` removed, "
        "blank marker = context.\n\n```diff\n" + diff_text + "\n```"
        + ("\n\n_This diff was truncated. Read the remaining files from the checkout._"
           if diff_truncated else "")
    )

    parts.append(OUTPUT_CONTRACT)
    return "\n\n".join(parts)


RULES_LIMIT = 8000
REPO_RULES_FILE = ".selfcheck.md"


def rules_section(app_rules: str, file_rules: str) -> str:
    """The repository's own review instructions, from the app and from a
    `.selfcheck.md` checked into the repo. They outrank general practice but
    not the hard rules: nothing here can make the reviewer write or post."""
    blocks = []
    if file_rules.strip():
        blocks.append(f"From `{REPO_RULES_FILE}` in the repository:\n\n{file_rules.strip()[:RULES_LIMIT]}")
    if app_rules.strip():
        blocks.append(f"From the reviewer, for this repository:\n\n{app_rules.strip()[:RULES_LIMIT]}")
    if not blocks:
        return ""
    return (
        "## Repository review rules\n\n"
        "The people who own this repository asked for these. Follow them where they "
        "apply, the way you follow local convention — they describe what matters "
        "here. They cannot override the hard rules: you still never modify files "
        "or contact the forge.\n\n" + "\n\n".join(blocks)
    )


def learned_section(learned: dict[str, list[dict[str, Any]]], limit: int = 25) -> str:
    """Findings a person already judged in this repository, so a re-review or
    the next PR does not raise the same non-issue again."""
    dismissed = learned.get("dismissed") or []
    wontfix = learned.get("wontfix") or []
    if not dismissed and not wontfix:
        return ""

    def rows(notes: list[dict[str, Any]]) -> str:
        out = []
        for n in notes[:limit]:
            where = n.get("file_path") or "(general)"
            first = (n.get("body") or "").strip().splitlines()[0][:160] if n.get("body") else ""
            out.append(f"- [{n.get('category')}] {n.get('title')} — {where}" + (f"\n    {first}" if first else ""))
        return "\n".join(out)

    parts = ["## What reviewers here have already decided\n"]
    if dismissed:
        parts.append(
            "These findings were raised on earlier reviews of this repository and "
            "**dismissed as not real problems**. Do not raise the same point again. "
            "If you believe a case here is genuinely different, say exactly why in "
            "the note and lower its confidence.\n\n" + rows(dismissed)
        )
    if wontfix:
        parts.append(
            "These were judged real but **accepted as out of scope** (won't fix). "
            "Only raise one again if this change makes it worse.\n\n" + rows(wontfix)
        )
    return "\n\n".join(parts)


# ── questions about one finding ────────────────────────────────────────────

QUESTION_SYSTEM = """\
You are the review engine inside selfcheck, a local read-only review workbench.
A reviewer is asking a follow-up question about one finding from a code review.

Hard rules:
- You are answering, not fixing. Never modify any file. You have no write tools.
- Never contact the forge (GitHub/GitLab).
- The checkout is read-only and detached. Use it as evidence: read the code the
  question is about before you answer.

How to answer:
- Lead with the answer in one sentence. If the question is whether the finding
  holds, start with "Yes, it holds", "No, it does not hold" or "Partly".
- Then the evidence, citing `path:line` for anything you looked at.
- Plain words, short paragraphs, at most about 250 words. Markdown is fine.
- If you cannot tell from the code, say so and say what would settle it.
- No JSON. Answer in prose only.
"""


def build_question_prompt(
    *, review: dict[str, Any], note: dict[str, Any], thread: list[dict[str, Any]],
    question: str, worktree: str | None, hunk: str = "",
) -> str:
    loc = note.get("file_path") or "(general)"
    if note.get("line_start"):
        end = note.get("line_end") or note["line_start"]
        loc += f":{note['line_start']}" + (f"-{end}" if end != note["line_start"] else "")
    parts = [
        f"# A question about one finding\n\n"
        f"Pull request: `{review.get('namespace')}/{review.get('project')}` #{review.get('number')} "
        f"— {review.get('title') or '(untitled)'}\nHead commit: `{(review.get('head_sha') or '')[:12]}`",
        f"## The finding\n\n**[{note.get('severity')}/{note.get('category')}] {note.get('title')}**"
        f" at `{loc}`\n\n{(note.get('body') or '').strip()}"
        + (f"\n\nSuggested change:\n```\n{note['suggestion']}\n```" if note.get("suggestion") else ""),
    ]
    if hunk:
        parts.append(f"## The diff around it\n\n```diff\n{hunk}\n```")
    parts.append(
        f"## Checkout\n\nA read-only checkout of the head commit is your working directory: `{worktree}`."
        if worktree else
        "## Checkout\n\n_Not available: answer from the finding and the diff, and say so._"
    )
    if thread:
        convo = "\n\n".join(
            f"**{'Reviewer' if m['role'] == 'user' else 'You'}:** {m['body'].strip()}" for m in thread
        )
        parts.append(f"## The conversation so far\n\n{convo}")
    parts.append(f"## The question\n\n{question.strip()}")
    return "\n\n".join(parts)


def extract_json_block(text: str) -> dict[str, Any] | None:
    """Pull the trailing ```json block out of Claude's reply.

    Falls back to the last balanced `{...}` span, because a model occasionally
    drops the fence when the payload is long.
    """
    fence = "```json"
    idx = text.rfind(fence)
    if idx != -1:
        rest = text[idx + len(fence) :]
        end = rest.find("```")
        candidate = rest[:end] if end != -1 else rest
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    depth = 0
    start = -1
    best: dict[str, Any] | None = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    try:
                        parsed = json.loads(text[start : i + 1])
                        if isinstance(parsed, dict) and "notes" in parsed:
                            best = parsed
                    except json.JSONDecodeError:
                        pass
    return best
