# Scheduling maintenance runs

`scripts/maintenance_run.sh` is the single entrypoint for every scheduler. It
is safe to schedule aggressively: `run.lock` guarantees only one run works at a
time (a second exits 0 without work), and nothing unlinted is ever pushed.

## Laptop cron (Mode A)

```cron
# zettel-bootstrap: weekly maintenance, Sundays 06:00 local
0 6 * * 0  cd $HOME/knowledge-base && $HOME/auto-zettel-skill/scripts/maintenance_run.sh --repo "$PWD" --mailto you@example.org >> $HOME/.zettel-cron.log 2>&1
```

Notes:
- cron's PATH is minimal — use absolute paths, and make sure `claude`, `git`,
  and `python3` resolve (set `PATH=` in the crontab or export `CLAUDE_BIN`).
- Run frequency is a cost decision: each run is a headless `claude -p` session
  billed against your normal usage/quota, capped by `budget.usd` and
  `budget.max_turns` in config.yml. Observed in testing: even a minimal cycle
  with a strong-tier model runs $1.50–2.50; a full orchestra dispatch costs
  more. Budget at least `usd: 5` / `max_turns: 40` (the genesis defaults) for
  real research runs, and follow the spec's threshold guidance — if runs
  consistently hit the cap mid-cycle, reduce researcher fan-out or space the
  connector/skill-smith cadences further apart before scaling topics.
- Result JSON and stderr logs land in `<repo>-runs/` next to the content repo
  (override with `RESULTS_DIR`).
- Connector and skill-smith work run on their own slower cadences
  (`connector_cadence`, `skill_smith_cadence` in config.yml); the maintenance
  prompt checks `log.md` to decide whether each is due, so no extra cron
  entries are needed.

## Claude Code Desktop / Cowork scheduled tasks

Both apps can run a scheduled task that fires a fresh session on your machine
with full access to files, MCP servers, skills, and plugins. Point the task at
the same command:

```
$HOME/auto-zettel-skill/scripts/maintenance_run.sh --repo $HOME/knowledge-base --mailto you@example.org
```

Caveat: desktop/Cowork tasks run **only while the app is open**. For unattended
cadence, cron (or a launchd/systemd timer wrapping the same script) is the
reliable option.

## Scheduled remote sessions (no laptop)

The fully unattended path: a Routine fires a fresh remote Claude Code session on
a configured cloud environment, which runs the cycle and hands a PR to CI. No
machine of yours needs to be awake. Setup, guarantees, and trade-offs are in
[`remote-execution.md`](remote-execution.md).

Prefer this over cron when you want maintenance to keep running while your
laptop is closed. Prefer cron when you want a hard per-run dollar cap, which
only the nested `claude -p` path provides.

## Cloud sessions and claude.ai (Mode B)

Cloud and Cowork-cloud sessions do **not** read `~/.claude/skills/` on your
machine. For the skill to exist there it must be:
- enabled for your claude.ai account (uploaded as a skill), or
- committed to the cloned repo's `.claude/skills/` directory, or
- shipped in a plugin the repo declares.

Cloud Routines could invoke maintenance on a schedule, but that path is
deferred (spec §10): per-plan daily run caps apply, and the skill must be
present in the cloud session by one of the routes above. The documented,
supported schedulers are laptop cron and desktop/Cowork tasks.

## What a scheduled run guarantees

1. Serialization: `run.lock` (stale locks broken after 6h, configurable via
   `STALE_LOCK_HOURS`).
2. Preflight: clean tree required; `git pull --ff-only` before work.
3. Budget: `--max-budget-usd` and `--max-turns` from config.yml; a cutoff run
   exits non-zero, keeps its commits local, and pushes nothing.
4. Gates: `build_manifest --check`, `lint_citations`, `lint_links` re-run by
   the wrapper after the model finishes; push only on pass, with up to three
   re-pull/re-lint retries on rejection.
5. Audit: every step stamped in the content repo's `log.md`.
