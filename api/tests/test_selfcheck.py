"""Tests for selfcheck's parsing and, more importantly, its read-only promises."""

from __future__ import annotations

import asyncio

import pytest

from selfcheck import workspace
from selfcheck.diffparse import parse_unified_diff, render_for_prompt, to_payload
from selfcheck.prompts import extract_json_block
from selfcheck.providers.base import UnsupportedUrl, parse_pull_url
from selfcheck.providers.http import ReadOnlyClient, WriteAttemptBlocked

# ── url parsing ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/pallets/click/pull/2731", ("github", "github.com", "pallets", "click", 2731)),
        ("github.com/a/b/pull/1", ("github", "github.com", "a", "b", 1)),
        ("https://github.com/a/b/pull/12/files", ("github", "github.com", "a", "b", 12)),
        ("gh:torvalds/linux#42", ("github", "github.com", "torvalds", "linux", 42)),
        ("GH:Org/Repo#7", ("github", "github.com", "Org", "Repo", 7)),
        (
            "https://gitlab.com/gitlab-org/gitlab/-/merge_requests/1234",
            ("gitlab", "gitlab.com", "gitlab-org", "gitlab", 1234),
        ),
        (
            "https://gitlab.corp.io/group/sub/proj/-/merge_requests/9",
            ("gitlab", "gitlab.corp.io", "group/sub", "proj", 9),
        ),
        (
            "https://gitlab.com/a/b/merge_requests/3",
            ("gitlab", "gitlab.com", "a", "b", 3),
        ),
        ("gl:group/project!15", ("gitlab", "gitlab.com", "group", "project", 15)),
        (
            "https://ghe.corp.io/team/svc/pull/88",
            ("github", "ghe.corp.io", "team", "svc", 88),
        ),
    ],
)
def test_parse_pull_url(url, expected):
    ref = parse_pull_url(url)
    assert (ref.provider, ref.host, ref.namespace, ref.project, ref.number) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "https://github.com/pallets/click",
        "https://example.com/some/page",
        "gh:noslash#1",
        "https://github.com/a/b/issues/3",
    ],
)
def test_parse_pull_url_rejects(bad):
    with pytest.raises(UnsupportedUrl):
        parse_pull_url(bad)


# ── diff parsing ───────────────────────────────────────────────────────────

SAMPLE = """diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,6 +10,7 @@ def handler(req):
     if not req:
         return None
-    return req.body
+    body = req.body
+    return body.strip()


diff --git a/new.txt b/new.txt
new file mode 100644
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,2 @@
+hello
+world
diff --git a/gone.txt b/gone.txt
deleted file mode 100644
--- a/gone.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-bye
diff --git a/old/name.py b/new/name.py
similarity index 90%
rename from old/name.py
rename to new/name.py
diff --git a/pic.png b/pic.png
index 3333333..4444444 100644
Binary files a/pic.png and b/pic.png differ
"""


def test_parse_unified_diff_structure():
    files = parse_unified_diff(SAMPLE)
    by_path = {f.path: f for f in files}
    assert set(by_path) == {"src/app.py", "new.txt", "gone.txt", "new/name.py", "pic.png"}

    app = by_path["src/app.py"]
    assert app.status == "modified"
    assert (app.additions, app.deletions) == (2, 1)

    assert by_path["new.txt"].status == "added"
    assert by_path["gone.txt"].status == "deleted"
    assert by_path["new/name.py"].status == "renamed"
    assert by_path["new/name.py"].old_path == "old/name.py"
    assert by_path["pic.png"].is_binary


def test_line_numbers_are_absolute():
    """Notes are anchored by line number, so this is the load-bearing detail."""
    app = next(f for f in parse_unified_diff(SAMPLE) if f.path == "src/app.py")
    lines = app.hunks[0].lines

    assert [(ln.kind, ln.old_line, ln.new_line) for ln in lines[:5]] == [
        ("context", 10, 10),
        ("context", 11, 11),
        ("del", 12, None),
        ("add", None, 12),
        ("add", None, 13),
    ]
    # Context after the replacement resumes with both sides advanced correctly.
    assert (lines[5].old_line, lines[5].new_line) == (13, 14)


def test_to_payload_stats():
    payload = to_payload(parse_unified_diff(SAMPLE))
    assert payload["stats"]["files"] == 5
    assert payload["stats"]["additions"] == 2 + 2
    assert payload["stats"]["deletions"] == 1 + 1


def test_render_for_prompt_carries_line_numbers():
    text, truncated = render_for_prompt(parse_unified_diff(SAMPLE))
    assert not truncated
    assert "=== src/app.py [modified] +2 -1 ===" in text
    assert "      12 +    body = req.body" in text
    assert "=== old/name.py -> new/name.py [renamed]" in text
    assert "(binary file, contents not shown)" in text


def test_render_for_prompt_truncates():
    big = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1,1 +1,2000 @@\n" + "".join(
        f"+line {i}\n" for i in range(2000)
    )
    text, truncated = render_for_prompt(parse_unified_diff(big), max_chars=500)
    assert truncated
    assert "diff truncated" in text


def test_empty_diff():
    assert parse_unified_diff("") == []


# ── JSON extraction from Claude's reply ────────────────────────────────────


def test_extract_json_block_fenced():
    reply = 'Here is my review.\n\n```json\n{"verdict": "comments", "notes": []}\n```\n'
    assert extract_json_block(reply) == {"verdict": "comments", "notes": []}


def test_extract_json_block_prefers_last():
    reply = '```json\n{"notes": [1]}\n```\nactually:\n```json\n{"notes": [2]}\n```'
    assert extract_json_block(reply) == {"notes": [2]}


def test_extract_json_block_unfenced_fallback():
    reply = 'I could not use a fence. {"verdict": "needs_work", "notes": [{"title": "x"}]}'
    parsed = extract_json_block(reply)
    assert parsed is not None and parsed["verdict"] == "needs_work"


def test_extract_json_block_gives_up():
    assert extract_json_block("no json at all here") is None


# ── read-only guarantees ───────────────────────────────────────────────────


@pytest.mark.parametrize("verb", ["POST", "PUT", "PATCH", "DELETE", "post", "delete"])
def test_forge_client_refuses_mutating_verbs(verb):
    client = ReadOnlyClient("https://api.github.com", {})
    with pytest.raises(WriteAttemptBlocked):
        asyncio.run(client.request(verb, "/repos/a/b/issues/1/comments"))


def test_forge_client_only_considers_get_and_head_safe():
    from selfcheck.providers.http import SAFE_METHODS

    assert SAFE_METHODS == {"GET", "HEAD"}


def test_forge_client_lets_get_reach_the_transport(monkeypatch):
    """The guard must reject writes without also blocking ordinary reads."""
    client = ReadOnlyClient("https://api.github.com", {})
    seen: dict[str, str] = {}

    async def fake_request(method, url, **kwargs):
        seen["method"] = method
        seen["url"] = url
        return "sentinel"

    monkeypatch.setattr(client._client, "request", fake_request)
    assert asyncio.run(client.get("/repos/a/b/pulls/1")) == "sentinel"
    assert seen == {"method": "GET", "url": "/repos/a/b/pulls/1"}


