from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional

ABILITY_REALTIME = "realtime_dubbing"
ABILITY_NARRATION = "long_narration"
ABILITY_VOICE_DESIGN = "voice_design"
ABILITY_VOICE_CLONE = "voice_clone"
ABILITY_VOICE_MANAGEMENT = "voice_management"

ABILITY_LABELS = {
    ABILITY_REALTIME: "实时配音",
    ABILITY_NARRATION: "长文本旁白",
    ABILITY_VOICE_DESIGN: "音色设计",
    ABILITY_VOICE_CLONE: "快速复刻",
    ABILITY_VOICE_MANAGEMENT: "音色管理",
}

TIER_HD = "hd"
TIER_TURBO = "turbo"
TIER_DESIGN = "design"
TIER_CLONE = "clone"
TIER_MANAGE = "manage"

TIER_LABELS = {
    TIER_HD: "高保真",
    TIER_TURBO: "极速版",
    TIER_DESIGN: "自定义音色设计",
    TIER_CLONE: "自定义音色复刻",
    TIER_MANAGE: "查询 / 删除",
}

VOICE_SOURCE_SYSTEM = "system"
VOICE_SOURCE_CUSTOM = "custom"
VOICE_SOURCE_NEW_DESIGN = "new_design"
VOICE_SOURCE_NEW_CLONE = "new_clone"

VOICE_SOURCE_LABELS = {
    VOICE_SOURCE_SYSTEM: "系统音色",
    VOICE_SOURCE_CUSTOM: "已有自定义音色",
    VOICE_SOURCE_NEW_DESIGN: "新建设计音色",
    VOICE_SOURCE_NEW_CLONE: "新建复刻音色",
}

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_EXPIRED = "expired"

PREVIEW_MODE = "preview"
GENERATE_MODE = "generate"

MINIMAX_MODEL_HD = "speech-2.8-hd"
MINIMAX_MODEL_TURBO = "speech-2.8-turbo"
MINIMAX_PREVIEW_MODEL_HD = MINIMAX_MODEL_HD
MINIMAX_PREVIEW_MODEL_TURBO = MINIMAX_MODEL_TURBO
MINIMAX_SPEECH_TAG_MODELS = {MINIMAX_MODEL_HD, MINIMAX_MODEL_TURBO}

MINIMAX_SPEECH_TAG_OPTIONS = [
    {"value": "(laughs)", "label": "笑声", "alias": ["笑声"]},
    {"value": "(chuckle)", "label": "轻笑", "alias": ["轻笑"]},
    {"value": "(coughs)", "label": "咳嗽", "alias": ["咳嗽"]},
    {"value": "(clear-throat)", "label": "清嗓子", "alias": ["清嗓子", "清嗓"]},
    {"value": "(groans)", "label": "呻吟", "alias": ["呻吟"]},
    {"value": "(breath)", "label": "正常换气", "alias": ["正常换气", "换气"]},
    {"value": "(pant)", "label": "喘气", "alias": ["喘气"]},
    {"value": "(inhale)", "label": "吸气", "alias": ["吸气"]},
    {"value": "(exhale)", "label": "呼气", "alias": ["呼气"]},
    {"value": "(gasps)", "label": "倒吸气", "alias": ["倒吸气"]},
    {"value": "(sniffs)", "label": "吸鼻子", "alias": ["吸鼻子"]},
    {"value": "(sighs)", "label": "叹气", "alias": ["叹气"]},
    {"value": "(snorts)", "label": "喷鼻息", "alias": ["喷鼻息"]},
    {"value": "(burps)", "label": "打嗝", "alias": ["打嗝"]},
    {"value": "(lip-smacking)", "label": "咂嘴", "alias": ["咂嘴"]},
    {"value": "(humming)", "label": "哼唱", "alias": ["哼唱"]},
    {"value": "(hissing)", "label": "嘶嘶声", "alias": ["嘶嘶声"]},
    {"value": "(emm)", "label": "嗯", "alias": ["嗯", "嗯声"]},
    {"value": "(whistles)", "label": "口哨", "alias": ["口哨"]},
    {"value": "(sneezes)", "label": "喷嚏", "alias": ["喷嚏", "打喷嚏"]},
    {"value": "(crying)", "label": "抽泣", "alias": ["抽泣"]},
    {"value": "(applause)", "label": "鼓掌", "alias": ["鼓掌"]},
]
MINIMAX_PAUSE_TAG_OPTIONS = [
    {"value": "<#0.25#>", "label": "0.25s"},
    {"value": "<#0.5#>", "label": "0.5s"},
    {"value": "<#1.0#>", "label": "1.0s"},
    {"value": "<#1.5#>", "label": "1.5s"},
]
_SPEECH_TAG_RE = re.compile(r"[（(]\s*([^)）]{1,32}?)\s*[)）]")
_SPEECH_TAG_ALIASES: Dict[str, str] = {}
for _tag in MINIMAX_SPEECH_TAG_OPTIONS:
    _value = str(_tag["value"])
    _SPEECH_TAG_ALIASES[_value.strip("()").lower()] = _value
    for _alias in _tag.get("alias", []):
        _SPEECH_TAG_ALIASES[str(_alias).strip().lower()] = _value

PRICING_REALTIME_HD = {"cost_price": 3.5, "suggested_price": 5.25, "sell_price_points": 53, "unit": "每万字符"}
PRICING_REALTIME_TURBO = {"cost_price": 2.0, "suggested_price": 3.0, "sell_price_points": 30, "unit": "每万字符"}
PRICING_NARRATION_HD = {"cost_price": 3.5, "suggested_price": 5.25, "sell_price_points": 53, "unit": "每万字符"}
PRICING_NARRATION_TURBO = {"cost_price": 2.0, "suggested_price": 3.0, "sell_price_points": 30, "unit": "每万字符"}
PRICING_VOICE_DESIGN = {"cost_price": 9.9, "suggested_price": 14.85, "sell_price_points": 149, "unit": "每个音色"}
PRICING_VOICE_CLONE = {"cost_price": 9.9, "suggested_price": 14.85, "sell_price_points": 149, "unit": "每个音色"}
PRICING_PREVIEW_HD = {"cost_price": 3.5, "suggested_price": 5.25, "sell_price_points": 53, "unit": "每万字符"}
PRICING_PREVIEW_TURBO = {"cost_price": 2.0, "suggested_price": 3.0, "sell_price_points": 30, "unit": "每万字符"}
PRICING_DESIGN_PREVIEW = {"cost_price": 2.0, "suggested_price": 3.0, "sell_price_points": 30, "unit": "每万字符"}
CHARACTER_BILLING_BASE = 10000

EMOTION_OPTIONS = [
    {"value": "happy", "label": "开心"},
    {"value": "sad", "label": "伤感"},
    {"value": "angry", "label": "愤怒"},
    {"value": "fearful", "label": "害怕"},
    {"value": "disgusted", "label": "厌恶"},
    {"value": "surprised", "label": "惊讶"},
    {"value": "calm", "label": "平静"},
    {"value": "fluent", "label": "流畅"},
    {"value": "whisper", "label": "耳语"},
]
FORMAT_OPTIONS = [{"value": "mp3", "label": "MP3"}, {"value": "wav", "label": "WAV"}]
SAMPLE_RATE_OPTIONS = [{"value": 32000, "label": "32000Hz"}, {"value": 44100, "label": "44100Hz"}]
BITRATE_OPTIONS = [{"value": 128000, "label": "128kbps"}, {"value": 256000, "label": "256kbps"}]
CHANNEL_OPTIONS = [{"value": 1, "label": "单声道"}, {"value": 2, "label": "双声道"}]
LANGUAGE_BOOST_OPTIONS = [
    {"value": "none", "label": "关闭"},
    {"value": "auto", "label": "自动增强"},
]
PREVIEW_TIER_OPTIONS = [
    {"value": TIER_HD, "label": "高保真试听"},
    {"value": TIER_TURBO, "label": "极速试听"},
]


def ceil_points_from_price(price: float) -> int:
    return int(math.ceil(round(float(price or 0), 2) / 0.1))


def calculate_billing_characters(text: str) -> int:
    total = 0
    for char in str(text or ""):
        if "\u4e00" <= char <= "\u9fff":
            total += 2
        else:
            total += 1
    return total


def calculate_unit_count(characters: int) -> int:
    return max(1, int(math.ceil(max(0, int(characters or 0)) / 10000)))


def calculate_chars_per_point(points_per_10k: int) -> float:
    if not points_per_10k:
        return 0.0
    return round(float(CHARACTER_BILLING_BASE) / float(points_per_10k), 2)


