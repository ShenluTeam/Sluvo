import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents.storyboard_agent import StoryboardAgent


def test_save_storyboard_uses_latest_artifacts_when_payload_missing():
    session = MagicMock()
    agent = StoryboardAgent(session=session)
    context = {
        "episode": SimpleNamespace(id=456, storyboard_mode="comic"),
        "current_script": "",
        "latest_artifacts": {
            "storyboard_bundle": {
                "artifact_type": "storyboard_bundle",
                "segment_draft": [
                    {
                        "sequence_num": 1,
                        "summary": "阴云密布，万丈悬崖下怒江奔腾。",
                        "scene_refs": ["大燕江边悬崖"],
                        "grid_count": 1,
                    }
                ],
            }
        },
    }

    with patch("services.agents.storyboard_agent.commit_story_segments_with_cells", return_value=[object()]) as commit_mock:
        with patch.object(
            agent,
            "_artifact_bundle",
            return_value={
                "storyboard_bundle": {
                    "artifact_type": "storyboard_bundle",
                    "storyboard_rows": [{"sequence_num": 1, "description": "阴云密布，万丈悬崖下怒江奔腾。", "scene_name": "大燕江边悬崖"}],
                    "segment_draft": [],
                    "gridcell_draft": [],
                    "storyboard_summary": "已生成 1 个分镜片段草稿",
                }
            },
        ):
            result = agent.execute_action(context, "save_storyboard", payload={})

    commit_mock.assert_called_once()
    story_segments = commit_mock.call_args.kwargs["story_segments"]
    assert story_segments[0]["summary"] == "阴云密布，万丈悬崖下怒江奔腾。"
    assert story_segments[0]["scene_refs"] == ["大燕江边悬崖"]
    assert result["refresh_hints"]["open_storyboard"] is True
    assert "分镜板已拆解完成" in result["message"]
    session.commit.assert_called_once()


def test_extract_storyboard_first_call_returns_plan_without_workspace_writeback():
    session = MagicMock()
    agent = StoryboardAgent(session=session)
    context = {
        "script": SimpleNamespace(default_storyboard_mode="comic"),
        "episode": SimpleNamespace(id=456, storyboard_mode="comic"),
        "current_script": "测试剧本",
        "runtime_event_callback": None,
    }
    plan_bundle = {
        "artifact_type": "storyboard_plan_bundle",
        "plan_id": "plan-1",
        "version": 1,
        "rows": [
            {
                "sequence_num": 1,
                "story_fragment": "主角冲向悬崖边",
                "dialogue": "",
                "estimated_duration_seconds": 6,
            }
        ],
        "status": "ready",
    }

    with patch("services.agents.storyboard_agent.build_storyboard_plan_bundle", return_value=plan_bundle):
        with patch("services.agents.storyboard_agent.commit_story_segments_with_cells", return_value=[object()]) as commit_mock:
            result = agent.execute_action(context, "extract_storyboard", payload={})

    commit_mock.assert_not_called()
    assert result["result"]["artifact_type"] == "storyboard_plan_bundle"
    assert result["refresh_hints"] == {}
    assert any(item["payload"]["mode"] == "split_confirmed" for item in result["suggested_actions"])


def test_extract_storyboard_confirmed_plan_commits_final_workspace_writeback():
    session = MagicMock()
    agent = StoryboardAgent(session=session)
    context = {
        "script": SimpleNamespace(default_storyboard_mode="comic"),
        "episode": SimpleNamespace(id=456, storyboard_mode="comic"),
        "current_script": "测试剧本",
        "runtime_event_callback": None,
        "latest_artifacts": {
            "storyboard_plan_bundle": {
                "artifact_type": "storyboard_plan_bundle",
                "plan_id": "plan-1",
                "version": 1,
                "rows": [{"sequence_num": 1, "story_fragment": "主角冲向悬崖边", "estimated_duration_seconds": 6}],
            }
        },
    }
    structured = {
        "story_segments": [
            {
                "sequence_num": 1,
                "summary": "主角冲向悬崖边",
                "scene_refs": ["悬崖"],
                "character_refs": ["主角"],
                "prop_refs": [],
                "grid_count": 1,
                "recommended_duration_seconds": 6,
                "grid_cells": [
                    {
                        "cell_index": 1,
                        "shot_description": "主角冲向悬崖边",
                        "action_description": "主角停在崖边",
                        "duration_seconds": 6,
                    }
                ],
            }
        ]
    }

    with patch("services.agents.storyboard_agent.build_storyboard_split_structured_draft", return_value=structured):
        with patch("services.agents.storyboard_agent.commit_story_segments_with_cells", return_value=[object()]) as commit_mock:
            with patch.object(agent, "_artifact_bundle", return_value={"storyboard_bundle": {"artifact_type": "storyboard_bundle"}}):
                result = agent.execute_action(context, "extract_storyboard", payload={"mode": "split_confirmed", "confirmed_plan_id": "plan-1"})

    assert commit_mock.call_count >= 1
    assert result["refresh_hints"]["open_storyboard"] is True
