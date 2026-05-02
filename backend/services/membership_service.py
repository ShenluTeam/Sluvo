from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from core.config import settings
from models import (
    MembershipPlan,
    Team,
    TeamMembership,
    TeamMemberLink,
    TaskJob,
    User,
    UserMembership,
    UserMembershipOverride,
)
from services.storage_service import serialize_user_storage

PLAN_STATUS_ACTIVE = "active"
PLAN_STATUS_DISABLED = "disabled"
VALID_PLAN_STATUSES = {PLAN_STATUS_ACTIVE, PLAN_STATUS_DISABLED}
VALID_PLAN_SCOPE_TYPES = {"user", "team", "both"}
TASK_CATEGORY_STORYBOARD = "storyboard"
TASK_CATEGORY_RESOURCE = "resource"
TASK_CATEGORY_MEDIA = "media"
TASK_CATEGORY_AUDIO = "audio"
TASK_CATEGORY_TO_FIELD = {
    TASK_CATEGORY_STORYBOARD: "max_storyboard_concurrency",
    TASK_CATEGORY_RESOURCE: "max_resource_concurrency",
    TASK_CATEGORY_MEDIA: "max_media_concurrency",
    TASK_CATEGORY_AUDIO: "max_audio_concurrency",
}

GB = 1024 * 1024 * 1024


def _quota_gb(value: int) -> int:
    return int(value) * GB

BUILTIN_PLAN_SPECS: List[Dict[str, Any]] = [
    {
        "code": "free",
        "name": "免费版",
        "scope_type": "both",
        "sort_order": 100,
        "priority_default": 100,
        "max_storyboard_concurrency": None,
        "max_resource_concurrency": None,
        "max_media_concurrency": None,
        "max_audio_concurrency": None,
        "storage_quota_bytes": _quota_gb(settings.STORAGE_FREE_QUOTA_GB),
        "description": "系统默认免费规则",
        "is_default": True,
        "is_builtin": True,
    },
    {
        "code": "starter",
        "name": "入门版",
        "scope_type": "user",
        "sort_order": 30,
        "priority_default": 30,
        "max_storyboard_concurrency": None,
        "max_resource_concurrency": None,
        "max_media_concurrency": None,
        "max_audio_concurrency": None,
        "storage_quota_bytes": _quota_gb(settings.STORAGE_MEMBER_QUOTA_GB),
        "description": "内置入门用户套餐",
        "is_default": False,
        "is_builtin": True,
    },
    {
        "code": "pro",
        "name": "专业版",
        "scope_type": "user",
        "sort_order": 20,
        "priority_default": 20,
        "max_storyboard_concurrency": None,
        "max_resource_concurrency": None,
        "max_media_concurrency": None,
        "max_audio_concurrency": None,
        "storage_quota_bytes": _quota_gb(settings.STORAGE_MEMBER_QUOTA_GB),
        "description": "内置专业用户套餐",
        "is_default": False,
        "is_builtin": True,
    },
    {
        "code": "team",
        "name": "团队版",
        "scope_type": "team",
        "sort_order": 10,
        "priority_default": 10,
        "max_storyboard_concurrency": None,
        "max_resource_concurrency": None,
        "max_media_concurrency": None,
        "max_audio_concurrency": None,
        "storage_quota_bytes": _quota_gb(settings.STORAGE_MEMBER_QUOTA_GB),
        "description": "内置团队套餐",
        "is_default": False,
        "is_builtin": True,
    },
]


def _now() -> datetime:
    return datetime.utcnow()


def _normalize_plan_status(value: Optional[str]) -> str:
    text = str(value or PLAN_STATUS_ACTIVE).strip().lower()
    if text not in VALID_PLAN_STATUSES:
        raise HTTPException(status_code=400, detail="invalid plan status")
    return text


