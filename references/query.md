# Querying existing knowledge

`scripts/query.py` answers one question — *what does this base already have
on X?* — and changes nothing while doing it. It exists because the other
twenty-one entry points either grow the repository or gate it, and a session
asked "what do we know about X" would otherwise reach for the researcher.
Growing the base is a cycle's job, behind the lock and the gates; mapping it
is not.

```sh
scripts/query.py --repo <repo> "<query>" [--top N] [--gaps N] [--include-raw] \
                 [--json] [--mermaid] [--file-gaps [g1,g3]]
scripts/query.py --repo <repo> --from-file raw/<id>-<slug>.txt      # passage mode
```

## How a note is ranked

The same TF-IDF vectoriser the serendipity sweep uses
(`zettel_lib.similarity.tfidf_vectors`) is applied query-versus-note instead
of note-versus-note. Each note's document is its **title three times, its
tags three times, and its body once**: a permanent note's title *is* its
claim and tags are the curated vocabulary, so both should outweigh a passing
mention in prose. The score is the cosine between the query vector and the
note vector; the `terms:` shown beside each hit are the shared terms that
contributed most, so a surprising hit can be checked rather than trusted.

Terms that appear in **no note at all** are reported separately. That is the
most useful negative result a knowledge base can give: "nothing here",
rather than a weak match dressed up as coverage.

Embeddings are deliberately not used here even when `embedding.enabled` is
set: a query must answer in a second from a cold start, and the lexical
ranking is explainable term by term.

## What the report contains

| Section | Source |
|---|---|
| Claims the base makes | matched `permanent` notes, each with the reference notes it links |
| Literature notes | matched `literature` notes with their `reference` and locator |
| Sources on file | matched `reference` notes: tier, verification method, how many notes cite them |
| Maps of content | matched `moc` notes |
| Fleeting captures | matched `fleeting` notes, when any — undistilled material |
| Open inquiries touching this | inquiries whose question shares a term with the query, with status and `result_notes` |
| Connected notes | notes one link away from a match (typed links, wikilinks, and inbound citations), not themselves matched |
| Gaps | see below |

`--json` emits the same structure for programmatic use (the orchestrator's
gap analysis in FR-28 step 3, for instance).

## The graph

The four grouped lists say which notes matched; they never said how any two of
them were connected. `edges` does:

```json
{"source": "atomic-notes--2026...", "target": "ahrens--2026...", "relation": "source"}
```

`relation` is one of the eight FR-5 relations, or `mentions` for a body
wikilink. A pair that is **both** typed-linked and wikilinked produces two
rows, because a curated `supports` and a passing mention in prose are different
claims about the same pair. `mentions` is deliberately outside the FR-5 set: if
it ever reached a note's `links` block, `lint_links` would fail it as
`bad-relation`.

The subgraph is exactly the notes the report already listed — matched plus
connected — and an edge is kept only when both its endpoints are in that set. A
reader cannot look up a node the report never named.

`moc_membership` gives, for every node, the maps of content that reach it. The
"sits in no map of content" gap is computed from the same map, so the field and
the gap can never disagree about whether a note is reachable from `INDEX.md`.

`--mermaid` adds the diagram as a **section of the report**, and the JSON always
carries the source in a `mermaid` field. It replaces nothing and is exclusive
with nothing, so one invocation gives both the prose and the picture. Node ids
are synthetic (`n0`, `n1`, …) because a note key contains `--`, which Mermaid
can read as the start of an edge inside an identifier; the key goes in the
label so the diagram stays something you can look notes up from. Shape carries
the note type, a prose mention is a dotted arrow where a curated relation is
solid, and the output is byte-identical across runs.

## Passage mode

```sh
scripts/query.py --repo <repo> --from-file raw/<id>-<slug>.txt
```

Ingesting a source produces a page-marked extraction and then leaves a reader
with ninety pages and "find the new parts". Passage mode cuts that text into
the passages a person considers one at a time and sorts them into three piles:

| verdict | means | what you get |
|---|---|---|
| `same-claim` | the base already states this | the note that states it |
| `touches` | related to a note, not the same claim | the nearest note |
| `none` | nothing in the base is close | a ready-to-run `capture.py literature` command |

