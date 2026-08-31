"""YAML-frontmatter parsing and the :class:`Note` model."""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DELIM = "---"


class FrontmatterError(ValueError):
    """Raised when a note's frontmatter is missing or unparseable."""


def split(text: str) -> tuple[dict[str, Any], str]:
    """Split note text into ``(metadata, body)``."""
    if not text.startswith(DELIM):
        raise FrontmatterError("missing YAML frontmatter (file must start with '---')")
    parts = text.split("\n" + DELIM, 1)
    if len(parts) != 2:
        raise FrontmatterError("unterminated YAML frontmatter (no closing '---')")
    raw_meta = parts[0][len(DELIM):]
    body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
    try:
        meta = yaml.safe_load(raw_meta) or {}
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"invalid YAML frontmatter: {exc}") from exc
    if not isinstance(meta, dict):
        raise FrontmatterError("frontmatter must be a YAML mapping")
    return meta, body


def dump(meta: dict[str, Any], body: str) -> str:
    """Serialize metadata + body back into note text."""
    buf = io.StringIO()
    buf.write(DELIM + "\n")
    yaml.safe_dump(meta, buf, sort_keys=False, allow_unicode=True, default_flow_style=False)
    buf.write(DELIM + "\n")
    buf.write(body if body.endswith("\n") or not body else body + "\n")
    return buf.getvalue()


@dataclass
class Note:
    """A single note file, parsed."""

    path: Path
    meta: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    @classmethod
    def load(cls, path: Path) -> "Note":
        try:
            meta, body = split(path.read_text(encoding="utf-8"))
        except FrontmatterError as exc:
            raise FrontmatterError(f"{path}: {exc}") from exc
        return cls(path=path, meta=meta, body=body)

    def save(self) -> None:
        self.path.write_text(dump(self.meta, self.body), encoding="utf-8")

    # -- frontmatter accessors -------------------------------------------------
    @property
    def id(self) -> str:
        return str(self.meta.get("id", ""))

    @property
    def key(self) -> str:
        return str(self.meta.get("key", ""))

    @property
    def slug(self) -> str:
        return str(self.meta.get("slug", ""))

    @property
    def type(self) -> str:
        return str(self.meta.get("type", ""))

    @property
    def title(self) -> str:
        return str(self.meta.get("title", ""))

    @property
    def tags(self) -> list[str]:
        return list(self.meta.get("tags") or [])

    @property
    def links(self) -> list[dict[str, Any]]:
        """Typed links from frontmatter, normalized to dicts."""
        out = []
        for link in self.meta.get("links") or []:
            if isinstance(link, dict):
                out.append(link)
        return out

    @property
    def stem(self) -> str:
        return self.path.stem

    # -- inquiry accessors (FR-6) ----------------------------------------------
    @property
    def question(self) -> str:
        return str(self.meta.get("question", ""))

    @property
    def status(self) -> str:
        return str(self.meta.get("status", ""))

    @property
    def priority(self) -> str:
        return str(self.meta.get("priority", ""))

    @property
    def result_notes(self) -> list[str]:
        """Note keys that answered this inquiry."""
        return [str(r) for r in (self.meta.get("result_notes") or [])]
