"""serendipity_sweep.py: cross-community link proposals (FR-24, checklist item 7).

Uses the two-cluster fixture: notes about atomicity and notes about compound
interest, densely linked within each cluster and never across, sharing the
recombination idea. Louvain must find both clusters, and the sweep must surface
exactly the cross-cluster kinship without touching a single note.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

import serendipity_sweep
from conftest import run_script
from zettel_lib.frontmatter import Note
from zettel_lib.repo import ContentRepo
from zettel_lib.similarity import EmbeddingScorer, LexicalScorer

ATOMIC_KEY = "atomic-notes-compound-over-time--202701010001"
COMPOUND_KEY = "reinvested-returns-compound--202701010011"


def sweep(repo: Path, *args):
    return run_script("serendipity_sweep.py", repo, *args)


def proposals(repo: Path) -> list[Note]:
    return [Note.load(p) for p in sorted((repo / "proposed-links").glob("*.md"))]


def pairs(repo: Path) -> set[tuple[str, str]]:
    return {tuple(sorted((str(n.meta["source"]), str(n.meta["target"]))))
            for n in proposals(repo)}


def fingerprint(repo: Path) -> dict[str, str]:
    """Hash every note so we can prove the sweep changed none of them.

    Excludes proposed-links/ (the sweep's own output) and log.md (append-only by
    design, NFR-2) -- everything else must come through untouched.
    """
    out = {}
    for path in sorted(repo.rglob("*.md")):
        if "proposed-links" in path.parts or path.name == "log.md":
            continue
        out[str(path.relative_to(repo))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


# --- graph and communities ----------------------------------------------------

def test_louvain_finds_the_two_planted_clusters(two_cluster_repo):
    repo = ContentRepo(two_cluster_repo)
    notes = serendipity_sweep.load_notes(repo)
    id_to_key = {n.id: n.key for n in notes if n.id}
    graph = serendipity_sweep.build_graph(notes, id_to_key)
    communities, method = serendipity_sweep.detect_communities(graph)

    assert method == "louvain"
    assert communities[ATOMIC_KEY] != communities[COMPOUND_KEY], \
        "the two planted clusters must land in different communities"


def test_only_swept_note_types_enter_the_graph(two_cluster_repo):
    repo = ContentRepo(two_cluster_repo)
    types = {n.type for n in serendipity_sweep.load_notes(repo)}
    assert types <= set(serendipity_sweep.SWEPT_TYPES)
    assert "reference" not in types, "bibliographic records are not ideas"


def test_communities_are_deterministic(two_cluster_repo):
    repo = ContentRepo(two_cluster_repo)
    notes = serendipity_sweep.load_notes(repo)
    id_to_key = {n.id: n.key for n in notes if n.id}
    graph = serendipity_sweep.build_graph(notes, id_to_key)
    assert (serendipity_sweep.detect_communities(graph)
            == serendipity_sweep.detect_communities(graph))


def test_graph_is_a_plain_adjacency_map(two_cluster_repo):
    """networkx must stay optional: the graph itself is stdlib."""
    repo = ContentRepo(two_cluster_repo)
    notes = serendipity_sweep.load_notes(repo)
    graph = serendipity_sweep.build_graph(notes, {n.id: n.key for n in notes if n.id})
    assert isinstance(graph, dict)
    assert all(isinstance(v, set) for v in graph.values())
    # edges are symmetric
    for node, neighbours in graph.items():
        for neighbour in neighbours:
            assert node in graph[neighbour]


def test_falls_back_to_connected_components_without_networkx(two_cluster_repo, monkeypatch):
    """A missing optional import must never crash a sweep (it promises exit 0)."""
    import builtins
    real_import = builtins.__import__

    def no_networkx(name, *args, **kwargs):
        if name.startswith("networkx"):
            raise ImportError("No module named 'networkx'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_networkx)
    repo = ContentRepo(two_cluster_repo)
    notes = serendipity_sweep.load_notes(repo)
    graph = serendipity_sweep.build_graph(notes, {n.id: n.key for n in notes if n.id})
    communities, method = serendipity_sweep.detect_communities(graph)

    assert method == "connected-components"
    assert communities[ATOMIC_KEY] != communities[COMPOUND_KEY], \
        "disconnected clusters must still separate without networkx"


def test_connected_components_partition_is_a_valid_cover(two_cluster_repo):
    repo = ContentRepo(two_cluster_repo)
    notes = serendipity_sweep.load_notes(repo)
    graph = serendipity_sweep.build_graph(notes, {n.id: n.key for n in notes if n.id})
    components = serendipity_sweep._connected_components(graph)
    flat = [k for c in components for k in c]
    assert sorted(flat) == sorted(graph), "every node in exactly one component"
    assert len(flat) == len(set(flat))


# --- selection policy ---------------------------------------------------------

def test_sweep_surfaces_the_cross_cluster_kinship(two_cluster_repo):
    result = sweep(two_cluster_repo)
    assert result.returncode == 0, result.stderr
    assert (ATOMIC_KEY, COMPOUND_KEY) in {tuple(sorted(p)) for p in pairs(two_cluster_repo)}


def test_proposals_are_never_within_one_community(two_cluster_repo):
    sweep(two_cluster_repo)
    for proposal in proposals(two_cluster_repo):
        first, second = proposal.meta["communities"]
        assert first != second, f"{proposal.path.name} links inside one community"


def test_already_linked_pairs_are_not_proposed(two_cluster_repo):
    """Cluster-internal notes are all mutually linked; none may be proposed."""
    sweep(two_cluster_repo)
    repo = ContentRepo(two_cluster_repo)
    notes = serendipity_sweep.load_notes(repo)
    id_to_key = {n.id: n.key for n in notes if n.id}
    linked = serendipity_sweep.existing_edges(
        serendipity_sweep.build_graph(notes, id_to_key))
    assert not (pairs(two_cluster_repo) & linked)


def test_high_threshold_suppresses_everything(two_cluster_repo):
    result = sweep(two_cluster_repo, "--threshold", "0.99")
    assert result.returncode == 0
    assert proposals(two_cluster_repo) == []


def test_max_proposals_is_respected(two_cluster_repo):
    sweep(two_cluster_repo, "--threshold", "0.0", "--max-proposals", "2")
    assert len(proposals(two_cluster_repo)) == 2


def test_highest_scoring_pair_wins_the_cap(two_cluster_repo):
    sweep(two_cluster_repo, "--max-proposals", "1")
    proposal = proposals(two_cluster_repo)[0]
    assert tuple(sorted((proposal.meta["source"], proposal.meta["target"]))) \
        == (ATOMIC_KEY, COMPOUND_KEY)


# --- proposal files -----------------------------------------------------------

def test_proposal_frontmatter_is_complete(two_cluster_repo):
    sweep(two_cluster_repo)
    for proposal in proposals(two_cluster_repo):
        for field in ("source", "target", "suggested_relation", "score",
                      "scorer", "communities", "evidence", "status"):
            assert field in proposal.meta, f"{proposal.path.name} missing {field}"
        assert proposal.meta["status"] == "pending-review"
        assert proposal.meta["suggested_relation"] == serendipity_sweep.NEUTRAL_RELATION


def test_proposals_land_in_the_connector_queue(two_cluster_repo):
    sweep(two_cluster_repo)
    assert list((two_cluster_repo / "proposed-links").glob("*.md"))


def test_proposal_body_flags_itself_as_unjustified(two_cluster_repo):
    """The script must not pretend a score is a justification."""
    sweep(two_cluster_repo)
    body = proposals(two_cluster_repo)[0].body
    assert "not a justification" in body
    assert "connector agent" in body


def test_evidence_terms_appear_in_both_notes(two_cluster_repo):
    from zettel_lib.similarity import tokenize
    sweep(two_cluster_repo)
    for proposal in proposals(two_cluster_repo):
        source = Note.load(next(two_cluster_repo.rglob(f"{proposal.meta['source']}.md")))
        target = Note.load(next(two_cluster_repo.rglob(f"{proposal.meta['target']}.md")))
        source_tokens = set(tokenize(source.title + " " + source.body))
        target_tokens = set(tokenize(target.title + " " + target.body))
        for term in proposal.meta["evidence"]:
            assert term in source_tokens and term in target_tokens


# --- the never-edits guarantee (FR-24) ----------------------------------------

def test_sweep_leaves_every_note_byte_identical(two_cluster_repo):
    before = fingerprint(two_cluster_repo)
    sweep(two_cluster_repo, "--threshold", "0.0")
    assert fingerprint(two_cluster_repo) == before


def test_rerunning_never_duplicates_a_proposal(two_cluster_repo):
    sweep(two_cluster_repo)
    first = pairs(two_cluster_repo)
    count = len(proposals(two_cluster_repo))
    sweep(two_cluster_repo)
    assert pairs(two_cluster_repo) == first
    assert len(proposals(two_cluster_repo)) == count


# --- scorer selection and degradation (NFR-5) ---------------------------------

def test_lexical_is_the_default_when_embeddings_are_disabled(two_cluster_repo):
    scorer, warnings = serendipity_sweep.choose_scorer(
        ContentRepo(two_cluster_repo), force_lexical=False)
    assert isinstance(scorer, LexicalScorer)
    assert warnings == []


def enable_embedding(repo: Path, model: str = "some/model"):
    cfg = yaml.safe_load((repo / "config.yml").read_text(encoding="utf-8"))
    cfg["embedding"] = {"enabled": True, "model": model}
    (repo / "config.yml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")


def test_unavailable_embedding_backend_degrades_with_a_logged_warning(two_cluster_repo):
    """sentence-transformers absent or its model unfetchable must not fail the sweep."""
    enable_embedding(two_cluster_repo)
    scorer, warnings = serendipity_sweep.choose_scorer(
        ContentRepo(two_cluster_repo), force_lexical=False)
    assert isinstance(scorer, LexicalScorer)
    assert warnings and "falling back to lexical" in warnings[0]

    result = sweep(two_cluster_repo)
    assert result.returncode == 0
    assert "falling back to lexical" in result.stderr
    assert "DEGRADED" in (two_cluster_repo / "log.md").read_text(encoding="utf-8")
    assert proposals(two_cluster_repo), "degraded sweep must still produce proposals"


def test_embedding_enabled_without_a_model_degrades(two_cluster_repo):
    enable_embedding(two_cluster_repo, model="")
    scorer, warnings = serendipity_sweep.choose_scorer(
        ContentRepo(two_cluster_repo), force_lexical=False)
    assert isinstance(scorer, LexicalScorer)
    assert "embedding.model is empty" in warnings[0]


def test_force_lexical_overrides_enabled_embeddings(two_cluster_repo):
    enable_embedding(two_cluster_repo)
    scorer, warnings = serendipity_sweep.choose_scorer(
        ContentRepo(two_cluster_repo), force_lexical=True)
    assert isinstance(scorer, LexicalScorer) and warnings == []


def test_injected_embedding_scorer_drives_the_embedding_path(two_cluster_repo, monkeypatch):
    """The real path, proven without a model download (HuggingFace is blocked here)."""
    calls = {}

    def fake_load(model_name):
        calls["model"] = model_name
        return EmbeddingScorer(lambda texts: [[1.0, float(i)] for i, _ in enumerate(texts)],
                               model_name)

    enable_embedding(two_cluster_repo, "fake/mini")
    monkeypatch.setattr(EmbeddingScorer, "load", staticmethod(fake_load))
    scorer, warnings = serendipity_sweep.choose_scorer(
        ContentRepo(two_cluster_repo), force_lexical=False)
    assert isinstance(scorer, EmbeddingScorer)
    assert calls["model"] == "fake/mini" and warnings == []


# --- contract -----------------------------------------------------------------

def test_sweep_survives_a_missing_networkx_end_to_end(two_cluster_repo):
    """Run the real CLI under an interpreter that cannot import networkx."""
    import subprocess, sys, textwrap
    from conftest import SCRIPTS

    # A sitecustomize that makes `import networkx` fail, injected via PYTHONPATH.
    blocker = two_cluster_repo.parent / "blocker"
    blocker.mkdir(exist_ok=True)
    (blocker / "sitecustomize.py").write_text(textwrap.dedent("""
        import sys
        class _Blocker:
            def find_module(self, name, path=None):
                if name.split('.')[0] == 'networkx':
                    return self
            def load_module(self, name):
                raise ImportError("No module named 'networkx'")
        sys.meta_path.insert(0, _Blocker())
    """), encoding="utf-8")

    import os
    env = {**os.environ, "PYTHONPATH": str(blocker)}
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "serendipity_sweep.py"), "--repo", str(two_cluster_repo)],
        capture_output=True, text=True, env=env)

    assert result.returncode == 0, f"sweep must exit 0 without networkx:\n{result.stderr}"
    assert "connected-components" in result.stdout
    assert "networkx unavailable" in result.stderr
    assert "DEGRADED" in (two_cluster_repo / "log.md").read_text(encoding="utf-8")
    assert proposals(two_cluster_repo), "degraded run must still propose"


def test_sweep_logs_its_summary(two_cluster_repo):
    sweep(two_cluster_repo)
    assert "serendipity_sweep:" in (two_cluster_repo / "log.md").read_text(encoding="utf-8")


def test_sweep_on_a_repo_with_too_few_notes_exits_zero(clean_repo):
    for path in (clean_repo / "permanent").glob("*.md"):
        path.unlink()
    for path in (clean_repo / "literature").glob("*.md"):
        path.unlink()
    for path in (clean_repo / "moc").glob("*.md"):
        path.unlink()
    result = sweep(clean_repo)
    assert result.returncode == 0
    assert "too few notes" in (clean_repo / "log.md").read_text(encoding="utf-8")


def test_help_exits_zero(two_cluster_repo):
    from conftest import SCRIPTS
    import subprocess, sys
    result = subprocess.run([sys.executable, str(SCRIPTS / "serendipity_sweep.py"), "--help"],
                            capture_output=True, text=True)
    assert result.returncode == 0 and "--threshold" in result.stdout
