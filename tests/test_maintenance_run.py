"""maintenance_run.sh: lock serialization, gate enforcement, push authority.

Uses the stub claude binary (tests/stub_claude/claude) and a local bare repo as
origin so push behavior is testable offline. Covers acceptance checklist items
8-9, AC-25, AC-28, AC-30, and the amendment-A3 guarantee that unlinted state is
never pushed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import PLUGIN_ROOT, build_clean_repo, drop_file, make_pdf

MAINTENANCE = PLUGIN_ROOT / "scripts" / "maintenance_run.sh"
STUB = PLUGIN_ROOT / "tests" / "stub_claude" / "claude"


@pytest.fixture
def repo_with_origin(tmp_path):
    """A clean content repo, committed, tracking a local bare origin."""
    repo = build_clean_repo(tmp_path / "kb")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["-c", "user.name=t", "-c", "user.email=t@localhost",
                          "commit", "-q", "-m", "genesis"], check=True)
    subprocess.run(git + ["remote", "add", "origin", str(origin)], check=True)
    subprocess.run(git + ["push", "-q", "-u", "origin", "main"], check=True)
    return repo, origin


def origin_head(origin: Path) -> str:
    return subprocess.run(["git", "-C", str(origin), "rev-parse", "main"],
                          capture_output=True, text=True, check=True).stdout.strip()


def run_maintenance(repo: Path, mode: str = "good", extra=(), env_extra=None):
    env = {
        **os.environ,
        "STUB_CLAUDE_MODE": mode,
        "PYTHON": sys.executable,
        "RESULTS_DIR": str(repo.parent / "runs"),
        **(env_extra or {}),
    }
    return subprocess.run(
        [str(MAINTENANCE), "--repo", str(repo), "--claude-bin", str(STUB), *extra],
        capture_output=True, text=True, env=env)


# --- happy path (checklist 8) -------------------------------------------------

def test_good_run_pushes_and_logs_cycle_order(repo_with_origin):
    repo, origin = repo_with_origin
    before = origin_head(origin)

    result = run_maintenance(repo)
    assert result.returncode == 0, result.stderr

    assert origin_head(origin) != before, "a clean run must push"
    log = (repo / "log.md").read_text(encoding="utf-8")
    # FR-28 order observable: wrapper step 1, stub steps 2..10, gates, push
    positions = [log.index(marker) for marker in
                 ["step 1 lock acquired", "step 2:", "step 5:", "step 8:", "step 10:",
                  "gates passed independently", "pushed"]]
    assert positions == sorted(positions), f"log out of order:\n{log}"


def test_dry_run_passes_gates_but_never_pushes(repo_with_origin):
    repo, origin = repo_with_origin
    before = origin_head(origin)
    result = run_maintenance(repo, extra=["--dry-run"])
    assert result.returncode == 0, result.stderr
    assert origin_head(origin) == before
    assert "dry-run" in (repo / "log.md").read_text(encoding="utf-8")


# --- A3: gate failure means no push -------------------------------------------

def test_lint_violation_blocks_the_push(repo_with_origin):
    repo, origin = repo_with_origin
    before = origin_head(origin)

    result = run_maintenance(repo, mode="violate")
    assert result.returncode != 0

    assert origin_head(origin) == before, \
        "unlinted state must never reach the origin (amendment A3)"
    # the run's commit is preserved locally for inspection, not rolled back
    local = subprocess.run(["git", "-C", str(repo), "log", "--oneline"],
                           capture_output=True, text=True).stdout
    assert "stub maintenance run" in local
    assert "GATE FAILED" in (repo / "log.md").read_text(encoding="utf-8")


def test_budget_cutoff_blocks_the_push_and_mirrors_exit_code(repo_with_origin):
    repo, origin = repo_with_origin
    before = origin_head(origin)
    result = run_maintenance(repo, mode="overbudget")
    assert result.returncode == 7, "wrapper must mirror claude's exit code"
    assert origin_head(origin) == before
    assert "ABORT claude exited 7" in (repo / "log.md").read_text(encoding="utf-8")


# --- FR-37 sandbox (checklist 10, AC-37) --------------------------------------

def test_smith_proposal_cycle_trials_scores_and_pushes(repo_with_origin):
    repo, origin = repo_with_origin
    before = origin_head(origin)
    # an inquiry for the auto-trial to run against, committed so preflight passes
    subprocess.run([sys.executable, str(PLUGIN_ROOT / "scripts" / "capture.py"),
                    "--repo", str(repo), "inquiry", "Does the trial fire?"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c",
                    "user.email=t@localhost", "commit", "-qm", "inquiry"], check=True)

    result = run_maintenance(repo, mode="smith")
    assert result.returncode == 0, result.stdout + result.stderr

    assert origin_head(origin) != before
    pushed = subprocess.run(
        ["git", "-C", str(origin), "ls-tree", "-r", "--name-only", "main"],
        capture_output=True, text=True, check=True).stdout
    assert "skills/demo-skill/SKILL.md" in pushed
    assert "skills/demo-skill/PURPOSE.md" in pushed
    impact_md = (repo / "skill-impact.md").read_text(encoding="utf-8")
    assert "proposed" in impact_md and "demo-skill" in impact_md
    log = (repo / "log.md").read_text(encoding="utf-8")
    assert "skill-smith: proposed demo-skill" in log
    # the wrapper auto-ran the A/B trial and committed its scores (FR-36)
    assert "step 7b A/B trial" in log
    assert "skill_trial: demo-skill with=" in log
    assert "| trial |" in impact_md
    pushed_log = subprocess.run(
        ["git", "-C", str(origin), "log", "--format=%s", "main"],
        capture_output=True, text=True, check=True).stdout
    assert "Record A/B trial scores for demo-skill" in pushed_log


def test_plugin_repo_write_is_blocked_and_logged(repo_with_origin):
    repo, origin = repo_with_origin
    before = origin_head(origin)
    planted = PLUGIN_ROOT / ".stub-escape"
    try:
        result = run_maintenance(repo, mode="smith-escape")
        assert result.returncode != 0, "an out-of-repo write must fail the run"
        assert planted.exists(), "the stub should have planted the escape file"
        assert origin_head(origin) == before, "nothing may be pushed (AC-37)"
        assert "SANDBOX VIOLATION" in (repo / "log.md").read_text(encoding="utf-8")
        assert "SANDBOX VIOLATION" in result.stderr
    finally:
        planted.unlink(missing_ok=True)


# --- run.lock (checklist 9, AC-30) --------------------------------------------

def test_second_concurrent_run_aborts_on_lock(repo_with_origin):
    repo, origin = repo_with_origin
    results = {}

    def run(tag, delay):
        time.sleep(delay)
        results[tag] = run_maintenance(repo, mode="slow")

    t1 = threading.Thread(target=run, args=("first", 0))
    t2 = threading.Thread(target=run, args=("second", 0.7))
    t1.start(); t2.start(); t1.join(); t2.join()

    outputs = [results["first"], results["second"]]
    held = [r for r in outputs if "another run holds run.lock" in r.stdout]
    worked = [r for r in outputs if "another run holds run.lock" not in r.stdout]
    assert len(held) == 1 and len(worked) == 1, \
        f"exactly one run must do work\nfirst: {results['first'].stdout}\nsecond: {results['second'].stdout}"
    assert held[0].returncode == 0, "the lock-held run exits 0 without work"
    assert worked[0].returncode == 0

    log = (repo / "log.md").read_text(encoding="utf-8")
    assert log.count("maintenance_run: start") == 1


def test_stale_lock_is_broken(repo_with_origin):
    repo, origin = repo_with_origin
    lock = repo / "run.lock"
    lock.write_text("pid=1 started=2020-01-01T00:00:00Z", encoding="utf-8")
    old = time.time() - 8 * 3600
    os.utime(lock, (old, old))

    result = run_maintenance(repo)
    assert result.returncode == 0, result.stderr
    assert "breaking stale run.lock" in result.stderr
    assert not lock.exists(), "lock must be released after the run"


def test_lock_released_after_failure(repo_with_origin):
    repo, _ = repo_with_origin
    run_maintenance(repo, mode="violate")
    assert not (repo / "run.lock").exists()


# --- preflight ----------------------------------------------------------------

def test_dirty_tree_refuses_to_run(repo_with_origin):
    repo, _ = repo_with_origin
    (repo / "INDEX.md").write_text("# dirtied\n", encoding="utf-8")
    result = run_maintenance(repo)
    assert result.returncode != 0
    assert "uncommitted changes" in result.stderr


def test_push_rejection_re_pulls_and_re_runs_every_merge_gate(repo_with_origin):
    """FR-28 step 10 / FR-30: a rejected push means re-pull, re-gate, retry.
    The retry used to re-run only two lints, so a merge that left the manifest
    stale or a skill unit malformed could still be pushed."""
    repo, origin = repo_with_origin
    before = origin_head(origin)

    result = run_maintenance(repo, mode="race")
    assert result.returncode == 0, result.stderr
    assert origin_head(origin) != before

    log = (repo / "log.md").read_text(encoding="utf-8")
    assert "push rejected (attempt 1)" in log
    assert "pushed" in log
    # Every merge gate ran twice: once before the first push, once after the merge.
    for gate in ("lint_citations", "lint_links", "lint_skills"):
        assert log.count(f"{gate}: PASS") >= 2, f"{gate} did not re-run after the merge:\n{log}"


def test_wrapper_ingests_dropped_sources_and_the_run_commits_them(repo_with_origin):
    """A11 on the laptop path: the wrapper ingests before the headless run, and
    the ingested artifacts are gate-clean, so the stub's commit pushes."""
    repo, origin = repo_with_origin
    drop_file(repo, "paper.pdf", make_pdf("A dropped paper"), sidecar={"title": "A dropped paper"})
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@localhost",
                    "commit", "-qm", "drop"], check=True)

    result = run_maintenance(repo)
    assert result.returncode == 0, result.stderr
    tree = subprocess.run(["git", "-C", str(origin), "ls-tree", "-r", "--name-only", "main"],
                          capture_output=True, text=True, check=True).stdout
    assert any(line.startswith("reference/a-dropped-paper--") for line in tree.splitlines())
    assert any(line.startswith("raw/") and line.endswith(".pdf") for line in tree.splitlines())
    assert "drop/paper.pdf" not in tree
    assert "ingest_drops: drop/paper.pdf" in (repo / "log.md").read_text()


