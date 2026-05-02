from __future__ import annotations

import asyncio
import uuid
from typing import List, Optional

import json
from urllib.parse import quote

import requests

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from core.config import settings
from core.security import decode_id, encode_id
from database import engine, get_session, session_scope
from dependencies import get_current_team, get_current_user, require_team_permission
from models import Team, TeamMemberLink, User
from schemas import (
    ExtractScriptAssetsRequest,
    GenerateSharedResourceImageRequest,
    SharedResourceCreate,
    SharedResourceVersionCreateRequest,
    SharedResourceVersionUpdateRequest,
)
from services.access_service import require_episode_team_access, require_script_team_access
from services.generation_record_service import _create_generation_record, _ensure_affordable
from services.image_model_registry import estimate_image_price, normalize_image_request
from services.workflow_preset_service import (
    build_style_prompt,
    get_style_display_label,
    resolve_asset_extraction_storyboard_mode,
    resolve_effective_workflow_profile,
)
from services.resource_service import (
    create_resource as create_resource_service,
    create_uploaded_resource_version as create_uploaded_resource_version_service,
    create_resource_version as create_resource_version_service,
    delete_resource_version as delete_resource_version_service,
    delete_resource as delete_resource_service,
    list_resource_versions as list_resource_versions_service,
    list_resources as list_resources_service,
    serialize_resource as serialize_resource_service,
    upload_shared_resource_file as upload_shared_resource_file_service,
    update_resource as update_resource_service,
    update_resource_version as update_resource_version_service,
)
from services.task_job_service import create_task_job, enqueue_task_job, get_task_job, serialize_task_job
from services.task_registry import resource_extract_tasks, resource_generate_tasks
from services.access_service import require_resource_team_access

router = APIRouter()


def _serialize_resource(resource):
    return {**serialize_resource_service(resource), "id": encode_id(resource.id)}


def _resolve_stream_user(session: Session, token: Optional[str], authorization: Optional[str]) -> User:
    auth_token = token
    if not auth_token and authorization:
        auth_token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    if not auth_token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")

    user = session.exec(select(User).where(User.session_token == auth_token)).first()
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def _serialize_asset_extract_task(task_id: str, session: Optional[Session] = None) -> Optional[dict]:
    job = get_task_job(task_id, session=session)
    if not job:
        task = resource_extract_tasks.get(task_id)
        if not task:
            return None
        return {
            "task_id": task_id,
            "status": task.get("status"),
            "msg": task.get("msg"),
            "progress": int(task.get("progress") or 0),
            "stage": task.get("stage"),
            "character_count": int(task.get("character_count") or task.get("result", {}).get("character_count") or 0),
            "scene_count": int(task.get("scene_count") or task.get("result", {}).get("scene_count") or 0),
            "prop_count": int(task.get("prop_count") or task.get("result", {}).get("prop_count") or 0),
            "created_count": int(task.get("created_count") or task.get("result", {}).get("created_count") or 0),
            "updated_count": int(task.get("updated_count") or task.get("result", {}).get("updated_count") or 0),
            "billing": task.get("billing"),
            "asset_quality_warnings": task.get("asset_quality_warnings") or task.get("result", {}).get("asset_quality_warnings") or [],
        }

    data = serialize_task_job(job)
    result = data.get("result") or {}
    return {
        "task_id": task_id,
        "status": data.get("legacy_status"),
        "msg": data.get("message"),
        "progress": int(data.get("progress") or 0),
        "stage": data.get("stage"),
        "character_count": int(result.get("character_count") or 0),
        "scene_count": int(result.get("scene_count") or 0),
        "prop_count": int(result.get("prop_count") or 0),
        "created_count": int(result.get("created_count") or 0),
        "updated_count": int(result.get("updated_count") or 0),
        "billing": data.get("billing"),
        "asset_quality_warnings": result.get("asset_quality_warnings") or [],
    }


def _parse_aliases_form(raw: Optional[str]) -> Optional[List[str]]:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return [item.strip() for item in text.split(",") if item.strip()] or None


def _build_download_filename(name: str | None, original_filename: str | None, content_type: str | None) -> str:
    base = str(original_filename or name or "asset").strip() or "asset"
    if "." in base:
        return base
    normalized_type = str(content_type or "").lower()
    if "png" in normalized_type:
        return f"{base}.png"
    if "webp" in normalized_type:
        return f"{base}.webp"
    if "jpeg" in normalized_type or "jpg" in normalized_type:
        return f"{base}.jpg"
    return f"{base}.bin"


