#!/usr/bin/env bash
# Open a session-driven cycle: answer a question, ingest a source, or close the
# gaps a query found.
#
# All three are the same shape -- claim the lock, branch, do the bookkeeping the
# work needs, then hand the session a checklist naming the exact commands. Only
# `ask` existed before (as adhoc_research.sh), so ingesting a source a session
# was handed and working a query's gaps were prose in SKILL.md: the session had
# to sequence lock, branch, generators, gates and PR from memory, every time.
#
# What must NOT differ between them is how the work lands. Each claims the same
# lock as a scheduled cycle, works on the same kind of run branch, and hands off
# through the same PR + required-check gate. There is no fast path to main,
# because a fast path to main is a path around the citation gates.
#
#   session_cycle.sh ask    --repo <path> --question "..." [--priority high] [--body -]
#   session_cycle.sh ingest --repo <path> --source <file> [--title ...] [--author ...]
#   session_cycle.sh query  --repo <path> --from-query "..." [--top N]
#
# Exit codes: 0 ok; 3 a live run holds the lock (stand down, do not force);
#             1 failure; 2 usage.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYBIN="${PYTHON:-python3}"
command -v "$PYBIN" >/dev/null 2>&1 || { echo "error: python not found: $PYBIN" >&2; exit 1; }
PYBIN="$(command -v "$PYBIN")"

case "${1:-}" in
  -h|--help|"") MODE="help" ;;
  *) MODE="$1" ;;
esac
shift || true

REPO=""; QUESTION=""; PRIORITY="normal"; BODY=""; HAVE_BODY=0
SOURCE=""; TOP=""; QUERY=""
declare -a SIDECAR=()

usage() {
  cat <<'USAGE'
Usage: session_cycle.sh <ask|ingest|query> --repo <content-repo> [options]

  ask    --question "<text>" [--priority low|normal|high] [--body TEXT|-]
         File the question as an inquiry and research it now.

  ingest --source <file> [--title ...] [--author ...] [--year ...] [--doi ...]
         [--isbn ...] [--arxiv ...] [--pmid ...] [--url ...] [--source-tier ...]
         [--priority ...] [--notes ...] [--tags a,b]
         Ingest a source this session was handed, then write its notes.

  query  --from-query "<text>" [--top N]
         File the gaps a query finds, on the run branch, and work them.

Each claims the run lock, opens a run branch, and prints a checklist. Hand off
with: remote_cycle.sh finish --repo <path>

Exit codes: 0 ok; 3 lock held by a live run (stand down); 1 failure; 2 usage.
USAGE
}

die() { echo "error: $*" >&2; exit 1; }
usage_error() { usage >&2; echo "error: $*" >&2; exit 2; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --question) QUESTION="${2:-}"; shift 2 ;;
    --priority) PRIORITY="${2:-}"; SIDECAR+=(--priority "${2:-}"); shift 2 ;;
    --body) BODY="${2:-}"; HAVE_BODY=1; shift 2 ;;
    --source) SOURCE="${2:-}"; shift 2 ;;
    --from-query) QUERY="${2:-}"; shift 2 ;;
    --top) TOP="${2:-}"; shift 2 ;;
    # Sidecar fields are passed through to ingest_drops verbatim, so the two
    # tools cannot describe a source differently.
    --title|--author|--year|--doi|--isbn|--arxiv|--pmid|--url|--source-tier|--notes|--tags)
      SIDECAR+=("$1" "${2:-}"); shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage_error "unknown argument: $1" ;;
  esac
done

if [[ "$MODE" == "help" ]]; then usage; exit 0; fi
case "$MODE" in ask|ingest|query) ;; *) usage_error "unknown mode: $MODE" ;; esac

# Every usage error is settled BEFORE any environment check, and both before
# the lock. The order matters twice: a run that claims the lock and then dies on
# a typo strands the repo for the stale-lock TTL, and a missing flag must report
# as a usage error (exit 2) rather than as whatever the environment complains
# about first -- a caller that passed no --question should be told that, not
# that some directory is not a git repository.
[[ -n "$REPO" ]] || usage_error "--repo is required"
case "$MODE" in
  ask)    [[ -n "${QUESTION// }" ]] || usage_error "--question is required for ask" ;;
  ingest) [[ -n "$SOURCE" ]] || usage_error "--source is required for ingest" ;;
  query)  [[ -n "${QUERY// }" ]] || usage_error "--from-query is required for query" ;;
esac

[[ -d "$REPO/.git" ]] || die "not a git repository: $REPO"
REPO="$(cd "$REPO" && pwd)"
if [[ "$MODE" == "ingest" ]]; then
  [[ -f "$SOURCE" ]] || die "not a file: $SOURCE"
  SOURCE="$(cd "$(dirname "$SOURCE")" && pwd)/$(basename "$SOURCE")"
fi

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

