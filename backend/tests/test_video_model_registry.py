from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from services.video_model_registry import (
    PRICING_RULE_FIXED_TABLE,
    PRICING_RULE_MULTIMODAL_MIN_BILL,
    PRICING_RULE_PER_SECOND,
    PRICING_RULE_PER_SECOND_WITH_ADDON,
    estimate_video_price,
    normalize_video_request,
)
from models import TemporaryUploadAsset
from services.generation_record_service import (
    _build_runninghub_video_payload,
    _compose_seedance20_prompt,
    _enrich_seedance_20_reference_request,
    _enhance_image_prompt_for_submission,
    _enhance_video_prompt_for_submission,
    _query_video_task_once,
)
from services.storyboard_director_service import render_segment_video_timeline_prompt


def _style_script():
    return SimpleNamespace(
        workflow_settings_json={
            "default_storyboard_mode": "comic",
            "profiles": {
                "comic": {
                    "style": {"custom_prompt": "电影写实质感，冷色调高对比光影"},
                }
            },
        },
        default_storyboard_mode="comic",
        aspect_ratio="16:9",
        style_preset="默认写实",
    )


def _style_episode():
    return SimpleNamespace(storyboard_mode="comic", workflow_override_json=None)


def test_image_submission_prompt_appends_workflow_style():
    script = _style_script()
    episode = _style_episode()

    prompt = _enhance_image_prompt_for_submission(
        None,
        binding={"script": script, "episode": episode, "panel": SimpleNamespace(storyboard_mode="comic")},
        payload={},
        prompt="罗峰站在训练场中央",
    )

    assert prompt.startswith("罗峰站在训练场中央")
    assert "风格基线：电影写实质感，冷色调高对比光影" in prompt


def test_video_submission_prompt_appends_workflow_style():
    script = _style_script()
    episode = _style_episode()

    prompt = _enhance_video_prompt_for_submission(
        None,
        binding={"script": script, "episode": episode, "panel": SimpleNamespace(storyboard_mode="comic")},
        normalized={"model_code": "seedance_v15_fast"},
        prompt="罗峰向前冲刺，镜头低角度跟拍",
    )

    assert prompt.startswith("罗峰向前冲刺")
    assert "风格基线：电影写实质感，冷色调高对比光影" in prompt


def test_official_veo_fixed_table_estimate():
    normalized = normalize_video_request(
        {
            "model_code": "veo_31_fast_official",
            "generation_type": "text_to_video",
            "prompt": "test",
            "duration": 4,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "audio_enabled": False,
        }
    )
    result = estimate_video_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert result["pricing_rule_type"] == PRICING_RULE_FIXED_TABLE
    assert result["sell_price_points"] == 30


def test_seedance_20_fast_per_second_estimate():
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20_fast",
            "generation_type": "text_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "audio_enabled": False,
        }
    )
    result = estimate_video_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert result["pricing_rule_type"] == PRICING_RULE_PER_SECOND
    assert result["sell_price_points"] == 65


def test_seedance_20_multimodal_min_bill_estimate():
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20",
            "generation_type": "reference_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "1080p",
            "aspect_ratio": "adaptive",
            "video_refs": ["https://example.com/ref.mp4"],
            "input_video_duration": 4,
        }
    )
    result = estimate_video_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert result["pricing_rule_type"] == PRICING_RULE_MULTIMODAL_MIN_BILL
    assert result["pricing_details"]["bill_seconds"] == 9


def test_kling_o3_reference_addon_estimate():
    normalized = normalize_video_request(
        {
            "model_code": "kling_o3_reference_pro",
            "generation_type": "reference_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "audio_enabled": True,
            "video_refs": ["https://example.com/ref.mp4"],
        }
    )
    result = estimate_video_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert result["pricing_rule_type"] == PRICING_RULE_PER_SECOND_WITH_ADDON
    assert result["sell_price_points"] == 95


def test_seedance_20_image_payload_uses_frame_url_fields():
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20_fast",
            "generation_type": "image_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "first_frame": "https://example.com/first.jpg",
            "last_frame": "https://example.com/last.jpg",
            "audio_enabled": True,
        }
    )
    payload = _build_runninghub_video_payload("seedance20_fast_image", normalized)
    assert payload["firstFrameUrl"] == "https://example.com/first.jpg"
    assert payload["lastFrameUrl"] == "https://example.com/last.jpg"
    assert "firstImageUrl" not in payload
    assert "lastImageUrl" not in payload


