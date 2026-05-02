import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents.asset_planner_agent import AssetPlannerAgent


def test_save_assets_uses_latest_artifacts_when_payload_missing():
    session = MagicMock()
    agent = AssetPlannerAgent(session=session)
    context = {
        "script": SimpleNamespace(id=123),
        "current_script": "测试原文",
        "latest_artifacts": {
            "characters": [
                {
                    "name": "伊雪儿",
                    "description": "角色说明",
                    "level": "主要人物",
                }
            ],
            "scenes": [
                {
                    "name": "悬崖峭壁",
                    "description": "场景说明",
                    "level": "主场景",
                }
            ],
            "props": [
                {
                    "name": "麻绳",
                    "description": "道具说明",
                    "level": "关键剧情道具",
                }
            ],
        },
    }

    with patch("services.agents.asset_planner_agent.sync_structured_assets_into_shared_resources") as sync_mock:
        with patch.object(agent, "_artifact_bundle", return_value={"asset_bundle": {"artifact_type": "asset_bundle", "characters": [{}], "scenes": [{}], "props": [{}], "asset_summary": "人物 1 / 场景 1 / 道具 1"}}):
            result = agent.execute_action(context, "save_assets", payload={})

    sync_mock.assert_called_once()
    called_script_id, called_assets = sync_mock.call_args.args
    assert called_script_id == 123
    assert called_assets["characters"][0]["name"] == "伊雪儿"
    assert called_assets["scenes"][0]["name"] == "悬崖峭壁"
    assert called_assets["props"][0]["name"] == "麻绳"
    assert result["message"] == "保存资产成功，已写入资产库。"
    session.commit.assert_called_once()
