from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from core.config import settings
from models import MembershipPlan, StorageObject, User, UserMembership, UserMembershipOverride, UserStorageUsage

GB = 1024 * 1024 * 1024
STORAGE_STATUS_ACTIVE = "active"
STORAGE_STATUS_MIGRATED = "migrated"
STORAGE_STATUS_PENDING_OLD_DELETE = "pending_old_delete"
STORAGE_STATUS_DELETED = "deleted"
COUNTED_STORAGE_STATUSES = [STORAGE_STATUS_ACTIVE, STORAGE_STATUS_MIGRATED, STORAGE_STATUS_PENDING_OLD_DELETE]


def _now() -> datetime:
    return datetime.utcnow()


def _quota_bytes_from_gb(value: int) -> int:
    return int(value) * GB


def default_free_quota_bytes() -> int:
    return _quota_bytes_from_gb(settings.STORAGE_FREE_QUOTA_GB)


def default_member_quota_bytes() -> int:
    return _quota_bytes_from_gb(settings.STORAGE_MEMBER_QUOTA_GB)


def generate_storage_namespace() -> str:
    return f"u_{secrets.token_urlsafe(18).replace('-', '').replace('_', '')[:24]}"


def ensure_user_storage_namespace(session: Session, user_id: int) -> str:
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    if user.storage_namespace:
        return user.storage_namespace

    for _ in range(8):
        namespace = generate_storage_namespace()
        existing = session.exec(select(User).where(User.storage_namespace == namespace)).first()
        if existing:
            continue
        user.storage_namespace = namespace
        session.add(user)
        session.commit()
        session.refresh(user)
        return namespace
    raise HTTPException(status_code=500, detail="failed to allocate storage namespace")


def get_or_create_usage(session: Session, user_id: int) -> UserStorageUsage:
    usage = session.get(UserStorageUsage, user_id)
    if usage:
        return usage
    usage = UserStorageUsage(user_id=user_id, used_bytes=0, reserved_bytes=0, quota_bytes_snapshot=get_effective_quota_bytes(session, user_id))
    session.add(usage)
    session.commit()
    session.refresh(usage)
    return usage


def _lock_usage_row(session: Session, user_id: int) -> UserStorageUsage:
    get_or_create_usage(session, user_id)
    usage = session.exec(
        select(UserStorageUsage)
        .where(UserStorageUsage.user_id == user_id)
        .with_for_update()
    ).first()
    if not usage:
        raise HTTPException(status_code=500, detail="failed to lock storage usage")
    return usage


def _active_user_membership_plan(session: Session, user_id: int) -> Optional[MembershipPlan]:
    now = _now()
    membership = session.exec(
        select(UserMembership)
        .where(UserMembership.user_id == user_id)
        .where(UserMembership.enabled == True)
        .order_by(UserMembership.id.desc())
    ).first()
    if not membership:
        return None
    if membership.starts_at and membership.starts_at > now:
        return None
    if membership.expires_at and membership.expires_at < now:
        return None
    return session.get(MembershipPlan, membership.plan_id)


def get_effective_quota_bytes(session: Session, user_id: int) -> int:
    override = session.exec(select(UserMembershipOverride).where(UserMembershipOverride.user_id == user_id)).first()
    if override and override.enabled and override.storage_quota_bytes is not None:
        return max(int(override.storage_quota_bytes or 0), 0)

    plan = _active_user_membership_plan(session, user_id)
    if plan and plan.storage_quota_bytes is not None:
        return max(int(plan.storage_quota_bytes or 0), 0)

    user = session.get(User, user_id)
    tier = str(getattr(user, "vip_tier", "") or "").lower()
    if tier and tier != "free":
        return default_member_quota_bytes()
    return default_free_quota_bytes()


def reserve_storage_bytes(session: Session, user_id: int, size_bytes: int, *, enforce: Optional[bool] = None) -> Dict[str, Any]:
    requested = max(int(size_bytes or 0), 0)
    usage = _lock_usage_row(session, user_id)
    quota = get_effective_quota_bytes(session, user_id)
    usage.quota_bytes_snapshot = quota
    should_enforce = settings.STORAGE_QUOTA_ENFORCE if enforce is None else bool(enforce)
    projected = int(usage.used_bytes or 0) + int(usage.reserved_bytes or 0) + requested
    if should_enforce and projected > quota:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "storage_quota_exceeded",
                "message": "存储容量不足，请升级会员或清理文件",
                "quota_bytes": quota,
                "used_bytes": int(usage.used_bytes or 0),
                "reserved_bytes": int(usage.reserved_bytes or 0),
                "required_bytes": requested,
            },
        )
    usage.reserved_bytes = int(usage.reserved_bytes or 0) + requested
    usage.updated_at = _now()
    session.add(usage)
    session.commit()
    return {
        "reserved": requested,
        "quota_bytes": quota,
        "enforced": should_enforce,
    }


def release_storage_reservation(session: Session, user_id: int, size_bytes: int) -> None:
    usage = _lock_usage_row(session, user_id)
    requested = max(int(size_bytes or 0), 0)
    usage.reserved_bytes = max(int(usage.reserved_bytes or 0) - requested, 0)
    usage.updated_at = _now()
    session.add(usage)
    session.commit()


