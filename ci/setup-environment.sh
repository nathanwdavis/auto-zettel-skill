#!/usr/bin/env bash
# Cloud environment setup script for scheduled zettel-bootstrap maintenance.
#
# Paste this into the environment's setup script field at claude.ai/code
# (cloud icon -> environment settings -> Setup script). It runs BEFORE Claude
# boots, in every session on that environment -- web, --cloud, and Routine-fired
# scheduled runs alike.
#
# The skill repo is public, so no token is required.
#
# IMPORTANT -- the result is CACHED per environment, so this script alone
# cannot keep the install current (a live session found it 12 commits stale,
# issue #7). The cache is the BOOTSTRAP; currency comes from
# `remote_cycle.sh refresh-skill`, which the remote maintenance prompt runs
# before every cycle (fast-forward-only, to ZETTEL_SKILL_REF). Pin a tag
# deliberately when you want runs frozen at a revision.

set -euo pipefail

ZETTEL_SKILL_REPO="${ZETTEL_SKILL_REPO:-https://github.com/nathanwdavis/auto-zettel-skill.git}"
ZETTEL_SKILL_REF="${ZETTEL_SKILL_REF:-main}"
INSTALL_DIR="${ZETTEL_INSTALL_DIR:-/opt/zettel-skill}"

echo "installing zettel-bootstrap from ${ZETTEL_SKILL_REPO}@${ZETTEL_SKILL_REF}"

# Update-if-exists rather than re-clone: cheaper on a warm cache, and it is
# the same ff-only mechanism refresh-skill uses at run time.
if [[ -d "$INSTALL_DIR/.git" ]]; then
  git -C "$INSTALL_DIR" fetch -q origin "$ZETTEL_SKILL_REF" \
    && git -C "$INSTALL_DIR" checkout -q -B "$ZETTEL_SKILL_REF" FETCH_HEAD \
    || { echo "warning: could not update ${INSTALL_DIR}; re-cloning" >&2
         rm -rf "$INSTALL_DIR"; }
fi
if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  rm -rf "$INSTALL_DIR"
  git clone --depth 1 --branch "$ZETTEL_SKILL_REF" "$ZETTEL_SKILL_REPO" "$INSTALL_DIR"
fi
SKILL_REV="$(git -C "$INSTALL_DIR" rev-parse --short HEAD)"
echo "zettel-bootstrap at revision ${SKILL_REV}"

# Make the skill discoverable to the session.
mkdir -p "$HOME/.claude/skills"
ln -sfn "$INSTALL_DIR/skills/zettel-bootstrap" "$HOME/.claude/skills/zettel-bootstrap"

# Register the agent definitions too. Without this, a remote session has NONE
# of the eight named agents the maintenance prompts delegate to -- the live
# session had to improvise the critic gate from prose (issue #7, finding 8).
mkdir -p "$HOME/.claude/agents"
for agent in "$INSTALL_DIR"/agents/*.md; do
  ln -sfn "$agent" "$HOME/.claude/agents/$(basename "$agent")"
done

# Deliberately NOT upgrading pip: on Debian-based images the system pip has no
# RECORD file and `pip install --upgrade pip` hard-fails the whole setup.
python3 -m pip install --quiet -r "$INSTALL_DIR/requirements.txt"

# Verify what actually landed, rather than trusting git's exit code. A clone can
# succeed and still be the wrong ref. Failing loudly here beats failing
# mid-cycle: a maintenance run without the gates is worse than no run at all,
# because nothing would stop ungrounded notes from landing.
[[ -f "$INSTALL_DIR/skills/zettel-bootstrap/SKILL.md" ]] \
  || { echo "error: SKILL.md missing from ${INSTALL_DIR} -- wrong ref '${ZETTEL_SKILL_REF}'?" >&2; exit 1; }
[[ -d "$INSTALL_DIR/agents" ]] \
  || { echo "error: agents/ missing from ${INSTALL_DIR}" >&2; exit 1; }
[[ -e "$HOME/.claude/agents/critic.md" ]] \
  || { echo "error: agent registration failed (no ~/.claude/agents/critic.md)" >&2; exit 1; }
python3 "$INSTALL_DIR/scripts/lint_citations.py" --help >/dev/null
python3 "$INSTALL_DIR/scripts/lint_links.py" --help >/dev/null
python3 -c "import yaml, requests, networkx"

echo "zettel-bootstrap ready at ${INSTALL_DIR} (${SKILL_REV}, ref ${ZETTEL_SKILL_REF})"