def calculate_points_by_characters(characters: int, points_per_10k: int) -> int:
    chars = max(1, int(characters or 0))
    chars_per_point = calculate_chars_per_point(points_per_10k)
    if chars_per_point <= 0:
        return 0
    return max(1, int(math.ceil(float(chars) / chars_per_point)))


def normalize_minimax_speech_tags(text: str, model_code: Optional[str]) -> str:
    source = str(text or "")
    if not source:
        return source
    resolved_model = str(model_code or "").strip()
    found_supported_tag = False

    def _replace(match: re.Match[str]) -> str:
        nonlocal found_supported_tag
        raw_label = match.group(1).strip()
        normalized = _SPEECH_TAG_ALIASES.get(raw_label.lower())
        if not normalized:
            return match.group(0)
        found_supported_tag = True
        return normalized

    normalized_text = _SPEECH_TAG_RE.sub(_replace, source)
    if found_supported_tag and resolved_model not in MINIMAX_SPEECH_TAG_MODELS:
        raise ValueError("unsupported_speech_tag_model")
    return normalized_text


def _copy_pricing(item: Dict[str, Any]) -> Dict[str, Any]:
    return dict(item)


def _field(
    key: str,
    label: str,
    field_type: str,
    *,
    required: bool = False,
    placeholder: str = "",
    help_text: str = "",
    options: Optional[List[Dict[str, Any]]] = None,
    max_file_size_mb: Optional[int] = None,
    accept: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "key": key,
        "label": label,
        "type": field_type,
        "required": required,
    }
    if placeholder:
        payload["placeholder"] = placeholder
    if help_text:
        payload["help_text"] = help_text
    if options:
        payload["options"] = options
    if max_file_size_mb:
        payload["max_file_size_mb"] = max_file_size_mb
    if accept:
        payload["accept"] = accept
    return payload


def _base_tts_fields(*, narration: bool = False) -> List[Dict[str, Any]]:
    fields = [
        _field("script_text", "配音文本", "textarea", required=not narration, placeholder="请输入需要配音的文本"),
        _field("voice_id", "音色选择", "voice_select", required=True),
        _field("emotion", "情绪", "select", options=EMOTION_OPTIONS),
        _field("speed", "语速", "number"),
        _field("volume", "音量", "number"),
        _field("pitch", "音调", "number"),
        _field("audio_format", "输出格式", "select", options=FORMAT_OPTIONS),
        _field("sample_rate", "采样率", "select", options=SAMPLE_RATE_OPTIONS),
        _field("bitrate", "比特率", "select", options=BITRATE_OPTIONS),
        _field("channel_count", "声道", "select", options=CHANNEL_OPTIONS),
    ]
    if narration:
        fields.extend(
            [
                _field("text_file_url", "文本文件", "file", help_text="支持 txt / zip 文本文件，文本直输与文件二选一。", accept=".txt,.zip"),
                _field("language_boost", "语言增强", "select", options=LANGUAGE_BOOST_OPTIONS),
            ]
        )
    else:
        fields.append(_field("subtitle_enabled", "字幕开关", "switch"))
    return fields


