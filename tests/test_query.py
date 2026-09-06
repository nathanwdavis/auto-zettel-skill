"""query.py: a read-only map of what the base already knows about a query."""

from __future__ import annotations

import hashlib
import json

from conftest import LIT_KEY, MOC_KEY, PERM_KEY, REF_KEY, SCRIPTS, run_script


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


def test_suggested_commands_are_shell_safe(clean_repo):
    """A query with quotes must not produce a command that misparses when pasted."""
    import shlex
    q = "the \"odd\" query's terms"
    data = json.loads(report(clean_repo, q, "--json").stdout)
    assert data["suggestions"], data["gaps"]
    argv = shlex.split(data["suggestions"][0]["command"])
    assert q in argv
    assert str(clean_repo) in argv


def test_file_gaps_captures_the_suggestions_and_logs(clean_repo):
    """The one write path, and only on request: suggestions become real
    captures through capture.py, the manifest is rebuilt, and log.md records it."""
    before = set(p.name for p in (clean_repo / "inquiries").glob("*.md"))
    out = report(clean_repo, "quantum chromodynamics", "--file-gaps").stdout
    assert "Filed for the next run" in out
    new = set(p.name for p in (clean_repo / "inquiries").glob("*.md")) - before
    assert len(new) == 1
    manifest = json.loads((clean_repo / "manifest.json").read_text(encoding="utf-8"))
    assert any(i["question"] == "quantum chromodynamics" for i in manifest["inquiries"])
    log = (clean_repo / "log.md").read_text(encoding="utf-8")
    assert "query --file-gaps: inquiry -> inquiries/" in log
    assert run_script("lint_links.py", clean_repo).returncode == 0


def test_file_gaps_turns_mapping_gaps_into_inbox_entries(two_cluster_repo):
    data = json.loads(report(two_cluster_repo, "reinvested returns", "--json",
                             "--top", "1", "--file-gaps").stdout)
    kinds = [f["kind"] for f in data["filed"]]
    assert kinds == ["inbox"]
    inbox = (two_cluster_repo / "INBOX.md").read_text(encoding="utf-8")
    assert "Add to a map of content: reinvested-returns-compound--202701010011" in inbox


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


# -- the graph (Phase 3) ------------------------------------------------------

def test_edges_distinguish_typed_relations_from_mentions(clean_repo):
    """The permanent note both cites the reference and mentions it in prose.

    Those are two different facts -- an author choosing `source` from the FR-5
    set, and a wikilink in a sentence -- so the subgraph carries both.
    """
    data = json.loads(report(clean_repo, "atomic notes", "--json").stdout)
    pairs = {(e["source"], e["target"], e["relation"]) for e in data["edges"]}
    assert (PERM_KEY, REF_KEY, "source") in pairs
    assert (PERM_KEY, REF_KEY, "mentions") in pairs
    assert (PERM_KEY, LIT_KEY, "elaborates") in pairs


def test_every_edge_endpoint_is_a_reported_node(clean_repo):
    """An edge to a note the report never listed would dangle."""
    data = json.loads(report(clean_repo, "atomic notes", "--json").stdout)
    listed = {m["key"] for m in data["matched"]} | {c["key"] for c in data["connected"]}
    for edge in data["edges"]:
        assert edge["source"] in listed and edge["target"] in listed, edge


def test_edges_are_sorted_and_stable(clean_repo):
    data = json.loads(report(clean_repo, "atomic notes", "--json").stdout)
    triples = [(e["source"], e["target"], e["relation"]) for e in data["edges"]]
    assert triples == sorted(triples)


def test_moc_membership_names_the_map_that_reaches_a_note(clean_repo):
    data = json.loads(report(clean_repo, "atomic notes", "--json").stdout)
    assert data["moc_membership"][PERM_KEY] == [MOC_KEY]
    assert data["moc_membership"][LIT_KEY] == []


def test_moc_membership_and_the_mapping_gap_agree(two_cluster_repo):
    """One source, so the JSON and the gap cannot disagree about reachability."""
    data = json.loads(report(two_cluster_repo, "reinvested returns", "--json",
                             "--top", "1").stdout)
    key = data["matched"][0]["key"]
    assert data["moc_membership"][key] == []
    assert any(key in g for g in data["gaps"] if "map of content" in g)


