"""query.py: a read-only map of what the base already knows about a query."""

from __future__ import annotations

import hashlib
import json

from conftest import LIT_KEY, MOC_KEY, PERM_KEY, REF_KEY, run_script


def tree_hash(repo) -> str:
    digest = hashlib.sha256()
    for p in sorted(x for x in repo.rglob("*") if x.is_file() and ".git" not in x.parts):
        digest.update(str(p.relative_to(repo)).encode())
        digest.update(p.read_bytes())
    return digest.hexdigest()


def report(repo, *args):
    result = run_script("query.py", repo, *args)
    assert result.returncode == 0, result.stderr
    return result


def test_query_reports_by_type_and_cites_keys(clean_repo):
    out = report(clean_repo, "smart notes").stdout
    assert "Claims the base makes" in out and PERM_KEY in out
    assert "Sources on file" in out and REF_KEY in out
    assert "verified via raw-capture" in out
    assert "Literature notes" in out and LIT_KEY in out


def test_query_writes_nothing(clean_repo):
    """A query is not an operation: no log.md line, no file touched (A9)."""
    before = tree_hash(clean_repo)
    report(clean_repo, "smart notes")
    report(clean_repo, "smart notes", "--json")
    assert tree_hash(clean_repo) == before


def test_json_report_shape(clean_repo):
    data = json.loads(report(clean_repo, "atomic notes", "--json").stdout)
    assert data["query"] == "atomic notes"
    assert data["note_count"] == 4
    keys = {m["key"] for m in data["matched"]}
    assert PERM_KEY in keys
    perm = next(m for m in data["matched"] if m["key"] == PERM_KEY)
    assert perm["sources"] == [REF_KEY]
    assert perm["score"] > 0 and perm["evidence"]
    assert set(data["by_type"]) == {"permanent", "literature", "reference", "moc", "fleeting"}


def test_connected_notes_are_one_link_from_a_match(two_cluster_repo):
    data = json.loads(report(two_cluster_repo, "reinvested returns", "--json", "--top", "1").stdout)
    assert [m["key"] for m in data["matched"]] == ["reinvested-returns-compound--202701010011"]
    connected = {c["key"] for c in data["connected"]}
    # its cluster-mates are linked to it; the other cluster is not
    assert "linear-growth-lacks-a-feedback-loop--202701010012" in connected
    assert "time-horizon-dominates-rate--202701010013" in connected
    assert not any(k.startswith("atomic-notes") for k in connected)


def test_unknown_terms_are_reported_as_a_gap(clean_repo):
    data = json.loads(report(clean_repo, "quantum chromodynamics", "--json").stdout)
    assert data["matched"] == []
    assert data["missing_terms"] == ["chromodynamic", "quantum"]
    assert any("nothing on them" in g for g in data["gaps"])
    out = report(clean_repo, "quantum chromodynamics").stdout
    assert "capture.py" in out and "inquiry" in out, "the next step is suggested, not taken"


def test_open_inquiries_touching_the_query_are_listed(clean_repo):
    run_script("capture.py", clean_repo, "inquiry", "Do atomic notes really compound?",
               "--priority", "high")
    data = json.loads(report(clean_repo, "atomic notes", "--json").stdout)
    assert len(data["inquiries"]) == 1
    assert data["inquiries"][0]["status"] == "new"
    assert data["inquiries"][0]["priority"] == "high"


def test_moc_gap_names_matched_notes_no_map_reaches(two_cluster_repo):
    # cluster B has no MOC pointing at it; cluster A's anchor is in the MOC
    data = json.loads(report(two_cluster_repo, "reinvested returns", "--json", "--top", "1").stdout)
    gap = next(g for g in data["gaps"] if "map of content" in g)
    assert "reinvested-returns-compound--202701010011" in gap
    data = json.loads(report(two_cluster_repo, "atomic notes compound over time",
                             "--json", "--top", "1").stdout)
    assert data["matched"][0]["key"] == "atomic-notes-compound-over-time--202701010001"
    assert not any("map of content" in g for g in data["gaps"]), data["gaps"]


def test_configured_topics_touched_are_reported(clean_repo):
    data = json.loads(report(clean_repo, "zettelkasten method", "--json").stdout)
    assert data["topics"] == ["zettelkasten method"]
    assert MOC_KEY in {m["key"] for m in data["matched"]}


def test_empty_query_is_a_usage_error(clean_repo):
    assert run_script("query.py", clean_repo, "   ").returncode == 2


def test_help_exits_zero(clean_repo):
    assert run_script("query.py", clean_repo, "--help").returncode == 0
