from __future__ import annotations

import logging
from typing import Any, Dict

from core.config import settings
from services.storyboard_director_service import StorySegmentParseError
from services.storyboard_split_runtime import run_storyboard_split_runtime
from services.task_job_service import TASK_STATUS_CANCELLED, get_task_job, mark_task_job_failed, update_task_job

logger = logging.getLogger(__name__)


def run_parse_story_segments_v3_task(task_id: str, payload: Dict[str, Any]) -> None:
    try:
        job = get_task_job(task_id)
        run_storyboard_split_runtime(
            episode_id=int(payload["episode_id"]),
            text=str(payload.get("text") or ""),
            storyboard_mode=payload.get("storyboard_mode"),
            api_key=settings.DEEPSEEK_API_KEY,
            task_id=task_id,
            confirmed_plan_bundle=payload.get("confirmed_plan_bundle") if isinstance(payload.get("confirmed_plan_bundle"), dict) else None,
            commit_segments=True,
            charge_enabled=True,
            user_id=int(payload["user_id"]) if payload.get("user_id") is not None else (int(job.user_id) if job and job.user_id is not None else None),
            team_id=int(payload["team_id"]) if payload.get("team_id") is not None else (int(job.team_id) if job and job.team_id is not None else None),
        )
    except StorySegmentParseError as exc:
        logger.exception("storyboard.parse_v3 failed: task_id=%s error_code=%s detail=%s", task_id, getattr(exc, "error_code", ""), getattr(exc, "detail", None) or str(exc))
        if getattr(exc, "error_code", "") == "task_cancelled":
            update_task_job(
                task_id,
                status=TASK_STATUS_CANCELLED,
                stage="cancelled",
                message=str(exc),
                error_code="task_cancelled",
                error_message=str(exc),
            )
            return
        mark_task_job_failed(
            task_id,
            error_code=getattr(exc, "error_code", "storyboard_parse_failed"),
            error_message=getattr(exc, "detail", None) or str(exc),
            message=str(exc),
            retryable=False,
        )
    except Exception as exc:
        logger.exception("storyboard.parse_v3 unexpected failure: task_id=%s", task_id)
        mark_task_job_failed(
            task_id,
            error_code="storyboard_parse_failed",
            error_message=str(exc),
            message="剧情片段拆分失败",
            retryable=False,
        )
