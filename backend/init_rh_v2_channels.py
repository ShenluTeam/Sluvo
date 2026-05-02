"""
One-time script: Insert the 4 new RunningHub V2 Standard Model channels into ChannelSettings.
Run once on the server:  python init_rh_v2_channels.py
"""
from database import engine, create_db_and_tables
from sqlmodel import Session, select
from models import ChannelSettings

NEW_CHANNELS = [
    {
        "channel_id": "rh-v2-text2img",
        "name": "全能图片V2-文生图",
        "description": "RunningHub Flash 文生图，极速出图",
        "cost_points": 1,
        "is_active": True,
        "is_vip_only": False,
        "sort_order": 10,
    },
    {
        "channel_id": "rh-v2-img2img",
        "name": "全能图片V2-图生图",
        "description": "RunningHub Flash 图生图，上传参考图生成",
        "cost_points": 1,
        "is_active": True,
        "is_vip_only": False,
        "sort_order": 11,
    },
    {
        "channel_id": "rh-v2-official-text2img",
        "name": "全能图片V2-官方-文生图",
        "description": "RunningHub 官方文生图 (定价随分辨率: 1k=6/2k=8/4k=10)",
        "cost_points": 6,  # 最低档基准价，实际由路由层动态计算
        "is_active": True,
        "is_vip_only": False,
        "sort_order": 12,
    },
    {
        "channel_id": "rh-v2-official-img2img",
        "name": "全能图片V2-官方-图生图",
        "description": "RunningHub 官方图生图 (定价随分辨率: 1k=6/2k=8/4k=10)",
        "cost_points": 6,
        "is_active": True,
        "is_vip_only": False,
        "sort_order": 13,
    },
]

def main():
    create_db_and_tables()
    with Session(engine) as session:
        for ch_data in NEW_CHANNELS:
            existing = session.exec(
                select(ChannelSettings).where(ChannelSettings.channel_id == ch_data["channel_id"])
            ).first()
            if existing:
                print(f"  [SKIP] {ch_data['channel_id']} already exists")
                continue
            channel = ChannelSettings(**ch_data)
            session.add(channel)
            print(f"  [ADD]  {ch_data['channel_id']} -> {ch_data['name']}")
        session.commit()
    print("Done! 4 new channels initialized.")

if __name__ == "__main__":
    main()
