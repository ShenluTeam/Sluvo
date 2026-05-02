import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.assistant_runtime import runtime_v2_overrides


class _DummyService:
    def _build_turn(self, *, role, blocks, metadata):
        return {
            "role": role,
            "blocks": blocks,
            "metadata": metadata,
        }


def test_save_script_turn_skips_followup_agent_artifact_previews():
    service = _DummyService()
    turn = runtime_v2_overrides._build_structured_agent_turn(
        service,
        agent_response={
            "message": "剧本已保存到当前工作区。",
            "artifacts": {
                "asset_bundle": {
                    "artifact_type": "asset_bundle",
                    "asset_summary": "当前资产数：0",
                }
            },
            "suggested_actions": [{"type": "extract_assets", "label": "提取资产"}],
            "stage": "assets_pending",
            "active_agent": "asset_planner_agent",
        },
        turn_source="structured_agent_action",
        message_override="剧本已保存到当前工作区。",
        result_artifacts={
            "artifact_type": "script_draft",
            "script_summary": "这是保存后的剧本摘要",
        },
        include_followup_artifacts=False,
    )

    artifact_types = [block.get("artifact_type") for block in turn["blocks"] if block.get("type") == "artifact_preview"]

    assert artifact_types == ["script_draft"]
    assert any(block.get("type") == "agent_actions" for block in turn["blocks"])


def test_non_save_actions_can_still_include_followup_agent_artifacts():
    service = _DummyService()
    turn = runtime_v2_overrides._build_structured_agent_turn(
        service,
        agent_response={
            "message": "资产提取完成。",
            "artifacts": {
                "asset_bundle": {
                    "artifact_type": "asset_bundle",
                    "asset_summary": "当前资产数：3",
                }
            },
            "suggested_actions": [{"type": "generate_asset_images", "label": "生成资产参考图"}],
            "stage": "asset_images_pending",
            "active_agent": "asset_planner_agent",
        },
        turn_source="structured_agent_action",
        message_override="资产提取完成。",
        result_artifacts={},
        include_followup_artifacts=True,
    )

    artifact_types = [block.get("artifact_type") for block in turn["blocks"] if block.get("type") == "artifact_preview"]

    assert artifact_types == ["asset_bundle"]


def test_extract_assets_turn_skips_followup_agent_artifact_previews():
    service = _DummyService()
    turn = runtime_v2_overrides._build_structured_agent_turn(
        service,
        agent_response={
            "message": "资产提取完成。",
            "artifacts": {
                "asset_bundle": {
                    "artifact_type": "asset_bundle",
                    "asset_summary": "当前资产数：3",
                }
            },
            "suggested_actions": [{"type": "generate_asset_images", "label": "生成资产参考图"}],
            "stage": "asset_images_pending",
            "active_agent": "asset_planner_agent",
        },
        turn_source="structured_agent_action",
        message_override="资产提取完成。",
        result_artifacts={
            "artifact_type": "asset_bundle",
            "asset_summary": "人物 1 / 场景 1 / 道具 1",
        },
        include_followup_artifacts=False,
    )

    artifact_types = [block.get("artifact_type") for block in turn["blocks"] if block.get("type") == "artifact_preview"]

    assert artifact_types == ["asset_bundle"]
    assert len([block for block in turn["blocks"] if block.get("type") == "artifact_preview"]) == 1


def test_extract_assets_action_hides_result_artifact_card():
    assert runtime_v2_overrides._include_result_artifacts_for_action("extract_assets") is False
    assert runtime_v2_overrides._include_result_artifacts_for_action("save_script") is True


def test_merge_suggested_actions_keeps_save_script_followups_before_stage_actions():
    merged = runtime_v2_overrides._merge_suggested_actions(
        [
            {"type": "rewrite_script", "label": "继续完善现有剧本", "payload": {"script_draft": "abc"}},
            {"type": "extract_assets", "label": "开始角色与场景设计"},
        ],
        [
            {"type": "extract_assets", "label": "提取资产"},
            {"type": "generate_asset_images", "label": "生成资产参考图"},
        ],
    )

    assert [item["type"] for item in merged] == ["rewrite_script", "extract_assets", "generate_asset_images"]


