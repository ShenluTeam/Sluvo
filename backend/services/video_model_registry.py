from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence, TypedDict

CATEGORY_SPEED = "speed"
CATEGORY_QUALITY = "quality"
CATEGORY_CONSISTENCY = "consistency"
CATEGORY_CONTROL = "control"

CATEGORY_LABELS = {
    CATEGORY_SPEED: "速度优先",
    CATEGORY_QUALITY: "质量优先",
    CATEGORY_CONSISTENCY: "一致性优先",
    CATEGORY_CONTROL: "控制力优先",
}

GEN_TEXT = "text_to_video"
GEN_IMAGE = "image_to_video"
GEN_REFERENCE = "reference_to_video"
GEN_START_END = "start_end_to_video"

GENERATION_TYPE_LABELS = {
    GEN_TEXT: "文生视频",
    GEN_IMAGE: "图生视频",
    GEN_REFERENCE: "参考生视频",
    GEN_START_END: "首尾帧视频",
}

PRICING_RULE_FIXED_TABLE = "fixed_table"
PRICING_RULE_PER_SECOND = "per_second"
PRICING_RULE_PER_SECOND_WITH_ADDON = "per_second_with_addon"
PRICING_RULE_MULTIMODAL_MIN_BILL = "multimodal_min_bill"

VIDEO_STATUS_CONNECTED = "已接入"
VIDEO_STATUS_PENDING = "待确认"

ASPECT_RATIO_OPTIONS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"]
MOTION_OPTIONS = ["auto", "small", "medium", "large"]
QUALITY_MODE_OPTIONS = ["std", "pro"]
QUALITY_MODE_LABELS = {"std": "标准", "pro": "高质量"}
SEEDANCE_IMAGE_REF_ROLE_ORDER = {"semantic": 0, "auxiliary": 1, "storyboard_board": 2}
SEEDANCE_IMAGE_REF_ROLES = set(SEEDANCE_IMAGE_REF_ROLE_ORDER.keys())

SEEDANCE_20_MIN_BILL_SECONDS = {4: 7, 5: 9, 6: 10, 7: 12, 8: 14, 9: 15, 10: 17, 11: 19, 12: 20, 13: 22, 14: 24, 15: 25}


class VideoFieldConfig(TypedDict, total=False):
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


class VideoPricingRule(TypedDict, total=False):
    pricing_rule_type: str
    component: str
    resolution: str
    duration: int
    audio_enabled: bool
    quality_mode: str
    has_video_ref: bool
    cost_price: float
    suggested_price: float
    sell_price_points: int
    pricing_note: str
    pricing_details: Dict[str, Any]


class VideoFeatureConfig(TypedDict):
    generation_type: str
    generation_type_label: str
    endpoint: str
    submit_type: str
    defaults: Dict[str, Any]
    fields: List[VideoFieldConfig]
    pricing_rule_type: str
    pricing_rules: List[VideoPricingRule]
    note: str
    connection_status: str


class VideoModelConfig(TypedDict):
    model_code: str
    label: str
    series: str
    category: str
    recommendation: str
    supports_audio: bool
    supports_high_resolution: bool
    status: str
    features: Dict[str, VideoFeatureConfig]


class VideoPricingEstimateResult(TypedDict):
    pricing_rule_type: str
    cost_price: float
    suggested_price: float
    sell_price_points: int
    pricing_note: str
    pricing_details: Dict[str, Any]


def _choice(value: str, label: Optional[str] = None) -> Dict[str, str]:
    return {"value": value, "label": label or value}


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


def _field(key: str, label: str, field_type: str, **extra: Any) -> VideoFieldConfig:
    payload: VideoFieldConfig = {"key": key, "label": label, "type": field_type}
    payload.update({k: v for k, v in extra.items() if v is not None})
    return payload


def _base_fields(
    durations: Sequence[int],
    resolutions: Sequence[str],
    *,
    image_list: Optional[dict] = None,
    video_list: Optional[dict] = None,
    audio_list: Optional[dict] = None,
    first_frame: Optional[dict] = None,
    last_frame: Optional[dict] = None,
    audio_enabled: bool = False,
    motion_strength: bool = False,
    quality_mode: bool = False,
    camera_fixed: bool = False,
    real_person_mode: bool = False,
    web_search: bool = False,
) -> List[VideoFieldConfig]:
    fields: List[VideoFieldConfig] = [
        _field("prompt", "视频描述", "textarea", required=True, placeholder="请输入希望生成的视频内容"),
        _field("duration", "时长", "select", required=True, options=[_choice(str(v), f"{v}秒") for v in durations]),
        _field("resolution", "分辨率", "select", required=True, options=[_choice(v, v.upper() if v.endswith("k") else v) for v in resolutions]),
        _field("aspect_ratio", "画幅比例", "select", required=True, options=[_choice(v) for v in ASPECT_RATIO_OPTIONS]),
    ]
    if image_list:
        fields.append(_field("image_refs", "参考图", "media_list", media_type="image", **image_list))
    if video_list:
        fields.append(_field("video_refs", "参考视频", "media_list", media_type="video", **video_list))
    if audio_list:
        fields.append(_field("audio_refs", "参考音频", "media_list", media_type="audio", **audio_list))
    if first_frame:
        fields.append(_field("first_frame", "首帧图片", "media_single", media_type="image", **first_frame))
    if last_frame:
        fields.append(_field("last_frame", "尾帧图片", "media_single", media_type="image", **last_frame))
    if motion_strength:
        fields.append(_field("motion_strength", "镜头运动强度", "select", options=[_choice(v) for v in MOTION_OPTIONS]))
    if audio_enabled:
        fields.append(_field("audio_enabled", "开启音频", "switch"))
    if real_person_mode:
        fields.append(_field("real_person_mode", "真人模式", "switch"))
    if web_search:
        fields.append(_field("web_search", "联网增强", "switch"))
    if quality_mode:
        fields.append(_field("quality_mode", "质量档位", "select", options=[_choice(v, QUALITY_MODE_LABELS[v]) for v in QUALITY_MODE_OPTIONS]))
    if camera_fixed:
        fields.append(_field("camera_fixed", "固定机位", "switch"))
    return fields


def _fixed_rule(cost_price: float, note: str, **meta: Any) -> VideoPricingRule:
    suggested, points = _sell_values(cost_price)
    payload: VideoPricingRule = {
        "pricing_rule_type": PRICING_RULE_FIXED_TABLE,
        "component": "total",
        "cost_price": round(cost_price, 2),
        "suggested_price": suggested,
        "sell_price_points": points,
        "pricing_note": note,
        "pricing_details": {"unit": "total"},
    }
    payload.update({k: v for k, v in meta.items() if v is not None})
    return payload


def _unit_rule(rule_type: str, component: str, cost_price: float, note: str, **meta: Any) -> VideoPricingRule:
    suggested, points = _sell_values(cost_price)
    payload: VideoPricingRule = {
        "pricing_rule_type": rule_type,
        "component": component,
        "cost_price": round(cost_price, 2),
        "suggested_price": suggested,
        "sell_price_points": points,
        "pricing_note": note,
        "pricing_details": {"unit": "per_second"},
    }
    payload.update({k: v for k, v in meta.items() if v is not None})
    return payload


def _build_fixed_cost_map(cost_map: Dict[str, float], note_prefix: str, *, duration: Optional[int] = None, audio_enabled: Optional[bool] = None, quality_mode: Optional[str] = None) -> List[VideoPricingRule]:
    return [_fixed_rule(cost, f"{note_prefix} · {resolution}" + (f" · {duration}秒" if duration is not None else "") + (f" · {'开音频' if audio_enabled else '关音频'}" if audio_enabled is not None else "") + (f" · {QUALITY_MODE_LABELS[quality_mode]}" if quality_mode else ""), resolution=resolution, duration=duration, audio_enabled=audio_enabled, quality_mode=quality_mode) for resolution, cost in cost_map.items()]


def _build_fixed_duration_map(cost_map: Dict[str, Dict[int, float]], note_prefix: str, *, audio_enabled: Optional[bool] = None) -> List[VideoPricingRule]:
    rules: List[VideoPricingRule] = []
    for resolution, duration_map in cost_map.items():
        for duration, cost in duration_map.items():
            rules.append(_fixed_rule(cost, f"{note_prefix} · {resolution} · {duration}秒" + (f" · {'开音频' if audio_enabled else '关音频'}" if audio_enabled is not None else ""), resolution=resolution, duration=duration, audio_enabled=audio_enabled))
    return rules


