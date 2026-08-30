"""new_worktree.sh: isolated worktrees sharing one .git (FR-26, AC-26)."""

from __future__ import annotations

import subprocess

import pytest

from conftest import PLUGIN_ROOT, build_clean_repo

SCRIPT = PLUGIN_ROOT / "scripts" / "new_worktree.sh"


@pytest.fixture
def git_repo(tmp_path):
    repo = build_clean_repo(tmp_path / "kb")
    git = ["git", "-C", str(repo)]
    subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["-c", "user.name=t", "-c", "user.email=t@localhost",
                          "commit", "-q", "-m", "genesis"], check=True)
    return repo


def worktree(repo, *args):
    return subprocess.run([str(SCRIPT), "--repo", str(repo), *args],
                          capture_output=True, text=True)


def test_two_worktrees_coexist_sharing_one_git(git_repo):
    r1 = worktree(git_repo, "--name", "agent-a")
    r2 = worktree(git_repo, "--name", "agent-b")
    assert r1.returncode == 0 and r2.returncode == 0, r1.stderr + r2.stderr

    p1, p2 = r1.stdout.strip(), r2.stdout.strip()
    assert p1 != p2
    listing = subprocess.run(["git", "-C", str(git_repo), "worktree", "list"],
                             capture_output=True, text=True, check=True).stdout
    assert p1 in listing and p2 in listing
    # both worktrees resolve to the same common .git directory
    commons = {
        subprocess.run(["git", "-C", p, "rev-parse", "--git-common-dir"],
                       capture_output=True, text=True, check=True).stdout.strip()
        for p in (p1, p2)
    }
    assert len(commons) == 1


def test_worktrees_dir_is_gitignored(git_repo):
    worktree(git_repo, "--name", "agent-a")
    status = subprocess.run(["git", "-C", str(git_repo), "status", "--porcelain",
                             "--untracked-files=all"],
                            capture_output=True, text=True, check=True).stdout
    assert ".worktrees/agent-a" not in status


def test_duplicate_name_fails(git_repo):
    assert worktree(git_repo, "--name", "agent-a").returncode == 0
    dup = worktree(git_repo, "--name", "agent-a")
    assert dup.returncode != 0
    assert "already exists" in dup.stderr


def test_remove_cleans_worktree_and_branch(git_repo):
    path = worktree(git_repo, "--name", "agent-a").stdout.strip()
    assert worktree(git_repo, "--name", "agent-a", "--remove").returncode == 0
    listing = subprocess.run(["git", "-C", str(git_repo), "worktree", "list"],
                             capture_output=True, text=True, check=True).stdout
    assert path not in listing
    branches = subprocess.run(["git", "-C", str(git_repo), "branch"],
                              capture_output=True, text=True, check=True).stdout
    assert "agent-a" not in branches


def test_invalid_branch_name_rejected(git_repo):
    bad = worktree(git_repo, "--name", "evil name; rm -rf")
    assert bad.returncode != 0
    assert "invalid branch name" in bad.stderr
