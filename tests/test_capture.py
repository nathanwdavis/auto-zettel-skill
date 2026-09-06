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

import capture as capture_mod
from conftest import PERM_KEY, REF_KEY, SCRIPTS, build_clean_repo, rules, run_script
from zettel_lib import http, naming
from zettel_lib.frontmatter import Note
from zettel_lib.repo import ContentRepo

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


def test_capture_leaves_the_manifest_current(repo):
    """A capture changes what the manifest indexes, and the content repo's
    required `gates` check rejects a stale manifest -- so a laptop capture
    committed as-is must already pass --check, with nobody re-running the
    generator by hand."""
    for kind, title in (("inquiry", "Does capture keep the manifest current?"),
                        ("fleeting", "A thought that must be indexed")):
        result = capture(repo, kind, title)
        assert result.returncode == 0, result.stderr
        check = run_script("build_manifest.py", repo, "--check")
        assert check.returncode == 0, f"stale after {kind} capture:\n{check.stderr}"


def test_preexisting_breakage_warns_but_does_not_eat_the_capture(repo):
    """Someone else's hand-written file must not make capture fail: the new
    artifact is well-formed by construction, and the failure attribution the
    tool exists for says the mess belongs to whoever made it."""
    (repo / "fleeting" / "hand-written.md").write_text("Just a thought.\n",
                                                      encoding="utf-8")
    result = capture(repo, "inquiry", "Survives a broken neighbour?")
    assert result.returncode == 0, result.stderr
    assert (repo / result.stdout.strip()).exists()
    assert "manifest could not be rebuilt" in result.stderr


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


# --- the note generators (A12) ------------------------------------------------
# The same gap as above, from the machine's side: the agents were told to write
# reference, literature, and permanent notes from templates/ by hand. These
# tests hold the line that a generator refuses at WRITE time what the lints
# refuse at gate time -- an unresolvable target, a relation outside FR-5, a
# literature note with no locator, a second reference for one source.

DOI = "10.48550/arXiv.2608.27454"
CROSSREF_OK = http.Response(200, json.dumps({"status": "ok", "message": {
    "DOI": DOI, "type": "journal-article", "title": ["A Captured Paper"],
    "author": [{"family": "Tang", "given": "Liyan"}],
    "issued": {"date-parts": [[2026, 8]]}, "container-title": ["A Journal"]}}), {})


def created(result: subprocess.CompletedProcess, repo: Path) -> Note:
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    return Note.load(repo / result.stdout.strip())


def test_reference_from_a_doi_is_enriched_and_verified_through_a_cassette(repo):
    transport = http.CassetteTransport({"api.crossref.org": CROSSREF_OK})
    path, payload = capture_mod.capture_reference(
        ContentRepo(repo), {"doi": DOI}, mailto="me@example.org", transport=transport)
    note = Note.load(path)
    assert note.meta["csl_json"]["title"] == "A Captured Paper"
    assert note.meta["csl_json"]["author"][0] == {"family": "Tang", "given": "Liyan"}
    assert note.meta["source_tier"] == "peer-reviewed"      # a DOI implies the tier
    assert note.meta["chicago_note"] and note.meta["chicago_bib"]
    assert note.meta["verification"]["verified"] is True    # crossref confirmed it
    assert payload["identity"] == f"doi:{DOI.lower()}"


def test_reference_offline_is_rendered_but_honestly_unverified(repo):
    result = capture(repo, "reference", "An Uncaptured Source",
                     "--author", "Tester, Ada", "--year", "2026",
                     "--url", "https://example.org/x", "--offline")
    note = created(result, repo)
    assert note.meta["chicago_note"], "Chicago strings are rendered at creation"
    assert note.meta["verification"]["verified"] is False
    assert "UNVERIFIED" in result.stderr and "fetch_source.py" in result.stderr
    # The gate must be the one that objects, and about exactly this.
    lint = run_script("lint_citations.py", repo)
    assert lint.returncode == 1
    assert rules(lint) == {"unverified-reference"}


def test_reference_duplicate_identity_is_refused_and_names_the_existing_key(repo):
    """FR-4: exactly one reference note per source, by registry identity."""
    result = capture(repo, "reference", "Smart Notes Again", "--isbn", "9781542866507")
    assert result.returncode == 2
    assert REF_KEY in result.stderr and "already exists" in result.stderr


def test_reference_needs_a_title_or_a_resolving_identifier(repo):
    result = capture(repo, "reference", "--offline")
    assert result.returncode == 2 and "needs a title" in result.stderr


