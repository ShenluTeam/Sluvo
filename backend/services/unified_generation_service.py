from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlmodel import Session

from models import GenerationRecord, User, Team
from services.billing_service import deduct_inspiration_points
from services.task_job_service import create_task_job, enqueue_task_job
from services.gen_model_registry import MODEL_REGISTRY


def submit_generation(
    *,
    user: User,
    team: Team,
    model_code: str,
    prompt: str,
    params: Dict[str, Any],
    target_type: Optional[str] = None,
    target_id: Optional[int] = None,
    script_id: Optional[int] = None,
    episode_id: Optional[int] = None,
    ownership_mode: str = "standalone",
    session: Session,
) -> Dict[str, Any]:
    entry = MODEL_REGISTRY.get(model_code)
    if not entry:
        raise HTTPException(status_code=400, detail=f"Unknown model_code: {model_code}")

    estimate_points: int = entry["estimate_fn"](params)
    task_type: str = entry["task_type"]
    record_type = task_type.split(".")[-1]  # "image" / "video" / "audio"

    deduct_inspiration_points(
        user, team, estimate_points,
        action_type=f"gen_{record_type}",
        description=f"{model_code} generation",
        session=session,
    )

    task_id = str(uuid.uuid4())
    record = GenerationRecord(
        user_id=user.id,
        team_id=team.id,
        record_type=record_type,
        ownership_mode=ownership_mode,
        script_id=script_id,
        episode_id=episode_id,
        target_type=target_type,
        target_id=target_id,
        task_id=task_id,
        status="queued",
        prompt=prompt,
        params_internal_json="{}",
        params_public_json="{}",
        estimate_points=estimate_points,
        points_status="deducted",
    )
    session.add(record)
    session.flush()  # get record.id

    job = create_task_job(
        session,
        task_id=task_id,
        task_type=entry["task_type"],
        queue_name=entry["queue"],
        task_category=entry["task_category"],
        provider=model_code,
        user_id=user.id,
        team_id=team.id,
        script_id=script_id,
        episode_id=episode_id,
        ownership_mode=ownership_mode,
        scope_type=target_type,
        scope_id=target_id,
        generation_record_id=record.id,
        payload={"record_id": record.id, "model_code": model_code, "prompt": prompt, "params": params},
    )
    session.commit()
    enqueue_task_job(job)

    return {"task_id": task_id, "estimate_points": estimate_points, "status": "queued"}
