# zettel-bootstrap

A Claude Code plugin that scaffolds and perpetually grows a **citation-grounded
Zettelkasten** knowledge repository on GitHub. Every sourced claim traces to a
verified reference; notes that cannot be grounded fail a lint and never land.

> **Status: all 4 phases shipped** — substrate, citation gates, the agent
> orchestra, scheduled maintenance (laptop cron *and* fully remote via
> Routines + CI gating), two-mode access, the serendipity sweep, human capture
> with tracked inquiries and ad-hoc research, and skill emergence: the base
> proposes its own child skills, A/B-trials them on its own questions, and a
> human decides. See [`PLAN.md`](PLAN.md).

## Two repositories

This is the **skill repo** — it contains only the plugin, never notes. Your
notes live in a separate **content repo**, scaffolded by `init_content_repo.sh`
at genesis. They never mix. Both repos are public: the skill has no secrets in
it (auth always comes from `gh`, the SSH agent, or environment variables), and
a public skill repo is what lets cloud environments install it with no token.

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
pandoc install needed. `requirements-optional.txt` adds
`sentence-transformers` for embedding-based serendipity scoring; it is opt-in
because it pulls torch (~1–2 GB), and the sweep works without it. See
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

### Capture — getting a thought, question, or note into the repo

```sh
scripts/capture.py --repo <content-repo> fleeting "A thought" --tags networks
scripts/capture.py --repo <content-repo> inquiry  "A question" --priority high
scripts/capture.py --repo <content-repo> inbox    "Feedback for the next run"
pbpaste | scripts/capture.py --repo <content-repo> fleeting "Clipped" --body -
```

Never hand-write a note file. The gates demand exact frontmatter, and a
malformed file in `fleeting/` fails the manifest build for the *next scheduled
run* — the person who dropped it never sees the breakage. `capture.py`
generates artifacts that already pass every gate, and allocates note IDs around
the ones already taken so two captures in the same minute cannot collide.

An **inquiry** is an open question tracked across runs
(`new → in-progress → answered → archived`). Runs work the `new` ones first;
`scripts/inquiries.py --repo <content-repo> [--status new] [--json]` lists them.
`lint_links.py` refuses to let an inquiry be marked `answered` without a
`result_notes` backlink to the permanent note that answered it.

### Query — what does the base already know?

```sh
scripts/query.py --repo <content-repo> "atomic notes" [--top 15] [--json]
```

Ranks every note against the query, groups the matches by type (claims,
literature, sources with their verification state, maps), lists open
inquiries that touch the topic and the notes one link away, and names the
gaps: terms the base never uses, matches with no distilled claim, notes no
MOC reaches. It reads only — no research, no notes, no log line — and ends
with one suggested follow-up per gap as a ready-to-run `capture.py` command.
Add `--file-gaps` (or tell the session to) and it captures them all for the
next run. Details: [`references/query.md`](references/query.md).

### Ad-hoc research — answering a question now

```sh
scripts/adhoc_research.sh --repo <content-repo> --question "..." --priority high
```

Claims the same lock as a scheduled cycle, files the question as an inquiry,
and opens a run branch. Research, then hand off with `remote_cycle.sh finish`:
the answer reaches `main` only through the required check, exactly like
scheduled work. Exit 3 means a scheduled run holds the lock — stand down, do
not force it. Details: [`references/capture.md`](references/capture.md).

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

### Serendipity — surfacing unplanned connections

```sh
scripts/serendipity_sweep.py --repo <content-repo>
```

Builds the link graph, detects communities with Louvain, and writes
cross-community candidate links into `proposed-links/`. Scoring uses the
standard library by default; set `embedding.enabled: true` in the content
repo's `config.yml` and install `requirements-optional.txt` to use
sentence-transformers instead (it degrades back to lexical, with a logged
warning, if the model is unavailable).

The sweep never edits notes and always exits 0 — a candidate is a reason to
look, not a link. The connector agent reads both notes and justifies or
discards each one; the critic writes accepted links into both notes. Details:
[`references/serendipity.md`](references/serendipity.md).

### Skill emergence — the base grows its own procedures

On `skill_smith_cadence` (monthly by default) a maintenance cycle's
skill-smith may propose **one** child skill into the content repo's
`skills/<name>/` — never into this repo; that rail is enforced in code, not
prose. An A/B trial then answers the repo's own open inquiries with and
without the candidate (read-only, cheap-tier) and records the scores in
`skill-impact.md`. Promotion is always yours:

