"""Distributed run lock held in the content repo's git remote.

A filesystem lock cannot serialize scheduled remote sessions: each firing gets a
fresh container, so neither run can see the other's lock file. This lock lives
in the remote instead, and the mutual exclusion comes from git itself -- pushing
a ref that already exists is rejected non-fast-forward, and only one racer's
push can win.

The lock ref holds a small JSON blob (holder, session, ISO timestamp) so a
blocked run can report *who* holds it, and so a lock left behind by a crashed
container can be broken once it is provably stale.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

LOCK_REF = "refs/zettel/run-lock"
DEFAULT_TTL_HOURS = 6


@dataclass(frozen=True)
class LockInfo:
    holder: str
    session: str
    acquired_at: str

    def age_hours(self, now: _dt.datetime | None = None) -> float:
        now = now or _dt.datetime.now(_dt.timezone.utc)
        try:
            then = _dt.datetime.fromisoformat(self.acquired_at.replace("Z", "+00:00"))
        except ValueError:
            return float("inf")  # unparseable timestamp: treat as ancient
        return (now - then).total_seconds() / 3600.0


class GitLockError(RuntimeError):
    pass


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True)
    if check and result.returncode != 0:
        raise GitLockError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read(repo: Path, remote: str = "origin") -> LockInfo | None:
    """Return the current lock holder, or None when the lock is free."""
    listing = _git(repo, "ls-remote", remote, LOCK_REF, check=False)
    if listing.returncode != 0 or not listing.stdout.strip():
        return None
    sha = listing.stdout.split()[0]
    # Fetch the object so it can be read; a blob is tiny.
    _git(repo, "fetch", "-q", remote, LOCK_REF, check=False)
    blob = _git(repo, "cat-file", "-p", sha, check=False)
    if blob.returncode != 0:
        return LockInfo("unknown", "unknown", "")
    try:
        data = json.loads(blob.stdout)
    except json.JSONDecodeError:
        return LockInfo("unknown", "unknown", "")
    return LockInfo(str(data.get("holder", "unknown")),
                    str(data.get("session", "unknown")),
                    str(data.get("acquired_at", "")))


def claim(repo: Path, holder: str, session: str = "",
          remote: str = "origin") -> tuple[bool, LockInfo | None]:
    """Try to take the lock. Returns ``(acquired, current_holder_if_blocked)``.

    Atomicity is git's: the push creates the ref only if it does not exist, and
    a concurrent racer's identical attempt is rejected by the remote.
    """
    payload = json.dumps({"holder": holder, "session": session,
                          "acquired_at": _now()}, sort_keys=True)
    result = subprocess.run(["git", "-C", str(repo), "hash-object", "-w", "--stdin"],
                            input=payload, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitLockError(f"could not write lock blob: {result.stderr.strip()}")
    sha = result.stdout.strip()

    push = _git(repo, "push", remote, f"{sha}:{LOCK_REF}", check=False)
    if push.returncode == 0:
        return True, None
    return False, read(repo, remote)


def release(repo: Path, remote: str = "origin") -> None:
    """Delete the lock ref. Safe to call when the lock is already gone."""
    _git(repo, "push", remote, "--delete", LOCK_REF, check=False)


def break_stale(repo: Path, ttl_hours: float = DEFAULT_TTL_HOURS,
                remote: str = "origin") -> LockInfo | None:
    """Force-release a lock older than ``ttl_hours``. Returns what was broken.

    A live lock is never broken -- a run that finds a fresh lock must exit, not
    steal it, or two sessions research the same inquiry and pay for it twice.
    """
    info = read(repo, remote)
    if info is None:
        return None
    if info.age_hours() < ttl_hours:
        return None
    release(repo, remote)
    return info
