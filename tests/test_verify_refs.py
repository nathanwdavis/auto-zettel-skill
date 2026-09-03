"""Reference verification: raw captures, metadata lookups, graceful degradation.

Network branches are driven through cassettes (see cassettes/README.md) because
this build environment's egress proxy blocks the upstream APIs.
"""

from __future__ import annotations

import json


import verify_refs
from conftest import REF_KEY, load, run_script
from zettel_lib import http

CROSSREF_OK = http.Response(
    200, json.dumps({"status": "ok", "message": {
        "DOI": "10.1145/3477132.3483540", "title": ["A Real Paper"],
        "type": "proceedings-article"}}), {})
CROSSREF_MISS = http.Response(404, json.dumps({"status": "error"}), {})
CROSSREF_RATE_LIMITED = http.Response(429, "", {"Retry-After": "0"})

OPENLIBRARY_OK = http.Response(
    200, json.dumps({"ISBN:9781542866507": {
        "title": "How to Take Smart Notes",
        "authors": [{"name": "Sönke Ahrens"}]}}), {})
OPENLIBRARY_MISS = http.Response(200, json.dumps({}), {})
GOOGLEBOOKS_OK = http.Response(
    200, json.dumps({"totalItems": 1, "items": [{"id": "abc"}]}), {})
GOOGLEBOOKS_MISS = http.Response(200, json.dumps({"totalItems": 0}), {})

ARXIV_OK = http.Response(
    200, "<feed><entry><title>WikiSkill</title><id>2608.27454</id></entry></feed>", {})
PUBMED_OK = http.Response(
    200, json.dumps({"result": {"12345678": {"title": "A PubMed Article"}}}), {})


def cassette(**pairs) -> http.CassetteTransport:
    return http.CassetteTransport(pairs)


def repo_of(path):
    from zettel_lib.repo import ContentRepo
    return ContentRepo(path)


def set_csl(repo, drop=(), **fields):
    """Rewrite the fixture reference's CSL-JSON and clear its prior verification."""
    note = load(repo, f"reference/{REF_KEY}.md")
    for field in drop:
        note.meta["csl_json"].pop(field, None)
    note.meta["csl_json"].update(fields)
    note.meta["raw_capture"] = ""
    note.meta["verification"] = {"method": "", "source": "", "verified": False, "date": ""}
    note.save()
    return load(repo, f"reference/{REF_KEY}.md")


# --- raw-capture path ---------------------------------------------------------

def test_offline_verifies_from_a_raw_capture(clean_repo):
    result = run_script("verify_refs.py", clean_repo, "--offline")
    assert result.returncode == 0
    note = load(clean_repo, f"reference/{REF_KEY}.md")
    assert note.meta["verification"]["verified"] is True
    assert note.meta["verification"]["method"] == "raw-capture"


def test_offline_without_a_capture_records_unverified(clean_repo):
    set_csl(clean_repo)
    result = run_script("verify_refs.py", clean_repo, "--offline")
    assert result.returncode == 0, "verify_refs records state; the lint is the gate"
    note = load(clean_repo, f"reference/{REF_KEY}.md")
    assert note.meta["verification"]["verified"] is False
    # ...and the gate then fails on it (FR-11)
    assert run_script("lint_citations.py", clean_repo).returncode != 0




def test_empty_capture_is_unverified(clean_repo):
    note = load(clean_repo, f"reference/{REF_KEY}.md")
    (clean_repo / note.meta["raw_capture"]).write_text("", encoding="utf-8")
    run_script("verify_refs.py", clean_repo, "--offline")
    assert load(clean_repo, f"reference/{REF_KEY}.md").meta["verification"]["verified"] is False


# --- metadata lookups ---------------------------------------------------------

def test_crossref_doi_lookup_verifies(clean_repo):
    note = set_csl(clean_repo, DOI="10.1145/3477132.3483540")
    v = verify_refs.verify_note(
        note, repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=cassette(**{"api.crossref.org": CROSSREF_OK}))
    assert (v.verified, v.method) == (True, "crossref")
    assert v.source == "https://doi.org/10.1145/3477132.3483540"


def test_crossref_request_carries_mailto_for_the_polite_pool(clean_repo):
    note = set_csl(clean_repo, DOI="10.1145/3477132.3483540")
    transport = cassette(**{"api.crossref.org": CROSSREF_OK})
    verify_refs.verify_note(note, repo_of(clean_repo), offline=False,
                            mailto="me@example.org", transport=transport)
    assert any("mailto=me%40example.org" in url for url in transport.calls), transport.calls


