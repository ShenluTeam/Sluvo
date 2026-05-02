from __future__ import annotations

import base64
import json
import uuid
from datetime import datetime
from urllib.parse import urlparse

import oss2
import requests
from sqlmodel import Session, select

from core.config import settings
from database import engine
from models import Episode, Panel, Script, TeamMemberLink
from services.panel_video_service import upsert_panel_video_history
from services.storage_service import (
    commit_storage_object,
    ensure_user_storage_namespace,
    mark_storage_object_deleted,
    release_storage_reservation,
    reserve_storage_bytes,
)

try:
    auth = oss2.Auth(settings.OSS_ACCESS_KEY_ID, settings.OSS_ACCESS_KEY_SECRET)
    bucket = oss2.Bucket(auth, settings.OSS_ENDPOINT, settings.OSS_BUCKET_NAME)
except Exception as e:
    print(f"OSS init failed: {e}")
    bucket = None


MEDIA_DIRS = {
    "image": "images",
    "video": "videos",
    "audio": "audio",
    "text": "texts",
    "temp": "temp",
    "other": "others",
}


def _safe_extension(filename: str, content_type: str, default: str = "bin") -> str:
    name = str(filename or "")
    if "." in name:
        ext = name.rsplit(".", 1)[-1].strip().lower()
        if ext and ext.replace("_", "").replace("-", "").isalnum() and len(ext) <= 8:
            return ext
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
    if "plain" in lowered:
        return "txt"
    return default


def normalize_storage_media_type(content_type: str = "", media_type: str = "") -> str:
    explicit = str(media_type or "").strip().lower()
    if explicit in {"image", "video", "audio", "text", "temp", "other"}:
        return explicit
    lowered = str(content_type or "").strip().lower()
    if lowered.startswith("image/"):
        return "image"
    if lowered.startswith("video/"):
        return "video"
    if lowered.startswith("audio/"):
        return "audio"
    if lowered.startswith("text/"):
        return "text"
    return "other"


def build_user_object_key(
    *,
    owner_user_id: int | None,
    content_type: str = "",
    filename: str = "",
    media_type: str = "",
    temp_media_type: str = "",
) -> str:
    ext = _safe_extension(filename, content_type)
    now = datetime.utcnow()
    normalized = normalize_storage_media_type(content_type, media_type)
    directory = MEDIA_DIRS.get(normalized, "others")
    if owner_user_id:
        with Session(engine) as session:
            namespace = ensure_user_storage_namespace(session, int(owner_user_id))
        if normalized == "temp":
            temp_dir = MEDIA_DIRS.get(normalize_storage_media_type(media_type=temp_media_type), "others")
            return f"users/{namespace}/temp/{temp_dir}/{now:%Y/%m}/{uuid.uuid4().hex}.{ext}"
        return f"users/{namespace}/{directory}/{now:%Y/%m}/{uuid.uuid4().hex}.{ext}"
    return f"system/legacy/{directory}/{now:%Y/%m}/{uuid.uuid4().hex}.{ext}"


def url_from_object_key(object_key: str) -> str:
    return f"{settings.OSS_DOMAIN}/{str(object_key or '').lstrip('/')}"


def object_key_from_url(url: str) -> str:
    source = str(url or "").strip()
    if not source:
        return ""
    domain = str(settings.OSS_DOMAIN or "").strip().rstrip("/")
    if domain and source.startswith(f"{domain}/"):
        return source[len(domain) + 1:].split("?", 1)[0]
    parsed = urlparse(source)
    if settings.OSS_BUCKET_NAME and parsed.netloc.startswith(f"{settings.OSS_BUCKET_NAME}."):
        return parsed.path.lstrip("/").split("?", 1)[0]
    return ""


def _resolve_panel_owner_user_id(session: Session, panel: Panel | None) -> int | None:
    if not panel:
        return None
    episode = session.get(Episode, panel.episode_id)
    script = session.get(Script, episode.script_id) if episode else None
    if not script:
        return None
    link = session.exec(
        select(TeamMemberLink)
        .where(TeamMemberLink.team_id == script.team_id)
        .order_by(TeamMemberLink.joined_at.asc())
    ).first()
    return int(link.user_id) if link and link.user_id else None


def _content_length(headers) -> int:
    try:
        return int(headers.get("Content-Length") or 0)
    except Exception:
        return 0


