import base64
import binascii

from fastapi import APIRouter, BackgroundTasks, Depends, File, Query, UploadFile
from sqlmodel import Session
from typing import Set, Tuple

from database import get_session
from dependencies import get_current_team, get_current_user, require_team_permission
from models import Team, TeamMemberLink, User
from schemas import (
    CreativeAudioEstimateRequest,
    CreativeAudioGenerateRequest,
    CreativeAssetGenerateRequest,
    CreativeBase64UploadRequest,
    CreativeEditingComposeRequest,
    CreativeEditingDraftSaveRequest,
    CreativeEditingJianyingDraftRequest,
    CreativeImageEstimateRequest,
    CreativeImageGenerateRequest,
    CreativeVideoEstimateRequest,
    CreativeVideoGenerateRequest,
)
from services.generation_record_service import (
    delete_generation_record,
    delete_voice_asset_record,
    estimate_audio_generation,
    estimate_image_generation,
    estimate_video_generation,
    get_audio_generation_catalog,
    get_image_generation_catalog,
    get_video_generation_catalog,
    get_generation_record_detail,
    list_generation_records,
    list_voice_assets,
    public_http_error,
    submit_audio_generation,
    submit_asset_generation,
    submit_image_generation,
    submit_video_generation,
)
from services.creative_editing_service import (
    get_creative_editing_catalog,
    get_creative_editing_draft,
    get_creative_editing_timeline_seed,
    save_creative_editing_draft,
    submit_creative_editing_compose,
    submit_creative_editing_jianying_draft,
)
from services.temp_media_service import get_or_create_temporary_upload

router = APIRouter()

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_AUDIO_BYTES = 50 * 1024 * 1024
MAX_TEXT_BYTES = 20 * 1024 * 1024

ALLOWED_IMAGE_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}
ALLOWED_VIDEO_MIME_TYPES = {
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-matroska",
}
ALLOWED_AUDIO_MIME_TYPES = {
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/webm",
    "audio/mp4",
    "audio/aac",
}
ALLOWED_TEXT_MIME_TYPES = {
    "text/plain",
    "application/zip",
    "application/x-zip-compressed",
    "multipart/x-zip",
}


def _validate_upload_file(
    upload: UploadFile,
    *,
    allowed_types: Set[str],
    max_size: int,
    field_label: str,
) -> Tuple[bytes, str]:
    content_type = str(upload.content_type or "").strip().lower()
    if content_type not in allowed_types:
        raise public_http_error(
            400,
            "invalid_file_type",
            f"{field_label}格式不支持，请更换后重试",
            field="file",
        )

    content = upload.file.read()
    if not content:
        raise public_http_error(
            400,
            "invalid_file",
            f"{field_label}内容为空，请重新上传",
            field="file",
        )
    if len(content) > max_size:
        raise public_http_error(
            400,
            "file_too_large",
            f"{field_label}大小超出限制，请压缩后重试",
            field="file",
        )
    return content, content_type


def _decode_base64_payload(*, encoded_data: str, max_size: int, field_label: str) -> bytes:
    raw = str(encoded_data or "").strip()
    if not raw:
        raise public_http_error(
            400,
            "invalid_file",
            f"{field_label}内容为空，请重新上传",
            field="file",
        )
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        content = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        raise public_http_error(
            400,
            "invalid_file",
            f"{field_label}内容无法解析，请重新上传",
            field="file",
        )
    if not content:
        raise public_http_error(
            400,
            "invalid_file",
            f"{field_label}内容为空，请重新上传",
            field="file",
        )
    if len(content) > max_size:
        raise public_http_error(
            400,
            "file_too_large",
            f"{field_label}大小超出限制，请压缩后重试",
            field="file",
        )
    return content


def _upload_media_payload(
    session: Session,
    *,
    owner_user_id: int,
    media_type: str,
    content: bytes,
    filename: str,
    content_type: str,
    include_thumbnail: bool,
) -> dict:
    meta = get_or_create_temporary_upload(
        session,
        owner_user_id=owner_user_id,
        media_type=media_type,
        content=content,
        filename=filename or "upload.bin",
        content_type=content_type,
        include_thumbnail=include_thumbnail,
    )
    return {"success": True, "data": meta}


