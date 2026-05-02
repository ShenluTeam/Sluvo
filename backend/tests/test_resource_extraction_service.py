import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import resource_extraction_service as extraction


def test_validate_extracted_assets_detects_conflicts_and_dynamic_states():
    errors = extraction._validate_extracted_assets(
        {
            "characters": [
                {
                    "name": "伊雪儿",
                    "description": "漂亮少女，被绑在悬崖边，正在哭泣，黑发红衣。",
                    "trigger_word": "伊雪儿",
                }
            ],
            "scenes": [
                {
                    "name": "悬崖边",
                    "description": "一个场景，此时正在发生激烈冲突。",
                }
            ],
            "props": [
                {
                    "name": "伊雪儿",
                    "description": "一把武器",
                }
            ],
        }
    )

    assert any("dynamic state" in item for item in errors["characters"])
    assert any("low-information" in item for item in errors["characters"])
    assert any("non-reusable event" in item for item in errors["scenes"])
    assert any("name conflict across categories" in item for item in errors["global"])


def test_asset_model_routes_match_mixed_strategy_defaults():
    assert extraction._resolve_asset_extractor_model() == "deepseek-v4-flash"
    assert extraction._resolve_asset_enrich_model("character") == "deepseek-v4-flash"
    assert extraction._resolve_asset_enrich_model("scene") == "deepseek-v4-flash"
    assert extraction._resolve_asset_enrich_model("prop") == "deepseek-v4-flash"
    assert extraction._resolve_asset_enrich_model("scene", escalate_reasoner=True) == "deepseek-v4-flash"


def test_asset_extract_prompt_has_asset_director_persona():
    prompt = extraction._asset_extract_prompt()
    assert "AI 漫剧资产策划专家" in prompt
    assert "高级角色资产总监" in prompt
    assert "角色一致性控制" in prompt
    assert "标准化、结构化、视觉化、生成友好、生产可用的资产方案" in prompt


def test_asset_enrich_prompts_use_production_expert_personas():
    character_prompt = extraction._character_enrich_prompt()
    scene_prompt = extraction._scene_enrich_prompt()
    prop_prompt = extraction._prop_enrich_prompt()

    assert "资深角色设定专家" in character_prompt
    assert "角色统一性" in character_prompt
    assert "资深场景资产分析专家" in scene_prompt
    assert "场景统筹顾问" in scene_prompt
    assert "资深道具资产分析专家" in prop_prompt
    assert "视觉锚点" in prop_prompt


def test_local_asset_description_fallback_allows_name_only_character():
    assets = {
        "characters": [
            {
                "name": "刀疤脸",
                "description": "刀疤脸",
                "trigger_word": "",
            }
        ],
        "scenes": [
            {
                "name": "巷口",
                "description": "巷口",
            }
        ],
        "props": [
            {
                "name": "匕首",
                "description": "匕首",
            }
        ],
    }

    repaired = extraction._apply_local_asset_description_fallbacks(assets)
    errors = extraction._validate_extracted_assets(repaired)

    assert errors == {}
    assert len(repaired["characters"][0]["description"]) >= 80
    assert repaired["characters"][0]["trigger_word"] == "刀疤脸"
    warnings = repaired["_asset_quality_warnings"]
    assert [item["name"] for item in warnings] == ["刀疤脸", "巷口", "匕首"]
    assert all("建议到资产页面" in item["suggestion"] for item in warnings)
