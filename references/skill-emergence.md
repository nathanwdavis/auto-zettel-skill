# Skill emergence

How the knowledge base grows its own procedures (spec §9.4, FR-33–FR-37),
adapted from WikiSkill (arXiv:2608.27454 §3.1) for an open world with no
ground-truth labels: the paper's score-improvement gate is replaced by an A/B
trial plus a **required human approval**, trading autonomy for safety on
purpose. Expect human-paced adoption; that is the design, not a limitation.

## The three layers, and why the asymmetry is load-bearing (FR-33)

| Layer | Contents | Rule |
|---|---|---|
| **Raw** | `raw/`, run traces | Immutable. Never edited or deleted; additions only. |
| **Knowledge** | notes, `manifest.json`, `log.md`, `skill-impact.md` | Compounds. **Never rolled back**, whatever a proposal's outcome. |
| **Skill** | `skills/<name>/` | Gated and rollbackable. Requires human promotion. |

A rejected child skill reverts; the knowledge it was proposed against stays.
The tracker itself belongs to the knowledge layer: a rejection *appends* to
`skill-impact.md`, it never erases the proposal from it.

## Lifecycle

1. **Propose** — on `skill_smith_cadence`, the skill-smith agent reads the
   manifest/INDEX, the full `skill-impact.md` history, and ≥4 recent run
   traces (FR-34), then makes **at most one** create-or-patch proposal
   (FR-35): `skills/<name>/SKILL.md` + `PURPOSE.md`, from the templates,
   with PURPOSE citing the motivating note keys. Its final act is
   `skill_review.py propose`, which captures the unified diff while the cycle
   base is unambiguous and records it (amendment A7). A patch to an approved
   skill flips PURPOSE back to `status: proposed` — it re-enters review, and
   the flip marks the pre-patch commit as the rejection restore point.
2. **Trial** — `skill_trial.py` answers the repo's own inquiry questions in
   two throwaway copies of the tree, with and without the candidate, and
   records groundedness (paired judge on the critic rubric) plus mechanical
   citation-coverage means as a `trial` record. The scheduled paths run it
   automatically after a proposal (the Mode-A wrapper; step 7 of the remote
   prompt); a human can rerun it any time. Cost is bounded: it fires at most
   once per proposal cycle, `trial_questions` (default 3) questions × 3
   cheap-tier read-only calls.
3. **Decide** — a human, always (FR-36, QA-5):
   `skill_review.py promote|reject --skill <name> --reason "..."`.
   Promotion flips PURPOSE to `approved`; later runs read approved skills as
   house procedure (maintenance step 3). Rejection reverts `skills/<name>/`
   to the last approved commit — removal, for a rejected create — and appends
   the outcome, diff, and scores to `skill-impact.md`. A rejected **create's
   name is permanently banned** (`re-proposed-skill` lint); a rejected patch
   is permanent history the smith must read, but the skill can still evolve.

## The sandbox, honestly (FR-37 / AC-37)

A `claude` session's writes cannot be intercepted in-process, so enforcement
is layered, and each layer is only as fine-grained as its diff:

| Layer | Mechanism | Catches |
|---|---|---|
| Structural, Mode A | `maintenance_run.sh` snapshots the plugin tree around the headless run; any change aborts unpushed | any write into the skill repo — the AC-37 red line |
| Structural, Mode B | the plugin is a fresh CI checkout; the required `gates` check is server-side | same, by construction |
| Diff gate, whole cycle | `check_skill_sandbox.py --base <pre-run HEAD>` in the wrapper and in CI | log.md rewrites, skill-impact.md edits, raw/ modification |
| Diff gate, smith-scoped | `--strict` on the smith's isolated diff (worktree, or pre/post HEAD remotely) before merging it | any smith write outside `skills/` + the two ledgers |
| Wellformedness | `lint_skills.py`, everywhere the other lints run | malformed skills, bad status, uncited PURPOSE, re-proposed creates |
| Human | approval required for promotion; PR review in Mode B | everything judgment-shaped |

The stated limit: at whole-cycle granularity a smith edit to a note is
indistinguishable from legitimate note-maintainer work — that is what the
strict smith-scoped check is for, and the critic, the lints, and the human
PR review are the residual backstop.

Budget rails: Mode A passes `--max-budget-usd`/`--max-turns` from config.yml;
a remote session has no budget flag (amendment A5), so remote cost is bounded
by cadence, prompt scope, model tier, and the trial's fixed call count.

## Command surface

- `skill_review.py propose --skill <name> --kind <create|patch> --motivation "..." [--base <ref>]`
  — the smith's final act; `--base` is the ref the FR-36 diff is captured
  against (default `HEAD`). Refuses a re-proposed rejected create
  (`re-proposed-skill`) and a second proposal in the open cycle
  (`second-proposal`, FR-35).
- `skill_review.py list [--json]`, `promote --skill --reason [--scores <trial.json>]`,
  `reject --skill --reason [--scores ...]`.
- `skill_trial.py --skill <name> [--questions N] [--model <id>] [--max-turns N] [--out <file>] [--seed N]`
  — the A/B trial; defaults come from config.yml (`trial_questions`,
  `models.cheap`).

## skill-impact.md format

The genesis 5-column table stays as the index; every event also appends a
`## <proposal_id> <event> <skill> (<date>)` detail section at end of file
carrying kind, motivation/reason, scores, and the fenced unified diff.
"Append-only" is therefore **semantic** — every existing row and section must
survive byte-identical; additions may land at the table bottom and file end —
enforced by `zettel_lib/impact.py`, whose `append_record` is the only writer.

## Rolling out to an existing content repo

`ci/content-repo-gates.yml` is *copied into* content repos, and cloud
environments cache `ci/setup-environment.sh` per environment. An existing
content repo picks up the two new gate steps only when the workflow file is
re-copied (and `ZETTEL_SKILL_REF`, if pinned, is bumped). Until then the
Mode-A wrapper still enforces everything locally; only the CI half is stale.
