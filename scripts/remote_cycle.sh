#!/usr/bin/env bash
# Scaffolding for a maintenance cycle where the SESSION is the agent.
#
# In the laptop path, maintenance_run.sh wraps a nested `claude -p` and pushes
# after re-running the lints itself. In a Routine-fired remote session there is
# no outer wrapper -- the session is the agent -- so the guarantee moves to CI:
# this script pushes a BRANCH and opens a PR, and a required status check on the
# content repo decides whether it may reach main. Nothing here can bypass that.
#
# Subcommands:
#   start   refresh this skill checkout, claim the lock, create the run branch
#   finish  commit, push the branch, open a PR, enable auto-merge
#   abort   release the lock, leave the branch for inspection
#   status  report lock holder and current branch

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYBIN="${PYTHON:-python3}"
command -v "$PYBIN" >/dev/null 2>&1 || { echo "error: python not found: $PYBIN" >&2; exit 1; }
PYBIN="$(command -v "$PYBIN")"

case "${1:-}" in
  -h|--help|"") CMD="help" ;;
  *) CMD="$1" ;;
esac
shift || true
REPO=""; TTL="${STALE_LOCK_HOURS:-6}"; TITLE=""

usage() {
  cat <<'USAGE'
Usage: remote_cycle.sh <start|finish|abort|status|refresh-skill> --repo <content-repo> [options]

  start   --repo <path> [--ttl <hours>]   refresh this skill checkout, claim
                                          lock, pull, create run branch
  finish  --repo <path> [--title <text>]  commit, push branch, open PR, auto-merge
  abort   --repo <path>                   release the lock, keep the branch
  status  --repo <path>                   report lock holder and branch
  refresh-skill                           fast-forward this skill checkout itself
                                          (start also does this; takes no --repo)

Exit codes: 0 ok; 3 lock held by a live run (not an error -- stand down); 2 usage error; 1 failure.
USAGE
}

die() { echo "error: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --ttl) TTL="${2:-}"; shift 2 ;;
    --title) TITLE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$CMD" == "help" ]]; then usage; exit 0; fi

# Fast-forward the checkout this script lives in, so a scheduled run picks
# up fixes without waiting for the environment cache to be rebuilt (issue
# #7: the cached install was found 12 commits stale, silently). ff-only is
# the safety property that makes auto-refresh acceptable: it structurally
# cannot damage a dirty or diverged developer checkout -- it just declines.
# Never fails the caller: refresh is advisory, and a cycle on
# current-but-older code beats no cycle at all. Leaves the before/after
# revisions in SKILL_BEFORE/SKILL_AFTER so `start` can tell whether the
# file it is running from was just replaced.
refresh_skill_checkout() {
  SKILL_ROOT_LOCAL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  REV() { git -C "$SKILL_ROOT_LOCAL" rev-parse --short HEAD 2>/dev/null || echo unknown; }
  SKILL_BEFORE="$(REV)"
  SKILL_AFTER="$SKILL_BEFORE"
  SKILL_BRANCH="$(git -C "$SKILL_ROOT_LOCAL" branch --show-current 2>/dev/null || true)"
  if [[ -z "$SKILL_BRANCH" ]]; then
    echo "skill checkout at $SKILL_BEFORE is detached or not a git repo; not refreshing"
    return 0
  fi
  if ! git -C "$SKILL_ROOT_LOCAL" fetch -q origin "$SKILL_BRANCH" 2>/dev/null; then
    echo "warning: could not fetch skill origin; staying at $SKILL_BEFORE" >&2
    return 0
  fi
  if git -C "$SKILL_ROOT_LOCAL" merge --ff-only -q FETCH_HEAD >/dev/null 2>&1; then
    SKILL_AFTER="$(REV)"
    if [[ "$SKILL_BEFORE" == "$SKILL_AFTER" ]]; then
      echo "skill already current at $SKILL_AFTER ($SKILL_BRANCH)"
    else
      echo "skill refreshed: $SKILL_BEFORE -> $SKILL_AFTER ($SKILL_BRANCH)"
    fi
  else
    echo "warning: skill checkout at $SKILL_BEFORE cannot fast-forward (dirty or diverged); staying put" >&2
  fi
  return 0
}

if [[ "$CMD" == "refresh-skill" ]]; then
  refresh_skill_checkout
  exit 0
fi

[[ -n "$REPO" ]] || { usage >&2; echo "error: --repo is required" >&2; exit 2; }
[[ -d "$REPO/.git" ]] || die "not a git repository: $REPO"
REPO="$(cd "$REPO" && pwd)"

STAMP() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "- \`$(STAMP)\` $*" >> "$REPO/log.md"; }
HOLDER="${ZETTEL_RUN_HOLDER:-remote-session}"
SESSION="${CLAUDE_SESSION_ID:-${ZETTEL_SESSION_ID:-unknown}}"

