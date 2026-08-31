"""adhoc_research.sh: answering a question now, without a path around the gates.

The temptation with ad-hoc work is a shortcut -- commit the answer straight to
main because a human is watching. That is exactly the path that lets an
unverified citation into the base. These tests pin the opposite: ad-hoc uses the
same lock and the same branch + PR handoff as a scheduled cycle, and stands down
rather than racing one.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import PLUGIN_ROOT, build_clean_repo
from zettel_lib import gitlock
from zettel_lib.frontmatter import Note

SCRIPT = PLUGIN_ROOT / "scripts" / "adhoc_research.sh"
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


def adhoc(repo, *args, holder="adhoc", stdin=None):
    env = {**os.environ, "PYTHON": sys.executable, "ZETTEL_RUN_HOLDER": holder}
    return subprocess.run([str(SCRIPT), "--repo", str(repo), *args],
                          capture_output=True, text=True, env=env, input=stdin)


def cycle(repo, *args, holder="scheduled"):
    env = {**os.environ, "PYTHON": sys.executable, "ZETTEL_RUN_HOLDER": holder}
    return subprocess.run([str(CYCLE), *args, "--repo", str(repo)],
                          capture_output=True, text=True, env=env)


def current_branch(repo) -> str:
    return subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                          capture_output=True, text=True, check=True).stdout.strip()


def branches_on(origin) -> list[str]:
    out = subprocess.run(["git", "-C", str(origin), "branch", "--format=%(refname:short)"],
                         capture_output=True, text=True, check=True).stdout
    return out.split()


def only_inquiry(repo: Path) -> Note:
    path, = (repo / "inquiries").glob("*.md")
    return Note.load(path)


# --- the happy path -----------------------------------------------------------

def test_start_creates_the_inquiry_and_a_run_branch(content_repo):
    repo, _ = content_repo
    result = adhoc(repo, "--question", "Do citation graphs show small-world structure?")
    assert result.returncode == 0, result.stderr

    branch = current_branch(repo)
    assert branch.startswith("zettel/run-")
    assert f"branch: {branch}" in result.stdout
    assert gitlock.read(repo) is not None

    inquiry = only_inquiry(repo)
    assert inquiry.question == "Do citation graphs show small-world structure?"
    assert inquiry.status == "new"


def test_priority_and_body_reach_the_inquiry(content_repo):
    repo, _ = content_repo
    adhoc(repo, "--question", "Why?", "--priority", "high", "--body", "-",
          stdin="context from a pipe\n")
    inquiry = only_inquiry(repo)
    assert inquiry.priority == "high"
    assert "context from a pipe" in inquiry.body


def test_the_question_is_filed_even_before_any_research(content_repo):
    """A question asked and then abandoned must still be in the repo to find."""
    repo, _ = content_repo
    adhoc(repo, "--question", "An abandoned question")
    cycle(repo, "abort")
    assert only_inquiry(repo).question == "An abandoned question"


# --- contention ---------------------------------------------------------------

def test_stands_down_with_exit_3_when_a_run_holds_the_lock(content_repo):
    repo, _ = content_repo
    assert cycle(repo, "start", holder="scheduled-run").returncode == 0

    result = adhoc(repo, "--question", "Can I barge in?")
    assert result.returncode == 3, (result.stdout, result.stderr)
    assert "lock held by scheduled-run" in result.stdout
    assert not list((repo / "inquiries").glob("*.md")), \
        "a stood-down session must leave no half-started work"


def test_standing_down_does_not_steal_the_lock(content_repo):
    repo, _ = content_repo
    cycle(repo, "start", holder="scheduled-run")
    adhoc(repo, "--question", "Can I barge in?")
    held = gitlock.read(repo)
    assert held is not None and held.holder == "scheduled-run"


# --- the handoff --------------------------------------------------------------

def test_finish_routes_the_answer_through_a_branch_never_main(content_repo):
    repo, origin = content_repo
    main_before = subprocess.run(["git", "-C", str(origin), "rev-parse", "main"],
                                 capture_output=True, text=True, check=True).stdout

    adhoc(repo, "--question", "What lands where?")
    branch = current_branch(repo)
    result = cycle(repo, "finish", "--title", "Research: what lands where?")
    assert result.returncode == 0, result.stderr

    assert branch in branches_on(origin)
    main_after = subprocess.run(["git", "-C", str(origin), "rev-parse", "main"],
                                capture_output=True, text=True, check=True).stdout
    assert main_before == main_after, "an ad-hoc answer never reaches main un-gated"
    assert gitlock.read(repo) is None


def test_the_inquiry_alone_counts_as_work_worth_pushing(content_repo):
    """Even with no notes yet, the question itself must survive the cycle."""
    repo, origin = content_repo
    adhoc(repo, "--question", "A question with no answer yet")
    branch = current_branch(repo)
    cycle(repo, "finish")
    files = subprocess.run(["git", "-C", str(origin), "ls-tree", "-r", "--name-only", branch],
                           capture_output=True, text=True, check=True).stdout
    assert "inquiries/" in files


# --- contract -----------------------------------------------------------------

def test_help_exits_zero_and_documents_the_handoff():
    result = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "remote_cycle.sh finish" in result.stdout


@pytest.mark.parametrize("args", [(), ("--question", "q"), ("--repo", "x")])
def test_missing_required_arguments_are_usage_errors(tmp_path, args):
    resolved = tuple(str(tmp_path) if a == "x" else a for a in args)
    result = subprocess.run([str(SCRIPT), *resolved], capture_output=True, text=True)
    assert result.returncode == 2


def test_blank_question_is_a_usage_error(content_repo):
    repo, _ = content_repo
    result = adhoc(repo, "--question", "   ")
    assert result.returncode == 2
    assert gitlock.read(repo) is None, "a usage error must not claim the lock"


def test_non_git_repo_is_rejected_before_the_lock(tmp_path):
    plain = build_clean_repo(tmp_path / "kb")
    result = subprocess.run([str(SCRIPT), "--repo", str(plain), "--question", "q"],
                            capture_output=True, text=True,
                            env={**os.environ, "PYTHON": sys.executable})
    assert result.returncode == 1
    assert "not a git repository" in result.stderr
