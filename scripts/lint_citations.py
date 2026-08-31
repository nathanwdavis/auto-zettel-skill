#!/usr/bin/env python3
"""Citation-grounding gate (FR-11, FR-12, FR-20).

Hard-fails the run (non-zero exit) on:
  * any reference note whose verification.verified is not true (FR-11);
  * any malformed or stale Chicago string (FR-11);
  * any permanent-note sourced claim with no link to a verified reference (FR-11, QA-2);
  * any note tagged `contested` with fewer than 3 distinct reference links (FR-12).

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
STRONG_TIERS = {"peer-reviewed", "primary-text", "reputable-secondary"}
WEAK_TIER = "general-web"

# A permanent note makes a "sourced claim" when it cites, quotes, or attributes.
SOURCED_CLAIM = re.compile(
    r"(\baccording to\b|\bargues\b|\bshows that\b|\bfound that\b|\breports\b"
    r"|\bdemonstrates\b|\bwrites\b|\bconcludes\b|\bper\b\s|\bcites\b|“|\")",
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

    for note in (n for n in notes if n.type == "reference"):
        violations.extend(_lint_reference(repo, note, available, warnings))

    for note in (n for n in notes if n.type == "permanent"):
        violations.extend(_lint_permanent(repo, note, by_key, id_to_key, verified_refs))
        warnings.extend(_check_sourcing_strength(repo, note, by_key, id_to_key, verified_refs))

    return violations, warnings


def _lint_reference(repo, note, available, warnings) -> list[Violation]:
    rel = repo.rel(note.path)
    out: list[Violation] = []

    verification = note.meta.get("verification") or {}
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

    if "contested" in note.tags and len(verified_linked) < CONTESTED_MIN_SOURCES:
        out.append(Violation(
            rel, "contested-undersourced",
            f"note is tagged 'contested' but links to {len(verified_linked)} verified "
            f"reference(s); {CONTESTED_MIN_SOURCES} independent sources required"))
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
