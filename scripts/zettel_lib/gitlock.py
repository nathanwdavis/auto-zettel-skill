"""Distributed run lock held on a branch of the content repo's remote.

A filesystem lock cannot serialize scheduled remote sessions: each firing gets a
fresh container, so neither run can see the other's lock file. This lock lives
in the remote instead, and the mutual exclusion comes from git itself: two
racers both try to advance the lock branch, and the remote accepts exactly one
(the loser gets a non-fast-forward rejection).

Why a branch and not a custom ref: managed remote sessions push through a git
proxy that only permits fast-forward pushes to ordinary branches -- custom
namespaces like ``refs/zettel/*`` and ref DELETIONS are denied (found live).
So the lock is a file, ``LOCK.json``, on the branch ``zettel/lock``: claiming
commits the file, releasing commits its removal, and the branch just accrues a
tiny claim/release history that nobody needs to read.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

LOCK_BRANCH = "zettel/lock"
LOCK_FILE = "LOCK.json"
DEFAULT_TTL_HOURS = 6

# git's well-known empty tree: what the lock branch holds when released.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


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


def _git(repo: Path, *args: str, check: bool = True,
         stdin: str | None = None) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-C", str(repo), *args],
                            capture_output=True, text=True, input=stdin)
    if check and result.returncode != 0:
        raise GitLockError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _remote_tip(repo: Path, remote: str) -> str | None:
    listing = _git(repo, "ls-remote", remote, f"refs/heads/{LOCK_BRANCH}", check=False)
    if listing.returncode != 0 or not listing.stdout.strip():
        return None
    return listing.stdout.split()[0]


def _info_at(repo: Path, commit: str, remote: str) -> LockInfo | None:
    """LockInfo from LOCK.json at ``commit``, or None when released/absent."""
    _git(repo, "fetch", "-q", remote, LOCK_BRANCH, check=False)
    blob = _git(repo, "show", f"{commit}:{LOCK_FILE}", check=False)
    if blob.returncode != 0:
        return None  # no LOCK.json at this commit: the lock is released
    try:
        data = json.loads(blob.stdout)
    except json.JSONDecodeError:
        return LockInfo("unknown", "unknown", "")
    return LockInfo(str(data.get("holder", "unknown")),
                    str(data.get("session", "unknown")),
                    str(data.get("acquired_at", "")))


def _push_state(repo: Path, remote: str, parent: str | None, holder_info: dict | None,
                message: str) -> subprocess.CompletedProcess:
    """Commit a new lock-branch state (file present or absent) and push it."""
    if holder_info is None:
        tree = EMPTY_TREE
    else:
        payload = json.dumps(holder_info, sort_keys=True)
        blob = _git(repo, "hash-object", "-w", "--stdin", stdin=payload).stdout.strip()
        tree = _git(repo, "mktree",
                    stdin=f"100644 blob {blob}\t{LOCK_FILE}\n").stdout.strip()
    args = ["commit-tree", tree, "-m", message]
    if parent:
        args = ["commit-tree", tree, "-p", parent, "-m", message]
    commit = _git(repo, "-c", "user.name=zettel-lock",
                  "-c", "user.email=noreply@localhost", *args).stdout.strip()
    return _git(repo, "push", remote, f"{commit}:refs/heads/{LOCK_BRANCH}", check=False)


def read(repo: Path, remote: str = "origin") -> LockInfo | None:
    """Return the current lock holder, or None when the lock is free."""
    tip = _remote_tip(repo, remote)
    if tip is None:
        return None
    return _info_at(repo, tip, remote)


def claim(repo: Path, holder: str, session: str = "",
          remote: str = "origin") -> tuple[bool, LockInfo | None]:
    """Try to take the lock. Returns ``(acquired, current_holder_if_blocked)``.

    Atomicity is git's: both racers push a child of the same tip, the remote
    fast-forwards exactly one, and the loser's push is rejected.
    """
    tip = _remote_tip(repo, remote)
    if tip is not None:
        current = _info_at(repo, tip, remote)
        if current is not None:
            return False, current

    push = _push_state(repo, remote, tip,
                       {"holder": holder, "session": session, "acquired_at": _now()},
                       f"lock: claim by {holder}")
    if push.returncode == 0:
        return True, None

    # Rejected: either we lost a race (a fresh claim now sits on the branch)
    # or the push itself is impossible (no credential, proxy denial). Found
    # live: reporting the latter as contention hid the real problem.
    current = read(repo, remote)
    if current is not None:
        return False, current
    raise GitLockError(
        "lock push rejected but no lock exists on the remote -- "
        f"push access failure, not contention: {push.stderr.strip()[:400]}")


def release(repo: Path, remote: str = "origin", *, reason: str = "") -> None:
    """Commit the lock file's removal. Safe when the lock is already free.

    ``reason`` goes into the release commit's message on the pushed lock
    branch. It exists because a failed start and a healthy no-op cycle were
    indistinguishable from the repo (issue #7): a no-op push nothing, and a
    crashed start's trap released silently. The lock branch's history is the
    one pushed artifact every cycle touches, so the reason lives there.
    """
    message = "lock: release" + (f" ({reason})" if reason else "")
    for _attempt in range(2):  # one retry: release races are benign
        tip = _remote_tip(repo, remote)
        if tip is None or _info_at(repo, tip, remote) is None:
            return
        push = _push_state(repo, remote, tip, None, message)
        if push.returncode == 0:
            return
    raise GitLockError("could not release the lock after retry")


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
    release(repo, remote, reason=f"stale-broken, was {info.holder}")
    return info
