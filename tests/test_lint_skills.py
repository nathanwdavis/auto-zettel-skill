"""lint_skills.py: the skill-layer wellformedness gate (FR-33/AC-34/AC-36)."""

from __future__ import annotations

from conftest import PERM_KEY, plant_skill, run_script, rules
from zettel_lib import impact
from zettel_lib.repo import ContentRepo


def test_empty_skills_dir_is_clean(clean_repo):
    result = run_script("lint_skills.py", clean_repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_wellformed_skill_passes(clean_repo):
    plant_skill(clean_repo, "demo-skill")
    result = run_script("lint_skills.py", clean_repo)
    assert result.returncode == 0, result.stdout + result.stderr


def test_missing_purpose_fails(clean_repo):
    d = plant_skill(clean_repo, "demo-skill")
    (d / "PURPOSE.md").unlink()
    result = run_script("lint_skills.py", clean_repo)
    assert result.returncode != 0
    assert "skill-missing-file" in rules(result)


def test_extra_file_fails(clean_repo):
    d = plant_skill(clean_repo, "demo-skill")
    (d / "notes.txt").write_text("stray\n", encoding="utf-8")
    result = run_script("lint_skills.py", clean_repo)
    assert "skill-extra-file" in rules(result)


def test_stray_file_directly_in_skills_fails(clean_repo):
    (clean_repo / "skills" / "loose.md").write_text("loose\n", encoding="utf-8")
    result = run_script("lint_skills.py", clean_repo)
    assert "skill-extra-file" in rules(result)


def test_name_mismatch_fails(clean_repo):
    d = plant_skill(clean_repo, "demo-skill")
    text = (d / "SKILL.md").read_text(encoding="utf-8")
    (d / "SKILL.md").write_text(
        text.replace("name: demo-skill", "name: other-name"), encoding="utf-8")
    result = run_script("lint_skills.py", clean_repo)
    assert "skill-name-mismatch" in rules(result)


def test_bad_status_fails(clean_repo):
    plant_skill(clean_repo, "demo-skill", status="rejected")
    result = run_script("lint_skills.py", clean_repo)
    assert "skill-bad-status" in rules(result)


def test_missing_section_fails(clean_repo):
    d = plant_skill(clean_repo, "demo-skill")
    text = (d / "PURPOSE.md").read_text(encoding="utf-8")
    (d / "PURPOSE.md").write_text(
        text.replace("## Origin\n", ""), encoding="utf-8")
    result = run_script("lint_skills.py", clean_repo)
    assert "purpose-missing-section" in rules(result)


def test_uncited_patterns_fails(clean_repo):
    plant_skill(clean_repo, "demo-skill", cite="no-such-note--209912312359")
    result = run_script("lint_skills.py", clean_repo)
    assert "purpose-uncited" in rules(result)


def test_rejected_create_may_not_be_reproposed(clean_repo):
    repo = ContentRepo(clean_repo)
    impact.append_record(repo, impact.Record(
        proposal_id="202609151200", event="proposed", skill="demo-skill",
        date="2026-09-15", kind="create", text="first try"))
    impact.append_record(repo, impact.Record(
        proposal_id="202609151200", event="Rejected", skill="demo-skill",
        date="2026-09-16", text="not useful"))
    plant_skill(clean_repo, "demo-skill")
    result = run_script("lint_skills.py", clean_repo)
    assert "re-proposed-skill" in rules(result)
    # ...but a patch to an existing skill of another name stays legal
    plant_skill(clean_repo, "other-skill", kind="patch", cite=PERM_KEY)
    (clean_repo / "skills" / "demo-skill" / "SKILL.md").unlink()
    (clean_repo / "skills" / "demo-skill" / "PURPOSE.md").unlink()
    (clean_repo / "skills" / "demo-skill").rmdir()
    result = run_script("lint_skills.py", clean_repo)
    assert result.returncode == 0, result.stdout + result.stderr
