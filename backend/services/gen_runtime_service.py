from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from sqlmodel import Session

from core.config import settings
from database import engine
from models import GenerationRecord, Team, User
from services.billing_service import refund_inspiration_points
from services.minimax_audio_service import minimax_audio_service
from services.oss_service import upload_bytes_to_oss_with_meta
from services.task_job_service import (
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_SUCCEEDED,
    get_task_job,
    mark_task_job_failed,
    mark_task_job_succeeded,
    update_task_job,
)

TASK_STATUS_WAITING_UPSTREAM = "waiting_upstream"


def _provider_callback_path(provider_key: str) -> str:
    path_by_provider = {
        "runninghub-image": "runninghub/image",
        "runninghub-video": "runninghub/video",
    }
    return path_by_provider.get(provider_key, provider_key)


def build_callback_url(*, provider_key: str, callback_token: str) -> str:
    base = str(settings.TASK_CALLBACK_BASE_URL or settings.OPENCLAW_PUBLIC_BASE_URL or "").rstrip("/")
    return f"{base}/api/provider-callbacks/{_provider_callback_path(provider_key)}?token={callback_token}"


def _next_poll_time(poll_attempts: int) -> datetime:
    if poll_attempts <= 3:
        delay = 2
    elif poll_attempts <= 10:
        delay = 5
    else:
        delay = 15
    return datetime.utcnow() + timedelta(seconds=delay)


def mark_task_waiting_upstream(
    task_id: str,
    *,
    upstream_task_id: str,
    callback_token: Optional[str] = None,
    use_poller: bool = False,
    message: Optional[str] = None,
) -> None:
    updates: Dict[str, Any] = {
        "status": TASK_STATUS_WAITING_UPSTREAM,
        "stage": "waiting_upstream",
        "upstream_task_id": upstream_task_id,
        "message": message or "任务已提交上游，等待结果中",
        "progress": 20,
        "callback_token": callback_token,
    }
    if use_poller:
        updates["next_poll_at"] = _next_poll_time(0)
        updates["poll_attempts"] = 0
    update_task_job(task_id, **updates)
    with Session(engine) as session:
        job = get_task_job(task_id, session=session)
        if not job or not job.generation_record_id:
            return
        record = session.get(GenerationRecord, job.generation_record_id)
        if not record:
            return
        record.status = "processing"
        session.add(record)
        session.commit()


def _resolve_audio_output(provider: str, output_ref: str, *, owner_user_id: Optional[int] = None, task_id: Optional[str] = None) -> Tuple[str, str]:
    if provider != "minimax-audio":
        return output_ref, ""
    content = minimax_audio_service.retrieve_file_content(output_ref)
    uploaded = upload_bytes_to_oss_with_meta(
        content,
        "minimax-audio-result.mp3",
        "audio/mpeg",
        owner_user_id=owner_user_id,
        media_type="audio",
        source_type="task_audio",
        source_id=None,
    )
    return str(uploaded.get("file_url") or ""), ""


def complete_generation_task(task_id: str, *, provider: str, result: Dict[str, Any]) -> None:
    output_ref = str(result.get("output_url") or "").strip()
    if not output_ref:
        mark_task_job_failed(
            task_id,
            error_code="provider_missing_output",
            error_message="上游返回成功但缺少输出地址",
            message="上游返回成功但缺少输出地址",
            retryable=False,
        )
        return
    with Session(engine) as session:
        job = get_task_job(task_id, session=session)
        if not job:
            return
        owner_user_id = job.user_id
    preview_url, thumbnail_url = _resolve_audio_output(provider, output_ref, owner_user_id=owner_user_id, task_id=task_id)
    with Session(engine) as session:
        job = get_task_job(task_id, session=session)
        if not job:
            return
        if job.generation_record_id:
            record = session.get(GenerationRecord, job.generation_record_id)
            if record:
                record.status = "completed"
                record.preview_url = preview_url
                record.thumbnail_url = thumbnail_url or record.thumbnail_url
                record.actual_points = record.estimate_points
                if not record.points_status:
                    record.points_status = "deducted"
                session.add(record)
                session.commit()
    mark_task_job_succeeded(
        task_id,
        result={**result, "preview_url": preview_url, "thumbnail_url": thumbnail_url},
        message="任务已完成",
    )


def fail_generation_task(task_id: str, *, error_message: str, error_code: str = "upstream_failed") -> None:
    with Session(engine) as session:
        job = get_task_job(task_id, session=session)
        if job and job.generation_record_id:
            record = session.get(GenerationRecord, job.generation_record_id)
            if record:
                if record.points_status == "deducted" and record.estimate_points:
                    user = session.get(User, record.user_id)
                    team = session.get(Team, record.team_id)
                    if user and team:
                        refund_inspiration_points(
                            user,
                            team,
                            int(record.estimate_points or 0),
                            "gen_refund",
                            "生成失败退款",
                            session,
                        )
                    record.points_status = "released"
                record.status = "failed"
                record.error_code_public = error_code
                record.error_message_public = error_message
                record.error_message_internal = error_message
                session.add(record)
                session.commit()
    mark_task_job_failed(
        task_id,
        error_code=error_code,
        error_message=error_message,
        message="任务失败",
        retryable=False,
    )


def build_callback_token() -> str:
    return secrets.token_urlsafe(24)


def schedule_next_poll(task_id: str, *, current_attempts: int, message: Optional[str] = None) -> None:
    update_task_job(
        task_id,
        status=TASK_STATUS_WAITING_UPSTREAM,
        poll_attempts=current_attempts,
        next_poll_at=_next_poll_time(current_attempts),
        message=message or "任务继续等待上游结果",
    )


def mark_callback_received(task_id: str) -> None:
    update_task_job(task_id, callback_received_at=datetime.utcnow(), next_poll_at=None)
