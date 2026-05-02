from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Sequence, TypedDict

import requests

from core.config import settings
from services.oss_service import upload_bytes_to_oss_with_meta
from services.provider_adapters import ProviderResult

CATEGORY_SPEED = "speed"
CATEGORY_BALANCED = "balanced"
CATEGORY_QUALITY = "quality"
CATEGORY_FLAGSHIP = "flagship"

CATEGORY_LABELS = {
    CATEGORY_SPEED: "速度优先",
    CATEGORY_BALANCED: "均衡优先",
    CATEGORY_QUALITY: "质量优先",
    CATEGORY_FLAGSHIP: "旗舰体验",
}

GEN_TEXT = "text_to_image"
GEN_IMAGE = "image_to_image"

GENERATION_TYPE_LABELS = {
    GEN_TEXT: "文生图",
    GEN_IMAGE: "图生图",
}

PRICING_RULE_FIXED_TABLE = "fixed_table"
PRICING_RULE_SINGLE_FIXED = "single_fixed"

IMAGE_STATUS_CONNECTED = "已接入"

MODEL_NANO_2 = "nano-banana-2"
MODEL_NANO_2_LOW = "nano-banana-2-低价版"
MODEL_NANO_PRO = "nano-banana-pro"
MODEL_NANO_PRO_LOW = "nano-banana-pro-低价版"
MODEL_GPT_IMAGE_2 = "gpt-image-2"
MODEL_GPT_IMAGE_2_FAST = "gpt-image-2-fast"

IMAGE_MODEL_ALIASES = {
    "shenlu-image-fast": MODEL_NANO_2_LOW,
    "low_cost": MODEL_NANO_2_LOW,
    "shenlu-image-stable": MODEL_NANO_PRO,
    "stable": MODEL_NANO_PRO,
    "nano-banana-pro-vip": MODEL_NANO_PRO,
    "nano-banana-pro-4k-vip": MODEL_NANO_PRO,
    "nano-banana-2-low": MODEL_NANO_2_LOW,
    "nano-banana-pro-low": MODEL_NANO_PRO_LOW,
    "nano_banana_2_low": MODEL_NANO_2_LOW,
    "nano_banana_pro_low": MODEL_NANO_PRO_LOW,
    "gpt-image-2-low": MODEL_GPT_IMAGE_2_FAST,
    "gpt_image_2_fast": MODEL_GPT_IMAGE_2_FAST,
}

DEFAULT_IMAGE_MODEL_CODE = MODEL_NANO_PRO
DEFAULT_IMAGE_RESOLUTION = "2k"
DEFAULT_IMAGE_ASPECT_RATIO = "16:9"

IMAGE_RESOLUTION_OPTIONS = ["1k", "2k", "4k"]
IMAGE_QUALITY_OPTIONS = ["low", "medium", "high"]
IMAGE_QUALITY_LABELS = {"low": "Low", "medium": "Medium", "high": "High"}
IMAGE_ASPECT_RATIO_OPTIONS = ["16:9", "9:16", "1:1", "4:3", "3:4", "3:2", "2:3", "5:4", "4:5", "21:9"]

RUNNINGHUB_QUERY_URL = "https://www.runninghub.cn/openapi/v2/query"
RUNNINGHUB_UPLOAD_URL = "https://www.runninghub.cn/openapi/v2/media/upload/binary"
RUNNINGHUB_AI_APP_URL = "https://www.runninghub.cn/openapi/v2/run/ai-app/{workflow_id}"
RUNNINGHUB_HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Bearer {api_key}",
}

RUNNINGHUB_AI_APP_THIRD_PARTY_IMAGE_SLOTS = ("3", "7", "8")

PROVIDER_RUNNINGHUB_IMAGE = "runninghub-image"
class ImageFieldConfig(TypedDict, total=False):
    key: str
    label: str
    type: str
    required: bool
    options: List[Dict[str, Any]]
    min_count: int
    max_count: int
    max_file_size_mb: int
    media_type: str
    help_text: str
    placeholder: str


class ImagePricingRule(TypedDict, total=False):
    pricing_rule_type: str
    generation_type: str
    resolution: Optional[str]
    quality: Optional[str]
    cost_price: float
    suggested_price: float
    sell_price_points: int
    pricing_note: str
    pricing_details: Dict[str, Any]


class ImageFeatureConfig(TypedDict):
    generation_type: str
    generation_type_label: str
    connection_status: str
    note: str
    defaults: Dict[str, Any]
    fields: List[ImageFieldConfig]
    pricing_rule_type: str
    pricing_rules: List[ImagePricingRule]
    submit_type: str


class ImageModelConfig(TypedDict):
    model_code: str
    label: str
    series: str
    category: str
    recommendation: str
    supports_high_resolution: bool
    status: str
    feature_tags: List[str]
    features: Dict[str, ImageFeatureConfig]


def _choice(value: str, label: Optional[str] = None) -> Dict[str, str]:
    return {"value": value, "label": label or value}


def _field(key: str, label: str, field_type: str, **extra: Any) -> ImageFieldConfig:
    payload: ImageFieldConfig = {"key": key, "label": label, "type": field_type}
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def _ceil_tenth(value: float) -> float:
    return math.ceil(value * 10) / 10


