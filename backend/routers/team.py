from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.security import decode_id, encode_id
from database import get_session
from dependencies import (
    get_current_team,
    get_current_team_member,
    get_current_user,
    get_role_permissions,
    require_team_vip_user,
    require_team_permission,
)
from models import Team, TeamMemberLink, User
from schemas import (
    TeamInviteAcceptRequest,
    TeamInviteCreateRequest,
    TeamMemberQuotaUpdateRequest,
    TeamMemberRoleUpdateRequest,
)
from services.team_service import (
    accept_team_invitation,
    create_team_invitation,
    list_team_invitations,
    list_team_members,
    revoke_team_invitation,
    update_team_member_quota,
    update_team_member_role,
)

router = APIRouter(dependencies=[Depends(require_team_vip_user)])


@router.get("/api/team/overview")
async def get_team_overview(
    team: Team = Depends(get_current_team),
    member_link: TeamMemberLink = Depends(get_current_team_member),
):
    role = str(member_link.role.value if hasattr(member_link.role, "value") else member_link.role)
    permissions = sorted(get_role_permissions(member_link.role))
    return {
        "team": {
            "id": encode_id(team.id),
            "raw_id": team.id,
            "name": team.name,
            "description": team.description,
            "is_team_billing": team.is_team_billing,
            "team_points": team.team_points,
            "created_at": team.created_at,
        },
        "current_role": role,
        "permissions": permissions,
    }


@router.get("/api/team/members")
async def get_team_members(
    team: Team = Depends(get_current_team),
    _: TeamMemberLink = Depends(require_team_permission("team:read")),
    session: Session = Depends(get_session),
):
    rows = list_team_members(session, team)
    items = []
    for user, link in rows:
        items.append(
            {
                "user_id": encode_id(user.id),
                "raw_user_id": user.id,
                "nickname": user.nickname,
                "email": user.email,
                "role": str(link.role.value if hasattr(link.role, "value") else link.role),
                "point_quota": link.point_quota,
                "point_quota_used": link.point_quota_used,
                "point_quota_remaining": (
                    None if link.point_quota is None else max(link.point_quota - link.point_quota_used, 0)
                ),
                "joined_at": link.joined_at,
            }
        )
    return {"items": items}


@router.get("/api/team/invitations")
async def get_team_invites(
    team: Team = Depends(get_current_team),
    _: TeamMemberLink = Depends(require_team_permission("team:manage")),
    session: Session = Depends(get_session),
):
    invitations = list_team_invitations(session, team)
    return {
        "items": [
            {
                "id": encode_id(item.id),
                "raw_id": item.id,
                "token": item.token,
                "role": str(item.role.value if hasattr(item.role, "value") else item.role),
                "target_email": item.target_email,
                "status": str(item.status.value if hasattr(item.status, "value") else item.status),
                "expire_at": item.expire_at,
                "created_at": item.created_at,
                "accepted_at": item.accepted_at,
                "invited_by_user_id": encode_id(item.invited_by_user_id),
                "accepted_by_user_id": encode_id(item.accepted_by_user_id) if item.accepted_by_user_id else None,
            }
            for item in invitations
        ]
    }


@router.post("/api/team/invitations")
async def create_team_invite(
    payload: TeamInviteCreateRequest,
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    _: TeamMemberLink = Depends(require_team_permission("team:manage")),
    session: Session = Depends(get_session),
):
    invitation = create_team_invitation(
        session,
        team,
        user,
        role=payload.role,
        target_email=payload.email,
        expire_hours=payload.expire_hours,
    )
    return {
        "id": encode_id(invitation.id),
        "token": invitation.token,
        "role": str(invitation.role.value if hasattr(invitation.role, "value") else invitation.role),
        "target_email": invitation.target_email,
        "status": str(invitation.status.value if hasattr(invitation.status, "value") else invitation.status),
        "expire_at": invitation.expire_at,
        "created_at": invitation.created_at,
    }


@router.post("/api/team/invitations/accept")
async def accept_team_invite(
    payload: TeamInviteAcceptRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    invitation, member_link = accept_team_invitation(
        session,
        user,
        payload.token,
        auto_migrate_projects=payload.auto_migrate_projects,
    )
    return {
        "status": "success",
        "team_id": encode_id(member_link.team_id),
        "role": str(member_link.role.value if hasattr(member_link.role, "value") else member_link.role),
        "invite_status": str(invitation.status.value if hasattr(invitation.status, "value") else invitation.status),
    }


@router.delete("/api/team/invitations/{invitation_id}")
async def revoke_team_invite(
    invitation_id: str,
    team: Team = Depends(get_current_team),
    _: TeamMemberLink = Depends(require_team_permission("team:manage")),
    session: Session = Depends(get_session),
):
    invitation = revoke_team_invitation(session, team, decode_id(invitation_id))
    return {
        "status": "success",
        "invite_status": str(invitation.status.value if hasattr(invitation.status, "value") else invitation.status),
    }


@router.put("/api/team/members/{member_id}/role")
async def change_team_member_role(
    member_id: str,
    payload: TeamMemberRoleUpdateRequest,
    team: Team = Depends(get_current_team),
    current_user: User = Depends(get_current_user),
    _: TeamMemberLink = Depends(require_team_permission("team:manage")),
    session: Session = Depends(get_session),
):
    link = update_team_member_role(
        session,
        team,
        operator_user_id=current_user.id,
        member_user_id=decode_id(member_id),
        role=payload.role,
    )
    return {
        "status": "success",
        "member_id": encode_id(link.user_id),
        "role": str(link.role.value if hasattr(link.role, "value") else link.role),
    }


@router.put("/api/team/members/{member_id}/quota")
async def change_team_member_quota(
    member_id: str,
    payload: TeamMemberQuotaUpdateRequest,
    team: Team = Depends(get_current_team),
    current_user: User = Depends(get_current_user),
    _: TeamMemberLink = Depends(require_team_permission("team:manage")),
    session: Session = Depends(get_session),
):
    link = update_team_member_quota(
        session,
        team,
        operator_user_id=current_user.id,
        member_user_id=decode_id(member_id),
        point_quota=payload.point_quota,
        reset_used=payload.reset_used,
    )
    return {
        "status": "success",
        "member_id": encode_id(link.user_id),
        "point_quota": link.point_quota,
        "point_quota_used": link.point_quota_used,
        "point_quota_remaining": None if link.point_quota is None else max(link.point_quota - link.point_quota_used, 0),
    }
