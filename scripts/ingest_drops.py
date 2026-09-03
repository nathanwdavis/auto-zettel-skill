#!/usr/bin/env python3
"""Ingest human-dropped source files into the content repo (amendment A11).

The pipeline could only cite what an agent could fetch, and the sources that
matter most are often the ones it cannot: paywalled papers, JavaScript-only
pages, a PDF the author sent. This is the door for those. A person commits a
file into ``drop/`` (git, the GitHub web UI, or a session); the next cycle
runs this before its planning step and every drop becomes:

  * a capture in ``raw/`` (the file, moved, plus a ``.txt`` text extraction
    when one is possible) -- immutable evidence, exactly like a fetched one;
  * a gate-clean reference note with CSL-JSON, identified from an optional
    sidecar ``<stem>.yml`` (title, author, year, doi, isbn, arxiv, pmid, url,
    source_tier, priority, notes), else from a DOI/arXiv id found in the text,
    enriched from Crossref when a DOI resolves;
  * an INBOX entry telling the run to write the literature and permanent
    notes from that capture -- a human handed it over, so it outranks new
    inquiries.

It is script-driven (called by ``remote_cycle.sh start`` and
``maintenance_run.sh``) rather than prompt-driven, because a Routine's prompt
freezes at creation and this must reach every existing schedule.

Never touches an existing note or anything already in ``raw/``. A drop that
duplicates a reference already on file, or exceeds ``fetch.max_capture_mb``,
is renamed in place (``<stem>.duplicate-of-<key>.pdf``, ``<stem>.too-large.pdf``)
and reported in INBOX rather than ingested twice or silently dropped.

    ingest_drops.py --repo <path> [--list] [--json] [--mailto <email>] [--offline]
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import quote

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_manifest
import capture
import verify_refs
from zettel_lib import citations, http, naming
from zettel_lib.cli import EXIT_OK, EXIT_USAGE, EXIT_VIOLATION, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note, dump
from zettel_lib.repo import ContentRepo, ContentRepoError, dig

DROP_DIR = "drop"
SOURCE_EXTS = (".pdf", ".txt", ".md", ".html", ".htm")
SKIP_NAMES = {".gitkeep", "README.md"}
MARKERS = (".duplicate-of-", ".too-large.")
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>)\]]+)", re.IGNORECASE)
ARXIV_RE = re.compile(r"arxiv:\s*(\d{4}\.\d{4,5}(?:v\d+)?)", re.IGNORECASE)
CROSSREF = "https://api.crossref.org/works/{doi}?mailto={mailto}"
PAGES_TO_READ = 5
DEFAULT_MAX_MB = 25
JOURNAL_TYPES = {"journal-article", "proceedings-article", "book-chapter", "book", "monograph"}


def pending(repo: ContentRepo) -> list[Path]:
    """Source files waiting in drop/, oldest name first. Marked files are skipped."""
    drop = repo.root / DROP_DIR
    if not drop.is_dir():
        return []
    out = []
    for path in sorted(drop.iterdir()):
        if not path.is_file() or path.name in SKIP_NAMES:
            continue
        if path.suffix.lower() not in SOURCE_EXTS:
            continue
        if any(marker in path.name for marker in MARKERS):
            continue
        out.append(path)
    return out


def sidecar_path(path: Path) -> Path:
    return path.with_suffix(".yml")


def read_sidecar(path: Path) -> dict:
    side = sidecar_path(path)
    if not side.exists():
        return {}
    data = yaml.safe_load(side.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ContentRepoError(f"{side.name}: sidecar must be a YAML mapping")
    return data


def extract(path: Path) -> tuple[str, dict, list[str]]:
    """(text, metadata, warnings) for a dropped file; degrades without pypdf."""
    if path.suffix.lower() != ".pdf":
        return path.read_text(encoding="utf-8", errors="replace"), {}, []
    try:
        import pypdf  # noqa: PLC0415 - optional at runtime, required by requirements.txt
    except ImportError:
        return "", {}, [f"{path.name}: pypdf is not installed; no text extraction "
                        "(identity from sidecar/filename only)"]
    try:
        reader = pypdf.PdfReader(str(path))
        pages = [p.extract_text() or "" for p in reader.pages[:PAGES_TO_READ]]
        meta = {}
        info = reader.metadata or {}
        for key, field in (("/Title", "title"), ("/Author", "author")):
            value = str(info.get(key) or "").strip()
            if value:
                meta[field] = value
        return "\n".join(pages), meta, []
    except Exception as exc:  # noqa: BLE001 - any parse failure degrades alike
        return "", {}, [f"{path.name}: could not read PDF ({type(exc).__name__}: {exc})"]


def find_identifiers(text: str, sidecar: dict) -> dict:
    ids = {}
    for field in ("doi", "isbn", "arxiv", "pmid", "url"):
        value = str(sidecar.get(field) or "").strip()
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
    """Sidecar/PDF authors as CSL author objects: 'Family, Given' or 'Given Family'."""
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


def first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if 8 <= len(line) <= 160 and not DOI_RE.search(line):
            return line
    return ""


def build_reference(note_id: str, path: Path, sidecar: dict, extracted_meta: dict,
                    text: str, ids: dict, enriched: dict | None) -> tuple[dict, str]:
    """(frontmatter, title) for the reference note this drop becomes."""
    enriched = enriched or {}
    title = (str(sidecar.get("title") or "").strip() or str(enriched.get("title") or "").strip()
             or extracted_meta.get("title", "") or first_line(text)
             or path.stem.replace("-", " ").replace("_", " ").strip())
    csl: dict = {"id": note_id, "type": str(sidecar.get("type") or enriched.get("type")
                                             or ("book" if ids.get("isbn") else "article-journal")),
                 "title": title}
    authors = authors_from(sidecar.get("author") or sidecar.get("authors"))
    if not authors and enriched.get("author"):
        authors = enriched["author"]
    if not authors and extracted_meta.get("author"):
        authors = authors_from(extracted_meta["author"])
    if authors:
        csl["author"] = authors
    year = sidecar.get("year")
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

    tier = str(sidecar.get("source_tier") or "").strip()
    if not tier:
        tier = ("peer-reviewed" if (ids.get("doi") or enriched.get("type") in JOURNAL_TYPES)
                else "reputable-secondary")
    key = naming.make_key(title, note_id)
    slug, _ = naming.split_key(key)
    today = capture.now_date()
    meta = {
        "id": note_id, "key": key, "slug": slug, "aliases": [note_id],
        "type": "reference", "title": title,
        "tags": [str(t) for t in (sidecar.get("tags") or [])],
        "source_tier": tier, "scripture": False,
        "csl_json": csl,
        "chicago_note": "", "chicago_bib": "", "citation_renderer": "pandoc",
        "verification": {"method": "", "source": "", "verified": False, "date": ""},
        "raw_capture": "",  # filled once the file is in place
        "provenance": {"dropped_as": path.name, "sidecar": bool(sidecar),
                       "ingested": today},
        "links": [],
        "created": today, "updated": today,
    }
    return meta, title


def existing_identities(repo: ContentRepo) -> dict[str, str]:
    """source identity -> reference key, for the duplicate check."""
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


def mark(path: Path, marker: str) -> Path:
    """Rename a drop in place so later runs skip it, keeping the sidecar paired."""
    target = path.with_name(f"{path.stem}{marker}{path.suffix}")
    path.rename(target)
    side = sidecar_path(path)
    if side.exists():
        side.rename(target.with_suffix(".yml"))
    return target


def ingest_one(repo: ContentRepo, path: Path, *, mailto: str, offline: bool,
               transport, max_mb: float, identities: dict[str, str]) -> dict:
    rel = repo.rel(path)
    warnings: list[str] = []
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        marked = mark(path, ".too-large")
        capture.capture_inbox(
            repo, f"Dropped source too large: {path.name}",
            f"{size_mb:.1f} MB exceeds fetch.max_capture_mb ({max_mb:g}); left in drop/ as "
            f"{marked.name}. Shrink it (or raise the cap in config.yml) and drop it again.")
        return {"kind": "too-large", "file": rel, "marked": repo.rel(marked), "warnings": warnings}

    sidecar = read_sidecar(path)
    text, extracted_meta, extract_warnings = extract(path)
    warnings.extend(extract_warnings)
    ids = find_identifiers(text, sidecar)

    enriched = None
    if ids.get("doi") and not offline:
        try:
            enriched = crossref_csl(ids["doi"], mailto=mailto, transport=transport)
            if enriched is None:
                warnings.append(f"{path.name}: DOI {ids['doi']} did not resolve at Crossref; "
                                "using sidecar/extracted metadata")
        except http.NetworkUnavailable as exc:
            warnings.append(f"{path.name}: network unavailable ({exc}); using "
                            "sidecar/extracted metadata")

    note_id = capture.allocate_id(repo)
    meta, title = build_reference(note_id, path, sidecar, extracted_meta, text, ids, enriched)

    identity = citations.source_identity(meta["csl_json"])
    if identity and identity in identities:
        dup = identities[identity]
        marked = mark(path, f".duplicate-of-{dup}")
        capture.capture_inbox(
            repo, f"Dropped source duplicates an existing reference: {path.name}",
            f"Same source ({identity}) as `{dup}`; left in drop/ as {marked.name}. "
            "Delete it, or fix the identifier in its sidecar and drop it again.")
        return {"kind": "duplicate", "file": rel, "duplicate_of": dup,
                "marked": repo.rel(marked), "warnings": warnings}

    # The capture: the file itself, moved (raw/ is additions-only, and drop/
    # is outside it), plus the extraction so agents and query.py can grep it.
    slug = meta["slug"]
    raw_dir = repo.root / "raw"
    raw_dir.mkdir(exist_ok=True)
    capture_path = raw_dir / f"{note_id}-{slug}{path.suffix.lower()}"
    if capture_path.exists():
        raise ContentRepoError(f"refusing to overwrite existing capture {repo.rel(capture_path)}")
    shutil.move(str(path), str(capture_path))
    text_path = None
    if text.strip() and path.suffix.lower() != ".txt":
        text_path = raw_dir / f"{note_id}-{slug}.txt"
        text_path.write_text(
            f"Text extraction of {capture_path.name} (dropped as {path.name}); "
            f"the {path.suffix.lower()[1:]} is the cited capture.\n\n{text}",
            encoding="utf-8")
    side = sidecar_path(path)
    if side.exists():
        side.unlink()
    meta["raw_capture"] = repo.rel(capture_path)

    ref_path = repo.root / "reference" / f"{meta['key']}.md"
    body = (f"Bibliographic record. Dropped by a human as `{path.name}`"
            + (f"; text extraction in `{repo.rel(text_path)}`" if text_path else "")
            + ".\n")
    capture._write(ref_path, meta, body)
    identities[identity or f"note:{meta['key']}"] = meta["key"]

    priority = str(sidecar.get("priority") or "normal")
    notes = str(sidecar.get("notes") or "").strip()
    capture.capture_inbox(
        repo, f"Dropped source ready: {title}",
        f"Reference `{meta['key']}` was created from `{path.name}`; its capture is "
        f"`{meta['raw_capture']}`" + (f" (text: `{repo.rel(text_path)}`)" if text_path else "")
        + f". Priority: {priority}. Write the literature note (own words, with a locator) "
        "and distil permanent notes from it; do not re-fetch the source."
        + (f"\n\nHuman notes: {notes}" if notes else ""))
    repo.append_log(f"ingest_drops: {rel} -> reference/{meta['key']}.md "
                    f"(capture {meta['raw_capture']})")
    return {"kind": "ingested", "file": rel, "key": meta["key"],
            "capture": meta["raw_capture"], "priority": priority, "warnings": warnings}


def ingest(repo: ContentRepo, *, mailto: str = "", offline: bool = False,
           transport=http.requests_transport) -> list[dict]:
    cfg = repo.config()
    max_mb = float(dig(cfg, "fetch.max_capture_mb") or DEFAULT_MAX_MB)
    mailto = mailto or str(dig(cfg, "fetch.mailto") or "")
    identities = existing_identities(repo)
    results = []
    for path in pending(repo):
        results.append(ingest_one(repo, path, mailto=mailto, offline=offline,
                                  transport=transport, max_mb=max_mb, identities=identities))
    ingested = [r for r in results if r["kind"] == "ingested"]
    for r in ingested:
        # Verified on its capture and rendered right away, so the artifact is
        # gate-clean by construction (the capture.py principle) rather than
        # after the run remembers to call verify_refs in step 8.
        note = Note.load(repo.root / "reference" / f"{r['key']}.md")
        result = verify_refs.verify_note(note, repo, offline=True, mailto="")
        ok, method, source = result[0], result[1], result[2]
        note.meta["verification"] = {"method": method, "source": source,
                                     "verified": bool(ok),
                                     "date": verify_refs.now() if ok else ""}
        verify_refs.rerender(note)
        note.save()
    if ingested:
        build_manifest.regenerate(repo)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true",
                        help="print the files waiting in drop/ and change nothing")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--mailto", default="",
                        help="contact email for Crossref (default: config fetch.mailto)")
    parser.add_argument("--offline", action="store_true",
                        help="skip the Crossref enrichment lookup")
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)

    if args.list:
        files = [repo.rel(p) for p in pending(repo)]
        print(json.dumps(files) if args.json else
              ("\n".join(files) if files else "ingest_drops: nothing pending"))
        return EXIT_OK

    try:
        results = ingest(repo, mailto=args.mailto, offline=args.offline)
    except (ContentRepoError, FrontmatterError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        repo.append_log(f"ingest_drops: FAILED {exc}")
        return EXIT_VIOLATION
    for r in results:
        for w in r["warnings"]:
            print(f"warning: {w}", file=sys.stderr)
            repo.append_log(f"ingest_drops: DEGRADED {w}")
    if args.json:
        print(json.dumps(results, indent=2))
    elif not results:
        print("ingest_drops: nothing pending")
    else:
        for r in results:
            if r["kind"] == "ingested":
                print(f"ingested\t{r['file']}\t{r['key']}\t{r['capture']}")
            else:
                print(f"{r['kind']}\t{r['file']}\t{r['marked']}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
