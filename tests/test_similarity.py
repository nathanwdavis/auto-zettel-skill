"""Lexical and embedding scorers (FR-24)."""

from __future__ import annotations

import pytest

from zettel_lib.similarity import (EmbeddingScorer, LexicalScorer, PairScore,
                                   normalize, tokenize)

ATOMIC = ("A note confined to one idea can be reused in contexts its author never "
          "anticipated. That reuse is what makes a slip-box compound rather than "
          "merely accumulate: each atomic note becomes a component that later "
          "thinking can recombine into new arguments over time.")
COMPOUND = ("Reinvested returns themselves earn returns. The mechanism is "
            "recombination over time: each period's gain becomes principal that "
            "later periods compound, so growth accelerates rather than staying "
            "linear.")
STEAK = "Sear the steak in a hot dry pan, then rest it before slicing across the grain."


# --- tokenizer ----------------------------------------------------------------

def test_tokenizer_drops_stopwords_and_short_tokens():
    tokens = tokenize("The note is a very good one and it compounds")
    assert "the" not in tokens and "is" not in tokens and "very" not in tokens
    assert tokens == ["note", "good", "compound"]


@pytest.mark.parametrize("noise", [
    "```python\nsecret_code_token = 1\n```",
    "<!-- an html comment with commentary -->",
    "[[some-note-key--202601010000]]",
    "https://example.com/a/very/long/path",
])
def test_tokenizer_strips_markdown_and_structure(noise):
    """Structure and code must not become vocabulary."""
    tokens = tokenize(f"Real prose here. {noise}")
    assert "prose" in tokens
    for leaked in ("secret_code_token", "commentary", "some-note-key", "example.com"):
        assert leaked not in tokens


def test_tokenizer_is_case_insensitive():
    assert tokenize("Compound COMPOUND compound") == ["compound"] * 3


# --- singularization ----------------------------------------------------------

@pytest.mark.parametrize("word,expected", [
    ("notes", "note"), ("compounds", "compound"), ("ideas", "idea"),
    ("periods", "period"), ("returns", "return"), ("areas", "area"),
    ("boxes", "box"), ("dishes", "dish"), ("churches", "church"),
    ("classes", "class"),
])
def test_plurals_normalize_to_their_singular(word, expected):
    assert normalize(word) == expected


@pytest.mark.parametrize("word", [
    "process", "analysis", "focus", "gas", "bias", "series", "species", "basis",
])
def test_singulars_ending_in_s_are_left_alone(word):
    """Over-stripping would merge unrelated concepts."""
    assert normalize(word) == word


def test_singular_and_plural_share_a_token():
    assert set(tokenize("compound")) == set(tokenize("compounds"))


# --- lexical scoring ----------------------------------------------------------

def test_identical_documents_score_near_one():
    pairs = LexicalScorer().score_pairs({"a": ATOMIC, "b": ATOMIC, "c": STEAK})
    top = next(p for p in pairs if p.unordered() == ("a", "b"))
    assert top.score == pytest.approx(1.0, abs=0.02)


def test_unrelated_documents_do_not_pair():
    pairs = LexicalScorer().score_pairs({"idea": ATOMIC, "food": STEAK})
    assert not [p for p in pairs if p.score > 0.01]


def test_cross_domain_kinship_outranks_noise():
    """The point of the sweep: shared mechanism beats shared function words."""
    docs = {"atomic": ATOMIC, "compound": COMPOUND, "steak": STEAK}
    pairs = LexicalScorer().score_pairs(docs)
    assert pairs, "expected at least one scored pair"
    best = pairs[0]
    assert best.unordered() == ("atomic", "compound")
    assert best.score >= LexicalScorer.default_threshold


def test_evidence_terms_are_really_shared():
    docs = {"atomic": ATOMIC, "compound": COMPOUND, "steak": STEAK}
    best = LexicalScorer().score_pairs(docs)[0]
    assert best.evidence
    for term in best.evidence:
        assert term in tokenize(ATOMIC) and term in tokenize(COMPOUND)


def test_scoring_is_deterministic():
    docs = {"a": ATOMIC, "b": COMPOUND, "c": STEAK}
    assert LexicalScorer().score_pairs(docs) == LexicalScorer().score_pairs(docs)


def test_results_are_sorted_by_descending_score():
    docs = {"a": ATOMIC, "b": COMPOUND, "c": ATOMIC + " " + COMPOUND, "d": STEAK}
    scores = [p.score for p in LexicalScorer().score_pairs(docs)]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.parametrize("docs", [{}, {"only": ATOMIC}])
def test_fewer_than_two_documents_yields_nothing(docs):
    assert LexicalScorer().score_pairs(docs) == []


# --- embedding scoring (injected encoder; no model download) -------------------

def test_embedding_scorer_uses_cosine_over_injected_vectors():
    vectors = {"a": [1.0, 0.0], "b": [0.6, 0.8], "c": [0.0, 1.0]}
    scorer = EmbeddingScorer(lambda texts: [vectors[t] for t in texts])
    pairs = scorer.score_pairs({"a": "a", "b": "b", "c": "c"})
    lookup = {p.unordered(): p.score for p in pairs}
    assert lookup[("a", "b")] == pytest.approx(0.6, abs=1e-6)
    assert lookup[("b", "c")] == pytest.approx(0.8, abs=1e-6)


def test_embedding_scorer_normalizes_unnormalized_vectors():
    """Magnitude must not influence similarity; only direction."""
    scorer = EmbeddingScorer(lambda texts: {"a": [3.0, 0.0], "b": [100.0, 0.0]}.get)
    scorer = EmbeddingScorer(lambda texts: [[3.0, 0.0], [100.0, 0.0]])
    pairs = scorer.score_pairs({"a": "x", "b": "y"})
    assert pairs[0].score == pytest.approx(1.0, abs=1e-6)


def test_embedding_scorer_names_its_model():
    scorer = EmbeddingScorer(lambda texts: [[1.0], [1.0]], "all-MiniLM-L6-v2")
    assert "all-MiniLM-L6-v2" in scorer.name


def test_backends_carry_separate_calibrated_thresholds():
    """TF-IDF and embedding cosine live on different scales."""
    assert LexicalScorer.default_threshold < EmbeddingScorer.default_threshold


def test_pair_score_unordered_is_stable():
    assert PairScore("z", "a", 1.0).unordered() == PairScore("a", "z", 1.0).unordered()
