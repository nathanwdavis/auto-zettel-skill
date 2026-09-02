"""Pairwise note similarity behind one pluggable scorer (FR-24).

Two backends share a single protocol so ``serendipity_sweep.py`` stays about
policy (which pairs are worth proposing) and the scoring stays unit-testable in
isolation -- the same injectable-seam pattern as ``http.py``'s transport.

``LexicalScorer`` is the default and uses only the standard library, so the
sweep works out of the box with no model download. ``EmbeddingScorer`` is used
when ``embedding.enabled`` is set in config.yml and sentence-transformers is
importable with its model available; otherwise the sweep logs the downgrade and
falls back to lexical (NFR-5).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Protocol, Sequence

# Deliberately small: enough to stop function words from dominating TF-IDF on
# short notes, without the maintenance burden of a full stopword corpus.
STOPWORDS = frozenset("""
a an the and or but if then than that this these those of in on at to from by
for with without about into over under again further is are was were be been
being have has had do does did doing will would shall should can could may
might must it its it's as not no nor so such only own same too very s t just
don now i you he she they we them his her their our your my me him us who whom
which what when where why how all any both each few more most other some
because since while although though however therefore thus hence rather
also there here between during before after above below out off up down
one two first second new old make makes made get gets got use uses used
never always often sometimes still yet even much many way ways thing things
""".split())

TOKEN_RE = re.compile(r"[a-z][a-z0-9'-]{2,}")

# Markdown/wiki syntax that would otherwise pollute the token stream.
STRIP_PATTERNS = (
    re.compile(r"```.*?```", re.DOTALL),        # fenced code
    re.compile(r"<!--.*?-->", re.DOTALL),       # html comments
    re.compile(r"\[\[[^\]]*\]\]"),              # wikilinks (structure, not prose)
    re.compile(r"https?://\S+"),                # bare urls
    re.compile(r"[`*_>#|-]+"),                  # md punctuation
)


# Conservative singularization only. "compounds" and "compound" are the same
# concept, and a sweep that misses that kinship over one letter is weaker for
# it -- but full Porter stemming merges unrelated words, so this handles just
# the dominant plural/third-person case and leaves everything else alone.
# Suffixes that are part of the stem (class, focus, analysis), plus the handful
# of common singulars a suffix rule cannot tell from plurals.
_KEEP_TRAILING_S = ("ss", "us", "is")
_NEVER_STRIP = frozenset(
    "gas bias canvas atlas lens news series species means basis thesis".split())
# "-es" is only a plural suffix after a sibilant (boxes, dishes, churches).
# Elsewhere the "e" belongs to the stem, so notes -> note, not "not".
_SIBILANT_ES = ("xes", "ches", "shes", "sses", "zes")


def normalize(token: str) -> str:
    if token in _NEVER_STRIP:
        return token
    if len(token) > 4 and token.endswith(_SIBILANT_ES):
        return token[:-2]
    if len(token) > 3 and token.endswith("s") and not token.endswith(_KEEP_TRAILING_S):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    """Lowercase content words from note prose, minus markdown and stopwords."""
    cleaned = text.lower()
    for pattern in STRIP_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    return [normalize(t) for t in TOKEN_RE.findall(cleaned)
            if t not in STOPWORDS and normalize(t) not in STOPWORDS]


@dataclass(frozen=True)
class PairScore:
    """One scored pair of note keys, with the evidence behind the score."""

    a: str
    b: str
    score: float
    evidence: tuple[str, ...] = field(default=())

    def unordered(self) -> tuple[str, str]:
        return tuple(sorted((self.a, self.b)))  # type: ignore[return-value]


class Scorer(Protocol):
    name: str
    default_threshold: float

    def score_pairs(self, docs: dict[str, str]) -> list[PairScore]: ...


class LexicalScorer:
    """TF-IDF cosine over note text, standard library only.

    Evidence is the set of shared terms contributing most to the score, which
    gives the connector agent something concrete to check rather than an
    unexplained number.
    """

    name = "lexical-tfidf"
    # TF-IDF cosine over short notes lands far below embedding cosine, so the
    # two backends carry their own calibrated defaults (--threshold overrides).
    default_threshold = 0.03

    def __init__(self, evidence_terms: int = 5):
        self.evidence_terms = evidence_terms

    def score_pairs(self, docs: dict[str, str]) -> list[PairScore]:
        keys = sorted(docs)
        if len(keys) < 2:
            return []
        vectors, _ = tfidf_vectors(docs)

        out: list[PairScore] = []
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                va, vb = vectors[a], vectors[b]
                shared = set(va) & set(vb)
                if not shared:
                    continue
                contributions = {t: va[t] * vb[t] for t in shared}
                score = sum(contributions.values())
                if score <= 0:
                    continue
                evidence = tuple(
                    t for t, _ in sorted(contributions.items(),
                                         key=lambda kv: (-kv[1], kv[0]))[:self.evidence_terms])
                out.append(PairScore(a, b, round(score, 6), evidence))
        out.sort(key=lambda p: (-p.score, p.a, p.b))
        return out


def tfidf_vectors(docs: dict[str, str]) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """Unit-normalised TF-IDF vectors for every doc, plus the corpus idf.

    Shared by pairwise scoring (the sweep) and query scoring (query.py) so the
    two cannot drift apart in how they read a note.
    """
    keys = sorted(docs)
    tokens = {k: tokenize(docs[k]) for k in keys}
    counts = {k: Counter(tokens[k]) for k in keys}
    n_docs = len(keys)

    doc_freq: Counter[str] = Counter()
    for k in keys:
        doc_freq.update(set(tokens[k]))

    # Smoothed idf; terms in every document contribute ~0.
    idf = {term: math.log((n_docs + 1) / (df + 1)) + 1e-9
           for term, df in doc_freq.items()}

    vectors: dict[str, dict[str, float]] = {}
    for k in keys:
        total = sum(counts[k].values()) or 1
        vec = {t: (c / total) * idf[t] for t, c in counts[k].items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors[k] = {t: v / norm for t, v in vec.items()}
    return vectors, idf


@dataclass(frozen=True)
class QueryHit:
    """One note scored against a free-text query, with the terms that matched."""

    key: str
    score: float
    evidence: tuple[str, ...] = field(default=())


def score_query(query: str, docs: dict[str, str],
                evidence_terms: int = 5) -> tuple[list[QueryHit], list[str]]:
    """Rank docs against a query by TF-IDF cosine; also report the query terms
    the corpus never uses at all.

    Returns ``(hits sorted best-first, missing_terms)``. A term absent from
    every note is the most useful negative result a knowledge base can give:
    it says "nothing here" rather than "weak match".
    """
    q_tokens = tokenize(query)
    if not q_tokens or not docs:
        return [], sorted(set(q_tokens))
    vectors, idf = tfidf_vectors(docs)
    q_counts = Counter(q_tokens)
    total = sum(q_counts.values())
    q_vec = {t: (c / total) * idf.get(t, 0.0) for t, c in q_counts.items()}
    norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
    q_vec = {t: v / norm for t, v in q_vec.items()}

    hits: list[QueryHit] = []
    for key, vec in vectors.items():
        shared = set(q_vec) & set(vec)
        if not shared:
            continue
        contributions = {t: q_vec[t] * vec[t] for t in shared}
        score = sum(contributions.values())
        if score <= 0:
            continue
        evidence = tuple(t for t, _ in sorted(contributions.items(),
                                              key=lambda kv: (-kv[1], kv[0]))[:evidence_terms])
        hits.append(QueryHit(key, round(score, 6), evidence))
    hits.sort(key=lambda h: (-h.score, h.key))
    missing = sorted(t for t in set(q_tokens) if t not in idf)
    return hits, missing


class EmbeddingScorer:
    """Cosine over sentence-transformers embeddings.

    Constructed with an ``encode`` callable so tests can inject a deterministic
    fake; ``load()`` builds the real one and raises when the dependency or its
    model is unavailable, which is what triggers the documented downgrade.
    """

    name = "embedding"
    default_threshold = 0.45

    def __init__(self, encode, model_name: str = ""):
        self.encode = encode
        self.model_name = model_name
        if model_name:
            self.name = f"embedding:{model_name}"

    @classmethod
    def load(cls, model_name: str) -> "EmbeddingScorer":
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        model = SentenceTransformer(model_name)
        return cls(lambda texts: model.encode(list(texts)), model_name)

    def score_pairs(self, docs: dict[str, str]) -> list[PairScore]:
        keys = sorted(docs)
        if len(keys) < 2:
            return []
        vectors = [_unit(v) for v in self.encode([docs[k] for k in keys])]
        out: list[PairScore] = []
        for i, a in enumerate(keys):
            for j in range(i + 1, len(keys)):
                score = sum(x * y for x, y in zip(vectors[i], vectors[j]))
                if score <= 0:
                    continue
                out.append(PairScore(a, keys[j], round(float(score), 6)))
        out.sort(key=lambda p: (-p.score, p.a, p.b))
        return out


def _unit(vector: Iterable[float]) -> Sequence[float]:
    values = [float(x) for x in vector]
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]
