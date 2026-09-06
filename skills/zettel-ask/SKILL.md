---
name: zettel-ask
description: Researches a question now against a zettel-bootstrap Zettelkasten content repo, capturing and verifying sources, then files the notes worth keeping through the same lock, branch, and citation gates a scheduled run uses. Use when the user asks a research question they want answered now and expects the knowledge base, knowledge repo, second brain, or zettelkasten to grow from the answer, or says to look something up and add what is found. Do not use to report what the base already holds - that is zettel-query, which should usually run first - or to add a source the user already has, which is zettel-ingest.
license: MIT
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
metadata:
  version: 0.2.0
  parent: zettel-bootstrap
---

# Answer a question now

`$ARGUMENTS` is the question. Ask for the content repo path if this session
does not already know it.

Ad-hoc research uses the same lock, branch, and gate as a scheduled run. There
is no fast path to `main`, because a fast path to `main` is a path around the
citation gates.

## Run this

```sh
SCRIPTS="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)}/scripts"

"$SCRIPTS/session_cycle.sh" ask --repo <content-repo> --question "$ARGUMENTS" \
  [--priority high] [--body "extra context"]
```

**Then follow the checklist it prints.** It names the branch, the inquiry key,
and the exact command for each step.

The question is filed as an inquiry *before* any research, so a session that
is interrupted, runs out of budget, or finds nothing still leaves the question
in the repo for a later run. A question asked is never lost, even when the
answer is.

## The shape of the work

1. **Check coverage first.** The checklist opens with a `query.py` call
   against the same question. Re-researching what the base already holds is
   the most expensive mistake available here — and if it already answers,
   say so and cite the keys.
2. **Capture before you cite.** A reference note comes from
   `capture.py reference`; the source itself is fetched into `raw/` by
   `fetch_source.py`. A reference that reports UNVERIFIED needs a capture, not
   an edited verification block.
3. **Notes through the generators**, never hand-written: `capture.py
   literature` (own words, one source, with a locator) then `capture.py
   permanent` (one atomic claim, title stated as a claim, linked to its
   verified reference).
4. **Gates, then hand off**: `remote_cycle.sh gates`, then
   `remote_cycle.sh finish`. `finish` re-runs the gates itself and refuses to
   push a red branch. If it says to open the PR yourself, open it with the
   GitHub MCP tools and enable auto-merge (squash).

## Two things to get right at the end

- **Answer in chat.** The user asked a question; give them the answer with the
  sources you verified. The notes are the durable record, not the reply.
- **Close the inquiry honestly.** `answered` requires the permanent notes that
  answered it. A question you could not resolve stays `in-progress` with a
  note saying why — that record is worth more than a tidy queue.

File what is worth citing again, and nothing else. Padding the base is a cost,
not a deliverable.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | the lock is yours; follow the printed checklist |
| 3 | a scheduled run holds the lock. **Stand down and say so.** Never force it — two sessions researching one question pay twice |

Full detail: `references/capture.md`. The other two session flows are
`zettel-query` (what does the base know?) and `zettel-ingest` (add a source
the user has).
