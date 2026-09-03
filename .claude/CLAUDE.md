# Working on zettel-bootstrap

Guidance for developing **this skill**. It is not loaded by maintenance runs —
`ci/setup-environment.sh` clones to `/opt/zettel-skill` and symlinks only
`skills/` and `agents/`, so nothing here reaches a scheduled cycle's context.

## What this repo is

The plugin, and only the plugin. Zettelkasten notes live in a separate
**content repo** created at genesis by `scripts/init_content_repo.sh`. They
never mix — a note file appearing in this tree is a bug.

Both repos are public (amendment A4). **Nothing here may ever contain a
secret** (NFR-4): auth flows through `gh`, the SSH agent, or environment
variables. `.gitignore` covers `.env`, `*.token`, `*.pem`, `.netrc`, `run.lock`.

## Running things

```sh
.venv/bin/python -m pytest -q      # 421 tests, ~160s
./smoke_test.sh                    # pytest + end-to-end scaffold; exit 0 or it isn't done
claude plugin validate --strict .
```

**`pytest` is not installed in the system python.** `python3 -m pytest` fails
with `No module named pytest`; the venv at `.venv/` has it. `smoke_test.sh`
finds the venv itself, but a bare `pytest` invocation will not.

Run `smoke_test.sh` before calling any change complete. It is the acceptance
checklist (`docs/REQUIREMENTS.md` §12) in executable form, and it catches
integration breaks the unit tests miss.

## The invariant everything else rests on

**Never make a gate pass by weakening it**, deleting the offending note, or
back-filling a citation nobody verified. Fix the note or capture the source.

This is not a style preference — it is the product. Phase 3.6 exists because
hand-written notes broke the manifest, and the tempting fix was to relax the
frontmatter requirement. Relaxing it would have removed the invariant that
every file in a content repo is well-formed, which the manifest, both lints,
and Mode-B remote access all depend on. Generating well-formed artifacts
(`scripts/capture.py`) cost one script and kept the invariant. Prefer that
shape of fix.

**It recurred from the other direction, and cost two cycles.** A run on a stale
install regenerated `manifest.json` without its `inquiries` block; CI's
`build_manifest.py --check` — running current code — rejected it. Two different
agents then "fixed" the gate by hand-writing an inquiries block to match, and
both guessed the same wrong schema (`id`/`slug`/`tags`/`url_or_apipath`, no
`priority`, unsorted `result_notes`). `main` sat red across two merges. What
worked was refreshing the install and re-running the generator. **Matching a
gate by hand is the same error as relaxing it**: a generated artifact is
whatever the tool emits, and any hand-authored version is a guess that the next
regeneration silently discards.

## Where the rules live

`docs/REQUIREMENTS.md` is the specification — FR-x, AC-x, NFR-x, QA-x. It is
the source of truth, and code comments cite it by number.

Deviations are recorded as **numbered amendments** at the top of that file
(A1–A8 so far). When implementation forces a change to the spec, append the next
rather than editing the requirement text: the reasoning is worth more than a
tidy document. `PLAN.md` tracks phase status and the build order.

## Environment facts, learned the hard way

