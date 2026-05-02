from __future__ import annotations

from datetime import datetime
import json
from typing import Iterable

from sqlmodel import Session, select

from models import EpisodeAssetLink, Script, SharedResource, SharedResourceVersion, StoryboardShotAssetLink, Team, TeamMemberLink
from services.access_service import require_resource_team_access, require_resource_version_team_access, require_script_team_access
from services.oss_service import (
    build_oss_thumbnail_url,
    is_oss_url,
    upload_base64_to_oss,
    upload_bytes_to_oss_with_meta,
    upload_remote_image_to_oss,
)

def _normalize_aliases(aliases: Iterable[str] | None) -> str | None:
    if not aliases:
        return None
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in aliases:
        if raw is None:
            continue
        name = str(raw).strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(name)
    if not cleaned:
        return None
    return json.dumps(cleaned, ensure_ascii=False)


def _normalize_resource_type(resource_type) -> str:
    return resource_type.value if hasattr(resource_type, "value") else str(resource_type)


def _serialize_aliases(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _resolve_resource_urls(
    file_url: str,
    *,
    owner_user_id: int | None = None,
    source_type: str | None = None,
    source_id: int | None = None,
) -> tuple[str, str | None]:
    source = (file_url or "").strip()
    if not source:
        return "", None

    if source.startswith("data:image/"):
        original_url = upload_base64_to_oss(
            source,
            owner_user_id=owner_user_id,
            source_type=source_type,
            source_id=source_id,
        )
        return original_url, build_oss_thumbnail_url(original_url)

    if source.startswith("http://") or source.startswith("https://"):
        if "x-oss-process=" in source:
            original_url = source.split("?x-oss-process=")[0]
            return original_url, build_oss_thumbnail_url(original_url)
        if "aliyuncs.com" in source or "oss-" in source or "OSS_DOMAIN" in source:
            return source, build_oss_thumbnail_url(source)

    return source, None


def _resolve_script_owner_user_id(session: Session, script_id: int | None) -> int | None:
    if not script_id:
        return None
    script = session.get(Script, script_id)
    if not script:
        return None
    link = session.exec(
        select(TeamMemberLink)
        .where(TeamMemberLink.team_id == script.team_id)
        .order_by(TeamMemberLink.joined_at.asc())
    ).first()
    return int(link.user_id) if link and link.user_id else None


def serialize_resource(resource: SharedResource) -> dict:
    payload = resource.dict()
    payload["aliases"] = _serialize_aliases(resource.aliases)
    return payload


def upload_shared_resource_file(content: bytes, filename: str, content_type: str = "application/octet-stream", *, owner_user_id: int | None = None) -> dict:
    meta = upload_bytes_to_oss_with_meta(
        content,
        filename,
        content_type,
        owner_user_id=owner_user_id,
        source_type="shared_resource_upload",
    )
    meta["thumbnail_url"] = meta.get("thumbnail_url") or build_oss_thumbnail_url(meta["file_url"])
    return meta


def create_resource(
    session: Session,
    team: Team,
    *,
    script_id: int,
    resource_type,
    name: str,
    file_url: str | None,
    trigger_word: str | None,
    aliases: list[str] | None,
    description: str | None,
    storage_object_key: str | None = None,
    original_filename: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
    owner_user_id: int | None = None,
) -> SharedResource:
    require_script_team_access(session, team, script_id)
    resolved_owner_user_id = owner_user_id or _resolve_script_owner_user_id(session, script_id)
    file_url, thumbnail_url = _resolve_resource_urls(
        file_url or "",
        owner_user_id=resolved_owner_user_id,
        source_type="shared_resource_inline",
    )
    resource = SharedResource(
        script_id=script_id,
        resource_type=_normalize_resource_type(resource_type),
        name=name,
        file_url=file_url,
        thumbnail_url=thumbnail_url,
        storage_object_key=storage_object_key,
        original_filename=original_filename,
        mime_type=mime_type,
        file_size=file_size,
        trigger_word=trigger_word,
        aliases=_normalize_aliases(aliases),
        description=description,
        updated_at=datetime.utcnow(),
    )
    session.add(resource)
    session.commit()
    session.refresh(resource)
    return resource


def list_resources(session: Session, team: Team, script_id: int, resource_type: str | None = None):
    require_script_team_access(session, team, script_id)
    query = select(SharedResource).where(SharedResource.script_id == script_id)
    if resource_type:
        query = query.where(SharedResource.resource_type == resource_type)
    query = query.order_by(SharedResource.created_at.desc())
    return session.exec(query).all()


def update_resource(
    session: Session,
    team: Team,
    resource_id: int,
    *,
    name: str,
    file_url: str | None,
    trigger_word: str | None,
    aliases: list[str] | None,
    description: str | None,
    storage_object_key: str | None = None,
    original_filename: str | None = None,
    mime_type: str | None = None,
    file_size: int | None = None,
    owner_user_id: int | None = None,
) -> SharedResource:
    resource = require_resource_team_access(session, team, resource_id)
    resolved_owner_user_id = owner_user_id or _resolve_script_owner_user_id(session, resource.script_id)
    file_url, thumbnail_url = _resolve_resource_urls(
        file_url or "",
        owner_user_id=resolved_owner_user_id,
        source_type="shared_resource_inline",
        source_id=resource_id,
    )
    resource.name = name
    resource.trigger_word = trigger_word
    if aliases is not None:
        resource.aliases = _normalize_aliases(aliases)
    resource.description = description
    if file_url:
        resource.file_url = file_url
        resource.thumbnail_url = thumbnail_url
    if storage_object_key is not None:
        resource.storage_object_key = storage_object_key
    if original_filename is not None:
        resource.original_filename = original_filename
    if mime_type is not None:
        resource.mime_type = mime_type
    if file_size is not None:
        resource.file_size = file_size
    resource.updated_at = datetime.utcnow()
    session.add(resource)
    session.commit()
    session.refresh(resource)
    return resource


def delete_resource(session: Session, team: Team, resource_id: int) -> None:
    resource = require_resource_team_access(session, team, resource_id)
    for link in session.exec(select(EpisodeAssetLink).where(EpisodeAssetLink.resource_id == resource_id)).all():
        session.delete(link)
    for link in session.exec(select(StoryboardShotAssetLink).where(StoryboardShotAssetLink.resource_id == resource_id)).all():
        session.delete(link)
    resource.updated_at = datetime.utcnow()
    session.delete(resource)
    session.commit()


def _ensure_current_resource_file_version(session: Session, resource: SharedResource) -> None:
    current_url = str(resource.file_url or "").strip()
    if not current_url or not is_oss_url(current_url):
        return
    existing = session.exec(
        select(SharedResourceVersion).where(
            SharedResourceVersion.resource_id == resource.id,
            SharedResourceVersion.file_url == current_url,
        )
    ).first()
    if existing:
        return

    defaults = session.exec(
        select(SharedResourceVersion).where(
            SharedResourceVersion.resource_id == resource.id,
            SharedResourceVersion.is_default == True,
        )
    ).all()
    for item in defaults:
        item.is_default = False
        session.add(item)

    session.add(
        SharedResourceVersion(
            resource_id=resource.id,
            version_tag=f"current-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            appearance_prompt=resource.description,
            file_url=current_url,
            trigger_word=resource.trigger_word,
            start_seq=None,
            end_seq=None,
            is_default=True,
        )
    )
    session.commit()


def list_resource_versions(session: Session, team: Team, resource_id: int):
    resource = require_resource_team_access(session, team, resource_id)
    _ensure_current_resource_file_version(session, resource)
    statement = (
        select(SharedResourceVersion)
        .where(SharedResourceVersion.resource_id == resource_id)
        .order_by(SharedResourceVersion.created_at.desc())
    )
    return session.exec(statement).all()


def create_resource_version(
    session: Session,
    team: Team,
    *,
    resource_id: int,
    version_tag: str,
    appearance_prompt: str | None,
    file_url: str | None,
    trigger_word: str | None,
    start_seq: int | None,
    end_seq: int | None,
    is_default: bool,
    owner_user_id: int | None = None,
) -> SharedResourceVersion:
    resource = require_resource_team_access(session, team, resource_id)
    file_url, _thumbnail_url = _resolve_resource_urls(
        file_url or "",
        owner_user_id=owner_user_id or _resolve_script_owner_user_id(session, resource.script_id),
        source_type="shared_resource_version_inline",
        source_id=resource_id,
    )

    if is_default:
        existing_defaults = session.exec(
            select(SharedResourceVersion).where(
                SharedResourceVersion.resource_id == resource_id,
                SharedResourceVersion.is_default == True,
            )
        ).all()
        for item in existing_defaults:
            item.is_default = False
            session.add(item)

    version = SharedResourceVersion(
        resource_id=resource_id,
        version_tag=version_tag,
        appearance_prompt=appearance_prompt,
        file_url=file_url,
        trigger_word=trigger_word,
        start_seq=start_seq,
        end_seq=end_seq,
        is_default=is_default,
    )
    session.add(version)

    if is_default:
        if trigger_word is not None:
            resource.trigger_word = trigger_word
        if file_url:
            resource.file_url = file_url
            resource.thumbnail_url = build_oss_thumbnail_url(file_url) if "http" in file_url else resource.thumbnail_url
        resource.updated_at = datetime.utcnow()
        session.add(resource)

    session.commit()
    session.refresh(version)
    return version


def create_uploaded_resource_version(
    session: Session,
    team: Team,
    *,
    resource_id: int,
    appearance_prompt: str | None = None,
) -> SharedResourceVersion:
    resource = require_resource_team_access(session, team, resource_id)
    existing_versions = session.exec(
        select(SharedResourceVersion).where(SharedResourceVersion.resource_id == resource_id)
    ).all()
    version_tag = f"v{len(existing_versions) + 1}"
    return create_resource_version(
        session,
        team,
        resource_id=resource_id,
        version_tag=version_tag,
        appearance_prompt=appearance_prompt,
        file_url=resource.file_url,
        trigger_word=resource.trigger_word,
        start_seq=None,
        end_seq=None,
        is_default=True,
    )


def update_resource_version(
    session: Session,
    team: Team,
    version_id: int,
    *,
    version_tag: str | None = None,
    appearance_prompt: str | None = None,
    file_url: str | None = None,
    trigger_word: str | None = None,
    start_seq: int | None = None,
    end_seq: int | None = None,
    is_default: bool | None = None,
    owner_user_id: int | None = None,
) -> SharedResourceVersion:
    version = require_resource_version_team_access(session, team, version_id)
    resource = require_resource_team_access(session, team, version.resource_id)

    resolved_file_url = None
    if file_url is not None:
        resolved_file_url, _thumbnail_url = _resolve_resource_urls(
            file_url,
            owner_user_id=owner_user_id or _resolve_script_owner_user_id(session, resource.script_id),
            source_type="shared_resource_version_inline",
            source_id=resource.id,
        )

    if version_tag is not None:
        version.version_tag = version_tag
    if appearance_prompt is not None:
        version.appearance_prompt = appearance_prompt
    if resolved_file_url is not None:
        version.file_url = resolved_file_url
    if trigger_word is not None:
        version.trigger_word = trigger_word
    if start_seq is not None:
        version.start_seq = start_seq
    if end_seq is not None:
        version.end_seq = end_seq

    if is_default is not None and is_default != version.is_default:
        if is_default:
            existing_defaults = session.exec(
                select(SharedResourceVersion).where(
                    SharedResourceVersion.resource_id == version.resource_id,
                    SharedResourceVersion.is_default == True,
                )
            ).all()
            for item in existing_defaults:
                item.is_default = False
                session.add(item)
        version.is_default = is_default

    if version.is_default:
        if version.trigger_word:
            resource.trigger_word = version.trigger_word
        if version.file_url:
            resource.file_url = version.file_url
            resource.thumbnail_url = build_oss_thumbnail_url(version.file_url)
        resource.updated_at = datetime.utcnow()
        session.add(resource)

    session.add(version)
    session.commit()
    session.refresh(version)
    return version


def delete_resource_version(
    session: Session,
    team: Team,
    version_id: int,
) -> dict:
    version = require_resource_version_team_access(session, team, version_id)
    resource = require_resource_team_access(session, team, version.resource_id)

    was_default = bool(version.is_default)
    resource_id = version.resource_id
    session.delete(version)
    session.flush()

    next_default = None
    if was_default:
        remaining = session.exec(
            select(SharedResourceVersion)
            .where(SharedResourceVersion.resource_id == resource_id)
            .order_by(SharedResourceVersion.created_at.desc(), SharedResourceVersion.id.desc())
        ).all()
        if remaining:
            next_default = remaining[0]
            next_default.is_default = True
            session.add(next_default)
            if next_default.trigger_word:
                resource.trigger_word = next_default.trigger_word
            if next_default.file_url:
                resource.file_url = next_default.file_url
                resource.thumbnail_url = build_oss_thumbnail_url(next_default.file_url)
        else:
            resource.file_url = ""
            resource.thumbnail_url = None

    resource.updated_at = datetime.utcnow()
    session.add(resource)
    session.commit()
    session.refresh(resource)
    if next_default:
        session.refresh(next_default)
    return {
        "resource_id": resource.id,
        "deleted_version_id": version_id,
        "next_default_version_id": next_default.id if next_default else None,
    }


def apply_generated_resource_image(
    session: Session,
    *,
    resource_id: int,
    prompt: str,
    file_url: str,
    version_tag: str | None = None,
    start_seq: int | None = None,
    end_seq: int | None = None,
    is_default: bool = True,
) -> SharedResourceVersion:
    resource = session.get(SharedResource, resource_id)
    if not resource:
        raise ValueError("resource not found")

    persisted_file_url = upload_remote_image_to_oss(
        file_url,
        owner_user_id=_resolve_script_owner_user_id(session, resource.script_id),
        source_type="shared_resource_generated_image",
        source_id=resource_id,
    )
    thumbnail_url = build_oss_thumbnail_url(persisted_file_url)

    if is_default:
        existing_defaults = session.exec(
            select(SharedResourceVersion).where(
                SharedResourceVersion.resource_id == resource_id,
                SharedResourceVersion.is_default == True,
            )
        ).all()
        for item in existing_defaults:
            item.is_default = False
            session.add(item)

        resource.file_url = persisted_file_url
        resource.thumbnail_url = thumbnail_url
        resource.updated_at = datetime.utcnow()
        session.add(resource)

    version = SharedResourceVersion(
        resource_id=resource_id,
        version_tag=version_tag or f"gen-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
        appearance_prompt=prompt,
        file_url=persisted_file_url,
        trigger_word=resource.trigger_word,
        start_seq=start_seq,
        end_seq=end_seq,
        is_default=is_default,
    )
    session.add(version)
    session.commit()
    session.refresh(version)
    return version
