import sys
from pathlib import Path
from decimal import Decimal
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import storyboard_split_runtime
from services.storyboard_split_runtime import (
    StorySegmentParseError,
    _blocking_story_segment_validation_errors,
    _compute_points_from_cost,
    _lock_story_segments_to_confirmed_durations,
    _repair_story_segments_locally,
    _segment_plans_from_confirmed_rows,
    validate_story_segments_semantics,
)


def test_compute_points_from_cost_matches_rule():
    assert _compute_points_from_cost(Decimal("0")) == 0
    assert _compute_points_from_cost(Decimal("0.01")) == 2
    assert _compute_points_from_cost(Decimal("0.10")) == 2
    assert _compute_points_from_cost(Decimal("0.11")) == 3


def test_validate_story_segments_semantics_detects_grid_and_duration_errors():
    segments = [
        {
            "sequence_num": 1,
            "summary": "主角冲向门口",
            "text_span": {"source_excerpt": "主角冲向门口", "start_offset": None, "end_offset": None},
            "segment_prompt_summary": "门口冲刺",
            "recommended_duration_seconds": 4,
            "grid_count": 2,
            "character_refs": ["主角"],
            "scene_refs": ["走廊"],
            "prop_refs": [],
            "grid_cells": [
                {
                    "cell_index": 1,
                    "start_second": 0,
                    "end_second": 1,
                    "duration_seconds": 1,
                    "shot_description": "主角起跑",
                    "action_description": "主角向前冲",
                }
            ],
        }
    ]

    errors = validate_story_segments_semantics(segments)

    assert any("grid_cells count" in item for item in errors)
    assert any("total grid duration" in item for item in errors)


def test_validate_story_segments_semantics_detects_long_single_grid_and_missing_speech_coverage():
    segments = [
        {
            "sequence_num": 1,
            "summary": "角色被吊在崖边，外部命令和内心独白同时出现。",
            "text_span": {"source_excerpt": "角色被吊在崖边，外部命令和内心独白同时出现。", "start_offset": None, "end_offset": None},
            "segment_prompt_summary": "崖边危局",
            "recommended_duration_seconds": 8,
            "grid_count": 1,
            "character_refs": ["伊雪儿"],
            "scene_refs": ["崖边"],
            "prop_refs": ["麻绳"],
            "speech_coverage_targets": ["spoken", "inner_monologue", "offscreen_voice"],
            "grid_cells": [
                {
                    "cell_index": 1,
                    "start_second": 0,
                    "end_second": 8,
                    "duration_seconds": 8,
                    "shot_description": "伊雪儿悬在崖边",
                    "action_description": "风中摇晃",
                    "speech_items": [
                        {
                            "speaker_name": "伊雪儿",
                            "speech_type": "spoken",
                            "text": "你终于来了。",
                        }
                    ],
                }
            ],
        }
    ]

    errors = validate_story_segments_semantics(segments)

    assert any("long single-grid duration" in item for item in errors)
    assert any("missing speech coverage" in item for item in errors)


def test_local_story_segment_repair_fixes_shape_timing_and_speech_coverage():
    segments = [
        {
            "sequence_num": 7,
            "summary": "Hero faces the warning.",
            "text_span": {"source_excerpt": "Hero faces the warning."},
            "segment_prompt_summary": "",
            "recommended_duration_seconds": 8,
            "grid_count": 1,
            "character_refs": ["Hero", "Hero", ""],
            "scene_refs": ["Hall"],
            "prop_refs": [],
            "speech_coverage_targets": ["spoken", "inner_monologue"],
            "grid_cells": [
                {
                    "cell_index": 3,
                    "start_second": 0,
                    "end_second": 8,
                    "duration_seconds": 8,
                    "shot_description": "Hero looks up.",
                    "action_description": "",
                    "speech_items": [{"speech_type": "spoken", "text": "Who is there?"}],
                }
            ],
        }
    ]

    repaired = _repair_story_segments_locally(segments, validation_errors=["shape mismatch"], warnings=[])

    assert validate_story_segments_semantics(repaired) == []
    assert repaired[0]["sequence_num"] == 1
    assert repaired[0]["grid_count"] == len(repaired[0]["grid_cells"])
    assert repaired[0]["character_refs"] == ["Hero"]


def test_local_story_segment_repair_retunes_absolute_batch_timeline_to_segment_duration():
    segments = [
        {
            "sequence_num": 2,
            "summary": "阿福追车后停下，流星划过。",
            "text_span": {"source_excerpt": "阿福追车后停下，流星划过。"},
            "segment_prompt_summary": "",
            "recommended_duration_seconds": 15,
            "grid_count": 4,
            "character_refs": ["阿福"],
            "scene_refs": ["街道"],
            "prop_refs": [],
            "grid_cells": [
                {
                    "cell_index": 1,
                    "start_second": 10,
                    "end_second": 20,
                    "duration_seconds": 10,
                    "shot_description": "车尾灯远去。",
                    "action_description": "阿福追车。",
                },
                {
                    "cell_index": 2,
                    "start_second": 20,
                    "end_second": 32.8,
                    "duration_seconds": 12.8,
                    "shot_description": "阿福停下喘气。",
                    "action_description": "阿福停在路边。",
                },
                {
                    "cell_index": 3,
                    "start_second": 32.8,
                    "end_second": 48.2,
                    "duration_seconds": 15.4,
                    "shot_description": "阿福抬头。",
                    "action_description": "它看向天空。",
                },
                {
                    "cell_index": 4,
                    "start_second": 48.2,
                    "end_second": 61.6,
                    "duration_seconds": 13.4,
                    "shot_description": "流星划过。",
                    "action_description": "夜空亮起。",
                },
            ],
        }
    ]

    assert any("total grid duration" in item for item in validate_story_segments_semantics(segments))

    repaired = _repair_story_segments_locally(segments, validation_errors=["total grid duration"], warnings=[])

    assert validate_story_segments_semantics(repaired) == []
    assert repaired[0]["recommended_duration_seconds"] == 15
    assert repaired[0]["grid_cells"][0]["start_second"] == 0
    assert repaired[0]["grid_cells"][-1]["end_second"] == 15
    assert all(float(cell["duration_seconds"]).is_integer() for cell in repaired[0]["grid_cells"])


