# The orchestra

Eight subagents, defined in the plugin's `agents/` directory, grow and guard
the knowledge base. In a headless maintenance run they are loaded via
`--plugin-dir` and re-emitted through `--agents` JSON with models resolved from
the content repo's config (agents are not auto-invoked in print mode, so the
maintenance prompt delegates to them by name).

## Roles and tiers

| agent | tier | does | never |
|---|---|---|---|
| orchestrator | strong | reads INBOX first, plans, assigns worktrees, dispatches | writes notes; pushes |
| researcher | cheap | captures sources into `raw/`, reference + literature + fleeting notes | cites what it didn't capture; edits `raw/` |
| synthesizer | strong | atomic permanent notes, title-as-claim, 1-1-1 | creates reference notes; unsourced claims |
| critic | strong | claim-by-claim groundedness, rubric scores, gates merges | rewrites notes |
| librarian | cheap | MOCs, INDEX layering, tag ontology, manifest rebuild | alters claim text |
| connector | cheap | runs the sweep, then reads both notes to justify or discard each candidate | edits notes directly; trusts a score without reading |
| note-maintainer | cheap | INBOX revisions, fleeting sweep, link repair | deletes knowledge on its own judgment |
| skill-smith | strong | ≤1 child-skill proposal per cycle, under content-repo `skills/` only | touches the skill repo; re-proposes rejections |

## Model tiers (AC-29)

The `.md` files declare tier **defaults** as aliases (`opus` = strong,
`haiku` = cheap). At run time, `config.yml`'s `models: {strong, cheap}` is
authoritative. Changing tiers is a config edit, not an agent-file edit — but
the two execution paths consume agents differently, so config reaches each by
its own route:

| Path | How agents are supplied | How config reaches them |
|---|---|---|
| Laptop (`maintenance_run.sh`) | `--agents` JSON on a headless `claude -p` | `agents_json()` substitutes the models and the wrapper passes the JSON |
| Remote (session-as-agent) | the registry in `~/.claude/agents/` | `remote_cycle.sh start` calls `materialize()`, rewriting each registered file's `model:` with the resolved ID |

Both resolve through the same `resolved_models()`, so the JSON the laptop path
sends and the files the remote path reads cannot drift.

**The remote half is newer than the docs above it, and the gap it closed was
silent.** `ci/setup-environment.sh` symlinks the agent files into the registry,
so the session read the checked-in *alias* — cheap-tier agents ran Haiku no
matter what `config.yml` said, and nothing reported the discrepancy.
`materialize()` works because Claude Code watches the agents directory: a
rewrite during `start` reaches that same session's later delegations. Two rules
in that function are load-bearing — it only rewrites files that are **already**
registered (so running `start` on a laptop never conjures a registry), and it
**unlinks before writing**, because those entries are symlinks into the plugin
tree and writing through one would edit the skill repo itself.

Do not "fix" a cheap-tier agent by changing its alias to `sonnet`: that maps to
**strong** in `TIER_BY_ALIAS`, which silently promotes the agent. The alias
names a tier; `config.yml` names the model.

## Critic thresholds (QA-1)

Groundedness is scored per note as the supported fraction of its sourced
claims: **< 0.80 flags** (recorded, note stays), **< 0.70 blocks** (note does
not merge). Blocks are final for the run — nothing may be weakened to pass.

## Isolation

Research/synthesis streams run in git worktrees (`scripts/new_worktree.sh`)
under `.worktrees/` (gitignored), sharing one `.git`. The orchestrator merges
accepted branches and removes worktrees; a blocked note simply stays on its
branch. Human feedback in INBOX overrides every agent, including the critic
(QA-4) — but a correction contradicting a verified source is applied *and*
logged as a tension.

## Push authority (amendment A3)

No agent pushes — ever. The headless run commits; `maintenance_run.sh`
independently re-runs `build_manifest --check`, the three lints, and
`check_skill_sandbox.py`, and pushes only when all pass (after a rejected
push it re-pulls and re-runs everything but the sandbox check). A budget- or turn-cut run leaves
its commits local and unpushed.
