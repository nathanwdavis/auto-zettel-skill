# Requirements Document — Anthropic Agent Skill: `zettel-bootstrap`

**Document type:** Implementation brief / full specification for Claude Code
**Target executor:** Claude Code (will implement and commit to a private GitHub “skill repo”)
**Status:** Complete spec (may be built in phases; all phases specified)
**Date:** 2026-08-30

-----

## Amendments (applied during implementation)

Recorded here rather than silently editing the prose above. The first two were
forced by facts checked against upstream at build time, exactly as the Caveats
section anticipates; the rest by implementation and by live runs. A9 is the
record of a full spec-compliance review.

### A1 — CSL style filename (2026-08-30, FR-8, FR-13)

The spec names `chicago-fullnote-bibliography.csl`. Upstream renamed the style;
that filename now 404s in the citation-style-language/styles repository, while
`chicago-notes-bibliography.csl` resolves and carries the title "Chicago Manual
of Style 18th edition (notes and bibliography)" — the style FR-8 describes. The
file is bundled under the current upstream name at
`scripts/csl/chicago-notes-bibliography.csl`, with provenance and its CC BY-SA
3.0 attribution in `scripts/csl/README.md`.

**Related:** FR-8 names `citeproc-py` as the primary renderer with a pandoc
fallback, and provides for switching "if `citeproc-py` cannot render valid
Chicago fullnote strings on the real fixtures". It cannot: the style overrides a
global `initialize-with` with 173 `<name initialize="false">` elements, which
citeproc-py ignores, rendering "L. Tang" where Chicago requires "Liyan Tang".
**Pandoc is therefore the primary backend and citeproc-py the fallback.**
`pypandoc-binary` ships a pandoc build so this needs no system install. See
`references/citation-rules.md`.

### A2 — Note filenames use the title-slug key (2026-08-30, FR-3, FR-5)

FR-5 specifies the bare timestamp ID as the filename stem. At the repository
owner's direction, filenames and links instead use the **note key**
`<title-slug>--<timestamp-id>`, e.g.
`atomic-notes-compound-over-time--202608301412.md`, so a vault listing reads as
titles rather than timestamps.

FR-5's substance is preserved: the timestamp `id` remains the immutable
identity, there is still no folgezettel, and the relation taxonomy is unchanged.
The slug is **frozen at creation**, so rewording a note's `title` never moves a
file or breaks a link. Frontmatter carries `id`, `slug`, `key`, and
`aliases: [<id>]`; body links use `[[key]]`; frontmatter `target_id` holds the
key; and `manifest.json` gains an `id_to_key` map so a bare timestamp still
resolves. `lint_links.py` fails any note whose filename stem, `key`, `slug`,
and `id` disagree.

### A3 — Push authority lives in the wrapper (2026-08-30, FR-25, FR-28)

