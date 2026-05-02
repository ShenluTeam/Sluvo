import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import resource_extraction_service


def test_asset_extract_prompt_contains_expected_keywords():
    prompt = resource_extraction_service._asset_extract_prompt()

    assert "人物" in prompt
    assert "场景" in prompt
    assert "道具" in prompt
    assert "JSON" in prompt


def test_asset_extraction_user_prompt_is_human_readable():
    prompt = resource_extraction_service._build_asset_extraction_user_prompt(
        "第1场：悬崖边，伊雪儿被吊在半空。",
        "",
        "",
    )

    assert "请从下面剧本文本中提取可复用的人物、场景、道具资产" in prompt
    assert "伊雪儿" in prompt
