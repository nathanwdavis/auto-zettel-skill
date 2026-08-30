#!/usr/bin/env python3
"""Link, layering, and note-identity lint (FR-21).

Enforces the FR-5 relation taxonomy, resolvability of every [[key]] and typed
link, the INDEX -> MOC -> note layering (FR-4), and the 1-1-1 rule (FR-4).
Also enforces the note-key naming amendment: a file's stem must equal its
frontmatter `key`, and that key must decompose into its own `slug` and `id`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib import naming
from zettel_lib.cli import EXIT_USAGE, Violation, base_parser, open_repo, report
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import ContentRepo, ContentRepoError

RELATIONS = {
    "supports", "contradicts", "analogous", "shared-concept",
    "historical-connection", "elaborates", "refutes", "source",
}

WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]")


def resolve(target: str, keys: set[str], id_to_key: dict[str, str]) -> str | None:
    """Resolve a reference to a note key, accepting a bare timestamp ID."""
    target = target.strip()
    if target in keys:
        return target
    if naming.is_id(target) and target in id_to_key:
        return id_to_key[target]
    return None


def lint(repo: ContentRepo) -> list[Violation]:
    violations: list[Violation] = []
    notes: list[Note] = []

    for path in repo.note_paths():
        try:
            notes.append(Note.load(path))
        except FrontmatterError as exc:
            violations.append(Violation(repo.rel(path), "frontmatter", str(exc)))

    keys = {n.key for n in notes if n.key}
    id_to_key = {n.id: n.key for n in notes if n.id and n.key}
    by_key = {n.key: n for n in notes if n.key}

    for note in notes:
        rel = repo.rel(note.path)

        # -- identity: filename stem, key, slug, id must agree -----------------
        if not note.key:
            violations.append(Violation(rel, "missing-key", "frontmatter has no 'key'"))
        elif note.stem != note.key:
            violations.append(Violation(
                rel, "filename-key-mismatch",
                f"filename stem '{note.stem}' != frontmatter key '{note.key}'"))
        else:
            try:
                slug, note_id = naming.split_key(note.key)
            except ValueError as exc:
                violations.append(Violation(rel, "malformed-key", str(exc)))
            else:
                if note.slug and note.slug != slug:
                    violations.append(Violation(
                        rel, "slug-key-mismatch",
                        f"key slug '{slug}' != frontmatter slug '{note.slug}'"))
                if note.id and note.id != note_id:
                    violations.append(Violation(
                        rel, "id-key-mismatch",
                        f"key id '{note_id}' != frontmatter id '{note.id}'"))

        # -- typed links -------------------------------------------------------
        for link in note.links:
            relation = str(link.get("relation", ""))
            target = str(link.get("target_id", ""))
            if relation not in RELATIONS:
                violations.append(Violation(
                    rel, "bad-relation",
                    f"relation '{relation}' is outside the FR-5 taxonomy"))
            if not resolve(target, keys, id_to_key):
                violations.append(Violation(
                    rel, "unresolved-link",
                    f"typed link target '{target}' is absent from the manifest"))

        # -- body wikilinks ----------------------------------------------------
        for match in WIKILINK.finditer(note.body):
            target = match.group(1)
            if not resolve(target, keys, id_to_key):
                violations.append(Violation(
                    rel, "unresolved-wikilink",
                    f"[[{target}]] does not resolve to a known note"))

        # -- 1-1-1 -------------------------------------------------------------
        if note.type == "permanent" and not note.links:
            violations.append(Violation(
                rel, "atomicity",
                "permanent note has no outbound typed link (1-1-1 requires >=1)"))

        if note.type == "literature":
            refs = [l for l in note.links
                    if resolve(str(l.get("target_id", "")), keys, id_to_key)
                    and by_key.get(
                        resolve(str(l.get("target_id", "")), keys, id_to_key)
                    ).type == "reference"]
            if len(refs) != 1:
                violations.append(Violation(
                    rel, "one-to-one",
                    f"literature note links to {len(refs)} reference notes; exactly 1 required"))

    violations.extend(lint_layering(repo, keys, id_to_key, by_key))
    return violations


def lint_layering(repo, keys, id_to_key, by_key) -> list[Violation]:
    """INDEX links only to MOCs; MOCs link to notes (FR-4)."""
    out: list[Violation] = []
    index = repo.root / "INDEX.md"
    if not index.exists():
        return [Violation("INDEX.md", "missing-index", "content repo has no INDEX.md")]

    for match in WIKILINK.finditer(index.read_text(encoding="utf-8")):
        target = match.group(1)
        resolved = resolve(target, keys, id_to_key)
        if not resolved:
            out.append(Violation("INDEX.md", "unresolved-wikilink",
                                 f"[[{target}]] does not resolve to a known note"))
        elif by_key[resolved].type != "moc":
            out.append(Violation(
                "INDEX.md", "layering",
                f"INDEX links to a '{by_key[resolved].type}' note; INDEX may link only to MOCs"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)
    try:
        violations = lint(repo)
    except (ContentRepoError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return report(violations, repo, "lint_links")


if __name__ == "__main__":
    raise SystemExit(main())
