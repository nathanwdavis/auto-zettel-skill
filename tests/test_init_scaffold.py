"""Genesis scaffolding: the FR-1 substrate, config keys, and safety rails (FR-18, AC-1)."""

from __future__ import annotations

import subprocess
import sys

import pytest
import yaml

from conftest import SCRIPTS

INIT = SCRIPTS / "init_content_repo.sh"

EXPECTED_FILES = {
    "INBOX.md", "INDEX.md", "manifest.json", "config.yml", "log.md",
    "skill-impact.md", "README.md", ".gitignore", ".bib/refs.json",
}
EXPECTED_DIRS = {
    "fleeting", "literature", "permanent", "reference", "moc",
    "inquiries", "raw", "skills", "proposed-links", ".bib",
}


def scaffold(tmp_path, *extra, name="kb-smoke", visibility="public"):
    target = tmp_path / name
    return subprocess.run(
        [str(INIT), "--name", name, "--visibility", visibility,
         "--owner", "example", "--topics", "alpha topic, beta topic",
         "--dir", str(target), "--no-remote", *extra],
        capture_output=True, text=True,
        env={"PATH": f"{sys.prefix}/bin:/usr/bin:/bin", "HOME": str(tmp_path)},
    ), target


@pytest.fixture
def scaffolded(tmp_path):
    result, target = scaffold(tmp_path)
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    return target


def tracked(repo) -> set[str]:
    out = subprocess.run(["git", "-C", str(repo), "ls-files"],
                         capture_output=True, text=True, check=True).stdout
    return set(out.split())


# --- AC-1 ---------------------------------------------------------------------

def test_every_substrate_path_is_committed(scaffolded):
    files = tracked(scaffolded)
    missing = EXPECTED_FILES - files
    assert not missing, f"substrate files missing from git: {sorted(missing)}"
    for directory in EXPECTED_DIRS:
        assert any(f.startswith(f"{directory}/") for f in files), \
            f"{directory}/ is not represented in git"


def test_run_lock_is_ignored_not_tracked(scaffolded):
    assert "run.lock" not in tracked(scaffolded)
    assert "run.lock" in (scaffolded / ".gitignore").read_text(encoding="utf-8")


def test_initial_commit_exists(scaffolded):
    log = subprocess.run(["git", "-C", str(scaffolded), "log", "--oneline"],
                         capture_output=True, text=True, check=True).stdout
    assert "Genesis" in log


# --- AC-2 ---------------------------------------------------------------------

def test_config_carries_every_required_key(scaffolded):
    cfg = yaml.safe_load((scaffolded / "config.yml").read_text(encoding="utf-8"))
    for key in ("topics", "cadence", "budget", "autonomy_level", "content_repo",
                "embedding", "models", "connector_cadence", "skill_smith_cadence"):
        assert key in cfg, f"config.yml missing {key}"
    assert cfg["topics"] == ["alpha topic", "beta topic"]
    assert set(cfg["budget"]) >= {"usd", "max_turns"}
    assert set(cfg["content_repo"]) >= {"name", "owner", "visibility"}
    assert set(cfg["models"]) >= {"strong", "cheap"}


def test_missing_required_config_key_hard_fails_with_a_clear_message(scaffolded):
    cfg = yaml.safe_load((scaffolded / "config.yml").read_text(encoding="utf-8"))
    del cfg["content_repo"]["visibility"]
    (scaffolded / "config.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "build_manifest.py"), "--repo", str(scaffolded)],
        capture_output=True, text=True)
    assert result.returncode != 0
    assert "content_repo.visibility" in result.stderr


# --- FR-18 safety rails -------------------------------------------------------

def test_refuses_to_overwrite_a_non_empty_directory(tmp_path):
    target = tmp_path / "kb-smoke"
    target.mkdir()
    (target / "precious.txt").write_text("do not clobber me", encoding="utf-8")

    result, _ = scaffold(tmp_path)
    assert result.returncode != 0
    assert "refusing to overwrite" in result.stderr
    assert (target / "precious.txt").read_text(encoding="utf-8") == "do not clobber me"


@pytest.mark.parametrize("visibility", ["", "internal", "publik"])
def test_rejects_an_invalid_visibility(tmp_path, visibility):
    result, _ = scaffold(tmp_path, visibility=visibility)
    assert result.returncode != 0
    assert "--visibility" in result.stderr


def test_missing_required_argument_is_rejected(tmp_path):
    result = subprocess.run(
        [str(INIT), "--name", "kb", "--visibility", "public", "--no-remote"],
        capture_output=True, text=True)
    assert result.returncode != 0
    assert "--owner is required" in result.stderr


def test_help_exits_zero():
    result = subprocess.run([str(INIT), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Usage:" in result.stdout


# --- the scaffold is lint-clean -----------------------------------------------

def test_fresh_scaffold_passes_both_lints(scaffolded):
    for script in ("lint_citations.py", "lint_links.py"):
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / script), "--repo", str(scaffolded)],
            capture_output=True, text=True)
        assert result.returncode == 0, f"{script}:\n{result.stdout}\n{result.stderr}"
