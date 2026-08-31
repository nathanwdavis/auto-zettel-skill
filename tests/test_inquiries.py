"""FR-6: the inquiry lifecycle, its manifest index, and the AC-6 lint.

The rule with teeth is AC-6: an inquiry marked `answered` must point at the
permanent notes that answered it. Without it a run can close every question it
touches and leave the knowledge base no larger -- and the status field would
report health it does not have.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from conftest import PERM_KEY, LIT_KEY, SCRIPTS, build_clean_repo, load, rules, run_script
from zettel_lib.frontmatter import dump

INQ_ID = "202608301400"
INQ_KEY = f"what-makes-a-claim-atomic--{INQ_ID}"


def write_inquiry(repo: Path, **overrides) -> Path:
    meta = {
        "id": INQ_ID, "key": INQ_KEY, "slug": INQ_KEY.rsplit("--", 1)[0],
        "aliases": [INQ_ID], "type": "inquiry",
        "question": "What makes a claim atomic?",
        "status": "new", "priority": "normal", "asked_by": "human",
        "result_notes": [], "created": "2026-08-30", "updated": "2026-08-30",
    }
    meta.update(overrides)
    path = repo / "inquiries" / f"{meta['key']}.md"
    path.write_text(dump(meta, "Some context.\n"), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path) -> Path:
    return build_clean_repo(tmp_path / "kb")


def lint(repo: Path) -> subprocess.CompletedProcess:
    return run_script("lint_links.py", repo)


# --- AC-6 ---------------------------------------------------------------------

def test_answered_without_result_notes_fails(repo):
    write_inquiry(repo, status="answered")
    result = lint(repo)
    assert result.returncode == 1
    assert "unanswered-answer" in rules(result)


def test_answered_with_a_resolvable_permanent_note_passes(repo):
    write_inquiry(repo, status="answered", result_notes=[PERM_KEY])
    assert lint(repo).returncode == 0


def test_answered_resolves_a_bare_timestamp_id(repo):
    perm_id = load(repo, f"permanent/{PERM_KEY}.md").id
    write_inquiry(repo, status="answered", result_notes=[perm_id])
    assert lint(repo).returncode == 0


def test_unresolvable_result_note_fails(repo):
    write_inquiry(repo, status="answered", result_notes=["ghost-note--209901010000"])
    assert "unresolved-result-note" in rules(lint(repo))


def test_result_note_must_be_permanent(repo):
    """A literature note summarises a source; it does not answer a question."""
    write_inquiry(repo, status="answered", result_notes=[LIT_KEY])
    assert "result-note-type" in rules(lint(repo))


@pytest.mark.parametrize("status", ["new", "in-progress", "answered", "archived"])
def test_every_lifecycle_status_is_accepted(repo, status):
    write_inquiry(repo, status=status,
                  result_notes=[PERM_KEY] if status == "answered" else [])
    assert lint(repo).returncode == 0, status


def test_unknown_status_fails(repo):
    write_inquiry(repo, status="pondering")
    assert "bad-status" in rules(lint(repo))


def test_missing_question_fails(repo):
    write_inquiry(repo, question="")
    assert "missing-question" in rules(lint(repo))


def test_filename_must_match_the_key(repo):
    path = write_inquiry(repo)
    path.rename(path.with_name("renamed.md"))
    assert "filename-key-mismatch" in rules(lint(repo))


def test_unparseable_inquiry_is_reported_not_crashed(repo):
    (repo / "inquiries" / "junk.md").write_text("no frontmatter here\n", encoding="utf-8")
    result = lint(repo)
    assert result.returncode == 1
    assert "frontmatter" in rules(result)


def test_an_inquiry_is_not_a_graph_node(repo):
    """Inquiries carry no links, so the 1-1-1 rule must not be applied to them."""
    write_inquiry(repo)
    assert lint(repo).returncode == 0
    manifest = json.loads((repo / "manifest.json").read_text(encoding="utf-8"))
    assert INQ_KEY not in {n["key"] for n in manifest["notes"]}


# --- manifest indexing --------------------------------------------------------

def manifest_of(repo: Path) -> dict:
    assert run_script("build_manifest.py", repo).returncode == 0
    return json.loads((repo / "manifest.json").read_text(encoding="utf-8"))


def test_inquiries_are_indexed(repo):
    write_inquiry(repo, status="answered", priority="high", result_notes=[PERM_KEY])
    entry, = manifest_of(repo)["inquiries"]
    assert entry == {
        "key": INQ_KEY,
        "question": "What makes a claim atomic?",
        "status": "answered",
        "priority": "high",
        "result_notes": [PERM_KEY],
        "path": f"inquiries/{INQ_KEY}.md",
        "updated": "2026-08-30",
    }


def test_manifest_stays_byte_idempotent_with_inquiries(repo):
    write_inquiry(repo)
    first = manifest_of(repo)
    raw = (repo / "manifest.json").read_bytes()
    assert manifest_of(repo) == first
    assert (repo / "manifest.json").read_bytes() == raw
    assert run_script("build_manifest.py", repo, "--check").returncode == 0


def test_empty_inquiries_dir_yields_an_empty_block(repo):
    assert manifest_of(repo)["inquiries"] == []


# --- the reporter -------------------------------------------------------------

def inquiries_script(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return run_script("inquiries.py", repo, *args)


def test_reporter_lists_open_questions(repo):
    write_inquiry(repo)
    result = inquiries_script(repo)
    assert result.returncode == 0
    assert INQ_KEY in result.stdout


def test_reporter_filters_by_status(repo):
    write_inquiry(repo, status="archived")
    rows = json.loads(inquiries_script(repo, "--status", "new", "--json").stdout)
    assert rows == []
    rows = json.loads(inquiries_script(repo, "--status", "archived", "--json").stdout)
    assert [r["key"] for r in rows] == [INQ_KEY]


def test_reporter_orders_new_and_high_priority_first(repo):
    write_inquiry(repo, id="202608301401", key=f"low--202608301401", slug="low",
                  status="new", priority="low", question="Low?")
    write_inquiry(repo, id="202608301402", key=f"high--202608301402", slug="high",
                  status="new", priority="high", question="High?")
    write_inquiry(repo, id="202608301403", key=f"done--202608301403", slug="done",
                  status="archived", priority="high", question="Done?")
    rows = json.loads(inquiries_script(repo, "--json").stdout)
    assert [r["key"] for r in rows] == ["high--202608301402", "low--202608301401",
                                        "done--202608301403"]


def test_reporter_on_an_empty_repo(repo):
    assert "none" in inquiries_script(repo).stdout


def test_reporter_never_writes(repo):
    write_inquiry(repo)
    before = {p: p.read_bytes() for p in repo.rglob("*.md")}
    inquiries_script(repo, "--json")
    assert {p: p.read_bytes() for p in repo.rglob("*.md")} == before
