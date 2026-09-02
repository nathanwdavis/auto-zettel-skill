#!/usr/bin/env python3
"""Anti-hallucination verification for reference notes (FR-10, FR-22).

A reference is verified by either (a) a raw capture actually present under
raw/, or (b) an authoritative metadata lookup: Crossref for DOIs, arXiv for
arXiv IDs, PubMed for PMIDs, Open Library or Google Books for ISBNs.

Crossref requests always carry the `mailto` parameter, which routes them to the
reserved "polite" pool; 429s are retried with exponential backoff (Crossref
revised its rate limits effective 2025-12-01).

Exits 0 even when some references remain unverified -- it records state, and
lint_citations.py is the gate (FR-22). Network failure degrades gracefully to
raw-capture verification only, logged as a warning (NFR-5).
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib import citations, http
from zettel_lib.cli import EXIT_OK, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import ContentRepo

CROSSREF = "https://api.crossref.org/works/{doi}?mailto={mailto}"
ARXIV = "https://export.arxiv.org/api/query?id_list={arxiv_id}"
PUBMED = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
          "?db=pubmed&retmode=json&id={pmid}")
OPENLIBRARY = "https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
GOOGLEBOOKS = "https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _identifier_lookup(csl: dict, *, mailto: str, transport) -> tuple[str, str] | None:
    """Try the authoritative registries for any identifier ``csl`` carries.

    Returns ``(method, source)`` on a confirmed hit, ``("", "")`` when
    identifiers exist but none confirmed, or ``None`` when there is nothing
    to look up. NetworkUnavailable propagates so callers can degrade (NFR-5).
    """
    saw_identifier = False

    doi = str(csl.get("DOI") or "").strip()
    if doi:
        saw_identifier = True
        url = CROSSREF.format(doi=quote(doi, safe="/"), mailto=quote(mailto))
        data = http.get_json(url, transport=transport)
        if data and (data.get("message") or {}).get("DOI"):
            return "crossref", f"https://doi.org/{doi}"

    arxiv_id = citations.arxiv_id(csl)
    if arxiv_id:
        saw_identifier = True
        url = ARXIV.format(arxiv_id=quote(arxiv_id))
        resp = _raw(url, transport)
        if resp and "<entry>" in resp and "<title>" in resp:
            return "arxiv", f"https://arxiv.org/abs/{arxiv_id}"

    pmid = str(csl.get("PMID") or "").strip()
    if pmid:
        saw_identifier = True
        data = http.get_json(PUBMED.format(pmid=quote(pmid)), transport=transport)
        result = (data or {}).get("result") or {}
        if pmid in result:
            return "pubmed", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

    isbn = str(csl.get("ISBN") or "").replace("-", "").strip()
    if isbn:
        saw_identifier = True
        data = http.get_json(OPENLIBRARY.format(isbn=quote(isbn)), transport=transport)
        if data and f"ISBN:{isbn}" in data:
            return "openlibrary", f"https://openlibrary.org/isbn/{isbn}"
        data = http.get_json(GOOGLEBOOKS.format(isbn=quote(isbn)), transport=transport)
        if data and int(data.get("totalItems") or 0) > 0:
            return "googlebooks", f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"

    return ("", "") if saw_identifier else None


def verify_note(
    note: Note,
    repo: ContentRepo,
    *,
    offline: bool,
    mailto: str,
    transport=http.requests_transport,
) -> tuple[bool, str, str, str]:
    """Return ``(verified, method, source, identifier_check)`` for one note.

    A raw capture verifies on its own, but it used to also END the check, so
    a wrong or rotted DOI on a captured source was never caught (issue #7).
    Now, when both a capture and an identifier are present and the network is
    up, the identifier is checked too: a hit upgrades the method to
    ``raw-capture+<registry>``, a definitive miss keeps the capture-based
    verification (the documented either/or) but records
    ``identifier_check: failed`` so the rot is visible instead of silent.
    """
    capture = str(note.meta.get("raw_capture") or "").strip()
    csl = note.meta.get("csl_json") or {}
    if not isinstance(csl, dict):
        csl = {}

    capture_ok = False
    if capture:
        path = repo.root / capture
        capture_ok = path.exists() and path.stat().st_size > 0

    if capture_ok:
        if offline:
            return True, "raw-capture", capture, ""
        hit = _identifier_lookup(csl, mailto=mailto, transport=transport)
        if hit is None:
            return True, "raw-capture", capture, ""
        method, source = hit
        if method:
            return True, f"raw-capture+{method}", source, "confirmed"
        return True, "raw-capture", capture, "failed"

    if offline:
        return False, "", "", ""

    hit = _identifier_lookup(csl, mailto=mailto, transport=transport)
    if hit and hit[0]:
        return True, hit[0], hit[1], ""
    return False, "", "", ""


def _raw(url: str, transport) -> str | None:
    try:
        resp = transport(url, {"User-Agent": "zettel-bootstrap/0.1"})
    except http.NetworkUnavailable:
        return None
    return resp.body if resp.status == 200 else None


def rerender(note: Note) -> bool:
    """Refresh chicago_note/chicago_bib from csl_json. Returns True on change."""
    csl = note.meta.get("csl_json")
    if not isinstance(csl, dict) or note.meta.get("scripture"):
        return False
    try:
        rendered = citations.render(csl)
    except citations.RenderError as exc:
        print(f"warning: {note.path.name}: {exc}", file=sys.stderr)
        return False
    changed = (note.meta.get("chicago_note") != rendered.note
               or note.meta.get("chicago_bib") != rendered.bib
               or note.meta.get("citation_renderer") != rendered.backend)
    note.meta["chicago_note"] = rendered.note
    note.meta["chicago_bib"] = rendered.bib
    note.meta["citation_renderer"] = rendered.backend
    return changed


def run(repo: ContentRepo, *, offline: bool, mailto: str, transport=http.requests_transport,
        render: bool = True) -> tuple[int, int]:
    verified = total = 0
    degraded = False

    for note in repo.notes(types=["reference"]):
        total += 1
        try:
            ok, method, source, id_check = verify_note(
                note, repo, offline=offline, mailto=mailto, transport=transport)
        except http.NetworkUnavailable as exc:
            if not degraded:
                print(f"warning: network unavailable ({exc}); "
                      "degrading to raw-capture verification only", file=sys.stderr)
                repo.append_log("verify_refs: WARNING network unavailable, raw-capture only")
                degraded = True
            ok, method, source, id_check = verify_note(
                note, repo, offline=True, mailto=mailto, transport=transport)

        old = dict(note.meta.get("verification") or {})
        new = {
            "method": method,
            "source": source,
            "verified": bool(ok),
        }
        if id_check:
            new["identifier_check"] = id_check

        # Only write when the verification STATE changed; a re-check that
        # found the same state keeps the old date. Unconditional saves turned
        # every cycle into a diff on every reference note and made `updated`
        # stop meaning "last authored edit" (issue #7). `verification.date`
        # is when this state was established, not when it was last re-checked.
        state_changed = {k: old.get(k) for k in new} != new
        if state_changed:
            new["date"] = now() if ok else ""
        else:
            new["date"] = old.get("date", "")
        note.meta["verification"] = new

        rendered_changed = rerender(note) if render else False
        if state_changed or rendered_changed:
            note.save()

        if id_check == "failed":
            print(f"warning: {note.path.name}: raw capture verifies, but its "
                  "identifier did not resolve at any registry -- check the "
                  "DOI/ISBN for rot", file=sys.stderr)

        verified += int(ok)
        status = f"verified via {method}" if ok else "UNVERIFIED"
        print(f"{repo.rel(note.path)}\t{status}")

    return verified, total


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("--offline", action="store_true",
                        help="skip all network lookups; verify from raw/ captures only")
    parser.add_argument("--mailto", default="",
                        help="contact email sent to Crossref for polite-pool routing")
    parser.add_argument("--no-render", action="store_true",
                        help="do not refresh chicago_note/chicago_bib from csl_json")
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)

    if not args.offline and not args.mailto:
        print("warning: no --mailto given; Crossref requests will use the public pool",
              file=sys.stderr)

    try:
        verified, total = run(repo, offline=args.offline, mailto=args.mailto,
                              render=not args.no_render)
    except FrontmatterError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_OK  # state-recording tool: lint_citations is the gate
    print(f"verify_refs: {verified}/{total} reference(s) verified")
    repo.append_log(f"verify_refs: {verified}/{total} verified")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