def _sell_values(cost_price: float) -> tuple[float, int]:
    cost = round(float(cost_price or 0), 2)
    if cost <= 1.5:
        profit = min(max(_ceil_tenth(cost * 0.30), 0.3), 0.6)
    elif cost <= 6:
        profit = min(max(_ceil_tenth(cost * 0.20), 0.6), 1.5)
    else:
        profit = min(max(_ceil_tenth(cost * 0.12), 1.5), 3.0)
    suggested = round(_ceil_tenth(cost + profit), 2)
    return suggested, int(math.ceil(suggested / 0.1))


def _fixed_rule(cost_price: float, note: str, *, generation_type: str, resolution: Optional[str] = None) -> ImagePricingRule:
    suggested, points = _sell_values(cost_price)
    return {
        "pricing_rule_type": PRICING_RULE_SINGLE_FIXED if resolution is None else PRICING_RULE_FIXED_TABLE,
        "generation_type": generation_type,
        "resolution": resolution,
        "cost_price": round(cost_price, 2),
        "suggested_price": suggested,
        "sell_price_points": points,
        "pricing_note": note,
        "pricing_details": {
            "billing_unit": "per_request",
            "resolution": resolution,
        },
    }


def _fixed_rule_with_points(
    cost_price: float,
    note: str,
    *,
    generation_type: str,
    sell_price_points: int,
    resolution: Optional[str] = None,
    quality: Optional[str] = None,
) -> ImagePricingRule:
    return {
        "pricing_rule_type": PRICING_RULE_SINGLE_FIXED if resolution is None else PRICING_RULE_FIXED_TABLE,
        "generation_type": generation_type,
        "resolution": resolution,
        "quality": quality,
        "cost_price": round(cost_price, 2),
        "suggested_price": round(float(sell_price_points or 0) / 10, 2),
        "sell_price_points": int(sell_price_points or 0),
        "pricing_note": note,
        "pricing_details": {
            "billing_unit": "per_request",
            "resolution": resolution,
            "quality": quality,
        },
    }


def _resolution_rules(cost_map: Dict[str, float], note_prefix: str, *, generation_type: str) -> List[ImagePricingRule]:
    return [
        _fixed_rule(cost, f"{note_prefix} · {resolution.upper()}", generation_type=generation_type, resolution=resolution)
        for resolution, cost in cost_map.items()
    ]


def _resolution_rules_with_points(
    cost_map: Dict[str, float],
    point_map: Dict[str, int],
    note_prefix: str,
    *,
    generation_type: str,
) -> List[ImagePricingRule]:
    return [
        _fixed_rule_with_points(
            cost_map[resolution],
            f"{note_prefix} · {resolution.upper()}",
            generation_type=generation_type,
            resolution=resolution,
            sell_price_points=point_map[resolution],
        )
        for resolution in point_map.keys()
    ]


def _quality_resolution_rules_with_points(
    cost_map: Dict[str, Dict[str, float]],
    point_map: Dict[str, Dict[str, int]],
    note_prefix: str,
    *,
    generation_type: str,
) -> List[ImagePricingRule]:
    rules: List[ImagePricingRule] = []
    for quality in IMAGE_QUALITY_OPTIONS:
        for resolution in IMAGE_RESOLUTION_OPTIONS:
            rules.append(
                _fixed_rule_with_points(
                    cost_map[quality][resolution],
                    f"{note_prefix} · {IMAGE_QUALITY_LABELS[quality]} · {resolution.upper()}",
                    generation_type=generation_type,
                    resolution=resolution,
                    quality=quality,
                    sell_price_points=point_map[quality][resolution],
                )
            )
    return rules


def _base_fields(
    *,
    include_refs: bool,
    max_refs: int = 14,
    help_text: str = "",
    include_resolution: bool = True,
    include_quality: bool = False,
) -> List[ImageFieldConfig]:
    fields: List[ImageFieldConfig] = [
        _field("prompt", "图片描述", "textarea", required=True, placeholder="请输入希望生成的画面内容"),
    ]
    if include_quality:
        fields.append(_field("quality", "画质等级", "select", required=True, options=[_choice(item, IMAGE_QUALITY_LABELS[item]) for item in IMAGE_QUALITY_OPTIONS]))
    if include_resolution:
        fields.append(_field("resolution", "分辨率", "select", required=True, options=[_choice(item, item.upper()) for item in IMAGE_RESOLUTION_OPTIONS]))
    fields.append(_field("aspect_ratio", "画幅比例", "select", required=True, options=[_choice(item) for item in IMAGE_ASPECT_RATIO_OPTIONS]))
    if include_refs:
        fields.append(
            _field(
                "reference_images",
                "参考图",
                "media_list",
                media_type="image",
                min_count=1,
                max_count=max_refs,
                max_file_size_mb=10,
                help_text=help_text or f"最多 {max_refs} 张参考图",
            )
        )
    return fields


