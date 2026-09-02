#!/usr/bin/env python3
"""Citation-grounding gate (FR-11, FR-12, FR-20).

Hard-fails the run (non-zero exit) on:
  * any reference note whose verification.verified is not true (FR-11);
  * any malformed or stale Chicago string (FR-11);
  * a reference note missing the FR-4 fields (source_tier, raw_capture, the
    four verification keys), carrying a source_tier outside the QA-3
    vocabulary, or marked scripture without the primary-text tier (AC-9);
  * two reference notes describing the same source (FR-4: exactly one per source);
  * any permanent-note sourced claim with no link to a verified reference (FR-11, QA-2);
  * any note tagged `contested` grounded in fewer than 3 distinct SOURCES (FR-12) --
    distinct by registry identifier, not by reference-note key, or three
    notes for one DOI would count as independent.

Chicago strings are re-rendered from the note's own CSL-JSON and compared. The
re-render uses the backend recorded in `citation_renderer`; when that backend is
not installed locally the comparison is skipped with a warning rather than
failing, since a different backend would report spurious mismatches (see
references/citation-rules.md).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib import citations
from zettel_lib.cli import EXIT_USAGE, Violation, base_parser, open_repo, report
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import ContentRepo, ContentRepoError

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")
CONTESTED_MIN_SOURCES = 3

# QA-3 tiers, strongest first. Researchers may reach any source to *find* a
# claim; a note grounded only in general web has been discovered but not yet
# verified against a primary source. That is a normal, temporary state -- so it
# warns rather than blocks.
SOURCE_TIERS = ("peer-reviewed", "primary-text", "reputable-secondary", "general-web")
STRONG_TIERS = {"peer-reviewed", "primary-text", "reputable-secondary"}
WEAK_TIER = "general-web"
SCRIPTURE_TIER = "primary-text"

#: The FR-4 reference-note fields a template writes and a hand-written note
#: forgets. Presence is checked; emptiness only where a verified note makes
#: the value load-bearing (see _lint_reference).
REFERENCE_FIELDS = ("source_tier", "raw_capture", "verification")
VERIFICATION_FIELDS = ("method", "source", "verified", "date")

# A permanent note makes a "sourced claim" when it cites, quotes, or attributes.
# "per" only counts as attribution when aimed at a named source ("per Smith",
# "per The Chicago Manual") -- bare "per period"/"per year" is plain English,
# not a citation, and flagging it forces links to references that do not exist.
SOURCED_CLAIM = re.compile(
    r"(\baccording to\b|\bargues\b|\bshows that\b|\bfound that\b|\breports\b"
    r"|\bdemonstrates\b|\bwrites\b|\bconcludes\b|\bper\s+(?=(?-i:[A-Z]))|\bcites\b|“|\")",
    re.IGNORECASE,
)


def lint(repo: ContentRepo) -> tuple[list[Violation], list[str]]:
    violations: list[Violation] = []
    warnings: list[str] = []
    notes: list[Note] = []

    for path in repo.note_paths():
        try:
            notes.append(Note.load(path))
        except FrontmatterError as exc:
            violations.append(Violation(repo.rel(path), "frontmatter", str(exc)))

    by_key = {n.key: n for n in notes if n.key}
    id_to_key = {n.id: n.key for n in notes if n.id and n.key}
    verified_refs = {
        n.key for n in notes
        if n.type == "reference" and (n.meta.get("verification") or {}).get("verified") is True
    }
    available = set(citations.available_backends())

    references = [n for n in notes if n.type == "reference"]
    for note in references:
        violations.extend(_lint_reference(repo, note, available, warnings))
    violations.extend(_lint_duplicate_sources(repo, references))

    for note in (n for n in notes if n.type == "permanent"):
        violations.extend(_lint_permanent(repo, note, by_key, id_to_key, verified_refs))
        warnings.extend(_check_sourcing_strength(repo, note, by_key, id_to_key, verified_refs))

    return violations, warnings


def _identity(note: Note) -> str:
    """What source a reference note describes; its own key when it cannot say."""
    csl = note.meta.get("csl_json")
    return citations.source_identity(csl if isinstance(csl, dict) else {}) or f"note:{note.key}"


def _lint_duplicate_sources(repo, references) -> list[Violation]:
    """FR-4: exactly one reference note per source (both notes are named)."""
    by_identity: dict[str, list[Note]] = {}
    for note in references:
        by_identity.setdefault(_identity(note), []).append(note)
    out = []
    for identity, group in by_identity.items():
        if len(group) < 2:
            continue
        for note in group:
            others = ", ".join(repo.rel(o.path) for o in group if o is not note)
            out.append(Violation(
                repo.rel(note.path), "duplicate-source",
                f"describes the same source ({identity}) as {others}; "
                "FR-4 allows exactly one reference note per source"))
    return out


def _lint_reference(repo, note, available, warnings) -> list[Violation]:
    rel = repo.rel(note.path)
    out: list[Violation] = []

    verification = note.meta.get("verification") or {}
    if not isinstance(verification, dict):
        verification = {}

    # FR-4 field completeness. The template writes every one of these; a note
    # written by hand, or by a model paraphrasing the template, drops them,
    # and a missing raw_capture used to mean "unverifiable" only after the
    # next verify_refs run noticed.
    for field in REFERENCE_FIELDS:
        if field not in note.meta:
            out.append(Violation(rel, "missing-field", f"reference note has no '{field}' field (FR-4)"))
    if "verification" in note.meta:
        for field in VERIFICATION_FIELDS:
            if field not in verification:
                out.append(Violation(rel, "missing-field",
                                     f"verification block has no '{field}' key (FR-4)"))
    if verification.get("verified") is True:
        method = str(verification.get("method") or "")
        if not str(verification.get("date") or "").strip():
            out.append(Violation(rel, "missing-field",
                                 "verification.date is empty for a verified reference"))
        if "raw-capture" in method and not str(note.meta.get("raw_capture") or "").strip():
            out.append(Violation(rel, "missing-field",
                                 "verification.method says raw-capture but raw_capture is empty"))

    tier = str(note.meta.get("source_tier") or "").strip()
    if "source_tier" in note.meta and tier not in SOURCE_TIERS:
        out.append(Violation(
            rel, "bad-source-tier",
            f"source_tier '{tier}' is not one of {'|'.join(SOURCE_TIERS)} (QA-3)"))
    if note.meta.get("scripture") and tier != SCRIPTURE_TIER:
        out.append(Violation(
            rel, "scripture-tier",
            f"scripture: true requires source_tier: {SCRIPTURE_TIER} (AC-9), got '{tier}'"))

    if verification.get("verified") is not True:
        out.append(Violation(
            rel, "unverified-reference",
            "verification.verified is not true; run verify_refs.py or capture the source into raw/"))
    elif not verification.get("method"):
        out.append(Violation(rel, "unverified-reference",
                             "verification.verified is true but no method is recorded"))

    csl = note.meta.get("csl_json")
    for problem in citations.validate_csl(csl if isinstance(csl, dict) else {}):
        out.append(Violation(rel, "malformed-csl", problem))

    note_str = str(note.meta.get("chicago_note") or "").strip()
    bib_str = str(note.meta.get("chicago_bib") or "").strip()
    is_scripture = bool(note.meta.get("scripture"))

    if not note_str:
        out.append(Violation(rel, "malformed-chicago", "chicago_note is empty"))
    if not bib_str and not is_scripture:
        out.append(Violation(rel, "malformed-chicago", "chicago_bib is empty"))
    if bib_str and is_scripture:
        out.append(Violation(
            rel, "scripture-in-bibliography",
            "scripture is cited in-text per SBL and must not carry a chicago_bib entry"))

    # Re-render and compare (FR-11), when we can do so faithfully.
    if isinstance(csl, dict) and note_str and not is_scripture:
        backend = str(note.meta.get("citation_renderer") or "") or None
        if backend and backend not in available:
            warnings.append(
                f"{rel}: citation_renderer '{backend}' unavailable locally; "
                "skipped Chicago string re-render check")
        else:
            try:
                rendered = citations.render(csl, backend=backend)
            except citations.RenderError as exc:
                warnings.append(f"{rel}: could not re-render Chicago strings ({exc})")
            else:
                if _norm(rendered.note) != _norm(note_str):
                    out.append(Violation(
                        rel, "stale-chicago",
                        "chicago_note does not match a re-render of csl_json"))
                if bib_str and _norm(rendered.bib) != _norm(bib_str):
                    out.append(Violation(
                        rel, "stale-chicago",
                        "chicago_bib does not match a re-render of csl_json"))
    return out


def _lint_permanent(repo, note, by_key, id_to_key, verified_refs) -> list[Violation]:
    rel = repo.rel(note.path)
    out: list[Violation] = []

    targets = {str(l.get("target_id", "")) for l in note.links}
    targets |= {m.group(1) for m in WIKILINK.finditer(note.body)}
    resolved = {id_to_key.get(t, t) for t in targets}
    linked_refs = {k for k in resolved if k in by_key and by_key[k].type == "reference"}
    verified_linked = linked_refs & verified_refs

    if SOURCED_CLAIM.search(note.body) and not verified_linked:
        out.append(Violation(
            rel, "uncited-claim",
            "permanent note makes a sourced claim but links to no verified reference note"))

    if "contested" in note.tags:
        sources = {_identity(by_key[k]) for k in verified_linked}
        if len(sources) < CONTESTED_MIN_SOURCES:
            out.append(Violation(
                rel, "contested-undersourced",
                f"note is tagged 'contested' but is grounded in {len(sources)} distinct "
                f"verified source(s) across {len(verified_linked)} reference note(s); "
                f"{CONTESTED_MIN_SOURCES} independent sources required"))
    return out


def _check_sourcing_strength(repo, note, by_key, id_to_key, verified_refs) -> list[str]:
    """Warn when a permanent note rests only on general-web sources (QA-3).

    Not a violation: general web is sometimes genuinely the primary source, and
    a lead found on the open web is exactly how research is meant to start. But
    a note that never reached a stronger tier is a visible backlog item, not a
    finished one.
    """
    targets = {str(l.get("target_id", "")) for l in note.links}
    targets |= {m.group(1) for m in WIKILINK.finditer(note.body)}
    resolved = {id_to_key.get(t, t) for t in targets}
    linked = [by_key[k] for k in resolved
              if k in by_key and by_key[k].type == "reference" and k in verified_refs]
    if not linked:
        return []

    tiers = {str(ref.meta.get("source_tier") or "").strip() for ref in linked}
    if tiers & STRONG_TIERS:
        return []
    if not tiers or tiers == {WEAK_TIER}:
        return [f"{repo.rel(note.path)}: weak-sourcing -- grounded only in "
                f"{WEAK_TIER} sources; verify against a primary or peer-reviewed "
                f"source to finish grounding this claim"]
    return []


def _norm(text: str) -> str:
    """Compare Chicago strings ignoring whitespace and quote-glyph variation."""
    text = re.sub(r"[“”]", '"', text or "")
    text = re.sub(r"[‘’]", "'", text)
    return re.sub(r"\s+", " ", text).strip().rstrip(".")


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)
    try:
        violations, warnings = lint(repo)
    except ContentRepoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return report(violations, repo, "lint_citations")


if __name__ == "__main__":
    raise SystemExit(main())
