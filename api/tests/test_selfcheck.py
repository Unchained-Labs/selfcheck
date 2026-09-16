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

    assert [(l.kind, l.old_line, l.new_line) for l in lines[:5]] == [
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

    from selfcheck import claude_runner

    src = inspect.getsource(claude_runner.run_claude)
    assert "except asyncio.CancelledError:" in src
    cancel_block = src.split("except asyncio.CancelledError:", 1)[1]
    assert "_terminate(proc)" in cancel_block.split("except", 1)[0]


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
