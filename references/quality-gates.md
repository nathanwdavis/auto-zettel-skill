# Quality gates

Every gate, what it enforces, and where it binds. The invariant behind all of
them: **never make a gate pass by weakening it**, deleting the offending note,
or back-filling a citation nobody verified. Fix the note or capture the
source. Generating well-formed artifacts (`capture.py`) is the approved shape
of "make the gate pass".

## The gates

| Gate | Enforces | Fails on |
|---|---|---|
| `verify_refs.py` | verification state per reference (records, exits 0; `--offline` checks raw/ captures only) | usage errors only — `lint_citations` is the gate that fails |
| `build_manifest.py --check` | manifest.json is current and deterministic | drift between notes and index |
| `lint_citations.py` | every sourced claim traces to a verified reference; Chicago strings current; reference-note field completeness, source-tier vocabulary, one note per source | ungrounded claims, unverified or malformed refs, duplicate sources |
| `lint_links.py` | link resolvability, FR-5 taxonomy, INDEX→MOC→note layering (both hops), 1-1-1 including the literature locator and `reference` field, key naming, inquiry lifecycle (AC-6) | broken/foreign links, malformed identity, empty MOCs, answered-with-nothing |
| `lint_skills.py` | skill layer wellformedness: two-file units, PURPOSE provenance and status, no re-proposed rejected creates | malformed or uncited child skills (AC-34/AC-36) |
| `check_skill_sandbox.py` | the cycle diff kept log.md and skill-impact.md append-only and raw/ immutable; `--strict` confines a smith diff to its sandbox | history rewrites, raw edits, sandbox escapes (AC-37) |

### `lint_links.py` rules

| Rule | Fails when |
|---|---|
| `missing-key`, `malformed-key`, `filename-key-mismatch`, `slug-key-mismatch`, `id-key-mismatch` | the filename stem, `key`, `slug`, and `id` disagree (A2) |
| `bad-relation` | a typed link's relation is outside the FR-5 taxonomy |
| `unresolved-link`, `unresolved-wikilink` | a typed link or `[[...]]` names no known note |
| `duplicate-id` | two notes share a timestamp id (A6) |
| `atomicity` | a permanent note has no outbound typed link |
| `one-to-one` | a literature note links to other than exactly one reference note |
| `reference-mismatch` | a literature note's `reference` field is empty or names a different note than its source link |
| `missing-locator` | a literature note has no locator |
| `layering` | INDEX links to something that is not a MOC |
| `moc-empty` | a MOC links to nothing |
| `missing-index` | no INDEX.md |
| `unanswered-answer`, `result-note-type`, `unresolved-result-note`, `bad-status`, `missing-question` | the inquiry lifecycle (AC-6; see `capture.md`) |

`build_manifest.py` additionally refuses a note whose `updated`/`created` is
not an ISO-8601 date (FR-3), and a duplicate id.

## Where each binds

| Site | What runs | Authority |
|---|---|---|
| In-session (prompt step 8) | all lints, fix-and-rerun | advisory — the model fixes its own work |
| Mode-A wrapper (`maintenance_run.sh`) | manifest `--check` + all three lints + sandbox gate, independently re-run after the session ends | the push: any failure means nothing is pushed (amendment A3) |
| Mode-B CI (`ci/content-repo-gates.yml`) | verify `--offline` + manifest `--check` + all three lints + sandbox gate, server-side | the merge: the required `gates` check decides what reaches main |

The wrapper and CI re-run gates *independently* of the session on purpose: a
runaway, turn-capped, or budget-cut run structurally cannot push or merge
unlinted state, whatever it believed about its own work.

## Thresholds and judgment gates

| Gate | Rule |
|---|---|
| QA-1 critic groundedness | flag < 0.80, block < 0.70 (open world, no ground truth) |
| QA-2 citation coverage | hard fail — an unverifiable sourced claim never lands |
| QA-3 link integrity | hard fail via `lint_links.py` |
| QA-4 human feedback | INBOX is authoritative and overrides automated decisions |
| QA-5 skill adoption | A/B trial + human approval (FR-36); scores inform, the human decides |

The A/B trial reuses QA-1's rubric: a paired judge scores both arms'
groundedness side by side (randomized order, against position bias), and
citation coverage is computed mechanically from the manifest — see
`references/skill-emergence.md`.

## Exit-code contract

Lints emit `FILE\tRULE\tREASON` lines and exit 1 on violations, 2 on usage
errors, 0 clean; every run appends PASS/FAIL to the content repo's log.md.
Advisory tools (the serendipity sweep, `verify_refs.py`) always exit 0 so a
degraded pass is a logged warning, not a blocked cycle.
