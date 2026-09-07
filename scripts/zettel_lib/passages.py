"""Reading a capture's text extraction the way a note-writer reads it.

``ingest_drops`` writes every page of a dropped source into ``raw/<id>-<slug>.txt``
with ``--- page N ---`` markers so a literature note can cite ``p. N`` without
reopening the PDF. This is the other half: it cuts that text back into the
passages a person would consider one at a time, scores each against the notes
the base already has, and says which of three things it is --

    same-claim   the base already states this; writing it again duplicates
    touches      related to a note, but not the same claim
    none         nothing in the base is close: candidate material

-- so that reading a source becomes "here are the eleven passages nobody has
written down yet" rather than "here are ninety pages, find the new parts".

Scoring reuses ``similarity``, the same TF-IDF the query ranking and the
serendipity sweep use. Nothing here writes.

Why two signals, not one
------------------------
Cosine alone cannot tell a restatement from a coincidence, and the evidence is
not hypothetical. Measured against a real content repository -- 237 permanent
and literature notes, and 849 passages cut from 25 real captures:

    a note's own body, scored back against the corpus   median 0.936, 160 shared
    real passages, 50th percentile                             0.122
    real passages, 90th percentile                             0.339
    real passages, 99th percentile                             0.513

and, separately, 87 of those 849 passages matched on FEWER THAN TWO distinct
terms -- 47 of them scoring above the `touches` band on score alone. They are
almost all OCR noise from old scans, where one accidental term carries the
whole cosine:

    score 0.272, 1 shared term: "Expence faved by alienation, being the fum
                                 alienated, toge- ther with ..."

So a chunk must clear a score AND share at least two distinct terms, and a
chunk too short to have a meaningful vector is not scored at all. The length
guard is not redundant with the shared-term guard: a four-token running header
scored 0.696 with two shared terms against a fixture corpus, and only its
length disqualified it.

At the shipped bands those 849 passages come out 8% same-claim, 61% touches,
30% none -- which is the intended bias. A false `none` writes a duplicate note;
a false `same-claim` silently discards material the source actually added;
`touches` costs a person ten seconds of reading. Uncertainty belongs there.

The bands are absolute cosines, so they depend on corpus size: a base of eight
notes inflates every score (a merely related passage scored 0.550 against the
test fixture, where the same shape of passage scores 0.12-0.34 against 237
notes). That is why they are configurable -- `query.same_claim` and
`query.touches` in the content repo's config.yml -- and why the defaults are
calibrated against a real base rather than the fixtures.

"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import similarity
from .references import EXTRACTION_PREAMBLE_RE, PAGE_MARKER_RE
from .repo import ContentRepo

#: Below this a cosine is one term's opinion. Real captures produce far more
#: short fragments than prose -- 2259 skipped against 849 kept across 25 real
#: sources -- and scoring them adds noise, not coverage.
MIN_CHUNK_TOKENS = 12

#: 87 of 849 real passages matched on one term; 47 of those cleared the touches
#: band on score alone. This is the shape of the rule rather than a tuning knob,
#: so it is not configurable; the score bands are
#: (config `query.same_claim` / `query.touches`).
MIN_SHARED_TERMS = 2

#: The note types a passage can restate. A reference note is a bibliographic
#: record and a MOC is a list of links -- neither states a claim, and both have
#: near-empty bodies that inflate a cosine.
CLAIM_TYPES = ("permanent", "literature")

SAME_CLAIM, TOUCHES, NONE = "same-claim", "touches", "none"

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
#: PDF extraction hard-wraps mid-word; rejoin before tokenising or "compound-\ning"
#: becomes two terms the corpus has never seen.
_HYPHEN_WRAP = re.compile(r"-\n(?=[a-z])")


@dataclass(frozen=True)
class Chunk:
    """One passage of a capture, with enough provenance to cite it."""

    index: int
    page: int | None
    paragraph: int
    text: str
    tokens: int

    @property
    def locator(self) -> str:
        """What a literature note cites this passage as.

        A page when the extraction is paginated. Otherwise the paragraph
        ordinal -- honest and countable -- because ``capture.py`` refuses an
        empty locator and inventing "p. 1" for an unpaginated text would put a
        false citation into a note that the gates cannot catch.
        """
        return f"p. {self.page}" if self.page is not None else f"para. {self.paragraph}"


def chunks(text: str) -> tuple[list[Chunk], dict[str, int]]:
    """Cut an extraction into scoreable passages, reporting what was set aside.

    The skip counts are returned rather than swallowed: a reader who is told
    "eleven passages" needs to know whether fourteen more were dropped, or the
    report is quietly deciding what the source says.
    """
    segments: list[tuple[int | None, str]] = []
    parts = PAGE_MARKER_RE.split(text)
    segments.append((None, parts[0]))
    for i in range(1, len(parts), 2):
        segments.append((int(parts[i]), parts[i + 1]))

    kept: list[Chunk] = []
    skipped = {"short": 0, "preamble": 0}
    paragraph = 0
    for page, body in segments:
        for raw in _PARAGRAPH_SPLIT.split(_HYPHEN_WRAP.sub("", body)):
            passage = " ".join(raw.split())
            if not passage:
                continue
            paragraph += 1
            if EXTRACTION_PREAMBLE_RE.match(passage):
                skipped["preamble"] += 1
                continue
            count = len(similarity.tokenize(passage))
            if count < MIN_CHUNK_TOKENS:
                skipped["short"] += 1
                continue
            kept.append(Chunk(len(kept) + 1, page, paragraph, passage, count))
    return kept, skipped


def verdict(hit, same_claim: float, touches: float) -> str:
    """Which of the three a scored chunk is.

    A single shared term is ``none`` however high the cosine: that is the
    steak-recipe case, and it is the whole reason ``shared`` exists.
    """
    if hit is None or hit.shared < MIN_SHARED_TERMS:
        return NONE
    if hit.score >= same_claim:
        return SAME_CLAIM
    if hit.score >= touches:
        return TOUCHES
    return NONE


def reference_for_capture(repo: ContentRepo, path) -> tuple[str | None, list[str]]:
    """The reference note whose capture this text belongs to.

    Both writers name a capture ``raw/<id>-<slug>.<ext>`` and put the extraction
    beside it as ``raw/<id>-<slug>.txt``, so four rules in order cover every
    shape one can take: the text IS the capture (a .txt drop), the text sits
    beside it (the PDF case), the stems agree (.html and .md captures), or the
    id prefix matches a reference whose raw_capture was never filled in.

    Returns ``(key, warnings)``. No match is not an error -- the passage
    analysis is still worth reading -- but it does mean no literature command
    can be offered, because a literature note must name a real reference.
    """
    rel = repo.rel(path)
    stem = path.stem
    note_id = stem.split("-", 1)[0]
    by_rule: dict[int, list[str]] = {}
    for note in repo.notes(types=["reference"]):
        capture = str(note.meta.get("raw_capture") or "").strip()
        if capture == rel:
            by_rule.setdefault(0, []).append(note.key)
        elif capture and capture.rsplit(".", 1)[0] == rel.rsplit(".", 1)[0]:
            by_rule.setdefault(1, []).append(note.key)
        elif not capture and note.id and note.id == note_id:
            by_rule.setdefault(2, []).append(note.key)
    for rule in sorted(by_rule):
        matches = sorted(by_rule[rule])
        if len(matches) > 1:
            return matches[0], [
                f"{rel} is claimed by {len(matches)} reference notes "
                f"({', '.join(matches)}); using {matches[0]}"]
        return matches[0], []
    return None, []


def analyse(repo: ContentRepo, path, docs: dict[str, str], *,
            same_claim: float, touches: float) -> dict:
    """Score every passage of ``path`` against ``docs``. Reads only.

    The corpus is vectorised ONCE and every chunk scored against it. Building
    it per chunk made reading a book quadratic in its own length.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    kept, skipped = chunks(text)
    vectors, idf = similarity.tfidf_vectors(docs) if docs else ({}, {})

    scored = []
    for chunk in kept:
        hits = similarity.score_against(similarity.query_vector(chunk.text, idf), vectors)
        best = hits[0] if hits else None
        scored.append({
            "index": chunk.index, "page": chunk.page, "paragraph": chunk.paragraph,
            "locator": chunk.locator, "tokens": chunk.tokens, "text": chunk.text,
            "verdict": verdict(best, same_claim, touches),
            "matches": [{"key": h.key, "score": h.score, "shared": h.shared,
                         "evidence": list(h.evidence)} for h in hits[:3]],
        })
    return {"chunks": scored, "skipped": skipped,
            "paginated": any(c.page is not None for c in kept)}
