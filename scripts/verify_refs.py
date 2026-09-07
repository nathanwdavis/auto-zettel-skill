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

Open access (amendment A11): a DOI is also resolved through Unpaywall and
OpenAlex, and the legal free copy's URL is recorded as
``verification.open_access``. The researcher fetches that instead of failing
on a publisher page; nothing is downloaded here, because this tool records
state and never writes outside a note's frontmatter.
"""

from __future__ import annotations

import datetime as _dt
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib import citations, http
from zettel_lib.cli import EXIT_OK, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import ContentRepo, dig

CROSSREF = "https://api.crossref.org/works/{doi}?mailto={mailto}"
UNPAYWALL = "https://api.unpaywall.org/v2/{doi}?email={mailto}"
OPENALEX = "https://api.openalex.org/works/https://doi.org/{doi}?mailto={mailto}"
ARXIV = "https://export.arxiv.org/api/query?id_list={arxiv_id}"
PUBMED = ("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
          "?db=pubmed&retmode=json&id={pmid}")
# `/api/books?jscmd=data` was the endpoint here until it began answering
# `200 {}` for books that are plainly on Open Library -- `search.json` returns
# numFound 1 for the same ISBNs. That silent change marked every ISBN-verified
# reference in a live repository as rotted, on every run, for four cycles.
# search.json also answers definitively: numFound 0 means "not in the index",
# which is a fact, where an empty body is only an absence of one.
OPENLIBRARY = "https://openlibrary.org/search.json?isbn={isbn}"
GOOGLEBOOKS = "https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"


def now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Lookup:
    """What the registries said about a note's identifiers.

    Three outcomes, not two, and the third is the whole point. ``method`` set
    is a hit. ``method`` empty with ``conclusive`` true is a registry saying
    "no such identifier" -- real rot, and it must stay visible. ``method``
    empty with ``conclusive`` FALSE is a registry that could not be read, which
    is not evidence of anything and must never overwrite a finding that was
    established when the registry could.
    """

    method: str = ""
    source: str = ""
    saw_identifier: bool = False
    conclusive: bool = True


def _identifier_lookup(csl: dict, *, mailto: str, transport) -> Lookup:
    """Try the authoritative registries for any identifier ``csl`` carries.

    A registry that fails to answer makes the WHOLE lookup inconclusive, even
    if a later one answers negatively: on partial information the safe move is
    to change nothing. NetworkUnavailable propagates so callers degrade (NFR-5).
    """
    saw_identifier = False
    unanswered = False

    def answered(result: http.JsonResult) -> object | None:
        nonlocal unanswered
        if not result.conclusive:
            unanswered = True
        return result.data

    doi = str(csl.get("DOI") or "").strip()
    if doi:
        saw_identifier = True
        url = CROSSREF.format(doi=quote(doi, safe="/"), mailto=quote(mailto))
        data = answered(http.get_json_result(url, transport=transport))
        if data and (data.get("message") or {}).get("DOI"):
            return Lookup("crossref", f"https://doi.org/{doi}", True)

    arxiv_id = citations.arxiv_id(csl)
    if arxiv_id:
        saw_identifier = True
        url = ARXIV.format(arxiv_id=quote(arxiv_id))
        resp = _raw(url, transport)
        if resp is None:
            unanswered = True
        elif "<entry>" in resp and "<title>" in resp:
            return Lookup("arxiv", f"https://arxiv.org/abs/{arxiv_id}", True)

    pmid = str(csl.get("PMID") or "").strip()
    if pmid:
        saw_identifier = True
        data = answered(http.get_json_result(PUBMED.format(pmid=quote(pmid)),
                                             transport=transport))
        if pmid in ((data or {}).get("result") or {}):
            return Lookup("pubmed", f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", True)

    isbn = str(csl.get("ISBN") or "").replace("-", "").strip()
    if isbn:
        saw_identifier = True
        data = answered(http.get_json_result(OPENLIBRARY.format(isbn=quote(isbn)),
                                             transport=transport))
        # An answer without numFound is not a negative one -- it is the shape
        # the endpoint stopped returning, and the reason this is a tristate.
        found = (data or {}).get("numFound")
        if found is None:
            unanswered = True
        elif int(found) > 0:
            return Lookup("openlibrary", f"https://openlibrary.org/isbn/{isbn}", True)
        data = answered(http.get_json_result(GOOGLEBOOKS.format(isbn=quote(isbn)),
                                             transport=transport))
        if data and int(data.get("totalItems") or 0) > 0:
            return Lookup("googlebooks",
                          f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}", True)

    return Lookup("", "", saw_identifier, conclusive=not unanswered)


def _open_access_lookup(doi: str, *, mailto: str, transport) -> str:
    """The URL of a legal open-access copy for a DOI, or "" (A11).

    Unpaywall first (it requires a contact email and is skipped without one),
    then OpenAlex, which needs none. Both index only legitimately open copies
    -- author-sharing sites are deliberately absent -- so a URL here is one
    the researcher may capture. NetworkUnavailable propagates so the caller
    degrades (the arXiv lesson: swallowing it turned a dead network into a
    definitive miss).
    """
    if mailto:
        data = http.get_json(UNPAYWALL.format(doi=quote(doi, safe="/"), mailto=quote(mailto)),
                             transport=transport)
        best = (data or {}).get("best_oa_location") or {}
        url = str(best.get("url_for_pdf") or best.get("url") or "").strip()
        if url:
            return url
    data = http.get_json(OPENALEX.format(doi=quote(doi, safe="/"), mailto=quote(mailto)),
                         transport=transport)
    best = (data or {}).get("best_oa_location") or {}
    url = str(best.get("pdf_url") or best.get("landing_page_url") or
              ((data or {}).get("open_access") or {}).get("oa_url") or "").strip()
    return url


@dataclass(frozen=True)
class Verification:
    """What one verify_note call established (A8 semantics, A11 open access)."""

    verified: bool
    method: str
    source: str
    identifier_check: str = ""
    open_access: str = ""


def verify_note(
    note: Note,
    repo: ContentRepo,
    *,
    offline: bool,
    mailto: str,
    transport=http.requests_transport,
) -> Verification:
    """Establish ``Verification`` for one note.

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
    prior = note.meta.get("verification") or {}
    if not isinstance(prior, dict):
        prior = {}

    def keep_prior() -> Verification:
        """The finding already on file, when this run learned nothing better.

        A record says an identifier resolved at a named registry on a named
        date. A registry that cannot be read today does not refute that, and
        replacing it with a weaker record destroys evidence -- unattended, on a
        schedule, in a repository whose whole point is that claims are
        traceable.
        """
        return Verification(True, str(prior.get("method") or "raw-capture"),
                            str(prior.get("source") or capture or ""),
                            str(prior.get("identifier_check") or ""))

    capture_ok = False
    if capture:
        path = repo.root / capture
        capture_ok = path.exists() and path.stat().st_size > 0

    if capture_ok:
        if offline:
            # Offline says nothing about identifiers either way, so whatever
            # was established when the network was up still stands.
            return keep_prior()
        found = _identifier_lookup(csl, mailto=mailto, transport=transport)
        if not found.saw_identifier:
            return Verification(True, "raw-capture", capture)
        if found.method:
            return Verification(True, f"raw-capture+{found.method}", found.source,
                                "confirmed")
        if not found.conclusive:
            return keep_prior()
        # A registry actually said "no such identifier": that is rot, and it
        # must be visible. The capture is still the documented either/or basis,
        # so verification itself holds.
        return Verification(True, "raw-capture", capture, "failed")

    if offline:
        # Deliberately NOT the keep_prior() rule that governs an inconclusive
        # network check (A14). The merge gate runs offline precisely so it can
        # never pass on a lucky live lookup: to reach `main`, a reference must
        # be backed by evidence inside the repository, not by a registry that
        # answered once. A registry-only note is honestly unverified here, and
        # `capture.py reference` now says so at the point it writes one.
        return Verification(False, "", "")

    # No capture yet: besides verifying the identifier, find where a legal
    # free copy lives so the researcher can capture that (A11).
    doi = str(csl.get("DOI") or "").strip()
    open_access = ""
    if doi:
        try:
            open_access = _open_access_lookup(doi, mailto=mailto, transport=transport)
        except http.NetworkUnavailable:
            # Enrichment, not verification: an unreachable OA registry must not
            # block a Crossref check that still works. A dead network still
            # surfaces below, from the identifier lookup itself.
            open_access = ""
    found = _identifier_lookup(csl, mailto=mailto, transport=transport)
    if found.method:
        return Verification(True, found.method, found.source, "", open_access)
    if not found.conclusive and prior.get("verified") is True:
        # Same rule with no capture to fall back on: an unreadable registry is
        # not grounds for un-verifying a note that was verified before.
        return Verification(True, str(prior.get("method") or ""),
                            str(prior.get("source") or ""),
                            str(prior.get("identifier_check") or ""), open_access)
    return Verification(False, "", "", "", open_access)