def test_mentions_is_not_an_fr5_relation():
    """If `mentions` ever reached a note's links block, lint_links would fail it
    as bad-relation -- so it must stay outside the closed set."""
    import sys
    sys.path.insert(0, str(SCRIPTS))
    from zettel_lib.graph import MENTIONS
    from zettel_lib.repo import RELATIONS
    assert MENTIONS not in RELATIONS


def test_mermaid_is_a_section_not_a_mode(clean_repo):
    """The diagram joins the report; it does not replace it."""
    out = report(clean_repo, "atomic notes", "--mermaid").stdout
    assert "# What the base knows about" in out
    assert "## The subgraph" in out and "```mermaid" in out and "graph LR" in out
    assert "## Gaps" in out


def test_mermaid_is_absent_from_the_report_unless_asked(clean_repo):
    out = report(clean_repo, "atomic notes").stdout
    assert "```mermaid" not in out


def test_json_always_carries_the_mermaid_source(clean_repo):
    """The JSON shape does not change with the flags, like every other field."""
    plain = json.loads(report(clean_repo, "atomic notes", "--json").stdout)
    flagged = json.loads(report(clean_repo, "atomic notes", "--json", "--mermaid").stdout)
    assert plain["mermaid"].startswith("graph LR")
    assert plain["mermaid"] == flagged["mermaid"]


def test_mermaid_is_byte_identical_across_runs(clean_repo):
    a = report(clean_repo, "atomic notes", "--mermaid").stdout
    b = report(clean_repo, "atomic notes", "--mermaid").stdout
    assert a == b


def test_mermaid_nodes_appear_in_sorted_key_order(clean_repo):
    data = json.loads(report(clean_repo, "atomic notes", "--json").stdout)
    ids = {}
    for line in data["mermaid"].splitlines():
        line = line.strip()
        if not line.startswith("n") or "<br/>" not in line:
            continue
        node_id = line.split("[")[0].split("(")[0].split("{")[0].split(">")[0]
        ids[node_id] = line.split("<br/>")[1].rstrip('")}]>')
    assert list(ids) == sorted(ids, key=lambda n: int(n[1:]))
    assert list(ids.values()) == sorted(ids.values())


def test_mermaid_draws_mentions_differently_from_typed_relations(clean_repo):
    """A curated relation and a passing mention must not look alike."""
    data = json.loads(report(clean_repo, "atomic notes", "--json").stdout)
    assert '-.->|"mentions"|' in data["mermaid"]
    assert '-->|"source"|' in data["mermaid"]


def test_mermaid_label_escapes_what_would_end_the_label_early():
    import sys
    sys.path.insert(0, str(SCRIPTS))
    from zettel_lib.graph import mermaid_label
    assert mermaid_label('A "quoted" [title]') == "A #quot;quoted#quot; #91;title#93;"
    assert mermaid_label("keeps\n  one space") == "keeps one space"


def test_mermaid_on_a_query_that_matches_nothing_is_still_valid(clean_repo):
    data = json.loads(report(clean_repo, "quantum chromodynamics", "--json").stdout)
    assert data["mermaid"] == "graph LR\n  %% no notes matched"


# -- gap ids, ranks, and selection (Phase 3) ----------------------------------

def test_gaps_stay_a_list_of_strings(two_cluster_repo):
    """A PLAN.md invariant: the structure went to gap_details, not into gaps."""
    data = json.loads(report(two_cluster_repo, "reinvested returns", "--json",
                             "--top", "1").stdout)
    assert data["gaps"] and all(isinstance(g, str) for g in data["gaps"])


def test_gaps_carry_ids_in_priority_order(clean_repo):
    """A research gap outranks a mapping gap, and g1 is the one to work first."""
    data = json.loads(report(clean_repo, "quantum chromodynamics", "--json").stdout)
    assert data["gaps"][0].startswith("g1: ")
    ranks = [d["rank"] for d in data["gap_details"]]
    assert ranks == sorted(ranks)
    assert [d["id"] for d in data["gap_details"]] == [f"g{i}" for i in
                                                     range(1, len(ranks) + 1)]


def test_gap_ids_are_stable_across_runs(clean_repo):
    a = json.loads(report(clean_repo, "quantum chromodynamics", "--json").stdout)
    b = json.loads(report(clean_repo, "quantum chromodynamics", "--json").stdout)
    assert a["gaps"] == b["gaps"]
    assert a["gap_details"] == b["gap_details"]


