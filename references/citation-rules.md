# Citation rules

## CSL-JSON is canonical

Each reference note carries its bibliographic record as `csl_json` in
frontmatter; `build_manifest.py` aggregates every one into `.bib/refs.json`.
The rendered Chicago strings are **derived artifacts** — regenerate them, never
edit them by hand.

## Rendering backend: pandoc, not citeproc-py

The spec (FR-8) named `citeproc-py` as the primary renderer with pandoc as a
fallback, and provided for flipping them if citeproc-py failed on real
fixtures. **It failed, so they are flipped.**

The bundled style sets `initialize-with=". "` globally on the `<style>` element
and then overrides it with 173 `<name initialize="false">` elements. citeproc-py
ignores those overrides:

| | citeproc-py | pandoc |
|---|---|---|
| Note | `L. Tang and C. Rashtchian, ...` | `Liyan Tang and Cyrus Rashtchian, ...` |
| Bibliography | `Tang, L., and C. Rashtchian.` | `Tang, Liyan, and Cyrus Rashtchian.` |
| Quotes | `"Title"` | `"Title."` |

Chicago never initializes given names, so citeproc-py's output is wrong. This
matches the known caveat that citeproc-py implements only part of the CSL test
suite.

`citeproc-py` stays installed and wired as a fallback for environments that
cannot run pandoc, but **its output is not authoritative**. `pypandoc-binary`
ships a pandoc build, so the correct backend needs no system install.

Each reference note records which backend produced its strings:

```yaml
citation_renderer: pandoc
```

`lint_citations.py` re-renders using *that* backend and compares. If the
recorded backend is not installed locally it emits a warning and skips the
comparison rather than failing — a different backend would report mismatches
that are the renderer's fault, not the note's.

## The bundled style

`scripts/csl/chicago-notes-bibliography.csl` — Chicago Manual of Style 18th
edition (notes and bibliography), vendored so rendering never needs the network.

The spec calls this file `chicago-fullnote-bibliography.csl`; upstream renamed
the style and the old name no longer resolves. See amendment A1 in
`docs/REQUIREMENTS.md` and `scripts/csl/README.md` for provenance and the
CC BY-SA 3.0 attribution.

## Verification: the anti-hallucination gate

A reference is verified only by:

1. **A raw capture** — the source actually fetched into `raw/`, non-empty; or
2. **An authoritative metadata lookup** — Crossref (DOI), arXiv (arXiv ID),
   PubMed (PMID), Open Library or Google Books (ISBN).

`verify_refs.py` writes the outcome and **exits 0 either way**; it records
state. `lint_citations.py` is the gate that fails on
`verification.verified: false`.

That split matters: a verifier that failed the run would create pressure to
mark things verified to get past it. Recording "I could not verify this"
honestly, and failing separately, keeps the record truthful.

When a reference carries **both** a capture and an authoritative identifier
and the network is up, both are checked: a registry hit upgrades the method
to `raw-capture+crossref` (or `+arxiv`, `+pubmed`, `+openlibrary`,
`+googlebooks`), and a definitive miss keeps the capture-based verification —
the documented either/or — while recording `identifier_check: failed` and
printing a warning, so a rotted or mistyped DOI is visible instead of
silently un-exercised.

### What the timestamps mean

- **`updated`** (note frontmatter) tracks **authored edits** — a human or
  agent changed the note's content.
- **`verification.date`** tracks the machine-check state: it is stamped when
  the verification *state* changes and left alone by a re-check that found
  the same state. `verify_refs.py` writes a note only when its verification
  state or rendered Chicago strings actually changed, so a quiet cycle
  produces no diff on untouched reference notes.

### Raw captures

A capture file's name is `<ref-id>-<slug>.<ext>` and its content is the
verbatim fetched source. If a header records when the fetch happened, use
full ISO-8601 UTC instants — a window as `<instant> to <instant>`, e.g.
`2026-08-31T11:18:00Z to 2026-08-31T11:19:00Z` — never a compressed form
like `11:18Z-11:19Z`. And a capture is never rewritten after the fact, an
awkward header included: captures are immutable evidence, and the sandbox
gate rejects any edit to `raw/`.

### Crossref politeness

Requests always send `mailto`, which routes them to Crossref's reserved polite
pool. 429s are retried with exponential backoff, honouring `Retry-After`.
Crossref revised its public/polite rate limits effective 2025-12-01, so
throttling is expected rather than exceptional.

```sh
verify_refs.py --repo <repo> --mailto you@example.org
```

### Offline and degraded operation

`--offline` skips all lookups and verifies from `raw/` captures only. If the
network dies mid-run, the verifier degrades to the same behaviour, logs a
warning, and keeps going — captured sources stay verified (NFR-5).

## Source tiers

Record `source_tier` on every reference, most to least authoritative:

```
peer-reviewed  >  primary-text  >  reputable-secondary  >  general-web
```

## Scripture

Cited by book–chapter–verse per the SBL Handbook of Style, and **excluded from
the bibliography** (FR-9):

```yaml
source_tier: primary-text
scripture: true
chicago_bib: ""      # must stay empty
```

`lint_citations.py` fails a scripture reference that carries a bibliography
entry; `build_manifest.py` omits it from `.bib/refs.json`.

## What the gate rejects

| Rule | Meaning |
|---|---|
| `unverified-reference` | No capture and no successful lookup |
| `malformed-csl` | `csl_json` missing `id`, `type`, `title`, or malformed dates |
| `malformed-chicago` | A required rendered string is empty |
| `stale-chicago` | Strings disagree with a re-render of `csl_json` |
| `uncited-claim` | Permanent note asserts something sourced, links nothing verified |
| `contested-undersourced` | Tagged `contested` with fewer than 3 verified references |
| `scripture-in-bibliography` | Scripture carrying a `chicago_bib` entry |

Never satisfy one of these by weakening the rule, deleting the note, or
inventing a citation. Capture the source or drop the claim.
