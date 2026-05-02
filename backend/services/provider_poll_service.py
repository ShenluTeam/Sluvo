from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List

from sqlmodel import Session, select

from core.config import settings
from database import engine
from models import TaskJob
from services.gen_model_registry import MODEL_REGISTRY
from services.gen_runtime_service import complete_generation_task, fail_generation_task, schedule_next_poll
from services.task_job_service import TASK_STATUS_WAITING_UPSTREAM
from services.upstream_media_service import complete_media_waiting_task, fail_media_waiting_task, query_media_waiting_task


PROVIDER_QUERY_LIMITS = {
    "runninghub-image": settings.RUNNINGHUB_IMAGE_QUERY_CONCURRENCY,
    "runninghub-video": settings.RUNNINGHUB_VIDEO_QUERY_CONCURRENCY,
    "suchuang-image": settings.SUCHUANG_QUERY_CONCURRENCY,
    "suchuang-video": settings.SUCHUANG_QUERY_CONCURRENCY,
    "minimax-audio": settings.MINIMAX_QUERY_CONCURRENCY,
    "grsai-image": settings.RUNNINGHUB_IMAGE_QUERY_CONCURRENCY,
}


def _now() -> datetime:
    return datetime.utcnow()


def _infer_provider_key(job: TaskJob) -> str:
    provider = str(job.provider or "")
    entry = MODEL_REGISTRY.get(provider)
    if entry:
        return str(entry.get("provider_key") or "")
    if provider == "runninghub-image":
        return "runninghub-image"
    if provider.startswith("runninghub-") or provider.startswith("runninghub:"):
        return "runninghub-video"
    return ""


def _load_due_poll_jobs(limit: int) -> List[TaskJob]:
    now = _now()
    with Session(engine) as session:
        waiting_jobs = session.exec(
            select(TaskJob)
            .where(TaskJob.status == TASK_STATUS_WAITING_UPSTREAM)
            .order_by(TaskJob.updated_at.asc(), TaskJob.id.asc())
            .limit(limit * 3)
        ).all()
        jobs = []
        for job in waiting_jobs:
            provider_key = _infer_provider_key(job)
            if not job.next_poll_at:
                if provider_key in {"runninghub-video", "runninghub-image"} and not job.callback_received_at:
                    jobs.append(job)
                continue
            if job.next_poll_at <= now:
                jobs.append(job)
            if len(jobs) >= limit:
                break
        return list(jobs)


async def _poll_one_job(job: TaskJob, semaphore: asyncio.Semaphore) -> None:
    async with semaphore:
        payload = {}
        try:
            import json
            payload = json.loads(job.payload_json or "{}")
        except Exception:
            payload = {}
        if job.task_type in {"media.generate_image", "media.generate_video", "audio.generate"}:
            try:
                result = query_media_waiting_task(job, payload)
            except Exception as exc:
                schedule_next_poll(job.task_id, current_attempts=int(job.poll_attempts or 0) + 1, message=f"轮询上游异常：{exc}")
                return
            if result.is_done:
                if result.is_failed:
                    fail_media_waiting_task(job, payload, result.error or "上游任务失败")
                else:
                    complete_media_waiting_task(job, payload, result)
                return
            schedule_next_poll(job.task_id, current_attempts=int(job.poll_attempts or 0) + 1)
            return
        entry = MODEL_REGISTRY.get(str(job.provider or ""))
        if not entry:
            fail_generation_task(job.task_id, error_message=f"unknown provider model: {job.provider}", error_code="provider_missing")
            return
        adapter = entry["adapter_cls"](**entry["adapter_kwargs"])
        try:
            result = await adapter.query(str(job.upstream_task_id or ""))
        except Exception as exc:
            schedule_next_poll(job.task_id, current_attempts=int(job.poll_attempts or 0) + 1, message=f"轮询上游异常：{exc}")
            return
        if result.is_done:
            if result.is_failed:
                fail_generation_task(job.task_id, error_message=result.error or "上游任务失败")
            else:
                complete_generation_task(
                    job.task_id,
                    provider=str(job.provider or ""),
                    result={"output_url": result.output_url, "raw_payload": result.raw_payload},
                )
            return
        schedule_next_poll(job.task_id, current_attempts=int(job.poll_attempts or 0) + 1)


async def run_poller_once() -> int:
    jobs = _load_due_poll_jobs(settings.POLLER_BATCH_LIMIT)
    if not jobs:
        return 0
    semaphores: Dict[str, asyncio.Semaphore] = {
        provider_key: asyncio.Semaphore(limit)
        for provider_key, limit in PROVIDER_QUERY_LIMITS.items()
    }
    tasks = []
    for job in jobs:
        provider_key = _infer_provider_key(job)
        semaphore = semaphores.get(provider_key, asyncio.Semaphore(5))
        tasks.append(asyncio.create_task(_poll_one_job(job, semaphore)))
    if tasks:
        await asyncio.gather(*tasks)
    return len(jobs)


async def run_poller_loop() -> None:
    while True:
        await run_poller_once()
        await asyncio.sleep(settings.POLLER_TICK_SECONDS)
