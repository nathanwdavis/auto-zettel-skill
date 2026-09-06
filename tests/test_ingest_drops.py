"""ingest_drops.py: a dropped PDF becomes a capture, a reference note, and an INBOX task (A11)."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess

import pytest

from conftest import REF_KEY, SCRIPTS, drop_file, load, make_pdf, run_script
from zettel_lib import http
from zettel_lib.repo import ContentRepo

import ingest_drops

DOI = "10.1145/3477132.3483540"
CROSSREF_OK = http.Response(200, json.dumps({"status": "ok", "message": {
    "DOI": DOI, "type": "proceedings-article", "title": ["A Real Paper"],
    "author": [{"family": "Tang", "given": "Liyan"}, {"family": "Vu", "given": "Tu"}],
    "issued": {"date-parts": [[2026, 8]]}, "container-title": ["Proc. of Something"],
    "publisher": "ACM"}}), {})


def tree_hash(repo) -> str:
    digest = hashlib.sha256()
    for p in sorted(x for x in repo.rglob("*") if x.is_file() and ".git" not in x.parts):
        digest.update(str(p.relative_to(repo)).encode())
        digest.update(p.read_bytes())
    return digest.hexdigest()


def references(repo):
    return sorted(p.name for p in (repo / "reference").glob("*.md"))


def gates_pass(repo):
    assert run_script("verify_refs.py", repo, "--offline").returncode == 0
    for script in ("build_manifest.py --check", "lint_citations.py", "lint_links.py"):
        name, *extra = script.split()
        result = run_script(name, repo, *extra)
        assert result.returncode == 0, f"{script}:\n{result.stdout}\n{result.stderr}"


def test_sidecar_drop_becomes_capture_reference_and_inbox_task(clean_repo):
    drop_file(clean_repo, "luhmann.pdf", make_pdf("Communicating with slip boxes"),
              sidecar={"title": "Communicating with Slip Boxes", "author": ["Luhmann, Niklas"],
                       "year": 1981, "isbn": "9783000000001", "priority": "high",
                       "notes": "The origin text."})
    result = run_script("ingest_drops.py", clean_repo)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("ingested\tdrop/luhmann.pdf\t")

    assert not (clean_repo / "drop" / "luhmann.pdf").exists()
    assert not (clean_repo / "drop" / "luhmann.yml").exists()
    key = [n for n in references(clean_repo) if n.startswith("communicating-with-slip-boxes--")][0]
    note = load(clean_repo, f"reference/{key}")
    capture = note.meta["raw_capture"]
    assert capture.startswith("raw/") and capture.endswith(".pdf")
    assert (clean_repo / capture).read_bytes()[:5] == b"%PDF-"
    assert (clean_repo / capture).with_suffix(".txt").exists(), "text extraction sits beside the PDF"
    assert note.meta["csl_json"]["author"] == [{"family": "Luhmann", "given": "Niklas"}]
    assert note.meta["csl_json"]["issued"] == {"date-parts": [[1981]]}
    assert note.meta["csl_json"]["ISBN"] == "9783000000001"
    assert note.meta["provenance"]["dropped_as"] == "luhmann.pdf"
    inbox = (clean_repo / "INBOX.md").read_text(encoding="utf-8")
    assert "Dropped source ready: Communicating with Slip Boxes" in inbox
    assert "Priority: high" in inbox and "The origin text." in inbox
    log = (clean_repo / "log.md").read_text(encoding="utf-8")
    assert "ingest_drops: drop/luhmann.pdf -> reference/" in log
    gates_pass(clean_repo)


def test_doi_in_the_text_is_found_and_crossref_enriches(clean_repo):
    drop_file(clean_repo, "paper.pdf",
              make_pdf(f"Some preprint header\nDOI: {DOI}\nAbstract text here."))
    transport = http.CassetteTransport({"api.crossref.org": CROSSREF_OK})
    results = ingest_drops.ingest(ContentRepo(clean_repo), mailto="me@example.org",
                                  transport=transport)
    assert [r["kind"] for r in results] == ["ingested"]
    assert any("mailto=me%40example.org" in url for url in transport.calls)
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    csl = note.meta["csl_json"]
    assert csl["title"] == "A Real Paper" and csl["DOI"] == DOI
    assert csl["author"][0] == {"family": "Tang", "given": "Liyan"}
    assert csl["container-title"] == "Proc. of Something"
    assert note.meta["source_tier"] == "peer-reviewed"
    assert results[0]["key"].startswith("a-real-paper--")


def test_pdf_without_identifiers_verifies_on_the_capture(clean_repo):
    drop_file(clean_repo, "notes-from-a-talk.pdf",
              make_pdf("Slip-box practice in the field\nA talk given somewhere, undated."))
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    assert results[0]["kind"] == "ingested"
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert note.meta["title"] == "Slip-box practice in the field", "first usable line becomes the title"
    assert note.meta["source_tier"] == "reputable-secondary"
    gates_pass(clean_repo)
    verified = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert verified.meta["verification"]["method"] == "raw-capture"


def test_duplicate_of_an_existing_reference_is_marked_not_ingested(clean_repo):
    before = references(clean_repo)
    drop_file(clean_repo, "ahrens-again.pdf", make_pdf("Another copy"),
              sidecar={"title": "Ahrens again", "isbn": "9781542866507"})
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    assert results[0]["kind"] == "duplicate" and results[0]["duplicate_of"] == REF_KEY
    assert references(clean_repo) == before
    marked = clean_repo / "drop" / f"ahrens-again.duplicate-of-{REF_KEY}.pdf"
    assert marked.exists() and marked.with_suffix(".yml").exists()
    assert "duplicates an existing reference" in (clean_repo / "INBOX.md").read_text()
    # marked files are skipped next time
    assert ingest_drops.ingest(ContentRepo(clean_repo), offline=True) == []


def test_oversize_drop_is_marked_and_reported(clean_repo):
    import yaml
    cfg = yaml.safe_load((clean_repo / "config.yml").read_text())
    cfg["fetch"]["max_capture_mb"] = 1
    (clean_repo / "config.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    path = drop_file(clean_repo, "huge.pdf", make_pdf("big"))
    os.truncate(path, 2 * 1024 * 1024)
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    assert results[0]["kind"] == "too-large"
    assert (clean_repo / "drop" / "huge.too-large.pdf").exists()
    assert "too large" in (clean_repo / "INBOX.md").read_text()
    assert not list((clean_repo / "raw").glob("*huge*"))


def test_list_is_read_only_and_a_second_run_is_a_noop(clean_repo):
    drop_file(clean_repo, "one.pdf", make_pdf("One source"), sidecar={"title": "One"})
    before = tree_hash(clean_repo)
    result = run_script("ingest_drops.py", clean_repo, "--list")
    assert result.returncode == 0 and result.stdout.strip() == "drop/one.pdf"
    assert tree_hash(clean_repo) == before

    assert run_script("ingest_drops.py", clean_repo).returncode == 0
    after = tree_hash(clean_repo)
    result = run_script("ingest_drops.py", clean_repo)
    assert result.returncode == 0 and "nothing pending" in result.stdout
    assert tree_hash(clean_repo) == after


def test_text_drops_are_accepted_as_their_own_capture(clean_repo):
    drop_file(clean_repo, "blog-post.md", b"# A blog post\n\nWith content.\n",
              sidecar={"title": "A blog post", "url": "https://example.org/post",
                       "source_tier": "general-web"})
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    assert results[0]["capture"].endswith(".md")
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert note.meta["source_tier"] == "general-web"
    assert note.meta["csl_json"]["URL"] == "https://example.org/post"
    gates_pass(clean_repo)


def test_degrades_without_pypdf(clean_repo, monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "pypdf", None)  # import raises ImportError
    drop_file(clean_repo, "scan.pdf", make_pdf("unreadable without pypdf"))
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    assert results[0]["kind"] == "ingested"
    assert any("pypdf is not installed" in w for w in results[0]["warnings"])
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert note.meta["title"] == "scan", "filename is the last-resort title"
    assert not (clean_repo / results[0]["capture"]).with_suffix(".txt").exists()


def test_the_move_passes_the_sandbox_gate(clean_repo):
    git = ["git", "-C", str(clean_repo)]
    subprocess.run(git + ["init", "-q", "-b", "main"], check=True)
    drop_file(clean_repo, "paper.pdf", make_pdf("Dropped before the base commit"),
              sidecar={"title": "Dropped paper"})
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["-c", "user.name=t", "-c", "user.email=t@localhost",
                          "commit", "-qm", "base with a drop"], check=True)
    assert run_script("ingest_drops.py", clean_repo).returncode == 0
    result = run_script("check_skill_sandbox.py", clean_repo, "--base", "HEAD")
    assert result.returncode == 0, result.stdout


def test_help_and_usage(clean_repo):
    assert run_script("ingest_drops.py", clean_repo, "--help").returncode == 0


# --- full-text, page-aware extraction (A12) -----------------------------------
# The extraction is what a literature note is written from, so truncating it at
# five pages meant a session could neither read past page five nor cite a
# locator it had not seen. Identity stays on the front pages, though: a DOI
# deep in a paper is nearly always a cited work's, not the source's own.

def test_every_page_is_extracted_with_page_markers(clean_repo):
    drop_file(clean_repo, "long.pdf", make_pdf(pages=[
        "Front matter and the title line here",
        "Page two body text",
        "Page three body text",
        "Page four body text",
        "Page five body text",
        "Page six says something quotable",
    ]), sidecar={"title": "A Long Paper"})
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    assert results[0]["kind"] == "ingested"
    text = (clean_repo / results[0]["capture"]).with_suffix(".txt").read_text(encoding="utf-8")
    assert "--- page 6 ---" in text
    assert "quotable" in text, "a late page must survive to be citable"
    assert text.count("--- page ") == 6


def test_a_late_page_doi_is_not_taken_as_the_source_identity(clean_repo):
    """Page seven's DOI belongs to a work this paper cites."""
    pages = ["Title page with no identifier at all"] + [f"Body page {i}" for i in range(2, 7)]
    pages.append(f"References: see {DOI} for the related work")
    drop_file(clean_repo, "late.pdf", make_pdf(pages=pages))
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert "DOI" not in note.meta["csl_json"]
    text = (clean_repo / results[0]["capture"]).with_suffix(".txt").read_text(encoding="utf-8")
    assert DOI in text, "the citation is still in the extraction, just not the identity"


