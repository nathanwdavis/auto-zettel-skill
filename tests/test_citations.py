"""Chicago rendering backends (FR-8, FR-9)."""

from __future__ import annotations

import pytest

from zettel_lib import citations

ARTICLE = {
    "id": "tang2026", "type": "article-journal",
    "title": "WikiSkill: Compiling Agent Experience into Persistent Knowledge",
    "author": [{"family": "Tang", "given": "Liyan"},
               {"family": "Rashtchian", "given": "Cyrus"}],
    "issued": {"date-parts": [[2026, 8, 27]]},
    "container-title": "arXiv", "URL": "https://arxiv.org/abs/2608.27454",
}
BOOK = {
    "id": "ahrens2017", "type": "book", "title": "How to Take Smart Notes",
    "author": [{"family": "Ahrens", "given": "Sönke"}],
    "issued": {"date-parts": [[2017]]}, "publisher": "CreateSpace",
}


def test_bundled_style_is_present():
    assert citations.CSL_STYLE.exists()
    assert "chicago" in citations.CSL_STYLE.name


def test_pandoc_is_the_default_backend():
    assert citations.available_backends()[0] == citations.PANDOC


@pytest.mark.parametrize("item", [ARTICLE, BOOK])
def test_render_produces_both_strings(item):
    rendered = citations.render(item)
    assert rendered.note and rendered.bib
    assert rendered.backend == citations.PANDOC


def test_chicago_note_uses_full_given_names():
    """The regression that forced pandoc over citeproc-py: Chicago never initializes."""
    note = citations.render(ARTICLE).note
    assert "Liyan Tang" in note
    assert "L. Tang" not in note


def test_note_and_bibliography_forms_differ():
    rendered = citations.render(BOOK)
    assert rendered.note.startswith("Sönke Ahrens")     # note: given name first
    assert rendered.bib.startswith("Ahrens, Sönke")     # bibliography: inverted


def test_render_is_deterministic():
    assert citations.render(ARTICLE) == citations.render(ARTICLE)


def test_citeproc_fallback_still_renders():
    """Kept wired as a fallback even though its Chicago output is not authoritative."""
    rendered = citations.render(BOOK, backend=citations.CITEPROC_PY)
    assert rendered.backend == citations.CITEPROC_PY
    assert rendered.note


@pytest.mark.parametrize("item,expected", [
    ({}, "csl_json missing required field 'id'"),
    ({"id": "x", "type": "book"}, "csl_json missing required field 'title'"),
    ({"id": "x", "type": "book", "title": "T", "issued": {"date-parts": []}},
     "csl_json 'issued' must carry non-empty date-parts"),
    ({"id": "x", "type": "book", "title": "T", "author": "not a list"},
     "csl_json 'author' must be a list"),
])
def test_validate_csl_reports_structural_problems(item, expected):
    assert expected in citations.validate_csl(item)


def test_validate_csl_accepts_a_well_formed_item():
    assert citations.validate_csl(ARTICLE) == []
