from types import SimpleNamespace
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents import prompt_rewrite_agent
from services.agents.prompt_rewrite_agent import PromptRewriteAgent


def _context(events=None):
    return {
        "script": SimpleNamespace(id=11),
        "episode": SimpleNamespace(id=22),
        "user": SimpleNamespace(id=1),
        "team": SimpleNamespace(id=2),
        "latest_user_message": "把第 3 镜改成雨夜",
        "latest_artifacts": {},
        "workflow_profile": {"image": {"model_code": "gpt-image-2"}, "video": {"model_code": "seedance_20_fast"}},
        "creative_stage": "storyboard_ready",
        "runtime_event_callback": (lambda event_type, data: events.append((event_type, data))) if events is not None else None,
    }


def test_prompt_rewrite_preview_only_returns_bundle(monkeypatch):
    events = []
    agent = PromptRewriteAgent(SimpleNamespace())
    monkeypatch.setattr(agent, "_panels_by_payload", lambda episode, payload: [SimpleNamespace(id=101, sequence_num=3)])
    monkeypatch.setattr(
        agent,
        "_panel_context_rows",
        lambda **kwargs: [
            {
                "panel_id": 101,
                "sequence_num": 3,
                "original_image_prompt": "分镜设定：白天街道",
                "original_video_prompt": "时间轴：0-6秒，白天街道",
                "recommended_duration_seconds": 6,
            }
        ],
    )
    monkeypatch.setattr(agent, "_valid_asset_names", lambda script_id: {"主角", "街道"})
    monkeypatch.setattr(
        agent,
        "_call_rewrite_model",
        lambda **kwargs: (
            [{"sequence_num": 3, "new_image_prompt": "分镜设定：雨夜街道", "rewrite_note": "改为雨夜"}],
            {"charged_points": 2, "actual_cost_cny": 0.12, "usage": {}, "points_status": "deducted"},
        ),
    )
    monkeypatch.setattr(agent, "_charge_rewrite_points", lambda **kwargs: kwargs["billing"])
    monkeypatch.setattr(agent, "_estimate_current_model", lambda **kwargs: {"current": {"model_name": "gpt-image-2", "estimate_points": 55}})

    result = agent.execute_action(_context(events), "rewrite_generation_prompts", {"target_kind": "image", "panel_sequence": 3})

    bundle = result["result"]
    assert bundle["artifact_type"] == "prompt_rewrite_bundle"
    assert bundle["status"] == "ready"
    assert bundle["billing"]["display"] == "✦ 2"
    assert bundle["rows"][0]["new_image_prompt"] == "分镜设定：雨夜街道"
    assert [item[0] for item in events] == ["prompt_rewrite_delta", "prompt_rewrite_delta", "prompt_rewrite_ready"]


def test_prompt_rewrite_apply_uses_panel_revision(monkeypatch):
    panel = SimpleNamespace(id=101, sequence_num=3)
    saved_payloads = []
    agent = PromptRewriteAgent(SimpleNamespace())
    monkeypatch.setattr(agent, "_list_episode_panels", lambda episode_id: [panel])
    monkeypatch.setattr(
        prompt_rewrite_agent,
        "update_panel_with_revision",
        lambda session, panel_obj, payload, created_by_user_id=None: saved_payloads.append((panel_obj, dict(payload), created_by_user_id)),
    )
    bundle = {
        "artifact_type": "prompt_rewrite_bundle",
        "rewrite_id": "rw1",
        "target_kind": "both",
        "rows": [
            {
                "sequence_num": 3,
                "target": {"image": True, "video": True},
                "new_image_prompt": "分镜设定：雨夜街道",
                "new_video_prompt": "时间轴：0-6秒，雨夜街道",
            }
        ],
    }

    result = agent.execute_action(_context(), "rewrite_generation_prompts", {"operation": "apply", "prompt_rewrite_bundle": bundle})

    assert result["message"] == "已保存 1 个分镜的改写提示词。"
    assert saved_payloads[0][0] is panel
    assert saved_payloads[0][1]["source"] == "agent_prompt_rewrite"
    assert saved_payloads[0][1]["multi_shot_prompt"] == "分镜设定：雨夜街道"
    assert saved_payloads[0][1]["multi_shot_video_prompt"] == "时间轴：0-6秒，雨夜街道"
    assert saved_payloads[0][2] == 1


def test_prompt_rewrite_apply_and_generate_reuses_generation_agent(monkeypatch):
    panel = SimpleNamespace(id=101, sequence_num=3)
    generation_calls = []

    class FakeGenerationAgent:
        def __init__(self, session):
            self.session = session

        def execute_action(self, context, action, payload=None):
            generation_calls.append((action, dict(payload or {})))
            return {"result": {"submitted_count": 1}, "next_stage_hint": "image_generation_pending"}

    agent = PromptRewriteAgent(SimpleNamespace())
    monkeypatch.setattr(agent, "_list_episode_panels", lambda episode_id: [panel])
    monkeypatch.setattr(prompt_rewrite_agent, "update_panel_with_revision", lambda *args, **kwargs: None)
    monkeypatch.setattr(prompt_rewrite_agent, "GenerationAgent", FakeGenerationAgent)
    bundle = {
        "artifact_type": "prompt_rewrite_bundle",
        "rewrite_id": "rw1",
        "target_kind": "image",
        "model_suggestion": {"recommended": {"payload": {"model_code": "gpt-image-2-hq"}}},
        "rows": [
            {
                "sequence_num": 3,
                "target": {"image": True, "video": False},
                "new_image_prompt": "分镜设定：电影感雨夜街道",
            }
        ],
    }

    result = agent.execute_action(
        _context(),
        "rewrite_generation_prompts",
        {"operation": "apply_and_generate", "prompt_rewrite_bundle": bundle, "generate_after": "image", "use_recommended_model": True},
    )

    assert "提交 1 个生成任务" in result["message"]
    assert generation_calls == [("generate_storyboard_images", {"selected_panel_sequences": [3], "model_code": "gpt-image-2-hq"})]