@pytest.mark.parametrize("sub", ["push", "commit", "tag", "reset", "clean", "am", "apply"])
def test_git_helper_refuses_writing_subcommands(sub, tmp_path):
    with pytest.raises(workspace.DisallowedGitCommand):
        workspace._git([sub, "--whatever"], tmp_path)


def test_git_allowlist_has_no_write_commands():
    forbidden = {
        "push", "commit", "merge", "rebase", "reset", "checkout", "switch",
        "am", "apply", "cherry-pick", "revert", "clean", "gc", "prune", "tag",
        "branch", "stash", "restore", "rm", "mv", "add",
    }
    assert workspace.ALLOWED_GIT & forbidden == set()


def test_credentials_never_enter_the_remote_url():
    url = workspace._url_with_username("https://github.com/a/b.git", "x-access-token")
    assert url == "https://x-access-token@github.com/a/b.git"
    assert "token" not in url.split("@")[0].removeprefix("https://").replace("x-access-token", "")


def test_credentials_replace_an_existing_userinfo():
    url = workspace._url_with_username("https://oldcreds:secret@gitlab.com/a/b.git", "oauth2")
    assert url == "https://oauth2@gitlab.com/a/b.git"
    assert "secret" not in url


def test_git_env_passes_token_out_of_band():
    env = workspace._git_env("s3cret")
    assert env["SELFCHECK_GIT_TOKEN"] == "s3cret"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_ASKPASS"].endswith(".git-askpass.sh")


def test_git_env_clears_token_when_absent():
    env = workspace._git_env("")
    assert "SELFCHECK_GIT_TOKEN" not in env
    assert "GIT_ASKPASS" not in env


def test_claude_runner_denies_write_tools():
    from selfcheck.claude_runner import ALLOWED_TOOLS, DENIED_TOOLS, build_argv

    assert set(ALLOWED_TOOLS) == {"Read", "Grep", "Glob"}
    for tool in ("Bash", "Write", "Edit", "WebFetch", "WebSearch"):
        assert tool in DENIED_TOOLS

    argv = build_argv(cwd=None, extra_dirs=[], model="")
    assert "--restricted" in argv
    assert "--strict-mcp-config" in argv
    assert '{"mcpServers":{}}' in argv
    # The allowlist must come through as separate argv entries, not one blob.
    assert argv[argv.index("--allowed-tools") + 1 : argv.index("--allowed-tools") + 4] == [
        "Read", "Grep", "Glob",
    ]


def test_claude_runner_strips_forge_tokens_from_child_env():
    """The review agent has no business holding a GitHub token."""
    from selfcheck.claude_runner import build_env

    env = build_env(
        {
            "GITHUB_TOKEN": "ghp_leak",
            "GITLAB_TOKEN": "glpat_leak",
            "GH_TOKEN": "leak",
            "SELFCHECK_GIT_TOKEN": "leak",
            "PATH": "/usr/bin",
        }
    )
    assert env == {"PATH": "/usr/bin", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}
    assert "ghp_leak" not in "".join(env.values())


# ── note normalisation ─────────────────────────────────────────────────────


def test_clean_note_clamps_unknown_values():
    from selfcheck.service import _clean_note

    n = _clean_note(
        {
            "file": "./src/x.py",
            "line": "42",
            "severity": "CATASTROPHIC",
            "category": "vibes",
            "side": "sideways",
            "title": "t",
            "body": "b",
        }
    )
    assert n["file_path"] == "src/x.py"
    assert n["line_start"] == 42 and n["line_end"] == 42
    assert n["severity"] == "minor"
    assert n["category"] == "correctness"
    assert n["side"] == "new"


def test_clean_note_handles_missing_lines():
    from selfcheck.service import _clean_note

    n = _clean_note({"file": "", "title": "general point", "body": ""})
    assert n["file_path"] == "" and n["line_start"] is None and n["line_end"] is None


# ── markdown renderer used by the export ───────────────────────────────────


def test_export_escapes_nothing_it_should_not():
    from selfcheck.exporting import _note_md

    note = {
        "severity": "major", "category": "correctness", "line_start": 4, "line_end": 9,
        "title": "Off by one", "body": "loop runs `n+1` times", "suggestion": "range(n)",
        "stale": 0,
    }
    md = "\n".join(_note_md(note, "src/x.py"))
    assert "### Major · L4–L9 · correctness" in md
    assert "**Off by one**" in md
    assert "range(n)" in md


def test_cancelling_a_run_kills_the_cli():
    """Cancel must stop the subprocess, not just abandon the task.

    CancelledError is a BaseException, so an `except Exception` handler alone
    would let the CLI keep running (and keep spending) after the user cancels.
    """
    import inspect

    from selfcheck import claude_runner, subproc
    from selfcheck.engines import codex, cursor

    src = inspect.getsource(subproc.run_cli)
    assert "except asyncio.CancelledError:" in src
    cancel_block = src.split("except asyncio.CancelledError:", 1)[1]
    assert "terminate(proc)" in cancel_block.split("except", 1)[0]

    # Every CLI engine has to go through that helper to inherit the guarantee.
    for module in (claude_runner, codex, cursor):
        assert "run_cli(" in inspect.getsource(module), module.__name__


def test_terminate_is_a_noop_for_a_finished_process():
    import asyncio as _asyncio

    class Finished:
        returncode = 0

        def terminate(self):  # pragma: no cover - must not be reached
            raise AssertionError("terminate() called on an exited process")

    _asyncio.run(claude_runner_terminate(Finished()))


async def claude_runner_terminate(proc):
    from selfcheck.claude_runner import _terminate

    await _terminate(proc)


# ── fine-grained GitLab tokens ─────────────────────────────────────────────


def _gitlab_provider_with(responses):
    """A GitLabProvider whose HTTP client serves `responses` and 403s the rest."""
    from selfcheck.providers.gitlab import GitLabProvider

    provider = GitLabProvider("gitlab.com")

    class Denied(Exception):
        pass

    async def get_json(path, **kwargs):
        # Exact match: prefix matching would hand the /commits request the
        # merge-request payload and mask the behaviour under test.
        if path in responses:
            return responses[path]
        raise Denied(f"403 for {path}")

    provider._client.get_json = get_json  # type: ignore[method-assign]
    return provider


def test_gitlab_meta_survives_a_403_on_the_project_endpoint():
    """A granular PAT can read a merge request but not /projects/:id.

    That endpoint only supplies the clone URL, which the host and path already
    determine, so it must not fail the whole fetch.
    """
    from selfcheck.providers.base import PullRef

    ref = PullRef("gitlab", "gitlab.com", "grp/sub", "proj", 7)
    provider = _gitlab_provider_with(
        {
            "/projects/grp%2Fsub%2Fproj/merge_requests/7": {
                "title": "A change",
                "author": {"username": "someone"},
                "state": "opened",
                "target_branch": "main",
                "source_branch": "feature",
                "diff_refs": {"base_sha": "b" * 40, "head_sha": "h" * 40},
                "source_project_id": 1,
                "target_project_id": 1,
            },
        }
    )
    meta = asyncio.run(provider.fetch_meta(ref))

    assert meta.title == "A change"
    assert meta.state == "open"
    assert meta.head_sha == "h" * 40
    assert meta.clone_url == "https://gitlab.com/grp/sub/proj.git"
    assert meta.head_clone_url == "https://gitlab.com/grp/sub/proj.git"
    assert meta.commits == []  # the commits endpoint 403'd too, and that is fine