def _normalize_plan_scope_type(value: Optional[str]) -> str:
    text = str(value or "both").strip().lower()
    if text not in VALID_PLAN_SCOPE_TYPES:
        raise HTTPException(status_code=400, detail="invalid plan scope_type")
    return text


def _coerce_optional_limit(value: Optional[int]) -> Optional[int]:
    if value is None:
        return None
    limit = int(value)
    if limit < 0:
        raise HTTPException(status_code=400, detail="concurrency limit must be >= 0")
    return limit


def _coerce_optional_storage_quota(bytes_value: Optional[int] = None, gb_value: Optional[float] = None) -> Optional[int]:
    if bytes_value is None and gb_value is None:
        return None
    if bytes_value is not None:
        quota = int(bytes_value)
    else:
        quota = int(float(gb_value or 0) * GB)
    if quota < 0:
        raise HTTPException(status_code=400, detail="storage quota must be >= 0")
    return quota


def ensure_builtin_membership_plans(session: Session) -> None:
    changed = False
    for spec in BUILTIN_PLAN_SPECS:
        existing = session.exec(select(MembershipPlan).where(MembershipPlan.code == spec["code"])).first()
        if existing:
            for key, value in spec.items():
                if getattr(existing, key) != value:
                    setattr(existing, key, value)
                    changed = True
            existing.status = PLAN_STATUS_ACTIVE
            session.add(existing)
            continue
        session.add(MembershipPlan(status=PLAN_STATUS_ACTIVE, created_at=_now(), updated_at=_now(), **spec))
        changed = True
    if changed:
        session.commit()


def _serialize_plan(plan: MembershipPlan) -> Dict[str, Any]:
    return {
        "id": plan.id,
        "code": plan.code,
        "name": plan.name,
        "status": plan.status,
        "scope_type": plan.scope_type,
        "sort_order": plan.sort_order,
        "priority_default": plan.priority_default,
        "max_storyboard_concurrency": plan.max_storyboard_concurrency,
        "max_resource_concurrency": plan.max_resource_concurrency,
        "max_media_concurrency": plan.max_media_concurrency,
        "max_audio_concurrency": plan.max_audio_concurrency,
        "storage_quota_bytes": plan.storage_quota_bytes,
        "storage_quota_gb": None if plan.storage_quota_bytes is None else round(int(plan.storage_quota_bytes or 0) / GB, 2),
        "description": plan.description,
        "is_default": plan.is_default,
        "is_builtin": plan.is_builtin,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }


def list_membership_plans(session: Session) -> List[Dict[str, Any]]:
    ensure_builtin_membership_plans(session)
    plans = session.exec(select(MembershipPlan).order_by(MembershipPlan.sort_order.asc(), MembershipPlan.id.asc())).all()
    return [_serialize_plan(plan) for plan in plans]