def _oss_object_size(object_key: str) -> int:
    if not bucket or not object_key:
        return 0
    try:
        meta = bucket.head_object(object_key)
        return int(getattr(meta, "content_length", 0) or 0)
    except Exception:
        return 0


def _upload_headers(content_type: str) -> dict:
    return {
        "Content-Type": content_type or "application/octet-stream",
        "x-oss-object-acl": "public-read",
    }


def _record_storage_object(
    *,
    owner_user_id: int | None,
    object_key: str,
    media_type: str,
    file_size: int,
    source_type: str | None = None,
    source_id: int | None = None,
    old_object_key: str | None = None,
    release_reserved: bool = True,
    reserved_size: int | None = None,
) -> None:
    if not owner_user_id:
        return
    with Session(engine) as session:
        commit_storage_object(
            session,
            owner_user_id=int(owner_user_id),
            object_key=object_key,
            media_type=media_type,
            file_size=int(file_size or 0),
            source_type=source_type,
            source_id=source_id,
            old_object_key=old_object_key,
            release_reserved=release_reserved,
            reserved_size=reserved_size,
        )


def _reserve(owner_user_id: int | None, file_size: int) -> None:
    if not owner_user_id:
        return
    with Session(engine) as session:
        reserve_storage_bytes(session, int(owner_user_id), int(file_size or 0))


def _release(owner_user_id: int | None, file_size: int) -> None:
    if not owner_user_id:
        return
    with Session(engine) as session:
        release_storage_reservation(session, int(owner_user_id), int(file_size or 0))


def _reserve_known_size(owner_user_id: int | None, size: int) -> int:
    known_size = max(int(size or 0), 0)
    if known_size > 0:
        _reserve(owner_user_id, known_size)
    return known_size


def _async_upload_to_oss(panel_id: int, url: str, owner_user_id: int | None = None):
    """Persist a generated panel image from a provider URL into OSS."""
    if not bucket:
        print("OSS is not configured; panel image persist skipped")
        return
    try:
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "image/png").split(";")[0]
            if owner_user_id is None:
                with Session(engine) as owner_session:
                    owner_user_id = _resolve_panel_owner_user_id(owner_session, owner_session.get(Panel, panel_id))
            reserved_size = _reserve_known_size(owner_user_id, _content_length(resp.headers))
            object_name = build_user_object_key(
                owner_user_id=owner_user_id,
                content_type=content_type,
                filename="panel-image",
                media_type="image",
            )
            try:
                result = bucket.put_object(object_name, resp.iter_content(chunk_size=1024 * 1024), headers=_upload_headers(content_type))
                if result.status != 200:
                    raise RuntimeError(f"OSS panel image upload failed with status {result.status}")
            except Exception:
                _release(owner_user_id, reserved_size)
                raise
            final_url = url_from_object_key(object_name)
            thumbnail_url = build_oss_thumbnail_url(final_url)
            with Session(engine) as session:
                panel = session.get(Panel, panel_id)
                if panel:
                    previous_image_url = str(panel.image_url or "").strip()
                    panel.file_url = final_url
                    panel.image_url = final_url
                    panel.thumbnail_url = thumbnail_url
                    panel.transfer_status = 3
                    history = json.loads(panel.history_urls_json) if panel.history_urls_json else []
                    history = [final_url if h == url else h for h in history]
                    if previous_image_url and previous_image_url != final_url:
                        history = [final_url if h == previous_image_url else h for h in history]
                    if not history:
                        history.append(final_url)
                    deduped = []
                    seen = set()
                    for item in history:
                        value = str(item or "").strip()
                        if not value or value in seen:
                            continue
                        seen.add(value)
                        deduped.append(value)
                    panel.history_urls_json = json.dumps(deduped)
                    session.add(panel)
                    session.commit()
            _record_storage_object(
                owner_user_id=owner_user_id,
                object_key=object_name,
                media_type="image",
                file_size=_oss_object_size(object_name) or reserved_size,
                source_type="panel_image",
                source_id=panel_id,
                release_reserved=reserved_size > 0,
                reserved_size=reserved_size,
            )
    except Exception as e:
        print(f"Panel image OSS persist failed: {e}")


