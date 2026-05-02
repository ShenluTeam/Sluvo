import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.assistant_runtime import deepseek_tool_runtime


def test_extract_explicit_tool_intent_maps_storyboard_request():
    result = deepseek_tool_runtime.extract_explicit_tool_intent("提取分镜")

    assert result is not None
    assert result["tool_name"] == "extract_storyboard"


def test_extract_explicit_tool_intent_maps_split_episode_source_skill_hint_to_storyboard_tool():
    result = deepseek_tool_runtime.extract_explicit_tool_intent(
        "/拆分镜",
        skill_hint={"id": "split_episode_source", "label": "拆分镜"},
    )

    assert result is not None
    assert result["tool_name"] == "extract_storyboard"


def test_extract_explicit_tool_intent_prefers_storyboard_image_over_storyboard_split():
    result = deepseek_tool_runtime.extract_explicit_tool_intent("帮我生成分镜图")

    assert result is not None
    assert result["tool_name"] == "generate_storyboard_images"


def test_tool_loop_system_prompt_forbids_user_visible_tool_names():
    prompt = deepseek_tool_runtime._tool_loop_system_prompt(
        context={},
        tools=[{"function": {"name": "save_script"}}, {"function": {"name": "generate_audio"}}],
        explicit_tool_intent=None,
    )

    assert "禁止出现" in prompt
    assert "内部英文标识" in prompt
    assert "创作者能理解的产品语言" in prompt
    assert "当前不提供联网搜索" in prompt
    assert "当前剧集文本和可用音色" in prompt


