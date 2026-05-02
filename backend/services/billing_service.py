from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models import PointLog, Team, TeamMemberLink, User


def _get_member_link(session: Session, team: Team, user: User) -> Optional[TeamMemberLink]:
    if not team or not user:
        return None
    return session.exec(
        select(TeamMemberLink).where(TeamMemberLink.team_id == team.id, TeamMemberLink.user_id == user.id)
    ).first()


def _ensure_member_quota(link: Optional[TeamMemberLink], cost: int) -> None:
    if not link or link.point_quota is None:
        return
    remaining = link.point_quota - link.point_quota_used
    if remaining < cost:
        raise HTTPException(status_code=402, detail=f"Member quota exceeded. Remaining: {max(remaining, 0)} points")


def deduct_inspiration_points(
    user: User,
    team: Team,
    cost: int,
    action_type: str,
    description: str,
    session: Session,
):
    """
    Unified billing:
    1) If team billing is enabled, deduct from team points.
    2) Otherwise deduct from user's temporary/permanent points.
    3) If member quota is configured, enforce it before deduction.
    """
    if cost <= 0:
        raise HTTPException(status_code=400, detail="Cost must be > 0")

    now = datetime.utcnow()
    member_link = _get_member_link(session, team, user)
    _ensure_member_quota(member_link, cost)

    if team and team.is_team_billing:
        if team.team_points < cost:
            raise HTTPException(status_code=402, detail="Team points are insufficient")

        team.team_points -= cost
        log = PointLog(
            team_id=team.id,
            user_id=user.id,
            change_amount=-cost,
            balance_after=team.team_points,
            action_type=action_type,
            description=description,
        )
        session.add(team)
        session.add(log)
    else:
        if user.temporary_expire_at and user.temporary_expire_at < now:
            user.temporary_points = 0
            user.temporary_expire_at = None

        total_balance = user.temporary_points + user.permanent_points
        if total_balance < cost:
            raise HTTPException(status_code=402, detail="User points are insufficient")

        if user.temporary_points >= cost:
            user.temporary_points -= cost
        else:
            remaining_cost = cost - user.temporary_points
            user.temporary_points = 0
            user.permanent_points -= remaining_cost

        log = PointLog(
            user_id=user.id,
            change_amount=-cost,
            balance_after=user.temporary_points + user.permanent_points,
            action_type=action_type,
            description=description,
        )
        session.add(user)
        session.add(log)

    if member_link and member_link.point_quota is not None:
        member_link.point_quota_used += cost
        session.add(member_link)

    return True


def refund_inspiration_points(
    user: User,
    team: Team,
    cost: int,
    action_type: str,
    description: str,
    session: Session,
):
    if cost <= 0:
        return
    now = datetime.utcnow()
    if team and team.is_team_billing:
        team.team_points += cost
        log = PointLog(
            team_id=team.id,
            user_id=user.id,
            change_amount=cost,
            balance_after=team.team_points,
            action_type=action_type,
            description=description,
        )
        session.add(team)
        session.add(log)
    else:
        user.permanent_points += cost
        log = PointLog(
            user_id=user.id,
            change_amount=cost,
            balance_after=user.temporary_points + user.permanent_points,
            action_type=action_type,
            description=description,
        )
        session.add(user)
        session.add(log)

    member_link = _get_member_link(session, team, user)
    if member_link and member_link.point_quota is not None:
        member_link.point_quota_used = max(0, member_link.point_quota_used - cost)
        session.add(member_link)