def test_an_early_page_doi_is_still_found(clean_repo):
    drop_file(clean_repo, "early.pdf", make_pdf(pages=[
        f"A Paper With Its Own DOI {DOI}", "Body page two", "Body page three"]))
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert note.meta["csl_json"]["DOI"] == DOI


def test_a_page_marker_never_becomes_the_title(clean_repo):
    """`--- page 1 ---` is 14 characters and would fit the title heuristic."""
    drop_file(clean_repo, "untitled.pdf", make_pdf(pages=["", "Body text on the second page"]))
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert "page" not in note.title.lower() or "---" not in note.title
    assert not note.title.startswith("---")


def test_an_oversize_extraction_is_truncated_with_a_warning(clean_repo, monkeypatch):
    monkeypatch.setattr(ingest_drops, "MAX_EXTRACT_CHARS", 200)
    drop_file(clean_repo, "big.pdf", make_pdf(pages=[f"Page {i} " + "filler " * 20
                                                     for i in range(1, 8)]),
              sidecar={"title": "A Big Scan"})
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    assert any("truncated" in w for w in results[0]["warnings"])
    text = (clean_repo / results[0]["capture"]).with_suffix(".txt").read_text(encoding="utf-8")
    assert len(text) < 600  # header + the 200 truncated chars


