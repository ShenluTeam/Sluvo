import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.storyboard_director_service import (
    estimate_cell_min_duration_seconds,
    estimate_language_beat_min_duration_seconds,
    expand_language_beats_for_timing,
    normalize_segment_timing,
)
from services.storyboard_split_runtime import _retime_segment_plans_with_language_beats


def test_expand_language_beats_for_timing_splits_long_spoken_beat():
    beats = expand_language_beats_for_timing(
        [
            {
                "beat_id": "LB01",
                "event_type": "spoken_dialogue",
                "speaker_name": "阿宁",
                "text": "你终于来了，我们已经等了很久。再晚一点，事情就彻底来不及了。",
                "source_excerpt": "你终于来了，我们已经等了很久。再晚一点，事情就彻底来不及了。",
                "intensity": "high",
                "visual_priority": "high",
                "mouth_sync_required": True,
                "split_recommendation": "prefer_new_cell",
            }
        ]
    )

    assert len(beats) >= 2
    assert all(float(item["estimated_total_seconds"]) > 0 for item in beats)
    assert beats[0]["beat_id"].startswith("LB01_")


def test_normalize_segment_timing_respects_speech_min_duration():
    cells = [
        {
            "cell_index": 1,
            "speech_items": [
                {
                    "speaker_name": "阿宁",
                    "speech_type": "spoken",
                    "text": "你终于来了，我们已经等了很久。",
                    "intensity": "medium",
                    "mouth_sync_required": True,
                }
            ],
            "shot_type": "中景",
            "action_description": "阿宁抬头看向门口。",
        },
        {
            "cell_index": 2,
            "speech_items": [
                {
                    "speaker_name": "阿宁",
                    "speech_type": "inner_monologue",
                    "text": "再晚一点就麻烦了。",
                    "intensity": "medium",
                    "mouth_sync_required": False,
                }
            ],
            "shot_type": "近景",
            "action_description": "她压住情绪，没有立刻露出慌张。",
        },
    ]

    timing = normalize_segment_timing(cells, 4, storyboard_mode="comic")

    assert len(timing) == 2
    assert sum(float(item["duration_seconds"]) for item in timing) >= 4
    assert timing[0]["duration_seconds"] >= estimate_cell_min_duration_seconds(cells[0], storyboard_mode="comic")
    assert timing[1]["duration_seconds"] >= estimate_cell_min_duration_seconds(cells[1], storyboard_mode="comic")


def test_runtime_retimes_and_splits_segment_plan_by_language_beats():
    beats = expand_language_beats_for_timing(
        [
            {
                "beat_id": "LB01",
                "event_type": "spoken_dialogue",
                "speaker_name": "阿宁",
                "text": "你终于来了，我们已经等了很久。",
                "source_excerpt": "你终于来了，我们已经等了很久。",
                "intensity": "high",
                "visual_priority": "high",
                "mouth_sync_required": True,
                "split_recommendation": "prefer_new_cell",
            },
            {
                "beat_id": "LB02",
                "event_type": "spoken_dialogue",
                "speaker_name": "顾川",
                "text": "路上出了点事，但我把东西带来了。",
                "source_excerpt": "路上出了点事，但我把东西带来了。",
                "intensity": "medium",
                "visual_priority": "high",
                "mouth_sync_required": True,
                "split_recommendation": "prefer_new_segment",
            },
            {
                "beat_id": "LB03",
                "event_type": "inner_monologue",
                "speaker_name": "阿宁",
                "text": "只要东西还在，一切就还有机会。",
                "source_excerpt": "只要东西还在，一切就还有机会。",
                "intensity": "medium",
                "visual_priority": "medium",
                "mouth_sync_required": False,
                "split_recommendation": "prefer_new_cell",
            },
        ]
    )
    plans = _retime_segment_plans_with_language_beats(
        [
            {
                "sequence_num": 1,
                "title": "门口对峙",
                "summary": "门口的对话逐步转入更紧张的交锋。",
                "text_span": {"source_excerpt": "门口的对话逐步转入更紧张的交锋。", "start_offset": None, "end_offset": None},
                "recommended_duration_seconds": 4,
                "grid_count": 1,
                "beat_ids": [item["beat_id"] for item in beats],
                "language_focus_summary": "对话和心理压力同步上升。",
            }
        ],
        beats,
    )

    assert len(plans) >= 2
    assert [item["sequence_num"] for item in plans] == [1, 2]
    for plan in plans:
        covered_beats = [beat for beat in beats if beat["beat_id"] in plan["beat_ids"]]
        assert plan["recommended_duration_seconds"] >= sum(
            estimate_language_beat_min_duration_seconds(beat) for beat in covered_beats
        )
        assert plan["grid_count"] >= 1


def test_runtime_biases_speech_dense_segment_toward_medium_duration_and_4_or_6_cells():
    beats = expand_language_beats_for_timing(
        [
            {
                "beat_id": "LB01",
                "event_type": "spoken_dialogue",
                "speaker_name": "伊雪儿",
                "text": "你终于来了。",
                "source_excerpt": "你终于来了。",
                "intensity": "medium",
                "visual_priority": "high",
                "mouth_sync_required": True,
                "split_recommendation": "prefer_new_cell",
            },
            {
                "beat_id": "LB02",
                "event_type": "inner_monologue",
                "speaker_name": "伊雪儿",
                "text": "可我已经不信命了。",
                "source_excerpt": "可我已经不信命了。",
                "intensity": "medium",
                "visual_priority": "medium",
                "mouth_sync_required": False,
                "split_recommendation": "prefer_new_cell",
            },
            {
                "beat_id": "LB03",
                "event_type": "offscreen_voice",
                "speaker_name": "太监",
                "text": "奉旨赦免死罪。",
                "source_excerpt": "奉旨赦免死罪。",
                "intensity": "high",
                "visual_priority": "high",
                "mouth_sync_required": False,
                "split_recommendation": "prefer_new_cell",
            },
            {
                "beat_id": "LB04",
                "event_type": "spoken_dialogue",
                "speaker_name": "慕容宸",
                "text": "抓紧绳子！",
                "source_excerpt": "抓紧绳子！",
                "intensity": "high",
                "visual_priority": "high",
                "mouth_sync_required": True,
                "split_recommendation": "prefer_new_cell",
            },
        ]
    )

    plans = _retime_segment_plans_with_language_beats(
        [
            {
                "sequence_num": 1,
                "title": "崖边营救",
                "summary": "对白、独白和画外音同时压上来。",
                "text_span": {"source_excerpt": "对白、独白和画外音同时压上来。", "start_offset": None, "end_offset": None},
                "recommended_duration_seconds": 5,
                "grid_count": 1,
                "beat_ids": [item["beat_id"] for item in beats],
                "language_focus_summary": "对白、独白和命令声交织。",
            }
        ],
        beats,
    )

    assert len(plans) == 1
    assert plans[0]["recommended_duration_seconds"] >= 6
    assert plans[0]["grid_count"] in {4, 6}
    assert set(plans[0]["speech_coverage_targets"]) >= {"spoken", "inner_monologue", "offscreen_voice"}
