"""skill_review.py: propose / list / promote / reject (FR-35, FR-36, AC-33).

Each test git-inits its fixture: the review flow is about history (diff
capture at proposal time, restore points for rejection), so a plain directory
cannot exercise it.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from conftest import plant_skill, run_script
from zettel_lib import impact
from zettel_lib.repo import ContentRepo


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True,
        capture_output=True, text=True).stdout


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@localhost",
        "commit", "-q", "-m", message)


def note_hashes(repo: Path) -> dict[str, str]:
    return {
        str(p.relative_to(repo)): hashlib.sha256(p.read_bytes()).hexdigest()
        for d in ("fleeting", "literature", "permanent", "reference", "moc")
        for p in (repo / d).glob("*.md")
    }


@pytest.fixture
def git_repo(clean_repo: Path) -> Path:
    git(clean_repo, "init", "-q", "-b", "main")
    commit_all(clean_repo, "base")
    return clean_repo


def review(repo: Path, *args: str):
    return run_script("skill_review.py", repo, *args)


def propose(repo: Path, name: str = "demo-skill", kind: str = "create"):
    plant_skill(repo, name, kind=kind)
    result = review(repo, "propose", "--skill", name, "--kind", kind,
                    "--motivation", "agents keep reinventing this")
    return result


def test_propose_records_diff_and_logs(git_repo):
    result = propose(git_repo)
    assert result.returncode == 0, result.stdout + result.stderr

    records = impact.records(ContentRepo(git_repo))
    assert [r.event for r in records] == ["proposed"]
    assert records[0].kind == "create"
    # the diff captured the untracked proposal files' content (FR-36, A7)
    assert "SKILL.md" in records[0].diff and "PURPOSE.md" in records[0].diff
    assert "When to use" in records[0].diff
    log = (git_repo / "log.md").read_text(encoding="utf-8")
    assert "skill-smith: proposed demo-skill" in log


def test_propose_refuses_a_rejected_create(git_repo):
    propose(git_repo)
    commit_all(git_repo, "cycle: proposal")
    assert review(git_repo, "reject", "--skill", "demo-skill",
                  "--reason", "not useful").returncode == 0

    result = propose(git_repo)
    assert result.returncode == 1
    assert "re-proposed-skill" in result.stdout


def test_second_proposal_in_one_cycle_is_refused(git_repo):
    """FR-35/AC-35: exactly one proposal per cycle, mechanically. The cycle is
    read from log.md's start/finish markers; outside an open cycle a hand-run
    propose is always allowed."""
    repo = ContentRepo(git_repo)
    repo.append_log("remote_cycle: start (mode=B holder=test branch=zettel/run-1)")
    assert propose(git_repo, "first-skill").returncode == 0

    result = propose(git_repo, "second-skill")
    assert result.returncode == 1
    assert "second-proposal" in result.stdout and "first-skill" in result.stdout
    assert "REFUSED second proposal second-skill" in (git_repo / "log.md").read_text()
    assert [r.skill for r in impact.records(repo)] == ["first-skill"]

    repo.append_log("remote_cycle: finish zettel/run-1 (skill-rev=abc; lock released after push)")
    assert propose(git_repo, "third-skill").returncode == 0, "next cycle may propose again"


def test_propose_outside_any_cycle_is_allowed_after_a_closed_one(git_repo):
    repo = ContentRepo(git_repo)
    repo.append_log("maintenance_run: start (mode=A dry_run=0 agents=critic)")
    assert propose(git_repo, "first-skill").returncode == 0
    repo.append_log("maintenance_run: headless run complete (result: x.json)")
    assert propose(git_repo, "by-hand").returncode == 0


def test_list_reports_status(git_repo):
    propose(git_repo)
    result = review(git_repo, "list", "--json")
    assert result.returncode == 0
    assert '"demo-skill"' in result.stdout and '"proposed"' in result.stdout


def test_promote_flips_status_and_commits_only_the_skill_layer(git_repo):
    propose(git_repo)
    commit_all(git_repo, "cycle: proposal")
    before_notes = note_hashes(git_repo)

    result = review(git_repo, "promote", "--skill", "demo-skill",
                    "--reason", "clearly earning its keep")
    assert result.returncode == 0, result.stdout + result.stderr

    purpose = (git_repo / "skills" / "demo-skill" / "PURPOSE.md").read_text(encoding="utf-8")
    assert "status: approved" in purpose
    assert "| promoted | Accepted |" in purpose
    records = impact.records(ContentRepo(git_repo))
    assert records[-1].event == "Accepted"
    assert note_hashes(git_repo) == before_notes
    changed = git(git_repo, "show", "--name-only", "--format=", "HEAD").split()
    assert all(p.startswith("skills/") or p in ("skill-impact.md", "log.md")
               for p in changed), changed


def test_reject_create_removes_dir_and_never_touches_notes(git_repo):
    propose(git_repo)
    commit_all(git_repo, "cycle: proposal")
    before_notes = note_hashes(git_repo)

    result = review(git_repo, "reject", "--skill", "demo-skill",
                    "--reason", "scores regressed")
    assert result.returncode == 0, result.stdout + result.stderr

    assert not (git_repo / "skills" / "demo-skill").exists()
    assert note_hashes(git_repo) == before_notes, "AC-33"
    records = impact.records(ContentRepo(git_repo))
    assert records[-1].event == "Rejected"
    assert records[-1].text == "scores regressed"
    assert "SKILL.md" in records[-1].diff
    # the repo stays gate-clean after the rejection
    assert run_script("lint_skills.py", git_repo).returncode == 0


def test_reject_patch_restores_the_approved_content(git_repo):
    plant_skill(git_repo, "demo-skill", status="approved")
    commit_all(git_repo, "approved state")
    approved = (git_repo / "skills" / "demo-skill" / "SKILL.md").read_text(encoding="utf-8")

    # The smith's patch flow: edit the procedure AND flip PURPOSE back to
    # 'proposed' — a patched skill is a proposal again until re-approved
    # (FR-36 gates every create-or-edit), and that flip is also what marks
    # the pre-patch commit as the restore point.
    skill_md = git_repo / "skills" / "demo-skill" / "SKILL.md"
    skill_md.write_text(approved + "\n## A bad patch\nRegression.\n", encoding="utf-8")
    purpose_md = git_repo / "skills" / "demo-skill" / "PURPOSE.md"
    purpose_md.write_text(purpose_md.read_text(encoding="utf-8").replace(
        "status: approved", "status: proposed"), encoding="utf-8")
    result = review(git_repo, "propose", "--skill", "demo-skill",
                    "--kind", "patch", "--motivation", "tighten the procedure")
    assert result.returncode == 0, result.stdout + result.stderr
    commit_all(git_repo, "cycle: patch proposal")

    result = review(git_repo, "reject", "--skill", "demo-skill",
                    "--reason", "the patch made answers worse")
    assert result.returncode == 0, result.stdout + result.stderr
    assert skill_md.read_text(encoding="utf-8") == approved
    assert (git_repo / "skills" / "demo-skill" / "PURPOSE.md").exists()
    # a rejected PATCH does not ban the name — only rejected creates do (A7)
    assert "demo-skill" not in impact.rejected_creates(ContentRepo(git_repo))


def test_promote_refuses_lint_violations(git_repo):
    propose(git_repo)
    (git_repo / "skills" / "demo-skill" / "stray.txt").write_text("x\n", encoding="utf-8")
    commit_all(git_repo, "cycle: proposal + stray")
    result = review(git_repo, "promote", "--skill", "demo-skill",
                    "--reason", "should not work")
    assert result.returncode != 0
    assert "skill-extra-file" in result.stdout


def test_decision_refuses_a_poisoned_index(git_repo):
    propose(git_repo)
    commit_all(git_repo, "cycle: proposal")
    perm = next((git_repo / "permanent").glob("*.md"))
    perm.write_text(perm.read_text(encoding="utf-8") + "\npoison\n", encoding="utf-8")
    git(git_repo, "add", "--", str(perm.relative_to(git_repo)))

    result = review(git_repo, "promote", "--skill", "demo-skill",
                    "--reason", "sneaky")
    assert result.returncode != 0
    assert "staged" in result.stderr
