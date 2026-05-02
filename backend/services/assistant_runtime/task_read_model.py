from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks
from sqlalchemy import desc
from sqlmodel import Session, select

from core.security import encode_id
from models import Episode, GenerationRecord, Panel, SharedResource, Team, User
from services.generation_record_service import (
    _run_asset_generation_job,
    _run_audio_async_job,
    _run_image_generation_job,
    _run_video_generation_job,
    submit_asset_generation,
    submit_audio_generation,
    submit_image_generation,
    submit_video_generation,
)
from services.task_registry import (
    nano_tasks,
    resource_extract_tasks,
    resource_generate_tasks,
    standalone_tasks,
    video_tasks,
)

ACTIVE_TASK_STATUSES = {"queued", "processing", "pending", "running", "submitted", "submitting", "committing", "applying"}
TERMINAL_TASK_STATUSES = {"completed", "success", "failed", "error", "expired", "canceled", "cancelled"}
STATUS_LABELS = {
    "queued": "排队中",
    "pending": "等待中",
    "submitted": "生成中",
    "processing": "生成中",
    "running": "生成中",
    "submitting": "生成中",
    "committing": "生成中",
    "applying": "生成中",
    "completed": "已完成",
    "success": "已完成",
    "failed": "失败",
    "error": "失败",
}

TARGET_TYPE_LABELS = {
    "panel": "分镜",
    "shared_resource": "共享资源",
    "episode_record": "剧集记录",
}


def _episode_display_title(title: Optional[str], sequence_num: Optional[int]) -> str:
    text = str(title or "").strip()
    if text:
        return text
    if sequence_num:
        return "第{0}集".format(sequence_num)
    return ""


def _build_script_task_context(
    session: Session,
    *,
    script_id: int,
) -> Dict[str, Dict[int, Dict[str, Any]]]:
    episode_lookup: Dict[int, Dict[str, Any]] = {}
    episode_to_script: Dict[int, int] = {}
    episode_ids: List[int] = []

    episode_rows = session.exec(
        select(Episode.id, Episode.script_id, Episode.sequence_num, Episode.title).where(Episode.script_id == script_id)
    ).all()
    for row in episode_rows:
        if not row or not row[0]:
            continue
        episode_id = int(row[0])
        episode_ids.append(episode_id)
        episode_to_script[episode_id] = int(row[1])
        episode_lookup[episode_id] = {
            "id": episode_id,
            "script_id": int(row[1]),
            "sequence_num": int(row[2]) if row[2] is not None else None,
            "title": str(row[3] or "").strip(),
        }

    panel_lookup: Dict[int, Dict[str, Any]] = {}
    if episode_ids:
        panel_rows = session.exec(
            select(Panel.id, Panel.sequence_num, Panel.episode_id).where(Panel.episode_id.in_(episode_ids))
        ).all()
        for row in panel_rows:
            if not row or not row[0]:
                continue
            panel_lookup[int(row[0])] = {
                "id": int(row[0]),
                "sequence_num": int(row[1]) if row[1] is not None else None,
                "episode_id": int(row[2]) if row[2] is not None else None,
            }

    resource_lookup: Dict[int, Dict[str, Any]] = {}
    resource_rows = session.exec(
        select(SharedResource.id, SharedResource.name, SharedResource.resource_type).where(SharedResource.script_id == script_id)
    ).all()
    for row in resource_rows:
        if not row or not row[0]:
            continue
        resource_lookup[int(row[0])] = {
            "id": int(row[0]),
            "name": str(row[1] or "").strip(),
            "resource_type": str(row[2] or "").strip(),
        }

    return {
        "episode_lookup": episode_lookup,
        "episode_to_script": episode_to_script,
        "panel_lookup": panel_lookup,
        "resource_lookup": resource_lookup,
    }


