"""Lints pass on the clean fixture and fail, with reasons, on each planted violation.

Covers acceptance checklist item 4 and AC-5, AC-11, AC-12.
"""

from __future__ import annotations


from conftest import LIT_KEY, MOC_KEY, PERM_KEY, REF_KEY, load, rules, run_script


# --- clean baseline ----------------------------------------------------------

def test_lints_pass_on_clean_repo(clean_repo):
    for script in ("lint_citations.py", "lint_links.py"):
        result = run_script(script, clean_repo)
        assert result.returncode == 0, f"{script} failed on clean fixture:\n{result.stdout}\n{result.stderr}"


# --- lint_citations (FR-11, FR-12) -------------------------------------------

def test_unverified_reference_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"reference/{REF_KEY}.md")
        note.meta["verification"]["verified"] = False
        note.meta["raw_capture"] = ""
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "unverified-reference" in rules(result)
    assert REF_KEY in result.stdout


def test_malformed_chicago_string_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"reference/{REF_KEY}.md")
        note.meta["chicago_note"] = "Ahrens, Sonke. Smart Notes. Wrong Publisher, 1999."
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "stale-chicago" in rules(result)


def test_empty_chicago_string_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"reference/{REF_KEY}.md")
        note.meta["chicago_note"] = ""
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "malformed-chicago" in rules(result)


def test_permanent_claim_without_reference_link_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.meta["links"] = [{"target_id": LIT_KEY, "relation": "elaborates"}]
        note.body = "Ahrens argues that atomic notes compound, with nothing cited.\n"
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "uncited-claim" in rules(result)


def test_contested_claim_under_three_sources_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.meta["tags"] = ["contested"]
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "contested-undersourced" in rules(result)


def test_scripture_excluded_from_bibliography(broken_repo):
    def mutate(repo):
        note = load(repo, f"reference/{REF_KEY}.md")
        note.meta["scripture"] = True
        note.meta["source_tier"] = "primary-text"
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "scripture-in-bibliography" in rules(result)


def test_plain_english_per_is_not_attribution(broken_repo):
    """'per period' is arithmetic, not a citation (found live by the CI gate)."""
    def mutate(repo):
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.body = ("The number of compounding periods matters more than the rate "
                     "per period over long horizons. [[" + REF_KEY + "]]\n")
        note.meta["links"] = [{"target_id": REF_KEY, "relation": "source"}]
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode == 0, result.stdout


def test_per_a_named_source_is_attribution(broken_repo):
    def mutate(repo):
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.body = "Per Ahrens, atomic notes compound; nothing is linked here.\n"
        note.meta["links"] = [{"target_id": LIT_KEY, "relation": "elaborates"}]
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "uncited-claim" in rules(result)


def test_reference_missing_a_required_field_fails(broken_repo):
    """FR-4 names the reference-note fields; a note that drops one used to
    pass every gate until the next verify_refs run noticed."""
    def mutate(repo):
        note = load(repo, f"reference/{REF_KEY}.md")
        del note.meta["raw_capture"]
        del note.meta["verification"]["date"]
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "missing-field" in rules(result)
    assert "raw_capture" in result.stdout and "date" in result.stdout


def test_verified_by_capture_needs_a_capture_path(broken_repo):
    def mutate(repo):
        note = load(repo, f"reference/{REF_KEY}.md")
        note.meta["raw_capture"] = ""
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "missing-field" in rules(result)


def test_unknown_source_tier_fails(broken_repo):
    """QA-3's vocabulary is closed; a made-up tier used to pass silently."""
    def mutate(repo):
        note = load(repo, f"reference/{REF_KEY}.md")
        note.meta["source_tier"] = "blog-post"
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "bad-source-tier" in rules(result)


def test_scripture_requires_the_primary_text_tier(broken_repo):
    """AC-9 pairs scripture: true with source_tier: primary-text."""
    def mutate(repo):
        note = load(repo, f"reference/{REF_KEY}.md")
        note.meta["scripture"] = True
        note.meta["chicago_bib"] = ""
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "scripture-tier" in rules(result)


def _clone_reference(repo, new_id: str):
    """A second reference note describing the fixture's source (same ISBN)."""
    note = load(repo, f"reference/{REF_KEY}.md")
    slug = "ahrens-again"
    key = f"{slug}--{new_id}"
    note.meta.update({"id": new_id, "key": key, "slug": slug, "aliases": [new_id]})
    note.path = repo / "reference" / f"{key}.md"
    note.save()
    return key