AUDIO_ABILITY_REGISTRY: Dict[str, Dict[str, Any]] = {
    ABILITY_REALTIME: {
        "ability_type": ABILITY_REALTIME,
        "label": "实时配音",
        "description": "适合角色台词、短句对白和快速试听。",
        "scene": "角色台词 / 短旁白 / 快速预演",
        "supports_preview": True,
        "is_async": False,
        "tiers": {
            TIER_HD: {
                "tier_code": TIER_HD,
                "tier_label": "高保真",
                "model_code": MINIMAX_MODEL_HD,
                "pricing": _copy_pricing(PRICING_REALTIME_HD),
                "fields": _base_tts_fields(narration=False),
            },
            TIER_TURBO: {
                "tier_code": TIER_TURBO,
                "tier_label": "极速版",
                "model_code": MINIMAX_MODEL_TURBO,
                "pricing": _copy_pricing(PRICING_REALTIME_TURBO),
                "fields": _base_tts_fields(narration=False),
            },
        },
        "default_tier": TIER_HD,
    },
    ABILITY_NARRATION: {
        "ability_type": ABILITY_NARRATION,
        "label": "长文本旁白",
        "description": "适合长章节旁白、有声内容和整段 narration。",
        "scene": "长旁白 / 有声书 / 解说",
        "supports_preview": False,
        "is_async": True,
        "tiers": {
            TIER_HD: {
                "tier_code": TIER_HD,
                "tier_label": "高保真",
                "model_code": MINIMAX_MODEL_HD,
                "pricing": _copy_pricing(PRICING_NARRATION_HD),
                "fields": _base_tts_fields(narration=True),
            },
            TIER_TURBO: {
                "tier_code": TIER_TURBO,
                "tier_label": "极速版",
                "model_code": MINIMAX_MODEL_TURBO,
                "pricing": _copy_pricing(PRICING_NARRATION_TURBO),
                "fields": _base_tts_fields(narration=True),
            },
        },
        "default_tier": TIER_HD,
    },
    ABILITY_VOICE_DESIGN: {
        "ability_type": ABILITY_VOICE_DESIGN,
        "label": "音色设计",
        "description": "通过文字描述生成全新音色并试听。",
        "scene": "角色音色原型 / 品牌声线 / 风格化配音",
        "supports_preview": True,
        "is_async": False,
        "tiers": {
            TIER_DESIGN: {
                "tier_code": TIER_DESIGN,
                "tier_label": "自定义音色设计",
                "model_code": "voice_design",
                "pricing": {
                    "asset": _copy_pricing(PRICING_VOICE_DESIGN),
                    "preview": _copy_pricing(PRICING_DESIGN_PREVIEW),
                },
                "fields": [
                    _field("prompt", "音色描述", "textarea", required=True, placeholder="请输入音色风格描述"),
                    _field("preview_text", "试听文本", "textarea", required=True, placeholder="请输入试听文本"),
                ],
            }
        },
        "default_tier": TIER_DESIGN,
    },
    ABILITY_VOICE_CLONE: {
        "ability_type": ABILITY_VOICE_CLONE,
        "label": "快速复刻",
        "description": "通过参考音频快速复刻自定义音色。",
        "scene": "角色声线复刻 / 真人口播复刻 / 固定角色配音",
        "supports_preview": True,
        "is_async": False,
        "tiers": {
            TIER_CLONE: {
                "tier_code": TIER_CLONE,
                "tier_label": "自定义音色复刻",
                "model_code": "voice_clone",
                "pricing": {
                    "asset": _copy_pricing(PRICING_VOICE_CLONE),
                    "preview_hd": _copy_pricing(PRICING_PREVIEW_HD),
                    "preview_turbo": _copy_pricing(PRICING_PREVIEW_TURBO),
                },
                "fields": [
                    _field("clone_reference_file", "参考音频", "file", required=True, help_text="支持 mp3 / m4a / wav，时长 10 秒到 5 分钟，文件不超过 20MB。", max_file_size_mb=20, accept=".mp3,.m4a,.wav"),
                    _field("preview_text", "试听文本", "textarea", required=True, placeholder="请输入试听文本"),
                    _field("preview_tier_code", "试听档位", "select", options=PREVIEW_TIER_OPTIONS),
                    _field("clone_prompt_audio", "额外示例音频", "file", help_text="可选增强示例音频。", max_file_size_mb=20, accept=".mp3,.m4a,.wav"),
                    _field("clone_prompt_text", "示例文本说明", "textarea", placeholder="可选，填写示例音频对应文本"),
                    _field("language_boost", "语言增强", "select", options=LANGUAGE_BOOST_OPTIONS),
                    _field("noise_reduction", "降噪开关", "switch"),
                    _field("volume_normalization", "音量归一化", "switch"),
                ],
            }
        },
        "default_tier": TIER_CLONE,
    },
    ABILITY_VOICE_MANAGEMENT: {
        "ability_type": ABILITY_VOICE_MANAGEMENT,
        "label": "音色管理",
        "description": "查询系统音色和自定义音色，管理自定义音色资产。",
        "scene": "音色查询 / 音色删除",
        "supports_preview": False,
        "is_async": False,
        "tiers": {
            TIER_MANAGE: {
                "tier_code": TIER_MANAGE,
                "tier_label": "查询 / 删除",
                "model_code": "voice_manage",
                "pricing": None,
                "fields": [],
            }
        },
        "default_tier": TIER_MANAGE,
    },
}


def get_audio_ability_or_none(ability_type: Optional[str]) -> Optional[Dict[str, Any]]:
    if not ability_type:
        return None
    return AUDIO_ABILITY_REGISTRY.get(str(ability_type).strip().lower())


