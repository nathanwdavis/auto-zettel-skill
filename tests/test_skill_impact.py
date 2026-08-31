"""zettel_lib.impact: the skill-impact.md parser/writer and its append-only law."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import build_clean_repo
from zettel_lib import impact
from zettel_lib.repo import ContentRepo

SCAFFOLD = """# Skill impact tracker

Prose header, as genesis writes it.

| date | proposal | target skill | outcome | reason |
|------|----------|--------------|---------|--------|
"""


@pytest.fixture
def repo(tmp_path: Path) -> ContentRepo:
    build_clean_repo(tmp_path / "kb")
    (tmp_path / "kb" / "skill-impact.md").write_text(SCAFFOLD, encoding="utf-8")
    return ContentRepo(tmp_path / "kb")


def rec(event="proposed", **kw):
    base = dict(proposal_id="202609151200", event=event, skill="demo-skill",
                date="2026-09-15", kind="create", text="agents keep reinventing X")
    base.update(kw)
    return impact.Record(**base)


def test_append_then_parse_round_trips(repo):
    impact.append_record(repo, rec(diff="+++ b/skills/demo-skill/SKILL.md\n+new"))
    impact.append_record(repo, rec(
        event="Rejected", text="scores regressed", scores="with=0.61 without=0.74 (n=3)"))

    records = impact.records(repo)
    assert [r.event for r in records] == ["proposed", "Rejected"]
    assert records[0].kind == "create"
    assert records[0].diff.endswith("+new")
    assert records[1].scores == "with=0.61 without=0.74 (n=3)"
    assert records[1].text == "scores regressed"

    text = (repo.root / "skill-impact.md").read_text(encoding="utf-8")
    assert text.count("| 2026-09-15 | 202609151200 | demo-skill |") == 2


def test_rejected_create_is_banned_but_rejected_patch_is_not(repo):
    impact.append_record(repo, rec())
    impact.append_record(repo, rec(event="Rejected", kind="", text="no"))
    impact.append_record(repo, rec(
        proposal_id="202610011200", skill="other-skill", kind="patch"))
    impact.append_record(repo, rec(
        proposal_id="202610011200", skill="other-skill", kind="",
        event="Rejected", text="bad patch"))
    assert impact.rejected_creates(repo) == {"demo-skill"}


def test_appends_are_append_only_by_construction(repo):
    before = (repo.root / "skill-impact.md").read_text(encoding="utf-8")
    impact.append_record(repo, rec())
    after = (repo.root / "skill-impact.md").read_text(encoding="utf-8")
    assert impact.is_append_only(before, after) == []


def test_is_append_only_rejects_edits_to_existing_records(repo):
    impact.append_record(repo, rec())
    old = (repo.root / "skill-impact.md").read_text(encoding="utf-8")

    assert impact.is_append_only(old, old.replace("proposed", "Accepted"))
    assert impact.is_append_only(old, old.replace(
        "| 2026-09-15", "").replace("\n\n\n", "\n\n"))
    # deleting the detail section
    assert impact.is_append_only(old, old[: old.index("## ")])
    # a legitimate append passes even though the new row lands mid-file
    impact.append_record(repo, rec(event="trial", scores="with=0.9 without=0.8 (n=3)"))
    new = (repo.root / "skill-impact.md").read_text(encoding="utf-8")
    assert impact.is_append_only(old, new) == []
    assert not new.startswith(old)  # ...which is why byte-prefix would be wrong


def test_pipes_and_newlines_are_flattened_in_table_cells(repo):
    impact.append_record(repo, rec(text="a | b\nmulti line"))
    text = (repo.root / "skill-impact.md").read_text(encoding="utf-8")
    row = next(l for l in text.splitlines() if l.startswith("| 2026-09-15"))
    assert "a \\| b multi line" in row


def test_unknown_event_is_refused(repo):
    with pytest.raises(impact.ImpactError):
        impact.append_record(repo, rec(event="pondered"))
