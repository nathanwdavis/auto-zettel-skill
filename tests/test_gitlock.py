"""Distributed run lock over a git ref (remote-execution replacement for run.lock).

Two clones of one bare origin stand in for two scheduled containers, which is
exactly the situation a filesystem lock cannot handle.
"""

from __future__ import annotations

import datetime as _dt
import json
import subprocess

import pytest

from zettel_lib import gitlock


@pytest.fixture
def two_containers(tmp_path):
    """A bare origin plus two independent clones, seeded with one commit."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)

    clones = []
    for name in ("container-a", "container-b"):
        path = tmp_path / name
        subprocess.run(["git", "clone", "-q", str(origin), str(path)], check=True)
        for key, value in (("user.name", "t"), ("user.email", "t@localhost")):
            subprocess.run(["git", "-C", str(path), "config", key, value], check=True)
        clones.append(path)

    seed = clones[0]
    (seed / "seed.txt").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(seed), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(seed), "commit", "-qm", "seed"], check=True)
    subprocess.run(["git", "-C", str(seed), "push", "-q", "origin", "main"], check=True)
    subprocess.run(["git", "-C", str(clones[1]), "pull", "-q", "origin", "main"], check=True)
    return clones[0], clones[1]


# --- mutual exclusion ---------------------------------------------------------

def test_first_claim_wins_and_second_is_blocked(two_containers):
    a, b = two_containers
    acquired_a, blocker = gitlock.claim(a, "run-A", "sess-1")
    assert acquired_a is True and blocker is None

    acquired_b, blocker = gitlock.claim(b, "run-B", "sess-2")
    assert acquired_b is False, "two containers must never both hold the lock"
    assert blocker is not None


def test_blocked_run_can_name_the_holder(two_containers):
    """A blocked run has to be able to say who holds the lock, for the log."""
    a, b = two_containers
    gitlock.claim(a, "run-A", "sess-1")
    _, blocker = gitlock.claim(b, "run-B", "sess-2")
    assert blocker.holder == "run-A"
    assert blocker.session == "sess-1"
    assert blocker.acquired_at.endswith("Z")


def test_release_frees_the_lock_for_the_other_container(two_containers):
    a, b = two_containers
    gitlock.claim(a, "run-A")
    gitlock.release(a)
    assert gitlock.read(b) is None
    acquired, _ = gitlock.claim(b, "run-B")
    assert acquired is True


def test_release_is_safe_when_no_lock_is_held(two_containers):
    a, _ = two_containers
    gitlock.release(a)  # must not raise
    assert gitlock.read(a) is None


def test_read_returns_none_when_free(two_containers):
    a, _ = two_containers
    assert gitlock.read(a) is None


# --- staleness ----------------------------------------------------------------

def test_a_live_lock_is_never_broken(two_containers):
    """Stealing a live lock would make two sessions do (and bill for) the same work."""
    a, b = two_containers
    gitlock.claim(a, "run-A")
    assert gitlock.break_stale(b, ttl_hours=6) is None
    assert gitlock.read(b) is not None, "the live lock must survive"


def test_stale_lock_is_broken_and_reported(two_containers):
    a, b = two_containers
    gitlock.claim(a, "run-A", "sess-1")
    broken = gitlock.break_stale(b, ttl_hours=0)
    assert broken is not None and broken.holder == "run-A"
    assert gitlock.read(b) is None
    acquired, _ = gitlock.claim(b, "run-B")
    assert acquired is True


def test_break_stale_on_a_free_lock_is_a_noop(two_containers):
    a, _ = two_containers
    assert gitlock.break_stale(a, ttl_hours=0) is None


@pytest.mark.parametrize("stamp,expected_ancient", [
    ("not-a-timestamp", True),
    ("", True),
])
def test_unparseable_timestamps_count_as_ancient(stamp, expected_ancient):
    """A corrupt lock must be breakable, not permanently wedge the schedule."""
    info = gitlock.LockInfo("h", "s", stamp)
    assert (info.age_hours() == float("inf")) is expected_ancient


def test_age_is_computed_from_the_recorded_timestamp():
    then = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=3)
    info = gitlock.LockInfo("h", "s", then.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert 2.9 < info.age_hours() < 3.1


# --- payload ------------------------------------------------------------------

def test_lock_blob_is_valid_json_with_the_expected_fields(two_containers):
    a, _ = two_containers
    gitlock.claim(a, "run-A", "sess-1")
    sha = subprocess.run(["git", "-C", str(a), "ls-remote", "origin", gitlock.LOCK_REF],
                         capture_output=True, text=True, check=True).stdout.split()[0]
    subprocess.run(["git", "-C", str(a), "fetch", "-q", "origin", gitlock.LOCK_REF], check=True)
    blob = subprocess.run(["git", "-C", str(a), "cat-file", "-p", sha],
                          capture_output=True, text=True, check=True).stdout
    data = json.loads(blob)
    assert set(data) == {"holder", "session", "acquired_at"}


def test_lock_does_not_disturb_the_branch(two_containers):
    """The lock is a detached ref; it must not appear as a commit on main."""
    a, _ = two_containers
    before = subprocess.run(["git", "-C", str(a), "rev-parse", "main"],
                            capture_output=True, text=True, check=True).stdout
    gitlock.claim(a, "run-A")
    after = subprocess.run(["git", "-C", str(a), "rev-parse", "main"],
                           capture_output=True, text=True, check=True).stdout
    assert before == after
