from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, or_
from sqlmodel import Session, select

from core.config import settings
from core.security import decode_id, encode_id
from database import engine
from models import (
    Episode,
    GenerationRecord,
    Panel,
    ResourceTypeEnum,
    Script,
    SharedResource,
    SharedResourceVersion,
    TaskStatusEnum,
    Team,
    TeamMemberLink,
    TemporaryUploadAsset,
    User,
    VoiceAsset,
)
from schemas import is_nine_grid_panel_type
from services.access_service import (
    require_episode_team_access,
    require_panel_team_access,
    require_resource_team_access,
    require_script_team_access,
)
from services.billing_service import deduct_inspiration_points
from services.oss_service import (
    build_oss_thumbnail_url,
    build_oss_video_snapshot_url,
    is_oss_url,
    upload_base64_to_oss,
    upload_remote_file_to_oss_with_meta,
)
from services.oss_service import upload_bytes_to_oss_with_meta
from services.minimax_audio_service import decode_hex_audio, minimax_audio_service
from services.panel_video_service import upsert_panel_video_history
from services.provider_adapters import ProviderResult
from services.runninghub_video_service import runninghub_video_service
from services.suchuang_video_service import suchuang_video_service
from services.task_job_service import create_task_job, enqueue_task_job
from services.task_job_service import get_redis_client, get_task_job, task_status_for_legacy, update_task_job
from services.workflow_preset_service import augment_prompt_with_style, resolve_effective_workflow_profile
from services.audio_model_registry import (
    ABILITY_LABELS as AUDIO_ABILITY_LABELS,
    ABILITY_NARRATION,
    ABILITY_REALTIME,
    ABILITY_VOICE_CLONE,
    ABILITY_VOICE_DESIGN,
    ABILITY_VOICE_MANAGEMENT,
    GENERATE_MODE as AUDIO_GENERATE_MODE,
    PREVIEW_MODE as AUDIO_PREVIEW_MODE,
    STATUS_EXPIRED as AUDIO_STATUS_EXPIRED,
    STATUS_FAILED as AUDIO_STATUS_FAILED,
    STATUS_RUNNING as AUDIO_STATUS_RUNNING,
    STATUS_SUCCESS as AUDIO_STATUS_SUCCESS,
    TIER_CLONE,
    TIER_DESIGN,
    TIER_HD as AUDIO_TIER_HD,
    TIER_LABELS as AUDIO_TIER_LABELS,
    TIER_MANAGE,
    TIER_TURBO as AUDIO_TIER_TURBO,
    VOICE_SOURCE_LABELS,
    VOICE_SOURCE_NEW_CLONE,
    VOICE_SOURCE_NEW_DESIGN,
    VOICE_SOURCE_SYSTEM,
    build_audio_catalog,
    estimate_audio_price,
    get_audio_ability_or_none,
    normalize_audio_request,
)
from services.video_model_registry import (
    GEN_REFERENCE,
    GEN_START_END,
    GENERATION_TYPE_LABELS,
    build_video_catalog,
    default_generation_type,
    estimate_video_price,
    get_video_model_or_none,
    normalize_video_request,
)
from services.image_model_registry import (
    GEN_IMAGE,
    GEN_TEXT,
    MODEL_GPT_IMAGE_2_FAST,
    build_image_catalog,
    estimate_image_price,
    get_image_model_or_none,
    normalize_image_model_code,
    normalize_image_request,
    query_image_generation,
    submit_image_generation as submit_image_request,
)

logger = logging.getLogger(__name__)


def _image_quality_label(params_public: Dict[str, Any]) -> str:
    return str(params_public.get("quality_label") or "").strip()


def _image_spec_text(params_public: Dict[str, Any], default_model: str) -> str:
    model_label = str(params_public.get("model_label") or default_model).strip() or default_model
    quality_label = _image_quality_label(params_public)
    return " · ".join([part for part in [model_label, quality_label] if part])


