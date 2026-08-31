"""The skill-impact tracker: parse, append, and defend `skill-impact.md`.

FR-36 requires each proposal's full record — metadata, target skill, unified
diff, A/B scores, and the Accepted/Rejected outcome with a reason — while the
genesis scaffold ships a five-column summary table. Rather than migrate every
existing content repo to a richer table, the file keeps the table as an index
and grows one `##` detail section per event at the end of the file. That is
also why "append-only" here is *semantic*, not byte-prefix (amendment A7):
a new table row lands mid-file, above the detail sections, so the invariant
that can actually be enforced is "every existing record survives byte-identical;
only additions are allowed" — which is what :func:`is_append_only` checks.

This module is the single writer for the file. Every entry point that records
a proposal outcome goes through :func:`append_record`, so the format cannot
drift between the smith, the trial harness, and the review flow.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from .repo import ContentRepo

IMPACT_FILE = "skill-impact.md"

#: The lifecycle events a record can carry. `proposed` and `trial` are interim;
#: `Accepted`/`Rejected` are the FR-36 outcomes (capitalized as the spec writes
#: them). A rejected proposal's record is permanent history and is how
#: "never re-proposed" is checked (AC-36).
EVENTS = ("proposed", "trial", "Accepted", "Rejected")

# The diff fence uses four backticks: a unified diff of note bodies can itself
# contain ``` lines, and a three-backtick fence would terminate early on them.
_FENCE = "````"

_HEADING = re.compile(
    r"^## (?P<pid>\d{12}) (?P<event>proposed|trial|Accepted|Rejected) "
    r"(?P<skill>\S+) \((?P<date>\d{4}-\d{2}-\d{2})\)$"
)
_BULLET = re.compile(r"^- (?P<key>[a-z-]+): ?(?P<value>.*)$")


@dataclass
class Record:
    """One event in a proposal's life, as a detail section + table row."""

    proposal_id: str
    event: str
    skill: str
    date: str = ""
    kind: str = ""  # create | patch, when known
    text: str = ""  # motivation (proposed) or reason (Accepted/Rejected)
    scores: str = ""  # e.g. "with=0.87 without=0.74 (n=3)"
    diff: str = ""
    extra: dict[str, str] = field(default_factory=dict)


class ImpactError(RuntimeError):
    pass


# -- structural split ----------------------------------------------------------

def _split_parts(text: str) -> tuple[str, list[str], str]:
    """Split the file into (head, table rows, tail).

    head ends with the table's `|---|` separator line; rows are the contiguous
    `|`-prefixed lines after it; tail is everything else (the detail sections).
    A file with no table yet degenerates to (text, [], "").
    """
    lines = text.splitlines(keepends=True)
    sep_idx = None
    for i, line in enumerate(lines):
        if line.startswith("|") and set(line.strip()) <= {"|", "-", " ", ":"}:
            sep_idx = i
            break
    if sep_idx is None:
        return text, [], ""
    rows_end = sep_idx + 1
    while rows_end < len(lines) and lines[rows_end].startswith("|"):
        rows_end += 1
    head = "".join(lines[: sep_idx + 1])
    rows = lines[sep_idx + 1 : rows_end]
    tail = "".join(lines[rows_end:])
    return head, rows, tail


def is_append_only(old: str, new: str) -> list[str]:
    """Reasons the change from ``old`` to ``new`` is NOT append-only.

    Additions may land in two places only: new rows at the bottom of the
    summary table, and new detail sections at the end of the file. Everything
    that existed before must survive byte-identical.
    """
    reasons: list[str] = []
    old_head, old_rows, old_tail = _split_parts(old)
    new_head, new_rows, new_tail = _split_parts(new)
    if new_head != old_head:
        reasons.append("header or table heading was rewritten")
    if new_rows[: len(old_rows)] != old_rows:
        reasons.append("an existing table row was edited, reordered, or deleted")
    if not new_tail.startswith(old_tail):
        reasons.append("an existing detail section was edited or deleted")
    return reasons


# -- parsing -------------------------------------------------------------------