Only `none` chunks get a command; offering one for covered material invites a
duplicate. The locator is already filled in — `p. N` when the extraction has
page markers, `para. N` when it does not (every capture taken before the page
markers shipped is unpaginated, and inventing `p. 1` would write a false
citation no gate could catch).

It is **read-only and refuses `--file-gaps`**: a literature note needs prose a
person writes, and auto-filing passages would mint the bodyless notes
`capture.py` exists to prevent. The title in each command is the passage's
opening sentence, there to be replaced by what the note actually says.

When no reference note claims the file, the analysis is still printed but no
command is offered — a literature note must name a real reference, and a
command carrying a placeholder is one that gets improvised around.

### How a passage is scored, and why two signals

Each chunk is scored against the base's `permanent` and `literature` notes with
the same TF-IDF used everywhere else. A reference note is a bibliographic
record and a MOC is a list of links; neither states a claim, and both have
near-empty bodies that inflate a cosine.

Cosine alone is not enough. Measured against a real content repository — 237
claim-bearing notes and 849 passages cut from 25 real captures:

| | |
|---|---|
| a note's own body, scored back against the corpus | median **0.936**, 160 shared terms |
| real passages, 50th percentile | 0.122 |
| real passages, 90th percentile | 0.339 |
| real passages, 99th percentile | 0.513 |

and 87 of those 849 passages matched on **fewer than two distinct terms** — 47
of them clearing the `touches` band on score alone. They are almost all OCR
noise from old scans, where one accidental word carries the whole vector:

> score 0.272, 1 shared term: "Expence faved by alienation, being the fum
> alienated, toge- ther with …"

So a chunk must clear a score **and** share at least two distinct terms, and a
chunk too short to have a meaningful vector is not scored at all. At the
shipped bands those passages come out 8% `same-claim`, 61% `touches`, 30%
`none` — the intended bias, because a false `none` writes a duplicate note and
a false `same-claim` silently discards what the source added, while `touches`
costs ten seconds of reading.

The bands are absolute cosines and therefore depend on corpus size: a base of
eight notes inflates every score. That is why `query.same_claim` and
`query.touches` are configurable, and why the defaults are calibrated against a
real base rather than the test fixtures.

Everything set aside is counted and reported. A reader told "eleven passages"
needs to know whether fourteen more were dropped.

## Configuration

An optional `query:` block in the content repo's `config.yml`. Every key is
optional and absent means the default, so a repository scaffolded before this
shipped needs no migration; none of them is in `REQUIRED_CONFIG_KEYS`.

```yaml
query:
  stale_inquiry_days: 30   # when an open inquiry becomes a gap
  same_claim: 0.35         # passage bands
  touches: 0.08
```

`stale_inquiry_days` is deliberately not derived from `cadence`, which is free
text ("weekly on Sunday at 06:00") as often as it is cron.

## Gaps

The report names eight kinds of absence, ranked, because each calls for
different work. Research gaps become **inquiries** — questions a run goes out
and answers. Everything else becomes an **INBOX** entry, because the material
is already in the repository: filing "nothing has been distilled from these
sources" as an inquiry would send the researcher to re-fetch what the base
already holds.

| # | Kind | Files | The absence |
|---|---|---|---|
| 1 | `unresearched` | inquiry | no note uses the terms, or nothing matched at all |
| 2 | `weak-sourcing` | inquiry | a claim grounded only in `general-web` |
| 3 | `stale-inquiry` | inbox | a question asked and never worked |
| 4 | `undistilled` | inbox | sources match but no permanent note does |
| 5 | `unsummarised-reference` | inbox | a source captured and never read |
| 6 | `orphan-claim` | inbox | nothing links to a claim |
| 7 | `unmapped` | inbox | matched notes no MOC reaches |
| 8 | `raw-mentions` | inbox | a term no note uses but a `raw/` capture does |

The rank is the order to work them, and it is the order they are filed in, so
a session told "work them in filing order" works the important ones first.

Three of them deserve their reasoning stated:

- **`weak-sourcing`** is the *same predicate* `lint_citations` already warns
  on, reusing its tiers rather than restating them. Two different things called
  `weak-sourcing` would be a trap. The lint's *violation* half — `uncited-claim`,
  a sourced claim with no verified reference at all — is never a gap: it is
  reported as a warning, because a gate's finding is the gate's to report and a
  query offering a follow-up for it would look like a way around it. **Gaps
  have suggestions; warnings do not.**
