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
#   start   claim the distributed lock, pull, create the run branch
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
Usage: remote_cycle.sh <start|finish|abort|status> --repo <content-repo> [options]

  start   --repo <path> [--ttl <hours>]   claim lock, pull, create run branch
  finish  --repo <path> [--title <text>]  commit, push branch, open PR, auto-merge
  abort   --repo <path>                   release the lock, keep the branch
  status  --repo <path>                   report lock holder and branch

Exit codes: 0 ok; 3 lock held by a live run (not an error -- stand down); 1 failure.
USAGE
}

die() { echo "error: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --ttl) TTL="${2:-}"; shift 2 ;;
    --title) TITLE="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
done

if [[ "$CMD" == "help" ]]; then usage; exit 0; fi
[[ -n "$REPO" ]] || { usage >&2; die "--repo is required"; }
[[ -d "$REPO/.git" ]] || die "not a git repository: $REPO"
REPO="$(cd "$REPO" && pwd)"

STAMP() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "- \`$(STAMP)\` $*" >> "$REPO/log.md"; }
HOLDER="${ZETTEL_RUN_HOLDER:-remote-session}"
SESSION="${CLAUDE_SESSION_ID:-${ZETTEL_SESSION_ID:-unknown}}"

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
    trap 'echo "start failed; releasing lock" >&2; PYTHONPATH="$SCRIPT_DIR" "$PYBIN" -c "
import sys; sys.path.insert(0, \"$SCRIPT_DIR\")
from pathlib import Path
from zettel_lib import gitlock; gitlock.release(Path(\"$REPO\"))"' ERR

    git -C "$REPO" fetch -q origin
    DEFAULT_BRANCH="$(git -C "$REPO" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's|origin/||')"
    DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
    git -C "$REPO" checkout -q "$DEFAULT_BRANCH"
    git -C "$REPO" pull -q --ff-only origin "$DEFAULT_BRANCH"

    BRANCH="zettel/run-$(date -u +%Y%m%d%H%M%S)"
    git -C "$REPO" checkout -q -b "$BRANCH"
    trap - ERR

    log "remote_cycle: start (holder=$HOLDER session=$SESSION branch=$BRANCH)"
    echo "$BRANCH"
    ;;

  finish)
    BRANCH="$(git -C "$REPO" branch --show-current)"
    [[ "$BRANCH" == zettel/run-* ]] || die "not on a run branch (on '$BRANCH'); run 'start' first"

    # Bookkeeping-only paths: a cycle that touched nothing else did no work.
    # Pushing it would open a PR every quiet week and drown the real ones.
    CHANGED="$(git -C "$REPO" status --porcelain --untracked-files=all \
      | awk '{print $NF}' | sort -u)"
    SUBSTANTIVE="$(printf '%s\n' "$CHANGED" | grep -v '^log\.md$' | grep -v '^$' || true)"
    AHEAD="$(git -C "$REPO" log "origin/${DEFAULT_BRANCH:-main}..HEAD" --oneline 2>/dev/null || true)"

    if [[ -z "$SUBSTANTIVE" && -z "$AHEAD" ]]; then
      # Discard the start/finish log lines too: an empty cycle leaves no trace
      # in the knowledge base, only in the session transcript.
      git -C "$REPO" checkout -q -- log.md 2>/dev/null || true
      "$0" abort --repo "$REPO" >/dev/null
      echo "no changes this cycle; nothing pushed"
      exit 0
    fi

    git -C "$REPO" add -A
    if ! git -C "$REPO" diff --cached --quiet; then
      git -C "$REPO" -c user.name="zettel-bootstrap" \
        -c user.email="noreply@users.noreply.github.com" \
        commit -q -m "${TITLE:-Maintenance cycle $(date -u +%Y-%m-%d)}"
    fi

    git -C "$REPO" push -q -u origin "$BRANCH" || die "could not push $BRANCH"
    log "remote_cycle: pushed $BRANCH ($(git -C "$REPO" rev-parse --short HEAD))"

    # The PR is the handoff to CI. Auto-merge means the session does not wait:
    # GitHub merges when the required gate check goes green, and never if it
    # does not. gh is absent in remote containers, so this is best-effort and
    # the branch + PR remain for a human or the GitHub MCP tools either way.
    if command -v gh >/dev/null 2>&1; then
      gh pr create --fill --title "${TITLE:-Maintenance cycle $(date -u +%Y-%m-%d)}" \
        >/dev/null 2>&1 && gh pr merge --auto --squash >/dev/null 2>&1 \
        && log "remote_cycle: PR opened with auto-merge enabled" \
        || log "remote_cycle: branch pushed; PR creation via gh failed (open it manually)"
    else
      log "remote_cycle: branch pushed; open a PR for $BRANCH (gh unavailable)"
      echo "PUSHED_BRANCH=$BRANCH"
      echo "note: gh not available - open a PR for $BRANCH so the gates can run"
    fi

    "$0" abort --repo "$REPO" >/dev/null
    echo "cycle finished on $BRANCH"
    ;;

  abort)
    PYTHONPATH="$SCRIPT_DIR" "$PYBIN" -c '
import sys
sys.path.insert(0, "'"$SCRIPT_DIR"'")
from pathlib import Path
from zettel_lib import gitlock
gitlock.release(Path(sys.argv[1]))
' "$REPO"
    log "remote_cycle: lock released"
    echo "lock released"
    ;;

  *) usage >&2; die "unknown subcommand: $CMD" ;;
esac
