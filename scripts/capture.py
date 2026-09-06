#!/usr/bin/env python3
"""Turn a title and some text into well-formed content-repo artifacts.

Everything else in this repo is machine-authored, so the gates assume perfect
frontmatter: a hand-written file in fleeting/ fails the manifest build and
takes the whole cycle's PR down with it. That makes casual capture -- the thing
a zettelkasten lives on -- the riskiest act in the system.

This closes the gap from the other side. Rather than loosening the gates, it
generates artifacts that already satisfy them: correct note key, full
frontmatter, real timestamps. Note captures also rebuild manifest.json, so a
capture committed on its own still passes the manifest-currency gate. Usable
by a human at a terminal, by an ad-hoc Claude session, or by the agents.

    capture.py --repo <path> fleeting   "Title" [--body TEXT|-] [--tags a,b]
    capture.py --repo <path> inquiry    "Question" [--body TEXT|-] [--priority high]
    capture.py --repo <path> inbox      "Title" [--body TEXT|-]
    capture.py --repo <path> reference  "Title" [--doi X] [--isbn X] [--arxiv X]
                                        [--pmid X] [--url X] [--author "Family, Given"]
                                        [--year N] [--source-tier T] [--offline]
    capture.py --repo <path> literature "Title" --reference KEY --locator "p. 12"
    capture.py --repo <path> permanent  "Claim" --link KEY:relation [--link ...]
    capture.py --repo <path> inquiry-update KEY [--status S] [--result-notes k1,k2]

The three note kinds were added once the same gap appeared from the other
direction (A12): the agents were told to write reference, literature, and
permanent notes from `templates/`, by hand, into a repo whose gates demand
exact frontmatter -- the machine-authored half of the very problem this tool
was built for.

A reference always needs a title. The one exception is a DOI that resolves at
Crossref, which supplies one; every other identifier is a lookup key, not a
source of metadata, so `--isbn` alone still needs the title passed. A generator per note type keeps the invariant without touching
a gate, and refuses at write time what the lints would refuse at gate time: an
unresolvable link target, a relation outside FR-5, a literature note with no
locator, a second reference note for a source already on file.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_manifest
import verify_refs
from zettel_lib import http, naming, references
from zettel_lib.cli import EXIT_OK, EXIT_USAGE
from zettel_lib.frontmatter import FrontmatterError, Note, dump
from zettel_lib.repo import (INQUIRY_STATUSES, RELATIONS, ContentRepo,
                             ContentRepoError, dig)

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
PRIORITIES = ("low", "normal", "high")
SOURCE_TIERS = ("peer-reviewed", "primary-text", "reputable-secondary", "general-web")


def now_date() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def read_body(raw: str | None) -> str:
    """Body text, or stdin when '-' is given, so the tool composes in pipelines."""
    if raw is None:
        return ""
    if raw == "-":
        return sys.stdin.read().strip()
    return raw.strip()


def existing_ids(repo: ContentRepo) -> set[str]:
    """Every timestamp ID already spoken for, notes and inquiries alike.

    Read from filenames, not frontmatter: a note whose frontmatter is currently
    unparseable still owns its ID, and capture must not hand it out again.
    """
    taken = set()
    for path in repo.note_paths() + repo.inquiry_paths():
        try:
            taken.add(naming.split_key(path.stem)[1])
        except ValueError:
            continue
    return taken


def allocate_id(repo: ContentRepo, when: _dt.datetime | None = None) -> str:
    """A timestamp ID no other note holds.

    IDs are minute-resolution, so two captures in the same minute would collide
    -- and the manifest's id_to_key map silently keeps only the last, which
    would send a bare-ID link to the wrong note. Jotting several thoughts in a
    minute is exactly what capture is for, so step the minute forward until the
    ID is free. Ordering stays monotonic; only the recorded minute drifts.
    """
    when = when or _dt.datetime.now(_dt.timezone.utc)
    taken = existing_ids(repo)
    for _ in range(1440):  # a day of minutes; far past any real burst
        candidate = naming.new_id(when)
        if candidate not in taken:
            return candidate
        when += _dt.timedelta(minutes=1)
    raise ContentRepoError("could not allocate a free note id within 24h of now")


def common_meta(title: str, note_type: str, note_id: str) -> dict:
    key = naming.make_key(title, note_id)
    slug, _ = naming.split_key(key)
    stamp = now_date()
    return {
        "id": note_id,
        "key": key,
        "slug": slug,
        "aliases": [note_id],
        "type": note_type,
        "title": title,
        "created": stamp,
        "updated": stamp,
    }


def capture_fleeting(repo: ContentRepo, title: str, body: str, tags: list[str]) -> Path:
    meta = common_meta(title, "fleeting", allocate_id(repo))
    meta["tags"] = tags
    meta["links"] = []
    path = repo.root / "fleeting" / f"{meta['key']}.md"
    _write(path, meta, body or title)
    return path


def capture_inquiry(repo: ContentRepo, question: str, body: str, priority: str) -> Path:
    meta = common_meta(question, "inquiry", allocate_id(repo))
    # An inquiry's identity is its question; `title` would duplicate it.
    meta.pop("title")
    meta["question"] = question
    meta["status"] = "new"
    meta["priority"] = priority
    meta["asked_by"] = "human"
    meta["result_notes"] = []
    meta["tags"] = []
    path = repo.root / "inquiries" / f"{meta['key']}.md"
    _write(path, meta, body or f"{question}\n")
    return path


def resolve_note(repo: ContentRepo, target: str, types=None) -> Note | None:
    """The note a key or bare timestamp id names, or None.

    Link targets are validated before a note is written rather than after, so
    a generator never mints the `unresolved-link` the lint would fail on.
    """
    target = target.strip()
    for path in repo.note_paths(types=types):
        if path.stem == target or (naming.is_id(target) and path.stem.endswith(f"--{target}")):
            try:
                return Note.load(path)
            except FrontmatterError:
                return None
    return None


def capture_reference(repo: ContentRepo, fields: dict, *, mailto: str = "",
                      offline: bool = False,
                      transport=http.requests_transport) -> tuple[Path, dict]:
    """Mint a reference note from whatever identity the caller can give it.

    Verification is attempted here, at creation, rather than left for step 8 of
    a cycle: with a resolvable identifier the note is gate-clean the moment it
    exists (the ingest_drops principle), and the same `verify_refs.verify_note`
    the gate uses decides -- there is no second opinion to drift. Without an
    identifier, or offline, the note stays honestly `verified: false` and the
    caller is told to capture the source. That red gate is the invariant
    working, not a defect to paper over.
    """
    ids = references.find_identifiers("", fields)
    warnings: list[str] = []
    enriched = None
    if ids.get("doi") and not offline:
        try:
            enriched = references.crossref_csl(ids["doi"], mailto=mailto, transport=transport)
            if enriched is None:
                warnings.append(f"DOI {ids['doi']} did not resolve at Crossref; "
                                "using the metadata you supplied")
        except http.NetworkUnavailable as exc:
            warnings.append(f"network unavailable ({exc}); using the metadata you supplied")

    note_id = allocate_id(repo)
    meta, title = references.build_reference(
        note_id, fields, {}, "", ids, enriched,
        provenance={"created_by": "capture.py", "created": now_date()})
    if not title.strip():
        raise ContentRepoError(
            "a reference needs a title: pass one, or a DOI that resolves at Crossref")

    identity = citations_identity(meta["csl_json"])
    if identity:
        existing = references.identities(repo).get(identity)
        if existing:
            raise ContentRepoError(
                f"a reference note for {identity} already exists: {existing} "
                "(FR-4 allows exactly one reference note per source)")

    path = repo.root / "reference" / f"{meta['key']}.md"
    _write(path, meta, "Bibliographic record.\n")

    # Render and verify in place, so what lands is what the gate will read.
    note = Note.load(path)
    verify_refs.rerender(note)
    result = verify_refs.verify_note(note, repo, offline=offline, mailto=mailto,
                                     transport=transport)
    references.apply_verification(note, result, when=verify_refs.now())
    note.save()
    return path, {"key": meta["key"], "identity": identity, "verified": result.verified,
                  "method": result.method, "warnings": warnings}


def citations_identity(csl: dict) -> str:
    from zettel_lib import citations  # noqa: PLC0415 - avoids a circular import at module load

    return citations.source_identity(csl)


def capture_literature(repo: ContentRepo, title: str, body: str, reference: str,
                       locator: str, tags: list[str]) -> Path:
    """A literature note against one reference note, with its locator.

    Both of the lint's 1-1-1 rules are enforced here at write time: the single
    `source` link and the `reference` field name the same note, and the locator
    is non-empty -- a summary nobody can trace back to a page is not a
    literature note.
    """
    ref = resolve_note(repo, reference, types=["reference"])
    if ref is None:
        raise ContentRepoError(
            f"no reference note matches {reference!r}; create it first with "
            "`capture.py reference`")
    if not locator.strip():
        raise ContentRepoError("a literature note needs a --locator (page, section, timestamp)")
    meta = common_meta(title, "literature", allocate_id(repo))
    meta["tags"] = tags
    meta["reference"] = ref.key
    meta["locator"] = locator.strip()
    meta["links"] = [{"target_id": ref.key, "relation": "source"}]
    path = repo.root / "literature" / f"{meta['key']}.md"
    _write(path, meta, body or f"Summary of [[{ref.key}]] in your own words.\n")
    return path


def parse_links(repo: ContentRepo, specs: list[str]) -> list[dict]:
    """`KEY:relation` pairs, validated against FR-5 and the notes on disk."""
    links = []
    for spec in specs:
        target, _, relation = spec.rpartition(":")
        if not target or not relation:
            raise ContentRepoError(
                f"--link {spec!r} is not KEY:relation (e.g. "
                "atomic-notes-compound-over-time--202608301200:elaborates)")
        if relation not in RELATIONS:
            raise ContentRepoError(
                f"relation {relation!r} is outside the FR-5 taxonomy: "
                + ", ".join(sorted(RELATIONS)))
        note = resolve_note(repo, target)
        if note is None:
            raise ContentRepoError(f"link target {target!r} resolves to no note in this repo")
        links.append({"target_id": note.key, "relation": relation})
    return links


def capture_permanent(repo: ContentRepo, title: str, body: str, links: list[str],
                      tags: list[str]) -> tuple[Path, list[str]]:
    """One atomic claim, with at least one validated outbound typed link."""
    if not links:
        raise ContentRepoError(
            "a permanent note needs at least one outbound typed link (1-1-1): --link KEY:relation")
    resolved = parse_links(repo, links)
    meta = common_meta(title, "permanent", allocate_id(repo))
    meta["tags"] = tags
    meta["links"] = resolved
    path = repo.root / "permanent" / f"{meta['key']}.md"
    text = body or f"{title}\n"
    _write(path, meta, text)

    # Warn, never refuse: the lint is the authority on what "sourced" means,
    # and a claim written before its source is captured is a normal state --
    # it just must not reach a commit.
    warnings = []
    import lint_citations  # noqa: PLC0415 - only needed for the heuristic

    if lint_citations.SOURCED_CLAIM.search(text):
        verified = {n.key for n in repo.notes(types=["reference"])
                    if (n.meta.get("verification") or {}).get("verified") is True}
        if not any(l["target_id"] in verified for l in resolved):
            warnings.append(
                "this note reads as a sourced claim but links no VERIFIED reference note; "
                "lint_citations will fail it (uncited-claim) until one is linked")
    return path, warnings


def update_inquiry(repo: ContentRepo, ref: str, *, status: str = "",
                   result_notes: list[str] | None = None, note: str = "") -> tuple[Path, dict]:
    """Move an inquiry along its FR-6 lifecycle.

    This lives in capture.py rather than inquiries.py deliberately.
    `inquiries.py` is a read-only reporter (A9: a query is not an operation),
    and the manifest indexes an inquiry's `status` and `result_notes` -- so a
    writer must also regenerate it or the next `--check` goes red. capture.py
    already owns both properties.

    Every check runs BEFORE anything is written: an inquiry that fails
    validation is left exactly as it was, rather than half-updated into a
    state the lint then rejects.
    """
    path = None
    ref = ref.strip()
    for candidate in repo.inquiry_paths():
        if candidate.stem == ref or (naming.is_id(ref) and candidate.stem.endswith(f"--{ref}")):
            path = candidate
            break
    if path is None:
        raise ContentRepoError(f"no inquiry matches {ref!r} (list them with inquiries.py)")
    inquiry = Note.load(path)

    if status and status not in INQUIRY_STATUSES:
        raise ContentRepoError(
            f"status {status!r} is outside {'|'.join(INQUIRY_STATUSES)}")

    added = []
    for target in result_notes or []:
        found = resolve_note(repo, target)
        if found is None:
            raise ContentRepoError(f"result note {target!r} resolves to no note in this repo")
        if found.type != "permanent":
            raise ContentRepoError(
                f"result note {target!r} is a '{found.type}' note; only permanent notes "
                "answer an inquiry (a literature note summarises a source, it does not "
                "assert an answer)")
        added.append(found.key)

    merged = list(inquiry.result_notes)
    for key in added:
        if key not in merged:
            merged.append(key)
    new_status = status or inquiry.status
    if new_status == "answered" and not merged:
        raise ContentRepoError(
            "an inquiry may only be marked 'answered' with at least one result note naming "
            "the permanent note that answered it (AC-6); leave it 'in-progress' and say why")

    before = inquiry.status
    if status:
        inquiry.meta["status"] = status
    if added:
        inquiry.meta["result_notes"] = merged
    inquiry.meta["updated"] = now_date()
    if note:
        body = inquiry.body.rstrip("\n")
        inquiry.body = f"{body}\n\n## {now_date()}\n\n{note.strip()}\n"
    inquiry.save()
    build_manifest.regenerate(repo)
    return path, {"key": inquiry.key, "status": new_status, "was": before,
                  "result_notes": merged, "added": added}


def capture_inbox(repo: ContentRepo, title: str, body: str) -> Path:
    """Append a rendered entry to INBOX.md.

    Append-only on purpose: an INBOX is a conversation with the runs, and
    rewriting it would silently drop feedback a cycle has not yet read.
    """
    template = (TEMPLATES / "inbox-entry.md").read_text(encoding="utf-8")
    entry = (template
             .replace("{{DATE}}", now_date())
             .replace("{{TITLE}}", title)
             .replace("{{BODY}}", body or "(no further detail)"))
    inbox = repo.root / "INBOX.md"
    existing = inbox.read_text(encoding="utf-8") if inbox.exists() else "# Inbox\n"
    separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    inbox.write_text(f"{existing}{separator}{entry.rstrip()}\n", encoding="utf-8")
    return inbox


def _write(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ContentRepoError(f"refusing to overwrite existing file: {path}")
    path.write_text(dump(meta, body if body.endswith("\n") else body + "\n"),
                    encoding="utf-8")


def _add_body(sub, help_text: str = "body text, or '-' to read stdin") -> None:
    sub.add_argument("--body", help=help_text)


def build_parser() -> argparse.ArgumentParser:
    """The CLI.

    Global flags stay BEFORE the kind (`--repo R fleeting "..."`), which is how
    every existing caller already spells it -- adhoc_research.sh, query.py's
    suggested commands, the smoke test, the agent definitions and the docs. A
    subcommand-first layout would have read more naturally and broken all of
    them.
    """
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--repo", required=True, type=Path,
                        help="path to the content repository")
    parser.add_argument("--json", action="store_true",
                        help="emit the created path as JSON, for programmatic callers")
    kinds = parser.add_subparsers(dest="kind", required=True, metavar="KIND")

    fleeting = kinds.add_parser("fleeting", help="a short-lived capture, swept next cycle")
    fleeting.add_argument("title")
    _add_body(fleeting)
    fleeting.add_argument("--tags", default="", help="comma-separated tags")

    inquiry = kinds.add_parser("inquiry", help="an open question, worked by a later run")
    inquiry.add_argument("title", help="the question")
    _add_body(inquiry)
    inquiry.add_argument("--priority", default="normal", choices=PRIORITIES)

    inbox = kinds.add_parser("inbox", help="feedback or an instruction for the next run")
    inbox.add_argument("title")
    _add_body(inbox)

    reference = kinds.add_parser(
        "reference", help="a bibliographic record for one source (FR-4: exactly one per source)")
    reference.add_argument("title", nargs="?", default="",
                           help="the source's title (optional when a DOI resolves at Crossref)")
    reference.add_argument("--doi", default="")
    reference.add_argument("--isbn", default="")
    reference.add_argument("--arxiv", default="")
    reference.add_argument("--pmid", default="")
    reference.add_argument("--url", default="")
    reference.add_argument("--author", action="append", default=[],
                           help="'Family, Given' or 'Given Family'; repeatable")
    reference.add_argument("--year", default="")
    reference.add_argument("--type", default="", help="CSL type (article-journal, book, ...)")
    reference.add_argument("--source-tier", default="", choices=("",) + SOURCE_TIERS,
                           help="default: peer-reviewed for a DOI, else reputable-secondary")
    reference.add_argument("--tags", default="")
    reference.add_argument("--offline", action="store_true",
                           help="skip Crossref enrichment and registry verification")
    reference.add_argument("--mailto", default="",
                           help="contact email for the polite pools (default: config fetch.mailto)")

    literature = kinds.add_parser(
        "literature", help="an own-words summary of exactly one source")
    literature.add_argument("title")
    _add_body(literature)
    literature.add_argument("--reference", required=True, help="reference note key or bare id")
    literature.add_argument("--locator", required=True, help="page, section, or timestamp")
    literature.add_argument("--tags", default="")

    permanent = kinds.add_parser("permanent", help="one atomic claim, title stated as a claim")
    permanent.add_argument("title", help="the claim")
    _add_body(permanent)
    permanent.add_argument("--link", action="append", default=[], metavar="KEY:RELATION",
                           help="typed link; repeatable; at least one required (1-1-1)")
    permanent.add_argument("--tags", default="")

    update = kinds.add_parser(
        "inquiry-update", help="move an inquiry along its lifecycle (status, result notes)")
    update.add_argument("key", help="inquiry key or bare id")
    update.add_argument("--status", default="", choices=("",) + INQUIRY_STATUSES)
    update.add_argument("--result-notes", default="",
                        help="comma-separated permanent-note keys that answered it")
    update.add_argument("--note", default="",
                        help="text appended to the inquiry body, or '-' to read stdin")
    return parser


def tag_list(raw: str) -> list[str]:
    return [t.strip() for t in raw.split(",") if t.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    title = getattr(args, "title", "") or ""
    if args.kind != "inquiry-update" and not title.strip() and args.kind != "reference":
        print("error: a title (or question) is required", file=sys.stderr)
        return EXIT_USAGE

    payload: dict = {}
    warnings: list[str] = []
    try:
        repo = ContentRepo(args.repo)
        if args.kind == "inquiry-update":
            note_text = read_body(args.note) if args.note else ""
            if not (args.status or args.result_notes or note_text):
                print("error: nothing to change; pass --status, --result-notes, or --note",
                      file=sys.stderr)
                return EXIT_USAGE
            path, payload = update_inquiry(
                repo, args.key, status=args.status,
                result_notes=tag_list(args.result_notes), note=note_text)
        elif args.kind == "fleeting":
            path = capture_fleeting(repo, title.strip(), read_body(args.body),
                                    tag_list(args.tags))
        elif args.kind == "inquiry":
            path = capture_inquiry(repo, title.strip(), read_body(args.body), args.priority)
        elif args.kind == "inbox":
            path = capture_inbox(repo, title.strip(), read_body(args.body))
        elif args.kind == "reference":
            mailto = args.mailto
            if not mailto and not args.offline:
                try:
                    mailto = str(dig(repo.config(), "fetch.mailto") or "")
                except ContentRepoError:
                    mailto = ""
            fields = {"title": title.strip(), "doi": args.doi, "isbn": args.isbn,
                      "arxiv": args.arxiv, "pmid": args.pmid, "url": args.url,
                      "author": args.author, "year": args.year, "type": args.type,
                      "source_tier": args.source_tier, "tags": tag_list(args.tags)}
            path, payload = capture_reference(repo, fields, mailto=mailto, offline=args.offline)
            warnings = payload.pop("warnings", [])
        elif args.kind == "literature":
            path = capture_literature(repo, title.strip(), read_body(args.body),
                                      args.reference, args.locator, tag_list(args.tags))
        else:
            path, warnings = capture_permanent(repo, title.strip(), read_body(args.body),
                                               args.link, tag_list(args.tags))
    except (ContentRepoError, FrontmatterError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    rel = repo.rel(path)
    if args.kind in ("fleeting", "inquiry", "reference", "literature", "permanent"):
        # This capture just changed what manifest.json indexes, and the content
        # repo's required `gates` check rejects a stale manifest -- so a capture
        # committed without a rebuild produces a PR that cannot merge. INBOX is
        # not indexed, so inbox captures skip it; inquiry-update rebuilds its
        # own. Best-effort on purpose: when the rebuild fails, the breakage
        # predates this capture (this artifact is well-formed by construction)
        # and must not eat the capture itself.
        try:
            build_manifest.regenerate(repo)
        except (ContentRepoError, FrontmatterError, OSError) as exc:
            print(f"warning: {rel} written, but the manifest could not be "
                  f"rebuilt: {exc}\nfix that and re-run build_manifest.py "
                  "before committing", file=sys.stderr)

    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    if args.kind == "reference" and not payload.get("verified"):
        print("UNVERIFIED: capture the source with "
              f"`fetch_source.py --repo {args.repo} --ref {payload['key']} --url <url>`, "
              "then run verify_refs.py. lint_citations fails until then -- that is the "
              "gate working, so do not hand-edit the verification block.", file=sys.stderr)

    if args.kind == "inquiry-update":
        detail = f"status={payload['was']}->{payload['status']}"
        if payload["added"]:
            detail += f" result_notes=+{','.join(payload['added'])}"
        repo.append_log(f"capture: inquiry-update {payload['key']} {detail}")
    elif args.kind == "reference":
        verified = payload["method"] if payload["verified"] else "no"
        repo.append_log(f"capture: reference -> {rel} "
                        f"(identity={payload.get('identity') or 'none'}, verified={verified})")
    else:
        repo.append_log(f"capture: {args.kind} -> {rel}")

    if args.json:
        out = {"kind": args.kind, "path": rel}
        out.update({k: v for k, v in payload.items() if k != "was"})
        if args.kind not in ("inbox", "inquiry-update"):
            out.setdefault("key", Path(rel).stem)
        print(json.dumps(out))
    else:
        print(rel)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
