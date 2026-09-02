#!/usr/bin/env python3
"""Regenerate manifest.json from note frontmatter (FR-3, FR-19).

Deterministic and idempotent: sorted keys, sorted entries, fixed separators, so
two runs over unchanged notes produce a byte-identical file (AC-3).

URL emission follows the public/private matrix (FR-topology): a public content
repo gets full raw.githubusercontent.com URLs; a private one gets repo-relative
paths plus GitHub API contents paths, and never an anonymous raw URL.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib.cli import EXIT_OK, EXIT_USAGE, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import ContentRepo, ContentRepoError, dig

RAW_URL = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
API_URL = "https://api.github.com/repos/{owner}/{repo}/contents/{path}"


def url_for(repo: ContentRepo, cfg: dict, rel_path: str, visibility: str) -> str:
    owner = dig(cfg, "content_repo.owner") or ""
    name = dig(cfg, "content_repo.name") or ""
    branch = dig(cfg, "content_repo.branch") or "main"
    if visibility == "public":
        return RAW_URL.format(owner=owner, repo=name, branch=branch, path=rel_path)
    return rel_path


def api_path_for(cfg: dict, rel_path: str) -> str:
    owner = dig(cfg, "content_repo.owner") or ""
    name = dig(cfg, "content_repo.name") or ""
    return API_URL.format(owner=owner, repo=name, path=rel_path)


def stamp(note: Note, rel: str) -> str:
    """The entry's `updated` (FR-3: ISO-8601), falling back to `created`.

    Validated because the manifest is what Mode-B readers and the freshness
    sweep sort by; a free-text date sorts nowhere. Accepts a date or a
    datetime (YAML already turns an unquoted 2026-08-30 into a date object).
    """
    for field in ("updated", "created"):
        value = note.meta.get(field)
        if value in (None, ""):
            continue
        if not isinstance(value, (_dt.date, _dt.datetime)):
            text = str(value).strip()
            try:
                _dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                raise FrontmatterError(
                    f"{rel}: '{field}' is {text!r}, not an ISO-8601 date (FR-3)") from None
    return str(note.meta.get("updated") or note.meta.get("created") or "")


def build(repo: ContentRepo) -> dict:
    cfg = repo.require_config("content_repo.owner", "content_repo.name",
                              "content_repo.visibility")
    visibility = str(dig(cfg, "content_repo.visibility"))
    entries: list[dict] = []
    id_to_key: dict[str, str] = {}

    for path in repo.note_paths():
        note = Note.load(path)
        rel = repo.rel(path)
        if not note.id:
            raise FrontmatterError(f"{rel}: frontmatter is missing 'id'")
        if not note.key:
            raise FrontmatterError(f"{rel}: frontmatter is missing 'key'")
        entry = {
            "id": note.id,
            "key": note.key,
            "slug": note.slug,
            "type": note.type,
            "title": note.title,
            "tags": sorted(note.tags),
            "links": sorted(
                (
                    {"target_id": str(link.get("target_id", "")),
                     "relation": str(link.get("relation", ""))}
                    for link in note.links
                ),
                key=lambda link: (link["target_id"], link["relation"]),
            ),
            "path": rel,
            "url_or_apipath": url_for(repo, cfg, rel, visibility),
            "updated": stamp(note, rel),
        }
        if visibility != "public":
            entry["api_path"] = api_path_for(cfg, rel)
        entries.append(entry)
        if note.id in id_to_key and id_to_key[note.id] != note.key:
            # A bare-ID link would otherwise resolve to whichever note was
            # indexed last -- silently, and to the wrong note.
            raise FrontmatterError(
                f"{rel}: duplicate note id {note.id!r}, already held by "
                f"{id_to_key[note.id]!r}")
        id_to_key[note.id] = note.key

    entries.sort(key=lambda e: e["key"])
    return {
        "generated_by": "build_manifest.py",
        "visibility": visibility,
        "note_count": len(entries),
        "id_to_key": dict(sorted(id_to_key.items())),
        "notes": entries,
        "inquiries": build_inquiries(repo),
    }


def build_inquiries(repo: ContentRepo) -> list[dict]:
    """Index open questions so a run can find them without parsing markdown (FR-6).

    Inquiries live alongside the notes but outside the graph, so they get their
    own block rather than a `type` in `notes`: nothing should ever traverse a
    link into a question.
    """
    out = []
    for path in repo.inquiry_paths():
        note = Note.load(path)
        rel = repo.rel(path)
        if not note.key:
            raise FrontmatterError(f"{rel}: frontmatter is missing 'key'")
        out.append({
            "key": note.key,
            "question": note.question,
            "status": note.status,
            "priority": note.priority,
            "result_notes": sorted(note.result_notes),
            "path": rel,
            "updated": stamp(note, rel),
        })
    out.sort(key=lambda item: item["key"])
    return out


def build_refs(repo: ContentRepo) -> list[dict]:
    """Aggregate every reference note's CSL-JSON into .bib/refs.json (FR-7, AC-7).

    Scripture is cited in-text per SBL and excluded from the bibliography (FR-9).
    """
    refs = []
    for note in repo.notes(types=["reference"]):
        if note.meta.get("scripture"):
            continue
        csl = note.meta.get("csl_json")
        if isinstance(csl, dict) and csl.get("id"):
            refs.append(csl)
    refs.sort(key=lambda item: str(item.get("id", "")))
    return refs


def serialize(manifest: dict) -> str:
    return json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def serialize_refs(refs: list[dict]) -> str:
    return json.dumps(refs, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def regenerate(repo: ContentRepo) -> dict:
    """Build and write manifest.json and .bib/refs.json; returns the manifest.

    The one write path for every entry point. capture.py calls this after a
    fleeting or inquiry capture because the capture is what made the committed
    manifest stale -- and with the content repo's `gates` check required, a
    stale manifest in a capture-only PR cannot merge. Any hand-rolled second
    writer would eventually drift from what --check expects, which is exactly
    the hand-authored-artifact failure this file's --check hint warns about.
    """
    manifest = build(repo)
    (repo.root / "manifest.json").write_text(serialize(manifest), encoding="utf-8")
    refs_target = repo.root / ".bib" / "refs.json"
    refs_target.parent.mkdir(parents=True, exist_ok=True)
    refs_target.write_text(serialize_refs(build_refs(repo)), encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="verify the manifest is up to date without writing it")
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)

    if args.check:
        try:
            manifest = build(repo)
        except (FrontmatterError, ContentRepoError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_USAGE
        target = repo.root / "manifest.json"
        refs_target = repo.root / ".bib" / "refs.json"
        checks = ((target, serialize(manifest)),
                  (refs_target, serialize_refs(build_refs(repo))))
        stale = []
        for path, expected in checks:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != expected:
                stale.append(repo.rel(path) if path.exists() else str(path.name))
        if stale:
            # Name the second cause, because the obvious advice makes it worse.
            # In CI this script is the CURRENT one and the committed file came
            # from a run's own install -- so when that install is stale, "re-run
            # build_manifest.py" regenerates the same wrong bytes. A live run hit
            # exactly this: it took the advice, still failed, and hand-wrote an
            # inquiries block in a guessed schema twice before finding the cache.
            print(f"error: {', '.join(stale)} out of date; re-run build_manifest.py",
                  file=sys.stderr)
            print("hint: if you just ran it and this still fails, the installed "
                  "skill is probably stale -- refresh it "
                  "(scripts/remote_cycle.sh refresh-skill) and rebuild. "
                  "Never hand-edit these files to match; the generator is canonical.",
                  file=sys.stderr)
            return EXIT_USAGE
        print("build_manifest: manifest.json and .bib/refs.json up to date")
        return EXIT_OK

    try:
        manifest = regenerate(repo)
    except (FrontmatterError, ContentRepoError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(f"build_manifest: wrote manifest.json ({manifest['note_count']} notes) "
          "and .bib/refs.json")
    repo.append_log(f"build_manifest: {manifest['note_count']} notes indexed")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
