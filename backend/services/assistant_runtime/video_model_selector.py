from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, TypedDict

from services.video_model_registry import (
    CATEGORY_CONSISTENCY,
    CATEGORY_CONTROL,
    CATEGORY_QUALITY,
    CATEGORY_SPEED,
    GEN_IMAGE,
    GEN_REFERENCE,
    GEN_START_END,
    GEN_TEXT,
    GENERATION_TYPE_LABELS,
    build_video_catalog,
)

class VideoModelSelectionContext(TypedDict):
    categories: List[Dict[str, Any]]
    models: List[Dict[str, Any]]
    supported_generation_types: List[str]
    supports_auto_model_selection: bool


_SUPPORTED_ALIAS_MAP = {
    "veo_31_fast": ["veo_31_fast", "veo 3.1 fast", "veo31 fast", "veo fast"],
    "veo_31_pro": ["veo_31_pro", "veo 3.1 pro", "veo31 pro", "veo pro"],
    "veo_31_fast_official": ["veo_31_fast_official", "veo 3.1 fast official", "veo fast official", "veo官方fast", "veo官方快速版"],
    "veo_31_pro_official": ["veo_31_pro_official", "veo 3.1 pro official", "veo pro official", "veo官方pro", "veo官方稳定版pro"],
    "vidu_q2_pro": ["vidu_q2_pro", "vidu q2 pro", "viduq2pro", "q2 pro", "vidu q2"],
    "vidu_q2_pro_fast": ["vidu_q2_pro_fast", "vidu q2 pro fast", "viduq2profast", "q2 pro fast", "vidu q2 fast"],
    "vidu_q3_pro": ["vidu_q3_pro", "vidu q3 pro", "viduq3pro", "q3 pro", "vidu q3"],
    "vidu_q3_turbo": ["vidu_q3_turbo", "vidu q3 turbo", "viduq3turbo", "q3 turbo"],
    "seedance_v15_pro": ["seedance_v15_pro", "seedance v1.5 pro", "seedance 1.5 pro", "seedance pro"],
    "seedance_v15_fast": ["seedance_v15_fast", "seedance v1.5 fast", "seedance 1.5 fast", "seedance fast"],
    "seedance_20_fast": ["seedance_20_fast", "seedance 2.0 fast", "seedance2.0 fast", "seedance fast 2.0"],
    "seedance_20": ["seedance_20", "seedance 2.0", "seedance2.0", "seedance 20"],
    "kling_o1": ["kling_o1", "kling o1", "klingo1", "kling"],
    "kling_30_std": ["kling_30_std", "kling 3.0 std", "kling3.0 std", "kling 3 std"],
    "kling_30_pro": ["kling_30_pro", "kling 3.0 pro", "kling3.0 pro", "kling 3 pro"],
    "kling_o3_std": ["kling_o3_std", "kling o3 std", "kling o3", "klingo3 std", "kling o3 reference std", "kling o3 reference", "kling o3 ref std"],
    "kling_o3_pro": ["kling_o3_pro", "kling o3 pro", "klingo3 pro", "kling o3 reference pro", "kling o3 ref pro"],
}

_UNAVAILABLE_ALIAS_MAP = {}

_CATEGORY_PREFERRED_ORDER = {
    CATEGORY_SPEED: ["seedance_20_fast", "veo_31_fast_official", "seedance_v15_fast", "veo_31_fast", "vidu_q3_turbo", "vidu_q2_pro_fast"],
    CATEGORY_QUALITY: ["veo_31_pro_official", "seedance_20", "kling_o3_pro", "kling_30_pro", "veo_31_pro", "vidu_q3_pro", "seedance_v15_pro", "kling_o3_std", "kling_30_std"],
    CATEGORY_CONSISTENCY: ["kling_o3_pro", "kling_o3_std", "vidu_q2_pro"],
    CATEGORY_CONTROL: ["kling_o1", "vidu_q2_pro"],
}

_CATEGORY_ORDER = [
    CATEGORY_CONTROL,
    CATEGORY_CONSISTENCY,
    CATEGORY_QUALITY,
    CATEGORY_SPEED,
]


def _normalize_text(value: Optional[str]) -> str:
    return re.sub(r"[\s_\-./]+", "", str(value or "").strip().lower())