def test_reference_passes_every_gate_once_its_source_is_captured(repo):
    """The honest path to green: capture the source, then verify."""
    result = capture(repo, "reference", "A Captured Source", "--author", "Tester, Ada",
                     "--year", "2026", "--offline")
    note = created(result, repo)
    (repo / "raw" / f"{note.id}-{note.slug}.txt").write_text("the source", encoding="utf-8")
    note.meta["raw_capture"] = f"raw/{note.id}-{note.slug}.txt"
    note.save()
    assert run_script("verify_refs.py", repo, "--offline").returncode == 0
    assert_gates_pass(repo)


def test_literature_note_passes_every_gate(repo):
    result = capture(repo, "literature", "Ada on capture", "--reference", REF_KEY,
                     "--locator", "p. 3", "--tags", "notes")
    note = created(result, repo)
    assert note.meta["reference"] == REF_KEY
    assert note.meta["locator"] == "p. 3"
    assert note.meta["links"] == [{"target_id": REF_KEY, "relation": "source"}]
    assert note.tags == ["notes"]
    assert_gates_pass(repo)


def test_literature_accepts_a_bare_reference_id(repo):
    note = created(capture(repo, "literature", "By id", "--reference",
                           REF_KEY.split("--")[1], "--locator", "ch. 2"), repo)
    assert note.meta["reference"] == REF_KEY


def test_literature_refuses_an_unknown_reference(repo):
    result = capture(repo, "literature", "Nope", "--reference",
                     "missing--209901010101", "--locator", "p. 1")
    assert result.returncode == 2 and "no reference note matches" in result.stderr


def test_literature_requires_a_locator(repo):
    result = capture(repo, "literature", "Nope", "--reference", REF_KEY, "--locator", "  ")
    assert result.returncode == 2 and "locator" in result.stderr


def test_permanent_note_with_typed_links_passes_every_gate(repo):
    note = created(capture(repo, "permanent", "Capture beats hand-writing",
                           "--link", f"{PERM_KEY}:supports",
                           "--link", f"{REF_KEY}:source"), repo)
    assert note.meta["links"] == [{"target_id": PERM_KEY, "relation": "supports"},
                                  {"target_id": REF_KEY, "relation": "source"}]
    assert_gates_pass(repo)


def test_permanent_refuses_a_relation_outside_fr5(repo):
    result = capture(repo, "permanent", "X", "--link", f"{PERM_KEY}:cites")
    assert result.returncode == 2 and "outside the FR-5 taxonomy" in result.stderr


def test_permanent_refuses_an_unresolved_target(repo):
    result = capture(repo, "permanent", "X", "--link", "missing--209901010101:supports")
    assert result.returncode == 2 and "resolves to no note" in result.stderr


def test_permanent_requires_at_least_one_link(repo):
    result = capture(repo, "permanent", "X")
    assert result.returncode == 2 and "1-1-1" in result.stderr


def test_permanent_refuses_a_malformed_link_spec(repo):
    result = capture(repo, "permanent", "X", "--link", "no-colon-here")
    assert result.returncode == 2 and "KEY:relation" in result.stderr


def test_permanent_warns_on_a_sourced_claim_without_a_verified_reference(repo):
    """A warning, not a refusal: the lint owns what 'sourced' means."""
    result = capture(repo, "permanent", "A claim", "--link", f"{PERM_KEY}:supports",
                     "--body", "Ahrens argues that notes compound.")
    assert result.returncode == 0
    assert "uncited-claim" in result.stderr
    assert run_script("lint_citations.py", repo).returncode == 1


def test_generators_leave_the_manifest_current(repo):
    capture(repo, "reference", "Fresh", "--author", "A, B", "--year", "2026", "--offline")
    assert run_script("build_manifest.py", repo, "--check").returncode == 0
    capture(repo, "literature", "Fresh lit", "--reference", REF_KEY, "--locator", "p. 9")
    assert run_script("build_manifest.py", repo, "--check").returncode == 0
    capture(repo, "permanent", "Fresh claim", "--link", f"{PERM_KEY}:analogous")
    assert run_script("build_manifest.py", repo, "--check").returncode == 0


def test_generator_json_output_carries_the_key(repo):
    result = capture(repo, "--json", "literature", "J", "--reference", REF_KEY,
                     "--locator", "p. 1")
    payload = json.loads(result.stdout)
    assert payload["kind"] == "literature"
    assert payload["key"] == Path(payload["path"]).stem


def test_reference_capture_is_logged_with_its_identity(repo):
    capture(repo, "reference", "Logged", "--url", "https://example.org/logged", "--offline")
    log = (repo / "log.md").read_text(encoding="utf-8")
    assert "capture: reference ->" in log
    assert "identity=url:example.org/logged" in log and "verified=no" in log
