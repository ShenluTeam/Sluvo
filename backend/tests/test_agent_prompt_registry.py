import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents.prompt_registry import (
    AGENT_PERSONAS,
    AGENT_SYSTEM_RULES,
    get_agent_prompt_bundle,
    get_agent_role_hint,
)


def test_all_agents_have_rich_personas_and_rules():
    expected_agents = {
        "director_agent",
        "asset_planner_agent",
        "storyboard_agent",
        "generation_agent",
    }
    assert expected_agents.issubset(set(AGENT_PERSONAS))
    assert expected_agents.issubset(set(AGENT_SYSTEM_RULES))
    for agent_name in expected_agents:
        bundle = get_agent_prompt_bundle(agent_name)
        assert len(bundle) > 200
        assert get_agent_role_hint(agent_name)
