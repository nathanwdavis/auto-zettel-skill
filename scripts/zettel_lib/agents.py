"""Resolve agent model tiers from a content repo's config (FR-29, AC-29).

The .md files under the plugin's ``agents/`` directory declare tier *defaults*
via model aliases -- ``opus`` marks a strong-tier agent, ``haiku`` a cheap-tier
one. At run time the content repo's ``config.yml`` ``models: {strong, cheap}``
is authoritative: this module re-emits every agent as ``--agents`` JSON with the
configured model substituted, which is how a headless ``claude -p`` run picks
the tiers up without editing the checked-in agent files.

Run as a module to print the JSON:
    python -m zettel_lib.agents --repo <content-repo> [--agents-dir <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .repo import ContentRepo, dig

TIER_BY_ALIAS = {"opus": "strong", "sonnet": "strong", "fable": "strong",
                 "haiku": "cheap"}

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


def agents_json(repo: ContentRepo, agents_dir: Path = DEFAULT_AGENTS_DIR) -> str:
    """Emit the --agents JSON with models resolved from config.yml (AC-29)."""
    cfg = repo.require_config("models.strong", "models.cheap")
    models = {"strong": str(dig(cfg, "models.strong")),
              "cheap": str(dig(cfg, "models.cheap"))}
    out = {}
    for meta in load_agents(agents_dir):
        out[meta["name"]] = {
            "description": meta["description"],
            "prompt": meta["_prompt"],
            "model": models[tier_of(meta)],
            "tools": list(meta.get("tools") or []),
        }
    return json.dumps(out, sort_keys=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--agents-dir", type=Path, default=DEFAULT_AGENTS_DIR)
    args = parser.parse_args(argv)
    try:
        print(agents_json(ContentRepo(args.repo), args.agents_dir))
    except (AgentDefinitionError, Exception) as exc:  # noqa: BLE001 - CLI boundary
        if isinstance(exc, SystemExit):
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
