#!/usr/bin/env bash
# Scaffold and publish a zettelkasten content repository (FR-18).
#
# Creates the FR-1 substrate (plus the CI gate workflow, amendment A9), writes
# config.yml from the bundled template, makes the initial commit, (unless
# --no-remote) creates the GitHub remote and pushes, then prints the
# scheduling next-steps (FR-27 step 5). Exits non-zero with an actionable message on any failure, and
# refuses to clobber an existing repository.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TEMPLATES="${PLUGIN_ROOT}/templates"

NAME=""; VISIBILITY=""; OWNER=""; TOPICS=""; CADENCE="weekly"
BUDGET_USD="5"; BUDGET_TURNS="40"; DIR=""; NO_REMOTE=0

usage() {
  cat <<'USAGE'
Usage: init_content_repo.sh --name <repo> --visibility <public|private> --owner <gh-owner>
                            --topics "<csv>" [--cadence <str>] [--budget <usd>]
                            [--max-turns <n>] [--dir <path>] [--no-remote]

  --name         content repository name (required)
  --visibility   public or private (required)
  --owner        GitHub user or org that will own the repo (required)
  --topics       comma-separated seed topics (required)
  --cadence      maintenance cadence, cron-like or human   [default: weekly]
  --budget       per-run USD cap                            [default: 5]
  --max-turns    per-run turn cap                           [default: 40]
  --dir          local path to scaffold into  [default: ./<name>]
  --no-remote    scaffold and commit locally; skip gh repo create and push
USAGE
}

die() { echo "error: $*" >&2; exit 1; }

# FR-27 step 5: how to keep the repo growing, printed once the scaffold is
# committed (and, on the gh path, published). The same content lives in
# references/scheduling.md and remote-execution.md; here so the person who
# just ran genesis does not have to go looking for it.
next_steps() {
  cat <<STEPS

Next steps -- scheduling maintenance (FR-27):

  1. One-time GitHub settings on ${OWNER}/${NAME} (Settings -> Rules / General):
       - make the "gates" status check REQUIRED on main
       - enable "Allow auto-merge" and "Automatically delete head branches"
     Without the required check a red PR still merges on a click.

  2. Pick a scheduler:
     - Laptop cron (runs while the machine is awake):
         0 6 * * 0  cd ${DIR} && ${SCRIPT_DIR}/maintenance_run.sh --repo ${DIR} --mailto you@example.org >> ${DIR}/../maintenance.log 2>&1
     - Claude Code Desktop / Cowork scheduled task: same command; runs only
       while the app is open (references/scheduling.md).
     - Fully remote, no laptop: a Routine that runs scripts/remote_cycle.sh in
       a cloud environment set up by ci/setup-environment.sh
       (references/remote-execution.md). This is the primary path.

  3. Do the first knowledge pass now: capture one source per topic into raw/,
     write its reference + literature notes, distil one permanent note, add a
     MOC and link it from INDEX.md, run the gates, commit (SKILL.md, "Genesis").
STEPS
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) NAME="${2:-}"; shift 2 ;;
    --visibility) VISIBILITY="${2:-}"; shift 2 ;;
    --owner) OWNER="${2:-}"; shift 2 ;;
    --topics) TOPICS="${2:-}"; shift 2 ;;
    --cadence) CADENCE="${2:-}"; shift 2 ;;
    --budget) BUDGET_USD="${2:-}"; shift 2 ;;
    --max-turns) BUDGET_TURNS="${2:-}"; shift 2 ;;
    --dir) DIR="${2:-}"; shift 2 ;;
    --no-remote) NO_REMOTE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; echo "error: unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ -n "$NAME" ]] || { usage >&2; echo "error: --name is required" >&2; exit 2; }
