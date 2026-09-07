"""Content-repo discovery, note loading, and the append-only run log."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Iterable, Iterator

import yaml

from .frontmatter import Note

NOTE_DIRS = ("fleeting", "literature", "permanent", "reference", "moc")
INQUIRY_DIR = "inquiries"
SUBSTRATE_DIRS = NOTE_DIRS + (INQUIRY_DIR, "raw", "skills", "proposed-links", ".bib")

#: FR-6 lifecycle. A run works `new` first and never touches `archived`.
INQUIRY_STATUSES = ("new", "in-progress", "answered", "archived")

#: The FR-5 typed-link taxonomy. Lives here rather than in lint_links because
#: it is now enforced in two places -- the lint that fails a bad relation, and
#: capture.py, which refuses to WRITE one. A generator holding its own copy of
#: the closed set would eventually mint links its own gate rejects.
RELATIONS = frozenset({
    "supports", "contradicts", "analogous", "shared-concept",
    "historical-connection", "elaborates", "refutes", "source",
})

#: The QA-3 source tiers, strongest first. Lives here for the same reason
#: RELATIONS does: three entry points read them -- lint_citations (which warns
#: on a claim grounded only in the weak tier), capture.py (which refuses to
#: WRITE a tier outside the set), and query.py (whose `weak-sourcing` gap must
#: be the SAME predicate the lint warns on, not a second one wearing the name).
SOURCE_TIERS = ("peer-reviewed", "primary-text", "reputable-secondary", "general-web")
STRONG_TIERS = frozenset({"peer-reviewed", "primary-text", "reputable-secondary"})
WEAK_TIER = "general-web"

#: Every FR-2 key, as dotted paths. The one list both maintenance paths
#: validate against (AC-2): the laptop wrapper used to carry its own copy and
#: the remote path had none, so a content repo missing `cadence` ran fine on
#: a Routine and died on a laptop. `autonomy_level` is required because FR-2
#: names it, though no code path reads it yet (A9).
REQUIRED_CONFIG_KEYS = (
    "topics", "cadence", "budget.usd", "budget.max_turns", "autonomy_level",
    "content_repo.name", "content_repo.owner", "content_repo.visibility",
    "embedding.enabled", "embedding.model",
    "models.strong", "models.cheap", "connector_cadence", "skill_smith_cadence",
)


class ContentRepoError(RuntimeError):
    pass


class ContentRepo:
    """A scaffolded content repository on disk."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ContentRepoError(f"not a directory: {self.root}")

    # -- config ---------------------------------------------------------------
    @property
    def config_path(self) -> Path:
        return self.root / "config.yml"

    def config(self) -> dict:
        if not self.config_path.exists():
            raise ContentRepoError(f"missing config.yml in {self.root}")
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ContentRepoError("config.yml must be a YAML mapping")
        return data

    def require_config(self, *keys: str) -> dict:
        """Load config.yml, hard-failing with a clear message on missing keys (AC-2)."""
        cfg = self.config()
        missing = [k for k in keys if dig(cfg, k) is None]
        if missing:
            raise ContentRepoError(
                "config.yml is missing required key(s): " + ", ".join(sorted(missing))
            )
        return cfg

    def visibility(self) -> str:
        return str(dig(self.config(), "content_repo.visibility") or "private")

    # -- notes ----------------------------------------------------------------
    def note_paths(self, types: Iterable[str] | None = None) -> list[Path]:
        dirs = tuple(types) if types else NOTE_DIRS
        paths: list[Path] = []
        for d in dirs:
            paths.extend(sorted((self.root / d).glob("*.md")))
        return paths

    def notes(self, types: Iterable[str] | None = None) -> Iterator[Note]:
        for path in self.note_paths(types):
            yield Note.load(path)

    # -- inquiries (FR-6) ------------------------------------------------------
    # Kept out of NOTE_DIRS deliberately: an inquiry is a question about the
    # graph, not a node in it, so it carries no links and never satisfies 1-1-1.
    def inquiry_paths(self) -> list[Path]:
        return sorted((self.root / INQUIRY_DIR).glob("*.md"))

    def inquiries(self) -> Iterator[Note]:
        for path in self.inquiry_paths():
            yield Note.load(path)

    def rel(self, path: Path) -> str:
        return str(Path(path).resolve().relative_to(self.root)).replace("\\", "/")

    # -- logging --------------------------------------------------------------
    def append_log(self, message: str) -> None:
        """Append a timestamped line to the repo's append-only log.md (NFR-2)."""
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log = self.root / "log.md"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"- `{stamp}` {message}\n")

    def log_lines(self) -> list[str]:
        """The run log's entry lines, oldest first, without the stamp prefix.

        Read-only companion to append_log for the few places that need to
        know what THIS cycle has already done (the FR-35 one-proposal guard).
        Lines that are not "- <stamp> message" entries (the heading, blank
        lines) are dropped.
        """
        log = self.root / "log.md"
        if not log.exists():
            return []
        out = []
        for line in log.read_text(encoding="utf-8").splitlines():
            if line.startswith("- `") and "` " in line[3:]:
                out.append(line[3:].split("` ", 1)[1])
        return out


