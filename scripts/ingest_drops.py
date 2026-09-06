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
import shutil
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_manifest
import capture
import verify_refs
from zettel_lib import citations, http, references
from zettel_lib.cli import EXIT_OK, EXIT_USAGE, EXIT_VIOLATION, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import ContentRepo, ContentRepoError, dig, max_capture_mb

DROP_DIR = "drop"
SOURCE_EXTS = (".pdf", ".txt", ".md", ".html", ".htm")
SKIP_NAMES = {".gitkeep", "README.md"}
MARKERS = (".duplicate-of-", ".too-large.")
# The reference builder and its identity helpers are shared with
# `capture.py reference` (zettel_lib/references.py); re-exported here because
# this module's own tests and callers have always reached for them by name.
DOI_RE = references.DOI_RE
ARXIV_RE = references.ARXIV_RE
CROSSREF = references.CROSSREF
JOURNAL_TYPES = references.JOURNAL_TYPES
crossref_csl = references.crossref_csl
authors_from = references.authors_from
first_line = references.first_line
build_reference = references.build_reference

#: Pages searched for the source's OWN identifier. The extraction now covers
#: every page (a literature note needs late-page locators), but a DOI deep in
#: a paper is nearly always a cited work's -- so identity stays on the front
#: matter while the text does not.
IDENTITY_PAGES = 5
#: A scanned book can extract to tens of megabytes of text; the capture itself
#: is already capped by fetch.max_capture_mb, but the .txt beside it is written
#: by us and would otherwise be unbounded.
MAX_EXTRACT_CHARS = 2_000_000


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
        pages = [p.extract_text() or "" for p in reader.pages]
        meta = {"pages": len(pages)}
        info = reader.metadata or {}
        for key, field in (("/Title", "title"), ("/Author", "author")):
            value = str(info.get(key) or "").strip()
            if value:
                meta[field] = value
        text = references.paginate(pages)
        warnings = []
        if len(text) > MAX_EXTRACT_CHARS:
            text = text[:MAX_EXTRACT_CHARS]
            warnings.append(f"{path.name}: extraction truncated at {MAX_EXTRACT_CHARS} "
                            "characters; later pages are not in the .txt")
        return text, meta, warnings
    except Exception as exc:  # noqa: BLE001 - any parse failure degrades alike
        return "", {}, [f"{path.name}: could not read PDF ({type(exc).__name__}: {exc})"]


def find_identifiers(text: str, sidecar: dict) -> dict:
    """Identity from the sidecar, else from the source's own front pages."""
    return references.find_identifiers(references.head_text(text, IDENTITY_PAGES), sidecar)


def mark(path: Path, marker: str) -> Path:
    """Rename a drop in place so later runs skip it, keeping the sidecar paired."""
    target = path.with_name(f"{path.stem}{marker}{path.suffix}")
    path.rename(target)
    side = sidecar_path(path)
    if side.exists():
        side.rename(target.with_suffix(".yml"))
    return target


def discard(path: Path) -> None:
    """Remove a copy this run made, and its generated sidecar."""
    path.unlink(missing_ok=True)
    sidecar_path(path).unlink(missing_ok=True)


