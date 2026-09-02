"""Resolve agent model tiers from a content repo's config (FR-29, AC-29).

The .md files under the plugin's ``agents/`` directory declare tier *defaults*
via model aliases -- ``opus`` marks a strong-tier agent, ``haiku`` a cheap-tier
one. At run time the content repo's ``config.yml`` ``models: {strong, cheap}``
is authoritative, and there are two ways that authority reaches a run, because
the two execution paths consume agents differently:

- **Laptop path.** ``agents_json()`` re-emits every agent as ``--agents`` JSON
  with the configured model substituted, and ``maintenance_run.sh`` hands that
  to a headless ``claude -p``.
- **Remote path.** The session *is* the agent and delegates to the definitions
  registered in ``~/.claude/agents/``, which ``ci/setup-environment.sh``
  symlinks straight from this plugin -- so it read the checked-in alias and
  config.yml never entered the picture: cheap-tier agents ran Haiku whatever
  config said. ``materialize()`` closes that by rewriting the registered files
  with the resolved model IDs. Claude Code watches the agents directory, so a
  rewrite during ``remote_cycle.sh start`` reaches that same session's later
  delegations.

Run as a module to print the JSON, or to materialize a registry:
    python -m zettel_lib.agents --repo <content-repo> [--agents-dir <dir>]
    python -m zettel_lib.agents --repo <content-repo> --materialize <dir>
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

from .repo import ContentRepo, dig

TIER_BY_ALIAS = {"opus": "strong", "sonnet": "strong", "fable": "strong",
                 "haiku": "cheap"}

# Only the frontmatter's model line, never a 'model:' the prompt body mentions.
MODEL_LINE_RE = re.compile(r"^model:.*$", re.MULTILINE)

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_AGENTS_DIR = PLUGIN_ROOT / "agents"


class AgentDefinitionError(ValueError):
    pass


def parse_agent(path: Path) -> dict:
    """Parse one agents/*.md file into its frontmatter dict + prompt body."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise AgentDefinitionError(f"{path.name}: missing YAML frontmatter")
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        raise AgentDefinitionError(f"{path.name}: unterminated frontmatter")
    meta = yaml.safe_load(parts[0][3:])
    if not isinstance(meta, dict):
        raise AgentDefinitionError(f"{path.name}: frontmatter must be a mapping")
    for required in ("name", "description"):
        if not meta.get(required):
            raise AgentDefinitionError(f"{path.name}: frontmatter missing '{required}'")
    body = parts[1].split("\n", 1)[1] if "\n" in parts[1] else ""
    meta["_prompt"] = body.strip()
    meta["_path"] = path
    return meta


def load_agents(agents_dir: Path = DEFAULT_AGENTS_DIR) -> list[dict]:
    paths = sorted(agents_dir.glob("*.md"))
    if not paths:
        raise AgentDefinitionError(f"no agent definitions found in {agents_dir}")
    return [parse_agent(p) for p in paths]


def tier_of(meta: dict) -> str:
    alias = str(meta.get("model", "opus"))
    return TIER_BY_ALIAS.get(alias, "strong")


def resolved_models(repo: ContentRepo) -> dict[str, str]:
    """The concrete model ID behind each tier name, per config.yml (AC-29).

    The single resolution point for both consumers below: a second copy of this
    lookup would let the JSON the laptop path sends and the files the remote
    path reads drift apart, and nothing would notice until a cycle silently ran
    the wrong tier.
    """
    cfg = repo.require_config("models.strong", "models.cheap")
    return {"strong": str(dig(cfg, "models.strong")),
            "cheap": str(dig(cfg, "models.cheap"))}


def agents_json(repo: ContentRepo, agents_dir: Path = DEFAULT_AGENTS_DIR) -> str:
    """Emit the --agents JSON with models resolved from config.yml (AC-29)."""
    models = resolved_models(repo)
    out = {}
    for meta in load_agents(agents_dir):
        out[meta["name"]] = {
            "description": meta["description"],
            "prompt": meta["_prompt"],
            "model": models[tier_of(meta)],
            "tools": list(meta.get("tools") or []),
        }
    return json.dumps(out, sort_keys=True)


def rewrite_model(text: str, model: str) -> str:
    """Return `text` with its frontmatter model line set to `model`.

    A targeted substitution rather than a YAML round-trip: re-dumping would
    reformat `tools: [Read, Grep]` into block style and would have to strip the
    private keys parse_agent injects. The generated file should differ from its
    source in exactly one line.
    """
    head, sep, body = text.partition("\n---")
    if not sep:
        raise AgentDefinitionError("unterminated frontmatter")
    new_head, count = MODEL_LINE_RE.subn(f"model: {model}", head, count=1)
    if count != 1:
        raise AgentDefinitionError("no 'model:' line in frontmatter")
    return new_head + sep + body


def materialize(repo: ContentRepo, dest_dir: Path,
                agents_dir: Path = DEFAULT_AGENTS_DIR) -> list[Path]:
    """Rewrite a registered agent directory with config.yml's model IDs.

    Two rules keep this safe, and both are load-bearing:

    - **Only files already present in dest_dir are touched.** The registry is
      something setup-environment.sh creates; a developer running `start` on a
      laptop must not have one conjured for them.
    - **The existing entry is unlinked, never written through.** Those entries
      are symlinks INTO THE PLUGIN TREE, so writing through one would edit the
      skill repo itself -- which maintenance_run.sh's snapshot check treats as
      a violation, and FR-37 forbids.
    """
    models = resolved_models(repo)
    written = []
    for meta in load_agents(agents_dir):
        source: Path = meta["_path"]
        target = dest_dir / source.name
        if not (target.exists() or target.is_symlink()):
            continue
        text = rewrite_model(source.read_text(encoding="utf-8"),
                             models[tier_of(meta)])
        target.unlink()
        target.write_text(text, encoding="utf-8")
        written.append(target)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--agents-dir", type=Path, default=DEFAULT_AGENTS_DIR)
    parser.add_argument("--materialize", type=Path, metavar="DIR",
                        help="rewrite the agent registry in DIR with the "
                             "models config.yml resolves, instead of printing "
                             "the JSON")
    parser.add_argument("--names", action="store_true",
                        help="print the registered agent names, comma-separated, "
                             "instead of the JSON (for the NFR-2 log line)")
    args = parser.parse_args(argv)
    try:
        repo = ContentRepo(args.repo)
        if args.names:
            print(",".join(meta["name"] for meta in load_agents(args.agents_dir)))
        elif args.materialize:
            written = materialize(repo, args.materialize, args.agents_dir)
            models = resolved_models(repo)
            print(f"agents: resolved {len(written)} definition(s) in "
                  f"{args.materialize} (strong={models['strong']} "
                  f"cheap={models['cheap']})")
        else:
            print(agents_json(repo, args.agents_dir))
    # AgentDefinitionError is already an Exception, and SystemExit is a
    # BaseException -- it bypasses this handler and propagates on its own,
    # which is what the guard that used to sit here was reaching for.
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