def build_video_model_selection_context() -> VideoModelSelectionContext:
    catalog = build_video_catalog()
    connected_models = [
        item for item in (catalog.get("models") or [])
        if str(item.get("status") or "").strip() == "已接入"
    ]

    categories: List[Dict[str, Any]] = []
    supported_generation_types: List[str] = []
    seen_generation_types = set()

    for category in catalog.get("categories") or []:
        public_models = []
        for item in category.get("models") or []:
            if str(item.get("status") or "").strip() != "已接入":
                continue
            generation_types = sorted(
                {
                    feature.get("generation_type")
                    for feature in item.get("features") or []
                    if feature.get("generation_type")
                }
            )
            for generation_type in generation_types:
                if generation_type not in seen_generation_types:
                    seen_generation_types.add(generation_type)
                    supported_generation_types.append(generation_type)
            public_models.append(
                {
                    "model_code": item.get("model_code"),
                    "model_name": item.get("model_name"),
                    "category": item.get("category"),
                    "category_label": item.get("category_label"),
                    "feature_tags": item.get("feature_tags") or [],
                    "supports_audio": bool(item.get("supports_audio")),
                    "recommendation": item.get("recommendation") or "",
                    "default_generation_type": item.get("default_generation_type"),
                }
            )
        if public_models:
            categories.append(
                {
                    "code": category.get("code"),
                    "label": category.get("label"),
                    "models": public_models,
                }
            )

    return {
        "categories": categories,
        "models": connected_models,
        "supported_generation_types": supported_generation_types,
        "supports_auto_model_selection": True,
    }


def build_video_skill_metadata() -> Dict[str, Any]:
    context = build_video_model_selection_context()
    return {
        "supports_auto_model_selection": True,
        "supported_generation_types": list(context["supported_generation_types"]),
        "video_model_categories": context["categories"],
    }


def resolve_explicit_video_model_request(content: str) -> Optional[Dict[str, Any]]:
    normalized = _normalize_text(content)
    if not normalized:
        return None

    context = build_video_model_selection_context()
    models_by_code = {str(item.get("model_code") or ""): item for item in context.get("models") or []}

    for model_code, aliases in _SUPPORTED_ALIAS_MAP.items():
        for alias in aliases:
            if _normalize_text(alias) and _normalize_text(alias) in normalized:
                item = models_by_code.get(model_code) or {}
                return {
                    "requested_text": alias,
                    "model_code": model_code,
                    "status": "已接入",
                    "connected": True,
                    "model_name": item.get("model_name") or model_code,
                    "category": item.get("category"),
                    "category_label": item.get("category_label"),
                }

    for model_code, aliases in _UNAVAILABLE_ALIAS_MAP.items():
        for alias in aliases:
            if _normalize_text(alias) and _normalize_text(alias) in normalized:
                return {
                    "requested_text": alias,
                    "model_code": model_code,
                    "status": "待确认",
                    "connected": False,
                    "model_name": model_code,
                    "category": CATEGORY_QUALITY,
                    "category_label": "质量优先",
                }
    return None