@router.post("/api/creative/images/estimate")
async def creative_image_estimate(
    payload: CreativeImageEstimateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del user, team
    return estimate_image_generation(session, payload.model_dump())


@router.post("/api/creative/videos/estimate")
async def creative_video_estimate(
    payload: CreativeVideoEstimateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del user, team
    return estimate_video_generation(session, payload.model_dump(exclude_unset=True))


@router.post("/api/creative/audio/estimate")
async def creative_audio_estimate(
    payload: CreativeAudioEstimateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del team
    request_payload = payload.model_dump()
    request_payload["_current_user"] = user
    return estimate_audio_generation(session, request_payload)


@router.get("/api/creative/editing/catalog")
async def creative_editing_catalog(
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
):
    del user, team
    return get_creative_editing_catalog()


@router.get("/api/creative/editing/timeline-seed")
async def creative_editing_timeline_seed(
    ownership_mode: str = Query(default="project"),
    project_id: str = Query(default=None),
    episode_id: str = Query(default=None),
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    return get_creative_editing_timeline_seed(
        session,
        user=user,
        team=team,
        ownership_mode=ownership_mode,
        project_id=project_id,
        episode_id=episode_id,
    )


@router.get("/api/creative/editing/draft")
async def creative_editing_draft(
    ownership_mode: str = Query(default="standalone"),
    project_id: str = Query(default=None),
    episode_id: str = Query(default=None),
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    return get_creative_editing_draft(
        session,
        user=user,
        team=team,
        ownership_mode=ownership_mode,
        project_id=project_id,
        episode_id=episode_id,
    )


@router.put("/api/creative/editing/draft")
async def creative_editing_save_draft(
    payload: CreativeEditingDraftSaveRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    return save_creative_editing_draft(
        session,
        user=user,
        team=team,
        payload=payload.model_dump(exclude_unset=True),
    )


@router.post("/api/creative/editing/compose")
async def creative_editing_compose(
    payload: CreativeEditingComposeRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    record = submit_creative_editing_compose(
        session,
        background_tasks=background_tasks,
        user=user,
        team=team,
        payload=payload.model_dump(),
    )
    return {"success": True, "data": {"record": get_generation_record_detail(session, user=user, record_id=record_id(record.id))}}


@router.post("/api/creative/editing/jianying-draft")
async def creative_editing_jianying_draft(
    payload: CreativeEditingJianyingDraftRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    record = submit_creative_editing_jianying_draft(
        session,
        background_tasks=background_tasks,
        user=user,
        team=team,
        payload=payload.model_dump(),
    )
    return {"success": True, "data": {"record": get_generation_record_detail(session, user=user, record_id=record_id(record.id))}}


@router.get("/api/creative/videos/catalog")
async def creative_video_catalog(
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del user, team
    return get_video_generation_catalog(session)


@router.get("/api/creative/images/catalog")
async def creative_image_catalog(
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del user, team
    return get_image_generation_catalog(session)


@router.get("/api/creative/audio/catalog")
async def creative_audio_catalog(
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del user, team
    return get_audio_generation_catalog(session)


@router.post("/api/creative/images")
async def creative_generate_image(
    payload: CreativeImageGenerateRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    record = submit_image_generation(
        session,
        background_tasks=background_tasks,
        user=user,
        team=team,
        payload=payload.model_dump(),
    )
    return {"success": True, "data": {"record": get_generation_record_detail(session, user=user, record_id=record_id(record.id))}}


@router.post("/api/creative/videos")
async def creative_generate_video(
    payload: CreativeVideoGenerateRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    record = submit_video_generation(
        session,
        background_tasks=background_tasks,
        user=user,
        team=team,
        payload=payload.model_dump(),
    )
    return {"success": True, "data": {"record": get_generation_record_detail(session, user=user, record_id=record_id(record.id))}}


@router.post("/api/creative/audio/generate")
async def creative_generate_audio(
    payload: CreativeAudioGenerateRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    record = submit_audio_generation(
        session,
        background_tasks=background_tasks,
        user=user,
        team=team,
        payload=payload.model_dump(),
    )
    return {"success": True, "data": {"record": get_generation_record_detail(session, user=user, record_id=record_id(record.id))}}


@router.post("/api/creative/assets/generate")
async def creative_generate_asset(
    payload: CreativeAssetGenerateRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    record = submit_asset_generation(
        session,
        background_tasks=background_tasks,
        user=user,
        team=team,
        payload=payload.model_dump(),
    )
    return {"success": True, "data": {"record": get_generation_record_detail(session, user=user, record_id=record_id(record.id))}}


@router.get("/api/creative/records")
async def creative_list_records(
    record_type: str = "",
    operation_type: str = "",
    ownership_mode: str = "",
    project_id: str = "",
    episode_id: str = "",
    q: str = "",
    status: str = "",
    date_from: str = "",
    date_to: str = "",
    sort_by: str = "created_at",
    sort_order: str = "desc",
    page: int = 1,
    page_size: int = 20,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del team
    return {
        "success": True,
        "data": list_generation_records(
            session,
            user=user,
            record_type=record_type or None,
            operation_type=operation_type or None,
            ownership_mode=ownership_mode or None,
            project_id=project_id or None,
            episode_id=episode_id or None,
            q=q or None,
            status=status or None,
            date_from=date_from or None,
            date_to=date_to or None,
            sort_by=sort_by or "created_at",
            sort_order=sort_order or "desc",
            page=page,
            page_size=page_size,
        ),
    }


@router.get("/api/creative/records/{record_id}")
async def creative_record_detail(
    record_id: str,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del team
    return {"success": True, "data": {"record": get_generation_record_detail(session, user=user, record_id=record_id)}}


@router.delete("/api/creative/records/{record_id}")
async def creative_delete_record(
    record_id: str,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del team
    delete_generation_record(session, user=user, record_id=record_id)
    return {"success": True, "message": "生成记录已删除"}


@router.get("/api/creative/voice-assets")
async def creative_voice_assets(
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del team
    return {"success": True, "data": list_voice_assets(session, user=user)}


@router.delete("/api/creative/voice-assets/{asset_id}")
async def creative_delete_voice_asset(
    asset_id: str,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del team
    delete_voice_asset_record(session, user=user, asset_id=asset_id)
    return {"success": True, "message": "音色资产已删除"}


@router.post("/api/creative/uploads/images")
async def creative_upload_image(
    file: UploadFile = File(...),
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    content, content_type = _validate_upload_file(
        file,
        allowed_types=ALLOWED_IMAGE_MIME_TYPES,
        max_size=MAX_IMAGE_BYTES,
        field_label="图片文件",
    )
    return _upload_media_payload(
        session,
        owner_user_id=int(user.id),
        media_type="image",
        content=content,
        filename=str(file.filename or "image.bin"),
        content_type=content_type,
        include_thumbnail=True,
    )


@router.post("/api/creative/uploads/images/base64")
async def creative_upload_image_base64(
    payload: CreativeBase64UploadRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    content_type = str(payload.content_type or "").strip().lower()
    if content_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise public_http_error(
            400,
            "invalid_file_type",
            "图片文件格式不支持，请更换后重试",
            field="file",
        )
    content = _decode_base64_payload(
        encoded_data=payload.data_base64,
        max_size=MAX_IMAGE_BYTES,
        field_label="图片文件",
    )
    return _upload_media_payload(
        session,
        owner_user_id=int(user.id),
        media_type="image",
        content=content,
        filename=payload.filename,
        content_type=content_type,
        include_thumbnail=True,
    )


@router.post("/api/creative/uploads/videos")
async def creative_upload_video(
    file: UploadFile = File(...),
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    content, content_type = _validate_upload_file(
        file,
        allowed_types=ALLOWED_VIDEO_MIME_TYPES,
        max_size=MAX_VIDEO_BYTES,
        field_label="视频文件",
    )
    return _upload_media_payload(
        session,
        owner_user_id=int(user.id),
        media_type="video",
        content=content,
        filename=str(file.filename or "video.bin"),
        content_type=content_type,
        include_thumbnail=False,
    )


@router.post("/api/creative/uploads/videos/base64")
async def creative_upload_video_base64(
    payload: CreativeBase64UploadRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    content_type = str(payload.content_type or "").strip().lower()
    if content_type not in ALLOWED_VIDEO_MIME_TYPES:
        raise public_http_error(
            400,
            "invalid_file_type",
            "视频文件格式不支持，请更换后重试",
            field="file",
        )
    content = _decode_base64_payload(
        encoded_data=payload.data_base64,
        max_size=MAX_VIDEO_BYTES,
        field_label="视频文件",
    )
    return _upload_media_payload(
        session,
        owner_user_id=int(user.id),
        media_type="video",
        content=content,
        filename=payload.filename,
        content_type=content_type,
        include_thumbnail=False,
    )


@router.post("/api/creative/uploads/audio")
async def creative_upload_audio(
    file: UploadFile = File(...),
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    content, content_type = _validate_upload_file(
        file,
        allowed_types=ALLOWED_AUDIO_MIME_TYPES,
        max_size=MAX_AUDIO_BYTES,
        field_label="音频文件",
    )
    return _upload_media_payload(
        session,
        owner_user_id=int(user.id),
        media_type="audio",
        content=content,
        filename=str(file.filename or "audio.bin"),
        content_type=content_type,
        include_thumbnail=False,
    )


@router.post("/api/creative/uploads/texts")
async def creative_upload_text(
    file: UploadFile = File(...),
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    content, content_type = _validate_upload_file(
        file,
        allowed_types=ALLOWED_TEXT_MIME_TYPES,
        max_size=MAX_TEXT_BYTES,
        field_label="文本文件",
    )
    return _upload_media_payload(
        session,
        owner_user_id=int(user.id),
        media_type="text",
        content=content,
        filename=str(file.filename or "script.txt"),
        content_type=content_type,
        include_thumbnail=False,
    )


def record_id(db_id: int) -> str:
    from core.security import encode_id

    return encode_id(db_id)
