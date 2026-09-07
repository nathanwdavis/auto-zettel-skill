# Every command

The complete CLI surface: 21 entry points, 15 Python and 6 shell. This page is
generated from each script's own `--help`, so it cannot drift from the code —
if something here looks wrong, run the command with `--help` and trust that.

For the task-shaped view ("I want to add a source"), see the README. For what
each gate enforces, see [`quality-gates.md`](quality-gates.md).

## The contracts every script shares

- **`--repo <path>`** — the path to your *content* repo, on every script that
  touches one. (`fetch_remote.py` is the exception: its `--repo` is a GitHub
  repository *name*, because it works without a clone.)
- **`--help`** on everything, exiting 0.
- **Exit codes:** `0` success · `1` the tool worked and the answer is no (a lint
  found violations, a fetch failed) · `2` you called it wrong · `3` *(cycle
  scripts only)* a live run holds the lock — stand down, this is a success.
- **Lints** print `FILE⇥RULE⇥REASON`, one line per problem.
- **Anything that acts appends to the content repo's `log.md`.** Read-only tools
  (`query.py`, `inquiries.py`, `skill_review.py list`, `new_worktree.sh`,
  `fetch_remote.py`) do not — a query is not an operation.
- **Which python?** These examples say `capture.py`; run them with the
  interpreter your dependencies are installed in, and use an absolute path when
  a scheduler will invoke them.

## Getting things in

### `capture.py`

Turn a title and some text into well-formed content-repo artifacts.

```
usage: capture.py [-h] --repo REPO [--json] KIND ...

Turn a title and some text into well-formed content-repo artifacts.

positional arguments:
  KIND
    fleeting        a short-lived capture, swept next cycle
    inquiry         an open question, worked by a later run
    inbox           feedback or an instruction for the next run
    reference       a bibliographic record for one source (FR-4: exactly one
                    per source)
    literature      an own-words summary of exactly one source
    permanent       one atomic claim, title stated as a claim
    moc             a map of content: the notes a reader walks down to
    inquiry-update  move an inquiry along its lifecycle (status, result notes)

options:
  -h, --help        show this help message and exit
  --repo REPO       path to the content repository (default: None)
  --json            emit the created path as JSON, for programmatic callers
                    (default: False)
```

### `ingest_drops.py`

Ingest human-dropped source files into the content repo (amendment A11).

```
usage: ingest_drops.py [-h] --repo REPO [--list] [--json] [--mailto MAILTO]
                       [--offline] [--file FILE] [--title TITLE]
                       [--author AUTHOR] [--year YEAR] [--doi DOI]
                       [--isbn ISBN] [--arxiv ARXIV] [--pmid PMID] [--url URL]
                       [--source-tier SOURCE_TIER] [--priority PRIORITY]
                       [--notes NOTES] [--tags TAGS]

Ingest human-dropped source files into the content repo (amendment A11).

options:
  -h, --help            show this help message and exit
  --repo REPO           path to the content repository (default: None)
  --list                print the files waiting in drop/ and change nothing
                        (default: False)
  --json                machine-readable output (default: False)
  --mailto MAILTO       contact email for Crossref (default: config
                        fetch.mailto) (default: )
  --offline             skip the Crossref enrichment lookup (default: False)
  --file FILE           an external source file to copy into drop/ and ingest
                        now (a session attachment); only that file is ingested
                        (default: None)
  --title TITLE         sidecar field (with --file) (default: )
  --author AUTHOR       sidecar field, repeatable (with --file) (default: [])
  --year YEAR           sidecar field (with --file) (default: )
  --doi DOI             sidecar field (with --file) (default: )
  --isbn ISBN           sidecar field (with --file) (default: )
  --arxiv ARXIV         sidecar field (with --file) (default: )
  --pmid PMID           sidecar field (with --file) (default: )
  --url URL             sidecar field (with --file) (default: )
  --source-tier SOURCE_TIER
                        sidecar field (with --file) (default: )
  --priority PRIORITY   sidecar field (with --file) (default: )
  --notes NOTES         sidecar field (with --file) (default: )
  --tags TAGS           comma-separated sidecar tags (with --file) (default: )
```

### `fetch_source.py`

Fetch a source into raw/ as the capture for a reference note (amendment A11).

