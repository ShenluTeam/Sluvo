from __future__ import annotations

import time
from typing import Any, Dict, List

import requests
from sqlmodel import Session, select

from core.config import settings
from database import engine
from models import GenerationRecord, Panel, TaskStatusEnum, Team, User
from services.billing_service import refund_inspiration_points
from services.generation_record_service import _complete_record_success, _mark_failed
from services.provider_adapters import ProviderResult
from services.grsai_service import _mark_panel_failed
from services.runninghub_service import HEADERS as RUNNINGHUB_HEADERS
from services.runninghub_service import _mark_panel_success_and_oss
from services.panel_video_service import upsert_panel_video_history
from services.oss_service import build_oss_video_snapshot_url
from services.runninghub_video_service import runninghub_video_service
from services.suchuang_video_service import suchuang_video_service
from services.task_job_service import mark_task_job_failed, mark_task_job_succeeded, update_task_job
from services.image_model_registry import (
    normalize_image_request,
    query_image_generation as query_registry_image_generation,
    submit_image_generation as submit_registry_image_generation,
)


def _refund_failed_record(record_id: int) -> None:
    with Session(engine) as session:
        record = session.get(GenerationRecord, record_id)
        if not record or record.points_status != "deducted" or not record.estimate_points:
            return
        user = session.get(User, record.user_id)
        team = session.get(Team, record.team_id)
        if user and team:
            refund_inspiration_points(
                user,
                team,
                int(record.estimate_points or 0),
                "gen_refund",
                "生成失败退款",
                session,
            )
        record.points_status = "released"
        session.add(record)
        session.commit()


def _submit_runninghub_image(*, channel: str, prompt: str, resolution: str, aspect_ratio: str, image_urls: List[str]) -> str:
    from services.runninghub_service import RH_V2_CHANNEL_MAP

    url = RH_V2_CHANNEL_MAP.get(channel)
    if not url:
        raise RuntimeError(f"未知的 RunningHub 通道: {channel}")
    payload: Dict[str, Any] = {
        "prompt": prompt,
        "resolution": resolution or "1k",
    }
    if image_urls:
        payload["imageUrls"] = image_urls
    if aspect_ratio:
        payload["aspectRatio"] = aspect_ratio
    data = requests.post(url, json=payload, headers=RUNNINGHUB_HEADERS, timeout=30).json()
    task_id = data.get("taskId", "")
    if not task_id:
        raise RuntimeError(data.get("errorMessage", "") or data.get("message", "") or "RunningHub 未返回 taskId")
    return task_id


def _poll_runninghub_image(task_id: str) -> str:
    url = "https://www.runninghub.cn/openapi/v2/query"
    payload = {"taskId": task_id}
    for _ in range(200):
        time.sleep(3)
        data = requests.post(url, json=payload, headers=RUNNINGHUB_HEADERS, timeout=30).json()
        status = data.get("status", "")
        if status == "SUCCESS":
            results = data.get("results", [])
            image_url = results[0].get("url", "") if results else ""
            if not image_url:
                raise RuntimeError("RunningHub 成功但未返回图片地址")
            return image_url
        if status == "FAILED":
            raise RuntimeError(data.get("errorMessage", "") or data.get("failedReason", "") or "RunningHub 任务失败")
    raise RuntimeError("RunningHub 轮询超时")


def _submit_grsai_image(*, channel: str, prompt: str, resolution: str, aspect_ratio: str, image_urls: List[str]) -> str:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}
    payload = {
        "model": channel,
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "imageSize": str(resolution or "1k").upper(),
        "urls": image_urls,
        "webHook": "-1",
    }
    data = requests.post(settings.NANO_API_URL, headers=headers, json=payload, timeout=30).json()
    task_id = data.get("data", {}).get("id", "")
    if not task_id:
        raise RuntimeError(f"画布平台未返回任务 ID: {data}")
    return task_id


