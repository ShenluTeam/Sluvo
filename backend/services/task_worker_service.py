from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from typing import Any, Callable, Dict, Iterable, Optional

import redis.asyncio as aioredis

from services.generation_record_service import (
    _run_asset_generation_job,
    _run_audio_generation_job,
    _run_image_generation_job,
    _run_video_generation_job,
)
from services.gen_runtime_service import build_callback_token, build_callback_url, mark_task_waiting_upstream
from services.legacy_media_task_service import run_legacy_image_generation_task, run_legacy_video_generation_task
from services.resource_task_service import run_resource_extract_task
from services.resource_task_service import run_resource_reference_image_task
from services.storyboard_task_service import run_parse_story_segments_v3_task
from services.upstream_media_service import submit_media_task
from services.task_job_service import (
    TASK_STATUS_CANCELLED,
    claim_next_task_job,
    enqueue_due_retry_tasks,
    get_redis_client,
    get_task_job,
    heartbeat_task_job,
    mark_task_job_failed,
    mark_task_job_running,
    mark_task_job_succeeded,
    requeue_orphaned_jobs,
    update_task_job,
    _queue_key,
)
from core.config import settings

TaskHandler = Callable[[str, Dict[str, Any]], None]
logger = logging.getLogger(__name__)


def _run_generation_handler(task_id: str, payload: Dict[str, Any], runner: Callable[[int], None]) -> None:
    record_id = int(payload["record_id"])
    runner(record_id)
    job = get_task_job(task_id)
    if not job:
        return
    if job.status in {"failed", "cancelled", "timed_out"}:
        return
    mark_task_job_succeeded(task_id, result={"generation_record_id": job.generation_record_id}, message=job.message or "任务完成")


def _run_resource_generate_image(task_id: str, payload: Dict[str, Any]) -> None:
    if payload.get("kind") == "resource_reference_image":
        run_resource_reference_image_task(task_id, payload)
        return
    _run_generation_handler(task_id, payload, _run_asset_generation_job)


def _run_media_generate_image(task_id: str, payload: Dict[str, Any]) -> None:
    submit_media_task(task_id, payload, "media.generate_image")


def _run_media_generate_video(task_id: str, payload: Dict[str, Any]) -> None:
    submit_media_task(task_id, payload, "media.generate_video")


def _run_gen_task(task_id: str, payload: dict) -> None:
    import asyncio
    from services.gen_model_registry import MODEL_REGISTRY
    from services.task_job_service import mark_task_job_failed

    record_id = int(payload["record_id"])
    model_code = payload["model_code"]
    prompt = payload.get("prompt", "")
    params = payload.get("params", {})

    entry = MODEL_REGISTRY.get(model_code)
    if not entry:
        mark_task_job_failed(task_id, error_code="unknown_model", error_message=f"Unknown model_code: {model_code}", message="未知模型", retryable=False)
        return

    adapter = entry["adapter_cls"](**entry["adapter_kwargs"])
    completion_mode = str(entry.get("completion_mode") or "poll")
    provider_key = str(entry.get("provider_key") or model_code)

    async def _submit():
        submit_payload = adapter.build_submit_payload({"prompt": prompt, **params})
        callback_token = None
        if completion_mode == "webhook" and adapter.supports_webhook():
            callback_token = build_callback_token()
            submit_payload["webhook_url"] = build_callback_url(provider_key=provider_key, callback_token=callback_token)
        upstream_id = await adapter.submit(submit_payload)
        return upstream_id, callback_token

    try:
        upstream_id, callback_token = asyncio.run(_submit())
    except Exception as exc:
        _refund_gen_record(record_id, task_id)
        mark_task_job_failed(task_id, error_code="gen_error", error_message=str(exc), message="生成失败", retryable=False)
        return

    mark_task_waiting_upstream(
        task_id,
        upstream_task_id=str(upstream_id),
        callback_token=callback_token,
        use_poller=completion_mode != "webhook",
        message="任务已提交上游，等待结果中",
    )


def _refund_gen_record(record_id: int, task_id: str) -> None:
    from database import engine
    from sqlmodel import Session
    from models import GenerationRecord, User, Team
    from services.billing_service import refund_inspiration_points
    try:
        with Session(engine) as session:
            record = session.get(GenerationRecord, record_id)
            if not record or record.points_status != "deducted":
                return
            user = session.get(User, record.user_id)
            team = session.get(Team, record.team_id)
            if user and team and record.estimate_points:
                refund_inspiration_points(user, team, record.estimate_points, "gen_refund", "生成失败退款", session)
            record.status = "failed"
            record.points_status = "released"
            session.add(record)
            session.commit()
    except Exception:
        pass


