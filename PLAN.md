# Build Plan — `zettel-bootstrap` Claude Code Skill

**Source of truth:** [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) (all FR-x / AC-x / NFR-x / QA-x / checklist references below point there).
**This repo:** the PRIVATE skill repo. It will contain ONLY the `zettel-bootstrap` plugin — never zettelkasten content. The content repo is created at genesis runtime by `init_content_repo.sh` and is out of scope for this repo's file tree.
**Status:** Phases 1-2 complete. Phases 3-4 not started.

---

## 1. Target repository layout (FR-13)

The plugin is laid out at the repo root (only `plugin.json` lives inside `.claude-plugin/`):

```
.claude-plugin/plugin.json          # name (required), version, description, author, repository (string URL)
skills/zettel-bootstrap/SKILL.md    # six portable frontmatter fields only; body <500 lines
agents/                             # 8 subagent definitions (.md + YAML frontmatter)
  orchestrator.md researcher.md synthesizer.md critic.md
  librarian.md connector.md note-maintainer.md skill-smith.md
references/                         # progressive-disclosure detail docs
  architecture.md note-types.md citation-rules.md orchestra.md
  two-mode-access.md scheduling.md skill-emergence.md quality-gates.md
templates/                          # content-repo scaffolding sources
  fleeting.md literature.md permanent.md reference.md moc.md
  inbox-entry.md config.yml PURPOSE.md child-SKILL.md
scripts/
  init_content_repo.sh maintenance_run.sh new_worktree.sh
  lint_citations.py lint_links.py build_manifest.py verify_refs.py
  fetch_remote.py serendipity_sweep.py
  csl/chicago-notes-bibliography.csl
tests/fixtures/                     # clean + planted-violation fixture notes (see §3)
requirements.txt
smoke_test.sh
.gitignore                          # already present; extend per NFR-4 (run.lock, *.token, .env, caches)
README.md                           # install + genesis/maintenance usage (FR-17)
docs/REQUIREMENTS.md                # the spec (committed alongside this plan)
PLAN.md                             # this file
```

---

## 2. Phased build order

Phases follow the spec's own Recommendations section. Each phase ends only when its exit-gate items from the §12 acceptance checklist pass.

### Phase 1 — Substrate + citation gates
*Exit gate: checklist items 1–6 and 8 (8 in stub form; fully exercised in Phase 2).*

Ship the genesis path first — smallest slice with standalone value, hardest gates.

1. **Templates** (`templates/`): the five note types encoding FR-4 rules, `inbox-entry.md`, `config.yml` with every FR-2 key (`topics`, `cadence`, `budget`, `autonomy_level`, `content_repo{name,owner,visibility}`, `embedding{enabled,model}`, `models{strong,cheap}`, `connector_cadence`, `skill_smith_cadence`), plus `PURPOSE.md` and `child-SKILL.md` for Phase 4. Reference template carries CSL-JSON frontmatter + `chicago_note`/`chicago_bib` + `source_tier` + `verification{method,source,verified,date}` + `raw_capture` fields (FR-4). IDs: timestamp-based immutable stems, no folgezettel; typed-link taxonomy `supports, contradicts, analogous, shared-concept, historical-connection, elaborates, refutes, source` (FR-5).
2. **`scripts/init_content_repo.sh`** (FR-18): args `--name --visibility --owner --topics --cadence --budget --dir`; scaffolds the exact FR-1 tree from templates, writes config.yml, `git init` + initial commit, `gh repo create <owner>/<name> --<visibility> --source=. --remote=origin --push`, builds initial manifest. Fails safely (non-zero, no clobber) when the remote name already exists (AC-18).
3. **`scripts/build_manifest.py`** (FR-3/FR-19): scans note frontmatter → `manifest.json` entries (`id,type,title,tags,links[{target_id,relation}],path,url_or_apipath,updated`). Deterministic and byte-idempotent (AC-3). Public content repo → full `raw.githubusercontent.com` URLs; private → repo-relative + GitHub API `contents` paths; never anonymous raw URLs for private (FR-topology).
4. **`scripts/verify_refs.py`** (FR-10/FR-22): Crossref (always send `mailto` for the polite pool; back off on HTTP 429), arXiv API, PubMed, Open Library / Google Books; OR `/raw/` capture. Writes `verification` blocks; exits 0 even with unverified refs (lint is the gate); `--offline` uses captures only; network failure degrades to capture-only with a logged warning (NFR-5).
5. **Citation rendering** (FR-8): **pandoc via bundled `pypandoc-binary` is the primary backend**, with `citeproc-py` wired as a fallback — the FR-8 threshold fired during Phase 1, because citeproc-py ignores the style's `initialize="false"` overrides and initializes given names (amendment A1). Style bundled at `scripts/csl/chicago-notes-bibliography.csl`, no network at runtime. Scripture: SBL book–chapter–verse, `source_tier: primary-text`, `scripture: true`, excluded from bibliography (FR-9).
6. **`scripts/lint_citations.py`** (FR-11/FR-12/FR-20): hard non-zero fail on any unverified reference, malformed/mismatched Chicago strings (recomputed from CSL-JSON), permanent-note sourced claim without a verified-reference link, `contested` note with <3 distinct reference links. Output: `FILE\tRULE\tREASON` lines.
7. **`scripts/lint_links.py`** (FR-21): typed-link taxonomy membership, `[[id]]` resolvability against manifest, INDEX→MOC→note layering, 1-1-1 rule, literature↔reference 1:1.
8. **`skills/zettel-bootstrap/SKILL.md`** (FR-14): frontmatter restricted to the six portable spec fields (`name, description, license, compatibility, metadata, allowed-tools`); third-person description with explicit what+when trigger language, ≤1024 chars, no XML tags; body <500 lines / ≤5,000 tokens with progressive disclosure into `references/`. Author/validate with the **skill-creator** skill.
9. **`.claude-plugin/plugin.json`** (FR-15), **`requirements.txt`** (citeproc-py, requests, pyyaml; sentence-transformers/networkx/python-louvain as optional extras), **`README.md`** (FR-17): plugin-marketplace install and `~/.claude/skills/` copy/link alternative, `gh` + PAT/SSH prerequisites, `pip install`, genesis vs. maintenance invocation.
10. **`references/`**: `architecture.md`, `note-types.md`, `citation-rules.md` written in this phase.
11. **Fixtures + `smoke_test.sh` v1** (checklist items 3–6): clean-note fixture set and one planted violation per lint rule (unverified ref, malformed Chicago string, missing reference link, bad relation, unresolved `[[id]]`, contested <3 sources); dummy content-repo creation/teardown documented.

