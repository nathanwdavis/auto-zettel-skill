#!/usr/bin/env python3
"""Mode-B container-side fetcher for a content repository (FR-23).

Fetches manifest.json -- and, optionally, specific notes -- from GitHub without
a local clone, for surfaces (claude.ai, the API) where server-side web_fetch
cannot reach skill-embedded URLs. Public repos are read via
raw.githubusercontent.com; private repos via the GitHub API `contents`
endpoint, which REQUIRES a token in the GITHUB_TOKEN or GH_TOKEN environment
variable (never an argument, never a file in the repo).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from zettel_lib import http

RAW = "https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
API = "https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"

EXIT_OK = 0
EXIT_FETCH_FAILED = 1
EXIT_USAGE = 2


def token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


def fetch(url: str, transport, use_token: bool = False) -> str | None:
    headers = {"User-Agent": "zettel-bootstrap-fetch/0.1"}
    if use_token:
        tok = token()
        if not tok:
            return None
        headers["Authorization"] = f"Bearer {tok}"
        headers["Accept"] = "application/vnd.github.raw+json"
    try:
        resp = transport(url, headers)
    except http.NetworkUnavailable:
        return None
    if resp.status != 200:
        return None
    # The API returns raw content with the raw+json Accept header, but fall
    # back to decoding the base64 JSON envelope if a proxy strips it.
    if use_token and resp.body.lstrip().startswith("{"):
        try:
            data = json.loads(resp.body)
            if isinstance(data, dict) and data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8")
        except (json.JSONDecodeError, KeyError, ValueError):
            pass
    return resp.body


def fetch_path(owner: str, repo: str, branch: str, path: str, transport) -> str | None:
    """Raw first (works anonymously for public repos), then API with token."""
    body = fetch(RAW.format(owner=owner, repo=repo, branch=branch, path=path), transport)
    if body is not None:
        return body
    return fetch(API.format(owner=owner, repo=repo, branch=branch, path=path),
                 transport, use_token=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest-url", help="full URL of manifest.json (public repos)")
    src.add_argument("--owner", help="GitHub owner (used with --repo)")
    parser.add_argument("--repo", help="GitHub repo name (with --owner)")
    parser.add_argument("--branch", default="main")
    parser.add_argument("--out", type=Path, default=Path("."),
                        help="directory to write fetched files into")
    parser.add_argument("--keys", default="",
                        help="comma-separated note keys to fetch after the manifest")
    args = parser.parse_args(argv)

    if args.owner and not args.repo:
        parser.error("--owner requires --repo")

    transport = http.requests_transport

    # --- manifest -------------------------------------------------------------
    if args.manifest_url:
        manifest_text = fetch(args.manifest_url, transport)
        if manifest_text is None and token():
            manifest_text = fetch(args.manifest_url, transport, use_token=True)
    else:
        manifest_text = fetch_path(args.owner, args.repo, args.branch,
                                   "manifest.json", transport)

    if manifest_text is None:
        print("error: could not fetch manifest.json by raw URL or GitHub API.", file=sys.stderr)
        if not token():
            print("For a PRIVATE content repo, set GITHUB_TOKEN (or GH_TOKEN) with "
                  "repo read scope, or use the GitHub MCP connector instead.", file=sys.stderr)
        return EXIT_FETCH_FAILED

    try:
        manifest = json.loads(manifest_text)
    except json.JSONDecodeError as exc:
        print(f"error: fetched manifest is not valid JSON: {exc}", file=sys.stderr)
        return EXIT_FETCH_FAILED

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "manifest.json").write_text(manifest_text, encoding="utf-8")
    print(f"fetched manifest.json ({manifest.get('note_count', '?')} notes) -> {args.out}")

    # --- requested notes ------------------------------------------------------
    failures = 0
    wanted = [k.strip() for k in args.keys.split(",") if k.strip()]
    by_key = {e["key"]: e for e in manifest.get("notes", [])}
    id_to_key = manifest.get("id_to_key", {})
    for want in wanted:
        entry = by_key.get(want) or by_key.get(id_to_key.get(want, ""))
        if not entry:
            print(f"error: key '{want}' not in manifest", file=sys.stderr)
            failures += 1
            continue
        url_or_path = entry["url_or_apipath"]
        if url_or_path.startswith("http"):
            body = fetch(url_or_path, transport)
        elif args.owner:
            body = fetch_path(args.owner, args.repo, args.branch, entry["path"], transport)
        else:
            body = fetch(entry.get("api_path", ""), transport, use_token=True)
        if body is None:
            print(f"error: could not fetch note '{want}'", file=sys.stderr)
            failures += 1
            continue
        target = args.out / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        print(f"fetched {entry['path']}")

    return EXIT_FETCH_FAILED if failures else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
