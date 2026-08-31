#!/usr/bin/env bash
# End-to-end smoke test (acceptance checklist item 11).
#
# Orchestrates checklist items 2-8 that are runnable without network or gh:
#   2. dependencies import and every script answers --help
#   3. genesis scaffolds a working content repo (--no-remote)
#   4. lints pass clean and fail, with reasons, on planted violations
#   5. manifest builds, is idempotent, and honours the public/private matrix
#   6. verification writes state; --offline verifies from raw/ captures
#   7. serendipity sweep proposes cross-community links without editing notes
#   8. the scaffolded repo ends lint-clean and committed
#   8b. a stub-driven maintenance cycle runs end-to-end and pushes
#   8c. the remote cycle: git-ref lock, run branch, no direct push to main
#   8d. capture + ad-hoc research: human input the gates accept
#   9. run.lock serialization: a second concurrent run aborts
#
# Exits 0 only if everything passes.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

PY="${PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"; else PY="$(command -v python3)"; fi
fi

pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1" >&2; exit 1; }
step() { printf '\n\033[1m%s\033[0m\n' "$1"; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- 2. scripts respond to --help --------------------------------------------
step "[2] script CLI contract"
for s in build_manifest.py lint_citations.py lint_links.py verify_refs.py fetch_remote.py \
         serendipity_sweep.py capture.py inquiries.py lint_skills.py \
         check_skill_sandbox.py skill_review.py skill_trial.py; do
  "$PY" "scripts/$s" --help >/dev/null 2>&1 || fail "scripts/$s --help"
  pass "scripts/$s --help"
done
for sh_script in init_content_repo.sh maintenance_run.sh new_worktree.sh adhoc_research.sh; do
  bash "scripts/$sh_script" --help >/dev/null || fail "$sh_script --help"
  pass "scripts/$sh_script --help"
done

# --- 3. genesis ---------------------------------------------------------------
step "[3] genesis scaffold"
KB="$WORK/kb-smoke"
PATH="$(dirname "$PY"):$PATH" bash scripts/init_content_repo.sh \
  --name kb-smoke --visibility public --owner smoke-owner \
  --topics "smoke topic" --dir "$KB" --no-remote >/dev/null \
  || fail "init_content_repo.sh"
pass "substrate scaffolded ($(git -C "$KB" ls-files | wc -l | tr -d ' ') files committed)"

for f in INBOX.md INDEX.md manifest.json config.yml log.md skill-impact.md .bib/refs.json; do
  git -C "$KB" ls-files --error-unmatch "$f" >/dev/null 2>&1 || fail "$f not committed"
done
pass "every substrate path is tracked (AC-1)"

git -C "$KB" diff --quiet && git -C "$KB" diff --cached --quiet \
  || fail "scaffold left uncommitted changes"
pass "working tree clean after genesis"

# --- 5. manifest idempotency --------------------------------------------------
step "[5] manifest determinism"
cp "$KB/manifest.json" "$WORK/manifest.first"
"$PY" scripts/build_manifest.py --repo "$KB" >/dev/null
cmp -s "$WORK/manifest.first" "$KB/manifest.json" || fail "manifest.json is not idempotent"
pass "manifest.json is byte-identical on re-run (AC-3)"

# --- 6 + 8. gates on the fresh scaffold ---------------------------------------
step "[6,8] gates on the scaffolded repo"
"$PY" scripts/verify_refs.py --repo "$KB" --offline >/dev/null || fail "verify_refs.py --offline"
pass "verify_refs.py --offline"
"$PY" scripts/lint_citations.py --repo "$KB" >/dev/null || fail "lint_citations.py on clean repo"
pass "lint_citations.py exits 0 on a clean repo"
"$PY" scripts/lint_links.py --repo "$KB" >/dev/null || fail "lint_links.py on clean repo"
pass "lint_links.py exits 0 on a clean repo"

# --- 7. serendipity sweep -----------------------------------------------------
step "[7] serendipity sweep"
SWEEP_KB="$WORK/kb-sweep"
"$PY" - "$SWEEP_KB" <<'PYEOF'
import sys
sys.path.insert(0, "tests"); sys.path.insert(0, "scripts")
from pathlib import Path
from conftest import build_two_cluster_repo
build_two_cluster_repo(Path(sys.argv[1]))
PYEOF
[[ -d "$SWEEP_KB" ]] || fail "sweep fixture not built"

BEFORE_HASH="$(find "$SWEEP_KB" -name '*.md' -not -path '*/proposed-links/*' -not -name 'log.md' -exec sha256sum {} + | sort | sha256sum)"
"$PY" scripts/serendipity_sweep.py --repo "$SWEEP_KB" >/dev/null || fail "serendipity_sweep.py"
N_PROPOSALS="$(find "$SWEEP_KB/proposed-links" -name '*.md' | wc -l | tr -d ' ')"
[[ "$N_PROPOSALS" -gt 0 ]] || fail "sweep produced no proposals"
pass "sweep wrote $N_PROPOSALS proposal(s) to proposed-links/"

AFTER_HASH="$(find "$SWEEP_KB" -name '*.md' -not -path '*/proposed-links/*' -not -name 'log.md' -exec sha256sum {} + | sort | sha256sum)"
[[ "$BEFORE_HASH" == "$AFTER_HASH" ]] || fail "sweep modified notes"
pass "no note was modified by the sweep"

"$PY" scripts/serendipity_sweep.py --repo "$SWEEP_KB" >/dev/null || fail "sweep re-run"
[[ "$(find "$SWEEP_KB/proposed-links" -name '*.md' | wc -l | tr -d ' ')" == "$N_PROPOSALS" ]] \
  || fail "sweep re-run duplicated proposals"
pass "re-run is idempotent (no duplicate proposals)"

# --- 8b + 9. maintenance cycle + lock serialization ---------------------------
step "[8b,9] stub maintenance cycle and run.lock"
MKB="$WORK/kb-maint"
PATH="$(dirname "$PY"):$PATH" bash scripts/init_content_repo.sh \
  --name kb-maint --visibility public --owner smoke-owner \
  --topics "smoke topic" --dir "$MKB" --no-remote >/dev/null || fail "maintenance scaffold"
ORIGIN="$WORK/origin.git"
git init -q --bare -b main "$ORIGIN"
git -C "$MKB" remote add origin "$ORIGIN"
git -C "$MKB" branch -M main
git -C "$MKB" push -q -u origin main
BEFORE="$(git -C "$ORIGIN" rev-parse main)"

STUB="$ROOT/tests/stub_claude/claude"
export PYTHON="$PY" RESULTS_DIR="$WORK/runs"

STUB_CLAUDE_MODE=good bash scripts/maintenance_run.sh --repo "$MKB" --claude-bin "$STUB" >/dev/null \
  || fail "maintenance run (good)"
[[ "$(git -C "$ORIGIN" rev-parse main)" != "$BEFORE" ]] || fail "good run did not push"
grep -q "gates passed independently" "$MKB/log.md" || fail "gate step not logged"
pass "stub maintenance cycle pushed; FR-28 steps visible in log.md (item 8)"

AFTER_GOOD="$(git -C "$ORIGIN" rev-parse main)"
STUB_CLAUDE_MODE=violate bash scripts/maintenance_run.sh --repo "$MKB" --claude-bin "$STUB" >/dev/null 2>&1 \
  && fail "violating run should exit non-zero"
[[ "$(git -C "$ORIGIN" rev-parse main)" == "$AFTER_GOOD" ]] || fail "violating run pushed"
pass "lint violation blocked the push (A3)"

# reset the repo for the lock test (the violating commit stays local otherwise)
git -C "$MKB" reset -q --hard "$AFTER_GOOD"
STUB_CLAUDE_MODE=slow bash scripts/maintenance_run.sh --repo "$MKB" --claude-bin "$STUB" >/dev/null &
FIRST_PID=$!
sleep 1
SECOND_OUT="$(STUB_CLAUDE_MODE=slow bash scripts/maintenance_run.sh --repo "$MKB" --claude-bin "$STUB")"
wait "$FIRST_PID" || fail "first concurrent run failed"
echo "$SECOND_OUT" | grep -q "another run holds run.lock" || fail "second run did not abort on lock"
pass "second concurrent run aborted on run.lock (item 9)"

# --- 8c. remote cycle: session-as-agent mechanics ------------------------------
step "[8c] remote cycle (git lock + run branch)"
RKB="$WORK/kb-remote"
PATH="$(dirname "$PY"):$PATH" bash scripts/init_content_repo.sh \
  --name kb-remote --visibility public --owner smoke-owner \
  --topics "smoke topic" --dir "$RKB" --no-remote >/dev/null || fail "remote scaffold"
RORIGIN="$WORK/remote-origin.git"
git init -q --bare -b main "$RORIGIN"
git -C "$RKB" remote add origin "$RORIGIN"
git -C "$RKB" branch -M main && git -C "$RKB" push -q -u origin main
git -C "$RKB" remote set-head origin -a >/dev/null 2>&1 || true

export PYTHON="$PY"
RBRANCH="$(ZETTEL_RUN_HOLDER=smoke-1 bash scripts/remote_cycle.sh start --repo "$RKB")" \
  || fail "remote_cycle start"
pass "lock claimed, run branch $RBRANCH"

git clone -q "$RORIGIN" "$WORK/kb-remote-2"
SECOND="$(ZETTEL_RUN_HOLDER=smoke-2 bash scripts/remote_cycle.sh start --repo "$WORK/kb-remote-2"; echo "rc=$?")"
echo "$SECOND" | grep -q "rc=3" || fail "second remote run did not stand down (got: $SECOND)"
pass "second container stood down on the git lock (exit 3)"

echo "- smoke change" >> "$RKB/INBOX.md"
MAIN_BEFORE="$(git -C "$RORIGIN" rev-parse main)"
bash scripts/remote_cycle.sh finish --repo "$RKB" --title "smoke cycle" >/dev/null || fail "remote_cycle finish"
[[ "$(git -C "$RORIGIN" rev-parse main)" == "$MAIN_BEFORE" ]] || fail "remote cycle pushed to main directly"
git -C "$RORIGIN" branch | grep -q "$RBRANCH" || fail "run branch missing from origin"
pass "work landed on the run branch; main untouched (CI decides)"

# --- 8d. capture and ad-hoc research ------------------------------------------
step "[8d] capture + ad-hoc research"

# The gap this closes: plain markdown in fleeting/ fails the NEXT run's manifest
# build, so the person who dropped it never sees the breakage.
echo "just a thought" > "$KB/fleeting/hand-written.md"
"$PY" scripts/build_manifest.py --repo "$KB" >/dev/null 2>&1 \
  && fail "hand-written note should have failed the manifest build"
rm "$KB/fleeting/hand-written.md"
pass "hand-written markdown fails the manifest build (the motivating gap)"

"$PY" scripts/capture.py --repo "$KB" fleeting "A captured thought" --tags smoke >/dev/null \
  || fail "capture.py fleeting"
"$PY" scripts/capture.py --repo "$KB" inquiry "Does capture hold the gates?" >/dev/null \
  || fail "capture.py inquiry"
"$PY" scripts/capture.py --repo "$KB" inbox "Smoke feedback" >/dev/null \
  || fail "capture.py inbox"
pass "captured a fleeting note, an inquiry, and an INBOX entry"

for g in build_manifest.py lint_citations.py lint_links.py; do
  "$PY" "scripts/$g" --repo "$KB" >/dev/null || fail "$g after capture"
done
pass "all gates still clean after capture"

grep -q '"inquiries"' "$KB/manifest.json" || fail "inquiries not indexed in manifest"
"$PY" scripts/inquiries.py --repo "$KB" --status new --json | grep -q "Does capture hold" \
  || fail "inquiries.py did not report the new inquiry"
pass "inquiry indexed in the manifest and reported by inquiries.py"

# AC-6: answered with nothing to point at must fail the lint.
INQ="$(ls "$KB"/inquiries/*.md | head -1)"
sed -i.bak 's/^status: new/status: answered/' "$INQ" && rm -f "$INQ.bak"
"$PY" scripts/lint_links.py --repo "$KB" >/dev/null 2>&1 \
  && fail "answered inquiry with empty result_notes should fail the lint (AC-6)"
sed -i.bak 's/^status: answered/status: new/' "$INQ" && rm -f "$INQ.bak"
pass "AC-6 rejects an answered inquiry with no result_notes"

# Ad-hoc research shares the lock with scheduled runs and never reaches main.
AKB="$WORK/kb-adhoc"
git clone -q "$RORIGIN" "$AKB"
git -C "$AKB" remote set-head origin -a >/dev/null 2>&1 || true
ABRANCH="$(ZETTEL_RUN_HOLDER=adhoc bash scripts/adhoc_research.sh \
  --repo "$AKB" --question "What does an ad-hoc run land?" | sed -n 's/^branch: //p')" \
  || fail "adhoc_research.sh"
[[ -n "$ABRANCH" ]] || fail "adhoc_research.sh printed no branch"
ls "$AKB"/inquiries/*.md >/dev/null 2>&1 || fail "adhoc did not file the inquiry"
pass "ad-hoc run claimed the lock, filed the inquiry, opened $ABRANCH"

ADHOC_BLOCKED="$(ZETTEL_RUN_HOLDER=adhoc-2 bash scripts/adhoc_research.sh \
  --repo "$RKB" --question "Can I barge in?" 2>/dev/null; echo "rc=$?")"
echo "$ADHOC_BLOCKED" | grep -q "rc=3" \
  || fail "ad-hoc did not stand down while the lock was held (got: $ADHOC_BLOCKED)"
pass "a second ad-hoc run stood down on the shared lock (exit 3)"

MAIN_BEFORE="$(git -C "$RORIGIN" rev-parse main)"
bash scripts/remote_cycle.sh finish --repo "$AKB" --title "smoke ad-hoc" >/dev/null \
  || fail "ad-hoc finish"
[[ "$(git -C "$RORIGIN" rev-parse main)" == "$MAIN_BEFORE" ]] \
  || fail "ad-hoc research pushed to main directly"
git -C "$RORIGIN" branch | grep -q "$ABRANCH" || fail "ad-hoc branch missing from origin"
pass "the ad-hoc answer landed on a branch; main untouched"

# --- 8e. skill sandbox: proposal, escape, reject, promote (checklist 10) -------
step "[8e] skill-smith sandbox and review flow"
SKB="$WORK/kb-skills"
PATH="$(dirname "$PY"):$PATH" bash scripts/init_content_repo.sh \
  --name kb-skills --visibility public --owner smoke-owner \
  --topics "smoke topic" --dir "$SKB" --no-remote >/dev/null || fail "skills scaffold"
SORIGIN="$WORK/skills-origin.git"
git init -q --bare -b main "$SORIGIN"
git -C "$SKB" remote add origin "$SORIGIN"
git -C "$SKB" branch -M main && git -C "$SKB" push -q -u origin main

NOTE_HASH() { find "$1" \( -path '*/permanent/*' -o -path '*/literature/*' \
  -o -path '*/reference/*' -o -path '*/moc/*' \) -name '*.md' \
  -exec sha256sum {} + | sort | sha256sum; }

# an inquiry for the auto-trial to answer, committed so preflight stays clean
"$PY" scripts/capture.py --repo "$SKB" inquiry "Does the smoke trial fire?" >/dev/null \
  || fail "capture inquiry for trial"
git -C "$SKB" add -A && git -C "$SKB" -c user.name=smoke -c user.email=s@localhost \
  commit -q -m "smoke: trial inquiry"

BEFORE_NOTES_TRIAL="$(NOTE_HASH "$SKB")"
STUB_CLAUDE_MODE=smith bash scripts/maintenance_run.sh --repo "$SKB" --claude-bin "$STUB" >/dev/null \
  || fail "smith maintenance run"
git -C "$SORIGIN" ls-tree -r --name-only main | grep -q "skills/demo-skill/SKILL.md" \
  || fail "proposal did not reach origin"
grep -q "proposed" "$SKB/skill-impact.md" || fail "proposal not recorded in skill-impact.md"
"$PY" scripts/lint_skills.py --repo "$SKB" >/dev/null || fail "lint_skills after proposal"
pass "smith cycle proposed skills/demo-skill and recorded it (FR-35)"

# the wrapper auto-ran the A/B trial: scores recorded, notes untouched (FR-36)
grep -q "skill_trial: demo-skill with=" "$SKB/log.md" || fail "trial scores not logged"
grep -q "| trial |" "$SKB/skill-impact.md" || fail "trial record missing from skill-impact.md"
ls "$WORK/runs"/trial-demo-skill-*.json >/dev/null 2>&1 || fail "trial scores JSON not written"
[[ "$(NOTE_HASH "$SKB")" == "$BEFORE_NOTES_TRIAL" ]] || fail "the trial modified knowledge notes"
pass "A/B trial auto-ran with the proposal; scores await the human gate (FR-36)"

SKB_MAIN="$(git -C "$SORIGIN" rev-parse main)"
# gate PASS lines land in log.md after the run's commit; drop them so the
# next run's clean-tree preflight is exercised on the pushed state
git -C "$SKB" reset -q --hard "$SKB_MAIN"
STUB_CLAUDE_MODE=smith-escape bash scripts/maintenance_run.sh --repo "$SKB" --claude-bin "$STUB" >/dev/null 2>&1 \
  && { rm -f "$ROOT/.stub-escape"; fail "plugin-repo write should fail the run"; }
rm -f "$ROOT/.stub-escape"
[[ "$(git -C "$SORIGIN" rev-parse main)" == "$SKB_MAIN" ]] || fail "escape run pushed"
grep -q "SANDBOX VIOLATION" "$SKB/log.md" || fail "sandbox violation not logged"
pass "an out-of-repo write attempt was blocked and logged (AC-37, item 10)"

# reset to the pushed proposal state; the escape run's commit stays local otherwise
git -C "$SKB" reset -q --hard "$SKB_MAIN"
BEFORE_NOTES="$(NOTE_HASH "$SKB")"
"$PY" scripts/skill_review.py --repo "$SKB" reject --skill demo-skill \
  --reason "smoke rejection" >/dev/null || fail "skill_review reject"
[[ ! -d "$SKB/skills/demo-skill" ]] || fail "rejected create not removed"
[[ "$(NOTE_HASH "$SKB")" == "$BEFORE_NOTES" ]] || fail "rejection touched knowledge notes (AC-33)"
grep -q "Rejected" "$SKB/skill-impact.md" || fail "rejection not recorded"
"$PY" scripts/lint_skills.py --repo "$SKB" >/dev/null || fail "lint_skills after rejection"
pass "rejection reverted the skill layer only; knowledge untouched (FR-36/AC-33)"

# the lint's PASS line above is uncommitted log noise; drop it so preflight passes
git -C "$SKB" checkout -q -- log.md
STUB_CLAUDE_MODE=smith bash scripts/maintenance_run.sh --repo "$SKB" --claude-bin "$STUB" >/dev/null 2>&1 \
  && fail "re-proposal of a rejected create should fail the gates"
grep -q "re-proposed-skill\|REFUSED re-proposal" "$SKB/log.md" \
  || fail "re-proposal not flagged"
# drop the aborted run's leavings but KEEP the rejection commit and record
git -C "$SKB" checkout -q -- . && git -C "$SKB" clean -qfd
pass "a rejected create is never retried (AC-36)"

"$PY" - "$SKB" <<'PYEOF'
import sys
sys.path.insert(0, "tests"); sys.path.insert(0, "scripts")
from pathlib import Path
from conftest import plant_skill
repo = Path(sys.argv[1])
plant_skill(repo, "keeper-skill", cite="stub-run-observation--209901010001")
PYEOF
"$PY" scripts/skill_review.py --repo "$SKB" propose --skill keeper-skill \
  --kind create --motivation "smoke promotion" >/dev/null || fail "propose keeper-skill"
git -C "$SKB" add -A && git -C "$SKB" -c user.name=smoke -c user.email=s@localhost \
  commit -q -m "smoke: keeper proposal"
"$PY" scripts/skill_review.py --repo "$SKB" promote --skill keeper-skill \
  --reason "smoke approval" >/dev/null || fail "skill_review promote"
grep -q "status: approved" "$SKB/skills/keeper-skill/PURPOSE.md" || fail "promotion did not flip status"
"$PY" scripts/skill_review.py --repo "$SKB" list | grep -q "keeper-skill.*approved" \
  || fail "list does not show the approved skill"
for g in build_manifest.py lint_citations.py lint_links.py lint_skills.py; do
  "$PY" "scripts/$g" --repo "$SKB" >/dev/null || fail "$g after promotion"
done
pass "promotion flipped status to approved and every gate stays clean (FR-36)"

# --- 4. lints fail on violations ----------------------------------------------
step "[4] planted violations are rejected"
if ! "$PY" -m pytest -q tests/ >"$WORK/pytest.log" 2>&1; then
  cat "$WORK/pytest.log" >&2
  fail "pytest suite"
fi
pass "pytest: $(grep -Eo '[0-9]+ passed[^=]*' "$WORK/pytest.log" | tail -1 | tr -d '\n')"

step "smoke test passed"
echo
echo "Not covered here (require network / gh -- run these manually):"
echo "  * gh repo create           : drop --no-remote on a machine with gh authenticated"
echo "  * live metadata lookups    : scripts/verify_refs.py --repo <repo> --mailto you@example.org"
