from __future__ import annotations

import time

from sqlmodel import Session

from database import engine
from services.image_model_registry import normalize_image_request, query_image_generation, submit_image_generation
from services.resource_service import apply_generated_resource_image
from services.task_registry import resource_generate_tasks

USER_FACING_SUBMIT_ERROR = "生成服务暂时不可用，请稍后重试"
USER_FACING_FAILURE_MSG = "生成失败，请稍后重试"
USER_FACING_PROCESSING_MSG = "资产图片正在生成..."
USER_FACING_COMPLETED_MSG = "资产图片生成完成"
USER_FACING_TIMEOUT_ERROR = "生成服务响应超时，请稍后重试"


def dispatch_shared_resource_generation(
    *,
    task_id: str,
    resource_id: int,
    prompt: str,
    channel: str,
    resolution: str,
    quality: str | None = None,
    aspect_ratio: str,
    reference_images: list[str] | None = None,
    version_tag: str | None = None,
    start_seq: int | None = None,
    end_seq: int | None = None,
    is_default: bool = True,
) -> None:
    try:
        normalized = _normalize_shared_resource_request(
            prompt=prompt,
            model_code=channel,
            resolution=resolution,
            quality=quality,
            aspect_ratio=aspect_ratio,
            reference_images=reference_images,
        )
        result = submit_image_generation(normalized)
        if str(result.get("completion_mode") or "") == "immediate":
            version = _apply_generated_result(
                resource_id=resource_id,
                prompt=prompt,
                image_url=str(result.get("output_url") or ""),
                version_tag=version_tag,
                start_seq=start_seq,
                end_seq=end_seq,
                is_default=is_default,
            )
            resource_generate_tasks.update(
                task_id,
                status="completed",
                url=version.file_url,
                msg=USER_FACING_COMPLETED_MSG,
            )
            return

        provider = str(result.get("provider") or "").strip()
        vendor_task_id = str(result.get("upstream_task_id") or "").strip()
        if not provider or not vendor_task_id:
            raise RuntimeError(USER_FACING_SUBMIT_ERROR)

        resource_generate_tasks.update(
            task_id,
            status="processing",
            msg=USER_FACING_PROCESSING_MSG,
            vendor_task_id=vendor_task_id,
            provider=provider,
        )
        _poll_shared_resource_generation(
            task_id=task_id,
            resource_id=resource_id,
            provider=provider,
            vendor_task_id=vendor_task_id,
            prompt=prompt,
            version_tag=version_tag,
            start_seq=start_seq,
            end_seq=end_seq,
            is_default=is_default,
        )
    except Exception as exc:
        print(f"[asset-generate] dispatch failed: {exc!r}")
        resource_generate_tasks.update(
            task_id,
            status="failed",
            error=USER_FACING_SUBMIT_ERROR,
            msg=USER_FACING_FAILURE_MSG,
            last_error=str(exc),
        )


def run_shared_resource_generation(
    *,
    resource_id: int,
    prompt: str,
    channel: str,
    resolution: str,
    quality: str | None = None,
    aspect_ratio: str,
    reference_images: list[str] | None = None,
    version_tag: str | None = None,
    start_seq: int | None = None,
    end_seq: int | None = None,
    is_default: bool = True,
) -> dict:
    normalized = _normalize_shared_resource_request(
        prompt=prompt,
        model_code=channel,
        resolution=resolution,
        quality=quality,
        aspect_ratio=aspect_ratio,
        reference_images=reference_images,
    )
    result = submit_image_generation(normalized)
    if str(result.get("completion_mode") or "") == "immediate":
        version = _apply_generated_result(
            resource_id=resource_id,
            prompt=prompt,
            image_url=str(result.get("output_url") or ""),
            version_tag=version_tag,
            start_seq=start_seq,
            end_seq=end_seq,
            is_default=is_default,
        )
        return {
            "file_url": version.file_url,
            "version_id": version.id,
            "resource_id": resource_id,
        }

    provider = str(result.get("provider") or "").strip()
    vendor_task_id = str(result.get("upstream_task_id") or "").strip()
    if not provider or not vendor_task_id:
        raise RuntimeError(USER_FACING_SUBMIT_ERROR)
    return _poll_shared_resource_generation_sync(
        resource_id=resource_id,
        provider=provider,
        vendor_task_id=vendor_task_id,
        prompt=prompt,
        version_tag=version_tag,
        start_seq=start_seq,
        end_seq=end_seq,
        is_default=is_default,
    )