[[ -n "$OWNER" ]] || { usage >&2; echo "error: --owner is required" >&2; exit 2; }
[[ -n "$TOPICS" ]] || { usage >&2; echo "error: --topics is required" >&2; exit 2; }
case "$VISIBILITY" in
  public|private) ;;
  *) die "--visibility must be 'public' or 'private' (got '${VISIBILITY:-}')" ;;
esac

DIR="${DIR:-./$NAME}"

# --- preflight ---------------------------------------------------------------
command -v git >/dev/null 2>&1 || die "git is not installed"

if [[ "$NO_REMOTE" -eq 0 ]]; then
  command -v gh >/dev/null 2>&1 || \
    die "gh CLI not found. Install it (https://cli.github.com) and run 'gh auth login', or pass --no-remote."
  gh auth status >/dev/null 2>&1 || \
    die "gh is not authenticated. Run 'gh auth login' first, or pass --no-remote."
  if gh repo view "${OWNER}/${NAME}" >/dev/null 2>&1; then
    die "https://github.com/${OWNER}/${NAME} already exists. Choose another --name; refusing to clobber it."
  fi
fi

if [[ -e "$DIR" ]] && [[ -n "$(ls -A "$DIR" 2>/dev/null)" ]]; then
  die "$DIR already exists and is not empty; refusing to overwrite it."
fi

# --- scaffold (FR-1) ---------------------------------------------------------
mkdir -p "$DIR"
DIR="$(cd "$DIR" && pwd)"
cd "$DIR"

for d in fleeting literature permanent reference moc inquiries raw skills proposed-links .bib; do
  mkdir -p "$d"
  cat > "$d/.gitkeep" <<'KEEP'
KEEP
done

TODAY="$(date -u +%Y-%m-%d)"
STAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# config.yml from the bundled template
TOPICS_YAML="[]"
if [[ -n "$TOPICS" ]]; then
  TOPICS_YAML="[$(echo "$TOPICS" | sed 's/[[:space:]]*,[[:space:]]*/", "/g; s/^/"/; s/$/"/')]"
fi
sed -e "s|{{TOPICS}}|${TOPICS_YAML}|" \
    -e "s|{{CADENCE}}|${CADENCE}|" \
    -e "s|{{BUDGET_USD}}|${BUDGET_USD}|" \
    -e "s|{{BUDGET_TURNS}}|${BUDGET_TURNS}|" \
    -e "s|{{REPO_NAME}}|${NAME}|" \
    -e "s|{{REPO_OWNER}}|${OWNER}|" \
    -e "s|{{REPO_VISIBILITY}}|${VISIBILITY}|" \
    "${TEMPLATES}/config.yml" > config.yml

cat > INBOX.md <<INBOX
# Inbox