def test_seedance_20_text_payload_uses_web_search_flag():
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20",
            "generation_type": "text_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "web_search": True,
        }
    )
    payload = _build_runninghub_video_payload("seedance20_text", normalized)
    assert payload["webSearch"] is True


def test_seedance_20_reference_payload_uses_real_person_mode():
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20_fast",
            "generation_type": "reference_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "image_refs": ["https://example.com/ref.jpg"],
            "real_person_mode": True,
        }
    )
    payload = _build_runninghub_video_payload("seedance20_fast_reference", normalized)
    assert payload["realPersonMode"] is True


def test_seedance_20_text_defaults_to_adaptive_aspect_ratio():
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20",
            "generation_type": "text_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
        }
    )
    assert normalized["aspect_ratio"] == "adaptive"


def test_seedance_20_reference_audio_requires_visual_refs():
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20",
            "generation_type": "reference_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "audio_refs": ["https://example.com/audio.mp3"],
        }
    )
    with pytest.raises(Exception) as exc_info:
        _enrich_seedance_20_reference_request(None, normalized, {})
    assert getattr(exc_info.value, "status_code", None) == 400
    assert "参考音频必须搭配参考图或参考视频" in str(exc_info.value.detail)


def _build_temp_asset(*, media_type: str, file_url: str, duration_seconds: float) -> TemporaryUploadAsset:
    now = datetime.utcnow()
    return TemporaryUploadAsset(
        content_hash=f"hash-{media_type}-{file_url}",
        media_type=media_type,
        storage_object_key=f"temp/{media_type}",
        file_url=file_url,
        thumbnail_url="",
        original_filename=f"{media_type}.bin",
        mime_type="video/mp4" if media_type == "video" else "audio/mpeg",
        file_size=1,
        duration_seconds=duration_seconds,
        has_audio=True,
        width=1920 if media_type == "video" else None,
        height=1080 if media_type == "video" else None,
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )


def test_seedance_20_reference_rejects_non_temporary_video_refs(monkeypatch):
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20",
            "generation_type": "reference_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "video_refs": ["https://example.com/video.mp4"],
        }
    )
    monkeypatch.setattr("services.generation_record_service._load_temporary_uploads_by_url", lambda session, urls: {})
    with pytest.raises(Exception) as exc_info:
        _enrich_seedance_20_reference_request(object(), normalized, {})
    assert getattr(exc_info.value, "status_code", None) == 400
    assert getattr(exc_info.value, "detail", {}).get("error") == "video_refs_unsupported_source"


def test_query_video_task_once_converts_runninghub_business_exception_to_failed(monkeypatch):
    def _raise_runninghub_error(awaitable):
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        raise Exception(
            "RunningHub 接口内部报错: Current mode does not support real-person content. "
            "To enable it, set realPersonMode to true"
        )

    monkeypatch.setattr(
        "services.generation_record_service._run_async_blocking",
        _raise_runninghub_error,
    )
    result = _query_video_task_once("runninghub:seedance_20", "task-123")
    assert result.is_done is True
    assert result.is_failed is True
    assert "realPersonMode" in str(result.error or "")


def test_seedance_20_reference_uses_uploaded_video_duration_for_billing(monkeypatch):
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20",
            "generation_type": "reference_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "video_refs": ["https://example.com/video.mp4"],
        }
    )
    asset = _build_temp_asset(media_type="video", file_url="https://example.com/video.mp4", duration_seconds=4.2)
    monkeypatch.setattr(
        "services.generation_record_service._load_temporary_uploads_by_url",
        lambda session, urls: {asset.file_url: asset},
    )
    enriched = _enrich_seedance_20_reference_request(object(), normalized, {})
    assert enriched["input_video_duration"] == 5