def ingest_one(repo: ContentRepo, path: Path, *, mailto: str, offline: bool,
               transport, max_mb: float, identities: dict[str, str],
               owned_copy: bool = False) -> dict:
    """Ingest one file from drop/.

    ``owned_copy`` marks a file this run copied in itself (``--file``, a
    session's attachment) rather than one a human committed. The difference is
    what a refusal should leave behind: a committed drop is marked in place and
    reported in INBOX, because a human handed it over and must be told why it
    did not land. A copy is deleted and reported to the caller instead --
    nothing was handed to a future run, and marking it would leave litter in
    drop/ plus an INBOX entry about a file the repo never really had.
    """
    rel = repo.rel(path)
    warnings: list[str] = []
    size_mb = path.stat().st_size / (1024 * 1024)
    if size_mb > max_mb:
        if owned_copy:
            discard(path)
            return {"kind": "too-large", "file": rel, "marked": "", "size_mb": round(size_mb, 1),
                    "warnings": warnings}
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
    meta, title = references.build_reference(
        note_id, sidecar, extracted_meta, text, ids, enriched,
        fallback_title=path.stem.replace("-", " ").replace("_", " "),
        provenance={"dropped_as": path.name, "sidecar": bool(sidecar),
                    "ingested": capture.now_date()})

    identity = citations.source_identity(meta["csl_json"])
    if identity and identity in identities:
        dup = identities[identity]
        if owned_copy:
            discard(path)
            return {"kind": "duplicate", "file": rel, "duplicate_of": dup,
                    "marked": "", "warnings": warnings}
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
    ext = path.suffix.lower()  # ".pdf"
    raw_dir = repo.root / "raw"
    raw_dir.mkdir(exist_ok=True)
    capture_path = raw_dir / f"{note_id}-{slug}{ext}"
    if capture_path.exists():
        raise ContentRepoError(f"refusing to overwrite existing capture {repo.rel(capture_path)}")
    shutil.move(str(path), str(capture_path))
    text_path = None
    if text.strip() and ext != ".txt":
        text_path = raw_dir / f"{note_id}-{slug}.txt"
        text_path.write_text(
            f"Text extraction of {capture_path.name} (dropped as {path.name}); "
            f"the {ext.lstrip('.')} file is the cited capture.\n\n{text}",
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
           transport=http.requests_transport, only: list[Path] | None = None,
           owned_copy: bool = False) -> list[dict]:
    """Ingest what is waiting in drop/, or just the files named by ``only``.

    ``only`` exists for the ``--file`` path: a session ingesting the source it
    was just handed must not also sweep up drops a human committed for the next
    scheduled cycle, whose INBOX entries would then land in someone else's PR.
    """
    cfg = repo.config()
    max_mb = max_capture_mb(cfg)
    mailto = mailto or str(dig(cfg, "fetch.mailto") or "")
    identities = references.identities(repo)
    results = []
    for path in (only if only is not None else pending(repo)):
        results.append(ingest_one(repo, path, mailto=mailto, offline=offline,
                                  transport=transport, max_mb=max_mb,
                                  identities=identities, owned_copy=owned_copy))
    ingested = [r for r in results if r["kind"] == "ingested"]
    for r in ingested:
        # Verified on its capture and rendered right away, so the artifact is
        # gate-clean by construction (the capture.py principle) rather than
        # after the run remembers to call verify_refs in step 8.
        note = Note.load(repo.root / "reference" / f"{r['key']}.md")
        result = verify_refs.verify_note(note, repo, offline=True, mailto="")
        references.apply_verification(note, result, when=verify_refs.now())
        verify_refs.rerender(note)
        note.save()
    if ingested:
        build_manifest.regenerate(repo)
    return results


#: CLI flags that stand in for a sidecar file, so a session that was handed a
#: source can name it in one command instead of writing YAML beside it.
SIDECAR_FLAGS = ("title", "year", "doi", "isbn", "arxiv", "pmid", "url",
                 "source_tier", "priority", "notes")