def upload_base64_to_oss(
    base64_data: str,
    *,
    owner_user_id: int | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
) -> str:
    if not bucket:
        raise Exception("OSS is not configured")
    image_bytes = b""
    try:
        if "," in base64_data:
            header, encoded = base64_data.split(",", 1)
        else:
            encoded = base64_data
            header = "data:image/png;base64"
        image_bytes = base64.b64decode(encoded)
        content_type = header.split(";")[0].replace("data:", "") if "data:" in header else "image/png"
        object_name = build_user_object_key(
            owner_user_id=owner_user_id,
            content_type=content_type,
            filename="base64-image",
            media_type="image",
        )
        _reserve(owner_user_id, len(image_bytes))
        result = bucket.put_object(object_name, image_bytes, headers=_upload_headers(content_type))
        if result.status != 200:
            raise Exception(f"OSS upload failed with status {result.status}")
        _record_storage_object(
            owner_user_id=owner_user_id,
            object_key=object_name,
            media_type="image",
            file_size=len(image_bytes),
            source_type=source_type,
            source_id=source_id,
        )
        return url_from_object_key(object_name)
    except Exception:
        _release(owner_user_id, len(image_bytes))
        raise


def upload_bytes_to_oss_with_meta(
    content: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    object_name: str = "",
    *,
    owner_user_id: int | None = None,
    media_type: str = "",
    source_type: str | None = None,
    source_id: int | None = None,
) -> dict:
    if not bucket:
        raise Exception("OSS is not configured")
    normalized_media_type = normalize_storage_media_type(content_type, media_type)
    if not object_name:
        object_name = build_user_object_key(
            owner_user_id=owner_user_id,
            content_type=content_type,
            filename=filename,
            media_type=normalized_media_type,
        )
    _reserve(owner_user_id, len(content))
    try:
        result = bucket.put_object(object_name, content, headers=_upload_headers(content_type))
        if result.status != 200:
            raise Exception(f"OSS upload failed with status {result.status}")
        file_url = url_from_object_key(object_name)
        thumbnail_url = ""
        if content_type.startswith("image/"):
            thumbnail_url = build_oss_thumbnail_url(file_url)
        elif content_type.startswith("video/"):
            thumbnail_url = build_oss_video_snapshot_url(file_url)
        _record_storage_object(
            owner_user_id=owner_user_id,
            object_key=object_name,
            media_type=normalized_media_type,
            file_size=len(content),
            source_type=source_type,
            source_id=source_id,
        )
        return {
            "file_url": file_url,
            "thumbnail_url": thumbnail_url,
            "storage_object_key": object_name,
            "original_filename": filename,
            "mime_type": content_type,
            "file_size": len(content),
        }
    except Exception:
        _release(owner_user_id, len(content))
        raise


def upload_bytes_to_oss(
    content: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    *,
    owner_user_id: int | None = None,
) -> str:
    return upload_bytes_to_oss_with_meta(content, filename, content_type, owner_user_id=owner_user_id)["file_url"]


def delete_object_from_oss(object_name: str) -> bool:
    target = str(object_name or "").strip()
    if not target or not bucket:
        return False
    try:
        bucket.delete_object(target)
        with Session(engine) as session:
            mark_storage_object_deleted(session, target)
        return True
    except Exception as e:
        print(f"OSS delete failed: {e}")
        return False


def is_oss_url(url: str) -> bool:
    source = str(url or "").strip()
    if not source:
        return False
    if settings.OSS_DOMAIN and settings.OSS_DOMAIN in source:
        return True
    return ("aliyuncs.com" in source) or ("oss-" in source)


def _guess_remote_filename(url: str, content_type: str) -> str:
    path = urlparse(str(url or "").strip()).path
    basename = path.rsplit("/", 1)[-1] if path else ""
    if basename and "." in basename:
        return basename
    return f"remote_{uuid.uuid4().hex}.{_safe_extension('', content_type)}"


def upload_remote_file_to_oss_with_meta(
    url: str,
    *,
    owner_user_id: int | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
) -> dict:
    source = str(url or "").strip()
    if not source:
        raise Exception("remote file URL is empty")
    with requests.get(source, stream=True, timeout=120) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "application/octet-stream").split(";")[0].strip().lower()
        content = resp.content
    meta = upload_bytes_to_oss_with_meta(
        content,
        filename=_guess_remote_filename(source, content_type),
        content_type=content_type or "application/octet-stream",
        owner_user_id=owner_user_id,
        source_type=source_type,
        source_id=source_id,
    )
    if content_type.startswith("video/"):
        meta["thumbnail_url"] = build_oss_video_snapshot_url(meta.get("file_url") or "")
    elif not content_type.startswith("image/"):
        meta["thumbnail_url"] = ""
    return meta


