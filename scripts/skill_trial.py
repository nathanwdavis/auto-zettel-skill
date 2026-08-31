#!/usr/bin/env python3
"""A/B trial for a candidate child skill on the repo's own inquiries (FR-36).

Answers the question a human approver actually has — *do answers get better
with this skill in the tree?* — by answering N inquiry questions twice, in
two throwaway copies of the repo: one carrying ``skills/<name>/``, one with
it removed. The copy is the isolation: both arms get the *same* prompt, so
the candidate's presence in the tree is the only variable, and the answer
sessions run read-only (Read/Glob/Grep), so a trial can never touch the
knowledge layer.

Per question the trial spends three model calls, not four: two answer calls
(one per arm) and ONE paired judge call that scores both answers side by side
against the critic rubric — cheaper, and side-by-side judging is also less
noisy than two absolute scores. Arm order in the judge prompt is randomized
against position bias. Citation coverage costs zero calls: it is the fraction
of ``[[key]]`` wikilinks in the answer that resolve against manifest.json.

Scores JSON lands in the runs directory (never inside the repo — the skill
dir must stay the two-file unit lint_skills enforces); the means are appended
to skill-impact.md as a ``trial`` record. Promotion still requires a human:
this trial is decision support, not a decision (QA-5).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import random
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inquiries import collect
from lint_links import WIKILINK, resolve
from zettel_lib import impact
from zettel_lib.cli import EXIT_OK, EXIT_USAGE, EXIT_VIOLATION, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, split
from zettel_lib.repo import ContentRepo, dig

ANSWER_PROMPT = """\
You are answering one question from a zettelkasten content repository, using
ONLY the notes in the current directory. Before answering, check the skills/
directory: if it contains a skill whose SKILL.md is relevant to the question,
read it and follow its procedure. Ground every claim in a note and cite the
notes you used as [[key]] wikilinks. Answer concisely.

Question: {question}
"""

JUDGE_PROMPT = """\
You are judging two answers to the same question from a zettelkasten content
repository, using the critic rubric: groundedness is the degree to which every
claim traces to a cited note that actually supports it (verify citations by
reading the notes; 0.80 is the flag line, 0.70 the block line). Do not reward
length or style.

Question: {question}

=== Answer A ===
{answer_a}

=== Answer B ===
{answer_b}

