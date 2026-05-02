from __future__ import annotations

import json
from copy import deepcopy
from typing import Any, Dict, List, Optional

from models import Episode, Script
from schemas import STORYBOARD_MODE_COMMENTARY, STORYBOARD_MODE_COMIC, normalize_storyboard_mode
from services.image_model_registry import DEFAULT_IMAGE_MODEL_CODE, normalize_image_model_code

WORKFLOW_ASPECT_RATIO_OPTIONS = ("16:9", "9:16")
DEFAULT_IMAGE_RESOLUTION = "2k"
DEFAULT_IMAGE_QUALITY = "medium"
DEFAULT_VIDEO_GENERATION_TYPE = "image_to_video"
DEFAULT_VIDEO_RESOLUTION = "720p"
STYLE_ID_CUSTOM = "custom"

STYLE_LIBRARY: Dict[str, Dict[str, str]] = {
    "ai_live_action": {
        "label": "AI仿真人电影写实",
        "mode_recommendation": "both",
        "display_description": "适合都市情绪戏、对峙戏和反转戏，强调真实皮肤质感、电影布光和短剧张力。",
        "internal_prompt_template": "AI仿真人电影写实风，短剧调色风格，真实皮肤纹理，电影质感，高级布光，浅景深，情绪张力强",
    },
    "dynamic_manhua": {
        "label": "2D高精动态漫",
        "mode_recommendation": "comic",
        "display_description": "适合漫剧主线，强调国漫短剧感、人物立绘感和强分镜张力。",
        "internal_prompt_template": "2D高精动态漫，国漫短剧风格，线条干净，精致上色，人物立绘感强，分镜感明显，情绪张力强",
    },
    "guofeng_fantasy": {
        "label": "2D国潮古风",
        "mode_recommendation": "both",
        "display_description": "适合古偶、玄幻、权谋与复仇题材，强调东方美学、水墨云雾和清冷电影质感。",
        "internal_prompt_template": "2D国潮古风，东方美学意境，古偶玄幻电影质感，服化道精致，鎏金云雾光效，水墨晕染氛围，画面高级清冷",
    },
    "anime_cel": {
        "label": "日系二次元",
        "mode_recommendation": "comic",
        "display_description": "适合校园、异能、青春悬疑与动画演出感较强的内容。",
        "internal_prompt_template": "日系二次元动画风，赛璐璐上色，线条清晰，动画分镜感强，角色精致，青春感明显",
    },
    "cg_cinematic": {
        "label": "3D动漫 / 半CG影视",
        "mode_recommendation": "comic",
        "display_description": "适合科幻、机甲和预告片感强的内容，强调建模、灯光和空间层次。",
        "internal_prompt_template": "高质量3D动漫，半CG影视风，游戏CG预告片质感，建模精细，灯光高级，空间层次强",
    },
    "meme_comedy": {
        "label": "沙雕搞笑 / 表情包画风",
        "mode_recommendation": "both",
        "display_description": "适合整活、搞笑、反差感内容，强调夸张表情和高信息密度笑点。",
        "internal_prompt_template": "沙雕搞笑，夸张魔性，表情夸张，画面信息明确，适配表情包画风与简笔画沙雕风",
    },
    "commentary_static": {
        "label": "解说漫 / 静态漫画轻动态",
        "mode_recommendation": "commentary",
        "display_description": "适合旁白讲故事、信息表达和批量内容生产，强调统一构图和轻动态画面。",
        "internal_prompt_template": "解说漫风格，静态漫画感，轻动态画面，构图清晰，信息表达明确，适合旁白讲故事，画面统一，氛围感明显",
    },
}


def _safe_json_loads(raw: Any, fallback: Any) -> Any:
    if raw in (None, ""):
        return deepcopy(fallback)
    if isinstance(raw, (dict, list)):
        return deepcopy(raw)
    try:
        return json.loads(str(raw))
    except Exception:
        return deepcopy(fallback)


def _safe_json_dumps(raw: Any, fallback: Any) -> str:
    try:
        return json.dumps(raw if raw is not None else fallback, ensure_ascii=False)
    except Exception:
        return json.dumps(fallback, ensure_ascii=False)