def create_membership_plan(session: Session, payload: Dict[str, Any]) -> MembershipPlan:
    ensure_builtin_membership_plans(session)
    code = str(payload.get("code") or "").strip().lower()
    name = str(payload.get("name") or "").strip()
    if not code or not name:
        raise HTTPException(status_code=400, detail="code and name are required")
    existing = session.exec(select(MembershipPlan).where(MembershipPlan.code == code)).first()
    if existing:
        raise HTTPException(status_code=409, detail="membership plan code already exists")
    plan = MembershipPlan(
        code=code,
        name=name,
        status=_normalize_plan_status(payload.get("status")),
        scope_type=_normalize_plan_scope_type(payload.get("scope_type")),
        sort_order=int(payload.get("sort_order") or 100),
        priority_default=int(payload.get("priority_default") or 100),
        max_storyboard_concurrency=_coerce_optional_limit(payload.get("max_storyboard_concurrency")),
        max_resource_concurrency=_coerce_optional_limit(payload.get("max_resource_concurrency")),
        max_media_concurrency=_coerce_optional_limit(payload.get("max_media_concurrency")),
        max_audio_concurrency=_coerce_optional_limit(payload.get("max_audio_concurrency")),
        storage_quota_bytes=_coerce_optional_storage_quota(payload.get("storage_quota_bytes"), payload.get("storage_quota_gb")),
        description=str(payload.get("description") or "").strip() or None,
        is_default=bool(payload.get("is_default")),
        is_builtin=False,
        created_at=_now(),
        updated_at=_now(),
    )
    if plan.priority_default < 0:
        raise HTTPException(status_code=400, detail="priority_default must be >= 0")
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def update_membership_plan(session: Session, plan_id: int, payload: Dict[str, Any]) -> MembershipPlan:
    ensure_builtin_membership_plans(session)
    plan = session.get(MembershipPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="membership plan not found")
    if "name" in payload:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")
        plan.name = name
    if "status" in payload:
        plan.status = _normalize_plan_status(payload.get("status"))
    if "scope_type" in payload:
        plan.scope_type = _normalize_plan_scope_type(payload.get("scope_type"))
    if "sort_order" in payload:
        plan.sort_order = int(payload.get("sort_order") or 100)
    if "priority_default" in payload:
        priority_default = int(payload.get("priority_default") or 0)
        if priority_default < 0:
            raise HTTPException(status_code=400, detail="priority_default must be >= 0")
        plan.priority_default = priority_default
    for field_name in TASK_CATEGORY_TO_FIELD.values():
        if field_name in payload:
            setattr(plan, field_name, _coerce_optional_limit(payload.get(field_name)))
    if "storage_quota_bytes" in payload or "storage_quota_gb" in payload:
        plan.storage_quota_bytes = _coerce_optional_storage_quota(payload.get("storage_quota_bytes"), payload.get("storage_quota_gb"))
    if "description" in payload:
        plan.description = str(payload.get("description") or "").strip() or None
    if "is_default" in payload:
        plan.is_default = bool(payload.get("is_default"))
    plan.updated_at = _now()
    session.add(plan)
    session.commit()
    session.refresh(plan)
    return plan


def _resolve_builtin_vip_tier(plan: MembershipPlan) -> str:
    code = str(plan.code or "").strip().lower()
    if code in {"free", "starter", "pro", "team"}:
        return code
    if plan.scope_type == "team":
        return "team"
    return "pro"


def _assign_membership(
    session: Session,
    *,
    owner_type: str,
    owner_id: int,
    plan_id: int,
    starts_at: Optional[datetime],
    expires_at: Optional[datetime],
    enabled: bool,
    remark: Optional[str],
) -> Tuple[Any, MembershipPlan]:
    plan = session.get(MembershipPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="membership plan not found")
    if owner_type == "user":
        if plan.scope_type not in {"user", "both"}:
            raise HTTPException(status_code=400, detail="selected plan is not available for users")
        target = session.exec(select(UserMembership).where(UserMembership.user_id == owner_id)).first()
        if not target:
            target = UserMembership(user_id=owner_id, plan_id=plan_id, created_at=_now(), updated_at=_now())
        target.plan_id = plan_id
        target.starts_at = starts_at
        target.expires_at = expires_at
        target.enabled = enabled
        target.remark = remark
        target.updated_at = _now()
        session.add(target)
        user = session.get(User, owner_id)
        if user:
            user.vip_tier = _resolve_builtin_vip_tier(plan)
            user.vip_expire_time = expires_at
            session.add(user)
        session.commit()
        session.refresh(target)
        return target, plan
    team = session.get(Team, owner_id)
    if not team:
        raise HTTPException(status_code=404, detail="team not found")
    if plan.scope_type not in {"team", "both"}:
        raise HTTPException(status_code=400, detail="selected plan is not available for teams")
    target = session.exec(select(TeamMembership).where(TeamMembership.team_id == owner_id)).first()
    if not target:
        target = TeamMembership(team_id=owner_id, plan_id=plan_id, created_at=_now(), updated_at=_now())
    target.plan_id = plan_id
    target.starts_at = starts_at
    target.expires_at = expires_at
    target.enabled = enabled
    target.remark = remark
    target.updated_at = _now()
    session.add(target)
    session.commit()
    session.refresh(target)
    return target, plan