def build_oss_thumbnail_url(url: str, *, width: int = 400, height: int = 400) -> str:
    source = str(url or "").strip()
    if not source:
        return ""
    if "x-oss-process=" in source:
        return source
    separator = "&" if "?" in source else "?"
    return f"{source}{separator}x-oss-process=image/resize,m_lfit,w_{width},h_{height}"


def build_oss_video_snapshot_url(url: str, *, width: int = 400, height: int = 225, time_ms: int = 1000) -> str:
    source = str(url or "").strip()
    if not source:
        return ""
    if "x-oss-process=" in source:
        return source
    oss_domain = str(settings.OSS_DOMAIN or "").strip()
    if "aliyuncs.com" not in source and (not oss_domain or oss_domain not in source):
        return ""
    separator = "&" if "?" in source else "?"
    return f"{source}{separator}x-oss-process=video/snapshot,t_{time_ms},f_jpg,w_{width},h_{height},m_fast"


def upload_remote_image_to_oss(
    url: str,
    *,
    object_prefix: str = "resources/asset",
    owner_user_id: int | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
) -> str:
    if not bucket:
        raise Exception("OSS is not configured")
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "image/png").split(";")[0]
        reserved_size = _reserve_known_size(owner_user_id, _content_length(resp.headers))
        object_name = build_user_object_key(
            owner_user_id=owner_user_id,
            content_type=content_type,
            filename=object_prefix,
            media_type="image",
        )
        try:
            result = bucket.put_object(object_name, resp.iter_content(chunk_size=1024 * 1024), headers=_upload_headers(content_type))
            if result.status != 200:
                raise Exception(f"OSS upload failed with status {result.status}")
        except Exception:
            _release(owner_user_id, reserved_size)
            raise
        _record_storage_object(
            owner_user_id=owner_user_id,
            object_key=object_name,
            media_type="image",
            file_size=_oss_object_size(object_name) or reserved_size,
            source_type=source_type,
            source_id=source_id,
            release_reserved=reserved_size > 0,
            reserved_size=reserved_size,
        )
        return url_from_object_key(object_name)


def _async_upload_video_to_oss(panel_id: int, url: str, owner_user_id: int | None = None):
    """Persist a generated panel video from a provider URL into OSS."""
    if not bucket:
        print("OSS is not configured; panel video persist skipped")
        return
    try:
        with requests.get(url, stream=True, timeout=120) as resp:
            resp.raise_for_status()
            content_type = resp.headers.get("Content-Type", "video/mp4").split(";")[0]
            if owner_user_id is None:
                with Session(engine) as owner_session:
                    owner_user_id = _resolve_panel_owner_user_id(owner_session, owner_session.get(Panel, panel_id))
            reserved_size = _reserve_known_size(owner_user_id, _content_length(resp.headers))
            object_name = build_user_object_key(
                owner_user_id=owner_user_id,
                content_type=content_type,
                filename="panel-video",
                media_type="video",
            )
            try:
                result = bucket.put_object(object_name, resp.iter_content(chunk_size=2048 * 1024), headers=_upload_headers(content_type))
                if result.status != 200:
                    raise RuntimeError(f"OSS panel video upload failed with status {result.status}")
            except Exception:
                _release(owner_user_id, reserved_size)
                raise
            final_url = url_from_object_key(object_name)
            thumbnail_url = build_oss_video_snapshot_url(final_url)
            with Session(engine) as session:
                panel = session.get(Panel, panel_id)
                if panel:
                    previous_video_url = str(panel.video_url or "").strip()
                    panel.video_url = final_url
                    panel.video_thumbnail_url = thumbnail_url or None
                    panel.video_history_json = upsert_panel_video_history(
                        panel.video_history_json,
                        preview_url=final_url,
                        thumbnail_url=thumbnail_url,
                        replace_url=previous_video_url or url,
                    )
                    session.add(panel)
                    session.commit()
            _record_storage_object(
                owner_user_id=owner_user_id,
                object_key=object_name,
                media_type="video",
                file_size=_oss_object_size(object_name) or reserved_size,
                source_type="panel_video",
                source_id=panel_id,
                release_reserved=reserved_size > 0,
                reserved_size=reserved_size,
            )
    except Exception as e:
        print(f"Panel video OSS persist failed: {e}")
