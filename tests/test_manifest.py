"""manifest.json determinism and the public/private URL matrix (FR-3, FR-19, AC-3)."""

from __future__ import annotations

import json

import yaml

from conftest import PERM_KEY, REF_KEY, load, run_script


def read_manifest(repo):
    return json.loads((repo / "manifest.json").read_text(encoding="utf-8"))


def test_manifest_is_byte_identical_on_rerun(clean_repo):
    first = (clean_repo / "manifest.json").read_bytes()
    run_script("build_manifest.py", clean_repo)
    assert (clean_repo / "manifest.json").read_bytes() == first


def test_manifest_entries_carry_every_required_field(clean_repo):
    manifest = read_manifest(clean_repo)
    assert manifest["note_count"] == 4
    for entry in manifest["notes"]:
        for field in ("id", "key", "type", "title", "tags", "links",
                      "path", "url_or_apipath", "updated"):
            assert field in entry, f"{entry.get('key')} missing {field}"
        for link in entry["links"]:
            assert set(link) == {"target_id", "relation"}


def test_public_repo_emits_raw_urls(clean_repo):
    manifest = read_manifest(clean_repo)
    urls = [e["url_or_apipath"] for e in manifest["notes"]]
    assert all(u.startswith("https://raw.githubusercontent.com/") for u in urls)


def test_private_repo_emits_relative_and_api_paths_but_never_raw_urls(clean_repo):
    cfg = yaml.safe_load((clean_repo / "config.yml").read_text(encoding="utf-8"))
    cfg["content_repo"]["visibility"] = "private"
    (clean_repo / "config.yml").write_text(yaml.safe_dump(cfg, sort_keys=False),
                                           encoding="utf-8")
    run_script("build_manifest.py", clean_repo)

    manifest = read_manifest(clean_repo)
    for entry in manifest["notes"]:
        assert not entry["url_or_apipath"].startswith("http"), \
            "private repos must not emit anonymous raw URLs (FR-topology)"
        assert entry["url_or_apipath"] == entry["path"]
        assert entry["api_path"].startswith("https://api.github.com/repos/")


def test_id_to_key_map_is_complete(clean_repo):
    manifest = read_manifest(clean_repo)
    assert manifest["id_to_key"]["202608301200"] == PERM_KEY
    assert len(manifest["id_to_key"]) == manifest["note_count"]


def test_refs_json_aggregates_every_reference(clean_repo):
    refs = json.loads((clean_repo / ".bib" / "refs.json").read_text(encoding="utf-8"))
    assert [r["id"] for r in refs] == ["202608301000"]


def test_scripture_is_excluded_from_refs_json(clean_repo):
    note = load(clean_repo, f"reference/{REF_KEY}.md")
    note.meta["scripture"] = True
    note.save()
    run_script("build_manifest.py", clean_repo)
    refs = json.loads((clean_repo / ".bib" / "refs.json").read_text(encoding="utf-8"))
    assert refs == []


def test_malformed_frontmatter_exits_non_zero(clean_repo):
    (clean_repo / "permanent" / f"{PERM_KEY}.md").write_text(
        "no frontmatter here\n", encoding="utf-8")
    result = run_script("build_manifest.py", clean_repo)
    assert result.returncode != 0
    assert "frontmatter" in result.stderr.lower()


def test_non_iso_updated_stamp_is_rejected(clean_repo):
    """FR-3: `updated` is ISO-8601. It was copied verbatim, so a free-text
    date sorted nowhere for Mode-B readers."""
    note = load(clean_repo, f"permanent/{PERM_KEY}.md")
    note.meta["updated"] = "last tuesday"
    note.save()
    result = run_script("build_manifest.py", clean_repo)
    assert result.returncode != 0
    assert "ISO-8601" in result.stderr


def test_iso_datetime_stamps_are_accepted(clean_repo):
    note = load(clean_repo, f"permanent/{PERM_KEY}.md")
    note.meta["updated"] = "2026-08-30T10:00:00Z"
    note.save()
    result = run_script("build_manifest.py", clean_repo)
    assert result.returncode == 0, result.stderr
    entry = next(e for e in read_manifest(clean_repo)["notes"] if e["key"] == PERM_KEY)
    assert entry["updated"] == "2026-08-30T10:00:00Z"


def test_check_flag_detects_staleness(clean_repo):
    assert run_script("build_manifest.py", clean_repo, "--check").returncode == 0
    note = load(clean_repo, f"permanent/{PERM_KEY}.md")
    note.meta["title"] = "A different title"
    note.save()
    assert run_script("build_manifest.py", clean_repo, "--check").returncode != 0


def test_stale_check_points_at_a_stale_install_not_just_a_rebuild(clean_repo):
    """A live run took the plain "re-run build_manifest.py" advice, still failed
    (its own generator was the stale thing), and hand-wrote a guessed schema
    twice before finding the cache. The message has to name that second cause."""
    note = load(clean_repo, f"permanent/{PERM_KEY}.md")
    note.meta["title"] = "A different title"
    note.save()
    err = run_script("build_manifest.py", clean_repo, "--check").stderr
    assert "refresh-skill" in err, "the hint must name the actual remedy"
    assert "hand-edit" in err, "and rule out the fix that made it worse"