def test_ingest_and_capture_share_one_reference_builder(clean_repo):
    """Two callers, one builder -- or the two input routes drift apart."""
    from zettel_lib import references

    assert ingest_drops.build_reference is references.build_reference
    assert ingest_drops.crossref_csl is references.crossref_csl


# --- --file: the source a session was handed (A12) ----------------------------

def test_file_flag_copies_an_external_source_and_ingests_it(tmp_path, clean_repo):
    external = tmp_path / "attached.pdf"
    external.write_bytes(make_pdf("An attached source about slip boxes"))
    result = run_script("ingest_drops.py", clean_repo, "--file", str(external),
                        "--title", "An Attached Source", "--author", "Tester, Ada",
                        "--year", "2026", "--source-tier", "general-web", "--offline")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("ingested\t")
    assert external.exists(), "the caller's file is copied, never consumed"
    key = result.stdout.split("\t")[2]
    note = load(clean_repo, f"reference/{key}.md")
    assert note.title == "An Attached Source"
    assert note.meta["csl_json"]["author"][0] == {"family": "Tester", "given": "Ada"}
    assert note.meta["source_tier"] == "general-web"
    assert note.meta["verification"]["verified"] is True   # verified on its capture
    assert not list((clean_repo / "drop").glob("attached*")), "drop/ is left clean"


def test_file_ingest_is_gate_clean(tmp_path, clean_repo):
    external = tmp_path / "gated.pdf"
    external.write_bytes(make_pdf("A source that must pass the gates"))
    run_script("ingest_drops.py", clean_repo, "--file", str(external),
               "--title", "A Gated Source", "--offline")
    for gate in ("build_manifest.py", "lint_citations.py", "lint_links.py"):
        assert run_script(gate, clean_repo).returncode == 0, gate


def test_file_ingests_only_that_file(tmp_path, clean_repo):
    """A committed drop belongs to the next scheduled cycle, not to this session."""
    drop_file(clean_repo, "someone-elses.pdf", make_pdf("Committed for the next run"),
              sidecar={"title": "Someone Else's Source"})
    external = tmp_path / "mine.pdf"
    external.write_bytes(make_pdf("The source I was handed"))
    result = run_script("ingest_drops.py", clean_repo, "--file", str(external),
                        "--title", "Mine", "--offline")
    assert result.returncode == 0
    assert len(result.stdout.strip().splitlines()) == 1
    assert (clean_repo / "drop" / "someone-elses.pdf").exists()


