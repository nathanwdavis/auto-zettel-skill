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


def verify_note(
    note: Note,
    repo: ContentRepo,
    *,
    offline: bool,
    mailto: str,
    transport=http.requests_transport,
) -> tuple[bool, str, str]:
    """Return ``(verified, method, source)`` for one reference note."""
    capture = str(note.meta.get("raw_capture") or "").strip()
    if capture:
        path = repo.root / capture
        if path.exists() and path.stat().st_size > 0:
            return True, "raw-capture", capture

    if offline:
        return False, "", ""

    csl = note.meta.get("csl_json") or {}
    if not isinstance(csl, dict):
        return False, "", ""

    doi = str(csl.get("DOI") or "").strip()
    if doi:
        url = CROSSREF.format(doi=quote(doi, safe="/"), mailto=quote(mailto))
        data = http.get_json(url, transport=transport)
        if data and (data.get("message") or {}).get("DOI"):
            return True, "crossref", f"https://doi.org/{doi}"

    arxiv_id = _arxiv_id(csl)
    if arxiv_id:
        url = ARXIV.format(arxiv_id=quote(arxiv_id))
        resp = _raw(url, transport)
        if resp and "<entry>" in resp and "<title>" in resp:
            return True, "arxiv", f"https://arxiv.org/abs/{arxiv_id}"

    pmid = str(csl.get("PMID") or "").strip()
    if pmid:
        data = http.get_json(PUBMED.format(pmid=quote(pmid)), transport=transport)
        result = (data or {}).get("result") or {}
        if pmid in result:
            return True, "pubmed", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"

    isbn = str(csl.get("ISBN") or "").replace("-", "").strip()
    if isbn:
        data = http.get_json(OPENLIBRARY.format(isbn=quote(isbn)), transport=transport)
        if data and f"ISBN:{isbn}" in data:
            return True, "openlibrary", f"https://openlibrary.org/isbn/{isbn}"
        data = http.get_json(GOOGLEBOOKS.format(isbn=quote(isbn)), transport=transport)
        if data and int(data.get("totalItems") or 0) > 0:
            return True, "googlebooks", f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"

    return False, "", ""


def _arxiv_id(csl: dict) -> str:
    for field in ("arxiv", "arXiv", "number"):
        value = str(csl.get(field) or "").strip()
        if value:
            return value.replace("arXiv:", "")
    url = str(csl.get("URL") or "")
    if "arxiv.org/abs/" in url:
        return url.rsplit("/", 1)[-1]
    return ""


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
            ok, method, source = verify_note(
                note, repo, offline=offline, mailto=mailto, transport=transport)
        except http.NetworkUnavailable as exc:
            if not degraded:
                print(f"warning: network unavailable ({exc}); "
                      "degrading to raw-capture verification only", file=sys.stderr)
                repo.append_log("verify_refs: WARNING network unavailable, raw-capture only")
                degraded = True
            ok, method, source = verify_note(
                note, repo, offline=True, mailto=mailto, transport=transport)

        note.meta["verification"] = {
            "method": method,
            "source": source,
            "verified": bool(ok),
            "date": now() if ok else "",
        }
        if render:
            rerender(note)
        note.save()
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
