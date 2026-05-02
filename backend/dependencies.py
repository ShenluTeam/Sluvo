from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from database import get_session
from models import RoleEnum, Team, TeamMemberLink, User, VIPTierEnum
from services.openclaw_api_key_service import find_openclaw_credential_by_api_key

TEAM_PERMISSION_MATRIX: dict[RoleEnum, set[str]] = {
    RoleEnum.ADMIN: {
        "team:read",
        "team:manage",
        "project:read",
        "project:write",
        "project:manage",
        "generate:run",
    },
    RoleEnum.DIRECTOR: {
        "team:read",
        "project:read",
        "project:write",
        "project:manage",
        "generate:run",
    },
    RoleEnum.EDITOR: {
        "team:read",
        "project:read",
        "project:write",
        "generate:run",
    },
    RoleEnum.VIEWER: {
        "team:read",
        "project:read",
    },
}


def _normalize_role(role: RoleEnum | str) -> RoleEnum:
    if isinstance(role, RoleEnum):
        return role
    try:
        return RoleEnum(str(role))
    except ValueError:
        return RoleEnum.VIEWER


def get_role_permissions(role: RoleEnum | str) -> set[str]:
    return TEAM_PERMISSION_MATRIX.get(_normalize_role(role), set())


def has_team_permission(role: RoleEnum | str, permission: str) -> bool:
    return permission in get_role_permissions(role)


# ==========================================
# 基础认证
# ==========================================
def get_current_user(
    authorization: Optional[str] = Header(None),
    session: Session = Depends(get_session),
) -> User:
    if not authorization:
        raise HTTPException(status_code=401, detail="未登录，请先登录")

    token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    user = session.exec(select(User).where(User.session_token == token)).first()
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用，请联系管理员")

    return user


def _extract_header_token(
    authorization: Optional[str],
    x_api_key: Optional[str],
    x_api_token: Optional[str],
) -> Optional[str]:
    if x_api_key and str(x_api_key).strip():
        return str(x_api_key).strip()
    if x_api_token and str(x_api_token).strip():
        return str(x_api_token).strip()
    if authorization and str(authorization).strip():
        return authorization.replace("Bearer ", "", 1) if authorization.startswith("Bearer ") else authorization.strip()
    return None


def get_current_user_by_api_token(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    x_api_token: Optional[str] = Header(None, alias="X-API-Token"),
    session: Session = Depends(get_session),
) -> User:
    token = _extract_header_token(authorization, x_api_key, x_api_token)
    if not token:
        raise HTTPException(status_code=401, detail={"code": "token_missing", "message": "缺少 OpenClaw API Key"})

    credential = find_openclaw_credential_by_api_key(session, api_key=token)
    if not credential:
        raise HTTPException(status_code=401, detail={"code": "token_invalid", "message": "OpenClaw API Key 无效"})
    if not credential.openclaw_api_enabled:
        raise HTTPException(status_code=403, detail={"code": "openclaw_api_disabled", "message": "当前 API Key 未开启 OpenClaw API 权限"})
    if credential.expires_at is not None and credential.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=401, detail={"code": "token_expired", "message": "OpenClaw API Key 已过期，请在用户中心手动生成新的 Key"})

    user = session.get(User, credential.user_id)
    if not user:
        raise HTTPException(status_code=401, detail={"code": "token_invalid", "message": "OpenClaw API Key 无法映射到有效账号"})
    if not user.is_active:
        raise HTTPException(status_code=403, detail={"code": "account_disabled", "message": "账号已被禁用，请联系管理员"})
    return user


def get_current_team_member(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> TeamMemberLink:
    link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user.id)).first()
    if not link:
        raise HTTPException(status_code=403, detail="当前账号未加入任何团队")
    return link


def get_current_team_member_by_api_token(
    user: User = Depends(get_current_user_by_api_token),
    session: Session = Depends(get_session),
) -> TeamMemberLink:
    link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user.id)).first()
    if not link:
        raise HTTPException(status_code=403, detail={"code": "permission_denied", "message": "当前 OpenClaw API Key 对应账号未加入任何团队"})
    return link


def get_current_team(
    link: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
) -> Team:
    team = session.get(Team, link.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="团队不存在")
    return team


def get_current_team_by_api_token(
    link: TeamMemberLink = Depends(get_current_team_member_by_api_token),
    session: Session = Depends(get_session),
) -> Team:
    team = session.get(Team, link.team_id)
    if not team:
        raise HTTPException(status_code=404, detail={"code": "team_not_found", "message": "团队不存在"})
    return team


def require_team_permission(permission: str):
    def _dependency(link: TeamMemberLink = Depends(get_current_team_member)) -> TeamMemberLink:
        role = _normalize_role(link.role)
        if permission not in get_role_permissions(role):
            raise HTTPException(status_code=403, detail=f"当前角色({role.value})无权限执行此操作")
        return link

    return _dependency


def require_team_permission_by_api_token(permission: str):
    def _dependency(link: TeamMemberLink = Depends(get_current_team_member_by_api_token)) -> TeamMemberLink:
        role = _normalize_role(link.role)
        if permission not in get_role_permissions(role):
            raise HTTPException(
                status_code=403,
                detail={"code": "permission_denied", "message": f"当前角色({role.value})无权限执行此操作"},
            )
        return link

    return _dependency


# ==========================================
# 系统管理员认证（后台）
# ==========================================
def get_current_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_superadmin:
        raise HTTPException(status_code=403, detail="拒绝访问：需要系统管理员权限")
    return user


def require_team_vip_user(user: User = Depends(get_current_user)) -> User:
    if user.vip_tier != VIPTierEnum.TEAM:
        raise HTTPException(status_code=403, detail="团队功能仅对团队版会员开放，请先升级到 Team 套餐")
    return user
