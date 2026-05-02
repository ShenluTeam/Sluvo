import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks
from sqlmodel import Session, select

from core.config import settings
from core.security import decode_id, encode_id
from database import engine
from models import CreativeEditingDraft, Episode, GenerationRecord, Panel, Script, Team, User
from schemas import (
    CREATIVE_EDITING_SOURCE_PANEL_IMAGE,
    CREATIVE_EDITING_SOURCE_PANEL_VIDEO,
    CREATIVE_EDITING_SOURCE_UPLOADED_IMAGE,
    CREATIVE_EDITING_SOURCE_UPLOADED_VIDEO,
    VALID_CREATIVE_EDITING_SOURCE_KINDS,
    VALID_CREATIVE_EDITING_TRANSITIONS,
)
from services.access_service import require_episode_team_access, require_script_team_access
from services.generation_record_service import (
    OWNERSHIP_MODE_PROJECT,
    OWNERSHIP_MODE_STANDALONE,
    TARGET_TYPE_EPISODE_RECORD,
    _complete_record_success,
    _create_generation_record,
    _json_dumps,
    _json_loads,
    _mark_failed,
    _mark_processing,
    public_http_error,
)
from services.jianying_draft_service import jianying_draft_service
from services.oss_service import build_oss_video_snapshot_url, upload_bytes_to_oss_with_meta
from services.video_compose_service import video_compose_service

logger = logging.getLogger(__name__)

RECORD_TYPE_EDITING = "editing"
OPERATION_TYPE_COMPOSE = "compose_video"
OPERATION_TYPE_JIANYING = "jianying_draft"
OUTPUT_KIND_VIDEO = "video"
OUTPUT_KIND_ZIP = "zip"
SCOPE_KIND_STANDALONE = "standalone"
SCOPE_KIND_PROJECT_EPISODE = "project_episode"
MAX_EDITING_CLIPS = 120
DEFAULT_UNKNOWN_CLIP_DURATION = 5.0
DEFAULT_ZOOM_LEVEL = 1.0
MIN_ZOOM_LEVEL = 0.5
MAX_ZOOM_LEVEL = 3.0

OPERATION_LABELS = {
    OPERATION_TYPE_COMPOSE: "成片合成",
    OPERATION_TYPE_JIANYING: "剪映草稿导出",
}
OUTPUT_KIND_LABELS = {
    OUTPUT_KIND_VIDEO: "MP4 成片",
    OUTPUT_KIND_ZIP: "剪映草稿 ZIP",
}


def _now() -> datetime:
    return datetime.utcnow()


