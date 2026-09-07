---
name: zettel-query
description: Maps what a zettel-bootstrap Zettelkasten content repo already knows about a topic - the related claims, sources, and maps of content, plus the top gaps in that coverage - and can file those gaps for research on the user's approval. Use when the user asks what their knowledge base, knowledge repo, second brain, or zettelkasten already has on a subject, what it says about something, where its coverage is thin, or what is missing. Read-only by default. Do not use to research a question the base cannot answer - that is zettel-ask - or to add a source, which is zettel-ingest.
license: MIT
allowed-tools: Read, Bash, Glob, Grep
metadata:
  version: 0.3.0
  parent: zettel-bootstrap
---

# What does the base already know?

`$ARGUMENTS` is the question or search term. Ask for the content repo path if
this session does not already know it.

This is a **different request** from "find out about X". Answer it from the
repo and only the repo: researching turns a question into a run, and runs go
through the lock and the gates.

## Step 1 — read the map

```sh
SCRIPTS="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)}/scripts"

"$SCRIPTS/query.py" --repo <content-repo> "$ARGUMENTS" [--top 15]
```

It ranks every note against the query, groups the matches by type — claims
(permanent notes), literature notes, sources on file with their verification
state, maps of content — lists the open inquiries that touch the topic, adds
the notes one link away, and names the gaps. Add `--mermaid` when the shape of
the neighbourhood is the answer; it appends a diagram to the same report.

The script writes nothing. Not a note, not an inquiry, not even a log line.

## Step 2 — answer, citing keys

Answer in chat from the report, naming note keys so the user can open them.
Read the top notes if the report alone cannot settle it. **Do not research,
fetch sources, or write notes.**

Say plainly when the base has nothing. Terms that appear in no note at all are
reported separately, and that is the most useful negative result a knowledge
base can give — far better than a weak match dressed up as coverage.

## Step 3 — end with the gaps, and offer

The report names eight kinds of absence, each carrying an id and listed in the
order they should be worked:

| Gap | What it means | Who closes it |
|---|---|---|
| `unresearched` | terms the base never uses; only research helps | a researcher |
| `weak-sourcing` | a claim resting only on general-web sources | a researcher |
| `stale-inquiry` | a question asked long ago and never worked | whoever works or archives it |
| `undistilled` | material captured, nothing distilled into a claim | a synthesizer |
| `unsummarised-reference` | a source on file that nobody has read | a synthesizer |
| `orphan-claim` | a claim nothing else links to | a connector |
| `unmapped` | notes exist but INDEX cannot reach them | a librarian |
| `raw-mentions` | a term only a `raw/` capture uses (needs `--include-raw`) | a synthesizer |

List them **with their ids** and say that on the user's word you will act.
**Never file unasked.** Then, when told to, pick one:

```sh
# File every gap for the next scheduled run to pick up:
"$SCRIPTS/query.py" --repo <content-repo> "$ARGUMENTS" --file-gaps

# Or just the ones the user chose:
"$SCRIPTS/query.py" --repo <content-repo> "$ARGUMENTS" --file-gaps g1,g3

# Or file them AND work them now, in this session:
"$SCRIPTS/session_cycle.sh" query --repo <content-repo> --from-query "$ARGUMENTS"
```

The second claims the lock and opens a run branch **before** filing, so the
captures land in this cycle's PR rather than in a working tree the next run
overwrites. It prints a checklist for the work; follow it. Exit 3 means a
scheduled run holds the lock: stand down and say so.

After a plain `--file-gaps`, commit the captures; from a remote session that
means a branch and a PR, like any other capture.

## Without a local clone (Mode B)

Fetch `manifest.json`, match the query against `title` and `tags` there, then
fetch the best few notes with `fetch_remote.py --keys` and answer from those.
**Say that the ranking was metadata-only.** Details:
`references/two-mode-access.md`.

Full detail on ranking and the report: `references/query.md`.
