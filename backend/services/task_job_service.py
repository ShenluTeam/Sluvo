from __future__ import annotations

import json
import socket
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import func
from sqlmodel import Session, select

from core.config import settings
from database import engine
from models import TaskJob
from services.membership_service import resolve_task_membership_policy

TASK_STATUS_QUEUED = "queued"
TASK_STATUS_LEASED = "leased"
TASK_STATUS_RUNNING = "running"
TASK_STATUS_WAITING_UPSTREAM = "waiting_upstream"
TASK_STATUS_RETRY_WAITING = "retry_waiting"
TASK_STATUS_SUCCEEDED = "succeeded"
TASK_STATUS_FAILED = "failed"
TASK_STATUS_CANCELLED = "cancelled"
TASK_STATUS_TIMED_OUT = "timed_out"

ACTIVE_TASK_STATUSES = {
    TASK_STATUS_QUEUED,
    TASK_STATUS_LEASED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_WAITING_UPSTREAM,
    TASK_STATUS_RETRY_WAITING,
}
TERMINAL_TASK_STATUSES = {
    TASK_STATUS_SUCCEEDED,
    TASK_STATUS_FAILED,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_TIMED_OUT,
}


def _now() -> datetime:
    return datetime.utcnow()


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def billing_rule_for_task_type(task_type: Optional[str]) -> str:
    normalized = str(task_type or "").strip()
    if normalized == "storyboard.parse_v3":
        return "if actual_cost_cny > 0 then ceil(actual_cost_cny / 0.1) + 1 else 0"
    if normalized == "resource.extract":
        return "if actual_cost_cny > 0 then ceil(actual_cost_cny / 0.1) else 0"
    return ""


def _queue_key(queue_name: str) -> str:
    return f"{settings.TASK_QUEUE_NAMESPACE}:task_queue:{queue_name}"


def _retry_key() -> str:
    return f"{settings.TASK_QUEUE_NAMESPACE}:task_retry_schedule"


def get_redis_client():
    from redis import Redis
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def build_worker_id(worker_name: str) -> str:
    return f"{worker_name}@{socket.gethostname()}"