def test_gitlab_prefers_the_real_clone_url_when_it_can_read_it():
    from selfcheck.providers.base import PullRef

    ref = PullRef("gitlab", "gitlab.com", "grp", "proj", 2)
    provider = _gitlab_provider_with(
        {
            "/projects/grp%2Fproj/merge_requests/2": {
                "title": "t", "state": "opened",
                "diff_refs": {"base_sha": "b", "head_sha": "h"},
                "source_project_id": 1, "target_project_id": 1,
            },
            "/projects/grp%2Fproj": {
                "http_url_to_repo": "https://gitlab.com/grp/renamed.git",
            },
        }
    )
    meta = asyncio.run(provider.fetch_meta(ref))
    assert meta.clone_url == "https://gitlab.com/grp/renamed.git"


# ── language-aware review guidance ─────────────────────────────────────────


def test_detect_languages_weights_by_churn():
    from selfcheck.prompts import detect_languages

    files = [
        {"path": "src/tree_publisher.cpp", "additions": 86, "deletions": 0},
        {"path": "include/tree_publisher.hpp", "additions": 55, "deletions": 0},
        {"path": "docs/index.md", "additions": 28, "deletions": 0},
        {"path": "CMakeLists.txt", "additions": 4, "deletions": 1},
    ]
    assert detect_languages(files) == ["C++"]


def test_detect_languages_treats_dot_h_as_cpp_only_alongside_cpp():
    from selfcheck.prompts import detect_languages

    assert detect_languages(
        [{"path": "a.cpp", "additions": 50, "deletions": 0},
         {"path": "b.h", "additions": 40, "deletions": 0}]
    ) == ["C++"]
    # A lone .h change has no C++ evidence, so claim nothing.
    assert detect_languages([{"path": "b.h", "additions": 40, "deletions": 0}]) == []


def test_detect_languages_reports_a_genuinely_mixed_change():
    from selfcheck.prompts import detect_languages

    langs = detect_languages(
        [{"path": "a.cpp", "additions": 100, "deletions": 0},
         {"path": "b.py", "additions": 90, "deletions": 0}]
    )
    assert set(langs) == {"C++", "Python"}


def test_detect_languages_ignores_incidental_files():
    from selfcheck.prompts import detect_languages

    assert detect_languages([{"path": "README.md", "additions": 10, "deletions": 1}]) == []
    assert detect_languages([]) == []


def test_cpp_guidance_reaches_the_prompt_and_python_guidance_does_not():
    from selfcheck.prompts import build_review_prompt

    files = [
        {"path": "src/tree_publisher.cpp", "status": "added", "additions": 86, "deletions": 0},
        {"path": "include/tree_publisher.hpp", "status": "added", "additions": 55, "deletions": 0},
    ]
    prompt = build_review_prompt(
        meta={"provider": "gitlab", "number": 34, "namespace": "g", "project": "p",
              "host": "gitlab.com", "title": "t", "base_ref": "main", "head_ref": "f",
              "head_sha": "a" * 40, "state": "open", "changed_files": 2,
              "additions": 141, "deletions": 0, "description": "", "commits": []},
        diff_text="@@",
        diff_truncated=False,
        worktree="/tmp/wt",
        file_list=files,
    )
    assert "## Language-specific checks" in prompt
    assert "### C++" in prompt
    assert "Rule of zero" in prompt
    assert "### Python" not in prompt


def test_prompt_has_no_language_section_for_a_docs_only_change():
    from selfcheck.prompts import build_review_prompt

    prompt = build_review_prompt(
        meta={"provider": "github", "number": 1, "namespace": "g", "project": "p",
              "host": "github.com", "title": "t", "base_ref": "main", "head_ref": "f",
              "head_sha": "a" * 40, "state": "open", "changed_files": 1,
              "additions": 3, "deletions": 0, "description": "", "commits": []},
        diff_text="@@",
        diff_truncated=False,
        worktree=None,
        file_list=[{"path": "README.md", "status": "modified", "additions": 3, "deletions": 0}],
    )
    assert "## Language-specific checks" not in prompt


def test_system_prompt_demands_fit_with_surrounding_code():
    """The 'alignment with the unchanged stack' instruction is load-bearing."""
    from selfcheck.prompts import SYSTEM_APPEND

    assert "Fit with the code around it" in SYSTEM_APPEND
    for cue in ("already an abstraction", "call site", "local convention", "right layer"):
        assert cue.lower() in SYSTEM_APPEND.lower(), cue


# ── how the review is written ──────────────────────────────────────────────


def test_prompt_specifies_the_writing_style():
    """Style adjectives alone do not move a model; the prompt has to say what
    they mean in checkable terms."""
    from selfcheck.prompts import SYSTEM_APPEND

    assert "How to write it:" in SYSTEM_APPEND
    style = SYSTEM_APPEND.split("How to write it:", 1)[1].lower()

    # skimmable / ADHD-friendly
    for cue in ("lead with the conclusion", "one finding per note", "break it up",
                "bullet list", "wall of text"):
        assert cue in style, cue

    # human readable
    for cue in ("plain words", "active voice", "short sentences"):
        assert cue in style, cue

    # educational but accessible
    for cue in ("teach the idea", "why it matters", "talking down"):
        assert cue in style, cue

    # polite, without going vague
    for cue in ("critique the code, not the person", "no sarcasm"):
        assert cue in style, cue
    assert "politeness is about tone, never about facts" in style


def test_style_guidance_does_not_license_hedging():
    """Politeness must not turn into unusable vagueness — the prompt says so
    explicitly, and that sentence is the one doing the work."""
    from selfcheck.prompts import SYSTEM_APPEND

    style = SYSTEM_APPEND.split("How to write it:", 1)[1]
    assert "Do not soften a real finding" in style
    assert "do not hedge on something you have actually verified" in style


def test_output_contract_matches_the_style_rules():
    from selfcheck.prompts import OUTPUT_CONTRACT

    assert "conclusion first" in OUTPUT_CONTRACT.lower()
    assert "plain language" in OUTPUT_CONTRACT.lower()


def test_skill_and_engine_agree_on_style():
    """The bundled skill drives the same job from an interactive session, so a
    reviewer should not be able to tell which one wrote the notes."""
    import pathlib

    from selfcheck.prompts import SYSTEM_APPEND

    skill = pathlib.Path(__file__).resolve().parents[2] / "skill" / "selfcheck" / "SKILL.md"
    text = skill.read_text().lower()
    style = SYSTEM_APPEND.lower()

    for cue in ("conclusion first", "one finding per note", "plain words",
                "critique the code, not the person", "politeness is tone"):
        assert cue in text, f"skill is missing: {cue}"
    for cue in ("lead with the conclusion", "one finding per note"):
        assert cue in style, cue


def test_prompt_gives_checkable_limits_not_just_adjectives():
    """Measured against a real PR, style prose alone made notes *longer*.
    Numeric limits plus a worked example are what actually moved them."""
    from selfcheck.prompts import SYSTEM_APPEND

    assert "Hard limits" in SYSTEM_APPEND
    limits = SYSTEM_APPEND.split("Hard limits", 1)[1]
    assert "900 characters" in limits
    assert "250 characters" in limits
    assert "three sentences" in limits
    assert "Bold exactly one span per note" in limits


