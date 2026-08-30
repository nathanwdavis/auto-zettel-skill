# zettel-bootstrap

A Claude Code plugin that scaffolds and perpetually grows a **citation-grounded
Zettelkasten** knowledge repository on GitHub. Every sourced claim traces to a
verified reference; notes that cannot be grounded fail a lint and never land.

> **Status: Phase 2 of 4** — substrate, citation gates, the agent orchestra,
> scheduled maintenance runs, and two-mode access. Serendipity sweeps (Phase 3)
> and skill emergence (Phase 4) remain. See [`PLAN.md`](PLAN.md).

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

### Maintenance — scheduled, unattended growth

```sh
scripts/maintenance_run.sh --repo <content-repo> --mailto you@example.org
```

One entrypoint for cron, launchd/systemd, or a desktop/Cowork scheduled task.
It serializes on `run.lock`, pulls, runs a headless `claude -p` session that
dispatches the 8-agent orchestra in isolated worktrees, then **re-runs the lint
gates itself and pushes only if they pass** — the model commits, the wrapper
pushes, so a runaway or budget-cut run can never push unlinted state. Budget
and turn caps come from the content repo's `config.yml`. `--dry-run` does
everything except the push. A working crontab line and the desktop/cloud
caveats are in [`references/scheduling.md`](references/scheduling.md).

### Remote reading (Mode B)

No local clone (claude.ai, the API)? `scripts/fetch_remote.py` fetches the
manifest and specific notes from inside a code-execution container — raw URLs
for public repos, the GitHub API with a `GITHUB_TOKEN` env var for private
ones (private repos otherwise require the GitHub MCP connector). All five
remote paths: [`references/two-mode-access.md`](references/two-mode-access.md).

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
agents/                      the 8 subagent definitions
scripts/                     genesis, maintenance, manifest, verification, lints
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

The maintenance runner is tested with a stub `claude` binary (locking, gate
enforcement, push authority) plus a real capped headless run where possible.

## Security

No token, key, or `.env` is ever committed to either repo. Auth goes through
`gh`, the SSH agent, or environment variables. `.gitignore` excludes
`run.lock`, `*.token`, `.env`, `*.pem`, and local caches.

## License

MIT. The bundled CSL style is CC BY-SA 3.0 — see
[`scripts/csl/README.md`](scripts/csl/README.md).
