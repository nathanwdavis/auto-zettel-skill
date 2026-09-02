# Spec compliance review — 2026-09-02

> **Resolution.** Every item in §1 was closed in code on the same branch
> (see `PLAN.md`, "Post-Phase-4 round 5"); §2's choices are recorded as
> amendment A9 in `docs/REQUIREMENTS.md`; §3's drift was corrected. The
> findings below are kept as written, as the record of what was found.

A pass over `docs/REQUIREMENTS.md` (FR/AC/NFR/QA, amendments A1–A8, §12
checklist) and `PLAN.md` against the code at `f5b953c` (main after PR #13).
Every claim below was checked against a file and line; probes that needed a
running lint were run against fixture repos in a scratch directory and are
described where relevant. Nothing in the tree was changed by this review.

**Baseline that still holds:** `claude plugin validate --strict .` passes;
`smoke_test.sh` exits 0; 347 tests pass; SKILL.md uses only the six portable
frontmatter fields (description 541 chars, body 291 lines); every §12
checklist item that can run offline runs green.

The findings are grouped by what they need: a code change, an amendment
(the implementation made a defensible choice the spec does not record), or a
doc fix. Within each group, most consequential first.

---

## 1. Functionality gaps (spec says X, code does not do X)

### 1.1 README's primary install route cannot work (FR-17 / AC-17)

`README.md:33-34` documents `/plugin marketplace add nathanwdavis/auto-zettel-skill`
then `/plugin install zettel-bootstrap@auto-zettel-skill`. A marketplace
needs `.claude-plugin/marketplace.json`; the directory holds only
`plugin.json`. The marketplace-add step fails, so AC-17 ("following README
steps on a clean machine yields an invocable command") is met only by the
plain-skill symlink route. Note that the symlink route links
`skills/zettel-bootstrap/` alone, so the relative `scripts/…` and
`references/…` paths SKILL.md cites do not resolve from `~/.claude/skills/`
either; the plugin route is the one where they would.

### 1.2 AC-2 config validation exists on the laptop path only

`maintenance_run.sh:80-92` hard-fails on twelve missing keys. `remote_cycle.sh`
performs no config validation at all: its only config read is the advisory
`zettel_lib.agents --materialize` call (`remote_cycle.sh:242-250`), which warns
and continues. On the remote path, which PLAN.md calls "the primary driver",
a missing `cadence`, `budget`, `autonomy_level`, `connector_cadence`, or
`skill_smith_cadence` is never reported; only `content_repo.*` fails, in CI,
via `build_manifest.py:44-46`, after the session has done its work.

Also: `embedding.enabled` / `embedding.model` (FR-2) are required nowhere,
and `autonomy_level` is checked for presence (`maintenance_run.sh:83`) but
read by no code path. It is an inert key.

### 1.3 FR-16: four agents lack the tools the spec gives all agents

FR-16: "All agents get `web_search` + `web_fetch` in their tool set."

| agent | WebSearch | WebFetch |
|---|---|---|
| `agents/critic.md:5` | no | yes |
| `agents/note-maintainer.md:5` | no | yes |
| `agents/connector.md:5` | no | no |
| `agents/skill-smith.md:5` | no | no |

The only rationale anywhere is a test docstring (`tests/test_agents.py:46-50`)
narrowing the intent to "agents that gather or check sources". Restricting the
connector and smith is defensible (they should not browse), but it is neither
amended nor explained in `references/orchestra.md`. Either add the tools or
record an amendment.

### 1.4 FR-27 genesis steps 4 and 5 are prose, not code

`init_content_repo.sh` scaffolds, builds the manifest, commits, and ends with
`echo "published …"` (`:236`) or the `--no-remote` hint (`:228-230`). It does
not dispatch a first orchestra pass and prints no scheduling next-steps (no
`cron`/`cowork`/`desktop` text in the script beyond the `--cadence` usage
line). Both exist only as instructions to the interactive session
(`SKILL.md:52-55`, `references/architecture.md:52-57`). AC-27's post-genesis
state (≥1 verified reference, literature, permanent, MOC) therefore depends on
the session following SKILL.md. No amendment records this.

### 1.5 FR-4 rules the templates state but no lint enforces

Probed by building a clean fixture repo and mutating one thing; each of
these passed `lint_citations.py` and `lint_links.py` with exit 0:

- **MOCs link to notes.** `lint_layering` (`lint_links.py:181-198`) checks
  INDEX→MOC only. A MOC whose only link is a reference note passes, and an
  INDEX listing zero MOCs passes. `references/note-types.md:73-76` says the
  lint enforces this.
- **Exactly one reference note per source.** Two reference notes with the
  same ISBN and the same `csl_json.id` pass both lints and both land in
  `refs.json` with duplicate ids. This also hollows out FR-12's
  "≥3 *independent* sources": `contested-undersourced`
  (`lint_citations.py:149-153`) counts distinct reference-note keys, so three
  notes for one DOI satisfy it.
- **Reference-note field completeness.** A reference with no `raw_capture`
  key, no `verification.source`/`date`, or no `source_tier` passes silently.
  Only `verification.verified`/`method` (`:84-91`), the CSL-JSON, and the
  Chicago strings are checked.
- **`source_tier` vocabulary (QA-3).** `source_tier: blog-post` passes with no
  warning; `_check_sourcing_strength` (`lint_citations.py:157-180`) only warns
  when the tier set is exactly `{"general-web"}`, so an unknown or empty value
  short-circuits to "fine". `scripture: true` does not require
  `source_tier: primary-text` (AC-9 pairs them).
- **Literature locator.** `locator: ""` plus a bogus `reference:` field
  passes; only the one-to-one link count is checked (`lint_links.py:110-119`).
- **`updated` is ISO-8601 (FR-3).** `updated: "last tuesday"` builds a
  manifest with exit 0; the value is copied verbatim.

### 1.6 FR-28 step 4 "freshness checks" are instructed nowhere

Neither prompt, `agents/note-maintainer.md`, nor `agents/orchestrator.md`
asks for re-verification or ageing of existing notes. A grep for
`freshness|re-verify|stale note` across `scripts/*.md agents/ references/
skills/` returns nothing. "Gap analysis vs config topics" is instructed, but
in step 3 (`maintenance_prompt.md:24`, `remote_maintenance_prompt.md:41`),
not step 4. Step 11 (update log + INBOX statuses, release lock) is folded
into step 10 on both paths with no step-11 stamp, while A3 says the
observable step order is unchanged.

The remote prompt's step 5 (`remote_maintenance_prompt.md:50-54`) also drops
the "critic reviews → accepted links written into BOTH notes → rejections
logged" clause that the laptop prompt carries (`maintenance_prompt.md:38`);
on the remote path that behaviour rests on `agents/critic.md:33-37` alone.

### 1.7 FR-35 "exactly one proposal per cycle" is prose-only

`skill-smith.md:20,46` and both prompts say it, and `tests/test_agents.py:152-158`
checks the wording. No code enforces it: `skill_review.py propose` accepts a
second proposal in the same cycle, `lint_skills.py` does not count
`status: proposed` directories, and `maintenance_run.sh:182-183` simply
`head -1`s the first new proposal for the trial.

### 1.8 NFR-2 log stamps are incomplete

- Neither path stamps "agents dispatched" structurally; it happens only if
  the orchestrator obeys `orchestrator.md:25`. `AGENTS_JSON` is built at
  `maintenance_run.sh:120` and never written to `log.md`.
- The remote path writes no commit SHA and no `mode=` token to `log.md`. The
  SHA goes to stdout only (`remote_cycle.sh:313`), because the finish line
  must precede the commit (`:293-295`).
- The laptop push-retry loop (`maintenance_run.sh:223-237`) re-runs only
  `lint_citations` and `lint_links` after a re-pull, not `build_manifest
  --check`, `lint_skills`, or the sandbox check the pre-push gate ran. A
  merge that desyncs the manifest can be pushed on retry.

### 1.9 §7 script contract: three entry points never append to `log.md`

`new_worktree.sh`, `inquiries.py`, and `skill_review.py list` take `--repo`
and write nothing to `log.md`. Reasonable for read-only tools, but the §7
preamble and `.claude/CLAUDE.md:126-127` state the rule without exceptions.
Usage-error exit codes are also inconsistent across the shell scripts:
`adhoc_research.sh` exits 2, the other four exit 1; Python scripts uniformly
exit 2.

### 1.10 Smaller items

- `verify_refs.py` fetches arXiv through `_raw` (`:148-153`), which swallows
  `NetworkUnavailable`, so a dead network on an arXiv-only reference reads as
  a miss rather than a degradation; the Crossref/PubMed/ISBN paths degrade
  correctly (`:185-192`).
- `verify_refs.py main` catches `FrontmatterError` and returns 0 after
  aborting the loop (`:249-251`): one unparseable reference note stops
  verification of every later note, silently.
- `build_refs` (`build_manifest.py:134`) silently drops a CSL item lacking
  `id`; AC-7 holds only because `lint_citations` separately flags
  `malformed-csl`.
- The content-repo `.gitignore` written by genesis (`init_content_repo.sh:156-165`)
  omits `*.pem`, `.netrc`, and cache directories that NFR-4 lists and the
  skill repo's own `.gitignore` covers.
- Genesis never installs `ci/content-repo-gates.yml`; it is a manual copy
  (`references/remote-execution.md:138-139`), and PLAN.md:294-300 records the
  live copy as stale, so the Phase-4 rails are currently not enforced
  server-side.

---

## 2. Implementation choices the spec does not record (amendment candidates)

Each is defensible and most are documented in a code comment or reference
doc, but none appears in the amendments list, which `.claude/CLAUDE.md` names
as the place deviations live.

1. **Routines are the de-facto primary entrypoint.** §10 says "Cloud Routines
   execution (documented as an option; not the default entrypoint)"; A5
   legitimises the remote model but does not revise §10. `PLAN.md:248` says
   "the Routine is the primary driver", `PLAN.md:285-293` makes it the
   critical path, and `PLAN.md:378` still lists cloud Routines as out of
   scope. `references/scheduling.md:65-68` says the path is "deferred (spec
   §10)" while `:46-55` of the same file says to prefer it.
2. **AC-8 is softened.** When the note's recorded `citation_renderer` is not
   installed locally the lint warns and skips the re-render comparison
   (`lint_citations.py:113-116`), and `_norm` (`:183-187`) ignores
   whitespace, quote glyphs, and trailing periods. AC-8 says "hard-fails on
   mismatch". Documented in `references/citation-rules.md:41-46`, not in A1.
3. **`archived` inquiries need no `result_notes`.** FR-6 prose says every
   stage carries backlinks; AC-6 names only `answered`. `lint_links.py:174`
   and `tests/test_inquiries.py:80-84` codify archived-with-empty as legal.
   A6 says "implemented as specified" and states only the `answered` rule.
4. **The "sourced claim" heuristic.** FR-11 never defines it; the lint uses
   a regex of attribution verbs, `per <Capitalised>`, or any quote character
   (`lint_citations.py:44-48`). Probe: `The system reports errors` and
   `She writes code` count as sourced claims. Documented in
   `references/note-types.md:49-52` with its false positives.
5. **General-web sourcing warns, never blocks** (`weak-sourcing`,
   `lint_citations.py:157-180`). QA-3 says only "record", so this is
   consistent, but the rule appears in no reference doc's gate table.
6. **`fetch_remote.py` has no `--token` flag.** FR-23 and PLAN.md:95 say
   `[--token]`; the token is env-only (`GITHUB_TOKEN`/`GH_TOKEN`,
   `fetch_remote.py:33-34`), a stricter NFR-4 reading.
7. **Connector is cheap-tier only.** FR-29 says "cheap for embeddings +
   strong for justification". The strong-tier justification is in practice
   delegated to the critic (`connector.md:36-37`, `critic.md:33-37`), but no
   doc says that is why the connector has one tier.
8. **FR-37 on the remote path is structural, not intercepted.** Nothing
   blocks a remote session writing to `/opt/zettel-skill`; CI checks out a
   fresh plugin (`ci/content-repo-gates.yml:37-42`) so tampering cannot reach
   the gate, and the `--strict` smith-scoped sandbox check is run by the
   session itself per prompt step 7, while CI runs the non-strict check
   (`gates.yml:77-81`). A7 acknowledges the granularity limit but not the
   session-enforced strict check. "Per-run budget caps" for the smith exist
   only at whole-run granularity on the laptop path and not at all remotely.
9. **`content_repo.branch`** is an undocumented optional config key
   (`build_manifest.py:31`).
10. **`ZETTEL_SKILL_REF` pins indirectly.** Docs say `refresh-skill`
    fast-forwards "to its configured ref"; `remote_cycle.sh` never reads the
    variable. It fetches `origin <current branch name>` (`:69-94`), which
    pins only because `ci/setup-environment.sh:30` creates a local branch
    named after the ref.
11. **FR-13 tree.** Three references (`serendipity.md`, `remote-execution.md`,
    `capture.md`), eight scripts, `ci/`, `docs/`, `tests/`, `.github/`, and
    `zettel_lib/` exist beyond the FR-13 listing. PLAN.md §1 is accurate;
    the spec tree was never amended past A1.

---

## 3. Documentation drift (docs say something the code does not)

| # | Where | Says | Actually |
|---|---|---|---|
| 1 | `references/architecture.md:7` | skill repo "Always private" | Both public since A4 (`REQUIREMENTS.md:63-70`, `README.md:18-20`) |
| 2 | `skills/zettel-bootstrap/SKILL.md:156-164`, `references/architecture.md:58,63-68`, `PLAN.md:122,348` | "Run all four" gates; `lint_skills.py` absent | README lists five; the wrapper runs `build_manifest --check` + three lints + sandbox (`maintenance_run.sh:198-199`); CI runs six steps. `references/quality-gates.md:25-26` is the one doc that is right |
| 3 | `references/orchestra.md:70-72`, `references/scheduling.md:77-78` | wrapper re-runs manifest check, `lint_citations`, `lint_links` | also `lint_skills.py` and `check_skill_sandbox.py` |
| 4 | `.claude/CLAUDE.md:3-5` | setup "symlinks only `skills/`" | also links `agents/*.md` (`ci/setup-environment.sh:49-50`; CLAUDE.md:100-101 says so) |
| 5 | `references/remote-execution.md:28`, `README.md:167`, A5 text (`REQUIREMENTS.md:78`) | lock is `refs/zettel/run-lock` / "git-ref lock" | `LOCK.json` on branch `zettel/lock` (`gitlock.py:25-26`); prose at `remote-execution.md:33-45` is correct |
| 6 | `PLAN.md:16` | SKILL.md "currently 286" lines | 291 |
| 7 | `PLAN.md:77` | `requirements.txt` = citeproc-py, requests, pyyaml; networkx/python-louvain optional | networkx is required, `pypandoc-binary` is the primary renderer, `python-louvain` appears nowhere (Louvain is `networkx.algorithms.community.louvain_communities`, `serendipity_sweep.py:120-127`) |
| 8 | `PLAN.md:103` (Phase 3) | embeddings default, python-louvain, "relation + one-line justification", "LLM-only degradation" | lexical TF-IDF default with embeddings opt-in (`templates/config.yml:22-24`), neutral `shared-concept` with no justification by design (`serendipity_sweep.py:35,186`), degradation to lexical. `references/serendipity.md` is accurate |
| 9 | `PLAN.md:93` | maintenance prompt encodes "commit+push with re-pull/re-lint retry" | prompt forbids push (`maintenance_prompt.md:78-79`); retry lives in the wrapper (A3) |
| 10 | `PLAN.md:32,112`, `remote_cycle.sh:10-14` header comment | subcommands `start|finish|abort|status` | also `refresh-skill` (`remote_cycle.sh:32,96-99`) |
| 11 | `PLAN.md:84` | all agents carry `web_search` + `web_fetch` | see §1.3 |
| 12 | `README.md:238`, `.claude/CLAUDE.md:117` | "thirteen entry points" | 12 `.py` + 5 `.sh` = 17 under `scripts/` |
| 13 | `references/capture.md:103-104` | "the third rule is why answers must be permanent" | that is the second rule, `result-note-type` (`lint_links.py:169-172`); the third is `unresolved-result-note` |
| 14 | `README.md:261-274` | "Two acceptance checks cannot run…" | three bullets follow, the third separated by an unrelated paragraph |
| 15 | `scripts/init_content_repo.sh:171` | content-repo README link text `zettel-bootstrap` | URL is `https://github.com/${OWNER}` (the content-repo owner's profile) |
| 16 | `.claude/CLAUDE.md:126-127` | every script takes `--repo`, answers `--help`, appends to `log.md` | `fetch_remote.py`'s `--repo` is a GitHub repo name and it never logs; `remote_cycle.sh refresh-skill` takes no `--repo` |
| 17 | `ci/content-repo-gates.yml:21-23` | comment says to pin `ZETTEL_SKILL_REF` deliberately | value is `main`, unpinned |

Behaviour that exists in code and is documented nowhere in README, SKILL.md,
or `references/`:

- Lint rules `weak-sourcing`, `atomicity`, `one-to-one`, `layering`,
  `missing-key`, `malformed-key`, `slug-key-mismatch`, `id-key-mismatch`
  (only `lint_citations` rule names are tabulated in `citation-rules.md`).
- Flags: `verify_refs.py --no-render` (used by CI), `serendipity_sweep.py
  --force-lexical`, `skill_trial.py --questions/--model/--max-turns/--out/--seed`,
  `skill_review.py list --json` and `propose --base`, `new_worktree.sh
  --remove`, `init_content_repo.sh --max-turns`.
- Environment variables: `ZETTEL_RUN_HOLDER`, `ZETTEL_SESSION_ID`,
  `CLAUDE_SESSION_ID` (`remote_cycle.sh:107-108`), `ZETTEL_INSTALL_DIR`,
  `ZETTEL_SKILL_REPO` (`ci/setup-environment.sh:20-22`), `PYTHON`.

---

## 4. Test-coverage notes

Not spec gaps, but places where a rule exists and no test pins it:

- `slug-key-mismatch`, `id-key-mismatch`, `malformed-key` have no dedicated
  test (only `filename-key-mismatch`, `tests/test_lints.py:153`).
- `test_manifest_entries_carry_every_required_field` (`tests/test_manifest.py:26-27`)
  does not assert `slug`, though it is emitted.
- `lint_skills.py:140` skips the Patterns-Addressed citation check when the
  section is empty, and checks note keys only, never that a trace or log
  entry is cited (FR-34 asks for "patterns/traces").

---

## 5. What was verified as compliant

So a reader does not re-check them: FR-1/AC-1 tree and `run.lock` ignore;
FR-3 manifest fields, `id_to_key`, `inquiries`, byte-idempotence, and
public/private URL emission; FR-5 taxonomy, resolution, key/slug/id agreement,
`duplicate-id`, no folgezettel; FR-6 status vocabulary and the AC-6 rules;
FR-7 `refs.json` aggregation and `--check` currency; FR-8 pandoc-primary
rendering with citeproc fallback and a bundled style; FR-9 scripture
exclusion from `refs.json`; FR-10/FR-22 Crossref `mailto` + 429 backoff,
arXiv, PubMed, Open Library, Google Books, `--offline`, graceful degradation;
FR-11/FR-12 rules and the `FILE\tRULE\tREASON` contract; FR-14/FR-15
frontmatter and `plugin.json`; FR-18 args, `gh repo create` command, clobber
refusal; FR-19–FR-21, FR-24, FR-26 CLI shapes; FR-25 flags, redirection,
lock, exit mirroring, no push on cutoff; FR-29 tier resolution on both paths
with no hardcoded model IDs; FR-30 lock semantics and gitlock release
reasons; FR-31 five Mode-B paths and the private-repo MCP rule; FR-32
crontab line, desktop/Cowork equivalent, and the `~/.claude/skills/` caveat;
FR-33/FR-36 reject-restores-skill-layer-only with knowledge notes untouched
(tested); FR-34 proposer inputs in `skill-smith.md`; AC-34 PURPOSE sections
enforced by `lint_skills.py`; FR-37 plugin-tree snapshot on the laptop path
(tested); QA-1 thresholds and QA-4 INBOX authority in every relevant file;
§12 item 4 has a planted-violation fixture for each named violation.
