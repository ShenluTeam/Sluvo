import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.config import settings
from services.image_model_registry import (
    MODEL_GPT_IMAGE_2,
    MODEL_GPT_IMAGE_2_FAST,
    MODEL_NANO_2,
    MODEL_NANO_2_LOW,
    MODEL_NANO_PRO,
    MODEL_NANO_PRO_LOW,
    _build_gpt_image_2_prompt,
    _build_submit_payload,
    _extract_first_http_url,
    build_image_catalog,
    estimate_image_price,
    normalize_image_model_code,
    normalize_image_request,
)


def test_build_image_catalog_contains_all_frontend_models():
    data = build_image_catalog()
    models = {item["model_code"] for item in data["models"]}
    assert MODEL_NANO_2_LOW in models
    assert "nano-banana-2" in models
    assert MODEL_NANO_PRO in models
    assert "nano-banana-pro-低价版" in models
    if settings.RUNNINGHUB_API_KEY:
        assert MODEL_GPT_IMAGE_2 in models
        assert MODEL_GPT_IMAGE_2_FAST in models
    else:
        assert MODEL_GPT_IMAGE_2 not in models
        assert MODEL_GPT_IMAGE_2_FAST not in models


def test_normalize_image_model_code_maps_legacy_values():
    assert normalize_image_model_code("shenlu-image-fast") == MODEL_NANO_2_LOW
    assert normalize_image_model_code("low_cost") == MODEL_NANO_2_LOW
    assert normalize_image_model_code("shenlu-image-stable") == MODEL_NANO_PRO
    assert normalize_image_model_code("stable") == MODEL_NANO_PRO


def test_estimate_image_price_for_gpt_image_2_fast_is_single_fixed():
    if not settings.RUNNINGHUB_API_KEY:
        return
    normalized = normalize_image_request(
        {
            "model_code": MODEL_GPT_IMAGE_2_FAST,
            "mode": "text_to_image",
            "prompt": "电影级海报",
            "resolution": "2k",
            "aspect_ratio": "16:9",
            "reference_images": [],
        }
    )
    price = estimate_image_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert price["pricing_rule_type"] == "single_fixed"
    assert int(price["sell_price_points"]) == 3


def test_gpt_image_2_fast_catalog_exposes_text_and_image_without_resolution():
    if not settings.RUNNINGHUB_API_KEY:
        return
    data = build_image_catalog()
    model = next((item for item in data["models"] if item["model_code"] == MODEL_GPT_IMAGE_2_FAST), None)
    assert model is not None
    assert [item["generation_type"] for item in model["features"]] == ["text_to_image", "image_to_image"]
    text_feature = next(item for item in model["features"] if item["generation_type"] == "text_to_image")
    image_feature = next(item for item in model["features"] if item["generation_type"] == "image_to_image")
    assert all(field["key"] != "resolution" for field in text_feature["fields"])
    assert all(field["key"] != "resolution" for field in image_feature["fields"])
    reference_field = next(field for field in image_feature["fields"] if field["key"] == "reference_images")
    assert reference_field["max_count"] == 10


def test_gpt_image_2_official_catalog_exposes_quality_and_resolution():
    if not settings.RUNNINGHUB_API_KEY:
        return
    data = build_image_catalog()
    model = next((item for item in data["models"] if item["model_code"] == MODEL_GPT_IMAGE_2), None)
    assert model is not None
    text_feature = next(item for item in model["features"] if item["generation_type"] == "text_to_image")
    assert any(field["key"] == "quality" for field in text_feature["fields"])
    assert any(field["key"] == "resolution" for field in text_feature["fields"])
    assert text_feature["defaults"]["quality"] == "medium"


def test_estimate_image_price_for_gpt_image_2_official_uses_quality_resolution_table():
    if not settings.RUNNINGHUB_API_KEY:
        return
    normalized = normalize_image_request(
        {
            "model_code": MODEL_GPT_IMAGE_2,
            "mode": "text_to_image",
            "prompt": "电影级海报",
            "quality": "high",
            "resolution": "2k",
            "aspect_ratio": "16:9",
            "reference_images": [],
        }
    )
    price = estimate_image_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert price["pricing_rule_type"] == "fixed_table"
    assert int(price["sell_price_points"]) == 31
    assert price["pricing_details"]["quality"] == "high"


def test_nano_banana_2_low_points_match_manual_pricing():
    normalized = normalize_image_request(
        {
            "model_code": MODEL_NANO_2_LOW,
            "mode": "text_to_image",
            "prompt": "测试图片",
            "resolution": "4k",
            "aspect_ratio": "16:9",
            "reference_images": [],
        }
    )
    price = estimate_image_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert int(price["sell_price_points"]) == 3
    assert price["cost_price"] == 0.2


