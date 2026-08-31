# Remote execution

The laptop path (cron → `maintenance_run.sh` → nested `claude -p`) still works
and is documented in `scheduling.md`. This is the alternative: scheduled
maintenance running entirely as remote Claude Code sessions, with no local
machine involved at all.

## The shape of a scheduled run

```
Routine (cron schedule)
  └─> fresh remote session on a configured cloud environment
        ├─ setup script has already installed the skill  (cached)
        ├─ remote_cycle.sh start   → claim git lock, create run branch
        ├─ the session IS the agent: reads INBOX, researches, synthesizes,
        │   runs the gates, rebuilds the manifest
        └─ remote_cycle.sh finish  → push branch, open PR
              └─> GitHub Actions runs the gates
                    └─> required check passes → auto-merge to main
```

## What changed from the laptop path, and why

| Concern | Laptop | Remote |
|---|---|---|
| Scheduler | cron | Routine, fires a fresh session |
| Agent | nested `claude -p` | the session itself |
| Lock | `run.lock` on disk | a git ref (`refs/zettel/run-lock`) |
| Gates enforced by | the wrapper script | GitHub Actions required check |
| Reaches main via | wrapper pushes after re-lint | auto-merge on green CI |
| Cost ceiling | `--max-budget-usd` | cadence, prompt scope, model tier |

**The lock had to change — twice.** Each Routine firing gets a fresh container,
so a lock file on disk is invisible to every other run. The replacement lives in
the remote — and the first design (a blob at `refs/zettel/run-lock`) died on
contact with reality: the managed git proxy only permits fast-forward pushes to
ordinary **branches**, denying custom ref namespaces and all ref deletions.

So the lock is a file, `LOCK.json`, on the branch `zettel/lock`. Claiming
commits the file; releasing commits its removal; the branch just accrues a tiny
claim/release history. Mutual exclusion is still git's own: two racers push a
child of the same tip and the remote fast-forwards exactly one. A run that
finds a live lock exits 3 and stands down; only a provably stale lock (older
than the TTL, default 6h) is broken, because stealing a live one means two
sessions research the same inquiry and bill twice.

Two proxy constraints to plan around, both found by live runs:
- **Push credentials exist only for a session's source repos.** A fresh-session
  Routine has none, so its pushes 403. Spawn maintenance sessions with the
  content repo as `source_url` — in practice, create the production Routine
  from the claude.ai Routines UI, where the repo (and connectors) bind to the
  schedule.
- **Sessions cannot delete remote branches.** Enable *Settings → General →
  "Automatically delete head branches"* on the content repo so merged run
  branches are cleaned up server-side.

**Gate enforcement got stronger, not weaker.** The old guarantee was a shell
script that re-ran the lints — enforcement the agent shared a filesystem with.
Now the run can only offer a branch, and a required status check decides. The
check runs server-side, on infrastructure no session can reach. That is what
makes it safe to drop the nested `claude -p`.

**The budget cap is the real loss.** `--max-budget-usd` is a flag on `claude -p`;
a Routine-fired session has no equivalent. Cost is now bounded by how often you
schedule, how much the prompt asks for, and which model tier runs. Watch the
first few cycles rather than assuming.

## Environment setup

Create a cloud environment (claude.ai/code → cloud icon → environment settings):

- **Network access: Full.** Researchers must reach any source to *find* claims;
  verification then happens against primary sources through Crossref, arXiv,
  PubMed, and Open Library. An allowlist would break discovery and, worse, make
  "unreachable" indistinguishable from "does not exist".
- **Setup script:** `ci/setup-environment.sh`, which clones this public skill
  repo, links it into `~/.claude/skills/`, installs dependencies, and verifies
  the skill actually landed.

Because Full egress means agents read untrusted text while holding write
access, every web-reading agent carries an explicit rule that fetched content is
data and never instructions, and `raw/` captures record what was actually read.

### The cache is load-bearing

The setup script's result is **cached per environment**. The skill version
freezes at cache time: a fix pushed here will not reach scheduled runs until the
script is edited. Pin `ZETTEL_SKILL_REF` to a tag deliberately, and treat
bumping it as a release step.

## Content-repo CI

Copy `ci/content-repo-gates.yml` into the content repo as
`.github/workflows/gates.yml`, then make **gates** a required status check on
`main` (Settings → Branches → branch protection). Without that protection rule
the workflow still runs, but nothing enforces its result — the guarantee comes
from the required check, not from the workflow existing.

CI runs `verify_refs.py --offline` on purpose. It re-checks what the run
recorded against the captures committed to `raw/`, so a gate can never pass
because of a lucky live lookup at merge time.

## When a run stands down

Exit 3 from `remote_cycle.sh start` means another run holds the lock. That is
the designed outcome for overlapping schedules, not an error — the session logs
it and ends. If a container dies mid-cycle, its lock is broken by the next run
once past the TTL, so a crash costs one cycle rather than wedging the schedule.

## Ad-hoc runs share the lock

A scheduled cycle is not the only thing that claims the lock.
`scripts/adhoc_research.sh` — "answer this question now" — calls the same
`remote_cycle.sh start`, so an ad-hoc session and a scheduled firing can never
both be writing to the content repo.

The contention is real in both directions, and both are handled the same way:

- **Ad-hoc arrives while a cycle is running** → exit 3, stand down, say so.
  Nothing is left behind: the inquiry is only written *after* the lock is held.
- **A Routine fires while an ad-hoc session is researching** → the scheduled
  session exits 3 and ends. It costs one cycle, which is the right price.

Neither steals a live lock. An ad-hoc session that researches for twenty
minutes is doing exactly what the lock protects, and a scheduled run that
barged in would duplicate the work and then race it into a conflicting branch.
Only a provably stale lock (past `STALE_LOCK_HOURS`) is ever broken.

Ad-hoc work hands off through `remote_cycle.sh finish` like any cycle: a run
branch, a PR, and the required check. There is no ad-hoc path to `main`.
See `references/capture.md`.
