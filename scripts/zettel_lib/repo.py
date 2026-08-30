"""Content-repo discovery, note loading, and the append-only run log."""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Iterable, Iterator

import yaml

from .frontmatter import Note

NOTE_DIRS = ("fleeting", "literature", "permanent", "reference", "moc")
SUBSTRATE_DIRS = NOTE_DIRS + ("inquiries", "raw", "skills", "proposed-links", ".bib")


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

    def rel(self, path: Path) -> str:
        return str(Path(path).resolve().relative_to(self.root)).replace("\\", "/")

    # -- logging --------------------------------------------------------------
    def append_log(self, message: str) -> None:
        """Append a timestamped line to the repo's append-only log.md (NFR-2)."""
        stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log = self.root / "log.md"
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"- `{stamp}` {message}\n")


def dig(data: dict, dotted: str):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur
