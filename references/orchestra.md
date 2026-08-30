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
| connector | cheap | cross-cluster link proposals into `proposed-links/` | edits notes directly |
| note-maintainer | cheap | INBOX revisions, fleeting sweep, link repair | deletes knowledge on its own judgment |
| skill-smith | strong | ≤1 child-skill proposal per cycle, under content-repo `skills/` only | touches the skill repo; re-proposes rejections |

## Model tiers (AC-29)

The `.md` files declare tier **defaults** as aliases (`opus` = strong,
`haiku` = cheap). At run time, `config.yml`'s `models: {strong, cheap}` is
authoritative: `python -m zettel_lib.agents --repo <repo>` re-emits every agent
with the configured model, and `maintenance_run.sh` passes that JSON to
`claude --agents`. Changing tiers is a config edit, not an agent-file edit.

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
independently re-runs `build_manifest --check`, `lint_citations`, and
`lint_links`, and pushes only when all pass. A budget- or turn-cut run leaves
its commits local and unpushed.