def normalize_image_model_code(value: Optional[str]) -> str:
    normalized = str(value or DEFAULT_IMAGE_MODEL_CODE).strip()
    if not normalized:
        return DEFAULT_IMAGE_MODEL_CODE
    lowered = normalized.lower()
    return IMAGE_MODEL_ALIASES.get(lowered, normalized)


def _is_model_enabled(model_code: str) -> bool:
    if model_code in {MODEL_GPT_IMAGE_2, MODEL_GPT_IMAGE_2_FAST}:
        return bool(str(settings.RUNNINGHUB_API_KEY or "").strip())
    return True


NANO_2_LOW_COSTS = {"1k": 0.16, "2k": 0.16, "4k": 0.20}
NANO_2_COSTS = {"1k": 0.49, "2k": 0.74, "4k": 0.99}
NANO_PRO_COSTS = {"1k": 0.80, "2k": 1.00, "4k": 1.50}
NANO_PRO_LOW_COSTS = {"1k": 0.40, "2k": 0.40, "4k": 0.50}
GPT_IMAGE_2_FAST_COST_CNY = 0.20
GPT_IMAGE_2_OFFICIAL_COSTS = {
    "low": {"1k": 0.29, "2k": 0.328, "4k": 0.378},
    "medium": {"1k": 0.586, "2k": 0.926, "4k": 1.373},
    "high": {"1k": 1.581, "2k": 2.948, "4k": 4.738},
}

NANO_2_LOW_POINTS = {"1k": 2, "2k": 2, "4k": 3}
NANO_2_POINTS = {"1k": 9, "2k": 11, "4k": 13}
NANO_PRO_LOW_POINTS = {"1k": 5, "2k": 5, "4k": 6}
NANO_PRO_POINTS = {"1k": 9, "2k": 11, "4k": 16}
NANO_PRO_ULTRA_POINTS = {"4k": 13, "8k": 16}
GPT_IMAGE_2_FAST_POINTS = 3
GPT_IMAGE_2_OFFICIAL_POINTS = {
    "low": {"1k": 4, "2k": 4, "4k": 5},
    "medium": {"1k": 7, "2k": 10, "4k": 15},
    "high": {"1k": 17, "2k": 31, "4k": 48},
}

TEXT_AND_IMAGE_FEATURES = {
    GEN_TEXT: {
        "generation_type": GEN_TEXT,
        "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT],
        "connection_status": "connected",
        "note": "",
        "defaults": {"resolution": DEFAULT_IMAGE_RESOLUTION, "aspect_ratio": DEFAULT_IMAGE_ASPECT_RATIO},
        "fields": _base_fields(include_refs=False),
        "pricing_rule_type": PRICING_RULE_FIXED_TABLE,
        "pricing_rules": [],
        "submit_type": "",
    },
    GEN_IMAGE: {
        "generation_type": GEN_IMAGE,
        "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE],
        "connection_status": "connected",
        "note": "",
        "defaults": {"resolution": DEFAULT_IMAGE_RESOLUTION, "aspect_ratio": DEFAULT_IMAGE_ASPECT_RATIO},
        "fields": _base_fields(include_refs=True),
        "pricing_rule_type": PRICING_RULE_FIXED_TABLE,
        "pricing_rules": [],
        "submit_type": "",
    },
}