def test_extract_storyboard_allows_when_assets_have_no_reference_images(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.commit_called = False

        def get(self, model, item_id):
            if "Script" in str(model) or "Episode" in str(model):
                return SimpleNamespace(id=item_id, source_text="测试剧本")
            return None

        def add(self, _item):
            return None

        def commit(self):
            self.commit_called = True

    class FakeStoryboardAgent:
        def __init__(self, _session):
            pass

        def execute_action(self, context, action, payload=None):
            assert action == "extract_storyboard"
            assert context["current_script"] == "测试剧本文本"
            return {
                "message": "分镜提取完成",
                "result": {"artifact_type": "storyboard_bundle", "segment_draft": []},
                "refresh_hints": {"open_storyboard": True},
                "next_stage_hint": "storyboard_ready",
            }

    monkeypatch.setattr(
        deepseek_tool_runtime,
        "_load_project_resources",
        lambda session, script_id: [
            SimpleNamespace(resource_type="character", file_url=""),
            SimpleNamespace(resource_type="scene", file_url=""),
        ],
    )
    monkeypatch.setattr(
        deepseek_tool_runtime,
        "build_agent_context",
        lambda *args, **kwargs: {
            "current_script": "测试剧本文本",
            "creative_stage": "storyboard_pending",
            "workflow_profile": {},
            "latest_artifacts": {},
            "page_context": {},
        },
    )
    monkeypatch.setattr(deepseek_tool_runtime, "StoryboardAgent", FakeStoryboardAgent)
    monkeypatch.setattr(
        deepseek_tool_runtime,
        "_build_post_context_brief",
        lambda *args, **kwargs: {"creative_stage": "storyboard_pending"},
    )

    fake_session = FakeSession()
    executor = deepseek_tool_runtime.InternalDirectorToolExecutor(
        service=SimpleNamespace(session=fake_session),
        session_obj=SimpleNamespace(script_id=11, episode_id=22),
        user=SimpleNamespace(id=1),
        team=SimpleNamespace(id=2),
        base_context={},
    )

    result = executor.execute("extract_storyboard", {})

    assert result["status"] == "completed"
    assert result["message"] == "分镜提取完成"
    assert result["refresh_hints"]["open_storyboard"] is True


def test_generate_storyboard_images_blocks_when_assets_have_no_reference_images(monkeypatch):
    class FakeSession:
        def get(self, model, item_id):
            return SimpleNamespace(id=item_id, source_text="测试剧本") if "Script" in str(model) or "Episode" in str(model) else None

    monkeypatch.setattr(
        deepseek_tool_runtime,
        "_load_project_resources",
        lambda session, script_id: [
            SimpleNamespace(id=1, resource_type="character", file_url=""),
            SimpleNamespace(id=2, resource_type="scene", file_url=""),
        ],
    )
    monkeypatch.setattr(
        deepseek_tool_runtime,
        "_load_episode_panels",
        lambda session, episode_id: [
            SimpleNamespace(id=101, sequence_num=1, entity_bindings_json='{"characters":[{"asset_id":1,"name":"主角"}],"scenes":[{"asset_id":2,"name":"街道"}],"props":[]}', image_url="", video_url=""),
        ],
    )
    monkeypatch.setattr(
        deepseek_tool_runtime,
        "build_agent_context",
        lambda *args, **kwargs: {
            "current_script": "测试剧本文本",
            "creative_stage": "storyboard_ready",
            "workflow_profile": {},
            "latest_artifacts": {},
            "page_context": {},
        },
    )
    monkeypatch.setattr(
        deepseek_tool_runtime,
        "_build_post_context_brief",
        lambda *args, **kwargs: {"creative_stage": "storyboard_ready"},
    )

    executor = deepseek_tool_runtime.InternalDirectorToolExecutor(
        service=SimpleNamespace(session=FakeSession()),
        session_obj=SimpleNamespace(script_id=11, episode_id=22),
        user=SimpleNamespace(id=1),
        team=SimpleNamespace(id=2),
        base_context={},
    )

    result = executor.execute("generate_storyboard_images", {})

    assert result["result"]["status"] == "failed"
    assert result["result"]["reason"] == "missing_asset_reference_images"
    assert [item["type"] for item in result["suggested_actions"]] == ["generate_asset_images"]


def test_run_internal_director_tool_loop_executes_tool_then_returns_final_payload(monkeypatch):
    responses = [
        {
            "payload": None,
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "extract_storyboard",
                        "arguments": "{}",
                    },
                }
            ],
            "finish_reason": "tool_calls",
            "reasoning": "先拆分分镜",
            "route_tag": "test-tool",
        },
        {
            "payload": {
                "message": "分镜已拆解完成。",
                "suggested_actions": [{"type": "generate_storyboard_images", "label": "生成全部分镜图"}],
                "artifacts": {},
                "next_stage_hint": "storyboard_ready",
                "refresh_hints": {},
            },
            "content": '{"message":"分镜已拆解完成。","suggested_actions":[{"type":"generate_storyboard_images","label":"生成全部分镜图"}],"artifacts":{},"next_stage_hint":"storyboard_ready","refresh_hints":{}}',
            "tool_calls": [],
            "finish_reason": "stop",
            "reasoning": "工具执行完毕",
            "route_tag": "test-final",
        },
    ]

    first_reasoning = responses[0]["reasoning"]
    captured_messages = []

    def fake_chat_json_with_tools(**kwargs):
        captured_messages.append(list(kwargs.get("messages") or []))
        return responses.pop(0)

    class FakeExecutor:
        def __init__(self, **kwargs):
            self.latest_artifacts = {}

        def execute(self, tool_name, arguments):
            assert tool_name == "extract_storyboard"
            self.latest_artifacts = {
                "storyboard_bundle": {
                    "artifact_type": "storyboard_bundle",
                    "storyboard_summary": "已整理 1 个分镜片段",
                }
            }
            return {
                "tool_name": tool_name,
                "status": "completed",
                "summary": "分镜拆解完成",
                "message": "分镜拆解完成",
                "result": self.latest_artifacts["storyboard_bundle"],
                "refresh_hints": {"open_storyboard": True},
                "next_stage_hint": "storyboard_ready",
                "artifacts": dict(self.latest_artifacts),
                "post_context": {"creative_stage": "storyboard_ready"},
            }

    class FakeService:
        def __init__(self):
            self.session = object()
            self.events = []

        def _update_runtime_state(self, *args, **kwargs):
            return {}

        def _publish_runtime_delta(self, *args, **kwargs):
            return None

        def _update_reasoning_progress(self, *args, **kwargs):
            return None

        def _upsert_runtime_feed_item(self, *args, **kwargs):
            return {}

        def _complete_runtime_feed_item(self, *args, **kwargs):
            return {}

        def _remove_runtime_feed_item(self, *args, **kwargs):
            return None

        def _patch_runtime_feed_item(self, *args, **kwargs):
            return {}

        def publish_event(self, session_id, event):
            self.events.append(event)
            return event

    monkeypatch.setattr(deepseek_tool_runtime, "chat_json_with_tools", fake_chat_json_with_tools)
    monkeypatch.setattr(deepseek_tool_runtime, "InternalDirectorToolExecutor", FakeExecutor)
    monkeypatch.setattr(
        deepseek_tool_runtime,
        "resolve_deepseek_agent_route",
        lambda ctx: {
            "model": "deepseek-chat",
            "thinking_enabled": True,
            "max_tokens": 1024,
            "route_tag": "test",
            "strict_tools_enabled": True,
        },
    )

    service = FakeService()
    session_obj = SimpleNamespace(id=7, script_id=12, episode_id=34)
    user = SimpleNamespace(id=88)
    team = SimpleNamespace(id=9)
    context = {
        "creative_stage": "storyboard_pending",
        "creative_stage_label": "分镜拆解",
        "latest_user_message": "提取分镜",
        "current_script": "测试剧本文本",
        "workspace_facts_preview": {"panel_count": 0, "resource_counts": {"characters": 2}},
        "workflow_profile": {},
        "latest_artifacts": {},
    }

    result = deepseek_tool_runtime.run_internal_director_tool_loop(
        service=service,
        session_obj=session_obj,
        user=user,
        team=team,
        context=context,
        explicit_tool_intent={"tool_name": "extract_storyboard"},
        stream_skill_hint={"id": "extract_storyboard", "label": "提取分镜"},
    )

    assert result["final_payload"]["message"] == "分镜已拆解完成。"
    assert result["final_payload"]["next_stage_hint"] == "storyboard_ready"
    assert result["final_payload"]["artifacts"]["storyboard_bundle"]["artifact_type"] == "storyboard_bundle"
    assert result["project_changes"][0]["refresh_hints"]["open_storyboard"] is True
    event_types = [item.get("type") for item in service.events]
    assert "tool_call_started" in event_types
    assert "tool_call_completed" in event_types
    second_call_messages = captured_messages[1]
    assistant_messages = [item for item in second_call_messages if item.get("role") == "assistant"]
    assert assistant_messages[-1]["reasoning_content"] == first_reasoning


