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

    capture.py --repo <path> fleeting "Title" [--body TEXT|-] [--tags a,b]
    capture.py --repo <path> inquiry  "Question" [--body TEXT|-] [--priority high]
    capture.py --repo <path> inbox    "Title" [--body TEXT|-]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_manifest
from zettel_lib import naming
from zettel_lib.cli import EXIT_OK, EXIT_USAGE
from zettel_lib.frontmatter import FrontmatterError, dump
from zettel_lib.repo import ContentRepo, ContentRepoError

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
PRIORITIES = ("low", "normal", "high")


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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--repo", required=True, type=Path,
                        help="path to the content repository")
    parser.add_argument("--json", action="store_true",
                        help="emit the created path as JSON, for programmatic callers")
    parser.add_argument("kind", choices=["fleeting", "inquiry", "inbox"])
    parser.add_argument("title", help="note title, or the question for an inquiry")
    parser.add_argument("--body", help="body text, or '-' to read stdin")
    parser.add_argument("--tags", default="", help="comma-separated tags (fleeting only)")
    parser.add_argument("--priority", default="normal", choices=PRIORITIES,
                        help="inquiry priority")
    args = parser.parse_args(argv)

    if not args.title.strip():
        print("error: a title (or question) is required", file=sys.stderr)
        return EXIT_USAGE

    try:
        repo = ContentRepo(args.repo)
        body = read_body(args.body)
        if args.kind == "fleeting":
            tags = [t.strip() for t in args.tags.split(",") if t.strip()]
            path = capture_fleeting(repo, args.title.strip(), body, tags)
        elif args.kind == "inquiry":
            path = capture_inquiry(repo, args.title.strip(), body, args.priority)
        else:
            path = capture_inbox(repo, args.title.strip(), body)
    except (ContentRepoError, FrontmatterError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    rel = repo.rel(path)
    if args.kind != "inbox":
        # This capture just changed what manifest.json indexes, and the content
        # repo's required `gates` check rejects a stale manifest -- so a capture
        # committed without a rebuild produces a PR that cannot merge. INBOX is
        # not indexed, so inbox captures skip it. Best-effort on purpose: when
        # the rebuild fails, the breakage predates this capture (this artifact
        # is well-formed by construction) and must not eat the capture itself.
        try:
            build_manifest.regenerate(repo)
        except (ContentRepoError, FrontmatterError, OSError) as exc:
            print(f"warning: {rel} written, but the manifest could not be "
                  f"rebuilt: {exc}\nfix that and re-run build_manifest.py "
                  "before committing", file=sys.stderr)
    repo.append_log(f"capture: {args.kind} -> {rel}")
    print(json.dumps({"kind": args.kind, "path": rel}) if args.json else rel)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
