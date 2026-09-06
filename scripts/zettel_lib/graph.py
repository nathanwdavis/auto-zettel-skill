"""The note link graph: one traversal, read the same way by every caller.

Four entry points walk the same edges -- ``lint_links`` (which fails an
unresolvable one), ``lint_citations`` (which follows them to a note's
references), ``query.py`` (which reports neighbours and now the subgraph
itself), and ``serendipity_sweep`` (which scores across them). Before this
module the ``[[wikilink]]`` pattern was written out three times and the
"typed links plus body wikilinks, bare ids resolved" walk four times. A graph
read four slightly different ways is a graph nobody can reason about: the lint
would pass a link the report never drew, or the reverse.

So the pattern and the walk live here, once.

Two edges are NOT the same fact and this module keeps them apart. A typed link
is curated -- an author chose ``supports`` from the closed FR-5 set. A body
wikilink is a mention in prose: real evidence of a connection, but nobody
asserted a relation. ``out_edges`` returns both, labelled, and ``neighbours``
flattens them for the callers that only need "what is one hop away".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import naming
from .frontmatter import Note

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")

#: The relation label for a body wikilink. Deliberately OUTSIDE
#: ``repo.RELATIONS``: it describes an edge the graph observed, not one an
#: author asserted, and if it ever leaked into a note's ``links`` block
#: ``lint_links`` would (correctly) fail it as ``bad-relation``.
MENTIONS = "mentions"


@dataclass(frozen=True, order=True)
class Edge:
    """One directed edge, with the relation that justifies it."""

    source: str
    target: str
    relation: str


def resolve(target: str, keys: set[str], id_to_key: dict[str, str]) -> str | None:
    """Resolve a link target to a note key, accepting a bare timestamp ID."""
    target = target.strip()
    if target in keys:
        return target
    if naming.is_id(target) and target in id_to_key:
        return id_to_key[target]
    return None


def out_edges(note: Note, keys: set[str], id_to_key: dict[str, str]) -> list[Edge]:
    """Every resolvable edge leaving ``note``: typed links first, then mentions.

    A target that is both typed-linked and wikilinked yields TWO edges. That is
    not duplication -- a curated ``elaborates`` and a passing mention in prose
    are different claims about the same pair, and collapsing them would lose
    the distinction the whole module exists to keep.

    Unresolvable targets are dropped rather than reported: this is the reader,
    and ``lint_links`` is the gate that fails them.
    """
    edges: list[Edge] = []
    for link in note.links:
        target = resolve(str(link.get("target_id", "")), keys, id_to_key)
        if target:
            edges.append(Edge(note.key, target, str(link.get("relation", ""))))
    for match in WIKILINK.finditer(note.body):
        target = resolve(match.group(1), keys, id_to_key)
        if target:
            edges.append(Edge(note.key, target, MENTIONS))
    return edges


def neighbours(note: Note, keys: set[str], id_to_key: dict[str, str]) -> set[str]:
    """Keys one link away, by any kind of edge."""
    return {e.target for e in out_edges(note, keys, id_to_key)}


def inbound_map(notes, keys: set[str], id_to_key: dict[str, str]) -> dict[str, set[str]]:
    """For every key, the notes that link TO it.

    Who cites whom: a permanent note can show its sources and a reference can
    show what rests on it. Every key in ``keys`` is present, with an empty set
    when nothing points at it -- callers ask about orphans, and a KeyError is
    not an answer.
    """
    inbound: dict[str, set[str]] = {k: set() for k in keys}
    for note in notes:
        for edge in out_edges(note, keys, id_to_key):
            inbound[edge.target].add(edge.source)
    return inbound


def moc_membership(key: str, inbound: dict[str, set[str]], by_key: dict[str, Note]) -> list[str]:
    """The maps of content that reach ``key``, sorted.

    One definition, because two things need it and they must agree: the JSON
    field a session reads, and the gap that fires when a note is in no map at
    all. Two implementations would eventually disagree about whether a note is
    reachable from INDEX, which is the only thing either of them is for.
    """
    return sorted(k for k in inbound.get(key, ()) if k in by_key and by_key[k].type == "moc")


#: How each note type is drawn. Shape carries the type so a reader can tell a
#: claim from its source without following the legend on every node.
MERMAID_SHAPES = {
    "permanent": ('["', '"]'),
    "literature": ('("', '")'),
    "reference": ('[("', '")]'),
    "moc": ('{{"', '"}}'),
    "fleeting": ('>"', '"]'),
}
_DEFAULT_SHAPE = ('["', '"]')

#: Mermaid reads these as syntax inside a label even when the label is quoted,
#: so they go in as HTML entities. Order matters only in that `"` must be
#: handled like the rest -- there is no escape character to double up.
_MERMAID_ESCAPES = {
    '"': "#quot;", "[": "#91;", "]": "#93;", "(": "#40;", ")": "#41;",
    "{": "#123;", "}": "#125;", "<": "#60;", ">": "#62;", "|": "#124;",
}


def mermaid_label(text: str) -> str:
    """A note title made safe to sit inside a quoted Mermaid label.

    A title is free text -- it can contain quotes, brackets, or a pipe -- and
    any of those ends the label early and produces a diagram that either fails
    to parse or, worse, silently renders the wrong graph.
    """
    out = "".join(_MERMAID_ESCAPES.get(ch, ch) for ch in str(text))
    return " ".join(out.split())


def render_mermaid(node_types: dict[str, str], titles: dict[str, str],
                   edges) -> str:
    """The subgraph as Mermaid source, deterministically.

    Node ids are synthetic (``n0``, ``n1`` ...) and assigned in sorted-key
    order: a note key contains ``--``, which Mermaid can read as the start of an
    edge inside an identifier. The key still appears in the label, because a
    diagram a reader cannot look notes up from is decoration.

    Nothing here reads a clock or a score, so the same repo and query always
    produce byte-identical output.
    """
    keys = sorted(node_types)
    if not keys:
        return "graph LR\n  %% no notes matched"
    ids = {key: f"n{i}" for i, key in enumerate(keys)}
    lines = ["graph LR",
             "  %% permanent [claim] · literature (summary) · reference [(source)] · "
             "moc {{map}} · fleeting >note]"]
    for key in keys:
        open_, close = MERMAID_SHAPES.get(node_types[key], _DEFAULT_SHAPE)
        label = f"{mermaid_label(titles.get(key, key))}<br/>{mermaid_label(key)}"
        lines.append(f"  {ids[key]}{open_}{label}{close}")
    for edge in sorted(edges):
        if edge.source not in ids or edge.target not in ids:
            continue
        # A dotted arrow for a prose mention, a solid one for a curated
        # relation: the eye should be able to tell them apart at a glance.
        arrow = "-.->" if edge.relation == MENTIONS else "-->"
        lines.append(f'  {ids[edge.source]} {arrow}|"{mermaid_label(edge.relation)}"| '
                     f'{ids[edge.target]}')
    return "\n".join(lines)
