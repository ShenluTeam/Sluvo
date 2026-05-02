from sqlmodel import Session, select
from database import engine
from models import ChannelSettings

# 定义要初始化的视频生成通道
VIDEO_CHANNELS = [
    {
        "channel_id": "suchuang-veo3.1-pro",
        "name": "VEO 3.1 Pro (速创)",
        "description": "veo 3.1 pro 高质量带有声音的视频生成。基础消耗: 4灵感值/秒。",
        "cost_points": 4,
        "is_active": True,
        "is_vip_only": False,
        "sort_order": 51
    },
    {
        "channel_id": "suchuang-digital-human",
        "name": "数字人对口型 (速创)",
        "description": "上传人物正面视频+音频，驱动数字人精准对口型。基础消耗: 1灵感值/秒。",
        "cost_points": 1,
        "is_active": True,
        "is_vip_only": False,
        "sort_order": 52
    },
    {
        "channel_id": "runninghub-vidu-q3-pro",
        "name": "Vidu Q3 Pro (RunningHub)",
        "description": "支持长达 16 秒的视频，支持音效生成。基础消耗: 2灵感值/秒。",
        "cost_points": 2,
        "is_active": True,
        "is_vip_only": False,
        "sort_order": 60
    },
    {
        "channel_id": "runninghub-vidu-q2-pro",
        "name": "Vidu Q2 Pro (RunningHub)",
        "description": "针对短视频处理，可调节运动运镜幅度。基础消耗: 2灵感值/秒。",
        "cost_points": 2,
        "is_active": True,
        "is_vip_only": False,
        "sort_order": 61
    }
]

def init_video_channels():
    print("开始初始化/更新视频通道配置...")
    with Session(engine) as session:
        for channel_data in VIDEO_CHANNELS:
            # 查找是否已存在该通道
            existing = session.exec(
                select(ChannelSettings).where(ChannelSettings.channel_id == channel_data["channel_id"])
            ).first()
            
            if existing:
                print(f"通道 {channel_data['channel_id']} 已存在，进行更新...")
                existing.name = channel_data["name"]
                existing.description = channel_data["description"]
                existing.cost_points = channel_data["cost_points"]
                existing.is_active = channel_data["is_active"]
                existing.is_vip_only = channel_data["is_vip_only"]
                existing.sort_order = channel_data["sort_order"]
                session.add(existing)
            else:
                print(f"通道 {channel_data['channel_id']} 不存在，新增...")
                new_channel = ChannelSettings(**channel_data)
                session.add(new_channel)

        # ??????????????????
        legacy_fast = session.exec(
            select(ChannelSettings).where(ChannelSettings.channel_id == "suchuang-veo3.1-fast")
        ).first()
        if legacy_fast:
            legacy_fast.is_active = False
            session.add(legacy_fast)
        
        # 提交更改
        try:
            session.commit()
            print("===========================")
            print("✅ 视频通道初始化成功完成！")
            print("===========================")
        except Exception as e:
            session.rollback()
            print(f"❌ 视频通道初始化失败: {str(e)}")

if __name__ == "__main__":
    init_video_channels()