DEFAULT_MAX_CAPTURE_MB = 25.0

#: query.py's thresholds (amendment A13). Optional, like `fetch:` and
#: `trial_questions` before them: absent keys mean these values, so a content
#: repo scaffolded before Phase 3 keeps working with no migration. None of them
#: joins REQUIRED_CONFIG_KEYS -- adding one would fail --check-config on every
#: repository that already exists.
DEFAULT_STALE_INQUIRY_DAYS = 30.0
DEFAULT_SAME_CLAIM = 0.35
DEFAULT_TOUCHES = 0.08


def positive_number(cfg: dict, dotted: str, default: float) -> float:
    """A positive numeric config value, defaulting when the key is absent.

    A bad value is a configuration error and says which key, rather than a
    ValueError surfacing from inside a gate with no clue where it came from.
    """
    raw = dig(cfg, dotted)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ContentRepoError(
            f"config.yml {dotted} must be a number, got {raw!r}") from None
    if value <= 0:
        raise ContentRepoError(f"config.yml {dotted} must be positive, got {raw!r}")
    return value


def max_capture_mb(cfg: dict) -> float:
    """config fetch.max_capture_mb as a number, defaulting when absent (A11)."""
    return positive_number(cfg, "fetch.max_capture_mb", DEFAULT_MAX_CAPTURE_MB)


def stale_inquiry_days(cfg: dict) -> float:
    """How old an open inquiry must be before query.py reports it as a gap.

    Deliberately NOT derived from `cadence`, which is free text ("weekly on
    Sunday at 06:00") as often as it is cron: computing days from that would be
    a guess wearing the clothes of a calculation.
    """
    return positive_number(cfg, "query.stale_inquiry_days", DEFAULT_STALE_INQUIRY_DAYS)


def passage_bands(cfg: dict) -> tuple[float, float]:
    """The (same-claim, touches) score bands for passage mode.

    Returned together because they are one decision: the calibration behind the
    defaults is in zettel_lib/passages.py, and a repo that moves one without
    the other gets a band ordering that cannot classify anything.
    """
    same = positive_number(cfg, "query.same_claim", DEFAULT_SAME_CLAIM)
    touches = positive_number(cfg, "query.touches", DEFAULT_TOUCHES)
    if touches >= same:
        raise ContentRepoError(
            f"config.yml query.touches ({touches}) must be below query.same_claim "
            f"({same}); a passage cannot be a weaker match than the weakest match")
    return same, touches


def dig(data: dict, dotted: str):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def main(argv: list[str] | None = None) -> int:
    """`python -m zettel_lib.repo --repo <path> --check-config`

    The shell entry points cannot import require_config, so this is how
    remote_cycle.sh and maintenance_run.sh both validate config.yml against
    the same key list before doing any work.
    """
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="content-repo config checks (AC-2)")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--check-config", action="store_true",
                        help="hard-fail unless every FR-2 key is present")
    args = parser.parse_args(argv)
    try:
        repo = ContentRepo(args.repo)
        if args.check_config:
            repo.require_config(*REQUIRED_CONFIG_KEYS)
            print(f"config.yml: all {len(REQUIRED_CONFIG_KEYS)} required keys present")
    except ContentRepoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
