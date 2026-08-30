---
name: zettel-bootstrap
description: Scaffolds and perpetually grows a citation-grounded Zettelkasten knowledge repository on GitHub, where every claim traces to a verified source. Use when the user wants to start a research knowledge base or "second brain" on a topic, grow or maintain an existing zettelkasten content repo, add notes from sources, verify citations, repair links, or run the citation and link gates. Also use when the user mentions their zettelkasten, knowledge repo, permanent or literature notes, Maps of Content, or asks to schedule recurring research runs.
license: MIT
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
metadata:
  version: 0.1.0
  phase: "1 (substrate + citation gates)"
---

# Zettel Bootstrap

Cultivates a Zettelkasten knowledge repository where **every sourced claim
traces to a verified reference**. Unverifiable notes fail a lint and never land.

Two repositories, never mixed:

- **Skill repo** (this one, private) — the plugin. Never contains notes.
- **Content repo** — created at genesis by `scripts/init_content_repo.sh`.
  Holds all knowledge. Public or private, chosen at genesis.

## Choosing what to do

| Situation | Go to |
|---|---|
| No content repo exists yet | [Genesis](#genesis) |
| Content repo exists, user asks a question or wants growth | [Adding knowledge](#adding-knowledge) |
| Before any commit to the content repo | [The gates](#the-gates) |
| User asks how a piece works | `references/` (below) |

## Genesis

Run once. Ask the user for **topics**, **content-repo name**, **visibility
(public or private)**, **cadence**, and **budget** — never guess these.

```sh
scripts/init_content_repo.sh \
  --name <repo> --visibility <public|private> --owner <gh-owner> \
  --topics "topic one, topic two" --cadence weekly --budget 5
```

Requires `gh` authenticated (`gh auth login`). Add `--no-remote` to scaffold
locally without creating the GitHub repo. The script refuses to clobber an
existing repo or a non-empty directory.

It scaffolds the substrate, writes `config.yml`, commits, and pushes. Then do a
first knowledge pass: capture at least one source per topic into `raw/`, write
its reference and literature notes, distil one permanent note, build `INDEX.md`
and one MOC, run [the gates](#the-gates), and commit.

## Adding knowledge

Read `INBOX.md` **first** — human feedback there is authoritative and overrides
any automated decision.

For each source:

1. **Capture** the source verbatim into `raw/`. This is what makes it
   verifiable. Never write a reference note for something you did not fetch or
   cannot look up authoritatively.
2. **Reference note** (`reference/`) — one per source, from
   `templates/reference.md`. Fill `csl_json`; leave the Chicago strings empty
   and let `verify_refs.py` render them. Never hand-write them.
3. **Literature note** (`literature/`) — your own words, one source, with a
   locator. Never paste source prose.
4. **Permanent note** (`permanent/`) — one atomic idea, title stated as a
   claim, at least one outbound typed link. Every sourced claim links to a
   verified reference note.
5. **MOC** (`moc/`) — link the new note in. `INDEX.md` links only to MOCs.

### Naming notes

Filenames and links both use the note key: `<title-slug>--<timestamp-id>.md`,
for example `atomic-notes-compound-over-time--202608301412.md`.

- `id` is the immutable timestamp (`YYYYMMDDHHMM`); it never changes.
- The slug is **frozen at creation**. When a title is reworded, edit
  `title` in frontmatter and leave the filename alone — that is what keeps
  links stable.
- Link with `[[atomic-notes-compound-over-time--202608301412]]`. A bare
  timestamp also resolves, via the manifest's `id_to_key` map.

Typed links live in frontmatter, and the relation must be one of:
`supports`, `contradicts`, `analogous`, `shared-concept`,
`historical-connection`, `elaborates`, `refutes`, `source`.

See `references/note-types.md` for the full rules per note type.

## The gates

Run all four, in order, before every commit. **A failing gate means do not
commit and do not push** — fix the notes instead.

```sh
scripts/verify_refs.py    --repo <repo> --mailto <you@example.org>
scripts/build_manifest.py --repo <repo>
scripts/lint_citations.py --repo <repo>   # hard-fails on ungrounded claims
scripts/lint_links.py     --repo <repo>   # hard-fails on broken/foreign links
```

`verify_refs.py` records state and exits 0 even with unverified references —
`lint_citations.py` is the gate that fails. Use `--offline` to verify from
`raw/` captures only when there is no network.

Lints print `FILE⇥RULE⇥REASON` lines. Each names the note and what to fix.

Never make a lint pass by weakening it, deleting the offending note, or
back-filling a citation you did not verify. Fix the note or capture the source.

## Reference material

Read these only when the task calls for them:

| File | Covers |
|---|---|
| `references/architecture.md` | Repo topology, the three layers, run flow |
| `references/note-types.md` | Every note type, frontmatter, the 1-1-1 rule |
| `references/citation-rules.md` | Chicago rendering, verification, scripture, source tiers |

## Rules that do not bend

- No token, key, or `.env` is ever committed to either repo.
- The `raw/` layer is immutable — captures are never edited.
- Knowledge notes are never rolled back to make something else pass.
- This skill's own repo is never modified by a run against a content repo.