def _do_extract_script_assets(
    task_id: str,
    script_id: int,
    source_text: str,
    api_key: str,
    style_prompt: str = "",
    style_label: str = "",
):
    try:
        resource_extract_tasks.update(task_id, status="processing", msg="AI 正在提取角色、场景、道具资产...")
        result = extract_script_assets_into_shared_resources(
            script_id,
            source_text,
            api_key,
            style_prompt=style_prompt,
            style_label=style_label,
        )
        resource_extract_tasks.update(
            task_id,
            status="completed",
            msg=(
                f"提取完成：角色 {result['character_count']}，场景 {result['scene_count']}，道具 {result['prop_count']}；"
                f"新增 {result['created_count']}，更新 {result['updated_count']}"
            ),
            **result,
        )
    except Exception as exc:
        resource_extract_tasks.update(task_id, status="failed", msg=f"提取失败: {exc}")


@router.post("/api/resources")
async def create_resource(
    resource_in: SharedResourceCreate,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    try:
        real_script_id = decode_id(resource_in.script_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid script ID format")
    resource = create_resource_service(
        session,
        team,
        script_id=real_script_id,
        resource_type=resource_in.resource_type,
        name=resource_in.name,
        file_url=resource_in.file_url,
        trigger_word=resource_in.trigger_word,
        aliases=resource_in.aliases,
        description=resource_in.description,
        owner_user_id=int(user.id),
    )
    return _serialize_resource(resource)


@router.get("/api/scripts/{script_id}/resources")
async def get_script_resources(
    script_id: str,
    resource_type: Optional[str] = None,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    try:
        real_script_id = decode_id(script_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid script ID format")
    resources = list_resources_service(session, team, real_script_id, resource_type)
    return [_serialize_resource(resource) for resource in resources]


@router.get("/api/scripts/{script_id}/shared_resources")
async def get_script_shared_resources(
    script_id: str,
    type: Optional[str] = None,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    try:
        real_script_id = decode_id(script_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid script ID format")

    resource_type = None
    if type:
        type_map = {
            "character": "character",
            "scene": "scene",
            "prop": "prop",
        }
        resource_type = type_map.get(type)
    resources = list_resources_service(session, team, real_script_id, resource_type)
    return [_serialize_resource(resource) for resource in resources]


@router.delete("/api/resources/{resource_id}")
async def delete_resource(
    resource_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    try:
        real_res_id = decode_id(resource_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resource ID format")
    delete_resource_service(session, team, real_res_id)
    return {"status": "success"}


@router.put("/api/resources/{resource_id}")
async def update_resource(
    resource_id: str,
    resource_in: SharedResourceCreate,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    try:
        real_res_id = decode_id(resource_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resource ID format")
    resource = update_resource_service(
        session,
        team,
        real_res_id,
        name=resource_in.name,
        file_url=resource_in.file_url,
        trigger_word=resource_in.trigger_word,
        aliases=resource_in.aliases,
        description=resource_in.description,
        owner_user_id=int(user.id),
    )
    return _serialize_resource(resource)


@router.get("/api/resources/{resource_id}/download")
async def download_resource_file(
    resource_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    try:
        real_res_id = decode_id(resource_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resource ID format")

    resource = require_resource_team_access(session, team, real_res_id)
    source = str(resource.file_url or "").strip()
    if not source:
        raise HTTPException(status_code=404, detail="当前资源没有可下载的原图")

    try:
        upstream = requests.get(source, stream=True, timeout=120)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"下载源文件失败: {exc}")

    if not upstream.ok:
        upstream.close()
        raise HTTPException(status_code=502, detail="下载源文件失败")

    media_type = upstream.headers.get("Content-Type") or resource.mime_type or "application/octet-stream"
    filename = _build_download_filename(resource.name, resource.original_filename, media_type)
    disposition = f"attachment; filename*=UTF-8''{quote(filename)}"

    def iter_stream():
        try:
            for chunk in upstream.iter_content(chunk_size=1024 * 64):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        iter_stream(),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


@router.post("/api/scripts/{script_id}/resources/upload")
async def upload_script_resource(
    script_id: str,
    resource_type: str = Form(...),
    name: str = Form(...),
    trigger_word: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    aliases: Optional[str] = Form(None),
    file: UploadFile = File(...),
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    try:
        real_script_id = decode_id(script_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid script ID format")

    require_script_team_access(session, team, real_script_id)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件不能为空")

    upload_meta = upload_shared_resource_file_service(
        content,
        file.filename or "resource.bin",
        file.content_type or "application/octet-stream",
        owner_user_id=int(user.id),
    )
    resource = create_resource_service(
        session,
        team,
        script_id=real_script_id,
        resource_type=resource_type,
        name=name,
        file_url=upload_meta["file_url"],
        trigger_word=trigger_word,
        aliases=_parse_aliases_form(aliases),
        description=description,
        storage_object_key=upload_meta["storage_object_key"],
        original_filename=upload_meta["original_filename"],
        mime_type=upload_meta["mime_type"],
        file_size=upload_meta["file_size"],
        owner_user_id=int(user.id),
    )
    create_uploaded_resource_version_service(
        session,
        team,
        resource_id=resource.id,
        appearance_prompt=resource.description,
    )
    session.refresh(resource)
    return _serialize_resource(resource)


@router.put("/api/resources/{resource_id}/upload")
async def upload_resource_file(
    resource_id: str,
    name: Optional[str] = Form(None),
    trigger_word: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    aliases: Optional[str] = Form(None),
    file: UploadFile = File(...),
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    try:
        real_res_id = decode_id(resource_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid resource ID format")

    resource = require_resource_team_access(session, team, real_res_id)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="上传文件不能为空")

    upload_meta = upload_shared_resource_file_service(
        content,
        file.filename or "resource.bin",
        file.content_type or "application/octet-stream",
        owner_user_id=int(user.id),
    )
    updated = update_resource_service(
        session,
        team,
        real_res_id,
        name=name if name is not None else resource.name,
        file_url=upload_meta["file_url"],
        trigger_word=trigger_word if trigger_word is not None else resource.trigger_word,
        aliases=_parse_aliases_form(aliases) if aliases is not None else serialize_resource_service(resource).get("aliases"),
        description=description if description is not None else resource.description,
        storage_object_key=upload_meta["storage_object_key"],
        original_filename=upload_meta["original_filename"],
        mime_type=upload_meta["mime_type"],
        file_size=upload_meta["file_size"],
        owner_user_id=int(user.id),
    )
    create_uploaded_resource_version_service(
        session,
        team,
        resource_id=updated.id,
        appearance_prompt=updated.description,
    )
    session.refresh(updated)
    return _serialize_resource(updated)


@router.get("/api/resources/{resource_id}/versions")
async def list_resource_versions(
    resource_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    versions = list_resource_versions_service(session, team, decode_id(resource_id))
    return [{**item.dict(), "id": encode_id(item.id), "resource_id": encode_id(item.resource_id)} for item in versions]


@router.post("/api/resources/{resource_id}/versions")
async def create_resource_version(
    resource_id: str,
    payload: SharedResourceVersionCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    version = create_resource_version_service(
        session,
        team,
        resource_id=decode_id(resource_id),
        version_tag=payload.version_tag,
        appearance_prompt=payload.appearance_prompt,
        file_url=payload.file_url,
        trigger_word=payload.trigger_word,
        start_seq=payload.start_seq,
        end_seq=payload.end_seq,
        is_default=payload.is_default,
        owner_user_id=int(user.id),
    )
    return {**version.dict(), "id": encode_id(version.id), "resource_id": encode_id(version.resource_id)}


@router.post("/api/resources/{resource_id}/generate-image")
async def generate_resource_image(
    resource_id: str,
    payload: GenerateSharedResourceImageRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
):
    real_resource_id = decode_id(resource_id)
    resource = require_resource_team_access(session, team, real_resource_id)

    prompt = (payload.prompt or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt 不能为空")

    normalized = normalize_image_request(
        {
            "model_code": payload.model_code or payload.channel,
            "mode": "image_to_image" if payload.reference_images else "text_to_image",
            "prompt": prompt,
            "resolution": payload.resolution,
            "quality": payload.quality,
            "aspect_ratio": payload.aspectRatio,
            "reference_images": payload.reference_images,
        }
    )
    price = estimate_image_price(normalized["model_code"], normalized["generation_type"], normalized)
    estimate_points = int(price["sell_price_points"])
    _ensure_affordable(session, user, team, estimate_points)

    task_id = f"resource-gen-{uuid.uuid4().hex[:12]}"
    record = _create_generation_record(
        session,
        user=user,
        team=team,
        record_type="asset",
        ownership_mode="project",
        script_id=resource.script_id,
        episode_id=None,
        target_type="shared_resource",
        target_id=real_resource_id,
        prompt=prompt,
        negative_prompt=None,
        params_internal={
            "resource_reference_image": True,
            "internal_model": normalized["model_code"],
            "model_code": normalized["model_code"],
            "generation_type": normalized["generation_type"],
            "resolution": normalized["resolution"],
            "quality": normalized.get("quality"),
            "aspect_ratio": normalized["aspect_ratio"],
            "reference_images": list(normalized["reference_images"]),
            "version_tag": payload.version_tag,
            "start_seq": payload.start_seq,
            "end_seq": payload.end_seq,
            "is_default": bool(payload.is_default),
        },
        params_public={
            "asset_type": str(resource.resource_type),
            "name": resource.name,
            "model_code": normalized["model_code"],
            "model": normalized["model_code"],
            "model_label": normalized["model_name"],
            "generation_type": normalized["generation_type"],
            "generation_type_label": normalized["generation_type_label"],
            "resolution": normalized["resolution"],
            "quality": normalized.get("quality"),
            "quality_mode": normalized.get("quality"),
            "quality_mode_label": normalized.get("quality_label"),
            "quality_label": None
            if normalized["model_code"] == "gpt-image-2-fast"
            else " · ".join([part for part in [normalized.get("quality_label"), normalized["resolution"].upper()] if part]),
            "aspect_ratio": normalized["aspect_ratio"],
            "aspect_ratio_label": normalized["aspect_ratio"],
            "prompt_summary": prompt[:42],
            "source": "webui",
            "pricing_rule_type": price["pricing_rule_type"],
            "pricing_note": price["pricing_note"],
            "pricing_details": price["pricing_details"],
        },
        estimate_points=estimate_points,
    )
    record.task_id = task_id
    session.add(record)
    session.commit()
    job = create_task_job(
        session,
        task_id=task_id,
        task_type="resource.generate_image",
        queue_name="resource",
        provider=normalized["model_code"],
        team_id=team.id,
        user_id=user.id,
        script_id=resource.script_id,
        ownership_mode="project",
        scope_type="shared_resource",
        scope_id=real_resource_id,
        task_category="resource",
        generation_record_id=record.id,
        payload={
            "kind": "resource_reference_image",
            "record_id": record.id,
            "resource_id": real_resource_id,
            "prompt": prompt,
            "model_code": normalized["model_code"],
            "resolution": normalized["resolution"],
            "quality": normalized.get("quality"),
            "aspect_ratio": normalized["aspect_ratio"],
            "reference_images": list(normalized["reference_images"]),
            "version_tag": payload.version_tag,
            "start_seq": payload.start_seq,
            "end_seq": payload.end_seq,
            "is_default": bool(payload.is_default),
        },
        message="资源参考图生成任务已提交",
        max_retries=2,
    )
    enqueue_task_job(job)
    return {"task_id": task_id, "status": "submitted", "msg": f"参考图任务已提交，生成成功后将扣除 {estimate_points} 灵感值"}
    resource_generate_tasks.create(
        task_id,
        status="submitted",
        url="",
        error="",
        msg="任务已提交，正在排队...",
        resource_id=resource_id,
        script_id=resource.script_id,
        user_id=user.id,
        kind="asset",
        source="webui",
        title="资源图生成",
        summary=resource.name,
    )

    thread = threading.Thread(
        target=dispatch_shared_resource_generation,
        kwargs={
            "task_id": task_id,
            "resource_id": real_resource_id,
            "prompt": prompt,
            "channel": payload.channel,
            "resolution": payload.resolution,
            "quality": payload.quality,
            "aspect_ratio": payload.aspectRatio,
            "reference_images": payload.reference_images,
            "version_tag": payload.version_tag,
            "start_seq": payload.start_seq,
            "end_seq": payload.end_seq,
            "is_default": bool(payload.is_default),
        },
        daemon=True,
    )
    thread.start()
    return {"task_id": task_id, "status": "submitted"}


@router.get("/api/resource_generate_status/{task_id}")
async def get_resource_generate_status(task_id: str, user: User = Depends(get_current_user)):
    job = get_task_job(task_id)
    if job:
        data = serialize_task_job(job)
        result = data.get("result") or {}
        error = data.get("error") or {}
        return {
            "task_id": task_id,
            "status": data.get("legacy_status"),
            "url": result.get("file_url") or "",
            "error": error.get("message") or "",
            "msg": data.get("message") or "",
        }
    task = resource_generate_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    if task.get("status") in {"completed", "failed"}:
        return resource_generate_tasks.pop(task_id) or task
    return task


@router.get("/api/resource_extract_stream/{task_id}")
async def stream_resource_extract(
    task_id: str,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    with session_scope() as stream_session:
        user = _resolve_stream_user(stream_session, token, authorization)
        link = stream_session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user.id)).first()
        if not link:
            raise HTTPException(status_code=403, detail="当前账号未加入任何团队")
        team = stream_session.get(Team, link.team_id)
        if not team:
            raise HTTPException(status_code=404, detail="团队不存在")
        initial_task = _serialize_asset_extract_task(task_id, session=stream_session)
        if not initial_task:
            raise HTTPException(status_code=404, detail="任务不存在")

        job = get_task_job(task_id, session=stream_session)
        real_script_id = int(getattr(job, "script_id", 0) or 0)
        if not real_script_id:
            raise HTTPException(status_code=404, detail="任务缺少有效剧本范围")
        require_script_team_access(stream_session, team, real_script_id)
        team_id = int(team.id)

    async def event_generator():
        last_task_signature = None
        last_resource_signatures = {}

        try:
            while True:
                with session_scope() as loop_session:
                    next_task = _serialize_asset_extract_task(task_id, session=loop_session)
                    if not next_task:
                        yield "event: error\ndata: {0}\n\n".format(
                            json.dumps({"type": "error", "message": "任务不存在"}, ensure_ascii=False)
                        )
                        return

                    loop_team = loop_session.get(Team, team_id)
                    if not loop_team:
                        yield "event: error\ndata: {0}\n\n".format(
                            json.dumps({"type": "error", "message": "团队不存在"}, ensure_ascii=False)
                        )
                        return
                    resources = list_resources_service(loop_session, loop_team, real_script_id)
                    serialized_resources = [_serialize_resource(item) for item in resources]

                task_signature = json.dumps(next_task, ensure_ascii=False, sort_keys=True, default=str)
                resource_signatures = {
                    str(item["id"]): json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
                    for item in serialized_resources
                }

                if last_task_signature is None:
                    yield "event: snapshot\ndata: {0}\n\n".format(
                        json.dumps(
                            {"type": "snapshot", "task": next_task, "resources": serialized_resources},
                            ensure_ascii=False,
                            default=str,
                        )
                    )
                else:
                    if task_signature != last_task_signature:
                        yield "event: task\ndata: {0}\n\n".format(
                            json.dumps({"type": "task", "task": next_task}, ensure_ascii=False, default=str)
                        )
                    for item in serialized_resources:
                        item_id = str(item["id"])
                        if last_resource_signatures.get(item_id) != resource_signatures[item_id]:
                            yield "event: resource_upsert\ndata: {0}\n\n".format(
                                json.dumps({"type": "resource_upsert", "resource": item}, ensure_ascii=False, default=str)
                            )

                last_task_signature = task_signature
                last_resource_signatures = resource_signatures

                if str(next_task.get("status") or "") in {"completed", "failed", "cancelled"}:
                    yield "event: done\ndata: {0}\n\n".format(
                        json.dumps({"type": "done", "task": next_task}, ensure_ascii=False, default=str)
                    )
                    return

                await asyncio.sleep(0.8)
                yield "event: heartbeat\ndata: {0}\n\n".format(
                    json.dumps({"type": "heartbeat"}, ensure_ascii=False)
                )
        except asyncio.CancelledError:
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.put("/api/resources/versions/{version_id}")
async def update_resource_version(
    version_id: str,
    payload: SharedResourceVersionUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    version = update_resource_version_service(
        session,
        team,
        decode_id(version_id),
        version_tag=payload.version_tag,
        appearance_prompt=payload.appearance_prompt,
        file_url=payload.file_url,
        trigger_word=payload.trigger_word,
        start_seq=payload.start_seq,
        end_seq=payload.end_seq,
        is_default=payload.is_default,
        owner_user_id=int(user.id),
    )
    return {**version.dict(), "id": encode_id(version.id), "resource_id": encode_id(version.resource_id)}


@router.delete("/api/resources/versions/{version_id}")
async def delete_resource_version(
    version_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    result = delete_resource_version_service(session, team, decode_id(version_id))
    return {
        "status": "success",
        "resource_id": encode_id(result["resource_id"]),
        "deleted_version_id": encode_id(result["deleted_version_id"]),
        "next_default_version_id": encode_id(result["next_default_version_id"]) if result["next_default_version_id"] else None,
    }


@router.post("/api/scripts/{script_id}/extract-assets")
async def extract_script_assets(
    script_id: str,
    payload: ExtractScriptAssetsRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    session: Session = Depends(get_session),
    team: Team = Depends(get_current_team),
):
    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="服务端未配置 DEEPSEEK_API_KEY")

    try:
        real_script_id = decode_id(script_id)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid script ID format")

    script = require_script_team_access(session, team, real_script_id)
    episode = None
    if payload.episode_id:
        try:
            real_episode_id = decode_id(payload.episode_id)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid episode ID format")
        episode = require_episode_team_access(session, team, real_episode_id)
        if int(getattr(episode, "script_id", 0) or 0) != int(script.id):
            raise HTTPException(status_code=400, detail="当前分集不属于目标剧本")
    source_text = (payload.source_text or script.source_text or "").strip()
    if not source_text:
        raise HTTPException(status_code=400, detail="请先保存剧本原文后再执行资产提取")

    workflow_profile = resolve_effective_workflow_profile(
        script,
        episode=episode,
        storyboard_mode=resolve_asset_extraction_storyboard_mode(script, episode=episode),
    )
    style_prompt = build_style_prompt(workflow_profile.get("style"), fallback=getattr(script, "style_preset", ""))
    style_label = get_style_display_label(workflow_profile.get("style"), getattr(script, "style_preset", "默认写实"))

    task_id = f"asset-{uuid.uuid4().hex[:12]}"
    job = create_task_job(
        session,
        task_id=task_id,
        task_type="resource.extract",
        queue_name="resource",
        provider="deepseek",
        team_id=team.id,
        user_id=getattr(_, "user_id", None),
        script_id=real_script_id,
        ownership_mode="project",
        scope_type="script",
        scope_id=real_script_id,
        task_category="resource",
        payload={
            "script_id": real_script_id,
            "source_text": source_text,
            "style_prompt": style_prompt,
            "style_label": style_label,
            "user_id": getattr(_, "user_id", None),
            "team_id": team.id,
        },
        message="资产提取任务已提交",
        max_retries=1,
    )
    enqueue_task_job(job)
    return {"task_id": task_id, "status": "submitted"}
    resource_extract_tasks.create(
        task_id,
        status="submitted",
        msg="任务已提交，正在排队...",
        character_count=0,
        scene_count=0,
        prop_count=0,
        created_count=0,
        updated_count=0,
        script_id=real_script_id,
        user_id=getattr(_, "user_id", None),
        kind="asset_extract",
        source="webui",
        title="提取项目资产",
        summary=script.name,
    )
    thread = threading.Thread(
        target=_do_extract_script_assets,
        args=(task_id, real_script_id, source_text, settings.DEEPSEEK_API_KEY, style_prompt, style_label),
        daemon=True,
    )
    thread.start()
    return {"task_id": task_id, "status": "submitted"}


@router.get("/api/resource_extract_status/{task_id}")
async def get_resource_extract_status(task_id: str, user: User = Depends(get_current_user)):
    job = get_task_job(task_id)
    if job:
        data = serialize_task_job(job)
        result = data.get("result") or {}
        return {
            "task_id": task_id,
            "status": data.get("legacy_status"),
            "msg": data.get("message"),
            "character_count": result.get("character_count") or 0,
            "scene_count": result.get("scene_count") or 0,
            "prop_count": result.get("prop_count") or 0,
            "created_count": result.get("created_count") or 0,
            "updated_count": result.get("updated_count") or 0,
            "billing": data.get("billing"),
            "charged_points": data.get("charged_points"),
            "actual_points": data.get("actual_points"),
            "actual_cost_cny": data.get("actual_cost_cny"),
            "points_status": data.get("points_status"),
            "asset_quality_warnings": result.get("asset_quality_warnings") or [],
        }
    task = resource_extract_tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在或已过期")
    return task