def test_prompt_carries_a_worked_example_of_a_good_note():
    """Few-shot beats instruction for style transfer, so the example has to
    demonstrate the shape it asks for."""
    from selfcheck.prompts import SYSTEM_APPEND

    assert "This is the shape to aim for:" in SYSTEM_APPEND
    example = SYSTEM_APPEND.split("This is the shape to aim for:", 1)[1]
    body = example.split("Three short paragraphs")[0]

    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    assert len(paragraphs) == 3, "the example must model a three-paragraph note"
    assert paragraphs[0].lstrip().startswith("**"), "it must open with the bolded conclusion"
    assert body.count("**") == 2, "exactly one bolded span, as the rule requires"
    for para in paragraphs:
        flat = " ".join(para.split())
        assert len(flat) <= 250, f"example paragraph breaks its own limit: {len(flat)}"


def test_output_contract_states_the_body_budget():
    from selfcheck.prompts import OUTPUT_CONTRACT

    assert "<= 900 chars" in OUTPUT_CONTRACT
    assert "<= 4 paragraphs" in OUTPUT_CONTRACT


# ── re-reviews replace, rather than accumulate ─────────────────────────────


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """A throwaway database for tests that write."""
    from selfcheck import db as dbmod
    from selfcheck.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SELFCHECK_DATA_DIR", str(tmp_path))
    dbmod._local.__dict__.clear()
    dbmod.init_db()
    yield dbmod
    dbmod._local.__dict__.clear()
    get_settings.cache_clear()


def _seed_review(dbmod):
    from selfcheck import service

    rid = dbmod.new_id("rev")
    ts = dbmod.now()
    with dbmod.tx() as c:
        c.execute(
            "INSERT INTO reviews (id, provider, host, namespace, project, number, url,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (rid, "github", "github.com", "o", "r", 1, "u", ts, ts),
        )
    return rid, service


def test_rereview_replaces_the_previous_runs_findings(temp_db):
    """Three runs of the same PR used to leave three copies of every finding."""
    rid, service = _seed_review(temp_db)
    finding = [{"file": "a.py", "line_start": 1, "title": "Leaks a handle", "body": "x"}]

    for run in ("run_1", "run_2", "run_3"):
        service.add_notes(
            rid, finding, run_id=run, origin="claude",
            carry_status=service.supersede_claude_notes(rid),
        )

    notes = service.list_notes(rid)
    assert len(notes) == 1, f"expected one finding, got {len(notes)}"
    assert notes[0]["run_id"] == "run_3", "the surviving note is from the latest run"


def test_rereview_keeps_your_own_notes(temp_db):
    rid, service = _seed_review(temp_db)
    service.add_notes(rid, [{"file": "a.py", "title": "Mine", "body": ""}], origin="human")
    service.add_notes(
        rid, [{"file": "a.py", "title": "Claude's"}], run_id="r1", origin="claude",
        carry_status=service.supersede_claude_notes(rid),
    )
    service.add_notes(
        rid, [{"file": "a.py", "title": "Claude's"}], run_id="r2", origin="claude",
        carry_status=service.supersede_claude_notes(rid),
    )

    titles = sorted(n["title"] for n in service.list_notes(rid))
    assert titles == ["Claude's", "Mine"], "a human note must survive a re-review"


def test_rereview_does_not_resurrect_a_dismissed_finding(temp_db):
    """If you dismissed something, saying it again should not reopen it."""
    rid, service = _seed_review(temp_db)
    created = service.add_notes(
        rid, [{"file": "a.py", "title": "Not a real problem"}], run_id="r1", origin="claude",
    )
    service.update_note(created[0]["id"], {"status": "dismissed"})

    service.add_notes(
        rid, [{"file": "a.py", "title": "  not a REAL problem  "}], run_id="r2",
        origin="claude", carry_status=service.supersede_claude_notes(rid),
    )

    notes = service.list_notes(rid)
    assert len(notes) == 1
    assert notes[0]["status"] == "dismissed", "your decision must carry across the re-review"
    assert notes[0]["run_id"] == "r2"


def test_rereview_reopens_nothing_it_did_not_reissue(temp_db):
    """A finding the new run drops is gone, not left hanging around as open."""
    rid, service = _seed_review(temp_db)
    service.add_notes(
        rid,
        [{"file": "a.py", "title": "Fixed since"}, {"file": "a.py", "title": "Still broken"}],
        run_id="r1", origin="claude",
    )
    service.add_notes(
        rid, [{"file": "a.py", "title": "Still broken"}], run_id="r2", origin="claude",
        carry_status=service.supersede_claude_notes(rid),
    )
    assert [n["title"] for n in service.list_notes(rid)] == ["Still broken"]


def test_normalise_title_absorbs_only_harmless_drift():
    from selfcheck.service import normalise_title

    assert normalise_title("  The  Thing\nbroke ") == "the thing broke"
    assert normalise_title("A") != normalise_title("B")


# ── schema migrations ──────────────────────────────────────────────────────


