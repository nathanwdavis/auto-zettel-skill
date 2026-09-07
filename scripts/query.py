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

    query.py --repo <path> "<query>" [--top N] [--gaps N] [--include-raw]
             [--json] [--mermaid] [--file-gaps [g1,g3]]
    query.py --repo <path> --from-file raw/<id>-<slug>.txt   (passage mode)

A query is not an operation, so nothing is appended to log.md (A9). The one
exception is explicit: ``--file-gaps`` turns the report's suggested
follow-ups (an inquiry for a topic the base lacks, INBOX entries for
undistilled or unmapped material) into real captures through capture.py, so
a person reading the report in a remote session can say "file those" and
have it done. That IS an operation, and it logs like one.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture
import lint_citations
from zettel_lib import graph, passages, similarity
from zettel_lib.cli import EXIT_OK, EXIT_USAGE, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import (STRONG_TIERS, WEAK_TIER, ContentRepo, ContentRepoError,
                             dig, passage_bands, stale_inquiry_days)

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


#: How many captures a raw-mentions gap names before it says "...". Enough to
#: act on, few enough that the line stays readable; the count is always given.
RAW_NAMED = 3


def age_in_days(note: Note) -> float | None:
    """Days since a note was last touched, or None when it cannot be told.

    `updated` is what inquiry-update bumps, so it is the honest "last worked"
    stamp; `created` is the fallback for a note nothing has touched since. A
    date that will not parse yields None rather than raising: build_manifest is
    the gate for malformed frontmatter, and a query is not a gate.
    """
    for field in ("updated", "created"):
        raw = str(note.meta.get(field) or "").strip()
        if not raw:
            continue
        try:
            stamp = _dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=_dt.timezone.utc)
        return (_dt.datetime.now(_dt.timezone.utc) - stamp).total_seconds() / 86400
    return None


