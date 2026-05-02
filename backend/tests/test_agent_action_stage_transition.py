import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agent_stage_service import get_next_stage_after_action


def test_generate_storyboard_images_keeps_images_pending_by_default():
    assert (
        get_next_stage_after_action(
            action_type="generate_storyboard_images",
            current_stage="storyboard_ready",
            action_result={},
            facts={},
        )
        == "images_pending"
    )


def test_extract_assets_can_switch_to_asset_images_pending():
    assert (
        get_next_stage_after_action(
            action_type="extract_assets",
            current_stage="assets_pending",
            action_result={"next_stage_hint": "asset_images_pending"},
            facts={},
        )
        == "asset_images_pending"
    )