def test_init_db_upgrades_an_older_database_in_place(tmp_path, monkeypatch):
    """A database from before modes and engines must gain the new columns
    without losing what is in it."""
    import sqlite3

    from selfcheck import db as dbmod
    from selfcheck.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("SELFCHECK_DATA_DIR", str(tmp_path))
    conn = sqlite3.connect(tmp_path / "selfcheck.db")
    conn.executescript(
        "CREATE TABLE reviews (id TEXT PRIMARY KEY, provider TEXT, host TEXT, namespace TEXT,"
        " project TEXT, number INTEGER, url TEXT, created_at TEXT, updated_at TEXT);"
        "CREATE TABLE runs (id TEXT PRIMARY KEY, review_id TEXT, status TEXT, created_at TEXT);"
        "INSERT INTO reviews VALUES ('rev_old','github','github.com','o','r',1,'u','t','t');"
    )
    conn.commit()
    conn.close()
    try:
        dbmod.init_db()
        dbmod.init_db()  # idempotent
        conn = sqlite3.connect(tmp_path / "selfcheck.db")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(reviews)")}
        assert {"mode", "engine", "repo_watch_id"} <= cols
        assert {"mode", "engine"} <= {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
        assert conn.execute("SELECT id FROM reviews").fetchall() == [("rev_old",)]
        conn.close()
    finally:
        dbmod._local.__dict__.clear()
        get_settings.cache_clear()


def test_restart_marks_in_flight_runs_failed(temp_db):
    rid, service = _seed_review(temp_db)
    with temp_db.tx() as c:
        for run_id, status in (("run_a", "analyzing"), ("run_b", "queued"), ("run_c", "done")):
            c.execute("INSERT INTO runs (id, review_id, status, created_at) VALUES (?,?,?,?)",
                      (run_id, rid, status, temp_db.now()))
    assert service.recover_interrupted_runs() == 2
    assert service.get_run("run_a")["status"] == "failed"
    assert "restarted" in service.get_run("run_b")["error"]
    assert service.get_run("run_c")["status"] == "done"


# ── modes and engines ──────────────────────────────────────────────────────


def _prompt(mode):
    from selfcheck.prompts import build_review_prompt

    return build_review_prompt(
        meta={"provider": "github", "number": 1, "namespace": "g", "project": "p",
              "host": "github.com", "head_sha": "a" * 40},
        diff_text="@@", diff_truncated=False, worktree="/tmp/wt",
        file_list=[], mode=mode,
    )


def test_modes_change_what_the_prompt_asks_for():
    assert "Review depth: light" in _prompt("light")
    assert "At most five notes" in _prompt("light")
    assert "Review depth: thorough" in _prompt("thorough")
    assert "Review depth" not in _prompt("normal")
    assert _prompt("nonsense") == _prompt("normal")


def test_every_mode_keeps_the_writing_limits():
    """Thorough must mean more checking, never longer notes."""
    from selfcheck.prompts import MODES

    assert set(MODES) == {"light", "normal", "thorough"}
    assert "limits still apply" in MODES["thorough"]["prompt"]
    assert MODES["light"]["max_turns"] < MODES["normal"]["max_turns"] < MODES["thorough"]["max_turns"]


def test_run_resolves_mode_and_engine_from_request_then_review_then_default(temp_db):
    from selfcheck.engines import UnknownEngine

    rid, service = _seed_review(temp_db)
    review = service.get_review(rid)
    assert service.resolve_mode(None, review) == "normal"
    assert service.resolve_engine(None, review) == "claude"

    review = {**review, "mode": "light", "engine": "codex"}
    assert service.resolve_mode(None, review) == "light"
    assert service.resolve_mode("thorough", review) == "thorough"
    assert service.resolve_engine(None, review) == "codex"
    assert service.resolve_engine("openai", review) == "openai"
    with pytest.raises(UnknownEngine):
        service.resolve_engine("skynet", review)


def test_codex_engine_runs_in_its_read_only_sandbox(monkeypatch):
    from selfcheck.engines import codex

    monkeypatch.setattr(codex, "resolve_codex_bin", lambda: "/bin/codex")
    argv = codex.build_argv(cwd="/wt", model="", mode="thorough", last_message="/tmp/m")
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "model_reasoning_effort=high" in argv
    assert argv[-1] == "-", "the prompt goes through stdin, not argv"
    assert "--dangerously-bypass-approvals-and-sandbox" not in argv
    assert "--full-auto" not in argv


def test_cursor_engine_uses_ask_mode_and_never_approves_mcp(monkeypatch):
    from selfcheck.engines import cursor

    monkeypatch.setattr(cursor, "resolve_cursor_bin", lambda: "/bin/cursor-agent")
    argv = cursor.build_argv(workspace="/wt", brief_dir="/runs/x", model="")
    assert argv[argv.index("--mode") + 1] == "ask"
    assert argv[argv.index("--sandbox") + 1] == "enabled"
    for forbidden in ("--force", "--yolo", "--approve-mcps", "--auto-review"):
        assert forbidden not in argv


def test_cli_engines_strip_forge_tokens():
    from selfcheck.subproc import child_env

    env = child_env({"GITHUB_TOKEN": "x", "GITLAB_TOKEN": "y", "PATH": "/bin"})
    assert env == {"PATH": "/bin"}


def test_every_engine_is_registered_and_describes_its_guarantee():
    from selfcheck.engines import ENGINE_IDS, get_engine

    for engine_id in ENGINE_IDS:
        engine = get_engine(engine_id)
        assert engine.id == engine_id
        assert engine.kind in ("cli", "api")
        assert engine.read_only


def test_anthropic_cost_is_zero_for_an_unknown_model_not_a_guess():
    from selfcheck.engines.anthropic_api import cost_usd

    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert cost_usd("claude-opus-5-5", usage) == pytest.approx(24.0)
    assert cost_usd("some-future-model", usage) == 0.0


# ── the API engines' file tools ────────────────────────────────────────────


def _repo(tmp_path):
    root = tmp_path / "wt"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def handler(req):\n    return req.body\n")
    (root / "tests").mkdir()
    (root / "tests" / "test_app.py").write_text("from src.app import handler\n")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("handler secret\n")
    (tmp_path / "outside.txt").write_text("handler outside\n")
    return root


def test_repo_tools_read_search_and_list(tmp_path):
    from selfcheck.engines.tools import RepoTools

    tools = RepoTools(_repo(tmp_path))
    assert "     2      return req.body" in tools.read_file("src/app.py")
    hits = tools.search(r"handler")
    assert "src/app.py:1:" in hits and "tests/test_app.py:1:" in hits
    assert ".git" not in hits, ".git is not part of the code under review"
    assert tools.list_files(glob="*.py").splitlines() == ["src/app.py", "tests/test_app.py"]


def test_repo_tools_cannot_leave_the_checkout(tmp_path):
    from selfcheck.engines.tools import RepoTools

    root = _repo(tmp_path)
    (root / "escape").symlink_to(tmp_path / "outside.txt")
    tools = RepoTools(root)

    for path in ("../outside.txt", "/etc/passwd", "escape", "src/../../outside.txt"):
        out, is_error = asyncio.run(tools.call("read_file", {"path": path}))
        assert is_error and "handler outside" not in out, path
    assert "outside" not in tools.search("handler")
    out, is_error = asyncio.run(tools.call("write_file", {"path": "x"}))
    assert is_error


def test_repo_tools_ignore_unexpected_arguments(tmp_path):
    from selfcheck.engines.tools import RepoTools

    tools = RepoTools(_repo(tmp_path))
    out, is_error = asyncio.run(tools.call("read_file", {"path": "src/app.py", "mode": "w"}))
    assert not is_error and "handler" in out


# ── repository wakeups ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("url", "provider", "expected"),
    [
        ("https://github.com/pallets/click", "", ("github", "github.com", "pallets", "click")),
        ("github.com/pallets/click/pulls", "", ("github", "github.com", "pallets", "click")),
        ("https://github.com/pallets/click/pull/2731", "", ("github", "github.com", "pallets", "click")),
        ("https://github.com/pallets/click.git", "", ("github", "github.com", "pallets", "click")),
        ("gh:pallets/click", "", ("github", "github.com", "pallets", "click")),
        ("https://gitlab.com/g/sub/proj", "", ("gitlab", "gitlab.com", "g/sub", "proj")),
        ("https://gitlab.com/g/sub/proj/-/merge_requests", "", ("gitlab", "gitlab.com", "g/sub", "proj")),
        ("https://gitlab.com/g/proj/-/tree/main", "", ("gitlab", "gitlab.com", "g", "proj")),
        ("gl:g/sub/proj", "", ("gitlab", "gitlab.com", "g/sub", "proj")),
        ("https://code.corp.io/team/svc", "gitlab", ("gitlab", "code.corp.io", "team", "svc")),
    ],
)
def test_parse_repo_url(url, provider, expected):
    from selfcheck.providers import parse_repo_url

    r = parse_repo_url(url, provider)
    assert (r.provider, r.host, r.namespace, r.project) == expected


@pytest.mark.parametrize("bad", ["", "https://github.com/pallets", "https://code.corp.io/a/b"])
def test_parse_repo_url_rejects(bad):
    from selfcheck.providers import parse_repo_url

    with pytest.raises(UnsupportedUrl):
        parse_repo_url(bad)