def test_seedance_20_reference_rejects_invalid_audio_duration(monkeypatch):
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20",
            "generation_type": "reference_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "image_refs": ["https://example.com/ref.jpg"],
            "audio_refs": ["https://example.com/audio.mp3"],
        }
    )
    asset = _build_temp_asset(media_type="audio", file_url="https://example.com/audio.mp3", duration_seconds=16.0)
    monkeypatch.setattr(
        "services.generation_record_service._load_temporary_uploads_by_url",
        lambda session, urls: {asset.file_url: asset},
    )
    with pytest.raises(Exception) as exc_info:
        _enrich_seedance_20_reference_request(object(), normalized, {})
    assert getattr(exc_info.value, "status_code", None) == 400
    assert getattr(exc_info.value, "detail", {}).get("error") == "reference_media_duration_invalid"


def test_normalize_video_request_sorts_storyboard_board_image_entry_last():
    normalized = normalize_video_request(
        {
            "model_code": "seedance_20",
            "generation_type": "reference_to_video",
            "prompt": "test",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "adaptive",
            "image_ref_entries": [
                {"url": "https://example.com/board.jpg", "label": "分镜宫格图", "role": "storyboard_board"},
                {"url": "https://example.com/hero.jpg", "label": "主角", "role": "semantic"},
                {"url": "https://example.com/extra.jpg", "label": "补充图", "role": "auxiliary"},
            ],
        }
    )
    assert [item["label"] for item in normalized["image_ref_entries"]] == ["主角", "补充图", "分镜宫格图"]
    assert normalized["image_refs"] == [
        "https://example.com/hero.jpg",
        "https://example.com/extra.jpg",
        "https://example.com/board.jpg",
    ]


def test_render_segment_video_timeline_prompt_includes_camera_and_cutting_semantics():
    cells = [
        {
            "start_second": 0,
            "end_second": 2,
            "shot_type": "远景",
            "camera_motion": "推进",
            "camera_position": "侧前方",
            "camera_direction": "朝向主角与悬崖",
            "action_description": "@主角在@悬崖边试探性前行",
            "scene_refs": ["悬崖"],
            "character_refs": ["主角"],
            "prop_refs": [],
            "lighting": "冷色逆光",
            "ambiance": "紧张压迫",
            "shot_purpose": "建立空间与危险关系",
            "dialogue_excerpt": "",
        },
        {
            "start_second": 2,
            "end_second": 4,
            "shot_type": "近景",
            "camera_motion": "静止",
            "camera_position": "平视",
            "camera_direction": "朝向主角侧脸",
            "action_description": "@主角抬眼望向前方，呼吸明显变重",
            "scene_refs": ["悬崖"],
            "character_refs": ["主角"],
            "prop_refs": [],
            "lighting": "冷色逆光",
            "ambiance": "紧张压迫",
            "shot_purpose": "切入人物反应",
            "dialogue_excerpt": "",
        },
    ]

    prompt = render_segment_video_timeline_prompt(cells, transition_to_next="dissolve")

    assert "镜头语言" in prompt
    assert "切镜：结尾直接切到下一镜的近景" in prompt
    assert "切镜：结尾以溶解转场衔接下一分镜" in prompt
    assert "参考策略：" in prompt


def test_compose_seedance20_prompt_appends_shot_control_and_reference_guidance():
    normalized = {
        "generation_type": "reference_to_video",
        "image_refs": ["https://example.com/ref1.jpg"],
        "video_refs": ["https://example.com/ref1.mp4"],
        "audio_refs": ["https://example.com/ref1.mp3"],
        "audio_url": "",
        "duration": 5,
        "aspect_ratio": "16:9",
        "resolution": "720p",
    }
    context = {
        "scene_prompt": "分镜设定：场景：@天台；人物：@主角；夜风很强。",
        "shot_controls": [
            "镜头1：@主角在@天台中缓慢前行；镜头语言：远景，机位侧前方，运镜推进；切镜：结尾直接切到下一镜的近景，继续抬眼观察",
        ],
        "reference_assets": ["@主角", "@天台"],
    }

    prompt = _compose_seedance20_prompt(
        "0-2秒：远景，@主角缓慢前行",
        normalized=normalized,
        context=context,
        style_preset="默认写实",
    )

    assert "镜头控制：" in prompt
    assert "参考控制：" in prompt
    assert "参考视频 1 段用于约束动作轨迹、运镜节奏与切镜感觉。" in prompt
    assert "风格基线：默认写实" in prompt