def test_nano_banana_2_points_match_manual_pricing():
    normalized = normalize_image_request(
        {
            "model_code": MODEL_NANO_2,
            "mode": "text_to_image",
            "prompt": "测试图片",
            "resolution": "2k",
            "aspect_ratio": "16:9",
            "reference_images": [],
        }
    )
    price = estimate_image_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert int(price["sell_price_points"]) == 11
    assert price["cost_price"] == 0.74


def test_nano_banana_pro_low_points_match_manual_pricing():
    normalized = normalize_image_request(
        {
            "model_code": MODEL_NANO_PRO_LOW,
            "mode": "text_to_image",
            "prompt": "测试图片",
            "resolution": "1k",
            "aspect_ratio": "16:9",
            "reference_images": [],
        }
    )
    price = estimate_image_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert int(price["sell_price_points"]) == 5
    assert price["cost_price"] == 0.4


def test_nano_banana_pro_points_match_manual_pricing():
    normalized = normalize_image_request(
        {
            "model_code": MODEL_NANO_PRO,
            "mode": "text_to_image",
            "prompt": "测试图片",
            "resolution": "4k",
            "aspect_ratio": "16:9",
            "reference_images": [],
        }
    )
    price = estimate_image_price(normalized["model_code"], normalized["generation_type"], normalized)
    assert int(price["sell_price_points"]) == 16
    assert price["cost_price"] == 1.5


def test_gpt_image_2_image_mode_routes_with_reference_images():
    if not settings.RUNNINGHUB_API_KEY:
        try:
            normalize_image_request(
                {
                    "model_code": MODEL_GPT_IMAGE_2,
                    "mode": "image_to_image",
                    "prompt": "保留人物构图",
                    "resolution": "2k",
                    "aspect_ratio": "16:9",
                    "reference_images": ["https://example.com/a.png"],
                }
            )
        except ValueError as exc:
            assert str(exc) == "model_not_configured"
            return
        raise AssertionError("expected gpt-image-2 to be disabled without server config")
    normalized = normalize_image_request(
        {
            "model_code": MODEL_GPT_IMAGE_2,
            "mode": "image_to_image",
            "prompt": "保留人物构图",
            "resolution": "2k",
            "aspect_ratio": "16:9",
            "reference_images": ["https://example.com/ref.png"],
        }
    )
    assert normalized["generation_type"] == "image_to_image"
    assert normalized["reference_images"] == ["https://example.com/ref.png"]


def test_gpt_image_2_official_submit_payload_includes_quality_resolution_and_aspect_ratio():
    if not settings.RUNNINGHUB_API_KEY:
        return
    normalized = normalize_image_request(
        {
            "model_code": MODEL_GPT_IMAGE_2,
            "mode": "image_to_image",
            "prompt": "保留人物构图",
            "quality": "medium",
            "resolution": "2k",
            "aspect_ratio": "16:9",
            "reference_images": ["https://example.com/ref.png"],
        }
    )
    endpoint, payload = _build_submit_payload(normalized)
    assert endpoint.endswith("/rhart-image-g-2-official/image-to-image")
    assert payload["aspectRatio"] == "16:9"
    assert payload["quality"] == "medium"
    assert payload["resolution"] == "2k"
    assert payload["imageUrls"] == ["https://example.com/ref.png"]


def test_gpt_image_2_fast_text_payload_keeps_fast_shape_without_resolution():
    if not settings.RUNNINGHUB_API_KEY:
        return
    normalized = normalize_image_request(
        {
            "model_code": MODEL_GPT_IMAGE_2_FAST,
            "mode": "text_to_image",
            "prompt": "电影级海报",
            "resolution": "2k",
            "aspect_ratio": "21:9",
            "reference_images": [],
        }
    )
    endpoint, payload = _build_submit_payload(normalized)
    assert endpoint.endswith("/rhart-image-g-2/text-to-image")
    assert payload["aspectRatio"] == "21:9"
    assert "resolution" not in payload
    assert "quality" not in payload


def test_gpt_image_2_prompt_no_longer_appends_aspect_ratio_suffix():
    normalized = {
        "prompt": "分镜设定：老师讲课，教室安静。",
        "aspect_ratio": "16:9",
    }
    assert _build_gpt_image_2_prompt(normalized) == "分镜设定：老师讲课，教室安静。"


def test_nano_models_auto_route_to_image_to_image_when_references_present():
    normalized = normalize_image_request(
        {
            "model_code": MODEL_NANO_PRO,
            "mode": "text_to_image",
            "prompt": "保留人物关键特征",
            "resolution": "2k",
            "aspect_ratio": "16:9",
            "reference_images": ["https://example.com/ref.png"],
        }
    )
    assert normalized["generation_type"] == "image_to_image"


def test_extract_first_http_url_strips_trailing_punctuation():
    result = _extract_first_http_url("see https://example.com/demo.png;")
    assert result == "https://example.com/demo.png"
