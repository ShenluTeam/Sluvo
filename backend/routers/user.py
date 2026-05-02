from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlmodel import Session, select

from core.security import get_password_hash, verify_password
from database import get_session
from dependencies import get_current_user, get_role_permissions
from models import PointLog, Team, TeamMemberLink, User
from schemas import ChangePasswordRequest, UpdateProfileRequest
from services.user_dashboard_service import (
    build_user_point_log_item,
    get_action_types_for_feature,
    get_user_dashboard_data,
)
from services.membership_service import build_user_membership_summary
from services.storage_service import serialize_user_storage

router = APIRouter()


def _cleanup_expired_temporary_points(user: User, session: Session) -> None:
    now = datetime.utcnow()
    if user.temporary_expire_at and now > user.temporary_expire_at:
        user.temporary_points = 0
        user.temporary_expire_at = None
        session.add(user)
        session.commit()
        session.refresh(user)


@router.get("/api/user/me")
async def get_user_info(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _cleanup_expired_temporary_points(user, session)

    total_points = user.permanent_points + user.temporary_points
    link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user.id)).first()
    team_id = link.team_id if link else None
    team = session.get(Team, team_id) if team_id else None
    team_role = (link.role.value if hasattr(link.role, "value") else link.role) if link else None
    team_permissions = sorted(get_role_permissions(link.role)) if link else []
    team_point_quota = link.point_quota if link else None
    team_point_quota_used = link.point_quota_used if link else 0

    return {
        "nickname": user.nickname,
        "email": user.email,
        "email_verified": user.email_verified,
        "total_points": total_points,
        "vip_tier": user.vip_tier,
        "team_id": team_id,
        "team_name": team.name if team else None,
        "team_role": team_role,
        "team_permissions": team_permissions,
        "can_manage_team": "team:manage" in team_permissions,
        "team_point_quota": team_point_quota,
        "team_point_quota_used": team_point_quota_used,
        "team_point_quota_remaining": (
            None if team_point_quota is None else max(team_point_quota - team_point_quota_used, 0)
        ),
        "daily_bonus_amount": 0,
        "membership": build_user_membership_summary(session, user.id),
        "storage": serialize_user_storage(session, int(user.id)),
    }


@router.get("/api/user/storage")
async def get_user_storage(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    return {"success": True, "data": serialize_user_storage(session, int(user.id))}


@router.get("/api/user/dashboard")
async def get_user_dashboard(user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    _cleanup_expired_temporary_points(user, session)
    return get_user_dashboard_data(session, user)


@router.get("/api/user/point_logs")
async def get_user_point_logs(
    page: int = 1,
    size: int = 20,
    action_type: Optional[str] = None,
    feature_type: Optional[str] = None,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    _cleanup_expired_temporary_points(user, session)

    if page < 1:
        raise HTTPException(status_code=400, detail="page must be >= 1")
    if size < 1 or size > 100:
        raise HTTPException(status_code=400, detail="size must be between 1 and 100")

    query = select(PointLog).where(PointLog.user_id == user.id)
    if action_type:
        query = query.where(PointLog.action_type == action_type)
    elif feature_type:
        action_types = get_action_types_for_feature(feature_type)
        if action_types:
            query = query.where(PointLog.action_type.in_(action_types))

    total = session.exec(select(func.count()).select_from(query.subquery())).one() or 0
    logs = session.exec(query.order_by(PointLog.id.desc()).offset((page - 1) * size).limit(size)).all()

    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [build_user_point_log_item(log) for log in logs],
    }


@router.put("/api/user/profile")
async def update_profile(req: UpdateProfileRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    user.nickname = req.nickname
    session.add(user)
    session.commit()
    return {"status": "success", "nickname": user.nickname}


@router.post("/api/user/change_password")
async def change_password(req: ChangePasswordRequest, user: User = Depends(get_current_user), session: Session = Depends(get_session)):
    if not verify_password(req.old_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="原密码不正确")
    user.hashed_password = get_password_hash(req.new_password)
    session.add(user)
    session.commit()
    return {"status": "success", "msg": "密码修改成功"}

