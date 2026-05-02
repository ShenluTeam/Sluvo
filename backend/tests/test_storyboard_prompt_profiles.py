import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schemas import STORYBOARD_MODE_COMIC, STORYBOARD_MODE_COMMENTARY
from services.storyboard_director_service import (
    StorySegmentParseError,
    _call_json_model_with_repair,
    _create_deepseek_chat_completion,
    build_commentary_story_segment_prompt_v3,
    build_comic_story_segment_prompt_v3,
    _render_comic_segment_video_prompt,
    _story_grid_batch_expander_prompt,
    _story_grid_expander_prompt,
    _story_segment_planner_prompt,
    build_segment_prompt_locks,
    render_segment_scene_prompt,
)


def test_commentary_and_comic_director_prompts_have_distinct_mode_focus():
    commentary_prompt = build_commentary_story_segment_prompt_v3()
    comic_prompt = build_comic_story_segment_prompt_v3()
    assert "story_segments" in commentary_prompt
    assert "story_segments" in comic_prompt
    assert "JSON" in commentary_prompt
    assert "JSON" in comic_prompt
    assert commentary_prompt != comic_prompt


def test_deepseek_chat_completion_enables_json_output_mode_by_default():
    captured = {}

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return object()

    class _Client:
        class _Chat:
            completions = _Completions()

        chat = _Chat()

    _create_deepseek_chat_completion(
        _Client(),
        model="deepseek-chat",
        messages=[{"role": "system", "content": "return JSON"}],
        max_tokens=128,
    )

    assert captured["response_format"] == {"type": "json_object"}
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["extra_body"]["thinking"]["type"] == "disabled"


def test_planner_prompt_emphasizes_segment_boundary_not_mechanical_split():
    planner_prompt = _story_segment_planner_prompt(STORYBOARD_MODE_COMIC)
    assert "story_segments" in planner_prompt
    assert "grid_cells" in planner_prompt
    assert "JSON" in planner_prompt
    assert "schema" in planner_prompt


def test_expander_prompt_emphasizes_shot_function_and_variation():
    expander_prompt = _story_grid_expander_prompt(STORYBOARD_MODE_COMMENTARY)
    assert "grid_cells" in expander_prompt
    assert "duration_seconds" in expander_prompt
    assert "JSON" in expander_prompt
    assert "schema" in expander_prompt


def test_batch_expander_prompt_requires_segment_local_timeline():
    batch_prompt = _story_grid_batch_expander_prompt(STORYBOARD_MODE_COMIC)

    assert "段内相对时间轴" in batch_prompt
    assert "recommended_duration_seconds" in batch_prompt
    assert "不要使用整集累计时间轴" in batch_prompt


def test_scene_prompt_and_comic_video_prompt_have_no_garbled_placeholders_or_double_at():
    segment = {
        "summary": "暴雨中的悬崖险境",
        "scene_constraint": "@悬崖边 外景，狂风暴雨，麻绳悬垂",
        "scene_refs": ["@悬崖边"],
        "character_refs": ["@伊雪儿"],
        "prop_refs": ["@麻绳"],
        "grid_count": 4,
        "continuity_state": {
            "scene_anchor": "@悬崖边 外景，狂风暴雨，麻绳悬垂",
            "characters": ["伊雪儿"],
            "costume_state": {"伊雪儿": ["她身着素白囚衣"]},
            "body_state": {"伊雪儿": ["双臂反绑"]},
            "prop_state": ["麻绳在风中摇晃"],
            "carry_forward": ["她身着素白囚衣", "双臂反绑", "麻绳在风中摇晃"],
        },
    }
    locks = build_segment_prompt_locks(segment, aspect_ratio="16:9", storyboard_mode=STORYBOARD_MODE_COMIC)
    scene_prompt = render_segment_scene_prompt(
        summary=segment["summary"],
        scene_constraint=segment["scene_constraint"],
        scene_refs=["@悬崖边"],
        character_refs=["@伊雪儿"],
        prop_refs=["@麻绳"],
        prompt_locks=locks,
    )

    assert "???" not in scene_prompt
    assert "@@" not in scene_prompt

    video_prompt = _render_comic_segment_video_prompt([
        {
            "start_second": 0,
            "end_second": 2,
            "shot_type": "远景",
            "camera_motion": "固定",
            "camera_position": "崖外高处",
            "camera_direction": "俯视悬崖与江面",
            "shot_description": "悬崖占据主体画面，江水翻涌",
            "action_description": "镜头建立暴雨悬崖的压迫环境",
            "composition": "悬崖与江面共同占据主体画面",
            "lighting": "阴冷天光",
            "ambiance": "压抑、凶险",
            "shot_purpose": "建立险境",
            "scene_refs": ["@悬崖边"],
            "character_refs": ["@伊雪儿"],
            "prop_refs": ["@麻绳"],
        }
    ])

    assert "@@" not in video_prompt