def create_task_job(
    session: Session,
    *,
    task_id: str,
    task_type: str,
    queue_name: str,
    priority: int = 100,
    provider: Optional[str] = None,
    team_id: Optional[int] = None,
    user_id: Optional[int] = None,
    script_id: Optional[int] = None,
    episode_id: Optional[int] = None,
    ownership_mode: Optional[str] = None,
    scope_type: Optional[str] = None,
    scope_id: Optional[int] = None,
    task_category: Optional[str] = None,
    generation_record_id: Optional[int] = None,
    payload: Optional[Dict[str, Any]] = None,
    result: Optional[Dict[str, Any]] = None,
    progress: int = 0,
    stage: Optional[str] = None,
    message: Optional[str] = None,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
    retry_count: int = 0,
    max_retries: int = 0,
    scheduled_at: Optional[datetime] = None,
    actual_cost_cny: float = 0.0,
    charged_points: int = 0,
    actual_points: int = 0,
    points_status: str = "free",
    billing_detail: Optional[List[Dict[str, Any]]] = None,
) -> TaskJob:
    now = _now()
    resolved_payload = dict(payload or {})
    effective_priority = priority
    membership_source = None
    membership_plan_id = None
    membership_plan_name = None
    membership_subject_type = None
    membership_subject_id = None
    concurrency_limit = None
    if task_category and user_id:
        policy = resolve_task_membership_policy(
            session,
            user_id=user_id,
            team_id=team_id,
            task_category=task_category,
            ownership_mode=ownership_mode,
        )
        effective_priority = int(policy["effective_priority"])
        membership_source = policy["membership_source"]
        membership_plan_id = policy["membership_plan_id"]
        membership_plan_name = policy["membership_plan_name"]
        membership_subject_type = policy["membership_subject_type"]
        membership_subject_id = policy["membership_subject_id"]
        concurrency_limit = policy["limits"].get(task_category)
        resolved_payload["membership_policy"] = policy
    job = TaskJob(
        task_id=task_id,
        task_type=task_type,
        queue_name=queue_name,
        status=TASK_STATUS_QUEUED,
        priority=effective_priority,
        provider=provider,
        team_id=team_id,
        user_id=user_id,
        script_id=script_id,
        episode_id=episode_id,
        ownership_mode=ownership_mode,
        scope_type=scope_type,
        scope_id=scope_id,
        task_category=task_category,
        membership_source=membership_source,
        membership_plan_id=membership_plan_id,
        membership_plan_name=membership_plan_name,
        membership_subject_type=membership_subject_type,
        membership_subject_id=membership_subject_id,
        concurrency_limit=concurrency_limit,
        actual_cost_cny=actual_cost_cny,
        charged_points=charged_points,
        actual_points=actual_points,
        points_status=points_status,
        billing_detail_json=_json_dumps(billing_detail or []),
        generation_record_id=generation_record_id,
        payload_json=_json_dumps(resolved_payload),
        result_json=_json_dumps(result or {}),
        progress=progress,
        stage=stage,
        message=message,
        error_code=error_code,
        error_message=error_message,
        retry_count=retry_count,
        max_retries=max_retries,
        scheduled_at=scheduled_at or now,
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def enqueue_task_id(task_id: str, *, queue_name: str, delay_seconds: Optional[int] = None) -> bool:
    try:
        client = get_redis_client()
        if delay_seconds and delay_seconds > 0:
            client.zadd(_retry_key(), {task_id: _now().timestamp() + delay_seconds})
        else:
            client.lpush(_queue_key(queue_name), task_id)
        return True
    except Exception:
        return False


def enqueue_task_job(job: TaskJob, *, delay_seconds: Optional[int] = None) -> bool:
    return enqueue_task_id(job.task_id, queue_name=job.queue_name, delay_seconds=delay_seconds)


def enqueue_due_retry_tasks(*, limit: Optional[int] = None) -> int:
    moved = 0
    limit = limit or settings.TASK_QUEUE_SCAN_LIMIT
    try:
        client = get_redis_client()
        now_ts = _now().timestamp()
        task_ids = client.zrangebyscore(_retry_key(), min=0, max=now_ts, start=0, num=limit)
        if not task_ids:
            return 0
        with Session(engine) as session:
            for task_id in task_ids:
                job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
                if not job:
                    client.zrem(_retry_key(), task_id)
                    continue
                client.zrem(_retry_key(), task_id)
                client.lpush(_queue_key(job.queue_name), task_id)
                moved += 1
    except Exception:
        return moved
    return moved


def requeue_orphaned_jobs(*, limit: Optional[int] = None) -> int:
    limit = limit or settings.TASK_QUEUE_SCAN_LIMIT
    now = _now()
    touched = 0
    with Session(engine) as session:
        queued_jobs = session.exec(
            select(TaskJob)
            .where(TaskJob.status.in_([TASK_STATUS_QUEUED, TASK_STATUS_RETRY_WAITING]))
            .order_by(TaskJob.updated_at.asc())
            .limit(limit)
        ).all()
        for job in queued_jobs:
            enqueue_task_job(job)
            touched += 1

        expired_jobs = session.exec(
            select(TaskJob)
            .where(TaskJob.status.in_([TASK_STATUS_LEASED, TASK_STATUS_RUNNING]))
            .where(TaskJob.lease_expires_at != None)
            .where(TaskJob.lease_expires_at < now)
            .limit(limit)
        ).all()
        for job in expired_jobs:
            if job.retry_count < job.max_retries:
                job.status = TASK_STATUS_RETRY_WAITING
                job.retry_count += 1
                job.message = job.message or "任务租约过期，正在重试"
                job.error_code = "worker_lease_expired"
                job.error_message = "任务租约过期，已重新排队"
                job.lease_expires_at = None
                job.worker_id = None
                job.updated_at = now
                session.add(job)
                enqueue_task_job(job, delay_seconds=settings.TASK_QUEUE_RETRY_DELAY_SECONDS)
            else:
                job.status = TASK_STATUS_TIMED_OUT
                job.finished_at = now
                job.error_code = "worker_lease_expired"
                job.error_message = "任务租约过期，且已超过重试次数"
                job.lease_expires_at = None
                job.worker_id = None
                job.updated_at = now
                session.add(job)
            touched += 1
        session.commit()
    return touched


def get_task_job(task_id: str, session: Optional[Session] = None) -> Optional[TaskJob]:
    owns_session = session is None
    session = session or Session(engine)
    try:
        return session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
    finally:
        if owns_session:
            session.close()


def claim_task_job(task_id: str, *, worker_id: str) -> Optional[TaskJob]:
    now = _now()
    with Session(engine) as session:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
        if not job:
            return None
        if job.cancel_requested_at and job.status not in TERMINAL_TASK_STATUSES:
            job.status = TASK_STATUS_CANCELLED
            job.finished_at = now
            job.updated_at = now
            session.add(job)
            session.commit()
            session.refresh(job)
            return job
        if job.status not in {TASK_STATUS_QUEUED, TASK_STATUS_RETRY_WAITING}:
            return None
        job.status = TASK_STATUS_LEASED
        job.worker_id = worker_id
        job.started_at = job.started_at or now
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=settings.TASK_QUEUE_LEASE_SECONDS)
        job.updated_at = now
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def _has_concurrency_capacity(session: Session, job: TaskJob) -> bool:
    if not job.membership_subject_type or not job.membership_subject_id or not job.task_category:
        return True
    if job.concurrency_limit is None:
        return True
    if int(job.concurrency_limit) <= 0:
        return False
    active_count = session.exec(
        select(func.count(TaskJob.id)).where(
            TaskJob.membership_subject_type == job.membership_subject_type,
            TaskJob.membership_subject_id == job.membership_subject_id,
            TaskJob.task_category == job.task_category,
            TaskJob.status.in_([TASK_STATUS_LEASED, TASK_STATUS_RUNNING, TASK_STATUS_WAITING_UPSTREAM]),
            TaskJob.id != job.id,
        )
    ).one()
    return int(active_count or 0) < int(job.concurrency_limit)


