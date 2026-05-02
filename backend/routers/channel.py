from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from database import get_session
from dependencies import get_current_user
from models import User, ChannelSettings
from schemas import ChannelUpdate

router = APIRouter()

@router.get("/api/channels")
async def get_channels(session: Session = Depends(get_session)):
    """获取所有启用的通道，包含价格和 VIP 状态 (供前端拉取)"""
    statement = select(ChannelSettings).where(ChannelSettings.is_active == True).order_by(ChannelSettings.sort_order.asc())
    channels = session.exec(statement).all()
    return channels

@router.put("/api/admin/channels/{channel_id}")
async def update_channel_settings(
    channel_id: str, 
    update_data: ChannelUpdate,
    current_user: User = Depends(get_current_user), 
    session: Session = Depends(get_session)
):
    """管理员修改通道配置"""
    if not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="没有超级管理员权限")
    statement = select(ChannelSettings).where(ChannelSettings.channel_id == channel_id)
    channel = session.exec(statement).first()
    if not channel:
        raise HTTPException(status_code=404, detail="通道不存在")
    update_dict = update_data.model_dump(exclude_unset=True)
    for key, value in update_dict.items():
        setattr(channel, key, value)
    session.add(channel)
    session.commit()
    session.refresh(channel)
    return channel
