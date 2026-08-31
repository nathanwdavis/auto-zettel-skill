"""Source-tier warnings (QA-3): discovery is unrestricted, grounding is tracked.

Researchers may reach any source to find a claim. A permanent note that never
got past general-web sourcing is discovered but not finished -- surfaced as a
warning, never a block, because the exit code belongs to real violations.
"""

from __future__ import annotations

import pytest

from conftest import PERM_KEY, REF_KEY, load, run_script


def set_tier(repo, tier):
    note = load(repo, f"reference/{REF_KEY}.md")
    note.meta["source_tier"] = tier
    note.save()


def warnings_of(result) -> str:
    return result.stderr


@pytest.mark.parametrize("tier", ["peer-reviewed", "primary-text", "reputable-secondary"])
def test_strong_tiers_produce_no_warning(clean_repo, tier):
    set_tier(clean_repo, tier)
    result = run_script("lint_citations.py", clean_repo)
    assert result.returncode == 0
    assert "weak-sourcing" not in warnings_of(result)


def test_general_web_only_warns(clean_repo):
    set_tier(clean_repo, "general-web")
    result = run_script("lint_citations.py", clean_repo)
    assert "weak-sourcing" in warnings_of(result)
    assert PERM_KEY in warnings_of(result)


def test_the_warning_never_changes_the_exit_code(clean_repo):
    """A lead found on the open web is a normal state, not a failure."""
    set_tier(clean_repo, "general-web")
    result = run_script("lint_citations.py", clean_repo)
    assert result.returncode == 0, "weak sourcing must warn, never block"


def test_warning_explains_what_would_resolve_it(clean_repo):
    set_tier(clean_repo, "general-web")
    text = warnings_of(run_script("lint_citations.py", clean_repo))
    assert "primary or peer-reviewed" in text


def test_a_mixed_note_with_one_strong_source_is_clean(clean_repo):
    """One primary source is enough to consider the claim grounded."""
    import shutil
    set_tier(clean_repo, "general-web")

    # Add a second, stronger reference and link the permanent note to it.
    src = clean_repo / "reference" / f"{REF_KEY}.md"
    strong_key = "a-peer-reviewed-study--202608301500"
    dst = clean_repo / "reference" / f"{strong_key}.md"
    shutil.copy(src, dst)

    from zettel_lib.frontmatter import Note
    strong = Note.load(dst)
    strong.meta.update({
        "id": "202608301500", "key": strong_key,
        "slug": strong_key.rsplit("--", 1)[0], "aliases": ["202608301500"],
        "source_tier": "peer-reviewed", "title": "A peer reviewed study",
    })
    strong.meta["csl_json"] = {**strong.meta["csl_json"], "id": "202608301500"}
    strong.save()

    perm = load(clean_repo, f"permanent/{PERM_KEY}.md")
    perm.meta["links"].append({"target_id": strong_key, "relation": "supports"})
    perm.save()

    run_script("build_manifest.py", clean_repo)
    run_script("verify_refs.py", clean_repo, "--offline")
    result = run_script("lint_citations.py", clean_repo)
    assert "weak-sourcing" not in warnings_of(result)


def test_an_unsourced_note_is_not_flagged_for_weak_sourcing(clean_repo):
    """A note with no references at all is a different problem, not this one."""
    perm = load(clean_repo, f"permanent/{PERM_KEY}.md")
    perm.meta["links"] = [{"target_id": "ahrens-on-the-slip-box-workflow--202608301100",
                           "relation": "elaborates"}]
    perm.body = "A claim with no attribution language and no sources.\n"
    perm.save()
    run_script("build_manifest.py", clean_repo)
    result = run_script("lint_citations.py", clean_repo)
    assert "weak-sourcing" not in warnings_of(result)
