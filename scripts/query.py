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

    query.py --repo <path> "<query>" [--top N] [--json]

A query is not an operation, so nothing is appended to log.md (A9).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib import similarity
from zettel_lib.cli import EXIT_OK, EXIT_USAGE, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import ContentRepo, ContentRepoError, dig

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
TYPE_ORDER = ("permanent", "literature", "reference", "moc", "fleeting")
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


def neighbours(note: Note, keys: set[str], id_to_key: dict[str, str]) -> set[str]:
    """Keys one link away (typed links and body wikilinks, bare ids resolved)."""
    targets = {str(l.get("target_id", "")) for l in note.links}
    targets |= {m.group(1).strip() for m in WIKILINK.finditer(note.body)}
    out = set()
    for t in targets:
        resolved = t if t in keys else id_to_key.get(t)
        if resolved:
            out.add(resolved)
    return out


def query(repo: ContentRepo, text: str, top: int = 15) -> dict:
    notes, warnings = load_notes(repo)
    by_key = {n.key: n for n in notes if n.key}
    id_to_key = {n.id: n.key for n in notes if n.id and n.key}
    keys = set(by_key)

    hits, missing = similarity.score_query(text, {k: doc_text(n) for k, n in by_key.items()})
    hits = hits[:top]
    hit_keys = {h.key for h in hits}

    # Who cites whom, so a permanent note can show its sources and a
    # reference can show what rests on it.
    inbound: dict[str, set[str]] = {k: set() for k in keys}
    for n in by_key.values():
        for target in neighbours(n, keys, id_to_key):
            inbound[target].add(n.key)

    def describe(note: Note) -> dict:
        row = {"key": note.key, "type": note.type, "title": note.title,
               "path": repo.rel(note.path), "tags": note.tags}
        if note.type == "permanent":
            row["sources"] = sorted(k for k in neighbours(note, keys, id_to_key)
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
        for k in sorted(neighbours(by_key[h.key], keys, id_to_key) | inbound[h.key]):
            if k in seen:
                continue
            seen.add(k)
            row = describe(by_key[k])
            row["via"] = h.key
            connected.append(row)

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
    gaps = []
    if missing:
        gaps.append("no note uses the term(s) " + ", ".join(f"'{t}'" for t in missing)
                    + "; the base has nothing on them")
    if matched and by_type["permanent"] == 0:
        gaps.append("sources or summaries match but no permanent note does: "
                    "nothing has been distilled into a claim yet")
    uncovered = [m["key"] for m in matched if m["type"] != "moc"
                 and not any(by_key[k].type == "moc" for k in inbound[m["key"]])]
    if uncovered:
        gaps.append(f"{len(uncovered)} matched note(s) sit in no map of content, so a "
                    "reader walking down from INDEX cannot find them: "
                    + ", ".join(f"`{k}`" for k in uncovered))
    if not matched:
        gaps.append("no note matches this query at all")
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
        "inquiries": inquiries,
        "topics": touched_topics,
        "gaps": gaps,
        "warnings": warnings,
    }


def render(report: dict, repo_path: str) -> str:
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

    out.append("## Gaps")
    for gap in report["gaps"]:
        out.append(f"- {gap}")
    if not report["gaps"]:
        out.append("- none obvious: claims, sources, and a map all exist")
    out.append("")
    out.append("This report wrote nothing. If a gap is worth closing, file it for the "
               "next run:")
    out.append(f"  scripts/capture.py --repo {repo_path} inquiry "
               f"\"{report['query']}\" --priority normal")
    for w in report["warnings"]:
        out.append(f"warning: {w}")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("query", help="free-text question or topic")
    parser.add_argument("--top", type=int, default=15,
                        help="maximum matched notes to report (default 15)")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    args = parser.parse_args(argv)
    if not args.query.strip():
        print("error: empty query", file=sys.stderr)
        return EXIT_USAGE
    repo = open_repo(args.repo)
    try:
        report = query(repo, args.query, top=max(1, args.top))
    except ContentRepoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(render(report, str(repo.root)))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