def test_merge_suggested_actions_deduplicates_same_type_and_payload():
    merged = runtime_v2_overrides._merge_suggested_actions(
        [{"type": "extract_assets", "label": "开始角色与场景设计"}],
        [{"type": "extract_assets", "label": "提取资产"}],
    )

    assert [item["type"] for item in merged] == ["extract_assets"]


def test_merge_suggested_actions_does_not_reinject_same_primary_action_type():
    merged = runtime_v2_overrides._merge_suggested_actions(
        [
            {"type": "generate_asset_images", "label": "生成场景图", "payload": {"generation_scope": "scene"}},
            {"type": "extract_storyboard", "label": "提取分镜"},
        ],
        [
            {"type": "generate_asset_images", "label": "生成人物图", "payload": {"generation_scope": "character"}},
            {"type": "open_assets_upload", "label": "我自己上传资产图"},
        ],
    )

    assert [item["type"] for item in merged] == ["generate_asset_images", "extract_storyboard", "open_assets_upload"]
    assert merged[0]["payload"]["generation_scope"] == "scene"


def test_smalltalk_capability_reply_uses_product_language_without_tool_names():
    reply = runtime_v2_overrides._match_smalltalk_reply("你会干什么")

    assert reply
    assert "save_script" not in reply
    assert "generate_audio" not in reply
    assert "search_reference_materials" not in reply
    assert "剧本" in reply
    assert "分镜" in reply
    assert "配音" in reply
    assert "漫剧" in reply
    assert "多智能体协同" in reply


def test_merge_suggested_actions_normalizes_action_type_aliases():
    merged = runtime_v2_overrides._merge_suggested_actions(
        [{"action_type": "generate_storyboard_images", "label": "生成全部分镜图"}],
        [
            {"type": "generate_storyboard_images", "label": "继续下一步"},
            {"action": "generate_video", "label": "生成视频"},
        ],
    )

    assert [item["type"] for item in merged] == ["generate_storyboard_images", "generate_video"]
    assert merged[0]["label"] == "生成全部分镜图"


def test_next_step_request_fills_stage_actions_when_model_omits_them(monkeypatch):
    def fake_run_active_agent(context):
        assert context["disable_llm"] is True
        return {
            "message": "阶段建议已整理。",
            "stage": "storyboard_ready",
            "stage_label": "分镜已就绪",
            "active_agent": "generation_agent",
            "suggested_actions": [
                {"type": "generate_storyboard_images", "label": "一键生成全部分镜图"},
                {"type": "open_storyboard", "label": "打开分镜表"},
            ],
            "artifacts": {"generation_bundle": {"artifact_type": "generation_bundle"}},
        }

    monkeypatch.setattr(runtime_v2_overrides, "run_active_agent", fake_run_active_agent)

    response = runtime_v2_overrides._ensure_next_step_suggested_actions(
        content="下一步",
        agent_response={"message": "你希望下一步做什么呢？以下是建议：", "suggested_actions": []},
        context={"creative_stage": "storyboard_ready"},
    )

    assert response["message"] == "你希望下一步做什么呢？以下是建议："
    assert [item["type"] for item in response["suggested_actions"]] == [
        "generate_storyboard_images",
        "open_storyboard",
    ]
    assert response["stage"] == "storyboard_ready"


def test_generate_asset_images_delays_followup_actions_until_tasks_finish():
    assert runtime_v2_overrides._should_delay_followup_actions_for_action(
        "generate_asset_images",
        {
            "result": {
                "submitted_assets": [
                    {"name": "伊雪儿", "task_id": "task-1"},
                    {"name": "慕容宸", "task_id": "task-2"},
                ]
            }
        },
    ) is True

    assert runtime_v2_overrides._should_delay_followup_actions_for_action(
        "extract_storyboard",
        {"result": {"submitted_assets": [{"name": "伊雪儿", "task_id": "task-1"}]}},
    ) is False


