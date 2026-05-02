from __future__ import annotations

from typing import Any, Dict

from models import TaskJob
from services.gen_runtime_service import build_callback_token, build_callback_url, mark_task_waiting_upstream
from services.generation_record_service import (
    complete_generation_record_from_upstream,
    complete_generation_record_from_upstream_deferred,
    fail_generation_record_from_upstream,
    query_audio_generation_upstream,
    query_image_generation_upstream,
    query_video_generation_upstream,
    submit_audio_generation_upstream,
    submit_image_generation_upstream,
    submit_video_generation_upstream,
)
from services.legacy_media_task_service import (
    complete_legacy_image_generation,
    complete_legacy_video_generation,
    fail_legacy_image_generation,
    fail_legacy_video_generation,
    query_legacy_image_generation,
    query_legacy_video_generation,
    submit_legacy_image_generation,
    submit_legacy_video_generation,
)
from services.provider_adapters import ProviderResult
from services.task_job_service import mark_task_job_failed, mark_task_job_succeeded, update_task_job


def submit_media_task(task_id: str, job_payload: Dict[str, Any], task_type: str) -> None:
    if task_type == "media.generate_image":
        if job_payload.get("kind") == "legacy_image_v2":
            result = submit_legacy_image_generation(job_payload)
            if result.get("completion_mode") == "immediate":
                complete_legacy_image_generation(task_id, job_payload, str(result.get("output_url") or ""))
                return
            update_task_job(task_id, provider=str(result.get("provider") or ""))
            mark_task_waiting_upstream(
                task_id,
                upstream_task_id=str(result["upstream_task_id"]),
                use_poller=True,
                message="图片任务已提交上游，等待结果中",
            )
            return
        callback_token = build_callback_token()
        webhook_url = build_callback_url(provider_key="runninghub-image", callback_token=callback_token)
        result = submit_image_generation_upstream(int(job_payload["record_id"]), webhook_url=webhook_url)
        if result.get("completion_mode") == "immediate":
            preview_url = str(result.get("output_url") or "")
            complete_generation_record_from_upstream_deferred(int(job_payload["record_id"]), preview_url=preview_url)
            mark_task_job_succeeded(task_id, result={"preview_url": preview_url}, message="图片生成完成")
            return
        update_task_job(task_id, provider=str(result.get("provider") or ""))
        mark_task_waiting_upstream(
            task_id,
            upstream_task_id=str(result["upstream_task_id"]),
            callback_token=callback_token if result.get("completion_mode") == "webhook" else None,
            use_poller=result.get("completion_mode") != "webhook",
            message="图片任务已提交上游，等待结果中",
        )
        return

    if task_type == "media.generate_video":
        if job_payload.get("kind") == "legacy_video":
            callback_token = None
            webhook_url = None
            if str(job_payload.get("channel_id") or "").startswith("runninghub-"):
                callback_token = build_callback_token()
                webhook_url = build_callback_url(provider_key="runninghub-video", callback_token=callback_token)
            result = submit_legacy_video_generation(job_payload, webhook_url=webhook_url)
            update_task_job(task_id, provider=str(result.get("provider") or ""))
            mark_task_waiting_upstream(
                task_id,
                upstream_task_id=str(result["upstream_task_id"]),
                callback_token=callback_token,
                use_poller=result.get("completion_mode") != "webhook",
                message="视频任务已提交上游，等待结果中",
            )
            return
        result = submit_video_generation_upstream(int(job_payload["record_id"]))
        mark_task_waiting_upstream(
            task_id,
            upstream_task_id=str(result["upstream_task_id"]),
            use_poller=True,
            message="视频任务已提交上游，等待结果中",
        )
        return

    if task_type == "audio.generate":
        result = submit_audio_generation_upstream(int(job_payload["record_id"]))
        if result.get("completion_mode") == "immediate":
            return
        mark_task_waiting_upstream(
            task_id,
            upstream_task_id=str(result["upstream_task_id"]),
            use_poller=True,
            message="配音任务已提交上游，等待结果中",
        )
        return

    raise RuntimeError(f"unsupported media task_type: {task_type}")


