#!/usr/bin/env python3
"""Propose cross-community links between notes (FR-24).

Every link an agent writes is one it meant to write while working on a note.
This sweep does the opposite: it looks for kinship between notes that live in
*different* regions of the link graph, so an idea captured for one topic can
surface next to a distant one nobody thought to connect it to.

Pipeline: load notes -> build the typed-link graph -> detect communities with
Louvain -> score every pair -> keep only cross-community, above-threshold,
not-already-linked pairs -> write proposals into proposed-links/.

The sweep NEVER edits notes and always exits 0. It proposes; the connector
agent justifies; the critic decides. The suggested relation is deliberately the
neutral `shared-concept` -- choosing `supports` or `contradicts` requires
reading meaning, which is the critic's job, not a similarity score's.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib import naming
from zettel_lib.cli import EXIT_OK, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note, dump
from zettel_lib.repo import ContentRepo, ContentRepoError, dig
from zettel_lib.similarity import EmbeddingScorer, LexicalScorer, PairScore

# Ideas and their summaries connect; reference notes are bibliographic records
# and fleeting notes are transient, so neither belongs in a serendipity graph.
SWEPT_TYPES = ("permanent", "literature", "moc")
NEUTRAL_RELATION = "shared-concept"
LOUVAIN_SEED = 7


def choose_scorer(repo: ContentRepo, force_lexical: bool) -> tuple[object, list[str]]:
    """Pick a scorer, returning it with any degradation warnings to log (NFR-5)."""
    warnings: list[str] = []
    if force_lexical:
        return LexicalScorer(), warnings

    cfg = repo.config()
    if not dig(cfg, "embedding.enabled"):
        return LexicalScorer(), warnings

    model = str(dig(cfg, "embedding.model") or "").strip()
    if not model:
        warnings.append("embedding.enabled is true but embedding.model is empty; "
                        "falling back to lexical scoring")
        return LexicalScorer(), warnings
    try:
        return EmbeddingScorer.load(model), warnings
    except Exception as exc:  # noqa: BLE001 - any load failure degrades alike
        warnings.append(f"embedding scorer unavailable ({type(exc).__name__}: {exc}); "
                        f"falling back to lexical scoring")
        return LexicalScorer(), warnings


def load_notes(repo: ContentRepo) -> list[Note]:
    notes = []
    for note in repo.notes(types=SWEPT_TYPES):
        if note.key:
            notes.append(note)
    return notes


def build_graph(notes: list[Note], id_to_key: dict[str, str]):
    """Undirected typed-link graph over note keys."""
    import networkx as nx

    graph = nx.Graph()
    keys = {n.key for n in notes}
    graph.add_nodes_from(sorted(keys))
    for note in notes:
        targets = {str(link.get("target_id", "")) for link in note.links}
        for target in targets:
            resolved = target if target in keys else id_to_key.get(target, "")
            if resolved in keys and resolved != note.key:
                graph.add_edge(note.key, resolved)
    return graph


def detect_communities(graph) -> dict[str, int]:
    from networkx.algorithms.community import louvain_communities

    if graph.number_of_nodes() == 0:
        return {}
    communities = louvain_communities(graph, seed=LOUVAIN_SEED)
    # Sort for determinism: same graph in, same community ids out.
    ordered = sorted((sorted(c) for c in communities), key=lambda c: c[0])
    return {key: idx for idx, members in enumerate(ordered) for key in members}


def existing_edges(graph) -> set[tuple[str, str]]:
    return {tuple(sorted(edge)) for edge in graph.edges()}


def existing_proposals(out_dir: Path) -> set[tuple[str, str]]:
    """Unordered pairs already proposed, so re-running never duplicates."""
    pairs = set()
    for path in out_dir.glob("*.md"):
        try:
            note = Note.load(path)
        except FrontmatterError:
            continue
        source, target = str(note.meta.get("source", "")), str(note.meta.get("target", ""))
        if source and target:
            pairs.add(tuple(sorted((source, target))))
    return pairs


def select(pairs: list[PairScore], communities: dict[str, int], linked: set,
           proposed: set, threshold: float, limit: int) -> list[PairScore]:
    chosen: list[PairScore] = []
    for pair in pairs:
        if pair.score < threshold:
            continue
        key = pair.unordered()
        if key in linked or key in proposed:
            continue
        if communities.get(pair.a) == communities.get(pair.b):
            continue  # same community: not serendipity, just neighbourhood
        chosen.append(pair)
        if len(chosen) >= limit:
            break
    return chosen


def write_proposal(out_dir: Path, pair: PairScore, notes_by_key: dict[str, Note],
                   communities: dict[str, int], scorer_name: str) -> Path:
    a, b = pair.unordered()
    path = out_dir / f"{a}--TO--{b}.md"
    meta = {
        "source": a,
        "target": b,
        "suggested_relation": NEUTRAL_RELATION,
        "score": pair.score,
        "scorer": scorer_name,
        "communities": [communities.get(a), communities.get(b)],
        "evidence": list(pair.evidence),
        "status": "pending-review",
    }
    evidence = ", ".join(pair.evidence) if pair.evidence else "(embedding similarity only)"
    body = (
        f"# Proposed link\n\n"
        f"- **{a}** — {notes_by_key[a].title}\n"
        f"- **{b}** — {notes_by_key[b].title}\n\n"
        f"These notes sit in different communities of the link graph "
        f"({communities.get(a)} and {communities.get(b)}) yet score "
        f"{pair.score} by {scorer_name}. Shared terms: {evidence}.\n\n"
        f"This is a machine-generated candidate, not a justification. The "
        f"connector agent must read both notes and either write a real one-line "
        f"justification with an honest relation, or discard this proposal.\n"
    )
    path.write_text(dump(meta, body), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("--threshold", type=float, default=None,
                        help="minimum similarity to propose "
                             "(default: the chosen scorer's calibrated value)")
    parser.add_argument("--out", default="proposed-links",
                        help="repo-relative directory for proposals")
    parser.add_argument("--max-proposals", type=int, default=10,
                        help="cap on proposals written per sweep")
    parser.add_argument("--force-lexical", action="store_true",
                        help="always use stdlib lexical scoring, ignoring config")
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)

    try:
        scorer, warnings = choose_scorer(repo, args.force_lexical)
        notes = load_notes(repo)
    except (ContentRepoError, FrontmatterError) as exc:
        # A sweep is advisory: report and exit 0 rather than failing a run.
        print(f"warning: {exc}", file=sys.stderr)
        repo.append_log(f"serendipity_sweep: SKIPPED ({exc})")
        return EXIT_OK

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
        repo.append_log(f"serendipity_sweep: DEGRADED {warning}")

    if len(notes) < 2:
        print("serendipity_sweep: fewer than 2 sweepable notes; nothing to do")
        repo.append_log("serendipity_sweep: 0 proposals (too few notes)")
        return EXIT_OK

    id_to_key = {n.id: n.key for n in notes if n.id}
    graph = build_graph(notes, id_to_key)
    communities = detect_communities(graph)
    n_communities = len(set(communities.values()))

    docs = {n.key: f"{n.title}\n{n.body}" for n in notes}
    pairs = scorer.score_pairs(docs)

    out_dir = repo.root / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    threshold = args.threshold if args.threshold is not None else scorer.default_threshold

    chosen = select(pairs, communities, existing_edges(graph),
                    existing_proposals(out_dir), threshold, args.max_proposals)

    notes_by_key = {n.key: n for n in notes}
    for pair in chosen:
        path = write_proposal(out_dir, pair, notes_by_key, communities, scorer.name)
        print(f"proposed\t{repo.rel(path)}\t{pair.score}")

    summary = (f"{len(chosen)} proposal(s) from {len(notes)} notes in "
               f"{n_communities} communities (scorer={scorer.name}, "
               f"threshold={threshold})")
    print(f"serendipity_sweep: {summary}")
    repo.append_log(f"serendipity_sweep: {summary}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