def test_extract_assets_executes_live_without_submitting_task(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.commit_called = False

        def get(self, model, item_id):
            if "Script" in str(model):
                return SimpleNamespace(id=item_id, source_text="测试剧本", default_storyboard_mode="comic", style_preset="default")
            if "Episode" in str(model):
                return SimpleNamespace(id=item_id, source_text="测试剧本", storyboard_mode="comic")
            return None

        def add(self, _item):
            return None

        def commit(self):
            self.commit_called = True

    class FakeService:
        def __init__(self, session):
            self.session = session
            self.feed_items = []
            self.patches = []

        def _patch_runtime_feed_item(self, _session_obj, item_id, patch, publish=False):
            self.patches.append((item_id, dict(patch), publish))
            return {}

        def _upsert_runtime_feed_item(self, _session_obj, item, publish=False):
            self.feed_items.append((dict(item), publish))
            return {}

    fake_session = FakeSession()
    fake_service = FakeService(fake_session)

    monkeypatch.setattr(
        deepseek_tool_runtime,
        "build_agent_context",
        lambda *args, **kwargs: {
            "script": fake_session.get("Script", 11),
            "episode": fake_session.get("Episode", 22),
            "team": SimpleNamespace(id=2),
            "user": SimpleNamespace(id=1),
            "current_script": "测试剧本文本",
            "creative_stage": "assets_pending",
            "workflow_profile": {},
            "latest_artifacts": {},
            "page_context": {},
        },
    )
    monkeypatch.setattr(deepseek_tool_runtime, "resolve_effective_workflow_profile", lambda *args, **kwargs: {"style": {}})
    monkeypatch.setattr(deepseek_tool_runtime, "build_style_prompt", lambda *args, **kwargs: "")
    monkeypatch.setattr(deepseek_tool_runtime, "get_style_display_label", lambda *args, **kwargs: "默认写实")
    monkeypatch.setattr(
        deepseek_tool_runtime,
        "extract_script_assets_structured",
        lambda *args, **kwargs: {
            "characters": [{"name": "伊雪儿", "description": "女主角", "trigger_word": "白衣少女"}],
            "scenes": [{"name": "悬崖", "description": "大燕江边悬崖"}],
            "props": [{"name": "麻绳", "description": "悬坠伊雪儿的绳索"}],
            "_metrics": [],
            "_validation_errors": [],
        },
    )
    monkeypatch.setattr(
        deepseek_tool_runtime,
        "sync_structured_assets_into_shared_resources",
        lambda *args, **kwargs: {"created_count": 3, "updated_count": 0},
    )
    monkeypatch.setattr(deepseek_tool_runtime, "settings", SimpleNamespace(DEEPSEEK_API_KEY="test-key"))
    monkeypatch.setattr(
        deepseek_tool_runtime.AssetPlannerAgent,
        "_artifact_bundle",
        lambda self, _script_id: {
            "asset_bundle": {
                "artifact_type": "asset_bundle",
                "characters": [{"name": "伊雪儿", "description": "女主角", "trigger_word": "白衣少女", "has_image": False}],
                "scenes": [{"name": "悬崖", "description": "大燕江边悬崖", "trigger_word": "", "has_image": False}],
                "props": [{"name": "麻绳", "description": "悬坠伊雪儿的绳索", "trigger_word": "", "has_image": False}],
                "asset_summary": "人物 1 / 场景 1 / 道具 1",
            }
        },
    )
    monkeypatch.setattr(
        deepseek_tool_runtime,
        "_build_post_context_brief",
        lambda *args, **kwargs: {"creative_stage": "asset_images_pending"},
    )

    executor = deepseek_tool_runtime.InternalDirectorToolExecutor(
        service=fake_service,
        session_obj=SimpleNamespace(script_id=11, episode_id=22),
        user=SimpleNamespace(id=1),
        team=SimpleNamespace(id=2),
        base_context={},
    )

    result = executor.execute("extract_assets", {})

    assert result["status"] == "completed"
    assert result["result"]["artifact_type"] == "asset_bundle"
    assert result["result"]["created_count"] == 3
    assert result["refresh_hints"]["open_assets"] is True
    assert not result["result"].get("task_id")
    table_card_ids = [item["id"] for item, _publish in fake_service.feed_items if item.get("type") == "table_card"]
    assert "asset-extract-characters" in table_card_ids
    assert "asset-extract-scenes" in table_card_ids
    assert "asset-extract-props" in table_card_ids