def test_generate_storyboard_images_delays_followup_actions_until_tasks_finish():
    assert runtime_v2_overrides._should_delay_followup_actions_for_action(
        "generate_storyboard_images",
        {
            "result": {
                "submitted_panels": [
                    {"panel_sequence": 1, "task_id": "task-1"},
                    {"panel_sequence": 2, "task_id": "task-2"},
                ]
            }
        },
    ) is True


def test_runtime_facts_source_card_uses_view_script_copy():
    cards = runtime_v2_overrides._runtime_feed_facts_cards(
        {
            "workspace_facts": {
                "script_name": "测试项目",
                "episode_title": "第1集",
                "episode_has_source_text": True,
                "current_script": "罗峰进入训练场，发现新的精神念力测试即将开始。",
                "resource_counts": {"characters": 2, "scenes": 1, "props": 1},
                "asset_image_count": 3,
                "characters": [{"name": "罗峰"}, {"name": "徐欣"}],
                "scenes": [{"name": "极限武馆训练场"}],
                "props": [{"name": "精神念力飞刀"}],
                "panel_count": 2,
                "panels_with_images": 1,
                "panels_with_videos": 0,
                "panels": [
                    {"sequence_num": 1, "summary": "罗峰进入训练场，镜头跟随他观察测试设备。"},
                    {"sequence_num": 2, "summary": "教官宣布精神念力测试即将开始。"},
                ],
            },
            "stage_facts": {},
        }
    )

    source_card = next(item for item in cards if item.get("id") == "facts-source")
    assert source_card["title"] == "正在查看剧本"
    assert source_card["body"] == "已读取当前剧本：罗峰进入训练场，发现新的精神念力测试即将开始。"
    asset_card = next(item for item in cards if item.get("id") == "facts-assets")
    assert "资产名单：人物：罗峰、徐欣；场景：极限武馆训练场；道具：精神念力飞刀" in asset_card["body"]
    storyboard_card = next(item for item in cards if item.get("id") == "facts-storyboard")
    assert "分镜摘要：第 1 镜：罗峰进入训练场，镜头跟随他观察测试设备。；第 2 镜：教官宣布精神念力测试即将开始。" in storyboard_card["body"]


def test_long_script_source_message_uses_fast_path_detection():
    content = """【剧本正文】
场景一：路边·黄昏
（特写）一双脏兮兮的小爪子，在水泥地上不停地刨。
阿福蹲坐在路边，眼睛死死盯着远处那辆启动的面包车。
小男孩趴在车窗上哭喊：“阿福！阿福！”
车子开走了。阿福猛地追上去，跑累了，停下来发出一声呜咽。
天空中一颗流星划过，稍纵即逝。

场景二：狗贩子窝点·夜
阿福被铁钳夹住脖子，想要挣脱，刀疤脸男人一棍砸下。
趁刀疤脸转身，它疯狂撞开铁笼笼门，拖着伤腿冲进夜色。
"""

    assert runtime_v2_overrides._looks_like_script_source_message(content) is True
    assert runtime_v2_overrides._looks_like_script_source_message("帮我看看当前进度") is False


