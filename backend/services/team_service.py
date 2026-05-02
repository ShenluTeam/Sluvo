from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models import (
    InvitationStatusEnum,
    RoleEnum,
    Script,
    Team,
    TeamInvitation,
    TeamMemberLink,
    User,
)

ASSIGNABLE_ROLES = {RoleEnum.DIRECTOR, RoleEnum.EDITOR, RoleEnum.VIEWER}


def normalize_role(role: RoleEnum | str) -> RoleEnum:
    if isinstance(role, RoleEnum):
        return role
    try:
        return RoleEnum(str(role).lower())
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid team role") from exc


def parse_assignable_role(role: RoleEnum | str) -> RoleEnum:
    parsed = normalize_role(role)
    if parsed not in ASSIGNABLE_ROLES:
        raise HTTPException(status_code=400, detail="Only director/editor/viewer roles are assignable")
    return parsed


def _mark_invitation_expired_if_needed(session: Session, invitation: TeamInvitation) -> None:
    if invitation.status == InvitationStatusEnum.PENDING and invitation.expire_at <= datetime.utcnow():
        invitation.status = InvitationStatusEnum.EXPIRED
        session.add(invitation)


def cleanup_expired_invitations(session: Session, team_id: Optional[int] = None) -> int:
    query = select(TeamInvitation).where(TeamInvitation.status == InvitationStatusEnum.PENDING)
    if team_id is not None:
        query = query.where(TeamInvitation.team_id == team_id)
    invitations = session.exec(query).all()

    changed = 0
    now = datetime.utcnow()
    for invitation in invitations:
        if invitation.expire_at <= now:
            invitation.status = InvitationStatusEnum.EXPIRED
            session.add(invitation)
            changed += 1
    if changed > 0:
        session.commit()
    return changed


def get_team_member_link(session: Session, team_id: int, user_id: int) -> TeamMemberLink | None:
    return session.exec(
        select(TeamMemberLink).where(TeamMemberLink.team_id == team_id, TeamMemberLink.user_id == user_id)
    ).first()


def list_team_members(session: Session, team: Team):
    statement = (
        select(User, TeamMemberLink)
        .join(TeamMemberLink, TeamMemberLink.user_id == User.id)
        .where(TeamMemberLink.team_id == team.id)
        .order_by(TeamMemberLink.joined_at.asc(), User.id.asc())
    )
    return session.exec(statement).all()


def list_team_invitations(session: Session, team: Team):
    cleanup_expired_invitations(session, team.id)
    statement = (
        select(TeamInvitation)
        .where(TeamInvitation.team_id == team.id)
        .order_by(TeamInvitation.created_at.desc(), TeamInvitation.id.desc())
    )
    return session.exec(statement).all()


def create_team_invitation(
    session: Session,
    team: Team,
    inviter: User,
    *,
    role: RoleEnum | str,
    target_email: str | None,
    expire_hours: int,
) -> TeamInvitation:
    invite_role = parse_assignable_role(role)
    ttl_hours = max(1, min(expire_hours or 72, 24 * 14))
    normalized_email = (target_email or "").strip().lower() or None

    if normalized_email:
        target_user = session.exec(select(User).where(User.email == normalized_email)).first()
        if target_user:
            existing_link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == target_user.id)).first()
            if existing_link and existing_link.team_id == team.id:
                raise HTTPException(status_code=400, detail="鐠囥儳鏁ら幋宄板嚒缂佸繑妲歌ぐ鎾冲閸ャ垽妲﹂幋鎰喅")

    invitation = TeamInvitation(
        team_id=team.id,
        role=invite_role,
        target_email=normalized_email,
        invited_by_user_id=inviter.id,
        expire_at=datetime.utcnow() + timedelta(hours=ttl_hours),
    )
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    return invitation


def _validate_can_switch_team(session: Session, current_link: TeamMemberLink) -> list[Script]:
    member_links = session.exec(select(TeamMemberLink).where(TeamMemberLink.team_id == current_link.team_id)).all()
    scripts = session.exec(select(Script).where(Script.team_id == current_link.team_id)).all()
    if len(member_links) > 1:
        raise HTTPException(status_code=400, detail="褰撳墠璐﹀彿宸插湪鍗忎綔鍥㈤槦涓紝鏆備笉鏀寔鐩存帴鍒囨崲鍥㈤槦")
    return scripts


