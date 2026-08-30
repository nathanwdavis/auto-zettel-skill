# zettel-bootstrap

A Claude Code plugin that scaffolds and perpetually grows a **citation-grounded
Zettelkasten** knowledge repository on GitHub. Every sourced claim traces to a
verified reference; notes that cannot be grounded fail a lint and never land.

> **Status: Phase 1 of 4** — substrate and citation gates. The subagent
> orchestra, scheduled maintenance runs, serendipity sweeps, and skill
> emergence arrive in Phases 2–4. See [`PLAN.md`](PLAN.md).

## Two repositories

This is the **skill repo** — private, and it contains only the plugin. Your
notes live in a separate **content repo** that `init_content_repo.sh` creates
for you at genesis, public or private as you choose. They never mix.

## Install

### Prerequisites

- [`gh` CLI](https://cli.github.com), authenticated: `gh auth login`
  (needs a PAT or SSH key with `repo` scope to create the content repo)
- Python 3.11+

### As a plugin

```sh
/plugin marketplace add nathanwdavis/auto-zettel-skill
/plugin install zettel-bootstrap@auto-zettel-skill
```

### Or as a plain skill

```sh
git clone git@github.com:nathanwdavis/auto-zettel-skill.git
ln -s "$PWD/auto-zettel-skill/skills/zettel-bootstrap" ~/.claude/skills/zettel-bootstrap
```

### Python dependencies

```sh
pip install -r requirements.txt
```

This pulls `pypandoc-binary`, which ships its own pandoc build — no system
pandoc install needed. See
[`references/citation-rules.md`](references/citation-rules.md) for why pandoc
rather than citeproc-py renders the Chicago strings.

## Use

Ask Claude to start a knowledge base and the skill triggers on its own. To
drive the scripts directly:

### Genesis — create the content repo

```sh
scripts/init_content_repo.sh \
  --name my-knowledge-base \
  --visibility private \
  --owner <your-github-username> \
  --topics "topic one, topic two" \
  --cadence weekly \
  --budget 5
```

Add `--no-remote` to scaffold and commit locally without touching GitHub. The
script refuses to clobber an existing repo or a non-empty directory.

### The gates — run before every commit

```sh
scripts/verify_refs.py    --repo <content-repo> --mailto you@example.org
scripts/build_manifest.py --repo <content-repo>
scripts/lint_citations.py --repo <content-repo>
scripts/lint_links.py     --repo <content-repo>
```

The lints exit non-zero and print `FILE⇥RULE⇥REASON` for each problem.
`verify_refs.py --offline` verifies from `raw/` captures only when there is no
network.

## How notes are named

```
permanent/atomic-notes-compound-over-time--202608301412.md
```

Filenames and `[[links]]` both use this key, so a vault listing reads as titles
rather than timestamps. The trailing id is immutable and the slug is frozen at
creation — rewording a note's `title` never moves the file or breaks a link.

## Layout

```
.claude-plugin/plugin.json   plugin manifest
skills/zettel-bootstrap/     SKILL.md (entry point)
references/                  architecture, note types, citation rules
templates/                   note, config, and child-skill templates
scripts/                     genesis, manifest, verification, lints
  zettel_lib/                shared library (see note below)
  csl/                       bundled Chicago style + provenance
tests/                       pytest suite and cassettes
docs/REQUIREMENTS.md         the specification, with amendments
```

`scripts/zettel_lib/` is an addition to the layout the spec prescribes: the
four Python scripts share frontmatter parsing, note naming, repo access, HTTP,
and citation rendering, and duplicating those across four entry points would
guarantee they drift.

## Tests

```sh
pip install -r requirements-dev.txt
./smoke_test.sh
```

`smoke_test.sh` runs the full pytest suite plus an end-to-end genesis scaffold.

Two acceptance checks cannot run in a sandboxed or offline environment and are
**manual steps on a networked machine**:

- `gh repo create` — the live publish path (`--no-remote` covers the rest).
- Live metadata lookups — `verify_refs.py --repo <repo> --mailto you@example.org`
  against a real DOI and ISBN. The suite covers the parsing and state-writing
  with recorded-shape cassettes; see [`tests/cassettes/README.md`](tests/cassettes/README.md).

## Security

No token, key, or `.env` is ever committed to either repo. Auth goes through
`gh`, the SSH agent, or environment variables. `.gitignore` excludes
`run.lock`, `*.token`, `.env`, `*.pem`, and local caches.

## License

MIT. The bundled CSL style is CC BY-SA 3.0 — see
[`scripts/csl/README.md`](scripts/csl/README.md).