- **The sandbox proxy blocks Crossref, OpenLibrary, PubMed, arXiv, and
  HuggingFace.** Network paths are tested with cassettes
  (`tests/cassettes/`, injected via `zettel_lib/http.py`'s `Transport`). Live
  verification does work in a Full-egress cloud environment — it has been
  confirmed there — so a failure here is the sandbox, not the code.
- **`gh` is absent in remote containers.** Use the GitHub MCP tools for PRs and
  `init_content_repo.sh --no-remote` to scaffold locally.
- **The git proxy permits only fast-forward pushes to ordinary branches** — no
  custom ref namespaces, no deletions. That is why `zettel_lib/gitlock.py` is a
  `LOCK.json` file on branch `zettel/lock` rather than `refs/zettel/run-lock`,
  which is what the design originally called for and the proxy rejected.
- **A Routine-fired session has no push credentials** unless it is spawned with
  `source_url`, or the Routine was created from the claude.ai UI.
- **A remote-session clone has no `refs/remotes/origin/HEAD`**, and the cached
  `/opt/zettel-skill` install can be arbitrarily stale — both bit live runs
  (issue #7, amendment A8). Default-branch probes must be pipefail-safe, and
  `remote_cycle.sh refresh-skill` is the currency mechanism; do not "verify"
  install freshness with presence checks. Since PR #10, `start` runs that
  refresh itself and re-execs when HEAD moves, so currency no longer depends on
  the prompt remembering to ask — but see the next bullet for the one hop that
  still needs a human.
- **A Routine's prompt freezes at creation time.** This is the sharpest edge in
  the whole system and it has bitten twice. Editing
  `scripts/remote_maintenance_prompt.md` changes nothing for Routines that
  already exist — they keep sending the text they were created with, forever.
  So a fix that lives *only* in the prompt reaches new Routines and no others.
  Put anything load-bearing in the scripts, where a stale install can at least
  fast-forward to it. The bootstrap is unavoidably manual exactly once: a stale
  installed `start` does not contain the self-refresh, so after changing that
  code path someone must update or recreate the Routine so its prompt runs
  `refresh-skill` one more time.
- **The agent registry is symlinks into the plugin tree.**
  `ci/setup-environment.sh` links `agents/*.md` into `~/.claude/agents/`, so
  anything that rewrites a registered definition must `unlink` first: writing
  through the symlink edits the *skill repo*, which `maintenance_run.sh`'s
  snapshot check treats as a violation and FR-37 forbids.
  `zettel_lib.agents.materialize()` is the one writer, and
  `test_materialize_never_writes_through_the_symlink` is what keeps it honest.
- `rsync` is not installed (use `tar`). `pip install --upgrade pip` hard-fails
  on the Debian system pip, which is why `ci/setup-environment.sh` skips it.

## Conventions

- **Comments and docstrings carry the *why*.** What the code does is visible;
  why it is shaped that way is not. `scripts/capture.py`'s module docstring is
  the model — it explains the failure mode that justifies the tool's existence.
- **Shared logic goes in `scripts/zettel_lib/`**, never duplicated across entry
  points. Frontmatter, naming, repo access, HTTP, citations, similarity, and
  the git lock all live there precisely so the twenty entry points cannot drift.
- **`--allowedTools` must be one quoted comma-separated argument.** Split
  across shell words, space-containing patterns like `Bash(git add:*)` shatter
  and silently deny commits mid-run. `tests/stub_claude` asserts this.
- Lints emit `FILE\tRULE\tREASON` and exit 1; usage errors exit 2. Scripts that
  advise rather than gate (the sweep) always exit 0.
- Every script takes `--repo` and answers `--help`; every script that *acts*
  appends to the content repo's `log.md` (spec §7). Read-only tools
  (`inquiries.py`, `query.py`, `skill_review.py list`, `new_worktree.sh`,
  `fetch_remote.py`, whose `--repo` is a GitHub name) do not — a query is not
  an operation (A9).

## Git workflow

Develop on `claude/<slug>`. After that branch's PR merges, **restart it from
`origin/main`** rather than stacking on merged history:

```sh
git fetch origin main && git checkout -B claude/<slug> origin/main
```

Commit in logical chunks with messages that explain the reasoning, not the
diff. Never push to `main`; never merge your own PR.

## Skill emergence (Phase 4, shipped) — the standing rails

**FR-37 is absolute: skill-smith may never write to this repo.** Child skills
are sandboxed under the *content* repo's `skills/` directory until a human
promotes them, and the knowledge layer is never rolled back for a skill
outcome. Rejected proposals are permanent history in `skill-impact.md` and
are never retried (name-level, for creates — amendment A7).

Those rails are now code, and changes must keep them that way:

- `maintenance_run.sh` snapshots the plugin tree around the headless run and
  aborts on any change; smoke step 8e and
  `test_maintenance_run.py::test_plugin_repo_write_is_blocked_and_logged`
  assert it. Never route around that check.
- `zettel_lib/impact.py` is the ONLY writer for `skill-impact.md` — never
  append to it by hand from a new entry point, or the semantic append-only
  check in `check_skill_sandbox.py` and the format will drift apart.
- A patch to an approved skill must flip PURPOSE back to `status: proposed`.
  The rejection flow finds its restore point by walking history for the
  newest committed PURPOSE that says `approved`; skip the flip and rejection
  restores the wrong state.
- `skill_trial.py` isolates its control arm by copying the tree minus the
  candidate. Keep isolation in the tree, not in the prompt.
