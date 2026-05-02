from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from sqlmodel import Session, select

from core.config import settings
from core.security import decode_id, encode_id
from database import get_session
from dependencies import (
    get_current_team_by_api_token,
    get_current_user_by_api_token,
    require_team_permission_by_api_token,
)
from models import Episode, ExternalAgentSession, GenerationRecord, Panel, ResourceTypeEnum, Script, SharedResource, Team, TeamMemberLink, User
from schemas import (
    CreativeAssetGenerateRequest,
    CreativeAudioEstimateRequest,
    CreativeAudioGenerateRequest,
    CreativeImageEstimateRequest,
    CreativeImageGenerateRequest,
    CreativeVideoEstimateRequest,
    CreativeVideoGenerateRequest,
    EXTERNAL_PROVIDER_SHENLU_AGENT,
    OpenClawAgentChatRequest,
    OpenClawAssetExtractRequest,
    OpenClawAssetImportRequest,
    OpenClawEpisodeCreateRequest,
    OpenClawProjectCreateRequest,
    OpenClawProjectSettingsUpdateRequest,
)
from services.access_service import require_script_team_access
from services.assistant_runtime import AssistantRuntimeService
from services.generation_record_service import (
    estimate_audio_generation,
    estimate_image_generation,
    estimate_video_generation,
    get_generation_record_detail,
    list_generation_records,
    serialize_generation_record,
    submit_asset_generation,
    submit_audio_generation,
    submit_image_generation,
    submit_video_generation,
)
from services.openclaw_catalog_service import get_openclaw_public_catalog
from services.resource_extraction_service import extract_script_assets_structured
from services.workflow_preset_service import build_style_prompt, get_style_display_label, resolve_effective_workflow_profile
from services.resource_service import (
    create_resource as create_resource_service,
    list_resources as list_resources_service,
    serialize_resource as serialize_resource_service,
    update_resource as update_resource_service,
)
from services.script_service import create_script as create_script_service, list_scripts

router = APIRouter()

CHAT_TIMEOUT_SECONDS = 15.0
CHAT_POLL_INTERVAL_SECONDS = 0.5

RESOURCE_TYPE_MAP = {
    "character": ResourceTypeEnum.CHARACTER_REF.value,
    "scene": ResourceTypeEnum.SCENE_REF.value,
    "prop": ResourceTypeEnum.PROP_REF.value,
}


