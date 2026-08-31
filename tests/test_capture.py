"""capture.py: hand-written input that the gates accept.

The gap this closes is concrete. Drop plain markdown into fleeting/ and
build_manifest raises on it, which fails the required check and takes the whole
cycle's PR down. These tests hold the line from the other side: whatever capture
writes must pass every gate, first time, without a human touching frontmatter.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import SCRIPTS, build_clean_repo, run_script
from zettel_lib import naming
from zettel_lib.frontmatter import Note

CAPTURE = SCRIPTS / "capture.py"


def capture(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CAPTURE), "--repo", str(repo), *args],
        capture_output=True, text=True, input=stdin,
    )


def gates(repo: Path) -> list[subprocess.CompletedProcess]:
    return [run_script(name, repo) for name in
            ("build_manifest.py", "lint_citations.py", "lint_links.py")]


def assert_gates_pass(repo: Path) -> None:
    for result in gates(repo):
        assert result.returncode == 0, f"{result.args[1]}:\n{result.stdout}\n{result.stderr}"


@pytest.fixture
def repo(tmp_path) -> Path:
    return build_clean_repo(tmp_path / "kb")


# --- the motivating gap -------------------------------------------------------

def test_hand_written_markdown_breaks_the_manifest(repo):
    """The reason capture.py exists: without it, casual capture fails the gates."""
    (repo / "fleeting" / "a-thought.md").write_text("Just a thought.\n", encoding="utf-8")
    result = run_script("build_manifest.py", repo)
    assert result.returncode != 0
    assert "frontmatter" in result.stderr


def test_captured_fleeting_note_passes_every_gate(repo):
    result = capture(repo, "fleeting", "A thought about atomicity")
    assert result.returncode == 0, result.stderr
    assert_gates_pass(repo)


# --- what capture writes ------------------------------------------------------

def test_fleeting_note_is_well_formed(repo):
    rel = capture(repo, "fleeting", "Small worlds", "--tags", "networks, graphs",
                  "--body", "Do citation graphs show it?").stdout.strip()
    note = Note.load(repo / rel)
    slug, note_id = naming.split_key(note.key)
    assert note.type == "fleeting"
    assert note.title == "Small worlds"
    assert note.stem == note.key == f"small-worlds--{note_id}"
    assert note.slug == slug
    assert note.id == note_id
    assert note.tags == ["networks", "graphs"]
    assert note.links == []
    assert "Do citation graphs show it?" in note.body


def test_inquiry_carries_the_fr6_schema(repo):
    rel = capture(repo, "inquiry", "What makes a claim atomic?",
                  "--priority", "high").stdout.strip()
    inquiry = Note.load(repo / rel)
    assert rel.startswith("inquiries/")
    assert inquiry.type == "inquiry"
    assert inquiry.question == "What makes a claim atomic?"
    assert inquiry.status == "new"
    assert inquiry.priority == "high"
    assert inquiry.result_notes == []
    # An inquiry's identity is its question; a duplicate `title` would drift.
    assert "title" not in inquiry.meta


def test_body_reads_from_stdin(repo):
    rel = capture(repo, "fleeting", "Piped", "--body", "-",
                  stdin="text from a pipe\n").stdout.strip()
    assert "text from a pipe" in Note.load(repo / rel).body


def test_json_output_shape(repo):
    payload = json.loads(capture(repo, "--json", "inquiry", "Why?").stdout)
    assert payload["kind"] == "inquiry"
    assert (repo / payload["path"]).exists()


def test_capture_is_logged(repo):
    capture(repo, "fleeting", "Logged")
    assert "capture: fleeting" in (repo / "log.md").read_text(encoding="utf-8")


# --- identity under bursts ----------------------------------------------------

def test_captures_in_the_same_minute_get_distinct_ids(repo):
    """IDs are minute-resolution and id_to_key is many-to-one.

    Without allocation, three thoughts jotted in one minute would share an ID
    and a bare-ID link would silently resolve to whichever was indexed last.
    """
    for title in ("First thought", "Second thought", "Third thought"):
        assert capture(repo, "fleeting", title).returncode == 0
    ids = [Note.load(p).id for p in sorted((repo / "fleeting").glob("*.md"))]
    assert len(set(ids)) == len(ids) == 3
    assert_gates_pass(repo)


def test_allocation_spans_notes_and_inquiries(repo):
    from capture import allocate_id
    from zettel_lib.repo import ContentRepo

    when = _dt.datetime(2027, 3, 1, 9, 0, tzinfo=_dt.timezone.utc)
    content = ContentRepo(repo)
    (repo / "inquiries" / f"already-taken--{naming.new_id(when)}.md").write_text(
        "---\ntype: inquiry\n---\n", encoding="utf-8")
    assert allocate_id(content, when) == naming.new_id(when + _dt.timedelta(minutes=1))


def test_duplicate_ids_are_a_lint_violation(repo):
    """The lint backs the allocator up, for notes capture.py did not write."""
    from conftest import rules

    twin = sorted((repo / "permanent").glob("*.md"))[0]
    note = Note.load(twin)
    clone_key = f"a-twin--{note.id}"
    (repo / "permanent" / f"{clone_key}.md").write_text(
        note.path.read_text(encoding="utf-8")
        .replace(f"key: {note.key}", f"key: {clone_key}")
        .replace(f"slug: {note.slug}", "slug: a-twin"),
        encoding="utf-8")
    result = run_script("lint_links.py", repo)
    assert result.returncode == 1
    assert "duplicate-id" in rules(result)


# --- awkward titles -----------------------------------------------------------

@pytest.mark.parametrize("title", ["Sönke Ahrens on notes", "日本語のタイトル", "???", "   x   "])
def test_awkward_titles_still_produce_valid_keys(repo, title):
    result = capture(repo, "fleeting", title)
    assert result.returncode == 0, result.stderr
    naming.split_key(Path(result.stdout.strip()).stem)
    assert_gates_pass(repo)


def test_empty_title_is_a_usage_error(repo):
    assert capture(repo, "fleeting", "   ").returncode == 2


def test_missing_repo_is_a_usage_error(tmp_path):
    assert capture(tmp_path / "nope", "fleeting", "x").returncode == 2


# --- INBOX --------------------------------------------------------------------

def test_inbox_append_preserves_existing_entries(repo):
    inbox = repo / "INBOX.md"
    inbox.write_text("# Inbox\n\n## 2026-01-01 — Existing\n\nDo not lose me.\n",
                     encoding="utf-8")
    capture(repo, "inbox", "New question", "--body", "Some detail.")
    text = inbox.read_text(encoding="utf-8")
    assert "Do not lose me." in text
    assert "New question" in text
    assert "Some detail." in text
    assert text.index("Existing") < text.index("New question")


def test_repeated_inbox_captures_accumulate(repo):
    for i in range(3):
        capture(repo, "inbox", f"Entry {i}")
    text = (repo / "INBOX.md").read_text(encoding="utf-8")
    assert all(f"Entry {i}" in text for i in range(3))


def test_inbox_capture_does_not_disturb_the_gates(repo):
    capture(repo, "inbox", "A question for the next run")
    assert_gates_pass(repo)
