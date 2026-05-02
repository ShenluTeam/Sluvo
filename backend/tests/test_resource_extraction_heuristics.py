import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import resource_extraction_service


def test_heuristic_extract_assets_from_script_finds_core_entities():
    source_text = """1-1：大燕江边悬崖。日。外。
△一根粗砺麻绳从峭壁垂下，绳端缚着伊雪儿（20岁）。
△伊雪儿手腕一沉，一枚金钱镖捏在手中。

1-3：崖顶。日。外。
△（特写）慕容宸（25岁）勒马急停。
△太监策马上前，不顾风雨展开明黄圣旨。
"""

    result = resource_extraction_service._heuristic_extract_assets_from_script(source_text)

    character_names = [item["name"] for item in result["characters"]]
    scene_names = [item["name"] for item in result["scenes"]]
    prop_names = [item["name"] for item in result["props"]]

    assert "伊雪儿" in character_names
    assert "慕容宸" in character_names
    assert "大燕江边悬崖" in scene_names
    assert "麻绳" in prop_names
    assert "金钱镖" in prop_names
