# zettel-bootstrap

A Claude Code plugin that scaffolds and then perpetually grows a
**citation-grounded Zettelkasten** on GitHub. You give it a topic; it researches,
writes atomic notes, and links them — and every sourced claim traces to a
reference it verified. Notes that cannot be grounded fail a lint and never land.

It is built to keep working while you are not watching: a scheduled run opens a
pull request, a required status check re-runs every gate, and only green work
reaches `main`.

**What it needs before you start:** a GitHub account and the `gh` CLI, Python
3.11+, and — if you want it to grow on a schedule — a willingness to spend money
on model calls. A minimal weekly cycle runs roughly **$1.50–2.50** on the strong
tier; the cheap tier is the default for scheduled runs and costs less. Nothing
here is free to run unattended.

**What it is not:** a note-taking app. There is no UI. Your notes are plain
markdown in a git repository you own, readable in Obsidian or any editor, and
this plugin is the thing that fills and maintains them.

---

## What it produces

One permanent note, exactly as `capture.py` writes it — an atomic claim, typed
links to the source it rests on, and an immutable id:

```markdown
---
id: '202609070308'
key: learners-confidence-ranks-study-methods-in-the-wrong-order--202609070308
type: permanent
title: Learners' confidence ranks study methods in the wrong order
links:
- target_id: karpicke-and-blunt-on-retrieval-versus-concept-mapping--202609070307
  relation: elaborates
- target_id: karpicke-and-blunt-retrieval-practice-produces-more-learning--202609070306
  relation: source
created: '2026-09-07'
---
Students who built concept maps judged they had learned more than students who
practised retrieval, while testing showed the reverse. A learner's sense of how
well a method is working is therefore not usable as a signal for choosing
between methods.
```

And this is what asking it what it knows looks like — grouped by type, with the
gaps named and numbered so you can act on one:

```
# What the base knows about: "retrieval practice"

Matched 4 of 4 notes (permanent 1, literature 1, reference 1, moc 1).

## Claims the base makes (permanent notes)
- **Learners' confidence ranks study methods in the wrong order** -- `learners-confidence...--202609070308`
  sources: karpicke-and-blunt-retrieval-practice-produces-more-learning--202609070306

## Sources on file (reference notes)
- **Karpicke and Blunt, Retrieval Practice Produces More Learning** -- `karpicke-and-blunt...--202609070306`
  peer-reviewed · verified via raw-capture · cited by 2 note(s)

## Gaps
- g1: 2 matched note(s) sit in no map of content, so a reader walking down from
  INDEX cannot find them: ...

To file all 1 at once, re-run this query with --file-gaps; to file a selection,
name the gap ids: --file-gaps g1,g3.
```

## Two repositories

This is the **skill repo** — it contains only the plugin, never notes. Your
notes live in a separate **content repo**, scaffolded by `init_content_repo.sh`
at genesis. They never mix.

The skill repo is public and contains no secrets — auth always comes from `gh`,
the SSH agent, or environment variables — which is what lets a cloud environment
install it with no token. **Your content repo can be public or private; you
choose at genesis.**

## Install

### Prerequisites

- **`git`**, and a **GitHub account** — you will end up with *two* repositories:
  this plugin, and a separate content repo for your notes.
