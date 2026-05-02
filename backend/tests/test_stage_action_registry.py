import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agents import stage_action_registry


def test_post_save_script_actions_prioritize_asset_design():
    actions = stage_action_registry.post_save_script_actions("草稿")

    assert [item["type"] for item in actions] == ["extract_assets", "rewrite_script"]


def test_assets_ready_actions_prioritize_asset_images_before_storyboard():
    actions = stage_action_registry.assets_ready_actions()

    assert [item["type"] for item in actions] == [
        "generate_asset_images",
        "generate_asset_images",
        "generate_asset_images",
        "generate_asset_images",
        "extract_storyboard",
        "open_assets_upload",
        "open_assets_create",
    ]


def test_storyboard_ready_actions_prioritize_batch_then_range_then_first():
    actions = stage_action_registry.storyboard_ready_actions([1, 2, 3, 4])

    assert [item["type"] for item in actions] == [
        "generate_storyboard_images",
        "generate_storyboard_images",
        "generate_storyboard_images",
        "open_storyboard",
        "rewrite_script",
    ]
    assert actions[0]["payload"]["selected_panel_sequences"] == [1, 2, 3, 4]
    assert actions[1]["payload"]["selected_panel_sequences"] == [1, 2, 3]
    assert actions[2]["payload"]["panel_sequence"] == 1


def test_images_ready_actions_prioritize_video_generation():
    actions = stage_action_registry.images_ready_actions([2, 3])

    assert [item["type"] for item in actions] == ["generate_video", "open_storyboard", "generate_storyboard_images", "generate_storyboard_images", "generate_storyboard_images"]


def test_stage_action_labels_are_clean_utf8_text():
    actions = stage_action_registry.post_save_script_actions("草稿")

    assert [item["label"] for item in actions] == ["开始角色与场景设计", "继续完善现有剧本"]


def test_asset_reference_followup_actions_exclude_completed_scope():
    actions = stage_action_registry.asset_reference_followup_actions("character")

    scopes = [
        (item.get("payload") or {}).get("generation_scope")
        for item in actions
        if item["type"] == "generate_asset_images"
    ]
    assert "character" not in scopes
    assert scopes[:3] == ["all", "scene", "prop"]
