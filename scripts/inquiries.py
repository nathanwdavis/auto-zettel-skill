#!/usr/bin/env python3
"""List the open questions in a content repo (FR-6).

Read-only, and deliberately so: a maintenance run decides which inquiries to
work and moves their status itself. This just answers "what is outstanding?"
without anyone having to parse markdown -- for a run picking its next job, or
for a human wondering whether last week's question ever landed.

    inquiries.py --repo <path> [--status new] [--json]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib.cli import EXIT_OK, EXIT_USAGE, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError
from zettel_lib.repo import INQUIRY_STATUSES, ContentRepo, ContentRepoError

#: `new` first, then work in progress: the order a run should pick jobs in.
#: Archived sorts last because it is history, not a queue.
STATUS_ORDER = {s: i for i, s in enumerate(INQUIRY_STATUSES)}
PRIORITY_ORDER = {"high": 0, "normal": 1, "low": 2}


def collect(repo: ContentRepo, status: str | None = None) -> list[dict]:
    rows = []
    for inquiry in repo.inquiries():
        if status and inquiry.status != status:
            continue
        rows.append({
            "key": inquiry.key,
            "question": inquiry.question,
            "status": inquiry.status,
            "priority": inquiry.priority or "normal",
            "result_notes": inquiry.result_notes,
            "path": repo.rel(inquiry.path),
        })
    rows.sort(key=lambda r: (STATUS_ORDER.get(r["status"], len(STATUS_ORDER)),
                             PRIORITY_ORDER.get(r["priority"], 1),
                             r["key"]))
    return rows


def render(rows: list[dict]) -> str:
    if not rows:
        return "inquiries: none"
    lines = []
    for row in rows:
        answered = f"  -> {', '.join(row['result_notes'])}" if row["result_notes"] else ""
        lines.append(f"{row['status']}\t{row['priority']}\t{row['key']}\t"
                     f"{row['question']}{answered}")
    lines.append(f"\ninquiries: {len(rows)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("--status", choices=list(INQUIRY_STATUSES),
                        help="show only inquiries in this state")
    parser.add_argument("--json", action="store_true",
                        help="emit JSON, for programmatic callers")
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)

    try:
        rows = collect(repo, args.status)
    except (ContentRepoError, FrontmatterError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    print(json.dumps(rows, indent=2, ensure_ascii=False) if args.json else render(rows))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
