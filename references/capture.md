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
| Get an answer **now** | `adhoc_research.sh` | a run branch, gated by CI |

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
it does not have. The third rule is why answers must be *permanent* notes: a
literature note summarises a source, it does not assert an answer.

## Ad-hoc research

```sh
scripts/adhoc_research.sh --repo <repo> --question "..." [--priority high] [--body -]
```

This does bookkeeping only — the research is the session's work. What it
guarantees is that an ad-hoc answer arrives by exactly the same road as a
scheduled one:

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

## Where this sits

- `references/note-types.md` — the note types and their frontmatter
- `references/remote-execution.md` — the lock, the run branch, CI as the gate
- `references/two-mode-access.md` — Mode B has no local clone, so it routes
  write intentions through `INBOX.md` rather than capturing directly
