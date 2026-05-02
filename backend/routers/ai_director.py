from __future__ import annotations

import uuid
from typing import Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.config import settings
from core.security import decode_id, encode_id
from database import get_session
from dependencies import get_current_team, require_team_permission
from models import Script, Team, TeamMemberLink
from schemas import ParseScriptV2CommitRequest, ParseScriptV2Request, normalize_storyboard_mode
from services.access_service import require_episode_team_access
from services.resource_extraction_service import (
    load_structured_assets_from_shared_resources,
    sync_structured_assets_into_shared_resources,
)
from services.story_segment_service import commit_story_segments_with_cells
from services.task_job_service import (
    cancel_task_job,
    create_task_job,
    enqueue_task_job,
    get_task_job,
    serialize_task_job,
)
from services.workflow_preset_service import resolve_storyboard_extraction_storyboard_mode
from services.storyboard_split_runtime import StoryboardSplitBillingTracker, build_storyboard_plan_bundle

router = APIRouter()

AI_SERVICE_UNAVAILABLE_DETAIL = "当前智能拆分服务暂不可用，请稍后重试"


def _require_split_assets(session: Session, script_id: int) -> None:
    structured_assets_raw = load_structured_assets_from_shared_resources(session, script_id)
    if not any(structured_assets_raw.get(key) for key in ("characters", "scenes", "props")):
        raise HTTPException(status_code=400, detail="请先完成资产提取后再拆分分镜")


def _normalize_storyboard_task_message(data: Dict[str, object]) -> str:
    stage = str(data.get("stage") or "").strip().lower()
    legacy_status = str(data.get("legacy_status") or "").strip().lower()
    raw_message = str(data.get("message") or "").strip()

    if stage == "submitted":
        return "剧情片段拆分任务已提交，正在准备分析当前分集。"
    if legacy_status == "processing" and ("worker" in raw_message.lower() or "接受" in raw_message):
        return "正在准备剧情片段拆分。"
    if stage == "planning_segments":
        return raw_message or "正在规划剧情片段与整体节奏。"
    if stage == "expanding_grids":
        return raw_message or "正在细化镜头与宫格结构。"
    if stage == "json_fixing":
        return raw_message or "正在修复结构化结果。"
    if stage == "committing":
        return raw_message or "正在写入分镜结果。"
    return raw_message


def _serialize_v3_status(task_id: str, job) -> Dict[str, object]:
    data = serialize_task_job(job)
    result = data.get("result") or {}
    error = data.get("error") or {}
    return {
        "task_id": task_id,
        "status": data.get("legacy_status"),
        "msg": _normalize_storyboard_task_message(data),
        "progress": data.get("progress"),
        "stage": data.get("stage"),
        "current_segment": result.get("current_segment"),
        "segment_count": result.get("segment_count"),
        "panel_count": result.get("panel_count") or 0,
        "structured_draft": result.get("structured_draft"),
        "warnings": result.get("warnings") or [],
        "error_code": error.get("code"),
        "error_detail": error.get("message"),
        "grid_distribution": result.get("grid_distribution"),
        "average_duration_seconds": result.get("average_duration_seconds"),
        "segments": result.get("segments"),
        "storyboard_mode": result.get("storyboard_mode"),
        "billing": data.get("billing"),
        "charged_points": data.get("charged_points"),
        "actual_points": data.get("actual_points"),
        "actual_cost_cny": data.get("actual_cost_cny"),
        "points_status": data.get("points_status"),
    }