def test_two_reference_notes_for_one_source_fail(broken_repo):
    """FR-4: exactly one reference note per source, decided by identifier."""
    def mutate(repo):
        _clone_reference(repo, "202608301001")

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "duplicate-source" in rules(result)
    assert result.stdout.count("duplicate-source") == 2, "both notes are named"


def test_contested_counts_distinct_sources_not_reference_notes(broken_repo):
    """FR-12 asks for independent sources; three notes for one ISBN are one."""
    def mutate(repo):
        keys = [REF_KEY, _clone_reference(repo, "202608301001"),
                _clone_reference(repo, "202608301002")]
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.meta["tags"] = ["contested"]
        note.meta["links"] = [{"target_id": k, "relation": "source"} for k in keys]
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "contested-undersourced" in rules(result)
    assert "1 distinct verified source(s) across 3 reference note(s)" in result.stdout


# --- lint_links (FR-5, FR-21) -------------------------------------------------

def test_bad_typed_link_relation_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.meta["links"][1]["relation"] = "vaguely-related-to"
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "bad-relation" in rules(result)


def test_unresolved_wikilink_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.body += "\nSee also [[a-note-that-does-not-exist--209901010000]].\n"
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "unresolved-wikilink" in rules(result)


def test_unresolved_typed_link_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.meta["links"].append(
            {"target_id": "ghost--209901010000", "relation": "supports"})
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "unresolved-link" in rules(result)


def test_filename_key_mismatch_fails(broken_repo):
    def mutate(repo):
        src = repo / "permanent" / f"{PERM_KEY}.md"
        src.rename(repo / "permanent" / "renamed-by-hand--202608301200.md")

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "filename-key-mismatch" in rules(result)


def test_permanent_note_without_outbound_link_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.meta["links"] = []
        note.body = "An orphan idea with no connections.\n"
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "atomicity" in rules(result)


def test_literature_note_must_cite_exactly_one_reference(broken_repo):
    def mutate(repo):
        note = load(repo, f"literature/{LIT_KEY}.md")
        note.meta["links"] = []
        note.body = "Summary with no reference link.\n"
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "one-to-one" in rules(result)


def test_index_may_link_only_to_mocs(broken_repo):
    def mutate(repo):
        (repo / "INDEX.md").write_text(
            f"# Index\n\n## Maps of Content\n\n- [[{PERM_KEY}]]\n", encoding="utf-8")

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "layering" in rules(result)


def test_bare_timestamp_id_still_resolves(broken_repo):
    """A bare ID is accepted as shorthand for the full key via manifest id_to_key."""

    def mutate(repo):
        note = load(repo, f"permanent/{PERM_KEY}.md")
        note.meta["links"][0]["target_id"] = "202608301000"
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode == 0, result.stdout


def test_moc_that_links_to_nothing_fails(broken_repo):
    """FR-4's second layering hop: MOCs link to notes. Only INDEX -> MOC was
    checked, so an empty MOC was a dead end for a Mode-B reader."""
    def mutate(repo):
        note = load(repo, f"moc/{MOC_KEY}.md")
        note.body = "# Zettelkasten method\n\n## Notes\n"
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "moc-empty" in rules(result)


def test_literature_without_a_locator_fails(broken_repo):
    def mutate(repo):
        note = load(repo, f"literature/{LIT_KEY}.md")
        note.meta["locator"] = ""
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "missing-locator" in rules(result)


def test_literature_reference_field_must_name_its_linked_source(broken_repo):
    def mutate(repo):
        note = load(repo, f"literature/{LIT_KEY}.md")
        note.meta["reference"] = PERM_KEY
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode != 0
    assert "reference-mismatch" in rules(result)


def test_literature_reference_field_accepts_the_bare_id(broken_repo):
    def mutate(repo):
        note = load(repo, f"literature/{LIT_KEY}.md")
        note.meta["reference"] = REF_KEY.rsplit("--", 1)[1]
        note.save()

    result = run_script("lint_links.py", broken_repo(mutate))
    assert result.returncode == 0, result.stdout


# --- machine-readable output --------------------------------------------------

def test_violations_are_tab_separated_with_file_and_reason(broken_repo):
    def mutate(repo):
        note = load(repo, f"reference/{REF_KEY}.md")
        note.meta["verification"]["verified"] = False
        note.meta["raw_capture"] = ""
        note.save()

    result = run_script("lint_citations.py", broken_repo(mutate))
    lines = [l for l in result.stdout.splitlines() if "\t" in l]
    assert lines, "expected at least one FILE\\tRULE\\tREASON line"
    for line in lines:
        file, rule, reason = line.split("\t", 2)
        assert file.endswith(".md") and rule and reason
