"""Chicago notes-bibliography rendering from CSL-JSON (FR-8, FR-9).

Backend order is **pandoc first, citeproc-py second**, inverting the spec's
stated preference. The spec anticipated this ("if citeproc-py cannot render
valid Chicago fullnote strings on the real fixtures, switch to the pandoc
fallback"), and it does not: the bundled style overrides a global
``initialize-with`` with 173 ``<name initialize="false">`` elements, which
citeproc-py ignores, so it renders "L. Tang" where Chicago requires
"Liyan Tang". Pandoc's citeproc honours the override.

Because the two backends disagree, each reference note records the backend that
produced its strings; ``lint_citations`` re-renders with that same backend and
skips (with a warning) rather than hard-failing when it is unavailable locally.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

CSL_STYLE = Path(__file__).resolve().parent.parent / "csl" / "chicago-notes-bibliography.csl"

PANDOC = "pandoc"
CITEPROC_PY = "citeproc-py"


class RenderError(RuntimeError):
    pass


@dataclass(frozen=True)
class Rendered:
    note: str
    bib: str
    backend: str


def pandoc_path() -> str | None:
    """Locate pandoc: the pypandoc-bundled binary first, then PATH."""
    try:
        import pypandoc

        path = pypandoc.get_pandoc_path()
        if path and Path(path).exists():
            return path
    except Exception:  # noqa: BLE001 - pypandoc optional; fall through to PATH
        pass
    return shutil.which(PANDOC)


def available_backends() -> list[str]:
    backends = []
    if pandoc_path():
        backends.append(PANDOC)
    try:
        import citeproc  # noqa: F401

        backends.append(CITEPROC_PY)
    except ImportError:
        pass
    return backends


def render(csl_item: dict, backend: str | None = None) -> Rendered:
    """Render one CSL-JSON item to (chicago_note, chicago_bib).

    Scripture is cited in-text by book-chapter-verse per SBL and never enters a
    bibliography (FR-9); callers filter it out before reaching here.
    """
    if not CSL_STYLE.exists():
        raise RenderError(f"bundled CSL style not found at {CSL_STYLE}")
    chosen = backend or (available_backends() or [None])[0]
    if chosen == PANDOC:
        return _render_pandoc(csl_item)
    if chosen == CITEPROC_PY:
        return _render_citeproc(csl_item)
    raise RenderError(
        "no citation backend available; install pypandoc-binary (preferred) "
        "or citeproc-py -- see requirements.txt"
    )


def _render_pandoc(csl_item: dict) -> Rendered:
    exe = pandoc_path()
    if not exe:
        raise RenderError("pandoc not available")
    item = dict(csl_item)
    cid = item.get("id") or "ref"
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        bib = tmpdir / "refs.json"
        bib.write_text(json.dumps([item], ensure_ascii=False), encoding="utf-8")
        doc = tmpdir / "doc.md"
        doc.write_text(f"X.[^1]\n\n[^1]: [@{cid}]\n", encoding="utf-8")
        proc = subprocess.run(
            [exe, "--citeproc", "--csl", str(CSL_STYLE), "--bibliography", str(bib),
             "-f", "markdown", "-t", "plain", "--wrap=none", str(doc)],
            capture_output=True, text=True, timeout=120,
        )
    if proc.returncode != 0:
        raise RenderError(f"pandoc failed: {proc.stderr.strip()}")
    return Rendered(*_parse_pandoc(proc.stdout), backend=PANDOC)


def _parse_pandoc(out: str) -> tuple[str, str]:
    """Pull the note and bibliography entries out of pandoc's plain output."""
    lines = [ln.rstrip() for ln in out.splitlines()]
    note, bib = "", ""
    for idx, line in enumerate(lines):
        if line.startswith("[1] "):
            note = " ".join(_gather(lines, idx))[4:]
            break
    for idx, line in enumerate(lines):
        if line.strip() and not line.startswith("[1]") and not line.startswith("X."):
            candidate = " ".join(_gather(lines, idx))
            if candidate and not candidate.startswith("[1]"):
                bib = candidate
                break
    return _tidy(note), _tidy(bib)


def _gather(lines: list[str], start: int) -> list[str]:
    """Collect a logical entry: its first line plus wrapped continuations."""
    out = [lines[start]]
    for line in lines[start + 1:]:
        if not line.strip() or line.startswith("[") or line.startswith("X."):
            break
        out.append(line.strip())
    return out


def _render_citeproc(csl_item: dict) -> Rendered:
    from citeproc import (Citation, CitationItem, CitationStylesBibliography,
                          CitationStylesStyle, formatter)
    from citeproc.source.json import CiteProcJSON

    item = dict(csl_item)
    source = CiteProcJSON([item])
    style = CitationStylesStyle(str(CSL_STYLE), validate=False)
    bibliography = CitationStylesBibliography(style, source, formatter.plain)
    citation = Citation([CitationItem(item.get("id", "ref"))])
    bibliography.register(citation)
    note = str(bibliography.cite(citation, lambda _x: None))
    entries = bibliography.bibliography()
    bib = str(entries[0]) if entries else ""
    return Rendered(_tidy(note), _tidy(bib), CITEPROC_PY)


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def validate_csl(item: dict) -> list[str]:
    """Structural CSL-JSON checks (FR-7). Returns a list of problems."""
    problems = []
    if not isinstance(item, dict):
        return ["csl_json is not a mapping"]
    for required in ("id", "type", "title"):
        if not item.get(required):
            problems.append(f"csl_json missing required field '{required}'")
    issued = item.get("issued")
    if issued is not None:
        parts = issued.get("date-parts") if isinstance(issued, dict) else None
        if not parts or not isinstance(parts, list) or not parts[0]:
            problems.append("csl_json 'issued' must carry non-empty date-parts")
    authors = item.get("author")
    if authors is not None and not isinstance(authors, list):
        problems.append("csl_json 'author' must be a list")
    return problems