def parse(text: str) -> list[Record]:
    """Parse the detail sections into :class:`Record` objects, in file order."""
    records: list[Record] = []
    current: Record | None = None
    in_diff = False
    diff_lines: list[str] = []
    for line in text.splitlines():
        if in_diff:
            if line.strip() == _FENCE:
                assert current is not None
                current.diff = "\n".join(diff_lines)
                in_diff, diff_lines = False, []
            else:
                diff_lines.append(line)
            continue
        m = _HEADING.match(line)
        if m:
            current = Record(
                proposal_id=m["pid"], event=m["event"],
                skill=m["skill"], date=m["date"],
            )
            records.append(current)
            continue
        if current is None:
            continue
        if line.strip() == _FENCE + "diff":
            in_diff = True
            continue
        b = _BULLET.match(line)
        if b:
            key, value = b["key"], b["value"]
            if key == "kind":
                current.kind = value
            elif key in ("motivation", "reason"):
                current.text = value
            elif key == "scores":
                current.scores = value
            else:
                current.extra[key] = value
    return records


def records(repo: ContentRepo) -> list[Record]:
    path = repo.root / IMPACT_FILE
    if not path.exists():
        return []
    return parse(path.read_text(encoding="utf-8"))


def rejected_creates(repo: ContentRepo) -> set[str]:
    """Skill names whose *creation* was rejected — permanently banned (AC-36).

    Name-level and creates-only, per amendment A7: a rejected patch is recorded
    history the smith must read, but it does not freeze the skill forever.
    """
    recs = records(repo)
    kind_by_pid = {r.proposal_id: r.kind for r in recs if r.event == "proposed"}
    banned: set[str] = set()
    for r in recs:
        if r.event != "Rejected":
            continue
        kind = r.kind or kind_by_pid.get(r.proposal_id, "")
        if kind == "create":
            banned.add(r.skill)
    return banned


# -- the single writer ---------------------------------------------------------

def _row_text(record: Record) -> str:
    def cell(s: str) -> str:
        return " ".join(s.split()).replace("|", "\\|")

    outcome = record.event
    reason = record.scores if record.event == "trial" else record.text
    return (
        f"| {record.date} | {record.proposal_id} | {cell(record.skill)} "
        f"| {outcome} | {cell(reason)} |\n"
    )


def _section_text(record: Record) -> str:
    lines = [
        f"## {record.proposal_id} {record.event} {record.skill} ({record.date})",
        "",
    ]
    if record.kind:
        lines.append(f"- kind: {record.kind}")
    if record.text:
        label = "motivation" if record.event == "proposed" else "reason"
        lines.append(f"- {label}: " + " ".join(record.text.split()))
    if record.scores:
        lines.append(f"- scores: {record.scores}")
    for key, value in sorted(record.extra.items()):
        lines.append(f"- {key}: " + " ".join(str(value).split()))
    if record.diff:
        lines.append("")
        lines.append(_FENCE + "diff")
        lines.append(record.diff.rstrip("\n"))
        lines.append(_FENCE)
    return "\n".join(lines) + "\n"


def append_record(repo: ContentRepo, record: Record) -> None:
    """Append one event to skill-impact.md: a table row plus a detail section."""
    if record.event not in EVENTS:
        raise ImpactError(f"unknown event '{record.event}' (allowed: {EVENTS})")
    if not record.date:
        record.date = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    path = repo.root / IMPACT_FILE
    if not path.exists():
        raise ImpactError(f"missing {IMPACT_FILE} in {repo.root}")
    old = path.read_text(encoding="utf-8")
    head, rows, tail = _split_parts(old)
    if tail and not tail.endswith("\n"):
        tail += "\n"
    new = head + "".join(rows) + _row_text(record) + tail + "\n" + _section_text(record)
    # Belt and braces: the writer must itself satisfy the invariant the
    # sandbox gate enforces, or a future format change silently breaks CI.
    reasons = is_append_only(old, new)
    if reasons:
        raise ImpactError("append_record broke append-only: " + "; ".join(reasons))
    path.write_text(new, encoding="utf-8")
