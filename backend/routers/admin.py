from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func
from sqlmodel import Session, select

from database import get_session
from dependencies import get_current_admin
from models import MembershipPlan, Order, PointLog, User
from schemas import (
    AdminLoginRequest,
    MembershipAssignmentRequest,
    MembershipPlanUpsertRequest,
    UserMembershipOverrideRequest,
)
from services.admin_service import admin_login as admin_login_service, get_dashboard_data
from services.membership_service import (
    assign_team_membership,
    assign_user_membership,
    build_runtime_overview,
    build_user_membership_summary,
    create_membership_plan,
    create_starts_and_expires,
    list_membership_plans,
    update_membership_plan,
    upsert_user_membership_override,
)
from services.storage_service import recalculate_user_storage_usage, serialize_user_storage

router = APIRouter()


@router.post("/api/admin/login")
async def admin_login(req: AdminLoginRequest, request: Request, session: Session = Depends(get_session)):
    return admin_login_service(session, request, email=req.email, password=req.password)


@router.get("/api/admin/dashboard")
async def get_admin_dashboard(admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    return get_dashboard_data(session)


@router.get("/api/admin/users")
async def get_all_users(
    page: int = 1,
    size: int = 20,
    keyword: Optional[str] = None,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    query = select(User)
    if keyword:
        query = query.where(
            (User.nickname.contains(keyword))
            | (User.email.contains(keyword))
            | (User.register_ip.contains(keyword))
            | (User.last_login_ip.contains(keyword))
        )
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    users = session.exec(query.order_by(User.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": user.id,
                "nickname": user.nickname,
                "email": user.email,
                "is_active": user.is_active,
                "is_superadmin": user.is_superadmin,
                "vip_tier": user.vip_tier,
                "permanent_points": user.permanent_points,
                "temporary_points": user.temporary_points,
                "register_ip": user.register_ip,
                "last_login_ip": user.last_login_ip,
                "last_login_at": str(user.last_login_at) if user.last_login_at else None,
                "created_at": str(user.created_at) if user.created_at else None,
                "storage": serialize_user_storage(session, int(user.id)),
                **build_user_membership_summary(session, user.id),
            }
            for user in users
        ],
    }


@router.post("/api/admin/users/{user_id}/grant_points")
async def admin_grant_points(user_id: int, points: int, admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    target_user.permanent_points += points
    session.add(PointLog(
        user_id=target_user.id,
        change_amount=points,
        balance_after=target_user.permanent_points + target_user.temporary_points,
        action_type="admin_grant",
        description=f"系统管理员人工调整：{points} 点",
    ))
    session.add(target_user)
    session.commit()
    return {"status": "success", "msg": f"成功为用户 {target_user.nickname} 调整 {points} 点积分"}


@router.post("/api/admin/users/{user_id}/toggle_active")
async def toggle_user_active(user_id: int, admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if target_user.is_superadmin:
        raise HTTPException(status_code=400, detail="不能封禁超级管理员")
    target_user.is_active = not target_user.is_active
    session.add(target_user)
    session.commit()
    action = "解封" if target_user.is_active else "封禁"
    return {"status": "success", "is_active": target_user.is_active, "msg": f"已{action}用户 {target_user.nickname}"}


@router.post("/api/admin/users/{user_id}/set_vip")
async def set_user_vip(user_id: int, vip_tier: str, admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    target_user = session.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="用户不存在")
    plan = session.exec(select(MembershipPlan).where(MembershipPlan.code == vip_tier)).first()
    if not plan:
        raise HTTPException(status_code=404, detail="VIP 套餐不存在")
    assign_user_membership(
        session,
        user_id=user_id,
        payload={
            "plan_id": plan.id,
            "enabled": True,
            "duration_days": None if vip_tier == "free" else 30,
        },
    )
    return {"status": "success", "msg": f"已将用户 {target_user.nickname} 的 VIP 设为 {vip_tier}"}


@router.get("/api/admin/membership/plans")
async def get_membership_plans(admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    return {"items": list_membership_plans(session)}


@router.post("/api/admin/membership/plans")
async def post_membership_plan(
    payload: MembershipPlanUpsertRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    plan = create_membership_plan(session, payload.model_dump(exclude_unset=True))
    return {"status": "success", "item": plan.model_dump()}


@router.put("/api/admin/membership/plans/{plan_id}")
async def put_membership_plan(
    plan_id: int,
    payload: MembershipPlanUpsertRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    plan = update_membership_plan(session, plan_id, payload.model_dump(exclude_unset=True))
    return {"status": "success", "item": plan.model_dump()}


@router.post("/api/admin/users/{user_id}/membership")
async def post_user_membership(
    user_id: int,
    payload: MembershipAssignmentRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    starts_at, expires_at = create_starts_and_expires(payload.model_dump(exclude_unset=True))
    result = assign_user_membership(
        session,
        user_id=user_id,
        payload={**payload.model_dump(exclude_unset=True), "starts_at": starts_at, "expires_at": expires_at},
    )
    return {"status": "success", "item": result}


@router.post("/api/admin/teams/{team_id}/membership")
async def post_team_membership(
    team_id: int,
    payload: MembershipAssignmentRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    starts_at, expires_at = create_starts_and_expires(payload.model_dump(exclude_unset=True))
    result = assign_team_membership(
        session,
        team_id=team_id,
        payload={**payload.model_dump(exclude_unset=True), "starts_at": starts_at, "expires_at": expires_at},
    )
    return {"status": "success", "item": result}


@router.put("/api/admin/users/{user_id}/membership-override")
async def put_user_membership_override(
    user_id: int,
    payload: UserMembershipOverrideRequest,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    result = upsert_user_membership_override(session, user_id=user_id, payload=payload.model_dump(exclude_unset=True))
    return {"status": "success", "item": result}


@router.get("/api/admin/membership/runtime-overview")
async def get_membership_runtime_overview(admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    return build_runtime_overview(session)


@router.get("/api/admin/storage/users/{user_id}")
async def get_admin_user_storage(user_id: int, admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    del admin
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return {"success": True, "data": serialize_user_storage(session, user_id)}


@router.post("/api/admin/storage/users/{user_id}/recalculate")
async def recalculate_admin_user_storage(user_id: int, admin: User = Depends(get_current_admin), session: Session = Depends(get_session)):
    del admin
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="user not found")
    return {"success": True, "data": recalculate_user_storage_usage(session, user_id)}


@router.get("/api/admin/point_logs")
async def get_admin_point_logs(
    page: int = 1,
    size: int = 20,
    user_id: Optional[int] = None,
    action_type: Optional[str] = None,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    query = select(PointLog)
    if user_id:
        query = query.where(PointLog.user_id == user_id)
    if action_type:
        query = query.where(PointLog.action_type == action_type)
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    logs = session.exec(query.order_by(PointLog.id.desc()).offset((page - 1) * size).limit(size)).all()
    user_ids = list(set(log.user_id for log in logs if log.user_id))
    users_map = {}
    if user_ids:
        users_map = {user.id: user.nickname for user in session.exec(select(User).where(User.id.in_(user_ids))).all()}
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "user_nickname": users_map.get(log.user_id, "未知"),
                "change_amount": log.change_amount,
                "balance_after": log.balance_after,
                "action_type": log.action_type,
                "description": log.description,
                "created_at": str(log.created_at) if log.created_at else None,
            }
            for log in logs
        ],
    }


@router.get("/api/admin/orders")
async def get_admin_orders(
    page: int = 1,
    size: int = 20,
    status: Optional[str] = None,
    admin: User = Depends(get_current_admin),
    session: Session = Depends(get_session),
):
    query = select(Order)
    if status:
        query = query.where(Order.status == status)
    total = session.exec(select(func.count()).select_from(query.subquery())).one()
    orders = session.exec(query.order_by(Order.id.desc()).offset((page - 1) * size).limit(size)).all()
    user_ids = list(set(order.user_id for order in orders))
    users_map = {}
    if user_ids:
        users_map = {user.id: user.nickname for user in session.exec(select(User).where(User.id.in_(user_ids))).all()}
    return {
        "total": total,
        "page": page,
        "size": size,
        "items": [
            {
                "id": order.id,
                "order_no": order.order_no,
                "user_id": order.user_id,
                "user_nickname": users_map.get(order.user_id, "未知"),
                "package_name": order.package_name,
                "pay_amount": order.pay_amount,
                "points_added": order.points_added,
                "status": order.status,
                "created_at": str(order.created_at) if order.created_at else None,
                "paid_at": str(order.paid_at) if order.paid_at else None,
            }
            for order in orders
        ],
    }