def _normalize_aspect_ratio(value: Optional[str], fallback: str) -> str:
    text = str(value or "").strip()
    return text if text in WORKFLOW_ASPECT_RATIO_OPTIONS else fallback


def _normalize_duration(value: Any, fallback: int) -> int:
    try:
        duration = int(value)
    except Exception:
        duration = fallback
    return max(1, min(duration, 15))


def _normalize_image_model(value: Optional[str]) -> str:
    return normalize_image_model_code(value or DEFAULT_IMAGE_MODEL_CODE)


def _normalize_video_model(value: Optional[str], fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _normalize_style_config(raw: Any, *, fallback_style_id: str, legacy_style_preset: Optional[str] = None) -> Dict[str, str]:
    base = {"style_id": fallback_style_id, "custom_label": "", "custom_prompt": ""}
    payload = raw if isinstance(raw, dict) else {}
    style_id = str(payload.get("style_id") or "").strip()
    custom_label = str(payload.get("custom_label") or "").strip()
    custom_prompt = str(payload.get("custom_prompt") or "").strip()

    legacy = str(legacy_style_preset or "").strip()
    if not style_id and legacy and legacy != "默认写实":
        style_id = STYLE_ID_CUSTOM
        custom_label = custom_label or legacy
        custom_prompt = custom_prompt or legacy

    if style_id in STYLE_LIBRARY:
        return {
            "style_id": style_id,
            "custom_label": "",
            "custom_prompt": "",
        }

    if style_id == STYLE_ID_CUSTOM or custom_label or custom_prompt:
        return {
            "style_id": STYLE_ID_CUSTOM,
            "custom_label": custom_label or legacy or "自定义风格",
            "custom_prompt": custom_prompt or legacy,
        }

    return base


def _default_profile(mode: str) -> Dict[str, Any]:
    if mode == STORYBOARD_MODE_COMIC:
        return {
            "aspect_ratio": "16:9",
            "storyboard": {
                "deep_thinking": False,
            },
            "image": {
                "model_code": DEFAULT_IMAGE_MODEL_CODE,
                "resolution": DEFAULT_IMAGE_RESOLUTION,
                "quality": DEFAULT_IMAGE_QUALITY,
            },
            "video": {
                "model_code": "seedance_20_fast",
                "generation_type": "reference_to_video",
                "duration": 8,
                "resolution": DEFAULT_VIDEO_RESOLUTION,
                "audio_enabled": True,
                "motion_strength": "",
                "quality_mode": "",
                "camera_fixed": False,
                "real_person_mode": False,
                "web_search": False,
            },
            "style": {
                "style_id": "dynamic_manhua",
                "custom_label": "",
                "custom_prompt": "",
            },
        }

    return {
        "aspect_ratio": "9:16",
        "storyboard": {
            "deep_thinking": False,
        },
        "image": {
            "model_code": DEFAULT_IMAGE_MODEL_CODE,
            "resolution": DEFAULT_IMAGE_RESOLUTION,
            "quality": DEFAULT_IMAGE_QUALITY,
        },
        "video": {
            "model_code": "seedance_v15_fast",
            "generation_type": DEFAULT_VIDEO_GENERATION_TYPE,
            "duration": 6,
            "resolution": DEFAULT_VIDEO_RESOLUTION,
            "audio_enabled": True,
            "motion_strength": "",
            "quality_mode": "",
            "camera_fixed": False,
            "real_person_mode": False,
            "web_search": False,
        },
        "style": {
            "style_id": "commentary_static",
            "custom_label": "",
            "custom_prompt": "",
        },
    }


def normalize_workflow_profile(
    raw: Any,
    *,
    mode: str,
    legacy_aspect_ratio: Optional[str] = None,
    legacy_style_preset: Optional[str] = None,
) -> Dict[str, Any]:
    mode = normalize_storyboard_mode(mode)
    defaults = _default_profile(mode)
    payload = raw if isinstance(raw, dict) else {}
    fallback_ratio = _normalize_aspect_ratio(legacy_aspect_ratio, defaults["aspect_ratio"])

    profile = {
        "aspect_ratio": _normalize_aspect_ratio(payload.get("aspect_ratio"), fallback_ratio),
        "storyboard": {
            "deep_thinking": bool((((payload.get("storyboard") or {}) if isinstance(payload.get("storyboard"), dict) else {}).get("deep_thinking"))
            if ((payload.get("storyboard") or {}) if isinstance(payload.get("storyboard"), dict) else {}).get("deep_thinking") is not None
            else defaults["storyboard"]["deep_thinking"]),
        },
        "image": {
            "model_code": _normalize_image_model(((payload.get("image") or {}) if isinstance(payload.get("image"), dict) else {}).get("model_code")),
            "resolution": str((((payload.get("image") or {}) if isinstance(payload.get("image"), dict) else {}).get("resolution") or defaults["image"]["resolution"])).strip() or defaults["image"]["resolution"],
            "quality": str((((payload.get("image") or {}) if isinstance(payload.get("image"), dict) else {}).get("quality") or defaults["image"]["quality"])).strip() or defaults["image"]["quality"],
        },
        "video": {
            "model_code": _normalize_video_model((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("model_code")), defaults["video"]["model_code"]),
            "generation_type": str((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("generation_type") or defaults["video"]["generation_type"])).strip() or defaults["video"]["generation_type"],
            "duration": _normalize_duration((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("duration")), defaults["video"]["duration"]),
            "resolution": str((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("resolution") or defaults["video"]["resolution"])).strip() or defaults["video"]["resolution"],
            "audio_enabled": bool((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("audio_enabled")) if ((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("audio_enabled") is not None else defaults["video"]["audio_enabled"]),
            "motion_strength": str((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("motion_strength") or defaults["video"]["motion_strength"])).strip(),
            "quality_mode": str((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("quality_mode") or defaults["video"]["quality_mode"])).strip(),
            "camera_fixed": bool((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("camera_fixed")) if ((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("camera_fixed") is not None else defaults["video"]["camera_fixed"]),
            "real_person_mode": bool((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("real_person_mode")) if ((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("real_person_mode") is not None else defaults["video"]["real_person_mode"]),
            "web_search": bool((((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("web_search")) if ((payload.get("video") or {}) if isinstance(payload.get("video"), dict) else {}).get("web_search") is not None else defaults["video"]["web_search"]),
        },
        "style": _normalize_style_config(payload.get("style"), fallback_style_id=defaults["style"]["style_id"], legacy_style_preset=legacy_style_preset),
    }
    return profile


def build_default_workflow_settings(
    *,
    default_storyboard_mode: Optional[str] = None,
    legacy_aspect_ratio: Optional[str] = None,
    legacy_style_preset: Optional[str] = None,
) -> Dict[str, Any]:
    default_mode = normalize_storyboard_mode(default_storyboard_mode or STORYBOARD_MODE_COMIC)
    return {
        "version": 1,
        "default_storyboard_mode": default_mode,
        "profiles": {
            STORYBOARD_MODE_COMMENTARY: normalize_workflow_profile(
                {},
                mode=STORYBOARD_MODE_COMMENTARY,
                legacy_aspect_ratio=legacy_aspect_ratio,
                legacy_style_preset=legacy_style_preset,
            ),
            STORYBOARD_MODE_COMIC: normalize_workflow_profile(
                {},
                mode=STORYBOARD_MODE_COMIC,
                legacy_aspect_ratio=legacy_aspect_ratio,
                legacy_style_preset=legacy_style_preset,
            ),
        },
    }


def normalize_workflow_settings(
    raw: Any,
    *,
    legacy_aspect_ratio: Optional[str] = None,
    legacy_style_preset: Optional[str] = None,
    default_storyboard_mode: Optional[str] = None,
) -> Dict[str, Any]:
    payload = _safe_json_loads(raw, {})
    default_mode = normalize_storyboard_mode(
        (payload.get("default_storyboard_mode") if isinstance(payload, dict) else None)
        or default_storyboard_mode
        or STORYBOARD_MODE_COMIC
    )
    payload_profiles = payload.get("profiles") if isinstance(payload, dict) and isinstance(payload.get("profiles"), dict) else {}
    return {
        "version": 1,
        "default_storyboard_mode": default_mode,
        "profiles": {
            STORYBOARD_MODE_COMMENTARY: normalize_workflow_profile(
                payload_profiles.get(STORYBOARD_MODE_COMMENTARY),
                mode=STORYBOARD_MODE_COMMENTARY,
                legacy_aspect_ratio=legacy_aspect_ratio,
                legacy_style_preset=legacy_style_preset,
            ),
            STORYBOARD_MODE_COMIC: normalize_workflow_profile(
                payload_profiles.get(STORYBOARD_MODE_COMIC),
                mode=STORYBOARD_MODE_COMIC,
                legacy_aspect_ratio=legacy_aspect_ratio,
                legacy_style_preset=legacy_style_preset,
            ),
        },
    }


def normalize_episode_workflow_override(raw: Any) -> Dict[str, Any]:
    payload = _safe_json_loads(raw, {})
    profiles = payload.get("profiles") if isinstance(payload, dict) and isinstance(payload.get("profiles"), dict) else {}
    normalized_profiles: Dict[str, Any] = {}
    for mode in (STORYBOARD_MODE_COMMENTARY, STORYBOARD_MODE_COMIC):
        profile = profiles.get(mode)
        if not isinstance(profile, dict):
            continue
        storyboard = profile.get("storyboard") if isinstance(profile.get("storyboard"), dict) else {}
        if storyboard.get("deep_thinking") is None:
            continue
        normalized_profiles[mode] = {
            "storyboard": {
                "deep_thinking": bool(storyboard.get("deep_thinking")),
            }
        }
    return {"profiles": normalized_profiles}


def workflow_settings_to_json(
    raw: Any,
    *,
    legacy_aspect_ratio: Optional[str] = None,
    legacy_style_preset: Optional[str] = None,
    default_storyboard_mode: Optional[str] = None,
) -> str:
    return _safe_json_dumps(
        normalize_workflow_settings(
            raw,
            legacy_aspect_ratio=legacy_aspect_ratio,
            legacy_style_preset=legacy_style_preset,
            default_storyboard_mode=default_storyboard_mode,
        ),
        build_default_workflow_settings(
            default_storyboard_mode=default_storyboard_mode,
            legacy_aspect_ratio=legacy_aspect_ratio,
            legacy_style_preset=legacy_style_preset,
        ),
    )


def workflow_override_to_json(raw: Any) -> str:
    normalized = normalize_episode_workflow_override(raw)
    if not normalized["profiles"]:
        return "{}"
    return _safe_json_dumps(normalized, {})


def resolve_default_storyboard_mode(script: Script) -> str:
    settings_payload = normalize_workflow_settings(
        getattr(script, "workflow_settings_json", "{}"),
        legacy_aspect_ratio=getattr(script, "aspect_ratio", None),
        legacy_style_preset=getattr(script, "style_preset", None),
        default_storyboard_mode=getattr(script, "default_storyboard_mode", None),
    )
    return normalize_storyboard_mode(
        settings_payload.get("default_storyboard_mode")
        or getattr(script, "default_storyboard_mode", None)
        or STORYBOARD_MODE_COMIC
    )


def resolve_asset_extraction_storyboard_mode(
    script: Script,
    *,
    episode: Optional[Episode] = None,
) -> str:
    return normalize_storyboard_mode(
        (getattr(episode, "storyboard_mode", None) if episode is not None else None)
        or resolve_default_storyboard_mode(script)
        or STORYBOARD_MODE_COMIC
    )


def resolve_storyboard_extraction_storyboard_mode(script: Script) -> str:
    return normalize_storyboard_mode(
        resolve_default_storyboard_mode(script)
        or getattr(script, "default_storyboard_mode", None)
        or STORYBOARD_MODE_COMIC
    )


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def get_style_display_label(style_config: Optional[Dict[str, Any]], fallback: str = "默认写实") -> str:
    payload = style_config or {}
    style_id = str(payload.get("style_id") or "").strip()
    if style_id in STYLE_LIBRARY:
        return STYLE_LIBRARY[style_id]["label"]
    custom_label = str(payload.get("custom_label") or "").strip()
    if custom_label:
        return custom_label
    custom_prompt = str(payload.get("custom_prompt") or "").strip()
    if custom_prompt:
        return custom_prompt[:24]
    return fallback


def build_style_prompt(style_config: Optional[Dict[str, Any]], fallback: str = "") -> str:
    payload = style_config or {}
    style_id = str(payload.get("style_id") or "").strip()
    if style_id in STYLE_LIBRARY:
        return STYLE_LIBRARY[style_id]["internal_prompt_template"]
    custom_prompt = str(payload.get("custom_prompt") or "").strip()
    if custom_prompt:
        return custom_prompt
    custom_label = str(payload.get("custom_label") or "").strip()
    if custom_label:
        return custom_label
    return str(fallback or "").strip()


def augment_prompt_with_style(base_prompt: str, profile: Optional[Dict[str, Any]], *, label_fallback: str = "") -> str:
    prompt = str(base_prompt or "").strip()
    if not profile:
        return prompt
    style_config = profile.get("style") if isinstance(profile, dict) else {}
    style_prompt = build_style_prompt(style_config, fallback=label_fallback)
    if not style_prompt:
        return prompt
    if style_prompt in prompt:
        return prompt
    if not prompt:
        return f"风格基线：{style_prompt}"
    return f"{prompt}\n风格基线：{style_prompt}"


def list_public_style_options() -> List[Dict[str, str]]:
    options: List[Dict[str, str]] = []
    for style_id, item in STYLE_LIBRARY.items():
        options.append(
            {
                "style_id": style_id,
                "label": item["label"],
                "mode_recommendation": item["mode_recommendation"],
                "display_description": item["display_description"],
            }
        )
    options.append(
        {
            "style_id": STYLE_ID_CUSTOM,
            "label": "自定义风格",
            "mode_recommendation": "both",
            "display_description": "自行输入风格名称与风格提示词，平台不会展示内部模板。",
        }
    )
    return options


def resolve_effective_workflow_profile(
    script: Script,
    *,
    episode: Optional[Episode] = None,
    storyboard_mode: Optional[str] = None,
) -> Dict[str, Any]:
    mode = normalize_storyboard_mode(
        storyboard_mode
        or (getattr(episode, "storyboard_mode", None) if episode is not None else None)
        or resolve_default_storyboard_mode(script)
        or STORYBOARD_MODE_COMMENTARY
    )
    settings = normalize_workflow_settings(
        getattr(script, "workflow_settings_json", "{}"),
        legacy_aspect_ratio=getattr(script, "aspect_ratio", None),
        legacy_style_preset=getattr(script, "style_preset", None),
    )
    profile = deepcopy(settings["profiles"][mode])
    if episode is not None:
        override = normalize_episode_workflow_override(getattr(episode, "workflow_override_json", "{}"))
        mode_override = override["profiles"].get(mode)
        if mode_override:
            profile = _deep_merge(profile, mode_override)

    profile["storyboard_mode"] = mode
    profile["style"]["label"] = get_style_display_label(profile.get("style"), getattr(script, "style_preset", "默认写实"))
    profile["style"]["display_description"] = STYLE_LIBRARY.get(profile["style"].get("style_id") or "", {}).get("display_description", "")
    return profile


def serialize_script_workflow(script: Script) -> Dict[str, Any]:
    settings = normalize_workflow_settings(
        getattr(script, "workflow_settings_json", "{}"),
        legacy_aspect_ratio=getattr(script, "aspect_ratio", None),
        legacy_style_preset=getattr(script, "style_preset", None),
    )
    return {
        "workflow_settings": settings,
        "default_storyboard_mode": settings["default_storyboard_mode"],
        "style_options": list_public_style_options(),
    }


def serialize_episode_workflow(script: Script, episode: Episode) -> Dict[str, Any]:
    override = normalize_episode_workflow_override(getattr(episode, "workflow_override_json", "{}"))
    effective = resolve_effective_workflow_profile(script, episode=episode)
    return {
        "workflow_override": override,
        "effective_workflow_profile": effective,
    }