SKILL_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# Every cycle records which skill revision produced it (issue #7): a stale
# cached install is otherwise invisible, and a bug report from a run cannot
# be attributed to a revision.
skill_rev() { git -C "$SKILL_ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown; }

# Resolve the content repo's default branch WITHOUT assuming the local clone
# has refs/remotes/origin/HEAD -- a Claude Code remote-session clone does not,
# and under `set -euo pipefail` a bare `git symbolic-ref` there exits 128 and
# killed every scheduled run before any fallback could apply (issue #7, P0).
# Ask the remote first, so a repo whose default branch is not `main` resolves
# correctly too; the `|| true` inside each substitution is what keeps a miss
# non-fatal.
default_branch() {
  local db
  db="$(git -C "$REPO" ls-remote --symref origin HEAD 2>/dev/null \
    | awk '/^ref:/ {sub("refs/heads/","",$2); print $2; exit}' || true)"
  [[ -n "$db" ]] || db="$(git -C "$REPO" symbolic-ref --short \
    refs/remotes/origin/HEAD 2>/dev/null | sed 's|origin/||' || true)"
  echo "${db:-main}"
}

# Release the distributed lock, recording WHY on the lock branch. The reason
# is the one artifact that distinguishes a failed start from a healthy no-op
# cycle from outside the session (issue #7 comment): the lock branch is
# pushed either way, log.md only when a cycle has work.
release_lock() {
  PYTHONPATH="$SCRIPT_DIR" "$PYBIN" -c '
import sys
sys.path.insert(0, "'"$SCRIPT_DIR"'")
from pathlib import Path
from zettel_lib import gitlock
gitlock.release(Path(sys.argv[1]), reason=sys.argv[2])
' "$REPO" "${1:-}"
}

lockpy() { PYTHONPATH="$SCRIPT_DIR" "$PYBIN" -c "$1" "$REPO" "${@:2}"; }

case "$CMD" in
  status)
    lockpy '
import sys
sys.path.insert(0, "'"$SCRIPT_DIR"'")
from pathlib import Path
from zettel_lib import gitlock
info = gitlock.read(Path(sys.argv[1]))
print(f"lock: {info.holder} (session {info.session}, {info.age_hours():.2f}h old)" if info else "lock: free")
'
    echo "branch: $(git -C "$REPO" branch --show-current)"
    ;;

  start)
    # Freshness must not depend on the prompt asking for it: a Routine stores
    # its prompt at creation time, so prompt-template fixes never reach
    # existing Routines -- the sandbox repo's PR #6 ran a months-newer prompt's
    # cycle on a stale cached install for exactly this reason and silently
    # regenerated the manifest without its inquiries block. If the refresh
    # moved HEAD, re-exec the refreshed file: the exec is a process boundary,
    # so bash never keeps reading a script that changed under it, and the env
    # guard makes a second refresh (and thus a loop) impossible. Messages go
    # to stderr because callers read the run branch from start's stdout.
    if [[ -z "${ZETTEL_SKILL_REFRESHED:-}" ]]; then
      refresh_skill_checkout >&2
      if [[ "$SKILL_BEFORE" != "$SKILL_AFTER" ]]; then
        ZETTEL_SKILL_REFRESHED=1 exec "$SCRIPT_DIR/remote_cycle.sh" start \
          --repo "$REPO" --ttl "$TTL"
      fi
    fi

    # AC-2 on this path too: a content repo missing an FR-2 key used to fail
    # only on a laptop, because only maintenance_run.sh validated. Checked
    # before any lock work so a bad config never needs a release.
    PYTHONPATH="$SCRIPT_DIR" "$PYBIN" -m zettel_lib.repo --repo "$REPO" --check-config >/dev/null \
      || die "config.yml validation failed (see error above); fix config.yml and re-run"

    # Break a provably stale lock, then claim. A LIVE lock is never stolen:
    # two sessions researching the same inquiry pay for it twice.
    lockpy '
import sys
sys.path.insert(0, "'"$SCRIPT_DIR"'")
from pathlib import Path
from zettel_lib import gitlock
repo, ttl = Path(sys.argv[1]), float(sys.argv[2])
broken = gitlock.break_stale(repo, ttl)
if broken:
    print(f"warning: broke stale lock from {broken.holder} "
          f"({broken.age_hours():.1f}h old)", file=sys.stderr)
' "$TTL"

    # claim() raises on a push-access failure (as opposed to contention), so a
    # non-zero exit here means "cannot push locks at all" -- die with the real
    # error rather than pretending another run holds the lock.
    set +e
    ACQUIRED="$(lockpy '