def _poll_grsai_image(task_id: str) -> str:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}
    for _ in range(200):
        time.sleep(3)
        data = requests.post(settings.NANO_RESULT_URL, json={"id": task_id}, headers=headers, timeout=30).json()
        result_data = data.get("data", data)
        status = result_data.get("status", "")
        if status == "succeeded":
            results = result_data.get("results", [])
            image_url = results[0]["url"] if results else ""
            if not image_url:
                raise RuntimeError("画布平台成功但未返回图片地址")
            return image_url
        if status in {"failed", "error"}:
            raise RuntimeError(result_data.get("error", "") or result_data.get("message", "") or "画布平台任务失败")
    raise RuntimeError("画布平台轮询超时")


def _submit_suchuang_image(*, channel: str, prompt: str, resolution: str, aspect_ratio: str, image_urls: List[str]) -> str:
    if channel == "suchuang-nanobanana2":
        url = f"https://api.wuyinkeji.com/api/async/image_nanoBanana2?key={settings.SUCHUANG_KEY}"
    else:
        url = f"https://api.wuyinkeji.com/api/async/image_nanoBanana_pro?key={settings.SUCHUANG_KEY}"
    payload: Dict[str, Any] = {"prompt": prompt}
    if resolution:
        payload["size"] = str(resolution).upper()
    if aspect_ratio:
        payload["aspectRatio"] = aspect_ratio
    for index, image_url in enumerate(image_urls[:14]):
        payload[f"urls[{index}]"] = image_url
    data = requests.post(url, data=payload, timeout=30).json()
    if data.get("code") != 200:
        raise RuntimeError(data.get("msg", "") or "速创提交失败")
    response_data = data.get("data", {})
    task_id = response_data.get("id", "") if isinstance(response_data, dict) else str(response_data)
    if not task_id:
        raise RuntimeError(f"速创未返回任务 ID: {data}")
    return task_id


def _poll_suchuang_image(task_id: str) -> str:
    url = f"https://api.wuyinkeji.com/api/async/detail?key={settings.SUCHUANG_KEY}&id={task_id}"
    for _ in range(200):
        time.sleep(3)
        data = requests.get(url, timeout=30).json().get("data", {})
        if not isinstance(data, dict):
            continue
        status = data.get("status", 0)
        if status == 2:
            result = data.get("result", [])
            image_url = result[0] if result and isinstance(result, list) else ""
            if not image_url:
                raise RuntimeError("速创成功但未返回图片地址")
            return str(image_url)
        if status == 3:
            raise RuntimeError(data.get("message", "") or "速创任务失败")
    raise RuntimeError("速创轮询超时")


def _query_runninghub_image_once(task_id: str) -> ProviderResult:
    url = "https://www.runninghub.cn/openapi/v2/query"
    payload = {"taskId": task_id}
    data = requests.post(url, json=payload, headers=RUNNINGHUB_HEADERS, timeout=30).json()
    status = data.get("status", "")
    if status == "SUCCESS":
        results = data.get("results", [])
        image_url = results[0].get("url", "") if results else ""
        return ProviderResult(is_done=True, is_failed=False, output_url=image_url or None, raw_payload=data)
    if status == "FAILED":
        return ProviderResult(is_done=True, is_failed=True, error=data.get("errorMessage") or data.get("failedReason"), raw_payload=data)
    return ProviderResult(is_done=False, is_failed=False, raw_payload=data)


def _query_grsai_image_once(task_id: str) -> ProviderResult:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}
    data = requests.post(settings.NANO_RESULT_URL, json={"id": task_id}, headers=headers, timeout=30).json()
    result_data = data.get("data", data)
    status = result_data.get("status", "")
    if status == "succeeded":
        results = result_data.get("results", [])
        image_url = results[0]["url"] if results else ""
        return ProviderResult(is_done=True, is_failed=False, output_url=image_url or None, raw_payload=data)
    if status in {"failed", "error"}:
        return ProviderResult(is_done=True, is_failed=True, error=result_data.get("error") or result_data.get("message"), raw_payload=data)
    return ProviderResult(is_done=False, is_failed=False, raw_payload=data)


