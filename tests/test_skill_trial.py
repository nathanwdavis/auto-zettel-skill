"""skill_trial.py: the FR-36 A/B harness, driven by the stub claude."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from conftest import PLUGIN_ROOT, plant_skill, run_script
from zettel_lib import impact
from zettel_lib.repo import ContentRepo

STUB = PLUGIN_ROOT / "tests" / "stub_claude" / "claude"


def repo_hash(repo: Path) -> str:
    """Everything except the two ledgers a trial is allowed to append to."""
    digest = hashlib.sha256()
    for p in sorted(repo.rglob("*")):
        rel = str(p.relative_to(repo))
        if p.is_file() and rel not in ("log.md", "skill-impact.md"):
            digest.update(rel.encode() + p.read_bytes())
    return digest.hexdigest()


@pytest.fixture
def trial_repo(clean_repo: Path) -> Path:
    plant_skill(clean_repo, "demo-skill")
    run_script("capture.py", clean_repo, "inquiry", "Does compounding need atomicity?")
    run_script("capture.py", clean_repo, "inquiry", "What makes notes reusable?")
    return clean_repo


def trial(repo: Path, *args: str):
    return run_script("skill_trial.py", repo, "--skill", "demo-skill",
                      "--claude-bin", str(STUB), "--seed", "1", *args)


def test_trial_scores_both_arms_and_never_touches_the_repo(trial_repo, tmp_path):
    out = tmp_path / "scores.json"
    before = repo_hash(trial_repo)

    result = trial(trial_repo, "--out", str(out))
    assert result.returncode == 0, result.stdout + result.stderr
    assert repo_hash(trial_repo) == before, \
        "a trial may only append to log.md and skill-impact.md"

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["skill"] == "demo-skill"
    assert len(data["questions"]) == 2  # only two inquiries exist
    for entry in data["questions"]:
        for arm in ("with", "without"):
            assert 0.0 <= entry[arm]["score"] <= 1.0
    # the stub's with-arm cites a real key and judges higher: with > without
    assert data["means"]["with"] > data["means"]["without"]
    assert data["delta"] > 0

    records = impact.records(ContentRepo(trial_repo))
    assert records[-1].event == "trial"
    assert "with=" in records[-1].scores
    log = (trial_repo / "log.md").read_text(encoding="utf-8")
    assert "skill_trial: demo-skill with=" in log


def test_trial_respects_question_cap(trial_repo, tmp_path):
    out = tmp_path / "scores.json"
    result = trial(trial_repo, "--questions", "1", "--out", str(out))
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(json.loads(out.read_text(encoding="utf-8"))["questions"]) == 1


def test_no_inquiries_is_a_failure_not_a_fabrication(clean_repo):
    plant_skill(clean_repo, "demo-skill")
    result = trial(clean_repo)
    assert result.returncode == 1
    assert "no inquiries" in result.stderr
    assert "skill_trial: FAILED" in (clean_repo / "log.md").read_text(encoding="utf-8")


def test_missing_skill_is_a_failure(trial_repo):
    result = run_script("skill_trial.py", trial_repo, "--skill", "no-such-skill",
                        "--claude-bin", str(STUB))
    assert result.returncode == 1


def test_control_arm_copy_lacks_the_candidate(trial_repo, tmp_path):
    """The without-arm's isolation is the tree itself, not a polite prompt."""
    workdir = tmp_path / "arms"
    seen = tmp_path / "seen.txt"
    spy = tmp_path / "spy"
    spy.write_text(
        "#!/usr/bin/env bash\n"
        f"if [ -d skills/demo-skill ]; then echo with >> {seen}; "
        f"else echo without >> {seen}; fi\n"
        "exec \"%s\" \"$@\"\n" % STUB,
        encoding="utf-8")
    spy.chmod(0o755)

    result = run_script("skill_trial.py", trial_repo, "--skill", "demo-skill",
                        "--claude-bin", str(spy), "--seed", "1",
                        "--questions", "1", "--workdir", str(workdir),
                        "--out", str(tmp_path / "s.json"))
    assert result.returncode == 0, result.stdout + result.stderr
    arms = seen.read_text(encoding="utf-8").split()
    assert "with" in arms and "without" in arms
    assert not workdir.exists(), "trial work trees must be cleaned up"