def claim_next_task_job(queue_name: str, *, worker_id: str, scan_limit: Optional[int] = None) -> Optional[TaskJob]:
    scan_limit = scan_limit or settings.TASK_QUEUE_SCAN_LIMIT
    now = _now()
    with Session(engine) as session:
        candidates = session.exec(
            select(TaskJob)
            .where(TaskJob.queue_name == queue_name)
            .where(TaskJob.status.in_([TASK_STATUS_QUEUED, TASK_STATUS_RETRY_WAITING]))
            .order_by(TaskJob.priority.asc(), TaskJob.created_at.asc(), TaskJob.id.asc())
            .limit(scan_limit)
        ).all()
        for job in candidates:
            if job.cancel_requested_at and job.status not in TERMINAL_TASK_STATUSES:
                job.status = TASK_STATUS_CANCELLED
                job.finished_at = now
                job.updated_at = now
                session.add(job)
                session.commit()
                continue
            if not _has_concurrency_capacity(session, job):
                continue
            job.status = TASK_STATUS_LEASED
            job.worker_id = worker_id
            job.started_at = job.started_at or now
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=settings.TASK_QUEUE_LEASE_SECONDS)
            job.updated_at = now
            session.add(job)
            session.commit()
            session.refresh(job)
            return job
    return None


def mark_task_job_running(task_id: str, *, stage: Optional[str] = None, message: Optional[str] = None) -> Optional[TaskJob]:
    with Session(engine) as session:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
        if not job:
            return None
        now = _now()
        job.status = TASK_STATUS_RUNNING
        job.stage = stage or job.stage
        job.message = message or job.message
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=settings.TASK_QUEUE_LEASE_SECONDS)
        job.updated_at = now
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def heartbeat_task_job(task_id: str, *, worker_id: Optional[str] = None) -> None:
    with Session(engine) as session:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
        if not job or job.status not in {TASK_STATUS_LEASED, TASK_STATUS_RUNNING}:
            return
        if worker_id and job.worker_id and job.worker_id != worker_id:
            return
        now = _now()
        job.heartbeat_at = now
        job.lease_expires_at = now + timedelta(seconds=settings.TASK_QUEUE_LEASE_SECONDS)
        job.updated_at = now
        session.add(job)
        session.commit()


def update_task_job(task_id: str, **payload: Any) -> Optional[TaskJob]:
    with Session(engine) as session:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
        if not job:
            return None
        now = _now()
        for key, value in payload.items():
            if key == "payload":
                job.payload_json = _json_dumps(value or {})
            elif key == "result":
                job.result_json = _json_dumps(value or {})
            elif key == "billing_detail":
                job.billing_detail_json = _json_dumps(value or [])
            else:
                setattr(job, key, value)
        job.updated_at = now
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def mark_task_job_succeeded(task_id: str, *, result: Optional[Dict[str, Any]] = None, message: Optional[str] = None) -> Optional[TaskJob]:
    now = _now()
    return update_task_job(
        task_id,
        status=TASK_STATUS_SUCCEEDED,
        stage="completed",
        result=result or {},
        progress=100,
        message=message,
        finished_at=now,
        lease_expires_at=None,
        heartbeat_at=now,
    )


def mark_task_job_failed(
    task_id: str,
    *,
    error_code: str,
    error_message: str,
    message: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    retryable: bool = False,
) -> Optional[TaskJob]:
    with Session(engine) as session:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
        if not job:
            return None
        now = _now()
        if retryable and job.retry_count < job.max_retries:
            job.status = TASK_STATUS_RETRY_WAITING
            job.retry_count += 1
            job.error_code = error_code
            job.error_message = error_message
            job.message = message or error_message
            job.result_json = _json_dumps(result or {})
            job.lease_expires_at = None
            job.heartbeat_at = now
            job.updated_at = now
            session.add(job)
            session.commit()
            session.refresh(job)
            enqueue_task_job(job, delay_seconds=settings.TASK_QUEUE_RETRY_DELAY_SECONDS)
            return job
        job.status = TASK_STATUS_FAILED
        job.error_code = error_code
        job.error_message = error_message
        job.message = message or error_message
        job.result_json = _json_dumps(result or {})
        job.finished_at = now
        job.lease_expires_at = None
        job.heartbeat_at = now
        job.updated_at = now
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def cancel_task_job(task_id: str) -> Optional[TaskJob]:
    with Session(engine) as session:
        job = session.exec(select(TaskJob).where(TaskJob.task_id == task_id)).first()
        if not job:
            return None
        now = _now()
        if job.status in TERMINAL_TASK_STATUSES:
            return job
        job.cancel_requested_at = now
        job.updated_at = now
        if job.status in {TASK_STATUS_QUEUED, TASK_STATUS_RETRY_WAITING}:
            job.status = TASK_STATUS_CANCELLED
            job.finished_at = now
            job.message = job.message or "任务已取消"
        session.add(job)
        session.commit()
        session.refresh(job)
        return job