TASK_HANDLERS: Dict[str, TaskHandler] = {
    "storyboard.parse_v3": run_parse_story_segments_v3_task,
    "resource.extract": run_resource_extract_task,
    "resource.generate_image": _run_resource_generate_image,
    "media.generate_image": _run_media_generate_image,
    "media.generate_video": _run_media_generate_video,
    "audio.generate": lambda task_id, payload: submit_media_task(task_id, payload, "audio.generate"),
    "gen.image": _run_gen_task,
    "gen.video": _run_gen_task,
    "gen.audio": _run_gen_task,
}


def _heartbeat_loop(task_id: str, worker_id: str, stop_event: threading.Event) -> None:
    while not stop_event.wait(settings.TASK_QUEUE_HEARTBEAT_SECONDS):
        heartbeat_task_job(task_id, worker_id=worker_id)


def _process_task(queue_name: str, *, worker_id: str) -> None:
    job = claim_next_task_job(queue_name, worker_id=worker_id)
    if not job:
        return
    task_id = job.task_id
    if job.status == TASK_STATUS_CANCELLED:
        return
    handler = TASK_HANDLERS.get(job.task_type)
    if not handler:
        mark_task_job_failed(
            task_id,
            error_code="task_handler_missing",
            error_message=f"未找到任务处理器: {job.task_type}",
            message="任务处理器不存在",
            retryable=False,
        )
        return
    mark_task_job_running(task_id, stage=job.stage or "running", message=job.message or "任务执行中")
    stop_event = threading.Event()
    heartbeat_thread = threading.Thread(target=_heartbeat_loop, args=(task_id, worker_id, stop_event), daemon=True)
    heartbeat_thread.start()
    try:
        handler(task_id, job.payload_json and json.loads(job.payload_json) or {})
    except Exception as exc:
        logger.exception("worker task failed: task_id=%s task_type=%s queue=%s", task_id, job.task_type, queue_name)
        mark_task_job_failed(
            task_id,
            error_code="task_execution_failed",
            error_message=str(exc),
            message="任务执行失败",
            retryable=False,
        )
    finally:
        stop_event.set()
        heartbeat_thread.join(timeout=1)


_SEMAPHORE: Optional[asyncio.Semaphore] = None


async def _run_task_async(task_id: str, queue_name: str, worker_id: str) -> None:
    assert _SEMAPHORE is not None
    async with _SEMAPHORE:
        update_task_job(task_id, message="任务已被 worker 接收")
        await asyncio.to_thread(_process_task, queue_name, worker_id=worker_id)


async def _dequeue_loop(redis_async: aioredis.Redis, queue_keys: list, worker_id: str) -> None:
    while True:
        item = await redis_async.brpop(queue_keys, timeout=settings.TASK_QUEUE_REDIS_BLOCK_SECONDS)
        if not item:
            continue
        queue_key, task_id = item
        queue_name = str(queue_key).split(":")[-1]
        asyncio.create_task(_run_task_async(task_id, queue_name, worker_id))


async def _maintenance_loop() -> None:
    while True:
        await asyncio.sleep(settings.TASK_QUEUE_HEARTBEAT_SECONDS)
        await asyncio.to_thread(requeue_orphaned_jobs, limit=settings.TASK_QUEUE_SCAN_LIMIT)
        await asyncio.to_thread(enqueue_due_retry_tasks, limit=settings.TASK_QUEUE_SCAN_LIMIT)


async def run_worker_async(*, queues: Iterable[str], worker_id: str) -> None:
    global _SEMAPHORE
    queue_names = [str(item).strip() for item in queues if str(item).strip()]
    if not queue_names:
        raise ValueError("queues cannot be empty")
    _SEMAPHORE = asyncio.Semaphore(settings.TASK_QUEUE_SUBMIT_MAX_CONCURRENCY)
    queue_keys = [_queue_key(name) for name in queue_names]
    redis_async = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    import logging
    logging.getLogger(__name__).info("async worker started, queues=%s", queue_names)
    async with redis_async:
        await asyncio.gather(
            _dequeue_loop(redis_async, queue_keys, worker_id),
            _maintenance_loop(),
        )


def run_worker(*, queues: Iterable[str], worker_id: str) -> None:
    queue_names = [str(item).strip() for item in queues if str(item).strip()]
    if not queue_names:
        raise ValueError("queues cannot be empty")
    queue_keys = [_queue_key(name) for name in queue_names]
    client = get_redis_client()
    last_recover_at = 0.0
    while True:
        now = time.time()
        if now - last_recover_at >= settings.TASK_QUEUE_HEARTBEAT_SECONDS:
            requeue_orphaned_jobs(limit=settings.TASK_QUEUE_SCAN_LIMIT)
            enqueue_due_retry_tasks(limit=settings.TASK_QUEUE_SCAN_LIMIT)
            last_recover_at = now
        item = client.brpop(queue_keys, timeout=settings.TASK_QUEUE_REDIS_BLOCK_SECONDS)
        if not item:
            continue
        queue_key, task_id = item
        queue_name = str(queue_key).split(":")[-1]
        update_task_job(task_id, message="任务已被 worker 接收")
        _process_task(queue_name, worker_id=worker_id)