def test_daily_wakeup_fires_at_its_wall_clock_time():
    from datetime import datetime, timedelta

    from selfcheck.watches import next_check

    local = datetime.now().astimezone()
    before = local.replace(hour=8, minute=0, second=0, microsecond=0)
    after = local.replace(hour=10, minute=0, second=0, microsecond=0)
    watch = {"interval_minutes": 1440, "daily_at": "09:00"}

    same_day = datetime.fromisoformat(next_check(watch, before)).astimezone()
    assert (same_day.hour, same_day.minute, same_day.date()) == (9, 0, before.date())
    next_day = datetime.fromisoformat(next_check(watch, after)).astimezone()
    assert next_day.date() == (after + timedelta(days=1)).date() and next_day.hour == 9

    hourly = datetime.fromisoformat(next_check({"interval_minutes": 60, "daily_at": "09:00"}, after))
    assert hourly - after == timedelta(hours=1), "daily_at only applies to a daily cadence"
    floor = datetime.fromisoformat(next_check({"interval_minutes": 1}, after))
    assert floor - after == timedelta(minutes=15)


def _wakeup(temp_db, monkeypatch, pulls, **overrides):
    """A wakeup on o/r whose forge serves `pulls`, with sync and runs stubbed."""
    from selfcheck import service, watches
    from selfcheck.providers import PullSummary

    listing = [PullSummary(**p) for p in pulls]

    async def fake_list(_repo):
        return listing

    started: list[str] = []

    async def fake_sync(review_id):
        return service.get_review(review_id)

    def fake_run(review_id, trigger="manual", guidance="", *, mode=None, engine=None):
        started.append(review_id)
        return {"id": f"run_{len(started)}", "mode": mode, "engine": engine}

    monkeypatch.setattr(watches, "list_open", fake_list)
    monkeypatch.setattr(service, "sync_review", fake_sync)
    monkeypatch.setattr(service, "create_run", fake_run)
    watch = asyncio.run(watches.create_watch("gh:o/r", **overrides))
    return watches, watch, started


def _pr(number, created="2030-01-01T00:00:00Z", **kw):
    return {"number": number, "title": f"PR {number}", "author": "dev", "base_ref": "main",
            "head_sha": f"{number:040d}", "created_at": created,
            "web_url": f"https://github.com/o/r/pull/{number}", **kw}


def test_wakeup_reviews_new_prs_and_leaves_older_ones_alone(temp_db, monkeypatch):
    pulls = [_pr(1, created="2000-01-01T00:00:00Z"), _pr(2), _pr(3, draft=True)]
    watches, watch, started = _wakeup(temp_db, monkeypatch, pulls, mode="light")

    result = asyncio.run(watches.check(watch["id"]))

    assert [s["number"] for s in result["started"]] == [2], "1 predates the wakeup, 3 is a draft"
    review = temp_db.get_conn().execute("SELECT * FROM reviews WHERE number=2").fetchone()
    assert review["repo_watch_id"] == watch["id"] and review["mode"] == "light"
    assert "1 review started" in watches.get_watch(watch["id"])["last_result"]

    again = asyncio.run(watches.check(watch["id"]))
    assert again["started"] == [], "a PR is reviewed once, not on every check"


def test_wakeup_caps_reviews_per_check(temp_db, monkeypatch):
    pulls = [_pr(n) for n in range(1, 6)]
    watches, watch, started = _wakeup(
        temp_db, monkeypatch, pulls, include_existing=True, max_per_check=2,
    )
    first = asyncio.run(watches.check(watch["id"]))
    assert len(first["started"]) == 2 and first["deferred"] == 3
    second = asyncio.run(watches.check(watch["id"]))
    assert [s["number"] for s in second["started"]] == [3, 4], "the backlog drains oldest first"


def test_wakeup_filters_by_branch_and_author(temp_db, monkeypatch):
    pulls = [_pr(1, base_ref="dev"), _pr(2, author="Alice"), _pr(3, author="bob")]
    watches, watch, _ = _wakeup(
        temp_db, monkeypatch, pulls, include_existing=True,
        target_branch="main", authors="alice, carol",
    )
    result = asyncio.run(watches.check(watch["id"]))
    assert [s["number"] for s in result["started"]] == [2]


def test_wakeup_rereviews_on_push_only_when_asked(temp_db, monkeypatch):
    from selfcheck.providers import PullSummary

    pulls = [_pr(1)]
    watches, watch, started = _wakeup(temp_db, monkeypatch, pulls, include_existing=True)
    asyncio.run(watches.check(watch["id"]))
    with temp_db.tx() as c:
        c.execute("UPDATE reviews SET head_sha=? WHERE number=1", ("1" * 40,))

    async def moved(_repo):
        return [PullSummary(**{**_pr(1), "head_sha": "2" * 40})]

    monkeypatch.setattr(watches, "list_open", moved)
    assert asyncio.run(watches.check(watch["id"]))["started"] == []

    watches.update_watch(watch["id"], {"rereview_on_push": True})
    result = asyncio.run(watches.check(watch["id"]))
    assert [s["number"] for s in result["started"]] == [1] and result["started"][0]["rereview"]


def test_wakeup_rejects_a_duplicate_and_a_bad_schedule(temp_db, monkeypatch):
    watches, watch, _ = _wakeup(temp_db, monkeypatch, [])
    with pytest.raises(watches.WatchError):
        asyncio.run(watches.create_watch("https://github.com/o/r"))
    with pytest.raises(watches.WatchError):
        watches.update_watch(watch["id"], {"daily_at": "25:00"})


def test_wakeup_only_ever_reads_from_the_forge():
    """Listing PRs goes through the same GET-only client as everything else."""
    import inspect

    from selfcheck.providers import github, gitlab

    for module in (github, gitlab):
        src = inspect.getsource(module)
        list_src = src.split("async def list_open_pulls", 1)[1].split("\n    def ", 1)[0]
        assert "self._client.get_json(" in list_src
        assert "post(" not in src.lower() and "put(" not in src.lower()


# ── analytics ──────────────────────────────────────────────────────────────


def test_run_keeps_its_finding_counts_after_a_rereview_replaces_the_notes(temp_db):
    """The dashboard counts findings per run; superseding notes must not erase them."""
    from selfcheck.routes.analytics import analytics

    rid, service = _seed_review(temp_db)
    with temp_db.tx() as c:
        c.execute("UPDATE reviews SET assignees=? WHERE id=?", ('["ana"]', rid))
        c.execute("INSERT INTO runs (id, review_id, status, note_counts, created_at)"
                  " VALUES ('run_old', ?, 'done', '{\"major\": 2}', ?)", (rid, temp_db.now()))
        c.execute("INSERT INTO runs (id, review_id, status, created_at)"
                  " VALUES ('run_legacy', ?, 'done', ?)", (rid, temp_db.now()))
    service.add_notes(rid, [{"file": "a.py", "title": "x", "severity": "minor"}],
                      run_id="run_legacy", origin="claude")

    data = analytics()
    by_id = {r["id"]: r for r in data["runs"]}
    assert by_id["run_old"]["notes"] == {"major": 2}
    assert by_id["run_legacy"]["notes"] == {"minor": 1}, "legacy runs fall back to the notes table"
    assert data["reviews"][0]["assignees"] == ["ana"]