def test_call_json_model_with_repair_retries_on_empty_response(monkeypatch):
    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Message(content)

    class _Response:
        def __init__(self, content):
            self.choices = [_Choice(content)]
            self.usage = None

    responses = [_Response(""), _Response('{"ok": true}')]
    called_models = []

    monkeypatch.setattr("services.storyboard_director_service.OpenAI", lambda *args, **kwargs: object())
    monkeypatch.setattr("services.storyboard_director_service._create_deepseek_chat_completion", lambda client, **kwargs: (called_models.append(kwargs.get("model")) or responses.pop(0)))
    monkeypatch.setattr("services.storyboard_director_service.settings.DEEPSEEK_STORY_SEGMENT_USE_STRICT_SCHEMA", False)

    payload = _call_json_model_with_repair(
        api_key="test-key",
        model="deepseek-chat",
        provider_timeout_seconds=None,
        json_fix_timeout_seconds=None,
        max_tokens=256,
        system_prompt="system",
        user_prompt="user",
        repair_storyboard_mode=STORYBOARD_MODE_COMIC,
        repair_schema_prompt=None,
        repair_example_prompt=None,
        provider_timeout_code="planner_timeout",
        provider_timeout_message="planner timeout",
        provider_error_code="provider_error",
        provider_error_message="provider error",
        invalid_json_code="planner_invalid_json",
        invalid_json_message="planner empty",
    )

    assert payload["ok"] is True
    assert called_models == ["deepseek-v4-flash", "deepseek-v4-flash"]


def test_call_json_model_with_repair_rewraps_empty_error_to_stage_specific_code(monkeypatch):
    class _Message:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Message(content)

    class _Response:
        def __init__(self, content):
            self.choices = [_Choice(content)]
            self.usage = None

    responses = [_Response(""), _Response(""), _Response(""), _Response("")]

    monkeypatch.setattr("services.storyboard_director_service.OpenAI", lambda *args, **kwargs: object())
    monkeypatch.setattr("services.storyboard_director_service._create_deepseek_chat_completion", lambda client, **kwargs: responses.pop(0))
    monkeypatch.setattr("services.storyboard_director_service.settings.DEEPSEEK_STORY_SEGMENT_USE_STRICT_SCHEMA", False)

    try:
        _call_json_model_with_repair(
            api_key="test-key",
            model="deepseek-chat",
            provider_timeout_seconds=None,
            json_fix_timeout_seconds=None,
            max_tokens=256,
            system_prompt="system",
            user_prompt="user",
            repair_storyboard_mode=STORYBOARD_MODE_COMMENTARY,
            repair_schema_prompt=None,
            repair_example_prompt=None,
            provider_timeout_code="planner_timeout",
            provider_timeout_message="planner timeout",
            provider_error_code="provider_error",
            provider_error_message="provider error",
            invalid_json_code="planner_invalid_json",
            invalid_json_message="planner empty",
        )
        assert False, "expected StorySegmentParseError"
    except StorySegmentParseError as exc:
        assert exc.error_code == "planner_invalid_json"


def test_prompts_bias_to_medium_grid_counts_and_preserve_speech_layers():
    planner_prompt = _story_segment_planner_prompt(STORYBOARD_MODE_COMIC)
    expander_prompt = _story_grid_expander_prompt(STORYBOARD_MODE_COMIC)

    assert "4 宫格或 6 宫格" in planner_prompt
    assert "单宫格 + 长时长" in planner_prompt
    assert "内心独白" in planner_prompt
    assert "画外音" in planner_prompt
    assert "speech_coverage_targets" in expander_prompt
    assert "不要做成长时长单宫格" in expander_prompt
    assert "不要做 9 宫格" in expander_prompt
