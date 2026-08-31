#!/usr/bin/env python3
"""Skill-layer wellformedness gate (FR-33, AC-34, AC-36).

Every child skill under the content repo's ``skills/`` must be exactly the
two-file rollbackable unit the promotion flow can revert — ``SKILL.md`` (the
procedure) plus ``PURPOSE.md`` (the provenance) — with PURPOSE frontmatter
carrying the proposal state and its Patterns-Addressed section citing the
note keys that motivated it. A ``proposed`` create whose name was already
rejected in skill-impact.md is flagged: rejected creates are permanent
history and are never retried (AC-36, amendment A7).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lint_links import WIKILINK, resolve
from zettel_lib import impact
from zettel_lib.cli import Violation, base_parser, open_repo, report
from zettel_lib.frontmatter import FrontmatterError, split

REQUIRED_FILES = ("SKILL.md", "PURPOSE.md")
PURPOSE_SECTIONS = ("Origin", "Patterns-Addressed", "Evolution-History")

#: The only in-tree states. `rejected` is deliberately absent: rejection
#: reverts the skill layer, so a rejected skill has no files to carry a status
#: — its record lives in skill-impact.md alone (FR-36).
STATUSES = ("proposed", "approved")


def _manifest_keys(repo) -> tuple[set[str], dict[str, str]]:
    path = repo.root / "manifest.json"
    if not path.exists():
        return set(), {}
    data = json.loads(path.read_text(encoding="utf-8"))
    keys = {n["key"] for n in data.get("notes", []) if n.get("key")}
    return keys, dict(data.get("id_to_key") or {})


def _section(body: str, heading: str) -> str:
    """The text under ``## <heading>`` up to the next ``## ``."""
    marker = f"## {heading}"
    idx = body.find(marker)
    if idx < 0:
        return ""
    rest = body[idx + len(marker):]
    nxt = rest.find("\n## ")
    return rest if nxt < 0 else rest[:nxt]


def lint(repo) -> list[Violation]:
    violations: list[Violation] = []
    skills_dir = repo.root / "skills"
    if not skills_dir.is_dir():
        return [Violation("skills", "missing-skills-dir",
                          "content repo has no skills/ directory (FR-1)")]

    keys, id_to_key = _manifest_keys(repo)
    banned = impact.rejected_creates(repo)

    for entry in sorted(skills_dir.iterdir()):
        rel = repo.rel(entry)
        if entry.is_file():
            if entry.name != ".gitkeep":
                violations.append(Violation(
                    rel, "skill-extra-file",
                    "skills/ holds only per-skill directories"))
            continue

        files = sorted(p.name for p in entry.iterdir())
        for required in REQUIRED_FILES:
            if required not in files:
                violations.append(Violation(
                    rel, "skill-missing-file",
                    f"child skill lacks {required} (FR-35 output is exactly "
                    "SKILL.md + PURPOSE.md)"))
        for name in files:
            if name not in REQUIRED_FILES:
                violations.append(Violation(
                    f"{rel}/{name}", "skill-extra-file",
                    "a child skill is exactly SKILL.md + PURPOSE.md — the "
                    "unit the promotion flow can revert (FR-33)"))

        skill_md = entry / "SKILL.md"
        if skill_md.exists():
            try:
                meta, _ = split(skill_md.read_text(encoding="utf-8"))
            except FrontmatterError as exc:
                violations.append(Violation(
                    repo.rel(skill_md), "frontmatter", str(exc)))
            else:
                if str(meta.get("name", "")) != entry.name:
                    violations.append(Violation(
                        repo.rel(skill_md), "skill-name-mismatch",
                        f"SKILL.md name '{meta.get('name', '')}' != directory "
                        f"'{entry.name}'"))

        purpose_md = entry / "PURPOSE.md"
        if purpose_md.exists():
            violations.extend(_lint_purpose(
                repo, purpose_md, entry.name, keys, id_to_key, banned))
    return violations


def _lint_purpose(repo, path, dirname, keys, id_to_key, banned) -> list[Violation]:
    rel = repo.rel(path)
    out: list[Violation] = []
    try:
        meta, body = split(path.read_text(encoding="utf-8"))
    except FrontmatterError as exc:
        return [Violation(rel, "frontmatter", str(exc))]

    if str(meta.get("skill", "")) != dirname:
        out.append(Violation(
            rel, "skill-name-mismatch",
            f"PURPOSE.md skill '{meta.get('skill', '')}' != directory '{dirname}'"))

    status = str(meta.get("status", ""))
    if status not in STATUSES:
        out.append(Violation(
            rel, "skill-bad-status",
            f"status '{status}' is outside {'|'.join(STATUSES)} — a rejected "
            "skill has no in-tree files at all"))

    for heading in PURPOSE_SECTIONS:
        if f"## {heading}" not in body:
            out.append(Violation(
                rel, "purpose-missing-section",
                f"PURPOSE.md lacks the '## {heading}' section (AC-34)"))

    patterns = _section(body, "Patterns-Addressed")
    cited = any(
        resolve(m.group(1), keys, id_to_key)
        for m in WIKILINK.finditer(patterns)
    )
    if patterns and not cited:
        out.append(Violation(
            rel, "purpose-uncited",
            "Patterns-Addressed cites no resolvable [[note-key]] — a proposal "
            "must map back to the knowledge patterns that motivated it (AC-34)"))

    if status == "proposed" and str(meta.get("kind", "")) == "create" \
            and dirname in banned:
        out.append(Violation(
            rel, "re-proposed-skill",
            "a create of this name was rejected in skill-impact.md; rejected "
            "creates are never retried (AC-36)"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)
    return report(lint(repo), repo, "lint_skills")


if __name__ == "__main__":
    raise SystemExit(main())
