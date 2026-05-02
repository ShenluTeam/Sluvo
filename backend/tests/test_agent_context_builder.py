import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents.context_builder import build_agent_specific_context


def test_context_builder_returns_different_shapes_for_agents():
    base_context = {
        "creative_stage": "assets_pending",
        "creative_stage_label": "资产提取",
        "latest_user_message": "帮我先提取人物和场景",
        "available_actions": [{"type": "extract_assets", "label": "提取资产"}],
    }
    workspace_facts = {
        "current_script": "主角回到旧城，发现家里留下的钥匙能打开地下室。",
        "resource_counts": {"characters": 1, "scenes": 1, "props": 1},
        "characters": [{"name": "林夏"}],
        "scenes": [{"name": "旧宅"}],
        "props": [{"name": "钥匙"}],
        "panels": [{"sequence_num": 1, "summary": "主角推门进屋"}],
        "panel_count": 1,
        "panels_with_images": 0,
        "panels_with_videos": 0,
    }
    latest_artifacts = {
        "script_draft": {"artifact_type": "script_draft", "script_draft": "草稿"},
        "asset_bundle": {"artifact_type": "asset_bundle", "characters": []},
    }

    director_context = build_agent_specific_context(
        agent_name="director_agent",
        base_context=base_context,
        workspace_facts=workspace_facts,
        latest_artifacts=latest_artifacts,
    )
    asset_context = build_agent_specific_context(
        agent_name="asset_planner_agent",
        base_context=base_context,
        workspace_facts=workspace_facts,
        latest_artifacts=latest_artifacts,
    )
    generation_context = build_agent_specific_context(
        agent_name="generation_agent",
        base_context=base_context,
        workspace_facts=workspace_facts,
        latest_artifacts=latest_artifacts,
    )

    assert "latest_script_artifact" in director_context
    assert "resource_counts" in asset_context
    assert "panels" in generation_context
    assert "latest_generation_artifact" in generation_context
