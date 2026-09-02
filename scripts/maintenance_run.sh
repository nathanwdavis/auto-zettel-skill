#!/usr/bin/env bash
# Cron entrypoint for a zettel-bootstrap maintenance run (FR-25, FR-28, FR-30).
#
# Wraps a headless `claude -p` invocation. The headless run performs the
# maintenance cycle and COMMITS but never pushes; this wrapper then re-runs the
# lint gates independently and pushes only if they pass (amendment A3), so a
# runaway or budget-cut run structurally cannot push unlinted state.
#
# Serialized via run.lock: a second concurrent run exits 0 without work.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REPO=""; MAILTO=""; DRY_RUN=0
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
PYBIN="${PYTHON:-python3}"
command -v "$PYBIN" >/dev/null 2>&1 || { echo "error: python not found: $PYBIN" >&2; exit 1; }
PYBIN="$(command -v "$PYBIN")"
STALE_LOCK_HOURS="${STALE_LOCK_HOURS:-6}"

usage() {
  cat <<'USAGE'
Usage: maintenance_run.sh --repo <content-repo> [--mailto <email>]
                          [--dry-run] [--claude-bin <path>]

  --repo        path to the content repository (required)
  --mailto      contact email for Crossref polite-pool routing
  --dry-run     run everything, including the gates, but never push
  --claude-bin  claude binary to invoke              [default: claude]

Environment: CLAUDE_BIN, PYTHON, STALE_LOCK_HOURS override defaults.
Exit codes: 0 ok (or lock held by a fresh run); 2 usage error; 1 any other failure.
USAGE
}

die() { echo "error: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --mailto) MAILTO="${2:-}"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    --claude-bin) CLAUDE_BIN="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$REPO" ]] || { usage >&2; echo "error: --repo is required" >&2; exit 2; }
[[ -d "$REPO" ]] || die "not a directory: $REPO"
REPO="$(cd "$REPO" && pwd)"
command -v "$CLAUDE_BIN" >/dev/null 2>&1 || die "claude binary not found: $CLAUDE_BIN"

STAMP() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "- \`$(STAMP)\` $*" >> "$REPO/log.md"; }

# --- step 1: run.lock (FR-30) -------------------------------------------------
LOCK="$REPO/run.lock"
if ( set -C; echo "pid=$$ started=$(STAMP)" > "$LOCK" ) 2>/dev/null; then
  trap 'rm -f "$LOCK"' EXIT
else
  # A lock exists. Fresh -> another run is active; stale -> break it.
  lock_mtime="$("$PYBIN" -c "import os,sys;print(int(os.path.getmtime(sys.argv[1])))" "$LOCK" 2>/dev/null || echo 0)"
  age_s=$(( $(date +%s) - lock_mtime ))
  if (( age_s < STALE_LOCK_HOURS * 3600 )); then
    echo "maintenance_run: another run holds run.lock (age ${age_s}s); exiting without work"
    exit 0
  fi
  echo "warning: breaking stale run.lock (age ${age_s}s > ${STALE_LOCK_HOURS}h)" >&2
  rm -f "$LOCK"
  ( set -C; echo "pid=$$ started=$(STAMP)" > "$LOCK" ) || die "could not acquire run.lock"
  trap 'rm -f "$LOCK"' EXIT
fi

# --- config (AC-2: missing keys hard-fail) ------------------------------------
CFG_JSON="$(PYTHONPATH="$SCRIPT_DIR" "$PYBIN" - "$REPO" <<'PYEOF'
import json, sys
from zettel_lib.repo import REQUIRED_CONFIG_KEYS, ContentRepo, dig
repo = ContentRepo(sys.argv[1])
cfg = repo.require_config(*REQUIRED_CONFIG_KEYS)
print(json.dumps({
    "budget_usd": dig(cfg, "budget.usd"),
    "max_turns": dig(cfg, "budget.max_turns"),
    "strong": dig(cfg, "models.strong"),
}))
PYEOF
)" || { log "maintenance_run: ABORT invalid config.yml"; die "config.yml validation failed"; }

BUDGET_USD="$(echo "$CFG_JSON" | "$PYBIN" -c 'import json,sys;print(json.load(sys.stdin)["budget_usd"])')"
MAX_TURNS="$(echo "$CFG_JSON" | "$PYBIN" -c 'import json,sys;print(json.load(sys.stdin)["max_turns"])')"
STRONG_MODEL="$(echo "$CFG_JSON" | "$PYBIN" -c 'import json,sys;print(json.load(sys.stdin)["strong"])')"

# --- pull + clean-tree preflight ----------------------------------------------
if ! git -C "$REPO" diff --quiet || ! git -C "$REPO" diff --cached --quiet; then
  log "maintenance_run: ABORT dirty working tree"
  die "content repo has uncommitted changes; refusing to run"