def _normalize_shared_resource_request(
    *,
    prompt: str,
    model_code: str,
    resolution: str,
    quality: str | None,
    aspect_ratio: str,
    reference_images: list[str] | None,
) -> dict:
    return normalize_image_request(
        {
            "model_code": model_code,
            "mode": "image_to_image" if reference_images else "text_to_image",
            "prompt": prompt,
            "resolution": resolution,
            "quality": quality,
            "aspect_ratio": aspect_ratio,
            "reference_images": [str(item).strip() for item in (reference_images or []) if str(item).strip()],
        }
    )


def _apply_generated_result(
    *,
    resource_id: int,
    prompt: str,
    image_url: str,
    version_tag: str | None,
    start_seq: int | None,
    end_seq: int | None,
    is_default: bool,
):
    if not image_url:
        raise RuntimeError("生成成功但未返回图片地址")
    with Session(engine) as session:
        return apply_generated_resource_image(
            session,
            resource_id=resource_id,
            prompt=prompt,
            file_url=image_url,
            version_tag=version_tag,
            start_seq=start_seq,
            end_seq=end_seq,
            is_default=is_default,
        )


def _poll_shared_resource_generation(
    *,
    task_id: str,
    resource_id: int,
    provider: str,
    vendor_task_id: str,
    prompt: str,
    version_tag: str | None,
    start_seq: int | None,
    end_seq: int | None,
    is_default: bool,
) -> None:
    for _ in range(200):
        time.sleep(3)
        try:
            result = query_image_generation(provider, vendor_task_id)
            if result.is_done and not result.is_failed and result.output_url:
                version = _apply_generated_result(
                    resource_id=resource_id,
                    prompt=prompt,
                    image_url=str(result.output_url or ""),
                    version_tag=version_tag,
                    start_seq=start_seq,
                    end_seq=end_seq,
                    is_default=is_default,
                )
                resource_generate_tasks.update(
                    task_id,
                    status="completed",
                    url=version.file_url,
                    msg=USER_FACING_COMPLETED_MSG,
                )
                return
            if result.is_done and result.is_failed:
                reason = result.error or "任务失败"
                print(f"[asset-generate] vendor task failed: {reason}")
                resource_generate_tasks.update(
                    task_id,
                    status="failed",
                    error=USER_FACING_SUBMIT_ERROR,
                    msg=USER_FACING_FAILURE_MSG,
                    last_error=reason,
                )
                return
        except Exception as exc:
            print(f"[asset-generate] poll transient error: {exc!r}")
            resource_generate_tasks.update(
                task_id,
                status="processing",
                msg=USER_FACING_PROCESSING_MSG,
                last_error=str(exc),
            )

    resource_generate_tasks.update(
        task_id,
        status="failed",
        error=USER_FACING_TIMEOUT_ERROR,
        msg=USER_FACING_FAILURE_MSG,
        last_error="vendor_poll_timeout",
    )


def _poll_shared_resource_generation_sync(
    *,
    resource_id: int,
    provider: str,
    vendor_task_id: str,
    prompt: str,
    version_tag: str | None,
    start_seq: int | None,
    end_seq: int | None,
    is_default: bool,
) -> dict:
    for _ in range(200):
        time.sleep(3)
        result = query_image_generation(provider, vendor_task_id)
        if result.is_done and not result.is_failed and result.output_url:
            version = _apply_generated_result(
                resource_id=resource_id,
                prompt=prompt,
                image_url=str(result.output_url or ""),
                version_tag=version_tag,
                start_seq=start_seq,
                end_seq=end_seq,
                is_default=is_default,
            )
            return {
                "file_url": version.file_url,
                "version_id": version.id,
                "resource_id": resource_id,
            }
        if result.is_done and result.is_failed:
            raise RuntimeError(result.error or USER_FACING_FAILURE_MSG)
    raise RuntimeError(USER_FACING_TIMEOUT_ERROR)