def _run_async_blocking(awaitable):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result_box: Dict[str, Any] = {}
    error_box: Dict[str, BaseException] = {}

    def _runner() -> None:
        try:
            result_box["value"] = asyncio.run(awaitable)
        except BaseException as exc:  # pragma: no cover - defensive bridge
            error_box["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    if "error" in error_box:
        raise error_box["error"]
    return result_box.get("value")

FORBIDDEN_EXTERNAL_FIELDS = {"provider", "channel", "route", "internal_model", "task_backend"}

RECORD_TYPE_IMAGE = "image"
RECORD_TYPE_VIDEO = "video"
RECORD_TYPE_ASSET = "asset"
RECORD_TYPE_AUDIO = "audio"
RECORD_TYPE_EDITING = "editing"

OWNERSHIP_MODE_PROJECT = "project"
OWNERSHIP_MODE_STANDALONE = "standalone"
VALID_OWNERSHIP_MODES = {OWNERSHIP_MODE_PROJECT, OWNERSHIP_MODE_STANDALONE}

TARGET_TYPE_PANEL = "panel"
TARGET_TYPE_SHARED_RESOURCE = "shared_resource"
TARGET_TYPE_EPISODE_RECORD = "episode_record"
VALID_TARGET_TYPES = {TARGET_TYPE_PANEL, TARGET_TYPE_SHARED_RESOURCE, TARGET_TYPE_EPISODE_RECORD}

STATUS_QUEUED = "queued"
STATUS_PROCESSING = "processing"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

IMAGE_MODE_TEXT = "text_to_image"
IMAGE_MODE_IMAGE = "image_to_image"
VALID_IMAGE_MODES = {IMAGE_MODE_TEXT, IMAGE_MODE_IMAGE}

IMAGE_MODEL_LOW_COST = "low_cost"
IMAGE_MODEL_STABLE = "stable"
VALID_IMAGE_MODELS = {IMAGE_MODEL_LOW_COST, IMAGE_MODEL_STABLE}
VALID_IMAGE_RESOLUTIONS = {"1k", "2k", "4k"}

VIDEO_TYPE_STANDARD = "standard"
VIDEO_TYPE_DIGITAL_HUMAN = "digital_human"
VALID_VIDEO_TYPES = {VIDEO_TYPE_STANDARD, VIDEO_TYPE_DIGITAL_HUMAN}

VIDEO_MODEL_Q2 = "vidu_q2"
VIDEO_MODEL_Q3 = "vidu_q3"
VIDEO_MODEL_DIGITAL_HUMAN = "digital_human"
VALID_VIDEO_MODELS = {VIDEO_MODEL_Q2, VIDEO_MODEL_Q3, VIDEO_MODEL_DIGITAL_HUMAN}

ASSET_TYPE_CHARACTER = "character"
ASSET_TYPE_SCENE = "scene"
ASSET_TYPE_PROP = "prop"
VALID_ASSET_TYPES = {ASSET_TYPE_CHARACTER, ASSET_TYPE_SCENE, ASSET_TYPE_PROP}

IMAGE_MODEL_LABELS = {IMAGE_MODEL_LOW_COST: "低价版", IMAGE_MODEL_STABLE: "稳定版"}
VIDEO_MODEL_LABELS = {VIDEO_MODEL_Q2: "Vidu Q2", VIDEO_MODEL_Q3: "Vidu Q3", VIDEO_MODEL_DIGITAL_HUMAN: "数字人"}
ASSET_TYPE_LABELS = {ASSET_TYPE_CHARACTER: "人物", ASSET_TYPE_SCENE: "场景", ASSET_TYPE_PROP: "道具"}
OWNERSHIP_MODE_LABELS = {OWNERSHIP_MODE_PROJECT: "项目内", OWNERSHIP_MODE_STANDALONE: "独立"}
TARGET_TYPE_LABELS = {TARGET_TYPE_PANEL: "分镜", TARGET_TYPE_SHARED_RESOURCE: "共享资源", TARGET_TYPE_EPISODE_RECORD: "剧集记录"}
STATUS_LABELS = {
    STATUS_QUEUED: "排队中",
    STATUS_PROCESSING: "生成中",
    "waiting_upstream": "生成中",
    STATUS_COMPLETED: "已完成",
    STATUS_FAILED: "失败",
    AUDIO_STATUS_RUNNING: "生成中",
    AUDIO_STATUS_SUCCESS: "已完成",
    AUDIO_STATUS_FAILED: "失败",
    AUDIO_STATUS_EXPIRED: "已过期",
}

USER_STATUS_GENERATING = "generating"
USER_STATUS_COMPLETED = "completed"
USER_STATUS_FAILED = "failed"

FAILURE_REASON_TIMEOUT = "timeout"
FAILURE_REASON_VIOLATION = "violation"
FAILURE_REASON_INVALID = "invalid"
FAILURE_REASON_GENERIC = "generic"

USER_STATUS_LABELS = {
    USER_STATUS_GENERATING: "生成中",
    USER_STATUS_COMPLETED: "完成",
    USER_STATUS_FAILED: "失败",
}

USER_FAILURE_MESSAGES = {
    FAILURE_REASON_TIMEOUT: "超时",
    FAILURE_REASON_VIOLATION: "内容违规",
    FAILURE_REASON_INVALID: "参数有误",
    FAILURE_REASON_GENERIC: "系统繁忙，请稍后重试",
}
IMAGE_MODEL_TO_INTERNAL = {IMAGE_MODEL_LOW_COST: "nano-banana-2", IMAGE_MODEL_STABLE: "nano-banana-pro-vip"}
VIDEO_MODEL_TO_INTERNAL = {
    VIDEO_MODEL_Q2: "runninghub-vidu-q2-pro",
    VIDEO_MODEL_Q3: "runninghub-vidu-q3-pro",
    VIDEO_MODEL_DIGITAL_HUMAN: "suchuang-digital-human",
}
ASSET_TYPE_TO_RESOURCE_TYPE = {
    ASSET_TYPE_CHARACTER: ResourceTypeEnum.CHARACTER_REF.value,
    ASSET_TYPE_SCENE: ResourceTypeEnum.SCENE_REF.value,
    ASSET_TYPE_PROP: ResourceTypeEnum.PROP_REF.value,
}

IMAGE_TIER_RESOLUTION_COSTS = {
    IMAGE_MODEL_LOW_COST: {"1k": 2, "2k": 2, "4k": 3},
    IMAGE_MODEL_STABLE: {"1k": 9, "2k": 11, "4k": 13},
}
VIDEO_Q2_PRICING = {
    "540p": {1: 7, 2: 8, 3: 9, 4: 10, 5: 11, 6: 12, 7: 13, 8: 14, 9: 15, 10: 16},
    "720p": {1: 9, 2: 10, 3: 11, 4: 12, 5: 13, 6: 14, 7: 15, 8: 16, 9: 18, 10: 19},
    "1080p": {1: 21, 2: 23, 3: 26, 4: 28, 5: 30, 6: 32, 7: 34, 8: 36, 9: 39, 10: 41},
}
VIDEO_Q3_PRICING = {
    "360p": {3: 10, 5: 12, 8: 16, 10: 18},
    "540p": {3: 12, 5: 14, 8: 18, 10: 20},
    "720p": {3: 16, 5: 18, 8: 24, 10: 28},
    "1080p": {3: 24, 5: 28, 8: 36, 10: 42},
    "2k": {3: 30, 5: 35, 8: 44, 10: 50},
}
DIGITAL_HUMAN_PRICING = {5: 18, 10: 32}


def public_error_payload(error: str, message: str, *, retryable: bool = False, field: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": False, "error": error, "message": message, "retryable": retryable}
    if field:
        payload["field"] = field
    return payload


def public_http_error(
    status_code: int,
    error: str,
    message: str,
    *,
    retryable: bool = False,
    field: Optional[str] = None,
) -> HTTPException:
    return HTTPException(status_code=status_code, detail=public_error_payload(error, message, retryable=retryable, field=field))


def _now() -> datetime:
    return datetime.utcnow()


INLINE_PREVIEW_CACHE_PREFIX = "generation:inline_preview"
INLINE_PREVIEW_TTL_SECONDS = 60 * 60


def _inline_preview_cache_key(record_id: int) -> str:
    namespace = str(getattr(settings, "TASK_QUEUE_NAMESPACE", "aidrama") or "aidrama").strip()
    return f"{namespace}:{INLINE_PREVIEW_CACHE_PREFIX}:{record_id}"


def _is_inline_data_image(value: str) -> bool:
    return str(value or "").strip().startswith("data:image/")


def _set_inline_preview_cache(record_id: int, preview_url: str) -> bool:
    content = str(preview_url or "").strip()
    if not content:
        return False
    try:
        client = get_redis_client()
        client.setex(_inline_preview_cache_key(record_id), INLINE_PREVIEW_TTL_SECONDS, content)
        return True
    except Exception:
        return False


def _get_inline_preview_cache(record_id: int) -> Optional[str]:
    try:
        client = get_redis_client()
        value = client.get(_inline_preview_cache_key(record_id))
    except Exception:
        return None
    content = str(value or "").strip()
    return content or None


def _clear_inline_preview_cache(record_id: int) -> None:
    try:
        client = get_redis_client()
        client.delete(_inline_preview_cache_key(record_id))
    except Exception:
        return


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _parse_external_datetime(value: Optional[str], *, field_name: str) -> Optional[datetime]:
    source = str(value or "").strip()
    if not source:
        return None
    normalized = source.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        raise public_http_error(400, "invalid_request", f"{field_name} 不合法", field=field_name)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _encode_optional_id(value: Optional[int]) -> Optional[str]:
    return encode_id(value) if value else None


def _normalize_assistant_session_id(params_internal: Dict[str, Any]) -> Optional[str]:
    raw_value = params_internal.get("assistant_session_id")
    if raw_value in (None, ""):
        return None
    try:
        return encode_id(int(raw_value))
    except Exception:
        text = str(raw_value).strip()
        return text or None


def _record_id(record: GenerationRecord) -> str:
    return encode_id(record.id)


def _ensure_no_internal_keys(payload: Dict[str, Any]) -> None:
    for key in FORBIDDEN_EXTERNAL_FIELDS:
        if key in payload:
            raise public_http_error(400, "invalid_request", "请求参数包含内部字段，禁止访问", field=key)


def _cleanup_expired_temporary_points(user: User, session: Session) -> None:
    now = _now()
    if user.temporary_expire_at and user.temporary_expire_at < now:
        user.temporary_points = 0
        user.temporary_expire_at = None
        session.add(user)
        session.commit()
        session.refresh(user)


def _normalize_ownership_mode(value: Optional[str]) -> str:
    mode = str(value or OWNERSHIP_MODE_STANDALONE).strip().lower()
    if mode not in VALID_OWNERSHIP_MODES:
        raise public_http_error(400, "invalid_request", "ownership_mode 不合法", field="ownership_mode")
    return mode


def _normalize_target_type(value: Optional[str]) -> Optional[str]:
    if value is None or str(value).strip() == "":
        return None
    target_type = str(value).strip().lower()
    if target_type not in VALID_TARGET_TYPES:
        raise public_http_error(400, "invalid_target", "target_type 不合法", field="target_type")
    return target_type


def _normalize_image_mode(value: Optional[str]) -> str:
    mode = str(value or IMAGE_MODE_TEXT).strip().lower()
    if mode not in VALID_IMAGE_MODES:
        raise public_http_error(400, "invalid_request", "图片生成模式不合法", field="mode")
    return mode


def _normalize_image_model(value: Optional[str]) -> str:
    model = str(value or IMAGE_MODEL_STABLE).strip().lower()
    if model not in VALID_IMAGE_MODELS:
        raise public_http_error(400, "invalid_model", "图片模型不合法", field="model")
    return model


def _normalize_image_resolution(value: Optional[str]) -> str:
    resolution = str(value or "2k").strip().lower()
    if resolution not in VALID_IMAGE_RESOLUTIONS:
        raise public_http_error(400, "invalid_resolution", "图片画质不合法", field="resolution")
    return resolution


def _normalize_video_type(value: Optional[str]) -> str:
    video_type = str(value or VIDEO_TYPE_STANDARD).strip().lower()
    if video_type not in VALID_VIDEO_TYPES:
        raise public_http_error(400, "invalid_request", "video_type 不合法", field="video_type")
    return video_type


def _normalize_video_model(value: Optional[str], video_type: str) -> str:
    default_model = VIDEO_MODEL_DIGITAL_HUMAN if video_type == VIDEO_TYPE_DIGITAL_HUMAN else VIDEO_MODEL_Q2
    model = str(value or default_model).strip().lower()
    if model not in VALID_VIDEO_MODELS:
        raise public_http_error(400, "invalid_model", "视频模型不合法", field="model")
    if video_type == VIDEO_TYPE_DIGITAL_HUMAN and model != VIDEO_MODEL_DIGITAL_HUMAN:
        raise public_http_error(400, "invalid_model", "数字人模式仅支持数字人模型", field="model")
    if video_type != VIDEO_TYPE_DIGITAL_HUMAN and model == VIDEO_MODEL_DIGITAL_HUMAN:
        raise public_http_error(400, "invalid_model", "普通视频模式不支持数字人模型", field="model")
    return model


def _normalize_video_resolution(value: Optional[str], model: str) -> str:
    resolution = str(value or "720p").strip().lower()
    valid_map = {
        VIDEO_MODEL_Q2: {"540p", "720p", "1080p"},
        VIDEO_MODEL_Q3: {"360p", "540p", "720p", "1080p", "2k"},
        VIDEO_MODEL_DIGITAL_HUMAN: {"720p"},
    }
    if resolution not in valid_map[model]:
        raise public_http_error(400, "invalid_resolution", "视频分辨率不合法", field="resolution")
    return resolution


def _normalize_duration(value: Any) -> int:
    try:
        duration = int(value or 5)
    except Exception:
        raise public_http_error(400, "invalid_duration", "duration 不合法", field="duration")
    if duration < 1 or duration > 16:
        raise public_http_error(400, "invalid_duration", "duration 超出允许范围", field="duration")
    return duration


def _normalize_aspect_ratio(value: Optional[str]) -> str:
    ratio = str(value or "16:9").strip()
    if ratio not in {"16:9", "9:16", "1:1", "4:3"}:
        raise public_http_error(400, "invalid_request", "aspect_ratio 不合法", field="aspect_ratio")
    return ratio


def _normalize_asset_type(value: Optional[str]) -> str:
    asset_type = str(value or "").strip().lower()
    if asset_type not in VALID_ASSET_TYPES:
        raise public_http_error(400, "invalid_request", "asset_type 不合法", field="asset_type")
    return asset_type


def _prompt_summary(prompt: str) -> str:
    text = str(prompt or "").strip()
    return f"{text[:42]}..." if len(text) > 42 else text


def _looks_like_image_url(url: Optional[str]) -> bool:
    source = str(url or "").strip().lower()
    if not source:
        return False
    if any(token in source for token in ("image/", ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")):
        return True
    return "x-oss-process=image/" in source


def _derive_record_thumbnail_url(record_type: str, preview_url: str, current_thumbnail_url: Optional[str] = None) -> Optional[str]:
    source = str(preview_url or "").strip()
    existing = str(current_thumbnail_url or "").strip()
    if record_type == RECORD_TYPE_VIDEO:
        if _looks_like_image_url(existing):
            return existing
        if is_oss_url(source):
            return build_oss_video_snapshot_url(source) or None
        return None
    if record_type == RECORD_TYPE_EDITING:
        if _looks_like_image_url(existing):
            return existing
        lowered = source.lower()
        if lowered.endswith(".mp4") and is_oss_url(source):
            return build_oss_video_snapshot_url(source) or None
        return existing or None
    if is_oss_url(source):
        return build_oss_thumbnail_url(source) or source
    return source or None


def _normalize_duration_price(table: Dict[int, int], duration: int) -> int:
    if duration in table:
        return table[duration]
    keys = sorted(table.keys())
    for item in keys:
        if duration <= item:
            return table[item]
    return table[keys[-1]]


def _estimate_video_points(model: str, resolution: str, duration: int) -> int:
    if model == VIDEO_MODEL_Q2:
        table = VIDEO_Q2_PRICING.get(resolution) or VIDEO_Q2_PRICING["720p"]
        return _normalize_duration_price(table, min(duration, 10))
    if model == VIDEO_MODEL_Q3:
        table = VIDEO_Q3_PRICING.get(resolution) or VIDEO_Q3_PRICING["720p"]
        return _normalize_duration_price(table, 10 if duration > 10 else duration)
    return DIGITAL_HUMAN_PRICING[10 if duration > 5 else 5]


def _normalize_productized_image_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        normalized = normalize_image_request(payload)
    except ValueError as exc:
        field_name = str(exc)
        message_map = {
            "invalid_model": ("invalid_model", "当前图片模型暂不可用", "model_code"),
            "model_not_configured": ("invalid_model", "当前图片模型尚未在服务端完成配置", "model_code"),
            "invalid_generation_type": ("invalid_request", "当前图片模型不支持该生成方式", "mode"),
            "prompt": ("invalid_request", "prompt 不能为空", "prompt"),
            "reference_images": ("invalid_request", "当前生成方式至少需要一张参考图", "reference_images"),
            "reference_images_public_url": ("invalid_request", "gpt-image-2 图生图当前仅支持 OSS 或公网可访问参考图", "reference_images"),
        }
        error_code, message, field = message_map.get(field_name, ("invalid_request", "当前图片请求参数不合法，请检查后重试", None))
        raise public_http_error(400, error_code, message, field=field)
    return normalized


def _estimate_image_public_params(session: Session, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    del session
    _ensure_no_internal_keys(payload)
    ownership_mode = _normalize_ownership_mode(payload.get("ownership_mode"))
    estimate_payload = dict(payload or {})
    estimate_payload["prompt"] = str(estimate_payload.get("prompt") or "estimate").strip() or "estimate"
    normalized = _normalize_productized_image_request(estimate_payload)
    price = estimate_image_price(normalized["model_code"], normalized["generation_type"], normalized)
    public_params = {
        "mode": normalized["generation_type"],
        "mode_label": normalized["generation_type_label"],
        "generation_type": normalized["generation_type"],
        "generation_type_label": normalized["generation_type_label"],
        "model_code": normalized["model_code"],
        "model": normalized["model_code"],
        "model_label": normalized["model_name"],
        "resolution": None if normalized["model_code"] == MODEL_GPT_IMAGE_2_FAST else normalized["resolution"],
        "quality": normalized.get("quality"),
        "quality_mode": normalized.get("quality"),
        "quality_mode_label": normalized.get("quality_label"),
        "quality_label": None
        if normalized["model_code"] == MODEL_GPT_IMAGE_2_FAST
        else " · ".join([part for part in [normalized.get("quality_label"), normalized["resolution"].upper()] if part]),
        "aspect_ratio": normalized["aspect_ratio"],
        "aspect_ratio_label": normalized["aspect_ratio"],
        "reference_image_count": len(normalized["reference_images"]),
        "ownership_mode": ownership_mode,
        "ownership_mode_label": OWNERSHIP_MODE_LABELS[ownership_mode],
        "cost_price": price["cost_price"],
        "suggested_price": price["suggested_price"],
        "sell_price_points": int(price["sell_price_points"]),
        "pricing_note": price["pricing_note"],
        "pricing_rule_type": price["pricing_rule_type"],
        "pricing_details": price["pricing_details"],
        "feature_note": normalized.get("feature_note") or "",
    }
    return public_params, int(price["sell_price_points"])


def _estimate_video_public_params(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    _ensure_no_internal_keys(payload)
    ownership_mode = _normalize_ownership_mode(payload.get("ownership_mode"))
    video_type = _normalize_video_type(payload.get("video_type"))
    model = _normalize_video_model(payload.get("model"), video_type)
    resolution = _normalize_video_resolution(payload.get("resolution"), model)
    duration = _normalize_duration(payload.get("duration"))
    aspect_ratio = _normalize_aspect_ratio(payload.get("aspect_ratio"))
    reference_images = [str(item).strip() for item in payload.get("reference_images", []) if str(item).strip()]
    reference_videos = [str(item).strip() for item in payload.get("reference_videos", []) if str(item).strip()]
    audio_enabled = bool(payload.get("audio_enabled"))
    estimate_points = _estimate_video_points(model, resolution, duration)
    public_params = {
        "video_type": video_type,
        "video_type_label": "数字人" if video_type == VIDEO_TYPE_DIGITAL_HUMAN else "普通视频",
        "model": model,
        "model_label": VIDEO_MODEL_LABELS[model],
        "resolution": resolution,
        "resolution_label": resolution.upper() if resolution.endswith("k") else resolution,
        "duration": duration,
        "duration_label": f"{duration}秒",
        "aspect_ratio": aspect_ratio,
        "aspect_ratio_label": aspect_ratio,
        "reference_image_count": len(reference_images),
        "reference_video_count": len(reference_videos),
        "audio_enabled": audio_enabled,
        "ownership_mode": ownership_mode,
        "ownership_mode_label": OWNERSHIP_MODE_LABELS[ownership_mode],
    }
    return public_params, estimate_points


def _combined_audio_reference_urls(normalized: Dict[str, Any]) -> List[str]:
    urls: List[str] = []
    for value in normalized.get("audio_refs") or []:
        url = str(value or "").strip()
        if url and url not in urls:
            urls.append(url)
    audio_url = str(normalized.get("audio_url") or "").strip()
    if audio_url and audio_url not in urls:
        urls.append(audio_url)
    return urls


def _load_temporary_uploads_by_url(session: Session, urls: List[str]) -> Dict[str, TemporaryUploadAsset]:
    cleaned = [str(item).strip() for item in urls if str(item).strip()]
    if not cleaned:
        return {}
    rows = session.exec(
        select(TemporaryUploadAsset).where(TemporaryUploadAsset.file_url.in_(cleaned))
    ).all()
    return {str(item.file_url or "").strip(): item for item in rows}


def _load_project_video_records_by_url(session: Session, urls: List[str], *, script_id: Optional[int]) -> Dict[str, GenerationRecord]:
    cleaned = [str(item).strip() for item in urls if str(item).strip()]
    if not cleaned or not script_id:
        return {}
    rows = session.exec(
        select(GenerationRecord)
        .where(
            GenerationRecord.script_id == script_id,
            GenerationRecord.record_type == RECORD_TYPE_VIDEO,
            GenerationRecord.status == STATUS_COMPLETED,
            GenerationRecord.preview_url.in_(cleaned),
        )
        .order_by(GenerationRecord.updated_at.desc(), GenerationRecord.id.desc())
    ).all()
    resolved: Dict[str, GenerationRecord] = {}
    for item in rows:
        url = str(item.preview_url or "").strip()
        if url and url not in resolved:
            resolved[url] = item
    return resolved


def _extract_record_duration_seconds(record: GenerationRecord) -> float:
    params_public = _json_loads(record.params_public_json, {})
    params_internal = _json_loads(record.params_internal_json, {})
    raw_value = params_public.get("duration")
    if raw_value in (None, ""):
        request_payload = params_internal.get("request_payload") if isinstance(params_internal, dict) else {}
        if isinstance(request_payload, dict):
            raw_value = request_payload.get("duration")
    try:
        return float(raw_value or 0.0)
    except Exception:
        return 0.0


def _require_temporary_upload_assets(
    session: Session,
    *,
    urls: List[str],
    field_name: str,
    media_type: str,
    error_code: str,
    error_message: str,
) -> List[TemporaryUploadAsset]:
    cleaned = [str(item).strip() for item in urls if str(item).strip()]
    if not cleaned:
        return []
    assets_by_url = _load_temporary_uploads_by_url(session, cleaned)
    now = datetime.utcnow()
    assets: List[TemporaryUploadAsset] = []
    for url in cleaned:
        asset = assets_by_url.get(url)
        if not asset or str(asset.media_type or "").strip().lower() != media_type:
            raise public_http_error(400, error_code, error_message, field=field_name)
        if asset.expires_at <= now:
            raise public_http_error(400, error_code, f"{error_message}（素材已过期，请重新上传）", field=field_name)
        assets.append(asset)
    return assets


def _validate_reference_media_duration_values(
    durations: List[float],
    *,
    field_name: str,
    media_label: str,
) -> float:
    if not durations:
        return 0.0
    total_duration = 0.0
    for value in durations:
        duration = float(value or 0.0)
        if duration < 2 or duration > 15:
            raise public_http_error(
                400,
                "reference_media_duration_invalid",
                f"{media_label}单段时长需在 2 到 15 秒之间，请重新上传后再试",
                field=field_name,
            )
        total_duration += duration
    if total_duration > 15:
        raise public_http_error(
            400,
            "reference_media_duration_exceeded",
            f"{media_label}总时长不能超过 15 秒，请减少素材后再试",
            field=field_name,
        )
    return total_duration


def _validate_reference_media_duration(
    assets: List[TemporaryUploadAsset],
    *,
    field_name: str,
    media_label: str,
) -> float:
    return _validate_reference_media_duration_values(
        [float(asset.duration_seconds or 0.0) for asset in assets],
        field_name=field_name,
        media_label=media_label,
    )


def _resolve_seedance_20_video_ref_durations(
    session: Session,
    normalized: Dict[str, Any],
    payload: Dict[str, Any],
) -> List[float]:
    video_urls = [str(item).strip() for item in (normalized.get("video_refs") or []) if str(item).strip()]
    if not video_urls:
        return []
    upload_assets = _load_temporary_uploads_by_url(session, video_urls)
    script_id = None
    if _normalize_ownership_mode(payload.get("ownership_mode")) == OWNERSHIP_MODE_PROJECT:
        script_id = _decode_external_id(payload.get("project_id"), field_name="project_id")
    project_records = _load_project_video_records_by_url(session, video_urls, script_id=script_id)
    now = datetime.utcnow()
    durations: List[float] = []

    for url in video_urls:
        asset = upload_assets.get(url)
        if asset and str(asset.media_type or "").strip().lower() == "video":
            if asset.expires_at > now:
                durations.append(float(asset.duration_seconds or 0.0))
                continue
        record = project_records.get(url)
        if record:
            durations.append(_extract_record_duration_seconds(record))
            continue
        raise public_http_error(
            400,
            "video_refs_unsupported_source",
            "Seedance 2.0 多模态的参考视频仅支持平台上传素材或当前项目已生成的分镜视频",
            field="video_refs",
        )
    return durations


def _enrich_seedance_20_reference_request(session: Session, normalized: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    if normalized.get("model_code") not in {"seedance_20", "seedance_20_fast"}:
        return normalized
    if normalized.get("generation_type") != GEN_REFERENCE:
        return normalized

    audio_urls = _combined_audio_reference_urls(normalized)
    if audio_urls and not ((normalized.get("image_refs") or []) or (normalized.get("video_refs") or [])):
        raise public_http_error(
            400,
            "audio_refs_requires_visual_ref",
            "参考音频必须搭配参考图或参考视频一起使用",
            field="audio_refs",
        )

    video_durations = _resolve_seedance_20_video_ref_durations(session, normalized, payload)
    audio_assets = _require_temporary_upload_assets(
        session,
        urls=audio_urls,
        field_name="audio_url" if normalized.get("audio_url") and not (normalized.get("audio_refs") or []) else "audio_refs",
        media_type="audio",
        error_code="audio_refs_upload_only",
        error_message="Seedance 2.0 多模态的参考音频仅支持平台上传素材",
    )

    input_video_duration = 0
    if video_durations:
        input_video_duration = int(
            math.ceil(
                _validate_reference_media_duration_values(
                    video_durations,
                    field_name="video_refs",
                    media_label="参考视频",
                )
            )
        )
    if audio_assets:
        _validate_reference_media_duration(
            audio_assets,
            field_name="audio_refs",
            media_label="参考音频",
        )

    enriched = dict(normalized)
    enriched["input_video_duration"] = input_video_duration
    return enriched


def _normalize_productized_video_request(session: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_video_request(payload)
    return _enrich_seedance_20_reference_request(session, normalized, payload)


def _resolve_workflow_profile_for_payload(session: Session, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    script = None
    episode = None
    panel = None

    target_type = str(payload.get("target_type") or "").strip()
    target_id = str(payload.get("target_id") or "").strip()
    episode_id = str(payload.get("episode_id") or "").strip()
    project_id = str(payload.get("project_id") or "").strip()

    try:
        if target_type == "panel" and target_id:
            panel = session.get(Panel, decode_id(target_id))
            if panel:
                episode = session.get(Episode, panel.episode_id)
        elif episode_id:
            episode = session.get(Episode, decode_id(episode_id))
        if episode:
            script = session.get(Script, episode.script_id)
        elif project_id:
            script = session.get(Script, decode_id(project_id))
    except Exception:
        return None

    if not script:
        return None
    storyboard_mode = getattr(panel, "storyboard_mode", None) if panel is not None else getattr(episode, "storyboard_mode", None)
    return resolve_effective_workflow_profile(script, episode=episode, storyboard_mode=storyboard_mode)


def _resolve_target_video_duration(session: Session, payload: Dict[str, Any]) -> Optional[int]:
    target_type = str(payload.get("target_type") or "").strip()
    target_id = str(payload.get("target_id") or "").strip()
    if target_type != "panel" or not target_id:
      return None
    try:
        panel = session.get(Panel, decode_id(target_id))
    except Exception:
        return None
    if not panel:
        return None
    duration = int(getattr(panel, "recommended_duration_seconds", 0) or 0)
    return duration if duration > 0 else None


def _apply_video_workflow_defaults(session: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    next_payload = dict(payload or {})
    profile = _resolve_workflow_profile_for_payload(session, next_payload)
    target_duration = _resolve_target_video_duration(session, next_payload)
    if not profile and target_duration is None:
        return next_payload

    video_profile = (profile or {}).get("video") or {}
    if profile and not str(next_payload.get("model_code") or next_payload.get("model") or "").strip():
        next_payload["model_code"] = video_profile.get("model_code")
    if profile and not str(next_payload.get("generation_type") or "").strip():
        next_payload["generation_type"] = video_profile.get("generation_type")
    if "duration" not in next_payload:
        next_payload["duration"] = target_duration or video_profile.get("duration")
    if profile and not str(next_payload.get("resolution") or "").strip():
        next_payload["resolution"] = video_profile.get("resolution")
    if profile and not str(next_payload.get("aspect_ratio") or "").strip():
        next_payload["aspect_ratio"] = profile.get("aspect_ratio")
    if profile and "audio_enabled" not in next_payload:
        next_payload["audio_enabled"] = bool(video_profile.get("audio_enabled"))
    if profile and "camera_fixed" not in next_payload:
        next_payload["camera_fixed"] = bool(video_profile.get("camera_fixed"))
    if profile and "real_person_mode" not in next_payload:
        next_payload["real_person_mode"] = bool(video_profile.get("real_person_mode"))
    if profile and "web_search" not in next_payload:
        next_payload["web_search"] = bool(video_profile.get("web_search"))
    if profile and not str(next_payload.get("quality_mode") or "").strip():
        next_payload["quality_mode"] = str(video_profile.get("quality_mode") or "").strip()
    if profile and not str(next_payload.get("motion_strength") or "").strip():
        next_payload["motion_strength"] = str(video_profile.get("motion_strength") or "").strip()
    if profile and not str(next_payload.get("style") or "").strip():
        next_payload["style"] = (profile.get("style") or {}).get("label") or ""
    return next_payload


def _enhance_image_prompt_for_submission(
    session: Session,
    *,
    binding: Dict[str, Any],
    payload: Dict[str, Any],
    prompt: str,
) -> str:
    script = binding.get("script")
    episode = binding.get("episode")
    panel = binding.get("panel")
    workflow_profile = (
        resolve_effective_workflow_profile(
            script,
            episode=episode,
            storyboard_mode=getattr(panel, "storyboard_mode", None) if panel is not None else getattr(episode, "storyboard_mode", None),
        )
        if script
        else _resolve_workflow_profile_for_payload(session, payload)
    )
    return augment_prompt_with_style(
        prompt,
        workflow_profile,
        label_fallback=str(getattr(script, "style_preset", "") or payload.get("style") or "").strip(),
    )


def _estimate_video_public_params(session: Session, payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    payload = _apply_video_workflow_defaults(session, payload)
    _ensure_no_internal_keys(payload)
    ownership_mode = _normalize_ownership_mode(payload.get("ownership_mode"))
    request_summary = {
        "ownership_mode": ownership_mode,
        "model_code": payload.get("model_code") or payload.get("model"),
        "generation_type": payload.get("generation_type"),
        "duration": payload.get("duration"),
        "resolution": payload.get("resolution"),
        "aspect_ratio": payload.get("aspect_ratio"),
        "image_ref_count": len(payload.get("image_refs") or payload.get("reference_images") or []),
        "video_ref_count": len(payload.get("video_refs") or payload.get("reference_videos") or []),
        "audio_ref_count": len(payload.get("audio_refs") or []),
        "has_first_frame": bool(payload.get("first_frame") or payload.get("start_frame")),
        "has_last_frame": bool(payload.get("last_frame")),
        "real_person_mode": bool(payload.get("real_person_mode")),
        "web_search": bool(payload.get("web_search")),
    }
    try:
        normalized = _normalize_productized_video_request(session, payload)
    except ValueError as exc:
        field_name = str(exc)
        logger.warning("video_estimate_rejected_value_error summary=%s reason=%s", request_summary, field_name)
        message_map = {
            "invalid_model": ("invalid_model", "当前模型暂不可用", "model_code"),
            "invalid_generation_type": ("invalid_request", "当前模型不支持该功能类型", "generation_type"),
            "duration": ("invalid_duration", "duration 不合法", "duration"),
            "resolution": ("invalid_resolution", "resolution 不合法", "resolution"),
            "aspect_ratio": ("invalid_request", "aspect_ratio 不合法", "aspect_ratio"),
            "quality_mode": ("invalid_request", "quality_mode 不合法", "quality_mode"),
            "motion_strength": ("invalid_request", "motion_strength 不合法", "motion_strength"),
            "image_refs": ("invalid_request", "参考图数量或必填要求不合法", "image_refs"),
            "video_refs": ("invalid_request", "参考视频数量或必填要求不合法", "video_refs"),
            "audio_refs": ("invalid_request", "参考音频数量或必填要求不合法", "audio_refs"),
            "first_frame": ("invalid_request", "当前功能需要首帧图片", "first_frame"),
            "last_frame": ("invalid_request", "当前功能需要尾帧图片", "last_frame"),
            "reference_assets": ("invalid_request", "当前功能至少需要一张参考图或参考视频", "image_refs"),
        }
        error_code, message, field = message_map.get(field_name, ("invalid_request", "当前请求参数不合法，请检查后重试", None))
        raise public_http_error(400, error_code, message, field=field)
    except HTTPException as exc:
        logger.warning("video_estimate_rejected_http_exception summary=%s detail=%s", request_summary, exc.detail)
        raise
    price = estimate_video_price(normalized["model_code"], normalized["generation_type"], normalized)
    if not price:
        logger.warning("video_estimate_missing_price summary=%s normalized=%s", request_summary, {
            "model_code": normalized["model_code"],
            "generation_type": normalized["generation_type"],
            "duration": normalized["duration"],
            "resolution": normalized["resolution"],
            "aspect_ratio": normalized["aspect_ratio"],
            "input_video_duration": normalized.get("input_video_duration"),
        })
        raise public_http_error(400, "invalid_request", "当前组合价格待补充，暂不支持直接生成", retryable=False)

    public_params = {
        "model_code": normalized["model_code"],
        "model": normalized["model_code"],
        "model_label": normalized["model_name"],
        "generation_type": normalized["generation_type"],
        "generation_type_label": normalized["generation_type_label"],
        "resolution": normalized["resolution"],
        "resolution_label": normalized["resolution"].upper() if normalized["resolution"].endswith("k") else normalized["resolution"],
        "duration": normalized["duration"],
        "duration_label": f"{normalized['duration']}秒",
        "aspect_ratio": normalized["aspect_ratio"],
        "aspect_ratio_label": normalized["aspect_ratio"],
        "reference_image_count": len(normalized["image_refs"]),
        "reference_video_count": len(normalized["video_refs"]),
        "reference_audio_count": len(_combined_audio_reference_urls(normalized)),
        "audio_enabled": normalized["audio_enabled"],
        "camera_fixed": normalized["camera_fixed"],
        "real_person_mode": bool(normalized.get("real_person_mode")),
        "web_search": bool(normalized.get("web_search")),
        "quality_mode": normalized["quality_mode"],
        "motion_strength": normalized["motion_strength"],
        "input_video_duration": int(normalized.get("input_video_duration") or 0),
        "ownership_mode": ownership_mode,
        "ownership_mode_label": OWNERSHIP_MODE_LABELS[ownership_mode],
        "prompt_summary": _prompt_summary(str(payload.get("prompt") or "")),
        "cost_price": price["cost_price"],
        "suggested_price": price["suggested_price"],
        "sell_price_points": price["sell_price_points"],
        "pricing_note": price["pricing_note"],
        "pricing_rule_type": price["pricing_rule_type"],
        "pricing_details": price["pricing_details"],
    }
    return public_params, int(price["sell_price_points"])


def estimate_image_generation(session: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    public_params, estimate_points = _estimate_image_public_params(session, payload)
    return {
        "success": True,
        "estimate_points": estimate_points,
        "currency_label": "灵感值",
        "resolved": public_params,
        "notes": [],
    }


def estimate_video_generation(session: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    public_params, estimate_points = _estimate_video_public_params(session, payload)
    return {
        "success": True,
        "estimate_points": estimate_points,
        "currency_label": "灵感值",
        "resolved": public_params,
        "notes": [],
    }


def get_video_generation_catalog(session: Session) -> Dict[str, Any]:
    del session
    return {"success": True, "data": build_video_catalog()}


def get_image_generation_catalog(session: Session) -> Dict[str, Any]:
    del session
    return {"success": True, "data": build_image_catalog()}


def estimate_audio_generation(session: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_no_internal_keys(payload)
    try:
        normalized = normalize_audio_request(payload)
        price = estimate_audio_price(normalized)
    except ValueError as exc:
        message = str(exc)
        if message == "missing_script_text":
            raise public_http_error(400, "invalid_request", "请先填写配音文本或上传文本文件", field="script_text")
        if message == "invalid_ability_type":
            raise public_http_error(400, "invalid_request", "ability_type 不合法", field="ability_type")
        if message == "invalid_tier_code":
            raise public_http_error(400, "invalid_request", "tier_code 不合法", field="tier_code")
        raise public_http_error(400, "invalid_request", "当前请求参数不合法，请检查后重试")
    user_token = payload.get("_current_user")
    if isinstance(user_token, User):
        price = _attach_audio_voice_activation_charge(session, user=user_token, normalized=normalized, price=price)
    resolved = {
        "ability_type": normalized["ability_type"],
        "ability_label": normalized["ability_label"],
        "tier_code": normalized["tier_code"],
        "tier_label": normalized["tier_label"],
        "model_code": normalized["model_code"],
        "voice_source_type": normalized["voice_source_type"],
        "voice_source_label": VOICE_SOURCE_LABELS.get(normalized["voice_source_type"], normalized["voice_source_type"]),
        "characters": price["characters"],
        "unit_count": price["unit_count"],
        "pricing_note": price["pricing_note"],
        "voice_activation_required": bool(price.get("voice_activation_required")),
        "voice_activation_label": price.get("voice_activation_label"),
    }
    return {
        "success": True,
        "estimate_points": int(price["sell_price_points"]),
        "currency_label": "灵感值",
        "resolved": resolved,
        "notes": [],
        "breakdown": [
            {
                "label": item["label"],
                "sell_price_points": int(item["sell_price_points"]),
            }
            for item in price["breakdown"]
        ],
    }


def get_audio_generation_catalog(session: Session) -> Dict[str, Any]:
    del session
    return {"success": True, "data": build_audio_catalog()}


def _ensure_affordable(session: Session, user: User, team: Team, estimate_points: int) -> None:
    _cleanup_expired_temporary_points(user, session)
    member_link = session.exec(
        select(TeamMemberLink).where(TeamMemberLink.team_id == team.id, TeamMemberLink.user_id == user.id)
    ).first()
    if member_link and member_link.point_quota is not None:
        remaining = member_link.point_quota - member_link.point_quota_used
        if remaining < estimate_points:
            raise public_http_error(402, "permission_denied", "当前灵感值额度不足，请调整后重试")

    if team.is_team_billing:
        if team.team_points < estimate_points:
            raise public_http_error(402, "permission_denied", "团队灵感值不足，请充值后重试")
        return

    available = user.permanent_points + user.temporary_points
    if available < estimate_points:
        raise public_http_error(402, "permission_denied", "灵感值不足，请充值后重试")


def _decode_external_id(value: Optional[str], *, field_name: str) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return decode_id(str(value))
    except Exception:
        raise public_http_error(400, "invalid_target", f"{field_name} 不合法", field=field_name)


def _require_project_binding(session: Session, team: Team, payload: Dict[str, Any]) -> Dict[str, Any]:
    ownership_mode = _normalize_ownership_mode(payload.get("ownership_mode"))
    bound: Dict[str, Any] = {
        "ownership_mode": ownership_mode,
        "script": None,
        "episode": None,
        "target_type": None,
        "target_id": None,
        "panel": None,
        "resource": None,
        "target_note": None,
    }
    if ownership_mode != OWNERSHIP_MODE_PROJECT:
        return bound

    script_id = _decode_external_id(payload.get("project_id"), field_name="project_id")
    episode_id = _decode_external_id(payload.get("episode_id"), field_name="episode_id")
    if not script_id or not episode_id:
        raise public_http_error(400, "invalid_target", "项目内模式必须指定项目和剧集")

    script = require_script_team_access(session, team, script_id)
    episode = require_episode_team_access(session, team, episode_id)
    if episode.script_id != script.id:
        raise public_http_error(400, "invalid_target", "所选剧集不属于该项目")

    target_type = _normalize_target_type(payload.get("target_type"))
    target_id = _decode_external_id(payload.get("target_id"), field_name="target_id")
    panel = None
    resource = None

    if target_type == TARGET_TYPE_PANEL:
        if not target_id:
            raise public_http_error(400, "invalid_target", "分镜目标必须指定 target_id", field="target_id")
        panel = require_panel_team_access(session, team, target_id)
        if panel.episode_id != episode.id:
            raise public_http_error(400, "invalid_target", "鐩爣鍒嗛暅涓嶅睘浜庤鍓ч泦")
        if is_nine_grid_panel_type(panel.panel_type):
            bound["target_note"] = "九宫格目标会按九宫格语义处理，不作为普通单图目标。"
    elif target_type == TARGET_TYPE_SHARED_RESOURCE:
        if target_id:
            resource = require_resource_team_access(session, team, target_id)
            if resource.script_id != script.id:
                raise public_http_error(400, "invalid_target", "目标共享资源不属于该项目")
    elif target_type == TARGET_TYPE_EPISODE_RECORD:
        target_id = None

    bound.update(
        {
            "script": script,
            "episode": episode,
            "target_type": target_type,
            "target_id": target_id,
            "panel": panel,
            "resource": resource,
        }
    )
    return bound


def _create_generation_record(
    session: Session,
    *,
    user: User,
    team: Team,
    record_type: str,
    ownership_mode: str,
    script_id: Optional[int],
    episode_id: Optional[int],
    target_type: Optional[str],
    target_id: Optional[int],
    prompt: str,
    negative_prompt: Optional[str],
    params_internal: Dict[str, Any],
    params_public: Dict[str, Any],
    estimate_points: int,
) -> GenerationRecord:
    record = GenerationRecord(
        user_id=user.id,
        team_id=team.id,
        record_type=record_type,
        ownership_mode=ownership_mode,
        script_id=script_id,
        episode_id=episode_id,
        target_type=target_type,
        target_id=target_id,
        task_id=str(uuid.uuid4()),
        status=STATUS_QUEUED,
        prompt=prompt,
        negative_prompt=negative_prompt,
        params_internal_json=_json_dumps(params_internal),
        params_public_json=_json_dumps(params_public),
        estimate_points=estimate_points,
        actual_points=0,
        created_at=_now(),
        updated_at=_now(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def _enqueue_generation_record_task(
    session: Session,
    *,
    record: GenerationRecord,
    task_type: str,
    queue_name: str,
    provider: Optional[str],
    max_retries: int,
    scope_type: Optional[str] = None,
    scope_id: Optional[int] = None,
) -> None:
    task_category = {
        RECORD_TYPE_IMAGE: "media",
        RECORD_TYPE_VIDEO: "media",
        RECORD_TYPE_AUDIO: "audio",
        RECORD_TYPE_ASSET: "resource",
    }.get(str(record.record_type or "").strip().lower())
    job = create_task_job(
        session,
        task_id=str(record.task_id),
        task_type=task_type,
        queue_name=queue_name,
        provider=provider,
        team_id=record.team_id,
        user_id=record.user_id,
        script_id=record.script_id,
        episode_id=record.episode_id,
        ownership_mode=record.ownership_mode,
        scope_type=scope_type or record.target_type or record.record_type,
        scope_id=scope_id if scope_id is not None else record.target_id,
        task_category=task_category,
        generation_record_id=record.id,
        payload={"record_id": record.id},
        message="任务已入队",
        max_retries=max_retries,
    )
    enqueue_task_job(job)


def _build_seedance20_target_context(session: Session, binding: Dict[str, Any]) -> Dict[str, Any]:
    panel = binding.get("panel")
    if not panel:
        return {}
    try:
        from services.story_segment_service import serialize_segment_workspace_item
        from services.storyboard_director_service import (
            render_video_control_line_from_structured,
            resolve_gridcell_video_prompt_structured,
        )
    except Exception:
        return {}

    script = binding.get("script")
    workspace = serialize_segment_workspace_item(
        session,
        panel,
        script_id=script.id if script else None,
    )
    grid_cells = list(workspace.get("grid_cells") or [])
    transition_to_next = str(workspace.get("transition_to_next") or getattr(panel, "transition_to_next", None) or "cut").strip() or "cut"
    shot_controls: List[str] = []
    quality_constraints: List[str] = []
    for idx, cell in enumerate(grid_cells):
        next_cell = grid_cells[idx + 1] if idx + 1 < len(grid_cells) else None
        structured = resolve_gridcell_video_prompt_structured(
            cell,
            next_cell=next_cell,
            transition_to_next=transition_to_next if idx == len(grid_cells) - 1 else "cut",
        )
        line = render_video_control_line_from_structured(structured)
        if line:
            shot_controls.append(f"镜头{idx + 1}：{line}")
        negative_constraints = str(structured.get("negative_constraints") or "").strip()
        if negative_constraints and negative_constraints not in quality_constraints:
            quality_constraints.append(negative_constraints)
    reference_assets: List[str] = []
    reference_asset_items: List[Dict[str, str]] = []
    for item in workspace.get("reference_assets") or []:
        if not isinstance(item, dict):
            continue
        name = _clean_seedance_asset_name(item.get("name") or "")
        if not name:
            continue
        reference_assets.append(_seedance_asset_token(name))
        reference_asset_items.append({
            "name": name,
            "type": str(item.get("type") or item.get("resource_type") or "").strip().lower(),
        })
    return {
        "scene_prompt": str(workspace.get("scene_prompt") or "").strip(),
        "shot_controls": shot_controls,
        "reference_assets": reference_assets,
        "reference_asset_items": reference_asset_items,
        "quality_constraints": quality_constraints,
        "storyboard_mode": str(workspace.get("storyboard_mode") or getattr(panel, "storyboard_mode", "") or "").strip().lower(),
    }


def _clean_seedance_asset_name(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^@+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _seedance_asset_token(value: Any) -> str:
    name = _clean_seedance_asset_name(value)
    return f"@{name}" if name else ""


def _sanitize_seedance_prompt_text(value: Any) -> str:
    return re.sub(r"@{2,}", "@", str(value or "").strip())


def _build_seedance20_reference_lines(normalized: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> List[str]:
    context = context or {}
    lines: List[str] = []
    reference_assets = [
        _seedance_asset_token(item)
        for item in context.get("reference_assets") or []
        if _clean_seedance_asset_name(item)
    ]
    if reference_assets:
        lines.append("项目绑定资产优先保持一致：" + "、".join(reference_assets))

    generation_type = str(normalized.get("generation_type") or "").strip()
    image_refs = list(normalized.get("image_refs") or [])
    video_refs = list(normalized.get("video_refs") or [])
    audio_refs = list(normalized.get("audio_refs") or [])
    first_frame = str(normalized.get("first_frame") or "").strip()
    last_frame = str(normalized.get("last_frame") or "").strip()
    audio_url = str(normalized.get("audio_url") or "").strip()

    if generation_type == "reference_to_video":
        if image_refs:
            lines.append(f"参考图 {len(image_refs)} 张用于锁定主体外观、场景与关键道具。")
        if video_refs:
            lines.append(f"参考视频 {len(video_refs)} 段用于约束动作轨迹、运镜节奏与切镜感觉。")
        if audio_refs or audio_url:
            lines.append("参考音频仅用于环境声、节奏和氛围，不改写主体身份。")
    elif generation_type in {"image_to_video", "start_end_to_video"}:
        if first_frame:
            lines.append("首帧图片用于锁定开场主体、服装与镜头起始状态。")
        if last_frame:
            lines.append("尾帧图片用于收束结尾状态，并保证转场落点明确。")
    return lines


SEEDANCE_PROMPT_SECTION_RE = re.compile(
    r"(?m)^(全局基础设定|分镜设定|参考映射|时间轴|质量约束|生成要求)[：:]"
)


def _extract_seedance_prompt_sections(prompt: str) -> Dict[str, str]:
    text = str(prompt or "").strip()
    if not text:
        return {}
    matches = list(SEEDANCE_PROMPT_SECTION_RE.finditer(text))
    if not matches:
        return {}
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        title = str(match.group(1) or "").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            sections[title] = content
    return sections


def _format_seedance_section(title: str, content: str) -> str:
    cleaned = _sanitize_seedance_prompt_text(content)
    if not cleaned:
        return ""
    return f"{title}：\n{cleaned}"


def _build_seedance20_structured_reference_mapping(normalized: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> str:
    context = context or {}
    video_entries = list(normalized.get("video_ref_entries") or [])
    audio_entries = list(normalized.get("audio_ref_entries") or [])
    lines: List[str] = []

    for index, entry in enumerate(video_entries, start=1):
        label = _clean_seedance_asset_name(entry.get("label") or "")
        token = f"视频{index}（{label}）" if label else f"视频{index}"
        lines.append(f"{token}：用于约束动作轨迹、运镜节奏与切镜感觉。")

    for index, entry in enumerate(audio_entries, start=1):
        label = _clean_seedance_asset_name(entry.get("label") or "")
        token = f"音频{index}（{label}）" if label else f"音频{index}"
        lines.append(f"{token}：用于控制环境音、台词氛围或节奏，不改写主体动作与身份。")

    return "\n".join(lines).strip()


def _compose_seedance20_comic_reference_prompt(
    base_prompt: str,
    *,
    normalized: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    style_preset: str = "",
) -> str:
    context = context or {}
    sections = _extract_seedance_prompt_sections(base_prompt)
    global_setting = _sanitize_seedance_prompt_text(
        sections.get("全局基础设定")
        or sections.get("分镜设定")
        or str(context.get("scene_prompt") or "").strip()
    )
    timeline = _sanitize_seedance_prompt_text(sections.get("时间轴") or str(base_prompt or "").strip())
    quality_constraints = _sanitize_seedance_prompt_text(sections.get("质量约束") or "；".join([
        str(item).strip()
        for item in context.get("quality_constraints") or []
        if str(item).strip()
    ]))
    reference_mapping = _build_seedance20_structured_reference_mapping(normalized, context)

    requirement_lines: List[str] = []
    if style_preset:
        requirement_lines.append(f"风格基线：{style_preset}")
    duration = normalized.get("duration")
    aspect_ratio = str(normalized.get("aspect_ratio") or "").strip()
    resolution = str(normalized.get("resolution") or "").strip()
    if duration and aspect_ratio and resolution:
        requirement_lines.append(f"输出规格：{duration}秒，{aspect_ratio}，{resolution}")
    requirement_lines.append("严格按时间轴逐镜推进动作与运镜，镜头之间的切换要清晰自然，不要跳步或乱切。")
    requirement_lines.append("保持主体身份、服装、场景与动作连续，画面稳定，无闪烁、无重影、无多余人物、无字幕水印。")

    blocks = [
        _format_seedance_section("全局基础设定", global_setting),
        _format_seedance_section("参考映射", reference_mapping),
        _format_seedance_section("时间轴", timeline),
        _format_seedance_section("质量约束", quality_constraints),
        _format_seedance_section("生成要求", "\n".join(f"- {item}" for item in requirement_lines if item)),
    ]
    return _sanitize_seedance_prompt_text("\n\n".join([item for item in blocks if item]).strip())


def _compose_seedance20_prompt(
    base_prompt: str,
    *,
    normalized: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    style_preset: str = "",
) -> str:
    context = context or {}
    is_comic_seedance_reference = (
        str(normalized.get("generation_type") or "").strip() == GEN_REFERENCE
        and str(context.get("storyboard_mode") or "").strip().lower() == "comic"
        and str(normalized.get("model_code") or "").strip().lower() in {"seedance_20", "seedance_20_fast"}
        and bool(normalized.get("image_ref_entries"))
    )
    if is_comic_seedance_reference:
        return _compose_seedance20_comic_reference_prompt(
            base_prompt,
            normalized=normalized,
            context=context,
            style_preset=style_preset,
        )
    prompt = _sanitize_seedance_prompt_text(base_prompt)
    blocks: List[str] = [prompt] if prompt else []

    scene_prompt = _sanitize_seedance_prompt_text(context.get("scene_prompt") or "")
    if scene_prompt and scene_prompt not in prompt:
        blocks.append(scene_prompt)

    shot_controls = [_sanitize_seedance_prompt_text(item) for item in context.get("shot_controls") or [] if str(item).strip()]
    if shot_controls:
        blocks.append("镜头控制：\n" + "\n".join(f"- {item}" for item in shot_controls[:8]))

    reference_lines = _build_seedance20_reference_lines(normalized, context)
    if reference_lines:
        blocks.append("参考控制：\n" + "\n".join(f"- {item}" for item in reference_lines))

    requirement_lines: List[str] = []
    if style_preset:
        requirement_lines.append(f"风格基线：{style_preset}")
    duration = normalized.get("duration")
    aspect_ratio = str(normalized.get("aspect_ratio") or "").strip()
    resolution = str(normalized.get("resolution") or "").strip()
    if duration and aspect_ratio and resolution:
        requirement_lines.append(f"输出规格：{duration}秒，{aspect_ratio}，{resolution}")
    requirement_lines.append("严格按时间轴逐镜推进动作与运镜，镜头之间的切换要清晰自然，不要跳步或乱切。")
    requirement_lines.append("保持主体身份、服装、场景与动作连续，画面稳定，无闪烁、无重影、无多余人物、无字幕水印。")
    blocks.append("生成要求：\n" + "\n".join(f"- {item}" for item in requirement_lines if item))
    return _sanitize_seedance_prompt_text("\n\n".join([item for item in blocks if item]).strip())


def _enhance_video_prompt_for_submission(
    session: Session,
    *,
    binding: Dict[str, Any],
    normalized: Dict[str, Any],
    prompt: str,
) -> str:
    from services.storyboard_director_service import compile_seedance_submit_prompt

    model_code = str(normalized.get("model_code") or "").strip().lower()
    script = binding.get("script")
    episode = binding.get("episode")
    workflow_profile = resolve_effective_workflow_profile(
        script,
        episode=episode,
        storyboard_mode=getattr(binding.get("panel"), "storyboard_mode", None) if binding.get("panel") is not None else getattr(episode, "storyboard_mode", None),
    ) if script else None
    styled_prompt = augment_prompt_with_style(
        prompt,
        workflow_profile,
        label_fallback=str(getattr(script, "style_preset", "") or normalized.get("style") or "").strip(),
    )
    if model_code not in {"seedance_20", "seedance_20_fast"}:
        return styled_prompt
    compiled_bundle = compile_seedance_submit_prompt(
        styled_prompt,
        image_ref_entries=normalized.get("image_ref_entries"),
        video_ref_entries=normalized.get("video_ref_entries"),
        audio_ref_entries=normalized.get("audio_ref_entries"),
    )
    context = _build_seedance20_target_context(session, binding)
    style_preset = str((workflow_profile or {}).get("style", {}).get("label") or getattr(script, "style_preset", "") or normalized.get("style") or "").strip()
    return _compose_seedance20_prompt(
        str(compiled_bundle.get("submit_prompt") or styled_prompt),
        normalized=normalized,
        context=context,
        style_preset=style_preset,
    )


def _productized_charge_description(record: GenerationRecord, params_public: Dict[str, Any]) -> Tuple[str, str]:
    if record.record_type == RECORD_TYPE_IMAGE:
        return (
            "creative_image_generate",
            "图片生成：{0}".format(_image_spec_text(params_public, "稳定版")),
        )
    if record.record_type == RECORD_TYPE_VIDEO:
        return (
            "creative_video_generate",
            f"视频生成：{params_public.get('model_label', 'Vidu Q2')} · {params_public.get('resolution_label', '720p')} · {params_public.get('duration_label', '5秒')}",
        )
    if record.record_type == RECORD_TYPE_AUDIO:
        return (
            "creative_audio_generate",
            "配音生成：{0} · {1}".format(
                params_public.get("ability_label", "实时配音"),
                params_public.get("tier_label", "高保真"),
            ),
        )
    if record.record_type == RECORD_TYPE_EDITING:
        return (
            "creative_editing_generate",
            "剪辑任务：{0} · {1}".format(
                params_public.get("operation_type_label", "剪辑"),
                params_public.get("scope_label", "时间线"),
            ),
        )
    return (
        "creative_asset_generate",
        f"{params_public.get('asset_type_label', '资产')}资产生成：{params_public.get('model_label', '稳定版')}",
    )


def _charge_points_after_success(record_id: int) -> None:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record or record.status != STATUS_COMPLETED or (record.actual_points or 0) > 0:
            return
        cost = int(record.estimate_points or 0)
        if cost <= 0:
            # Some productized tasks, such as editing export in phase 1, are intentionally free.
            # They should stay completed instead of tripping the billing path on zero-cost records.
            return
        user = session.get(User, record.user_id)
        team = session.get(Team, record.team_id)
        if not user or not team:
            return
        params_public = _json_loads(record.params_public_json, {})
        action_type, description = _productized_charge_description(record, params_public)
        deduct_inspiration_points(
            user=user,
            team=team,
            cost=cost,
            action_type=action_type,
            description=description,
            session=session,
        )
        record.actual_points = cost
        record.updated_at = _now()
        session.add(record)
        if record.record_type == RECORD_TYPE_AUDIO:
            params_public = _json_loads(record.params_public_json, {})
            if params_public.get("voice_activation_required"):
                voice_id = str(params_public.get("voice_id") or "").strip()
                if voice_id:
                    asset = session.exec(
                        select(VoiceAsset).where(
                            VoiceAsset.user_id == user.id,
                            VoiceAsset.provider_voice_id == voice_id,
                        )
                    ).first()
                    if asset and not asset.activation_billed_at:
                        asset.activation_billed_at = _now()
                        asset.updated_at = _now()
                        session.add(asset)
        session.commit()


def _mark_failed(record_id: int, *, error_code: str, message: str, internal_message: Optional[str] = None) -> None:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record:
            return
        record.status = STATUS_FAILED
        record.actual_points = 0
        record.error_code_public = error_code
        record.error_message_public = message
        record.error_message_internal = internal_message or message
        record.updated_at = _now()
        session.add(record)
        session.commit()


def _mark_processing(record_id: int, backend_task_id: Optional[str] = None) -> None:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record:
            return
        record.status = STATUS_PROCESSING
        if backend_task_id:
            params_internal = _json_loads(record.params_internal_json, {})
            params_internal["backend_task_id"] = backend_task_id
            record.params_internal_json = _json_dumps(params_internal)
        record.updated_at = _now()
        session.add(record)
        session.commit()


def _map_user_status(raw_status: str) -> str:
    normalized = str(raw_status or "").strip().lower()
    if normalized in {"queued", "pending", "processing", "running", "waiting_upstream", "leased", "retry_waiting"}:
        return USER_STATUS_GENERATING
    if normalized in {"completed", "success", "succeeded"}:
        return USER_STATUS_COMPLETED
    return USER_STATUS_FAILED


def _map_user_failure(code: Optional[str], message: Optional[str], internal_message: Optional[str] = None) -> Dict[str, Optional[str]]:
    code_text = str(code or "").strip().lower()
    joined = " ".join([
        str(message or "").strip().lower(),
        str(internal_message or "").strip().lower(),
    ])
    if any(token in code_text for token in ["timeout", "timed_out", "lease_expired"]) or "超时" in joined:
        reason = FAILURE_REASON_TIMEOUT
    elif any(token in code_text for token in ["violation", "moderation", "content_policy"]) or any(
        token in joined for token in ["不支持真人", "内容违规", "prohibited", "violation", "sensitive", "审核"]
    ):
        reason = FAILURE_REASON_VIOLATION
    elif any(token in code_text for token in ["invalid", "bad_request", "invalid_request", "invalid_target"]) or any(
        token in joined for token in ["参数", "不合法", "invalid", "required", "unsupported", "格式不支持"]
    ):
        reason = FAILURE_REASON_INVALID
    else:
        reason = FAILURE_REASON_GENERIC
    return {
        "failure_reason": reason,
        "failure_message": USER_FAILURE_MESSAGES[reason],
    }


def _complete_record_success(record_id: int, *, preview_url: str, thumbnail_url: Optional[str] = None) -> None:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record:
            return
        record.status = STATUS_COMPLETED
        record.preview_url = preview_url
        if thumbnail_url:
            record.thumbnail_url = thumbnail_url
        elif preview_url:
            record.thumbnail_url = _derive_record_thumbnail_url(record.record_type, preview_url, record.thumbnail_url)
        record.error_code_public = None
        record.error_message_public = None
        record.updated_at = _now()
        session.add(record)
        session.commit()

    _charge_points_after_success(record_id)


def _submit_nano_task(internal_model: str, *, prompt: str, resolution: str, aspect_ratio: str, urls: List[str]) -> str:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}
    payload = {
        "model": internal_model,
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "imageSize": resolution.upper(),
        "urls": urls,
        "webHook": "-1",
    }
    response = requests.post(settings.NANO_API_URL, headers=headers, json=payload, timeout=30)
    data = response.json()
    task_id = data.get("data", {}).get("id")
    if not response.ok or not task_id:
        raise RuntimeError("鍥剧墖鐢熸垚鏈嶅姟鏆備笉鍙敤")
    return task_id


def _poll_nano_task(task_id: str) -> str:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}
    for _ in range(200):
        time.sleep(3)
        try:
            response = requests.post(settings.NANO_RESULT_URL, headers=headers, json={"id": task_id}, timeout=30)
            data = response.json()
            result_data = data.get("data", data)
            status = str(result_data.get("status", "")).lower()
            if status == "succeeded":
                results = result_data.get("results", [])
                if results and results[0].get("url"):
                    return results[0]["url"]
                raise RuntimeError("鍥剧墖鐢熸垚缁撴灉涓虹┖")
            if status in {"failed", "error"}:
                raise RuntimeError("鍥剧墖鐢熸垚澶辫触锛岃绋嶅悗閲嶈瘯")
        except RuntimeError:
            raise
        except Exception:
            continue
    raise RuntimeError("鍥剧墖鐢熸垚瓒呮椂锛岃绋嶅悗閲嶈瘯")


def _query_nano_task_once(task_id: str) -> ProviderResult:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}
    response = requests.post(settings.NANO_RESULT_URL, headers=headers, json={"id": task_id}, timeout=30)
    data = response.json()
    result_data = data.get("data", data)
    status = str(result_data.get("status", "")).lower()
    if status == "succeeded":
        results = result_data.get("results", [])
        url = results[0].get("url") if results else None
        return ProviderResult(is_done=True, is_failed=False, output_url=url, raw_payload=data)
    if status in {"failed", "error"}:
        return ProviderResult(is_done=True, is_failed=True, error=result_data.get("error") or result_data.get("message"), raw_payload=data)
    return ProviderResult(is_done=False, is_failed=False, raw_payload=data)


def _submit_video_task(params_public: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[str, str]:
    model = params_public["model"]
    internal_model = VIDEO_MODEL_TO_INTERNAL[model]
    prompt = str(payload.get("prompt") or "").strip()
    reference_images = [str(item).strip() for item in payload.get("reference_images", []) if str(item).strip()]
    reference_videos = [str(item).strip() for item in payload.get("reference_videos", []) if str(item).strip()]
    duration = params_public["duration"]
    resolution = params_public["resolution"]
    aspect_ratio = params_public["aspect_ratio"]
    audio_enabled = bool(payload.get("audio_enabled"))
    start_frame = str(payload.get("start_frame") or "").strip()
    audio_url = str(payload.get("audio_url") or "").strip()

    if model == VIDEO_MODEL_Q3:
        if len(reference_images) != 1 or reference_videos:
            raise public_http_error(400, "invalid_request", "Vidu Q3 浠呮敮鎸佸崟寮犲弬鑰冨浘鐢熸垚", field="reference_images")
        data = _run_async_blocking(
            runninghub_video_service.generate_vidu_q3_pro(
                prompt=prompt,
                image_urls=reference_images,
                duration=str(duration),
                resolution=resolution,
                audio=audio_enabled,
            )
        )
        task_id = data.get("taskId") or data.get("data", {}).get("taskId")
        if not task_id:
            raise RuntimeError("视频生成服务暂不可用")
        return internal_model, task_id

    if model == VIDEO_MODEL_Q2:
        if not reference_images and not start_frame:
            raise public_http_error(400, "invalid_request", "鏅€氳棰戣嚦灏戦渶瑕佷竴寮犻甯ф垨鍙傝€冨浘", field="reference_images")
        image_urls = reference_images or ([start_frame] if start_frame else [])
        data = _run_async_blocking(
            runninghub_video_service.generate_vidu_q2_pro(
                prompt=prompt,
                image_urls=image_urls,
                video_urls=reference_videos,
                duration=str(duration),
                resolution=resolution,
                bgm=audio_enabled,
                aspect_ratio=aspect_ratio,
            )
        )
        task_id = data.get("taskId") or data.get("data", {}).get("taskId")
        if not task_id:
            raise RuntimeError("视频生成服务暂不可用")
        return internal_model, task_id

    if not start_frame or not audio_url:
        raise public_http_error(400, "invalid_request", "数字人模式需要首帧图片和音频链接", field="audio_url")
    data = _run_async_blocking(
        suchuang_video_service.generate_digital_human(
            video_name=f"digital_{int(time.time())}",
            video_url=start_frame,
            audio_url=audio_url,
        )
    )
    task_id = data.get("data", {}).get("id") or data.get("id")
    if not task_id:
        raise RuntimeError("数字人服务暂不可用")
    return internal_model, str(task_id)


def _require_media_url(value: str, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise public_http_error(400, "invalid_request", f"{field} 涓嶈兘涓虹┖", field=field)
    return text


def _pick_first_image(normalized: Dict[str, Any]) -> str:
    if normalized["first_frame"]:
        return normalized["first_frame"]
    if normalized["image_refs"]:
        return normalized["image_refs"][0]
    raise public_http_error(400, "invalid_request", "褰撳墠鍔熻兘鑷冲皯闇€瑕佷竴寮犲弬鑰冨浘", field="image_refs")


def _build_runninghub_video_payload(submit_type: str, normalized: Dict[str, Any]) -> Dict[str, Any]:
    prompt = normalized["prompt"]
    duration = str(normalized["duration"])
    resolution = normalized["resolution"]
    aspect_ratio = normalized["aspect_ratio"]

    if submit_type == "veo_text":
        return {"prompt": prompt, "duration": duration, "resolution": resolution, "aspectRatio": aspect_ratio}
    if submit_type == "veo_official_text":
        return {
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "duration": duration,
            "resolution": resolution,
            "generateAudio": bool(normalized["audio_enabled"]),
            "negativePrompt": None,
            "seed": None,
        }
    if submit_type == "veo_image":
        image_urls = normalized["image_refs"] or [_pick_first_image(normalized)]
        return {"prompt": prompt, "imageUrls": image_urls, "duration": duration, "resolution": resolution, "aspectRatio": aspect_ratio}
    if submit_type == "veo_official_image":
        payload = {
            "prompt": prompt,
            "imageUrl": _require_media_url(normalized["first_frame"] or _pick_first_image(normalized), "first_frame"),
            "aspectRatio": aspect_ratio,
            "duration": duration,
            "resolution": resolution,
            "generateAudio": bool(normalized["audio_enabled"]),
            "negativePrompt": None,
            "seed": None,
        }
        if normalized["last_frame"]:
            payload["lastImageUrl"] = normalized["last_frame"]
        return payload
    if submit_type == "veo_reference":
        return {"prompt": prompt, "imageUrls": normalized["image_refs"], "duration": duration, "resolution": resolution, "aspectRatio": aspect_ratio}
    if submit_type == "veo_start_end":
        return {"prompt": prompt, "firstFrameUrl": _require_media_url(normalized["first_frame"], "first_frame"), "lastFrameUrl": _require_media_url(normalized["last_frame"], "last_frame"), "duration": duration, "resolution": resolution, "aspectRatio": aspect_ratio}
    if submit_type == "vidu_q2_image":
        return {"prompt": prompt, "imageUrl": _pick_first_image(normalized), "duration": duration, "resolution": resolution, "movementAmplitude": normalized["motion_strength"] or "auto", "bgm": bool(normalized["audio_enabled"])}
    if submit_type == "vidu_q2_reference":
        payload = {"prompt": prompt, "imageUrls": normalized["image_refs"], "duration": duration, "resolution": resolution, "aspectRatio": aspect_ratio, "movementAmplitude": normalized["motion_strength"] or "auto"}
        if normalized["video_refs"]:
            payload["videos"] = normalized["video_refs"]
        return payload
    if submit_type == "vidu_q2_start_end":
        return {"prompt": prompt, "firstImageUrl": _require_media_url(normalized["first_frame"], "first_frame"), "lastImageUrl": _require_media_url(normalized["last_frame"], "last_frame"), "duration": duration, "resolution": resolution, "movementAmplitude": normalized["motion_strength"] or "auto", "bgm": bool(normalized["audio_enabled"])}
    if submit_type == "vidu_q2_fast_image":
        return {"prompt": prompt, "imageUrl": _pick_first_image(normalized), "duration": duration, "resolution": resolution, "movementAmplitude": normalized["motion_strength"] or "auto"}
    if submit_type == "vidu_q2_fast_start_end":
        return {"prompt": prompt, "firstImageUrl": _require_media_url(normalized["first_frame"], "first_frame"), "lastImageUrl": _require_media_url(normalized["last_frame"], "last_frame"), "duration": duration, "resolution": resolution, "movementAmplitude": normalized["motion_strength"] or "auto"}
    if submit_type in {"vidu_q3_text", "vidu_q3_turbo_text"}:
        return {"prompt": prompt, "duration": duration, "resolution": resolution, "audio": bool(normalized["audio_enabled"])}
    if submit_type in {"vidu_q3_image", "vidu_q3_turbo_image"}:
        return {"prompt": prompt, "imageUrl": _pick_first_image(normalized), "duration": duration, "resolution": resolution, "audio": bool(normalized["audio_enabled"])}
    if submit_type in {"vidu_q3_start_end", "vidu_q3_turbo_start_end"}:
        return {"prompt": prompt, "firstImageUrl": _require_media_url(normalized["first_frame"], "first_frame"), "lastImageUrl": _require_media_url(normalized["last_frame"], "last_frame"), "duration": duration, "resolution": resolution, "audio": bool(normalized["audio_enabled"])}
    if submit_type in {"seedance_text", "seedance_fast_text"}:
        return {"prompt": prompt, "aspectRatio": aspect_ratio, "duration": duration, "resolution": resolution, "generateAudio": bool(normalized["audio_enabled"]), "cameraFixed": bool(normalized["camera_fixed"])}
    if submit_type in {"seedance_image", "seedance_fast_image"}:
        payload = {"prompt": prompt, "firstImageUrl": _require_media_url(normalized["first_frame"] or _pick_first_image(normalized), "first_frame"), "aspectRatio": aspect_ratio, "duration": duration, "resolution": resolution, "generateAudio": bool(normalized["audio_enabled"]), "cameraFixed": bool(normalized["camera_fixed"])}
        if normalized["last_frame"]:
            payload["lastImageUrl"] = normalized["last_frame"]
        return payload
    if submit_type in {"seedance_start_end", "seedance_fast_start_end"}:
        return {"prompt": prompt, "firstImageUrl": _require_media_url(normalized["first_frame"], "first_frame"), "lastImageUrl": _require_media_url(normalized["last_frame"], "last_frame"), "aspectRatio": aspect_ratio, "duration": duration, "resolution": resolution, "generateAudio": bool(normalized["audio_enabled"]), "cameraFixed": bool(normalized["camera_fixed"])}
    if submit_type in {"seedance20_fast_text", "seedance20_text"}:
        return {
            "prompt": prompt,
            "resolution": resolution,
            "duration": duration,
            "generateAudio": bool(normalized["audio_enabled"]),
            "ratio": aspect_ratio,
            "webSearch": bool(normalized.get("web_search")),
        }
    if submit_type in {"seedance20_fast_image", "seedance20_image"}:
        payload = {
            "prompt": prompt,
            "firstFrameUrl": _require_media_url(normalized["first_frame"] or _pick_first_image(normalized), "first_frame"),
            "resolution": resolution,
            "duration": duration,
            "generateAudio": bool(normalized["audio_enabled"]),
            "ratio": aspect_ratio,
            "realPersonMode": bool(normalized.get("real_person_mode")),
        }
        if normalized["last_frame"]:
            payload["lastFrameUrl"] = normalized["last_frame"]
        return payload
    if submit_type in {"seedance20_fast_reference", "seedance20_reference"}:
        payload = {
            "prompt": prompt,
            "resolution": resolution,
            "duration": duration,
            "imageUrls": normalized["image_refs"],
            "videoUrls": normalized["video_refs"],
            "audioUrls": _combined_audio_reference_urls(normalized),
            "generateAudio": bool(normalized["audio_enabled"]),
            "ratio": aspect_ratio,
            "realPersonMode": bool(normalized.get("real_person_mode")),
        }
        return payload
    if submit_type == "kling_o1_text":
        return {"prompt": prompt, "aspectRatio": aspect_ratio, "duration": duration, "mode": normalized["quality_mode"] or "std"}
    if submit_type in {"kling30_text", "kling_o3_text"}:
        return {"prompt": prompt, "negativePrompt": None, "duration": duration, "aspectRatio": aspect_ratio, "cfgScale": 0.5, "sound": bool(normalized["audio_enabled"]), "multiShot": False, "shotType": "customize"}
    if submit_type == "kling_o1_image":
        return {"prompt": prompt, "firstImageUrl": _require_media_url(normalized["first_frame"] or _pick_first_image(normalized), "first_frame"), "aspectRatio": aspect_ratio, "duration": duration, "mode": normalized["quality_mode"] or "std"}
    if submit_type in {"kling30_image", "kling_o3_image"}:
        payload = {"prompt": prompt, "negativePrompt": None, "firstImageUrl": _require_media_url(normalized["first_frame"] or _pick_first_image(normalized), "first_frame"), "duration": duration, "cfgScale": 0.8, "sound": bool(normalized["audio_enabled"]), "multiShot": False, "shotType": "customize"}
        if normalized["last_frame"]:
            payload["lastImageUrl"] = normalized["last_frame"]
        return payload
    if submit_type == "kling_o1_start_end":
        return {
            "prompt": prompt,
            "firstImageUrl": _require_media_url(normalized["first_frame"], "first_frame"),
            "lastImageUrl": _require_media_url(normalized["last_frame"], "last_frame"),
            "aspectRatio": aspect_ratio,
            "duration": duration,
            "mode": normalized["quality_mode"] or "std",
        }
    if submit_type == "kling_o1_reference":
        payload = {
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "duration": duration,
            "mode": normalized["quality_mode"] or "std",
            "videoUrl": _require_media_url((normalized["video_refs"] or [None])[0], "video_refs"),
            "keepOriginalSound": bool(normalized["audio_enabled"]),
        }
        if normalized["image_refs"]:
            payload["imageUrls"] = normalized["image_refs"][:7]
        return payload
    if submit_type == "kling_o3_reference":
        payload = {
            "prompt": prompt,
            "keepOriginalSound": bool(normalized["video_refs"]),
            "sound": bool(normalized["audio_enabled"]),
            "aspectRatio": aspect_ratio,
            "duration": int(normalized["duration"]),
            "multiShot": False,
        }
        if normalized["video_refs"]:
            payload["videoUrl"] = normalized["video_refs"][0]
        if normalized["image_refs"]:
            payload["imageUrls"] = normalized["image_refs"][:7]
        return payload
    raise public_http_error(400, "invalid_request", "当前模型功能暂未接入", retryable=False)


def _submit_video_task(params_public: Dict[str, Any], payload: Dict[str, Any]) -> Tuple[str, str]:
    del params_public
    normalized = normalize_video_request(payload)
    model = get_video_model_or_none(normalized["model_code"])
    if not model:
        raise public_http_error(400, "invalid_model", "当前模型暂不可用", retryable=False, field="model_code")
    feature = model.get("features", {}).get(normalized["generation_type"])
    if not feature:
        raise public_http_error(400, "invalid_request", "当前模型不支持该功能类型", retryable=False, field="generation_type")
    if not normalized["prompt"]:
        raise public_http_error(400, "invalid_request", "prompt 不能为空", retryable=False, field="prompt")
    if normalized["generation_type"] == GEN_REFERENCE:
        if normalized["model_code"] in {"seedance_20", "seedance_20_fast"}:
            if not normalized["image_refs"] and not normalized["video_refs"]:
                raise public_http_error(400, "invalid_request", "当前功能至少需要参考图或参考视频", retryable=False, field="image_refs")
        elif not normalized["image_refs"]:
            raise public_http_error(400, "invalid_request", "参考生视频至少需要一张参考图", retryable=False, field="image_refs")

    request_payload = _build_runninghub_video_payload(feature["submit_type"], normalized)
    data = _run_async_blocking(runninghub_video_service.submit_task(feature["endpoint"], request_payload))
    task_id = data.get("taskId") or data.get("data", {}).get("taskId")
    if not task_id:
        raise RuntimeError("视频生成服务暂不可用")
    return f"runninghub:{normalized['model_code']}", str(task_id)


def _query_video_task_once(internal_model: str, task_id: str) -> ProviderResult:
    if internal_model == VIDEO_MODEL_TO_INTERNAL[VIDEO_MODEL_DIGITAL_HUMAN]:
        data = _run_async_blocking(suchuang_video_service.query_task(task_id))
        payload = data.get("data") or data
        status = str(payload.get("status") or "")
        if status == "2":
            preview_url = str(payload.get("url") or payload.get("videoUrl") or "").strip()
            return ProviderResult(is_done=True, is_failed=False, output_url=preview_url, raw_payload=data)
        if status == "3":
            return ProviderResult(is_done=True, is_failed=True, error=str(payload.get("message") or "数字人生成失败"), raw_payload=data)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=data)

    try:
        data = _run_async_blocking(runninghub_video_service.query_task(task_id))
    except Exception as exc:
        message = str(exc or "").strip()
        if message:
            # RunningHub sometimes surfaces business failures as query exceptions
            # instead of a regular FAILED payload. Treat these as terminal failures.
            if "RunningHub 接口内部报错" in message or "Current mode does not support real-person content" in message:
                return ProviderResult(is_done=True, is_failed=True, error=message, raw_payload={"error": message})
        raise
    status = str(data.get("status") or "").upper()
    if status == "SUCCESS":
        results = data.get("results") or []
        preview_url = str(results[0].get("url") or "").strip() if results else ""
        return ProviderResult(is_done=True, is_failed=False, output_url=preview_url or None, raw_payload=data)
    if status == "FAILED":
        return ProviderResult(is_done=True, is_failed=True, error=str(data.get("errorMessage") or data.get("failedReason") or "视频生成失败"), raw_payload=data)
    return ProviderResult(is_done=False, is_failed=False, raw_payload=data)


def _poll_video_task(internal_model: str, task_id: str) -> str:
    for _ in range(200):
        time.sleep(3)
        try:
            if internal_model == VIDEO_MODEL_TO_INTERNAL[VIDEO_MODEL_DIGITAL_HUMAN]:
                data = _run_async_blocking(suchuang_video_service.query_task(task_id))
                payload = data.get("data") or data
                status = str(payload.get("status") or payload.get("state") or "").lower()
                result_url = payload.get("resultUrl") or payload.get("videoUrl") or payload.get("url")
            else:
                data = _run_async_blocking(runninghub_video_service.query_task(task_id))
                status = str(data.get("status") or "").lower()
                results = data.get("results") or data.get("data", {}).get("results") or []
                result_url = ""
                if results:
                    result_url = results[0].get("url") or results[0].get("fileUrl") or ""

            if status in {"success", "completed", "succeeded"} and result_url:
                return result_url
            if status in {"failed", "error"}:
                raise RuntimeError("视频生成失败，请稍后重试")
        except RuntimeError:
            raise
        except Exception:
            continue
    raise RuntimeError("视频生成超时，请稍后重试")


def submit_image_generation_upstream(record_id: int, *, webhook_url: Optional[str] = None) -> Dict[str, Any]:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record:
            raise RuntimeError("record not found")
        params_internal = _json_loads(record.params_internal_json, {})
        request_payload = params_internal.get("request_payload")
        if not isinstance(request_payload, dict):
            request_payload = {
                "model_code": params_internal.get("model_code") or params_internal.get("internal_model"),
                "mode": params_internal.get("generation_type") or params_internal.get("mode") or IMAGE_MODE_TEXT,
                "resolution": params_internal.get("resolution"),
                "aspect_ratio": params_internal.get("aspect_ratio"),
                "reference_images": params_internal.get("reference_images") or [],
                "prompt": record.prompt,
            }
        normalized = _normalize_productized_image_request({
            **request_payload,
            "webhook_url": webhook_url,
        })
        result = submit_image_request({
            **normalized,
            "webhook_url": webhook_url,
        })
        response = {
            "provider": str(result.get("provider") or ""),
            "completion_mode": str(result.get("completion_mode") or "poll"),
        }
        if response["completion_mode"] == "immediate":
            response["output_url"] = str(result.get("output_url") or "")
            return response
        response["upstream_task_id"] = str(result.get("upstream_task_id") or "")
        return response


def query_image_generation_upstream(provider: str, upstream_task_id: str) -> ProviderResult:
    return query_image_generation(provider, upstream_task_id)


def submit_video_generation_upstream(record_id: int) -> Dict[str, Any]:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record:
            raise RuntimeError("record not found")
        params_public = _json_loads(record.params_public_json, {})
        params_internal = _json_loads(record.params_internal_json, {})
        payload = params_internal.get("request_payload", {})
        provider, upstream_task_id = _submit_video_task(params_public, payload)
        return {
            "provider": provider,
            "upstream_task_id": upstream_task_id,
            "completion_mode": "poll",
        }


def query_video_generation_upstream(provider: str, upstream_task_id: str) -> ProviderResult:
    return _query_video_task_once(provider, upstream_task_id)


def submit_audio_generation_upstream(record_id: int) -> Dict[str, Any]:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record:
            raise RuntimeError("record not found")
        params_internal = _json_loads(record.params_internal_json, {})
        normalized = params_internal.get("request_payload", {})
        if not isinstance(normalized, dict):
            raise RuntimeError("配音任务参数缺失")
        ability_type = normalized.get("ability_type")
        if ability_type == ABILITY_NARRATION:
            request_payload = _build_audio_async_request(normalized, owner_user_id=record.user_id)
            params_internal["request_payload"] = request_payload
            record.params_internal_json = _json_dumps(params_internal)
            session.add(record)
            session.commit()
            result = minimax_audio_service.submit_long_narration(request_payload)
            upstream_task_id = str(result.get("task_id") or result.get("task_token") or "")
            if not upstream_task_id:
                raise RuntimeError("配音服务未返回任务 ID")
            return {
                "provider": "minimax-audio",
                "upstream_task_id": upstream_task_id,
                "completion_mode": "poll",
            }
        _run_audio_generation_job(record_id)
        return {"provider": "minimax-audio", "upstream_task_id": "", "completion_mode": "immediate"}


def query_audio_generation_upstream(provider: str, upstream_task_id: str) -> ProviderResult:
    del provider
    query = minimax_audio_service.query_long_narration(upstream_task_id)
    status = str(query.get("status") or query.get("data", {}).get("status") or "").lower()
    final_file_id = str(query.get("file_id") or query.get("data", {}).get("file_id") or "")
    if status in {"success", "succeeded", "completed"} and final_file_id:
        content = minimax_audio_service.retrieve_file_content(final_file_id)
        meta = _upload_audio_bytes_result(content, "narration-result.mp3", record_id=record_id)
        return ProviderResult(is_done=True, is_failed=False, output_url=meta["file_url"], raw_payload=query)
    if status in {"failed", "error", "expired"}:
        return ProviderResult(is_done=True, is_failed=True, error=str(query.get("base_resp", {}).get("status_msg") or "配音生成失败"), raw_payload=query)
    return ProviderResult(is_done=False, is_failed=False, raw_payload=query)


def complete_generation_record_from_upstream(record_id: int, *, preview_url: str, thumbnail_url: Optional[str] = None) -> None:
    _complete_record_success(record_id, preview_url=preview_url, thumbnail_url=thumbnail_url)
    _apply_success_to_target(record_id, preview_url=preview_url)
    _persist_record_media_to_oss(record_id)


def complete_generation_record_from_upstream_deferred(record_id: int, *, preview_url: str, thumbnail_url: Optional[str] = None) -> None:
    if _is_inline_data_image(preview_url) and _set_inline_preview_cache(record_id, preview_url):
        _complete_record_success(record_id, preview_url="", thumbnail_url=thumbnail_url)
        threading.Thread(target=_persist_record_media_to_oss, args=(record_id,), daemon=True).start()
        return
    _complete_record_success(record_id, preview_url=preview_url, thumbnail_url=thumbnail_url)
    _apply_success_to_target(record_id, preview_url=preview_url)
    threading.Thread(target=_persist_record_media_to_oss, args=(record_id,), daemon=True).start()


def fail_generation_record_from_upstream(record_id: int, *, error_code: str, message: str, internal_message: Optional[str] = None) -> None:
    _mark_failed(record_id, error_code=error_code, message=message, internal_message=internal_message)


def _update_panel_after_success(
    panel_id: int,
    *,
    prompt: str,
    preview_url: str,
    thumbnail_url: Optional[str],
    is_video: bool,
    note_for_nine_grid: Optional[str],
) -> None:
    with Session(engine) as session:
        panel = session.get(Panel, panel_id)
        if not panel:
            return
        previous_video_url = str(panel.video_url or "").strip()
        panel.task_id = None
        panel.status = TaskStatusEnum.COMPLETED
        if is_video:
            panel.video_prompt = prompt
            panel.video_url = preview_url
            resolved_video_thumbnail = thumbnail_url or _derive_record_thumbnail_url(
                RECORD_TYPE_VIDEO,
                preview_url,
                panel.video_thumbnail_url,
            )
            panel.video_thumbnail_url = resolved_video_thumbnail
            panel.video_history_json = upsert_panel_video_history(
                panel.video_history_json,
                preview_url=preview_url,
                thumbnail_url=resolved_video_thumbnail,
                replace_url=previous_video_url,
            )
        else:
            if note_for_nine_grid:
                panel.nine_grid_prompt = prompt
            else:
                panel.prompt = prompt
            panel.image_url = preview_url
            panel.thumbnail_url = thumbnail_url or _derive_record_thumbnail_url(RECORD_TYPE_IMAGE, preview_url, panel.thumbnail_url)
        session.add(panel)
        session.commit()


def _create_or_update_shared_resource(
    *,
    script_id: int,
    resource_id: Optional[int],
    resource_type: str,
    name: str,
    file_url: str,
    description: Optional[str],
    trigger_word: Optional[str],
    aliases: Optional[List[str]],
    appearance_prompt: Optional[str] = None,
) -> int:
    with Session(engine) as session:
        if resource_id:
            resource = session.get(SharedResource, resource_id)
            if not resource:
                raise RuntimeError("共享资源不存在")
            resource.file_url = file_url
            resource.thumbnail_url = _derive_record_thumbnail_url(RECORD_TYPE_IMAGE, file_url)
            resource.description = description or resource.description
            resource.trigger_word = trigger_word or resource.trigger_word
            if aliases is not None:
                resource.aliases = _json_dumps(aliases)
            session.add(resource)
            _create_generated_resource_version_if_needed(
                session,
                resource=resource,
                file_url=file_url,
                prompt=appearance_prompt or description,
            )
            session.commit()
            session.refresh(resource)
            return resource.id

        resource = SharedResource(
            script_id=script_id,
            resource_type=resource_type,
            name=name,
            file_url=file_url,
            thumbnail_url=_derive_record_thumbnail_url(RECORD_TYPE_IMAGE, file_url),
            description=description,
            trigger_word=trigger_word,
            aliases=_json_dumps(aliases or []),
        )
        session.add(resource)
        session.commit()
        session.refresh(resource)
        return resource.id


def _create_generated_resource_version_if_needed(
    session: Session,
    *,
    resource: SharedResource,
    file_url: str,
    prompt: Optional[str],
) -> None:
    resolved_url = str(file_url or "").strip()
    if not resolved_url or not is_oss_url(resolved_url):
        return
    defaults = session.exec(
        select(SharedResourceVersion).where(
            SharedResourceVersion.resource_id == resource.id,
            SharedResourceVersion.is_default == True,
        )
    ).all()
    existing = session.exec(
        select(SharedResourceVersion).where(
            SharedResourceVersion.resource_id == resource.id,
            SharedResourceVersion.file_url == resolved_url,
        )
    ).first()
    if existing:
        for item in defaults:
            if item.id != existing.id:
                item.is_default = False
                session.add(item)
        existing.is_default = True
        if prompt:
            existing.appearance_prompt = prompt
        session.add(existing)
        return

    for item in defaults:
        item.is_default = False
        session.add(item)

    version = SharedResourceVersion(
        resource_id=resource.id,
        version_tag=f"gen-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        appearance_prompt=prompt or resource.description,
        file_url=resolved_url,
        trigger_word=resource.trigger_word,
        start_seq=None,
        end_seq=None,
        is_default=True,
    )
    session.add(version)


def _apply_success_to_target(record_id: int, *, preview_url: str) -> None:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record or record.ownership_mode != OWNERSHIP_MODE_PROJECT:
            return
        params_public = _json_loads(record.params_public_json, {})
        target_note = params_public.get("target_note")

        if record.target_type == TARGET_TYPE_PANEL and record.target_id:
            _update_panel_after_success(
                record.target_id,
                prompt=record.prompt,
                preview_url=preview_url,
                thumbnail_url=record.thumbnail_url,
                is_video=record.record_type == RECORD_TYPE_VIDEO,
                note_for_nine_grid=target_note,
            )
            return

        if record.record_type == RECORD_TYPE_ASSET and record.script_id:
            resource_id = record.target_id if record.target_type == TARGET_TYPE_SHARED_RESOURCE else None
            new_resource_id = _create_or_update_shared_resource(
                script_id=record.script_id,
                resource_id=resource_id,
                resource_type=ASSET_TYPE_TO_RESOURCE_TYPE[params_public["asset_type"]],
                name=params_public["name"],
                file_url=preview_url,
                description=params_public.get("description"),
                trigger_word=params_public.get("trigger_word"),
                aliases=params_public.get("aliases") or [],
                appearance_prompt=record.prompt,
            )
            with Session(engine) as update_session:
                latest = update_session.get(GenerationRecord, record_id)
                if latest:
                    latest.target_type = TARGET_TYPE_SHARED_RESOURCE
                    latest.target_id = new_resource_id
                    latest.updated_at = _now()
                    update_session.add(latest)
                    update_session.commit()
            return

        if record.record_type == RECORD_TYPE_IMAGE and record.target_type == TARGET_TYPE_SHARED_RESOURCE and record.target_id and record.script_id:
            _create_or_update_shared_resource(
                script_id=record.script_id,
                resource_id=record.target_id,
                resource_type=ResourceTypeEnum.SCENE_REF.value,
                name=params_public.get("prompt_summary") or "图片资源",
                file_url=preview_url,
                description=record.prompt,
                trigger_word=None,
                aliases=None,
                appearance_prompt=record.prompt,
            )


def _update_record_urls(record_id: int, *, preview_url: str, thumbnail_url: Optional[str] = None) -> None:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record:
            return
        record.preview_url = preview_url
        record.thumbnail_url = thumbnail_url if thumbnail_url is not None else _derive_record_thumbnail_url(record.record_type, preview_url, record.thumbnail_url)
        record.updated_at = _now()
        session.add(record)
        session.commit()


def _load_target_preview(record_id: int) -> Tuple[Optional[str], Optional[str]]:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record:
            return None, None
        if record.target_type == TARGET_TYPE_PANEL and record.target_id:
            panel = session.get(Panel, record.target_id)
            if not panel:
                return None, None
            preview = panel.video_url if record.record_type == RECORD_TYPE_VIDEO else panel.image_url
            if preview:
                if record.record_type == RECORD_TYPE_VIDEO:
                    return preview, panel.video_thumbnail_url or _derive_record_thumbnail_url(record.record_type, preview)
                return preview, _derive_record_thumbnail_url(record.record_type, preview)
            return None, None
        if record.target_type == TARGET_TYPE_SHARED_RESOURCE and record.target_id:
            resource = session.get(SharedResource, record.target_id)
            if not resource:
                return None, None
            if resource.file_url:
                return resource.file_url, resource.thumbnail_url or _derive_record_thumbnail_url(RECORD_TYPE_IMAGE, resource.file_url)
        return None, None


def _persist_record_media_to_oss(record_id: int) -> None:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record or record.status != STATUS_COMPLETED:
            return
        current_preview = str(record.preview_url or "").strip()
        if not current_preview:
            current_preview = str(_get_inline_preview_cache(record_id) or "").strip()
            if not current_preview:
                return
        if is_oss_url(current_preview):
            desired_thumbnail = _derive_record_thumbnail_url(record.record_type, current_preview, record.thumbnail_url)
            if desired_thumbnail != record.thumbnail_url:
                record.thumbnail_url = desired_thumbnail
                record.updated_at = _now()
                session.add(record)
                session.commit()
            return
        record_type = record.record_type

    try:
        if current_preview.startswith("data:image/"):
            persisted_preview = upload_base64_to_oss(
                current_preview,
                owner_user_id=record.user_id,
                source_type="generation_record",
                source_id=record_id,
            )
            persisted_thumbnail = _derive_record_thumbnail_url(record_type, persisted_preview, None)
        else:
            meta = upload_remote_file_to_oss_with_meta(
                current_preview,
                owner_user_id=record.user_id,
                source_type="generation_record",
                source_id=record_id,
            )
            persisted_preview = meta.get("file_url") or current_preview
            persisted_thumbnail = meta.get("thumbnail_url") or _derive_record_thumbnail_url(record_type, persisted_preview)
    except Exception as exc:
        fallback_preview, fallback_thumbnail = _load_target_preview(record_id)
        if fallback_preview and is_oss_url(fallback_preview):
            _update_record_urls(record_id, preview_url=fallback_preview, thumbnail_url=fallback_thumbnail)
            _clear_inline_preview_cache(record_id)
        else:
            print(f"[generation-record] preview persist skipped for {record_id}: {exc}")
        return

    _update_record_urls(record_id, preview_url=persisted_preview, thumbnail_url=persisted_thumbnail)
    _apply_success_to_target(record_id, preview_url=persisted_preview)
    _clear_inline_preview_cache(record_id)


def repair_generation_record_previews(batch_size: int = 100, max_batches: int = 20) -> None:
    for batch_index in range(max_batches):
        with Session(engine) as session:
            statement = (
                select(GenerationRecord)
                .where(GenerationRecord.status == STATUS_COMPLETED)
                .order_by(GenerationRecord.id.desc())
                .offset(batch_index * batch_size)
                .limit(batch_size)
            )
            records = session.exec(statement).all()
        if not records:
            break
        for record in records:
            try:
                if not str(record.preview_url or "").strip():
                    inline_preview = _get_inline_preview_cache(record.id)
                    if inline_preview:
                        _persist_record_media_to_oss(record.id)
                        continue
                    fallback_preview, fallback_thumbnail = _load_target_preview(record.id)
                    if fallback_preview:
                        _update_record_urls(record.id, preview_url=fallback_preview, thumbnail_url=fallback_thumbnail)
                    continue
                if is_oss_url(record.preview_url):
                    desired_thumbnail = _derive_record_thumbnail_url(record.record_type, record.preview_url, record.thumbnail_url)
                    if desired_thumbnail != record.thumbnail_url:
                        _update_record_urls(record.id, preview_url=record.preview_url, thumbnail_url=desired_thumbnail)
                    continue
                _persist_record_media_to_oss(record.id)
            except Exception as exc:
                print(f"[generation-record] repair skipped for {record.id}: {exc}")


def _run_image_generation_job(record_id: int) -> None:
    try:
        with Session(engine) as session:
            record = session.get(GenerationRecord, record_id)
            if not record:
                return
            params_internal = _json_loads(record.params_internal_json, {})
            request_payload = params_internal.get("request_payload") if isinstance(params_internal.get("request_payload"), dict) else {}
            submit_prompt = str(request_payload.get("prompt") or record.prompt or "").strip()

        backend_task_id = _submit_nano_task(
            params_internal["internal_model"],
            prompt=submit_prompt,
            resolution=params_internal["resolution"],
            aspect_ratio=params_internal["aspect_ratio"],
            urls=params_internal.get("reference_images", []),
        )
        _mark_processing(record_id, backend_task_id)
        preview_url = _poll_nano_task(backend_task_id)
        _complete_record_success(record_id, preview_url=preview_url)
        _apply_success_to_target(record_id, preview_url=preview_url)
        _persist_record_media_to_oss(record_id)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        _mark_failed(
            record_id,
            error_code=str(detail.get("error") or "generation_failed"),
            message=str(detail.get("message") or "鍥剧墖鐢熸垚澶辫触锛岃绋嶅悗閲嶈瘯"),
            internal_message=str(exc.detail),
        )
    except Exception as exc:
        _mark_failed(record_id, error_code="generation_failed", message="鍥剧墖鐢熸垚澶辫触锛岃绋嶅悗閲嶈瘯", internal_message=str(exc))


def _run_video_generation_job(record_id: int) -> None:
    try:
        with Session(engine) as session:
            record = session.get(GenerationRecord, record_id)
            if not record:
                return
            params_public = _json_loads(record.params_public_json, {})
            params_internal = _json_loads(record.params_internal_json, {})
            payload = params_internal.get("request_payload", {})

        internal_model, backend_task_id = _submit_video_task(params_public, payload)
        _mark_processing(record_id, backend_task_id)
        preview_url = _poll_video_task(internal_model, backend_task_id)
        _complete_record_success(record_id, preview_url=preview_url)
        _apply_success_to_target(record_id, preview_url=preview_url)
        _persist_record_media_to_oss(record_id)
    except HTTPException as exc:
        logger.exception("视频生成任务失败（HTTPException），record_id=%s", record_id)
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        _mark_failed(
            record_id,
            error_code=str(detail.get("error") or "generation_failed"),
            message=str(detail.get("message") or "视频生成失败，请稍后重试"),
            internal_message=str(exc.detail),
        )
    except Exception as exc:
        logger.exception("视频生成任务失败（Exception），record_id=%s", record_id)
        _mark_failed(record_id, error_code="generation_failed", message="视频生成失败，请稍后重试", internal_message=str(exc))


def _run_asset_generation_job(record_id: int) -> None:
    try:
        with Session(engine) as session:
            record = session.get(GenerationRecord, record_id)
            if not record:
                return
            params_internal = _json_loads(record.params_internal_json, {})
            task_id = str(record.task_id or "").strip()
            request_payload = params_internal.get("request_payload") if isinstance(params_internal.get("request_payload"), dict) else {}

        normalized = normalize_image_request(
            {
                "model_code": request_payload.get("model_code") or params_internal.get("model_code") or params_internal.get("internal_model"),
                "mode": request_payload.get("mode") or params_internal.get("generation_type"),
                "prompt": request_payload.get("prompt") or record.prompt,
                "resolution": request_payload.get("resolution") or params_internal.get("resolution"),
                "quality": request_payload.get("quality") or params_internal.get("quality"),
                "aspect_ratio": request_payload.get("aspect_ratio") or params_internal.get("aspect_ratio"),
                "reference_images": request_payload.get("reference_images") or params_internal.get("reference_images") or [],
            }
        )
        if task_id:
            update_task_job(
                task_id,
                stage="submitting",
                progress=15,
                message="资产参考图生成中",
                provider=str(normalized.get("model_code") or ""),
            )
        submit_result = submit_image_request(normalized)
        completion_mode = str(submit_result.get("completion_mode") or "").strip().lower()
        if completion_mode == "immediate":
            preview_url = str(submit_result.get("output_url") or "").strip()
            if not preview_url:
                raise RuntimeError("资产参考图生成结果为空")
            _mark_processing(record_id, None)
            if task_id:
                update_task_job(task_id, stage="processing", progress=80, message="正在整理资产参考图结果")
        else:
            provider = str(submit_result.get("provider") or "").strip()
            backend_task_id = str(submit_result.get("upstream_task_id") or "").strip()
            if not provider or not backend_task_id:
                raise RuntimeError("资产参考图上游提交失败")
            _mark_processing(record_id, backend_task_id)
            if task_id:
                update_task_job(
                    task_id,
                    stage="polling",
                    progress=45,
                    message="资产参考图生成中",
                    provider=provider,
                    upstream_task_id=backend_task_id,
                )
            preview_url = ""
            for _ in range(200):
                time.sleep(3)
                result = query_image_generation(provider, backend_task_id)
                if result.is_done and not result.is_failed and result.output_url:
                    preview_url = str(result.output_url or "").strip()
                    break
                if result.is_done and result.is_failed:
                    raise RuntimeError(result.error or "资产参考图生成失败，请稍后重试")
            if not preview_url:
                raise RuntimeError("资产参考图生成超时，请稍后重试")
        _complete_record_success(record_id, preview_url=preview_url)
        _apply_success_to_target(record_id, preview_url=preview_url)
        _persist_record_media_to_oss(record_id)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        _mark_failed(
            record_id,
            error_code=str(detail.get("error") or "generation_failed"),
            message=str(detail.get("message") or "璧勪骇鐢熸垚澶辫触锛岃绋嶅悗閲嶈瘯"),
            internal_message=str(exc.detail),
        )
    except Exception as exc:
        _mark_failed(record_id, error_code="generation_failed", message="璧勪骇鐢熸垚澶辫触锛岃绋嶅悗閲嶈瘯", internal_message=str(exc))


def submit_image_generation(session: Session, *, background_tasks: BackgroundTasks, user: User, team: Team, payload: Dict[str, Any]) -> GenerationRecord:
    public_params, estimate_points = _estimate_image_public_params(session, payload)
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise public_http_error(400, "invalid_request", "prompt 涓嶈兘涓虹┖", field="prompt")
    if public_params["mode"] == IMAGE_MODE_IMAGE and not public_params["reference_image_count"]:
        raise public_http_error(400, "invalid_request", "鍥剧敓鍥炬ā寮忚嚦灏戦渶瑕佷竴寮犲弬鑰冨浘", field="reference_images")

    binding = _require_project_binding(session, team, payload)
    _ensure_affordable(session, user, team, estimate_points)
    if binding["target_note"]:
        public_params["target_note"] = binding["target_note"]
    public_params["prompt_summary"] = _prompt_summary(prompt)
    submit_prompt = _enhance_image_prompt_for_submission(
        session,
        binding=binding,
        payload=payload,
        prompt=prompt,
    )
    normalized = _normalize_productized_image_request({
        **payload,
        "prompt": submit_prompt,
    })

    internal_params = {
        "internal_model": normalized["model_code"],
        "model_code": normalized["model_code"],
        "generation_type": normalized["generation_type"],
        "resolution": normalized["resolution"],
        "aspect_ratio": normalized["aspect_ratio"],
        "reference_images": list(normalized["reference_images"]),
        "request_payload": {
            "mode": normalized["generation_type"],
            "generation_type": normalized["generation_type"],
            "model_code": normalized["model_code"],
            "resolution": normalized["resolution"],
            "aspect_ratio": normalized["aspect_ratio"],
            "reference_images": list(normalized["reference_images"]),
            "prompt": submit_prompt,
            "display_prompt": prompt,
            "negative_prompt": str(payload.get("negative_prompt") or "").strip() or None,
        },
    }
    record = _create_generation_record(
        session,
        user=user,
        team=team,
        record_type=RECORD_TYPE_IMAGE,
        ownership_mode=public_params["ownership_mode"],
        script_id=binding["script"].id if binding["script"] else None,
        episode_id=binding["episode"].id if binding["episode"] else None,
        target_type=binding["target_type"],
        target_id=binding["target_id"],
        prompt=prompt,
        negative_prompt=str(payload.get("negative_prompt") or "").strip() or None,
        params_internal=internal_params,
        params_public=public_params,
        estimate_points=estimate_points,
    )
    _enqueue_generation_record_task(
        session,
        record=record,
        task_type="media.generate_image",
        queue_name="media",
        provider=normalized["model_code"],
        max_retries=2,
    )
    return record


def submit_video_generation(session: Session, *, background_tasks: BackgroundTasks, user: User, team: Team, payload: Dict[str, Any]) -> GenerationRecord:
    payload = _apply_video_workflow_defaults(session, payload)
    public_params, estimate_points = _estimate_video_public_params(session, payload)
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise public_http_error(400, "invalid_request", "prompt 涓嶈兘涓虹┖", field="prompt")
    normalized = _normalize_productized_video_request(session, payload)

    binding = _require_project_binding(session, team, payload)
    _ensure_affordable(session, user, team, estimate_points)
    if binding["target_note"]:
        public_params["target_note"] = binding["target_note"]
    public_params["prompt_summary"] = _prompt_summary(prompt)
    submit_prompt = _enhance_video_prompt_for_submission(
        session,
        binding=binding,
        normalized=normalized,
        prompt=prompt,
    )

    internal_params = {
        "request_payload": {
            "prompt": submit_prompt,
            "display_prompt": prompt,
            "model_code": normalized["model_code"],
            "generation_type": normalized["generation_type"],
            "resolution": normalized["resolution"],
            "duration": normalized["duration"],
            "aspect_ratio": normalized["aspect_ratio"],
            "image_refs": list(normalized.get("image_refs") or []),
            "video_refs": list(normalized.get("video_refs") or []),
            "audio_refs": list(normalized.get("audio_refs") or []),
            "image_ref_entries": list(normalized.get("image_ref_entries") or []),
            "video_ref_entries": list(normalized.get("video_ref_entries") or []),
            "audio_ref_entries": list(normalized.get("audio_ref_entries") or []),
            "audio_enabled": bool(normalized.get("audio_enabled")),
            "first_frame": str(normalized.get("first_frame") or "").strip(),
            "last_frame": str(normalized.get("last_frame") or "").strip(),
            "motion_strength": normalized.get("motion_strength"),
            "camera_fixed": bool(normalized.get("camera_fixed")),
            "real_person_mode": bool(normalized.get("real_person_mode")),
            "web_search": bool(normalized.get("web_search")),
            "quality_mode": normalized.get("quality_mode"),
            "audio_url": str(normalized.get("audio_url") or "").strip(),
            "input_video_duration": int(normalized.get("input_video_duration") or 0),
        }
    }
    record = _create_generation_record(
        session,
        user=user,
        team=team,
        record_type=RECORD_TYPE_VIDEO,
        ownership_mode=public_params["ownership_mode"],
        script_id=binding["script"].id if binding["script"] else None,
        episode_id=binding["episode"].id if binding["episode"] else None,
        target_type=binding["target_type"],
        target_id=binding["target_id"],
        prompt=prompt,
        negative_prompt=None,
        params_internal=internal_params,
        params_public=public_params,
        estimate_points=estimate_points,
    )
    _enqueue_generation_record_task(
        session,
        record=record,
        task_type="media.generate_video",
        queue_name="media",
        provider=str(normalized["model_code"]),
        max_retries=2,
    )
    return record


def submit_asset_generation(session: Session, *, background_tasks: BackgroundTasks, user: User, team: Team, payload: Dict[str, Any]) -> GenerationRecord:
    _ensure_no_internal_keys(payload)
    asset_type = _normalize_asset_type(payload.get("asset_type"))
    normalized = _normalize_productized_image_request(
        {
            "model_code": payload.get("model_code") or payload.get("model"),
            "mode": GEN_IMAGE if payload.get("reference_images") else GEN_TEXT,
            "resolution": payload.get("resolution"),
            "quality": payload.get("quality"),
            "aspect_ratio": payload.get("aspect_ratio") or "1:1",
            "reference_images": payload.get("reference_images") or [],
            "prompt": payload.get("prompt"),
        }
    )
    model_code = normalized["model_code"]
    resolution = normalized["resolution"]
    quality = normalized.get("quality")
    aspect_ratio = _normalize_aspect_ratio(payload.get("aspect_ratio") or "1:1")
    prompt = str(payload.get("prompt") or "").strip()
    name = str(payload.get("name") or "").strip()
    if not prompt:
        raise public_http_error(400, "invalid_request", "prompt 涓嶈兘涓虹┖", field="prompt")
    if not name:
        raise public_http_error(400, "invalid_request", "name 涓嶈兘涓虹┖", field="name")

    binding = _require_project_binding(session, team, payload)
    if binding["ownership_mode"] == OWNERSHIP_MODE_PROJECT and binding["target_type"] not in {None, TARGET_TYPE_SHARED_RESOURCE, TARGET_TYPE_EPISODE_RECORD}:
        raise public_http_error(400, "invalid_target", "璧勪骇鐢熸垚涓嶆敮鎸佺粦瀹氬埌鍒嗛暅鐩爣", field="target_type")
    submit_prompt = _enhance_image_prompt_for_submission(
        session,
        binding=binding,
        payload=payload,
        prompt=prompt,
    )
    price = estimate_image_price(model_code, normalized["generation_type"], normalized)
    estimate_points = int(price["sell_price_points"])
    _ensure_affordable(session, user, team, estimate_points)

    public_params = {
        "asset_type": asset_type,
        "asset_type_label": ASSET_TYPE_LABELS[asset_type],
        "name": name,
        "description": str(payload.get("description") or "").strip() or None,
        "trigger_word": str(payload.get("trigger_word") or "").strip() or None,
        "aliases": [str(item).strip() for item in payload.get("aliases", []) if str(item).strip()],
        "model_code": model_code,
        "model": model_code,
        "model_label": normalized["model_name"],
        "resolution": resolution,
        "quality": quality,
        "quality_mode": quality,
        "quality_mode_label": normalized.get("quality_label"),
        "quality_label": None
        if model_code == "gpt-image-2-fast"
        else " · ".join([part for part in [normalized.get("quality_label"), resolution.upper()] if part]),
        "aspect_ratio": aspect_ratio,
        "aspect_ratio_label": aspect_ratio,
        "ownership_mode": binding["ownership_mode"],
        "ownership_mode_label": OWNERSHIP_MODE_LABELS[binding["ownership_mode"]],
        "prompt_summary": _prompt_summary(prompt),
        "pricing_rule_type": price["pricing_rule_type"],
        "pricing_note": price["pricing_note"],
        "pricing_details": price["pricing_details"],
    }
    internal_params = {
        "internal_model": model_code,
        "model_code": model_code,
        "generation_type": normalized["generation_type"],
        "resolution": resolution,
        "quality": quality,
        "aspect_ratio": aspect_ratio,
        "reference_images": list(normalized["reference_images"]),
        "request_payload": {
            "mode": normalized["generation_type"],
            "generation_type": normalized["generation_type"],
            "model_code": model_code,
            "resolution": resolution,
            "quality": quality,
            "aspect_ratio": aspect_ratio,
            "reference_images": list(normalized["reference_images"]),
            "prompt": submit_prompt,
            "display_prompt": prompt,
        },
    }
    target_type = binding["target_type"]
    if binding["ownership_mode"] == OWNERSHIP_MODE_PROJECT and not target_type:
        target_type = TARGET_TYPE_SHARED_RESOURCE

    record = _create_generation_record(
        session,
        user=user,
        team=team,
        record_type=RECORD_TYPE_ASSET,
        ownership_mode=binding["ownership_mode"],
        script_id=binding["script"].id if binding["script"] else None,
        episode_id=binding["episode"].id if binding["episode"] else None,
        target_type=target_type,
        target_id=binding["target_id"],
        prompt=prompt,
        negative_prompt=None,
        params_internal=internal_params,
        params_public=public_params,
        estimate_points=estimate_points,
    )
    _enqueue_generation_record_task(
        session,
        record=record,
        task_type="resource.generate_image",
        queue_name="resource",
        provider=model_code,
        max_retries=2,
    )
    return record


def _voice_type_for_source(source_type: str) -> str:
    if source_type == VOICE_SOURCE_NEW_CLONE:
        return "voice_cloning"
    if source_type == VOICE_SOURCE_NEW_DESIGN:
        return "voice_generation"
    if source_type == VOICE_SOURCE_SYSTEM:
        return "system"
    return "voice_generation"


def _voice_asset_source_label(source_type: str) -> str:
    return VOICE_SOURCE_LABELS.get(source_type, source_type)


def _join_voice_description(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _voice_contains(text: str, keywords: List[str]) -> bool:
    source = str(text or "").lower()
    return any(keyword.lower() in source for keyword in keywords)


def _classify_system_voice(display_name: str, voice_id: str, description: str) -> Dict[str, str]:
    merged = " ".join([display_name, voice_id, description]).strip()

    if _voice_contains(merged, ["santa", "grinch", "rudolph", "cartoon", "robot", "卡通", "机器人", "圣诞", "精灵"]):
        return {"category_label": "节日/卡通", "style_label": "角色特色"}
    if _voice_contains(merged, ["cantonese", "粤", "hk_flight_attendant"]):
        return {"category_label": "粤语", "style_label": "地区口音"}
    if _voice_contains(merged, ["english"]):
        return {"category_label": "英语", "style_label": "英文表达"}
    if _voice_contains(merged, ["japanese", "日语", "日文"]):
        return {"category_label": "日语", "style_label": "日语角色"}
    if _voice_contains(merged, ["korean", "韩语", "韩文"]):
        return {"category_label": "韩语", "style_label": "韩语角色"}
    if _voice_contains(merged, ["dutch", "vietnamese", "arabic", "spanish", "french", "german", "italian", "portuguese"]):
        return {"category_label": "其他语言", "style_label": "小语种"}
    if _voice_contains(merged, ["主播", "播报", "新闻", "host", "radio", "announcer", "flight_attendant", "高管", "讲述", "professional"]):
        return {"category_label": "中文口播", "style_label": "主持/讲述"}
    if _voice_contains(merged, ["男童", "女童", "童", "boy", "girl", "little sister", "teen", "student", "少年", "少女", "shaonv"]):
        return {"category_label": "中文角色", "style_label": "年轻/童声"}
    if _voice_contains(merged, ["御姐", "学姐", "王子", "公主", "皇后", "骑士", "queen", "prince", "princess", "knight", "warrior", "butler", "sister", "gentleman"]):
        return {"category_label": "中文角色", "style_label": "人物角色"}
    return {"category_label": "中文通用", "style_label": "通用表达"}


def _build_voice_search_text(*parts: Any) -> str:
    return " ".join(str(item).strip() for item in parts if str(item or "").strip())


def _upsert_voice_asset(
    session: Session,
    *,
    user_id: int,
    provider_voice_id: str,
    voice_type: str,
    source_type: str,
    display_name: str,
    description: Optional[str] = None,
    preview_audio_url: Optional[str] = None,
    created_at_source: Optional[str] = None,
) -> VoiceAsset:
    asset = session.exec(
        select(VoiceAsset).where(
            VoiceAsset.user_id == user_id,
            VoiceAsset.provider_voice_id == provider_voice_id,
        )
    ).first()
    now = _now()
    if not asset:
        asset = VoiceAsset(
            user_id=user_id,
            provider_voice_id=provider_voice_id,
            voice_type=voice_type,
            source_type=source_type,
            display_name=display_name,
            description=description,
            preview_audio_url=preview_audio_url,
            created_at_source=created_at_source,
            last_used_at=now,
            created_at=now,
            updated_at=now,
        )
    else:
        asset.voice_type = voice_type
        asset.source_type = source_type
        asset.display_name = display_name or asset.display_name
        asset.description = description if description is not None else asset.description
        asset.preview_audio_url = preview_audio_url or asset.preview_audio_url
        asset.created_at_source = created_at_source or asset.created_at_source
        asset.last_used_at = now
        asset.updated_at = now
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return asset


def _touch_voice_asset(session: Session, *, user_id: int, voice_id: str) -> None:
    if not voice_id:
        return
    asset = session.exec(
        select(VoiceAsset).where(VoiceAsset.user_id == user_id, VoiceAsset.provider_voice_id == voice_id)
    ).first()
    if not asset:
        return
    asset.last_used_at = _now()
    asset.updated_at = _now()
    session.add(asset)
    session.commit()


def _get_voice_activation_pricing(asset: VoiceAsset) -> Optional[Dict[str, Any]]:
    if asset.source_type == VOICE_SOURCE_NEW_DESIGN:
        return {
            "label": "设计音色启用",
            "cost_price": 9.9,
            "suggested_price": 14.85,
            "sell_price_points": 149,
        }
    if asset.source_type == VOICE_SOURCE_NEW_CLONE:
        return {
            "label": "复刻音色启用",
            "cost_price": 9.9,
            "suggested_price": 14.85,
            "sell_price_points": 149,
        }
    return None


def _attach_audio_voice_activation_charge(
    session: Session,
    *,
    user: User,
    normalized: Dict[str, Any],
    price: Dict[str, Any],
) -> Dict[str, Any]:
    if normalized["ability_type"] not in {ABILITY_REALTIME, ABILITY_NARRATION}:
        return price
    if normalized.get("voice_source_type") == VOICE_SOURCE_SYSTEM:
        return price
    voice_id = str(normalized.get("voice_id") or "").strip()
    if not voice_id:
        return price
    asset = session.exec(
        select(VoiceAsset).where(
            VoiceAsset.user_id == user.id,
            VoiceAsset.provider_voice_id == voice_id,
        )
    ).first()
    if not asset or asset.activation_billed_at:
        return price

    activation = _get_voice_activation_pricing(asset)
    if not activation:
        return price

    breakdown = list(price.get("breakdown", []))
    breakdown.append(dict(activation))
    return {
        **price,
        "cost_price": round(float(price.get("cost_price") or 0) + float(activation["cost_price"]), 2),
        "suggested_price": round(float(price.get("suggested_price") or 0) + float(activation["suggested_price"]), 2),
        "sell_price_points": int(price.get("sell_price_points") or 0) + int(activation["sell_price_points"]),
        "pricing_note": "{0}；首次正式使用该音色会额外收取{1}".format(
            price.get("pricing_note") or "",
            activation["label"],
        ).strip("；"),
        "breakdown": breakdown,
        "voice_activation_required": True,
        "voice_activation_label": activation["label"],
    }


def _record_owner_user_id(record_id: Optional[int]) -> Optional[int]:
    if not record_id:
        return None
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        return int(record.user_id) if record and record.user_id else None


def _upload_audio_bytes_result(content: bytes, filename: str = "dubbing-result.mp3", *, record_id: Optional[int] = None) -> Dict[str, Any]:
    return upload_bytes_to_oss_with_meta(
        content,
        filename,
        "audio/mpeg",
        owner_user_id=_record_owner_user_id(record_id),
        source_type="generation_record_audio",
        source_id=record_id,
    )


def _resolve_audio_result_to_oss(source: str, *, fallback_name: str = "dubbing-result.mp3", record_id: Optional[int] = None) -> Dict[str, Any]:
    text = str(source or "").strip()
    if not text:
        raise RuntimeError("音频结果为空")
    if text.startswith("http://") or text.startswith("https://"):
        return upload_remote_file_to_oss_with_meta(
            text,
            owner_user_id=_record_owner_user_id(record_id),
            source_type="generation_record_audio",
            source_id=record_id,
        )
    content = decode_hex_audio(text)
    if not content:
        raise RuntimeError("音频结果无法解析")
    return _upload_audio_bytes_result(content, fallback_name, record_id=record_id)


def _build_audio_public_params(normalized: Dict[str, Any], price: Dict[str, Any], *, prompt_summary: str = "") -> Dict[str, Any]:
    return {
        "ability_type": normalized["ability_type"],
        "ability_label": normalized["ability_label"],
        "tier_code": normalized["tier_code"],
        "tier_label": normalized["tier_label"],
        "model_code": normalized["model_code"],
        "voice_id": normalized["voice_id"],
        "voice_source_type": normalized["voice_source_type"],
        "voice_source_label": VOICE_SOURCE_LABELS.get(normalized["voice_source_type"], normalized["voice_source_type"]),
        "characters": price["characters"],
        "unit_count": price["unit_count"],
        "pricing_note": price["pricing_note"],
        "voice_activation_required": bool(price.get("voice_activation_required")),
        "voice_activation_label": price.get("voice_activation_label"),
        "prompt_summary": prompt_summary,
        "audio_format": normalized["audio_format"],
        "language_boost": normalized["language_boost"],
    }


def _build_audio_sync_request(normalized: Dict[str, Any]) -> Dict[str, Any]:
    def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        if value is None or value == "":
            return default
        try:
            return int(round(float(value)))
        except Exception:
            return default

    payload: Dict[str, Any] = {
        "model": normalized["model_code"],
        "text": normalized["preview_text"] if normalized["ability_type"] in {ABILITY_VOICE_DESIGN, ABILITY_VOICE_CLONE} else normalized["script_text"],
        "stream": False,
        "voice_setting": {
            "voice_id": normalized["voice_id"],
        },
        "audio_setting": {
            "sample_rate": _as_int(normalized.get("sample_rate"), 32000),
            "bitrate": _as_int(normalized.get("bitrate"), 128000),
            "format": normalized["audio_format"] or "mp3",
            "channel": _as_int(normalized.get("channel_count"), 1),
        },
        "subtitle_enable": bool(normalized["subtitle_enabled"]),
    }
    if normalized.get("emotion"):
        payload["voice_setting"]["emotion"] = normalized["emotion"]
    if normalized.get("speed") is not None:
        payload["voice_setting"]["speed"] = _as_int(normalized.get("speed"), 1)
    if normalized.get("volume") is not None:
        payload["voice_setting"]["vol"] = _as_int(normalized.get("volume"), 1)
    if normalized.get("pitch") is not None:
        payload["voice_setting"]["pitch"] = _as_int(normalized.get("pitch"), 0)
    return payload


def _build_audio_async_request(normalized: Dict[str, Any], *, owner_user_id: Optional[int] = None) -> Dict[str, Any]:
    def _as_int(value: Any, default: Optional[int] = None) -> Optional[int]:
        if value is None or value == "":
            return default
        try:
            return int(round(float(value)))
        except Exception:
            return default

    payload: Dict[str, Any] = {
        "model": normalized["model_code"],
        "voice_setting": {
            "voice_id": normalized["voice_id"],
        },
        "audio_setting": {
            "sample_rate": _as_int(normalized.get("sample_rate"), 32000),
            "bitrate": _as_int(normalized.get("bitrate"), 128000),
            "format": normalized["audio_format"] or "mp3",
            "channel": _as_int(normalized.get("channel_count"), 1),
        },
    }
    if normalized.get("script_text"):
        payload["text"] = normalized["script_text"]
    if normalized.get("text_file_url"):
        file_meta = upload_remote_file_to_oss_with_meta(
            normalized["text_file_url"],
            owner_user_id=owner_user_id,
            source_type="audio_text_file",
        )
        provider_file = minimax_audio_service.upload_file(
            content=requests.get(file_meta["file_url"], timeout=120).content,
            filename=file_meta.get("original_filename") or "narration.txt",
            purpose="file",
        )
        file_id = provider_file.get("file", {}).get("file_id") or provider_file.get("file_id")
        if file_id:
            payload["text_file_id"] = str(file_id)
    if normalized.get("speed") is not None:
        payload["voice_setting"]["speed"] = _as_int(normalized.get("speed"), 1)
    if normalized.get("volume") is not None:
        payload["voice_setting"]["vol"] = _as_int(normalized.get("volume"), 1)
    if normalized.get("pitch") is not None:
        payload["voice_setting"]["pitch"] = _as_int(normalized.get("pitch"), 0)
    if normalized.get("language_boost"):
        payload["language_boost"] = normalized["language_boost"]
    return payload


def _run_audio_async_job(record_id: int) -> None:
    try:
        with Session(engine) as session:
            record = session.get(GenerationRecord, record_id)
            if not record:
                return
            params_internal = _json_loads(record.params_internal_json, {})
            request_payload = params_internal.get("request_payload", {})
        result = minimax_audio_service.submit_long_narration(request_payload)
        task_id = str(result.get("task_id") or result.get("task_token") or "")
        file_id = str(result.get("file_id") or "")
        _mark_processing(record_id, task_id or None)
        deadline = time.time() + 900
        final_file_id = file_id
        while time.time() < deadline:
            time.sleep(5)
            query = minimax_audio_service.query_long_narration(task_id)
            status = str(query.get("status") or query.get("data", {}).get("status") or "").lower()
            final_file_id = str(query.get("file_id") or query.get("data", {}).get("file_id") or final_file_id or "")
            if status in {"success", "succeeded", "completed"} and final_file_id:
                content = minimax_audio_service.retrieve_file_content(final_file_id)
                meta = _upload_audio_bytes_result(content, "narration-result.mp3", record_id=record_id)
                _complete_record_success(record_id, preview_url=meta["file_url"], thumbnail_url="")
                return
            if status in {"failed", "error"}:
                raise RuntimeError("长文本旁白生成失败")
            if status in {"expired"}:
                _mark_failed(record_id, error_code="service_unavailable", message="配音结果已过期，请重新生成", internal_message="expired")
                return
        raise RuntimeError("长文本旁白生成超时")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        _mark_failed(record_id, error_code=str(detail.get("error") or "generation_failed"), message=str(detail.get("message") or "配音生成失败，请稍后重试"), internal_message=str(exc.detail))
    except Exception as exc:
        logger.exception("配音异步任务失败，record_id=%s", record_id)
        _mark_failed(record_id, error_code="generation_failed", message="配音生成失败，请稍后重试", internal_message=str(exc))


def _run_audio_generation_job(record_id: int) -> None:
    try:
        with Session(engine) as session:
            record = session.get(GenerationRecord, record_id)
            if not record:
                return
            params_internal = _json_loads(record.params_internal_json, {})
            normalized = params_internal.get("request_payload", {})
            if not isinstance(normalized, dict):
                raise RuntimeError("配音任务参数缺失")

        ability_type = normalized.get("ability_type")
        if ability_type == ABILITY_NARRATION:
            with Session(engine) as session:
                record = session.get(GenerationRecord, record_id)
                if not record:
                    return
                params_internal = _json_loads(record.params_internal_json, {})
                params_internal["request_payload"] = _build_audio_async_request(normalized, owner_user_id=record.user_id)
                record.params_internal_json = _json_dumps(params_internal)
                session.add(record)
                session.commit()
            _run_audio_async_job(record_id)
            return

        if ability_type == ABILITY_REALTIME:
            request_payload = _build_audio_sync_request(normalized)
            result = minimax_audio_service.synthesize_realtime(request_payload)
            audio_hex = str(result.get("data", {}).get("audio") or "")
            meta = _resolve_audio_result_to_oss(audio_hex, fallback_name="dubbing-result.{0}".format(normalized.get("audio_format") or "mp3"), record_id=record_id)
            _complete_record_success(record_id, preview_url=meta["file_url"], thumbnail_url="")
            with Session(engine) as session:
                record = session.get(GenerationRecord, record_id)
                if record:
                    _touch_voice_asset(session, user_id=record.user_id, voice_id=str(normalized.get("voice_id") or ""))
            return

        if ability_type == ABILITY_VOICE_DESIGN:
            result = minimax_audio_service.design_voice(
                {
                    "prompt": str(normalized.get("prompt") or "").strip(),
                    "preview_text": normalized.get("preview_text"),
                    "aigc_watermark": bool(normalized.get("watermark_enabled")),
                }
            )
            voice_id = str(result.get("voice_id") or "")
            trial_audio = str(result.get("trial_audio") or "")
            meta = _resolve_audio_result_to_oss(trial_audio, fallback_name="voice-design-preview.mp3", record_id=record_id)
            _complete_record_success(record_id, preview_url=meta["file_url"], thumbnail_url="")
            if voice_id:
                with Session(engine) as session:
                    record = session.get(GenerationRecord, record_id)
                    if record:
                        _upsert_voice_asset(
                            session,
                            user_id=record.user_id,
                            provider_voice_id=voice_id,
                            voice_type="voice_generation",
                            source_type=VOICE_SOURCE_NEW_DESIGN,
                            display_name="设计音色 {0}".format(voice_id[-8:]),
                            description=str(normalized.get("prompt") or "").strip(),
                            preview_audio_url=meta["file_url"],
                        )
            return

        if ability_type == ABILITY_VOICE_CLONE:
            reference_url = str(normalized.get("clone_reference_file") or "").strip()
            if not reference_url:
                raise public_http_error(400, "invalid_request", "请先上传参考音频", field="clone_reference_file")
            reference_bytes = requests.get(reference_url, timeout=120).content
            provider_file = minimax_audio_service.upload_file(
                content=reference_bytes,
                filename="voice-clone-reference.wav",
                purpose="voice_clone",
            )
            file_id = provider_file.get("file", {}).get("file_id") or provider_file.get("file_id")
            clone_payload: Dict[str, Any] = {
                "file_id": file_id,
                "voice_id": normalized.get("voice_id") or "voice-clone-{0}".format(uuid.uuid4().hex[:12]),
                "text": normalized.get("preview_text"),
                "model": AUDIO_TIER_HD == normalized.get("preview_tier_code") and "speech-2.8-hd" or "speech-2.8-turbo",
                "language_boost": normalized.get("language_boost") or "none",
                "need_noise_reduction": bool(normalized.get("noise_reduction")),
                "need_volume_normalization": bool(normalized.get("volume_normalization")),
                "aigc_watermark": bool(normalized.get("watermark_enabled")),
            }
            if normalized.get("clone_prompt_text"):
                clone_payload["clone_prompt"] = {"prompt_text": normalized.get("clone_prompt_text")}
            if normalized.get("clone_prompt_audio"):
                prompt_audio_bytes = requests.get(normalized["clone_prompt_audio"], timeout=120).content
                prompt_audio_file = minimax_audio_service.upload_file(
                    content=prompt_audio_bytes,
                    filename="voice-clone-prompt.wav",
                    purpose="voice_clone",
                )
                prompt_file_id = prompt_audio_file.get("file", {}).get("file_id") or prompt_audio_file.get("file_id")
                clone_payload.setdefault("clone_prompt", {})["prompt_audio"] = prompt_file_id
            result = minimax_audio_service.clone_voice(clone_payload)
            voice_id = str(result.get("voice_id") or clone_payload["voice_id"])
            demo_audio = str(result.get("demo_audio") or result.get("audio") or "")
            meta = _resolve_audio_result_to_oss(demo_audio, fallback_name="voice-clone-preview.mp3", record_id=record_id)
            _complete_record_success(record_id, preview_url=meta["file_url"], thumbnail_url="")
            with Session(engine) as session:
                record = session.get(GenerationRecord, record_id)
                if record:
                    _upsert_voice_asset(
                        session,
                        user_id=record.user_id,
                        provider_voice_id=voice_id,
                        voice_type="voice_cloning",
                        source_type=VOICE_SOURCE_NEW_CLONE,
                        display_name="复刻音色 {0}".format(voice_id[-8:]),
                        description="快速复刻音色",
                        preview_audio_url=meta["file_url"],
                    )
            return

        raise RuntimeError("当前配音能力不支持异步执行")
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        _mark_failed(
            record_id,
            error_code=str(detail.get("error") or "generation_failed"),
            message=str(detail.get("message") or "配音生成失败，请稍后重试"),
            internal_message=str(exc.detail),
        )
    except Exception as exc:
        logger.exception("配音任务失败，record_id=%s", record_id)
        _mark_failed(
            record_id,
            error_code="generation_failed",
            message="配音生成失败，请稍后重试",
            internal_message=str(exc),
        )


def submit_audio_generation(session: Session, *, background_tasks: BackgroundTasks, user: User, team: Team, payload: Dict[str, Any]) -> GenerationRecord:
    _ensure_no_internal_keys(payload)
    normalized = normalize_audio_request(payload)
    if normalized["ability_type"] == ABILITY_VOICE_MANAGEMENT:
        raise public_http_error(400, "invalid_request", "当前能力不支持直接生成", field="ability_type")
    price = estimate_audio_price(normalized)
    price = _attach_audio_voice_activation_charge(session, user=user, normalized=normalized, price=price)
    if not price["sell_price_points"]:
        raise public_http_error(400, "invalid_request", "当前组合价格待补充", retryable=False)
    binding = _require_project_binding(session, team, payload)
    _ensure_affordable(session, user, team, int(price["sell_price_points"]))
    normalized["prompt"] = str(payload.get("prompt") or "").strip()

    prompt_summary = _prompt_summary(
        normalized.get("preview_text")
        or normalized.get("script_text")
        or str(payload.get("prompt") or "")
    )
    public_params = _build_audio_public_params(normalized, price, prompt_summary=prompt_summary)
    internal_params = {"request_payload": normalized}

    record = _create_generation_record(
        session,
        user=user,
        team=team,
        record_type=RECORD_TYPE_AUDIO,
        ownership_mode=binding["ownership_mode"],
        script_id=binding["script"].id if binding["script"] else None,
        episode_id=binding["episode"].id if binding["episode"] else None,
        target_type=binding["target_type"],
        target_id=binding["target_id"],
        prompt=normalized.get("script_text") or normalized.get("preview_text") or str(payload.get("prompt") or ""),
        negative_prompt=None,
        params_internal=internal_params,
        params_public=public_params,
        estimate_points=int(price["sell_price_points"]),
    )
    _enqueue_generation_record_task(
        session,
        record=record,
        task_type="audio.generate",
        queue_name="audio",
        provider=str(normalized.get("model_code") or "minimax"),
        max_retries=2,
    )
    return record


def list_voice_assets(session: Session, *, user: User) -> Dict[str, Any]:
    local_assets = session.exec(select(VoiceAsset).where(VoiceAsset.user_id == user.id).order_by(VoiceAsset.id.desc())).all()
    assets: List[Dict[str, Any]] = []
    seen_ids = set()
    for item in local_assets:
        seen_ids.add(item.provider_voice_id)
        assets.append(
            {
                "asset_id": encode_id(item.id),
                "voice_id": item.provider_voice_id,
                "display_name": item.display_name,
                "voice_type": item.voice_type,
                "source_type": item.source_type,
                "source_label": _voice_asset_source_label(item.source_type),
                "description": item.description or "",
                "category_label": "我的音色",
                "style_label": "自定义",
                "search_text": _build_voice_search_text(item.display_name, item.provider_voice_id, item.description),
                "preview_audio_url": item.preview_audio_url,
                "created_at": _to_iso(item.created_at),
                "last_used_at": _to_iso(item.last_used_at),
                "activation_billed": bool(item.activation_billed_at),
                "deletable": item.source_type in {VOICE_SOURCE_NEW_DESIGN, VOICE_SOURCE_NEW_CLONE},
            }
        )

    try:
        provider = minimax_audio_service.get_voices("system")
    except Exception:
        logger.exception("系统音色查询失败，user_id=%s", user.id)
        provider = {}

    system_voices = provider.get("system_voice", []) or []
    logger.info("系统音色查询完成，user_id=%s, count=%s", user.id, len(system_voices))

    for item in system_voices:
        voice_id = str(item.get("voice_id") or "").strip()
        if not voice_id or voice_id in seen_ids:
            continue
        display_name = str(item.get("voice_name") or voice_id)
        description = _join_voice_description(item.get("description"))
        category = _classify_system_voice(display_name, voice_id, description)
        assets.append(
            {
                "asset_id": None,
                "voice_id": voice_id,
                "display_name": display_name,
                "voice_type": "system_voice",
                "source_type": VOICE_SOURCE_SYSTEM,
                "source_label": _voice_asset_source_label(VOICE_SOURCE_SYSTEM),
                "description": description,
                "category_label": category["category_label"],
                "style_label": category["style_label"],
                "search_text": _build_voice_search_text(display_name, voice_id, description, category["category_label"], category["style_label"]),
                "preview_audio_url": "",
                "created_at": None,
                "last_used_at": None,
                "activation_billed": True,
                "deletable": False,
            }
        )
        seen_ids.add(voice_id)

    return {"assets": assets}


def delete_voice_asset_record(session: Session, *, user: User, asset_id: str) -> None:
    real_id = _decode_external_id(asset_id, field_name="asset_id")
    if not real_id:
        raise public_http_error(404, "record_not_found", "音色资产不存在")
    asset = session.get(VoiceAsset, real_id)
    if not asset or asset.user_id != user.id:
        raise public_http_error(404, "record_not_found", "音色资产不存在")
    if asset.source_type not in {VOICE_SOURCE_NEW_DESIGN, VOICE_SOURCE_NEW_CLONE}:
        raise public_http_error(400, "invalid_request", "系统音色不可删除", retryable=False)
    try:
        minimax_audio_service.delete_voice(
            voice_type="voice_generation" if asset.source_type == VOICE_SOURCE_NEW_DESIGN else "voice_cloning",
            voice_id=asset.provider_voice_id,
        )
    except Exception:
        pass
    session.delete(asset)
    session.commit()


def _build_spec_summary(record: GenerationRecord, params_public: Dict[str, Any]) -> str:
    if record.record_type == RECORD_TYPE_IMAGE:
        return _image_spec_text(params_public, "稳定版")
    if record.record_type == RECORD_TYPE_VIDEO:
        parts: List[str] = []
        generation_type = params_public.get('generation_type')
        generation_type_label = params_public.get('generation_type_label')
        model_label = params_public.get('model_label', 'Vidu Q2')
        quality_mode_label = params_public.get('quality_mode_label')
        resolution_label = params_public.get('resolution_label')
        duration_label = params_public.get('duration_label')
        image_count = int(params_public.get('reference_image_count') or 0)
        video_count = int(params_public.get('reference_video_count') or 0)

        if generation_type_label:
            parts.append(generation_type_label)
        parts.append(model_label)
        if quality_mode_label:
            parts.append(quality_mode_label)
        if resolution_label:
            parts.append(resolution_label)
        if duration_label:
            parts.append(duration_label)

        if generation_type == GEN_REFERENCE:
            if image_count:
                parts.append(f"{image_count}张参考图")
            if video_count:
                parts.append(f"{video_count}个参考视频")
        elif generation_type == GEN_START_END:
            parts.append("首尾帧")

        return " · ".join(parts[:6])
    if record.record_type == RECORD_TYPE_AUDIO:
        parts: List[str] = []
        if params_public.get("ability_label"):
            parts.append(params_public.get("ability_label"))
        if params_public.get("tier_label"):
            parts.append(params_public.get("tier_label"))
        if params_public.get("characters"):
            parts.append("{0} 字符".format(params_public.get("characters")))
        return " · ".join(parts[:4])
    if record.record_type == RECORD_TYPE_EDITING:
        parts: List[str] = []
        if params_public.get("operation_type_label"):
            parts.append(params_public.get("operation_type_label"))
        if params_public.get("scope_label"):
            parts.append(params_public.get("scope_label"))
        if params_public.get("clip_count"):
            parts.append("{0} 个片段".format(params_public.get("clip_count")))
        if params_public.get("output_kind_label"):
            parts.append(params_public.get("output_kind_label"))
        return " · ".join(parts[:4])
    return f"{params_public.get('asset_type_label', '资产')} · {params_public.get('model_label', '稳定版')} · {params_public.get('quality_label', '2K')}"

def _serialize_related(
    session: Session,
    record: GenerationRecord,
    *,
    script_map: Optional[Dict[int, Script]] = None,
    episode_map: Optional[Dict[int, Episode]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    project = None
    episode = None
    target = None
    if record.script_id:
        script = script_map.get(record.script_id) if script_map is not None else session.get(Script, record.script_id)
        if script:
            project = {"project_id": encode_id(script.id), "name": script.name}
    if record.episode_id:
        episode_model = episode_map.get(record.episode_id) if episode_map is not None else session.get(Episode, record.episode_id)
        if episode_model:
            episode = {"episode_id": encode_id(episode_model.id), "title": episode_model.title}
    if record.target_type:
        target = {
            "target_type": record.target_type,
            "target_type_label": TARGET_TYPE_LABELS.get(record.target_type, record.target_type),
            "target_id": _encode_optional_id(record.target_id),
        }
    return project, episode, target


def serialize_generation_record(
    session: Session,
    record: GenerationRecord,
    *,
    include_detail: bool = False,
    script_map: Optional[Dict[int, Script]] = None,
    episode_map: Optional[Dict[int, Episode]] = None,
) -> Dict[str, Any]:
    params_public = _json_loads(record.params_public_json, {})
    params_internal = _json_loads(record.params_internal_json, {})
    source = str(params_public.get("source") or params_internal.get("source") or "webui").strip() or "webui"
    assistant_session_id = _normalize_assistant_session_id(params_internal)
    task_job = get_task_job(str(record.task_id or "")) if record.task_id else None
    effective_status = str(record.status or "")
    effective_status_label = STATUS_LABELS.get(effective_status, effective_status)
    if task_job:
        effective_status = str(task_job.status or effective_status)
        effective_status_label = STATUS_LABELS.get(effective_status, task_job.message or effective_status)
    has_record_failure = bool(
        str(record.error_code_public or "").strip()
        or str(record.error_message_public or "").strip()
        or str(record.error_message_internal or "").strip()
        or str(record.status or "").strip().lower() in {"failed", "error", "expired", "canceled", "cancelled", "timed_out"}
    )
    if has_record_failure:
        effective_status = STATUS_FAILED
        effective_status_label = STATUS_LABELS.get(STATUS_FAILED, STATUS_FAILED)
    user_status = _map_user_status(effective_status)
    failure_meta = _map_user_failure(
        record.error_code_public,
        record.error_message_public,
        record.error_message_internal,
    ) if user_status == USER_STATUS_FAILED else {"failure_reason": None, "failure_message": None}
    project, episode, target = _serialize_related(
        session,
        record,
        script_map=script_map,
        episode_map=episode_map,
    )
    resolved_preview_url = str(record.preview_url or "").strip()
    if not resolved_preview_url and record.record_type == RECORD_TYPE_IMAGE and str(record.status or "").strip().lower() == STATUS_COMPLETED:
        resolved_preview_url = str(_get_inline_preview_cache(record.id) or "").strip()
    resolved_thumbnail_url = (
        str(record.thumbnail_url or "").strip()
        or _derive_record_thumbnail_url(record.record_type, resolved_preview_url, record.thumbnail_url)
    )
    payload: Dict[str, Any] = {
        "record_id": _record_id(record),
        "record_type": record.record_type,
        "type": record.record_type,
        "task_id": record.task_id,
        "source": source,
        "ownership_mode": record.ownership_mode,
        "ownership_mode_label": OWNERSHIP_MODE_LABELS.get(record.ownership_mode, record.ownership_mode),
        "status": effective_status,
        "status_label": effective_status_label,
        "user_status": user_status,
        "user_status_label": USER_STATUS_LABELS[user_status],
        "failure_reason": failure_meta.get("failure_reason"),
        "failure_message": failure_meta.get("failure_message"),
        "preview_url": resolved_preview_url,
        "thumbnail_url": resolved_thumbnail_url,
        "prompt_summary": params_public.get("prompt_summary") or _prompt_summary(record.prompt),
        "project_id": _encode_optional_id(record.script_id),
        "episode_id": _encode_optional_id(record.episode_id),
        "assistant_session_id": assistant_session_id,
        "project": project,
        "episode": episode,
        "target": target,
        "spec_summary": _build_spec_summary(record, params_public),
        "estimate_points": record.estimate_points or 0,
        "actual_points": record.actual_points or 0,
        "created_at": _to_iso(record.created_at),
        "updated_at": _to_iso(record.updated_at),
        "params": params_public,
        "error": (
            {
                "error": record.error_code_public,
                "message": record.error_message_public,
                "retryable": record.error_code_public in {"service_unavailable", "generation_failed"},
                "failure_reason": failure_meta.get("failure_reason"),
                "failure_message": failure_meta.get("failure_message"),
            }
            if record.error_code_public
            else None
        ),
    }
    if include_detail:
        payload["prompt"] = record.prompt
        payload["negative_prompt"] = record.negative_prompt
        request_payload = params_internal.get("request_payload")
        if isinstance(request_payload, dict):
            payload["internal_request"] = request_payload
    return payload


def _serialize_generation_records(session: Session, records: List[GenerationRecord]) -> List[Dict[str, Any]]:
    if not records:
        return []

    script_ids = sorted({record.script_id for record in records if record.script_id})
    episode_ids = sorted({record.episode_id for record in records if record.episode_id})

    script_map: Dict[int, Script] = {}
    episode_map: Dict[int, Episode] = {}

    if script_ids:
        scripts = session.exec(select(Script).where(Script.id.in_(script_ids))).all()
        script_map = {item.id: item for item in scripts}
    if episode_ids:
        episodes = session.exec(select(Episode).where(Episode.id.in_(episode_ids))).all()
        episode_map = {item.id: item for item in episodes}

    return [
        serialize_generation_record(
            session,
            record,
            script_map=script_map,
            episode_map=episode_map,
        )
        for record in records
    ]


def _resolve_record_status_values(status: str) -> List[str]:
    normalized = str(status or "").strip().lower()
    if not normalized:
        return []
    mapping = {
        "queued": ["queued", "pending"],
        "processing": ["processing", "running", "waiting_upstream"],
        "waiting_upstream": ["waiting_upstream"],
        "completed": ["completed", "success"],
        "failed": ["failed", "canceled", "expired"],
    }
    if normalized not in mapping:
        raise public_http_error(400, "invalid_request", "status 不合法", field="status")
    return mapping[normalized]


def list_generation_records(
    session: Session,
    *,
    user: Optional[User] = None,
    team: Optional[Team] = None,
    record_type: Optional[str] = None,
    operation_type: Optional[str] = None,
    ownership_mode: Optional[str] = None,
    project_id: Optional[str] = None,
    episode_id: Optional[str] = None,
    q: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> Dict[str, Any]:
    if page < 1:
        page = 1
    page_size = min(max(page_size, 1), 50)
    if team is not None:
        statement = select(GenerationRecord).where(GenerationRecord.team_id == team.id)
        count_statement = select(func.count(GenerationRecord.id)).select_from(GenerationRecord).where(GenerationRecord.team_id == team.id)
    elif user is not None:
        statement = select(GenerationRecord).where(GenerationRecord.user_id == user.id)
        count_statement = select(func.count(GenerationRecord.id)).select_from(GenerationRecord).where(GenerationRecord.user_id == user.id)
    else:
        raise ValueError("list_generation_records requires either user or team scope")
    if record_type:
        normalized_record_type = str(record_type).strip().lower()
        if normalized_record_type not in {RECORD_TYPE_IMAGE, RECORD_TYPE_VIDEO, RECORD_TYPE_ASSET, RECORD_TYPE_AUDIO, RECORD_TYPE_EDITING}:
            raise public_http_error(400, "invalid_request", "record_type 不合法", field="record_type")
        statement = statement.where(GenerationRecord.record_type == normalized_record_type)
        count_statement = count_statement.where(GenerationRecord.record_type == normalized_record_type)
    if operation_type:
        normalized_operation_type = str(operation_type).strip().lower()
        if normalized_operation_type not in {"compose_video", "jianying_draft"}:
            raise public_http_error(400, "invalid_request", "operation_type 不合法", field="operation_type")
        operation_filter = func.lower(func.coalesce(GenerationRecord.params_public_json, "")).like(
            f'%\"operation_type\": \"{normalized_operation_type}\"%'
        )
        statement = statement.where(operation_filter)
        count_statement = count_statement.where(operation_filter)
    if ownership_mode:
        normalized_ownership_mode = _normalize_ownership_mode(ownership_mode)
        statement = statement.where(GenerationRecord.ownership_mode == normalized_ownership_mode)
        count_statement = count_statement.where(GenerationRecord.ownership_mode == normalized_ownership_mode)
    if project_id:
        decoded_project_id = _decode_external_id(project_id, field_name="project_id")
        statement = statement.where(
            GenerationRecord.script_id == decoded_project_id
        )
        count_statement = count_statement.where(GenerationRecord.script_id == decoded_project_id)
    if episode_id:
        decoded_episode_id = _decode_external_id(episode_id, field_name="episode_id")
        statement = statement.where(
            GenerationRecord.episode_id == decoded_episode_id
        )
        count_statement = count_statement.where(GenerationRecord.episode_id == decoded_episode_id)
    if status:
        resolved_statuses = _resolve_record_status_values(status)
        statement = statement.where(GenerationRecord.status.in_(resolved_statuses))
        count_statement = count_statement.where(GenerationRecord.status.in_(resolved_statuses))

    parsed_date_from = _parse_external_datetime(date_from, field_name="date_from")
    parsed_date_to = _parse_external_datetime(date_to, field_name="date_to")
    if parsed_date_from and parsed_date_to and parsed_date_from > parsed_date_to:
        raise public_http_error(400, "invalid_request", "时间范围不合法", field="date_from")
    if parsed_date_from:
        statement = statement.where(GenerationRecord.created_at >= parsed_date_from)
        count_statement = count_statement.where(GenerationRecord.created_at >= parsed_date_from)
    if parsed_date_to:
        statement = statement.where(GenerationRecord.created_at <= parsed_date_to)
        count_statement = count_statement.where(GenerationRecord.created_at <= parsed_date_to)

    keyword = str(q or "").strip()
    if keyword:
        statement = statement.outerjoin(Script, GenerationRecord.script_id == Script.id).outerjoin(Episode, GenerationRecord.episode_id == Episode.id)
        count_statement = count_statement.outerjoin(Script, GenerationRecord.script_id == Script.id).outerjoin(Episode, GenerationRecord.episode_id == Episode.id)
        like_value = f"%{keyword.lower()}%"
        keyword_filter = or_(
            func.lower(func.coalesce(GenerationRecord.prompt, "")).like(like_value),
            func.lower(func.coalesce(GenerationRecord.params_public_json, "")).like(like_value),
            func.lower(func.coalesce(Script.name, "")).like(like_value),
            func.lower(func.coalesce(Episode.title, "")).like(like_value),
        )
        statement = statement.where(
            keyword_filter
        )
        count_statement = count_statement.where(keyword_filter)

    normalized_sort_by = str(sort_by or "created_at").strip().lower()
    if normalized_sort_by != "created_at":
        raise public_http_error(400, "invalid_request", "sort_by 不合法", field="sort_by")
    normalized_sort_order = str(sort_order or "desc").strip().lower()
    if normalized_sort_order not in {"asc", "desc"}:
        raise public_http_error(400, "invalid_request", "sort_order 不合法", field="sort_order")

    order_column = GenerationRecord.created_at.asc() if normalized_sort_order == "asc" else GenerationRecord.created_at.desc()
    order_id_column = GenerationRecord.id.asc() if normalized_sort_order == "asc" else GenerationRecord.id.desc()
    start = (page - 1) * page_size
    total = int(session.exec(count_statement).one() or 0)
    records = session.exec(
        statement
        .order_by(order_column, order_id_column)
        .offset(start)
        .limit(page_size)
    ).all()
    return {
        "records": _serialize_generation_records(session, records),
        "pagination": {"page": page, "page_size": page_size, "total": total},
    }


def get_generation_record_detail(
    session: Session,
    *,
    user: Optional[User] = None,
    team: Optional[Team] = None,
    record_id: str,
) -> Dict[str, Any]:
    real_id = _decode_external_id(record_id, field_name="record_id")
    if not real_id:
        raise public_http_error(404, "record_not_found", "生成记录不存在")
    record = session.get(GenerationRecord, real_id)
    if not record:
        raise public_http_error(404, "record_not_found", "生成记录不存在")
    if team is not None and record.team_id != team.id:
        raise public_http_error(404, "record_not_found", "生成记录不存在")
    if team is None and user is not None and record.user_id != user.id:
        raise public_http_error(404, "record_not_found", "生成记录不存在")
    if team is None and user is None:
        raise public_http_error(404, "record_not_found", "生成记录不存在")
    return serialize_generation_record(session, record, include_detail=True)


def _clear_record_bound_target(session: Session, record: GenerationRecord) -> None:
    if record.target_type == TARGET_TYPE_PANEL and record.target_id:
        panel = session.get(Panel, record.target_id)
        if not panel:
            return
        if record.record_type == RECORD_TYPE_IMAGE:
            if panel.image_url == record.preview_url or panel.file_url == record.preview_url:
                panel.image_url = None
                if panel.file_url == record.preview_url:
                    panel.file_url = None
                if record.thumbnail_url and panel.thumbnail_url == record.thumbnail_url:
                    panel.thumbnail_url = None
                session.add(panel)
        elif record.record_type == RECORD_TYPE_VIDEO:
            if panel.video_url == record.preview_url:
                panel.video_url = None
                if not record.thumbnail_url or panel.video_thumbnail_url == record.thumbnail_url:
                    panel.video_thumbnail_url = None
                session.add(panel)
        return

    if record.target_type == TARGET_TYPE_SHARED_RESOURCE and record.target_id and record.record_type == RECORD_TYPE_IMAGE:
        resource = session.get(SharedResource, record.target_id)
        if resource and resource.file_url == record.preview_url:
            session.delete(resource)
        return

    if record.target_type == TARGET_TYPE_EPISODE_RECORD and record.target_id and record.record_type == RECORD_TYPE_EDITING:
        episode = session.get(Episode, record.target_id)
        if not episode:
            return
        params_public = _json_loads(record.params_public_json, {})
        if params_public.get("operation_type") != "compose_video":
            return
        if str(episode.composed_video_url or "").strip() == str(record.preview_url or "").strip():
            episode.composed_video_url = None
            episode.composed_video_thumbnail_url = None
            episode.composed_video_updated_at = None
            session.add(episode)


def delete_generation_record(session: Session, *, user: User, record_id: str) -> None:
    real_id = _decode_external_id(record_id, field_name="record_id")
    if not real_id:
        raise public_http_error(404, "record_not_found", "生成记录不存在")

    record = session.get(GenerationRecord, real_id)
    if not record or record.user_id != user.id:
        raise public_http_error(404, "record_not_found", "生成记录不存在")

    if record.record_type not in {RECORD_TYPE_IMAGE, RECORD_TYPE_VIDEO, RECORD_TYPE_AUDIO, RECORD_TYPE_EDITING}:
        raise public_http_error(400, "invalid_request", "当前仅支持删除图片、视频、配音和剪辑记录")

    if record.record_type in {RECORD_TYPE_IMAGE, RECORD_TYPE_VIDEO, RECORD_TYPE_EDITING} and record.status in {STATUS_QUEUED, STATUS_PROCESSING}:
        raise public_http_error(409, "invalid_request", "进行中的任务暂不支持删除", retryable=False)

    if record.record_type == RECORD_TYPE_AUDIO and record.status == STATUS_PROCESSING:
        raise public_http_error(409, "invalid_request", "正在生成中的配音任务暂不支持删除", retryable=False)

    _clear_record_bound_target(session, record)
    session.delete(record)
    session.commit()

