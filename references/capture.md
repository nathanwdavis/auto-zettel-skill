# Capture, inquiries, and ad-hoc research

Everything else in this system is machine-authored. The gates assume perfect
frontmatter because the agents always produce it. Humans do not, and should not
have to — so the input paths need their own design.

## The three routes in

| You want to | Route | Lands |
|---|---|---|
| Jot a thought before it evaporates | `capture.py … fleeting` | `fleeting/`, swept next cycle |
| Ask a question for a run to work later | `capture.py … inquiry` | `inquiries/`, worked next cycle |
| Give a run feedback or an instruction | `capture.py … inbox`, or edit `INBOX.md` | `INBOX.md`, read first each cycle |
| Get an answer **now** | `session_cycle.sh ask` | a run branch, gated by CI |
| Add a source **now** | `session_cycle.sh ingest --source` | a run branch, gated by CI |
| Close the gaps a query found **now** | `session_cycle.sh query --from-query` | a run branch, gated by CI |

## The three session flows

```sh
scripts/session_cycle.sh ask    --repo <repo> --question "..."
scripts/session_cycle.sh ingest --repo <repo> --source <file> [--title ...] [--doi ...]
scripts/session_cycle.sh query  --repo <repo> --from-query "..."
```

Different work, identical handling: each claims the same lock a scheduled
cycle claims, opens the same kind of `zettel/run-*` branch, and hands off
through the same PR and required check. There is no fast path to `main`,
because a fast path to `main` is a path around the citation gates. Exit 3 from
any of them means a live run holds the lock — stand down; never force it.

Each then prints a **checklist naming the concrete commands** for the rest of
the job, rendered with this repo's real paths the way the maintenance prompts
are. That is the point of the script: a checklist of placeholders gets
improvised around, one of real commands gets run.

- **`ask`** files the question as an inquiry *before* any research, so an
  interrupted session still leaves the question behind. Its checklist opens
  with a coverage check, because re-researching what the base already holds is
  the most expensive mistake available.