IMAGE_MODEL_REGISTRY: Dict[str, ImageModelConfig] = {
    MODEL_NANO_2_LOW: {
        "model_code": MODEL_NANO_2_LOW,
        "label": MODEL_NANO_2_LOW,
        "series": "Nano Banana / 2 / Third-party",
        "category": CATEGORY_SPEED,
        "recommendation": "低价优先，适合快速试图和批量预览。",
        "supports_high_resolution": True,
        "status": IMAGE_STATUS_CONNECTED,
        "feature_tags": [GENERATION_TYPE_LABELS[GEN_TEXT], GENERATION_TYPE_LABELS[GEN_IMAGE], "RunningHub 优先"],
        "features": {
            GEN_TEXT: {
                **TEXT_AND_IMAGE_FEATURES[GEN_TEXT],
                "pricing_rules": _resolution_rules_with_points(NANO_2_LOW_COSTS, NANO_2_LOW_POINTS, "nano-banana-2-低价版 文生图", generation_type=GEN_TEXT),
                "submit_type": "runninghub_g31_flash_text",
            },
            GEN_IMAGE: {
                **TEXT_AND_IMAGE_FEATURES[GEN_IMAGE],
                "pricing_rules": _resolution_rules_with_points(NANO_2_LOW_COSTS, NANO_2_LOW_POINTS, "nano-banana-2-低价版 图生图", generation_type=GEN_IMAGE),
                "submit_type": "runninghub_g31_flash_image",
            },
        },
    },
    MODEL_NANO_2: {
        "model_code": MODEL_NANO_2,
        "label": MODEL_NANO_2,
        "series": "Nano Banana / 2 / Official",
        "category": CATEGORY_BALANCED,
        "recommendation": "均衡优先，适合常规正式出图。",
        "supports_high_resolution": True,
        "status": IMAGE_STATUS_CONNECTED,
        "feature_tags": [GENERATION_TYPE_LABELS[GEN_TEXT], GENERATION_TYPE_LABELS[GEN_IMAGE], "RunningHub 官方"],
        "features": {
            GEN_TEXT: {
                **TEXT_AND_IMAGE_FEATURES[GEN_TEXT],
                "pricing_rules": _resolution_rules_with_points(NANO_2_COSTS, NANO_2_POINTS, "nano-banana-2 文生图", generation_type=GEN_TEXT),
                "submit_type": "runninghub_g31_flash_official_text",
            },
            GEN_IMAGE: {
                **TEXT_AND_IMAGE_FEATURES[GEN_IMAGE],
                "pricing_rules": _resolution_rules_with_points(NANO_2_COSTS, NANO_2_POINTS, "nano-banana-2 图生图", generation_type=GEN_IMAGE),
                "submit_type": "runninghub_g31_flash_official_image",
            },
        },
    },
    MODEL_NANO_PRO: {
        "model_code": MODEL_NANO_PRO,
        "label": MODEL_NANO_PRO,
        "series": "Nano Banana / Pro / Official",
        "category": CATEGORY_QUALITY,
        "recommendation": "质量优先，适合角色一致性和正式版本。",
        "supports_high_resolution": True,
        "status": IMAGE_STATUS_CONNECTED,
        "feature_tags": [GENERATION_TYPE_LABELS[GEN_TEXT], GENERATION_TYPE_LABELS[GEN_IMAGE], "RunningHub PRO"],
        "features": {
            GEN_TEXT: {
                **TEXT_AND_IMAGE_FEATURES[GEN_TEXT],
                "pricing_rules": _resolution_rules_with_points(NANO_PRO_COSTS, NANO_PRO_POINTS, "nano-banana-pro 文生图", generation_type=GEN_TEXT),
                "submit_type": "runninghub_n_pro_text",
            },
            GEN_IMAGE: {
                **TEXT_AND_IMAGE_FEATURES[GEN_IMAGE],
                "pricing_rules": _resolution_rules_with_points(NANO_PRO_COSTS, NANO_PRO_POINTS, "nano-banana-pro 图生图", generation_type=GEN_IMAGE),
                "submit_type": "runninghub_n_pro_image",
            },
        },
    },
    MODEL_NANO_PRO_LOW: {
        "model_code": MODEL_NANO_PRO_LOW,
        "label": MODEL_NANO_PRO_LOW,
        "series": "Nano Banana / Pro / Third-party",
        "category": CATEGORY_SPEED,
        "recommendation": "更低成本的 Pro 路线，优先走 RunningHub Third-party 方案。",
        "supports_high_resolution": True,
        "status": IMAGE_STATUS_CONNECTED,
        "feature_tags": [GENERATION_TYPE_LABELS[GEN_TEXT], GENERATION_TYPE_LABELS[GEN_IMAGE], "RunningHub Third-party"],
        "features": {
            GEN_TEXT: {
                **TEXT_AND_IMAGE_FEATURES[GEN_TEXT],
                "pricing_rules": _resolution_rules_with_points(NANO_PRO_LOW_COSTS, NANO_PRO_LOW_POINTS, "nano-banana-pro-低价版 文生图", generation_type=GEN_TEXT),
                "submit_type": "runninghub_ai_app_pro_text_third_party",
            },
            GEN_IMAGE: {
                **TEXT_AND_IMAGE_FEATURES[GEN_IMAGE],
                "fields": _base_fields(include_refs=True, max_refs=3, help_text="当前 Third-party 方案默认最多 3 张参考图"),
                "pricing_rules": _resolution_rules_with_points(NANO_PRO_LOW_COSTS, NANO_PRO_LOW_POINTS, "nano-banana-pro-低价版 图生图", generation_type=GEN_IMAGE),
                "submit_type": "runninghub_ai_app_pro_image_third_party",
            },
        },
    },
    MODEL_GPT_IMAGE_2_FAST: {
        "model_code": MODEL_GPT_IMAGE_2_FAST,
        "label": MODEL_GPT_IMAGE_2_FAST,
        "series": "RunningHub / GPT Image 2 / Fast",
        "category": CATEGORY_FLAGSHIP,
        "recommendation": "旗舰体验，适合高质量单次生成；低价渠道版不提供分辨率选项，画面比例通过结构化参数提交。",
        "supports_high_resolution": True,
        "status": IMAGE_STATUS_CONNECTED,
        "feature_tags": [GENERATION_TYPE_LABELS[GEN_TEXT], GENERATION_TYPE_LABELS[GEN_IMAGE], "RunningHub G-2.0 低价渠道版", "3 灵感值"],
        "features": {
            GEN_TEXT: {
                **TEXT_AND_IMAGE_FEATURES[GEN_TEXT],
                "fields": _base_fields(include_refs=False, include_resolution=False),
                "pricing_rule_type": PRICING_RULE_SINGLE_FIXED,
                "pricing_rules": [_fixed_rule_with_points(GPT_IMAGE_2_FAST_COST_CNY, "gpt-image-2-fast 固定单次价格", generation_type=GEN_TEXT, sell_price_points=GPT_IMAGE_2_FAST_POINTS)],
                "submit_type": "runninghub_gpt_image_2_fast_text",
            },
            GEN_IMAGE: {
                **TEXT_AND_IMAGE_FEATURES[GEN_IMAGE],
                "fields": _base_fields(include_refs=True, max_refs=10, help_text="最多 10 张参考图，每张 10 MB", include_resolution=False),
                "pricing_rule_type": PRICING_RULE_SINGLE_FIXED,
                "pricing_rules": [_fixed_rule_with_points(GPT_IMAGE_2_FAST_COST_CNY, "gpt-image-2-fast 固定单次价格", generation_type=GEN_IMAGE, sell_price_points=GPT_IMAGE_2_FAST_POINTS)],
                "submit_type": "runninghub_gpt_image_2_fast_image",
            },
        },
    },
    MODEL_GPT_IMAGE_2: {
        "model_code": MODEL_GPT_IMAGE_2,
        "label": MODEL_GPT_IMAGE_2,
        "series": "RunningHub / GPT Image 2 / Official",
        "category": CATEGORY_FLAGSHIP,
        "recommendation": "官方稳定版，支持 quality 与 resolution 分档，适合高保真正式出图。",
        "supports_high_resolution": True,
        "status": IMAGE_STATUS_CONNECTED,
        "feature_tags": [GENERATION_TYPE_LABELS[GEN_TEXT], GENERATION_TYPE_LABELS[GEN_IMAGE], "RunningHub G-2 官方稳定版", "分档计费"],
        "features": {
            GEN_TEXT: {
                **TEXT_AND_IMAGE_FEATURES[GEN_TEXT],
                "defaults": {"resolution": DEFAULT_IMAGE_RESOLUTION, "quality": "medium", "aspect_ratio": DEFAULT_IMAGE_ASPECT_RATIO},
                "fields": _base_fields(include_refs=False, include_resolution=True, include_quality=True),
                "pricing_rule_type": PRICING_RULE_FIXED_TABLE,
                "pricing_rules": _quality_resolution_rules_with_points(GPT_IMAGE_2_OFFICIAL_COSTS, GPT_IMAGE_2_OFFICIAL_POINTS, "gpt-image-2 官方稳定版 文生图", generation_type=GEN_TEXT),
                "submit_type": "runninghub_gpt_image_2_official_text",
            },
            GEN_IMAGE: {
                **TEXT_AND_IMAGE_FEATURES[GEN_IMAGE],
                "defaults": {"resolution": DEFAULT_IMAGE_RESOLUTION, "quality": "medium", "aspect_ratio": DEFAULT_IMAGE_ASPECT_RATIO},
                "fields": _base_fields(include_refs=True, max_refs=10, help_text="最多 10 张参考图，每张 10 MB", include_resolution=True, include_quality=True),
                "pricing_rule_type": PRICING_RULE_FIXED_TABLE,
                "pricing_rules": _quality_resolution_rules_with_points(GPT_IMAGE_2_OFFICIAL_COSTS, GPT_IMAGE_2_OFFICIAL_POINTS, "gpt-image-2 官方稳定版 图生图", generation_type=GEN_IMAGE),
                "submit_type": "runninghub_gpt_image_2_official_image",
            },
        },
    },
}