def test_crossref_backs_off_on_429_then_succeeds(clean_repo):
    """429s are retried with backoff, honouring Retry-After (FR-10)."""
    responses = [CROSSREF_RATE_LIMITED, CROSSREF_OK]
    slept: list[float] = []

    def transport(url, headers):
        return responses.pop(0)

    data = http.get_json("https://api.crossref.org/works/x?mailto=a%40b.org",
                         transport=transport, sleep=slept.append)
    assert data["message"]["DOI"] == "10.1145/3477132.3483540"
    assert slept == [0.0], "expected one Retry-After-driven pause"


def test_reference_that_misses_every_lookup_is_not_verified(clean_repo):
    note = set_csl(clean_repo, DOI="10.9999/does-not-exist")
    v = verify_refs.verify_note(
        note, repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=cassette(**{"api.crossref.org": CROSSREF_MISS,
                              "openlibrary.org": OPENLIBRARY_MISS,
                              "googleapis.com": GOOGLEBOOKS_MISS}))
    assert (v.verified, v.method) == (False, "")


def test_isbn_verifies_via_open_library(clean_repo):
    note = set_csl(clean_repo)
    v = verify_refs.verify_note(
        note, repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=cassette(**{"openlibrary.org": OPENLIBRARY_OK}))
    assert (v.verified, v.method) == (True, "openlibrary")


def test_isbn_falls_back_to_google_books(clean_repo):
    note = set_csl(clean_repo)
    v = verify_refs.verify_note(
        note, repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=cassette(**{"openlibrary.org": OPENLIBRARY_MISS,
                              "googleapis.com": GOOGLEBOOKS_OK}))
    assert (v.verified, v.method) == (True, "googlebooks")


def test_arxiv_id_verifies(clean_repo):
    note = set_csl(clean_repo, drop=["ISBN"], URL="https://arxiv.org/abs/2608.27454")
    v = verify_refs.verify_note(
        note, repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=cassette(**{"arxiv.org": ARXIV_OK}))
    assert (v.verified, v.method) == (True, "arxiv")


def test_pubmed_pmid_verifies(clean_repo):
    note = set_csl(clean_repo, drop=["ISBN"], PMID="12345678")
    v = verify_refs.verify_note(
        note, repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=cassette(**{"eutils.ncbi.nlm.nih.gov": PUBMED_OK}))
    assert (v.verified, v.method) == (True, "pubmed")


# --- capture + identifier together (issue #7, finding 4) ----------------------

def with_doi_and_capture(repo, doi="10.1145/3477132.3483540"):
    """The fixture note keeps its raw capture AND gains a DOI."""
    note = load(repo, f"reference/{REF_KEY}.md")
    note.meta["csl_json"]["DOI"] = doi
    note.save()
    return load(repo, f"reference/{REF_KEY}.md")


def test_capture_plus_confirmed_doi_upgrades_the_method(clean_repo):
    note = with_doi_and_capture(clean_repo)
    v = verify_refs.verify_note(
        note, repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=cassette(**{"api.crossref.org": CROSSREF_OK}))
    assert (v.verified, v.method, v.identifier_check) == (True, "raw-capture+crossref", "confirmed")
    assert v.source == "https://doi.org/10.1145/3477132.3483540"


def test_capture_with_rotted_doi_stays_verified_but_flags_it(clean_repo):
    """The capture is the documented either/or basis, so verification holds --
    but a DOI no registry knows must be visible, not silent."""
    note = with_doi_and_capture(clean_repo, doi="10.9999/rotted")
    v = verify_refs.verify_note(
        note, repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=cassette(**{"api.crossref.org": CROSSREF_MISS,
                              "openlibrary.org": OPENLIBRARY_MISS,
                              "googleapis.com": GOOGLEBOOKS_MISS}))
    assert (v.verified, v.method, v.identifier_check) == (True, "raw-capture", "failed")

    verify_refs.run(repo_of(clean_repo), offline=False, mailto="me@example.org",
                    transport=cassette(**{"api.crossref.org": CROSSREF_MISS,
                                          "openlibrary.org": OPENLIBRARY_MISS,
                                          "googleapis.com": GOOGLEBOOKS_MISS}),
                    render=False)
    saved = load(clean_repo, f"reference/{REF_KEY}.md")
    assert saved.meta["verification"]["verified"] is True
    assert saved.meta["verification"]["identifier_check"] == "failed"


