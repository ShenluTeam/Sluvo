import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents.generation_agent import GenerationAgent


def test_generate_storyboard_images_passes_session_to_reference_loader():
    session = MagicMock()
    agent = GenerationAgent(session=session)
    panel = SimpleNamespace(
        id=321,
        sequence_num=3,
        multi_shot_prompt="测试分镜提示词",
        scene_prompt="测试场景",
        prompt="测试提示词",
    )
    episode = SimpleNamespace(id=456)
    script = SimpleNamespace(id=789)
    context = {
        "script": script,
        "episode": episode,
        "user": MagicMock(),
        "team": MagicMock(),
        "workflow_profile": {"image": {"model_code": "nano-banana-2-低价版", "resolution": "2k"}, "aspect_ratio": "16:9"},
        "stage_read_model": {"facts": {}},
    }

    with patch.object(agent, "_first_storyboard_panel", return_value=panel):
        with patch("services.agents.generation_agent.get_panel_reference_images", return_value=["https://example.com/ref.png"]) as refs_mock:
            with patch("services.agents.generation_agent.submit_image_generation", return_value=SimpleNamespace(task_id="task-1")):
                with patch.object(agent, "_artifact_bundle", return_value={"generation_bundle": {"artifact_type": "generation_bundle"}}):
                    result = agent.execute_action(context, "generate_storyboard_images", payload={})

    refs_mock.assert_called_once_with(session, panel)
    assert result["next_stage_hint"] == "images_pending"


def test_generate_storyboard_images_supports_selected_panel_sequences_batch():
    session = MagicMock()
    agent = GenerationAgent(session=session)
    panels = [
        SimpleNamespace(id=101, sequence_num=1, multi_shot_prompt="镜头 1", scene_prompt="", prompt=""),
        SimpleNamespace(id=102, sequence_num=2, multi_shot_prompt="镜头 2", scene_prompt="", prompt=""),
    ]
    episode = SimpleNamespace(id=456)
    script = SimpleNamespace(id=789)
    context = {
        "script": script,
        "episode": episode,
        "user": MagicMock(),
        "team": MagicMock(),
        "workflow_profile": {"image": {"model_code": "nano-banana-pro", "resolution": "2k"}, "aspect_ratio": "16:9"},
        "stage_read_model": {"facts": {}},
    }

    with patch.object(agent, "_panels_by_sequences", return_value=panels):
        with patch("services.agents.generation_agent.get_panel_reference_images", return_value=[]):
            with patch(
                "services.agents.generation_agent.submit_image_generation",
                side_effect=[SimpleNamespace(task_id="task-1"), SimpleNamespace(task_id="task-2")],
            ):
                with patch.object(agent, "_artifact_bundle", return_value={"generation_bundle": {"artifact_type": "generation_bundle"}}):
                    result = agent.execute_action(
                        context,
                        "generate_storyboard_images",
                        payload={"selected_panel_sequences": [1, 2]},
                    )

    assert result["result"]["submitted_count"] == 2
    assert result["result"]["submitted_panel_sequences"] == [1, 2]
    assert [item["panel_sequence"] for item in result["result"]["submitted_panels"]] == [1, 2]


def test_generate_video_supports_selected_panel_sequences_batch():
    session = MagicMock()
    agent = GenerationAgent(session=session)
    panels = [
        SimpleNamespace(id=201, sequence_num=3, image_url="https://example.com/3.png", multi_shot_video_prompt="视频 3", video_prompt="", scene_prompt="", recommended_duration_seconds=5),
        SimpleNamespace(id=202, sequence_num=4, image_url="https://example.com/4.png", multi_shot_video_prompt="视频 4", video_prompt="", scene_prompt="", recommended_duration_seconds=5),
    ]
    episode = SimpleNamespace(id=456)
    script = SimpleNamespace(id=789)
    context = {
        "script": script,
        "episode": episode,
        "user": MagicMock(),
        "team": MagicMock(),
        "workflow_profile": {"video": {"model_code": "seedance", "resolution": "720p", "duration": 5}, "aspect_ratio": "16:9"},
        "stage_read_model": {"facts": {}},
    }

    with patch.object(agent, "_panels_by_sequences", return_value=panels):
        with patch(
            "services.agents.generation_agent.submit_video_generation",
            side_effect=[SimpleNamespace(task_id="video-1"), SimpleNamespace(task_id="video-2")],
        ):
            with patch.object(agent, "_artifact_bundle", return_value={"generation_bundle": {"artifact_type": "generation_bundle"}}):
                result = agent.execute_action(
                    context,
                    "generate_video",
                    payload={"selected_panel_sequences": [3, 4]},
                )

    assert result["result"]["submitted_count"] == 2
    assert result["result"]["submitted_panel_sequences"] == [3, 4]