fi
if git -C "$REPO" remote get-url origin >/dev/null 2>&1; then
  git -C "$REPO" pull -q --ff-only origin "$(git -C "$REPO" branch --show-current)" \
    || { log "maintenance_run: ABORT pull failed"; die "git pull failed"; }
  HAS_REMOTE=1
else
  HAS_REMOTE=0
fi
PRE_HEAD="$(git -C "$REPO" rev-parse HEAD)"

# --- render prompt + agents JSON ----------------------------------------------
VERIFY_ARGS="--offline"
[[ -n "$MAILTO" ]] && VERIFY_ARGS="--mailto $MAILTO"
PROMPT="$(sed -e "s|{{REPO}}|$REPO|g" -e "s|{{VERIFY_ARGS}}|$VERIFY_ARGS|g" \
  -e "s|{{SCRIPTS}}|$SCRIPT_DIR|g" -e "s|{{PYTHON}}|$PYBIN|g" \
  "$SCRIPT_DIR/maintenance_prompt.md")"
AGENTS_JSON="$(PYTHONPATH="$SCRIPT_DIR" "$PYBIN" -m zettel_lib.agents --repo "$REPO")" \
  || die "failed to build agents JSON from config.yml"
# NFR-2 asks for "agents dispatched" in the log. The wrapper cannot see which
# delegations the session actually made, but it does know exactly which
# definitions it handed over, and that is the set any dispatch draws from.
AGENT_NAMES="$(PYTHONPATH="$SCRIPT_DIR" "$PYBIN" -m zettel_lib.agents --repo "$REPO" --names)"
log "maintenance_run: start (mode=A dry_run=${DRY_RUN} agents=${AGENT_NAMES})"
log "maintenance_run: step 1 lock acquired, pulled, HEAD=${PRE_HEAD:0:9}"

# --- steps 2-10: the headless run (FR-25) -------------------------------------
RESULTS_DIR="${RESULTS_DIR:-$REPO/../$(basename "$REPO")-runs}"
mkdir -p "$RESULTS_DIR"
RUN_ID="$(date -u +%Y%m%d%H%M%S)"
RESULT_JSON="$RESULTS_DIR/$RUN_ID.json"
RUN_LOG="$RESULTS_DIR/$RUN_ID.log"

# One comma-separated argument: several patterns contain spaces, so this must
# never be word-split (a split allowlist silently denies git add/commit).
#
# $PYBIN is allowlisted by its resolved absolute path because that is exactly
# how the prompt invokes it -- a bare `Bash(python3:*)` pattern does not match
# `/path/to/.venv/bin/python ...`, which silently denies every script call.
ALLOWED_TOOLS="Read,Write,Edit,Glob,Grep,Agent,WebSearch,WebFetch,Bash(${PYBIN}:*),Bash(python:*),Bash(python3:*),Bash(git add:*),Bash(git commit:*),Bash(git status:*),Bash(git diff:*),Bash(git log:*),Bash(git merge:*),Bash(git worktree:*),Bash(git branch:*),Bash(bash:*)"

# AC-37's red line: a run has no reason to write to the plugin repo, so any
# change to it is a sandbox violation, not a judgment call. Snapshot the tree
# around the headless run; the comparison is pre-vs-post, so a plugin checkout
# that was already dirty (a dev machine) still passes as long as the run
# itself touched nothing.
PLUGIN_PRE_STATE="$(git -C "$PLUGIN_ROOT" status --porcelain 2>/dev/null; git -C "$PLUGIN_ROOT" rev-parse HEAD 2>/dev/null)"

set +e
( cd "$REPO" && "$CLAUDE_BIN" -p "$PROMPT" \
  --plugin-dir "$PLUGIN_ROOT" \
  --add-dir "$PLUGIN_ROOT" \
  --agents "$AGENTS_JSON" \
  --output-format json \
  --max-turns "$MAX_TURNS" \
  --max-budget-usd "$BUDGET_USD" \
  --model "$STRONG_MODEL" \
  --allowedTools "$ALLOWED_TOOLS" \
  --permission-mode dontAsk \
  > "$RESULT_JSON" 2> "$RUN_LOG" )
CLAUDE_EXIT=$?
set -e

PLUGIN_POST_STATE="$(git -C "$PLUGIN_ROOT" status --porcelain 2>/dev/null; git -C "$PLUGIN_ROOT" rev-parse HEAD 2>/dev/null)"
if [[ "$PLUGIN_PRE_STATE" != "$PLUGIN_POST_STATE" ]]; then
  log "maintenance_run: SANDBOX VIOLATION plugin repo modified; nothing pushed"
  echo "SANDBOX VIOLATION: the run modified the zettel-bootstrap plugin repo (FR-37)." >&2
  echo "Inspect: git -C $PLUGIN_ROOT status; commits in $REPO are preserved locally." >&2
  exit 1
fi