```
usage: fetch_source.py [-h] --repo REPO --ref REF --url URL
                       [--renderer {auto,none,jina,firecrawl}] [--no-inbox]
                       [--json]

Fetch a source into raw/ as the capture for a reference note (amendment A11).

options:
  -h, --help            show this help message and exit
  --repo REPO           path to the content repository (default: None)
  --ref REF             reference note key (or bare id) (default: None)
  --url URL             the source URL to capture (default: None)
  --renderer {auto,none,jina,firecrawl}
                        JavaScript renderer for shell pages (default: config
                        fetch.renderer) (default: auto)
  --no-inbox            on failure, do not file the INBOX 'source needed'
                        entry (default: False)
  --json                machine-readable output (default: False)
```


## Reading the base

### `query.py`

Map what a content repo already knows about a query. Read-only.

```
usage: query.py [-h] --repo REPO [--from-file PATH] [--top TOP] [--json]
                [--mermaid] [--include-raw] [--gaps N] [--file-gaps [g1,g3]]
                [query]

Map what a content repo already knows about a query. Read-only.

positional arguments:
  query                free-text question or topic (omit only with --from-
                       file) (default: )

options:
  -h, --help           show this help message and exit
  --repo REPO          path to the content repository (default: None)
  --from-file PATH     passage mode: read a capture's .txt extraction and
                       score it chunk by chunk against the notes the base
                       already has (default: None)
  --top TOP            maximum matched notes to report (default 15) (default:
                       15)
  --json               emit the report as JSON (default: False)
  --mermaid            include a Mermaid diagram of the subgraph in the report
                       (the JSON always carries it) (default: False)
  --include-raw        also scan raw/*.txt for query terms no note uses;
                       slower, and turns a research gap into a distillation
                       one (default: False)
  --gaps N             report at most N gaps, highest priority first (0 = all)
                       (default: 0)
  --file-gaps [g1,g3]  capture the suggested follow-ups (inquiries / INBOX
                       entries) through capture.py instead of only printing
                       them; bare files every one, or name the gap ids to file
                       (default: None)
```

### `inquiries.py`

List the open questions in a content repo (FR-6).

```
usage: inquiries.py [-h] --repo REPO
                    [--status {new,in-progress,answered,archived}] [--json]

List the open questions in a content repo (FR-6).

options:
  -h, --help            show this help message and exit
  --repo REPO           path to the content repository (default: None)
  --status {new,in-progress,answered,archived}
                        show only inquiries in this state (default: None)
  --json                emit JSON, for programmatic callers (default: False)
```

### `fetch_remote.py`

Mode-B container-side fetcher for a content repository (FR-23).

```
usage: fetch_remote.py [-h] (--manifest-url MANIFEST_URL | --owner OWNER)
                       [--repo REPO] [--branch BRANCH] [--out OUT]
                       [--keys KEYS]

Mode-B container-side fetcher for a content repository (FR-23).

options:
  -h, --help            show this help message and exit
  --manifest-url MANIFEST_URL
                        full URL of manifest.json (public repos) (default:
                        None)
  --owner OWNER         GitHub owner (used with --repo) (default: None)
  --repo REPO           GitHub repo name (with --owner) (default: None)
  --branch BRANCH
  --out OUT             directory to write fetched files into (default: .)
  --keys KEYS           comma-separated note keys to fetch after the manifest
                        (default: )
```


## The gates

### `verify_refs.py`

Anti-hallucination verification for reference notes (FR-10, FR-22).

```
usage: verify_refs.py [-h] --repo REPO [--offline] [--mailto MAILTO]
                      [--no-render]

Anti-hallucination verification for reference notes (FR-10, FR-22).

options:
  -h, --help       show this help message and exit
  --repo REPO      path to the content repository (default: None)
  --offline        skip all network lookups; verify from raw/ captures only
                   (default: False)
  --mailto MAILTO  contact email sent to Crossref for polite-pool routing
                   (default: )
  --no-render      do not refresh chicago_note/chicago_bib from csl_json
                   (default: False)
```

### `build_manifest.py`

Regenerate manifest.json from note frontmatter (FR-3, FR-19).

```
usage: build_manifest.py [-h] --repo REPO [--check]

Regenerate manifest.json from note frontmatter (FR-3, FR-19).

options:
  -h, --help   show this help message and exit
  --repo REPO  path to the content repository (default: None)
  --check      verify the manifest is up to date without writing it (default:
               False)
```

### `lint_citations.py`

Citation-grounding gate (FR-11, FR-12, FR-20).