def commit_storage_object(
    session: Session,
    *,
    owner_user_id: int,
    object_key: str,
    media_type: str,
    file_size: int,
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
    old_object_key: Optional[str] = None,
    status: str = STORAGE_STATUS_ACTIVE,
    release_reserved: bool = True,
    reserved_size: Optional[int] = None,
) -> StorageObject:
    now = _now()
    existing = session.exec(select(StorageObject).where(StorageObject.object_key == object_key)).first()
    old_status = existing.status if existing else None
    old_size = int(existing.file_size or 0) if existing else 0
    if existing:
        existing.owner_user_id = owner_user_id
        existing.media_type = media_type
        existing.file_size = int(file_size or existing.file_size or 0)
        existing.source_type = source_type or existing.source_type
        existing.source_id = source_id if source_id is not None else existing.source_id
        existing.old_object_key = old_object_key or existing.old_object_key
        existing.status = status or existing.status
        existing.updated_at = now
        obj = existing
    else:
        obj = StorageObject(
            owner_user_id=owner_user_id,
            object_key=object_key,
            old_object_key=old_object_key,
            media_type=media_type,
            file_size=int(file_size or 0),
            status=status,
            source_type=source_type,
            source_id=source_id,
            created_at=now,
            updated_at=now,
        )
    session.add(obj)

    usage = _lock_usage_row(session, owner_user_id)
    size = int(obj.file_size or 0)
    existing_counted = bool(existing and old_status in COUNTED_STORAGE_STATUSES)
    next_counted = (status or STORAGE_STATUS_ACTIVE) in COUNTED_STORAGE_STATUSES
    if not existing and next_counted:
        usage.used_bytes = int(usage.used_bytes or 0) + size
    elif existing_counted and next_counted:
        usage.used_bytes = max(int(usage.used_bytes or 0) + size - old_size, 0)
    elif existing_counted and not next_counted:
        usage.used_bytes = max(int(usage.used_bytes or 0) - old_size, 0)
    elif not existing_counted and next_counted:
        usage.used_bytes = int(usage.used_bytes or 0) + size
    if release_reserved:
        release_size = size if reserved_size is None else max(int(reserved_size or 0), 0)
        usage.reserved_bytes = max(int(usage.reserved_bytes or 0) - release_size, 0)
    usage.quota_bytes_snapshot = get_effective_quota_bytes(session, owner_user_id)
    usage.updated_at = now
    session.add(usage)
    session.commit()
    session.refresh(obj)
    return obj


def mark_old_object_deleted(session: Session, object_key: str) -> None:
    objects = session.exec(select(StorageObject).where(StorageObject.old_object_key == object_key)).all()
    if not objects:
        return
    now = _now()
    for obj in objects:
        obj.old_deleted_at = now
        obj.updated_at = now
        if obj.status == STORAGE_STATUS_PENDING_OLD_DELETE:
            obj.status = STORAGE_STATUS_MIGRATED
        session.add(obj)
    session.commit()


def mark_pending_old_delete(session: Session, object_key: str) -> None:
    objects = session.exec(select(StorageObject).where(StorageObject.old_object_key == object_key)).all()
    if not objects:
        return
    now = _now()
    for obj in objects:
        obj.status = STORAGE_STATUS_PENDING_OLD_DELETE
        obj.updated_at = now
        session.add(obj)
    session.commit()


def mark_storage_object_deleted(session: Session, object_key: str) -> None:
    obj = session.exec(select(StorageObject).where(StorageObject.object_key == object_key)).first()
    if not obj:
        return
    was_counted = obj.status in COUNTED_STORAGE_STATUSES
    obj.status = STORAGE_STATUS_DELETED
    obj.updated_at = _now()
    session.add(obj)
    if was_counted:
        usage = _lock_usage_row(session, int(obj.owner_user_id))
        usage.used_bytes = max(int(usage.used_bytes or 0) - int(obj.file_size or 0), 0)
        usage.quota_bytes_snapshot = get_effective_quota_bytes(session, int(obj.owner_user_id))
        usage.updated_at = obj.updated_at
        session.add(usage)
    session.commit()


def serialize_user_storage(session: Session, user_id: int) -> Dict[str, Any]:
    usage = get_or_create_usage(session, user_id)
    quota = get_effective_quota_bytes(session, user_id)
    return {
        "user_id": user_id,
        "used_bytes": int(usage.used_bytes or 0),
        "reserved_bytes": int(usage.reserved_bytes or 0),
        "quota_bytes": quota,
        "quota_bytes_snapshot": int(usage.quota_bytes_snapshot or quota),
        "over_quota": int(usage.used_bytes or 0) + int(usage.reserved_bytes or 0) > quota,
    }


def recalculate_user_storage_usage(session: Session, user_id: int) -> Dict[str, Any]:
    total = session.exec(
        select(func.coalesce(func.sum(StorageObject.file_size), 0))
        .where(StorageObject.owner_user_id == user_id)
        .where(StorageObject.status.in_(COUNTED_STORAGE_STATUSES))
    ).one()
    usage = get_or_create_usage(session, user_id)
    usage.used_bytes = int(total or 0)
    usage.reserved_bytes = 0
    usage.quota_bytes_snapshot = get_effective_quota_bytes(session, user_id)
    usage.updated_at = _now()
    session.add(usage)
    session.commit()
    return serialize_user_storage(session, user_id)
