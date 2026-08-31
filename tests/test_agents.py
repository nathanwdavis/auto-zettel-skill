"""Agent definitions parse and resolve model tiers from config (FR-16, FR-29)."""

from __future__ import annotations

import json

import pytest

from conftest import PLUGIN_ROOT
from zettel_lib import agents as agents_mod
from zettel_lib.repo import ContentRepo

AGENTS_DIR = PLUGIN_ROOT / "agents"
EXPECTED = {"orchestrator", "researcher", "synthesizer", "critic",
            "librarian", "connector", "note-maintainer", "skill-smith"}
STRONG = {"orchestrator", "synthesizer", "critic", "skill-smith"}


def test_all_eight_agents_exist():
    names = {p.stem for p in AGENTS_DIR.glob("*.md")}
    assert names == EXPECTED


@pytest.mark.parametrize("path", sorted(AGENTS_DIR.glob("*.md")),
                         ids=lambda p: p.stem)
def test_agent_parses_with_required_fields(path):
    meta = agents_mod.parse_agent(path)
    assert meta["name"] == path.stem
    assert len(meta["description"]) > 40, "description needs when-to-delegate language"
    assert meta["_prompt"], "system prompt body must not be empty"
    assert meta["model"] in agents_mod.TIER_BY_ALIAS, \
        f"model '{meta.get('model')}' is not a known tier alias"
    assert isinstance(meta.get("tools"), list) and meta["tools"], \
        "tools must be declared explicitly (AC-16)"


@pytest.mark.parametrize("path", sorted(AGENTS_DIR.glob("*.md")),
                         ids=lambda p: p.stem)
def test_agents_that_reach_the_web_use_pascalcase_tool_names(path):
    meta = agents_mod.parse_agent(path)
    tools = set(meta["tools"])
    assert not {"web_search", "web_fetch"} & tools, \
        "tool names are PascalCase in Claude Code (WebSearch/WebFetch)"


def test_research_facing_agents_carry_web_tools():
    """FR-16's intent: agents that gather or check sources can reach the web."""
    for name in ("orchestrator", "researcher", "synthesizer", "librarian"):
        meta = agents_mod.parse_agent(AGENTS_DIR / f"{name}.md")
        assert {"WebSearch", "WebFetch"} <= set(meta["tools"]), name


def test_tier_defaults_match_fr29():
    for path in AGENTS_DIR.glob("*.md"):
        meta = agents_mod.parse_agent(path)
        expected = "strong" if path.stem in STRONG else "cheap"
        assert agents_mod.tier_of(meta) == expected, path.stem


def test_agents_json_resolves_models_from_config(clean_repo):
    payload = json.loads(agents_mod.agents_json(ContentRepo(clean_repo)))
    assert set(payload) == EXPECTED
    for name, spec in payload.items():
        expected_tier = "strong" if name in STRONG else "cheap"
        expected_model = ("claude-opus-5" if expected_tier == "strong"
                          else "claude-haiku-4-5-20251001")
        assert spec["model"] == expected_model, name
        assert spec["description"] and spec["prompt"] and spec["tools"]


def test_agents_json_hard_fails_on_missing_models_key(clean_repo):
    import yaml
    cfg = yaml.safe_load((clean_repo / "config.yml").read_text(encoding="utf-8"))
    del cfg["models"]
    (clean_repo / "config.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(Exception, match="models"):
        agents_mod.agents_json(ContentRepo(clean_repo))


def test_skill_smith_prompt_carries_the_fr37_rails():
    prompt = agents_mod.parse_agent(AGENTS_DIR / "skill-smith.md")["_prompt"]
    assert "Never modify the zettel-bootstrap skill repo" in prompt
    assert "one proposal per cycle" in prompt
    # Phase 4 shipped: proposals go through the recorded flow, and the
    # pre-harness "Phase note" is gone
    assert "skill_review.py" in prompt
    assert "Phase note" not in prompt
