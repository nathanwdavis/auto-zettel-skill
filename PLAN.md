# Build Plan — `zettel-bootstrap` Claude Code Skill

**Source of truth:** [`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) (all FR-x / AC-x / NFR-x / QA-x / checklist references below point there). Deviations forced by implementation are recorded there as numbered amendments — **A1–A6** so far.
**Working on this repo:** [`.claude/CLAUDE.md`](.claude/CLAUDE.md) — how to run the suite, the environment's sharp edges, and the conventions.
**This repo:** the skill repo. It contains ONLY the `zettel-bootstrap` plugin — never zettelkasten content. The content repo is created at genesis runtime by `init_content_repo.sh` and is out of scope for this repo's file tree. Both repos are public (A4); nothing here may contain a secret (NFR-4).
**Status:** Phases 1, 2, 3, 3.5, and 3.6 complete (3.6 on PR #5). Phase 4 not started.

---

## 1. Target repository layout (FR-13)

The plugin is laid out at the repo root (only `plugin.json` lives inside `.claude-plugin/`):

```
.claude-plugin/plugin.json          # name (required), version, description, author, repository (string URL)
skills/zettel-bootstrap/SKILL.md    # six portable frontmatter fields only; body <500 lines (currently 248)
agents/                             # 8 subagent definitions (.md + YAML frontmatter)
  orchestrator.md researcher.md synthesizer.md critic.md
  librarian.md connector.md note-maintainer.md skill-smith.md
references/                         # progressive-disclosure detail docs
  architecture.md note-types.md citation-rules.md orchestra.md
  two-mode-access.md scheduling.md serendipity.md remote-execution.md
  capture.md
  # Phase 4 will add: skill-emergence.md quality-gates.md
templates/                          # content-repo scaffolding sources
  fleeting.md literature.md permanent.md reference.md moc.md inquiry.md
  inbox-entry.md config.yml PURPOSE.md child-SKILL.md
scripts/
  init_content_repo.sh              # genesis (FR-18); --no-remote for local
  capture.py inquiries.py           # human/agent input + the FR-6 inquiry reporter
  adhoc_research.sh                 # "answer this now", through the scheduled path
  maintenance_run.sh                # laptop path: wraps a nested `claude -p`
  remote_cycle.sh                   # remote path: start|finish|abort|status
  maintenance_prompt.md remote_maintenance_prompt.md
  new_worktree.sh fetch_remote.py
  build_manifest.py verify_refs.py lint_citations.py lint_links.py
  serendipity_sweep.py
  zettel_lib/                       # shared library -- see the README note
    naming.py frontmatter.py repo.py cli.py http.py
    citations.py similarity.py agents.py gitlock.py
  csl/chicago-notes-bibliography.csl
ci/
  content-repo-gates.yml            # installed IN the content repo as a required check
  setup-environment.sh              # cloud environment setup (paste into claude.ai/code)
.github/workflows/ci.yml            # this repo's own CI: pytest + smoke test
tests/                              # pytest suite; fixtures are built in conftest.py,
  conftest.py cassettes/ stub_claude/  # not checked in as static files (see §3)
requirements.txt requirements-dev.txt requirements-optional.txt
smoke_test.sh
.gitignore                          # NFR-4: run.lock, *.token, .env, *.pem, caches
README.md                           # install + usage (FR-17)
.claude/CLAUDE.md                   # guidance for developing the skill itself
docs/REQUIREMENTS.md                # the spec, with amendments A1-A6
PLAN.md                             # this file
```

---

## 2. Phased build order

Phases follow the spec's own Recommendations section. Each phase ends only when its exit-gate items from the §12 acceptance checklist pass.

### Phase 1 — Substrate + citation gates  ✅ shipped
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

### Phase 2 — Orchestra + maintenance + two-mode access  ✅ shipped
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

### Phase 3 — Connector / serendipity  ✅ shipped
*Exit gate: checklist item 7.*

1. **`scripts/serendipity_sweep.py`** (FR-24): args `--repo --threshold --out`; sentence-transformers embeddings (compact all-MiniLM-class default, configurable), cosine similarity, typed-link graph, Louvain community detection (`networkx` + `python-louvain`), cross-community link proposals (relation + one-line justification) into `/proposed-links/`. Writes proposals only — never edits notes. Graceful LLM-only degradation with logged downgrade when embeddings are unavailable.
2. Wire the Critic-review → accept-into-both-notes / log-rejection flow into the maintenance prompt (FR-28 step 5, slower configurable cadence).

### Phase 3.5 — Remote-native execution  ✅ shipped
*Amendment A5. Exit gate: a Routine-fired session grows the wiki with no laptop involved.*

Phases 1–3 assumed a laptop: `maintenance_run.sh` wraps a nested `claude -p` and pushes only after re-running the lints itself. That wrapper cannot exist in a Routine-fired remote session, because **the session *is* the agent**. Three mechanisms changed shape, and the guarantee moved rather than weakened.

1. **`run.lock` → a git-native distributed lock** (`zettel_lib/gitlock.py`). A filesystem lock cannot serialize two ephemeral containers. The design called for `refs/zettel/run-lock`; **the git proxy rejected it** — only fast-forward pushes to ordinary branches are permitted, no custom ref namespaces and no deletions — so the lock is `LOCK.json` on branch `zettel/lock`. `claim()` raises `GitLockError` on a push-access failure rather than reporting false contention, so "cannot push at all" never masquerades as "another run is working".
2. **Wrapper-enforced gates → CI as the gate authority.** `scripts/remote_cycle.sh` (`start|finish|abort|status`) can only offer a branch; `ci/content-repo-gates.yml`, installed in the content repo with `gates` as a **required status check**, re-runs the lints server-side and decides what merges. This is strictly stronger than A3 — no session can bypass it. Exit 3 from `start` means stand down, and is a success.
3. **`--max-budget-usd` has no remote equivalent.** Cost is bounded by cadence, prompt scope, and model tier instead. A production run on Sonnet cost $2.33 against $6.94 on the stronger tier with quality holding, so the cheap tier is the default for scheduled cycles.

Proven by a three-round spike ($10.14) against a throwaway sandbox content repo. Also settled there: **a fresh Routine session has no push credentials** unless spawned with `source_url` or created from the claude.ai UI, and `ci/setup-environment.sh` **caches per environment** — a fix pushed to this repo does not reach scheduled runs until that script is edited.

### Phase 3.6 — Capture, inquiries, ad-hoc research  ✅ shipped (PR #5)
*Amendment A6. Exit gate: a human can add input, and ask a question, without a path around the gates.*

Every input path assumed a machine authored it. Dropping plain markdown into `fleeting/` made `build_manifest.py` raise, failing the required check on the *next scheduled run* — the author never saw the breakage, and an unrelated cycle took the red PR. The fix generated well-formed artifacts rather than loosening the gate.

1. **`scripts/capture.py`** — fleeting notes, inquiries, and INBOX entries that pass all four gates as written. One tool for a human at a terminal, an ad-hoc session, and the agents; reads bodies from stdin so it composes.
2. **FR-6 implemented** — `templates/inquiry.md`, a top-level `inquiries` block in the manifest, `scripts/inquiries.py` (read-only, `new` and highest-priority first), and the **AC-6 lint**: `answered` requires ≥1 `result_notes` entry resolving to a **permanent** note. Inquiries sit outside `NOTE_DIRS` — a question is not a node in the graph and is never a link target.
3. **`scripts/adhoc_research.sh`** — same lock, same run branch, same required-check handoff as a scheduled cycle. Exit 3 propagates unchanged: a live lock is never stolen. The question is filed *before* any research, so an interrupted session still leaves it behind. There is deliberately no ad-hoc path to `main`.
4. **A latent bug the tests surfaced**: note IDs are minute-resolution and the manifest's `id_to_key` map is many-to-one, so two notes minted in the same minute collided and a bare-ID link resolved to whichever was indexed last — silently. `capture.py` allocates around IDs in use; `build_manifest.py` raises and `lint_links.py` reports `duplicate-id` for notes it did not write.

**Still open**: the live sandbox check — capture an inquiry, let the next scheduled Routine pick it up, confirm it lands `answered` with a `result_notes` backlink. It is the only end-to-end test of the human → scheduled-run handoff against a real cycle. Worth running before Phase 4.

### Phase 4 — Skill emergence (WikiSkill-adapted)  ⬜ not started
*Exit gate: checklist item 10.*

1. **Skill-smith agent** + **`references/skill-emergence.md`** / **`quality-gates.md`**: three-layer separation inside the content repo (FR-33) — `/raw/` + traces immutable; note graph + `log.md` + `skill-impact.md` never rolled back; `/skills/<name>/{SKILL.md,PURPOSE.md}` gated and rollbackable.
2. Proposer inputs (FR-34): manifest/INDEX + `skill-impact.md` + ≥4 recent run traces before proposing; PURPOSE.md carries Origin / Patterns-Addressed / Evolution-History.
3. Atomic proposals (FR-35): exactly one create-or-patch per cycle; prefer patching an existing skill.
4. Open-world gating (FR-36): A/B trial on inbox questions (groundedness / citation-coverage / critic scores), **human approval required**; rejection reverts the skill layer only and appends metadata + unified diff + scores + outcome to `skill-impact.md`; rejected proposals are not re-proposed; knowledge layer untouched.
5. Safety rails (FR-37): Skill-smith can never write to this skill repo; writes outside content-repo `/skills/` are blocked and logged; per-run budget caps enforced.

---

## 3. Testing & definition of done

The §12 checklist is the definition of done, run before final commit of each phase and in full before v1. `smoke_test.sh` orchestrates every item that works without network or `gh`; the pytest suite currently stands at **280 tests**.

Fixtures are **built programmatically** in `tests/conftest.py`, not checked in as static files, so every violation fixture is provably "the clean repo with exactly one thing broken" and the reference note's Chicago strings stay self-consistent with its CSL-JSON.


1. `claude plugin validate --strict .` clean; SKILL.md parses with only the six spec fields.
2. `pip install -r requirements.txt` succeeds; every script answers `--help`, exits 0/non-zero correctly, logs to stdout and (with `--repo`) appends to `log.md`, reads no secrets from the repo (§7 preamble, NFR-4).
3. `init_content_repo.sh` produces a live throwaway content repo with the full substrate committed; teardown documented.
4. Lints: 0 on clean fixtures; non-zero with named note+reason on each planted violation.
5. `build_manifest.py`: valid, byte-idempotent; correct public/private URL emission.
6. `verify_refs.py`: known DOI via Crossref (with `mailto`), known ISBN via Open Library/Google Books, `--offline` against a `/raw/` capture.
7. `serendipity_sweep.py`: embeddings path and LLM-only degradation both write to `/proposed-links/`.
8. Stub-topic dry-run maintenance cycle: FR-28 order visible in `log.md`; ends lint-clean-committed or aborts without push (NFR-3).
9. `run.lock`: second concurrent run aborts.
10. Skill-smith sandbox: proposal only under content-repo `/skills/`; out-of-repo write blocked and logged. **(Phase 4 — the one open item.)**
11. `smoke_test.sh` orchestrates 2–8 and exits 0.

Added after the spec was written, and enforced by `smoke_test.sh` steps 8b–8d:

12. Maintenance cycle (stub `claude`): FR-28 order visible in `log.md`; a lint violation blocks the push; a second concurrent run aborts on `run.lock`.
13. Remote cycle: the git lock serializes two clones, work lands on a `zettel/run-*` branch, and `main` is never pushed directly.
14. Capture: hand-written markdown fails the manifest build (the motivating gap, asserted rather than assumed); everything `capture.py` writes passes all four gates; a burst of captures in one minute gets distinct IDs.
15. AC-6: an inquiry marked `answered` with empty `result_notes` fails `lint_links.py`; so does a `result_notes` entry that is unresolvable or not a permanent note.
16. Ad-hoc research: stands down with exit 3 on a lock held by a scheduled run, leaving no half-started work, and its answer reaches `main` only through the required check.

---

## 4. Risks & contingency thresholds

**Resolved during the build** (kept for the reasoning, not as open risk):

- ~~**citeproc-py CSL coverage**~~ — **fired, and flipped.** citeproc-py ignores the bundled style's 173 `initialize="false"` overrides and renders "L. Tang" where Chicago requires "Liyan Tang". pandoc via `pypandoc-binary` is now primary, citeproc-py the wired fallback (A1).
- ~~**`refs/zettel/run-lock` for the distributed lock**~~ — **denied by the git proxy**, which permits only fast-forward pushes to ordinary branches: no custom ref namespaces, no deletions. Rebuilt as `LOCK.json` on branch `zettel/lock` (A5).
- ~~**Routine-fired sessions can push**~~ — **they cannot**, unless spawned with `source_url` or created from the claude.ai UI. Settled in the Phase 3.5 spike.
- ~~**Minute-resolution note IDs are unique enough**~~ — **they are not.** Two notes minted in the same minute collided in the manifest's many-to-one `id_to_key` map and a bare-ID link silently resolved to the wrong note. Fixed by allocation in `capture.py` plus a `duplicate-id` lint (A6).

**Still live:**

- **`ci/setup-environment.sh` is cached per environment.** The skill version freezes at cache time, so a fix pushed here does not reach scheduled runs until that script is edited (changing `ZETTEL_SKILL_REF` suffices). Stability feature, freshness trap.
- **Server-side `web_fetch` URL-origin restriction**: skill-embedded URLs are not fetchable on claude.ai/API — the FR-31 five-path design is mandatory, with `fetch_remote.py` as the primary container-side mechanism.
- **Private content repo + Mode B**: requires authenticated GitHub MCP; must be configured and tested before Phase 2 sign-off if the user needs private Mode B.
- **Crossref rate limits** (revised effective 2025-12-01): always send `mailto`, back off on 429.
- **Budget**: if runs consistently trip `--max-budget-usd` mid-cycle, reduce Researcher fan-out and space connector/skill-smith cadences before scaling topics.
- **Platform drift**: plugin layout, six-field frontmatter rule, `claude -p` flags, and `gh repo create` flags were verified as of 2026-08-30 — re-verify with `claude plugin validate` and live docs at build time.
- **The sandbox blocks the citation APIs** (Crossref, OpenLibrary, PubMed, arXiv) and HuggingFace. Those paths are cassette-tested here and confirmed working in a Full-egress cloud environment; a failure in the sandbox is the proxy, not the code. See [`.claude/CLAUDE.md`](.claude/CLAUDE.md).

---

## 5. Inputs deferred to genesis runtime (not build-time)

Topic(s)/research path; content-repo name + visibility; cadence (plus connector/skill-smith sub-cadences); budget (USD/turn caps); whether GitHub MCP is enabled (mandatory for Mode B on private content repos). The first real seed topic, desktop/Cowork task setup, embedding enablement, and cloud Routines remain out of scope per §10.