def assign_user_membership(session: Session, *, user_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    starts_at = payload.get("starts_at")
    expires_at = payload.get("expires_at")
    record, plan = _assign_membership(
        session,
        owner_type="user",
        owner_id=user_id,
        plan_id=int(payload["plan_id"]),
        starts_at=starts_at,
        expires_at=expires_at,
        enabled=bool(payload.get("enabled", True)),
        remark=str(payload.get("remark") or "").strip() or None,
    )
    return {
        "user_id": user_id,
        "plan": _serialize_plan(plan),
        "starts_at": record.starts_at.isoformat() if record.starts_at else None,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "enabled": record.enabled,
        "remark": record.remark,
    }


def assign_team_membership(session: Session, *, team_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    starts_at = payload.get("starts_at")
    expires_at = payload.get("expires_at")
    record, plan = _assign_membership(
        session,
        owner_type="team",
        owner_id=team_id,
        plan_id=int(payload["plan_id"]),
        starts_at=starts_at,
        expires_at=expires_at,
        enabled=bool(payload.get("enabled", True)),
        remark=str(payload.get("remark") or "").strip() or None,
    )
    return {
        "team_id": team_id,
        "plan": _serialize_plan(plan),
        "starts_at": record.starts_at.isoformat() if record.starts_at else None,
        "expires_at": record.expires_at.isoformat() if record.expires_at else None,
        "enabled": record.enabled,
        "remark": record.remark,
    }


def upsert_user_membership_override(session: Session, *, user_id: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    override = session.exec(select(UserMembershipOverride).where(UserMembershipOverride.user_id == user_id)).first()
    if not override:
        override = UserMembershipOverride(user_id=user_id, created_at=_now(), updated_at=_now())
    override.enabled = bool(payload.get("enabled", True))
    override.effective_priority = payload.get("effective_priority")
    if override.effective_priority is not None and int(override.effective_priority) < 0:
        raise HTTPException(status_code=400, detail="effective_priority must be >= 0")
    override.effective_priority = int(override.effective_priority) if override.effective_priority is not None else None
    for field_name in TASK_CATEGORY_TO_FIELD.values():
        setattr(override, field_name, _coerce_optional_limit(payload.get(field_name)))
    if "storage_quota_bytes" in payload or "storage_quota_gb" in payload:
        override.storage_quota_bytes = _coerce_optional_storage_quota(payload.get("storage_quota_bytes"), payload.get("storage_quota_gb"))
    override.remark = str(payload.get("remark") or "").strip() or None
    override.updated_at = _now()
    session.add(override)
    session.commit()
    session.refresh(override)
    return {
        "user_id": user_id,
        "enabled": override.enabled,
        "effective_priority": override.effective_priority,
        "max_storyboard_concurrency": override.max_storyboard_concurrency,
        "max_resource_concurrency": override.max_resource_concurrency,
        "max_media_concurrency": override.max_media_concurrency,
        "max_audio_concurrency": override.max_audio_concurrency,
        "storage_quota_bytes": override.storage_quota_bytes,
        "storage_quota_gb": None if override.storage_quota_bytes is None else round(int(override.storage_quota_bytes or 0) / GB, 2),
        "remark": override.remark,
    }


def _is_membership_active(enabled: bool, starts_at: Optional[datetime], expires_at: Optional[datetime]) -> bool:
    now = _now()
    if not enabled:
        return False
    if starts_at and now < starts_at:
        return False
    if expires_at and now > expires_at:
        return False
    return True


def _load_default_free_plan(session: Session) -> MembershipPlan:
    ensure_builtin_membership_plans(session)
    plan = session.exec(select(MembershipPlan).where(MembershipPlan.code == "free")).first()
    if not plan:
        raise HTTPException(status_code=500, detail="default free membership plan missing")
    return plan


def _build_policy_from_plan(
    *,
    source: str,
    plan: MembershipPlan,
    subject_type: str,
    subject_id: Optional[int],
    override: Optional[UserMembershipOverride] = None,
) -> Dict[str, Any]:
    policy = {
        "membership_source": source,
        "membership_plan_id": plan.id,
        "membership_plan_name": plan.name,
        "effective_priority": plan.priority_default,
        "membership_subject_type": subject_type,
        "membership_subject_id": subject_id,
        "storage_quota_bytes": plan.storage_quota_bytes,
        "limits": {
            TASK_CATEGORY_STORYBOARD: plan.max_storyboard_concurrency,
            TASK_CATEGORY_RESOURCE: plan.max_resource_concurrency,
            TASK_CATEGORY_MEDIA: plan.max_media_concurrency,
            TASK_CATEGORY_AUDIO: plan.max_audio_concurrency,
        },
    }
    if override and override.enabled:
        if override.effective_priority is not None:
            policy["effective_priority"] = override.effective_priority
        for category, field_name in TASK_CATEGORY_TO_FIELD.items():
            value = getattr(override, field_name)
            if value is not None:
                policy["limits"][category] = value
        if override.storage_quota_bytes is not None:
            policy["storage_quota_bytes"] = override.storage_quota_bytes
    return policy


def resolve_task_membership_policy(
    session: Session,
    *,
    user_id: Optional[int],
    team_id: Optional[int],
    task_category: str,
    ownership_mode: Optional[str],
) -> Dict[str, Any]:
    ownership = str(ownership_mode or "").strip().lower()
    if task_category not in TASK_CATEGORY_TO_FIELD:
        raise HTTPException(status_code=400, detail="invalid task category")
    if ownership == "project" and team_id:
        membership = session.exec(select(TeamMembership).where(TeamMembership.team_id == team_id)).first()
        if membership:
            plan = session.get(MembershipPlan, membership.plan_id)
            if plan and plan.status == PLAN_STATUS_ACTIVE and _is_membership_active(membership.enabled, membership.starts_at, membership.expires_at):
                return _build_policy_from_plan(
                    source="team",
                    plan=plan,
                    subject_type="team",
                    subject_id=team_id,
                )
        plan = _load_default_free_plan(session)
        return _build_policy_from_plan(
            source="system_default",
            plan=plan,
            subject_type="team",
            subject_id=team_id,
        )

    if user_id:
        membership = session.exec(select(UserMembership).where(UserMembership.user_id == user_id)).first()
        override = session.exec(select(UserMembershipOverride).where(UserMembershipOverride.user_id == user_id)).first()
        if membership:
            plan = session.get(MembershipPlan, membership.plan_id)
            if plan and plan.status == PLAN_STATUS_ACTIVE and _is_membership_active(membership.enabled, membership.starts_at, membership.expires_at):
                return _build_policy_from_plan(
                    source="user",
                    plan=plan,
                    subject_type="user",
                    subject_id=user_id,
                    override=override,
                )
        plan = _load_default_free_plan(session)
        return _build_policy_from_plan(
            source="system_default",
            plan=plan,
            subject_type="user",
            subject_id=user_id,
            override=override,
        )
    plan = _load_default_free_plan(session)
    return _build_policy_from_plan(
        source="system_default",
        plan=plan,
        subject_type="user",
        subject_id=user_id,
    )


def summarize_membership_assignments(session: Session) -> Dict[str, Any]:
    ensure_builtin_membership_plans(session)
    plans = session.exec(select(MembershipPlan).order_by(MembershipPlan.sort_order.asc(), MembershipPlan.id.asc())).all()
    user_assignments = session.exec(select(UserMembership)).all()
    team_assignments = session.exec(select(TeamMembership)).all()
    return {
        "plans": [_serialize_plan(plan) for plan in plans],
        "plan_stats": [
            {
                "plan_id": plan.id,
                "plan_code": plan.code,
                "plan_name": plan.name,
                "user_count": sum(1 for item in user_assignments if item.plan_id == plan.id and item.enabled),
                "team_count": sum(1 for item in team_assignments if item.plan_id == plan.id and item.enabled),
            }
            for plan in plans
        ],
    }


def build_user_membership_summary(session: Session, user_id: int) -> Dict[str, Any]:
    override = session.exec(select(UserMembershipOverride).where(UserMembershipOverride.user_id == user_id)).first()
    user_policy = resolve_task_membership_policy(
        session,
        user_id=user_id,
        team_id=None,
        task_category=TASK_CATEGORY_MEDIA,
        ownership_mode="standalone",
    )
    team_link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user_id)).first()
    team_policy = None
    if team_link:
        team_policy = resolve_task_membership_policy(
            session,
            user_id=user_id,
            team_id=team_link.team_id,
            task_category=TASK_CATEGORY_MEDIA,
            ownership_mode="project",
        )
    return {
        "standalone_membership": {
            "source": user_policy["membership_source"],
            "plan_id": user_policy["membership_plan_id"],
            "plan_name": user_policy["membership_plan_name"],
            "effective_priority": user_policy["effective_priority"],
            "limits": user_policy["limits"],
            "storage_quota_bytes": user_policy.get("storage_quota_bytes"),
            "storage_quota_gb": None if user_policy.get("storage_quota_bytes") is None else round(int(user_policy.get("storage_quota_bytes") or 0) / GB, 2),
        },
        "team_membership": {
            "team_id": team_link.team_id if team_link else None,
            "source": team_policy["membership_source"] if team_policy else None,
            "plan_id": team_policy["membership_plan_id"] if team_policy else None,
            "plan_name": team_policy["membership_plan_name"] if team_policy else None,
            "effective_priority": team_policy["effective_priority"] if team_policy else None,
            "limits": team_policy["limits"] if team_policy else None,
            "storage_quota_bytes": team_policy.get("storage_quota_bytes") if team_policy else None,
            "storage_quota_gb": None if not team_policy or team_policy.get("storage_quota_bytes") is None else round(int(team_policy.get("storage_quota_bytes") or 0) / GB, 2),
        },
        "override": {
            "enabled": override.enabled,
            "effective_priority": override.effective_priority,
            "max_storyboard_concurrency": override.max_storyboard_concurrency,
            "max_resource_concurrency": override.max_resource_concurrency,
            "max_media_concurrency": override.max_media_concurrency,
            "max_audio_concurrency": override.max_audio_concurrency,
            "storage_quota_bytes": override.storage_quota_bytes,
            "storage_quota_gb": None if override.storage_quota_bytes is None else round(int(override.storage_quota_bytes or 0) / GB, 2),
            "remark": override.remark,
        } if override else None,
    }


def create_starts_and_expires(payload: Dict[str, Any]) -> Tuple[Optional[datetime], Optional[datetime]]:
    starts_at = payload.get("starts_at")
    expires_at = payload.get("expires_at")
    duration_days = payload.get("duration_days")
    if starts_at and isinstance(starts_at, str):
        starts_at = datetime.fromisoformat(starts_at)
    if expires_at and isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at is None and duration_days is not None:
        base = starts_at or _now()
        expires_at = base + timedelta(days=int(duration_days))
    return starts_at, expires_at


def build_runtime_overview(session: Session) -> Dict[str, Any]:
    plans_summary = summarize_membership_assignments(session)
    users = session.exec(select(User).order_by(User.id.desc()).limit(200)).all()
    teams = session.exec(select(Team).order_by(Team.id.desc()).limit(200)).all()
    team_memberships = {item.team_id: item for item in session.exec(select(TeamMembership)).all()}
    user_memberships = {item.user_id: item for item in session.exec(select(UserMembership)).all()}
    active_tasks = session.exec(
        select(TaskJob).where(TaskJob.status.in_(["leased", "running"])).order_by(TaskJob.updated_at.desc()).limit(500)
    ).all()
    queued_tasks = session.exec(
        select(TaskJob).where(TaskJob.status == "queued").order_by(TaskJob.created_at.asc()).limit(500)
    ).all()

    queue_summary: Dict[str, Dict[str, int]] = {
        TASK_CATEGORY_STORYBOARD: {"running": 0, "queued": 0},
        TASK_CATEGORY_RESOURCE: {"running": 0, "queued": 0},
        TASK_CATEGORY_MEDIA: {"running": 0, "queued": 0},
        TASK_CATEGORY_AUDIO: {"running": 0, "queued": 0},
    }
    for task in active_tasks:
        if task.task_category in queue_summary:
            queue_summary[task.task_category]["running"] += 1
    for task in queued_tasks:
        if task.task_category in queue_summary:
            queue_summary[task.task_category]["queued"] += 1

    subject_counts: Dict[Tuple[str, int], Dict[str, int]] = {}
    for task in active_tasks:
        if not task.membership_subject_type or not task.membership_subject_id or not task.task_category:
            continue
        key = (task.membership_subject_type, int(task.membership_subject_id))
        bucket = subject_counts.setdefault(key, {
            TASK_CATEGORY_STORYBOARD: 0,
            TASK_CATEGORY_RESOURCE: 0,
            TASK_CATEGORY_MEDIA: 0,
            TASK_CATEGORY_AUDIO: 0,
        })
        if task.task_category in bucket:
            bucket[task.task_category] += 1

    user_items = []
    for user in users:
        summary = build_user_membership_summary(session, user.id)
        user_items.append(
            {
                "id": user.id,
                "nickname": user.nickname,
                "email": user.email,
                "membership": summary,
                "storage": serialize_user_storage(session, int(user.id)),
                "running_usage": subject_counts.get(("user", user.id), {
                    TASK_CATEGORY_STORYBOARD: 0,
                    TASK_CATEGORY_RESOURCE: 0,
                    TASK_CATEGORY_MEDIA: 0,
                    TASK_CATEGORY_AUDIO: 0,
                }),
            }
        )

    team_items = []
    for team in teams:
        membership = team_memberships.get(team.id)
        plan = session.get(MembershipPlan, membership.plan_id) if membership else _load_default_free_plan(session)
        team_items.append(
            {
                "id": team.id,
                "name": team.name,
                "description": team.description,
                "membership": {
                    "plan_id": plan.id if plan else None,
                    "plan_name": plan.name if plan else None,
                    "source": "team" if membership else "system_default",
                    "limits": {
                        TASK_CATEGORY_STORYBOARD: plan.max_storyboard_concurrency if plan else None,
                        TASK_CATEGORY_RESOURCE: plan.max_resource_concurrency if plan else None,
                        TASK_CATEGORY_MEDIA: plan.max_media_concurrency if plan else None,
                        TASK_CATEGORY_AUDIO: plan.max_audio_concurrency if plan else None,
                    },
                    "priority": plan.priority_default if plan else 100,
                },
                "running_usage": subject_counts.get(("team", team.id), {
                    TASK_CATEGORY_STORYBOARD: 0,
                    TASK_CATEGORY_RESOURCE: 0,
                    TASK_CATEGORY_MEDIA: 0,
                    TASK_CATEGORY_AUDIO: 0,
                }),
            }
        )

    return {
        **plans_summary,
        "queue_summary": queue_summary,
        "active_task_count": len(active_tasks),
        "queued_task_count": len(queued_tasks),
        "worker_max_concurrency": 300,
        "users": user_items,
        "teams": team_items,
    }
