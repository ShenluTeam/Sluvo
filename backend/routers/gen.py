from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from database import get_session
from dependencies import get_current_user, get_current_team
from models import GenerationRecord, TaskJob, User, Team
from services.unified_generation_service import submit_generation

router = APIRouter()


class GenSubmitRequest(BaseModel):
    model_code: str
    prompt: str
    params: Dict[str, Any] = {}
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    script_id: Optional[int] = None
    episode_id: Optional[int] = None
    ownership_mode: str = "standalone"


@router.post("/api/gen/submit")
def gen_submit(
    req: GenSubmitRequest,
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    return submit_generation(
        user=user, team=team,
        model_code=req.model_code,
        prompt=req.prompt,
        params=req.params,
        target_type=req.target_type,
        target_id=req.target_id,
        script_id=req.script_id,
        episode_id=req.episode_id,
        ownership_mode=req.ownership_mode,
        session=session,
    )


@router.get("/api/gen/tasks")
def gen_list_tasks(
    page: int = 1,
    page_size: int = 20,
    record_type: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    query = select(GenerationRecord).where(GenerationRecord.user_id == user.id)
    if record_type:
        query = query.where(GenerationRecord.record_type == record_type)
    query = query.order_by(GenerationRecord.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    records = session.exec(query).all()
    return {"items": [_safe_record(r, session) for r in records], "page": page, "page_size": page_size}


@router.get("/api/gen/tasks/{task_id}")
def gen_get_task(
    task_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    record = session.exec(
        select(GenerationRecord).where(GenerationRecord.task_id == task_id, GenerationRecord.user_id == user.id)
    ).first()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Task not found")
    return _safe_record(record, session)


def _safe_record(record: GenerationRecord, session: Session) -> dict:
    progress = 0
    if record.task_id:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == record.task_id)).first()
        if job:
            progress = job.progress
    return {
        "task_id": record.task_id,
        "record_type": record.record_type,
        "status": record.status,
        "progress": progress,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "estimate_points": record.estimate_points,
        "actual_points": record.actual_points,
        "points_status": record.points_status,
        "preview_url": record.preview_url,
        "error_message_public": record.error_message_public,
    }
