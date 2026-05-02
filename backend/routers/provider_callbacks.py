from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlmodel import Session, select

from database import engine
from models import TaskJob
from services.gen_model_registry import MODEL_REGISTRY
from services.gen_runtime_service import complete_generation_task, fail_generation_task, mark_callback_received
from services.upstream_media_service import complete_media_waiting_task, fail_media_waiting_task
import json

router = APIRouter()


def _infer_provider_key(job: TaskJob) -> str:
    entry = MODEL_REGISTRY.get(str(job.provider or ""))
    if entry:
        return str(entry.get("provider_key") or "")
    provider = str(job.provider or "")
    if provider == "runninghub-image":
        return "runninghub-image"
    if provider.startswith("runninghub-") or provider.startswith("runninghub:"):
        return "runninghub-video"
    return ""


def _load_callback_job(session: Session, *, token: str, provider_key: str) -> TaskJob:
    job = session.exec(select(TaskJob).where(TaskJob.callback_token == token)).first()
    if not job:
        raise HTTPException(status_code=404, detail="callback task not found")
    if _infer_provider_key(job) != provider_key:
        raise HTTPException(status_code=400, detail="callback provider mismatch")
    return job


@router.post("/api/provider-callbacks/runninghub/video")
@router.post("/api/provider-callbacks/runninghub-video")
async def runninghub_video_callback(
    request: Request,
    token: str = Query(...),
):
    body = await request.json()
    with Session(engine) as session:
        job = _load_callback_job(session, token=token, provider_key="runninghub-video")
        adapter_entry = MODEL_REGISTRY.get(str(job.provider or ""))
        if adapter_entry:
            adapter = adapter_entry["adapter_cls"](**adapter_entry["adapter_kwargs"])
        else:
            from services.provider_adapters.runninghub_video import RunningHubVideoAdapter
            adapter = RunningHubVideoAdapter(model="vidu_q2_pro")
        result = adapter.parse_callback(body, dict(request.headers))
        mark_callback_received(job.task_id)
        if result.is_done:
            if result.is_failed:
                if job.task_type == "media.generate_video":
                    payload = json.loads(job.payload_json or "{}")
                    fail_media_waiting_task(job, payload, result.error or "runninghub callback failed")
                else:
                    fail_generation_task(job.task_id, error_message=result.error or "runninghub callback failed")
            else:
                if job.task_type == "media.generate_video":
                    payload = json.loads(job.payload_json or "{}")
                    complete_media_waiting_task(job, payload, result)
                else:
                    complete_generation_task(
                        job.task_id,
                        provider=str(job.provider or ""),
                        result={"output_url": result.output_url, "raw_payload": result.raw_payload},
                    )
    return {"success": True}


@router.post("/api/provider-callbacks/runninghub/image")
@router.post("/api/provider-callbacks/runninghub-image")
async def runninghub_image_callback(
    request: Request,
    token: str = Query(...),
):
    body = await request.json()
    with Session(engine) as session:
        job = _load_callback_job(session, token=token, provider_key="runninghub-image")
        from services.provider_adapters.runninghub_image import RunningHubImageAdapter
        adapter = RunningHubImageAdapter()
        result = adapter.parse_callback(body, dict(request.headers))
        mark_callback_received(job.task_id)
        if result.is_done:
            if result.is_failed:
                if job.task_type == "media.generate_image":
                    payload = json.loads(job.payload_json or "{}")
                    fail_media_waiting_task(job, payload, result.error or "runninghub image callback failed")
                else:
                    fail_generation_task(job.task_id, error_message=result.error or "runninghub image callback failed")
            else:
                if job.task_type == "media.generate_image":
                    payload = json.loads(job.payload_json or "{}")
                    complete_media_waiting_task(job, payload, result)
                else:
                    complete_generation_task(
                        job.task_id,
                        provider=str(job.provider or ""),
                        result={"output_url": result.output_url, "raw_payload": result.raw_payload},
                    )
    return {"success": True}