def test_start_line_names_the_agents_handed_to_the_run(repo_with_origin):
    """NFR-2: log.md records the agents dispatched. The wrapper knows exactly
    which definitions it handed to claude -p, which is the set any dispatch
    draws from."""
    repo, _ = repo_with_origin
    assert run_maintenance(repo).returncode == 0
    log = (repo / "log.md").read_text(encoding="utf-8")
    start = next(line for line in log.splitlines() if "maintenance_run: start" in line)
    assert "mode=A" in start
    for name in ("orchestrator", "critic", "skill-smith"):
        assert name in start, start


def test_missing_config_key_hard_fails(repo_with_origin):
    repo, _ = repo_with_origin
    import yaml
    cfg = yaml.safe_load((repo / "config.yml").read_text(encoding="utf-8"))
    del cfg["budget"]["max_turns"]
    (repo / "config.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c",
                    "user.email=t@localhost", "commit", "-aqm", "break config"], check=True)
    result = run_maintenance(repo)
    assert result.returncode != 0
    assert "config" in result.stderr.lower()


def test_missing_embedding_key_hard_fails(repo_with_origin):
    """FR-2 names embedding.{enabled,model}; they were the two keys nothing
    required."""
    repo, _ = repo_with_origin
    import yaml
    cfg = yaml.safe_load((repo / "config.yml").read_text(encoding="utf-8"))
    del cfg["embedding"]["model"]
    (repo / "config.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c",
                    "user.email=t@localhost", "commit", "-aqm", "break config"], check=True)
    result = run_maintenance(repo)
    assert result.returncode != 0
    assert "embedding.model" in result.stderr


def test_help_exits_zero():
    result = subprocess.run([str(MAINTENANCE), "--help"], capture_output=True, text=True)
    assert result.returncode == 0 and "Usage:" in result.stdout


def test_usage_error_exits_two(tmp_path):
    result = subprocess.run([str(MAINTENANCE), "--bogus"], capture_output=True, text=True)
    assert result.returncode == 2