def stage_file(repo: ContentRepo, source: Path, fields: dict) -> Path:
    """Copy an external source into drop/ so the normal ingest can run on it.

    A copy, never a move: the file belongs to whoever handed it over (a session
    attachment, a path in the user's home) and this tool has no business
    consuming it. Everything downstream is then identical to a committed drop,
    which is the point -- one ingest path, not two.
    """
    if not source.is_file():
        raise ContentRepoError(f"not a file: {source}")
    # The same filter pending() applies to committed drops. Without it --file
    # was the one way into raw/ that skipped it: a .bin or .docx would be
    # copied in, "extracted" as replacement-character noise, and cited as
    # evidence -- and raw/ is immutable, so the bad capture would stay.
    if source.suffix.lower() not in SOURCE_EXTS:
        kind = source.suffix or "(no extension)"
        raise ContentRepoError(
            f"{source.name}: unsupported source type {kind}; ingest accepts "
            f"{', '.join(SOURCE_EXTS)}. Convert it first, or export the text and "
            "drop that.")
    drop = repo.root / DROP_DIR
    drop.mkdir(exist_ok=True)
    target = drop / source.name
    if target.exists():
        raise ContentRepoError(
            f"drop/{source.name} already exists; rename the file or ingest what is pending first")
    shutil.copy2(source, target)
    if fields:
        sidecar_path(target).write_text(yaml.safe_dump(fields, sort_keys=False), encoding="utf-8")
    repo.append_log(f"ingest_drops: --file {source} staged as {repo.rel(target)}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("--list", action="store_true",
                        help="print the files waiting in drop/ and change nothing")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--mailto", default="",
                        help="contact email for Crossref (default: config fetch.mailto)")
    parser.add_argument("--offline", action="store_true",
                        help="skip the Crossref enrichment lookup")
    parser.add_argument("--file", type=Path,
                        help="an external source file to copy into drop/ and ingest now "
                             "(a session attachment); only that file is ingested")
    parser.add_argument("--title", default="", help="sidecar field (with --file)")
    parser.add_argument("--author", action="append", default=[],
                        help="sidecar field, repeatable (with --file)")
    parser.add_argument("--year", default="", help="sidecar field (with --file)")
    parser.add_argument("--doi", default="", help="sidecar field (with --file)")
    parser.add_argument("--isbn", default="", help="sidecar field (with --file)")
    parser.add_argument("--arxiv", default="", help="sidecar field (with --file)")
    parser.add_argument("--pmid", default="", help="sidecar field (with --file)")
    parser.add_argument("--url", default="", help="sidecar field (with --file)")
    parser.add_argument("--source-tier", default="", help="sidecar field (with --file)")
    parser.add_argument("--priority", default="", help="sidecar field (with --file)")
    parser.add_argument("--notes", default="", help="sidecar field (with --file)")
    parser.add_argument("--tags", default="", help="comma-separated sidecar tags (with --file)")
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)

    fields = {name: getattr(args, name) for name in SIDECAR_FLAGS
              if str(getattr(args, name) or "").strip()}
    if args.author:
        fields["author"] = args.author
    if args.tags.strip():
        fields["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
    if fields and not args.file:
        print("error: sidecar flags describe a --file; without it, put a <stem>.yml "
              "beside the file in drop/", file=sys.stderr)
        return EXIT_USAGE

    if args.list:
        files = [repo.rel(p) for p in pending(repo)]
        print(json.dumps(files) if args.json else
              ("\n".join(files) if files else "ingest_drops: nothing pending"))
        return EXIT_OK

    # Staging is argument validation -- a path that is not a file, a type this
    # pipeline cannot read, a name already pending -- so it exits 2 like every
    # other usage error, not 1 like a failed ingest.
    staged = None
    if args.file:
        try:
            staged = stage_file(repo, args.file, fields)
        except (ContentRepoError, OSError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE

    try:
        if staged is not None:
            results = ingest(repo, mailto=args.mailto, offline=args.offline,
                             only=[staged], owned_copy=True)
        else:
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
                print(f"{r['kind']}\t{r['file']}\t{r['marked'] or '(discarded)'}")
    # A --file caller asked for ONE source and needs to know whether it landed;
    # a sweep of drop/ is reporting on other people's files and stays exit 0.
    if args.file and results and results[0]["kind"] != "ingested":
        r = results[0]
        detail = (f"duplicate of {r['duplicate_of']}" if r["kind"] == "duplicate"
                  else f"{r.get('size_mb', '?')} MB exceeds fetch.max_capture_mb")
        print(f"error: {args.file.name} was not ingested: {detail}", file=sys.stderr)
        return EXIT_VIOLATION
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
