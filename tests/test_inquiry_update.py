"""capture.py inquiry-update: moving a question along its FR-6 lifecycle.

Closing an inquiry used to mean hand-editing YAML, which is how the two rules
with teeth get broken: `answered` with nothing to point at (AC-6), and a
`result_notes` entry that is not a permanent note. Both are checked here
BEFORE anything is written, so a refused update leaves the inquiry exactly as
it was rather than half-changed into a state the lint then rejects.

The manifest indexes an inquiry's status and result notes, so every accepted
update must also rebuild it -- otherwise the next `build_manifest --check`
goes red on a PR that only moved a status.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import LIT_KEY, PERM_KEY, SCRIPTS, build_clean_repo, run_script
from zettel_lib.frontmatter import Note

CAPTURE = SCRIPTS / "capture.py"


def capture(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CAPTURE), "--repo", str(repo), *args],
        capture_output=True, text=True, input=stdin,
    )


@pytest.fixture
def repo(tmp_path) -> Path:
    return build_clean_repo(tmp_path / "kb")


@pytest.fixture
def inquiry(repo) -> str:
    """A fresh `new` inquiry, returned as its key."""
    result = capture(repo, "inquiry", "Does an updated inquiry stay gate-clean?")
    assert result.returncode == 0, result.stderr
    return Path(result.stdout.strip()).stem


def load_inquiry(repo: Path, key: str) -> Note:
    return Note.load(repo / "inquiries" / f"{key}.md")


# --- the two rules with teeth -------------------------------------------------

def test_answered_requires_a_permanent_result_note(repo, inquiry):
    result = capture(repo, "inquiry-update", inquiry, "--status", "answered")
    assert result.returncode == 2
    assert "AC-6" in result.stderr
    assert load_inquiry(repo, inquiry).status == "new", "refused updates change nothing"


def test_result_note_must_be_a_permanent_note(repo, inquiry):
    result = capture(repo, "inquiry-update", inquiry, "--status", "answered",
                     "--result-notes", LIT_KEY)
    assert result.returncode == 2
    assert "literature" in result.stderr and "only permanent notes answer" in result.stderr
    assert load_inquiry(repo, inquiry).result_notes == []


def test_result_note_must_resolve(repo, inquiry):
    result = capture(repo, "inquiry-update", inquiry, "--result-notes", "missing--209901010101")
    assert result.returncode == 2 and "resolves to no note" in result.stderr


def test_a_refused_update_leaves_the_manifest_current(repo, inquiry):
    capture(repo, "inquiry-update", inquiry, "--status", "answered")
    assert run_script("build_manifest.py", repo, "--check").returncode == 0


# --- the accepted path --------------------------------------------------------

def test_update_sets_status_appends_the_note_and_rebuilds_the_manifest(repo, inquiry):
    result = capture(repo, "inquiry-update", inquiry, "--status", "in-progress",
                     "--note", "Half the sources are captured.")
    assert result.returncode == 0
    note = load_inquiry(repo, inquiry)
    assert note.status == "in-progress"
    assert "Half the sources are captured." in note.body
    assert run_script("build_manifest.py", repo, "--check").returncode == 0
    manifest = json.loads((repo / "manifest.json").read_text(encoding="utf-8"))
    indexed = next(i for i in manifest["inquiries"] if i["key"] == inquiry)
    assert indexed["status"] == "in-progress"


def test_answering_with_a_permanent_note_keeps_every_gate_green(repo, inquiry):
    result = capture(repo, "inquiry-update", inquiry, "--status", "answered",
                     "--result-notes", PERM_KEY)
    assert result.returncode == 0
    assert load_inquiry(repo, inquiry).result_notes == [PERM_KEY]
    for gate in ("build_manifest.py", "lint_citations.py", "lint_links.py"):
        assert run_script(gate, repo).returncode == 0, gate


def test_result_notes_merge_and_never_duplicate(repo, inquiry):
    capture(repo, "inquiry-update", inquiry, "--result-notes", PERM_KEY)
    capture(repo, "inquiry-update", inquiry, "--result-notes", PERM_KEY)
    assert load_inquiry(repo, inquiry).result_notes == [PERM_KEY]


def test_update_accepts_a_bare_id(repo, inquiry):
    result = capture(repo, "inquiry-update", inquiry.split("--")[1], "--status", "archived")
    assert result.returncode == 0
    assert load_inquiry(repo, inquiry).status == "archived"


def test_archived_needs_no_result_notes(repo, inquiry):
    """A9: a question may be closed as no longer worth answering."""
    assert capture(repo, "inquiry-update", inquiry, "--status", "archived").returncode == 0
    assert run_script("lint_links.py", repo).returncode == 0


def test_update_bumps_updated(repo, inquiry):
    before = load_inquiry(repo, inquiry)
    before.meta["updated"] = "2020-01-01"
    before.save()
    capture(repo, "inquiry-update", inquiry, "--status", "in-progress")
    assert load_inquiry(repo, inquiry).meta["updated"] != "2020-01-01"


def test_note_reads_from_stdin(repo, inquiry):
    result = capture(repo, "inquiry-update", inquiry, "--note", "-", stdin="piped reasoning")
    assert result.returncode == 0
    assert "piped reasoning" in load_inquiry(repo, inquiry).body


def test_update_is_logged_with_the_transition(repo, inquiry):
    capture(repo, "inquiry-update", inquiry, "--status", "in-progress")
    capture(repo, "inquiry-update", inquiry, "--status", "answered",
            "--result-notes", PERM_KEY)
    log = (repo / "log.md").read_text(encoding="utf-8")
    assert f"capture: inquiry-update {inquiry} status=new->in-progress" in log
    assert f"result_notes=+{PERM_KEY}" in log


def test_json_output_reports_the_transition(repo, inquiry):
    result = capture(repo, "--json", "inquiry-update", inquiry, "--status", "answered",
                     "--result-notes", PERM_KEY)
    payload = json.loads(result.stdout)
    assert payload["status"] == "answered"
    assert payload["added"] == [PERM_KEY]


# --- usage --------------------------------------------------------------------

def test_update_with_nothing_to_change_is_a_usage_error(repo, inquiry):
    result = capture(repo, "inquiry-update", inquiry)
    assert result.returncode == 2 and "nothing to change" in result.stderr


def test_unknown_inquiry_is_a_usage_error(repo):
    result = capture(repo, "inquiry-update", "no-such--209901010101", "--status", "new")
    assert result.returncode == 2 and "no inquiry matches" in result.stderr


def test_bad_status_is_a_usage_error(repo, inquiry):
    result = capture(repo, "inquiry-update", inquiry, "--status", "done")
    assert result.returncode == 2


def test_inquiries_py_stays_read_only(repo, inquiry):
    """A9: the reporter reports; the writer is capture.py."""
    result = run_script("inquiries.py", repo, "--status", "new")
    assert result.returncode == 0 and inquiry in result.stdout
    assert "--status" in run_script("inquiries.py", repo, "--help").stdout
    assert "set" not in run_script("inquiries.py", repo, "--help").stdout.split("options:")[0]