```
usage: lint_citations.py [-h] --repo REPO

Citation-grounding gate (FR-11, FR-12, FR-20).

options:
  -h, --help   show this help message and exit
  --repo REPO  path to the content repository (default: None)
```

### `lint_links.py`

Link, layering, and note-identity lint (FR-21).

```
usage: lint_links.py [-h] --repo REPO

Link, layering, and note-identity lint (FR-21).

options:
  -h, --help   show this help message and exit
  --repo REPO  path to the content repository (default: None)
```

### `lint_skills.py`

Skill-layer wellformedness gate (FR-33, AC-34, AC-36).

```
usage: lint_skills.py [-h] --repo REPO

Skill-layer wellformedness gate (FR-33, AC-34, AC-36).

options:
  -h, --help   show this help message and exit
  --repo REPO  path to the content repository (default: None)
```

### `check_skill_sandbox.py`

Skill-sandbox gate: a cycle's diff may not escape the FR-37 rails (AC-37).

```
usage: check_skill_sandbox.py [-h] --repo REPO --base BASE [--strict]

Skill-sandbox gate: a cycle's diff may not escape the FR-37 rails (AC-37).

options:
  -h, --help   show this help message and exit
  --repo REPO  path to the content repository (default: None)
  --base BASE  git ref the cycle started from (e.g. the pre-run HEAD)
               (default: None)
  --strict     reject any change outside skills/, skill-impact.md, log.md (for
               the skill-smith's isolated diff) (default: False)
```


## Cycles and scheduling

### `session_cycle.sh`

Open a session-driven cycle: answer a question, ingest a source, or close the

```
Usage: session_cycle.sh <ask|ingest|query> --repo <content-repo> [options]

  ask    --question "<text>" [--priority low|normal|high] [--body TEXT|-]
         File the question as an inquiry and research it now.

  ingest --source <file> [--title ...] [--author ...] [--year ...] [--doi ...]
         [--isbn ...] [--arxiv ...] [--pmid ...] [--url ...] [--source-tier ...]
         [--priority ...] [--notes ...] [--tags a,b]
         Ingest a source this session was handed, then write its notes.

  query  --from-query "<text>" [--top N]
         File the gaps a query finds, on the run branch, and work them.

Each claims the run lock, opens a run branch, and prints a checklist. Hand off
with: remote_cycle.sh finish --repo <path>

Exit codes: 0 ok; 3 lock held by a live run (stand down); 1 failure; 2 usage.
```

### `remote_cycle.sh`

Scaffolding for a maintenance cycle where the SESSION is the agent.

```
Usage: remote_cycle.sh <start|gates|finish|abort|status|refresh-skill> --repo <content-repo> [options]

  start   --repo <path> [--ttl <hours>]   refresh this skill checkout, claim
                                          lock, pull, create run branch
  gates   --repo <path> [--online]        run the merge gates as CI runs them
          [--mailto <email>] [--base <rev>]
  finish  --repo <path> [--title <text>]  gate, commit, push branch, open PR,
          [--no-gates]                    auto-merge
  abort   --repo <path>                   release the lock, keep the branch
  status  --repo <path>                   report lock holder and branch
  refresh-skill                           fast-forward this skill checkout itself
                                          (start also does this; takes no --repo)

Exit codes: 0 ok; 3 lock held by a live run (not an error -- stand down); 2 usage error; 1 failure.
```

### `maintenance_run.sh`

Cron entrypoint for a zettel-bootstrap maintenance run (FR-25, FR-28, FR-30).

```
Usage: maintenance_run.sh --repo <content-repo> [--mailto <email>]
                          [--dry-run] [--claude-bin <path>]

  --repo        path to the content repository (required)
  --mailto      contact email for Crossref polite-pool routing
  --dry-run     run everything, including the gates, but never push
  --claude-bin  claude binary to invoke              [default: claude]

Environment: CLAUDE_BIN, PYTHON, STALE_LOCK_HOURS override defaults.
Exit codes: 0 ok (or lock held by a fresh run); 2 usage error; 1 any other failure.
```

### `adhoc_research.sh`

Open an ad-hoc research cycle for one question.

```
Usage: adhoc_research.sh --repo <content-repo> --question "<text>" [options]

  --repo      path to the content repository (required)
  --question  the question to research (required)
  --priority  low | normal | high                        [default: normal]
  --body      extra context, or '-' to read stdin

Claims the run lock, records the question as an inquiry, and creates the run
branch. Research, then hand off with: remote_cycle.sh finish --repo <path>

The same cycle is available as `session_cycle.sh ask`, alongside `ingest`
(a source this session was handed) and `query` (close the gaps a query found).

Exit codes: 0 ok; 3 lock held by a live run (stand down); 1 failure; 2 usage.
```

