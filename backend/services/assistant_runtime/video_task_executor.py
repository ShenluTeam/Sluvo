from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, HTTPException

from core.security import encode_id
from models import AssistantSession, Panel, Team, User
from services.generation_record_service import _run_video_generation_job, submit_video_generation
from services.storyboard_mode_service import get_panel_latest_image, get_panel_reference_images

from .panel_selection import build_selected_panels_payload, format_selected_panel_display
from .video_skill_planner import build_video_execution_plan_payload, build_video_generation_field_options


def attachment_media_urls(attachments: Optional[List[Dict[str, Any]]]) -> Dict[str, List[str]]:
    image_urls: List[str] = []
    video_urls: List[str] = []
    for item in attachments or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        item_type = str(item.get("type") or "").strip().lower()
        mime_type = str(item.get("mime_type") or "").strip().lower()
        if item_type == "video" or mime_type.startswith("video/"):
            video_urls.append(url)
        else:
            image_urls.append(url)
    return {"image_urls": image_urls, "video_urls": video_urls}


def coerce_bool(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def panel_latest_image(panel: Panel) -> str:
    return str(get_panel_latest_image(panel) or panel.file_url or "").strip()


def panel_has_video(panel: Panel) -> bool:
    if str(panel.video_url or "").strip():
        return True
    return str(getattr(panel, "video_history_json", "") or "").strip() not in {"", "[]", "null"}


def panel_video_duration(panel: Panel) -> int:
    storyboard_mode = str(getattr(panel, "storyboard_mode", "") or "").strip().lower()
    return 8 if storyboard_mode == "comic" else 6


def derive_panel_video_prompt(panel: Panel) -> str:
    for value in [
        panel.video_prompt,
        panel.prompt,
        panel.prompt_zh,
        panel.image_framing,
        panel.composition,
        panel.original_text,
        panel.narration_text,
        panel.dialogue_text,
    ]:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def build_panel_video_payload(
    service,
    *,
    session_obj: AssistantSession,
    panel: Panel,
    prompt_override: Optional[str],
    model_code: str,
    generation_type: str,
    duration: int,
    resolution: str,
    audio_enabled: bool,
    attachment_image_urls: List[str],
    attachment_video_urls: List[str],
) -> Dict[str, Any]:
    base_prompt = derive_panel_video_prompt(panel)
    extra_prompt = str(prompt_override or "").strip()
    prompt = extra_prompt or base_prompt
    if base_prompt and extra_prompt:
        prompt = "{0}\n补充要求：{1}".format(base_prompt, extra_prompt)
    if not prompt:
        raise HTTPException(status_code=400, detail="当前分镜缺少可用视频提示词，请先补充分镜描述或在向导里填写补充要求")

    latest_image = panel_latest_image(panel)
    panel_reference_images = [
        str(item).strip()
        for item in (get_panel_reference_images(service.session, panel) or [])
        if str(item).strip()
    ]
    image_refs = [str(item).strip() for item in attachment_image_urls if str(item).strip()]
    video_refs = [str(item).strip() for item in attachment_video_urls if str(item).strip()]
    first_frame = ""
    last_frame = ""

    if generation_type == "image_to_video":
        first_frame = (image_refs[0] if image_refs else latest_image) or ""
        image_refs = [first_frame] if first_frame else []
    elif generation_type == "reference_to_video":
        if not image_refs:
            image_refs = panel_reference_images[:7]
        if not image_refs and latest_image:
            image_refs = [latest_image]
        image_refs = image_refs[:7]
        video_refs = video_refs[:2]
    elif generation_type == "start_end_to_video":
        if len(image_refs) >= 2:
            first_frame = image_refs[0]
            last_frame = image_refs[1]
        else:
            first_frame = latest_image or (image_refs[0] if image_refs else "")
            last_frame = image_refs[1] if len(image_refs) > 1 else ""

    storyboard_mode = str(getattr(panel, "storyboard_mode", "") or "").strip().lower()
    aspect_ratio = "16:9" if storyboard_mode == "comic" else "9:16"

    return {
        "ownership_mode": "project",
        "project_id": encode_id(session_obj.script_id),
        "episode_id": encode_id(panel.episode_id),
        "target_type": "panel",
        "target_id": encode_id(panel.id),
        "model_code": model_code,
        "generation_type": generation_type,
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
        "image_refs": image_refs,
        "video_refs": video_refs,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "audio_enabled": audio_enabled,
        "motion_strength": "auto",
    }


def submit_panel_video_generation_tasks(
    service,
    *,
    session_obj: AssistantSession,
    user: User,
    selected_panels: List[Panel],
    prompt_override: Optional[str] = None,
    model_choice: Optional[Dict[str, Any]] = None,
    duration: Optional[Any] = None,
    resolution: Optional[str] = None,
    generation_type: Optional[str] = None,
    audio_enabled: bool = False,
    attachments: Optional[List[Dict[str, Any]]] = None,
    selection_reason: str = "",
    selection_mode: str = "auto",
    resume_hint: str = "",
) -> Dict[str, Any]:
    team = service.session.get(Team, session_obj.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="当前会话所属团队不存在")
    if not selected_panels:
        raise HTTPException(status_code=400, detail="请先选择要处理的分镜范围")

    resolved_model = (model_choice or {}).get("model") or {}
    resolved_model_code = str(resolved_model.get("model_code") or "").strip().lower()
    if not resolved_model_code:
        raise HTTPException(status_code=400, detail="当前没有可用的视频模型，请先调整模型或生成方式")

    media_urls = attachment_media_urls(attachments)
    resolved_generation_type = str(generation_type or resolved_model.get("generation_type") or "text_to_video").strip().lower()
    field_options = build_video_generation_field_options(resolved_model_code, resolved_generation_type)
    try:
        resolved_duration = int(duration or field_options["defaults"].get("duration") or panel_video_duration(selected_panels[0]))
    except Exception:
        resolved_duration = int(field_options["defaults"].get("duration") or panel_video_duration(selected_panels[0]))

    allowed_durations = {int(item["value"]) for item in field_options["duration_options"]}
    if allowed_durations and resolved_duration not in allowed_durations:
        resolved_duration = sorted(allowed_durations)[0]

    resolved_resolution = str(resolution or field_options["defaults"].get("resolution") or "720p").strip().lower()
    allowed_resolutions = {str(item["value"]).strip().lower() for item in field_options["resolution_options"]}
    if allowed_resolutions and resolved_resolution not in allowed_resolutions:
        resolved_resolution = sorted(allowed_resolutions)[0]

    selected_display = format_selected_panel_display(selected_panels)
    selected_panel_payload = build_selected_panels_payload(selected_panels)
    execution_plan = build_video_execution_plan_payload(
        execution_stage="submitted_video_tasks",
        selected_panels=selected_panels,
        model_choice=model_choice,
        selection_reason=selection_reason,
        resume_hint=resume_hint or "已按 {0} 提交视频任务。".format(selected_display),
    )

    task_items: List[Dict[str, Any]] = []
    refresh_hints = {"panels": True, "canvas": True}

    for panel in selected_panels:
        payload = build_panel_video_payload(
            service,
            session_obj=session_obj,
            panel=panel,
            prompt_override=prompt_override,
            model_code=resolved_model_code,
            generation_type=resolved_generation_type,
            duration=resolved_duration,
            resolution=resolved_resolution,
            audio_enabled=audio_enabled,
            attachment_image_urls=media_urls["image_urls"],
            attachment_video_urls=media_urls["video_urls"],
        )
        background_tasks = BackgroundTasks()
        record = submit_video_generation(
            service.session,
            background_tasks=background_tasks,
            user=user,
            team=team,
            payload=payload,
        )
        record = service._mark_generation_record_source(
            session_obj=session_obj,
            record=record,
            params_public_updates={
                "selected_panels": selected_panel_payload,
                "selected_panel_sequences": [int(item.sequence_num or 0) for item in selected_panels if int(item.sequence_num or 0) > 0],
                "selected_panel_count": len(selected_panels),
                "selected_panel_display": selected_display,
                "selection_reason": selection_reason,
                "selection_mode": selection_mode,
                "resolved_model_choice": execution_plan.get("resolved_model_choice"),
            },
            params_internal_updates={
                "selected_panels": selected_panel_payload,
                "selection_reason": selection_reason,
                "selection_mode": selection_mode,
                "resume_hint": resume_hint,
                "assistant_execution_plan": execution_plan,
                "attachment_image_urls": media_urls["image_urls"],
                "attachment_video_urls": media_urls["video_urls"],
            },
        )
        threading.Thread(target=_run_video_generation_job, args=(record.id,), daemon=True).start()
        task_items.append(
            {
                "task_id": str(record.task_id or ""),
                "record_id": encode_id(record.id) if record.id else None,
                "panel_id": encode_id(panel.id) if panel.id else None,
                "panel_sequence": int(panel.sequence_num or 0),
                "status": str(record.status or "queued"),
            }
        )

    return {
        "task_items": task_items,
        "selected_display": selected_display,
        "selected_panel_payload": selected_panel_payload,
        "resolved_model": resolved_model,
        "resolved_generation_type": resolved_generation_type,
        "refresh_hints": refresh_hints,
        "execution_plan": execution_plan,
    }