def build_video_model_options(
    *,
    generation_type: Optional[str] = None,
    audio_enabled: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    context = build_video_model_selection_context()
    candidates = context["models"]
    if generation_type:
        candidates = [
            item
            for item in candidates
            if generation_type in {feature.get("generation_type") for feature in item.get("features") or []}
        ]
    if audio_enabled:
        candidates = [item for item in candidates if item.get("supports_audio")]

    return [
        {
            "value": item.get("model_code"),
            "label": item.get("model_name"),
            "model_code": item.get("model_code"),
            "model_name": item.get("model_name"),
            "category_label": item.get("category_label"),
            "feature_tags": item.get("feature_tags") or [],
            "supports_audio": bool(item.get("supports_audio")),
            "recommendation": item.get("recommendation") or "",
        }
        for item in candidates
    ]


def choose_video_model(
    *,
    content: str,
    generation_type: str,
    duration: int,
    audio_enabled: bool,
    image_ref_count: int,
    video_ref_count: int,
    explicit_request: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    context = build_video_model_selection_context()
    candidates = _filter_model_candidates(
        context=context,
        generation_type=generation_type,
        audio_enabled=audio_enabled,
    )
    if not candidates:
        return {
            "ok": False,
            "reason": "当前条件下没有可用的视频模型。",
            "alternatives": [],
        }

    if explicit_request:
        explicit_choice = _resolve_candidate(explicit_request.get("model_code"), candidates)
        if not explicit_request.get("connected"):
            alternatives = _build_alternative_models(candidates, preferred_category=explicit_request.get("category"), exclude_codes=[])
            return {
                "ok": False,
                "reason": "你指定的 {0} 当前在神鹿里还不可用。".format(explicit_request.get("model_name") or explicit_request.get("model_code")),
                "requested_text": explicit_request.get("requested_text"),
                "alternatives": alternatives,
            }
        if not explicit_choice:
            alternatives = _build_alternative_models(candidates, preferred_category=explicit_request.get("category"), exclude_codes=[])
            return {
                "ok": False,
                "reason": "你指定的 {0} 与当前生成方式或音频条件不兼容。".format(explicit_request.get("model_name") or explicit_request.get("model_code")),
                "requested_text": explicit_request.get("requested_text"),
                "alternatives": alternatives,
            }
        selection_reason = _build_selection_reason(
            mode="explicit",
            model_name=explicit_choice["model_name"],
            category_label=explicit_choice["category_label"],
            generation_type=generation_type,
            duration=duration,
            audio_enabled=audio_enabled,
            image_ref_count=image_ref_count,
            video_ref_count=video_ref_count,
        )
        return {
            "ok": True,
            "model": explicit_choice,
            "selection_reason": selection_reason,
            "selection_mode": "explicit",
            "alternatives": _build_alternative_models(
                candidates,
                preferred_category=explicit_choice.get("category"),
                exclude_codes=[explicit_choice["model_code"]],
            ),
        }

    preferred_category = _infer_preferred_category(
        content=content,
        image_ref_count=image_ref_count,
        video_ref_count=video_ref_count,
        audio_enabled=audio_enabled,
    )
    ordered_codes = _preferred_model_codes(
        preferred_category=preferred_category,
        generation_type=generation_type,
        audio_enabled=audio_enabled,
    )
    choice = None
    for code in ordered_codes:
        choice = _resolve_candidate(code, candidates)
        if choice:
            break
    if not choice:
        choice = candidates[0]
        preferred_category = choice.get("category")

    selection_reason = _build_selection_reason(
        mode="auto",
        model_name=choice["model_name"],
        category_label=choice["category_label"],
        generation_type=generation_type,
        duration=duration,
        audio_enabled=audio_enabled,
        image_ref_count=image_ref_count,
        video_ref_count=video_ref_count,
    )
    return {
        "ok": True,
        "model": choice,
        "selection_reason": selection_reason,
        "selection_mode": "auto",
        "alternatives": _build_alternative_models(
            candidates,
            preferred_category=preferred_category,
            exclude_codes=[choice["model_code"]],
        ),
    }


def infer_video_generation_type(
    *,
    content: str,
    latest_image: str,
    attachment_image_urls: Sequence[str],
    attachment_video_urls: Sequence[str],
) -> str:
    lowered = str(content or "").strip().lower()
    image_ref_count = len([item for item in attachment_image_urls if str(item or "").strip()])
    video_ref_count = len([item for item in attachment_video_urls if str(item or "").strip()])
    if video_ref_count > 0:
        return GEN_REFERENCE
    if any(keyword in lowered for keyword in ["首尾帧", "首帧", "尾帧", "起始帧", "结束帧"]) and image_ref_count >= 2:
        return GEN_START_END
    if image_ref_count >= 2 and any(keyword in lowered for keyword in ["参考图", "多参考", "一致性", "统一风格", "角色一致"]):
        return GEN_REFERENCE
    if image_ref_count == 1:
        return GEN_IMAGE
    if latest_image:
        return GEN_IMAGE
    return GEN_TEXT


def infer_audio_enabled(content: str) -> bool:
    lowered = str(content or "").strip().lower()
    return any(keyword in lowered for keyword in ["带音频", "开启音频", "保留原音", "带声音", "有声音", "保留声音", "带音效"])


def build_model_unavailable_message(*, reason: str, alternatives: Sequence[Dict[str, Any]]) -> str:
    if not alternatives:
        return reason
    parts = []
    for item in list(alternatives)[:3]:
        parts.append("{0}（{1}）".format(item.get("model_name") or item.get("model_code"), item.get("category_label") or item.get("category") or "可用替代"))
    return "{0} 可考虑：{1}。".format(reason, "、".join(parts))


def _filter_model_candidates(*, context: VideoModelSelectionContext, generation_type: str, audio_enabled: bool) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []
    for item in context["models"]:
        feature_map = {feature.get("generation_type"): feature for feature in item.get("features") or []}
        if generation_type not in feature_map:
            continue
        if audio_enabled and not item.get("supports_audio"):
            continue
        candidates.append(
            {
                "model_code": item.get("model_code"),
                "model_name": item.get("model_name"),
                "category": item.get("category"),
                "category_label": item.get("category_label"),
                "feature_tags": item.get("feature_tags") or [],
                "supports_audio": bool(item.get("supports_audio")),
                "recommendation": item.get("recommendation") or "",
                "generation_type": generation_type,
                "generation_type_label": GENERATION_TYPE_LABELS.get(generation_type, generation_type),
            }
        )
    return candidates


def _resolve_candidate(model_code: Optional[str], candidates: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    code = str(model_code or "").strip().lower()
    if not code:
        return None
    for item in candidates:
        if str(item.get("model_code") or "").strip().lower() == code:
            return dict(item)
    return None


def _infer_preferred_category(*, content: str, image_ref_count: int, video_ref_count: int, audio_enabled: bool) -> str:
    lowered = str(content or "").strip().lower()
    if video_ref_count > 0 or any(keyword in lowered for keyword in ["参考视频", "按这个动作", "动作参考", "镜头控制", "控制力", "动作一致"]):
        return CATEGORY_CONTROL
    if image_ref_count > 1 or any(keyword in lowered for keyword in ["一致性", "角色一致", "多参考", "统一风格", "同一角色"]):
        return CATEGORY_CONSISTENCY
    if any(keyword in lowered for keyword in ["高质量", "高质", "正式成片", "电影感", "细节", "质感", "精致"]):
        return CATEGORY_QUALITY
    if audio_enabled or any(keyword in lowered for keyword in ["快速", "预演", "预览", "试跑", "先试试", "快一点", "批量"]):
        return CATEGORY_SPEED
    return CATEGORY_SPEED


def _preferred_model_codes(*, preferred_category: str, generation_type: str, audio_enabled: bool) -> List[str]:
    ordered: List[str] = []
    for category in [preferred_category] + [item for item in _CATEGORY_ORDER if item != preferred_category]:
        ordered.extend(_CATEGORY_PREFERRED_ORDER.get(category) or [])
    if audio_enabled:
        ordered = [code for code in ordered if code in {"vidu_q2_pro", "seedance_v15_pro", "seedance_v15_fast"}]
    if generation_type == GEN_TEXT:
        ordered = [code for code in ordered if code not in {"vidu_q2_pro_fast"}]
    return list(dict.fromkeys(ordered))


def _build_selection_reason(
    *,
    mode: str,
    model_name: str,
    category_label: str,
    generation_type: str,
    duration: int,
    audio_enabled: bool,
    image_ref_count: int,
    video_ref_count: int,
) -> str:
    parts = []
    parts.append("已按你指定的模型使用 {0}".format(model_name) if mode == "explicit" else "已自动选择 {0}".format(model_name))
    if category_label:
        parts.append("当前更偏向 {0}".format(category_label))
    if video_ref_count > 0:
        parts.append("检测到参考视频，优先满足动作控制")
    elif image_ref_count > 1:
        parts.append("检测到多张参考图，优先保证角色与风格一致性")
    elif generation_type == GEN_IMAGE:
        parts.append("当前会复用分镜首帧做图生视频")
    if audio_enabled:
        parts.append("并且已限制为支持音频的模型")
    if duration >= 8:
        parts.append("适配 {0} 秒时长".format(duration))
    return "，".join(parts) + "。"


def _build_alternative_models(candidates: Sequence[Dict[str, Any]], *, preferred_category: Optional[str], exclude_codes: Sequence[str]) -> List[Dict[str, Any]]:
    excluded = {str(item or "").strip().lower() for item in exclude_codes}
    ordered: List[Dict[str, Any]] = []
    for category in ([preferred_category] if preferred_category else []) + [item for item in _CATEGORY_ORDER if item != preferred_category]:
        for code in _CATEGORY_PREFERRED_ORDER.get(category or "", []):
            candidate = _resolve_candidate(code, candidates)
            if not candidate or candidate["model_code"] in excluded:
                continue
            ordered.append(candidate)
    if not ordered:
        ordered = [dict(item) for item in candidates if item.get("model_code") not in excluded]
    unique: List[Dict[str, Any]] = []
    seen = set()
    for item in ordered:
        code = str(item.get("model_code") or "").strip().lower()
        if not code or code in seen:
            continue
        seen.add(code)
        unique.append(item)
    return unique[:3]