def test_file_duplicate_discards_the_copy_and_exits_nonzero(tmp_path, clean_repo):
    external = tmp_path / "dup.pdf"
    external.write_bytes(make_pdf("Smart notes again"))
    result = run_script("ingest_drops.py", clean_repo, "--file", str(external),
                        "--title", "Smart Notes Again", "--isbn", "9781542866507", "--offline")
    assert result.returncode == 1
    assert REF_KEY in result.stdout or REF_KEY in result.stderr
    assert not list((clean_repo / "drop").glob("dup*")), "no litter, no INBOX entry"
    assert "duplicates an existing reference" not in (clean_repo / "INBOX.md").read_text()
    assert external.exists()


def test_file_name_collision_in_drop_is_refused(tmp_path, clean_repo):
    drop_file(clean_repo, "same.pdf", make_pdf("Already pending"))
    external = tmp_path / "same.pdf"
    external.write_bytes(make_pdf("A different source with the same filename"))
    result = run_script("ingest_drops.py", clean_repo, "--file", str(external), "--offline")
    # 2, not 1: staging is argument validation (a bad path, an unreadable type,
    # a name already pending), and usage errors exit 2 across every entry point.
    assert result.returncode == 2 and "already exists" in result.stderr


def test_sidecar_flags_without_file_are_a_usage_error(clean_repo):
    result = run_script("ingest_drops.py", clean_repo, "--title", "Orphaned flag")
    assert result.returncode == 2 and "describe a --file" in result.stderr


def test_file_staging_is_logged(tmp_path, clean_repo):
    external = tmp_path / "logged.pdf"
    external.write_bytes(make_pdf("Logged source"))
    run_script("ingest_drops.py", clean_repo, "--file", str(external),
               "--title", "Logged Source", "--offline")
    log = (clean_repo / "log.md").read_text(encoding="utf-8")
    assert "--file" in log and "staged as drop/logged.pdf" in log


# --- review findings on PR #17 ------------------------------------------------

def test_file_refuses_an_unsupported_source_type(tmp_path, clean_repo):
    """--file was the one way into raw/ that skipped pending()'s filter.

    A committed drop of the wrong type is silently ignored; --file copied it in,
    "extracted" replacement-character noise from it, and wrote a reference note
    citing it. raw/ is immutable, so that capture would then stay forever.
    """
    junk = tmp_path / "spreadsheet.xlsx"
    junk.write_bytes(b"PK\x03\x04 not a document this pipeline can read")
    result = run_script("ingest_drops.py", clean_repo, "--file", str(junk), "--offline")
    assert result.returncode == 2
    assert "unsupported source type" in result.stderr
    assert ".pdf" in result.stderr, "the message names what IS accepted"
    assert not list((clean_repo / "drop").glob("spreadsheet*")), "nothing was staged"
    assert not list((clean_repo / "raw").glob("*spreadsheet*"))


def test_file_accepts_every_type_a_committed_drop_would(tmp_path, clean_repo):
    """The two routes agree on what a source is."""
    for i, ext in enumerate(ingest_drops.SOURCE_EXTS):
        source = tmp_path / f"source{i}{ext}"
        source.write_bytes(make_pdf(f"A source {i}") if ext == ".pdf"
                           else f"A source about slip boxes {i}".encode())
        result = run_script("ingest_drops.py", clean_repo, "--file", str(source),
                            "--title", f"Accepted Source {i}", "--offline")
        assert result.returncode == 0, f"{ext}: {result.stderr}"


def test_a_scalar_sidecar_tag_is_one_tag_not_five(clean_repo):
    """`tags: notes` in YAML is the natural way to write one tag."""
    drop_file(clean_repo, "tagged.pdf", make_pdf("A tagged source"),
              sidecar={"title": "A Tagged Source", "tags": "notes"})
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert note.tags == ["notes"], "a string must not iterate into characters"


def test_a_comma_separated_sidecar_tag_string_splits_like_the_cli(clean_repo):
    drop_file(clean_repo, "multi.pdf", make_pdf("A multi-tagged source"),
              sidecar={"title": "A Multi Tagged Source", "tags": "notes, networks"})
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert note.tags == ["notes", "networks"]


def test_a_sidecar_tag_list_still_works(clean_repo):
    drop_file(clean_repo, "listed.pdf", make_pdf("A list-tagged source"),
              sidecar={"title": "A List Tagged Source", "tags": ["notes", "networks"]})
    results = ingest_drops.ingest(ContentRepo(clean_repo), offline=True)
    note = load(clean_repo, f"reference/{results[0]['key']}.md")
    assert note.tags == ["notes", "networks"]
