from __future__ import annotations

import hashlib
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict

from sqlmodel import Session, select

from database import engine
from models import TemporaryUploadAsset
from services.oss_service import (
    build_oss_thumbnail_url,
    delete_object_from_oss,
    upload_bytes_to_oss_with_meta,
)
from services.video_compose_service import video_compose_service

TEMP_UPLOAD_TTL_HOURS = 2
TEMP_UPLOAD_TTL = timedelta(hours=TEMP_UPLOAD_TTL_HOURS)


def _now() -> datetime:
    return datetime.utcnow()


def _guess_extension(filename: str, content_type: str) -> str:
    name = str(filename or "").strip()
    if "." in name:
        return name.rsplit(".", 1)[-1].lower()

    lowered = str(content_type or "").lower()
    if "jpeg" in lowered or "jpg" in lowered:
        return "jpg"
    if "png" in lowered:
        return "png"
    if "webp" in lowered:
        return "webp"
    if "gif" in lowered:
        return "gif"
    if "mp4" in lowered:
        return "mp4"
    if "webm" in lowered:
        return "webm"
    if "quicktime" in lowered:
        return "mov"
    if "matroska" in lowered:
        return "mkv"
    if "mpeg" in lowered or "mp3" in lowered:
        return "mp3"
    if "wav" in lowered:
        return "wav"
    return "bin"


def _build_temp_object_key(media_type: str, content_hash: str, filename: str, content_type: str) -> str:
    ext = _guess_extension(filename, content_type)
    safe_media_type = str(media_type or "file").strip().lower() or "file"
    return f"temp/creative/{safe_media_type}/{content_hash[:2]}/{content_hash}.{ext}"


def _serialize(asset: TemporaryUploadAsset) -> Dict[str, object]:
    return {
        "file_url": asset.file_url,
        "thumbnail_url": asset.thumbnail_url or "",
        "storage_object_key": asset.storage_object_key,
        "original_filename": asset.original_filename or "",
        "mime_type": asset.mime_type or "",
        "file_size": asset.file_size,
        "duration_seconds": asset.duration_seconds,
        "has_audio": asset.has_audio,
        "width": asset.width,
        "height": asset.height,
        "expires_at": asset.expires_at.isoformat(),
        "is_temporary": True,
    }


def _inspect_media_bytes(*, media_type: str, content: bytes, filename: str, content_type: str) -> Dict[str, object]:
    if media_type not in {"video", "audio"} or not content:
        return {}
    dependency_state = video_compose_service.get_dependency_state()
    if not dependency_state.get("ffprobe"):
        return {}

    ext = _guess_extension(filename, content_type)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as handle:
            handle.write(content)
            temp_path = handle.name
        media_info = video_compose_service.probe_local_media(str(temp_path))
    except Exception:
        return {}
    finally:
        if temp_path:
            try:
                Path(temp_path).unlink(missing_ok=True)
            except Exception:
                pass

    return {
        "duration_seconds": float(media_info.get("duration_seconds") or 0.0) or None,
        "has_audio": bool(media_info.get("has_audio")),
        "width": media_info.get("width"),
        "height": media_info.get("height"),
    }


def _apply_inspected_media(asset: TemporaryUploadAsset, inspected: Dict[str, object]) -> None:
    if "duration_seconds" in inspected:
        asset.duration_seconds = inspected.get("duration_seconds")
    if "has_audio" in inspected:
        asset.has_audio = inspected.get("has_audio")
    if "width" in inspected:
        asset.width = inspected.get("width")
    if "height" in inspected:
        asset.height = inspected.get("height")


def get_or_create_temporary_upload(
    session: Session,
    *,
    owner_user_id: int | None = None,
    media_type: str,
    content: bytes,
    filename: str,
    content_type: str,
    include_thumbnail: bool,
) -> Dict[str, object]:
    now = _now()
    expires_at = now + TEMP_UPLOAD_TTL
    hash_payload = content if owner_user_id is None else f"user:{owner_user_id}:".encode("utf-8") + content
    content_hash = hashlib.sha256(hash_payload).hexdigest()
    inspected = _inspect_media_bytes(
        media_type=media_type,
        content=content,
        filename=filename,
        content_type=content_type,
    )

    existing = session.exec(
        select(TemporaryUploadAsset).where(TemporaryUploadAsset.content_hash == content_hash)
    ).first()

    if existing and existing.expires_at > now:
        existing.expires_at = expires_at
        existing.updated_at = now
        if filename:
            existing.original_filename = filename
        existing.media_type = media_type
        existing.mime_type = content_type
        existing.file_size = len(content)
        _apply_inspected_media(existing, inspected)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return _serialize(existing)

    object_key = _build_temp_object_key(media_type, content_hash, filename, content_type)
    if owner_user_id:
        from services.oss_service import build_user_object_key

        object_key = build_user_object_key(
            owner_user_id=owner_user_id,
            content_type=content_type,
            filename=filename,
            media_type="temp",
            temp_media_type=media_type,
        )
    meta = upload_bytes_to_oss_with_meta(
        content,
        filename=filename,
        content_type=content_type,
        object_name=object_key,
        owner_user_id=owner_user_id,
        media_type=media_type,
        source_type="temporary_upload",
    )
    if not include_thumbnail:
        meta["thumbnail_url"] = ""

    if existing:
        existing.media_type = media_type
        existing.storage_object_key = meta["storage_object_key"]
        existing.file_url = meta["file_url"]
        existing.thumbnail_url = meta["thumbnail_url"]
        existing.original_filename = filename
        existing.mime_type = content_type
        existing.file_size = len(content)
        existing.expires_at = expires_at
        existing.updated_at = now
        asset = existing
    else:
        asset = TemporaryUploadAsset(
            content_hash=content_hash,
            media_type=media_type,
            storage_object_key=meta["storage_object_key"],
            file_url=meta["file_url"],
            thumbnail_url=meta["thumbnail_url"],
            original_filename=filename,
            mime_type=content_type,
            file_size=len(content),
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )

    _apply_inspected_media(asset, inspected)
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return _serialize(asset)


def cleanup_expired_temporary_uploads(*, batch_size: int = 100) -> int:
    now = _now()
    removed = 0
    with Session(engine) as session:
        expired_items = session.exec(
            select(TemporaryUploadAsset)
            .where(TemporaryUploadAsset.expires_at <= now)
            .order_by(TemporaryUploadAsset.expires_at.asc())
            .limit(batch_size)
        ).all()

        for item in expired_items:
            delete_object_from_oss(item.storage_object_key)
            session.delete(item)
            removed += 1

        if removed:
            session.commit()
    return removed


def start_temporary_upload_cleanup_loop(*, interval_seconds: int = 600, batch_size: int = 100) -> None:
    while True:
        try:
            cleanup_expired_temporary_uploads(batch_size=batch_size)
        except Exception as exc:
            print(f"⚠️ 临时上传清理失败: {exc}")
        time.sleep(interval_seconds)
