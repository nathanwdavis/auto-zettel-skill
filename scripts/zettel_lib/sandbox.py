"""FR-37 sandbox classification: what a cycle's diff was allowed to touch.

A `claude` session's writes cannot be intercepted in-process, so the sandbox
is enforced post-hoc by inspecting the git diff a run produced (amendment A7).
Two granularities share this one classifier:

- **strict** — applied to the skill-smith's isolated diff: the smith may touch
  only `skills/`, one append to `skill-impact.md`, and `log.md`. Anything else
  is a `sandbox-escape` (AC-37).
- **non-strict** — applied to a whole cycle, where other agents legitimately
  edit notes: only the invariants that hold for *everyone* are checked —
  `log.md` is byte-prefix append-only, `skill-impact.md` is semantically
  append-only (see :mod:`zettel_lib.impact`), and `raw/` captures are
  immutable (FR-33: additions fine, edits and deletions never).

The plugin-repo half of AC-37 ("never write to the skill repo") is structural:
`maintenance_run.sh` snapshots the plugin tree around the headless run, and in
remote mode the plugin is a fresh CI checkout no session can reach.
"""

from __future__ import annotations

import subprocess
from pathlib import PurePosixPath

from .cli import Violation
from .repo import ContentRepo

#: The skill layer plus its two append-only ledgers — all a smith may write.
ALLOWED_FILES = ("skill-impact.md", "log.md")
ALLOWED_DIR = "skills"


class SandboxError(RuntimeError):
    """A git failure (bad base ref, not a repository) — a usage error, not a finding."""


def _git(repo: ContentRepo, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo.root), *args],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SandboxError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def _show_at_base(repo: ContentRepo, base_ref: str, path: str) -> str | None:
    proc = subprocess.run(
        ["git", "-C", str(repo.root), "show", f"{base_ref}:{path}"],
        capture_output=True, text=True,
    )
    return proc.stdout if proc.returncode == 0 else None


def changed_paths(repo: ContentRepo, base_ref: str) -> list[tuple[str, str]]:
    """(status, path) pairs for base..worktree, untracked files included as adds."""
    out: list[tuple[str, str]] = []
    for line in _git(repo, "diff", "--name-status", base_ref).splitlines():
        parts = line.split("\t")
        if not parts or not parts[0]:
            continue
        status = parts[0][0]  # M/A/D; R100 -> R, C100 -> C
        # For a rename both sides count: the old path was effectively deleted.
        if status in ("R", "C") and len(parts) == 3:
            out.append(("D" if status == "R" else "A", parts[1]))
            out.append(("A", parts[2]))
        else:
            out.append((status, parts[-1]))
    for line in _git(repo, "ls-files", "--others", "--exclude-standard").splitlines():
        if line:
            out.append(("A", line))
    return out


def _is_allowed(path: str) -> bool:
    p = PurePosixPath(path)
    return path in ALLOWED_FILES or (p.parts and p.parts[0] == ALLOWED_DIR)


def classify_changes(
    repo: ContentRepo, base_ref: str, strict: bool = False
) -> list[Violation]:
    from . import impact  # local import: impact has no dependency back on us

    violations: list[Violation] = []
    changes = changed_paths(repo, base_ref)

    for status, path in changes:
        top = PurePosixPath(path).parts[0] if PurePosixPath(path).parts else ""
        if strict and not _is_allowed(path):
            violations.append(Violation(
                path, "sandbox-escape",
                "the skill-smith may write only under skills/ plus "
                "skill-impact.md and log.md (FR-37)"))
        if top == "raw" and status in ("M", "D") and path != "raw/.gitkeep":
            violations.append(Violation(
                path, "raw-modified",
                "raw/ captures are immutable; additions only (FR-33)"))

    changed_files = {path for _, path in changes}

    if "log.md" in changed_files:
        old = _show_at_base(repo, base_ref, "log.md")
        new_path = repo.root / "log.md"
        new = new_path.read_text(encoding="utf-8") if new_path.exists() else None
        if old is not None and (new is None or not new.startswith(old)):
            violations.append(Violation(
                "log.md", "log-rewritten",
                "log.md must only ever grow; an existing line was edited "
                "or removed (NFR-2)"))

    if "skill-impact.md" in changed_files:
        old = _show_at_base(repo, base_ref, "skill-impact.md")
        new_path = repo.root / "skill-impact.md"
        if old is not None:
            if not new_path.exists():
                violations.append(Violation(
                    "skill-impact.md", "skill-impact-rewritten",
                    "skill-impact.md was deleted; it is permanent history (FR-36)"))
            else:
                for reason in impact.is_append_only(
                    old, new_path.read_text(encoding="utf-8")
                ):
                    violations.append(Violation(
                        "skill-impact.md", "skill-impact-rewritten",
                        reason + " (FR-36)"))

    return violations