def _query_suchuang_image_once(task_id: str) -> ProviderResult:
    url = f"https://api.wuyinkeji.com/api/async/detail?key={settings.SUCHUANG_KEY}&id={task_id}"
    data = requests.get(url, timeout=30).json().get("data", {})
    if not isinstance(data, dict):
        return ProviderResult(is_done=False, is_failed=False, raw_payload={"data": data})
    status = data.get("status", 0)
    if status == 2:
        result = data.get("result", [])
        image_url = result[0] if result and isinstance(result, list) else ""
        return ProviderResult(is_done=True, is_failed=False, output_url=str(image_url or "") or None, raw_payload={"data": data})
    if status == 3:
        return ProviderResult(is_done=True, is_failed=True, error=data.get("message"), raw_payload={"data": data})
    return ProviderResult(is_done=False, is_failed=False, raw_payload={"data": data})


def submit_legacy_image_generation(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = normalize_image_request(
        {
            "model_code": payload.get("model_code") or payload.get("channel"),
            "mode": payload.get("mode"),
            "prompt": payload.get("prompt"),
            "resolution": payload.get("resolution"),
            "quality": payload.get("quality"),
            "aspect_ratio": payload.get("aspect_ratio"),
            "reference_images": payload.get("image_urls") or payload.get("reference_images") or [],
        }
    )
    return submit_registry_image_generation(normalized)


def query_legacy_image_generation(provider: str, upstream_task_id: str) -> ProviderResult:
    return query_registry_image_generation(provider, upstream_task_id)


def run_legacy_image_generation_task(task_id: str, payload: Dict[str, Any]) -> None:
    record_id = int(payload["record_id"])
    panel_id = int(payload["panel_id"])
    try:
        update_task_job(task_id, status="running", stage="submitting", progress=15, message="图片任务已开始提交")
        result = submit_legacy_image_generation(payload)
        if str(result.get("completion_mode") or "") == "immediate":
            image_url = str(result.get("output_url") or "").strip()
        else:
            provider = str(result.get("provider") or "")
            upstream_task_id = str(result.get("upstream_task_id") or "")
            update_task_job(task_id, stage="polling", progress=40, message="正在轮询图片结果")
            query = query_legacy_image_generation(provider, upstream_task_id)
            while not query.is_done:
                time.sleep(3)
                query = query_legacy_image_generation(provider, upstream_task_id)
            if query.is_failed:
                raise RuntimeError(query.error or "图片生成失败")
            image_url = str(query.output_url or "").strip()
        _mark_panel_success_and_oss(panel_id, task_id, image_url)
        _complete_record_success(record_id, preview_url=image_url)
        mark_task_job_succeeded(task_id, result={"preview_url": image_url}, message="图片生成完成")
    except Exception as exc:
        _mark_panel_failed(panel_id, task_id, str(exc))
        _refund_failed_record(record_id)
        _mark_failed(record_id, error_code="legacy_image_failed", message="图片生成失败，请稍后重试", internal_message=str(exc))
        mark_task_job_failed(
            task_id,
            error_code="legacy_image_failed",
            error_message=str(exc),
            message="图片生成失败",
            retryable=False,
        )


def _store_panel_video_success(panel_id: int, task_id: str, video_url: str) -> str:
    thumbnail_url = build_oss_video_snapshot_url(video_url)
    with Session(engine) as session:
        panel = session.get(Panel, panel_id)
        if not panel:
            raise RuntimeError("Panel not found")
        previous_video_url = str(panel.video_url or "").strip()
        panel.video_history_json = upsert_panel_video_history(
            panel.video_history_json,
            preview_url=video_url,
            thumbnail_url=thumbnail_url,
            replace_url=previous_video_url,
        )
        panel.video_url = video_url
        panel.video_thumbnail_url = thumbnail_url or None
        panel.status = TaskStatusEnum.COMPLETED
        session.add(panel)
        session.commit()
    return thumbnail_url or ""


def _query_suchuang_video_once(task_id: str) -> ProviderResult:
    query = suchuang_video_service.query_task(task_id)
    if hasattr(query, "__await__"):
        import asyncio
        query = asyncio.run(query)
    code = query.get("code")
    data = query.get("data", {})
    status = data.get("status")
    if code == 200 and status == 2:
        video_url = data.get("url") or data.get("videoUrl")
        return ProviderResult(is_done=True, is_failed=False, output_url=str(video_url or "") or None, raw_payload=query)
    if status == 3:
        return ProviderResult(is_done=True, is_failed=True, error=data.get("message"), raw_payload=query)
    return ProviderResult(is_done=False, is_failed=False, raw_payload=query)


def _query_runninghub_video_once(task_id: str) -> ProviderResult:
    query = runninghub_video_service.query_task(task_id)
    if hasattr(query, "__await__"):
        import asyncio
        query = asyncio.run(query)
    status = query.get("status")
    if status == "SUCCESS":
        results = query.get("results", [])
        video_url = results[0]["url"] if results else ""
        return ProviderResult(is_done=True, is_failed=False, output_url=video_url or None, raw_payload=query)
    if status == "FAILED":
        return ProviderResult(is_done=True, is_failed=True, error=query.get("errorMessage") or query.get("failedReason"), raw_payload=query)
    return ProviderResult(is_done=False, is_failed=False, raw_payload=query)


def submit_legacy_video_generation(payload: Dict[str, Any], *, webhook_url: str | None = None) -> Dict[str, Any]:
    channel_id = str(payload["channel_id"] or "")
    prompt = str(payload["prompt"] or "")
    duration = int(payload.get("duration") or 5)
    resolution = str(payload.get("resolution") or "720p")
    audio = bool(payload.get("audio"))
    aspect_ratio = str(payload.get("aspect_ratio") or "16:9")
    movement_amplitude = str(payload.get("movement_amplitude") or "auto")
    image_refs = [str(item).strip() for item in (payload.get("reference_images") or []) if str(item).strip()]
    video_refs = [str(item).strip() for item in (payload.get("reference_videos") or []) if str(item).strip()]
    first_frame = str(payload.get("start_frame") or payload.get("image_url") or "")
    audio_url = str(payload.get("audio_url") or "")
    if channel_id == "suchuang-veo3.1-pro":
        resp = suchuang_video_service.generate_veo3_1_pro(
            prompt=prompt,
            first_frame_url=first_frame,
            last_frame_url=str(payload.get("end_frame") or ""),
            size=resolution,
        )
        if hasattr(resp, "__await__"):
            import asyncio
            resp = asyncio.run(resp)
        return {"provider": "suchuang-video", "upstream_task_id": str(resp["data"]["id"]), "completion_mode": "poll"}
    if channel_id == "runninghub-vidu-q3-pro":
        resp = runninghub_video_service.generate_vidu_q3_pro(
            prompt=prompt,
            image_urls=image_refs,
            duration=str(duration),
            resolution=resolution,
            audio=audio,
            webhook_url=webhook_url,
        )
    else:
        resp = runninghub_video_service.generate_vidu_q2_pro(
            prompt=prompt,
            image_urls=image_refs or ([first_frame] if first_frame else []),
            video_urls=video_refs,
            duration=str(duration),
            resolution=resolution,
            bgm=audio,
            aspect_ratio=aspect_ratio,
            movement_amplitude=movement_amplitude,
            webhook_url=webhook_url,
        )
    if hasattr(resp, "__await__"):
        import asyncio
        resp = asyncio.run(resp)
    task_id = resp.get("taskId")
    if not task_id:
        raise RuntimeError("视频平台未返回任务 ID")
    return {"provider": "runninghub-video", "upstream_task_id": str(task_id), "completion_mode": "webhook" if webhook_url else "poll"}


def query_legacy_video_generation(provider: str, upstream_task_id: str) -> ProviderResult:
    if provider == "suchuang-video":
        return _query_suchuang_video_once(upstream_task_id)
    if provider == "runninghub-video":
        return _query_runninghub_video_once(upstream_task_id)
    return ProviderResult(is_done=True, is_failed=True, error=f"unknown legacy video provider: {provider}")


def complete_legacy_image_generation(task_id: str, payload: Dict[str, Any], preview_url: str) -> None:
    record_id = int(payload["record_id"])
    panel_id = int(payload["panel_id"])
    _mark_panel_success_and_oss(panel_id, task_id, preview_url)
    _complete_record_success(record_id, preview_url=preview_url)
    mark_task_job_succeeded(task_id, result={"preview_url": preview_url}, message="图片生成完成")


def fail_legacy_image_generation(task_id: str, payload: Dict[str, Any], error_message: str) -> None:
    record_id = int(payload["record_id"])
    panel_id = int(payload["panel_id"])
    _mark_panel_failed(panel_id, task_id, error_message)
    _refund_failed_record(record_id)
    _mark_failed(record_id, error_code="legacy_image_failed", message="图片生成失败，请稍后重试", internal_message=error_message)
    mark_task_job_failed(task_id, error_code="legacy_image_failed", error_message=error_message, message="图片生成失败", retryable=False)


def complete_legacy_video_generation(task_id: str, payload: Dict[str, Any], preview_url: str) -> None:
    record_id = int(payload["record_id"])
    panel_id = int(payload["panel_id"])
    thumbnail_url = _store_panel_video_success(panel_id, task_id, preview_url)
    _complete_record_success(record_id, preview_url=preview_url, thumbnail_url=thumbnail_url)
    mark_task_job_succeeded(task_id, result={"preview_url": preview_url, "thumbnail_url": thumbnail_url}, message="视频生成完成")


def fail_legacy_video_generation(task_id: str, payload: Dict[str, Any], error_message: str) -> None:
    record_id = int(payload["record_id"])
    panel_id = int(payload["panel_id"])
    with Session(engine) as session:
        panel = session.get(Panel, panel_id)
        if panel:
            panel.status = TaskStatusEnum.FAILED
            session.add(panel)
            session.commit()
    _refund_failed_record(record_id)
    _mark_failed(record_id, error_code="legacy_video_failed", message="视频生成失败，请稍后重试", internal_message=error_message)
    mark_task_job_failed(task_id, error_code="legacy_video_failed", error_message=error_message, message="视频生成失败", retryable=False)


def run_legacy_video_generation_task(task_id: str, payload: Dict[str, Any]) -> None:
    record_id = int(payload["record_id"])
    panel_id = int(payload["panel_id"])
    channel_id = str(payload["channel_id"] or "")
    prompt = str(payload["prompt"] or "")
    duration = int(payload.get("duration") or 5)
    resolution = str(payload.get("resolution") or "720p")
    audio = bool(payload.get("audio"))
    aspect_ratio = str(payload.get("aspect_ratio") or "16:9")
    movement_amplitude = str(payload.get("movement_amplitude") or "auto")
    image_refs = [str(item).strip() for item in (payload.get("reference_images") or []) if str(item).strip()]
    video_refs = [str(item).strip() for item in (payload.get("reference_videos") or []) if str(item).strip()]
    first_frame = str(payload.get("start_frame") or payload.get("image_url") or "")
    audio_url = str(payload.get("audio_url") or "")
    try:
        update_task_job(task_id, status="running", stage="submitting", progress=15, message="视频任务已开始提交")
        if channel_id == "suchuang-veo3.1-pro":
            resp = suchuang_video_service.generate_veo3_1_pro(
                prompt=prompt,
                first_frame_url=first_frame,
                last_frame_url=str(payload.get("end_frame") or ""),
                size=resolution,
            )
            if hasattr(resp, "__await__"):
                import asyncio
                resp = asyncio.run(resp)
            backend_task_id = resp["data"]["id"]
            update_task_job(task_id, stage="polling", progress=45, message="正在轮询速创视频结果")
            while True:
                time.sleep(8)
                query = suchuang_video_service.query_task(backend_task_id)
                if hasattr(query, "__await__"):
                    import asyncio
                    query = asyncio.run(query)
                code = query.get("code")
                data = query.get("data", {})
                status = data.get("status")
                if code == 200 and status == 2:
                    video_url = data.get("url") or data.get("videoUrl")
                    if not video_url:
                        raise RuntimeError("速创成功但未返回视频地址")
                    thumbnail_url = _store_panel_video_success(panel_id, task_id, video_url)
                    _complete_record_success(record_id, preview_url=video_url, thumbnail_url=thumbnail_url)
                    mark_task_job_succeeded(task_id, result={"preview_url": video_url, "thumbnail_url": thumbnail_url}, message="视频生成完成")
                    return
                if status == 3:
                    raise RuntimeError(data.get("message") or "速创视频任务失败")
        else:
            if channel_id == "runninghub-vidu-q3-pro":
                resp = runninghub_video_service.generate_vidu_q3_pro(
                    prompt=prompt,
                    image_urls=image_refs,
                    duration=str(duration),
                    resolution=resolution,
                    audio=audio,
                )
            else:
                resp = runninghub_video_service.generate_vidu_q2_pro(
                    prompt=prompt,
                    image_urls=image_refs or ([first_frame] if first_frame else []),
                    video_urls=video_refs,
                    duration=str(duration),
                    resolution=resolution,
                    bgm=audio,
                    aspect_ratio=aspect_ratio,
                    movement_amplitude=movement_amplitude,
                )
            if hasattr(resp, "__await__"):
                import asyncio
                resp = asyncio.run(resp)
            backend_task_id = resp.get("taskId")
            if not backend_task_id:
                raise RuntimeError("视频平台未返回任务 ID")
            update_task_job(task_id, stage="polling", progress=45, message="正在轮询视频平台结果")
            while True:
                time.sleep(8)
                query = runninghub_video_service.query_task(backend_task_id)
                if hasattr(query, "__await__"):
                    import asyncio
                    query = asyncio.run(query)
                status = query.get("status")
                if status == "SUCCESS":
                    results = query.get("results", [])
                    video_url = results[0]["url"] if results else ""
                    if not video_url:
                        raise RuntimeError("视频平台成功但未返回视频地址")
                    thumbnail_url = _store_panel_video_success(panel_id, task_id, video_url)
                    _complete_record_success(record_id, preview_url=video_url, thumbnail_url=thumbnail_url)
                    mark_task_job_succeeded(task_id, result={"preview_url": video_url, "thumbnail_url": thumbnail_url}, message="视频生成完成")
                    return
                if status == "FAILED":
                    raise RuntimeError(query.get("errorMessage") or query.get("failedReason") or "视频平台任务失败")
    except Exception as exc:
        with Session(engine) as session:
            panel = session.get(Panel, panel_id)
            if panel:
                panel.status = TaskStatusEnum.FAILED
                session.add(panel)
                session.commit()
        _refund_failed_record(record_id)
        _mark_failed(record_id, error_code="legacy_video_failed", message="视频生成失败，请稍后重试", internal_message=str(exc))
        mark_task_job_failed(
            task_id,
            error_code="legacy_video_failed",
            error_message=str(exc),
            message="视频生成失败",
            retryable=False,
        )