### Phase 2 — Orchestra + maintenance + two-mode access
*Exit gate: checklist items 8–9.*

1. **`agents/`** — 8 definitions (FR-16/FR-29), each YAML frontmatter (`name`, `description`; explicit `tools` including `web_search` + `web_fetch`; `model` tier) with the system prompt as body; strong/cheap tiers resolved from content-repo `config.yml` `models`:
   - Orchestrator (strong): reads INBOX first, plans run, assigns worktrees.
   - Researchers (cheap): fleeting + literature notes, raw captures into `/raw/`.
   - Synthesizers (strong): atomic permanent notes, 1-1-1 enforcement.
   - Critic (strong): claim-by-claim groundedness; flag <0.80, block <0.70 (QA-1).
   - Librarian (cheap/strong): MOCs, tag ontology, manifest + refs.json rebuild.
   - Connector (cheap embed + strong justify): Phase 3 sweep.
   - Note-Maintainer (cheap): feedback revisions, fleeting sweeps, link hygiene.
   - Skill-smith (strong): Phase 4.
2. **`scripts/maintenance_run.sh`** (FR-25): wraps `claude -p "<maintenance prompt>" --output-format json --max-turns <N> --model <m> --max-budget-usd <B> --allowedTools "<scoped>" --permission-mode dontAsk`; stdout→result JSON, stderr→log; always sets `--max-turns` explicitly; honors `run.lock`; never pushes partial unlinted state on turn/budget cutoff. The embedded maintenance prompt encodes the FR-28 eleven-step cycle order (lock/pull → INBOX → inquiry research → routine maintenance → connector sweep → critic gates → skill-smith retrospective → lints → manifest/refs rebuild → commit+push with re-pull/re-lint retry → log + unlock), each step stamped into `log.md` (AC-28, NFR-2).
3. **`scripts/new_worktree.sh`** (FR-26) and `run.lock` serialization (FR-30): second concurrent run finds a fresh lock and exits without work.
4. **`scripts/fetch_remote.py`** (FR-23): container-side fetcher; `--manifest-url` or `--owner --repo [--token]` (token from env, never a repo file); raw for public, API+token for private.
5. **`references/two-mode-access.md`** + SKILL.md Mode-B section (FR-31 — the spec's most fragile point, belt-and-suspenders mandatory): document all five paths (manifest raw URLs; user-message/web_search URL entry so server-side `web_fetch` origin rules are satisfied; `fetch_remote.py` as primary container mechanism; GitHub MCP `get_file_contents` preferred when connected; Claude Code WebFetch) and the hard requirement of authenticated GitHub MCP for private content repos. Note the documented MCP `get_file_contents` 404 failure modes → PAT/API fallback stays wired.
6. **`references/scheduling.md` + `orchestra.md`** (FR-32): working crontab line, desktop/Cowork scheduled-task equivalent, and the caveat that Cowork/cloud sessions do not read local `~/.claude/skills/`.
7. Extend `smoke_test.sh`: dry-run maintenance cycle with a stub topic (checklist 8) and concurrent-lock test (checklist 9).

### Phase 3 — Connector / serendipity
*Exit gate: checklist item 7.*

1. **`scripts/serendipity_sweep.py`** (FR-24): args `--repo --threshold --out`; sentence-transformers embeddings (compact all-MiniLM-class default, configurable), cosine similarity, typed-link graph, Louvain community detection (`networkx` + `python-louvain`), cross-community link proposals (relation + one-line justification) into `/proposed-links/`. Writes proposals only — never edits notes. Graceful LLM-only degradation with logged downgrade when embeddings are unavailable.
2. Wire the Critic-review → accept-into-both-notes / log-rejection flow into the maintenance prompt (FR-28 step 5, slower configurable cadence).

### Phase 4 — Skill emergence (WikiSkill-adapted)
*Exit gate: checklist item 10.*

1. **Skill-smith agent** + **`references/skill-emergence.md`** / **`quality-gates.md`**: three-layer separation inside the content repo (FR-33) — `/raw/` + traces immutable; note graph + `log.md` + `skill-impact.md` never rolled back; `/skills/<name>/{SKILL.md,PURPOSE.md}` gated and rollbackable.
2. Proposer inputs (FR-34): manifest/INDEX + `skill-impact.md` + ≥4 recent run traces before proposing; PURPOSE.md carries Origin / Patterns-Addressed / Evolution-History.
3. Atomic proposals (FR-35): exactly one create-or-patch per cycle; prefer patching an existing skill.
4. Open-world gating (FR-36): A/B trial on inbox questions (groundedness / citation-coverage / critic scores), **human approval required**; rejection reverts the skill layer only and appends metadata + unified diff + scores + outcome to `skill-impact.md`; rejected proposals are not re-proposed; knowledge layer untouched.
5. Safety rails (FR-37): Skill-smith can never write to this skill repo; writes outside content-repo `/skills/` are blocked and logged; per-run budget caps enforced.

---

## 3. Testing & definition of done

The §12 checklist is the definition of done, run before final commit of each phase and in full before v1:

1. `claude plugin validate --strict .` clean; SKILL.md parses with only the six spec fields.
2. `pip install -r requirements.txt` succeeds; every script answers `--help`, exits 0/non-zero correctly, logs to stdout and (with `--repo`) appends to `log.md`, reads no secrets from the repo (§7 preamble, NFR-4).
3. `init_content_repo.sh` produces a live throwaway content repo with the full substrate committed; teardown documented.
4. Lints: 0 on clean fixtures; non-zero with named note+reason on each planted violation.
5. `build_manifest.py`: valid, byte-idempotent; correct public/private URL emission.
6. `verify_refs.py`: known DOI via Crossref (with `mailto`), known ISBN via Open Library/Google Books, `--offline` against a `/raw/` capture.
7. `serendipity_sweep.py`: embeddings path and LLM-only degradation both write to `/proposed-links/`.
8. Stub-topic dry-run maintenance cycle: FR-28 order visible in `log.md`; ends lint-clean-committed or aborts without push (NFR-3).
9. `run.lock`: second concurrent run aborts.
10. Skill-smith sandbox: proposal only under content-repo `/skills/`; out-of-repo write blocked and logged.
11. `smoke_test.sh` orchestrates 2–8 and exits 0.

---

## 4. Risks & contingency thresholds

- **citeproc-py CSL coverage** (implements CSL 1.0.1, partial test-suite pass): validate Chicago output on real fixtures early; flip to pandoc primary before Phase 1 sign-off if needed.
- **Server-side `web_fetch` URL-origin restriction**: skill-embedded URLs are not fetchable on claude.ai/API — the FR-31 five-path design is mandatory, with `fetch_remote.py` as the primary container-side mechanism.
- **Private content repo + Mode B**: requires authenticated GitHub MCP; must be configured and tested before Phase 2 sign-off if the user needs private Mode B.
- **Crossref rate limits** (revised effective 2025-12-01): always send `mailto`, back off on 429.
- **Budget**: if runs consistently trip `--max-budget-usd` mid-cycle, reduce Researcher fan-out and space connector/skill-smith cadences before scaling topics.
- **Platform drift**: plugin layout, six-field frontmatter rule, `claude -p` flags, and `gh repo create` flags were verified as of 2026-08-30 — re-verify with `claude plugin validate` and live docs at build time.

---

## 5. Inputs deferred to genesis runtime (not build-time)

Topic(s)/research path; content-repo name + visibility; cadence (plus connector/skill-smith sub-cadences); budget (USD/turn caps); whether GitHub MCP is enabled (mandatory for Mode B on private content repos). The first real seed topic, desktop/Cowork task setup, embedding enablement, and cloud Routines remain out of scope per §10.
