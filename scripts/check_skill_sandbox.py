#!/usr/bin/env python3
"""Skill-sandbox gate: a cycle's diff may not escape the FR-37 rails (AC-37).

Run with ``--base <ref>`` naming the commit the cycle started from. Non-strict
(the default) enforces the invariants that hold for a whole cycle regardless
of which agent wrote what: log.md byte-prefix append-only, skill-impact.md
semantically append-only, raw/ immutable. ``--strict`` additionally rejects
ANY change outside skills/ + those two ledgers, and is meant for the
skill-smith's isolated diff before it merges.

"Blocked and logged": a violation exits 1 (so the Mode-A wrapper refuses to
push and the Mode-B required check refuses the PR) and the outcome is appended
to the content repo's log.md by the shared reporter.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib.cli import EXIT_USAGE, base_parser, open_repo, report
from zettel_lib.sandbox import SandboxError, classify_changes


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument(
        "--base", required=True,
        help="git ref the cycle started from (e.g. the pre-run HEAD)")
    parser.add_argument(
        "--strict", action="store_true",
        help="reject any change outside skills/, skill-impact.md, log.md "
             "(for the skill-smith's isolated diff)")
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)
    try:
        violations = classify_changes(repo, args.base, strict=args.strict)
    except SandboxError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    return report(violations, repo, "check_skill_sandbox")


if __name__ == "__main__":
    raise SystemExit(main())
