#!/usr/bin/env bash
# Open an ad-hoc research cycle for one question.
#
# This is now `session_cycle.sh ask`, kept as its own entry point because the
# name is what SKILL.md, the docs, and two live cycles reach for, and because
# its output contract (a `branch:` line, an `inquiry:` line, exit 3 on a live
# lock) is parsed by callers. The three session modes -- answer a question,
# ingest a source, close a query's gaps -- all claim the same lock and hand off
# the same way, so the lock/branch/abort logic lives in one script rather than
# being copied per mode.
#
#   adhoc_research.sh --repo <path> --question "..." [--priority high] [--body -]
#
# Exit codes: 0 ok; 3 a live run holds the lock (stand down, do not force);
#             1 failure; 2 usage.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: adhoc_research.sh --repo <content-repo> --question "<text>" [options]

  --repo      path to the content repository (required)
  --question  the question to research (required)
  --priority  low | normal | high                        [default: normal]
  --body      extra context, or '-' to read stdin

Claims the run lock, records the question as an inquiry, and creates the run
branch. Research, then hand off with: remote_cycle.sh finish --repo <path>

The same cycle is available as `session_cycle.sh ask`, alongside `ingest`
(a source this session was handed) and `query` (close the gaps a query found).

Exit codes: 0 ok; 3 lock held by a live run (stand down); 1 failure; 2 usage.
USAGE
  exit 0
fi

exec "$SCRIPT_DIR/session_cycle.sh" ask "$@"
