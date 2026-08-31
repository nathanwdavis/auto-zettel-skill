#!/usr/bin/env bash
# Open an ad-hoc research cycle for one question.
#
# Scheduled runs are not the only way knowledge should enter the base: sometimes
# you want an answer now. What must NOT change is how the answer lands. This
# claims the same lock, opens the same kind of run branch, and hands off through
# the same PR + required-check gate as a scheduled cycle. There is no fast path
# to main, because a fast path to main is a path around the citation gates.
#
# It does the bookkeeping only. The research itself is the session's work,
# following the SKILL.md "Answering a question now" recipe; when done, hand off
# with `remote_cycle.sh finish`.
#
#   adhoc_research.sh --repo <path> --question "..." [--priority high] [--body -]
#
# Exit codes: 0 ok; 3 a live run holds the lock (stand down, do not force);
#             1 failure; 2 usage.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYBIN="${PYTHON:-python3}"
command -v "$PYBIN" >/dev/null 2>&1 || { echo "error: python not found: $PYBIN" >&2; exit 1; }
PYBIN="$(command -v "$PYBIN")"

REPO=""; QUESTION=""; PRIORITY="normal"; BODY=""; HAVE_BODY=0

usage() {
  cat <<'USAGE'
Usage: adhoc_research.sh --repo <content-repo> --question "<text>" [options]

  --repo      path to the content repository (required)
  --question  the question to research (required)
  --priority  low | normal | high                        [default: normal]
  --body      extra context, or '-' to read stdin

Claims the run lock, records the question as an inquiry, and creates the run
branch. Research, then hand off with: remote_cycle.sh finish --repo <path>

Exit codes: 0 ok; 3 lock held by a live run (stand down); 1 failure; 2 usage.
USAGE
}

die() { echo "error: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --question) QUESTION="${2:-}"; shift 2 ;;
    --priority) PRIORITY="${2:-}"; shift 2 ;;
    --body) BODY="${2:-}"; HAVE_BODY=1; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$REPO" ]] || { usage >&2; echo "error: --repo is required" >&2; exit 2; }
[[ -n "${QUESTION// }" ]] || { usage >&2; echo "error: --question is required" >&2; exit 2; }
[[ -d "$REPO/.git" ]] || die "not a git repository: $REPO"
REPO="$(cd "$REPO" && pwd)"

# Read stdin before claiming: a lock held while blocked on a pipe is a lock
# nobody can break for six hours.
if [[ "$BODY" == "-" ]]; then BODY="$(cat)"; fi

# Exit 3 means a scheduled run is already working. Propagate it unchanged --
# waiting is the correct behaviour, and remote_cycle.sh never steals a live lock.
set +e
BRANCH="$("$SCRIPT_DIR/remote_cycle.sh" start --repo "$REPO")"
RC=$?
set -e
if [[ $RC -eq 3 ]]; then
  echo "$BRANCH"
  echo "a scheduled run holds the lock; try again when it finishes" >&2
  exit 3
fi
[[ $RC -eq 0 ]] || die "could not start a run cycle"

# From here the lock is ours, so any failure must release it rather than
# stranding the repo for the stale-lock TTL.
trap '"$SCRIPT_DIR/remote_cycle.sh" abort --repo "$REPO" >/dev/null 2>&1 || true' ERR

CAPTURE_ARGS=(--repo "$REPO" --json inquiry "$QUESTION" --priority "$PRIORITY")
if [[ $HAVE_BODY -eq 1 ]]; then CAPTURE_ARGS+=(--body "$BODY"); fi
INQUIRY="$("$PYBIN" "$SCRIPT_DIR/capture.py" "${CAPTURE_ARGS[@]}")"
trap - ERR

INQUIRY_PATH="$("$PYBIN" -c 'import json,sys; print(json.loads(sys.argv[1])["path"])' "$INQUIRY")"

echo "branch: $BRANCH"
echo "inquiry: $INQUIRY_PATH"
cat <<NEXT

Research the question, then file what is worth keeping (reference -> literature
-> permanent -> MOC), set the inquiry's status and result_notes, run the gates,
and hand off:

  $SCRIPT_DIR/remote_cycle.sh finish --repo $REPO --title "Research: $QUESTION"

Never push to main and never merge: the required check decides.
NEXT