### `new_worktree.sh`

Create (or remove) an isolated git worktree for a subagent (FR-26).

```
Usage: new_worktree.sh --repo <content-repo> --name <branch> [--remove]

  --repo    path to the content repository (required)
  --name    branch name for the worktree (required)
  --remove  remove the worktree and delete its branch instead of creating it

On create, prints the worktree path on stdout (the only stdout output), so
callers can capture it: WT=$(new_worktree.sh --repo r --name n).
```


## Genesis

### `init_content_repo.sh`

Scaffold and publish a zettelkasten content repository (FR-18).

```
Usage: init_content_repo.sh --name <repo> --visibility <public|private> --owner <gh-owner>
                            --topics "<csv>" [--cadence <str>] [--budget <usd>]
                            [--max-turns <n>] [--dir <path>] [--no-remote]

  --name         content repository name (required)
  --visibility   public or private (required)
  --owner        GitHub user or org that will own the repo (required)
  --topics       comma-separated seed topics (required)
  --cadence      maintenance cadence, cron-like or human   [default: weekly]
  --budget       per-run USD cap                            [default: 5]
  --max-turns    per-run turn cap                           [default: 40]
  --dir          local path to scaffold into  [default: ./<name>]
  --no-remote    scaffold and commit locally; skip gh repo create and push
```


## Serendipity and child skills

### `serendipity_sweep.py`

Propose cross-community links between notes (FR-24).

```
usage: serendipity_sweep.py [-h] --repo REPO [--threshold THRESHOLD]
                            [--out OUT] [--max-proposals MAX_PROPOSALS]
                            [--force-lexical]

Propose cross-community links between notes (FR-24).

options:
  -h, --help            show this help message and exit
  --repo REPO           path to the content repository (default: None)
  --threshold THRESHOLD
                        minimum similarity to propose (default: the chosen
                        scorer's calibrated value) (default: None)
  --out OUT             repo-relative directory for proposals (default:
                        proposed-links)
  --max-proposals MAX_PROPOSALS
                        cap on proposals written per sweep (default: 10)
  --force-lexical       always use stdlib lexical scoring, ignoring config
                        (default: False)
```

### `skill_review.py`

Child-skill lifecycle: propose, list, promote, reject (FR-35/FR-36).

```
usage: skill_review.py [-h] --repo REPO {propose,list,promote,reject} ...

Child-skill lifecycle: propose, list, promote, reject (FR-35/FR-36).

positional arguments:
  {propose,list,promote,reject}
    propose             record a proposal in skill-impact.md
    list                list child skills and their status
    promote             approve a proposed skill (human act)
    reject              revert a skill to its last approved state and record
                        why (human act)

options:
  -h, --help            show this help message and exit
  --repo REPO           path to the content repository (default: None)
```

### `skill_trial.py`

A/B trial for a candidate child skill on the repo's own inquiries (FR-36).

```
usage: skill_trial.py [-h] --repo REPO --skill SKILL [--questions QUESTIONS]
                      [--claude-bin CLAUDE_BIN] [--model MODEL]
                      [--max-turns MAX_TURNS] [--out OUT] [--seed SEED]

A/B trial for a candidate child skill on the repo's own inquiries (FR-36).

options:
  -h, --help            show this help message and exit
  --repo REPO           path to the content repository (default: None)
  --skill SKILL         candidate child skill under skills/ (default: None)
  --questions QUESTIONS
                        inquiry questions per arm [default: config
                        trial_questions, else 3] (default: None)
  --claude-bin CLAUDE_BIN
                        claude binary to invoke [default: $CLAUDE_BIN, else
                        'claude'] (default: claude)
  --model MODEL         model for answer+judge calls [default: config
                        models.cheap] (default: None)
  --max-turns MAX_TURNS
                        turn cap per answer/judge call; bounds trial cost
                        [default: 15] (default: 15)
  --out OUT             scores JSON path [default: the runs directory]
                        (default: None)
  --seed SEED           randomization seed for the judge's arm order (default:
                        None)
```

---

**Next:** [`../README.md`](../README.md) for the task-shaped view, or [`tutorial.md`](tutorial.md) to see them in sequence.
All reference docs: [`README.md`](README.md).