- **`ingest`** copies the file in (never consuming the caller's), captures it
  into `raw/`, writes the reference note, and hands over the page-marked text.
  A source already on file exits 1 with `duplicate_of: <key>` and releases the
  lock — that is an answer, not a failure.
- **`query`** claims the lock and opens the branch **before** filing the gaps.
  The order is the whole reason it exists: filing first would put the captures
  on whatever branch was checked out, and `start`'s own checkout would strand
  them. Nothing worth filing means no cycle: it releases the lock and says so.

Each flow is also a slash command — `/zettel-ask`, `/zettel-ingest`,
`/zettel-query` — through the sub-skills under `skills/`.

`adhoc_research.sh` remains as `session_cycle.sh ask` under its original name,
with its output contract unchanged.

### The note generators (A12)

The three routes above cover human input. The notes themselves have
generators too, for the same reason and against the same invariant — the
agents were previously told to write reference, literature, and permanent
notes from `templates/` by hand, into a repo whose gates demand exact
frontmatter:

| Kind | Command | Refuses at write time |
|---|---|---|
| reference | `capture.py --repo R reference "Title" --doi X` | a second note for a source already on file (FR-4) |
| literature | `capture.py --repo R literature "Title" --reference KEY --locator "p. 12"` | an unknown reference; an empty locator |
| permanent | `capture.py --repo R permanent "Claim" --link KEY:relation` | no link (1-1-1); a relation outside FR-5; an unresolvable target |

Each refuses at *write* time exactly what the lints refuse at *gate* time, so
a generated note cannot fail the gate it was written for.

`reference` also renders its Chicago strings and attempts verification at
creation, through the same `verify_refs` the gate uses. With a resolvable DOI,
ISBN, arXiv id, or PMID the note is gate-clean the moment it exists. Without
one — or with `--offline` — it stays honestly `verified: false` and the tool
says so:

```
UNVERIFIED: capture the source with `fetch_source.py --ref <key> --url <url>`,
then run verify_refs.py. lint_citations fails until then -- that is the gate
working, so do not hand-edit the verification block.
```

That red gate is the invariant doing its job. The way out is a capture, never
an edit to the verification block.

### Moving an inquiry along (A12)

```sh
scripts/capture.py --repo <repo> inquiry-update <key> --status in-progress
scripts/capture.py --repo <repo> inquiry-update <key> --status answered \
  --result-notes atomic-notes-compound-over-time--202608301200
scripts/capture.py --repo <repo> inquiry-update <key> --note "Why this stalled."
```

It lives in `capture.py` rather than `inquiries.py` on purpose. `inquiries.py`
is a read-only reporter (A9: a query is not an operation), and the manifest
indexes an inquiry's `status` and `result_notes` — so a writer must rebuild it
or the next `build_manifest --check` goes red on a PR that only moved a
status. `capture.py` already logs and already rebuilds.

Every check runs **before** anything is written, so a refused update leaves
the inquiry exactly as it was: `answered` needs at least one result note
(AC-6), and every result note must resolve to a **permanent** note. `--note`
appends a dated paragraph to the body, which is where an unresolved question
records why it stalled.

### Why a capture tool rather than looser gates

A plain-markdown file in `fleeting/` makes `build_manifest.py` raise. The
manifest is the first gate, so the whole run fails — and it fails for the
*scheduled cycle*, hours later, not for whoever dropped the file. The person who
made the mess never sees the breakage; the run that had nothing to do with it
takes the red PR.

Loosening the gates would fix that by removing the invariant that everything in
the repo is well-formed, which is the invariant the manifest, the lints, and
Mode-B access all rest on. Generating well-formed artifacts costs one script and
keeps the invariant:

```sh
scripts/capture.py --repo <repo> fleeting "Small worlds in citation graphs" \
  --tags networks,bibliometrics
scripts/capture.py --repo <repo> inquiry "Does peer review improve accuracy?" \
  --priority high
scripts/capture.py --repo <repo> inbox "The Ahrens note conflates two ideas"
pbpaste | scripts/capture.py --repo <repo> fleeting "Clipped" --body -
```

`--json` prints `{"kind": …, "path": …}` for programmatic callers. Every capture
appends a line to `log.md`, and a fleeting or inquiry capture also rebuilds
`manifest.json` and `.bib/refs.json` — the capture is what made them stale, and
with the `gates` check required on `main`, a capture-only PR carrying a stale
manifest cannot merge. Inbox captures skip the rebuild; `INBOX.md` is not
indexed.

Two details worth knowing:

- **Note IDs are minute-resolution**, and the manifest's `id_to_key` map is
  many-to-one. Two notes minted in the same minute would collide and a bare-ID
  link would silently resolve to the wrong one. `capture.py` allocates around
  existing IDs — stepping the recorded minute forward, never the ordering — and
  `lint_links.py` carries a `duplicate-id` rule for notes it did not write.
- **`INBOX.md` is append-only** through the tool. It is a conversation with the
  runs, and rewriting it would drop feedback a cycle has not read yet.

### Editing the repo directly

Hand-editing `INBOX.md` is fine and always has been — it is prose, not
frontmatter, and two live cycles have read human edits from it. On GitHub's web
UI, branch protection means a browser edit opens a PR rather than committing to
`main`. Let it: the PR runs the gates. An admin bypass exists and skips the
required check, which is exactly the thing the check is for.

Hand-editing an inquiry's `status` or `result_notes` is also fine. Hand-creating
a note file is not — use `capture.py`.

One directory is off-limits to *everyone*, always: **`raw/` is immutable**.
A capture is evidence — the verbatim source a citation was verified against —
and rewriting one after it has been cited is a worse precedent than any
defect in it (a malformed header, an awkward filename). Fix the tooling or
guidance that produced the defect, add a fresh capture if a better one is
needed, and leave the original alone. The sandbox gate
(`check_skill_sandbox.py`) rejects edits and deletions under `raw/` outright.

## The inquiry lifecycle (FR-6)

An inquiry is an open question, tracked across runs. It lives in `inquiries/`,
alongside the notes but **outside the graph**: it carries no typed links, is
never a link target, and never satisfies the 1-1-1 rule. It is a question
*about* the graph, not a node in it, which is why the manifest indexes it in its
own `inquiries` block rather than under `notes`.

```
new  ->  in-progress  ->  answered  ->  archived
```

A run reads every non-archived inquiry and works the `new` ones first, highest
priority first. `scripts/inquiries.py --repo <repo> [--status new] [--json]`
lists them in that order without anyone parsing markdown; it is strictly
read-only, because deciding what to work is the run's job.

`lint_links.py` enforces the schema (AC-6):

| Rule | Fails when |
|---|---|
| `unanswered-answer` | `status: answered` with empty `result_notes` |
| `result-note-type` | a `result_notes` entry is not a permanent note |
| `unresolved-result-note` | a `result_notes` entry is not in the manifest |
| `bad-status` | `status` is outside the four values |
| `missing-question` | no `question` in frontmatter |

The first is the one with teeth. Without it a run can close every question it
touches and leave the base no larger, and the status field would report health
it does not have. The second rule is why answers must be *permanent* notes: a
literature note summarises a source, it does not assert an answer.

## Dropping a source (amendment A11)

The fourth route in, for sources the pipeline cannot fetch itself: a
paywalled paper you have access to, a PDF an author sent, a page no renderer
gets through. Commit the file into `drop/` — from a clone, from a session,
or with GitHub's "Add file → Upload files", which opens a PR because `main`
is protected. `scripts/ingest_drops.py` runs at the start of every cycle
(from `remote_cycle.sh start` and `maintenance_run.sh`, not from the prompt,
so existing Routines get it) and, per file:

1. moves it to `raw/<id>-<slug>.<ext>` — immutable evidence, exactly like a
   fetched capture — and writes `raw/<id>-<slug>.txt` with the text pypdf
   extracts from **every** page, each marked `--- page N ---` so a literature
   note can cite `p. N` without reopening the PDF. Identity detection still
   reads only the first five pages: a DOI deep in a paper is almost always a
   cited work's, not the source's own;
2. writes `reference/<key>.md` with CSL-JSON: from the optional sidecar
   `<stem>.yml` (`title, author, year, doi, isbn, arxiv, pmid, url,
   source_tier, priority, notes, tags`), else from a DOI or arXiv id found in
   the text and the PDF's own metadata, enriched from Crossref when the DOI
   resolves; the tier defaults to `peer-reviewed` for a DOI and
   `reputable-secondary` otherwise; `provenance` records the original name;
3. verifies it on the capture and renders the Chicago strings immediately,
   so the artifact is gate-clean by construction;
4. files an INBOX entry — "Dropped source ready: <title>" — that the run
   works before any new inquiry: literature note from the capture, then
   synthesis, never a re-fetch.

### A source handed to a session

`drop/` is the route for a file you commit for the *next* cycle. When a
session is handed a source right now — an attachment, a path on disk — it
ingests that one file directly:

```sh
scripts/ingest_drops.py --repo <repo> --file ~/Downloads/paper.pdf \
  --title "..." --author "Ahrens, Sönke" --year 2017 --doi 10.xxxx/yyy
```

The flags stand in for the sidecar, so nothing needs writing beside the file.
The file is **copied**, never consumed — it belongs to whoever handed it over
— and only that file is ingested, so a drop someone committed for the next
scheduled cycle is not swept into this session's PR. A `--file` that turns out
to duplicate a reference already on file is deleted rather than marked, and
the command exits non-zero: nothing was handed to a future run, so there is
nothing to report in INBOX.

Two things are marked rather than ingested, so a run never creates a second
reference for one source and never silently loses a file: a drop whose
DOI/ISBN/arXiv/URL matches a reference already on file becomes
`<stem>.duplicate-of-<key>.pdf`, and one over `fetch.max_capture_mb`
becomes `<stem>.too-large.pdf`; both get an INBOX entry. Nothing in
`drop/` is ever cited; `ingest_drops.py --list` shows what is pending.

## Ad-hoc research

```sh
scripts/session_cycle.sh ask --repo <repo> --question "..." [--priority high] [--body -]
```

This does bookkeeping and instruction — the research is the session's work.
What it guarantees is that an ad-hoc answer arrives by exactly the same road
as a scheduled one:

1. **Same lock.** It calls `remote_cycle.sh start`, so an ad-hoc session and a
   scheduled cycle can never both be writing. **Exit 3 means a live run holds
   the lock: stand down.** A live lock is never stolen — two sessions
   researching the same question pay for it twice. Only a provably stale lock
   (older than `STALE_LOCK_HOURS`, default 6) is broken.
2. **Same branch.** Work goes on `zettel/run-<timestamp>`, never `main`.
3. **Same gate.** `remote_cycle.sh finish` pushes the branch and hands off to
   the required status check. Where `gh` exists it opens the PR and arms
   auto-merge itself; where it does not (remote containers), open the PR with
   the GitHub MCP tools and enable auto-merge (squash) so it lands exactly when
   the check passes. An ad-hoc session never pushes to `main` and never
   merges. The check decides, and it cannot be talked out of it.

The question is filed as an inquiry *before* any research, so a session that is
interrupted, runs out of budget, or finds nothing still leaves the question in
the repo for a later run to pick up. That is the point: a question asked is
never lost, even when the answer is.

When the research is done, answer the user in chat with the sources you
verified, file notes only if they are worth citing again, and set the inquiry's
`status` and `result_notes` either way.

## Worktrees

`scripts/new_worktree.sh --repo <repo> --name <branch>` creates an isolated
worktree under `.worktrees/` for a subagent and prints its path; `--remove`
tears one down. `init_content_repo.sh --max-turns N` sets the per-run turn
cap written to `config.yml` at genesis (default 40).

## Where this sits

- `references/note-types.md` — the note types and their frontmatter
- `references/remote-execution.md` — the lock, the run branch, CI as the gate
- `references/two-mode-access.md` — Mode B has no local clone, so it routes
  write intentions through `INBOX.md` rather than capturing directly