FR-28 step 10 has the headless run itself commit **and push**. At the
repository owner's direction, pushing moves to `maintenance_run.sh`: the
headless run performs steps 1–9 and commits, then the wrapper independently
re-runs `build_manifest.py --check`, `lint_citations.py`, and `lint_links.py`
and pushes only when all pass (retaining FR-28's re-pull/re-lint retry loop).
This turns G3/NFR-3's "no unlinted push" from a prompted behaviour into a
structural guarantee — a runaway, turn-capped, or budget-cut run cannot push.
Observable step order in `log.md` (AC-28) is unchanged.

### A4 — Both repositories are public (2026-08-31, §3.3, FR-13)

The spec fixes the skill repo as "Always private". At the repository owner's
direction both the skill repo and the content repo are **public**. A secret
scan of every tracked file found no credentials (auth flows through `gh`, the
SSH agent, or environment variables per NFR-4). Consequences are simplifying:
cloud environment setup scripts clone the skill repo with no token, and Mode B
reads the content repo through anonymous raw URLs with no connector.

### A5 — Remote execution model (2026-08-31, FR-25, FR-28, FR-30, FR-32)

Scheduled maintenance may run as Routine-fired remote Claude Code sessions with
no laptop involved. In that mode, three mechanisms change shape:

- **`run.lock` → git ref.** A filesystem lock cannot serialize ephemeral
  containers; `refs/zettel/run-lock` provides the same mutual exclusion through
  git's atomic ref updates (`zettel_lib/gitlock.py`). FR-30's semantics are
  preserved: a run finding a fresh lock stands down; only provably stale locks
  are broken.
- **Wrapper-enforced gates → CI required status check.** The session is the
  agent and can only offer a branch (`remote_cycle.sh`); a GitHub Actions
  workflow (`ci/content-repo-gates.yml`) re-runs the lints server-side and a
  required check decides what merges. This strengthens A3's guarantee — no
  session can bypass it.
- **`--max-budget-usd` has no equivalent** for a fired session. Cost is bounded
  by cadence, prompt scope, and model tier instead; the laptop path retains the
  hard cap.

The laptop path (FR-25/FR-32 as written) remains fully supported.

### A6 — Human capture and ad-hoc research (2026-08-31, FR-6, §7)

The spec describes every input as machine-authored, and the gates were built on
that assumption: `build_manifest.py` raises on a note without exact
frontmatter. That made casual human capture -- what a zettelkasten actually
lives on -- the riskiest act in the system, since a hand-written file in
`fleeting/` fails the *next scheduled run's* manifest build rather than the
author's own.

Three additions close it without loosening any gate:

- **`scripts/capture.py`** is the supported authoring path for humans and for
  ad-hoc sessions: it generates fleeting notes, inquiries, and INBOX entries
  that already satisfy every gate. Because note IDs are minute-resolution and
  the manifest's `id_to_key` map is many-to-one, it also allocates around IDs
  already in use; `lint_links.py` gains a `duplicate-id` rule to cover notes it
  did not write. (Two notes sharing an ID previously made bare-ID links resolve
  to whichever was indexed last, silently.)
- **FR-6 is implemented as specified.** `templates/inquiry.md` fixes the
  schema, `build_manifest.py` indexes inquiries in a top-level `inquiries`
  block, `scripts/inquiries.py` reports open questions, and `lint_links.py`
  enforces AC-6 -- an `answered` inquiry must carry at least one `result_notes`
  entry resolving to a **permanent** note. Inquiries sit outside `NOTE_DIRS`:
  a question is not a node in the graph and is never a link target.
- **`scripts/adhoc_research.sh`** gives "answer this now" the same guarantees
  as a scheduled cycle -- same lock (standing down on exit 3 rather than
  stealing a live one), same run branch, same required-check handoff. There is
  deliberately no ad-hoc path to `main`, because a fast path to `main` is a
  path around the citation gates.

### A7 — Skill emergence, as implementable (2026-08-31, FR-36, FR-37, AC-36, AC-37)

Phase 4 forced five refinements of §9.4; the requirements' intent is
unchanged, but each needed a mechanical shape the prose does not fix:

- **skill-impact.md append-only is semantic, not byte-prefix.** The genesis
  scaffold puts the summary table above the detail sections, so a new row
  lands mid-file. The enforceable invariant is "every existing record
  survives byte-identical; only additions are allowed", checked by
  `zettel_lib/impact.py` and gated by `check_skill_sandbox.py`
  (`log.md` remains byte-prefix append-only).
- **The FR-36 unified diff is captured at proposal time**, by
  `skill_review.py propose` as the smith's final act, when the diff against
  the cycle base is cheap and unambiguous. Reconstructing it at decision
  time would be neither.
- **"Not re-proposed" is mechanical at name level, for creates.** A rejected
  create's name is permanently banned (`re-proposed-skill` lint rule). A
  rejected *patch* is permanent history the smith must read (FR-34), but a
  later different patch to the same skill stays legal — otherwise one bad
  tweak freezes a skill forever. Recurrence in patches is the human
  reviewer's call.
- **AC-37 enforcement is layered by diff granularity.** A `claude` session's
  writes cannot be intercepted in-process, so: the Mode-A wrapper snapshots
  the plugin tree around the headless run (any change aborts, unpushed); the
  cycle-wide diff gate enforces the append-only/raw invariants in the
  wrapper and in CI; and a `--strict` check on the smith's isolated diff
  confines it to `skills/` plus the two ledgers before its work merges. At
  whole-cycle granularity a smith note-edit is indistinguishable from
  note-maintainer work — the strict smith-scoped check is where that rail
  actually binds, with critic/lints/PR review as residual backstop.
- **The A/B trial auto-runs in the proposing cycle** (owner's direction:
  the human gate must not also be a scheduling bottleneck), with cost pinned:
  at most one trial per proposal cycle, `trial_questions` (default 3)
  questions × 3 cheap-tier read-only calls — two answer arms in throwaway
  tree copies (the without-copy simply lacks the candidate) plus ONE paired
  judge call, order-randomized. Promotion itself remains a human act; FR-36
  is unchanged. Remote budget caps remain as A5 states.

### A8 — Field fixes from the first live remote session (2026-08-31, FR-10, FR-22, FR-25, FR-28, FR-29, NFR-2; issue #7)

The first real end-to-end session against a live content repo surfaced ten
findings (issue #7). Five change spec-adjacent behavior:

- **Skill currency (P0).** A5's cached environment install froze the skill at
  cache time — found 12 commits stale, silently, while a presence-style check
  passed. The cache is now the *bootstrap*; `remote_cycle.sh refresh-skill`
  (fast-forward-only, always exit 0, run by the remote prompt before every
  cycle) is the *currency mechanism*, and `start`/`finish` log the installed
  skill revision so every cycle records which code produced it.
  `ZETTEL_SKILL_REF` still pins deliberately.
- **Agent availability (FR-29).** The remote path had none of the eight named
  agents (only `skills/` was linked; the `--agents` mechanism is
  laptop-only), so "delegate to the `critic`" could silently skip the QA-1
  gate. Setup now registers `agents/*.md` in `~/.claude/agents`, and both
  maintenance prompts carry the explicit fallback: adopt the missing agent's
  role from its definition, logged as self-review. **The critic gate is the
  session's own responsibility; delegation is an optimization, never a
  precondition.**
- **Stand-down legibility (FR-30/NFR-2).** A failed `start` and a healthy
  no-op cycle were indistinguishable from the repo, because a no-op pushes
  nothing by design. `gitlock.release()` now records a reason in the release
  commit on the pushed lock branch (`start-failed`, `empty-cycle`,
  `already-merged`, `finished <branch>`, `abort`, `stale-broken`).
- **Verification semantics (FR-10/FR-22).** `verify_refs.py` writes a note
  only when its verification state or rendered strings changed
  (`verification.date` = when the state was established; `updated` = last
  authored edit), and when a capture and an identifier are both present it
  checks both: hit → `method: raw-capture+<registry>`; definitive miss →
  still verified on the capture, plus `identifier_check: failed` and a
  warning. The either/or of FR-10 is unchanged; "verified" just means the
  stronger thing when the stronger check is possible.
- **Default-branch resolution.** `refs/remotes/origin/HEAD` cannot be assumed
  (remote-session clones lack it, and under pipefail the old probe killed
  every scheduled run); the default branch is asked of the remote, with
  `main` as last resort, in both `start` and `finish`.

### A9 — Spec-compliance review (2026-09-02, FR-1, FR-2, FR-6, FR-8, FR-11, FR-13, FR-16, FR-23, FR-27, FR-28, FR-29, FR-35, FR-37, §7, §10, NFR-2, QA-3)

A pass over this document against the code (`docs/SPEC_COMPLIANCE_REVIEW.md`)
found gaps of three kinds. The functionality gaps were closed in code (config
validation on the remote path, the FR-4 lint rules the templates only stated,
a marketplace manifest, FR-16's tool sets, FR-35's one-proposal rule, the
FR-27 next-steps, freshness checks in FR-28 step 4). What follows records
the implementation choices that were defensible but unamended, so the spec
and the code agree again:

- **FR-1:** genesis also writes `.github/workflows/gates.yml` (a copy of
  `ci/content-repo-gates.yml`). A5 made a CI required check the merge
  authority for remote sessions, and a workflow that had to be copied by
  hand went stale on the first live content repo.
- **§10 and FR-32:** Routine-fired remote sessions (A5) are the *primary*
  scheduled entrypoint, not a deferred option; laptop cron and desktop tasks
  remain fully supported and are the only path with a hard per-run dollar
  cap.
- **AC-8:** `lint_citations.py` re-renders with the backend the note recorded
  (`citation_renderer`); when that backend is not installed locally it warns
  and skips the comparison rather than failing on a spurious cross-backend
  mismatch, and it compares after whitespace, quote-glyph, and trailing-period
  normalisation. Both are consequences of A1's two-backend world.
- **FR-6:** only `answered` requires `result_notes`; `archived` may carry
  none, so a question can be closed as no longer worth answering.
- **FR-11 / QA-3:** a "sourced claim" is what the `SOURCED_CLAIM` heuristic
  matches (attribution verbs, `per <Name>`, quotation marks); its known
  false positives are documented in `references/note-types.md`. A permanent
  note grounded only in `general-web` sources warns (`weak-sourcing`) and
  never blocks — QA-3 asks that the tier be recorded, and open-web leads are
  how research starts.
- **FR-23:** `fetch_remote.py` has no `--token` flag. The token is env-only
  (`GITHUB_TOKEN`/`GH_TOKEN`), which is NFR-4 read strictly.
- **FR-27 steps 4–5:** the first orchestra pass is instructed by SKILL.md's
  Genesis section, not dispatched by `init_content_repo.sh`; the script does
  print the scheduling next-steps.
- **FR-28 step 11:** folded into step 10 — INBOX and inquiry statuses are
  updated *before* the commit so they are committed, and the lock is released
  by the wrapper (Mode A) or `finish` (remote). There is no separate step-11
  stamp in `log.md`; A3's claim that the observable order is unchanged
  should be read with that fold.
- **NFR-2 (remote):** the commit SHA cannot appear in `log.md` because the
  `finish` line must precede the commit it describes; it goes to stdout and
  the PR. `agents dispatched` is the set of definitions handed to the run
  (Mode A) or materialized for it (remote), stamped on the start line.
- **FR-29:** the connector is cheap-tier only. The strong-tier "justification"
  the spec assigns to it is the critic's review of `proposed-links/`.
- **FR-37 (remote):** nothing intercepts a remote session's writes; the rail
  is structural — CI checks out a fresh plugin, so a tampered install cannot
  reach the gate — and the `--strict` smith-scoped sandbox check is run by
  the session itself in step 7. Per-run budget caps for the smith exist only
  at whole-run granularity on the laptop path (A5).
- **§7 preamble:** read-only tools (`inquiries.py`, `skill_review.py list`,
  `new_worktree.sh`, `fetch_remote.py`) do not append to `log.md`; a query
  is not an operation.
- **FR-2:** `autonomy_level` is required and reserved; no code path reads it
  yet. `content_repo.branch` is an optional key (default `main`).
- **A5/A8 mechanics:** the lock is `LOCK.json` on branch `zettel/lock`, not
  `refs/zettel/run-lock` (the git proxy permits only ordinary branches).
  `ZETTEL_SKILL_REF` pins by naming the local branch at install time;
  `refresh-skill` fast-forwards whatever branch is checked out.
- **FR-13:** the tree gained `references/{serendipity,remote-execution,capture}.md`,
  `scripts/{capture,inquiries,lint_skills,check_skill_sandbox,skill_review,skill_trial}.py`,
  `scripts/{adhoc_research,remote_cycle}.sh`, the two prompt templates,
  `scripts/zettel_lib/`, `ci/`, `docs/`, `tests/`, and
  `.claude-plugin/marketplace.json`.
- **FR-35:** now mechanical — `skill_review.py propose` refuses a second
  proposal in the cycle `log.md` shows open (`second-proposal`).

### A10 — Knowledge query mode (2026-09-02, FR-13, §7, §10)

The spec describes growing and gating a content repo, never *reading it
back*: a user asking "what does the base already have on X" had no entry
point, and a session would reach for the researcher, turning a question into
a run. `scripts/query.py` (with `references/query.md` and a SKILL.md section)
fills that: it ranks notes against a free-text query, reports coverage by
note type with sources and verification state, lists touching inquiries and
one-hop neighbours, and names gaps. It is strictly read-only — no note, no
inquiry, no `log.md` line (the §7 read-only exception A9 records) — and
prints, never runs, one `capture.py` follow-up per gap. `--file-gaps` is the
explicit opt-in that captures them (an operation, logged as one), so a
person reading the report in a remote session can say "file those". Mode A
only; Mode B degrades to manifest metadata by hand.

-----

## TL;DR

- Build `zettel-bootstrap`, a topic-agnostic “seed DNA” Claude Code skill that scaffolds and then perpetually grows a citation-grounded, Zettelkasten-style knowledge repository on GitHub using an orchestra of parallel Claude subagents, scheduled headless runs, and a quality-gated skill-emergence loop adapted from WikiSkill (Liyan Tang, Cyrus Rashtchian, Chun-Sung Ferng, Andrew Tomkins, Da-Cheng Juan, and Tu Vu, “WikiSkill: Compiling Agent Experience into Persistent Knowledge for Skill Evolution,” arXiv:2608.27454, submitted 27 Aug 2026).
- Two repos: a PRIVATE skill repo containing ONLY the bootstrap skill (this is what Claude Code builds), and a SEPARATE content repo that the skill’s init script creates at genesis (public or private, chosen at runtime).
- Package as a Claude Code plugin (`.claude-plugin/plugin.json`) bundling the SKILL.md, subagents, scripts, references, and templates; the persistent knowledge layer is never rolled back while emergent child skills are gated and rollbackable.

-----

## 1. Overview & Goals

### 1.1 Purpose

`zettel-bootstrap` is a self-perpetuating knowledge-cultivation skill. Given a topic, question, or research path supplied at runtime, it (a) scaffolds a Zettelkasten-style content repository on GitHub, (b) grows it over time via scheduled headless Claude Code runs that dispatch an orchestra of subagents, (c) enforces citation-grounding and anti-hallucination gates on every note, and (d) authors its own child skills (domain- and workflow-oriented) that are quality-gated before adoption.

### 1.2 Design lineage

The skill-emergence subsystem adapts the WikiSkill pattern (arXiv:2608.27454, Tang et al., Google Research & Virginia Tech). WikiSkill’s core architecture, quoted verbatim (§3.1): *“WikiSkill organizes an agent’s workspace into three layers: a Raw Layer that stores immutable execution traces, a Wiki Layer that maintains structured knowledge, and a Skill Layer that contains evolving procedural knowledge.”* Key adopted invariant: **the knowledge (wiki) layer is never rolled back; skills are gated and reverted on regression** (in the paper, *“the wiki W_k is never rolled back regardless of the acceptance decision”*). WikiSkill’s original acceptance rule requires each proposal to improve a validation score against ground truth (a limitation the authors note: *“our validation gating requires each accepted proposal to improve the validation score, which excludes neutral proposals”*). Because this project runs in an open-world setting with **no ground-truth labels**, that score-based gate is replaced by human approval + A/B comparison on inbox questions using groundedness, citation-coverage, and critic scores.

### 1.3 Goals (measurable)

- G1: A single genesis run produces a working content repo with valid substrate and a first commit.
- G2: Every reference note is verified (raw capture on disk OR authoritative metadata lookup); lints hard-fail otherwise.
- G3: Scheduled maintenance runs are idempotent, serialized, and leave the content repo in a lint-clean committed state or abort without pushing.
- G4: Child skills never touch the skill repo, are sandboxed in the content repo, and require human promotion.

### 1.4 Non-goals

See §10.

-----

## 2. Definitions

- **Skill repo:** The PRIVATE GitHub repository Claude Code builds and commits to. Contains ONLY the `zettel-bootstrap` skill/plugin. Never contains zettelkasten content.
- **Content repo:** A SEPARATE repository the skill’s `init_content_repo.sh` creates at genesis. Holds all knowledge notes. Visibility (public/private) chosen at runtime.
- **Genesis run:** The first execution; prompts the user for topic(s), content-repo name/visibility, cadence, budget; scaffolds and pushes the content repo.
- **Maintenance run:** Any subsequent scheduled/headless run that grows and repairs the content repo.
- **Note types:** fleeting, literature, permanent, reference, structure/MOC (defined §4.2).
- **1-1-1 rule:** One permanent note = one atomic idea = one source-of-truth claim, with ≥1 outbound typed link; each literature note summarizes exactly one source and links to exactly one reference note.
- **Mode A (local-clone):** Run has a local filesystem; clones/pulls the content repo, works in git worktrees, commits/pushes.
- **Mode B (remote-walk):** Run has no local filesystem (e.g., claude.ai); reads the content repo by fetching raw URLs or via GitHub MCP.
- **Orchestra:** The set of Claude Code subagents (Orchestrator, Researcher, Synthesizer, Critic, Librarian, Connector, Note-Maintainer, Skill-smith).
- **Skill-smith:** The subagent implementing the WikiSkill-style skill proposer.

-----

## 3. Repo Topology

### 3.1 Skill repo (what Claude Code builds — PRIVATE)

Packaged as a Claude Code plugin. Full file layout in §6.

### 3.2 Content repo (created at genesis by the skill)

Full substrate layout in §4.1.

### 3.3 Private/public matrix

|Dimension         |Skill repo                           |Content repo (public)                                        |Content repo (private)                                                          |
|------------------|-------------------------------------|-------------------------------------------------------------|--------------------------------------------------------------------------------|
|Visibility        |Always private                       |Public                                                       |Private                                                                         |
|Contains notes?   |No                                   |Yes                                                          |Yes                                                                             |
|Mode A access     |git clone/pull over SSH/HTTPS w/ auth|same                                                         |same                                                                            |
|Mode B access     |N/A (skill installed locally/plugin) |`web_fetch` of `raw.githubusercontent.com` URLs OR GitHub MCP|**GitHub MCP/connector with auth REQUIRED** (raw URLs not anonymously fetchable)|
|manifest URL field|N/A                                  |full `raw.githubusercontent.com` URLs                        |repo-relative paths + GitHub API `contents` paths                               |

**FR-topology acceptance:** build_manifest.py MUST emit full raw URLs only when the content repo is public; for private content repos it MUST emit repo-relative paths plus GitHub API content paths and MUST NOT emit anonymous raw URLs.

-----

## 4. Functional Requirements — Substrate

### 4.1 Content-repo layout (scaffolded by init script)

**FR-1.** `init_content_repo.sh` MUST scaffold exactly this tree and commit it:

```
/INBOX.md            # user inquiries/feedback; read FIRST every run
/INDEX.md            # root MOC; remote-walk entry point; links ONLY to MOCs
/manifest.json       # machine-readable note index (see FR-3)
/config.yml          # topics, cadence, budget, autonomy, embedding, model mix
/inquiries/          # optional per-inquiry files (lifecycle FR-6)
/fleeting/  /literature/  /permanent/  /reference/  /moc/
/raw/                # source captures (verbatim fetched content)
/skills/             # self-authored child skills (each: SKILL.md + PURPOSE.md)
/proposed-links/     # connector queue
/skill-impact.md     # adoption tracker incl. rejected proposals + reasons
/.bib/refs.json      # aggregated CSL-JSON
/log.md              # append-only operation log
/.gitignore
/README.md           # explains the content repo, generated
```

**AC-1:** After genesis, `git ls-files` in the content repo lists every path above; `run.lock` is documented (FR-30) but not committed as a tracked artifact.

**FR-2 (config.yml).** MUST contain at minimum: `topics: []`, `cadence` (cron-like or human string), `budget` (per-run USD cap + max-turns), `autonomy_level`, `content_repo: {name, owner, visibility}`, `embedding: {enabled, model}`, `models: {strong, cheap}`, `connector_cadence`, `skill_smith_cadence`. **AC-2:** genesis writes all keys; maintenance reads them; missing required keys hard-fail with a clear message.

**FR-3 (manifest.json).** **[Amended A2: entries also carry `key` and `slug`, and the manifest carries a top-level `id_to_key` map.]** Each note entry MUST include: `id`, `type`, `title`, `tags[]`, `links[]` (each `{target_id, relation}`), `path`, `url_or_apipath`, `updated` (ISO-8601). **AC-3:** `build_manifest.py` regenerates deterministically from note frontmatter; running it twice with no note changes produces a byte-identical file (idempotent).

### 4.2 Note types & rules

**FR-4.** Note-type rules enforced by lints:

- **fleeting:** short-lived capture; swept each cycle by Note-Maintainer.
- **literature:** own-words summary of exactly ONE source with locator; links to exactly one reference note.
- **permanent:** ONE atomic idea; title-as-claim; ≥1 outbound typed link; any sourced claim links to a verified reference note; 1-1-1 enforced.
- **reference:** exactly one per source; CSL-JSON frontmatter + `chicago_note` + `chicago_bib` strings + `source_tier` + `verification` block `{method, source, verified(bool), date}` + `raw_capture` path.
- **structure/MOC:** INDEX links only to MOCs; MOCs link to notes.

**FR-5 (IDs & links).** Timestamp-based immutable IDs (e.g., `202608301412`) used as filename stem AND frontmatter `id`; optional `slug`; **[Amended A2: filenames and links use the note key `<title-slug>--<id>`; the `id` stays immutable and the slug is frozen at creation.]** **NO folgezettel**. Body links use Obsidian-style `[[id|slug]]`; typed links live in frontmatter with taxonomy: `supports, contradicts, analogous, shared-concept, historical-connection, elaborates, refutes, source`. **AC-5:** lint_links rejects any typed link whose relation is outside this taxonomy or whose `target_id` is absent from manifest.

**FR-6 (inquiry lifecycle).** Optional `/inquiries/<id>.md` files move `new → in-progress → answered → archived`, each carrying `result_notes` backlinks to the permanent notes that answered them. **AC-6:** an inquiry marked `answered` MUST have ≥1 `result_notes` backlink resolvable in manifest.

-----

## 5. Functional Requirements — Citation Subsystem

**FR-7 (canonical storage).** CSL-JSON is the canonical bibliographic store (per-reference frontmatter + aggregated `/.bib/refs.json`). **AC-7:** every reference note’s CSL-JSON validates and appears in refs.json.

**FR-8 (rendering).** Rendered `chicago_note` and `chicago_bib` strings MUST be produced by a citeproc-based renderer using the `chicago-fullnote-bibliography` CSL style (Chicago notes-bibliography, 17th/18th ed.). **Implementation choice for Claude Code:** use Python `citeproc-py` with the `chicago-fullnote-bibliography.csl` style bundled under `scripts/csl/`; if unavailable, fall back to `pandoc --citeproc --csl chicago-fullnote-bibliography.csl`. **[Amended A1: bundled as `chicago-notes-bibliography.csl`; pandoc is primary and citeproc-py the fallback.]**  Bundle the CSL file so no network fetch is required at runtime. **AC-8:** lint_citations recomputes the two strings from CSL-JSON and hard-fails on mismatch/malformed output.

**FR-9 (scripture).** Scripture cited by book–chapter–verse per SBL Handbook of Style conventions and excluded from the bibliography. **AC-9:** scripture references carry a `source_tier: primary-text` and a `scripture: true` flag and are skipped by chicago_bib aggregation.

**FR-10 (verification / anti-hallucination).** Every reference note MUST be verified by (a) a raw capture actually fetched into `/raw/`, OR (b) an authoritative metadata lookup: Crossref REST for DOI; arXiv API for arXiv IDs; PubMed for PMIDs; Open Library or Google Books for ISBN. Crossref requires no key; per Crossref’s official `rest-api-doc`, HTTPS queries that include contact info via the `mailto` parameter are routed to the reserved “polite” pool (e.g. `https://api.crossref.org/works?...&mailto=you@example.org`). Note: Crossref revised its public/polite pool rate limits effective 1 December 2025, so `verify_refs.py` MUST send the `mailto` param and back off on HTTP 429. **AC-10:** `verify_refs.py` sets `verification.verified=true` only on a successful capture or lookup; otherwise false.

**FR-11 (hard-fail lint).** `lint_citations.py` MUST hard-fail the run (non-zero exit) on: any unverified reference; any malformed Chicago string; any permanent-note sourced claim lacking a link to a verified reference note. **AC-11:** on fixture notes containing each violation, the lint exits non-zero and names the offending note+reason; on clean fixtures it exits 0.

**FR-12 (contested claims).** A claim flagged contested requires ≥3 independent sources and a `contested` tag. **AC-12:** lint flags a `contested`-tagged permanent note with <3 distinct reference links.

-----

## 6. Functional Requirements — Skill-Repo Deliverables (file-by-file)

**FR-13.** Claude Code MUST create the PRIVATE skill repo with this structure (plugin-packaged; only `plugin.json` goes inside `.claude-plugin/`, all components at plugin root):

```
zettel-bootstrap/
├── .claude-plugin/
│   └── plugin.json                 # name, version, description, author, repository
├── skills/
│   └── zettel-bootstrap/
│       └── SKILL.md                # frontmatter + body <500 lines, progressive disclosure
├── agents/                         # Claude Code subagent definitions (.md, YAML frontmatter)
│   ├── orchestrator.md  researcher.md  synthesizer.md  critic.md
│   ├── librarian.md  connector.md  note-maintainer.md  skill-smith.md
├── references/
│   ├── architecture.md  note-types.md  citation-rules.md  orchestra.md
│   ├── two-mode-access.md  scheduling.md  skill-emergence.md  quality-gates.md
├── templates/
│   ├── fleeting.md  literature.md  permanent.md  reference.md  moc.md
│   ├── inbox-entry.md  config.yml  PURPOSE.md  child-SKILL.md
├── scripts/
│   ├── init_content_repo.sh  maintenance_run.sh  new_worktree.sh
│   ├── lint_citations.py  lint_links.py  build_manifest.py  verify_refs.py
│   ├── fetch_remote.py  serendipity_sweep.py
│   └── csl/chicago-notes-bibliography.csl        # [A1] upstream rename
├── requirements.txt                # python deps
├── smoke_test.sh                   # end-to-end dry run (see §12)
├── .gitignore
└── README.md
```

**AC-13:** `claude plugin validate .` passes on the repo; SKILL.md frontmatter parses; all referenced files exist.

**FR-14 (SKILL.md frontmatter).** Frontmatter MUST include `name: zettel-bootstrap` and a `description` written in the third person with explicit trigger language (both what it does AND when Claude should use it). Per Anthropic’s Claude Platform Docs (Agent Skills overview), the description “Must be non-empty · Maximum 1024 characters · Cannot contain XML tags · The description must include both what the Skill does and when Claude should use it.” Body MUST use progressive disclosure and stay under the spec limit of ≤500 lines / ≤5,000 tokens, pointing to `references/` files for detail. Because the skill is distributed as a Claude Code plugin AND may be uploaded for Cowork/cloud use, restrict SKILL.md frontmatter to the **six portable Agent Skills spec fields** — `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools` — since any field outside this set triggers an “Unexpected fields in frontmatter” validation error on packaging/upload; Claude-Code-only fields belong in the plugin/agent files, not SKILL.md. **AC-14:** SKILL.md loads in Claude Code without a parse error and contains no non-spec frontmatter keys.

**FR-15 (plugin.json).** MUST set at least `name` (the only strictly required field) and SHOULD set `version` (semver — used by Claude Code to detect updates), `description`, `author`, `repository` (string URL, not an object). **AC-15:** `claude plugin validate --strict` reports no errors (unknown fields are warnings/errors under `--strict`; wrong types always fail).

**FR-16 (subagent format).** Each file in `agents/` is Markdown with YAML frontmatter (`name`, `description` required; optional `tools`, `model`); body is the system prompt. All agents get `web_search` + `web_fetch` in their tool set. **AC-16:** each agent file parses and declares its tool set explicitly.

**FR-17 (README).** MUST document install for Claude Code: cloning the private skill repo; installing as a plugin (`/plugin marketplace add <owner>/<repo>` then `/plugin install <name>@<marketplace>`) OR linking/copying `skills/zettel-bootstrap` into `~/.claude/skills/`; GitHub auth prerequisites (`gh` CLI + PAT/SSH); `pip install -r requirements.txt`; and how to run genesis vs. maintenance. **AC-17:** following README steps on a clean machine yields an invocable `/zettel-bootstrap` (or plugin-namespaced `/zettel-bootstrap:...`) command.

-----

## 7. Script Specifications (inputs / outputs / exit codes / CLI)

All Python scripts MUST: read no secrets from the repo; accept `--help`; exit 0 on success, non-zero on failure; log to stdout and, when `--repo <path>` is given, append to that repo’s `log.md`.

**FR-18 `init_content_repo.sh`**

- Args: `--name`, `--visibility {public|private}`, `--owner`, `--topics "<csv>"`, `--cadence`, `--budget`, `--dir <path>`.
- Behavior: scaffold §4.1 tree from templates; write config.yml; `git init`; initial commit; `gh repo create <owner>/<name> --<visibility> --source=. --remote=origin --push`  (verified `gh repo create` flags: visibility via `--public`/`--private`/`--internal`, `--source`, `--remote`, `--push`); build initial manifest.
- Exit: 0 on push success; non-zero on `gh`/auth failure with actionable message. **AC-18:** produces a live remote repo with the substrate committed; re-running with an existing repo name fails safely without clobbering.

**FR-19 `build_manifest.py`** — Args `--repo <path>`. Scans note frontmatter; emits manifest.json per FR-3; public→full raw URLs, private→relative + API paths. Idempotent (AC-3). Exit non-zero on malformed frontmatter.

**FR-20 `lint_citations.py`** — Args `--repo <path>`. Implements FR-11/12. Exit non-zero on any violation; prints machine-readable `FILE\tRULE\tREASON` lines.

**FR-21 `lint_links.py`** — Args `--repo <path>`. Enforces FR-5 taxonomy, `[[id]]` resolvability, INDEX→MOC→note layering, 1-1-1. Exit non-zero on violation.

**FR-22 `verify_refs.py`** — Args `--repo <path>`, `--offline` (skip network, rely on `/raw/` captures only), `--mailto <email>` (sent to Crossref for polite-pool routing). Implements FR-10 lookups (Crossref/arXiv/PubMed/OpenLibrary/GoogleBooks). Writes `verification` blocks. Exit 0 even if some refs unverified (it records state); lint_citations is the gate. Network failure → graceful degradation to `/raw/`-capture verification only, logged as a warning.

**FR-23 `fetch_remote.py`** — Mode-B container-side fetcher. Args `--manifest-url <url>` OR `--owner --repo [--token]`. curls manifest + requested notes from inside the code-execution container. For private repos requires a token (env var, never a repo file). Exit non-zero if neither raw fetch nor API succeeds.

**FR-24 `serendipity_sweep.py`** — Args `--repo <path>`, `--threshold <float>`, `--out /proposed-links/`. Computes note embeddings (default `sentence-transformers`, e.g. a compact all-MiniLM-class model; configurable in config.yml), cosine similarity, builds the typed-link graph, runs Louvain community detection (`python-louvain`/`networkx`),  and proposes cross-community links (relation type + one-line justification) into `/proposed-links/`. **Graceful degradation:** if `sentence-transformers` is unavailable, fall back to LLM-only candidate linking and log the downgrade. Exit 0; writes proposals, never edits notes directly.

**FR-25 `maintenance_run.sh`** — The cron entrypoint. Wraps a headless Claude Code invocation. MUST use the current print-mode flags: `claude -p "<maintenance prompt>" --output-format json --max-turns <N> --model <model> --max-budget-usd <B> --allowedTools "<scoped list>" --permission-mode dontAsk`. Redirect stdout→result JSON, stderr→log file. Honors `run.lock` (FR-30). Exit code mirrors the Claude run; on `--max-turns`/budget cutoff, does NOT push partial unlinted state. **AC-25:** a dry-run with a stub topic completes end-to-end and leaves the repo lint-clean or unpushed. (Note: `--max-turns` exits non-zero at the limit and there is no default turn limit in print mode, so always set it explicitly.)

**FR-26 `new_worktree.sh`** — Args `--repo <path> --name <branch>`. Creates an isolated git worktree/branch for a subagent; prints the worktree path. **AC-26:** two invocations create non-conflicting worktrees sharing one `.git`. 

-----

## 8. Genesis & Maintenance Sequences

**FR-27 (Genesis sequence).**

1. Detect first run (no content repo configured).
1. Prompt user for: topic(s); content-repo name + visibility; schedule cadence; budget (USD/turns).
1. Run `init_content_repo.sh` (FR-18).
1. Dispatch a minimal first orchestra pass: Researcher(s) capture ≥1 raw source per topic → literature notes; Synthesizer distills ≥1 permanent note; Librarian builds INDEX + first MOC; verify_refs + lint gates; build_manifest; commit/push; append log.md.
1. Print next-steps for scheduling (cron template + Cowork/desktop task note).
   **AC-27:** after genesis, the content repo passes all lints and contains ≥1 verified reference, ≥1 literature, ≥1 permanent note, INDEX, and a MOC.

**FR-28 (Maintenance cycle order).** Each run MUST execute in this order:

1. Acquire `run.lock`; `git pull` (Mode A) / establish remote read (Mode B).
1. Read INBOX (prioritize `new` inquiries).
1. Research/synthesize for open inquiries (Orchestrator → Researchers → Synthesizers in worktrees).
1. Routine maintenance: freshness checks, fleeting sweep, link repair, gap analysis vs. config topics.
1. Connector sweep (slower cadence, e.g., weekly; configurable) → `/proposed-links/`; Critic reviews; accepted links written into BOTH notes; rejections logged.
1. Critic gates (groundedness/atomicity/clarity/link-quality).
1. Skill-smith retrospective (if its cadence is due) — §9.4.
1. Lint gates (lint_citations, lint_links).
1. Rebuild manifest.json + `.bib/refs.json`.
1. Commit + push (push-rejection retry: re-pull, re-lint, retry). **[Amended A3: the headless run commits; the wrapper re-lints and pushes.]**
1. Update log.md and INBOX statuses; release `run.lock`.
   **AC-28:** steps are observable in log.md in order; a failed gate aborts before step 10.

-----

## 9. Functional Requirements — Orchestra, Two-Mode Access, Scheduling, Skill Emergence

### 9.1 Orchestra

**FR-29.** Implement subagents with these responsibilities and model mix (configurable in config.yml `models`):

- **Orchestrator/Planner** (strong model): reads INBOX first; plans the run; assigns worktrees.
- **Researchers** (cheap model): produce fleeting + literature notes; capture raw sources into `/raw/`.
- **Synthesizers** (strong model): distill atomic permanent notes; enforce atomicity/1-1-1.
- **Critic** (strong model): claim-by-claim groundedness vs. cited sources; rubric scoring atomicity/clarity/link-quality/own-words; flag <0.80 groundedness, block <0.70.
- **Librarian** (cheap/strong): MOCs, tag ontology, rebuild manifest + refs.json.
- **Connector/Serendipity** (cheap for embeddings + strong for justification): FR-24 sweep.
- **Note-Maintainer** (cheap): feedback-driven revisions, fleeting sweeps, link hygiene.
- **Skill-smith** (strong): §9.4.
  **AC-29:** each agent definition names its model tier and tools; strong/cheap tiers are read from config.yml.

### 9.2 Two-mode git access

**FR-30 (Mode A).** Run starts with pull/clone; agents work in worktrees; validation gates MUST pass before commit+push; `run.lock` serializes concurrent scheduled runs (a run that finds a fresh lock exits without work); push-rejection retry loop. **AC-30:** simulated concurrent runs do not both push; the second aborts on lock.

**FR-31 (Mode B — critical platform constraint).** Per Anthropic’s web fetch docs, server-side `web_fetch` “can only fetch URLs that have previously appeared in the conversation context” (user messages, client-side tool results, or prior web_search/web_fetch results) and “cannot fetch arbitrary URLs that Claude generates or URLs from container-based server tools (Code Execution, Bash, etc.).” Consequently, URLs entering context only via SKILL.md loaded through the code-execution container are NOT fetchable by server-side web_fetch. Claude Code’s own WebFetch (domain-permission model) CAN fetch skill-embedded URLs. Therefore Mode B MUST be belt-and-suspenders:

1. manifest.json stores full `raw.githubusercontent.com` URLs (public repos).
1. SKILL.md instructs: obtain the index/manifest URL from the user message or via `web_search` by repo name, THEN fetch it (so the URL legitimately enters context).
1. Bundled `fetch_remote.py` curls the manifest/notes from inside the code-execution container as the PRIMARY Mode-B mechanism on claude.ai/API.
1. Prefer GitHub MCP server `get_file_contents` when connected.
1. On the Claude Code surface, WebFetch may embed and fetch URLs directly.
   **For PRIVATE content repos, Mode B REQUIRES the GitHub MCP server/connector with auth** (anonymous raw URLs 404; `get_file_contents` needs a token/PAT with repo read scope). **AC-31:** SKILL.md documents all five paths and the private-repo MCP requirement; fetch_remote.py works container-side for both public (raw) and private (token/API) repos.

### 9.3 Scheduling

**FR-32.** Provide a cron template invoking `maintenance_run.sh` (which wraps `claude -p …` per FR-25) on the laptop, AND document optional Claude Code Desktop scheduled tasks  / Cowork scheduled tasks (both run locally while the app is open; each run fires a fresh session with full access to files, MCP servers, skills, connectors, and plugins). Maintenance cycle order per FR-28; connector and skill-smith run on slower configurable cadences. **AC-32:** README/scheduling.md shows a working crontab line and the desktop-task equivalent, and notes that Cowork/cloud sessions do NOT read `~/.claude/skills/` on the local machine — for those the skill must be enabled for the claude.ai account, or (cloud sessions) committed to the cloned repo’s `.claude/skills/` or shipped in a repo-declared plugin.

### 9.4 Skill emergence (WikiSkill-adapted)

**FR-33 (three-layer separation).** Mirror WikiSkill’s architecture (arXiv:2608.27454, §3.1) inside the content repo: **Raw layer** = immutable `/raw/` captures + run traces/logs (never edited); **Wiki/knowledge layer** = the persistent note graph + pattern knowledge + `log.md` + `skill-impact.md` (compounds, never rolled back — in the paper, *“The wiki is not reset between iterations, but rather accumulates and compiles knowledge continuously”*); **Skill layer** = `/skills/<name>/{SKILL.md, PURPOSE.md}` (gated, rollbackable). **AC-33:** rejecting a proposed child skill never deletes or reverts knowledge notes.

**FR-34 (proposer inputs).** Before proposing, the Skill-smith MUST read: (a) the knowledge index (manifest/INDEX), (b) the skill-impact history (`skill-impact.md`), and (c) ≥4 recent run traces/logs — then inspect specific notes/traces on demand (mirroring WikiSkill’s Skill Proposer, which is provided the wiki index, the skill-impact tracker, and a summary of task outcomes, then uses `read_file` to inspect specific patterns/traces). **AC-34:** each proposal cites the patterns/traces that motivated it in PURPOSE.md (Origin / Patterns-Addressed / Evolution-History sections — PURPOSE.md “maps the skill back to the motivating Wiki patterns,” per the paper §3.1).

**FR-35 (atomic proposal).** Exactly ONE child-skill create-or-edit proposal per cycle; domain- or workflow-scoped; PREFER patching a partially-correct existing skill over creating new (incremental patch-based edit). Output `SKILL.md` + `PURPOSE.md`. **AC-35:** a cycle produces at most one proposal; the proposal is a create OR a single-skill patch.

**FR-36 (open-world gating).** Candidate child skill → A/B trial on inbox questions comparing groundedness / citation-coverage / critic scores with vs. without the candidate → **human approval REQUIRED before promotion**. On rejection, revert the skill layer to the last approved configuration and append the outcome (proposal metadata, target skill name, unified diff of the modification, scores, and Accepted/Rejected + reason) to `skill-impact.md` — matching WikiSkill’s programmatic impact-tracker entry, which records “proposal metadata, target skill name, unified diff of the modification, validation score … and final acceptance outcome.” **The knowledge layer is never rolled back regardless of outcome.** **AC-36:** rejected proposals appear in skill-impact.md with reasons and are not re-proposed; knowledge notes are untouched.

**FR-37 (safety rails).** Skill-smith may NEVER modify the bootstrap skill repo itself; max 1 proposal/cycle; all child skills sandboxed under content-repo `/skills/` until human-promoted; per-run budget caps enforced. **AC-37:** an attempt to write outside `/skills/` (e.g., into the skill repo) is blocked and logged.

-----

## 9a. Non-Functional Requirements

- **NFR-1 (budget/idempotency):** every run honors `--max-budget-usd` and `--max-turns`; lints and manifest build are idempotent.
- **NFR-2 (logging):** append-only `log.md`; each run stamps start/end, mode, agents dispatched, gate results, commit SHA.
- **NFR-3 (error handling):** any gate failure aborts before push; partial work is discarded or left uncommitted; push-rejection retries with re-pull/re-lint.
- **NFR-4 (no secrets):** no tokens/keys committed to either repo; auth via `gh`/env/SSH agent; `.gitignore` excludes `run.lock`, `__pycache__`, `.venv`, local caches, any `*.token`/`.env`.
- **NFR-5 (graceful degradation):** offline/dep-missing paths for verify_refs (raw-only), serendipity (LLM-only), citeproc (pandoc fallback).
- **NFR-6 (portability):** SKILL.md restricted to the six spec fields; Claude-Code-only behavior lives in agents/plugin files.

-----

## 9b. Quality / Acceptance Framework

- **QA-1 groundedness gate:** critic rubric prompts flag <0.80, block <0.70 (open-world, no ground truth).
- **QA-2 citation-coverage:** hard fail if a permanent sourced claim lacks a verified reference link.
- **QA-3 source tiers:** record per reference `source_tier` (peer-reviewed > primary text > reputable secondary > general web).
- **QA-4 human authority:** INBOX feedback is authoritative and overrides automated decisions.
- **QA-5 skill adoption:** A/B + human gate (FR-36).

-----

## 10. Out-of-Scope / Deferred

- First real seed topic (supplied at genesis runtime, not baked in).
- Cowork/desktop scheduled-task setup is manual (documented, not automated).
- Embedding model is optional (LLM-only fallback ships by default).
- Cloud Routines execution (documented as an option; not the default entrypoint).

## 11. Open Items Requiring User Input at Runtime

- Topic(s) / question / research path.
- Content-repo name + visibility (public/private).
- Schedule cadence (and connector/skill-smith sub-cadences).
- Budget (USD/turn caps).
- Whether to enable GitHub MCP (mandatory for Mode B on private content repos).

## 12. Testing & Acceptance Checklist (Claude Code MUST run before final commit)

1. `claude plugin validate --strict .` passes; SKILL.md frontmatter parses and uses only the six spec fields.
1. `pip install -r requirements.txt` succeeds; all scripts respond to `--help`.
1. `init_content_repo.sh` creates a working DUMMY content repo (throwaway name) with the full substrate and an initial commit; teardown documented.
1. Lints pass on clean fixture notes and FAIL (non-zero, with reasons) on planted-violation fixtures: unverified ref; malformed Chicago string; permanent claim missing reference link; bad typed-link relation; unresolved `[[id]]`; contested claim with <3 sources.
1. `build_manifest.py` builds valid manifest.json; re-run is byte-identical (idempotent); public→raw URLs, private→relative+API paths.
1. `verify_refs.py` verifies a known DOI via Crossref (with `mailto`) and a known ISBN via Open Library/Google Books; `--offline` verifies a `/raw/`-captured source.
1. `serendipity_sweep.py` runs with embeddings if available and degrades to LLM-only otherwise, writing to `/proposed-links/`.
1. A dry-run maintenance cycle with a STUB topic completes end-to-end (FR-28 order visible in log.md) and leaves the repo lint-clean-committed or aborts without push.
1. `run.lock` serialization verified (second concurrent run aborts).
1. Skill-smith writes a proposal only under content-repo `/skills/` and records to skill-impact.md; an out-of-repo write attempt is blocked.
1. `smoke_test.sh` orchestrates 2–8 and exits 0.

-----

## Recommendations (build order)

1. **Phase 1 (substrate + citation gates):** templates, init_content_repo.sh, build_manifest.py, lint_citations.py, lint_links.py, verify_refs.py, SKILL.md, plugin.json, README. Ship the genesis run first — it is the smallest slice that delivers standalone value and exercises the hardest gates. Exit gate: checklist items 1–6, 8.
1. **Phase 2 (orchestra + maintenance + two-mode):** agents/, maintenance_run.sh, new_worktree.sh, fetch_remote.py, run.lock, scheduling docs. Exit gate: items 8–9.
1. **Phase 3 (connector + serendipity):** serendipity_sweep.py, proposed-links flow. Exit gate: item 7.
1. **Phase 4 (skill emergence):** skill-smith, skill-impact.md, A/B + human gate. Exit gate: item 10.

**Thresholds that change the plan:** if `citeproc-py` cannot render valid Chicago fullnote strings on the real fixtures, switch to the pandoc fallback before Phase 1 sign-off; if private-content-repo Mode B is required by the user, GitHub MCP must be configured and tested before Phase 2 sign-off; if per-run budget consistently trips `--max-budget-usd` before the cycle completes, reduce parallel Researcher fan-out and/or push the connector and skill-smith cadences further apart before scaling topics.

## Caveats

- Platform behavior was verified against current Anthropic/GitHub documentation as of 2026-08-30: skill locations (`~/.claude/skills/`, `.claude/skills/`, plugin `skills/`), the plugin layout (`.claude-plugin/plugin.json` at root), the six portable SKILL.md frontmatter fields and 1,024-char description cap, `claude -p` print-mode flags (`--output-format`, `--max-turns`, `--max-budget-usd`, `--allowedTools`, `--permission-mode`), `gh repo create` visibility flags, GitHub MCP `get_file_contents`, and the `web_fetch` URL-origin rule. These can change—re-verify at build time with `claude plugin validate` and the live docs.
- The server-side `web_fetch` URL-origin restriction is the single most fragile design point for Mode B; the belt-and-suspenders approach (FR-31) is mandatory, not optional. Note that GitHub’s remote MCP server has documented failure modes for `get_file_contents` on some private/org repos with IP allow-lists (404s), so the local/Docker MCP server or a PAT-based API path in fetch_remote.py should be available as a fallback.
- `citeproc-py` implements CSL 1.0.1 and historically passes only a portion of the CSL test suite; validate Chicago output on real fixtures and keep the pandoc fallback wired in.
- WikiSkill’s original gating uses validation against ground truth; this design substitutes human approval + A/B because the open-world knowledge base has no labels—expect slower, human-paced skill adoption. This is a deliberate trade of autonomy for safety and is reinforced by FR-37’s rails.
- Cadence choice interacts with cost and platform limits: laptop cron + `claude -p` uses your normal usage quota, desktop/Cowork tasks run only while the app is open, and cloud Routines (if later adopted) carry per-plan daily run caps and require the skill to be present in the cloud session—design cadences accordingly.