- **[`gh` CLI](https://cli.github.com), authenticated**: `gh auth login`
  (needs a PAT or SSH key with `repo` scope to create the content repo).
- **Python 3.11+**.
- **The `claude` CLI on your `PATH`** — scheduled maintenance runs invoke it.

### Route 1 — as a plugin

```sh
/plugin marketplace add nathanwdavis/auto-zettel-skill
/plugin install zettel-bootstrap@auto-zettel-skill
```

This installs all four skills, so `/zettel-bootstrap:zettel-ask` and its
siblings work immediately.

**Where the scripts land.** The plugin is installed under Claude's plugin
directory, not your working directory, so `scripts/capture.py` on its own will
not resolve. Inside a Claude session the plugin root is `$CLAUDE_PLUGIN_ROOT`;
set `SCRIPTS` once and every command in this README works:

```sh
SCRIPTS="$CLAUDE_PLUGIN_ROOT/scripts"
"$SCRIPTS/query.py" --repo <content-repo> "atomic notes"
```

`$CLAUDE_PLUGIN_ROOT` is set inside a Claude session and is the supported way
to find the plugin; where it unpacks on disk is an implementation detail that
can change between versions, so do not hardcode a path. **If you want to run
these scripts from your own terminal — or schedule them — use route 2**, which
gives you a directory you own.

### Route 2 — as plain skills, from a clone

Gives you a directory you own, which is the easier route if you intend to run
the scripts directly or schedule them. Link **every** skill and **every** agent —
linking only the router leaves you without the `/zettel-ask`, `/zettel-query`
and `/zettel-ingest` commands, and without the eight subagents a maintenance
run delegates to:

```sh
git clone https://github.com/nathanwdavis/auto-zettel-skill.git
cd auto-zettel-skill

mkdir -p ~/.claude/skills ~/.claude/agents
for skill in skills/*/;   do ln -sfn "$PWD/${skill%/}" ~/.claude/skills/$(basename "${skill%/}"); done
for agent in agents/*.md; do ln -sfn "$PWD/$agent"     ~/.claude/agents/$(basename "$agent");     done
```

Slash commands are then bare — `/zettel-query` — rather than namespaced.
`SCRIPTS` is just `$PWD/scripts`.

(This is the same loop [`ci/setup-environment.sh`](ci/setup-environment.sh) runs
for cloud environments, so a later sub-skill is picked up without editing it.)

### Python dependencies

```sh
pip install -r requirements.txt
```

**Install these into the interpreter that will actually run the scripts.** If
you use a virtualenv and later schedule a maintenance run under `cron` or
`launchd`, that scheduler must invoke the same interpreter — set `PYTHON` to an
absolute path in the job, or the run fails several steps in with a missing
module.

This pulls `pypandoc-binary`, which ships its own pandoc build — no system
pandoc install needed. `requirements-optional.txt` adds
`sentence-transformers` for embedding-based serendipity scoring; it is opt-in
because it pulls torch (~1–2 GB), and the sweep works without it. See
[`references/citation-rules.md`](references/citation-rules.md) for why pandoc
rather than citeproc-py renders the Chicago strings.

## Quickstart

From nothing to a grounded note. Assumes you have installed the plugin above and
run `gh auth login`.

```sh
# 1. Create the content repo. It asks for nothing it can infer, and refuses to
#    clobber an existing repo or a non-empty directory.
"$SCRIPTS/init_content_repo.sh" --name my-kb --visibility private \
  --owner <your-github-username> --topics "retrieval practice, spaced repetition"

# 2. Give it a source you already have. Anything in drop/ is ingested as
#    immutable evidence, with a reference note written for it.
cp ~/notes-on-a-paper.txt my-kb/drop/
"$SCRIPTS/ingest_drops.py" --repo my-kb --offline

# 3. Ask what it now knows.
"$SCRIPTS/query.py" --repo my-kb "retrieval practice"
```

That is a real, gate-clean repository with one verified source in it. The
[full tutorial](references/tutorial.md) takes it from there — the first
literature and permanent notes, a map of content, the gates, and putting it on a
schedule.

Or skip all of it and just ask Claude, below.

## Using it through Claude

This is the way the plugin is meant to be used. The skill triggers on its own
when you describe what you want:

> *"Start a knowledge base on spaced repetition and retrieval practice."*
> *"What do we already know about interleaving?"*
> *"Read this paper and add it to my zettelkasten."* (with a PDF attached)
> *"Look up whether spacing effects hold for motor skills, and file what you find."*

Claude will ask for anything it cannot infer — it never guesses your repo name,
owner, or visibility — and then drives the same scripts documented below.

### Slash commands

Four skills ship, so each flow is directly invocable. Through the plugin they
are namespaced (`/zettel-bootstrap:zettel-query`); through the symlink route
they are bare.

| Command | Takes | Does | Writes? |
|---|---|---|---|
| `/zettel-bootstrap` | — | the router: genesis, gates, maintenance, anything not below | depends |
| `/zettel-query <topic>` | a topic or question | maps what the base already knows and names the gaps | **nothing**, not even a log line |
| `/zettel-ask <question>` | a question | researches it now, captures and verifies sources, files the notes | claims a lock, opens a branch and a PR |
| `/zettel-ingest <file>` | a path to a PDF/md/txt | adds a source you hand it, then writes its notes | claims a lock, opens a branch and a PR |

Three things worth knowing before you use them:

- **`/zettel-query` first.** It is free and read-only, and it will often show
  you the base already answers the question — which is the cheapest possible
  outcome. `/zettel-ask` starts by running it for exactly this reason.
- **`/zettel-ask` and `/zettel-ingest` are write operations.** They claim the
  same lock a scheduled run uses, work on a `zettel/run-*` branch, and hand off
  through a pull request. There is deliberately no fast path to `main`, because
  a fast path to `main` is a path around the citation gates.
- **Exit 3 means stand down.** A scheduled run holds the lock. That is a
  success, not an error — do not force it.

## Using it yourself

Every script that touches a content repo takes `--repo <path-to-that-repo>`, and
every script answers `--help`. (`fetch_remote.py` is the one exception: it works
without a clone, so its `--repo` is a GitHub repository *name*.) The full flag
surface for all 21 entry points is in
[`references/commands.md`](references/commands.md); this is the task-shaped view.

These examples use the `SCRIPTS` you set during [install](#install). If you would
rather type bare command names, put that directory on your `PATH` instead:

```sh
export PATH="$SCRIPTS:$PATH"
```

### Get something in

```sh
# a thought, a question, feedback for the next run
"$SCRIPTS/capture.py" --repo <repo> fleeting "A thought" --tags networks
"$SCRIPTS/capture.py" --repo <repo> inquiry  "Does spacing help motor skills?" --priority high
"$SCRIPTS/capture.py" --repo <repo> inbox    "Prefer primary sources for the theology cluster"

# a source you have the identifier for
"$SCRIPTS/capture.py" --repo <repo> reference --doi 10.1126/science.1199327
"$SCRIPTS/fetch_source.py" --repo <repo> --ref <ref-key> --url <open-access-url>

# a source you have the FILE for -- the drop box
cp paper.pdf <repo>/drop/            # optional: paper.yml beside it
"$SCRIPTS/ingest_drops.py" --repo <repo>
```

**Never hand-write a note file.** The gates demand exact frontmatter, and a
malformed file in `fleeting/` fails the manifest build for the *next* scheduled
run — so the person who wrote it never sees the breakage. The generators produce
artifacts that already pass every gate. `INBOX.md` and `INDEX.md` are prose, not
notes; editing those by hand is fine and expected.

### Write the notes

```sh
"$SCRIPTS/capture.py" --repo <repo> literature "<title>" --reference <ref-key> --locator "p. 12" --body -
"$SCRIPTS/capture.py" --repo <repo> permanent  "<claim as a sentence>" --link <lit-key>:elaborates --body -
"$SCRIPTS/capture.py" --repo <repo> moc        "<subject>" --note <perm-key>
```

Then link the MOC from `INDEX.md` by hand — INDEX links only to MOCs, MOCs link
to notes. Each generator refuses at write time exactly what the lints refuse at
gate time: a second reference for a source already on file, a relation outside
the [FR-5 taxonomy](references/note-types.md), a literature note with no
locator, a map that lists nothing.

### Find out what you have

```sh
"$SCRIPTS/query.py" --repo <repo> "<topic>" [--top 15] [--json] [--mermaid] [--include-raw] [--gaps N]
"$SCRIPTS/query.py" --repo <repo> --from-file raw/<id>-<slug>.txt          # passage mode
"$SCRIPTS/query.py" --repo <repo> "<topic>" --file-gaps g1,g3              # file a selection
```

Read-only unless you pass `--file-gaps`. It ranks every note, shows the typed
links between what it found, names eight kinds of gap in the order they should
be worked, and — in passage mode — reads a captured source paragraph by
paragraph and tells you which passages the base already covers and which are
new. Details: [`references/query.md`](references/query.md).

### Do a whole piece of work, through the lock and the gates

```sh
"$SCRIPTS/session_cycle.sh" ask    --repo <repo> --question "..."
"$SCRIPTS/session_cycle.sh" ingest --repo <repo> --source ~/paper.pdf --title "..."
"$SCRIPTS/session_cycle.sh" query  --repo <repo> --from-query "..."
```

Each claims the lock, opens a run branch, and prints a checklist naming the
concrete commands for the rest of the job. These are what the slash commands
run. Exit 3 means a scheduled run holds the lock.

### Run the gates

```sh
"$SCRIPTS/remote_cycle.sh" gates --repo <repo>
```

Runs all six exactly as CI runs them: `verify_refs` (offline), `build_manifest
--check`, `lint_citations`, `lint_links`, `lint_skills`, `check_skill_sandbox`.
`remote_cycle.sh finish` runs them itself and refuses to push a red branch.

## Keeping it growing

A knowledge base that only grows when you sit down with it is a notebook. The
point of this plugin is the scheduled run.

**First, three one-time settings on your content repo.** Nothing works properly
without the first one, and the workflow file alone does not do it:

1. **Make `gates` a required status check on `main`** (Settings → Rules →
   Rulesets). Without it a red pull request still merges on a click. The gate
   workflow itself is installed for you at genesis.
2. **Allow auto-merge** (Settings → General → Pull Requests), so a green run
   lands without waiting for you.
3. **Automatically delete head branches** (same page) — sessions cannot delete
   remote branches, so `zettel/run-*` accumulates forever otherwise.

**Then pick a scheduler:**

| | Runs when | Hard cost cap | Needs |
|---|---|---|---|
| **Laptop cron / launchd** | the machine is awake | **yes** (`budget.usd`) | a local clone, `claude` on PATH |
| **Desktop / Cowork task** | the app is open | yes | the app running |
| **Cloud Routine** | always | no | a cloud environment + a Routine bound to the content repo |

```sh
"$SCRIPTS/maintenance_run.sh" --repo <repo> --mailto you@example.org [--dry-run]
```

is the entry point for the first two. It serializes on a lock, runs the 8-agent
orchestra in isolated worktrees, then **re-runs the gates itself and pushes only
if they pass** — the model commits, the wrapper pushes, so a runaway or
budget-cut run can never push unlinted state.

The cloud Routine is the only path that grows the base with your laptop closed,
and it is the one with no per-run dollar cap. Full walkthroughs, including a
crontab line and a launchd plist:
[`references/scheduling.md`](references/scheduling.md) and
[`references/remote-execution.md`](references/remote-execution.md).

## Reading your notes

They are plain markdown in a git repository. Clone it and open the directory in
[Obsidian](https://obsidian.md) — the `[[key]]` links and the `INDEX.md` →
MOC → note layering are exactly the shape Obsidian's graph expects, and note
frontmatter carries `aliases` so a bare `[[202608301412]]` resolves too. Any
editor works; nothing here is Obsidian-specific.

Without a local clone at all — from claude.ai, or an API session — there is a
remote-read path that walks `manifest.json` and fetches individual notes:

```sh
# note: --repo here is the GitHub repository NAME, not a path -- there is no clone
"$SCRIPTS/fetch_remote.py" --owner <you> --repo <repo-name> --keys <key1>,<key2>
```

Public repos need no token; private ones read `GITHUB_TOKEN` from the
environment. All five remote paths, in preference order:
[`references/two-mode-access.md`](references/two-mode-access.md).

## When something fails

**Exit codes**, shared across every entry point:

| | Means |
|---|---|
| `0` | fine |
| `1` | the tool did its job and the answer is no — a lint found violations, a fetch failed |
| `2` | you called it wrong |
| `3` | *(cycle scripts only)* a live run holds the lock. **Stand down. This is a success.** |

Lints print one line per problem as `FILE⇥RULE⇥REASON`. The common ones:

| Rule | Means | Fix |
|---|---|---|
| `unverified-reference` | `verification.verified` is not true | capture the source with `fetch_source.py`, then re-run `verify_refs.py` |
| `uncited-claim` | a permanent note makes a sourced claim but links no verified reference | link the reference, or soften the claim to what you can support |
| `missing-locator` | a literature note has no page/section | add `--locator` — re-capture it, do not hand-edit |
| `duplicate-source` | two reference notes for one source | keep one; `capture.py reference` refuses the second and names the first |
| `moc-empty` | a map of content lists nothing | `capture.py moc ... --note <key>` writes one that cannot be empty |
| `unresolved-link` / `unresolved-wikilink` | a link target is not in the manifest | rebuild the manifest, or fix the key |
| `contested-undersourced` | a note tagged `contested` rests on fewer than 3 distinct sources | find more sources, or drop the tag |

**The rule that governs all of it: never make a gate pass by weakening it**,
deleting the offending note, or back-filling a citation nobody verified. Fix the
note or capture the source. Every rule and what trips it:
[`references/quality-gates.md`](references/quality-gates.md) and
[`references/citation-rules.md`](references/citation-rules.md).

Two failures that look like bugs and are not:

- **A reference verified by DOI still fails the merge gate.** The gate re-runs
  verification *offline*, on purpose, so no gate can pass because of a lucky
  live lookup. Capture the source into `raw/` and it passes. `capture.py
  reference` tells you this when it writes such a note.
- **A cycle "did nothing".** Usually a stand-down on the lock, not a crash.
  Check `log.md` and the release reason on the `zettel/lock` branch.

## Configuration

`config.yml` in your content repo. Genesis writes every required key; the
optional ones can be absent and mean the default shown.

| Key | Req | Default | Controls |
|---|---|---|---|
| `topics` | ● | your `--topics` | what scheduled runs research |
| `cadence` | ● | `weekly` | free text or cron; how often you intend to run |
| `budget.usd` / `budget.max_turns` | ● | `5` / `40` | per-run caps (laptop path only) |
| `autonomy_level` | ● | `suggest` | reserved; no code reads it yet |
| `content_repo.{name,owner,visibility}` | ● | from genesis | visibility drives raw-URL vs API paths in the manifest |
| `embedding.enabled` / `.model` | ● | `false` / MiniLM | opt-in embedding similarity for the sweep |
| `models.strong` / `.cheap` | ● | Opus / Sonnet | which tier each agent runs on |
| `connector_cadence` / `skill_smith_cadence` | ● | `weekly` / `monthly` | sub-cadences |
| `trial_questions` | ○ | `3` | questions per A/B arm when a child skill is proposed |
| `fetch.mailto` | ○ | *(empty)* | **your real email, sent to Crossref, Unpaywall and OpenAlex.** Unpaywall is skipped without it, so open-access resolution degrades |
| `fetch.renderer` | ○ | `none` | `jina` or `firecrawl` for JavaScript-only pages — opt-in, because every rendered URL goes to that third party |
| `fetch.max_capture_mb` | ○ | `25` | a bigger capture fails the citation lint |
| `query.stale_inquiry_days` | ○ | `30` | when an open question becomes a gap |
| `query.same_claim` / `.touches` | ○ | `0.35` / `0.08` | passage-mode bands ([why these numbers](references/query.md)) |

Optional keys are deliberately outside the required set, so a repo scaffolded
before they existed keeps working with no migration.

## How notes are named

```
permanent/atomic-notes-compound-over-time--202608301412.md
```

Filenames and `[[links]]` both use this key, so a vault listing reads as titles
rather than timestamps. The trailing id is immutable and the slug is frozen at
creation — rewording a note's `title` never moves the file or breaks a link.

## Reference

Fourteen documents, read on demand, indexed at
[`references/README.md`](references/README.md). Start with the first three if
you want to understand the system rather than operate it.

**Understand it**

| | |
|---|---|
| [`architecture.md`](references/architecture.md) | the two repos, the Raw/Knowledge/Skill layers, and why the gates run in that order |
| [`note-types.md`](references/note-types.md) | every note type, the 1-1-1 rule, and the eight link relations |
| [`quality-gates.md`](references/quality-gates.md) | each gate, what it enforces, what it rejects, and where it binds |

**Do something**

| | |
|---|---|
| [`tutorial.md`](references/tutorial.md) | genesis to first scheduled run, end to end |
| [`commands.md`](references/commands.md) | every entry point and every flag |
| [`capture.md`](references/capture.md) | the four routes in, inquiries, the drop box, session flows |
| [`query.md`](references/query.md) | ranking, the graph, passage mode, the eight gap kinds |
| [`scheduling.md`](references/scheduling.md) | cron, launchd, desktop tasks, and what a run guarantees |

**Deeper**

| | |
|---|---|
| [`citation-rules.md`](references/citation-rules.md) | CSL-JSON, Chicago rendering, verification, source tiers |
| [`remote-execution.md`](references/remote-execution.md) | Routines, the git-branch lock, cloud environments, content-repo CI |
| [`two-mode-access.md`](references/two-mode-access.md) | reading a base with no local clone |
| [`serendipity.md`](references/serendipity.md) | how cross-cluster link candidates are chosen |
| [`orchestra.md`](references/orchestra.md) | the 8 subagents, their tiers, and who may write what |
| [`skill-emergence.md`](references/skill-emergence.md) | how the base proposes, trials and promotes its own child skills |

The specification itself is [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) —
FR-x, AC-x, NFR-x, QA-x, plus the numbered amendments that record every place
implementation forced a change. Code comments cite it by number.

## Working on the skill itself

These commands are for contributors working from a clone of this repository;
run them from the plugin root, not from your content repo:

[`.claude/CLAUDE.md`](.claude/CLAUDE.md) has the conventions, the environment's
sharp edges, and the one invariant that governs every change. [`PLAN.md`](PLAN.md)
tracks phase status.

```sh
pip install -r requirements-dev.txt
./smoke_test.sh          # the acceptance checklist, executable; exit 0 or it is not done
```

`smoke_test.sh` runs the full suite (630 tests) plus an end-to-end genesis
scaffold. To run pytest alone use the virtualenv's interpreter — `pytest` is
generally not in the system python. Three acceptance checks need a networked
machine and are manual: `gh repo create`, live metadata lookups, and live
`sentence-transformers` scoring.

## Security

No token, key, or `.env` is ever committed to either repo. Auth goes through
`gh`, the SSH agent, or environment variables. `.gitignore` excludes
`run.lock`, `*.token`, `.env`, `*.pem`, and local caches.

## License

MIT. The bundled CSL style is CC BY-SA 3.0 — see
[`scripts/csl/README.md`](scripts/csl/README.md).