def raw_mentions(repo: ContentRepo, terms: list[str]) -> dict[str, list[str]]:
    """Which raw/ captures use each term, for terms no NOTE uses.

    The point is not that the term appears somewhere -- it is that the base
    already holds a source for it, so the follow-up is distillation rather than
    research. Filing an inquiry here would send a researcher to re-fetch what is
    already on disk.

    Tokenised rather than substring-matched, so the term set agrees with the
    scorer that produced `missing` in the first place; sorted, so two runs over
    an unchanged repo agree.
    """
    wanted = set(terms)
    hits: dict[str, list[str]] = {t: [] for t in wanted}
    for path in sorted((repo.root / "raw").glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        present = wanted & set(similarity.tokenize(text))
        for term in present:
            hits[term].append(repo.rel(path))
    return {t: v for t, v in hits.items() if v}


def check_from_file(repo: ContentRepo, raw: Path) -> Path:
    """Validate a --from-file path, or raise with the fix in the message.

    Outside the repo is refused rather than read: passage mode's entire output
    is `capture.py literature --reference <key>` commands, and the reference is
    resolved from a repo-relative `raw_capture`. A file the repository does not
    hold has no reference note and can yield no citable locator.
    """
    path = Path(raw).resolve()
    if not path.exists():
        raise ValueError(f"no such file: {raw}")
    if not path.is_relative_to(repo.root):
        raise ValueError(f"--from-file must be inside {repo.root}; got {path}")
    if path.suffix.lower() != ".txt":
        sibling = path.with_suffix(".txt")
        hint = (f"; try {repo.rel(sibling)}" if sibling.exists()
                else " (ingest_drops.py writes one beside every capture it takes)")
        raise ValueError(
            f"passage mode reads the text extraction, not the capture itself{hint}")
    return path


def passage_report(repo: ContentRepo, path: Path, *, top: int = 15) -> dict:
    """Score a capture's text extraction passage by passage. Reads only.

    The commands it prints are the deliverable. A `none` chunk gets a
    ready-to-run `capture.py literature` line with its locator already filled
    in, because that is the step a reader would otherwise do by hand -- and
    hand-authoring a literature note is what capture.py exists to prevent.

    A `same-claim` or `touches` chunk gets no runnable command, only the note it
    lands on. Offering one would invite a duplicate.
    """
    notes, warnings = load_notes(repo)
    by_key = {n.key: n for n in notes if n.key}
    docs = {k: doc_text(n) for k, n in by_key.items() if n.type in passages.CLAIM_TYPES}

    cfg = {}
    try:
        cfg = repo.config()
    except ContentRepoError:
        pass
    same_claim, touches = passage_bands(cfg)

    reference, ref_warnings = passages.reference_for_capture(repo, path)
    warnings.extend(ref_warnings)
    if reference is None:
        # No command is better than a command with a placeholder in it: a
        # checklist naming a placeholder is one that gets improvised around,
        # and a literature note must name a reference that exists.
        warnings.append(
            f"no reference note names {repo.rel(path)}, so no literature command can be "
            "offered; mint one with `capture.py reference` (or re-drop the file through "
            "ingest_drops.py) and re-run")

    analysis = passages.analyse(repo, path, docs, same_claim=same_claim, touches=touches)
    repo_arg = shlex.quote(str(repo.root))
    for chunk in analysis["chunks"]:
        chunk["matches"] = chunk["matches"][:3]
        chunk["command"] = ""
        if chunk["verdict"] == passages.NONE and reference:
            chunk["command"] = (
                f"scripts/capture.py --repo {repo_arg} literature "
                f"{shlex.quote(headline(chunk['text']))} --reference {reference} "
                f"--locator {shlex.quote(chunk['locator'])} --body -")

    candidates = [c["index"] for c in analysis["chunks"] if c["verdict"] == passages.NONE]
    return {
        "mode": "passage",
        "query": "",
        "source": repo.rel(path),
        "reference": reference,
        "note_count": len(by_key),
        "corpus": len(docs),
        "bands": {"same_claim": same_claim, "touches": touches,
                  "min_shared_terms": passages.MIN_SHARED_TERMS,
                  "min_chunk_tokens": passages.MIN_CHUNK_TOKENS},
        "chunks": analysis["chunks"],
        "skipped": analysis["skipped"],
        "paginated": analysis["paginated"],
        "candidates": candidates,
        # Present and empty so a consumer that parses either mode never has to
        # ask which one it got before reading a key; `mode` is how it branches.
        "matched": [], "connected": [], "edges": [], "moc_membership": {},
        "inquiries": [], "topics": [], "mermaid": "",
        "gaps": [], "gap_details": [], "suggestions": [], "filed": [],
        "warnings": warnings,
    }


def headline(text: str, limit: int = 80) -> str:
    """A chunk's first sentence, trimmed at a word boundary, as a note title."""
    first = re.split(r"(?<=[.!?])\s", text.strip())[0]
    if len(first) <= limit:
        return first
    return first[:limit].rsplit(" ", 1)[0] + "..."


def render_passages(report: dict) -> str:
    out = [f"# Passages in `{report['source']}` against what the base knows", ""]
    skipped = report["skipped"]
    out.append(f"{len(report['chunks'])} passage(s) scored against "
               f"{report['corpus']} claim-bearing note(s); "
               f"{skipped['short']} too short to score and {skipped['preamble']} "
               "extraction header(s) set aside.")
    if report["reference"]:
        out.append(f"Source on file as `{report['reference']}`.")
    if not report["paginated"]:
        out.append("No page markers in this extraction, so locators are paragraph "
                   "ordinals rather than pages.")
    out.append("")

    groups = ((passages.NONE, "Candidate claims (nothing in the base is close)"),
              (passages.TOUCHES, "Touches a note (related, but not the same claim)"),
              (passages.SAME_CLAIM, "Already stated (the base makes this claim)"))
    for verdict, title in groups:
        rows = [c for c in report["chunks"] if c["verdict"] == verdict]
        out.append(f"## {title} -- {len(rows)}")
        if not rows:
            out.append("- none")
        for row in rows:
            out.append(f"- **{row['locator']}** {row['text'][:200]}"
                       + ("..." if len(row["text"]) > 200 else ""))
            if row["matches"] and verdict != passages.NONE:
                best = row["matches"][0]
                out.append(f"  nearest: `{best['key']}` (score {best['score']:.3f}, "
                           f"{best['shared']} shared terms)")
            if row["command"]:
                out.append(f"  {row['command']}")
        out.append("")

    if report["candidates"] and report["reference"]:
        out.append("Each candidate command writes one literature note in your own words "
                   "-- the passage above is what to summarise, not what to paste, and "
                   "the title in the command is its opening sentence, there to be "
                   "replaced with what the note actually says. Then distil the claim:")
        out.append(f"    scripts/capture.py --repo <repo> permanent \"<claim>\" "
                   "--link <the key capture.py just printed>:elaborates --body -")
        out.append("")
    for w in report["warnings"]:
        out.append(f"warning: {w}")
    return "\n".join(out)


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


def query(repo: ContentRepo, text: str, top: int = 15, *, gap_cap: int = 0,
          include_raw: bool = False) -> dict:
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
                              "result_notes": inq.result_notes,
                              "age_days": age_in_days(inq)})

    by_type = {t: sum(1 for m in matched if m["type"] == t) for t in TYPE_ORDER}

    # Each gap names one absence and points at the follow-up that would close
    # it. They are suggestions: printed as ready-to-run capture commands, and
    # executed only under --file-gaps. Which capture kind each gap files, and
    # in what order, is GAP_KINDS above.
    found: list[Gap] = []
    repo_arg = shlex.quote(str(repo.root))
    # Loaded before the gaps rather than after: stale-inquiry reads a threshold
    # from it. A missing or broken config is not this tool's problem to report
    # -- the gates own that -- so it degrades to the documented defaults.
    cfg = {}
    try:
        cfg = repo.config()
    except ContentRepoError:
        pass

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


    # -- unsummarised-reference: a source is on file that nobody has read -----
    # Not "no permanent note cites it": summarising a source in your own words
    # is a literature note's job under 1-1-1, and a claim can rest on a source
    # nobody has yet summarised.
    summarised = {str(n.meta.get("reference") or "") for n in by_key.values()
                  if n.type == "literature"}
    summarised |= {e.target for n in by_key.values() if n.type == "literature"
                   for e in graph.out_edges(n, keys, id_to_key)}
    for row in matched:
        if row["type"] != "reference" or row["key"] in summarised:
            continue
        found.append(Gap(
            "unsummarised-reference",
            f"`{row['key']}` is on file but no literature note summarises it: "
            "the source was captured and never read",
            suggest("inbox",
                    f"Write the literature note (own words, with a locator) for "
                    f"{row['key']}; do not re-fetch the source",
                    "the source is already captured -- reading, not research"),
            keys=(row["key"],)))

    # -- weak-sourcing: the same predicate lint_citations warns on ------------
    # Deliberately only the ADVISORY half. The lint's violation half
    # (uncited-claim: a sourced claim with no verified reference at all) is a
    # gate finding and is reported as a warning below, never as a gap: a query
    # offering a follow-up for a failing gate would look like a way around it.
    for row in matched:
        if row["type"] != "permanent":
            continue
        linked = [by_key[k] for k in graph.neighbours(by_key[row["key"]], keys, id_to_key)
                  if by_key[k].type == "reference"
                  and (by_key[k].meta.get("verification") or {}).get("verified") is True]
        if not linked:
            # Gaps have suggestions; warnings do not. A note that makes a
            # sourced claim with no verified reference is lint_citations'
            # `uncited-claim` VIOLATION, and a query offering a follow-up for a
            # failing gate would read as a way around it. The predicate is
            # imported rather than restated: two regexes deciding what counts
            # as a sourced claim would eventually disagree, and this report
            # would announce a gate failure that is not one.
            if lint_citations.SOURCED_CLAIM.search(by_key[row["key"]].body):
                warnings.append(
                    f"{row['path']}: makes a sourced claim but links to no verified "
                    "reference; that is lint_citations' gate to fail, not a gap this "
                    "report can close")
            continue
        tiers = {str(r.meta.get("source_tier") or "").strip() for r in linked}
        if tiers & STRONG_TIERS or tiers - {WEAK_TIER}:
            continue
        found.append(Gap(
            "weak-sourcing",
            f"`{row['key']}` is grounded only in {WEAK_TIER} sources; it has been "
            "discovered but not verified against a stronger one",
            suggest("inquiry", f"Find a primary or peer-reviewed source for: {row['title']}",
                    "a stronger source is one the base does not hold yet"),
            keys=(row["key"],)))

    # -- orphan-claim: nothing links here ------------------------------------
    # Inbound, not outbound. lint_links already fails a permanent note with no
    # OUTBOUND typed link and capture.py refuses to write one, so an outbound
    # check could only fire on a repo that already fails a gate. Inbound is
    # invisible to every gate, and is the classic failure: a note written once
    # and never met again.
    for row in matched:
        if row["type"] != "permanent" or inbound.get(row["key"]):
            continue
        found.append(Gap(
            "orphan-claim",
            f"`{row['key']}` has no inbound link: nothing in the base refers to it, "
            "so it will not be met again by accident",
            suggest("inbox",
                    f"Link {row['key']} into the graph: propose a typed relation to a "
                    "related claim, or run serendipity_sweep.py",
                    "linking work over material the base already holds"),
            keys=(row["key"],)))

    # -- stale-inquiry: a question nobody has worked --------------------------
    # The one time-dependent gap: it is about now by nature. Filing a fresh
    # inquiry would duplicate the question, so it files an INBOX entry that
    # says work it or archive it.
    stale_days = stale_inquiry_days(cfg)
    for inq in inquiries:
        if inq["status"] not in ("new", "in-progress"):
            continue
        age = inq.get("age_days")
        if age is None or age < stale_days:
            continue
        found.append(Gap(
            "stale-inquiry",
            f"inquiry `{inq['key']}` has been {inq['status']} for {int(age)} days "
            f"(threshold {int(stale_days)}): it was asked and never worked",
            suggest("inbox",
                    f"Work or archive the stale inquiry {inq['key']}: {inq['question']}",
                    "the question already exists; a second one would duplicate it"),
            keys=(inq["key"],)))

    # -- raw-mentions: the base HAS the source, it just has no note -----------
    # Opt-in because raw/ holds whole-book extractions: a base with 200
    # captures is hundreds of megabytes to read, against notes measured in
    # kilobytes, and a query must answer in a second from a cold start.
    if include_raw and missing:
        hits_by_term = raw_mentions(repo, missing)
        for term, captures in sorted(hits_by_term.items()):
            found.append(Gap(
                "raw-mentions",
                f"no note uses '{term}', but {len(captures)} capture(s) in raw/ do: "
                + ", ".join(f"`{c}`" for c in captures[:RAW_NAMED])
                + ("..." if len(captures) > RAW_NAMED else ""),
                suggest("inbox",
                        f"Distil notes on '{term}' from captures already on file: "
                        + ", ".join(captures[:RAW_NAMED]),
                        "the source is in raw/ -- distillation, not research"),
                terms=(term,), keys=tuple(captures[:RAW_NAMED])))

    gaps, gap_details, suggestions = rank_gaps(found, cap=gap_cap)

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
    parser.add_argument("query", nargs="?", default="",
                        help="free-text question or topic (omit only with --from-file)")
    parser.add_argument("--from-file", metavar="PATH", type=Path, default=None,
                        help="passage mode: read a capture's .txt extraction and score "
                             "it chunk by chunk against the notes the base already has")
    parser.add_argument("--top", type=int, default=15,
                        help="maximum matched notes to report (default 15)")
    parser.add_argument("--json", action="store_true", help="emit the report as JSON")
    parser.add_argument("--mermaid", action="store_true",
                        help="include a Mermaid diagram of the subgraph in the report "
                             "(the JSON always carries it)")
    parser.add_argument("--include-raw", action="store_true",
                        help="also scan raw/*.txt for query terms no note uses; slower, "
                             "and turns a research gap into a distillation one")
    parser.add_argument("--gaps", type=int, default=0, metavar="N",
                        help="report at most N gaps, highest priority first (0 = all)")
    parser.add_argument("--file-gaps", nargs="?", const=ALL_GAPS, default=None,
                        metavar="g1,g3",
                        help="capture the suggested follow-ups (inquiries / INBOX entries) "
                             "through capture.py instead of only printing them; bare files "
                             "every one, or name the gap ids to file")
    args = parser.parse_args(argv)
    # Usage before environment: a caller who got the arguments wrong should be
    # told that, not that their directory is not a content repo.
    if args.from_file is None and not args.query.strip():
        # The likeliest way to reach this is `--file-gaps <query>`: the flag
        # takes an optional value, so it swallows a query written after it and
        # the positional is left empty. Naming that beats "give a query".
        swallowed = (args.file_gaps not in (None, ALL_GAPS)
                     and not all(GAP_ID.match(i.strip())
                                 for i in args.file_gaps.split(",") if i.strip()))
        if swallowed:
            message = (f"--file-gaps takes gap ids like 'g1,g3'; got "
                       f"{args.file_gaps!r} (put the query before the flag)")
        elif args.query:
            message = "empty query"
        else:
            message = "give a query, or --from-file PATH"
        print(f"error: {message}", file=sys.stderr)
        return EXIT_USAGE
    if args.from_file is not None and args.query.strip():
        print("error: a query and --from-file ask different questions; pass one",
              file=sys.stderr)
        return EXIT_USAGE
    if args.gaps < 0:
        print("error: --gaps must be >= 0", file=sys.stderr)
        return EXIT_USAGE
    repo = open_repo(args.repo)

    try:
        if args.from_file is not None:
            path = check_from_file(repo, args.from_file)
            if args.file_gaps is not None:
                # Not conservatism: a literature note needs prose a person
                # writes, and auto-filing these would mint bodyless notes --
                # the failure capture.py exists to prevent.
                print("error: passage mode is read-only; its suggestions need a body "
                      "you write", file=sys.stderr)
                return EXIT_USAGE
            report = passage_report(repo, path, top=max(1, args.top))
        else:
            report = query(repo, args.query, top=max(1, args.top), gap_cap=args.gaps,
                           include_raw=args.include_raw)
            # `is not None` is what keeps "writes nothing without --file-gaps"
            # literally true: an empty selection string is still a request.
            if args.file_gaps is not None:
                file_gaps(repo, report, args.file_gaps)
    except (ContentRepoError, FrontmatterError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    elif report.get("mode") == "passage":
        print(render_passages(report))
    else:
        print(render(report, str(repo.root), mermaid=args.mermaid))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