def test_generation_agent_storyboard_ready_actions_prioritize_all_then_range_then_first():
    session = MagicMock()
    agent = GenerationAgent(session=session)
    context = {
        "creative_stage": "storyboard_ready",
        "creative_stage_label": "分镜已就绪",
        "episode": SimpleNamespace(id=456),
        "stage_read_model": {"facts": {}},
    }

    with patch.object(agent, "_pending_storyboard_image_sequences", return_value=[1, 2, 3, 4]):
        with patch.object(agent, "_artifact_bundle", return_value={"generation_bundle": {"artifact_type": "generation_bundle"}}):
            response = agent._fallback_response(context)

    actions = response["suggested_actions"]
    assert [item["type"] for item in actions[:4]] == [
        "generate_storyboard_images",
        "generate_storyboard_images",
        "generate_storyboard_images",
        "open_storyboard",
    ]
    assert actions[0]["payload"]["selected_panel_sequences"] == [1, 2, 3, 4]
    assert actions[1]["payload"]["selected_panel_sequences"] == [1, 2, 3]
    assert actions[2]["payload"]["panel_sequence"] == 1


def test_generate_asset_images_normalizes_resource_type_before_submit():
    session = MagicMock()
    agent = GenerationAgent(session=session)
    resource = SimpleNamespace(id=11, name="???", resource_type="character", description="??", trigger_word="???", aliases=[])
    script = SimpleNamespace(id=789)
    episode = SimpleNamespace(id=456)
    context = {
        "script": script,
        "episode": episode,
        "user": MagicMock(),
        "team": MagicMock(),
        "workflow_profile": {"image": {"model_code": "nano-banana-2", "resolution": "2k"}},
        "stage_read_model": {"facts": {}},
    }

    with patch.object(agent, "_resources_for_generation_scope", return_value=[resource]):
        with patch("services.agents.generation_agent.submit_asset_generation", return_value=SimpleNamespace(task_id="asset-task-1")) as submit_mock:
            with patch.object(agent, "_artifact_bundle", return_value={"generation_bundle": {"artifact_type": "generation_bundle"}}):
                result = agent.execute_action(context, "generate_asset_images", payload={"generation_scope": "character"})

    submitted_payload = submit_mock.call_args.kwargs["payload"]
    assert submitted_payload["asset_type"] == "character"
    assert result["result"]["submitted_assets"][0]["resource_type"] == "character"


def test_generate_asset_images_builds_constrained_character_prompt_when_no_prompt_override():
    session = MagicMock()
    agent = GenerationAgent(session=session)
    resource = SimpleNamespace(
        id=11,
        name="沈青",
        resource_type="character",
        description="20岁左右的年轻女子，黑色长发，素净古装。",
        trigger_word="沈青",
        aliases=[],
    )
    script = SimpleNamespace(id=789, style_preset="默认写实", source_text="古风宫廷故事")
    episode = SimpleNamespace(id=456, source_text="金銮殿内，沈青入场。")
    context = {
        "script": script,
        "episode": episode,
        "user": MagicMock(),
        "team": MagicMock(),
        "workflow_profile": {"image": {"model_code": "nano-banana-2", "resolution": "2k"}},
        "stage_read_model": {"facts": {}},
    }

    with patch.object(agent, "_resources_for_generation_scope", return_value=[resource]):
        with patch("services.agents.generation_agent.submit_asset_generation", return_value=SimpleNamespace(task_id="asset-task-1")) as submit_mock:
            with patch.object(agent, "_artifact_bundle", return_value={"generation_bundle": {"artifact_type": "generation_bundle"}}):
                agent.execute_action(context, "generate_asset_images", payload={"generation_scope": "character"})

    submitted_payload = submit_mock.call_args.kwargs["payload"]
    assert submitted_payload["aspect_ratio"] == "9:16"
    assert "单人全身照" in submitted_payload["prompt"]
    assert "纯色背景" in submitted_payload["prompt"]
    assert "仅允许出现这一个角色本人" in submitted_payload["prompt"]


def test_generate_asset_images_preserves_explicit_prompt_override():
    session = MagicMock()
    agent = GenerationAgent(session=session)
    resource = SimpleNamespace(id=11, name="沈青", resource_type="character", description="描述", trigger_word="沈青", aliases=[])
    script = SimpleNamespace(id=789, style_preset="默认写实", source_text="")
    episode = SimpleNamespace(id=456, source_text="")
    context = {
        "script": script,
        "episode": episode,
        "user": MagicMock(),
        "team": MagicMock(),
        "workflow_profile": {"image": {"model_code": "nano-banana-2", "resolution": "2k"}},
        "stage_read_model": {"facts": {}},
    }

    with patch.object(agent, "_resources_for_generation_scope", return_value=[resource]):
        with patch("services.agents.generation_agent.submit_asset_generation", return_value=SimpleNamespace(task_id="asset-task-1")) as submit_mock:
            with patch.object(agent, "_artifact_bundle", return_value={"generation_bundle": {"artifact_type": "generation_bundle"}}):
                agent.execute_action(
                    context,
                    "generate_asset_images",
                    payload={"generation_scope": "character", "prompt": "只用这句自定义提示词"},
                )

    submitted_payload = submit_mock.call_args.kwargs["payload"]
    assert submitted_payload["prompt"] == "只用这句自定义提示词"