def query_media_waiting_task(job: TaskJob, payload: Dict[str, Any]) -> ProviderResult:
    if job.task_type == "media.generate_image":
        if payload.get("kind") == "legacy_image_v2":
            return query_legacy_image_generation(str(job.provider or ""), str(job.upstream_task_id or ""))
        return query_image_generation_upstream(str(job.provider or ""), str(job.upstream_task_id or ""))
    if job.task_type == "media.generate_video":
        if payload.get("kind") == "legacy_video":
            return query_legacy_video_generation(str(job.provider or ""), str(job.upstream_task_id or ""))
        return query_video_generation_upstream(str(job.provider or ""), str(job.upstream_task_id or ""))
    if job.task_type == "audio.generate":
        return query_audio_generation_upstream(str(job.provider or ""), str(job.upstream_task_id or ""))
    raise RuntimeError(f"unsupported task_type for poll: {job.task_type}")


def complete_media_waiting_task(job: TaskJob, payload: Dict[str, Any], result: ProviderResult) -> None:
    preview_url = str(result.output_url or "").strip()
    if job.task_type == "media.generate_image":
        if payload.get("kind") == "legacy_image_v2":
            complete_legacy_image_generation(job.task_id, payload, preview_url)
            return
        complete_generation_record_from_upstream_deferred(int(payload["record_id"]), preview_url=preview_url)
        mark_task_job_succeeded(job.task_id, result={"preview_url": preview_url}, message="图片生成完成")
        return
    if job.task_type == "media.generate_video":
        if payload.get("kind") == "legacy_video":
            complete_legacy_video_generation(job.task_id, payload, preview_url)
            return
        complete_generation_record_from_upstream(int(payload["record_id"]), preview_url=preview_url)
        mark_task_job_succeeded(job.task_id, result={"preview_url": preview_url}, message="视频生成完成")
        return
    if job.task_type == "audio.generate":
        complete_generation_record_from_upstream(int(payload["record_id"]), preview_url=preview_url, thumbnail_url="")
        mark_task_job_succeeded(job.task_id, result={"preview_url": preview_url}, message="配音生成完成")
        return
    raise RuntimeError(f"unsupported task_type for complete: {job.task_type}")


def fail_media_waiting_task(job: TaskJob, payload: Dict[str, Any], error_message: str) -> None:
    if job.task_type == "media.generate_image":
        if payload.get("kind") == "legacy_image_v2":
            fail_legacy_image_generation(job.task_id, payload, error_message)
            return
        fail_generation_record_from_upstream(
            int(payload["record_id"]),
            error_code="generation_failed",
            message="图片生成失败，请稍后重试",
            internal_message=error_message,
        )
        mark_task_job_failed(
            job.task_id,
            error_code="generation_failed",
            error_message=error_message,
            message="图片生成失败",
            retryable=False,
        )
        return
    if job.task_type == "media.generate_video":
        if payload.get("kind") == "legacy_video":
            fail_legacy_video_generation(job.task_id, payload, error_message)
            return
        fail_generation_record_from_upstream(
            int(payload["record_id"]),
            error_code="generation_failed",
            message="视频生成失败，请稍后重试",
            internal_message=error_message,
        )
        mark_task_job_failed(
            job.task_id,
            error_code="generation_failed",
            error_message=error_message,
            message="视频生成失败",
            retryable=False,
        )
        return
    if job.task_type == "audio.generate":
        fail_generation_record_from_upstream(
            int(payload["record_id"]),
            error_code="generation_failed",
            message="配音生成失败，请稍后重试",
            internal_message=error_message,
        )
        mark_task_job_failed(
            job.task_id,
            error_code="generation_failed",
            error_message=error_message,
            message="配音生成失败",
            retryable=False,
        )
        return
    raise RuntimeError(f"unsupported task_type for fail: {job.task_type}")
