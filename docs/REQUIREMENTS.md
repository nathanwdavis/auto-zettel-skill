# Requirements Document — Anthropic Agent Skill: `zettel-bootstrap`

**Document type:** Implementation brief / full specification for Claude Code
**Target executor:** Claude Code (will implement and commit to a private GitHub “skill repo”)
**Status:** Complete spec (may be built in phases; all phases specified)
**Date:** 2026-08-30

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

**FR-3 (manifest.json).** Each note entry MUST include: `id`, `type`, `title`, `tags[]`, `links[]` (each `{target_id, relation}`), `path`, `url_or_apipath`, `updated` (ISO-8601). **AC-3:** `build_manifest.py` regenerates deterministically from note frontmatter; running it twice with no note changes produces a byte-identical file (idempotent).

### 4.2 Note types & rules

**FR-4.** Note-type rules enforced by lints:

- **fleeting:** short-lived capture; swept each cycle by Note-Maintainer.
- **literature:** own-words summary of exactly ONE source with locator; links to exactly one reference note.
- **permanent:** ONE atomic idea; title-as-claim; ≥1 outbound typed link; any sourced claim links to a verified reference note; 1-1-1 enforced.
- **reference:** exactly one per source; CSL-JSON frontmatter + `chicago_note` + `chicago_bib` strings + `source_tier` + `verification` block `{method, source, verified(bool), date}` + `raw_capture` path.
- **structure/MOC:** INDEX links only to MOCs; MOCs link to notes.

**FR-5 (IDs & links).** Timestamp-based immutable IDs (e.g., `202608301412`) used as filename stem AND frontmatter `id`; optional `slug`; **NO folgezettel**. Body links use Obsidian-style `[[id|slug]]`; typed links live in frontmatter with taxonomy: `supports, contradicts, analogous, shared-concept, historical-connection, elaborates, refutes, source`. **AC-5:** lint_links rejects any typed link whose relation is outside this taxonomy or whose `target_id` is absent from manifest.

**FR-6 (inquiry lifecycle).** Optional `/inquiries/<id>.md` files move `new → in-progress → answered → archived`, each carrying `result_notes` backlinks to the permanent notes that answered them. **AC-6:** an inquiry marked `answered` MUST have ≥1 `result_notes` backlink resolvable in manifest.

-----

## 5. Functional Requirements — Citation Subsystem

**FR-7 (canonical storage).** CSL-JSON is the canonical bibliographic store (per-reference frontmatter + aggregated `/.bib/refs.json`). **AC-7:** every reference note’s CSL-JSON validates and appears in refs.json.

**FR-8 (rendering).** Rendered `chicago_note` and `chicago_bib` strings MUST be produced by a citeproc-based renderer using the `chicago-fullnote-bibliography` CSL style (Chicago notes-bibliography, 17th/18th ed.). **Implementation choice for Claude Code:** use Python `citeproc-py` with the `chicago-fullnote-bibliography.csl` style bundled under `scripts/csl/`; if unavailable, fall back to `pandoc --citeproc --csl chicago-fullnote-bibliography.csl`.  Bundle the CSL file so no network fetch is required at runtime. **AC-8:** lint_citations recomputes the two strings from CSL-JSON and hard-fails on mismatch/malformed output.

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
│   └── csl/chicago-fullnote-bibliography.csl
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
1. Commit + push (push-rejection retry: re-pull, re-lint, retry).
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