def test_confirmed_plan_duration_lock_restores_planned_segment_seconds():
    segments = [
        {
            "sequence_num": 1,
            "summary": "妈妈劝说男孩，阿福追车。",
            "recommended_duration_seconds": 15,
            "grid_count": 4,
            "grid_cells": [
                {"cell_index": 1, "start_second": 0, "end_second": 4, "duration_seconds": 4},
                {"cell_index": 2, "start_second": 4, "end_second": 8, "duration_seconds": 4},
                {"cell_index": 3, "start_second": 8, "end_second": 12, "duration_seconds": 4},
                {"cell_index": 4, "start_second": 12, "end_second": 15, "duration_seconds": 3},
            ],
        },
        {
            "sequence_num": 2,
            "summary": "刀疤脸抓住阿福。",
            "recommended_duration_seconds": 15,
            "grid_count": 4,
            "grid_cells": [
                {"cell_index": 1, "start_second": 0, "end_second": 4, "duration_seconds": 4},
                {"cell_index": 2, "start_second": 4, "end_second": 8, "duration_seconds": 4},
                {"cell_index": 3, "start_second": 8, "end_second": 12, "duration_seconds": 4},
                {"cell_index": 4, "start_second": 12, "end_second": 15, "duration_seconds": 3},
            ],
        },
    ]

    _lock_story_segments_to_confirmed_durations(segments, {1: 10, 2: 9})

    assert [item["recommended_duration_seconds"] for item in segments] == [10, 9]
    assert sum(cell["duration_seconds"] for cell in segments[0]["grid_cells"]) == 10
    assert sum(cell["duration_seconds"] for cell in segments[1]["grid_cells"]) == 9
    assert all(float(cell["start_second"]).is_integer() for item in segments for cell in item["grid_cells"])


def test_story_segment_validation_splits_blocking_errors_from_advisories():
    errors = [
        "segment 1 uses grid_count 9 too early; prefer 4 or 6 cells before nine-grid",
        "segment 2 is missing speech coverage for spoken",
        "segment 3 grid_cells count 1 does not match grid_count 4",
    ]

    assert _blocking_story_segment_validation_errors(errors) == [
        "segment 3 grid_cells count 1 does not match grid_count 4",
    ]


def test_confirmed_plan_blank_same_scene_row_does_not_inherit_speech_targets():
    rows = [
        {
            "sequence_num": 1,
            "story_fragment": "阿福追车，流星划过。",
            "dialogue": "小男孩喊：阿福！",
            "estimated_duration_seconds": 6,
            "grid_count": 4,
        },
        {
            "sequence_num": 2,
            "story_fragment": "阿福追车，流星划过。",
            "dialogue": "",
            "estimated_duration_seconds": 6,
            "grid_count": 4,
        },
    ]
    language_beats = [
        {
            "beat_id": "b1",
            "event_type": "spoken_dialogue",
            "source_excerpt": "小男孩喊：阿福！",
            "text": "小男孩喊：阿福！",
        },
        {
            "beat_id": "b2",
            "event_type": "visual_action",
            "source_excerpt": "阿福追车后停下，流星划过。",
            "text": "阿福追车后停下，流星划过。",
        },
    ]

    plans = _segment_plans_from_confirmed_rows(rows, language_beats, route_tag="test")

    assert plans[0]["speech_coverage_targets"]
    assert plans[1]["speech_coverage_targets"] == []
    assert "无对白动作/情绪延展段" in plans[1]["text_span"]["source_excerpt"]


def test_run_storyboard_split_runtime_fails_when_commit_creates_no_segments(monkeypatch):
    monkeypatch.setattr(
        storyboard_split_runtime,
        "build_storyboard_split_structured_draft",
        lambda **kwargs: {
            "storyboard_mode": "comic",
            "story_segments": [
                {
                    "sequence_num": 1,
                    "summary": "主角冲进房间",
                    "text_span": {"source_excerpt": "主角冲进房间"},
                    "segment_prompt_summary": "冲门而入",
                    "recommended_duration_seconds": 4,
                    "grid_count": 1,
                    "grid_cells": [
                        {
                            "cell_index": 1,
                            "start_second": 0,
                            "end_second": 4,
                            "duration_seconds": 4,
                            "shot_description": "主角推门冲入",
                            "action_description": "主角冲进室内",
                        }
                    ],
                }
            ],
            "warnings": [],
        },
    )
    monkeypatch.setattr(storyboard_split_runtime, "commit_story_segments_with_cells", lambda *args, **kwargs: [])

    class DummySession:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, model, episode_id):
            return SimpleNamespace(id=episode_id)

    monkeypatch.setattr(storyboard_split_runtime, "Session", DummySession)

    with pytest.raises(StorySegmentParseError) as exc:
        storyboard_split_runtime.run_storyboard_split_runtime(
            episode_id=123,
            text="测试剧本文本",
            storyboard_mode="comic",
            api_key="test-key",
        )

    assert exc.value.error_code == "commit_failed"