def get_image_model_or_none(model_code: Optional[str]) -> Optional[ImageModelConfig]:
    normalized = normalize_image_model_code(model_code)
    if not _is_model_enabled(normalized):
        return None
    return IMAGE_MODEL_REGISTRY.get(normalized)


def list_supported_image_models() -> List[ImageModelConfig]:
    return [
        item
        for item in IMAGE_MODEL_REGISTRY.values()
        if item["status"] == IMAGE_STATUS_CONNECTED and _is_model_enabled(item["model_code"])
    ]


def _feature_start_points(feature: ImageFeatureConfig) -> Optional[int]:
    values = [int(item["sell_price_points"]) for item in feature.get("pricing_rules") or [] if item.get("sell_price_points") is not None]
    return min(values) if values else None


def build_image_catalog() -> Dict[str, Any]:
    categories: List[Dict[str, Any]] = []
    items: List[Dict[str, Any]] = []
    for model in list_supported_image_models():
        features: List[Dict[str, Any]] = []
        start_points = None
        for feature in model["features"].values():
            feature_start = _feature_start_points(feature)
            if feature_start is not None:
                start_points = feature_start if start_points is None else min(start_points, feature_start)
            features.append(
                {
                    "generation_type": feature["generation_type"],
                    "generation_type_label": feature["generation_type_label"],
                    "connection_status": feature["connection_status"],
                    "note": feature["note"],
                    "defaults": feature["defaults"],
                    "fields": feature["fields"],
                    "pricing_rule_type": feature["pricing_rule_type"],
                }
            )
        items.append(
            {
                "model_code": model["model_code"],
                "model_name": model["label"],
                "series": model["series"],
                "category": model["category"],
                "category_label": CATEGORY_LABELS[model["category"]],
                "recommendation": model["recommendation"],
                "supports_high_resolution": model["supports_high_resolution"],
                "status": model["status"],
                "start_points": start_points,
                "default_generation_type": GEN_TEXT,
                "feature_tags": model["feature_tags"],
                "features": features,
            }
        )
    for category in [CATEGORY_SPEED, CATEGORY_BALANCED, CATEGORY_QUALITY, CATEGORY_FLAGSHIP]:
        categories.append(
            {
                "code": category,
                "label": CATEGORY_LABELS[category],
                "models": [item for item in items if item["category"] == category and item["status"] == IMAGE_STATUS_CONNECTED],
            }
        )
    return {"categories": categories, "models": items}


