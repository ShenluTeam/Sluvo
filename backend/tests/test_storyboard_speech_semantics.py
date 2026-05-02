import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.story_segment_service import _build_grid_cell, _cell_payload
from services.storyboard_director_service import (
    _render_comic_segment_video_prompt,
    _normalize_language_beats,
    build_gridcell_video_prompt_structured,
    render_video_prompt_from_structured,
)


def test_normalize_language_beats_binds_existing_speaker_and_defaults_spoken_sync():
    beats = _normalize_language_beats(
        [
            {
                "beat_id": "LB01",
                "source_excerpt": "Alice said hello.",
                "event_type": "spoken_dialogue",
                "speaker_name": "Alice",
                "listener_refs": ["@Bob"],
                "text": "Hello",
                "emotion": "calm",
                "intensity": "medium",
                "visual_priority": "high",
                "split_recommendation": "prefer_new_cell",
            }
        ],
        structured_assets={"characters": [{"name": "Alice"}]},
    )

    assert beats[0]["speaker_ref"] == "@Alice"
    assert beats[0]["mouth_sync_required"] is True
    assert beats[0]["event_type"] == "spoken_dialogue"


def test_gridcell_video_prompt_structured_keeps_speech_items_and_only_spoken_dialogue_in_dialogue():
    structured = build_gridcell_video_prompt_structured(
        action_description="Alice pauses before answering.",
        camera_motion="static",
        speech_items=[
            {
                "speaker_name": "Alice",
                "speaker_ref": "@Alice",
                "speech_type": "spoken",
                "text": "You came.",
                "emotion": "tense",
                "intensity": "medium",
                "mouth_sync_required": True,
            },
            {
                "speaker_name": "Alice",
                "speaker_ref": "@Alice",
                "speech_type": "inner_monologue",
                "text": "Stay calm.",
                "emotion": "suppressed",
                "intensity": "medium",
                "mouth_sync_required": False,
            },
        ],
    )

    assert len(structured["speech_items"]) == 2
    assert structured["dialogue"] == [{"speaker": "Alice", "line": "You came."}]


def test_story_segment_cell_roundtrip_preserves_speech_items_and_compiles_dialogue_excerpt():
    cell = _build_grid_cell(
        1,
        {
            "cell_index": 1,
            "start_second": 0,
            "end_second": 2,
            "duration_seconds": 2,
            "shot_description": "Alice looks up.",
            "action_description": "Alice answers quietly.",
            "speech_items": [
                {
                    "speaker_name": "Alice",
                    "speaker_ref": "@Alice",
                    "speech_type": "spoken",
                    "text": "You came.",
                    "emotion": "tense",
                    "intensity": "medium",
                    "mouth_sync_required": True,
                },
                {
                    "speaker_name": "Alice",
                    "speaker_ref": "@Alice",
                    "speech_type": "inner_monologue",
                    "text": "Don't panic.",
                    "emotion": "suppressed",
                    "intensity": "medium",
                    "mouth_sync_required": False,
                },
            ],
            "mouth_sync_required": True,
        },
        {},
        1,
    )

    payload = _cell_payload(cell)

    assert len(payload["speech_items"]) == 2
    assert "Alice" in payload["dialogue_excerpt"]
    assert "OS" in payload["dialogue_excerpt"]
    assert payload["mouth_sync_required"] is True


def test_render_video_prompt_from_structured_separates_spoken_and_os_sections():
    prompt = render_video_prompt_from_structured(
        {
            "action": "Alice looks up and answers.",
            "camera_motion": "static",
            "ambiance_audio": "quiet room tone",
            "speech_items": [
                {
                    "speaker_name": "Alice",
                    "speech_type": "spoken",
                    "text": "You came.",
                    "mouth_sync_required": True,
                },
                {
                    "speaker_name": "Alice",
                    "speech_type": "inner_monologue",
                    "text": "Stay calm.",
                    "mouth_sync_required": False,
                },
            ],
        }
    )

    assert "对白" in prompt
    assert "OS/旁白" in prompt
    assert "Stay calm." in prompt


def test_comic_segment_video_prompt_keeps_dialogue_and_inner_os_in_timeline():
    prompt = _render_comic_segment_video_prompt(
        [
            {
                "start_second": 0,
                "end_second": 4,
                "duration_seconds": 4,
                "shot_description": "Alice looks up.",
                "action_description": "Alice answers quietly while hiding panic.",
                "shot_type": "近景",
                "camera_motion": "静止",
                "character_refs": ["Alice"],
                "speech_items": [
                    {
                        "speaker_name": "Alice",
                        "speech_type": "spoken",
                        "text": "You came.",
                        "mouth_sync_required": True,
                    },
                    {
                        "speaker_name": "Alice",
                        "speech_type": "inner_monologue",
                        "text": "Stay calm.",
                        "mouth_sync_required": False,
                    },
                ],
            }
        ]
    )

    assert "对白" in prompt
    assert "You came." in prompt
    assert "OS/旁白" in prompt
    assert "Stay calm." in prompt
