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
# IMPORTANT -- the result is CACHED per environment. The skill version freezes
# at cache time: a fix pushed to the skill repo will NOT reach scheduled runs
# until you edit this script (changing ZETTEL_SKILL_REF is enough). That is a
# feature for stability and a trap for freshness. Pin a tag deliberately.

set -euo pipefail

ZETTEL_SKILL_REPO="${ZETTEL_SKILL_REPO:-https://github.com/nathanwdavis/auto-zettel-skill.git}"
ZETTEL_SKILL_REF="${ZETTEL_SKILL_REF:-main}"
INSTALL_DIR="${ZETTEL_INSTALL_DIR:-/opt/zettel-skill}"

echo "installing zettel-bootstrap from ${ZETTEL_SKILL_REPO}@${ZETTEL_SKILL_REF}"

rm -rf "$INSTALL_DIR"
git clone --depth 1 --branch "$ZETTEL_SKILL_REF" "$ZETTEL_SKILL_REPO" "$INSTALL_DIR"

# Make the skill discoverable to the session.
mkdir -p "$HOME/.claude/skills"
ln -sfn "$INSTALL_DIR/skills/zettel-bootstrap" "$HOME/.claude/skills/zettel-bootstrap"

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
python3 "$INSTALL_DIR/scripts/lint_citations.py" --help >/dev/null
python3 "$INSTALL_DIR/scripts/lint_links.py" --help >/dev/null
python3 -c "import yaml, requests, networkx"

echo "zettel-bootstrap ready at ${INSTALL_DIR} (ref ${ZETTEL_SKILL_REF})"