def _normalize_generation_type(value: Optional[str], reference_images: Sequence[str]) -> str:
    text = str(value or "").strip().lower()
    if text in {GEN_TEXT, GEN_IMAGE}:
        return text
    return GEN_IMAGE if reference_images else GEN_TEXT


def _normalize_resolution(value: Optional[str]) -> str:
    normalized = str(value or DEFAULT_IMAGE_RESOLUTION).strip().lower()
    return normalized if normalized in IMAGE_RESOLUTION_OPTIONS else DEFAULT_IMAGE_RESOLUTION


def _normalize_quality(value: Optional[str]) -> str:
    normalized = str(value or "medium").strip().lower()
    return normalized if normalized in IMAGE_QUALITY_OPTIONS else "medium"


def _normalize_aspect_ratio(value: Optional[str]) -> str:
    normalized = str(value or DEFAULT_IMAGE_ASPECT_RATIO).strip()
    return normalized if normalized in IMAGE_ASPECT_RATIO_OPTIONS else DEFAULT_IMAGE_ASPECT_RATIO


def _normalize_reference_images(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _looks_like_public_image_url(url: str) -> bool:
    value = str(url or "").strip()
    return value.startswith("http://") or value.startswith("https://")


def _build_gpt_image_2_prompt(normalized: Dict[str, Any]) -> str:
    return str(normalized.get("prompt") or "").strip()


def normalize_image_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    model_code = normalize_image_model_code(payload.get("model_code") or payload.get("model") or payload.get("channel"))
    if not _is_model_enabled(model_code):
        raise ValueError("model_not_configured")
    model = get_image_model_or_none(model_code)
    if not model:
        raise ValueError("invalid_model")

    reference_images = _normalize_reference_images(payload.get("reference_images") or payload.get("imageUrls"))
    generation_type = GEN_IMAGE if reference_images else GEN_TEXT
    feature = model["features"].get(generation_type)
    if not feature:
        raise ValueError("invalid_generation_type")

    resolution = _normalize_resolution(payload.get("resolution"))
    supports_quality = any(item.get("key") == "quality" for item in feature["fields"])
    quality = _normalize_quality(payload.get("quality")) if supports_quality else None
    aspect_ratio = _normalize_aspect_ratio(payload.get("aspect_ratio") or payload.get("aspectRatio"))
    prompt = str(payload.get("prompt") or "").strip()

    if not prompt:
        raise ValueError("prompt")
    if generation_type == GEN_IMAGE and not reference_images:
        raise ValueError("reference_images")

    max_count = next((int(item.get("max_count") or 0) for item in feature["fields"] if item.get("key") == "reference_images"), 0)
    if max_count and len(reference_images) > max_count:
        raise ValueError("reference_images")

    return {
        "model_code": model["model_code"],
        "model_name": model["label"],
        "generation_type": generation_type,
        "generation_type_label": feature["generation_type_label"],
        "prompt": prompt,
        "resolution": resolution,
        "quality": quality,
        "quality_label": IMAGE_QUALITY_LABELS.get(quality or "", quality or ""),
        "aspect_ratio": aspect_ratio,
        "reference_images": reference_images,
        "pricing_rule_type": feature["pricing_rule_type"],
        "submit_type": feature["submit_type"],
        "feature_note": feature["note"],
    }


def estimate_image_price(model_code: str, generation_type: str, normalized: Dict[str, Any]) -> Dict[str, Any]:
    model = get_image_model_or_none(model_code)
    if not model:
        raise ValueError("invalid_model")
    feature = model["features"].get(generation_type)
    if not feature:
        raise ValueError("invalid_generation_type")

    if feature["pricing_rule_type"] == PRICING_RULE_SINGLE_FIXED:
        rule = (feature.get("pricing_rules") or [None])[0]
        if not rule:
            raise ValueError("missing_price")
        return {
            "pricing_rule_type": rule["pricing_rule_type"],
            "cost_price": rule["cost_price"],
            "suggested_price": rule["suggested_price"],
            "sell_price_points": rule["sell_price_points"],
            "pricing_note": rule["pricing_note"],
            "pricing_details": rule["pricing_details"],
        }

    resolution = str(normalized.get("resolution") or DEFAULT_IMAGE_RESOLUTION).lower()
    quality = str(normalized.get("quality") or "medium").lower()
    for rule in feature.get("pricing_rules") or []:
        rule_quality = str(rule.get("quality") or "").lower()
        if str(rule.get("resolution") or "").lower() == resolution and (not rule_quality or rule_quality == quality):
            return {
                "pricing_rule_type": rule["pricing_rule_type"],
                "cost_price": rule["cost_price"],
                "suggested_price": rule["suggested_price"],
                "sell_price_points": rule["sell_price_points"],
                "pricing_note": rule["pricing_note"],
                "pricing_details": rule["pricing_details"],
            }
    raise ValueError("missing_price")


def _runninghub_headers() -> Dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer {0}".format(settings.RUNNINGHUB_API_KEY),
    }


