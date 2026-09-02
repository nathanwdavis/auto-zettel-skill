#!/usr/bin/env python3
"""Child-skill lifecycle: propose, list, promote, reject (FR-35/FR-36).

The skill layer is the only rollbackable layer (FR-33), and this script is
where that asymmetry becomes mechanical:

- ``propose`` records a proposal in skill-impact.md with its unified diff,
  captured NOW — at proposal time the diff against the cycle base is cheap
  and unambiguous, where reconstructing it at decision time is neither
  (amendment A7). Run by the skill-smith as its final act.
- ``promote`` / ``reject`` implement the human decision FR-36 requires.
  Rejection restores ``skills/<name>/`` to its last *approved* commit (or
  removes it, for a rejected create) and records the outcome permanently;
  it stages only the skill layer plus the two ledgers and refuses anything
  else, which is AC-33 — knowledge is never rolled back — made structural.
- ``list`` is the one command maintenance prompts use to find approved
  skills to read as house procedure.

Promotion is a human act: nothing here runs unattended except ``propose``.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib import impact
from zettel_lib.cli import EXIT_OK, EXIT_USAGE, EXIT_VIOLATION, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, dump, split
from zettel_lib.gitlock import EMPTY_TREE
from zettel_lib.repo import ContentRepo
from zettel_lib.sandbox import is_allowed_path

PROPOSAL_ID_RE = re.compile(r"^\d{12}$")


def die(message: str, code: int = EXIT_USAGE) -> "SystemExit":
    print(f"error: {message}", file=sys.stderr)
    return SystemExit(code)


def _git(repo: ContentRepo, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", str(repo.root), *args],
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise die(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc


def _require_git(repo: ContentRepo) -> None:
    if _git(repo, "rev-parse", "--git-dir", check=False).returncode != 0:
        raise die(f"{repo.root} is not a git repository; the review flow "
                  "needs history to capture diffs and restore points")


def _purpose(repo: ContentRepo, skill: str) -> tuple[Path, dict, str]:
    path = repo.root / "skills" / skill / "PURPOSE.md"
    if not path.exists():
        raise die(f"skills/{skill}/PURPOSE.md does not exist")
    try:
        meta, body = split(path.read_text(encoding="utf-8"))
    except FrontmatterError as exc:
        raise die(str(exc))
    return path, meta, body


def _today() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")


def _scores_summary(scores_path: str | None) -> str:
    if not scores_path:
        return ""
    data = json.loads(Path(scores_path).read_text(encoding="utf-8"))
    means = data.get("means", {})
    n = len(data.get("questions", []))
    with_mean, without_mean = means.get("with"), means.get("without")
    if with_mean is None or without_mean is None:
        return ""
    return f"with={with_mean} without={without_mean} (n={n})"


def _commit_skill_change(repo: ContentRepo, skill: str, message: str) -> None:
    """Stage only the skill layer + ledgers, prove it, commit.

    The staged-set assertion is deliberate paranoia: this script dogfoods the
    same path classifier the sandbox gate uses, so a promotion or rejection
    can never smuggle a knowledge-layer change into its commit (AC-33).
    """
    _git(repo, "add", "-A", "--", f"skills/{skill}", "skill-impact.md", "log.md")
    staged = _git(repo, "diff", "--cached", "--name-only").stdout.splitlines()
    offending = [p for p in staged if not is_allowed_path(p)]
    if offending:
        raise die("refusing to commit: staged paths outside the skill layer: "
                  + ", ".join(offending), EXIT_VIOLATION)
    _git(repo, "-c", "user.name=zettel-bootstrap",
         "-c", "user.email=noreply@localhost", "commit", "-q", "-m", message)


def _require_clean_index(repo: ContentRepo) -> None:
    if _git(repo, "diff", "--cached", "--quiet", check=False).returncode != 0:
        raise die("the git index already has staged changes; commit or reset "
                  "them first so the decision commit stays skill-layer-only")


# -- propose -------------------------------------------------------------------

#: log.md lines that open a cycle and lines that close one. A proposal is
#: "this cycle's" when the newest open marker has no close marker after it.
CYCLE_OPEN = ("maintenance_run: start (", "remote_cycle: start (")
CYCLE_CLOSE = ("maintenance_run: headless run complete", "maintenance_run: ABORT",
               "maintenance_run: SANDBOX VIOLATION", "remote_cycle: finish ",
               "remote_cycle: lock released")
PROPOSED = "skill-smith: proposed "


def proposal_this_cycle(repo: ContentRepo) -> str:
    """The skill already proposed in the open cycle, or "" (FR-35, AC-35).

    "Exactly one proposal per cycle" was prose in the smith's definition and
    both prompts; nothing refused a second one. The cycle is read from log.md:
    the wrapper and remote_cycle.sh stamp its start, and the headless run
    completing (laptop) or `finish`/abort (remote) closes it. A hand-run
    propose outside any open cycle is always allowed -- that is how a human
    records a proposal of their own.
    """
    newest = ""
    for line in reversed(repo.log_lines()):
        if line.startswith(CYCLE_CLOSE):
            return ""
        if line.startswith(CYCLE_OPEN):
            return newest
        if line.startswith(PROPOSED) and not newest:
            newest = line[len(PROPOSED):].split(" ", 1)[0]
    return ""


def cmd_propose(repo: ContentRepo, args) -> int:
    _require_git(repo)
    skill = args.skill
    skill_dir = repo.root / "skills" / skill
    if not (skill_dir / "SKILL.md").exists():
        raise die(f"skills/{skill}/SKILL.md does not exist — write the "
                  "proposal files first, then record it")
    path, meta, _ = _purpose(repo, skill)

    if args.kind == "create" and skill in impact.rejected_creates(repo):
        print(f"skills/{skill}\tre-proposed-skill\ta create of this name was "
              "rejected in skill-impact.md and is never retried (AC-36)")
        repo.append_log(f"skill-smith: REFUSED re-proposal of rejected create {skill}")
        return EXIT_VIOLATION

    earlier = proposal_this_cycle(repo)
    if earlier:
        print(f"skills/{skill}\tsecond-proposal\tthis cycle already proposed "
              f"{earlier}; FR-35 allows exactly one proposal per cycle")
        repo.append_log(f"skill-smith: REFUSED second proposal {skill} "
                        f"(this cycle already proposed {earlier})")
        return EXIT_VIOLATION

    # A patch re-enters review carrying the PURPOSE.md of an earlier proposal,
    # so an id that already appears in skill-impact.md is spent — every
    # proposal event gets its own id or the tracker's history goes ambiguous.
    used = {r.proposal_id for r in impact.records(repo)}
    proposal_id = str(meta.get("proposal_id", ""))
    if not PROPOSAL_ID_RE.match(proposal_id) or proposal_id in used:
        # Minute-resolution ids collide when two proposals land in the same
        # minute (a rejected run retried, say) — bump until unused.
        when = _dt.datetime.now(_dt.timezone.utc)
        while when.strftime("%Y%m%d%H%M") in used:
            when += _dt.timedelta(minutes=1)
        proposal_id = when.strftime("%Y%m%d%H%M")
        meta2, body = split(path.read_text(encoding="utf-8"))
        meta2["proposal_id"] = proposal_id
        path.write_text(dump(meta2, body), encoding="utf-8")

    # The FR-36 unified diff, captured while the base is unambiguous. Untracked
    # proposal files need --no-index against /dev/null (git diff <base> only
    # sees tracked paths); --no-index exits 1 on difference by design.
    diff = _git(repo, "diff", args.base, "--", f"skills/{skill}").stdout
    tracked = set(_git(repo, "ls-files", "--", f"skills/{skill}").stdout.splitlines())
    for f in sorted(skill_dir.iterdir()):
        rel = f"skills/{skill}/{f.name}"
        if rel not in tracked:
            diff += _git(repo, "diff", "--no-index", "--", "/dev/null", rel,
                         check=False).stdout
    impact.append_record(repo, impact.Record(
        proposal_id=proposal_id, event="proposed", skill=skill,
        date=_today(), kind=args.kind, text=args.motivation, diff=diff))
    repo.append_log(f"skill-smith: proposed {skill} ({args.kind}, {proposal_id})")
    print(f"proposed {skill} ({args.kind}, {proposal_id})")
    return EXIT_OK


# -- list ----------------------------------------------------------------------

def cmd_list(repo: ContentRepo, args) -> int:
    rows = []
    skills_dir = repo.root / "skills"
    if skills_dir.is_dir():
        for entry in sorted(skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            try:
                _, meta, _ = _purpose(repo, entry.name)
            except SystemExit:
                meta = {}
            rows.append({
                "skill": entry.name,
                "status": str(meta.get("status", "?")),
                "proposal_id": str(meta.get("proposal_id", "")),
                "proposed": str(meta.get("proposed", "")),
                "decided": str(meta.get("decided", "")),
            })
    if args.json:
        print(json.dumps(rows, indent=2))
    elif rows:
        for r in rows:
            print(f"{r['skill']}\t{r['status']}\t{r['proposal_id']}"
                  f"\t{r['decided'] or '-'}")
    else:
        print("no child skills")
    return EXIT_OK


# -- promote -------------------------------------------------------------------

def cmd_promote(repo: ContentRepo, args) -> int:
    _require_git(repo)
    _require_clean_index(repo)
    skill = args.skill

    import lint_skills
    blocking = [v for v in lint_skills.lint(repo)
                if v.file.startswith(f"skills/{skill}")]
    if blocking:
        for v in blocking:
            print(v.render())
        raise die(f"skills/{skill} does not pass lint_skills; fix it before "
                  "promoting", EXIT_VIOLATION)

    path, meta, body = _purpose(repo, skill)
    if str(meta.get("status")) != "proposed":
        raise die(f"skills/{skill} has status '{meta.get('status')}'; only a "
                  "proposed skill can be promoted")
    meta["status"] = "approved"
    meta["decided"] = _today()
    body = body.rstrip("\n") + f"\n| {_today()} | promoted | Accepted |\n"
    path.write_text(dump(meta, body), encoding="utf-8")

    scores = _scores_summary(args.scores)
    impact.append_record(repo, impact.Record(
        proposal_id=str(meta.get("proposal_id", "")) or "000000000000",
        event="Accepted", skill=skill, date=_today(),
        kind=str(meta.get("kind", "")), text=args.reason, scores=scores))
    repo.append_log(f"skill_review: Accepted {skill} — {args.reason}")
    _commit_skill_change(repo, skill, f"Promote child skill {skill}\n\n{args.reason}")
    print(f"Accepted {skill}")
    return EXIT_OK


# -- reject --------------------------------------------------------------------

def cmd_reject(repo: ContentRepo, args) -> int:
    _require_git(repo)
    _require_clean_index(repo)
    skill = args.skill
    skill_dir = repo.root / "skills" / skill
    if not skill_dir.is_dir():
        raise die(f"skills/{skill} does not exist")
    if _git(repo, "status", "--porcelain", "--", f"skills/{skill}").stdout.strip():
        raise die(f"skills/{skill} has uncommitted changes; the rejection "
                  "reverts committed history — commit or discard them first")

    _, meta, _ = _purpose(repo, skill)
    proposal_id = str(meta.get("proposal_id", "")) or "000000000000"
    # What was rejected is the *proposal*, so its kind comes from the proposed
    # record — a patch to a skill whose PURPOSE still says kind: create must
    # not read as a rejected create, which would ban the name forever (A7).
    kind = next((r.kind for r in impact.records(repo)
                 if r.event == "proposed" and r.proposal_id == proposal_id),
                str(meta.get("kind", "")))

    # The restore point is the newest commit whose PURPOSE.md was 'approved' —
    # FR-36's "last approved configuration". A rejected create has none, so
    # its restoration is removal.
    restore = None
    for commit in _git(repo, "log", "--format=%H", "--",
                       f"skills/{skill}").stdout.splitlines():
        shown = _git(repo, "show", f"{commit}:skills/{skill}/PURPOSE.md",
                     check=False)
        if shown.returncode != 0:
            continue
        try:
            old_meta, _ = split(shown.stdout)
        except FrontmatterError:
            continue
        if str(old_meta.get("status")) == "approved":
            restore = commit
            break

    diff = _git(repo, "diff", restore or EMPTY_TREE, "HEAD", "--",
                f"skills/{skill}").stdout
    scores = _scores_summary(args.scores)
    impact.append_record(repo, impact.Record(
        proposal_id=proposal_id, event="Rejected", skill=skill,
        date=_today(), kind=kind, text=args.reason, scores=scores, diff=diff))

    # Revert the skill layer only: wipe, then restore the approved state if
    # one exists. rm-then-checkout also drops files added after the restore
    # point, which plain `git checkout <ref> -- path` would leave behind.
    for f in sorted(skill_dir.rglob("*"), reverse=True):
        f.unlink() if f.is_file() else f.rmdir()
    skill_dir.rmdir()
    if restore:
        _git(repo, "checkout", restore, "--", f"skills/{skill}")

    repo.append_log(f"skill_review: Rejected {skill} — {args.reason}")
    _commit_skill_change(repo, skill, f"Reject child skill {skill}\n\n{args.reason}")
    print(f"Rejected {skill}" + (" (reverted to last approved state)"
                                 if restore else " (removed)"))
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("propose", help="record a proposal in skill-impact.md")
    p.add_argument("--skill", required=True)
    p.add_argument("--kind", required=True, choices=("create", "patch"))
    p.add_argument("--motivation", required=True)
    p.add_argument("--base", default="HEAD",
                   help="git ref the proposal diff is captured against")

    p = sub.add_parser("list", help="list child skills and their status")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("promote", help="approve a proposed skill (human act)")
    p.add_argument("--skill", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--scores", help="trial scores JSON from skill_trial.py")

    p = sub.add_parser("reject", help="revert a skill to its last approved "
                                      "state and record why (human act)")
    p.add_argument("--skill", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--scores", help="trial scores JSON from skill_trial.py")

    args = parser.parse_args(argv)
    repo = open_repo(args.repo)
    handler = {"propose": cmd_propose, "list": cmd_list,
               "promote": cmd_promote, "reject": cmd_reject}[args.command]
    return handler(repo, args)


if __name__ == "__main__":
    raise SystemExit(main())