def _iso(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.isoformat()


def _decode_external_id(value: Optional[str], *, field_name: str) -> Optional[int]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        decoded = decode_id(text)
    except Exception:
        decoded = None
    if not decoded:
        raise public_http_error(400, "invalid_request", "{0} 不合法".format(field_name), field=field_name)
    return int(decoded)


def _pick_panel_caption(panel: Panel, episode: Episode) -> str:
    mode = str(panel.storyboard_mode or episode.storyboard_mode or "commentary").strip().lower()
    if mode == "comic":
        return str(panel.dialogue_text or panel.original_text or "").strip()
    return str(panel.narration_text or panel.original_text or "").strip()


def _normalize_transition(value: Optional[str]) -> str:
    transition = str(value or "cut").strip().lower() or "cut"
    if transition not in VALID_CREATIVE_EDITING_TRANSITIONS:
        raise public_http_error(400, "invalid_request", "transition_to_next 不合法", field="transition_to_next")
    return transition


def _normalize_music_volume(value: Any) -> float:
    try:
        volume = float(value if value is not None else 0.3)
    except Exception:
        raise public_http_error(400, "invalid_request", "music volume 不合法", field="music_track.volume")
    return max(0.0, min(volume, 1.0))


def _normalize_transition_duration(value: Any) -> float:
    try:
        duration = float(value if value is not None else 0.5)
    except Exception:
        raise public_http_error(400, "invalid_request", "transition_duration 不合法", field="transition_duration")
    if duration < 0:
        raise public_http_error(400, "invalid_request", "transition_duration 不能小于 0", field="transition_duration")
    return min(duration, 3.0)


def _normalize_zoom_level(value: Any) -> float:
    try:
        zoom = float(value if value is not None else DEFAULT_ZOOM_LEVEL)
    except Exception:
        zoom = DEFAULT_ZOOM_LEVEL
    return max(MIN_ZOOM_LEVEL, min(zoom, MAX_ZOOM_LEVEL))


def _normalize_seconds(value: Any, *, field_name: str, default: Optional[float] = None) -> Optional[float]:
    if value in (None, ""):
        return default
    try:
        seconds = float(value)
    except Exception:
        raise public_http_error(400, "invalid_request", "{0} 不合法".format(field_name), field=field_name)
    return seconds


def _scope_kind_for_ownership(ownership_mode: str) -> str:
    return SCOPE_KIND_PROJECT_EPISODE if ownership_mode == OWNERSHIP_MODE_PROJECT else SCOPE_KIND_STANDALONE


def _scope_label_for_ownership(ownership_mode: str) -> str:
    return "项目剧集剪辑" if ownership_mode == OWNERSHIP_MODE_PROJECT else "独立时间线剪辑"


def _operation_summary(operation_type: str, ownership_mode: str, clip_count: int, episode: Optional[Episode] = None) -> str:
    scope_title = _scope_label_for_ownership(ownership_mode)
    action_title = OPERATION_LABELS.get(operation_type, "剪辑任务")
    if episode and ownership_mode == OWNERSHIP_MODE_PROJECT:
        return "{0} · {1} · {2} 个片段".format(action_title, str(episode.title or "当前剧集").strip() or "当前剧集", clip_count)
    return "{0} · {1} · {2} 个片段".format(action_title, scope_title, clip_count)


def _normalize_duration_label(duration_seconds: float) -> str:
    try:
        duration_value = float(duration_seconds or 0.0)
    except Exception:
        duration_value = 0.0
    if duration_value <= 0:
        return "0"
    if duration_value >= 60:
        minutes = int(duration_value // 60)
        seconds = int(round(duration_value % 60))
        return "{0}分{1}秒".format(minutes, seconds)
    return "{0}".format(round(duration_value, 1)).rstrip("0").rstrip(".")


def _dependency_message_for_compose() -> str:
    state = video_compose_service.get_dependency_state()
    if not state.get("ffmpeg"):
        return "服务器暂未安装 ffmpeg，当前无法执行成片合成"
    if not state.get("ffprobe"):
        return "服务器暂未安装 ffprobe，当前无法读取片段媒体信息"
    return ""


def _dependency_message_for_jianying() -> str:
    state = jianying_draft_service.get_dependency_state()
    if not state.get("py_jianying_draft"):
        return "服务器暂未安装 pyJianYingDraft，当前无法导出剪映草稿"
    if not state.get("mediainfo"):
        return "服务器暂未安装 mediainfo，当前无法导出剪映草稿"
    return ""


def get_creative_editing_catalog() -> Dict[str, Any]:
    compose_message = _dependency_message_for_compose()
    jianying_message = _dependency_message_for_jianying()
    return {
        "success": True,
        "data": {
            "supports_visual_editor": True,
            "supported_modes": [SCOPE_KIND_STANDALONE, SCOPE_KIND_PROJECT_EPISODE],
            "max_clips": MAX_EDITING_CLIPS,
            "transitions": [
                {"value": "cut", "label": "直接切换"},
                {"value": "fade", "label": "淡入淡出"},
                {"value": "dissolve", "label": "溶解"},
                {"value": "wipe", "label": "擦除"},
            ],
            "preview_transitions": ["cut", "fade", "dissolve", "wipe"],
            "timeline": {
                "min_zoom": MIN_ZOOM_LEVEL,
                "max_zoom": MAX_ZOOM_LEVEL,
                "default_zoom": DEFAULT_ZOOM_LEVEL,
                "default_pixels_per_second": 64,
                "autosave_delay_ms": 800,
            },
            "defaults": {
                "use_transitions": True,
                "transition_duration": 0.5,
                "music_volume": 0.3,
                "jianying_version": "6",
                "include_subtitles": True,
                "draft_path_placeholder": getattr(settings, "JIANYING_DRAFT_PATH_PLACEHOLDER", "") or "",
            },
            "dependencies": {
                "ffmpeg": bool(video_compose_service.get_dependency_state().get("ffmpeg")),
                "ffprobe": bool(video_compose_service.get_dependency_state().get("ffprobe")),
                "py_jianying_draft": bool(jianying_draft_service.get_dependency_state().get("py_jianying_draft")),
                "mediainfo": bool(jianying_draft_service.get_dependency_state().get("mediainfo")),
            },
            "operations": {
                OPERATION_TYPE_COMPOSE: {
                    "enabled": not bool(compose_message),
                    "label": OPERATION_LABELS[OPERATION_TYPE_COMPOSE],
                    "output_kind": OUTPUT_KIND_VIDEO,
                    "message": compose_message or "可用",
                },
                OPERATION_TYPE_JIANYING: {
                    "enabled": not bool(jianying_message),
                    "label": OPERATION_LABELS[OPERATION_TYPE_JIANYING],
                    "output_kind": OUTPUT_KIND_ZIP,
                    "message": jianying_message or "可用",
                },
            },
        },
    }


def _build_panel_asset_id(panel: Panel) -> str:
    return "panel:{0}".format(encode_id(panel.id))


def _extract_panel_media_meta(panel: Panel) -> Tuple[float, Optional[bool]]:
    duration_seconds = DEFAULT_UNKNOWN_CLIP_DURATION
    has_audio = None
    history = _json_loads(panel.video_history_json, [])
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            try:
                if item.get("duration_seconds") not in (None, ""):
                    duration_seconds = float(item.get("duration_seconds") or duration_seconds)
            except Exception:
                duration_seconds = DEFAULT_UNKNOWN_CLIP_DURATION
            if item.get("has_audio") is not None:
                has_audio = bool(item.get("has_audio"))
            break
    return max(float(duration_seconds or DEFAULT_UNKNOWN_CLIP_DURATION), 0.1), has_audio


def _get_episode_media_panels(session: Session, episode_id: int) -> List[Panel]:
    panels = session.exec(
        select(Panel)
        .where(Panel.episode_id == episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    return [
        panel
        for panel in panels
        if str(panel.video_url or "").strip() or str(panel.image_url or "").strip()
    ]


def _build_source_asset_from_panel(panel: Panel, episode: Episode) -> Dict[str, Any]:
    if not str(panel.video_url or "").strip():
        return {
            "asset_id": _build_panel_asset_id(panel),
            "source_kind": CREATIVE_EDITING_SOURCE_PANEL_IMAGE,
            "panel_id": encode_id(panel.id),
            "name": "分镜 {0}".format(panel.sequence_num or panel.id),
            "video_url": None,
            "image_url": str(panel.image_url or "").strip(),
            "thumbnail_url": str(panel.thumbnail_url or panel.image_url or "").strip() or None,
            "source_duration_seconds": DEFAULT_UNKNOWN_CLIP_DURATION,
            "has_audio": False,
            "default_caption_text": _pick_panel_caption(panel, episode),
        }

    duration_seconds, has_audio = _extract_panel_media_meta(panel)
    return {
        "asset_id": _build_panel_asset_id(panel),
        "source_kind": CREATIVE_EDITING_SOURCE_PANEL_VIDEO,
        "panel_id": encode_id(panel.id),
        "name": "分镜 {0}".format(panel.sequence_num or panel.id),
        "video_url": str(panel.video_url or "").strip(),
        "image_url": None,
        "thumbnail_url": str(panel.video_thumbnail_url or panel.thumbnail_url or "").strip() or None,
        "source_duration_seconds": duration_seconds,
        "has_audio": has_audio,
        "default_caption_text": _pick_panel_caption(panel, episode),
    }


def _build_seeded_timeline(source_assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    timeline = []
    for index, asset in enumerate(source_assets):
        duration_seconds = float(asset.get("source_duration_seconds") or DEFAULT_UNKNOWN_CLIP_DURATION)
        timeline.append(
            {
                "clip_id": "clip:{0}:{1}".format(index + 1, asset["asset_id"]),
                "asset_id": asset["asset_id"],
                "enabled": True,
                "sequence": index + 1,
                "source_in_seconds": 0.0,
                "source_out_seconds": duration_seconds,
                "play_duration_seconds": duration_seconds,
                "transition_to_next": "cut",
                "caption_text": asset.get("default_caption_text") or "",
            }
        )
    return timeline


def _resolve_project_binding(
    session: Session,
    *,
    team: Team,
    ownership_mode: str,
    project_id: Optional[str],
    episode_id: Optional[str],
) -> Tuple[Optional[Script], Optional[Episode]]:
    if ownership_mode != OWNERSHIP_MODE_PROJECT:
        return None, None
    script = require_script_team_access(session, team, _decode_external_id(project_id, field_name="project_id"))
    episode = require_episode_team_access(session, team, _decode_external_id(episode_id, field_name="episode_id"))
    if episode.script_id != script.id:
        raise public_http_error(400, "invalid_request", "当前剧集不属于所选项目", field="episode_id")
    return script, episode


def _find_existing_draft(
    session: Session,
    *,
    user_id: int,
    ownership_mode: str,
    script_id: Optional[int],
    episode_id: Optional[int],
) -> Optional[CreativeEditingDraft]:
    statement = select(CreativeEditingDraft).where(
        CreativeEditingDraft.user_id == user_id,
        CreativeEditingDraft.ownership_mode == ownership_mode,
    )
    if ownership_mode == OWNERSHIP_MODE_PROJECT:
        statement = statement.where(CreativeEditingDraft.script_id == script_id, CreativeEditingDraft.episode_id == episode_id)
    else:
        statement = statement.where(CreativeEditingDraft.script_id == None, CreativeEditingDraft.episode_id == None)  # noqa: E711
    statement = statement.order_by(CreativeEditingDraft.updated_at.desc(), CreativeEditingDraft.id.desc())
    return session.exec(statement).first()


def _build_project_source_assets(
    session: Session,
    *,
    script: Script,
    episode: Episode,
) -> List[Dict[str, Any]]:
    del script
    panels = _get_episode_media_panels(session, episode.id)
    return [_build_source_asset_from_panel(panel, episode) for panel in panels]


def _serialize_draft(draft: CreativeEditingDraft, *, document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "draft_id": encode_id(draft.id),
        "ownership_mode": draft.ownership_mode,
        "project_id": encode_id(draft.script_id) if draft.script_id else None,
        "episode_id": encode_id(draft.episode_id) if draft.episode_id else None,
        "version": int(draft.version or 1),
        "updated_at": _iso(draft.updated_at),
        "created_at": _iso(draft.created_at),
        "document": document,
        "summary": {
            "asset_count": len(document.get("source_assets") or []),
            "clip_count": len(document.get("timeline_clips") or []),
            "enabled_clip_count": len([item for item in document.get("timeline_clips") or [] if item.get("enabled")]),
            "version": int(draft.version or 1),
        },
    }


def _validate_ownership_mode(value: Optional[str]) -> str:
    ownership_mode = str(value or OWNERSHIP_MODE_STANDALONE).strip().lower()
    if ownership_mode not in {OWNERSHIP_MODE_PROJECT, OWNERSHIP_MODE_STANDALONE}:
        raise public_http_error(400, "invalid_request", "ownership_mode 不合法", field="ownership_mode")
    return ownership_mode


def _sanitize_standalone_source_assets(raw_assets: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    if raw_assets is None:
        raw_assets = []
    if not isinstance(raw_assets, list):
        raise public_http_error(400, "invalid_request", "source_assets 不合法", field="document.source_assets")

    warnings = []
    normalized_assets = []
    seen_asset_ids = set()
    for index, item in enumerate(raw_assets):
        if not isinstance(item, dict):
            raise public_http_error(400, "invalid_request", "source_assets[{0}] 不合法".format(index), field="document.source_assets")
        asset_id = str(item.get("asset_id") or "").strip()
        if not asset_id:
            raise public_http_error(400, "invalid_request", "asset_id 不能为空", field="document.source_assets")
        if asset_id in seen_asset_ids:
            raise public_http_error(400, "invalid_request", "素材 asset_id 重复", field="document.source_assets")
        seen_asset_ids.add(asset_id)
        source_kind = str(item.get("source_kind") or "").strip().lower()
        if source_kind not in VALID_CREATIVE_EDITING_SOURCE_KINDS:
            raise public_http_error(400, "invalid_request", "source_kind 不合法", field="document.source_assets")
        if source_kind not in {CREATIVE_EDITING_SOURCE_UPLOADED_VIDEO, CREATIVE_EDITING_SOURCE_UPLOADED_IMAGE}:
            raise public_http_error(400, "invalid_request", "独立模式只允许上传图片或视频素材", field="document.source_assets")
        is_image_asset = source_kind == CREATIVE_EDITING_SOURCE_UPLOADED_IMAGE
        video_url = str(item.get("video_url") or "").strip()
        image_url = str(item.get("image_url") or "").strip()
        source_url = image_url if is_image_asset else video_url
        if not source_url:
            raise public_http_error(
                400,
                "invalid_request",
                "图片素材必须提供 image_url，视频素材必须提供 video_url",
                field="document.source_assets",
            )
        duration_seconds = _normalize_seconds(
            item.get("source_duration_seconds"),
            field_name="document.source_assets.source_duration_seconds",
            default=None,
        )
        if not duration_seconds or duration_seconds <= 0:
            duration_seconds = DEFAULT_UNKNOWN_CLIP_DURATION
            warnings.append("存在缺少时长信息的素材，已按默认 5 秒处理")
        normalized_assets.append(
            {
                "asset_id": asset_id,
                "source_kind": source_kind,
                "panel_id": None,
                "name": str(item.get("name") or "上传素材").strip() or "上传素材",
                "video_url": video_url or None,
                "image_url": image_url or None,
                "thumbnail_url": str(item.get("thumbnail_url") or image_url or video_url or "").strip() or None,
                "source_duration_seconds": float(duration_seconds),
                "has_audio": False if is_image_asset else (bool(item.get("has_audio")) if item.get("has_audio") is not None else None),
                "default_caption_text": str(item.get("default_caption_text") or "").strip() or "",
            }
        )
    return normalized_assets, warnings


def _sanitize_timeline(
    raw_clips: Any,
    *,
    asset_lookup: Dict[str, Dict[str, Any]],
    allow_empty: bool,
    require_enabled_clip: bool,
    transition_duration: float,
    use_transitions: bool,
    ownership_mode: str,
) -> Tuple[List[Dict[str, Any]], int, float, List[str], Optional[str]]:
    if raw_clips is None:
        raw_clips = []
    if not isinstance(raw_clips, list):
        raise public_http_error(400, "invalid_request", "timeline_clips 不合法", field="document.timeline_clips")
    if len(raw_clips) > MAX_EDITING_CLIPS:
        raise public_http_error(400, "invalid_request", "当前时间线片段数量超过上限", field="document.timeline_clips")
    if not raw_clips and not allow_empty:
        raise public_http_error(400, "invalid_request", "当前时间线还没有片段", field="document.timeline_clips")

    normalized_clips = []
    warnings = []
    seen_clip_ids = set()
    for index, item in enumerate(sorted(raw_clips, key=lambda value: int((value or {}).get("sequence") or 0))):
        if not isinstance(item, dict):
            raise public_http_error(400, "invalid_request", "timeline_clips[{0}] 不合法".format(index), field="document.timeline_clips")
        clip_id = str(item.get("clip_id") or "").strip()
        if not clip_id:
            raise public_http_error(400, "invalid_request", "clip_id 不能为空", field="document.timeline_clips")
        if clip_id in seen_clip_ids:
            raise public_http_error(400, "invalid_request", "时间线 clip_id 重复", field="document.timeline_clips")
        seen_clip_ids.add(clip_id)

        asset_id = str(item.get("asset_id") or "").strip()
        asset = asset_lookup.get(asset_id)
        if not asset:
            raise public_http_error(400, "invalid_request", "存在无效的素材引用", field="document.timeline_clips")
        if ownership_mode == OWNERSHIP_MODE_PROJECT and asset.get("source_kind") not in {CREATIVE_EDITING_SOURCE_PANEL_VIDEO, CREATIVE_EDITING_SOURCE_PANEL_IMAGE}:
            raise public_http_error(400, "invalid_request", "项目模式只允许引用当前剧集的分镜素材", field="document.timeline_clips")

        source_duration_seconds = float(asset.get("source_duration_seconds") or DEFAULT_UNKNOWN_CLIP_DURATION)
        source_in_seconds = _normalize_seconds(item.get("source_in_seconds"), field_name="document.timeline_clips.source_in_seconds", default=0.0) or 0.0
        if source_in_seconds < 0:
            raise public_http_error(400, "invalid_request", "source_in_seconds 不能小于 0", field="document.timeline_clips")
        source_out_seconds = _normalize_seconds(item.get("source_out_seconds"), field_name="document.timeline_clips.source_out_seconds", default=source_duration_seconds)
        if source_out_seconds is None or source_out_seconds <= 0:
            source_out_seconds = source_duration_seconds
        source_out_seconds = min(source_out_seconds, source_duration_seconds)
        if source_out_seconds <= source_in_seconds:
            raise public_http_error(400, "invalid_request", "片段裁剪范围无效", field="document.timeline_clips")

        play_duration_seconds = round(source_out_seconds - source_in_seconds, 3)
        normalized_clips.append(
            {
                "clip_id": clip_id,
                "asset_id": asset_id,
                "enabled": bool(item.get("enabled", True)),
                "sequence": len(normalized_clips) + 1,
                "source_in_seconds": round(source_in_seconds, 3),
                "source_out_seconds": round(source_out_seconds, 3),
                "play_duration_seconds": play_duration_seconds,
                "transition_to_next": _normalize_transition(item.get("transition_to_next")),
                "caption_text": str(item.get("caption_text") or asset.get("default_caption_text") or "").strip(),
                "source_kind": asset.get("source_kind"),
                "panel_id": asset.get("panel_id"),
                "video_url": asset.get("video_url"),
                "image_url": asset.get("image_url"),
                "thumbnail_url": asset.get("thumbnail_url"),
                "name": asset.get("name"),
                "has_audio": asset.get("has_audio"),
            }
        )

    enabled_clips = [item for item in normalized_clips if item.get("enabled")]
    if require_enabled_clip and not enabled_clips:
        raise public_http_error(400, "invalid_request", "当前时间线没有启用的片段", field="document.timeline_clips")

    estimated_duration_seconds = 0.0
    first_thumbnail_url = None
    for index, clip in enumerate(enabled_clips):
        estimated_duration_seconds += float(clip.get("play_duration_seconds") or 0.0)
        if first_thumbnail_url is None and clip.get("thumbnail_url"):
            first_thumbnail_url = clip.get("thumbnail_url")
        if first_thumbnail_url is None and clip.get("image_url"):
            first_thumbnail_url = clip.get("image_url")
        if use_transitions and index < len(enabled_clips) - 1:
            transition_key = str(clip.get("transition_to_next") or "cut").strip().lower()
            if transition_key != "cut":
                next_duration = float(enabled_clips[index + 1].get("play_duration_seconds") or 0.0)
                overlap = min(float(transition_duration or 0.0), float(clip.get("play_duration_seconds") or 0.0), next_duration)
                estimated_duration_seconds = max(0.0, estimated_duration_seconds - overlap)

    if not first_thumbnail_url and normalized_clips:
        first_thumbnail_url = normalized_clips[0].get("thumbnail_url") or normalized_clips[0].get("image_url")
    return normalized_clips, len(enabled_clips), round(estimated_duration_seconds, 2), warnings, first_thumbnail_url


def _normalize_editing_document(
    session: Session,
    *,
    team: Team,
    payload: Dict[str, Any],
    allow_empty_timeline: bool = False,
    require_enabled_clip: bool = True,
) -> Dict[str, Any]:
    ownership_mode = _validate_ownership_mode(payload.get("ownership_mode"))
    script, episode = _resolve_project_binding(
        session,
        team=team,
        ownership_mode=ownership_mode,
        project_id=payload.get("project_id"),
        episode_id=payload.get("episode_id"),
    )
    document = payload.get("document")
    if not isinstance(document, dict):
        raise public_http_error(400, "invalid_request", "document 不合法", field="document")

    use_transitions = bool(document.get("use_transitions", True))
    transition_duration = _normalize_transition_duration(document.get("transition_duration"))
    warnings = []

    if ownership_mode == OWNERSHIP_MODE_PROJECT:
        source_assets = _build_project_source_assets(session, script=script, episode=episode)
    else:
        source_assets, asset_warnings = _sanitize_standalone_source_assets(document.get("source_assets"))
        warnings.extend(asset_warnings)

    asset_lookup = {item["asset_id"]: item for item in source_assets}
    normalized_clips, enabled_clip_count, estimated_duration_seconds, clip_warnings, first_thumbnail_url = _sanitize_timeline(
        document.get("timeline_clips"),
        asset_lookup=asset_lookup,
        allow_empty=allow_empty_timeline,
        require_enabled_clip=require_enabled_clip,
        transition_duration=transition_duration,
        use_transitions=use_transitions,
        ownership_mode=ownership_mode,
    )
    warnings.extend(clip_warnings)

    raw_music = document.get("music_track") or {}
    if raw_music and not isinstance(raw_music, dict):
        raise public_http_error(400, "invalid_request", "music_track 不合法", field="document.music_track")
    music_audio_url = str(raw_music.get("audio_url") or "").strip() or None
    music_enabled = bool(raw_music.get("enabled")) and bool(music_audio_url)
    music_volume = _normalize_music_volume(raw_music.get("volume"))
    music_start_seconds = _normalize_seconds(raw_music.get("start_seconds"), field_name="music_track.start_seconds", default=0.0) or 0.0
    music_duration_seconds = _normalize_seconds(raw_music.get("duration_seconds"), field_name="music_track.duration_seconds", default=None)
    if music_duration_seconds is not None and music_duration_seconds <= 0:
        music_duration_seconds = None
    music_track = {
        "audio_url": music_audio_url,
        "enabled": music_enabled,
        "volume": music_volume,
        "start_seconds": round(max(0.0, music_start_seconds), 3),
        "duration_seconds": round(float(music_duration_seconds), 3) if music_duration_seconds is not None else None,
    }

    playhead_seconds = _normalize_seconds(document.get("playhead_seconds"), field_name="document.playhead_seconds", default=0.0) or 0.0
    selected_clip_id = str(document.get("selected_clip_id") or "").strip() or None
    if selected_clip_id and selected_clip_id not in {item["clip_id"] for item in normalized_clips}:
        selected_clip_id = None

    normalized_document = {
        "version": max(int(document.get("version") or 1), 1),
        "ownership_mode": ownership_mode,
        "project_id": encode_id(script.id) if script else None,
        "episode_id": encode_id(episode.id) if episode else None,
        "source_assets": source_assets,
        "timeline_clips": normalized_clips,
        "music_track": music_track if music_audio_url else None,
        "use_transitions": use_transitions,
        "transition_duration": transition_duration,
        "playhead_seconds": round(max(0.0, playhead_seconds), 3),
        "zoom_level": _normalize_zoom_level(document.get("zoom_level")),
        "selected_clip_id": selected_clip_id,
    }

    timeline_manifest = []
    for clip in normalized_clips:
        timeline_manifest.append(
            {
                "clip_id": clip["clip_id"],
                "asset_id": clip["asset_id"],
                "source_kind": clip.get("source_kind"),
                "panel_id": clip.get("panel_id"),
                "video_url": clip.get("video_url"),
                "image_url": clip.get("image_url"),
                "thumbnail_url": clip.get("thumbnail_url"),
                "caption_text": clip.get("caption_text"),
                "transition_to_next": clip.get("transition_to_next"),
                "enabled": clip.get("enabled"),
                "duration_seconds": clip.get("play_duration_seconds"),
                "source_in_seconds": clip.get("source_in_seconds"),
                "source_out_seconds": clip.get("source_out_seconds"),
                "name": clip.get("name"),
                "has_audio": clip.get("has_audio"),
            }
        )

    return {
        "ownership_mode": ownership_mode,
        "scope_kind": _scope_kind_for_ownership(ownership_mode),
        "scope_label": _scope_label_for_ownership(ownership_mode),
        "script": script,
        "episode": episode,
        "document": normalized_document,
        "source_assets": source_assets,
        "timeline_manifest": timeline_manifest,
        "clip_count": enabled_clip_count,
        "estimated_duration_seconds": estimated_duration_seconds,
        "warnings": sorted(set([item for item in warnings if item])),
        "music_audio_url": music_audio_url if music_enabled else None,
        "music_volume": music_volume,
        "music_enabled": music_enabled,
        "music_start_seconds": round(max(0.0, music_start_seconds), 3),
        "music_duration_seconds": round(float(music_duration_seconds), 3) if music_duration_seconds is not None else None,
        "use_transitions": use_transitions,
        "transition_duration": transition_duration,
        "preferred_aspect_ratio": str(getattr(script, "aspect_ratio", "") or "").strip() if script else "",
        "first_thumbnail_url": first_thumbnail_url,
    }


def get_creative_editing_timeline_seed(
    session: Session,
    *,
    user: User,
    team: Team,
    ownership_mode: str,
    project_id: Optional[str] = None,
    episode_id: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_ownership_mode = _validate_ownership_mode(ownership_mode)
    if normalized_ownership_mode == OWNERSHIP_MODE_STANDALONE:
        draft = _find_existing_draft(session, user_id=user.id, ownership_mode=OWNERSHIP_MODE_STANDALONE, script_id=None, episode_id=None)
        draft_summary = None
        if draft:
            raw_document = _json_loads(draft.document_json, {})
            draft_summary = {
                "version": int(draft.version or 1),
                "updated_at": _iso(draft.updated_at),
                "asset_count": len((raw_document or {}).get("source_assets") or []),
                "clip_count": len((raw_document or {}).get("timeline_clips") or []),
            }
        return {
            "success": True,
            "data": {
                "ownership_mode": OWNERSHIP_MODE_STANDALONE,
                "scope_kind": SCOPE_KIND_STANDALONE,
                "scope_label": _scope_label_for_ownership(OWNERSHIP_MODE_STANDALONE),
                "source_assets": [],
                "seeded_timeline": [],
                "draft_summary": draft_summary,
                "project_title": "",
                "episode_title": "",
            },
        }

    script, episode = _resolve_project_binding(
        session,
        team=team,
        ownership_mode=normalized_ownership_mode,
        project_id=project_id,
        episode_id=episode_id,
    )
    source_assets = _build_project_source_assets(session, script=script, episode=episode)
    seeded_timeline = _build_seeded_timeline(source_assets)
    draft = _find_existing_draft(session, user_id=user.id, ownership_mode=OWNERSHIP_MODE_PROJECT, script_id=script.id, episode_id=episode.id)
    draft_summary = None
    if draft:
        raw_document = _json_loads(draft.document_json, {})
        draft_summary = {
            "version": int(draft.version or 1),
            "updated_at": _iso(draft.updated_at),
            "asset_count": len((raw_document or {}).get("source_assets") or []),
            "clip_count": len((raw_document or {}).get("timeline_clips") or []),
        }
    return {
        "success": True,
        "data": {
            "ownership_mode": OWNERSHIP_MODE_PROJECT,
            "scope_kind": SCOPE_KIND_PROJECT_EPISODE,
            "scope_label": _scope_label_for_ownership(OWNERSHIP_MODE_PROJECT),
            "project_id": encode_id(script.id),
            "episode_id": encode_id(episode.id),
            "project_title": script.name,
            "episode_title": episode.title,
            "storyboard_mode": episode.storyboard_mode,
            "source_assets": source_assets,
            "seeded_timeline": seeded_timeline,
            "draft_summary": draft_summary,
        },
    }


def get_creative_editing_draft(
    session: Session,
    *,
    user: User,
    team: Team,
    ownership_mode: str,
    project_id: Optional[str] = None,
    episode_id: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_ownership_mode = _validate_ownership_mode(ownership_mode)
    script, episode = _resolve_project_binding(
        session,
        team=team,
        ownership_mode=normalized_ownership_mode,
        project_id=project_id,
        episode_id=episode_id,
    )
    draft = _find_existing_draft(
        session,
        user_id=user.id,
        ownership_mode=normalized_ownership_mode,
        script_id=script.id if script else None,
        episode_id=episode.id if episode else None,
    )
    if not draft:
        return {"success": True, "data": {"draft": None}}

    raw_document = _json_loads(draft.document_json, {})
    payload = {
        "ownership_mode": normalized_ownership_mode,
        "project_id": encode_id(script.id) if script else None,
        "episode_id": encode_id(episode.id) if episode else None,
        "document": raw_document,
    }
    try:
        normalized = _normalize_editing_document(
            session,
            team=team,
            payload=payload,
            allow_empty_timeline=True,
            require_enabled_clip=False,
        )
        document = normalized["document"]
    except Exception as exc:
        logger.warning("剪辑草稿恢复失败，将回退到默认时间线: draft_id=%s error=%s", draft.id, exc)
        return {
            "success": True,
            "data": {
                "draft": None,
                "invalidated": True,
                "message": "原草稿已失效，已回退到默认时间线",
            },
        }

    return {"success": True, "data": {"draft": _serialize_draft(draft, document=document)}}


def save_creative_editing_draft(
    session: Session,
    *,
    user: User,
    team: Team,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    normalized = _normalize_editing_document(
        session,
        team=team,
        payload=payload,
        allow_empty_timeline=True,
        require_enabled_clip=False,
    )
    script = normalized.get("script")
    episode = normalized.get("episode")
    existing = _find_existing_draft(
        session,
        user_id=user.id,
        ownership_mode=normalized["ownership_mode"],
        script_id=script.id if script else None,
        episode_id=episode.id if episode else None,
    )

    requested_updated_at = str(payload.get("updated_at") or "").strip()
    if existing and requested_updated_at and requested_updated_at != _iso(existing.updated_at):
        raise public_http_error(409, "draft_conflict", "草稿已被更新，请刷新后重试")

    document = dict(normalized["document"])
    next_version = int(existing.version or 1) + 1 if existing else 1
    document["version"] = next_version
    now = _now()

    if existing:
        draft = existing
        draft.team_id = team.id
        draft.document_json = _json_dumps(document)
        draft.version = next_version
        draft.updated_at = now
    else:
        draft = CreativeEditingDraft(
            user_id=user.id,
            team_id=team.id,
            ownership_mode=normalized["ownership_mode"],
            script_id=script.id if script else None,
            episode_id=episode.id if episode else None,
            document_json=_json_dumps(document),
            version=next_version,
            created_at=now,
            updated_at=now,
        )

    session.add(draft)
    session.commit()
    session.refresh(draft)
    return {"success": True, "data": {"draft": _serialize_draft(draft, document=document)}}


def _update_record_public_params(record_id: int, updates: Dict[str, Any]) -> None:
    if not updates:
        return
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record:
            return
        params_public = _json_loads(record.params_public_json, {})
        params_public.update(updates)
        record.params_public_json = _json_dumps(params_public)
        session.add(record)
        session.commit()


def _update_episode_composed_video(episode_id: Optional[int], *, preview_url: str, thumbnail_url: Optional[str]) -> None:
    if not episode_id:
        return
    with Session(engine) as session:
        episode = session.get(Episode, int(episode_id))
        if not episode:
            return
        episode.composed_video_url = preview_url
        episode.composed_video_thumbnail_url = thumbnail_url or build_oss_video_snapshot_url(preview_url) or None
        episode.composed_video_updated_at = _now()
        session.add(episode)
        session.commit()


def _friendly_background_error(*, operation_type: str, exc: Exception) -> str:
    error_text = str(exc or "").strip().lower()
    if operation_type == OPERATION_TYPE_COMPOSE:
        if "ffmpeg" in error_text or "ffprobe" in error_text:
            return "服务端缺少剪辑依赖，暂时无法完成成片合成"
        if "http" in error_text or "download" in error_text or "timed out" in error_text:
            return "剪辑输入素材加载失败，请稍后重试"
        return "成片合成失败，请稍后重试"
    if "ffmpeg" in error_text or "ffprobe" in error_text:
        return "当前时间线包含图片素材时，导出剪映草稿还需要 ffmpeg / ffprobe 支持"
    if "mediainfo" in error_text:
        return "服务端缺少 mediainfo，暂时无法生成剪映草稿"
    if "pyjianyingdraft" in error_text or "jianying" in error_text:
        return "服务端当前无法生成剪映草稿，请稍后再试"
    if "http" in error_text or "download" in error_text or "timed out" in error_text:
        return "剪辑输入素材加载失败，请稍后重试"
    return "剪映草稿导出失败，请稍后重试"


def _create_editing_record(
    session: Session,
    *,
    user: User,
    team: Team,
    normalized: Dict[str, Any],
    operation_type: str,
    output_kind: str,
    extra_public: Optional[Dict[str, Any]] = None,
    extra_internal: Optional[Dict[str, Any]] = None,
) -> GenerationRecord:
    script = normalized.get("script")
    episode = normalized.get("episode")
    summary = _operation_summary(operation_type, normalized["ownership_mode"], normalized["clip_count"], episode)
    params_public = {
        "operation_type": operation_type,
        "operation_type_label": OPERATION_LABELS[operation_type],
        "output_kind": output_kind,
        "output_kind_label": OUTPUT_KIND_LABELS[output_kind],
        "scope_kind": normalized["scope_kind"],
        "scope_label": normalized["scope_label"],
        "clip_count": normalized["clip_count"],
        "source_asset_count": len(normalized.get("source_assets") or []),
        "estimated_duration_seconds": normalized["estimated_duration_seconds"],
        "estimated_duration_label": "{0} 秒".format(_normalize_duration_label(normalized["estimated_duration_seconds"])),
        "use_transitions": normalized["use_transitions"],
        "transition_duration": normalized["transition_duration"],
        "music_enabled": normalized["music_enabled"],
        "summary": summary,
        "safe_summary": summary,
        "prompt_summary": summary,
        "source": "webui",
    }
    if normalized.get("first_thumbnail_url"):
        params_public["cover_thumbnail_url"] = normalized["first_thumbnail_url"]
    if extra_public:
        params_public.update(extra_public)

    params_internal = {
        "document": normalized["document"],
        "source_assets": normalized["source_assets"],
        "timeline_manifest": normalized["timeline_manifest"],
        "music_audio_url": normalized["music_audio_url"],
        "music_volume": normalized["music_volume"],
        "use_transitions": normalized["use_transitions"],
        "transition_duration": normalized["transition_duration"],
        "preferred_aspect_ratio": normalized["preferred_aspect_ratio"],
        "source": "webui",
    }
    if extra_internal:
        params_internal.update(extra_internal)

    return _create_generation_record(
        session,
        user=user,
        team=team,
        record_type=RECORD_TYPE_EDITING,
        ownership_mode=normalized["ownership_mode"],
        script_id=script.id if script else None,
        episode_id=episode.id if episode else None,
        target_type=TARGET_TYPE_EPISODE_RECORD if episode else None,
        target_id=episode.id if episode else None,
        prompt=summary,
        negative_prompt=None,
        params_internal=params_internal,
        params_public=params_public,
        estimate_points=0,
    )


def submit_creative_editing_compose(
    session: Session,
    *,
    background_tasks: BackgroundTasks,
    user: User,
    team: Team,
    payload: Dict[str, Any],
) -> GenerationRecord:
    dependency_message = _dependency_message_for_compose()
    if dependency_message:
        raise public_http_error(503, "editing_unavailable", dependency_message)
    normalized = _normalize_editing_document(session, team=team, payload=payload)
    record = _create_editing_record(
        session,
        user=user,
        team=team,
        normalized=normalized,
        operation_type=OPERATION_TYPE_COMPOSE,
        output_kind=OUTPUT_KIND_VIDEO,
    )
    background_tasks.add_task(_run_editing_compose_job, int(record.id))
    return record


def submit_creative_editing_jianying_draft(
    session: Session,
    *,
    background_tasks: BackgroundTasks,
    user: User,
    team: Team,
    payload: Dict[str, Any],
) -> GenerationRecord:
    dependency_message = _dependency_message_for_jianying()
    if dependency_message:
        raise public_http_error(503, "editing_unavailable", dependency_message)
    normalized = _normalize_editing_document(session, team=team, payload=payload)
    has_image_clip = any(
        str(item.get("source_kind") or "").strip().lower().endswith("_image")
        or (item.get("image_url") and not item.get("video_url"))
        for item in (normalized.get("timeline_manifest") or [])
        if item.get("enabled", True)
    )
    if has_image_clip:
        compose_dependency_message = _dependency_message_for_compose()
        if compose_dependency_message:
            raise public_http_error(
                503,
                "editing_unavailable",
                "当前时间线包含图片素材，导出剪映草稿还需要 ffmpeg / ffprobe 支持",
            )
    draft_path = str(payload.get("draft_path") or "").strip()
    if not draft_path:
        raise public_http_error(400, "invalid_request", "draft_path 不能为空", field="draft_path")
    jianying_version = str(payload.get("jianying_version") or "6").strip() or "6"
    include_subtitles = bool(payload.get("include_subtitles", True))
    record = _create_editing_record(
        session,
        user=user,
        team=team,
        normalized=normalized,
        operation_type=OPERATION_TYPE_JIANYING,
        output_kind=OUTPUT_KIND_ZIP,
        extra_public={
            "include_subtitles": include_subtitles,
            "jianying_version": jianying_version,
        },
        extra_internal={
            "draft_path": draft_path,
            "jianying_version": jianying_version,
            "include_subtitles": include_subtitles,
        },
    )
    background_tasks.add_task(_run_editing_jianying_job, int(record.id))
    return record


def _run_editing_compose_job(record_id: int) -> None:
    workspace_dir = ""
    try:
        _mark_processing(record_id)
        with Session(engine) as session:
            record = session.get(GenerationRecord, record_id)
            if not record:
                return
            params_internal = _json_loads(record.params_internal_json, {})
            params_public = _json_loads(record.params_public_json, {})

        compose_result = video_compose_service.compose(
            clips=params_internal.get("timeline_manifest") or [],
            music_audio_url=params_internal.get("music_audio_url"),
            music_volume=params_internal.get("music_volume") or 0.3,
            music_start_seconds=float(params_internal.get("music_start_seconds") or 0.0),
            music_duration_seconds=params_internal.get("music_duration_seconds"),
            use_transitions=bool(params_internal.get("use_transitions", True)),
            transition_duration=float(params_internal.get("transition_duration") or 0.5),
            preferred_aspect_ratio=str(params_internal.get("preferred_aspect_ratio") or "").strip(),
            output_basename="editing_compose_{0}".format(record_id),
        )
        workspace_dir = str(compose_result.get("workspace_dir") or "")
        with open(str(compose_result["local_path"]), "rb") as handle:
            media_meta = upload_bytes_to_oss_with_meta(
                handle.read(),
                "editing_compose_{0}.mp4".format(record_id),
                "video/mp4",
                owner_user_id=record.user_id,
                media_type="video",
                source_type="editing_compose",
                source_id=record_id,
            )

        _update_record_public_params(
            record_id,
            {
                "estimated_duration_seconds": round(float(compose_result.get("duration_seconds") or 0.0), 2),
                "estimated_duration_label": "{0} 秒".format(_normalize_duration_label(compose_result.get("duration_seconds") or 0.0)),
                "output_width": compose_result.get("width"),
                "output_height": compose_result.get("height"),
            },
        )
        _complete_record_success(
            record_id,
            preview_url=media_meta.get("file_url") or "",
            thumbnail_url=media_meta.get("thumbnail_url") or params_public.get("cover_thumbnail_url"),
        )
        _update_episode_composed_video(
            record.episode_id,
            preview_url=media_meta.get("file_url") or "",
            thumbnail_url=media_meta.get("thumbnail_url"),
        )
    except Exception as exc:
        logger.exception("成片合成后台任务失败: record_id=%s", record_id)
        _mark_failed(
            record_id,
            error_code="generation_failed",
            message=_friendly_background_error(operation_type=OPERATION_TYPE_COMPOSE, exc=exc),
            internal_message=str(exc),
        )
    finally:
        video_compose_service.cleanup(workspace_dir)


def _run_editing_jianying_job(record_id: int) -> None:
    workspace_dir = ""
    try:
        _mark_processing(record_id)
        with Session(engine) as session:
            record = session.get(GenerationRecord, record_id)
            if not record:
                return
            params_internal = _json_loads(record.params_internal_json, {})
            params_public = _json_loads(record.params_public_json, {})

        draft_result = jianying_draft_service.export_timeline(
            clips=params_internal.get("timeline_manifest") or [],
            draft_name="神鹿剪映草稿_{0}".format(record_id),
            draft_path=str(params_internal.get("draft_path") or "").strip(),
            include_subtitles=bool(params_internal.get("include_subtitles", True)),
            jianying_version=str(params_internal.get("jianying_version") or "6").strip() or "6",
            preferred_aspect_ratio=str(params_internal.get("preferred_aspect_ratio") or "").strip(),
            music_audio_url=params_internal.get("music_audio_url"),
            music_start_seconds=float(params_internal.get("music_start_seconds") or 0.0),
            music_duration_seconds=params_internal.get("music_duration_seconds"),
            use_transitions=bool(params_internal.get("use_transitions", True)),
            transition_duration=float(params_internal.get("transition_duration") or 0.5),
        )
        workspace_dir = str(draft_result.get("workspace_dir") or "")
        with open(str(draft_result["local_path"]), "rb") as handle:
            media_meta = upload_bytes_to_oss_with_meta(
                handle.read(),
                "{0}.zip".format(draft_result.get("draft_name") or "shenlu_jianying_draft"),
                "application/zip",
                owner_user_id=record.user_id,
                media_type="other",
                source_type="editing_jianying_draft",
                source_id=record_id,
            )

        _update_record_public_params(
            record_id,
            {
                "draft_name": draft_result.get("draft_name"),
                "draft_path_hint": draft_result.get("draft_path_hint"),
                "cover_thumbnail_url": params_public.get("cover_thumbnail_url"),
            },
        )
        _complete_record_success(
            record_id,
            preview_url=media_meta.get("file_url") or "",
            thumbnail_url=params_public.get("cover_thumbnail_url"),
        )
    except Exception as exc:
        logger.exception("剪映草稿后台任务失败: record_id=%s", record_id)
        _mark_failed(
            record_id,
            error_code="generation_failed",
            message=_friendly_background_error(operation_type=OPERATION_TYPE_JIANYING, exc=exc),
            internal_message=str(exc),
        )
    finally:
        jianying_draft_service.cleanup(workspace_dir)
