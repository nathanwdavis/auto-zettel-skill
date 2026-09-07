# Reference documentation

Fourteen documents. This page exists so you can find the right one without
reading all of them — each is written to be read on its own.

New here? [`../README.md`](../README.md) explains what this is, and
[`tutorial.md`](tutorial.md) walks a topic from genesis to a scheduled run.

## Understand the system

| | |
|---|---|
| [`architecture.md`](architecture.md) | The two repositories, the Raw / Knowledge / Skill layers, the content-repo layout, and why the gates run in the order they do. |
| [`note-types.md`](note-types.md) | Every note type and the rules binding it: note identity, the 1-1-1 rule, the eight typed relations, the inquiry lifecycle. |
| [`quality-gates.md`](quality-gates.md) | Each gate, what it enforces, what it rejects, where it binds, and the exit-code contract. |

## Do something

| | |
|---|---|
| [`tutorial.md`](tutorial.md) | Genesis to first scheduled run, end to end, with real output. |
| [`commands.md`](commands.md) | Every entry point and every flag, generated from each script's `--help`. |
| [`capture.md`](capture.md) | The four routes in, the note generators, inquiries, the drop box, the three session flows. |
| [`query.md`](query.md) | How notes are ranked, the typed-edge graph, passage mode, and the eight kinds of gap. |
| [`scheduling.md`](scheduling.md) | Cron, launchd, desktop tasks, cloud Routines, and what a scheduled run guarantees. |

## Deeper

| | |
|---|---|
| [`citation-rules.md`](citation-rules.md) | CSL-JSON, Chicago rendering, the verification rule, source tiers, and what the citation gate rejects. |
| [`remote-execution.md`](remote-execution.md) | Routine-fired cycles, the git-branch lock, cloud environments, and the content repo's required check. |
| [`two-mode-access.md`](two-mode-access.md) | Reading a knowledge base with no local clone, and the five remote paths in preference order. |
| [`serendipity.md`](serendipity.md) | How cross-community link candidates are chosen, the two scoring backends, and why the sweep proposes rather than links. |
| [`orchestra.md`](orchestra.md) | The eight subagents, their model tiers, what each may write, and where push authority lives. |
| [`skill-emergence.md`](skill-emergence.md) | How the base proposes, A/B-trials and promotes its own child skills, and the rails around it. |

The specification is [`../docs/REQUIREMENTS.md`](../docs/REQUIREMENTS.md) —
FR-x, AC-x, NFR-x, QA-x, and the numbered amendments recording every place
implementation forced a change to it.