Reply with ONLY a JSON object: {{"a": <groundedness 0..1>, "b": <groundedness 0..1>}}
"""

COPY_IGNORE = shutil.ignore_patterns(".git", ".worktrees", "run.lock", ".venv")


class TrialError(RuntimeError):
    pass


def _claude(claude_bin: str, prompt: str, cwd: Path, model: str,
            max_turns: int) -> str:
    proc = subprocess.run(
        [claude_bin, "-p", prompt, "--model", model,
         "--max-turns", str(max_turns), "--output-format", "json",
         "--allowedTools", "Read,Glob,Grep", "--permission-mode", "dontAsk"],
        cwd=str(cwd), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise TrialError(
            f"claude exited {proc.returncode}: {proc.stderr.strip()[:500]}")
    try:
        return str(json.loads(proc.stdout).get("result", ""))
    except json.JSONDecodeError:
        return proc.stdout


def _coverage(answer: str, keys: set[str], id_to_key: dict[str, str]) -> float:
    links = [m.group(1) for m in WIKILINK.finditer(answer)]
    if not links:
        return 0.0
    resolved = sum(1 for target in links if resolve(target, keys, id_to_key))
    return round(resolved / len(links), 3)


def _judge_scores(raw: str) -> tuple[float, float]:
    m = re.search(r'\{[^{}]*"a"[^{}]*\}', raw)
    if not m:
        raise TrialError(f"judge reply carried no score JSON: {raw[:200]}")
    data = json.loads(m.group(0))
    return float(data["a"]), float(data["b"])


def run_trial(repo: ContentRepo, args) -> dict:
    skill_dir = repo.root / "skills" / args.skill
    if not (skill_dir / "SKILL.md").exists():
        raise TrialError(f"skills/{args.skill}/SKILL.md does not exist")

    questions = [r["question"] for r in collect(repo)
                 if r["status"] in ("new", "in-progress", "answered")]
    questions = questions[: args.questions]
    if not questions:
        raise TrialError("no inquiries to trial against; capture some first")

    manifest = json.loads((repo.root / "manifest.json").read_text(encoding="utf-8"))
    keys = {n["key"] for n in manifest.get("notes", []) if n.get("key")}
    id_to_key = dict(manifest.get("id_to_key") or {})

    work = Path(args.workdir) if args.workdir else repo.root.parent / (
        repo.root.name + f"-trial-{os.getpid()}")
    arms: dict[str, Path] = {}
    results = []
    try:
        for arm in ("with", "without"):
            dst = work / arm
            shutil.copytree(repo.root, dst, ignore=COPY_IGNORE)
            if arm == "without":
                shutil.rmtree(dst / "skills" / args.skill)
            arms[arm] = dst

        rng = random.Random(args.seed)
        for question in questions:
            answers = {
                arm: _claude(args.claude_bin,
                             ANSWER_PROMPT.format(question=question),
                             arms[arm], args.model, args.max_turns)
                for arm in ("with", "without")
            }
            first, second = (("with", "without") if rng.random() < 0.5
                             else ("without", "with"))
            a_score, b_score = _judge_scores(_claude(
                args.claude_bin,
                JUDGE_PROMPT.format(question=question,
                                    answer_a=answers[first],
                                    answer_b=answers[second]),
                repo.root, args.model, args.max_turns))
            groundedness = {first: a_score, second: b_score}
            entry = {"question": question}
            for arm in ("with", "without"):
                cov = _coverage(answers[arm], keys, id_to_key)
                entry[arm] = {
                    "answer": answers[arm],
                    "groundedness": groundedness[arm],
                    "coverage": cov,
                    "score": round((groundedness[arm] + cov) / 2, 3),
                }
            results.append(entry)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    means = {
        arm: round(sum(r[arm]["score"] for r in results) / len(results), 3)
        for arm in ("with", "without")
    }
    return {
        "skill": args.skill,
        "generated": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": args.model,
        "questions": results,
        "means": means,
        "delta": round(means["with"] - means["without"], 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("--skill", required=True,
                        help="candidate child skill under skills/")
    parser.add_argument("--questions", type=int, default=None,
                        help="inquiry questions per arm "
                             "[default: config trial_questions, else 3]")
    parser.add_argument("--claude-bin",
                        default=os.environ.get("CLAUDE_BIN", "claude"))
    parser.add_argument("--model", default=None,
                        help="model for answer+judge calls "
                             "[default: config models.cheap]")
    parser.add_argument("--max-turns", type=int, default=15)
    parser.add_argument("--out", type=Path, default=None,
                        help="scores JSON path [default: the runs directory]")
    parser.add_argument("--workdir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--seed", type=int, default=None,
                        help="randomization seed for the judge's arm order")
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)

    cfg = repo.config()
    if args.questions is None:
        args.questions = int(dig(cfg, "trial_questions") or 3)
    if args.model is None:
        args.model = str(dig(cfg, "models.cheap") or "")
        if not args.model:
            print("error: no --model and no models.cheap in config.yml",
                  file=sys.stderr)
            return EXIT_USAGE

    try:
        trial = run_trial(repo, args)
    except (TrialError, FrontmatterError, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        repo.append_log(f"skill_trial: FAILED for {args.skill} ({exc})")
        return EXIT_VIOLATION

    out = args.out
    if out is None:
        runs_dir = Path(os.environ.get(
            "RESULTS_DIR", repo.root.parent / f"{repo.root.name}-runs"))
        runs_dir.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d%H%M%S")
        out = runs_dir / f"trial-{args.skill}-{stamp}.json"
    out.write_text(json.dumps(trial, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    scores = (f"with={trial['means']['with']} "
              f"without={trial['means']['without']} "
              f"(n={len(trial['questions'])})")
    purpose = repo.root / "skills" / args.skill / "PURPOSE.md"
    meta, _ = split(purpose.read_text(encoding="utf-8"))
    impact.append_record(repo, impact.Record(
        proposal_id=str(meta.get("proposal_id", "")) or "000000000000",
        event="trial", skill=args.skill,
        scores=scores, extra={"scores-file": out.name}))
    repo.append_log(f"skill_trial: {args.skill} {scores}")
    print(f"trial complete: {scores} -> {out}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
