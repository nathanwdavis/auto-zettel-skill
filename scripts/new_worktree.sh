#!/usr/bin/env bash
# Create (or remove) an isolated git worktree for a subagent (FR-26).
#
# Worktrees live under <repo>/.worktrees/<branch>, which is gitignored, and
# share the repository's single .git. Two invocations with different names
# coexist without conflict (AC-26).

set -euo pipefail

REPO=""; NAME=""; REMOVE=0

usage() {
  cat <<'USAGE'
Usage: new_worktree.sh --repo <content-repo> --name <branch> [--remove]

  --repo    path to the content repository (required)
  --name    branch name for the worktree (required)
  --remove  remove the worktree and delete its branch instead of creating it

On create, prints the worktree path on stdout (the only stdout output), so
callers can capture it: WT=$(new_worktree.sh --repo r --name n).
USAGE
}

die() { echo "error: $*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo) REPO="${2:-}"; shift 2 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --remove) REMOVE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; die "unknown argument: $1" ;;
  esac
done

[[ -n "$REPO" ]] || { usage >&2; die "--repo is required"; }
[[ -n "$NAME" ]] || { usage >&2; die "--name is required"; }
[[ -d "$REPO/.git" ]] || die "not a git repository: $REPO"
[[ "$NAME" =~ ^[A-Za-z0-9._/-]+$ ]] || die "invalid branch name: $NAME"

REPO="$(cd "$REPO" && pwd)"
WT_DIR="$REPO/.worktrees/$NAME"

if [[ $REMOVE -eq 1 ]]; then
  git -C "$REPO" worktree remove --force "$WT_DIR" 2>/dev/null \
    || die "no worktree at $WT_DIR"
  git -C "$REPO" branch -D "$NAME" >/dev/null 2>&1 || true
  echo "removed worktree $NAME" >&2
  exit 0
fi

[[ -e "$WT_DIR" ]] && die "worktree already exists: $WT_DIR"
grep -qx '\.worktrees/' "$REPO/.gitignore" 2>/dev/null \
  || echo '.worktrees/' >> "$REPO/.gitignore"

mkdir -p "$REPO/.worktrees"
git -C "$REPO" worktree add -b "$NAME" "$WT_DIR" >&2 \
  || die "git worktree add failed for $NAME"
echo "$WT_DIR"