def _json_loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _require_text(value: Optional[str], *, code: str, message: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise _error(400, code, message)
    return text


def _project_sessions(session: Session, script_id: int) -> List[ExternalAgentSession]:
    return session.exec(
        select(ExternalAgentSession)
        .where(
            ExternalAgentSession.script_id == script_id,
            ExternalAgentSession.provider == EXTERNAL_PROVIDER_SHENLU_AGENT,
        )
        .order_by(ExternalAgentSession.is_active.desc(), ExternalAgentSession.updated_at.desc(), ExternalAgentSession.id.desc())
    ).all()


def _active_bridge_session(sessions: List[ExternalAgentSession]) -> Optional[ExternalAgentSession]:
    return next((item for item in sessions if item.is_active), sessions[0] if sessions else None)


def _episode_bridge_session(sessions: List[ExternalAgentSession], episode_id: int) -> Optional[ExternalAgentSession]:
    return next((item for item in sessions if item.episode_id == episode_id), None)


def _get_project(session: Session, team: Team, project_id: str) -> Tuple[Script, List[ExternalAgentSession]]:
    script = require_script_team_access(session, team, decode_id(project_id))
    return script, _project_sessions(session, script.id)


def _get_episode(session: Session, team: Team, project_id: str, episode_id: str) -> Tuple[Script, Episode, List[ExternalAgentSession]]:
    script, sessions = _get_project(session, team, project_id)
    episode = session.get(Episode, decode_id(episode_id))
    if not episode or episode.script_id != script.id:
        raise _error(404, "episode_not_found", "指定剧集不存在")
    return script, episode, sessions


def _current_openclaw_settings(script: Script) -> Dict[str, Any]:
    data = _json_loads(script.openclaw_settings_json, {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("aspect_ratio", script.aspect_ratio)
    data.setdefault("style", script.style_preset)
    return data


def _apply_openclaw_settings(script: Script, settings_payload: Dict[str, Any]) -> Dict[str, Any]:
    data = _current_openclaw_settings(script)
    for key, value in (settings_payload or {}).items():
        if value is None:
            continue
        data[key] = value
    if data.get("aspect_ratio"):
        script.aspect_ratio = str(data["aspect_ratio"])
    if data.get("style"):
        script.style_preset = str(data["style"])
    script.openclaw_settings_json = _json_dumps(data)
    return data


def _serialize_bridge(session_obj: Optional[ExternalAgentSession]) -> Optional[Dict[str, Any]]:
    if not session_obj:
        return None
    return {
        "provider": session_obj.provider,
        "session_id": session_obj.session_id or "",
        "base_id": session_obj.base_id or "",
        "base_name": session_obj.base_name or "",
        "provider_episode_id": session_obj.provider_episode_id or "",
        "status": session_obj.status or "idle",
        "is_active": bool(session_obj.is_active),
        "updated_at": _iso(session_obj.updated_at),
    }


def _collapse_public_generation_status(status: Optional[str]) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "waiting_upstream":
        return "processing"
    return normalized


def _collapse_public_generation_status_label(status: Optional[str], status_label: Optional[str]) -> str:
    if _collapse_public_generation_status(status) == "processing":
        return "生成中"
    return str(status_label or status or "").strip()


def _sanitize_public_generation_record(payload: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(payload or {})
    raw_status = sanitized.get("status")
    collapsed_status = _collapse_public_generation_status(raw_status)
    sanitized["status"] = collapsed_status
    sanitized["status_label"] = _collapse_public_generation_status_label(raw_status, sanitized.get("status_label"))
    error_payload = sanitized.get("error")
    if isinstance(error_payload, dict):
        sanitized["error"] = dict(error_payload)
    return sanitized


def _serialize_episode(episode: Episode, session_obj: Optional[ExternalAgentSession]) -> Dict[str, Any]:
    return {
        "episode_id": encode_id(episode.id),
        "title": episode.title,
        "sequence_num": episode.sequence_num,
        "provider_episode_id": session_obj.provider_episode_id if session_obj else "",
        "session_id": session_obj.session_id if session_obj else "",
        "status": session_obj.status if session_obj else "ready",
        "is_active": bool(session_obj and session_obj.is_active),
        "updated_at": _iso((session_obj.updated_at if session_obj else None) or episode.created_at),
        "bridge": _serialize_bridge(session_obj),
    }


def _serialize_project(script: Script, sessions: List[ExternalAgentSession], episode_count: int) -> Dict[str, Any]:
    active_bridge = _active_bridge_session(sessions)
    return {
        "project_id": encode_id(script.id),
        "name": script.name,
        "description": script.description or "",
        "provider": "shenlu_openclaw_public",
        "status": "ready",
        "episode_count": episode_count,
        "active_episode_id": encode_id(active_bridge.episode_id) if active_bridge and active_bridge.episode_id else None,
        "settings": _current_openclaw_settings(script),
        "base_id": active_bridge.base_id if active_bridge else "",
        "created_at": _iso(script.created_at),
        "updated_at": _iso((active_bridge.updated_at if active_bridge else None) or script.last_accessed_at or script.created_at),
        "bridge": _serialize_bridge(active_bridge),
    }


def _normalize_resource_type(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    normalized = RESOURCE_TYPE_MAP.get(text)
    if not normalized:
        raise _error(400, "invalid_request", "resource_type 仅支持 character / scene / prop")
    return normalized


def _resource_type_label(value: Optional[str]) -> str:
    text = str(value or "").strip().lower()
    if text in {"character", "scene", "prop"}:
        return text
    reverse_map = {item: key for key, item in RESOURCE_TYPE_MAP.items()}
    return reverse_map.get(text, text or "")


def _serialize_resource(resource: SharedResource) -> Dict[str, Any]:
    payload = serialize_resource_service(resource)
    return {
        "resource_id": encode_id(resource.id),
        "resource_type": _resource_type_label(payload.get("resource_type")),
        "name": payload.get("name") or "",
        "description": payload.get("description") or "",
        "trigger_word": payload.get("trigger_word") or "",
        "aliases": payload.get("aliases") or [],
        "file_url": payload.get("file_url") or "",
        "thumbnail_url": payload.get("thumbnail_url") or "",
    }


def _filter_structured_assets(structured_assets: Dict[str, Any], resource_types: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    requested = set(resource_types)
    return {
        "characters": list(structured_assets.get("characters") or []) if "character" in requested else [],
        "scenes": list(structured_assets.get("scenes") or []) if "scene" in requested else [],
        "props": list(structured_assets.get("props") or []) if "prop" in requested else [],
    }


def _upsert_project_assets(
    session: Session,
    *,
    team: Team,
    script_id: int,
    structured_assets: Dict[str, List[Dict[str, Any]]],
    overwrite_existing: bool,
    owner_user_id: int | None = None,
) -> Dict[str, Any]:
    existing_resources = list_resources_service(session, team, script_id, None)
    existing_map = {
        (_resource_type_label(resource.resource_type), str(resource.name or "").strip().lower()): resource
        for resource in existing_resources
    }

    created_resources: List[SharedResource] = []
    updated_resources: List[SharedResource] = []
    skipped_resources: List[Dict[str, Any]] = []

    def _handle_items(items: List[Dict[str, Any]], resource_type_key: str) -> None:
        for item in items:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            description = str(item.get("description") or "").strip() or None
            trigger_word = str(item.get("trigger_word") or "").strip() or None
            aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else None
            file_url = str(item.get("file_url") or "").strip()
            map_key = (resource_type_key, name.lower())
            existing = existing_map.get(map_key)
            if existing:
                if not overwrite_existing:
                    skipped_resources.append({"resource_type": resource_type_key, "name": name, "reason": "exists"})
                    continue
                updated = update_resource_service(
                    session,
                    team,
                    existing.id,
                    name=name,
                    file_url=file_url or existing.file_url,
                    trigger_word=trigger_word if resource_type_key == "character" else existing.trigger_word,
                    aliases=aliases if aliases is not None else serialize_resource_service(existing).get("aliases"),
                    description=description if description is not None else existing.description,
                    owner_user_id=owner_user_id,
                )
                updated_resources.append(updated)
                existing_map[map_key] = updated
                continue
            created = create_resource_service(
                session,
                team,
                script_id=script_id,
                resource_type=RESOURCE_TYPE_MAP[resource_type_key],
                name=name,
                file_url=file_url,
                trigger_word=trigger_word if resource_type_key == "character" else None,
                aliases=aliases,
                description=description,
                owner_user_id=owner_user_id,
            )
            created_resources.append(created)
            existing_map[map_key] = created

    _handle_items(structured_assets.get("characters") or [], "character")
    _handle_items(structured_assets.get("scenes") or [], "scene")
    _handle_items(structured_assets.get("props") or [], "prop")

    return {
        "created_count": len(created_resources),
        "updated_count": len(updated_resources),
        "skipped_count": len(skipped_resources),
        "created_resources": [_serialize_resource(item) for item in created_resources],
        "updated_resources": [_serialize_resource(item) for item in updated_resources],
        "skipped_resources": skipped_resources,
    }


def _mark_record_source(
    session: Session,
    *,
    record: GenerationRecord,
    source: str,
    assistant_session_id: Optional[int] = None,
) -> GenerationRecord:
    params_public = _json_loads(record.params_public_json, {})
    params_internal = _json_loads(record.params_internal_json, {})
    params_public["source"] = source
    params_internal["source"] = source
    if assistant_session_id:
        params_internal["assistant_session_id"] = assistant_session_id
    record.params_public_json = _json_dumps(params_public)
    record.params_internal_json = _json_dumps(params_internal)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def _build_workspace_files(
    session: Session,
    *,
    team: Team,
    script: Script,
    episode: Episode,
) -> List[Dict[str, Any]]:
    panels = session.exec(select(Panel).where(Panel.episode_id == episode.id)).all()
    resources = session.exec(select(SharedResource).where(SharedResource.script_id == script.id)).all()
    records = session.exec(
        select(GenerationRecord).where(
            GenerationRecord.team_id == team.id,
            GenerationRecord.script_id == script.id,
            GenerationRecord.episode_id == episode.id,
        )
    ).all()

    resources_by_type = {
        "character": [item for item in resources if item.resource_type == ResourceTypeEnum.CHARACTER_REF.value],
        "scene": [item for item in resources if item.resource_type == ResourceTypeEnum.SCENE_REF.value],
        "prop": [item for item in resources if item.resource_type == ResourceTypeEnum.PROP_REF.value],
    }
    records_by_type = {
        "image": [item for item in records if item.record_type == "image"],
        "video": [item for item in records if item.record_type == "video"],
        "audio": [item for item in records if item.record_type == "audio"],
    }

    def _latest(items: List[Any], attr: str = "updated_at", fallback: Optional[datetime] = None) -> Optional[str]:
        values = [getattr(item, attr, None) for item in items if getattr(item, attr, None)]
        if values:
            return _iso(max(values))
        return _iso(fallback)

    script_text = str(episode.source_text or script.source_text or "").strip()
    return [
        {
            "file_id": f"script-{encode_id(script.id)}-{encode_id(episode.id)}",
            "name": episode.title or script.name,
            "docu_type": "script",
            "record_count": 1 if script_text else 0,
            "updated_at": _iso(script.last_accessed_at or script.created_at),
        },
        {
            "file_id": f"panel-{encode_id(episode.id)}",
            "name": f"{episode.title or '当前剧集'} 分镜",
            "docu_type": "panel",
            "record_count": len(panels),
            "updated_at": _latest(panels, attr="created_at", fallback=episode.created_at),
        },
        {
            "file_id": f"character-{encode_id(script.id)}",
            "name": "角色资源",
            "docu_type": "character",
            "record_count": len(resources_by_type["character"]),
            "updated_at": _latest(resources_by_type["character"], attr="created_at", fallback=script.created_at),
        },
        {
            "file_id": f"scene-{encode_id(script.id)}",
            "name": "场景资源",
            "docu_type": "scene",
            "record_count": len(resources_by_type["scene"]),
            "updated_at": _latest(resources_by_type["scene"], attr="created_at", fallback=script.created_at),
        },
        {
            "file_id": f"prop-{encode_id(script.id)}",
            "name": "道具资源",
            "docu_type": "prop",
            "record_count": len(resources_by_type["prop"]),
            "updated_at": _latest(resources_by_type["prop"], attr="created_at", fallback=script.created_at),
        },
        {
            "file_id": f"image-{encode_id(episode.id)}",
            "name": "图片结果",
            "docu_type": "image",
            "record_count": len(records_by_type["image"]),
            "updated_at": _latest(records_by_type["image"], fallback=episode.created_at),
        },
        {
            "file_id": f"video-{encode_id(episode.id)}",
            "name": "视频结果",
            "docu_type": "video",
            "record_count": len(records_by_type["video"]),
            "updated_at": _latest(records_by_type["video"], fallback=episode.created_at),
        },
        {
            "file_id": f"audio-{encode_id(episode.id)}",
            "name": "音频结果",
            "docu_type": "audio",
            "record_count": len(records_by_type["audio"]),
            "updated_at": _latest(records_by_type["audio"], fallback=episode.created_at),
        },
    ]


def _panel_media_state(
    session: Session,
    *,
    team: Team,
    episode: Episode,
) -> Dict[str, Any]:
    records = session.exec(
        select(GenerationRecord)
        .where(
            GenerationRecord.team_id == team.id,
            GenerationRecord.script_id == episode.script_id,
            GenerationRecord.episode_id == episode.id,
        )
        .order_by(GenerationRecord.updated_at.desc(), GenerationRecord.id.desc())
    ).all()

    image_url_map: Dict[int, str] = {}
    video_url_map: Dict[int, str] = {}
    panel_image_status: Dict[int, str] = {}
    panel_video_status: Dict[int, str] = {}
    latest_audio_url: Optional[str] = None
    latest_audio_status: Optional[str] = None

    for record in records:
        target_type = str(record.target_type or "").strip().lower()
        if target_type == "panel" and record.target_id:
            target_id = int(record.target_id)
            if record.record_type == "image" and target_id not in panel_image_status:
                panel_image_status[target_id] = _collapse_public_generation_status(record.status)
                if record.preview_url and record.status in {"completed", "success"}:
                    image_url_map[target_id] = record.preview_url
            if record.record_type == "video" and target_id not in panel_video_status:
                panel_video_status[target_id] = _collapse_public_generation_status(record.status)
                if record.preview_url and record.status in {"completed", "success"}:
                    video_url_map[target_id] = record.preview_url
        if target_type == "episode_record" and record.record_type == "audio" and latest_audio_status is None:
            latest_audio_status = _collapse_public_generation_status(record.status)
            if record.preview_url and record.status in {"completed", "success"}:
                latest_audio_url = record.preview_url

    return {
        "image_url_map": image_url_map,
        "video_url_map": video_url_map,
        "panel_image_status": panel_image_status,
        "panel_video_status": panel_video_status,
        "latest_audio_url": latest_audio_url,
        "latest_audio_status": latest_audio_status,
    }


def _panel_status_value(panel: Panel) -> str:
    status = getattr(panel, "status", None)
    if hasattr(status, "value"):
        return str(status.value)
    return str(status or "")


def _serialize_public_panel(panel: Panel, media_state: Dict[str, Any]) -> Dict[str, Any]:
    latest_image_url = (
        media_state["image_url_map"].get(panel.id)
        or str(panel.image_url or "").strip()
        or str(panel.file_url or "").strip()
        or None
    )
    latest_video_url = media_state["video_url_map"].get(panel.id) or str(panel.video_url or "").strip() or None
    latest_audio_url = media_state.get("latest_audio_url")
    return {
        "panel_id": encode_id(panel.id),
        "sequence": panel.sequence_num,
        "original_text": panel.original_text or "",
        "narration_text": panel.narration_text or "",
        "dialogue_text": panel.dialogue_text or "",
        "image_prompt": panel.prompt_zh or panel.prompt or "",
        "video_prompt": panel.video_prompt or "",
        "status_summary": {
            "panel_status": _panel_status_value(panel),
            "image_task_status": media_state["panel_image_status"].get(panel.id),
            "video_task_status": media_state["panel_video_status"].get(panel.id),
            "audio_task_status": media_state.get("latest_audio_status"),
            "has_image": bool(latest_image_url),
            "has_video": bool(latest_video_url),
            "has_audio": bool(latest_audio_url),
        },
        "latest_image_url": latest_image_url,
        "latest_video_url": latest_video_url,
        "latest_audio_url": latest_audio_url,
    }


def _assistant_reply_text(turn: Optional[Dict[str, Any]]) -> str:
    if not isinstance(turn, dict):
        return ""
    texts: List[str] = []
    for block in turn.get("blocks") or []:
        block_type = str(block.get("type") or "")
        if block_type == "text" and block.get("text"):
            texts.append(str(block.get("text")))
        elif block_type == "reasoning_summary" and block.get("summary"):
            texts.append(str(block.get("summary")))
        elif block_type == "tool_result" and block.get("summary"):
            texts.append(str(block.get("summary")))
    return "\n".join(item for item in texts if item).strip()


def _latest_assistant_turn(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for turn in reversed(snapshot.get("turns") or []):
        if str(turn.get("role") or "") == "assistant":
            return turn
    return None


def _draft_partial_reply(snapshot: Dict[str, Any]) -> str:
    return _assistant_reply_text(snapshot.get("draft_turn") or {})


def _extract_task_ids_from_turn(turn: Optional[Dict[str, Any]]) -> List[str]:
    task_ids: List[str] = []
    if not isinstance(turn, dict):
        return task_ids
    for block in turn.get("blocks") or []:
        task_id = str(block.get("task_id") or "").strip()
        result = block.get("result") if isinstance(block.get("result"), dict) else {}
        result_task_id = str(result.get("task_id") or "").strip() if isinstance(result, dict) else ""
        if task_id and task_id not in task_ids:
            task_ids.append(task_id)
        if result_task_id and result_task_id not in task_ids:
            task_ids.append(result_task_id)
    return task_ids


def _serialize_public_task(session: Session, *, team: Team, task_id: str) -> Optional[Dict[str, Any]]:
    record = session.exec(
        select(GenerationRecord).where(
            GenerationRecord.team_id == team.id,
            GenerationRecord.task_id == task_id,
        )
    ).first()
    if not record:
        return None
    return _sanitize_public_generation_record(serialize_generation_record(session, record, include_detail=True))


def _extract_public_tasks(session: Session, *, team: Team, snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    task_ids = _extract_task_ids_from_turn(_latest_assistant_turn(snapshot))
    tasks: List[Dict[str, Any]] = []
    for task_id in task_ids:
        task_payload = _serialize_public_task(session, team=team, task_id=task_id)
        if task_payload:
            tasks.append(task_payload)
    return tasks


def _pending_question_payload(snapshot: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    pending_wizard = snapshot.get("pending_question_wizard")
    if pending_wizard:
        return pending_wizard
    pending_questions = snapshot.get("pending_questions") or []
    return pending_questions[0] if pending_questions else None


def _chat_actions(pending_question: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not pending_question:
        return []
    return [
        {
            "type": "answer_question",
            "question_id": pending_question.get("id"),
            "question_type": pending_question.get("question_type"),
        }
    ]


def _wait_for_public_chat(
    session: Session,
    *,
    assistant_service: AssistantRuntimeService,
    assistant_session_id: int,
) -> Tuple[Dict[str, Any], bool]:
    snapshot = assistant_service.get_snapshot_by_id(assistant_session_id)
    deadline = time.time() + CHAT_TIMEOUT_SECONDS
    while time.time() < deadline:
        pending_question = _pending_question_payload(snapshot)
        status = str((snapshot.get("session") or {}).get("status") or "")
        if pending_question or status in {"completed", "error", "interrupted"}:
            return snapshot, False
        time.sleep(CHAT_POLL_INTERVAL_SECONDS)
        session.expire_all()
        snapshot = assistant_service.get_snapshot_by_id(assistant_session_id)
    session.expire_all()
    snapshot = assistant_service.get_snapshot_by_id(assistant_session_id)
    timed_out = str((snapshot.get("session") or {}).get("status") or "") == "running" and not _pending_question_payload(snapshot)
    return snapshot, timed_out


def _build_chat_response(
    session: Session,
    *,
    team: Team,
    script: Script,
    episode: Episode,
    snapshot: Dict[str, Any],
    timed_out: bool,
) -> Dict[str, Any]:
    latest_turn = _latest_assistant_turn(snapshot)
    pending_question = _pending_question_payload(snapshot)
    reply = _assistant_reply_text(latest_turn)
    partial_reply = _draft_partial_reply(snapshot)
    session_status = str((snapshot.get("session") or {}).get("status") or "")

    if pending_question:
        status = "needs_input"
    elif timed_out:
        status = "timeout"
    elif session_status == "error":
        status = "error"
    else:
        status = "completed"

    if not reply and pending_question:
        reply = str(pending_question.get("prompt") or "")
    if not reply and status == "timeout":
        reply = partial_reply

    payload: Dict[str, Any] = {
        "session_id": (snapshot.get("session") or {}).get("id"),
        "status": status,
        "reply": reply or "",
        "actions": _chat_actions(pending_question),
        "workspace": {"files": _build_workspace_files(session, team=team, script=script, episode=episode)},
        "tasks": _extract_public_tasks(session, team=team, snapshot=snapshot),
        "project_changes": snapshot.get("project_changes") or [],
        "pending_question": pending_question,
    }
    if status == "timeout":
        payload["partial_reply"] = partial_reply or ""
    return payload


def _legacy_episode_bridge_or_404(sessions: List[ExternalAgentSession], episode_id: int) -> ExternalAgentSession:
    session_obj = _episode_bridge_session(sessions, episode_id)
    if not session_obj:
        raise _error(404, "episode_not_bound", "当前剧集尚未绑定 legacy bridge session")
    return session_obj


@router.get("/api/openclaw/capabilities")
async def get_openclaw_capabilities(request: Request):
    return {"success": True, "data": get_openclaw_public_catalog(base_url=str(request.base_url).rstrip("/"))}


@router.get("/api/openclaw/projects")
async def list_openclaw_projects(
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:read")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    projects: List[Dict[str, Any]] = []
    for script in list_scripts(session, team):
        sessions = _project_sessions(session, script.id)
        episode_count = len(session.exec(select(Episode).where(Episode.script_id == script.id)).all())
        projects.append(_serialize_project(script, sessions, episode_count))
    return {"success": True, "data": {"projects": projects}}


@router.post("/api/openclaw/projects")
async def create_openclaw_project(
    payload: OpenClawProjectCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:manage")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    new_script = create_script_service(
        session,
        team,
        name=_require_text(payload.name, code="invalid_request", message="项目名称不能为空"),
        description=payload.description,
        aspect_ratio=payload.aspect_ratio,
        style_preset=payload.style_preset,
    )
    first_episode = session.exec(
        select(Episode).where(Episode.script_id == new_script.id).order_by(Episode.sequence_num.asc())
    ).first()
    if not first_episode:
        raise _error(500, "episode_init_failed", "项目初始化失败，未创建默认剧集")

    first_episode.title = _require_text(payload.episode_title, code="invalid_request", message="剧集标题不能为空")
    if payload.source_text is not None:
        new_script.source_text = payload.source_text or None
        first_episode.source_text = payload.source_text or None
    settings_payload = payload.settings.model_dump(exclude_none=True) if payload.settings else {}
    _apply_openclaw_settings(
        new_script,
        {
            "aspect_ratio": payload.aspect_ratio,
            "style": payload.style_preset,
            **settings_payload,
        },
    )
    session.add(new_script)
    session.add(first_episode)
    session.commit()
    session.refresh(new_script)
    session.refresh(first_episode)
    return {
        "success": True,
        "data": {
            "project": _serialize_project(new_script, _project_sessions(session, new_script.id), episode_count=1),
            "episode": _serialize_episode(first_episode, None),
        },
    }


@router.get("/api/openclaw/projects/{project_id}")
async def get_openclaw_project_detail(
    project_id: str,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:read")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    script, sessions = _get_project(session, team, project_id)
    episodes = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc())).all()
    session_map = {item.episode_id: item for item in sessions if item.episode_id}
    return {
        "success": True,
        "data": {
            "project": _serialize_project(script, sessions, episode_count=len(episodes)),
            "episodes": [_serialize_episode(episode, session_map.get(episode.id)) for episode in episodes],
        },
    }


@router.get("/api/openclaw/projects/{project_id}/episodes")
async def list_openclaw_episodes(
    project_id: str,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:read")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    script, sessions = _get_project(session, team, project_id)
    episodes = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc())).all()
    session_map = {item.episode_id: item for item in sessions if item.episode_id}
    return {"success": True, "data": {"episodes": [_serialize_episode(item, session_map.get(item.id)) for item in episodes]}}


@router.post("/api/openclaw/projects/{project_id}/episodes")
async def create_openclaw_episode(
    project_id: str,
    payload: OpenClawEpisodeCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:manage")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    script, _ = _get_project(session, team, project_id)
    last_episode = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.desc())).first()
    next_seq = (last_episode.sequence_num + 1) if last_episode else 1
    episode = Episode(
        script_id=script.id,
        title=_require_text(payload.title, code="invalid_request", message="剧集标题不能为空"),
        sequence_num=next_seq,
        source_text=payload.source_text or None,
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)
    return {"success": True, "data": {"episode": _serialize_episode(episode, None)}}


@router.patch("/api/openclaw/projects/{project_id}/settings")
async def update_openclaw_project_settings(
    project_id: str,
    payload: OpenClawProjectSettingsUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:manage")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    script, sessions = _get_project(session, team, project_id)
    settings_payload = payload.settings.model_dump(exclude_none=True)
    if not settings_payload:
        raise _error(400, "invalid_settings", "settings 不能为空")
    _apply_openclaw_settings(script, settings_payload)
    session.add(script)
    session.commit()
    session.refresh(script)
    episode_count = len(session.exec(select(Episode).where(Episode.script_id == script.id)).all())
    return {"success": True, "data": {"project": _serialize_project(script, sessions, episode_count)}}


@router.get("/api/openclaw/projects/{project_id}/resources")
async def list_openclaw_project_resources(
    project_id: str,
    resource_type: Optional[str] = None,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:read")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    script, _ = _get_project(session, team, project_id)
    normalized_type = _normalize_resource_type(resource_type) if resource_type else None
    resources = list_resources_service(session, team, script.id, normalized_type)
    return {"success": True, "data": {"project_id": project_id, "resources": [_serialize_resource(item) for item in resources]}}


@router.post("/api/openclaw/projects/{project_id}/episodes/{episode_id}/assets/extract")
async def extract_openclaw_episode_assets(
    project_id: str,
    episode_id: str,
    payload: OpenClawAssetExtractRequest,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:write")),
    user: User = Depends(get_current_user_by_api_token),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    script, episode, _ = _get_episode(session, team, project_id, episode_id)
    source_text = str(payload.source_text or episode.source_text or script.source_text or "").strip()
    if not source_text:
        raise _error(400, "invalid_request", "请先保存当前剧集剧本文本，再执行资产提取")
    if not settings.DEEPSEEK_API_KEY:
        raise _error(502, "provider_error", "当前环境未配置资产提取服务")

    requested_types = payload.resource_types or ["character", "scene", "prop"]
    normalized_requested: List[str] = []
    for item in requested_types:
        label = str(item or "").strip().lower()
        if label not in RESOURCE_TYPE_MAP:
            raise _error(400, "invalid_request", "resource_types 仅支持 character / scene / prop")
        if label not in normalized_requested:
            normalized_requested.append(label)

    workflow_profile = resolve_effective_workflow_profile(
        script,
        episode=episode,
        storyboard_mode=getattr(episode, "storyboard_mode", None),
    )
    style_prompt = build_style_prompt(workflow_profile.get("style"), fallback=getattr(script, "style_preset", ""))
    style_label = get_style_display_label(workflow_profile.get("style"), getattr(script, "style_preset", "默认写实"))

    try:
        structured_assets = extract_script_assets_structured(
            source_text,
            settings.DEEPSEEK_API_KEY,
            style_prompt=style_prompt,
            style_label=style_label,
        )
    except Exception as exc:
        raise _error(502, "provider_error", f"资产提取失败: {exc}")

    filtered_assets = _filter_structured_assets(structured_assets, normalized_requested)
    result_payload: Dict[str, Any] = {
        "project_id": project_id,
        "episode_id": encode_id(episode.id),
        "assets": filtered_assets,
        "summary": {
            "character_count": len(filtered_assets.get("characters") or []),
            "scene_count": len(filtered_assets.get("scenes") or []),
            "prop_count": len(filtered_assets.get("props") or []),
            "source_text_length": len(source_text),
        },
    }
    if payload.import_to_platform:
        result_payload["import_result"] = _upsert_project_assets(
            session,
            team=team,
            script_id=script.id,
            structured_assets=filtered_assets,
            overwrite_existing=True,
            owner_user_id=int(user.id),
        )
    return {"success": True, "data": result_payload}


@router.post("/api/openclaw/projects/{project_id}/assets/import")
async def import_openclaw_project_assets(
    project_id: str,
    payload: OpenClawAssetImportRequest,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:write")),
    user: User = Depends(get_current_user_by_api_token),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    script, _ = _get_project(session, team, project_id)
    structured_assets = {
        "characters": [item.model_dump(exclude_none=True) for item in payload.characters],
        "scenes": [item.model_dump(exclude_none=True) for item in payload.scenes],
        "props": [item.model_dump(exclude_none=True) for item in payload.props],
    }
    if not any(structured_assets.values()):
        raise _error(400, "invalid_request", "至少需要提供 characters / scenes / props 中的一类资产")
    import_result = _upsert_project_assets(
        session,
        team=team,
        script_id=script.id,
        structured_assets=structured_assets,
        overwrite_existing=payload.overwrite_existing,
        owner_user_id=int(user.id),
    )
    return {"success": True, "data": {"project_id": project_id, "import_result": import_result}}


@router.get("/api/openclaw/projects/{project_id}/episodes/{episode_id}/workspace/files")
async def get_openclaw_workspace_files(
    project_id: str,
    episode_id: str,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:read")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    script, episode, _ = _get_episode(session, team, project_id, episode_id)
    return {
        "success": True,
        "data": {
            "project_id": project_id,
            "episode_id": encode_id(episode.id),
            "files": _build_workspace_files(session, team=team, script=script, episode=episode),
        },
    }


@router.get("/api/openclaw/projects/{project_id}/episodes/{episode_id}/panels")
async def get_openclaw_episode_panels(
    project_id: str,
    episode_id: str,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:read")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    _, episode, _ = _get_episode(session, team, project_id, episode_id)
    panels = session.exec(select(Panel).where(Panel.episode_id == episode.id).order_by(Panel.sequence_num.asc(), Panel.id.asc())).all()
    media_state = _panel_media_state(session, team=team, episode=episode)
    return {
        "success": True,
        "data": {
            "project_id": project_id,
            "episode_id": encode_id(episode.id),
            "panels": [_serialize_public_panel(panel, media_state) for panel in panels],
        },
    }


@router.post("/api/openclaw/projects/{project_id}/episodes/{episode_id}/agent/chat")
async def openclaw_agent_chat(
    project_id: str,
    episode_id: str,
    payload: OpenClawAgentChatRequest,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("project:write")),
    team: Team = Depends(get_current_team_by_api_token),
    user: User = Depends(get_current_user_by_api_token),
    session: Session = Depends(get_session),
):
    script, episode, sessions = _get_episode(session, team, project_id, episode_id)
    assistant_service = AssistantRuntimeService(session)

    if payload.question_answer and payload.wizard_answer:
        raise _error(400, "invalid_request", "question_answer 和 wizard_answer 不能同时提交")
    if not payload.question_answer and not payload.wizard_answer and not str(payload.message or "").strip() and not payload.attachments:
        raise _error(400, "invalid_request", "message、attachments 或 question answer 至少要提供一项")

    public_session_id = decode_id(payload.session_id) if payload.session_id else None

    if settings.OPENCLAW_PUBLIC_PROVIDER_V2_ENABLED:
        assistant_session = assistant_service.get_or_create_openclaw_public_session(
            user=user,
            team=team,
            script_id=script.id,
            episode_id=episode.id,
            session_id=public_session_id,
            title=episode.title or script.name,
        )
        if payload.question_answer or payload.wizard_answer:
            answer_payload = payload.wizard_answer or payload.question_answer
            assistant_service.answer_question(
                session_obj=assistant_session,
                user=user,
                question_key=answer_payload.question_id,
                action=answer_payload.action,
                answer=getattr(answer_payload, "answer", None),
                modifications=getattr(answer_payload, "modifications", None),
                answers=getattr(answer_payload, "answers", None),
                async_mode=True,
            )
        else:
            assistant_service.start_message(
                session_obj=assistant_session,
                user=user,
                content=payload.message,
                attachments=[item.model_dump() for item in payload.attachments],
                async_mode=True,
            )
    else:
        bridge_session = _legacy_episode_bridge_or_404(sessions, episode.id)
        assistant_session = assistant_service.get_or_create_openclaw_bridge_session(
            user=user,
            team=team,
            script_id=script.id,
            episode_id=episode.id,
            external_session=bridge_session,
        )
        if payload.question_answer or payload.wizard_answer:
            answer_payload = payload.wizard_answer or payload.question_answer
            assistant_service.answer_question(
                session_obj=assistant_session,
                user=user,
                question_key=answer_payload.question_id,
                action=answer_payload.action,
                answer=getattr(answer_payload, "answer", None),
                modifications=getattr(answer_payload, "modifications", None),
                answers=getattr(answer_payload, "answers", None),
                async_mode=True,
            )
        else:
            assistant_service.start_message(
                session_obj=assistant_session,
                user=user,
                content=payload.message,
                target="external",
                attachments=[item.model_dump() for item in payload.attachments],
                async_mode=True,
            )

    snapshot, timed_out = _wait_for_public_chat(session, assistant_service=assistant_service, assistant_session_id=assistant_session.id)
    return {"success": True, "data": _build_chat_response(session, team=team, script=script, episode=episode, snapshot=snapshot, timed_out=timed_out)}


@router.get("/api/openclaw/account/quota")
async def get_openclaw_account_quota(
    user: User = Depends(get_current_user_by_api_token),
    team: Team = Depends(get_current_team_by_api_token),
):
    total_points = int(user.permanent_points or 0) + int(user.temporary_points or 0)
    return {
        "success": True,
        "data": {
            "accounts": [
                {"scope": "user", "label": "个人灵感值", "points": total_points},
                {"scope": "team", "label": "团队灵感值", "points": int(team.team_points or 0)},
            ],
            "summary": {
                "total_points": total_points,
                "permanent_points": int(user.permanent_points or 0),
                "temporary_points": int(user.temporary_points or 0),
                "team_points": int(team.team_points or 0),
            },
        },
    }


@router.post("/api/openclaw/generate/images/estimate")
async def openclaw_estimate_image(
    payload: CreativeImageEstimateRequest,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    session: Session = Depends(get_session),
):
    return estimate_image_generation(session, payload.model_dump())


@router.post("/api/openclaw/generate/videos/estimate")
async def openclaw_estimate_video(
    payload: CreativeVideoEstimateRequest,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    session: Session = Depends(get_session),
):
    return estimate_video_generation(session, payload.model_dump())


@router.post("/api/openclaw/generate/audio/estimate")
async def openclaw_estimate_audio(
    payload: CreativeAudioEstimateRequest,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    session: Session = Depends(get_session),
):
    return estimate_audio_generation(session, payload.model_dump())


@router.post("/api/openclaw/generate/images")
async def openclaw_generate_image(
    payload: CreativeImageGenerateRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    user: User = Depends(get_current_user_by_api_token),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    record = submit_image_generation(session, background_tasks=background_tasks, user=user, team=team, payload=payload.model_dump())
    record = _mark_record_source(session, record=record, source="openclaw_api")
    return {
        "success": True,
        "data": {
            "task_id": record.task_id,
            "record": get_generation_record_detail(session, team=team, record_id=encode_id(record.id)),
        },
    }


@router.post("/api/openclaw/generate/videos")
async def openclaw_generate_video(
    payload: CreativeVideoGenerateRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    user: User = Depends(get_current_user_by_api_token),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    record = submit_video_generation(session, background_tasks=background_tasks, user=user, team=team, payload=payload.model_dump())
    record = _mark_record_source(session, record=record, source="openclaw_api")
    return {
        "success": True,
        "data": {
            "task_id": record.task_id,
            "record": get_generation_record_detail(session, team=team, record_id=encode_id(record.id)),
        },
    }


@router.post("/api/openclaw/generate/audio")
async def openclaw_generate_audio(
    payload: CreativeAudioGenerateRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    user: User = Depends(get_current_user_by_api_token),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    record = submit_audio_generation(session, background_tasks=background_tasks, user=user, team=team, payload=payload.model_dump())
    record = _mark_record_source(session, record=record, source="openclaw_api")
    return {
        "success": True,
        "data": {
            "task_id": record.task_id,
            "record": get_generation_record_detail(session, team=team, record_id=encode_id(record.id)),
        },
    }


@router.post("/api/openclaw/generate/assets")
async def openclaw_generate_asset(
    payload: CreativeAssetGenerateRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    user: User = Depends(get_current_user_by_api_token),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    record = submit_asset_generation(session, background_tasks=background_tasks, user=user, team=team, payload=payload.model_dump())
    record = _mark_record_source(session, record=record, source="openclaw_api")
    return {
        "success": True,
        "data": {
            "task_id": record.task_id,
            "record": get_generation_record_detail(session, team=team, record_id=encode_id(record.id)),
        },
    }


@router.get("/api/openclaw/generate/tasks/{task_id}")
async def get_openclaw_generate_task(
    task_id: str,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    task = _serialize_public_task(session, team=team, task_id=task_id)
    if not task:
        raise _error(404, "record_not_found", "任务不存在")
    return {"success": True, "data": {"task": task}}


@router.get("/api/openclaw/generation-records")
async def openclaw_generation_records(
    record_type: str = "",
    ownership_mode: str = "",
    project_id: Optional[str] = None,
    episode_id: Optional[str] = None,
    q: Optional[str] = None,
    status: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    payload = list_generation_records(
        session,
        team=team,
        record_type=record_type or None,
        ownership_mode=ownership_mode or None,
        project_id=project_id,
        episode_id=episode_id,
        q=q,
        status=status,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    payload["records"] = [_sanitize_public_generation_record(item) for item in payload.get("records") or []]
    return {
        "success": True,
        "data": payload,
    }


@router.get("/api/openclaw/generation-records/{record_id}")
async def openclaw_generation_record_detail(
    record_id: str,
    _: TeamMemberLink = Depends(require_team_permission_by_api_token("generate:run")),
    team: Team = Depends(get_current_team_by_api_token),
    session: Session = Depends(get_session),
):
    record = get_generation_record_detail(session, team=team, record_id=record_id)
    return {"success": True, "data": {"record": _sanitize_public_generation_record(record)}}
