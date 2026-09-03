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