class _RuntimeStateService:
    def __init__(self, runtime_state=None):
        self.runtime_state = dict(runtime_state or {})
        self.feed = [
            {"id": "status-main", "type": "status_card", "status": "running"},
            {"id": "thought-plan", "type": "thought_card", "status": "running"},
        ]
        self.events = []

    def _get_runtime_state(self, _session_obj):
        return dict(self.runtime_state)

    def _update_runtime_state(self, _session_obj, **kwargs):
        clear_keys = kwargs.pop("clear_keys", None) or []
        kwargs.pop("commit", None)
        for key, value in kwargs.items():
            if value is not None:
                self.runtime_state[key] = value
        for key in clear_keys:
            self.runtime_state.pop(key, None)
        return dict(self.runtime_state)

    def _build_tool_activity(self, _skill_hint, _session_obj):
        return [
            {"id": "ctx", "label": "context", "status": "running"},
            {"id": "plan", "label": "plan", "status": "pending"},
            {"id": "result", "label": "result", "status": "pending"},
        ]

    def _build_draft_turn(self, **kwargs):
        return {"role": "assistant", "blocks": [], "metadata": kwargs}

    def _get_runtime_feed(self, _session_obj):
        return [dict(item) for item in self.feed]

    def _patch_runtime_feed_item(self, _session_obj, item_id, patch, publish=True):
        for index, item in enumerate(self.feed):
            if item.get("id") == item_id:
                self.feed[index] = {**item, **patch}
                return self.feed[index]
        return None

    def publish_event(self, _session_id, event):
        self.events.append(event)

    def _publish_runtime_delta(self, _session_obj):
        self.events.append({"type": "delta"})


class _SessionObj:
    id = 1


def test_public_reasoning_reuses_template_within_same_phase():
    service = _RuntimeStateService()
    session_obj = _SessionObj()

    runtime_v2_overrides._update_reasoning_progress(
        service,
        session_obj,
        content="提取分镜",
        skill_hint={"id": "extract_storyboard"},
        reasoning_text="abc",
        reasoning_delta="a",
    )
    first_id = service.runtime_state["public_reasoning_template_id"]

    runtime_v2_overrides._update_reasoning_progress(
        service,
        session_obj,
        content="提取分镜",
        skill_hint={"id": "extract_storyboard"},
        reasoning_text="abcdef",
        reasoning_delta="b",
    )

    assert service.runtime_state["public_reasoning_template_id"] == first_id
    assert service.feed[1]["template_id"] == first_id
    assert service.feed[1]["persona"] == "分镜导演"


def test_public_reasoning_changes_template_when_phase_changes():
    service = _RuntimeStateService()
    session_obj = _SessionObj()

    runtime_v2_overrides._update_reasoning_progress(
        service,
        session_obj,
        content="提取资产",
        skill_hint={"id": "extract_assets"},
        reasoning_text="a" * 10,
    )
    first_phase = service.runtime_state["public_reasoning_phase"]
    first_id = service.runtime_state["public_reasoning_template_id"]
    service.runtime_state["reasoning_public_phase_started_ms"] = 1

    runtime_v2_overrides._update_reasoning_progress(
        service,
        session_obj,
        content="提取资产",
        skill_hint={"id": "extract_assets"},
        reasoning_text="a" * 200,
    )

    assert first_phase == "understand_request"
    assert service.runtime_state["public_reasoning_phase"] == "prepare_result"
    assert service.runtime_state["public_reasoning_template_id"] != first_id


def test_public_reasoning_prefers_avoiding_recent_template_ids():
    recent = [
        "extract_storyboard.understand_request.01",
        "extract_storyboard.understand_request.02",
        "extract_storyboard.understand_request.03",
    ]
    service = _RuntimeStateService({"public_reasoning_recent_template_ids": recent})
    session_obj = _SessionObj()

    runtime_v2_overrides._update_reasoning_progress(
        service,
        session_obj,
        content="提取分镜",
        skill_hint={"id": "extract_storyboard"},
        reasoning_text="abc",
    )

    assert service.runtime_state["public_reasoning_template_id"] == "extract_storyboard.understand_request.04"
    assert service.runtime_state["public_reasoning_recent_template_ids"][0] == "extract_storyboard.understand_request.04"


def test_public_reasoning_unknown_intent_falls_back_to_general_question():
    service = _RuntimeStateService()
    session_obj = _SessionObj()

    runtime_v2_overrides._update_reasoning_progress(
        service,
        session_obj,
        content="帮我看看",
        skill_hint={"id": "unknown_skill"},
        reasoning_text="abc",
    )

    assert service.runtime_state["public_reasoning_intent"] == "general_project_question"
    assert service.feed[1]["persona"] == "总导演"
