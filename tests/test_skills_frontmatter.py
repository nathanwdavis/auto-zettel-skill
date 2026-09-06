"""Every skill in skills/ stays portable and discoverable.

The frontmatter rule is not style: a field outside the six portable Agent
Skills fields fails validation on packaging and upload, so a sub-skill that
drifts is one nobody can install. The other rules here are the ones that
silently produce a skill that exists but never triggers -- a name that does not
match its directory, a description with no trigger language, a body that never
consumes its arguments.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import PLUGIN_ROOT

SKILLS_DIR = PLUGIN_ROOT / "skills"
ROOT_SKILL = SKILLS_DIR / "zettel-bootstrap" / "SKILL.md"

#: FR-14/NFR-6. Anything outside this set triggers "Unexpected fields in
#: frontmatter" when the skill is packaged or uploaded for Cowork/cloud use.
PORTABLE_FIELDS = {"name", "description", "license", "compatibility",
                   "metadata", "allowed-tools"}
DESCRIPTION_CAP = 1024
BODY_LINE_CAP = 500

SUB_SKILLS = ("zettel-ingest", "zettel-query", "zettel-ask")


def skill_dirs() -> list[Path]:
    return sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())


def load(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), f"{path}: no frontmatter"
    _, raw, body = text.split("---\n", 2)
    return yaml.safe_load(raw), body


@pytest.mark.parametrize("directory", skill_dirs(), ids=lambda p: p.name)
def test_every_skill_dir_has_a_skill_md(directory):
    assert (directory / "SKILL.md").is_file()


@pytest.mark.parametrize("directory", skill_dirs(), ids=lambda p: p.name)
def test_frontmatter_uses_only_the_six_portable_fields(directory):
    meta, _ = load(directory / "SKILL.md")
    extra = set(meta) - PORTABLE_FIELDS
    assert not extra, f"{directory.name}: non-portable frontmatter fields {sorted(extra)}"


@pytest.mark.parametrize("directory", skill_dirs(), ids=lambda p: p.name)
def test_name_matches_its_directory(directory):
    meta, _ = load(directory / "SKILL.md")
    assert meta["name"] == directory.name


@pytest.mark.parametrize("directory", skill_dirs(), ids=lambda p: p.name)
def test_description_is_within_the_cap_and_carries_trigger_language(directory):
    meta, _ = load(directory / "SKILL.md")
    description = meta["description"]
    assert 0 < len(description) <= DESCRIPTION_CAP, len(description)
    assert "<" not in description and ">" not in description, "no XML tags (FR-14)"
    # "what it does AND when Claude should use it" -- the second half is what
    # makes a skill trigger, and is the half that gets dropped.
    assert "Use when" in description


@pytest.mark.parametrize("directory", skill_dirs(), ids=lambda p: p.name)
def test_allowed_tools_are_pascal_case_tool_names(directory):
    meta, _ = load(directory / "SKILL.md")
    tools = [t.strip() for t in str(meta.get("allowed-tools", "")).split(",") if t.strip()]
    assert tools, f"{directory.name}: declares no tools"
    for tool in tools:
        assert tool[0].isupper() and "_" not in tool, f"{directory.name}: {tool!r}"


@pytest.mark.parametrize("name", SUB_SKILLS)
def test_sub_skills_exist_and_consume_their_arguments(name):
    meta, body = load(SKILLS_DIR / name / "SKILL.md")
    assert "$ARGUMENTS" in body, f"{name}: never uses the text the user typed"
    assert meta["metadata"]["parent"] == "zettel-bootstrap"


@pytest.mark.parametrize("name", SUB_SKILLS)
def test_sub_skills_route_into_the_scripts(name):
    """A sub-skill that reimplements the flow in prose drifts from the script."""
    _, body = load(SKILLS_DIR / name / "SKILL.md")
    assert "CLAUDE_PLUGIN_ROOT" in body, "resolves the plugin root for both install routes"
    assert "session_cycle.sh" in body or "query.py" in body


@pytest.mark.parametrize("name", SUB_SKILLS)
def test_sub_skills_say_what_to_do_on_a_held_lock(name):
    """Exit 3 is a success that reads like a failure; every entry point must say so."""
    _, body = load(SKILLS_DIR / name / "SKILL.md")
    if name == "zettel-query":
        assert "Exit 3" in body or "exit 3" in body
    else:
        assert "3" in body and "Stand down" in body


def test_the_sub_skills_delineate_themselves_from_each_other():
    """Three overlapping skills need a stated boundary or they trigger on each other."""
    for name in SUB_SKILLS:
        meta, _ = load(SKILLS_DIR / name / "SKILL.md")
        others = [o for o in SUB_SKILLS if o != name]
        assert "Do not use" in meta["description"], name
        assert any(o in meta["description"] for o in others), name


def test_root_skill_stays_within_the_body_cap():
    _, body = load(ROOT_SKILL)
    lines = len(body.splitlines())
    assert lines < BODY_LINE_CAP, f"SKILL.md body is {lines} lines (cap {BODY_LINE_CAP})"


def test_root_skill_routes_to_every_sub_skill():
    _, body = load(ROOT_SKILL)
    for name in SUB_SKILLS:
        assert name in body, f"the router never mentions {name}"


def test_setup_script_links_every_skill_not_just_the_root():
    """A sub-skill nobody links is a slash command that does not exist."""
    setup = (PLUGIN_ROOT / "ci" / "setup-environment.sh").read_text(encoding="utf-8")
    assert 'skills/zettel-bootstrap" "$HOME/.claude/skills/zettel-bootstrap"' not in setup, \
        "the single-skill symlink is gone"
    assert "skills/*/" in setup, "the setup script loops over every skill directory"