def get_audio_ability_or_error(ability_type: Optional[str]) -> Dict[str, Any]:
    ability = get_audio_ability_or_none(ability_type)
    if not ability:
        raise ValueError("invalid_ability_type")
    return ability


def list_audio_abilities() -> List[Dict[str, Any]]:
    return list(AUDIO_ABILITY_REGISTRY.values())


def build_audio_catalog() -> Dict[str, Any]:
    abilities = []
    for ability in list_audio_abilities():
        tiers = []
        start_points = None
        for tier_code, tier in ability["tiers"].items():
            pricing = tier.get("pricing")
            points = None
            if isinstance(pricing, dict):
                if "sell_price_points" in pricing:
                    points = 1 if pricing.get("unit") == "每万字符" else pricing["sell_price_points"]
                elif "asset" in pricing:
                    if ability["ability_type"] == ABILITY_VOICE_DESIGN:
                        points = 1
                    elif ability["ability_type"] == ABILITY_VOICE_CLONE:
                        points = 1
                    else:
                        points = pricing["asset"]["sell_price_points"]
            if points is not None:
                start_points = points if start_points is None else min(start_points, points)
            tiers.append(
                {
                    "tier_code": tier_code,
                    "tier_label": tier["tier_label"],
                    "model_code": tier["model_code"],
                    "supports_speech_tags": tier["model_code"] in MINIMAX_SPEECH_TAG_MODELS,
                    "fields": tier["fields"],
                }
            )
        abilities.append(
            {
                "ability_type": ability["ability_type"],
                "label": ability["label"],
                "description": ability["description"],
                "scene": ability["scene"],
                "supports_preview": ability["supports_preview"],
                "is_async": ability["is_async"],
                "default_tier": ability["default_tier"],
                "start_points": start_points,
                "tiers": tiers,
            }
        )
    return {
        "abilities": abilities,
        "text_controls": {
            "speech_tag_models": sorted(MINIMAX_SPEECH_TAG_MODELS),
            "speech_tags": MINIMAX_SPEECH_TAG_OPTIONS,
            "pause_tags": MINIMAX_PAUSE_TAG_OPTIONS,
            "pause_range_seconds": {"min": 0.01, "max": 99.99},
        },
    }


def normalize_audio_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    ability_type = str(payload.get("ability_type") or "").strip().lower()
    ability = get_audio_ability_or_error(ability_type)
    tier_code = str(payload.get("tier_code") or ability["default_tier"]).strip().lower()
    tier = ability["tiers"].get(tier_code)
    if not tier:
        raise ValueError("invalid_tier_code")

    model_code = tier["model_code"]
    script_text = str(payload.get("script_text") or "").strip()
    preview_text = str(payload.get("preview_text") or "").strip()
    if ability_type in {ABILITY_REALTIME, ABILITY_NARRATION}:
        script_text = normalize_minimax_speech_tags(script_text, model_code)
        preview_text = normalize_minimax_speech_tags(preview_text, model_code)
    text_file_url = str(payload.get("text_file_url") or "").strip()
    voice_source_type = str(payload.get("voice_source_type") or VOICE_SOURCE_SYSTEM).strip().lower()

    return {
        "ability_type": ability_type,
        "ability_label": ability["label"],
        "tier_code": tier_code,
        "tier_label": tier["tier_label"],
        "model_code": model_code,
        "voice_id": str(payload.get("voice_id") or "").strip(),
        "voice_source_type": voice_source_type,
        "script_text": script_text,
        "preview_text": preview_text,
        "text_file_url": text_file_url,
        "emotion": str(payload.get("emotion") or "").strip() or None,
        "speed": payload.get("speed"),
        "volume": payload.get("volume"),
        "pitch": payload.get("pitch"),
        "sample_rate": payload.get("sample_rate"),
        "bitrate": payload.get("bitrate"),
        "audio_format": str(payload.get("audio_format") or "").strip() or "mp3",
        "channel_count": payload.get("channel_count"),
        "subtitle_enabled": bool(payload.get("subtitle_enabled")),
        "language_boost": str(payload.get("language_boost") or "").strip() or None,
        "watermark_enabled": bool(payload.get("watermark_enabled")),
        "clone_reference_file": str(payload.get("clone_reference_file") or "").strip(),
        "clone_prompt_audio": str(payload.get("clone_prompt_audio") or "").strip(),
        "clone_prompt_text": str(payload.get("clone_prompt_text") or "").strip(),
        "preview_tier_code": str(payload.get("preview_tier_code") or TIER_TURBO).strip().lower(),
        "noise_reduction": bool(payload.get("noise_reduction")),
        "volume_normalization": bool(payload.get("volume_normalization")),
        "submit_mode": str(payload.get("submit_mode") or GENERATE_MODE).strip().lower(),
    }


