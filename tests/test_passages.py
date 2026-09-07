"""zettel_lib.passages: cutting a capture into passages and scoring each.

Unit tests over pure functions, like test_similarity.py -- the CLI behaviour
lives in test_query.py. The band tests pin one row per measured class, so
moving a threshold past a known passage fails a named test rather than quietly
reclassifying every source the base has ever read.
"""

from __future__ import annotations

from zettel_lib import passages, similarity
from zettel_lib.references import EXTRACTION_PREAMBLE, PAGE_MARKER

LONG = ("Atomic notes compound over time because each single idea can be reused "
        "inside more than one later context, which is the point of the slip-box.")
OTHER = ("Searing a steak over very high heat for a short period on each side and "
         "then resting it produces a crust without overcooking the interior.")


def paginated(*pages: str) -> str:
    return "\n\n".join(f"{PAGE_MARKER.format(n=i)}\n{p}"
                       for i, p in enumerate(pages, start=1))


def test_chunks_split_on_page_markers_and_paragraphs():
    chunks, _ = passages.chunks(paginated(LONG + "\n\n" + OTHER, LONG))
    assert [c.page for c in chunks] == [1, 1, 2]
    assert chunks[0].text.startswith("Atomic notes")
    assert chunks[1].text.startswith("Searing a steak")


def test_page_number_travels_with_the_chunk():
    chunks, _ = passages.chunks(paginated(LONG, OTHER, LONG))
    assert [c.locator for c in chunks] == ["p. 1", "p. 2", "p. 3"]


def test_short_chunks_are_skipped_and_counted():
    """A reader told "two passages" must know whether ten more were dropped."""
    chunks, skipped = passages.chunks(paginated("Header\n\n" + LONG + "\n\nPage 3"))
    assert [c.text for c in chunks] == [LONG]
    assert skipped["short"] == 2


def test_the_extraction_preamble_is_not_a_chunk():
    """It is not from the source at all; unrecognised it becomes a false
    "claim the base has nothing on"."""
    preamble = EXTRACTION_PREAMBLE.format(capture="202608301000-x.pdf",
                                          dropped="paper.pdf", kind="pdf")
    chunks, skipped = passages.chunks(f"{preamble}\n\n{paginated(LONG)}")
    assert skipped["preamble"] == 1
    assert [c.text for c in chunks] == [LONG]


def test_an_unpaginated_capture_gets_paragraph_locators():
    """capture.py refuses an empty locator, and inventing "p. 1" for a text
    with no pages would put a false citation into a note no gate can catch."""
    chunks, _ = passages.chunks(f"{LONG}\n\n{OTHER}")
    assert [c.page for c in chunks] == [None, None]
    assert [c.locator for c in chunks] == ["para. 1", "para. 2"]


def test_paragraph_ordinals_count_skipped_paragraphs_too():
    """The ordinal must match what a reader counting paragraphs would find."""
    chunks, _ = passages.chunks(f"Header\n\n{LONG}")
    assert chunks[0].paragraph == 2


def test_hard_wrapped_words_are_rejoined_before_tokenising():
    wrapped = LONG.replace("compound", "com-\npound")
    chunks, _ = passages.chunks(wrapped)
    assert "compound" in chunks[0].text
    assert "com-" not in chunks[0].text


# -- the bands ----------------------------------------------------------------

def score(text: str, docs: dict[str, str]):
    vectors, idf = similarity.tfidf_vectors(docs)
    hits = similarity.score_against(similarity.query_vector(text, idf), vectors)
    return hits[0] if hits else None


CORPUS = {"a": LONG, "b": "Titles stated as claims force clarity in a permanent note.",
          "c": "Reinvested returns compound because growth applies to prior growth."}


def test_a_verbatim_restatement_is_same_claim():
    assert passages.verdict(score(LONG, CORPUS), 0.35, 0.08) == passages.SAME_CLAIM


def test_a_genuinely_novel_passage_is_none():
    novel = ("Tidal locking of exoplanets alters atmospheric circulation near the "
             "terminator boundary of the planetary body itself.")
    assert passages.verdict(score(novel, CORPUS), 0.35, 0.08) == passages.NONE


def test_a_single_shared_term_is_none_however_high_the_score():
    """The measured false positive: 87 of 849 real passages matched on one term,
    47 of them above the touches band on score alone -- mostly OCR noise where
    one accidental word carries the whole cosine."""
    class Hit:
        score, shared = 0.99, 1
    assert passages.verdict(Hit(), 0.35, 0.08) == passages.NONE


def test_no_match_at_all_is_none():
    assert passages.verdict(None, 0.35, 0.08) == passages.NONE


def test_bands_are_ordered_and_the_shared_guard_is_at_least_two():
    from zettel_lib.repo import DEFAULT_SAME_CLAIM, DEFAULT_TOUCHES
    assert 0 < DEFAULT_TOUCHES < DEFAULT_SAME_CLAIM < 1
    assert passages.MIN_SHARED_TERMS >= 2
    assert passages.MIN_CHUNK_TOKENS > 0


def test_reference_notes_are_not_in_the_claim_corpus():
    """A bibliographic record states no claim and its near-empty body inflates
    a cosine."""
    assert "reference" not in passages.CLAIM_TYPES
    assert "moc" not in passages.CLAIM_TYPES
