"""Note key generation and the frozen-slug guarantee (amendment A2 to FR-5)."""

from __future__ import annotations

import pytest

from conftest import PERM_KEY, load, run_script
from zettel_lib import naming


@pytest.mark.parametrize("title,expected", [
    ("Atomic notes compound over time", "atomic-notes-compound-over-time"),
    ("Sönke Ahrens on Zettelkästen", "sonke-ahrens-on-zettelkasten"),
    ("Groundedness: why <0.70 blocks!", "groundedness-why-0-70-blocks"),
    ("   leading and trailing   ", "leading-and-trailing"),
    ("Hyphen--collapse___test", "hyphen-collapse-test"),
    ("???", "untitled"),
    ("", "untitled"),
])
def test_slugify(title, expected):
    assert naming.slugify(title) == expected


def test_long_titles_truncate_on_a_word_boundary():
    slug = naming.slugify("the quick brown fox jumps over the lazy dog and keeps "
                          "running well past the limit")
    assert len(slug) <= naming.MAX_SLUG_LEN
    assert not slug.endswith("-")
    assert slug.split("-")[-1] in {"keeps", "and", "dog", "lazy", "the", "running", "past"}


def test_make_key_and_split_key_round_trip():
    key = naming.make_key("Atomic notes compound over time", "202608301412")
    assert key == "atomic-notes-compound-over-time--202608301412"
    assert naming.split_key(key) == ("atomic-notes-compound-over-time", "202608301412")


def test_make_key_rejects_a_non_timestamp_id():
    with pytest.raises(ValueError):
        naming.make_key("Title", "not-a-timestamp")


@pytest.mark.parametrize("bad", ["nokey", "slug--123", "SLUG--202608301412", "--202608301412"])
def test_split_key_rejects_malformed_keys(bad):
    with pytest.raises(ValueError):
        naming.split_key(bad)


def test_slug_is_frozen_when_a_title_is_reworded(clean_repo):
    """Editing `title` must not move the file or disturb links (frozen slug)."""
    note = load(clean_repo, f"permanent/{PERM_KEY}.md")
    original_path, original_key = note.path, note.key

    note.meta["title"] = "Completely rewritten claim about note atomicity"
    note.save()
    run_script("build_manifest.py", clean_repo)

    assert original_path.exists(), "renaming must not follow a title edit"
    assert load(clean_repo, f"permanent/{PERM_KEY}.md").key == original_key
    assert run_script("lint_links.py", clean_repo).returncode == 0