def test_providers_report_assignees_and_requested_reviewers():
    from selfcheck.providers.base import PullRef

    ref = PullRef("gitlab", "gitlab.com", "g", "p", 1)
    provider = _gitlab_provider_with({
        "/projects/g%2Fp/merge_requests/1": {
            "title": "t", "state": "opened", "diff_refs": {},
            "assignees": [{"username": "ana"}], "reviewers": [{"username": "bo"}, None],
        },
    })
    meta = asyncio.run(provider.fetch_meta(ref))
    assert meta.assignees == ["ana"] and meta.reviewers == ["bo"]


def test_sync_keeps_line_counts_a_forge_does_not_report(temp_db, monkeypatch):
    """GitLab's MR payload has no line totals; a sync must not zero the ones
    the parsed diff already established."""
    from selfcheck.providers.base import PullMeta

    rid, service = _seed_review(temp_db)
    with temp_db.tx() as c:
        c.execute("UPDATE reviews SET additions=120, deletions=7, changed_files=4 WHERE id=?", (rid,))

    class Forge:
        async def fetch_meta(self, ref):
            return PullMeta(title="t", head_sha="h" * 40)

        async def aclose(self):
            pass

    monkeypatch.setattr(service, "get_provider", lambda ref, url="": Forge())
    asyncio.run(service.sync_review(rid))
    r = service.get_review(rid)
    assert (r["additions"], r["deletions"], r["changed_files"]) == (120, 7, 4)


# ── settings changed from the app ──────────────────────────────────────────


@pytest.fixture()
def live_settings(temp_db):
    from selfcheck import settings_store

    settings_store._defaults.clear()
    settings_store.init()
    yield settings_store
    settings_store._defaults.clear()


def test_switching_engine_in_the_app_takes_effect_without_a_restart(live_settings):
    from selfcheck.config import get_settings

    assert get_settings().engine == "claude"
    live_settings.update({"engine": "cursor", "cursor_model": "gpt-5"})
    assert get_settings().engine == "cursor", "the next run must see it immediately"
    assert get_settings().cursor_model == "gpt-5"
    assert set(live_settings.snapshot()["overridden"]) == {"engine", "cursor_model"}

    live_settings.update({"engine": None})
    assert get_settings().engine == "claude", "null resets to the .env default"


def test_settings_survive_a_restart(live_settings):
    from selfcheck.config import get_settings

    live_settings.update({"default_mode": "thorough"})
    object.__setattr__(get_settings(), "default_mode", "normal")  # as if freshly started
    live_settings.init()
    assert get_settings().default_mode == "thorough"


def test_a_bad_setting_changes_nothing(live_settings):
    from selfcheck.config import get_settings

    with pytest.raises(live_settings.InvalidSetting):
        live_settings.update({"engine": "codex", "max_concurrent_runs": 99})
    assert get_settings().engine == "claude", "validation runs before anything is applied"
    with pytest.raises(live_settings.InvalidSetting):
        live_settings.update({"openai_base_url": "file:///etc/passwd"})
    with pytest.raises(live_settings.InvalidSetting):
        live_settings.update({"anthropic_api_key": "sk-123"})


def test_snapshot_reports_secrets_only_as_present_or_not(live_settings):
    snap = live_settings.snapshot()
    assert set(snap["secrets"]) == {"anthropic_api_key", "openai_api_key"}
    assert all(isinstance(v, bool) for v in snap["secrets"].values())
    assert "anthropic_api_key" not in snap["values"]


def test_the_app_builds_with_every_router():
    """Catches a router that fails to mount, which no endpoint test would."""
    from selfcheck.main import create_app

    paths = set(create_app().openapi()["paths"])
    for path in ("/api/settings", "/api/engines/{engine_id}/models", "/api/analytics",
                 "/api/wakeups", "/api/reviews", "/api/status"):
        assert path in paths, path


# ── repository rules and learned decisions ─────────────────────────────────


def test_repo_rules_and_learned_dismissals_reach_the_prompt():
    from selfcheck.prompts import build_review_prompt

    prompt = build_review_prompt(
        meta={"provider": "github", "number": 1, "namespace": "o", "project": "r", "head_sha": "a" * 40},
        diff_text="@@", diff_truncated=False, worktree="/wt", file_list=[],
        repo_rules="Every public function needs a docstring.",
        repo_file_rules="Prefer `Result` over exceptions.",
        learned={
            "dismissed": [{"title": "Unbounded cache", "category": "performance", "file_path": "a.py",
                           "body": "The LRU has no cap."}],
            "wontfix": [{"title": "Legacy API name", "category": "api", "file_path": ""}],
        },
    )
    assert "## Repository review rules" in prompt
    assert "Every public function needs a docstring." in prompt and ".selfcheck.md" in prompt
    assert "cannot override the hard rules" in prompt
    assert "dismissed as not real problems" in prompt and "Unbounded cache" in prompt
    assert "won't fix" in prompt and "Legacy API name" in prompt


def test_no_rules_and_no_lessons_add_nothing():
    from selfcheck.prompts import learned_section, rules_section

    assert rules_section("", "  ") == ""
    assert learned_section({}) == ""