def test_offline_capture_never_attempts_a_lookup(clean_repo):
    note = with_doi_and_capture(clean_repo)
    transport = cassette()  # any call would raise NetworkUnavailable
    v = verify_refs.verify_note(
        note, repo_of(clean_repo), offline=True, mailto="", transport=transport)
    assert (v.verified, v.method, v.identifier_check) == (True, "raw-capture", "")


# --- open access (A11) ---------------------------------------------------------

OA_PDF = "https://repo.example.edu/files/paper.pdf"
UNPAYWALL_OK = http.Response(200, json.dumps({
    "doi": "10.1145/3477132.3483540", "is_oa": True,
    "best_oa_location": {"url_for_pdf": OA_PDF, "url": "https://repo.example.edu/paper"}}), {})
UNPAYWALL_CLOSED = http.Response(200, json.dumps({
    "doi": "10.1145/3477132.3483540", "is_oa": False, "best_oa_location": None}), {})
OPENALEX_OK = http.Response(200, json.dumps({
    "id": "https://openalex.org/W1", "open_access": {"is_oa": True, "oa_url": OA_PDF},
    "best_oa_location": {"pdf_url": OA_PDF, "landing_page_url": "https://arxiv.org/abs/x"}}), {})
OPENALEX_MISS = http.Response(404, "", {})


def test_unpaywall_records_the_open_access_copy_for_a_doi(clean_repo):
    note = set_csl(clean_repo, DOI="10.1145/3477132.3483540")
    transport = cassette(**{"api.crossref.org": CROSSREF_OK, "api.unpaywall.org": UNPAYWALL_OK})
    v = verify_refs.verify_note(note, repo_of(clean_repo), offline=False,
                                mailto="me@example.org", transport=transport)
    assert (v.verified, v.method, v.open_access) == (True, "crossref", OA_PDF)
    assert any("api.unpaywall.org" in u and "email=me%40example.org" in u for u in transport.calls)


def test_openalex_is_the_fallback_when_unpaywall_has_no_copy(clean_repo):
    note = set_csl(clean_repo, DOI="10.1145/3477132.3483540")
    transport = cassette(**{"api.crossref.org": CROSSREF_OK,
                            "api.unpaywall.org": UNPAYWALL_CLOSED,
                            "api.openalex.org": OPENALEX_OK})
    v = verify_refs.verify_note(note, repo_of(clean_repo), offline=False,
                                mailto="me@example.org", transport=transport)
    assert v.open_access == OA_PDF
    assert any("api.openalex.org" in u for u in transport.calls)


def test_unpaywall_is_skipped_without_a_contact_email(clean_repo):
    """Unpaywall requires an email; OpenAlex does not."""
    note = set_csl(clean_repo, DOI="10.1145/3477132.3483540")
    transport = cassette(**{"api.crossref.org": CROSSREF_OK, "api.openalex.org": OPENALEX_MISS})
    v = verify_refs.verify_note(note, repo_of(clean_repo), offline=False,
                                mailto="", transport=transport)
    assert v.verified and v.open_access == ""
    assert not any("unpaywall" in u for u in transport.calls)


def test_an_unreachable_oa_registry_does_not_block_verification(clean_repo):
    note = set_csl(clean_repo, DOI="10.1145/3477132.3483540")
    v = verify_refs.verify_note(note, repo_of(clean_repo), offline=False,
                                mailto="me@example.org",
                                transport=cassette(**{"api.crossref.org": CROSSREF_OK}))
    assert (v.verified, v.open_access) == (True, "")


def test_open_access_url_is_persisted_and_survives_an_offline_recheck(clean_repo):
    set_csl(clean_repo, DOI="10.1145/3477132.3483540")
    verify_refs.run(repo_of(clean_repo), offline=False, mailto="me@example.org",
                    transport=cassette(**{"api.crossref.org": CROSSREF_OK,
                                          "api.unpaywall.org": UNPAYWALL_OK}), render=False)
    saved = load(clean_repo, f"reference/{REF_KEY}.md")
    assert saved.meta["verification"]["open_access"] == OA_PDF
    # Offline, a lookup-only reference is unverified again (CI relies on
    # captures), but the place to get the capture from must not be lost.
    verify_refs.run(repo_of(clean_repo), offline=True, mailto="", render=False)
    saved = load(clean_repo, f"reference/{REF_KEY}.md")
    assert saved.meta["verification"]["verified"] is False
    assert saved.meta["verification"]["open_access"] == OA_PDF