def _runninghub_submit(endpoint: str, payload: Dict[str, Any]) -> str:
    response = requests.post(endpoint, json=payload, headers=_runninghub_headers(), timeout=60)
    data = _safe_response_payload(response)
    task_id = str(data.get("taskId") or "").strip()
    if not task_id:
        raw_text = str(data.get("_raw_text") or "").strip()
        match = re.search(r'"taskId"\s*:\s*"([^"]+)"', raw_text)
        if match:
            task_id = match.group(1).strip()
    if not response.ok or not task_id:
        raise RuntimeError(data.get("errorMessage") or data.get("message") or "图片服务暂不可用")
    return task_id


def _build_runninghub_ai_app_payload(*, prompt: str, resolution: str, aspect_ratio: str, reference_images: Sequence[str], channel: str) -> Dict[str, Any]:
    node_info_list: List[Dict[str, Any]] = []
    for node_id, image_url in zip(RUNNINGHUB_AI_APP_THIRD_PARTY_IMAGE_SLOTS, list(reference_images)[: len(RUNNINGHUB_AI_APP_THIRD_PARTY_IMAGE_SLOTS)]):
        node_info_list.append(
            {
                "nodeId": node_id,
                "fieldName": "image",
                "fieldValue": image_url,
            }
        )
    node_info_list.extend(
        [
            {"nodeId": "2", "fieldName": "aspectRatio", "fieldValue": aspect_ratio},
            {"nodeId": "2", "fieldName": "resolution", "fieldValue": resolution},
            {"nodeId": "2", "fieldName": "channel", "fieldValue": channel},
            {"nodeId": "2", "fieldName": "prompt", "fieldValue": prompt},
        ]
    )
    return {
        "nodeInfoList": node_info_list,
        "instanceType": "default",
        "usePersonalQueue": "false",
    }


def _build_submit_payload(normalized: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    submit_type = str(normalized["submit_type"])
    prompt = normalized["prompt"]
    resolution = normalized["resolution"]
    quality = normalized.get("quality") or "medium"
    aspect_ratio = normalized["aspect_ratio"]
    reference_images = normalized["reference_images"]

    if submit_type == "runninghub_g31_flash_text":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash/text-to-image",
            {"prompt": prompt, "resolution": resolution, "aspectRatio": aspect_ratio},
        )
    if submit_type == "runninghub_g31_flash_image":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash/image-to-image",
            {"prompt": prompt, "resolution": resolution, "aspectRatio": aspect_ratio, "imageUrls": reference_images},
        )
    if submit_type == "runninghub_g31_flash_official_text":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash-official/text-to-image",
            {"prompt": prompt, "resolution": resolution, "aspectRatio": aspect_ratio},
        )
    if submit_type == "runninghub_g31_flash_official_image":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash-official/image-to-image",
            {"prompt": prompt, "resolution": resolution, "aspectRatio": aspect_ratio, "imageUrls": reference_images},
        )
    if submit_type == "runninghub_n_pro_text":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-n-pro/text-to-image",
            {"prompt": prompt, "resolution": resolution, "aspectRatio": aspect_ratio},
        )
    if submit_type == "runninghub_n_pro_image":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-n-pro/edit",
            {"prompt": prompt, "resolution": resolution, "aspectRatio": aspect_ratio, "imageUrls": reference_images},
        )
    if submit_type == "runninghub_ai_app_pro_text_third_party":
        return (
            RUNNINGHUB_AI_APP_URL.format(workflow_id=settings.WORKFLOW_ID),
            _build_runninghub_ai_app_payload(prompt=prompt, resolution=resolution, aspect_ratio=aspect_ratio, reference_images=[], channel="Third-party"),
        )
    if submit_type == "runninghub_ai_app_pro_image_third_party":
        return (
            RUNNINGHUB_AI_APP_URL.format(workflow_id=settings.WORKFLOW_ID),
            _build_runninghub_ai_app_payload(prompt=prompt, resolution=resolution, aspect_ratio=aspect_ratio, reference_images=reference_images, channel="Third-party"),
        )
    if submit_type == "runninghub_gpt_image_2_fast_text":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-g-2/text-to-image",
            {
                "prompt": _build_gpt_image_2_prompt(normalized),
                "aspectRatio": aspect_ratio,
            },
        )
    if submit_type == "runninghub_gpt_image_2_fast_image":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-g-2/image-to-image",
            {
                "prompt": _build_gpt_image_2_prompt(normalized),
                "imageUrls": reference_images,
                "aspectRatio": aspect_ratio,
            },
        )
    if submit_type == "runninghub_gpt_image_2_official_text":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-g-2-official/text-to-image",
            {
                "prompt": _build_gpt_image_2_prompt(normalized),
                "aspectRatio": aspect_ratio,
                "resolution": resolution,
                "quality": quality,
            },
        )
    if submit_type == "runninghub_gpt_image_2_official_image":
        return (
            "https://www.runninghub.cn/openapi/v2/rhart-image-g-2-official/image-to-image",
            {
                "prompt": _build_gpt_image_2_prompt(normalized),
                "imageUrls": reference_images,
                "aspectRatio": aspect_ratio,
                "resolution": resolution,
                "quality": quality,
            },
        )
    raise RuntimeError("unsupported_submit_type")