Questions, corrections, and instructions for the knowledge base. Every
maintenance run reads this file FIRST and prioritises entries marked \`new\`.
Human feedback here is authoritative and overrides automated decisions (QA-4).

Statuses: \`new\` -> \`in-progress\` -> \`answered\` -> \`archived\`.

---
INBOX

cat > INDEX.md <<'INDEX'
# Index

Root map of content, and the entry point for remote-walk (Mode B) reads.

This file links **only to MOCs**; MOCs link to notes (FR-4). `lint_links.py`
enforces that layering.

## Maps of Content
INDEX

cat > log.md <<LOG
# Operation log

Append-only. Each run stamps start/end, mode, agents dispatched, gate results,
and the resulting commit SHA (NFR-2).

- \`${STAMP}\` genesis: scaffolded substrate for topics [${TOPICS}]
LOG

cat > skill-impact.md <<'IMPACT'
# Skill impact tracker

Every child-skill proposal is recorded here with its metadata, target skill,
unified diff, A/B scores, and the Accepted/Rejected outcome with a reason
(FR-36). Rejected proposals stay listed so they are not re-proposed.

The knowledge layer is never rolled back, whatever a proposal's outcome (FR-33).

| date | proposal | target skill | outcome | reason |
|------|----------|--------------|---------|--------|
IMPACT

printf '[]\n' > .bib/refs.json

cat > .gitignore <<'IGNORE'
run.lock
.worktrees/
__pycache__/
*.py[cod]
.venv/
.pytest_cache/
.env
*.token
*.pem
.netrc
.DS_Store
IGNORE

# The merge gate (amendments A5, A9): a required status check on `gates` is
# what decides what reaches main from a remote session, and a copy that has
# to be made by hand went stale on the first live repo. Installed at genesis
# so a new content repo is gated from its first PR.
mkdir -p .github/workflows
cp "${PLUGIN_ROOT}/ci/content-repo-gates.yml" .github/workflows/gates.yml

cat > README.md <<README
# ${NAME}

A citation-grounded Zettelkasten, cultivated by the
[\`zettel-bootstrap\`](https://github.com/nathanwdavis/auto-zettel-skill) Claude Code skill.

**Topics:** ${TOPICS}

## Layout

| Path | Contents |
|------|----------|
| \`INBOX.md\` | Questions and corrections for the next run. Read first, every run. |
| \`INDEX.md\` | Root map of content; links only to MOCs. |
| \`manifest.json\` | Machine-readable note index. |
| \`config.yml\` | Topics, cadence, budget, model mix. |
| \`permanent/\` | Atomic ideas, one claim each. |
| \`literature/\` | Own-words summaries, one source each. |
| \`reference/\` | Bibliographic records, one per source. |
| \`moc/\` | Maps of content. |
| \`fleeting/\` | Short-lived captures, swept each cycle. |
| \`raw/\` | Verbatim source captures. Immutable. |
| \`inquiries/\` | Open questions and their answering notes. |
| \`proposed-links/\` | Connector queue awaiting review. |
| \`skills/\` | Self-authored child skills, pending human promotion. |
| \`.bib/refs.json\` | Aggregated CSL-JSON bibliography. |
| \`log.md\` | Append-only run log. |
| \`.github/workflows/gates.yml\` | The lint gates as a status check; make \`gates\` required on \`main\`. |

## Ground rules

Every claim traces to a verified source. A note whose reference cannot be
verified — by a capture in \`raw/\` or an authoritative metadata lookup — fails
the lint and never lands. Notes are named \`<title-slug>--<timestamp-id>.md\`;
the timestamp is immutable and the slug is frozen at creation, so links stay
stable when a title is reworded.

Generated by \`init_content_repo.sh\` on ${TODAY}.
README

# --- manifest ----------------------------------------------------------------
PYBIN="$(command -v python3 || command -v python)"
[[ -n "$PYBIN" ]] || die "python3 is required to build the manifest"
"$PYBIN" "${SCRIPT_DIR}/build_manifest.py" --repo "$DIR" >/dev/null || \
  die "failed to build the initial manifest"

# --- commit ------------------------------------------------------------------
git init -q -b main
git add -A
if ! git -c user.name="zettel-bootstrap" -c user.email="noreply@localhost" \
     commit -q -m "Genesis: scaffold ${NAME} substrate

Topics: ${TOPICS}
Cadence: ${CADENCE}
Budget: \$${BUDGET_USD}/run, ${BUDGET_TURNS} turns"; then
  die "initial commit failed"
fi

echo "scaffolded ${DIR} ($(git ls-files | wc -l | tr -d ' ') files committed)"

# --- publish -----------------------------------------------------------------
if [[ "$NO_REMOTE" -eq 1 ]]; then
  echo "--no-remote: skipped GitHub creation. Push manually with:"
  echo "  gh repo create ${OWNER}/${NAME} --${VISIBILITY} --source=. --remote=origin --push"
  next_steps
  exit 0
fi

gh repo create "${OWNER}/${NAME}" "--${VISIBILITY}" --source=. --remote=origin --push || \
  die "gh repo create failed; the local scaffold at ${DIR} is intact and committed"

echo "published https://github.com/${OWNER}/${NAME}"
next_steps
