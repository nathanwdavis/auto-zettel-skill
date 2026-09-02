"""check_skill_sandbox.py: the AC-37 diff-scoped gate.

conftest fixtures are not git repositories, and this gate is *about* git
history, so each test inits and commits the fixture itself to create the
base ref the check diffs against.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conftest import plant_skill, run_script, rules
from zettel_lib.repo import ContentRepo


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True).stdout


@pytest.fixture
def git_repo(clean_repo: Path) -> Path:
    git(clean_repo, "init", "-q", "-b", "main")
    git(clean_repo, "add", "-A")
    git(clean_repo, "-c", "user.name=t", "-c", "user.email=t@localhost",
        "commit", "-q", "-m", "base")
    return clean_repo


def check(repo: Path, *extra: str):
    return run_script("check_skill_sandbox.py", repo, "--base", "HEAD", *extra)


def test_clean_worktree_passes(git_repo):
    result = check(git_repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_legitimate_smith_writes_pass_strict(git_repo):
    plant_skill(git_repo, "demo-skill")
    ContentRepo(git_repo).append_log("skill-smith: proposed demo-skill")
    result = check(git_repo, "--strict")
    assert result.returncode == 0, result.stdout + result.stderr


def test_note_edit_escapes_strict_but_not_whole_cycle(git_repo):
    perm = next((git_repo / "permanent").glob("*.md"))
    perm.write_text(perm.read_text(encoding="utf-8") + "\nSmith was here.\n",
                    encoding="utf-8")
    assert check(git_repo).returncode == 0
    result = check(git_repo, "--strict")
    assert result.returncode != 0
    assert "sandbox-escape" in rules(result)


def test_untracked_file_outside_sandbox_escapes_strict(git_repo):
    (git_repo / "planted.txt").write_text("stray\n", encoding="utf-8")
    result = check(git_repo, "--strict")
    assert "sandbox-escape" in rules(result)


def test_log_rewrite_is_caught(git_repo):
    log = git_repo / "log.md"
    log.write_text(log.read_text(encoding="utf-8").replace(
        "# Operation log", "# Doctored log"), encoding="utf-8")
    result = check(git_repo)
    assert result.returncode != 0
    assert "log-rewritten" in rules(result)


def test_log_append_passes(git_repo):
    ContentRepo(git_repo).append_log("just growing")
    assert check(git_repo).returncode == 0


def test_impact_rewrite_is_caught(git_repo):
    impact_md = git_repo / "skill-impact.md"
    impact_md.write_text("# rewritten from scratch\n", encoding="utf-8")
    result = check(git_repo)
    assert "skill-impact-rewritten" in rules(result)


def test_raw_edit_and_delete_are_caught_but_additions_pass(git_repo):
    (git_repo / "raw" / "new-capture.txt").write_text("fresh\n", encoding="utf-8")
    assert check(git_repo).returncode == 0

    # The TRACKED capture, chosen deterministically: iterdir() order is
    # filesystem-dependent and on some runners handed back the untracked
    # new-capture.txt, whose edit is (correctly) still just an addition.
    capture = next(p for p in sorted((git_repo / "raw").iterdir())
                   if p.name not in (".gitkeep", "new-capture.txt"))
    capture.write_text("doctored\n", encoding="utf-8")
    result = check(git_repo)
    assert "raw-modified" in rules(result)

    git(git_repo, "checkout", "--", str(capture.relative_to(git_repo)))
    capture.unlink()
    result = check(git_repo)
    assert "raw-modified" in rules(result)


def test_bad_base_ref_is_a_usage_error(git_repo):
    result = run_script("check_skill_sandbox.py", git_repo,
                        "--base", "no-such-ref")
    assert result.returncode == 2
