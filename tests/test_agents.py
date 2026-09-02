"""Agent definitions parse and resolve model tiers from config (FR-16, FR-29)."""

from __future__ import annotations

import json
import subprocess
import sys

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


def test_names_flag_lists_every_registered_agent(clean_repo):
    """The wrapper stamps this list into log.md as the agents dispatched (NFR-2)."""
    result = subprocess.run(
        [sys.executable, "-m", "zettel_lib.agents", "--repo", str(clean_repo), "--names"],
        capture_output=True, text=True, cwd=str(PLUGIN_ROOT / "scripts"))
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.strip().split(",")) == EXPECTED


def test_agents_json_resolves_models_from_config(clean_repo):
    payload = json.loads(agents_mod.agents_json(ContentRepo(clean_repo)))
    assert set(payload) == EXPECTED
    for name, spec in payload.items():
        expected_tier = "strong" if name in STRONG else "cheap"
        expected_model = ("claude-opus-5" if expected_tier == "strong"
                          else "claude-sonnet-5")
        assert spec["model"] == expected_model, name
        assert spec["description"] and spec["prompt"] and spec["tools"]


def test_agents_json_hard_fails_on_missing_models_key(clean_repo):
    import yaml
    cfg = yaml.safe_load((clean_repo / "config.yml").read_text(encoding="utf-8"))
    del cfg["models"]
    (clean_repo / "config.yml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(Exception, match="models"):
        agents_mod.agents_json(ContentRepo(clean_repo))


# --- materialize: config.yml reaches the remote path's registry ---------------

def _registry(tmp_path):
    """A registry as ci/setup-environment.sh builds it: symlinks into the plugin."""
    dest = tmp_path / "agents"
    dest.mkdir()
    for path in AGENTS_DIR.glob("*.md"):
        (dest / path.name).symlink_to(path)
    return dest


def test_materialize_writes_the_configured_model_per_tier(clean_repo, tmp_path):
    dest = _registry(tmp_path)
    written = agents_mod.materialize(ContentRepo(clean_repo), dest)

    assert {p.name for p in written} == {f"{n}.md" for n in EXPECTED}
    for name in EXPECTED:
        meta = agents_mod.parse_agent(dest / f"{name}.md")
        expected = ("claude-opus-5" if name in STRONG else "claude-sonnet-5")
        assert meta["model"] == expected, name
        # Everything else must survive: a rewritten definition the session
        # delegates to is useless without its prompt and tools.
        source = agents_mod.parse_agent(AGENTS_DIR / f"{name}.md")
        assert meta["_prompt"] == source["_prompt"]
        assert meta["tools"] == source["tools"]
        assert meta["description"] == source["description"]


def test_materialize_never_writes_through_the_symlink(clean_repo, tmp_path):
    """The registry entries point INTO THE PLUGIN TREE. Writing through one
    would edit the skill repo itself -- what FR-37 forbids and what
    maintenance_run.sh's snapshot check exists to catch."""
    dest = _registry(tmp_path)
    before = {p: p.read_bytes() for p in AGENTS_DIR.glob("*.md")}

    agents_mod.materialize(ContentRepo(clean_repo), dest)

    for path, original in before.items():
        assert path.read_bytes() == original, f"{path} was modified in place"
    for entry in dest.glob("*.md"):
        assert not entry.is_symlink(), f"{entry} is still a symlink"


def test_materialize_only_touches_files_already_registered(clean_repo, tmp_path):
    """Scoped to registries setup-environment.sh built: running start on a
    laptop must not conjure an agent registry nobody asked for."""
    dest = tmp_path / "agents"
    dest.mkdir()
    (dest / "critic.md").symlink_to(AGENTS_DIR / "critic.md")

    written = agents_mod.materialize(ContentRepo(clean_repo), dest)

    assert [p.name for p in written] == ["critic.md"]
    assert {p.name for p in dest.iterdir()} == {"critic.md"}


def test_materialize_leaves_only_the_model_line_changed(clean_repo, tmp_path):
    dest = _registry(tmp_path)
    agents_mod.materialize(ContentRepo(clean_repo), dest)

    source = (AGENTS_DIR / "researcher.md").read_text(encoding="utf-8").splitlines()
    written = (dest / "researcher.md").read_text(encoding="utf-8").splitlines()
    differing = [(a, b) for a, b in zip(source, written) if a != b]
    assert len(source) == len(written)
    assert differing == [("model: haiku", "model: claude-sonnet-5")]


def test_rewrite_model_rejects_a_definition_without_one():
    with pytest.raises(agents_mod.AgentDefinitionError):
        agents_mod.rewrite_model("---\nname: x\n---\nbody\n", "claude-opus-5")


def test_skill_smith_prompt_carries_the_fr37_rails():
    prompt = agents_mod.parse_agent(AGENTS_DIR / "skill-smith.md")["_prompt"]
    assert "Never modify the zettel-bootstrap skill repo" in prompt
    assert "one proposal per cycle" in prompt
    # Phase 4 shipped: proposals go through the recorded flow, and the
    # pre-harness "Phase note" is gone
    assert "skill_review.py" in prompt
    assert "Phase note" not in prompt