def _build_fixed_rate_map(rate_map: Dict[str, float], durations: Sequence[int], note_prefix: str, *, audio_enabled: Optional[bool] = None) -> List[VideoPricingRule]:
    rules: List[VideoPricingRule] = []
    for resolution, unit_cost in rate_map.items():
        for duration in durations:
            rules.append(_fixed_rule(round(unit_cost * duration, 2), f"{note_prefix} · {resolution} · {duration}秒" + (f" · {'开音频' if audio_enabled else '关音频'}" if audio_enabled is not None else ""), resolution=resolution, duration=duration, audio_enabled=audio_enabled))
    return rules


def _build_fixed_audio_rates(rate_map: Dict[str, Dict[bool, float]], durations: Sequence[int], note_prefix: str) -> List[VideoPricingRule]:
    rules: List[VideoPricingRule] = []
    for resolution, audio_map in rate_map.items():
        for audio_enabled, unit_cost in audio_map.items():
            for duration in durations:
                rules.append(_fixed_rule(round(unit_cost * duration, 2), f"{note_prefix} · {resolution} · {duration}秒 · {'开音频' if audio_enabled else '关音频'}", resolution=resolution, duration=duration, audio_enabled=audio_enabled))
    return rules


def _build_per_second(rate_map: Dict[str, float], note_prefix: str) -> List[VideoPricingRule]:
    return [_unit_rule(PRICING_RULE_PER_SECOND, "unit", cost, f"{note_prefix} · {resolution}", resolution=resolution) for resolution, cost in rate_map.items()]


def _build_audio_per_second(cost_off: float, cost_on: float, note_prefix: str) -> List[VideoPricingRule]:
    return [
        _unit_rule(PRICING_RULE_PER_SECOND, "unit", cost_off, f"{note_prefix} · 关音频", audio_enabled=False),
        _unit_rule(PRICING_RULE_PER_SECOND, "unit", cost_on, f"{note_prefix} · 开音频", audio_enabled=True),
    ]


def _build_ref_addon(base_off: float, base_on: float, addon: float, note_prefix: str) -> List[VideoPricingRule]:
    return [
        _unit_rule(PRICING_RULE_PER_SECOND_WITH_ADDON, "base", base_off, f"{note_prefix} · 基础计费 · 关音频", audio_enabled=False, has_video_ref=False),
        _unit_rule(PRICING_RULE_PER_SECOND_WITH_ADDON, "base", base_on, f"{note_prefix} · 基础计费 · 开音频", audio_enabled=True, has_video_ref=False),
        _unit_rule(PRICING_RULE_PER_SECOND_WITH_ADDON, "addon", addon, f"{note_prefix} · videoUrl 附加计费", has_video_ref=True),
    ]


def _build_multimodal(no_ref: Dict[str, float], ref_base: Dict[str, float], ref_addon: Dict[str, float], note_prefix: str) -> List[VideoPricingRule]:
    rules: List[VideoPricingRule] = []
    for resolution, cost in no_ref.items():
        rules.append(_unit_rule(PRICING_RULE_MULTIMODAL_MIN_BILL, "base", cost, f"{note_prefix} · {resolution} · 无参考视频", resolution=resolution, has_video_ref=False))
    for resolution, cost in ref_base.items():
        rules.append(_unit_rule(PRICING_RULE_MULTIMODAL_MIN_BILL, "base", cost, f"{note_prefix} · {resolution} · 有参考视频 · 基础计费", resolution=resolution, has_video_ref=True))
    for resolution, cost in ref_addon.items():
        rules.append(_unit_rule(PRICING_RULE_MULTIMODAL_MIN_BILL, "addon", cost, f"{note_prefix} · {resolution} · 有参考视频 · 生成秒附加计费", resolution=resolution, has_video_ref=True))
    return rules


_VEO_LOW_DURATIONS = [8]
_VEO_OFFICIAL_DURATIONS = [4, 6, 8]
_VIDU_Q2_DURATIONS = list(range(1, 11))
_VIDU_Q2_START_DURATIONS = list(range(1, 9))
_VIDU_Q3_DURATIONS = list(range(1, 17))
_SEEDANCE_V15_DURATIONS = list(range(4, 13))
_SEEDANCE_20_DURATIONS = list(range(4, 16))
_KLING_DURATIONS = list(range(3, 16))

_VEO_FAST_LOW = {"720p": 0.20, "1080p": 0.25, "4k": 0.50}
_VEO_PRO_LOW = {"720p": 0.80, "1080p": 1.00, "4k": 1.40}
_VEO_FAST_OFFICIAL = {4: {False: 2.35, True: 3.52}, 6: {False: 3.52, True: 5.32}, 8: {False: 4.70, True: 7.04}}
_VEO_PRO_OFFICIAL = {4: {False: 4.70, True: 9.40}, 6: {False: 7.04, True: 14.10}, 8: {False: 9.40, True: 18.80}}
_VIDU_Q2 = {"540p": {1: 0.18, 2: 0.22, 3: 0.33, 4: 0.44, 5: 0.55, 6: 0.66, 7: 0.77, 8: 0.88, 9: 0.99, 10: 1.10}, "720p": {1: 0.33, 2: 0.55, 3: 0.77, 4: 0.98, 5: 1.20, 6: 1.42, 7: 1.64, 8: 1.86, 9: 2.08, 10: 2.30}, "1080p": {1: 1.20, 2: 1.53, 3: 1.86, 4: 2.19, 5: 2.52, 6: 2.84, 7: 3.17, 8: 3.50, 9: 3.83, 10: 4.16}}
_VIDU_Q2_REF = {"540p": {1: 0.44, 2: 0.55, 3: 0.66, 4: 0.77, 5: 0.88, 6: 0.98, 7: 1.09, 8: 1.20, 9: 1.31, 10: 1.42}, "720p": {1: 0.66, 2: 0.77, 3: 0.88, 4: 0.98, 5: 1.09, 6: 1.20, 7: 1.31, 8: 1.42, 9: 1.53, 10: 1.64}, "1080p": {1: 1.86, 2: 2.08, 3: 2.30, 4: 2.52, 5: 2.73, 6: 2.95, 7: 3.17, 8: 3.39, 9: 3.61, 10: 3.83}}
_VIDU_Q2_FAST = {"540p": {1: 0.44, 2: 0.55, 3: 0.66, 4: 0.77, 5: 0.88, 6: 0.98, 7: 1.09, 8: 1.20, 9: 1.31, 10: 1.42}, "720p": {1: 0.66, 2: 0.77, 3: 0.88, 4: 0.98, 5: 1.09, 6: 1.20, 7: 1.31, 8: 1.42, 9: 1.53, 10: 1.64}, "1080p": {1: 1.86, 2: 2.08, 3: 2.30, 4: 2.52, 5: 2.73, 6: 2.95, 7: 3.17, 8: 3.39, 9: 3.61, 10: 3.83}}
_VIDU_Q2_FAST_START = {"720p": {1: 0.18, 2: 0.23, 3: 0.28, 4: 0.33, 5: 0.38, 6: 0.43, 7: 0.48, 8: 0.53}, "1080p": {1: 0.35, 2: 0.44, 3: 0.53, 4: 0.62, 5: 0.71, 6: 0.80, 7: 0.89, 8: 0.98}}
_VIDU_Q3_PRO_TEXT = {"360p": 0.31, "540p": 0.31, "720p": 0.66, "1080p": 0.70}
_VIDU_Q3_PRO_IMAGE = {"360p": 0.31, "540p": 0.31, "720p": 0.66, "1080p": 0.70, "2k": 1.09}
_VIDU_Q3_PRO_START = {"540p": 0.31, "720p": 0.66, "1080p": 0.70}
_VIDU_Q3_TURBO = {"540p": 0.18, "720p": 0.27, "1080p": 0.35}
_SEEDANCE_V15_PRO = {"480p": {False: 0.07, True: 0.14}, "720p": {False: 0.16, True: 0.32}, "1080p": {False: 0.35, True: 0.70}}
_SEEDANCE_V15_FAST = {"720p": {False: 0.16, True: 0.32}, "1080p": {False: 0.35, True: 0.70}}
_SEEDANCE_20_FAST = {"480p": 0.50, "720p": 1.00, "1080p": 1.28, "2k": 1.42, "4k": 1.63}
_SEEDANCE_20 = {"480p": 0.60, "720p": 1.20, "1080p": 1.48, "2k": 1.62, "4k": 1.83}
_SEEDANCE_20_FAST_BASE = {"480p": 0.30, "720p": 0.60, "1080p": 0.60, "2k": 0.60, "4k": 0.60}
_SEEDANCE_20_BASE = {"480p": 0.40, "720p": 0.80, "1080p": 0.80, "2k": 0.80, "4k": 0.80}
_SEEDANCE_20_ADDON = {"1080p": 0.28, "2k": 0.42, "4k": 0.63}
_KLING_O1 = {"std": {5: 2.10, 10: 4.20}, "pro": {5: 2.80, 10: 5.60}}