@router.post("/api/episodes/{episode_id}/parse_story_segments_v3")
def parse_story_segments_v3(
    episode_id: str,
    req: ParseScriptV2Request,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_episode_id = decode_id(episode_id)
    episode = require_episode_team_access(session, team, real_episode_id)

    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail=AI_SERVICE_UNAVAILABLE_DETAIL)

    _require_split_assets(session, episode.script_id)

    script = session.get(Script, episode.script_id)
    resolved_storyboard_mode = resolve_storyboard_extraction_storyboard_mode(script) if script is not None else normalize_storyboard_mode(req.storyboard_mode or episode.storyboard_mode)
    mode = str(req.mode or "split_confirmed").strip().lower()
    if mode == "plan_first":
        billing_tracker = StoryboardSplitBillingTracker(
            user_id=getattr(_, "user_id", None),
            team_id=team.id,
            task_id=None,
            charge_enabled=True,
        )
        plan_bundle = build_storyboard_plan_bundle(
            episode_id=real_episode_id,
            text=req.text,
            api_key=settings.DEEPSEEK_API_KEY,
            storyboard_mode=resolved_storyboard_mode,
            previous_plan_bundle=req.confirmed_plan_bundle,
            revision_instruction=req.plan_revision_instruction,
            billing_tracker=billing_tracker,
        )
        return {
            "task_id": "",
            "status": "completed",
            "mode": "plan_first",
            "storyboard_plan_bundle": plan_bundle,
            "billing": billing_tracker.snapshot(),
        }

    task_id = str(uuid.uuid4())[:12]
    job = create_task_job(
        session,
        task_id=task_id,
        task_type="storyboard.parse_v3",
        queue_name="storyboard",
        provider="deepseek",
        team_id=team.id,
        user_id=getattr(_, "user_id", None),
        script_id=episode.script_id,
        episode_id=real_episode_id,
        ownership_mode="project",
        scope_type="episode",
        scope_id=real_episode_id,
        task_category="storyboard",
        payload={
            "episode_id": real_episode_id,
            "text": req.text,
            "storyboard_mode": resolved_storyboard_mode,
            "confirmed_plan_id": req.confirmed_plan_id,
            "confirmed_plan_bundle": req.confirmed_plan_bundle if isinstance(req.confirmed_plan_bundle, dict) else None,
            "user_id": getattr(_, "user_id", None),
            "team_id": team.id,
        },
        stage="submitted",
        message="剧情片段拆分任务已提交",
        max_retries=1,
    )
    enqueue_task_job(job)
    return {"task_id": task_id, "status": "submitted"}


@router.get("/api/parse_story_segments_v3/{task_id}")
def get_parse_story_segments_v3_status(task_id: str):
    job = get_task_job(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到剧情片段拆分任务")
    return _serialize_v3_status(task_id, job)


@router.post("/api/parse_story_segments_v3/{task_id}/cancel")
def cancel_parse_story_segments_v3(
    task_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    job = get_task_job(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="未找到剧情片段拆分任务")
    if job.episode_id:
        require_episode_team_access(session, team, int(job.episode_id))

    cancelled = cancel_task_job(task_id)
    if not cancelled:
        raise HTTPException(status_code=404, detail="未找到剧情片段拆分任务")
    return serialize_task_job(cancelled)


@router.post("/api/episodes/{episode_id}/parse_story_segments_v3/commit")
def commit_parse_story_segments_v3(
    episode_id: str,
    payload: ParseScriptV2CommitRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_episode_id = decode_id(episode_id)
    episode = require_episode_team_access(session, team, real_episode_id)
    structured_draft = payload.structured_draft.model_dump()
    story_segments = structured_draft.get("story_segments") or []
    if not story_segments:
        raise HTTPException(status_code=400, detail="没有可提交的剧情片段")

    resource_sync_result = {
        "character_count": 0,
        "scene_count": 0,
        "prop_count": 0,
        "created_count": 0,
        "updated_count": 0,
    }
    if payload.sync_resources:
        resource_sync_result = sync_structured_assets_into_shared_resources(
            episode.script_id,
            {
                "characters": structured_draft.get("characters") or [],
                "scenes": structured_draft.get("scenes") or [],
                "props": structured_draft.get("props") or [],
            },
        )

    created_panels = commit_story_segments_with_cells(
        session,
        episode=episode,
        story_segments=story_segments,
        replace_existing=payload.replace_existing_panels,
    )
    grid_distribution: Dict[str, int] = {}
    total_duration = 0
    for panel in created_panels:
        grid_key = str(panel.grid_count or 1)
        grid_distribution[grid_key] = grid_distribution.get(grid_key, 0) + 1
        total_duration += int(panel.recommended_duration_seconds or 0)

    draft_mode: Optional[str] = structured_draft.get("storyboard_mode")
    if not draft_mode and story_segments:
        draft_mode = story_segments[0].get("storyboard_mode")

    return {
        "status": "success",
        "episode_id": encode_id(episode.id),
        "script_id": encode_id(episode.script_id),
        "segment_count": len(created_panels),
        "grid_distribution": grid_distribution,
        "average_duration_seconds": round(total_duration / len(created_panels), 2) if created_panels else 0,
        "storyboard_mode": normalize_storyboard_mode(draft_mode or episode.storyboard_mode),
        "redirect_target": "table",
        "segments": [
            {
                "id": encode_id(panel.id),
                "hash_id": encode_id(panel.id),
                "sequence_num": panel.sequence_num,
                "grid_count": panel.grid_count,
            }
            for panel in created_panels
        ],
        "resource_sync": resource_sync_result,
        "msg": f"剧情片段已提交，已创建 {len(created_panels)} 个片段。",
    }