if [[ $CLAUDE_EXIT -ne 0 ]]; then
  log "maintenance_run: ABORT claude exited $CLAUDE_EXIT (turn/budget cutoff or error); nothing pushed"
  echo "claude run failed (exit $CLAUDE_EXIT); see $RUN_LOG" >&2
  echo "committed-but-unpushed work, if any, is preserved in $REPO" >&2
  exit "$CLAUDE_EXIT"
fi
log "maintenance_run: headless run complete (result: $RESULT_JSON)"

# --- step 7b: A/B trial when the cycle proposed a skill (FR-36) ---------------
# The wrapper, not the session, runs the trial: it needs fresh read-only
# claude calls, and nesting them inside the headless run would cost turns and
# an allowlist hole. A failed trial does not fail the run — the proposal
# stands recorded and a human can run skill_trial.py by hand; only the human
# gate decides promotion either way.
NEW_PROPOSAL="$(git -C "$REPO" diff "$PRE_HEAD" -- skill-impact.md 2>/dev/null \
  | awk -F'|' '/^\+\|/ { gsub(/ /,"",$5); if ($5=="proposed") { gsub(/ /,"",$4); print $4 } }' | head -1)"
if [[ -n "$NEW_PROPOSAL" ]]; then
  log "maintenance_run: step 7b A/B trial for proposal $NEW_PROPOSAL"
  if PYTHONPATH="$SCRIPT_DIR" "$PYBIN" "$SCRIPT_DIR/skill_trial.py" --repo "$REPO" \
       --skill "$NEW_PROPOSAL" --claude-bin "$CLAUDE_BIN" >> "$RUN_LOG" 2>&1; then
    git -C "$REPO" add skill-impact.md log.md
    git -C "$REPO" -c user.name="zettel-bootstrap" -c user.email="noreply@localhost" \
      commit -q -m "Record A/B trial scores for $NEW_PROPOSAL"
  else
    log "maintenance_run: skill_trial FAILED for $NEW_PROPOSAL; proposal stands, run it manually"
  fi
fi

# --- independent gates (amendment A3; NFR-3) ----------------------------------
# One gate list, run before the first push AND after every merge in the retry
# loop below. The retry used to re-run only the two lints, so a merge that
# left manifest.json stale or a skill unit malformed could still be pushed.
# The sandbox check stays pre-push only: its --base is this run's starting
# HEAD, and after a merge that diff includes the other run's log.md lines,
# which the append-only rule would then blame on this run.
run_gates() {
  local ok=1 gate
  for gate in "$@"; do
    if ! PYTHONPATH="$SCRIPT_DIR" "$PYBIN" $SCRIPT_DIR/${gate%% *} --repo "$REPO" ${gate#*.py} >> "$RUN_LOG" 2>&1; then
      log "maintenance_run: GATE FAILED ${gate%% *}; nothing pushed"
      ok=0
    fi
  done
  [[ $ok -eq 1 ]]
}
MERGE_GATES=("build_manifest.py --check" "lint_citations.py" "lint_links.py" "lint_skills.py")

if ! run_gates "${MERGE_GATES[@]}" "check_skill_sandbox.py --base $PRE_HEAD"; then
  echo "gate failure after headless run; commits preserved locally, nothing pushed (see $RUN_LOG)" >&2
  exit 1
fi
log "maintenance_run: gates passed independently"

# --- push with retry (FR-28 step 10) ------------------------------------------
if [[ $DRY_RUN -eq 1 ]]; then
  log "maintenance_run: dry-run, push skipped; HEAD=$(git -C "$REPO" rev-parse --short HEAD)"
  echo "dry-run complete; nothing pushed"
  exit 0
fi
if [[ $HAS_REMOTE -eq 0 ]]; then
  log "maintenance_run: no origin remote; push skipped"
  echo "no origin remote configured; commits are local only"
  exit 0
fi

BRANCH="$(git -C "$REPO" branch --show-current)"
for attempt in 1 2 3; do
  if git -C "$REPO" push origin "$BRANCH" >> "$RUN_LOG" 2>&1; then
    log "maintenance_run: pushed $(git -C "$REPO" rev-parse --short HEAD) (attempt $attempt)"
    echo "maintenance run complete; pushed $(git -C "$REPO" rev-parse --short HEAD)"
    exit 0
  fi
  log "maintenance_run: push rejected (attempt $attempt); re-pulling and re-linting"
  # The merge commit needs an identity; a cron host may have none configured.
  git -C "$REPO" -c user.name="zettel-bootstrap" -c user.email="noreply@localhost" \
      pull --no-rebase --no-edit origin "$BRANCH" >> "$RUN_LOG" 2>&1 \
    || { log "maintenance_run: ABORT re-pull failed"; die "push retry: pull failed (see $RUN_LOG)"; }
  run_gates "${MERGE_GATES[@]}" \
    || { log "maintenance_run: ABORT re-lint failed after merge"; die "push retry: a gate failed after merge (see $RUN_LOG)"; }
done
log "maintenance_run: ABORT push failed after 3 attempts"
die "push failed after 3 attempts; see $RUN_LOG"