- **`orphan-claim`** is about *inbound* links. `lint_links` already fails a
  permanent note with no outbound typed link and `capture.py` refuses to write
  one, so an outbound check could only fire on a repo already failing a gate. A
  note nothing refers to is invisible to every gate, and is the classic way a
  zettelkasten stops compounding.
- **`raw-mentions`** is opt-in (`--include-raw`) because `raw/` holds whole-book
  extractions: a base with 200 captures is hundreds of megabytes to read per
  query, and a query must answer in a second from a cold start. When it fires
  it *downgrades* the research gap for those terms to a distillation one, which
  is the entire point — the source is already on disk.

Each gap comes with one suggested follow-up, shown as a ready-to-run
`capture.py` command (shell-quoted, so a query with quotes pastes safely).

They are printed, not run: whether a gap is worth a cycle's budget is the
user's decision, and a query that filed inquiries as a side effect would be
an operation wearing a question's clothes (A9's read-only rule).

### Ids, ranks, and filing a selection

Every gap carries an id — `g1`, `g2` — assigned after ranking, so `g1` is
always the one to work first. The ids are **report-local and reproducible**:
identical for the same repo and query, renumbered as the repo grows. An id
durable across repository changes would have to be a content hash, which nobody
can type into `--file-gaps g1,g3`.

The `gaps` field stays a list of strings, each prefixed with its id; the
structure lives beside it in `gap_details`, which names each gap's kind, rank,
the note keys it points at, and the index of the suggestion that closes it.

Two gaps can share one follow-up — "no note uses these terms" and "nothing
matched at all" are one absence described twice — so suggestions are collected
by identity and filed once, and each says which gaps it closes.

```sh
scripts/query.py --repo <repo> "<query>" --file-gaps          # all of them
scripts/query.py --repo <repo> "<query>" --file-gaps g1,g3    # a selection
scripts/query.py --repo <repo> "<query>" --gaps 3             # report only the top 3
```

An unknown id exits 2 having written **nothing at all** — validated before any
capture, because a stale id means the caller is acting on a report they are no
longer reading, and filing "the ones that did exist" would file the wrong
things silently. `--gaps N` caps after ranking, so it bounds what `--file-gaps`
can write; capping the display while still filing everything would make the
printed receipt lie.

Note that `--file-gaps` takes an optional value, so a query written *after* it
is swallowed as the selection. That is refused with a message naming the fix
rather than treated as a selection.

`--file-gaps` is the explicit opt-in. It exists because most queries are
asked of a session, not typed at a terminal: the person reads the report in
chat and says "file those". The session re-runs the query with the flag,
which captures every suggestion through `capture.py`'s own functions (so
ids are allocated and the frontmatter is gate-clean), rebuilds the manifest,
and logs each capture. With the flag the tool *is* an operation and behaves
like one. Committing the captures is still the session's job: from a remote
session that means a branch and a PR, exactly as any other capture.

## Mode B (no local clone)

Full-text ranking needs note bodies, which only a clone has cheaply. Without
one, degrade honestly:

1. Fetch `manifest.json` (raw URL for a public repo; `fetch_remote.py` or the
   GitHub MCP for a private one — see `two-mode-access.md`).
2. Match the query against each entry's `title` and `tags`; the manifest's
   `inquiries` block gives the open questions.
3. Fetch the best few notes with `scripts/fetch_remote.py --owner --repo
   --keys k1,k2,...` and answer from them.
4. Say that the ranking was metadata-only.

## Guarantees

- Exit 0 whenever the repo opens, including a query that matches nothing;
  usage errors exit 2.
- Nothing is written without `--file-gaps`: no note, no inquiry, no
  `log.md` line (a query is not an operation). With it, exactly the listed
  suggestions are captured, and each is logged. **Passage mode refuses
  `--file-gaps` outright** — it is read-only with no exception.
- A rejected gap selection writes nothing at all, not even the ids that were
  valid.
- Deterministic: the same repo and query produce the same report, including the
  Mermaid source and the gap ids. The **one** exception is `stale-inquiry`,
  which is about how long a question has been open and therefore about now; its
  threshold and the measured age are both in the report so it explains itself.

---

**Next:** [`capture.md`](capture.md) for acting on a gap, or [`note-types.md`](note-types.md) for what the report is describing.
All reference docs: [`README.md`](README.md).
