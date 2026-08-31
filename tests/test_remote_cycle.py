"""remote_cycle.sh: lock, run branch, PR handoff for session-as-agent runs.

In the remote model there is no wrapper re-running the lints before a push --
the session is the agent. This script's job is to make the mechanics
deterministic: one run at a time, work lands on a branch, and CI decides
whether it reaches main.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from conftest import PLUGIN_ROOT, build_clean_repo
from zettel_lib import gitlock

SCRIPT = PLUGIN_ROOT / "scripts" / "remote_cycle.sh"


@pytest.fixture
def content_repo(tmp_path):
    """A committed content repo tracking a local bare origin, plus a 2nd clone."""
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


def cycle(repo, *args, holder="test-run"):
    env = {**os.environ, "PYTHON": sys.executable, "ZETTEL_RUN_HOLDER": holder}
    return subprocess.run([str(SCRIPT), *args, "--repo", str(repo)],
                          capture_output=True, text=True, env=env)


def branches_on(origin) -> list[str]:
    out = subprocess.run(["git", "-C", str(origin), "branch", "--format=%(refname:short)"],
                         capture_output=True, text=True, check=True).stdout
    return out.split()


def current_branch(repo) -> str:
    return subprocess.run(["git", "-C", str(repo), "branch", "--show-current"],
                          capture_output=True, text=True, check=True).stdout.strip()


# --- start --------------------------------------------------------------------

def test_start_claims_the_lock_and_creates_a_run_branch(content_repo):
    repo, _ = content_repo
    result = cycle(repo, "start")
    assert result.returncode == 0, result.stderr
    branch = result.stdout.strip()
    assert branch.startswith("zettel/run-")
    assert current_branch(repo) == branch
    assert gitlock.read(repo) is not None


def test_start_prints_only_the_branch_on_stdout(content_repo):
    """Callers capture stdout to get the branch; diagnostics belong on stderr."""
    repo, _ = content_repo
    result = cycle(repo, "start")
    assert result.stdout.strip().startswith("zettel/run-")
    assert "\n" not in result.stdout.strip()


def test_second_container_stands_down_with_exit_3(content_repo, tmp_path):
    """Two scheduled firings must never both work -- the whole point of the lock."""
    repo, origin = content_repo
    assert cycle(repo, "start", holder="run-1").returncode == 0

    other = tmp_path / "kb2"
    subprocess.run(["git", "clone", "-q", str(origin), str(other)], check=True)
    result = cycle(other, "start", holder="run-2")

    assert result.returncode == 3, "a blocked run stands down; it is not a failure"
    assert "lock held by run-1" in result.stdout
    assert current_branch(other) != "", "the blocked run must not be left mid-checkout"


def test_a_stale_lock_is_broken_so_a_crash_cannot_wedge_the_schedule(content_repo):
    repo, _ = content_repo
    gitlock.claim(repo, "crashed-container", "old-session")
    result = cycle(repo, "start", "--ttl", "0")
    assert result.returncode == 0
    assert "broke stale lock from crashed-container" in result.stderr


# --- finish -------------------------------------------------------------------

def test_finish_pushes_a_branch_and_releases_the_lock(content_repo):
    repo, origin = content_repo
    branch = cycle(repo, "start").stdout.strip()
    (repo / "INBOX.md").write_text("# Inbox\n\nnew content\n", encoding="utf-8")

    result = cycle(repo, "finish", "--title", "Test cycle")
    assert result.returncode == 0, result.stderr
    assert branch in branches_on(origin), "work must land on the run branch"
    assert gitlock.read(repo) is None, "the lock must always be released"


def test_finish_never_pushes_to_main(content_repo):
    """CI gates main; a run may only ever offer a branch."""
    repo, origin = content_repo
    main_before = subprocess.run(["git", "-C", str(origin), "rev-parse", "main"],
                                 capture_output=True, text=True, check=True).stdout
    cycle(repo, "start")
    (repo / "INBOX.md").write_text("# Inbox\n\nchanged\n", encoding="utf-8")
    cycle(repo, "finish")

    main_after = subprocess.run(["git", "-C", str(origin), "rev-parse", "main"],
                                capture_output=True, text=True, check=True).stdout
    assert main_before == main_after


def test_finish_with_no_changes_releases_without_pushing(content_repo):
    repo, origin = content_repo
    cycle(repo, "start")
    result = cycle(repo, "finish")
    assert result.returncode == 0
    assert "no changes" in result.stdout
    assert gitlock.read(repo) is None
    assert not [b for b in branches_on(origin) if b.startswith("zettel/run-")]


def test_finish_refuses_when_not_on_a_run_branch(content_repo):
    repo, _ = content_repo
    result = cycle(repo, "finish")
    assert result.returncode != 0
    assert "not on a run branch" in result.stderr


def test_push_denied_start_fails_clearly_not_as_standdown(content_repo):
    """No push access must exit 1 with the real error -- never a fake exit 3."""
    repo, origin = content_repo
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'access denied by the git proxy' >&2\nexit 1\n",
                    encoding="utf-8")
    hook.chmod(0o755)

    result = cycle(repo, "start")
    assert result.returncode == 1, (result.returncode, result.stdout, result.stderr)
    assert "push access" in result.stderr or "could not claim" in result.stderr
    assert "standing down" not in result.stdout
    assert "Traceback" not in result.stderr, "failures must be reported, not crash"


# --- abort --------------------------------------------------------------------

def test_abort_releases_the_lock_and_keeps_the_branch(content_repo):
    repo, _ = content_repo
    branch = cycle(repo, "start").stdout.strip()
    result = cycle(repo, "abort")
    assert result.returncode == 0
    assert gitlock.read(repo) is None
    assert current_branch(repo) == branch, "the branch stays for inspection"


def test_abort_is_safe_with_no_lock_held(content_repo):
    repo, _ = content_repo
    assert cycle(repo, "abort").returncode == 0


# --- status + contract --------------------------------------------------------

def test_status_reports_free_then_held(content_repo):
    repo, _ = content_repo
    assert "lock: free" in cycle(repo, "status").stdout
    cycle(repo, "start", holder="run-x")
    assert "lock: run-x" in cycle(repo, "status").stdout


def test_every_step_is_logged(content_repo):
    repo, _ = content_repo
    cycle(repo, "start")
    (repo / "INBOX.md").write_text("# Inbox\n\nx\n", encoding="utf-8")
    cycle(repo, "finish")
    log = (repo / "log.md").read_text(encoding="utf-8")
    for marker in ("remote_cycle: start", "remote_cycle: pushed", "remote_cycle: lock released"):
        assert marker in log


def test_help_and_bad_subcommand(content_repo):
    repo, _ = content_repo
    assert subprocess.run([str(SCRIPT), "--help"], capture_output=True,
                          text=True).returncode == 0
    assert cycle(repo, "frobnicate").returncode != 0