def estimate_audio_price(normalized: Dict[str, Any]) -> Dict[str, Any]:
    ability_type = normalized["ability_type"]
    tier_code = normalized["tier_code"]
    breakdown: List[Dict[str, Any]] = []
    notes: List[str] = []
    unit_count = 0
    characters = 0

    if ability_type in {ABILITY_REALTIME, ABILITY_NARRATION}:
        source_text = normalized["script_text"]
        if not source_text and not normalized["text_file_url"]:
            raise ValueError("missing_script_text")
        characters = calculate_billing_characters(source_text) if source_text else 0
        unit_count = calculate_unit_count(characters or 10000)
        pricing = PRICING_REALTIME_HD if tier_code == TIER_HD else PRICING_REALTIME_TURBO
        point_cost = calculate_points_by_characters(characters or 1, pricing["sell_price_points"])
        breakdown.append(
            {
                "label": f"{ABILITY_LABELS[ability_type]}·{TIER_LABELS[tier_code]}",
                "cost_price": round(pricing["cost_price"] * unit_count, 2),
                "suggested_price": round(pricing["suggested_price"] * unit_count, 2),
                "sell_price_points": point_cost,
            }
        )
        notes.append(
            f"{TIER_LABELS[tier_code]} / {characters or '文件上传'} 字符 / 约每 1 灵感值 {calculate_chars_per_point(pricing['sell_price_points'])} 字符"
        )
    elif ability_type == ABILITY_VOICE_DESIGN:
        preview_text = normalized["preview_text"]
        if preview_text:
            characters = calculate_billing_characters(preview_text)
            unit_count = calculate_unit_count(characters)
            point_cost = calculate_points_by_characters(characters, PRICING_DESIGN_PREVIEW["sell_price_points"])
            breakdown.append(
                {
                    "label": "音色试听",
                    "cost_price": round(PRICING_DESIGN_PREVIEW["cost_price"] * unit_count, 2),
                    "suggested_price": round(PRICING_DESIGN_PREVIEW["suggested_price"] * unit_count, 2),
                    "sell_price_points": point_cost,
                }
            )
        notes.append(
            "当前只收试听灵感值，正式用于配音后才会收取音色启用费用；试听按每 1 灵感值约 {0} 字符向上取整".format(
                calculate_chars_per_point(PRICING_DESIGN_PREVIEW["sell_price_points"])
            )
        )
    elif ability_type == ABILITY_VOICE_CLONE:
        preview_text = normalized["preview_text"]
        preview_pricing = PRICING_PREVIEW_HD if normalized["preview_tier_code"] == TIER_HD else PRICING_PREVIEW_TURBO
        if preview_text:
            characters = calculate_billing_characters(preview_text)
            unit_count = calculate_unit_count(characters)
            point_cost = calculate_points_by_characters(characters, preview_pricing["sell_price_points"])
            breakdown.append(
                {
                    "label": "复刻试听",
                    "cost_price": round(preview_pricing["cost_price"] * unit_count, 2),
                    "suggested_price": round(preview_pricing["suggested_price"] * unit_count, 2),
                    "sell_price_points": point_cost,
                }
            )
        notes.append(
            "当前只收试听灵感值，正式用于配音后才会收取复刻音色启用费用；{0}试听按每 1 灵感值约 {1} 字符向上取整".format(
                TIER_LABELS.get(normalized["preview_tier_code"], "试听"),
                calculate_chars_per_point(preview_pricing["sell_price_points"]),
            )
        )
    else:
        breakdown = []

    total_cost = round(sum(item["cost_price"] for item in breakdown), 2)
    total_suggested = round(sum(item["suggested_price"] for item in breakdown), 2)
    total_points = sum(int(item["sell_price_points"]) for item in breakdown)
    return {
        "cost_price": total_cost,
        "suggested_price": total_suggested,
        "sell_price_points": total_points,
        "characters": characters,
        "unit_count": unit_count,
        "pricing_note": " + ".join(notes),
        "breakdown": breakdown,
    }