VIDEO_MODEL_REGISTRY: Dict[str, VideoModelConfig] = {
    "veo_31_fast": {"model_code": "veo_31_fast", "label": "Veo 3.1 Fast", "series": "Veo / 3.1 Fast", "category": CATEGORY_SPEED, "recommendation": "速度优先，适合批量预览和快速试错。", "supports_audio": False, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "veo_31_pro": {"model_code": "veo_31_pro", "label": "Veo 3.1 Pro", "series": "Veo / 3.1 Pro", "category": CATEGORY_QUALITY, "recommendation": "质量优先，适合正式成片和电影感镜头。", "supports_audio": False, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "veo_31_fast_official": {"model_code": "veo_31_fast_official", "label": "Veo 3.1 Fast Official", "series": "Veo / 3.1 Fast Official", "category": CATEGORY_SPEED, "recommendation": "官方稳定版，支持原生音画同步。", "supports_audio": True, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "veo_31_pro_official": {"model_code": "veo_31_pro_official", "label": "Veo 3.1 Pro Official", "series": "Veo / 3.1 Pro Official", "category": CATEGORY_QUALITY, "recommendation": "官方稳定版质量档，适合正式成片。", "supports_audio": True, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "vidu_q2_pro": {"model_code": "vidu_q2_pro", "label": "Vidu Q2 Pro", "series": "Vidu / Q2 Pro", "category": CATEGORY_CONSISTENCY, "recommendation": "人物一致性和多参考稳定性较强。", "supports_audio": True, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "vidu_q2_pro_fast": {"model_code": "vidu_q2_pro_fast", "label": "Vidu Q2 Pro Fast", "series": "Vidu / Q2 Pro Fast", "category": CATEGORY_SPEED, "recommendation": "低成本快速动态化。", "supports_audio": False, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "vidu_q3_pro": {"model_code": "vidu_q3_pro", "label": "Vidu Q3 Pro", "series": "Vidu / Q3 Pro", "category": CATEGORY_QUALITY, "recommendation": "高质感长时长叙事。", "supports_audio": True, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "vidu_q3_turbo": {"model_code": "vidu_q3_turbo", "label": "Vidu Q3 Turbo", "series": "Vidu / Q3 Turbo", "category": CATEGORY_SPEED, "recommendation": "速度优先，适合长时长快速成片。", "supports_audio": False, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "seedance_v15_pro": {"model_code": "seedance_v15_pro", "label": "Seedance v1.5 Pro", "series": "Seedance / v1.5 Pro", "category": CATEGORY_QUALITY, "recommendation": "写实质感强。", "supports_audio": True, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "seedance_v15_fast": {"model_code": "seedance_v15_fast", "label": "Seedance v1.5 Pro Fast", "series": "Seedance / v1.5 Pro Fast", "category": CATEGORY_SPEED, "recommendation": "速度更快，适合预演。", "supports_audio": True, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "seedance_20_fast": {"model_code": "seedance_20_fast", "label": "Seedance 2.0 Fast", "series": "Seedance / 2.0 Fast", "category": CATEGORY_SPEED, "recommendation": "速度优先，支持多模态编辑。", "supports_audio": True, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "seedance_20": {"model_code": "seedance_20", "label": "Seedance 2.0", "series": "Seedance / 2.0", "category": CATEGORY_QUALITY, "recommendation": "质量优先，支持多模态编辑。", "supports_audio": True, "supports_high_resolution": True, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "kling_o1": {"model_code": "kling_o1", "label": "Kling o1", "series": "Kling / o1", "category": CATEGORY_CONTROL, "recommendation": "控制力优先。", "supports_audio": True, "supports_high_resolution": False, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "kling_30_std": {"model_code": "kling_30_std", "label": "Kling 3.0 Std", "series": "Kling / 3.0 Std", "category": CATEGORY_QUALITY, "recommendation": "电影感基础档。", "supports_audio": True, "supports_high_resolution": False, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "kling_30_pro": {"model_code": "kling_30_pro", "label": "Kling 3.0 Pro", "series": "Kling / 3.0 Pro", "category": CATEGORY_QUALITY, "recommendation": "高保真成片。", "supports_audio": True, "supports_high_resolution": False, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "kling_o3_std": {"model_code": "kling_o3_std", "label": "Kling O3 Std", "series": "Kling / O3 Std", "category": CATEGORY_QUALITY, "recommendation": "O3 架构进阶档。", "supports_audio": True, "supports_high_resolution": False, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "kling_o3_pro": {"model_code": "kling_o3_pro", "label": "Kling O3 Pro", "series": "Kling / O3 Pro", "category": CATEGORY_QUALITY, "recommendation": "O3 顶配档。", "supports_audio": True, "supports_high_resolution": False, "status": VIDEO_STATUS_CONNECTED, "features": {}},
    "kling_o3_reference_std": {"model_code": "kling_o3_reference_std", "label": "Kling O3 Reference Std", "series": "Kling / O3 Std Reference", "category": CATEGORY_CONSISTENCY, "recommendation": "高一致性角色锁定。", "supports_audio": True, "supports_high_resolution": False, "status": VIDEO_STATUS_CONNECTED, "hidden": True, "features": {}},
    "kling_o3_reference_pro": {"model_code": "kling_o3_reference_pro", "label": "Kling O3 Reference Pro", "series": "Kling / O3 Pro Reference", "category": CATEGORY_CONSISTENCY, "recommendation": "高一致性高画质档。", "supports_audio": True, "supports_high_resolution": False, "status": VIDEO_STATUS_CONNECTED, "hidden": True, "features": {}},
}

VEO_LOW_TEXT_FIELDS = _base_fields(_VEO_LOW_DURATIONS, ["720p", "1080p", "4k"])
VEO_LOW_IMAGE_FIELDS = _base_fields(_VEO_LOW_DURATIONS, ["720p", "1080p", "4k"], image_list={"required": True, "min_count": 1, "max_count": 3, "max_file_size_mb": 10})
VEO_START_END_FIELDS = _base_fields(_VEO_LOW_DURATIONS, ["720p", "1080p", "4k"], first_frame={"required": True, "max_file_size_mb": 10}, last_frame={"required": True, "max_file_size_mb": 10})
VEO_OFFICIAL_TEXT_FIELDS = _base_fields(_VEO_OFFICIAL_DURATIONS, ["720p", "1080p", "4k"], audio_enabled=True)
VEO_OFFICIAL_IMAGE_FIELDS = _base_fields(_VEO_OFFICIAL_DURATIONS, ["720p", "1080p", "4k"], first_frame={"required": True, "max_file_size_mb": 10}, last_frame={"required": False, "max_file_size_mb": 10}, audio_enabled=True)
VIDU_Q2_IMAGE_FIELDS = _base_fields(_VIDU_Q2_DURATIONS, ["540p", "720p", "1080p"], image_list={"required": True, "min_count": 1, "max_count": 1, "max_file_size_mb": 50}, motion_strength=True, audio_enabled=True)
VIDU_Q2_REFERENCE_FIELDS = _base_fields(_VIDU_Q2_DURATIONS, ["540p", "720p", "1080p"], image_list={"required": True, "min_count": 1, "max_count": 7, "max_file_size_mb": 50}, video_list={"required": False, "min_count": 0, "max_count": 2, "max_file_size_mb": 100}, motion_strength=True, audio_enabled=True)
VIDU_Q2_START_FIELDS = _base_fields(_VIDU_Q2_START_DURATIONS, ["540p", "720p", "1080p"], first_frame={"required": True, "max_file_size_mb": 50}, last_frame={"required": True, "max_file_size_mb": 50}, motion_strength=True, audio_enabled=True)
VIDU_Q2_FAST_IMAGE_FIELDS = _base_fields(_VIDU_Q2_DURATIONS, ["540p", "720p", "1080p"], image_list={"required": True, "min_count": 1, "max_count": 1, "max_file_size_mb": 50})
VIDU_Q2_FAST_START_FIELDS = _base_fields(_VIDU_Q2_START_DURATIONS, ["720p", "1080p"], first_frame={"required": True, "max_file_size_mb": 50}, last_frame={"required": True, "max_file_size_mb": 50})
VIDU_Q3_TEXT_FIELDS = _base_fields(_VIDU_Q3_DURATIONS, ["360p", "540p", "720p", "1080p"], audio_enabled=True)
VIDU_Q3_IMAGE_FIELDS = _base_fields(_VIDU_Q3_DURATIONS, ["360p", "540p", "720p", "1080p", "2k"], image_list={"required": True, "min_count": 1, "max_count": 1, "max_file_size_mb": 50}, audio_enabled=True)
VIDU_Q3_START_FIELDS = _base_fields(_VIDU_Q3_DURATIONS, ["540p", "720p", "1080p"], first_frame={"required": True, "max_file_size_mb": 50}, last_frame={"required": True, "max_file_size_mb": 50}, audio_enabled=True)
VIDU_Q3_TURBO_TEXT_FIELDS = _base_fields(_VIDU_Q3_DURATIONS, ["540p", "720p", "1080p"])
VIDU_Q3_TURBO_IMAGE_FIELDS = _base_fields(_VIDU_Q3_DURATIONS, ["540p", "720p", "1080p"], image_list={"required": True, "min_count": 1, "max_count": 1, "max_file_size_mb": 50})
SEEDANCE_V15_TEXT_FIELDS = _base_fields(_SEEDANCE_V15_DURATIONS, ["480p", "720p", "1080p"], audio_enabled=True, camera_fixed=True)
SEEDANCE_V15_IMAGE_FIELDS = _base_fields(_SEEDANCE_V15_DURATIONS, ["480p", "720p", "1080p"], first_frame={"required": True, "max_file_size_mb": 10}, last_frame={"required": False, "max_file_size_mb": 10}, audio_enabled=True, camera_fixed=True)
SEEDANCE_V15_FAST_TEXT_FIELDS = _base_fields(_SEEDANCE_V15_DURATIONS, ["720p", "1080p"], audio_enabled=True, camera_fixed=True)
SEEDANCE_V15_FAST_IMAGE_FIELDS = _base_fields(_SEEDANCE_V15_DURATIONS, ["720p", "1080p"], first_frame={"required": True, "max_file_size_mb": 10}, last_frame={"required": False, "max_file_size_mb": 10}, audio_enabled=True, camera_fixed=True)
SEEDANCE_20_TEXT_FIELDS = _base_fields(_SEEDANCE_20_DURATIONS, ["480p", "720p", "1080p", "2k", "4k"], audio_enabled=True, web_search=True)
SEEDANCE_20_IMAGE_FIELDS = _base_fields(_SEEDANCE_20_DURATIONS, ["480p", "720p", "1080p", "2k", "4k"], first_frame={"required": True, "max_file_size_mb": 30}, last_frame={"required": False, "max_file_size_mb": 30}, audio_enabled=True, real_person_mode=True)
SEEDANCE_20_REFERENCE_FIELDS = _base_fields(_SEEDANCE_20_DURATIONS, ["480p", "720p", "1080p", "2k", "4k"], image_list={"required": False, "min_count": 0, "max_count": 9, "max_file_size_mb": 30}, video_list={"required": False, "min_count": 0, "max_count": 3, "max_file_size_mb": 50, "help_text": "仅支持平台上传的临时参考视频。"}, audio_list={"required": False, "min_count": 0, "max_count": 3, "max_file_size_mb": 50, "help_text": "仅支持平台上传的临时参考音频，且必须搭配参考图或参考视频。"}, audio_enabled=True, real_person_mode=True)
KLING_O1_TEXT_FIELDS = _base_fields([5, 10], ["720p"], quality_mode=True)
KLING_O1_IMAGE_FIELDS = _base_fields([5, 10], ["720p"], first_frame={"required": True, "max_file_size_mb": 20}, quality_mode=True)
KLING_O1_START_FIELDS = _base_fields([5, 10], ["720p"], first_frame={"required": True, "max_file_size_mb": 20}, last_frame={"required": True, "max_file_size_mb": 20}, quality_mode=True)
KLING_O1_REFERENCE_FIELDS = _base_fields([5, 10], ["720p"], image_list={"required": False, "min_count": 0, "max_count": 7, "max_file_size_mb": 20}, video_list={"required": True, "min_count": 1, "max_count": 1, "max_file_size_mb": 10}, quality_mode=True, audio_enabled=True)
KLING_30_TEXT_FIELDS = _base_fields(_KLING_DURATIONS, ["720p"], audio_enabled=True)
KLING_30_IMAGE_FIELDS = _base_fields(_KLING_DURATIONS, ["720p"], first_frame={"required": True, "max_file_size_mb": 50}, last_frame={"required": False, "max_file_size_mb": 50}, audio_enabled=True)
KLING_O3_TEXT_FIELDS = _base_fields(_KLING_DURATIONS, ["720p"], audio_enabled=True)
KLING_O3_IMAGE_FIELDS = _base_fields(_KLING_DURATIONS, ["720p"], first_frame={"required": True, "max_file_size_mb": 50}, last_frame={"required": False, "max_file_size_mb": 50}, audio_enabled=True)
KLING_O3_REFERENCE_FIELDS = _base_fields(_KLING_DURATIONS, ["720p"], image_list={"required": False, "min_count": 0, "max_count": 7, "max_file_size_mb": 50}, video_list={"required": False, "min_count": 0, "max_count": 1, "max_file_size_mb": 50}, audio_enabled=True)

VIDEO_MODEL_REGISTRY["veo_31_fast"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/rhart-video-v3.1-fast/text-to-video", "submit_type": "veo_text", "defaults": {"duration": 8, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VEO_LOW_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_cost_map(_VEO_FAST_LOW, "Veo 3.1 Fast 文生", duration=8), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/rhart-video-v3.1-fast/image-to-video", "submit_type": "veo_image", "defaults": {"duration": 8, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VEO_LOW_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_cost_map(_VEO_FAST_LOW, "Veo 3.1 Fast 图生", duration=8), "note": "", "connection_status": "connected"},
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/rhart-video-v3.1-fast/image-to-video", "submit_type": "veo_reference", "defaults": {"duration": 8, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VEO_LOW_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_cost_map(_VEO_FAST_LOW, "Veo 3.1 Fast 参考生", duration=8), "note": "", "connection_status": "connected"},
    GEN_START_END: {"generation_type": GEN_START_END, "generation_type_label": GENERATION_TYPE_LABELS[GEN_START_END], "endpoint": "/rhart-video-v3.1-fast/start-end-to-video", "submit_type": "veo_start_end", "defaults": {"duration": 8, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VEO_START_END_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_cost_map(_VEO_FAST_LOW, "Veo 3.1 Fast 首尾帧", duration=8), "note": "", "connection_status": "connected"},
}
VIDEO_MODEL_REGISTRY["veo_31_pro"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/rhart-video-v3.1-pro/text-to-video", "submit_type": "veo_text", "defaults": {"duration": 8, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VEO_LOW_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_cost_map(_VEO_PRO_LOW, "Veo 3.1 Pro 文生", duration=8), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/rhart-video-v3.1-pro/image-to-video", "submit_type": "veo_image", "defaults": {"duration": 8, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VEO_LOW_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_cost_map(_VEO_PRO_LOW, "Veo 3.1 Pro 图生", duration=8), "note": "", "connection_status": "connected"},
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/rhart-video-v3.1-pro/image-to-video", "submit_type": "veo_reference", "defaults": {"duration": 8, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VEO_LOW_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_cost_map(_VEO_PRO_LOW, "Veo 3.1 Pro 参考生", duration=8), "note": "", "connection_status": "connected"},
    GEN_START_END: {"generation_type": GEN_START_END, "generation_type_label": GENERATION_TYPE_LABELS[GEN_START_END], "endpoint": "/rhart-video-v3.1-pro/start-end-to-video", "submit_type": "veo_start_end", "defaults": {"duration": 8, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VEO_START_END_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_cost_map(_VEO_PRO_LOW, "Veo 3.1 Pro 首尾帧", duration=8), "note": "", "connection_status": "connected"},
}


def get_video_model_or_none(model_code: Optional[str]) -> Optional[VideoModelConfig]:
    if not model_code:
        return None
    return VIDEO_MODEL_REGISTRY.get(str(model_code).strip().lower())


def default_generation_type(model_code: str) -> Optional[str]:
    model = get_video_model_or_none(model_code)
    if not model:
        return None
    for key in [GEN_TEXT, GEN_IMAGE, GEN_REFERENCE, GEN_START_END]:
        if key in model.get("features", {}):
            return key
    return None


def get_video_model_or_error(model_code: Optional[str]) -> VideoModelConfig:
    model = get_video_model_or_none(model_code)
    if model and model.get("status") == VIDEO_STATUS_CONNECTED:
        return model
    raise ValueError("invalid_model")


def _field_by_key(feature: VideoFeatureConfig, key: str) -> Optional[VideoFieldConfig]:
    for field in feature.get("fields", []):
        if field.get("key") == key:
            return field
    return None


def _field_values(field: Optional[VideoFieldConfig]) -> List[str]:
    return [str(item.get("value") or "").strip() for item in (field or {}).get("options", []) if str(item.get("value") or "").strip()]


def _normalize_reference_entries(entries: Any, *, media_type: str) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    seen: set[str] = set()
    default_label_prefix = {"image": "参考图", "video": "参考视频", "audio": "参考音频"}.get(media_type, "参考素材")

    for index, raw in enumerate(entries or [], start=1):
        if not isinstance(raw, dict):
            continue
        url = str(raw.get("url") or raw.get("file_url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        label = str(raw.get("label") or raw.get("name") or raw.get("title") or f"{default_label_prefix}{index}").strip()
        item = {"url": url, "label": label}
        if media_type == "image":
            role = str(raw.get("role") or "").strip().lower() or "auxiliary"
            item["role"] = role if role in SEEDANCE_IMAGE_REF_ROLES else "auxiliary"
        normalized.append(item)
    return normalized


def _sort_seedance_image_ref_entries(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(
        entries,
        key=lambda item: (
            SEEDANCE_IMAGE_REF_ROLE_ORDER.get(str(item.get("role") or "auxiliary"), SEEDANCE_IMAGE_REF_ROLE_ORDER["auxiliary"]),
        ),
    )


def normalize_video_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    model_code = str(payload.get("model_code") or payload.get("model") or "").strip().lower()
    model = get_video_model_or_error(model_code)
    generation_type = str(payload.get("generation_type") or "").strip().lower() or default_generation_type(model_code)
    feature = model["features"].get(generation_type)
    if not feature:
        raise ValueError("invalid_generation_type")
    defaults = feature.get("defaults", {})
    duration = int(payload.get("duration") or defaults.get("duration") or 0)
    duration_values = [int(v) for v in _field_values(_field_by_key(feature, "duration"))]
    if duration_values and duration not in duration_values:
        raise ValueError("duration")
    resolution = str(payload.get("resolution") or defaults.get("resolution") or "").strip().lower()
    if resolution and _field_values(_field_by_key(feature, "resolution")) and resolution not in _field_values(_field_by_key(feature, "resolution")):
        raise ValueError("resolution")
    aspect_ratio = str(payload.get("aspect_ratio") or defaults.get("aspect_ratio") or "16:9").strip()
    if aspect_ratio and _field_values(_field_by_key(feature, "aspect_ratio")) and aspect_ratio not in _field_values(_field_by_key(feature, "aspect_ratio")):
        raise ValueError("aspect_ratio")
    quality_mode = str(payload.get("quality_mode") or defaults.get("quality_mode") or "").strip().lower() or None
    if quality_mode and _field_values(_field_by_key(feature, "quality_mode")) and quality_mode not in _field_values(_field_by_key(feature, "quality_mode")):
        raise ValueError("quality_mode")
    motion_strength = str(payload.get("motion_strength") or defaults.get("motion_strength") or "").strip().lower() or None
    if motion_strength and _field_values(_field_by_key(feature, "motion_strength")) and motion_strength not in _field_values(_field_by_key(feature, "motion_strength")):
        raise ValueError("motion_strength")
    image_ref_entries = _sort_seedance_image_ref_entries(
        _normalize_reference_entries(payload.get("image_ref_entries"), media_type="image")
    )
    video_ref_entries = _normalize_reference_entries(payload.get("video_ref_entries"), media_type="video")
    audio_ref_entries = _normalize_reference_entries(payload.get("audio_ref_entries"), media_type="audio")
    image_refs = (
        [str(item.get("url") or "").strip() for item in image_ref_entries if str(item.get("url") or "").strip()]
        if image_ref_entries
        else [str(item).strip() for item in (payload.get("image_refs") or payload.get("reference_images") or []) if str(item).strip()]
    )
    video_refs = (
        [str(item.get("url") or "").strip() for item in video_ref_entries if str(item.get("url") or "").strip()]
        if video_ref_entries
        else [str(item).strip() for item in (payload.get("video_refs") or payload.get("reference_videos") or []) if str(item).strip()]
    )
    audio_refs = (
        [str(item.get("url") or "").strip() for item in audio_ref_entries if str(item.get("url") or "").strip()]
        if audio_ref_entries
        else [str(item).strip() for item in (payload.get("audio_refs") or []) if str(item).strip()]
    )
    first_frame = str(payload.get("first_frame") or payload.get("start_frame") or "").strip()
    last_frame = str(payload.get("last_frame") or payload.get("end_frame") or "").strip()
    audio_enabled = bool(payload.get("audio_enabled", payload.get("audio", defaults.get("audio_enabled", False))))
    camera_fixed = bool(payload.get("camera_fixed", defaults.get("camera_fixed", False)))
    real_person_mode = bool(payload.get("real_person_mode", defaults.get("real_person_mode", False)))
    web_search = bool(payload.get("web_search", defaults.get("web_search", False)))
    audio_url = str(payload.get("audio_url") or "").strip()
    input_video_duration = int(payload.get("input_video_duration") or 0)
    image_field = _field_by_key(feature, "image_refs")
    if image_field:
        if image_field.get("required") and len(image_refs) < int(image_field.get("min_count") or 1):
            raise ValueError("image_refs")
        if image_field.get("max_count") and len(image_refs) > int(image_field["max_count"]):
            raise ValueError("image_refs")
    video_field = _field_by_key(feature, "video_refs")
    if video_field:
        if video_field.get("required") and len(video_refs) < int(video_field.get("min_count") or 1):
            raise ValueError("video_refs")
        if video_field.get("max_count") and len(video_refs) > int(video_field["max_count"]):
            raise ValueError("video_refs")
    audio_field = _field_by_key(feature, "audio_refs")
    if audio_field:
        if audio_field.get("required") and len(audio_refs) < int(audio_field.get("min_count") or 1):
            raise ValueError("audio_refs")
        if audio_field.get("max_count") and len(audio_refs) > int(audio_field["max_count"]):
            raise ValueError("audio_refs")
    first_field = _field_by_key(feature, "first_frame")
    if first_field and first_field.get("required") and not first_frame and not image_refs:
        raise ValueError("first_frame")
    last_field = _field_by_key(feature, "last_frame")
    if last_field and last_field.get("required") and not last_frame:
        raise ValueError("last_frame")
    if generation_type == GEN_REFERENCE and model_code in {"seedance_20_fast", "seedance_20"} and not image_refs and not video_refs and not audio_refs and not audio_url:
        raise ValueError("reference_assets")
    if generation_type == GEN_REFERENCE and model_code in {"kling_o3_reference_std", "kling_o3_reference_pro", "kling_o3_std", "kling_o3_pro"} and not image_refs and not video_refs:
        raise ValueError("reference_assets")
    return {
        "model_code": model_code,
        "model_name": model["label"],
        "series": model["series"],
        "generation_type": generation_type,
        "generation_type_label": feature["generation_type_label"],
        "prompt": str(payload.get("prompt") or "").strip(),
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "image_refs": image_refs,
        "video_refs": video_refs,
        "audio_refs": audio_refs,
        "image_ref_entries": image_ref_entries,
        "video_ref_entries": video_ref_entries,
        "audio_ref_entries": audio_ref_entries,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "audio_enabled": audio_enabled,
        "camera_fixed": camera_fixed,
        "real_person_mode": real_person_mode,
        "web_search": web_search,
        "quality_mode": quality_mode,
        "motion_strength": motion_strength,
        "audio_url": audio_url,
        "input_video_duration": input_video_duration,
        "pricing_rule_type": feature["pricing_rule_type"],
    }


def list_supported_video_models() -> List[VideoModelConfig]:
    return [item for item in VIDEO_MODEL_REGISTRY.values() if item["status"] == VIDEO_STATUS_CONNECTED]


def _match_fixed_rule(rule: VideoPricingRule, normalized: Dict[str, Any]) -> bool:
    for key in ("resolution", "duration", "audio_enabled", "quality_mode", "has_video_ref"):
        if key in rule and rule.get(key) != normalized.get(key):
            return False
    return True


def _estimate_fixed_table(feature: VideoFeatureConfig, normalized: Dict[str, Any]) -> Optional[VideoPricingEstimateResult]:
    for rule in feature["pricing_rules"]:
        if _match_fixed_rule(rule, normalized):
            return {
                "pricing_rule_type": PRICING_RULE_FIXED_TABLE,
                "cost_price": float(rule["cost_price"]),
                "suggested_price": float(rule["suggested_price"]),
                "sell_price_points": int(rule["sell_price_points"]),
                "pricing_note": str(rule["pricing_note"]),
                "pricing_details": {"matched_rule": dict(rule), "rule_type": PRICING_RULE_FIXED_TABLE},
            }
    return None


def _estimate_per_second(feature: VideoFeatureConfig, normalized: Dict[str, Any]) -> Optional[VideoPricingEstimateResult]:
    unit_rule = None
    for rule in feature["pricing_rules"]:
        if rule.get("component") != "unit":
            continue
        if "resolution" in rule and rule["resolution"] != normalized.get("resolution"):
            continue
        if "audio_enabled" in rule and rule["audio_enabled"] != normalized.get("audio_enabled"):
            continue
        unit_rule = rule
        break
    if not unit_rule:
        return None
    duration = int(normalized["duration"])
    total_cost = round(float(unit_rule["cost_price"]) * duration, 2)
    total_suggested, total_points = _sell_values(total_cost)
    return {
        "pricing_rule_type": PRICING_RULE_PER_SECOND,
        "cost_price": total_cost,
        "suggested_price": total_suggested,
        "sell_price_points": total_points,
        "pricing_note": f"{unit_rule['pricing_note']} · {duration}秒",
        "pricing_details": {
            "rule_type": PRICING_RULE_PER_SECOND,
            "duration": duration,
            "unit_cost_price": float(unit_rule["cost_price"]),
            "unit_suggested_price": float(unit_rule["suggested_price"]),
            "unit_sell_price_points": int(unit_rule["sell_price_points"]),
            "total_cost_price": total_cost,
        },
    }


def _estimate_per_second_with_addon(feature: VideoFeatureConfig, normalized: Dict[str, Any]) -> Optional[VideoPricingEstimateResult]:
    has_video_ref = bool(normalized.get("video_refs"))
    base_rule = None
    addon_rule = None
    for rule in feature["pricing_rules"]:
        if rule.get("component") == "base" and rule.get("audio_enabled") == normalized.get("audio_enabled"):
            base_rule = rule
        if rule.get("component") == "addon" and has_video_ref:
            addon_rule = rule
    if not base_rule:
        return None
    duration = int(normalized["duration"])
    total_cost = round(float(base_rule["cost_price"]) * duration, 2)
    if addon_rule:
        total_cost = round(total_cost + float(addon_rule["cost_price"]) * duration, 2)
    total_suggested, total_points = _sell_values(total_cost)
    return {
        "pricing_rule_type": PRICING_RULE_PER_SECOND_WITH_ADDON,
        "cost_price": total_cost,
        "suggested_price": total_suggested,
        "sell_price_points": total_points,
        "pricing_note": f"{base_rule['pricing_note']} · {duration}秒" + (f" · 附加 {addon_rule['sell_price_points']} 灵感值/秒" if addon_rule else ""),
        "pricing_details": {
            "rule_type": PRICING_RULE_PER_SECOND_WITH_ADDON,
            "duration": duration,
            "has_video_ref": has_video_ref,
            "base_rule": dict(base_rule),
            "addon_rule": dict(addon_rule) if addon_rule else None,
        },
    }


def _estimate_multimodal(feature: VideoFeatureConfig, normalized: Dict[str, Any]) -> Optional[VideoPricingEstimateResult]:
    resolution = str(normalized.get("resolution") or "").strip().lower()
    has_video_ref = bool(normalized.get("video_refs"))
    base_rule = None
    addon_rule = None
    for rule in feature["pricing_rules"]:
        if rule.get("resolution") != resolution or rule.get("has_video_ref") != has_video_ref:
            continue
        if rule.get("component") == "base":
            base_rule = rule
        elif rule.get("component") == "addon":
            addon_rule = rule
    if not base_rule:
        return None
    output_duration = int(normalized["duration"])
    input_video_duration = int(normalized.get("input_video_duration") or 0)
    bill_seconds = output_duration
    if has_video_ref:
        min_bill = SEEDANCE_20_MIN_BILL_SECONDS.get(output_duration)
        if min_bill is None:
            return None
        bill_seconds = max(input_video_duration + output_duration, min_bill)
    total_cost = round(float(base_rule["cost_price"]) * bill_seconds, 2)
    if addon_rule:
        total_cost = round(total_cost + float(addon_rule["cost_price"]) * output_duration, 2)
    total_suggested, total_points = _sell_values(total_cost)
    return {
        "pricing_rule_type": PRICING_RULE_MULTIMODAL_MIN_BILL,
        "cost_price": total_cost,
        "suggested_price": total_suggested,
        "sell_price_points": total_points,
        "pricing_note": f"{base_rule['pricing_note']} · 输出 {output_duration}秒 · 计费秒数 {bill_seconds}",
        "pricing_details": {
            "rule_type": PRICING_RULE_MULTIMODAL_MIN_BILL,
            "output_duration": output_duration,
            "input_video_duration": input_video_duration,
            "bill_seconds": bill_seconds,
            "base_rule": dict(base_rule),
            "addon_rule": dict(addon_rule) if addon_rule else None,
            "min_bill_seconds_map": dict(SEEDANCE_20_MIN_BILL_SECONDS),
        },
    }


def estimate_video_price(model_code: str, generation_type: str, normalized: Dict[str, Any]) -> Optional[VideoPricingEstimateResult]:
    model = get_video_model_or_none(model_code)
    if not model:
        return None
    feature = model["features"].get(generation_type)
    if not feature:
        return None
    rule_type = feature["pricing_rule_type"]
    if rule_type == PRICING_RULE_FIXED_TABLE:
        return _estimate_fixed_table(feature, normalized)
    if rule_type == PRICING_RULE_PER_SECOND:
        return _estimate_per_second(feature, normalized)
    if rule_type == PRICING_RULE_PER_SECOND_WITH_ADDON:
        return _estimate_per_second_with_addon(feature, normalized)
    if rule_type == PRICING_RULE_MULTIMODAL_MIN_BILL:
        return _estimate_multimodal(feature, normalized)
    return None


def _feature_start_points(feature: VideoFeatureConfig) -> Optional[int]:
    rules = feature.get("pricing_rules", [])
    if not rules:
        return None
    if feature["pricing_rule_type"] == PRICING_RULE_FIXED_TABLE:
        return min(int(item["sell_price_points"]) for item in rules)
    duration_values = [int(v) for v in _field_values(_field_by_key(feature, "duration"))]
    min_duration = min(duration_values) if duration_values else 1
    unit_points = min(int(item["sell_price_points"]) for item in rules if item.get("component") != "addon")
    return unit_points * min_duration


def build_video_catalog() -> Dict[str, Any]:
    categories: List[Dict[str, Any]] = []
    items: List[Dict[str, Any]] = []
    for model in VIDEO_MODEL_REGISTRY.values():
        features = []
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
                "hidden": bool(model.get("hidden")),
                "model_code": model["model_code"],
                "model_name": model["label"],
                "series": model["series"],
                "category": model["category"],
                "category_label": CATEGORY_LABELS[model["category"]],
                "recommendation": model["recommendation"],
                "supports_audio": model["supports_audio"],
                "supports_high_resolution": model["supports_high_resolution"],
                "status": model["status"],
                "start_points": start_points,
                "default_generation_type": default_generation_type(model["model_code"]),
                "feature_tags": [item["generation_type_label"] for item in features],
                "features": features,
            }
        )
    for category in [CATEGORY_SPEED, CATEGORY_QUALITY, CATEGORY_CONSISTENCY, CATEGORY_CONTROL]:
        categories.append({"code": category, "label": CATEGORY_LABELS[category], "models": [item for item in items if item["category"] == category and item["status"] == VIDEO_STATUS_CONNECTED]})
    return {"categories": categories, "models": [item for item in items if not item.get("hidden")]}


VIDEO_MODEL_REGISTRY["veo_31_fast_official"]["features"] = {
    generation_type: {
        "generation_type": generation_type,
        "generation_type_label": GENERATION_TYPE_LABELS[generation_type],
        "endpoint": endpoint,
        "submit_type": submit_type,
        "defaults": {"duration": 4, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False},
        "fields": VEO_OFFICIAL_TEXT_FIELDS if generation_type == GEN_TEXT else VEO_OFFICIAL_IMAGE_FIELDS,
        "pricing_rule_type": PRICING_RULE_FIXED_TABLE,
        "pricing_rules": [
            rule
            for duration, audio_map in _VEO_FAST_OFFICIAL.items()
            for audio_enabled, cost in audio_map.items()
            for rule in _build_fixed_cost_map({"720p": cost, "1080p": cost, "4k": cost}, "Veo 3.1 Fast Official 文生" if generation_type == GEN_TEXT else "Veo 3.1 Fast Official 图生", duration=duration, audio_enabled=audio_enabled)
        ],
        "note": "",
        "connection_status": "connected",
    }
    for generation_type, endpoint, submit_type in [
        (GEN_TEXT, "/rhart-video-v3.1-fast-official/text-to-video", "veo_official_text"),
        (GEN_IMAGE, "/rhart-video-v3.1-fast-official/image-to-video", "veo_official_image"),
    ]
}

VIDEO_MODEL_REGISTRY["veo_31_pro_official"]["features"] = {
    generation_type: {
        "generation_type": generation_type,
        "generation_type_label": GENERATION_TYPE_LABELS[generation_type],
        "endpoint": endpoint,
        "submit_type": submit_type,
        "defaults": {"duration": 4, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False},
        "fields": VEO_OFFICIAL_TEXT_FIELDS if generation_type == GEN_TEXT else VEO_OFFICIAL_IMAGE_FIELDS,
        "pricing_rule_type": PRICING_RULE_FIXED_TABLE,
        "pricing_rules": [
            rule
            for duration, audio_map in _VEO_PRO_OFFICIAL.items()
            for audio_enabled, cost in audio_map.items()
            for rule in _build_fixed_cost_map({"720p": cost, "1080p": cost, "4k": cost}, "Veo 3.1 Pro Official 文生" if generation_type == GEN_TEXT else "Veo 3.1 Pro Official 图生", duration=duration, audio_enabled=audio_enabled)
        ],
        "note": "",
        "connection_status": "connected",
    }
    for generation_type, endpoint, submit_type in [
        (GEN_TEXT, "/rhart-video-v3.1-pro-official/text-to-video", "veo_official_text"),
        (GEN_IMAGE, "/rhart-video-v3.1-pro-official/image-to-video", "veo_official_image"),
    ]
}

VIDEO_MODEL_REGISTRY["vidu_q2_pro"]["features"] = {
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/vidu/image-to-video-q2-pro", "submit_type": "vidu_q2_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "motion_strength": "auto", "audio_enabled": False}, "fields": VIDU_Q2_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_duration_map(_VIDU_Q2, "Vidu Q2 Pro 图生"), "note": "", "connection_status": "connected"},
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/vidu/reference-to-video-q2-pro", "submit_type": "vidu_q2_reference", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "motion_strength": "auto"}, "fields": VIDU_Q2_REFERENCE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_duration_map(_VIDU_Q2_REF, "Vidu Q2 Pro 参考生"), "note": "", "connection_status": "connected"},
    GEN_START_END: {"generation_type": GEN_START_END, "generation_type_label": GENERATION_TYPE_LABELS[GEN_START_END], "endpoint": "/vidu/start-end-to-video-q2-pro", "submit_type": "vidu_q2_start_end", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "motion_strength": "auto", "audio_enabled": False}, "fields": VIDU_Q2_START_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_duration_map(_VIDU_Q2, "Vidu Q2 Pro 首尾帧"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["vidu_q2_pro_fast"]["features"] = {
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/vidu/image-to-video-q2-pro-fast", "submit_type": "vidu_q2_fast_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VIDU_Q2_FAST_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_duration_map(_VIDU_Q2_FAST, "Vidu Q2 Pro Fast 图生"), "note": "", "connection_status": "connected"},
    GEN_START_END: {"generation_type": GEN_START_END, "generation_type_label": GENERATION_TYPE_LABELS[GEN_START_END], "endpoint": "/vidu/start-end-to-video-q2-pro-fast", "submit_type": "vidu_q2_fast_start_end", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VIDU_Q2_FAST_START_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_duration_map(_VIDU_Q2_FAST_START, "Vidu Q2 Pro Fast 首尾帧"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["vidu_q3_pro"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/vidu/text-to-video-q3-pro", "submit_type": "vidu_q3_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": VIDU_Q3_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_per_second(_VIDU_Q3_PRO_TEXT, "Vidu Q3 Pro 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/vidu/image-to-video-q3-pro", "submit_type": "vidu_q3_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": VIDU_Q3_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_per_second(_VIDU_Q3_PRO_IMAGE, "Vidu Q3 Pro 图生"), "note": "", "connection_status": "connected"},
    GEN_START_END: {"generation_type": GEN_START_END, "generation_type_label": GENERATION_TYPE_LABELS[GEN_START_END], "endpoint": "/vidu/start-end-to-video-q3-pro", "submit_type": "vidu_q3_start_end", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": VIDU_Q3_START_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_per_second(_VIDU_Q3_PRO_START, "Vidu Q3 Pro 首尾帧"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["vidu_q3_turbo"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/vidu/text-to-video-q3-turbo", "submit_type": "vidu_q3_turbo_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VIDU_Q3_TURBO_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_rate_map(_VIDU_Q3_TURBO, _VIDU_Q3_DURATIONS, "Vidu Q3 Turbo 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/vidu/image-to-video-q3-turbo", "submit_type": "vidu_q3_turbo_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VIDU_Q3_TURBO_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_rate_map(_VIDU_Q3_TURBO, _VIDU_Q3_DURATIONS, "Vidu Q3 Turbo 图生"), "note": "", "connection_status": "connected"},
    GEN_START_END: {"generation_type": GEN_START_END, "generation_type_label": GENERATION_TYPE_LABELS[GEN_START_END], "endpoint": "/vidu/start-end-to-video-q3-turbo", "submit_type": "vidu_q3_turbo_start_end", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9"}, "fields": VIDU_Q3_START_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_rate_map(_VIDU_Q3_TURBO, _VIDU_Q3_DURATIONS, "Vidu Q3 Turbo 首尾帧"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["seedance_v15_pro"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/seedance-v1.5-pro/text-to-video", "submit_type": "seedance_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False, "camera_fixed": False}, "fields": SEEDANCE_V15_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_audio_rates(_SEEDANCE_V15_PRO, _SEEDANCE_V15_DURATIONS, "Seedance v1.5 Pro 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/seedance-v1.5-pro/image-to-video", "submit_type": "seedance_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False, "camera_fixed": False}, "fields": SEEDANCE_V15_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_audio_rates(_SEEDANCE_V15_PRO, _SEEDANCE_V15_DURATIONS, "Seedance v1.5 Pro 图生"), "note": "", "connection_status": "connected"},
    GEN_START_END: {"generation_type": GEN_START_END, "generation_type_label": GENERATION_TYPE_LABELS[GEN_START_END], "endpoint": "/seedance-v1.5-pro/image-to-video", "submit_type": "seedance_start_end", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False, "camera_fixed": False}, "fields": SEEDANCE_V15_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_audio_rates(_SEEDANCE_V15_PRO, _SEEDANCE_V15_DURATIONS, "Seedance v1.5 Pro 首尾帧"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["seedance_v15_fast"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/seedance-v1.5-pro/text-to-video-fast", "submit_type": "seedance_fast_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False, "camera_fixed": False}, "fields": SEEDANCE_V15_FAST_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_audio_rates(_SEEDANCE_V15_FAST, _SEEDANCE_V15_DURATIONS, "Seedance v1.5 Pro Fast 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/seedance-v1.5-pro/image-to-video-fast", "submit_type": "seedance_fast_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False, "camera_fixed": False}, "fields": SEEDANCE_V15_FAST_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_audio_rates(_SEEDANCE_V15_FAST, _SEEDANCE_V15_DURATIONS, "Seedance v1.5 Pro Fast 图生"), "note": "", "connection_status": "connected"},
    GEN_START_END: {"generation_type": GEN_START_END, "generation_type_label": GENERATION_TYPE_LABELS[GEN_START_END], "endpoint": "/seedance-v1.5-pro/image-to-video-fast", "submit_type": "seedance_fast_start_end", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False, "camera_fixed": False}, "fields": SEEDANCE_V15_FAST_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": _build_fixed_audio_rates(_SEEDANCE_V15_FAST, _SEEDANCE_V15_DURATIONS, "Seedance v1.5 Pro Fast 首尾帧"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["seedance_20_fast"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/rhart-video/sparkvideo-2.0-fast/text-to-video", "submit_type": "seedance20_fast_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "adaptive", "audio_enabled": False, "web_search": False}, "fields": SEEDANCE_20_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_per_second(_SEEDANCE_20_FAST, "Seedance 2.0 Fast 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/rhart-video/sparkvideo-2.0-fast/image-to-video", "submit_type": "seedance20_fast_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False, "real_person_mode": False}, "fields": SEEDANCE_20_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_per_second(_SEEDANCE_20_FAST, "Seedance 2.0 Fast 图生"), "note": "", "connection_status": "connected"},
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/rhart-video/sparkvideo-2.0-fast/multimodal-video", "submit_type": "seedance20_fast_reference", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "adaptive", "audio_enabled": False, "real_person_mode": False}, "fields": SEEDANCE_20_REFERENCE_FIELDS, "pricing_rule_type": PRICING_RULE_MULTIMODAL_MIN_BILL, "pricing_rules": _build_multimodal(_SEEDANCE_20_FAST, _SEEDANCE_20_FAST_BASE, _SEEDANCE_20_ADDON, "Seedance 2.0 Fast 多模态"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["seedance_20"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/rhart-video/sparkvideo-2.0/text-to-video", "submit_type": "seedance20_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "adaptive", "audio_enabled": False, "web_search": False}, "fields": SEEDANCE_20_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_per_second(_SEEDANCE_20, "Seedance 2.0 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/rhart-video/sparkvideo-2.0/image-to-video", "submit_type": "seedance20_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False, "real_person_mode": False}, "fields": SEEDANCE_20_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_per_second(_SEEDANCE_20, "Seedance 2.0 图生"), "note": "", "connection_status": "connected"},
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/rhart-video/sparkvideo-2.0/multimodal-video", "submit_type": "seedance20_reference", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "adaptive", "audio_enabled": False, "real_person_mode": False}, "fields": SEEDANCE_20_REFERENCE_FIELDS, "pricing_rule_type": PRICING_RULE_MULTIMODAL_MIN_BILL, "pricing_rules": _build_multimodal(_SEEDANCE_20, _SEEDANCE_20_BASE, _SEEDANCE_20_ADDON, "Seedance 2.0 多模态"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["kling_o1"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/kling-video-o1/text-to-video", "submit_type": "kling_o1_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "quality_mode": "std"}, "fields": KLING_O1_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": [rule for mode, durations in _KLING_O1.items() for duration, cost in durations.items() for rule in [_fixed_rule(cost, f"Kling o1 文生 · {duration}秒 · {QUALITY_MODE_LABELS[mode]}", duration=duration, resolution="720p", quality_mode=mode)]], "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/kling-video-o1/image-to-video", "submit_type": "kling_o1_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "quality_mode": "std"}, "fields": KLING_O1_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": [rule for mode, durations in _KLING_O1.items() for duration, cost in durations.items() for rule in [_fixed_rule(cost, f"Kling o1 图生 · {duration}秒 · {QUALITY_MODE_LABELS[mode]}", duration=duration, resolution="720p", quality_mode=mode)]], "note": "", "connection_status": "connected"},
    GEN_START_END: {"generation_type": GEN_START_END, "generation_type_label": GENERATION_TYPE_LABELS[GEN_START_END], "endpoint": "/kling-video-o1/start-to-end", "submit_type": "kling_o1_start_end", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "quality_mode": "std"}, "fields": KLING_O1_START_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": [rule for mode, durations in _KLING_O1.items() for duration, cost in durations.items() for rule in [_fixed_rule(cost, f"Kling o1 首尾帧 · {duration}秒 · {QUALITY_MODE_LABELS[mode]}", duration=duration, resolution="720p", quality_mode=mode)]], "note": "", "connection_status": "connected"},
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/kling-video-o1-std/refrence-to-video", "submit_type": "kling_o1_reference", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "quality_mode": "std", "audio_enabled": True}, "fields": KLING_O1_REFERENCE_FIELDS, "pricing_rule_type": PRICING_RULE_FIXED_TABLE, "pricing_rules": [rule for mode, durations in _KLING_O1.items() for duration, cost in durations.items() for rule in [_fixed_rule(cost, f"Kling o1 参考生 · {duration}秒 · {QUALITY_MODE_LABELS[mode]}", duration=duration, resolution="720p", quality_mode=mode, audio_enabled=True)]], "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["kling_30_std"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/kling-v3.0-std/text-to-video", "submit_type": "kling30_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_30_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_audio_per_second(0.52, 0.78, "Kling 3.0 Std 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/kling-v3.0-std/image-to-video", "submit_type": "kling30_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_30_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_audio_per_second(0.52, 0.78, "Kling 3.0 Std 图生"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["kling_30_pro"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/kling-v3.0-pro/text-to-video", "submit_type": "kling30_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_30_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_audio_per_second(0.69, 1.04, "Kling 3.0 Pro 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/kling-v3.0-pro/image-to-video", "submit_type": "kling30_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_30_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_audio_per_second(0.69, 1.04, "Kling 3.0 Pro 图生"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["kling_o3_std"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/kling-video-o3-std/text-to-video", "submit_type": "kling_o3_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_O3_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_audio_per_second(0.52, 0.69, "Kling O3 Std 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/kling-video-o3-std/image-to-video", "submit_type": "kling_o3_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_O3_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_audio_per_second(0.52, 0.69, "Kling O3 Std 图生"), "note": "", "connection_status": "connected"},
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/kling-video-o3-std/reference-to-video", "submit_type": "kling_o3_reference", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_O3_REFERENCE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND_WITH_ADDON, "pricing_rules": _build_ref_addon(0.54, 0.72, 0.27, "Kling O3 Std 参考生"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["kling_o3_pro"]["features"] = {
    GEN_TEXT: {"generation_type": GEN_TEXT, "generation_type_label": GENERATION_TYPE_LABELS[GEN_TEXT], "endpoint": "/kling-video-o3-pro/text-to-video", "submit_type": "kling_o3_text", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_O3_TEXT_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_audio_per_second(0.69, 0.87, "Kling O3 Pro 文生"), "note": "", "connection_status": "connected"},
    GEN_IMAGE: {"generation_type": GEN_IMAGE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_IMAGE], "endpoint": "/kling-video-o3-pro/image-to-video", "submit_type": "kling_o3_image", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_O3_IMAGE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND, "pricing_rules": _build_audio_per_second(0.69, 0.87, "Kling O3 Pro 图生"), "note": "", "connection_status": "connected"},
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/kling-video-o3-pro/reference-to-video", "submit_type": "kling_o3_reference", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_O3_REFERENCE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND_WITH_ADDON, "pricing_rules": _build_ref_addon(0.72, 0.90, 0.36, "Kling O3 Pro 参考生"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["kling_o3_reference_std"]["features"] = {
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/kling-video-o3-std/reference-to-video", "submit_type": "kling_o3_reference", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_O3_REFERENCE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND_WITH_ADDON, "pricing_rules": _build_ref_addon(0.54, 0.72, 0.27, "Kling O3 Reference Std"), "note": "", "connection_status": "connected"},
}

VIDEO_MODEL_REGISTRY["kling_o3_reference_pro"]["features"] = {
    GEN_REFERENCE: {"generation_type": GEN_REFERENCE, "generation_type_label": GENERATION_TYPE_LABELS[GEN_REFERENCE], "endpoint": "/kling-video-o3-pro/reference-to-video", "submit_type": "kling_o3_reference", "defaults": {"duration": 5, "resolution": "720p", "aspect_ratio": "16:9", "audio_enabled": False}, "fields": KLING_O3_REFERENCE_FIELDS, "pricing_rule_type": PRICING_RULE_PER_SECOND_WITH_ADDON, "pricing_rules": _build_ref_addon(0.72, 0.90, 0.36, "Kling O3 Reference Pro"), "note": "", "connection_status": "connected"},
}