def accept_team_invitation(
    session: Session,
    user: User,
    token: str,
    *,
    auto_migrate_projects: bool = True,
) -> tuple[TeamInvitation, TeamMemberLink]:
    clean_token = (token or "").strip()
    if not clean_token:
        raise HTTPException(status_code=400, detail="閭€璇风爜涓嶈兘涓虹┖")

    invitation = session.exec(select(TeamInvitation).where(TeamInvitation.token == clean_token)).first()
    if not invitation:
        raise HTTPException(status_code=404, detail="閭€璇蜂笉瀛樺湪鎴栧凡澶辨晥")

    _mark_invitation_expired_if_needed(session, invitation)
    if invitation.status == InvitationStatusEnum.EXPIRED:
        session.commit()
        raise HTTPException(status_code=400, detail="閭€璇峰凡杩囨湡")
    if invitation.status == InvitationStatusEnum.REVOKED:
        raise HTTPException(status_code=400, detail="閭€璇峰凡鎾ら攢")
    if invitation.status == InvitationStatusEnum.ACCEPTED:
        raise HTTPException(status_code=400, detail="Invitation has already been used")

    if invitation.target_email and invitation.target_email.lower() != user.email.lower():
        raise HTTPException(status_code=403, detail="This invitation is restricted to the target email user")

    current_link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user.id)).first()
    if current_link and current_link.team_id == invitation.team_id:
        invitation.status = InvitationStatusEnum.ACCEPTED
        invitation.accepted_by_user_id = user.id
        invitation.accepted_at = datetime.utcnow()
        session.add(invitation)
        session.commit()
        session.refresh(current_link)
        return invitation, current_link

    if current_link and current_link.team_id != invitation.team_id:
        scripts = _validate_can_switch_team(session, current_link)
        if scripts and not auto_migrate_projects:
            raise HTTPException(
                status_code=400,
                detail="褰撳墠鍥㈤槦瀛樺湪椤圭洰鏁版嵁锛岃鍏堣嚜琛屽浠藉苟娓呯┖椤圭洰鍚庡啀鍔犲叆鍥㈤槦",
            )
        for script in scripts:
            script.team_id = invitation.team_id
            session.add(script)
        session.delete(current_link)

    new_link = TeamMemberLink(team_id=invitation.team_id, user_id=user.id, role=invitation.role)
    session.add(new_link)
    invitation.status = InvitationStatusEnum.ACCEPTED
    invitation.accepted_by_user_id = user.id
    invitation.accepted_at = datetime.utcnow()
    session.add(invitation)
    session.commit()
    session.refresh(new_link)
    session.refresh(invitation)
    return invitation, new_link


def revoke_team_invitation(session: Session, team: Team, invitation_id: int) -> TeamInvitation:
    invitation = session.get(TeamInvitation, invitation_id)
    if not invitation or invitation.team_id != team.id:
        raise HTTPException(status_code=404, detail="Invitation not found")
    _mark_invitation_expired_if_needed(session, invitation)
    if invitation.status == InvitationStatusEnum.ACCEPTED:
        raise HTTPException(status_code=400, detail="Accepted invitation cannot be revoked")
    if invitation.status == InvitationStatusEnum.REVOKED:
        return invitation
    invitation.status = InvitationStatusEnum.REVOKED
    invitation.revoked_at = datetime.utcnow()
    session.add(invitation)
    session.commit()
    session.refresh(invitation)
    return invitation


def update_team_member_role(
    session: Session,
    team: Team,
    *,
    operator_user_id: int,
    member_user_id: int,
    role: RoleEnum | str,
) -> TeamMemberLink:
    target_role = parse_assignable_role(role)
    member_link = get_team_member_link(session, team.id, member_user_id)
    if not member_link:
        raise HTTPException(status_code=404, detail="Member not found")

    if member_link.user_id == operator_user_id:
        raise HTTPException(status_code=400, detail="You cannot modify your own team role")

    if normalize_role(member_link.role) == target_role:
        return member_link

    member_link.role = target_role
    session.add(member_link)
    session.commit()
    session.refresh(member_link)
    return member_link


def update_team_member_quota(
    session: Session,
    team: Team,
    *,
    operator_user_id: int,
    member_user_id: int,
    point_quota: int | None,
    reset_used: bool = False,
) -> TeamMemberLink:
    member_link = get_team_member_link(session, team.id, member_user_id)
    if not member_link:
        raise HTTPException(status_code=404, detail="Member not found")

    if member_link.user_id == operator_user_id:
        raise HTTPException(status_code=400, detail="You cannot edit your own quota")

    if point_quota is not None and point_quota < 0:
        raise HTTPException(status_code=400, detail="point_quota must be >= 0")

    if reset_used:
        member_link.point_quota_used = 0

    if point_quota is not None and member_link.point_quota_used > point_quota:
        raise HTTPException(
            status_code=400,
            detail="Current usage exceeds new quota. Set reset_used=true to reset used amount first.",
        )

    member_link.point_quota = point_quota
    session.add(member_link)
    session.commit()
    session.refresh(member_link)
    return member_link


