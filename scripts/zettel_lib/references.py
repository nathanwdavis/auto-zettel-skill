"""Building reference notes from whatever identity a source can be given.

Two entry points need to mint a reference note and they must produce the same
artifact: ``ingest_drops.py`` (a human handed the pipeline a file) and
``capture.py reference`` (a session or a researcher knows the identifiers but
has not fetched the source yet). Before this module the builder lived inside
``ingest_drops`` and the second caller did not exist -- the researcher agent
hand-wrote reference frontmatter from ``templates/reference.md``, which is
exactly the failure mode ``capture.py`` was created to remove: the gates
demand exact frontmatter, and a hand-written note fails the manifest build for
whoever runs next rather than for its author.

So the builder lives here, alone, and both callers pass the same shaped
``fields`` mapping (a drop's sidecar YAML and capture's CLI flags carry the
same keys by design: title, author, year, type, doi, isbn, arxiv, pmid, url,
source_tier, tags). Identity is whatever can be established -- a registry
identifier, then Crossref enrichment, then the text, then the filename -- and
what cannot be established honestly stays empty for a gate to catch.

``apply_verification`` lives here too because both callers must write the
verification block the same way, and ``verify_refs`` owns deciding what is
true; a second writer that shaped the block differently would drift from what
``lint_citations`` reads.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from urllib.parse import quote

from . import citations, http, naming
from .frontmatter import FrontmatterError, Note
from .repo import ContentRepo, ContentRepoError

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>)\]]+)", re.IGNORECASE)
ARXIV_RE = re.compile(r"arxiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
CROSSREF = "https://api.crossref.org/works/{doi}?mailto={mailto}"
JOURNAL_TYPES = {"journal-article", "proceedings-article", "book-chapter", "book", "monograph"}

#: The identity fields a caller may supply, in the order a reference note
#: records them. Shared by the drop sidecar and capture.py's flags so the two
#: input routes cannot describe a source differently.
IDENTIFIER_FIELDS = ("doi", "isbn", "arxiv", "pmid", "url")

#: Page markers in a capture's text extraction. Written by ingest_drops so a
#: literature note can cite `p. N` without reopening the PDF, and read back by
#: query.py's passage mode -- one definition, because a marker the reader does
#: not recognise is a locator silently lost.
PAGE_MARKER = "--- page {n} ---"
PAGE_MARKER_RE = re.compile(r"^--- page (\d+) ---$", re.MULTILINE)


def now_date() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def find_identifiers(text: str, fields: dict) -> dict:
    """Registry identifiers from explicit fields, falling back to the text.

    Explicit always wins: a human (or a researcher agent) naming the DOI is
    more reliable than a regex over a PDF, where the first DOI on the page may
    belong to a cited work rather than to the source itself.
    """
    ids = {}
    for field in IDENTIFIER_FIELDS:
        value = str(fields.get(field) or "").strip()
        if value:
            ids[field] = value
    if "doi" not in ids:
        m = DOI_RE.search(text)
        if m:
            ids["doi"] = m.group(1).rstrip(".,;")
    if "arxiv" not in ids:
        m = ARXIV_RE.search(text)
        if m:
            ids["arxiv"] = m.group(1)
    return ids


def crossref_csl(doi: str, *, mailto: str, transport) -> dict | None:
    """The CSL-shaped Crossref record for a DOI, or None on a miss.

    Crossref's ``message`` already uses CSL-JSON field names, so this is a
    projection onto the fields a reference note carries, not a translation.
    NetworkUnavailable propagates so the caller can degrade (NFR-5).
    """
    data = http.get_json(CROSSREF.format(doi=quote(doi, safe="/"), mailto=quote(mailto)),
                         transport=transport)
    msg = (data or {}).get("message") or {}
    if not msg.get("DOI"):
        return None
    out = {"DOI": msg["DOI"], "type": str(msg.get("type") or "article-journal")}
    titles = msg.get("title") or []
    if titles:
        out["title"] = str(titles[0])
    if isinstance(msg.get("author"), list):
        out["author"] = [{k: a[k] for k in ("family", "given") if k in a}
                         for a in msg["author"] if isinstance(a, dict)]
    for field in ("issued", "container-title", "publisher", "volume", "issue", "page", "URL"):
        value = msg.get(field)
        if isinstance(value, list):
            value = value[0] if value else None
        if value:
            out[field] = value
    return out


def authors_from(value) -> list[dict]:
    """Sidecar/PDF/CLI authors as CSL author objects: 'Family, Given' or 'Given Family'."""
    names = value if isinstance(value, list) else [n.strip() for n in str(value or "").split(";") if n.strip()]
    out = []
    for name in names:
        if isinstance(name, dict):
            out.append({k: str(v) for k, v in name.items() if k in ("family", "given", "literal")})
            continue
        name = str(name).strip()
        if not name:
            continue
        if "," in name:
            family, given = [part.strip() for part in name.split(",", 1)]
        elif " " in name:
            given, family = name.rsplit(" ", 1)
        else:
            family, given = name, ""
        out.append({"family": family, "given": given} if given else {"family": family})
    return out


def tags_from(value) -> list[str]:
    """Sidecar/CLI tags as a list, from a list or a scalar string.

    A scalar is the trap: ``tags: notes`` in a sidecar is the natural way to
    write one tag, and iterating the string yields ``["n","o","t","e","s"]`` --
    five one-character tags that then spread silently through the manifest and
    the tag ontology. Splitting on commas matches ``capture.py --tags``, so the
    two input routes agree on what a tag list looks like.
    """
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def first_line(text: str) -> str:
    """The first line that could plausibly be a title.

    Page markers are skipped explicitly: ``--- page 1 ---`` is 14 characters
    and so falls inside the length window, which would make every untitled
    multi-page drop a reference note called "--- page 1 ---".
    """
    for line in text.splitlines():
        line = line.strip()
        if not line or PAGE_MARKER_RE.match(line):
            continue
        if 8 <= len(line) <= 160 and not DOI_RE.search(line):
            return line
    return ""


def build_reference(note_id: str, fields: dict, extracted_meta: dict, text: str,
                    ids: dict, enriched: dict | None, *, fallback_title: str = "",
                    provenance: dict | None = None) -> tuple[dict, str]:
    """(frontmatter, title) for a reference note.

    ``fields`` is the caller's explicit identity (a drop's sidecar, or
    capture.py's flags); ``extracted_meta`` is what a PDF's own metadata said;
    ``enriched`` is the Crossref record when a DOI resolved. Precedence runs
    from most to least authoritative in exactly that order, with
    ``fallback_title`` (a filename, usually) as the last resort so a key can
    always be formed.

    The Chicago strings are left empty here and rendered by the caller through
    ``verify_refs.rerender``; they are derived artifacts and must come from the
    one renderer that records which backend produced them.
    """
    enriched = enriched or {}
    title = (str(fields.get("title") or "").strip() or str(enriched.get("title") or "").strip()
             or extracted_meta.get("title", "") or first_line(text)
             or fallback_title.strip())
    csl: dict = {"id": note_id, "type": str(fields.get("type") or enriched.get("type")
                                            or ("book" if ids.get("isbn") else "article-journal")),
                 "title": title}
    authors = authors_from(fields.get("author") or fields.get("authors"))
    if not authors and enriched.get("author"):
        authors = enriched["author"]
    if not authors and extracted_meta.get("author"):
        authors = authors_from(extracted_meta["author"])
    if authors:
        csl["author"] = authors
    year = fields.get("year")
    if year:
        csl["issued"] = {"date-parts": [[int(year)]]}
    elif enriched.get("issued"):
        csl["issued"] = enriched["issued"]
    for field in ("container-title", "publisher", "volume", "issue", "page", "URL"):
        if enriched.get(field):
            csl[field] = enriched[field]
    if ids.get("doi"):
        csl["DOI"] = ids["doi"]
    if ids.get("isbn"):
        csl["ISBN"] = ids["isbn"]
    if ids.get("arxiv"):
        csl["arxiv"] = ids["arxiv"]
    if ids.get("pmid"):
        csl["PMID"] = ids["pmid"]
    if ids.get("url"):
        csl["URL"] = ids["url"]

    tier = str(fields.get("source_tier") or "").strip()
    if not tier:
        tier = ("peer-reviewed" if (ids.get("doi") or enriched.get("type") in JOURNAL_TYPES)
                else "reputable-secondary")
    key = naming.make_key(title, note_id)
    slug, _ = naming.split_key(key)
    today = now_date()
    meta = {
        "id": note_id, "key": key, "slug": slug, "aliases": [note_id],
        "type": "reference", "title": title,
        "tags": tags_from(fields.get("tags")),
        "source_tier": tier, "scripture": False,
        "csl_json": csl,
        "chicago_note": "", "chicago_bib": "", "citation_renderer": "pandoc",
        "verification": {"method": "", "source": "", "verified": False, "date": ""},
        "raw_capture": "",  # filled once a capture exists
        "provenance": dict(provenance or {}),
        "links": [],
        "created": today, "updated": today,
    }
    return meta, title


def identities(repo: ContentRepo) -> dict[str, str]:
    """source identity -> reference key, for the FR-4 duplicate check.

    A note whose frontmatter will not parse is skipped rather than raising:
    the duplicate check is not the gate for malformed notes, ``lint_citations``
    is, and refusing to mint any reference because an unrelated one is broken
    would be the wrong failure.
    """
    out = {}
    for path in repo.note_paths(types=["reference"]):
        try:
            note = Note.load(path)
        except FrontmatterError:
            continue
        csl = note.meta.get("csl_json")
        identity = citations.source_identity(csl if isinstance(csl, dict) else {})
        if identity:
            out[identity] = note.key
    return out


def find_reference(repo: ContentRepo, ref: str) -> Note:
    """The reference note named by a key or a bare timestamp id.

    Raises ContentRepoError, which every entry point already reports as a
    usage error -- a caller naming a note that is not there mistyped it or has
    not created it yet, and neither is a crash.
    """
    ref = ref.strip()
    for path in repo.note_paths(types=["reference"]):
        if path.stem == ref or (naming.is_id(ref) and path.stem.endswith(f"--{ref}")):
            return Note.load(path)
    raise ContentRepoError(f"no reference note matches {ref!r}")


def apply_verification(note: Note, result, *, when: str) -> None:
    """Write ``verify_refs``'s finding into a note's verification block.

    One writer, because ``lint_citations`` reads these four keys and a second
    caller shaping them differently would pass its own gate and fail the real
    one. ``when`` is the timestamp to record for a successful check; the caller
    supplies it (``verify_refs.now()``) so this module needs no clock.
    """
    block = {
        "method": result.method,
        "source": result.source,
        "verified": bool(result.verified),
        "date": when if result.verified else "",
    }
    if getattr(result, "identifier_check", ""):
        block["identifier_check"] = result.identifier_check
    if getattr(result, "open_access", ""):
        block["open_access"] = result.open_access
    note.meta["verification"] = block


def paginate(pages: list[str]) -> str:
    """Join extracted pages with the markers a locator is read back from."""
    return "\n\n".join(f"{PAGE_MARKER.format(n=i)}\n{text}"
                       for i, text in enumerate(pages, start=1))


def head_text(text: str, pages: int) -> str:
    """The first ``pages`` marked pages of an extraction, for identity search.

    A DOI late in a paper is almost always a *cited* work's DOI; the source's
    own identifier is on its first pages. Without markers (a .txt or .md drop)
    the whole text is the head, which is the pre-pagination behaviour.
    """
    marks = list(PAGE_MARKER_RE.finditer(text))
    if len(marks) <= pages:
        return text
    return text[: marks[pages].start()]