import sys
sys.path.insert(0, "'"$SCRIPT_DIR"'")
from pathlib import Path
from zettel_lib import gitlock
try:
    ok, holder = gitlock.claim(Path(sys.argv[1]), sys.argv[2], sys.argv[3])
except gitlock.GitLockError as exc:
    print(f"error: {exc}", file=sys.stderr)
    raise SystemExit(1)
print("yes" if ok else f"no\t{holder.holder}\t{holder.session}\t{holder.age_hours():.2f}")
' "$HOLDER" "$SESSION")"
    CLAIM_RC=$?
    set -e
    [[ $CLAIM_RC -eq 0 ]] || die "could not claim the run lock -- no push access to origin? (see error above)"

    if [[ "$ACQUIRED" != "yes" ]]; then
      IFS=$'\t' read -r _ h s age <<< "$ACQUIRED"
      echo "lock held by ${h} (session ${s}, ${age}h old); standing down without work"
      exit 3
    fi
    trap 'echo "start failed; releasing lock" >&2; release_lock "start-failed"' ERR

    git -C "$REPO" fetch -q origin
    DEFAULT_BRANCH="$(default_branch)"
    git -C "$REPO" checkout -q "$DEFAULT_BRANCH"
    git -C "$REPO" pull -q --ff-only origin "$DEFAULT_BRANCH"

    # Second-resolution names collide when a run restarts within a second of
    # the last (surfaced by the reasons test): uniquify rather than fail.
    BRANCH="zettel/run-$(date -u +%Y%m%d%H%M%S)"
    while git -C "$REPO" show-ref --verify --quiet "refs/heads/$BRANCH"; do
      BRANCH="zettel/run-$(date -u +%Y%m%d%H%M%S)-$RANDOM"
    done
    git -C "$REPO" checkout -q -b "$BRANCH"
    trap - ERR

    # Make config.yml's model tiers authoritative for THIS session's subagents.
    # The registry ci/setup-environment.sh builds holds the checked-in aliases,
    # so without this the remote path ran cheap-tier agents on Haiku whatever
    # config.yml said -- config only ever reached the laptop path's --agents
    # JSON. Claude Code watches the agents directory, so a rewrite now reaches
    # the delegations that follow. Advisory like the skill refresh above: a
    # cycle on alias-resolved models beats no cycle, and start's stdout must
    # stay branch-only, so this reports to stderr.
    AGENTS_DIR="${ZETTEL_AGENTS_DIR:-$HOME/.claude/agents}"
    if MATERIALIZED="$(PYTHONPATH="$SCRIPT_DIR" "$PYBIN" -m zettel_lib.agents \
         --repo "$REPO" --materialize "$AGENTS_DIR" 2>&1)"; then
      echo "$MATERIALIZED" >&2
      log "remote_cycle: $MATERIALIZED"
    else
      echo "warning: could not resolve agent models from config.yml; " \
           "subagents run their checked-in tier aliases ($MATERIALIZED)" >&2
    fi

    log "remote_cycle: start (mode=B holder=$HOLDER session=$SESSION branch=$BRANCH skill-rev=$(skill_rev))"
    echo "$BRANCH"
    ;;

  finish)
    BRANCH="$(git -C "$REPO" branch --show-current)"
    [[ "$BRANCH" == zettel/run-* ]] || die "not on a run branch (on '$BRANCH'); run 'start' first"

    git -C "$REPO" fetch -q origin
    DEFAULT_BRANCH="$(default_branch)"

    # Bookkeeping-only paths: a cycle that touched nothing else did no work.
    # Pushing it would open a PR every quiet week and drown the real ones.
    CHANGED="$(git -C "$REPO" status --porcelain --untracked-files=all \
      | awk '{print $NF}' | sort -u)"
    SUBSTANTIVE="$(printf '%s\n' "$CHANGED" | grep -v '^log\.md$' | grep -v '^$' || true)"
    AHEAD="$(git -C "$REPO" log "origin/${DEFAULT_BRANCH}..HEAD" --oneline 2>/dev/null || true)"

    if [[ -z "$SUBSTANTIVE" && -z "$AHEAD" ]]; then
      # Discard the start/finish log lines too: an empty cycle leaves no trace
      # in the knowledge base -- the stand-down reason goes on the lock branch.
      release_lock "empty-cycle"
      git -C "$REPO" checkout -q -- log.md 2>/dev/null || true
      echo "no changes this cycle; nothing pushed"
      exit 0
    fi

    # A run branch whose work already merged (auto-merge squashes, so compare
    # TREES, not ancestry alone) must not open an empty duplicate PR. This
    # catches the common case -- re-finishing an old branch with no new work;
    # a stale branch whose base has since moved still needs a human eye.
    if [[ -z "$SUBSTANTIVE" ]] && { \
         git -C "$REPO" merge-base --is-ancestor HEAD "origin/$DEFAULT_BRANCH" 2>/dev/null \
         || [[ "$(git -C "$REPO" rev-parse "HEAD^{tree}")" == \
               "$(git -C "$REPO" rev-parse "origin/$DEFAULT_BRANCH^{tree}")" ]]; }; then
      release_lock "already-merged $BRANCH"
      git -C "$REPO" checkout -q -- log.md 2>/dev/null || true
      echo "this branch's work is already merged into $DEFAULT_BRANCH; nothing to push"
      exit 0
    fi

    # The completion line is logged BEFORE the commit so it actually lands on
    # the pushed branch; everything after the commit reports to stdout only
    # (a post-commit log line can never reach the branch it describes).
    log "remote_cycle: finish $BRANCH (skill-rev=$(skill_rev); lock released after push)"

    # When the PR handoff falls to the session, the script writes the record
    # itself: agents paraphrasing it produced "(gh unavailable)", which a
    # reviewer read as GitHub being down rather than the CLI being absent.
    if ! command -v gh >/dev/null 2>&1; then
      log "remote_cycle: PR for $BRANCH must be opened by the session (GitHub CLI not installed in this container)"
    fi

    git -C "$REPO" add -A
    if ! git -C "$REPO" diff --cached --quiet; then
      git -C "$REPO" -c user.name="zettel-bootstrap" \
        -c user.email="noreply@users.noreply.github.com" \
        commit -q -m "${TITLE:-Maintenance cycle $(date -u +%Y-%m-%d)}"
    fi

    git -C "$REPO" push -q -u origin "$BRANCH" || die "could not push $BRANCH"
    echo "pushed $BRANCH ($(git -C "$REPO" rev-parse --short HEAD))"

    # The PR is the handoff to CI. Auto-merge means the session does not wait:
    # GitHub merges when the required gate check goes green, and never if it
    # does not. Without gh this is NOT a dead end -- a remote session usually
    # has the GitHub MCP tools and should open the PR itself.
    if command -v gh >/dev/null 2>&1; then
      gh pr create --fill --title "${TITLE:-Maintenance cycle $(date -u +%Y-%m-%d)}" \
        >/dev/null 2>&1 && gh pr merge --auto --squash >/dev/null 2>&1 \
        && echo "PR opened with auto-merge enabled" \
        || echo "branch pushed; PR creation via gh failed (open it manually)"
    else
      ORIGIN_URL="$(git -C "$REPO" remote get-url origin 2>/dev/null || true)"
      SLUG="$(printf '%s' "$ORIGIN_URL" \
        | sed -E 's#^(git@github\.com:|https://github\.com/)##; s#\.git$##')"
      echo "PUSHED_BRANCH=$BRANCH"
      if [[ "$ORIGIN_URL" == *github.com* && "$SLUG" == */* ]]; then
        echo "open a PR for $BRANCH so the gates can run -- use whatever GitHub tooling this session has (the GitHub MCP tools in remote sessions): https://github.com/$SLUG/compare/$DEFAULT_BRANCH...$BRANCH"
      else
        echo "open a PR for $BRANCH so the gates can run -- use whatever GitHub tooling this session has (the GitHub MCP tools in remote sessions)"
      fi
      echo "then enable auto-merge on it (squash) so it lands exactly when the required gates check passes; never merge it yourself"
    fi

    # A proposal advances only when a human promotes or rejects it, and nothing
    # else in the pipeline says one is waiting: the smith records it, the trial
    # scores it, and then it can sit unread in a merged PR forever. Say so here,
    # where the session is composing its PR body and report.
    PROPOSED_SKILLS=""
    for PURPOSE_FILE in "$REPO"/skills/*/PURPOSE.md; do
      [[ -f "$PURPOSE_FILE" ]] || continue
      if grep -q '^status: proposed$' "$PURPOSE_FILE"; then
        PROPOSED_SKILLS="${PROPOSED_SKILLS:+$PROPOSED_SKILLS, }$(basename "$(dirname "$PURPOSE_FILE")")"
      fi
    done
    if [[ -n "$PROPOSED_SKILLS" ]]; then
      echo "child-skill proposals awaiting a human decision: $PROPOSED_SKILLS -- name them and their trial scores in the PR body and your report (skill_review.py promote|reject decides)"
    fi

    release_lock "finished $BRANCH"
    echo "cycle finished on $BRANCH"
    ;;

  abort)
    release_lock "abort"
    log "remote_cycle: lock released"
    echo "lock released"
    ;;

  *) usage >&2; echo "error: unknown subcommand: $CMD" >&2; exit 2 ;;
esac