# Render a checklist template with the concrete paths this cycle will use. The
# same substitution the maintenance prompts use, for the same reason: a
# checklist naming real commands is followed; one naming placeholders is
# improvised around.
render() {
  local template="$SCRIPT_DIR/$1"; shift
  local text; text="$(cat "$template")"
  while [[ $# -gt 1 ]]; do
    text="${text//"$1"/$2}"
    shift 2
  done
  printf '%s\n' "$text"
}

# Shell-quote a value for a checklist that will be pasted into a terminal.
shquote() { "$PYBIN" -c 'import shlex,sys; print(shlex.quote(sys.argv[1]))' "$1"; }

case "$MODE" in
  ask)
    CAPTURE_ARGS=(--repo "$REPO" --json inquiry "$QUESTION" --priority "$PRIORITY")
    if [[ $HAVE_BODY -eq 1 ]]; then CAPTURE_ARGS+=(--body "$BODY"); fi
    INQUIRY="$("$PYBIN" "$SCRIPT_DIR/capture.py" "${CAPTURE_ARGS[@]}")"
    trap - ERR
    INQUIRY_PATH="$("$PYBIN" -c 'import json,sys; print(json.loads(sys.argv[1])["path"])' "$INQUIRY")"
    INQUIRY_KEY="$(basename "$INQUIRY_PATH" .md)"

    # These two lines are the ad-hoc contract, unchanged since adhoc_research.sh:
    # callers parse them.
    echo "branch: $BRANCH"
    echo "inquiry: $INQUIRY_PATH"
    echo
    render session_ask_prompt.md \
      "{{REPO}}" "$REPO" "{{SCRIPTS}}" "$SCRIPT_DIR" "{{PYTHON}}" "$PYBIN" \
      "{{BRANCH}}" "$BRANCH" "{{INQUIRY}}" "$INQUIRY_PATH" \
      "{{INQUIRY_KEY}}" "$INQUIRY_KEY" "{{QUESTION}}" "$QUESTION" \
      "{{QUESTION_Q}}" "$(shquote "$QUESTION")"
    ;;

  ingest)
    # --file copies the source in and ingests only it, so a drop someone
    # committed for the next scheduled cycle is not swept into this PR.
    # stdout and stderr are kept apart: stdout is the JSON this script parses,
    # and merging the tool's diagnostics into it would make every failure
    # unparseable -- exactly when the caller most needs the reason.
    INGEST_ERR="$(mktemp)"
    set +e
    INGESTED="$("$PYBIN" "$SCRIPT_DIR/ingest_drops.py" --repo "$REPO" --file "$SOURCE" \
      --json "${SIDECAR[@]}" 2>"$INGEST_ERR")"
    IRC=$?
    set -e
    if [[ $IRC -ne 0 ]]; then
      # A source already on file is not a failure of this session -- it is an
      # answer. Release the lock rather than holding it while the user decides.
      "$SCRIPT_DIR/remote_cycle.sh" abort --repo "$REPO" >/dev/null 2>&1 || true
      trap - ERR
      cat "$INGEST_ERR" >&2
      DUP="$("$PYBIN" -c '
import json, sys
try:
    rows = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(0)
for r in rows if isinstance(rows, list) else []:
    if r.get("duplicate_of"):
        print(r["duplicate_of"])
' "$INGESTED" 2>/dev/null || true)"
      rm -f "$INGEST_ERR"
      if [[ -n "$DUP" ]]; then
        echo "duplicate_of: $DUP"
        echo "this source is already on file; read it with query.py, or ask a question about it" >&2
      fi
      exit 1
    fi
    rm -f "$INGEST_ERR"
    trap - ERR

    read -r REF_KEY CAPTURE_PATH TITLE <<<"$("$PYBIN" -c '
import json, sys
rows = json.loads(sys.argv[1])
row = rows[0]
print(row["key"], row["capture"], row["key"].rsplit("--", 1)[0].replace("-", " "))
' "$INGESTED")"
    TEXT_PATH="${CAPTURE_PATH%.*}.txt"
    [[ -f "$REPO/$TEXT_PATH" ]] || TEXT_PATH="$CAPTURE_PATH"

    echo "branch: $BRANCH"
    echo "reference: $REF_KEY"
    echo "capture: $CAPTURE_PATH"
    echo "text: $TEXT_PATH"
    echo
    render session_ingest_prompt.md \
      "{{REPO}}" "$REPO" "{{SCRIPTS}}" "$SCRIPT_DIR" "{{PYTHON}}" "$PYBIN" \
      "{{BRANCH}}" "$BRANCH" "{{REFERENCE}}" "$REF_KEY" \
      "{{CAPTURE}}" "$CAPTURE_PATH" "{{TEXT}}" "$TEXT_PATH" "{{TITLE}}" "$TITLE"
    ;;

  query)
    # The order here is the whole point of routing a query through a cycle:
    # `start` first, THEN file. Filing before the branch existed would put the
    # captures on whatever branch was checked out, and `start`'s own checkout
    # would strand them.
    QUERY_ARGS=(--repo "$REPO" "$QUERY" --json --file-gaps)
    [[ -n "$TOP" ]] && QUERY_ARGS+=(--top "$TOP")
    REPORT="$("$PYBIN" "$SCRIPT_DIR/query.py" "${QUERY_ARGS[@]}")"
    trap - ERR

    FILED="$("$PYBIN" -c '
import json, sys
report = json.loads(sys.argv[1])
for f in report.get("filed", []):
    print("- {}: {}".format(f["kind"], f["path"]))
' "$REPORT")"

    if [[ -z "$FILED" ]]; then
      # Nothing to file means nothing to work. Hand the lock back rather than
      # opening an empty cycle; the query already answered the user in chat.
      "$SCRIPT_DIR/remote_cycle.sh" abort --repo "$REPO" >/dev/null 2>&1 || true
      echo "branch: $BRANCH"
      echo "filed: nothing -- the query found no gap worth a cycle"
      echo "the base already covers this; answer from query.py's report and stop" >&2
      exit 0
    fi

    echo "branch: $BRANCH"
    echo "filed:"
    printf '%s\n' "$FILED"
    echo
    render session_query_prompt.md \
      "{{REPO}}" "$REPO" "{{SCRIPTS}}" "$SCRIPT_DIR" "{{PYTHON}}" "$PYBIN" \
      "{{BRANCH}}" "$BRANCH" "{{FILED}}" "$FILED" "{{QUERY}}" "$QUERY"
    ;;
esac