def _normalize_http_url_candidate(value: str) -> str:
    return str(value or "").strip().rstrip(");,]}>.")


def _canonicalize_url_for_compare(value: str) -> str:
    return _normalize_http_url_candidate(value)


def _is_blocked_output_url(candidate: str, blocked_urls: Optional[Sequence[str]] = None) -> bool:
    if not candidate:
        return False
    normalized_candidate = _canonicalize_url_for_compare(candidate)
    if not normalized_candidate:
        return False
    blocked = {_canonicalize_url_for_compare(item) for item in (blocked_urls or []) if str(item or "").strip()}
    return normalized_candidate in blocked


def _extract_first_http_url(value: str, *, blocked_urls: Optional[Sequence[str]] = None) -> Optional[str]:
    match = re.search(r"https?://[^\s\"']+", value or "")
    if not match:
        return None
    candidate = _normalize_http_url_candidate(match.group(0))
    if _is_blocked_output_url(candidate, blocked_urls):
        return None
    return candidate or None


def _safe_response_payload(response: requests.Response) -> Dict[str, Any]:
    try:
        data = response.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"data": data}
    text = ""
    try:
        text = response.text or ""
    except Exception:
        text = ""
    return {"_raw_text": text}


def _extract_runninghub_output_url(data: Dict[str, Any]) -> str:
    result_lists = []
    if isinstance(data.get("results"), list):
        result_lists.append(data.get("results"))
    nested_data = data.get("data")
    if isinstance(nested_data, dict) and isinstance(nested_data.get("results"), list):
        result_lists.append(nested_data.get("results"))

    for results in result_lists:
        for item in results or []:
            if not isinstance(item, dict):
                continue
            for key in ("url", "fileUrl", "download_url"):
                candidate = str(item.get(key) or "").strip()
                if candidate:
                    return candidate
            candidate = _extract_first_http_url(str(item.get("text") or ""))
            if candidate:
                return candidate
    raw_text = str(data.get("_raw_text") or "").strip()
    if raw_text:
        candidate = _extract_first_http_url(raw_text)
        if candidate:
            return candidate
    return ""


def _extract_runninghub_status(data: Dict[str, Any]) -> str:
    status = str(data.get("status") or "").strip()
    if status:
        return status.upper()
    nested_data = data.get("data")
    if isinstance(nested_data, dict):
        nested_status = str(nested_data.get("status") or nested_data.get("taskStatus") or "").strip()
        if nested_status:
            return nested_status.upper()
    raw_text = str(data.get("_raw_text") or "").strip()
    match = re.search(r'"status"\s*:\s*"([A-Za-z_]+)"', raw_text)
    if match:
        return str(match.group(1) or "").upper()
    return ""


def _extract_runninghub_error(data: Dict[str, Any]) -> str:
    for key in ("errorMessage", "failedReason", "message"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    nested_data = data.get("data")
    if isinstance(nested_data, dict):
        for key in ("errorMessage", "failedReason", "message"):
            value = str(nested_data.get(key) or "").strip()
            if value:
                return value
    return str(data.get("_raw_text") or "").strip()[:300]


def submit_image_generation(normalized: Dict[str, Any]) -> Dict[str, Any]:
    endpoint, payload = _build_submit_payload(normalized)
    webhook_url = str(normalized.get("webhook_url") or "").strip()
    if webhook_url:
        payload["webhookUrl"] = webhook_url
    return {
        "provider": PROVIDER_RUNNINGHUB_IMAGE,
        "completion_mode": "webhook" if webhook_url else "poll",
        "upstream_task_id": _runninghub_submit(endpoint, payload),
    }


def query_image_generation(provider: str, upstream_task_id: str) -> ProviderResult:
    if provider == PROVIDER_RUNNINGHUB_IMAGE:
        response = requests.post(RUNNINGHUB_QUERY_URL, json={"taskId": upstream_task_id}, headers=_runninghub_headers(), timeout=30)
        data = _safe_response_payload(response)
        status = _extract_runninghub_status(data)
        if status == "SUCCESS":
            url = _extract_runninghub_output_url(data)
            return ProviderResult(is_done=True, is_failed=False, output_url=url or None, raw_payload=data)
        if status == "FAILED":
            return ProviderResult(is_done=True, is_failed=True, error=_extract_runninghub_error(data), raw_payload=data)
        fallback_url = _extract_runninghub_output_url(data)
        if fallback_url:
            return ProviderResult(is_done=True, is_failed=False, output_url=fallback_url, raw_payload=data)
        if not response.ok:
            return ProviderResult(is_done=True, is_failed=True, error=_extract_runninghub_error(data) or "RunningHub 查询失败", raw_payload=data)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=data)
    return ProviderResult(is_done=True, is_failed=True, error="unknown image provider")
