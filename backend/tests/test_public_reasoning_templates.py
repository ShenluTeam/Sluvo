import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.assistant_runtime.public_reasoning_templates import (
    FORBIDDEN_PUBLIC_REASONING_TERMS,
    INTENT_PERSONAS,
    PUBLIC_REASONING_PHASES,
    PUBLIC_REASONING_TEMPLATE_ROWS,
    normalize_public_reasoning_intent,
    validate_public_reasoning_templates,
    visible_text_length,
)


def test_public_reasoning_templates_are_complete_and_valid():
    assert validate_public_reasoning_templates() == []

    ids = [row["template_id"] for row in PUBLIC_REASONING_TEMPLATE_ROWS]
    assert len(ids) == len(set(ids))

    for intent in INTENT_PERSONAS:
        for phase in PUBLIC_REASONING_PHASES:
            rows = [
                row
                for row in PUBLIC_REASONING_TEMPLATE_ROWS
                if row["intent"] == intent and row["phase"] == phase
            ]
            assert len(rows) >= 4


def test_public_reasoning_template_body_safety_and_length():
    for row in PUBLIC_REASONING_TEMPLATE_ROWS:
        body = row["body"]
        assert visible_text_length(body) <= 34
        for term in FORBIDDEN_PUBLIC_REASONING_TERMS:
            assert term.lower() not in body.lower()


def test_public_reasoning_intent_mapping_covers_runtime_actions():
    cases = {
        "split_episode_source": "extract_storyboard",
        "parse_story_segments": "extract_storyboard",
        "extract_storyboard": "extract_storyboard",
        "extract_project_assets": "extract_assets",
        "extract_assets": "extract_assets",
        "generate_asset_images": "generate_asset_images",
        "generate_panel_image": "generate_storyboard_images",
        "generate_storyboard_images": "generate_storyboard_images",
        "generate_panel_video": "generate_video",
        "generate_video": "generate_video",
        "generate_episode_dubbing": "generate_audio",
        "generate_audio": "generate_audio",
        "rewrite_script": "script_rewrite",
        "save_script": "script_writing",
    }
    for skill_id, intent in cases.items():
        assert normalize_public_reasoning_intent(skill_hint={"id": skill_id}) == intent

    assert normalize_public_reasoning_intent(content="下一步做什么") == "next_step_advice"
    assert normalize_public_reasoning_intent(skill_hint={"id": "unknown"}) == "general_project_question"
