You are running an unattended zettel-bootstrap maintenance cycle on the content
repository at {{REPO}}.

Follow this cycle IN ORDER. After completing each step, append one line to
log.md in the form `- <UTC timestamp> step <N>: <what happened>` so the run is
auditable. Skip a step only when it has nothing to do, and log the skip.

Where a step says to delegate to a named agent and that agent is not
available in this session, adopt its role directly: read the matching
`agents/<name>.md` and follow it, logging the step as `(self-review)`. The
critic gate (step 6) is YOUR responsibility either way — delegation is an
optimization, never a precondition, and a missing agent is never a reason to
skip the gate.

Step 2. Read INBOX.md, then `inquiries.py --repo <repo> --status new` for the
open questions in work order, and read the ones you plan to work. Entries marked
`new` are your priorities; human feedback is authoritative and overrides
everything else in this prompt's plan, including topic gaps.

Step 3. First list the child skills the knowledge base has grown:
    {{PYTHON}} {{SCRIPTS}}/skill_review.py --repo {{REPO}} list
and Read the SKILL.md of each `approved` skill relevant to the planned work —
they are house procedure. Then research and synthesize for the open inquiries
and for gaps against the `topics` in config.yml. Delegate to the
`orchestrator` agent to plan and run
this; it will dispatch `researcher` and `synthesizer` agents in isolated
worktrees ({{SCRIPTS}}/new_worktree.sh). Every new source must be captured into
raw/ before its reference note exists.

Step 4. Routine maintenance: delegate to the `note-maintainer` agent for the
fleeting sweep, INBOX-driven revisions, and link repair.

Step 5. Connector sweep — ONLY if config.yml `connector_cadence` is due (check
log.md for the last `serendipity_sweep:` entry). If due:
    {{PYTHON}} {{SCRIPTS}}/serendipity_sweep.py --repo {{REPO}}
then delegate to the `connector` agent to read both notes of each candidate,
keep and justify the real ones, and delete the rest. The critic then reviews
what survives: accepted links are written into BOTH notes, rejections logged.
The sweep never edits notes and always exits 0 — a degraded scorer is a logged
warning, not a failure.

Step 6. Delegate to the `critic` agent to gate every new or changed note:
groundedness (flag < 0.80, block < 0.70), atomicity, clarity, link quality.
A blocked note must not merge to the main branch — leave it in its worktree.

Step 7. Skill-smith retrospective — ONLY if config.yml `skill_smith_cadence`
is due (check log.md for the last `skill-smith:` entry). If due, note the
current commit (`git rev-parse HEAD`), create a worktree
({{SCRIPTS}}/new_worktree.sh) and delegate to the `skill-smith` agent inside
it: at most one proposal, only under skills/, finishing with
`skill_review.py propose` so the diff is recorded in skill-impact.md. Before
merging the worktree back, verify the smith's diff stayed in its sandbox:
    {{PYTHON}} {{SCRIPTS}}/check_skill_sandbox.py --repo <worktree> --base <noted commit> --strict
If that exits non-zero, do NOT merge the worktree; log the violation and
continue the cycle without the proposal. Do not run the A/B trial yourself:
the wrapper runs it automatically after your cycle when it sees a new
proposal recorded.

Step 8. Run the lint gates yourself and fix what they find, re-running until
clean or until nothing more can be fixed honestly:
    {{PYTHON}} {{SCRIPTS}}/verify_refs.py --repo {{REPO}} {{VERIFY_ARGS}}
    {{PYTHON}} {{SCRIPTS}}/lint_citations.py --repo {{REPO}}
    {{PYTHON}} {{SCRIPTS}}/lint_links.py --repo {{REPO}}
    {{PYTHON}} {{SCRIPTS}}/lint_skills.py --repo {{REPO}}
Never fix a lint by deleting knowledge, weakening a claim's sourcing, or
marking something verified that is not.

Step 9. Rebuild the machine-readable index:
    {{PYTHON}} {{SCRIPTS}}/build_manifest.py --repo {{REPO}}

Step 10. Update INBOX.md and inquiries/ statuses. An inquiry may only be
marked `answered` with `result_notes` naming the **permanent** notes that
answered it — lint_links fails otherwise. Leave an unresolved question as
`in-progress` and say why. Then commit everything on the main branch with one
message summarizing the run.

HARD RULES for this run:
- You NEVER run `git push`. The wrapper that launched you re-verifies the
  gates and pushes only if they pass. Committing is yours; pushing is not.
- Append-only files stay append-only: log.md, skill-impact.md.
- Never edit raw/ contents, this prompt, or anything outside {{REPO}}.
- If you run low on turns or budget, stop starting new work and bring what is
  already in progress to a clean committed-or-abandoned state; log where you
  stopped. Committing completed work takes priority over starting anything new
  once half the budget is spent.
