# Two-mode access

How a run reads and writes the content repo depends on where it executes.

## Mode A — local clone

The normal mode: laptop cron, desktop scheduled tasks, any environment with a
filesystem. `maintenance_run.sh` pulls, works in worktrees, commits, re-lints,
pushes; `run.lock` serializes concurrent runs; push rejections retry with
re-pull + re-lint (see `scheduling.md`).

## Mode B — remote walk (no local clone)

On claude.ai or the API there is no filesystem clone. One platform constraint
shapes everything here: **server-side `web_fetch` can only fetch URLs already
present in the conversation context** (from the user, `web_search` results, or
earlier fetches). A URL that only exists inside this skill's files, loaded via
the code-execution container, is NOT fetchable by server-side `web_fetch`.
Claude Code's own WebFetch tool does not have this restriction.

Belt and suspenders — five paths, in order of preference:

1. **GitHub MCP** (`get_file_contents`), when the connector is attached. The
   only fully general path, and **required for private content repos**.
2. **`scripts/fetch_remote.py`** run inside the code-execution container — the
   primary scripted mechanism. Fetches `manifest.json` then specific notes;
   raw URLs for public repos, GitHub API + `GITHUB_TOKEN`/`GH_TOKEN` env for
   private ones.
3. **Manifest raw URLs**: a public repo's `manifest.json` carries full
   `raw.githubusercontent.com` URLs for every note, so once the manifest is in
   context, every note is one fetch away.
4. **URL-into-context**: ask the user for the manifest/INDEX URL, or find the
   repo by name via `web_search` — either way the URL legitimately enters
   context and server-side `web_fetch` can then use it.
5. **Claude Code WebFetch**: on the Claude Code surface, fetch manifest URLs
   directly (domain permissions apply).

### Private content repos: the hard rule

Anonymous `raw.githubusercontent.com` URLs for a private repo return 404.
Mode B against a private content repo therefore **requires** either the GitHub
MCP connector (authenticated) or a PAT with repo read scope in the environment
for `fetch_remote.py`. `build_manifest.py` enforces the same split: private
manifests carry repo-relative + API paths, never anonymous raw URLs.

Known failure mode: the hosted GitHub MCP server's `get_file_contents` can 404
on some private/org repos behind IP allow-lists. The PAT + API path in
`fetch_remote.py` is the fallback; keep both available.

## What Mode B can and cannot do

Mode B reads and reasons; it does not run the lints or push. Writes from a
Mode-B session go through the INBOX pattern: propose the change as an inbox
entry (via the GitHub MCP write tools when available), and the next Mode-A
maintenance run applies it under the full gates.
