"""session_cycle.sh: the three session-driven cycles, all landing the same way.

Answering a question, ingesting a source someone handed the session, and
closing the gaps a query found are different work with identical *handling*:
the same lock a scheduled cycle claims, the same run branch, the same PR and
required-check handoff. These tests pin that, and pin the two orderings that
are easy to get wrong and expensive when wrong -- filing a query's gaps only
after the branch exists, and releasing the lock on every path that stops early.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import PLUGIN_ROOT, build_clean_repo, make_pdf
from zettel_lib import gitlock

SCRIPT = PLUGIN_ROOT / "scripts" / "session_cycle.sh"
ADHOC = PLUGIN_ROOT / "scripts" / "adhoc_research.sh"
CYCLE = PLUGIN_ROOT / "scripts" / "remote_cycle.sh"


@pytest.fixture
def content_repo(tmp_path):
    """A committed content repo tracking a local bare origin."""
    repo = build_clean_repo(tmp_path / "kb")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
    for key, value in (("user.name", "t"), ("user.email", "t@localhost")):
        subprocess.run(git + ["config", key, value], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-qm", "genesis"], check=True)
    subprocess.run(git + ["remote", "add", "origin", str(origin)], check=True)
    subprocess.run(git + ["push", "-q", "-u", "origin", "main"], check=True)
    subprocess.run(git + ["remote", "set-head", "origin", "-a"],
                   capture_output=True, check=False)
    return repo, origin


def env_for(repo, holder="session"):
    return {**os.environ, "PYTHON": sys.executable, "ZETTEL_RUN_HOLDER": holder,
            "ZETTEL_SKILL_REFRESHED": "1",
            "ZETTEL_AGENTS_DIR": str(Path(repo).parent / "claude-agents")}


def session(repo, *args, holder="session", stdin=None):
    return subprocess.run([str(SCRIPT), *args, "--repo", str(repo)],
                          capture_output=True, text=True, env=env_for(repo, holder),
                          input=stdin)


def cycle(repo, *args, holder="scheduled"):
    return subprocess.run([str(CYCLE), *args, "--repo", str(repo)],
                          capture_output=True, text=True, env=env_for(repo, holder))


def current_branch(repo) -> str:
    return subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                          capture_output=True, text=True, check=True).stdout.strip()


def line(out: str, prefix: str) -> str:
    for row in out.splitlines():
        if row.startswith(prefix):
            return row[len(prefix):].strip()
    raise AssertionError(f"no {prefix!r} line in:\n{out}")


# --- ask: the ad-hoc contract, unchanged --------------------------------------

def test_ask_keeps_the_adhoc_contract(content_repo):
    repo, _ = content_repo
    result = session(repo, "ask", "--question", "Do slip boxes compound?")
    assert result.returncode == 0, result.stderr
    assert current_branch(repo).startswith("zettel/run-")
    inquiry = line(result.stdout, "inquiry:")
    assert inquiry.startswith("inquiries/") and (repo / inquiry).exists()


def test_adhoc_wrapper_delegates_to_session_cycle(content_repo):
    """The old entry point still exists, still behaves, still exits the same."""
    repo, _ = content_repo
    result = subprocess.run([str(ADHOC), "--repo", str(repo), "--question", "Via the wrapper?"],
                            capture_output=True, text=True, env=env_for(repo))
    assert result.returncode == 0, result.stderr
    assert line(result.stdout, "branch:").startswith("zettel/run-")
    assert line(result.stdout, "inquiry:").startswith("inquiries/")


def test_ask_checklist_names_the_concrete_commands(content_repo):
    """A checklist of placeholders gets improvised around; one of real commands is run."""
    repo, _ = content_repo
    out = session(repo, "ask", "--question", "What lands in the checklist?").stdout
    for fragment in ("query.py", "capture.py", "inquiry-update", "fetch_source.py",
                     "remote_cycle.sh gates", "remote_cycle.sh finish"):
        assert fragment in out, fragment
    assert str(repo) in out, "the checklist names this repo, not a placeholder"
    assert "{{" not in out, "every placeholder was substituted"


def test_ask_checklist_shell_quotes_the_question(content_repo):
    """The query command is meant to be pasted; a quote in the question must not break it."""
    repo, _ = content_repo
    out = session(repo, "ask", "--question", "Why do \"smart\" notes work?").stdout
    query_line = next(r for r in out.splitlines() if "query.py" in r)
    assert "'Why do \"smart\" notes work?'" in query_line


# --- ingest: a source the session was handed ----------------------------------

def test_ingest_copies_ingests_and_reports_the_reference(tmp_path, content_repo):
    repo, _ = content_repo
    source = tmp_path / "handed.pdf"
    source.write_bytes(make_pdf(pages=["A handed source", "Page two of it"]))

    result = session(repo, "ingest", "--source", str(source),
                     "--title", "A Handed Source", "--author", "Tester, Ada", "--year", "2026")
    assert result.returncode == 0, result.stderr
    assert current_branch(repo).startswith("zettel/run-")
    assert source.exists(), "the caller's file is copied, never consumed"

    ref = line(result.stdout, "reference:")
    capture = line(result.stdout, "capture:")
    text = line(result.stdout, "text:")
    assert (repo / f"reference/{ref}.md").exists()
    assert (repo / capture).exists()
    assert "--- page 2 ---" in (repo / text).read_text(encoding="utf-8")
    assert not list((repo / "drop").glob("handed*")), "drop/ is left clean"


def test_ingest_checklist_points_at_the_capture_and_the_generators(tmp_path, content_repo):
    repo, _ = content_repo
    source = tmp_path / "handed.pdf"
    source.write_bytes(make_pdf("A handed source about slip boxes"))
    out = session(repo, "ingest", "--source", str(source), "--title", "Handed").stdout
    assert "--- page N ---" in out, "the checklist says locators come from page markers"
    for fragment in ("capture.py", "literature", "permanent", "remote_cycle.sh gates"):
        assert fragment in out, fragment
    assert "{{" not in out


def test_ingest_leaves_the_repo_gate_clean(tmp_path, content_repo):
    repo, _ = content_repo
    source = tmp_path / "handed.pdf"
    source.write_bytes(make_pdf("A handed source"))
    assert session(repo, "ingest", "--source", str(source), "--title", "Handed").returncode == 0
    assert cycle(repo, "gates").returncode == 0


def test_ingest_of_a_duplicate_releases_the_lock_and_names_the_existing_note(
        tmp_path, content_repo):
    """Already on file is an answer, not a failure -- and not a held lock."""
    repo, _ = content_repo
    source = tmp_path / "dup.pdf"
    source.write_bytes(make_pdf("Smart notes again"))
    result = session(repo, "ingest", "--source", str(source),
                     "--title", "Smart Notes Again", "--isbn", "9781542866507")
    assert result.returncode == 1
    assert "duplicate_of: ahrens-how-to-take-smart-notes--202608301000" in result.stdout
    assert gitlock.read(repo) is None, "the lock is handed back"
    assert source.exists()


def test_ingest_requires_an_existing_file(content_repo):
    repo, _ = content_repo
    assert session(repo, "ingest", "--source", "/nope/missing.pdf").returncode == 1
    assert gitlock.read(repo) is None, "a bad path never reaches the lock"


# --- query: file the gaps on the branch, then work them -----------------------

def test_query_files_gaps_on_the_run_branch(content_repo):
    """The ordering that matters: start FIRST, then file, or the captures strand."""
    repo, _ = content_repo
    result = session(repo, "query", "--from-query", "quantum chromodynamics")
    assert result.returncode == 0, result.stderr
    branch = line(result.stdout, "branch:")
    assert branch.startswith("zettel/run-")
    assert current_branch(repo) == branch
    assert "inquiry: inquiries/" in result.stdout
    filed, = (repo / "inquiries").glob("quantum-chromodynamics--*.md")
    assert filed.exists()
    assert "query --file-gaps" in (repo / "log.md").read_text(encoding="utf-8")


def test_query_with_nothing_to_file_releases_the_lock(content_repo):
    """No gap means no work; opening an empty cycle would be noise."""
    repo, _ = content_repo
    result = session(repo, "query", "--from-query", "atomic notes compound", "--top", "1")
    assert result.returncode == 0, result.stderr
    assert "filed: nothing" in result.stdout
    assert gitlock.read(repo) is None


def test_query_checklist_explains_each_kind_of_gap(content_repo):
    repo, _ = content_repo
    out = session(repo, "query", "--from-query", "quantum chromodynamics").stdout
    for fragment in ("An inquiry", "Distil a permanent note", "Add to a map of content",
                     "remote_cycle.sh gates", "inquiry-update"):
        assert fragment in out, fragment
    assert "{{" not in out


def test_query_gaps_survive_the_gates(content_repo):
    """A filed inquiry must not make the branch un-mergeable."""
    repo, _ = content_repo
    assert session(repo, "query", "--from-query", "quantum chromodynamics").returncode == 0
    assert cycle(repo, "gates").returncode == 0


# --- shared: the lock, and standing down --------------------------------------

@pytest.mark.parametrize("args", [
    ("ask", "--question", "Can I barge in?"),
    ("query", "--from-query", "anything at all"),
])
def test_every_mode_stands_down_on_a_live_lock(content_repo, args):
    repo, _ = content_repo
    assert cycle(repo, "start", holder="scheduled").returncode == 0
    result = session(repo, *args, holder="second")
    assert result.returncode == 3
    assert "standing down" in result.stdout or "holds the lock" in result.stderr


def test_ingest_stands_down_on_a_live_lock(tmp_path, content_repo):
    repo, _ = content_repo
    source = tmp_path / "handed.pdf"
    source.write_bytes(make_pdf("A handed source"))
    assert cycle(repo, "start", holder="scheduled").returncode == 0
    result = session(repo, "ingest", "--source", str(source), holder="second")
    assert result.returncode == 3
    assert not list((repo / "drop").glob("handed*")), "nothing was staged while standing down"


def test_standing_down_does_not_steal_the_lock(content_repo):
    repo, _ = content_repo
    assert cycle(repo, "start", holder="scheduled").returncode == 0
    session(repo, "ask", "--question", "Mine now?", holder="second")
    held = gitlock.read(repo)
    assert held is not None and held.holder == "scheduled"


# --- usage --------------------------------------------------------------------

def test_help_names_all_three_modes():
    out = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True).stdout
    for mode in ("ask", "ingest", "query"):
        assert mode in out
    assert "remote_cycle.sh finish" in out


@pytest.mark.parametrize("args", [
    ("ask",), ("ingest",), ("query",),
    ("ask", "--question", "q"),          # no --repo
    ("nonsense", "--question", "q"),
])
def test_usage_errors_exit_2_before_the_lock(tmp_path, content_repo, args):
    repo, _ = content_repo
    resolved = list(args)
    if "--repo" not in resolved and args[0] in ("ask", "ingest", "query") and len(args) == 1:
        resolved += ["--repo", str(repo)]
    result = subprocess.run([str(SCRIPT), *resolved], capture_output=True, text=True,
                            env=env_for(repo))
    assert result.returncode == 2, f"{args}: {result.stdout}{result.stderr}"
    assert gitlock.read(repo) is None


def test_a_missing_flag_reports_as_usage_not_as_a_bad_repo(tmp_path):
    """Order matters: tell the caller what they omitted, not what the env dislikes."""
    result = subprocess.run([str(SCRIPT), "ask", "--repo", str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 2
    assert "--question is required" in result.stderr
