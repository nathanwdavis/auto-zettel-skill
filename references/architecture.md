# Architecture

## Two repositories

| | Skill repo (this one) | Content repo |
|---|---|---|
| Visibility | Public (amendment A4) | Public or private, chosen at genesis |
| Contains notes? | Never | Yes, all of them |
| Created by | A human, once | `scripts/init_content_repo.sh` at genesis |
| Modified by a run? | Never | Yes — this is the working repo |

Keeping them apart is what makes the skill safe to run unattended: a run has no
reason to write to the skill repo, so any attempt to is a bug (FR-37).

## Three layers inside the content repo

Adapted from WikiSkill (arXiv:2608.27454, Tang et al.), which organizes an
agent workspace into a Raw layer of immutable traces, a Wiki layer of
structured knowledge, and a Skill layer of evolving procedure.

| Layer | Where | Rule |
|---|---|---|
| **Raw** | `raw/`, run traces | Immutable. Captures are never edited or deleted. |
| **Knowledge** | notes, `manifest.json`, `log.md`, `skill-impact.md` | Compounds. **Never rolled back**, whatever else fails. |
| **Skill** | `skills/<name>/` | Gated and rollbackable. Requires human promotion. |

The asymmetry is deliberate and load-bearing: a rejected child skill reverts,
but the knowledge it was proposed against stays. Knowledge is never sacrificed
to make a process step succeed.

## Content-repo layout

```
INBOX.md          questions and corrections; read FIRST every run
INDEX.md          root MOC; links only to MOCs
manifest.json     machine-readable note index (+ id_to_key map)
config.yml        topics, cadence, budget, autonomy, model mix
permanent/        atomic ideas, one claim each
literature/       own-words summaries, one source each
reference/        bibliographic records, one per source
moc/              maps of content
fleeting/         short-lived captures, swept each cycle
raw/              verbatim source captures (immutable)
inquiries/        open questions and their answering notes
proposed-links/   connector queue awaiting review
skills/           self-authored child skills, pending promotion
skill-impact.md   proposal outcomes, including rejections and why
.bib/refs.json    aggregated CSL-JSON
log.md            append-only run log
```

## Genesis flow

1. Ask the user for topics, repo name, visibility, cadence, budget.
2. `init_content_repo.sh` scaffolds, commits, and pushes the substrate.
3. First knowledge pass: capture sources, write reference + literature notes,
   distil a permanent note, build INDEX and a MOC.
4. Gates: `verify_refs` → `build_manifest` → `lint_citations` → `lint_links`
   → `lint_skills`.
5. Commit and push only if every gate passes. Append to `log.md`.

## Gate order, and why

```
verify_refs.py     records verification state; exits 0 even when refs fail
build_manifest.py  regenerates the index the lints resolve links against
lint_citations.py  HARD GATE: ungrounded claims
lint_links.py      HARD GATE: broken links, layering, 1-1-1
lint_skills.py     HARD GATE: malformed or uncited child skills (Phase 4)
```

The wrapper and CI additionally run `check_skill_sandbox.py` on the cycle's
diff (append-only ledgers, immutable raw/); see `quality-gates.md`.

`verify_refs` deliberately does not fail. Separating "record what is true" from
"decide whether that is acceptable" means a network outage degrades to
raw-capture verification and reports honestly, rather than silently marking
things verified to get past a gate.

The manifest is rebuilt *before* the lints because both resolve `[[key]]`
references through it. Linting against a stale manifest would report phantom
failures.

## Determinism

`build_manifest.py` sorts every collection and uses fixed JSON separators, so
re-running it over unchanged notes produces a byte-identical file. That makes
"did this run actually change the knowledge base?" answerable from `git diff`
alone, which matters for scheduled unattended runs.
