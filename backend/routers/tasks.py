from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from dependencies import get_current_team, require_team_permission
from models import GenerationRecord, TaskJob, Team, TeamMemberLink
from services.task_job_service import cancel_task_job, list_task_jobs, serialize_task_job

router = APIRouter()


def _load_scoped_task_or_404(session: Session, *, team: Team, task_id: str) -> TaskJob:
    job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
    if not job or (job.team_id and int(job.team_id) != int(team.id)):
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.get("/api/tasks/{task_id}")
def get_task_detail(
    task_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    job = _load_scoped_task_or_404(session, team=team, task_id=task_id)
    payload = serialize_task_job(job)
    if job.generation_record_id:
        record = session.get(GenerationRecord, job.generation_record_id)
        if record:
            payload["record"] = {
                "record_id": record.id,
                "record_type": record.record_type,
                "status": record.status,
                "preview_url": record.preview_url,
                "thumbnail_url": record.thumbnail_url,
            }
    return payload


@router.get("/api/tasks")
def get_task_list(
    scope_type: str = "",
    scope_id: int | None = None,
    limit: int = 50,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    jobs = [item for item in list_task_jobs(scope_type=scope_type or None, scope_id=scope_id, limit=limit) if not item.team_id or int(item.team_id) == int(team.id)]
    return {"tasks": [serialize_task_job(item) for item in jobs]}


@router.post("/api/tasks/{task_id}/cancel")
def post_task_cancel(
    task_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    _load_scoped_task_or_404(session, team=team, task_id=task_id)
    job = cancel_task_job(task_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return serialize_task_job(job)