def test_two_gaps_sharing_one_suggestion_file_it_once(clean_repo):
    """"No note uses these terms" and "nothing matched" are one absence."""
    data = json.loads(report(clean_repo, "quantum chromodynamics", "--json").stdout)
    assert len(data["gap_details"]) == 2
    assert {d["suggestion"] for d in data["gap_details"]} == {0}
    assert data["suggestions"][0]["gaps"] == ["g1", "g2"]
    filed = json.loads(report(clean_repo, "quantum chromodynamics", "--json",
                              "--file-gaps").stdout)["filed"]
    assert len(filed) == 1
    assert filed[0]["gaps"] == ["g1", "g2"]


def test_gaps_cap_keeps_the_highest_ranked(two_cluster_repo):
    full = json.loads(report(two_cluster_repo, "atomic notes compound", "--json").stdout)
    capped = json.loads(report(two_cluster_repo, "atomic notes compound", "--json",
                               "--gaps", "1").stdout)
    assert len(full["gap_details"]) >= 1
    assert len(capped["gap_details"]) == 1
    assert capped["gap_details"][0]["kind"] == full["gap_details"][0]["kind"]


def test_a_capped_gap_cannot_be_filed(clean_repo):
    """The cap bounds what --file-gaps can write, so the receipt cannot lie."""
    out = report(clean_repo, "quantum chromodynamics", "--json", "--gaps", "1",
                 "--file-gaps").stdout
    data = json.loads(out)
    assert len(data["gap_details"]) == 1
    assert data["filed"][0]["gaps"] == ["g1"]


def test_file_gaps_selection_files_only_the_named_gap(two_cluster_repo):
    before = set(p.name for p in (two_cluster_repo / "inquiries").glob("*.md"))
    data = json.loads(report(two_cluster_repo, "reinvested returns", "--json",
                             "--top", "1", "--file-gaps", "g1").stdout)
    assert [f["gaps"] for f in data["filed"]] == [["g1"]]
    assert set(p.name for p in (two_cluster_repo / "inquiries").glob("*.md")) == before


def test_file_gaps_bare_still_files_everything(clean_repo):
    data = json.loads(report(clean_repo, "quantum chromodynamics", "--json",
                             "--file-gaps").stdout)
    assert len(data["filed"]) == len(data["suggestions"])


def test_file_gaps_before_top_still_means_all(clean_repo):
    """The exact argv session_cycle.sh builds: --file-gaps, then --top.

    argparse must not read `--top` as the selection value. This is silent
    corruption rather than a crash, so it gets its own test.
    """
    result = run_script("query.py", clean_repo, "quantum chromodynamics",
                        "--json", "--file-gaps", "--top", "5")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert len(data["filed"]) == len(data["suggestions"]) == 1


def test_unknown_gap_id_is_a_usage_error_and_writes_nothing(clean_repo):
    before = tree_hash(clean_repo)
    result = run_script("query.py", clean_repo, "quantum chromodynamics",
                        "--file-gaps", "g99")
    assert result.returncode == 2
    assert "unknown gap id" in result.stderr
    assert tree_hash(clean_repo) == before, "a rejected selection still wrote"


def test_a_query_shaped_gap_selection_is_refused_and_writes_nothing(clean_repo):
    """`--file-gaps <query>` swallows the query as the selection value.

    It must never be mistaken for a real selection. (While `query` is a
    required positional argparse catches it first; once --from-file makes the
    positional optional, query.py's own validator reports it -- asserted in
    test_a_query_shaped_gap_selection_names_the_fix.)
    """
    before = tree_hash(clean_repo)
    result = run_script("query.py", clean_repo, "--file-gaps", "atomic notes")
    assert result.returncode == 2
    assert tree_hash(clean_repo) == before


def test_negative_gap_cap_is_a_usage_error(clean_repo):
    assert run_script("query.py", clean_repo, "atomic notes",
                      "--gaps", "-1").returncode == 2


def test_empty_query_is_a_usage_error(clean_repo):
    assert run_script("query.py", clean_repo, "   ").returncode == 2


def test_help_exits_zero(clean_repo):
    assert run_script("query.py", clean_repo, "--help").returncode == 0
