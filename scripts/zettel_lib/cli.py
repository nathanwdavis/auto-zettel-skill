"""Shared CLI plumbing: argument parsing, violation reporting, exit codes.

Every script honours the same contract (spec section 7): accepts ``--help``,
exits 0 on success and non-zero on failure, logs to stdout, and appends to the
target repo's ``log.md`` when ``--repo`` is given.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from .repo import ContentRepo, ContentRepoError

EXIT_OK = 0
EXIT_VIOLATION = 1
EXIT_USAGE = 2


@dataclass(frozen=True)
class Violation:
    """One lint finding, rendered as ``FILE\\tRULE\\tREASON`` (FR-20)."""

    file: str
    rule: str
    reason: str

    def render(self) -> str:
        return f"{self.file}\t{self.rule}\t{self.reason}"


def base_parser(description: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=description,
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--repo",
        required=True,
        type=Path,
        help="path to the content repository",
    )
    return parser


def open_repo(path: Path) -> ContentRepo:
    try:
        return ContentRepo(path)
    except ContentRepoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(EXIT_USAGE)


def report(violations: list[Violation], repo: ContentRepo, tool: str) -> int:
    """Print violations, log the outcome, and return the process exit code."""
    for v in sorted(violations, key=lambda v: (v.file, v.rule)):
        print(v.render())
    if violations:
        print(
            f"\n{tool}: {len(violations)} violation(s) across "
            f"{len({v.file for v in violations})} file(s)",
            file=sys.stderr,
        )
        repo.append_log(f"{tool}: FAIL ({len(violations)} violation(s))")
        return EXIT_VIOLATION
    print(f"{tool}: clean")
    repo.append_log(f"{tool}: PASS")
    return EXIT_OK
