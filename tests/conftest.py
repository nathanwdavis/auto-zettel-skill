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
    "models": {"strong": "claude-opus-5", "cheap": "claude-sonnet-5"},
    "connector_cadence": "weekly",
    "skill_smith_cadence": "monthly",
    "trial_questions": 3,
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
    (root / "skill-impact.md").write_text(
        "# Skill impact tracker\n\n"
        "| date | proposal | target skill | outcome | reason |\n"
        "|------|----------|--------------|---------|--------|\n",
        encoding="utf-8")
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


def plant_skill(repo: Path, name: str, status: str = "proposed",
                cite: str = PERM_KEY, kind: str = "create",
                proposal_id: str = "209901010100") -> Path:
    """Write a wellformed child skill: the two-file unit lint_skills accepts."""
    d = repo / "skills" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(dump(
        {"name": name, "description": f"A planted test skill named {name}."},
        f"# {name}\n\n## When to use\nIn tests.\n\n## Procedure\n1. Exist.\n",
    ), encoding="utf-8")
    (d / "PURPOSE.md").write_text(dump(
        {"skill": name, "status": status, "proposal_id": proposal_id,
         "kind": kind, "proposed": "2026-08-31", "decided": ""},
        f"# Purpose — {name}\n\n## Origin\nPlanted by a test.\n\n"
        f"## Patterns-Addressed\nMotivated by [[{cite}]].\n\n"
        f"## Evolution-History\n| date | change | outcome |\n"
        f"|------|--------|---------|\n",
    ), encoding="utf-8")
    return d


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


def build_two_cluster_repo(root: Path) -> Path:
    """A repo with two densely-linked clusters that share vocabulary across the divide.

    Cluster A is about note atomicity, cluster B about compound interest. They
    are linked internally but never to each other, so Louvain must find two
    communities -- and the pair that shares the recombination idea is exactly
    the cross-community link a sweep should surface.
    """
    build_clean_repo(root)
    for path in (root / "permanent").glob("*.md"):
        path.unlink()

    clusters = {
        "a": [
            ("atomic-notes-compound-over-time", "202701010001",
             "A note confined to one idea can be reused in contexts its author never "
             "anticipated. That reuse is what makes a slip-box compound rather than "
             "merely accumulate: each atomic note becomes a component later thinking "
             "can recombine into new arguments."),
            ("one-idea-per-note-enables-reuse", "202701010002",
             "Splitting a note at its seams leaves each piece linkable on its own. A "
             "note carrying three ideas can only ever be cited as a lump, so its "
             "reuse is limited to contexts wanting all three at once."),
            ("titles-stated-as-claims-force-clarity", "202701010003",
             "Writing a note title as a claim rather than a topic forces the author "
             "to decide what the note actually asserts, and makes the note legible "
             "in a link list without opening it."),
        ],
        "b": [
            ("reinvested-returns-compound", "202701010011",
             "Reinvested returns themselves earn returns. The mechanism is "
             "recombination over time: each period's gain becomes principal that "
             "later periods compound, so growth accelerates rather than staying "
             "linear."),
            ("linear-growth-lacks-a-feedback-loop", "202701010012",
             "Simple interest pays only on the original principal, so each period's "
             "gain leaves the earning base unchanged. Without that feedback loop "
             "growth stays a straight line however long you wait."),
            ("time-horizon-dominates-rate", "202701010013",
             "Over long horizons the number of compounding periods matters more than "
             "the rate per period, because periods multiply while the rate only "
             "scales each step."),
        ],
    }

    keys = {name: [f"{slug}--{nid}" for slug, nid, _ in members]
            for name, members in clusters.items()}

    for name, members in clusters.items():
        member_keys = keys[name]
        for idx, (slug, nid, body) in enumerate(members):
            key = member_keys[idx]
            # Link densely WITHIN the cluster and never across it.
            links = [{"target_id": other, "relation": "elaborates"}
                     for other in member_keys if other != key]
            _write(root / "permanent" / f"{key}.md", {
                "id": nid, "key": key, "slug": slug, "aliases": [nid],
                "type": "permanent", "title": slug.replace("-", " ").capitalize(),
                "tags": [], "links": links,
                "created": "2027-01-01", "updated": "2027-01-01",
            }, body + "\n")

    # The clean fixture's literature/moc notes point at a permanent note that no
    # longer exists; repoint them at a real one so the repo stays coherent.
    anchor = keys["a"][0]
    lit = Note.load(root / "literature" / f"{LIT_KEY}.md")
    lit.meta["links"] = [{"target_id": REF_KEY, "relation": "source"}]
    lit.body = f"Own-words summary of [[{REF_KEY}]].\n"
    lit.save()
    moc = Note.load(root / "moc" / f"{MOC_KEY}.md")
    moc.body = f"# Zettelkasten method\n\n## Notes\n\n- [[{anchor}]]\n"
    moc.save()

    run_script("build_manifest.py", root)
    return root


@pytest.fixture
def clean_repo(tmp_path: Path) -> Path:
    return build_clean_repo(tmp_path / "kb")


@pytest.fixture
def two_cluster_repo(tmp_path: Path) -> Path:
    return build_two_cluster_repo(tmp_path / "kb")


@pytest.fixture
def broken_repo(clean_repo: Path):
    """Yields a mutator that breaks the clean repo, then rebuilds the manifest."""

    def _break(mutate, rebuild: bool = True) -> Path:
        mutate(clean_repo)
        if rebuild:
            run_script("build_manifest.py", clean_repo)
        return clean_repo

    return _break