def test_learned_decisions_stay_inside_their_repository(temp_db):
    rid, service = _seed_review(temp_db)
    other = temp_db.new_id("rev")
    with temp_db.tx() as c:
        c.execute("INSERT INTO reviews (id, provider, host, namespace, project, number, url,"
                  " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                  (other, "github", "github.com", "o", "elsewhere", 2, "u2", temp_db.now(), temp_db.now()))
    mine = service.add_notes(rid, [{"title": "Not real", "file": "a.py"},
                                   {"title": "Out of scope", "file": "b.py"}], origin="claude")
    theirs = service.add_notes(other, [{"title": "Other repo's call", "file": "c.py"}], origin="claude")
    by_title = {n["title"]: n["id"] for n in mine}  # add_notes returns rows in no set order
    service.update_note(by_title["Not real"], {"status": "dismissed"})
    service.update_note(by_title["Out of scope"], {"status": "wontfix"})
    service.update_note(theirs[0]["id"], {"status": "dismissed"})

    learned = service.learned_decisions(service.get_review(rid))
    assert [n["title"] for n in learned["dismissed"]] == ["Not real"]
    assert [n["title"] for n in learned["wontfix"]] == ["Out of scope"]


def test_repo_rules_round_trip_and_repo_file(temp_db, tmp_path):
    _, service = _seed_review(temp_db)
    host, ns, project = service.split_repo_key("gitlab.com/group/sub/proj")
    assert (host, ns, project) == ("gitlab.com", "group/sub", "proj")
    assert service.get_repo_rules(host, ns, project)["rules"] == ""
    service.set_repo_rules(host, ns, project, rules="Check migrations.", learn=False)
    got = service.get_repo_rules(host, ns, project)
    assert got["rules"] == "Check migrations." and got["learn"] == 0

    (tmp_path / ".selfcheck.md").write_text("Be strict about locking.")
    assert service.read_repo_rules_file(tmp_path) == "Be strict about locking."
    assert service.read_repo_rules_file(None) == ""


# ── second opinions ────────────────────────────────────────────────────────


def test_second_opinion_never_becomes_the_current_review(temp_db):
    rid, service = _seed_review(temp_db)
    with temp_db.tx() as c:
        c.execute("INSERT INTO runs (id, review_id, status, kind, created_at) VALUES"
                  " ('run_main', ?, 'done', 'review', '2026-01-01T00:00:00+00:00')", (rid,))
        c.execute("INSERT INTO runs (id, review_id, status, kind, created_at) VALUES"
                  " ('run_2nd', ?, 'done', 'second_opinion', '2026-01-02T00:00:00+00:00')", (rid,))
    assert service.latest_run(rid)["id"] == "run_main"


def test_compare_matches_the_same_finding_across_engines(temp_db):
    rid, service = _seed_review(temp_db)
    service.add_notes(rid, [
        {"file": "a.py", "line_start": 40, "title": "File handle leaks on error"},
        {"file": "b.py", "line_start": 10, "title": "Off-by-one in pagination"},
    ], run_id="run_main", origin="claude")
    findings = [
        {"file_path": "a.py", "line_start": 42, "line_end": 42, "title": "Handle leaked when parse fails"},
        {"file_path": "c.py", "line_start": 5, "line_end": 5, "title": "Missing timeout"},
    ]
    with temp_db.tx() as c:
        c.execute("INSERT INTO runs (id, review_id, status, kind, findings, created_at) VALUES"
                  " ('run_2nd', ?, 'done', 'second_opinion', ?, ?)",
                  (rid, temp_db.jdump(findings), temp_db.now()))

    cmp = service.compare_opinion(rid)
    assert [a["ours"]["file_path"] for a in cmp["agreed"]] == ["a.py"]
    assert [n["file_path"] for n in cmp["only_ours"]] == ["b.py"]
    assert [t["file_path"] for t in cmp["only_theirs"]] == ["c.py"]
    assert cmp["agreement"] == round(1 / 3, 3)


# ── questions about a finding ──────────────────────────────────────────────


def test_question_prompt_carries_the_finding_the_thread_and_the_question():
    from selfcheck.prompts import QUESTION_SYSTEM, build_question_prompt

    prompt = build_question_prompt(
        review={"namespace": "o", "project": "r", "number": 3, "title": "t", "head_sha": "b" * 40},
        note={"file_path": "a.py", "line_start": 4, "line_end": 6, "severity": "major",
              "category": "correctness", "title": "Leaks", "body": "It leaks.", "suggestion": "with open(p):"},
        thread=[{"role": "user", "body": "Is it reachable?"}, {"role": "assistant", "body": "Yes, from main."}],
        question="What about the retry path?", worktree="/wt", hunk="@@ -1 +1 @@\n+x",
    )
    assert "`a.py:4-6`" in prompt and "It leaks." in prompt and "with open(p):" in prompt
    assert "Is it reachable?" in prompt and "Yes, from main." in prompt
    assert prompt.rstrip().endswith("What about the retry path?")
    assert "Never modify any file" in QUESTION_SYSTEM and "No JSON" in QUESTION_SYSTEM


def test_asking_about_an_unknown_note_is_a_404(temp_db):
    _, service = _seed_review(temp_db)
    with pytest.raises(service.NotFound):
        service.ask_about_note("note_nope", "why?")


# ── spend caps ─────────────────────────────────────────────────────────────


def test_budget_pauses_automatic_reviews_but_not_yours(temp_db, monkeypatch):
    from selfcheck.config import get_settings

    rid, service = _seed_review(temp_db)
    with temp_db.tx() as c:
        c.execute("INSERT INTO runs (id, review_id, status, cost_usd, created_at) VALUES"
                  " ('run_x', ?, 'done', 4.5, ?)", (rid, temp_db.now()))
    object.__setattr__(get_settings(), "daily_budget_usd", 4.0)
    state = service.budget_state()
    assert state["blocked"] and "daily budget" in state["reason"]
    assert state["today_usd"] == 4.5

    monkeypatch.setattr(service, "_spawn_run", lambda rid, guidance: None)
    with pytest.raises(service.BudgetExceeded):
        service.create_run(rid, trigger="schedule")
    with pytest.raises(service.BudgetExceeded):
        service.create_run(rid, trigger="watch")
    assert service.create_run(rid, trigger="manual")["status"] == "queued"

    object.__setattr__(get_settings(), "daily_budget_usd", 0.0)
    assert not service.budget_state()["blocked"], "0 means no cap"


# ── local branches ─────────────────────────────────────────────────────────


def _git_repo(tmp_path):
    import subprocess

    repo = tmp_path / "proj"
    repo.mkdir()
    env_cmd = ["git", "-c", "user.name=Dev", "-c", "user.email=dev@example.com"]

    def run(*args):
        subprocess.run([*env_cmd, *args], cwd=repo, check=True, capture_output=True)

    run("init", "-q", "-b", "main")
    (repo / "app.py").write_text("def f():\n    return 1\n")
    run("add", ".")
    run("commit", "-q", "-m", "base")
    run("checkout", "-q", "-b", "feature")
    (repo / "app.py").write_text("def f():\n    return 2\n")
    run("commit", "-qam", "Return two")
    return repo


def test_local_spec_parsing(tmp_path):
    from selfcheck.providers.local import local_url, looks_local, parse_local_spec, parse_local_url

    repo = _git_repo(tmp_path)
    assert looks_local(str(repo)) and looks_local("~/x") and not looks_local("https://github.com/a/b/pull/1")
    assert parse_local_spec(f"{repo}@feature..main") == (repo.resolve(), "feature", "main")
    assert parse_local_spec(str(repo)) == (repo.resolve(), "", "")
    url = local_url(repo, "feature", "main")
    assert parse_local_url(url) == (repo, "feature", "main")
    with pytest.raises(UnsupportedUrl):
        parse_local_spec(str(tmp_path))  # not a git repository


def test_local_branch_review_end_to_end_leaves_the_repo_untouched(temp_db, tmp_path):
    """Track a local branch, sync it, diff it and check it out read-only —
    without writing anything into the source repository."""
    import os

    from selfcheck import service

    repo = _git_repo(tmp_path)
    before = sorted(p.relative_to(repo) for p in repo.rglob("*"))
    git_dir_mtime = os.stat(repo / ".git").st_mtime_ns

    review = asyncio.run(service.create_local_review(str(repo)))
    assert (review["provider"], review["head_ref"], review["base_ref"]) == ("local", "feature", "main")
    again = asyncio.run(service.create_local_review(f"{repo}@feature..main"))
    assert again["id"] == review["id"], "tracking the same branch twice is idempotent"

    synced = asyncio.run(service.sync_review(review["id"]))
    assert synced["title"] == "Return two" and synced["author"] == "Dev"
    payload = asyncio.run(service.fetch_diff_payload(review["id"]))
    assert [f["path"] for f in payload["files"]] == ["app.py"]
    assert payload["stats"]["additions"] == 1

    wt = asyncio.run(service.prepare_checkout(service.get_review(review["id"])))
    assert (wt / "app.py").read_text() == "def f():\n    return 2\n"
    assert not os.access(wt / "app.py", os.W_OK), "the checkout is read-only"

    assert sorted(p.relative_to(repo) for p in repo.rglob("*")) == before
    assert os.stat(repo / ".git").st_mtime_ns == git_dir_mtime
