import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.workflow_preset_service import (
    normalize_episode_workflow_override,
    resolve_asset_extraction_storyboard_mode,
    resolve_effective_workflow_profile,
    resolve_storyboard_extraction_storyboard_mode,
)


def test_episode_workflow_override_only_keeps_deep_thinking():
    normalized = normalize_episode_workflow_override(
        {
            "profiles": {
                "comic": {
                    "aspect_ratio": "16:9",
                    "storyboard": {"deep_thinking": True},
                    "image": {"model_code": "nano-banana-pro", "resolution": "2k"},
                    "video": {
                        "model_code": "seedance_20_fast",
                        "generation_type": "reference_to_video",
                        "duration": 8,
                        "resolution": "720p",
                        "real_person_mode": False,
                    },
                    "style": {"style_id": "dynamic_manhua"},
                }
            }
        }
    )

    assert normalized == {
        "profiles": {
            "comic": {
                "storyboard": {
                    "deep_thinking": True,
                }
            }
        }
    }


def test_effective_profile_ignores_polluted_episode_override_media_fields():
    script = SimpleNamespace(
        workflow_settings_json={
            "default_storyboard_mode": "comic",
            "profiles": {
                "commentary": {},
                "comic": {
                    "aspect_ratio": "16:9",
                    "storyboard": {"deep_thinking": False},
                    "image": {"model_code": "nano-banana-2-低价版", "resolution": "4k"},
                    "video": {
                        "model_code": "seedance_20_fast",
                        "generation_type": "reference_to_video",
                        "duration": 8,
                        "resolution": "1080p",
                        "audio_enabled": True,
                        "camera_fixed": False,
                        "real_person_mode": True,
                        "web_search": False,
                        "quality_mode": "",
                        "motion_strength": "",
                    },
                    "style": {"style_id": "ai_live_action"},
                },
            },
        },
        aspect_ratio="16:9",
        style_preset="AI仿真人电影写实",
    )
    episode = SimpleNamespace(
        storyboard_mode="comic",
        workflow_override_json={
            "profiles": {
                "comic": {
                    "storyboard": {"deep_thinking": True},
                    "image": {"model_code": "nano-banana-pro", "resolution": "2k"},
                    "video": {"model_code": "seedance_v15_fast", "real_person_mode": False},
                    "style": {"style_id": "dynamic_manhua"},
                }
            }
        },
    )

    profile = resolve_effective_workflow_profile(script, episode=episode, storyboard_mode="comic")

    assert profile["storyboard"]["deep_thinking"] is True
    assert profile["image"]["model_code"] == "nano-banana-2-低价版"
    assert profile["image"]["resolution"] == "4k"
    assert profile["video"]["model_code"] == "seedance_20_fast"
    assert profile["video"]["real_person_mode"] is True
    assert profile["video"]["resolution"] == "1080p"
    assert profile["style"]["style_id"] == "ai_live_action"


def test_asset_extraction_mode_prefers_episode_mode():
    script = SimpleNamespace(
        workflow_settings_json={"default_storyboard_mode": "comic", "profiles": {"commentary": {}, "comic": {}}},
        default_storyboard_mode="comic",
        aspect_ratio="16:9",
        style_preset="默认写实",
    )
    episode = SimpleNamespace(storyboard_mode="commentary")

    assert resolve_asset_extraction_storyboard_mode(script, episode=episode) == "commentary"


def test_storyboard_extraction_mode_uses_script_default_mode():
    script = SimpleNamespace(
        workflow_settings_json={"default_storyboard_mode": "comic", "profiles": {"commentary": {}, "comic": {}}},
        default_storyboard_mode="comic",
        aspect_ratio="16:9",
        style_preset="默认写实",
    )

    assert resolve_storyboard_extraction_storyboard_mode(script) == "comic"