def is_task_cancel_requested(task_id: str) -> bool:
    job = get_task_job(task_id)
    return bool(job and job.cancel_requested_at)


def task_status_for_legacy(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized in {TASK_STATUS_QUEUED, TASK_STATUS_LEASED, TASK_STATUS_RUNNING, TASK_STATUS_RETRY_WAITING}:
        return "processing"
    if normalized == TASK_STATUS_WAITING_UPSTREAM:
        return "processing"
    if normalized == TASK_STATUS_SUCCEEDED:
        return "completed"
    if normalized == TASK_STATUS_FAILED:
        return "failed"
    if normalized == TASK_STATUS_CANCELLED:
        return "cancelled"
    if normalized == TASK_STATUS_TIMED_OUT:
        return "failed"
    return normalized or "unknown"


def serialize_task_job(job: TaskJob) -> Dict[str, Any]:
    payload = _json_loads(job.payload_json, {})
    result = _json_loads(job.result_json, {})
    billing_detail = _json_loads(job.billing_detail_json, [])
    billing = {
        "charged_points": int(job.charged_points or 0),
        "actual_points": int(job.actual_points or 0),
        "actual_cost_cny": float(job.actual_cost_cny or 0.0),
        "points_status": str(job.points_status or "free"),
        "billing_rule": billing_rule_for_task_type(job.task_type),
        "billing_detail": billing_detail if isinstance(billing_detail, list) else [],
    }
    return {
        "task_id": job.task_id,
        "task_type": job.task_type,
        "queue_name": job.queue_name,
        "status": job.status,
        "legacy_status": task_status_for_legacy(job.status),
        "progress": job.progress,
        "stage": job.stage,
        "message": job.message,
        "provider": job.provider,
        "priority": job.priority,
        "task_category": job.task_category,
        "ownership_mode": job.ownership_mode,
        "scope_type": job.scope_type,
        "scope_id": job.scope_id,
        "script_id": job.script_id,
        "episode_id": job.episode_id,
        "membership_source": job.membership_source,
        "membership_plan_id": job.membership_plan_id,
        "membership_plan_name": job.membership_plan_name,
        "membership_subject_type": job.membership_subject_type,
        "membership_subject_id": job.membership_subject_id,
        "concurrency_limit": job.concurrency_limit,
        "actual_cost_cny": float(job.actual_cost_cny or 0.0),
        "charged_points": int(job.charged_points or 0),
        "actual_points": int(job.actual_points or 0),
        "points_status": str(job.points_status or "free"),
        "billing": billing,
        "upstream_task_id": job.upstream_task_id,
        "callback_token": job.callback_token,
        "next_poll_at": job.next_poll_at.isoformat() if job.next_poll_at else None,
        "poll_attempts": job.poll_attempts,
        "callback_received_at": job.callback_received_at.isoformat() if job.callback_received_at else None,
        "generation_record_id": job.generation_record_id,
        "result": result,
        "error": {
            "code": job.error_code,
            "message": job.error_message,
        } if job.error_code or job.error_message else None,
        "payload": payload,
        "cancel_requested": bool(job.cancel_requested_at),
        "retry_count": job.retry_count,
        "max_retries": job.max_retries,
        "worker_id": job.worker_id,
        "scheduled_at": job.scheduled_at.isoformat() if job.scheduled_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "heartbeat_at": job.heartbeat_at.isoformat() if job.heartbeat_at else None,
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def list_task_jobs(*, scope_type: Optional[str] = None, scope_id: Optional[int] = None, limit: int = 50) -> List[TaskJob]:
    with Session(engine) as session:
        statement = select(TaskJob).order_by(TaskJob.updated_at.desc(), TaskJob.id.desc()).limit(limit)
        if scope_type:
            statement = statement.where(TaskJob.scope_type == scope_type)
        if scope_id is not None:
            statement = statement.where(TaskJob.scope_id == scope_id)
        return list(session.exec(statement).all())
