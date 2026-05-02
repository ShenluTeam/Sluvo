import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.storyboard_director_service import _apply_story_segment_consistency
from services.storyboard_split_runtime import _split_text_into_storyboard_chunks


def test_split_text_into_storyboard_chunks_prefers_scene_boundaries():
    source_text = """
1-1：大燕江边悬崖。日。外。
阴云密布，怒江奔腾，伊雪儿被悬在峭壁前。

她低声说：这就是结局吗？
她闭上眼睛，等待命运落下。

1-2：崖顶。日。外。
两名刽子手正在磨绳，催促尽快结束。

1-3：崖顶。日。外。
慕容宸率铁骑冲破雨幕赶到。
""".strip()

    chunks = _split_text_into_storyboard_chunks(source_text, max_chunk_tokens=35)
    assert len(chunks) >= 2
    assert chunks[0].startswith("1-1")
    assert any(chunk.startswith("1-2") or chunk.startswith("1-3") for chunk in chunks[1:])


def test_apply_story_segment_consistency_accepts_initial_previous_state():
    story_segments = [
        {
            "sequence_num": 1,
            "summary": "慕容宸冲到崖顶，看到血迹斑斑的麻绳。",
            "scene_constraint": "@崖顶 风雨未停，麻绳即将断裂",
            "continuity_note": "",
            "segment_prompt_summary": "慕容宸赶到现场",
            "text_span": {"source_excerpt": "慕容宸冲到崖顶，看到血迹斑斑的麻绳。"},
            "character_refs": ["@慕容宸"],
            "scene_refs": ["@崖顶"],
            "prop_refs": ["@麻绳"],
            "grid_cells": [],
        }
    ]
    warnings = []
    previous_state = {
        "scene_anchor": "@大燕江边悬崖 风雨压顶",
        "characters": ["@伊雪儿"],
        "carry_forward": ["@伊雪儿仍被悬在半空", "@麻绳已严重磨损"],
    }

    _apply_story_segment_consistency(
        story_segments,
        warnings,
        storyboard_mode="comic",
        initial_previous_state=previous_state,
    )

    assert story_segments[0]["continuity_note"]
    assert "麻绳" in story_segments[0]["continuity_note"]