def test_mailto_falls_back_to_config_fetch_mailto(clean_repo):
    import yaml
    cfg = yaml.safe_load((clean_repo / "config.yml").read_text())
    cfg["fetch"]["mailto"] = "cfg@example.org"
    (clean_repo / "config.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    result = run_script("verify_refs.py", clean_repo, "--offline")
    assert result.returncode == 0
    result = run_script("verify_refs.py", clean_repo)
    assert "no --mailto given" not in result.stderr


# --- write-only-on-change (issue #7, finding 3) --------------------------------

def test_second_run_over_an_unchanged_repo_writes_nothing(clean_repo):
    """Unconditional saves made every cycle a diff on every reference note."""
    run_script("verify_refs.py", clean_repo, "--offline")
    ref = clean_repo / "reference" / f"{REF_KEY}.md"
    first = ref.read_bytes()
    first_date = load(clean_repo, f"reference/{REF_KEY}.md").meta["verification"]["date"]

    run_script("verify_refs.py", clean_repo, "--offline")
    assert ref.read_bytes() == first, "an unchanged state must not be rewritten"
    assert load(clean_repo, f"reference/{REF_KEY}.md") \
        .meta["verification"]["date"] == first_date


def test_a_state_change_still_writes_and_stamps_a_fresh_date(clean_repo):
    run_script("verify_refs.py", clean_repo, "--offline")
    note = load(clean_repo, f"reference/{REF_KEY}.md")
    note.meta["verification"] = {"method": "", "source": "",
                                 "verified": False, "date": ""}
    note.save()
    run_script("verify_refs.py", clean_repo, "--offline")
    saved = load(clean_repo, f"reference/{REF_KEY}.md")
    assert saved.meta["verification"]["verified"] is True
    assert saved.meta["verification"]["date"] != ""


# --- graceful degradation (NFR-5) ---------------------------------------------

def test_network_failure_degrades_to_raw_capture_only(clean_repo):
    """A dead network must not lose an already-captured verification."""
    def dead(url, headers):
        raise http.NetworkUnavailable("connection refused")

    verified, total = verify_refs.run(
        repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=dead, render=False)
    assert (verified, total) == (1, 1)
    note = load(clean_repo, f"reference/{REF_KEY}.md")
    assert note.meta["verification"]["method"] == "raw-capture"


def test_dead_network_on_an_arxiv_reference_degrades_rather_than_flagging_rot(clean_repo):
    """The arXiv fetch used to swallow NetworkUnavailable, so a capture plus an
    arXiv id on a dead network came back as identifier_check: failed."""
    def dead(url, headers):
        raise http.NetworkUnavailable("connection refused")

    set_csl(clean_repo, drop=["ISBN"], URL="https://arxiv.org/abs/2608.27454")
    note = load(clean_repo, f"reference/{REF_KEY}.md")
    note.meta["raw_capture"] = "raw/202608301000-ahrens-smart-notes.txt"
    note.save()
    verified, total = verify_refs.run(
        repo_of(clean_repo), offline=False, mailto="me@example.org",
        transport=dead, render=False)
    assert (verified, total) == (1, 1)
    note = load(clean_repo, f"reference/{REF_KEY}.md")
    assert note.meta["verification"]["method"] == "raw-capture"
    assert "identifier_check" not in note.meta["verification"]


def test_one_malformed_reference_does_not_stop_the_others(clean_repo):
    (clean_repo / "reference" / "aaa-broken--202608300900.md").write_text(
        "no frontmatter\n", encoding="utf-8")
    result = run_script("verify_refs.py", clean_repo, "--offline")
    assert result.returncode == 0
    assert "SKIPPED" in result.stdout
    assert f"reference/{REF_KEY}.md\tverified via raw-capture" in result.stdout


# --- rendering ----------------------------------------------------------------

def test_verify_refresh_rewrites_chicago_strings_from_csl(clean_repo):
    note = load(clean_repo, f"reference/{REF_KEY}.md")
    note.meta["chicago_note"] = "stale nonsense"
    note.save()
    run_script("verify_refs.py", clean_repo, "--offline")
    assert "Ahrens" in load(clean_repo, f"reference/{REF_KEY}.md").meta["chicago_note"]
    assert run_script("lint_citations.py", clean_repo).returncode == 0
