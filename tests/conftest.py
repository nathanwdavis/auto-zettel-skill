"""Fixture builders for a clean content repo and its planted-violation variants.

The clean repo is built programmatically rather than checked in as static files
so every violation fixture is provably "the clean repo with exactly one thing
broken", and so the reference note's Chicago strings are always self-consistent
with its CSL-JSON.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PLUGIN_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from zettel_lib import citations  # noqa: E402
from zettel_lib.frontmatter import Note, dump  # noqa: E402

REF_ID = "202608301000"
LIT_ID = "202608301100"
PERM_ID = "202608301200"
MOC_ID = "202608301300"

REF_KEY = f"ahrens-how-to-take-smart-notes--{REF_ID}"
LIT_KEY = f"ahrens-on-the-slip-box-workflow--{LIT_ID}"
PERM_KEY = f"atomic-notes-compound-over-time--{PERM_ID}"
MOC_KEY = f"zettelkasten-method--{MOC_ID}"

CSL = {
    "id": REF_ID,
    "type": "book",
    "title": "How to Take Smart Notes",
    "author": [{"family": "Ahrens", "given": "Sönke"}],
    "issued": {"date-parts": [[2017]]},
    "publisher": "CreateSpace",
    "publisher-place": "North Charleston, SC",
    "ISBN": "9781542866507",
}

CONFIG = {
    "topics": ["zettelkasten method"],
    "cadence": "weekly",
    "budget": {"usd": 5, "max_turns": 40},
    "autonomy_level": "suggest",
    "content_repo": {"name": "kb-fixture", "owner": "example", "visibility": "public"},
    "embedding": {"enabled": False, "model": "sentence-transformers/all-MiniLM-L6-v2"},
    "models": {"strong": "claude-opus-5", "cheap": "claude-haiku-4-5-20251001"},
    "connector_cadence": "weekly",
    "skill_smith_cadence": "monthly",
}


def _write(path: Path, meta: dict, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(meta, body), encoding="utf-8")


def build_clean_repo(root: Path) -> Path:
    """Create a minimal content repo that passes every lint."""
    for d in ("fleeting", "literature", "permanent", "reference", "moc",
              "inquiries", "raw", "skills", "proposed-links", ".bib"):
        (root / d).mkdir(parents=True, exist_ok=True)

    (root / "config.yml").write_text(yaml.safe_dump(CONFIG, sort_keys=False), encoding="utf-8")
    (root / "log.md").write_text("# Operation log\n", encoding="utf-8")
    (root / "INBOX.md").write_text("# Inbox\n", encoding="utf-8")
    (root / "INDEX.md").write_text(
        f"# Index\n\n## Maps of Content\n\n- [[{MOC_KEY}]]\n", encoding="utf-8")

    capture = Path("raw") / f"{REF_ID}-ahrens-smart-notes.txt"
    (root / capture).write_text(
        "Verbatim capture of the source, fetched at genesis.\n", encoding="utf-8")

    rendered = citations.render(CSL)
    _write(root / "reference" / f"{REF_KEY}.md", {
        "id": REF_ID, "key": REF_KEY, "slug": REF_KEY.rsplit("--", 1)[0],
        "aliases": [REF_ID], "type": "reference",
        "title": "Ahrens, How to Take Smart Notes",
        "tags": [], "source_tier": "reputable-secondary", "scripture": False,
        "csl_json": CSL,
        "chicago_note": rendered.note,
        "chicago_bib": rendered.bib,
        "citation_renderer": rendered.backend,
        "verification": {"method": "raw-capture", "source": str(capture),
                         "verified": True, "date": "2026-08-30T10:00:00Z"},
        "raw_capture": str(capture),
        "links": [],
        "created": "2026-08-30", "updated": "2026-08-30",
    }, "Bibliographic record.\n")

    _write(root / "literature" / f"{LIT_KEY}.md", {
        "id": LIT_ID, "key": LIT_KEY, "slug": LIT_KEY.rsplit("--", 1)[0],
        "aliases": [LIT_ID], "type": "literature",
        "title": "Ahrens on the slip-box workflow",
        "tags": [], "reference": REF_KEY, "locator": "pp. 12-30",
        "links": [{"target_id": REF_KEY, "relation": "source"}],
        "created": "2026-08-30", "updated": "2026-08-30",
    }, f"Own-words summary of [[{REF_KEY}]].\n")

    _write(root / "permanent" / f"{PERM_KEY}.md", {
        "id": PERM_ID, "key": PERM_KEY, "slug": PERM_KEY.rsplit("--", 1)[0],
        "aliases": [PERM_ID], "type": "permanent",
        "title": "Atomic notes compound over time",
        "tags": [],
        "links": [{"target_id": REF_KEY, "relation": "source"},
                  {"target_id": LIT_KEY, "relation": "elaborates"}],
        "created": "2026-08-30", "updated": "2026-08-30",
    }, f"A note confined to one idea can be reused in contexts its author never "
       f"anticipated. Ahrens argues that this is what makes a slip-box compound "
       f"rather than merely accumulate: [[{REF_KEY}]].\n")

    _write(root / "moc" / f"{MOC_KEY}.md", {
        "id": MOC_ID, "key": MOC_KEY, "slug": MOC_KEY.rsplit("--", 1)[0],
        "aliases": [MOC_ID], "type": "moc", "title": "Zettelkasten method",
        "tags": ["moc"], "links": [],
        "created": "2026-08-30", "updated": "2026-08-30",
    }, f"# Zettelkasten method\n\n## Notes\n\n- [[{PERM_KEY}]]\n")

    run_script("build_manifest.py", root)
    return root


def run_script(name: str, repo: Path, *args: str) -> subprocess.CompletedProcess:
    """Invoke one of the plugin's scripts against a repo, capturing output."""
    return subprocess.run(
        [sys.executable, str(SCRIPTS / name), "--repo", str(repo), *args],
        capture_output=True, text=True,
    )


def load(repo: Path, rel: str) -> Note:
    return Note.load(repo / rel)


def rules(result: subprocess.CompletedProcess) -> set[str]:
    """Parse the FILE\\tRULE\\tREASON lines out of a lint's stdout."""
    return {
        line.split("\t")[1]
        for line in result.stdout.splitlines()
        if line.count("\t") >= 2
    }


@pytest.fixture
def clean_repo(tmp_path: Path) -> Path:
    return build_clean_repo(tmp_path / "kb")


@pytest.fixture
def broken_repo(clean_repo: Path):
    """Yields a mutator that breaks the clean repo, then rebuilds the manifest."""

    def _break(mutate, rebuild: bool = True) -> Path:
        mutate(clean_repo)
        if rebuild:
            run_script("build_manifest.py", clean_repo)
        return clean_repo

    return _break
