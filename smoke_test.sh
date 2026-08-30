#!/usr/bin/env bash
# End-to-end smoke test (acceptance checklist item 11).
#
# Orchestrates checklist items 2-8 that are runnable without network or gh:
#   2. dependencies import and every script answers --help
#   3. genesis scaffolds a working content repo (--no-remote)
#   4. lints pass clean and fail, with reasons, on planted violations
#   5. manifest builds, is idempotent, and honours the public/private matrix
#   6. verification writes state; --offline verifies from raw/ captures
#   8. the scaffolded repo ends lint-clean and committed
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
for s in build_manifest.py lint_citations.py lint_links.py verify_refs.py; do
  "$PY" "scripts/$s" --help >/dev/null 2>&1 || fail "scripts/$s --help"
  pass "scripts/$s --help"
done
bash scripts/init_content_repo.sh --help >/dev/null || fail "init_content_repo.sh --help"
pass "scripts/init_content_repo.sh --help"

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