def _raw(url: str, transport) -> str | None:
    """Fetch a non-JSON registry page. NetworkUnavailable propagates, like the
    JSON lookups: swallowing it here made a dead network on an arXiv-only
    reference read as a definitive miss (and, with a capture present, as a
    rotted identifier) instead of degrading to capture-only (NFR-5)."""
    resp = transport(url, {"User-Agent": "zettel-bootstrap/0.1"})
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

    for path in repo.note_paths(types=["reference"]):
        total += 1
        try:
            note = Note.load(path)
        except FrontmatterError as exc:
            # One unparseable note used to stop the whole run (exit 0, with
            # every later note silently unprocessed). Report it and go on;
            # lint_citations fails the note itself.
            print(f"warning: {exc}; skipping", file=sys.stderr)
            print(f"{repo.rel(path)}\tSKIPPED (malformed frontmatter)")
            continue
        try:
            result = verify_note(
                note, repo, offline=offline, mailto=mailto, transport=transport)
        except http.NetworkUnavailable as exc:
            if not degraded:
                print(f"warning: network unavailable ({exc}); "
                      "degrading to raw-capture verification only", file=sys.stderr)
                repo.append_log("verify_refs: WARNING network unavailable, raw-capture only")
                degraded = True
            result = verify_note(
                note, repo, offline=True, mailto=mailto, transport=transport)
        ok, method, source, id_check = (result.verified, result.method,
                                        result.source, result.identifier_check)

        old = dict(note.meta.get("verification") or {})
        # Built FROM the old block, not in place of it. Assigning a freshly
        # built dict dropped every key this run did not happen to produce --
        # one offline run stripped identifier_check from 22 reference notes in
        # a live repository and the cycle committed it before anyone noticed.
        new = dict(old)
        new.update({
            "method": method,
            "source": source,
            "verified": bool(ok),
        })
        if id_check:
            new["identifier_check"] = id_check
        # An open-access URL found earlier stays recorded until a capture
        # exists (an offline re-check must not erase it); a fresh one wins.
        open_access = result.open_access or (str(old.get("open_access") or "")
                                             if not ok or "raw-capture" not in method else "")
        if open_access:
            new["open_access"] = open_access

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
        # `date` records when THIS state was established. A re-check that found
        # the same state keeps it, so `updated` keeps meaning "last authored
        # edit" (issue #7).
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

    if not args.mailto:
        # config.yml's fetch.mailto is the standing contact address (A11);
        # the flag still wins when a caller has a reason to differ.
        try:
            args.mailto = str(dig(repo.config(), "fetch.mailto") or "")
        except Exception:  # noqa: BLE001 - a broken config is the gates' problem, not ours
            args.mailto = ""
    if not args.offline and not args.mailto:
        print("warning: no --mailto given and config fetch.mailto is empty; Crossref "
              "uses the public pool and Unpaywall is skipped", file=sys.stderr)

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
