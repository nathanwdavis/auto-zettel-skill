# Querying existing knowledge

`scripts/query.py` answers one question — *what does this base already have
on X?* — and changes nothing while doing it. It exists because the other
seventeen entry points either grow the repository or gate it, and a session
asked "what do we know about X" would otherwise reach for the researcher.
Growing the base is a cycle's job, behind the lock and the gates; mapping it
is not.

```sh
scripts/query.py --repo <repo> "<query>" [--top N] [--json] [--file-gaps]
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

## Gaps

The report names three kinds of absence, because each calls for a different
next step:

- **Terms the base never uses.** Nothing to read; only research would help.
- **Sources or summaries match but no permanent note does.** Material has
  been captured but nothing was distilled into a claim — a synthesizer's
  job, not a researcher's.
- **Matched notes that no MOC reaches.** They exist but a reader walking
  down from `INDEX.md` cannot find them — a librarian's job.

Each gap comes with one suggested follow-up, shown as a ready-to-run
`capture.py` command (shell-quoted, so a query with quotes pastes safely):

| Gap | Suggestion | Why that kind |
|---|---|---|
| terms the base never uses, or nothing matched | an **inquiry** for the query | a question a run researches |
| matches but no permanent note | an **INBOX** entry naming the material to distil | an instruction to the synthesizer; the sources are already on file |
| matched notes no MOC reaches | an **INBOX** entry naming the keys to map | an instruction to the librarian |

They are printed, not run: whether a gap is worth a cycle's budget is the
user's decision, and a query that filed inquiries as a side effect would be
an operation wearing a question's clothes (A9's read-only rule).

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
  suggestions are captured, and each is logged.
- Deterministic: the same repo and query produce the same report.