```sh
scripts/skill_review.py --repo <content-repo> list
scripts/skill_review.py --repo <content-repo> promote --skill <name> --reason "..."
scripts/skill_review.py --repo <content-repo> reject  --skill <name> --reason "..."
```

Rejection reverts only the skill layer — knowledge notes are never touched —
and is permanent history: a rejected create is never proposed again. Approved
skills are read by later runs as house procedure. The full design, including
what `lint_skills.py` and `check_skill_sandbox.py` enforce and where:
[`references/skill-emergence.md`](references/skill-emergence.md).

### Fully remote scheduled runs (no laptop)

A Routine fires a fresh remote session on a cloud environment whose setup
script (`ci/setup-environment.sh`) has already installed this skill. The
session claims a **git-branch lock** (`scripts/zettel_lib/gitlock.py` — a
container-local lock file can't serialize two ephemeral containers), works on a
`zettel/run-*` branch via `scripts/remote_cycle.sh`, and hands a PR to CI.
`ci/content-repo-gates.yml`, installed in the content repo with `gates` as a
**required status check**, decides what reaches `main` — enforcement no session
can bypass.

Three one-time settings on the content repo make that real, and the workflow
alone does not: make **`gates` a required status check** on `main` (Settings →
Rules → Rulesets), and enable **Allow auto-merge** and **Automatically delete
head branches** (Settings → General → Pull Requests). Without the required
check a red PR still merges on a click; without auto-merge every green run
waits on a human; without branch deletion `zettel/run-*` branches accumulate,
since sessions cannot delete remote branches. Full walkthrough:
[`references/remote-execution.md`](references/remote-execution.md).

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
scripts/lint_skills.py    --repo <content-repo>
```

The lints exit non-zero and print `FILE⇥RULE⇥REASON` for each problem.
`lint_links.py` also enforces the inquiry lifecycle (AC-6).
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
scripts/                     genesis, capture, query, maintenance, manifest, verification, lints
  zettel_lib/                shared library (see note below)
  csl/                       bundled Chicago style + provenance
ci/                          content-repo gate workflow + cloud env setup
tests/                       pytest suite and cassettes
.claude/CLAUDE.md            guidance for developing the skill itself
docs/REQUIREMENTS.md         the specification, with amendments
PLAN.md                      phase status and build order
```

`scripts/zettel_lib/` is an addition to the layout the spec prescribes: the
Python entry points share frontmatter parsing, note naming, repo access, HTTP,
citation rendering, similarity scoring, and the git lock, and duplicating those
across eighteen entry points would guarantee they drift.

## Working on the skill itself

[`.claude/CLAUDE.md`](.claude/CLAUDE.md) has the conventions, the environment's sharp edges,
and the one invariant that governs every change: never make a gate pass by
weakening it.

## Tests

```sh
pip install -r requirements-dev.txt
./smoke_test.sh
```

`smoke_test.sh` runs the full pytest suite (393 tests) plus an end-to-end
genesis scaffold. To run pytest alone, use the virtualenv's interpreter —
`pytest` is generally not installed in the system python:

```sh
.venv/bin/python -m pytest -q
```

Three acceptance checks cannot run in a sandboxed or offline environment and
are **manual steps on a networked machine**:

- `gh repo create` — the live publish path (`--no-remote` covers the rest).
- Live metadata lookups — `verify_refs.py --repo <repo> --mailto you@example.org`
  against a real DOI and ISBN. The suite covers the parsing and state-writing
  with recorded-shape cassettes; see [`tests/cassettes/README.md`](tests/cassettes/README.md).
- Live `sentence-transformers` scoring — the embedding path is unit-tested with
  an injected encoder; downloading real model weights needs network access to
  HuggingFace.

The maintenance runner is tested with a stub `claude` binary (locking, gate
enforcement, push authority) plus a real capped headless run where possible.

## Security

No token, key, or `.env` is ever committed to either repo. Auth goes through
`gh`, the SSH agent, or environment variables. `.gitignore` excludes
`run.lock`, `*.token`, `.env`, `*.pem`, and local caches.

## License

MIT. The bundled CSL style is CC BY-SA 3.0 — see
[`scripts/csl/README.md`](scripts/csl/README.md).
