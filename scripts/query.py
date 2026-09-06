#!/usr/bin/env python3
"""Map what a content repo already knows about a query. Read-only.

Every other entry point either grows the repository or gates it. This one
answers a different question -- "what does the base already have on X?" --
without researching, writing, or filing anything. That matters for two
reasons. A person deciding whether a question is worth an inquiry needs to
see the existing coverage first, and a session asked "what do we know about
X" must not quietly turn the question into a research run: growing the base
is a cycle's job, behind the lock and the gates.

The report is deterministic and cites note keys, so a session can answer from
it and the reader can open exactly the notes it names. Ranking is the same
TF-IDF the serendipity sweep uses (``zettel_lib.similarity``), applied query
vs. note instead of note vs. note; titles and tags are weighted above bodies
because a permanent note's title is its claim.

    query.py --repo <path> "<query>" [--top N] [--gaps N] [--json] [--mermaid]
             [--file-gaps [g1,g3]]

A query is not an operation, so nothing is appended to log.md (A9). The one
exception is explicit: ``--file-gaps`` turns the report's suggested
follow-ups (an inquiry for a topic the base lacks, INBOX entries for
undistilled or unmapped material) into real captures through capture.py, so
a person reading the report in a remote session can say "file those" and
have it done. That IS an operation, and it logs like one.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture
from zettel_lib import graph, similarity
from zettel_lib.cli import EXIT_OK, EXIT_USAGE, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import ContentRepo, ContentRepoError, dig

TYPE_ORDER = ("permanent", "literature", "reference", "moc", "fleeting")

#: Gap kinds in the order a run should work them, and the capture kind that
#: closes each. The order is load-bearing: `session_query_prompt.md` tells a
#: session to work the filed entries in the order they were filed, so filing
#: order has to encode priority. It used to be implicit in the sequence of
#: `if` blocks below, which meant adding a gap in the wrong place silently
#: reordered a session's work.
#:
#: Research gaps become inquiries -- questions a run goes out and answers.
#: Everything else becomes an INBOX entry, because the material is already in
#: the repository: filing "nothing has been distilled from these sources" as an
#: inquiry would send the researcher to re-fetch what the base already holds.
GAP_KINDS = (
    ("unresearched", "inquiry"),
    ("weak-sourcing", "inquiry"),
    ("stale-inquiry", "inbox"),
    ("undistilled", "inbox"),
    ("unsummarised-reference", "inbox"),
    ("orphan-claim", "inbox"),
    ("unmapped", "inbox"),
    ("raw-mentions", "inbox"),
)
GAP_RANK = {kind: i for i, (kind, _) in enumerate(GAP_KINDS, start=1)}

#: `--file-gaps` with no value files everything, which is what it has always
#: done; a value selects by id.
ALL_GAPS = "*"
GAP_ID = re.compile(r"^[gG](\d+)$")


@dataclass
class Gap:
    """One absence the report found, and the follow-up that would close it.

    ``suggestion`` is the dict itself rather than an index, because two gaps
    can share one follow-up -- "no note uses these terms" and "nothing matched
    at all" are two ways of saying the base lacks the topic, and they must not
    file two identical inquiries. Indices are assigned at the end, after
    ranking, when the surviving suggestions are known.
    """

    kind: str
    text: str
    suggestion: dict
    keys: tuple[str, ...] = ()
    terms: tuple[str, ...] = ()

    def sort_key(self) -> tuple[int, str]:
        """Rank first, then a stable string -- never a score, never dict order."""
        return (GAP_RANK[self.kind], " ".join(self.keys or self.terms))
#: A title is the claim and tags are the curated vocabulary; a body mentions
#: many things in passing. Repeating them weights the vector accordingly.
TITLE_WEIGHT = 3
TAG_WEIGHT = 3


def load_notes(repo: ContentRepo) -> tuple[list[Note], list[str]]:
    notes, warnings = [], []
    for path in repo.note_paths():
        try:
            notes.append(Note.load(path))
        except FrontmatterError as exc:
            warnings.append(f"{repo.rel(path)}: skipped ({exc})")
    return notes, warnings


def doc_text(note: Note) -> str:
    parts = [note.title] * TITLE_WEIGHT + [" ".join(note.tags)] * TAG_WEIGHT + [note.body]
    return "\n".join(parts)


def rank_gaps(found: list[Gap], cap: int = 0) -> tuple[list[str], list[dict], list[dict]]:
    """Order the gaps, number them, and collect the follow-ups they point at.

    Ids are assigned AFTER the sort, so `g1` is always the highest-priority gap
    and "work them in the order they were filed" stays true. They are
    report-local: the same repo and query reproduce them exactly, and adding a
    note renumbers them. That is the trade -- an id durable across repository
    changes would have to be a content hash, which nobody can type into
    `--file-gaps g1,g3`.

    ``cap`` truncates after ranking, so the cap keeps the gaps that matter and
    drops a follow-up whose only gaps were cut. Capping the display while still
    filing everything would make the printed receipt lie about what happened.
    """
    ordered = sorted(found, key=Gap.sort_key)
    if cap > 0:
        ordered = ordered[:cap]

    # Suggestions come out in gap order, and a shared one appears once.
    suggestions: list[dict] = []
    index: dict[int, int] = {}
    for gap in ordered:
        if id(gap.suggestion) not in index:
            index[id(gap.suggestion)] = len(suggestions)
            suggestions.append(dict(gap.suggestion, gaps=[]))

    gaps, details = [], []
    for position, gap in enumerate(ordered, start=1):
        gap_id = f"g{position}"
        slot = index[id(gap.suggestion)]
        suggestions[slot]["gaps"].append(gap_id)
        gaps.append(f"{gap_id}: {gap.text}")
        details.append({"id": gap_id, "rank": GAP_RANK[gap.kind], "kind": gap.kind,
                        "text": gap.text, "keys": list(gap.keys),
                        "terms": list(gap.terms), "suggestion": slot})
    return gaps, details, suggestions


def query(repo: ContentRepo, text: str, top: int = 15, *, gap_cap: int = 0) -> dict:
    notes, warnings = load_notes(repo)
    by_key = {n.key: n for n in notes if n.key}
    id_to_key = {n.id: n.key for n in notes if n.id and n.key}
    keys = set(by_key)

    hits, missing = similarity.score_query(text, {k: doc_text(n) for k, n in by_key.items()})
    hits = hits[:top]
    hit_keys = {h.key for h in hits}

    # Who cites whom, so a permanent note can show its sources and a
    # reference can show what rests on it.
    inbound = graph.inbound_map(by_key.values(), keys, id_to_key)

    def describe(note: Note) -> dict:
        row = {"key": note.key, "type": note.type, "title": note.title,
               "path": repo.rel(note.path), "tags": note.tags}
        if note.type == "permanent":
            row["sources"] = sorted(k for k in graph.neighbours(note, keys, id_to_key)
                                    if by_key[k].type == "reference")
        elif note.type == "literature":
            row["locator"] = str(note.meta.get("locator") or "")
            row["reference"] = str(note.meta.get("reference") or "")
        elif note.type == "reference":
            v = note.meta.get("verification") or {}
            row["source_tier"] = str(note.meta.get("source_tier") or "")
            row["verified"] = v.get("verified") is True
            row["method"] = str(v.get("method") or "")
            row["cited_by"] = sorted(inbound.get(note.key, ()))
            row["chicago_note"] = str(note.meta.get("chicago_note") or "")
        return row

    matched = []
    for h in hits:
        row = describe(by_key[h.key])
        row.update({"score": h.score, "evidence": list(h.evidence)})
        matched.append(row)

    connected = []
    seen = set(hit_keys)
    for h in hits:
        for k in sorted(graph.neighbours(by_key[h.key], keys, id_to_key) | inbound[h.key]):
            if k in seen:
                continue
            seen.add(k)
            row = describe(by_key[k])
            row["via"] = h.key
            connected.append(row)

    # The subgraph the report actually drew: matched notes plus the notes one
    # link away. Edges are kept only when BOTH endpoints are in that set -- an
    # edge to a node the report never listed would dangle, and a reader cannot
    # look up what is not there.
    subgraph_keys = {row["key"] for row in matched} | {row["key"] for row in connected}
    edges = sorted(
        {e for k in subgraph_keys
           for e in graph.out_edges(by_key[k], keys, id_to_key)
           if e.target in subgraph_keys})
    moc_membership = {k: graph.moc_membership(k, inbound, by_key)
                      for k in sorted(subgraph_keys)}
    # Always rendered, like every other field: the report's shape does not
    # change with the flags. --mermaid decides whether the HUMAN report shows
    # the diagram, not whether the JSON carries it.
    mermaid = graph.render_mermaid(
        {k: by_key[k].type for k in subgraph_keys},
        {k: by_key[k].title for k in subgraph_keys},
        edges)

    # Inquiries are questions about the graph, not nodes in it: match them
    # separately so "already asked" is visible next to "already answered".
    inquiries = []
    q_terms = set(similarity.tokenize(text))
    for inq in repo.inquiries():
        if q_terms & set(similarity.tokenize(inq.question)):
            inquiries.append({"key": inq.key, "status": inq.status,
                              "priority": inq.priority or "normal",
                              "question": inq.question,
                              "result_notes": inq.result_notes})

    by_type = {t: sum(1 for m in matched if m["type"] == t) for t in TYPE_ORDER}

    # Each gap names one absence and points at the follow-up that would close
    # it. They are suggestions: printed as ready-to-run capture commands, and
    # executed only under --file-gaps. Which capture kind each gap files, and
    # in what order, is GAP_KINDS above.
    found: list[Gap] = []
    repo_arg = shlex.quote(str(repo.root))

    def suggest(kind: str, title: str, why: str, priority: str = "normal") -> dict:
        cmd = f"scripts/capture.py --repo {repo_arg} {kind} {shlex.quote(title)}"
        if kind == "inquiry":
            cmd += f" --priority {priority}"
        return {"kind": kind, "title": title, "priority": priority,
                "why": why, "command": cmd}

    if missing or not matched:
        # One follow-up, up to two ways of describing the same absence: both
        # say the base lacks the topic, and filing two identical inquiries for
        # it would be noise the next run has to reconcile.
        research = suggest("inquiry", text, "research the topic the base lacks")
        if missing:
            found.append(Gap(
                "unresearched",
                "no note uses the term(s) " + ", ".join(f"'{t}'" for t in missing)
                + "; the base has nothing on them",
                research, terms=tuple(missing)))
        if not matched:
            found.append(Gap("unresearched", "no note matches this query at all",
                             research, terms=tuple(sorted(q_terms))))
    if matched and by_type["permanent"] == 0:
        material = [m["key"] for m in matched if m["type"] != "moc"]
        found.append(Gap(
            "undistilled",
            "sources or summaries match but no permanent note does: "
            "nothing has been distilled into a claim yet",
            suggest("inbox", f"Distil a permanent note on {text} from: " + ", ".join(material),
                    "the synthesizer's job, not the researcher's"),
            keys=tuple(material)))
    # Same source as the moc_membership field: two implementations would
    # eventually disagree about whether a note is reachable from INDEX, which is
    # the only thing either of them is for.
    uncovered = [m["key"] for m in matched
                 if m["type"] != "moc" and not moc_membership[m["key"]]]
    if uncovered:
        found.append(Gap(
            "unmapped",
            f"{len(uncovered)} matched note(s) sit in no map of content, so a "
            "reader walking down from INDEX cannot find them: "
            + ", ".join(f"`{k}`" for k in uncovered),
            suggest("inbox", "Add to a map of content: " + ", ".join(uncovered)
                    + f" (surfaced by a query for: {text})",
                    "the librarian's job"),
            keys=tuple(uncovered)))

    gaps, gap_details, suggestions = rank_gaps(found, cap=gap_cap)
    cfg = {}
    try:
        cfg = repo.config()
    except ContentRepoError:
        pass
    topics = [str(t) for t in (dig(cfg, "topics") or [])]
    touched_topics = [t for t in topics if q_terms & set(similarity.tokenize(t))]

    return {
        "query": text,
        "terms": sorted(q_terms),
        "missing_terms": missing,
        "note_count": len(by_key),
        "matched": matched,
        "by_type": by_type,
        "connected": connected,
        "edges": [{"source": e.source, "target": e.target, "relation": e.relation}
                  for e in edges],
        "moc_membership": moc_membership,
        "mermaid": mermaid,
        "inquiries": inquiries,
        "topics": touched_topics,
        "gaps": gaps,
        "gap_details": gap_details,
        "suggestions": suggestions,
        "filed": [],
        "warnings": warnings,
    }


def select_suggestions(report: dict, selection: str) -> list[dict]:
    """The suggestions ``selection`` names, or all of them for a bare flag.

    Every id is validated before anything is written, the way
    ``capture.py inquiry-update`` validates before it writes: an id that is not
    in this report means the caller is acting on a report they are no longer
    reading, and filing "the ones that did exist" would file the wrong things
    silently.
    """
    if selection == ALL_GAPS:
        return list(report["suggestions"])
    wanted, known = [], {d["id"]: d for d in report["gap_details"]}
    for raw in selection.split(","):
        item = raw.strip()
        if not GAP_ID.match(item):
            raise ValueError(
                f"--file-gaps takes gap ids like 'g1,g3'; got {item!r}"
                + (" (put the query before the flag)" if " " in item or not item else ""))
        item = item.lower()
        if item not in known:
            have = ", ".join(d["id"] for d in report["gap_details"]) or "no gaps"
            raise ValueError(f"unknown gap id {item!r}; this report has {have}")
        wanted.append(known[item]["suggestion"])
    # Two selected gaps can share one follow-up; file it once, in report order.
    return [report["suggestions"][i] for i in sorted(set(wanted))]


def file_gaps(repo: ContentRepo, report: dict, selection: str = ALL_GAPS) -> list[dict]:
    """Turn the report's suggestions into captures (the --file-gaps path).

    Goes through capture.py's own functions so the artifacts are exactly what
    a hand capture would produce -- allocated ids, gate-clean frontmatter --
    and rebuilds the manifest once at the end, the way capture.py does after
    an inquiry, so a capture-only commit still passes the currency gate.
    """
    chosen = select_suggestions(report, selection)
    filed = []
    for s in chosen:
        if s["kind"] == "inquiry":
            path = capture.capture_inquiry(repo, s["title"], "", s["priority"])
        else:
            path = capture.capture_inbox(repo, s["title"], "")
        rel = repo.rel(path)
        repo.append_log(f"query --file-gaps: {s['kind']} -> {rel}")
        filed.append({"kind": s["kind"], "path": rel, "gaps": list(s.get("gaps", ()))})
    if any(f["kind"] == "inquiry" for f in filed):
        capture.build_manifest.regenerate(repo)
    report["filed"] = filed
    return filed


def render(report: dict, repo_path: str, mermaid: bool = False) -> str:
    out = [f"# What the base knows about: \"{report['query']}\"", ""]
    counts = ", ".join(f"{t} {n}" for t, n in report["by_type"].items() if n)
    out.append(f"Matched {len(report['matched'])} of {report['note_count']} notes"
               + (f" ({counts})" if counts else "")
               + f"; {len(report['inquiries'])} inquiry(ies) touch it.")
    if report["topics"]:
        out.append("Configured topic(s) touched: " + ", ".join(report["topics"]) + ".")
    out.append("")

    def section(title: str, rows: list[dict], line) -> None:
        out.append(f"## {title}")
        if not rows:
            out.append("- none")
        for row in rows:
            out.append(line(row))
        out.append("")

    def score_tail(row: dict) -> str:
        return f" (score {row['score']:.3f}; terms: {', '.join(row['evidence'])})"

    matched = report["matched"]
    section("Claims the base makes (permanent notes)",
            [m for m in matched if m["type"] == "permanent"],
            lambda r: f"- **{r['title']}** -- `{r['key']}`{score_tail(r)}"
                      + (f"\n  sources: {', '.join(r['sources'])}" if r["sources"]
                         else "\n  sources: none linked"))
    section("Literature notes (one source each)",
            [m for m in matched if m["type"] == "literature"],
            lambda r: f"- **{r['title']}** -- `{r['key']}`{score_tail(r)}"
                      f"\n  source: `{r['reference']}`"
                      + (f", locator {r['locator']}" if r["locator"] else ""))
    section("Sources on file (reference notes)",
            [m for m in matched if m["type"] == "reference"],
            lambda r: f"- **{r['title']}** -- `{r['key']}`{score_tail(r)}"
                      f"\n  {r['source_tier'] or 'tier unset'} · "
                      + ("verified via " + r["method"] if r["verified"] else "UNVERIFIED")
                      + f" · cited by {len(r['cited_by'])} note(s)")
    section("Maps of content",
            [m for m in matched if m["type"] == "moc"],
            lambda r: f"- **{r['title']}** -- `{r['key']}`{score_tail(r)}")
    fleeting = [m for m in matched if m["type"] == "fleeting"]
    if fleeting:
        section("Fleeting captures (not yet distilled)", fleeting,
                lambda r: f"- **{r['title']}** -- `{r['key']}`{score_tail(r)}")
    section("Open inquiries touching this", report["inquiries"],
            lambda r: f"- {r['status']}/{r['priority']} `{r['key']}`: {r['question']}"
                      + (f" -> {', '.join(r['result_notes'])}" if r["result_notes"] else ""))
    section("Connected notes (one link from a match, not themselves matched)",
            report["connected"],
            lambda r: f"- {r['type']} **{r['title']}** -- `{r['key']}` (via `{r['via']}`)")

    if mermaid:
        out.append("## The subgraph")
        out.append("")
        out.append("```mermaid")
        out.append(report["mermaid"])
        out.append("```")
        out.append("")

    out.append("## Gaps")
    for gap in report["gaps"]:
        out.append(f"- {gap}")
    if not report["gaps"]:
        out.append("- none obvious: claims, sources, and a map all exist")
    out.append("")
    if report["filed"]:
        out.append("## Filed for the next run")
        for f in report["filed"]:
            closes = ", ".join(f.get("gaps", ()))
            out.append(f"- {f['kind']}: `{f['path']}`"
                       + (f" (closes {closes})" if closes else ""))
        out.append("")
        out.append("Commit these so the next scheduled run sees them (from a remote "
                   "session: on a branch, via a PR).")
    elif report["suggestions"]:
        out.append("## Suggested follow-ups (nothing has been filed)")
        for s in report["suggestions"]:
            closes = ", ".join(s.get("gaps", ())) or "-"
            out.append(f"- [{closes}] {s['kind']}: {s['title']}")
            out.append(f"  why: {s['why']}")
            out.append(f"  {s['command']}")
        out.append("")
        out.append(f"To file all {len(report['suggestions'])} at once, re-run this query "
                   "with --file-gaps (or ask the session to); to file a selection, name "
                   "the gap ids: --file-gaps g1,g3. Ids belong to this report -- they are "
                   "the same for the same repo and query, and renumber as the repo grows.")
    else:
        out.append("This report wrote nothing, and found nothing worth filing.")
    for w in report["warnings"]:
        out.append(f"warning: {w}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("query", help="free-text question or topic")
    parser.add_argument("--top", type=int, default=15,
                        help="maximum matched notes to report (default 15)")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument("--mermaid", action="store_true",
                        help="include a Mermaid diagram of the subgraph in the report "
                             "(the JSON always carries it)")
    parser.add_argument("--gaps", type=int, default=0, metavar="N",
                        help="report at most N gaps, highest priority first (0 = all)")
    parser.add_argument("--file-gaps", nargs="?", const=ALL_GAPS, default=None,
                        metavar="g1,g3",
                        help="capture the suggested follow-ups (inquiries / INBOX entries) "
                             "through capture.py instead of only printing them; bare files "
                             "every one, or name the gap ids to file")
    args = parser.parse_args(argv)
    if not args.query.strip():
        print("error: empty query", file=sys.stderr)
        return EXIT_USAGE
    if args.gaps < 0:
        print("error: --gaps must be >= 0", file=sys.stderr)
        return EXIT_USAGE
    repo = open_repo(args.repo)
    try:
        report = query(repo, args.query, top=max(1, args.top), gap_cap=args.gaps)
        # `is not None` is what keeps "writes nothing without --file-gaps"
        # literally true: an empty selection string is still a request.
        if args.file_gaps is not None:
            file_gaps(repo, report, args.file_gaps)
    except (ContentRepoError, FrontmatterError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render(report, str(repo.root), mermaid=args.mermaid))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