def test_compose_seedance20_prompt_builds_comic_submit_prompt_without_image_mapping():
    normalized = {
        "model_code": "seedance_20",
        "generation_type": "reference_to_video",
        "image_ref_entries": [
            {"url": "https://example.com/hero.jpg", "label": "伊雪儿", "role": "semantic"},
            {"url": "https://example.com/scene.jpg", "label": "悬崖峭壁", "role": "semantic"},
            {"url": "https://example.com/rope.jpg", "label": "麻绳", "role": "semantic"},
            {"url": "https://example.com/board.jpg", "label": "分镜宫格图", "role": "storyboard_board"},
        ],
        "video_ref_entries": [],
        "audio_ref_entries": [],
        "duration": 8,
        "aspect_ratio": "16:9",
        "resolution": "480p",
    }
    context = {
        "storyboard_mode": "comic",
        "scene_prompt": "图片1（伊雪儿）被绑在悬崖外侧。",
        "reference_asset_items": [
            {"name": "伊雪儿", "type": "character"},
            {"name": "悬崖峭壁", "type": "scene"},
            {"name": "麻绳", "type": "prop"},
        ],
        "quality_constraints": ["保持人物稳定，不要跳脸"],
    }
    prompt = _compose_seedance20_prompt(
        "分镜设定：图片1（伊雪儿）被绑在悬崖外侧。\n时间轴：\n0-2秒：远景建立悬崖压迫。\n质量约束：保持人物稳定，不要跳脸",
        normalized=normalized,
        context=context,
        style_preset="短剧电影写实风",
    )

    assert "全局基础设定：" in prompt
    assert "参考映射：" not in prompt
    assert "时间轴：" in prompt
    assert "质量约束：" in prompt
    assert "生成要求：" in prompt
    assert "图片4（分镜宫格图）：" not in prompt
    assert "用于镜头顺序、构图节奏与切镜衔接参考" not in prompt


def test_compose_seedance20_prompt_sanitizes_double_at_asset_mentions():
    normalized = {
        "model_code": "seedance_20_fast",
        "generation_type": "reference_to_video",
        "image_ref_entries": [
            {"url": "https://example.com/teacher.jpg", "label": "老师", "role": "semantic"},
            {"url": "https://example.com/luofeng.jpg", "label": "罗峰", "role": "semantic"},
            {"url": "https://example.com/classroom.jpg", "label": "普通高中教室", "role": "semantic"},
        ],
        "video_ref_entries": [],
        "audio_ref_entries": [],
        "duration": 7,
        "aspect_ratio": "16:9",
        "resolution": "720p",
    }
    context = {
        "storyboard_mode": "comic",
        "reference_asset_items": [
            {"name": "@老师", "type": "character"},
            {"name": "@罗峰", "type": "character"},
            {"name": "@普通高中教室", "type": "scene"},
        ],
        "quality_constraints": ["保持人物脸部、发型、服装和体型稳定，不要跳脸或突然换装"],
    }

    prompt = _compose_seedance20_prompt(
        "分镜设定：@@老师、@@罗峰保持人物外观、服装与表情连续；@@普通高中教室保持场景空间方向稳定\n"
        "时间轴：\n0-7秒：@罗峰在@普通高中教室中老师讲解相对论。",
        normalized=normalized,
        context=context,
        style_preset="短剧电影写实风",
    )

    assert "@@" not in prompt
    assert "@老师、@罗峰保持人物外观、服装与表情连续" in prompt
    assert "参考映射：" not in prompt
    assert "图片1（老师）：锁定人物外观、服装、发型与面部一致性。" not in prompt
    assert "图片3（普通高中教室）：锁定场景空间关系与背景方向。" not in prompt


def test_build_gridcell_video_prompt_structured_exposes_reference_strategy():
    from services.storyboard_director_service import build_gridcell_video_prompt_structured

    structured = build_gridcell_video_prompt_structured(
        action_description="主角转身看向门口",
        camera_motion="推进",
        reference_strategy="参考图锁定人物服装，参考视频约束转身节奏",
    )

    assert structured["reference_strategy"] == "参考图锁定人物服装，参考视频约束转身节奏"
