#!/usr/bin/env python3
"""Fetch a source into raw/ as the capture for a reference note (amendment A11).

The researcher used to fetch with WebFetch and write the capture by hand,
which lost two things: the capture's naming and immutability were the
agent's discipline rather than the tool's, and a page that came back as an
empty JavaScript shell was saved as if it were the source. This makes the
capture mechanical:

  * the file is named ``raw/<id>-<slug>.<ext>`` from the reference note, and
    an existing capture is never overwritten (captures are immutable);
  * the bytes are written verbatim -- a PDF stays a PDF, HTML stays HTML --
    and are never summarised here (fetched content is data, not instructions);
  * an HTML shell (almost no visible text, "enable JavaScript" markers) is
    detected. With ``fetch.renderer`` set to ``jina`` or ``firecrawl`` in
    config.yml (or ``--renderer``), the page is re-fetched rendered and saved
    as markdown; with ``none`` (the default: nothing leaves for a third
    party unless you opt in) the fetch fails and an INBOX "source needed"
    entry asks a human to drop the PDF instead;
  * author-sharing sites (Academia.edu, ResearchGate) are refused: their
    copies are of uncertain version and licence, their terms forbid tools
    fetching them, and Unpaywall/OpenAlex deliberately exclude them. Resolve
    the DOI and fetch the ``verification.open_access`` copy instead.

    fetch_source.py --repo <path> --ref <reference-key> --url <url>
                    [--renderer none|jina|firecrawl|auto] [--no-inbox] [--json]

Exit 0 on a saved capture; 1 when nothing could be captured (the INBOX entry
is the hand-off); 2 on usage errors.
"""

from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture
from zettel_lib import http, naming
from zettel_lib.cli import EXIT_OK, EXIT_USAGE, EXIT_VIOLATION, base_parser, open_repo
from zettel_lib.frontmatter import FrontmatterError, Note
from zettel_lib.repo import ContentRepo, ContentRepoError, dig

RENDERERS = ("none", "jina", "firecrawl")
JINA = "https://r.jina.ai/{url}"
FIRECRAWL = "https://api.firecrawl.dev/v1/scrape"
FIRECRAWL_KEY_ENV = "FIRECRAWL_API_KEY"
LEAD_ONLY_HOSTS = ("academia.edu", "researchgate.net")
SHELL_MIN_TEXT = 400
SHELL_MARKERS = ("enable javascript", "javascript is required", "__next_data__",
                 "please enable cookies", "checking your browser")
TAG_RE = re.compile(r"<(script|style|noscript)\b.*?</\1>|<[^>]+>", re.IGNORECASE | re.DOTALL)
USER_AGENT = "zettel-bootstrap-fetch/0.1"


class FetchError(RuntimeError):
    """A fetch that produced nothing citable; the message is for the INBOX entry."""


def find_reference(repo: ContentRepo, ref: str) -> Note:
    ref = ref.strip()
    for path in repo.note_paths(types=["reference"]):
        if path.stem == ref or (naming.is_id(ref) and path.stem.endswith(f"--{ref}")):
            return Note.load(path)
    raise ContentRepoError(f"no reference note matches {ref!r}")


def visible_text(markup: str) -> str:
    return html.unescape(TAG_RE.sub(" ", markup))


def looks_like_shell(markup: str) -> bool:
    text = " ".join(visible_text(markup).split())
    lowered = markup.lower()
    return len(text) < SHELL_MIN_TEXT or any(m in lowered for m in SHELL_MARKERS)


def extension_for(resp: http.Response, url: str) -> str:
    ctype = str(resp.headers.get("Content-Type") or resp.headers.get("content-type") or "").lower()
    data = resp.data
    if "pdf" in ctype or data[:5] == b"%PDF-":
        return "pdf"
    if "html" in ctype or b"<html" in data[:2000].lower():
        return "html"
    if "markdown" in ctype or url.lower().endswith(".md"):
        return "md"
    return "txt"


