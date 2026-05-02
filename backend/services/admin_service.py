from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request
from sqlalchemy import func
from sqlmodel import Session, select

from core.security import verify_password
from models import Order, OrderStatusEnum, PointLog, User


def admin_login(session: Session, request: Request, *, email: str, password: str) -> dict:
    user = session.exec(select(User).where(User.email == email)).first()
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=400, detail="邮箱或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="该账号已被封禁")
    if not user.is_superadmin:
        raise HTTPException(status_code=403, detail="该账号不是超级管理员")
    user.last_login_ip = request.client.host if request.client else None
    user.last_login_at = datetime.utcnow()
    user.session_token = str(uuid.uuid4())
    session.add(user)
    session.commit()
    return {"status": "success", "token": user.session_token, "nickname": user.nickname, "email": user.email}


def get_dashboard_data(session: Session) -> dict:
    now = datetime.utcnow()
    today_start = datetime.combine(now.date(), datetime.min.time())
    total_users = session.exec(select(func.count(User.id))).one()
    new_users_today = len(session.exec(select(User).where(User.created_at >= today_start)).all())
    total_permanent = session.exec(select(func.sum(User.permanent_points))).one() or 0
    total_temporary = session.exec(select(func.sum(User.temporary_points))).one() or 0
    today_logs = session.exec(select(PointLog).where(PointLog.created_at >= today_start)).all()
    today_consumed = sum(abs(log.change_amount) for log in today_logs if log.change_amount < 0)
    today_orders = session.exec(
        select(Order).where(Order.paid_at >= today_start, Order.status == OrderStatusEnum.PAID)
    ).all()
    today_revenue = sum(order.pay_amount for order in today_orders)
    trend = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        day_start = datetime.combine(day, datetime.min.time())
        day_end = datetime.combine(day, datetime.max.time())
        day_new_users = len(session.exec(select(User).where(User.created_at >= day_start, User.created_at <= day_end)).all())
        day_orders = session.exec(
            select(Order).where(Order.paid_at >= day_start, Order.paid_at <= day_end, Order.status == OrderStatusEnum.PAID)
        ).all()
        trend.append({"date": str(day), "new_users": day_new_users, "revenue": sum(order.pay_amount for order in day_orders)})
    return {
        "total_users": total_users,
        "new_users_today": new_users_today,
        "system_liability_points": total_permanent + total_temporary,
        "today_consumed_points": today_consumed,
        "today_revenue": today_revenue,
        "trend": trend,
    }
