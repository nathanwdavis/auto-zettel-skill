# Serendipity: finding unplanned connections

Every link an agent writes is one it meant to write while working on a note.
The sweep does the opposite job: it looks for kinship between notes that sit in
**different regions of the link graph**, so an idea captured for one topic can
surface next to a distant one nobody thought to connect it to.

```sh
scripts/serendipity_sweep.py --repo <content-repo>
```

## How a candidate is chosen

1. **Load** permanent, literature, and MOC notes. Reference notes are
   bibliographic records and fleeting notes are transient — neither is an idea,
   so neither enters the graph.
2. **Build** the undirected typed-link graph from frontmatter `links[]`,
   resolving targets through the manifest's `id_to_key` map.
3. **Detect communities** with Louvain (`networkx`, fixed seed, so the same
   graph always yields the same community ids).
4. **Score every pair** (see backends below).
5. **Keep** only pairs that are in *different* communities, above the
   threshold, and not already linked in either direction — highest score first,
   capped by `--max-proposals`.
6. **Write** one file per candidate into `proposed-links/`.

Same-community pairs are excluded on purpose. Two notes in one cluster are
already neighbours; connecting them is bookkeeping, not serendipity.

## Two backends, two scales

| backend | when | default threshold | evidence |
|---|---|---|---|
| `lexical-tfidf` (stdlib) | default, and whenever embeddings are unavailable | `0.03` | the shared terms driving the score |
| `embedding` | `embedding.enabled: true` in config.yml **and** sentence-transformers plus its model load | `0.45` | none (similarity is not decomposable) |

The thresholds differ because the scales do: TF-IDF cosine over short notes
lands an order of magnitude below embedding cosine. Each backend carries its
own calibrated default; `--threshold` overrides both.

**Tuning.** Too much noise, raise it; nothing surfacing, lower it. The
meaningful signal is the *ratio* between a genuine cross-domain pair and a
function-word coincidence — on realistic notes that gap is roughly 3×.

**Degradation (NFR-5).** If embeddings are enabled but the import fails, the
model can't be fetched, or `embedding.model` is empty, the sweep logs the
downgrade to `log.md`, warns on stderr, and continues with lexical scoring. It
never fails a maintenance run over a missing optional dependency.

The same holds for community detection: `networkx` is a refinement, not a
requirement. The graph itself is a stdlib adjacency map, and if networkx can't
be imported the sweep partitions by connected components instead of Louvain,
logs the downgrade, and carries on. Connected components is the conservative
choice — it yields *coarser* communities, so more pairs count as
same-community and the sweep under-proposes rather than inventing serendipity
that isn't there.

Lexical scoring folds plurals into singulars (`compounds` → `compound`) so a
kinship isn't missed over one letter, but deliberately stops short of full
stemming, which merges unrelated words.

## Why the script proposes rather than links

The sweep writes candidates with `status: pending-review` and the neutral
`shared-concept` relation. It does not choose `supports` or `contradicts`, and
it does not write a justification — **a similarity score is a reason to look,
not a reason to link.** Two notes can share vocabulary and no idea at all.

The connector agent then reads both notes of every candidate and either writes
a real one-line justification with an honest relation, or deletes the
candidate. The critic reviews what survives and writes accepted links into
**both** notes. Rejections are logged, never silently dropped.

That division is the whole point: the machine is good at finding pairs worth a
look and bad at knowing whether they mean anything.

## Guarantees

- **Never edits notes.** Proposals only — tested by hashing every note before
  and after a sweep.
- **Always exits 0.** A sweep is advisory; it must not fail a maintenance run —
  including when an optional dependency is missing entirely.
- **Idempotent.** Re-running never duplicates a proposal for a pair already in
  the queue.
- **Deterministic.** Same notes in, same communities and scores out.