def render(url: str, renderer: str, *, transport, post_transport, env) -> str:
    """The page as markdown through the configured renderer (A11 opt-in)."""
    if renderer == "jina":
        resp = transport(JINA.format(url=url), {"User-Agent": USER_AGENT, "Accept": "text/plain"})
        if resp.status != 200 or not resp.body.strip():
            raise FetchError(f"jina reader returned HTTP {resp.status} for {url}")
        return resp.body
    if renderer == "firecrawl":
        key = env.get(FIRECRAWL_KEY_ENV, "")
        if not key:
            raise FetchError(f"fetch.renderer is firecrawl but {FIRECRAWL_KEY_ENV} is not set")
        data = http.post_json(FIRECRAWL, {"url": url, "formats": ["markdown"]},
                              headers={"Authorization": f"Bearer {key}"},
                              transport=post_transport)
        markdown = str(((data or {}).get("data") or {}).get("markdown") or "").strip()
        if not markdown:
            raise FetchError(f"firecrawl returned no markdown for {url}")
        return markdown
    raise FetchError(f"page is an empty shell and no renderer is enabled "
                     f"(set fetch.renderer to jina or firecrawl in config.yml, or drop the PDF into drop/)")


def fetch(repo: ContentRepo, ref: str, url: str, *, renderer: str = "auto",
          transport=http.requests_transport, post_transport=http.requests_post_transport,
          env: dict | None = None) -> dict:
    """Capture ``url`` for reference ``ref``. Raises FetchError when nothing citable came back."""
    env = os.environ if env is None else env
    note = find_reference(repo, ref)
    existing = str(note.meta.get("raw_capture") or "").strip()
    if existing and (repo.root / existing).exists():
        raise ContentRepoError(f"{note.key} already has capture {existing}; captures are immutable")

    host = (urlparse(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in LEAD_ONLY_HOSTS):
        oa = str((note.meta.get("verification") or {}).get("open_access") or "")
        hint = f" -- its open-access copy is {oa}" if oa else " -- resolve its DOI for an open-access copy"
        raise FetchError(f"{host} is a lead, not a source: author uploads there are of "
                         f"uncertain version and licence and its terms forbid tool access{hint}")

    if renderer == "auto":
        renderer = str(dig(repo.config(), "fetch.renderer") or "none").strip().lower()
    if renderer not in RENDERERS:
        raise ContentRepoError(f"unknown renderer {renderer!r}; expected one of {'|'.join(RENDERERS)}")

    resp = transport(url, {"User-Agent": USER_AGENT})
    if resp.status != 200:
        raise FetchError(f"HTTP {resp.status} from {url}")
    ext = extension_for(resp, url)
    data = resp.data
    used = "none"
    if ext == "html" and looks_like_shell(resp.body):
        data = render(url, renderer, transport=transport, post_transport=post_transport,
                      env=env).encode("utf-8")
        ext, used = "md", renderer
    if not data.strip():
        raise FetchError(f"empty response from {url}")

    slug, note_id = naming.split_key(note.key)
    target = repo.root / "raw" / f"{note_id}-{slug}.{ext}"
    if target.exists():
        raise ContentRepoError(f"refusing to overwrite existing capture {repo.rel(target)}")
    target.parent.mkdir(exist_ok=True)
    target.write_bytes(data)
    note.meta["raw_capture"] = repo.rel(target)
    note.save()
    repo.append_log(f"fetch_source: {note.key} <- {url} (renderer={used}, {len(data)} bytes)")
    return {"key": note.key, "url": url, "capture": repo.rel(target), "renderer": used,
            "bytes": len(data)}


def main(argv: list[str] | None = None) -> int:
    parser = base_parser(__doc__.splitlines()[0])
    parser.add_argument("--ref", required=True, help="reference note key (or bare id)")
    parser.add_argument("--url", required=True, help="the source URL to capture")
    parser.add_argument("--renderer", default="auto", choices=("auto",) + RENDERERS,
                        help="JavaScript renderer for shell pages (default: config fetch.renderer)")
    parser.add_argument("--no-inbox", action="store_true",
                        help="on failure, do not file the INBOX 'source needed' entry")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)
    repo = open_repo(args.repo)
    try:
        result = fetch(repo, args.ref, args.url, renderer=args.renderer)
    except (ContentRepoError, FrontmatterError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except (FetchError, http.NetworkUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        repo.append_log(f"fetch_source: FAILED {args.ref} <- {args.url} ({exc})")
        if not args.no_inbox:
            capture.capture_inbox(
                repo, f"Source needed: {args.ref}",
                f"Could not capture {args.url}: {exc}. If you can obtain the source, "
                "drop the PDF into drop/ with a sidecar naming this reference's DOI or title.")
        return EXIT_VIOLATION
    print(json.dumps(result) if args.json else result["capture"])
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