def _build_generation_target_meta(
    record: GenerationRecord,
    *,
    episode_lookup: Dict[int, Dict[str, Any]],
    panel_lookup: Dict[int, Dict[str, Any]],
    resource_lookup: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    target_type = str(record.target_type or "").strip().lower()
    target_id = int(record.target_id) if record.target_id else None
    episode_meta = episode_lookup.get(int(record.episode_id)) if record.episode_id else None

    if target_type == "panel" and target_id:
        panel_meta = panel_lookup.get(target_id)
        linked_episode = episode_lookup.get(panel_meta.get("episode_id")) if panel_meta and panel_meta.get("episode_id") else episode_meta
        episode_title = _episode_display_title(
            linked_episode.get("title") if linked_episode else None,
            linked_episode.get("sequence_num") if linked_episode else None,
        )
        sequence_num = panel_meta.get("sequence_num") if panel_meta else None
        summary_parts = []
        if sequence_num:
            summary_parts.append("第 {0} 镜".format(sequence_num))
        if episode_title:
            summary_parts.append(episode_title)
        return {
            "label": TARGET_TYPE_LABELS.get("panel"),
            "name": "分镜 #{0}".format(sequence_num) if sequence_num else "对应分镜",
            "summary": " · ".join(summary_parts) or "对应分镜",
            "sequence": sequence_num,
            "episode_title": episode_title or None,
        }

    if target_type == "shared_resource" and target_id:
        resource_meta = resource_lookup.get(target_id)
        resource_name = resource_meta.get("name") if resource_meta else ""
        resource_type = resource_meta.get("resource_type") if resource_meta else ""
        summary = resource_name or TARGET_TYPE_LABELS.get("shared_resource")
        if resource_name and resource_type:
            summary = "{0} · {1}".format(resource_name, resource_type)
        return {
            "label": TARGET_TYPE_LABELS.get("shared_resource"),
            "name": resource_name or "对应资产",
            "summary": summary,
            "sequence": None,
            "episode_title": None,
        }

    if target_type == "episode_record":
        episode_title = _episode_display_title(
            episode_meta.get("title") if episode_meta else None,
            episode_meta.get("sequence_num") if episode_meta else None,
        )
        return {
            "label": TARGET_TYPE_LABELS.get("episode_record"),
            "name": episode_title or "当前剧集",
            "summary": episode_title or "当前剧集",
            "sequence": None,
            "episode_title": episode_title or None,
        }

    return {
        "label": TARGET_TYPE_LABELS.get(target_type, record.target_type),
        "name": None,
        "summary": None,
        "sequence": None,
        "episode_title": None,
    }


def _json_loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return "{}"


def _status_label(status: Optional[str]) -> str:
    text = str(status or "").strip().lower()
    return STATUS_LABELS.get(text, text or "未知")


def _normalize_status(status: Optional[str]) -> str:
    text = str(status or "").strip().lower()
    return text or "unknown"


def _derive_refresh_hints_for_generation(record: GenerationRecord) -> Dict[str, bool]:
    target_type = str(record.target_type or "").strip().lower()
    record_type = str(record.record_type or "").strip().lower()
    hints: Dict[str, bool] = {}
    if target_type == "panel":
        hints["panels"] = True
        if record_type in {"image", "video"}:
            hints["canvas"] = True
    elif target_type == "shared_resource":
        hints["resources"] = True
        hints["assets"] = True
    elif target_type == "episode_record":
        hints["episodes"] = True
    return hints


def _encode_optional_id(value: Optional[int]) -> Optional[str]:
    return encode_id(value) if value else None


def _normalize_assistant_session_id(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        return encode_id(int(value))
    except Exception:
        text = str(value).strip()
        return text or None


def _normalize_media_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _retry_error_retryable(record: GenerationRecord) -> bool:
    code = str(record.error_code_public or "").strip().lower()
    if code:
        return code in {"service_unavailable", "generation_failed"}
    return _normalize_status(record.status) in {"failed", "error"}


def _build_retry_payload(record: GenerationRecord) -> Optional[Dict[str, Any]]:
    ownership_mode = str(record.ownership_mode or "").strip() or "project"
    project_id = _encode_optional_id(record.script_id)
    episode_id = _encode_optional_id(record.episode_id)
    target_id = _encode_optional_id(record.target_id)
    if ownership_mode == "project" and (not project_id or not episode_id):
        return None

    params_public = _json_loads(record.params_public_json, {})
    params_internal = _json_loads(record.params_internal_json, {})
    common: Dict[str, Any] = {
        "ownership_mode": ownership_mode,
        "project_id": project_id,
        "episode_id": episode_id,
        "target_type": record.target_type,
        "target_id": target_id,
    }

    if record.record_type == "image":
        payload = dict(common)
        payload.update(
            {
                "prompt": str(record.prompt or "").strip(),
                "negative_prompt": str(record.negative_prompt or "").strip() or None,
                "model": str(params_public.get("model") or "").strip() or None,
                "resolution": str(params_public.get("resolution") or "").strip() or None,
                "aspect_ratio": str(params_public.get("aspect_ratio") or "").strip() or None,
                "reference_images": _normalize_media_list(params_internal.get("reference_images")),
            }
        )
        return payload

    if record.record_type == "video":
        request_payload = params_internal.get("request_payload") if isinstance(params_internal, dict) else {}
        request_payload = request_payload if isinstance(request_payload, dict) else {}
        payload = dict(common)
        payload.update(
            {
                "prompt": str(record.prompt or request_payload.get("prompt") or "").strip(),
                "model_code": str(request_payload.get("model_code") or params_public.get("model_code") or "").strip() or None,
                "generation_type": str(request_payload.get("generation_type") or params_public.get("generation_type") or "").strip() or None,
                "resolution": str(request_payload.get("resolution") or params_public.get("resolution") or "").strip() or None,
                "duration": request_payload.get("duration") or params_public.get("duration"),
                "aspect_ratio": str(request_payload.get("aspect_ratio") or params_public.get("aspect_ratio") or "").strip() or None,
                "image_refs": _normalize_media_list(request_payload.get("image_refs")),
                "video_refs": _normalize_media_list(request_payload.get("video_refs")),
                "audio_enabled": bool(request_payload.get("audio_enabled")),
                "first_frame": str(request_payload.get("first_frame") or "").strip() or None,
                "last_frame": str(request_payload.get("last_frame") or "").strip() or None,
                "motion_strength": str(request_payload.get("motion_strength") or "").strip() or None,
                "camera_fixed": bool(request_payload.get("camera_fixed")),
                "quality_mode": str(request_payload.get("quality_mode") or "").strip() or None,
                "audio_url": str(request_payload.get("audio_url") or "").strip() or None,
            }
        )
        return payload

    if record.record_type == "audio":
        request_payload = params_internal.get("request_payload") if isinstance(params_internal, dict) else {}
        request_payload = request_payload if isinstance(request_payload, dict) else {}
        payload = dict(common)
        payload.update(request_payload)
        if not payload.get("prompt"):
            payload["prompt"] = str(record.prompt or "").strip() or None
        return payload

    if record.record_type == "asset":
        payload = dict(common)
        payload.update(
            {
                "asset_type": str(params_public.get("asset_type") or "").strip() or None,
                "name": str(params_public.get("name") or "").strip() or None,
                "description": params_public.get("description"),
                "trigger_word": params_public.get("trigger_word"),
                "aliases": params_public.get("aliases") if isinstance(params_public.get("aliases"), list) else [],
                "prompt": str(record.prompt or "").strip(),
                "model": str(params_public.get("model") or "").strip() or None,
                "resolution": str(params_public.get("resolution") or "").strip() or None,
                "aspect_ratio": str(params_public.get("aspect_ratio") or "").strip() or None,
                "reference_images": _normalize_media_list(params_internal.get("reference_images")),
            }
        )
        return payload

    return None


def _apply_retry_source(session: Session, original: GenerationRecord, retried: GenerationRecord) -> GenerationRecord:
    original_public = _json_loads(original.params_public_json, {})
    original_internal = _json_loads(original.params_internal_json, {})
    retry_public = _json_loads(retried.params_public_json, {})
    retry_internal = _json_loads(retried.params_internal_json, {})
    source = str(original_public.get("source") or original_internal.get("source") or "").strip()
    if source:
        retry_public["source"] = source
        retry_internal["source"] = source
        retried.params_public_json = _json_dumps(retry_public)
        retried.params_internal_json = _json_dumps(retry_internal)
        session.add(retried)
        session.commit()
        session.refresh(retried)
    return retried


def _launch_retry_worker(record: GenerationRecord) -> None:
    return


def _serialize_generation_result(record: GenerationRecord, *, status: str) -> Optional[Dict[str, Any]]:
    preview_url = str(record.preview_url or "").strip()
    thumbnail_url = str(record.thumbnail_url or "").strip()
    error_message = str(record.error_message_public or "").strip()
    params_public = _json_loads(record.params_public_json, {})
    if status not in TERMINAL_TASK_STATUSES and not preview_url and not error_message:
        return None
    return {
        "kind": str(record.record_type or "task"),
        "preview_url": preview_url or None,
        "thumbnail_url": thumbnail_url or None,
        "output_kind": params_public.get("output_kind"),
        "operation_type": params_public.get("operation_type"),
        "error_message": error_message or None,
    }


def _build_generation_task(
    record: GenerationRecord,
    *,
    episode_lookup: Dict[int, Dict[str, Any]],
    panel_lookup: Dict[int, Dict[str, Any]],
    resource_lookup: Dict[int, Dict[str, Any]],
) -> Dict[str, Any]:
    params_public = _json_loads(record.params_public_json, {})
    params_internal = _json_loads(record.params_internal_json, {})
    record_type = str(record.record_type or "task")
    summary = (
        params_public.get("prompt_summary")
        or params_public.get("summary")
        or str(record.prompt or "").strip()
        or "{0} 任务".format(record_type)
    )
    status = _normalize_status(record.status)
    source = str(params_public.get("source") or params_internal.get("source") or "webui")
    assistant_session_id = _normalize_assistant_session_id(params_internal.get("assistant_session_id"))
    refresh_hints = _derive_refresh_hints_for_generation(record)
    preview_url = str(record.preview_url or "").strip() or None
    thumbnail_url = str(record.thumbnail_url or "").strip() or None
    result = _serialize_generation_result(record, status=status)
    retryable = status in {"failed", "error"} and _build_retry_payload(record) is not None
    target_meta = _build_generation_target_meta(
        record,
        episode_lookup=episode_lookup,
        panel_lookup=panel_lookup,
        resource_lookup=resource_lookup,
    )

    return {
        "task_id": str(record.task_id or "record-{0}".format(record.id)),
        "kind": record_type,
        "source": source,
        "assistant_session_id": assistant_session_id,
        "origin": "generation_record",
        "title": {
            "image": "图片生成",
            "video": "视频生成",
            "audio": "配音生成",
            "asset": "资产生成",
        }.get(record_type, "创作任务"),
        "summary": summary,
        "status": status,
        "status_label": _status_label(status),
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        "record_id": encode_id(record.id) if record.id else None,
        "project_id": encode_id(record.script_id) if record.script_id else None,
        "episode_id": encode_id(record.episode_id) if record.episode_id else None,
        "target_type": record.target_type,
        "target_id": encode_id(record.target_id) if record.target_id else None,
        "target_label": target_meta.get("label"),
        "target_name": target_meta.get("name"),
        "target_summary": target_meta.get("summary"),
        "target_sequence": target_meta.get("sequence"),
        "target_episode_title": target_meta.get("episode_title"),
        "preview_url": preview_url,
        "thumbnail_url": thumbnail_url,
        "is_terminal": status in TERMINAL_TASK_STATUSES,
        "retryable": retryable,
        "refresh_hints": refresh_hints,
        "result": result,
        "error": (
            {
                "code": str(record.error_code_public or "").strip() or None,
                "message": str(record.error_message_public or "").strip() or None,
                "retryable": _retry_error_retryable(record),
            }
            if str(record.error_code_public or "").strip() or str(record.error_message_public or "").strip()
            else None
        ),
        "meta": {
            "ownership_mode": record.ownership_mode,
            "estimate_points": record.estimate_points,
            "actual_points": record.actual_points,
            "params": params_public,
        },
    }


def _build_registry_task(
    task: Dict[str, Any],
    *,
    episode_to_script: Dict[int, int],
    episode_lookup: Dict[int, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    script_id = task.get("script_id")
    episode_id = task.get("episode_id")
    if not script_id and episode_id:
        try:
            script_id = episode_to_script.get(int(episode_id))
        except Exception:
            script_id = None
    if not script_id:
        return None

    status = _normalize_status(task.get("status"))
    episode_meta = episode_lookup.get(int(episode_id)) if episode_id else None
    episode_title = _episode_display_title(
        episode_meta.get("title") if episode_meta else None,
        episode_meta.get("sequence_num") if episode_meta else None,
    )
    return {
        "task_id": str(task.get("task_id") or ""),
        "kind": str(task.get("kind") or "task"),
        "source": str(task.get("source") or "webui"),
        "assistant_session_id": _normalize_assistant_session_id(task.get("assistant_session_id")),
        "origin": "registry",
        "title": str(task.get("title") or "进行中任务"),
        "summary": str(task.get("summary") or task.get("msg") or "").strip(),
        "status": status,
        "status_label": _status_label(status),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
        "record_id": None,
        "project_id": encode_id(int(script_id)) if script_id else None,
        "episode_id": encode_id(int(episode_id)) if episode_id else None,
        "target_type": task.get("target_type"),
        "target_id": task.get("target_id"),
        "target_label": TARGET_TYPE_LABELS.get(str(task.get("target_type") or "").strip().lower(), task.get("target_type")),
        "target_name": episode_title or None,
        "target_summary": episode_title or None,
        "target_sequence": None,
        "target_episode_title": episode_title or None,
        "preview_url": task.get("preview_url"),
        "thumbnail_url": task.get("thumbnail_url"),
        "is_terminal": status in TERMINAL_TASK_STATUSES,
        "refresh_hints": task.get("refresh_hints") or {},
        "result": task.get("result"),
        "error": task.get("error"),
        "meta": {
            "message": task.get("msg") or "",
            "progress": task.get("progress"),
            "panel_count": task.get("panel_count"),
            "resource_id": task.get("resource_id"),
        },
    }


def _sort_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        tasks,
        key=lambda item: (
            str(item.get("updated_at") or ""),
            str(item.get("created_at") or ""),
            str(item.get("task_id") or ""),
        ),
        reverse=True,
    )


def list_script_tasks(
    session: Session,
    *,
    user: User,
    script_id: int,
    active_only: bool = False,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    context = _build_script_task_context(session, script_id=script_id)
    episode_to_script = context["episode_to_script"]
    episode_lookup = context["episode_lookup"]
    panel_lookup = context["panel_lookup"]
    resource_lookup = context["resource_lookup"]

    statement = (
        select(GenerationRecord)
        .where(
            GenerationRecord.user_id == user.id,
            GenerationRecord.script_id == script_id,
        )
        .order_by(desc(GenerationRecord.updated_at), desc(GenerationRecord.id))
    )
    records = session.exec(statement.limit(limit)).all()

    tasks: List[Dict[str, Any]] = []
    for record in records:
        task = _build_generation_task(
            record,
            episode_lookup=episode_lookup,
            panel_lookup=panel_lookup,
            resource_lookup=resource_lookup,
        )
        if active_only and task["status"] not in ACTIVE_TASK_STATUSES:
            continue
        tasks.append(task)

    registries = [
        resource_extract_tasks,
        resource_generate_tasks,
        video_tasks,
        nano_tasks,
        standalone_tasks,
    ]
    for registry in registries:
        for item in registry.list():
            if item.get("user_id") and int(item.get("user_id")) != int(user.id):
                continue
            task = _build_registry_task(
                item,
                episode_to_script=episode_to_script,
                episode_lookup=episode_lookup,
            )
            if not task or task.get("project_id") != encode_id(script_id):
                continue
            if active_only and task["status"] not in ACTIVE_TASK_STATUSES:
                continue
            tasks.append(task)

    return _sort_tasks(tasks)[:limit]


def retry_script_task(
    session: Session,
    *,
    user: User,
    team: Team,
    script_id: int,
    task_id: str,
) -> Dict[str, Any]:
    record = session.exec(
        select(GenerationRecord).where(
            GenerationRecord.user_id == user.id,
            GenerationRecord.script_id == script_id,
            GenerationRecord.task_id == task_id,
        )
    ).first()
    if not record:
        raise ValueError("未找到可重试的任务")

    current_status = _normalize_status(record.status)
    if current_status in ACTIVE_TASK_STATUSES:
        raise RuntimeError("当前任务仍在进行中，暂时不能重试")

    retry_payload = _build_retry_payload(record)
    if not retry_payload:
        raise RuntimeError("当前任务暂不支持重试")

    background_tasks = BackgroundTasks()
    if record.record_type == "image":
        retried = submit_image_generation(session, background_tasks=background_tasks, user=user, team=team, payload=retry_payload)
    elif record.record_type == "video":
        retried = submit_video_generation(session, background_tasks=background_tasks, user=user, team=team, payload=retry_payload)
    elif record.record_type == "audio":
        retried = submit_audio_generation(session, background_tasks=background_tasks, user=user, team=team, payload=retry_payload)
    elif record.record_type == "asset":
        retried = submit_asset_generation(session, background_tasks=background_tasks, user=user, team=team, payload=retry_payload)
    else:
        raise RuntimeError("当前任务类型暂不支持重试")

    retried = _apply_retry_source(session, record, retried)
    _launch_retry_worker(retried)
    context = _build_script_task_context(session, script_id=script_id)
    return _build_generation_task(
        retried,
        episode_lookup=context["episode_lookup"],
        panel_lookup=context["panel_lookup"],
        resource_lookup=context["resource_lookup"],
    )
