"""Tool: 查询生成记录（确定性操作）"""
from typing import List, Optional

from sqlmodel import Session, select

from models import GenerationRecord
from ..schemas.orchestrator_schemas import GenerationRecord as GR


class GenerationQueryTool:
    """查询生成记录（确定性 Tool）"""

    def query_generation_records(
        self,
        session: Session,
        episode_id: int,
        record_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100
    ) -> List[GR]:
        """
        查询生成记录

        Args:
            session: 数据库会话
            episode_id: 剧集 ID
            record_type: 记录类型 (image/video/audio)，None 表示全部
            status: 状态 (pending/completed/failed)，None 表示全部
            limit: 返回数量限制

        Returns:
            List[GenerationRecord]: 生成记录列表
        """
        statement = select(GenerationRecord).where(GenerationRecord.episode_id == episode_id)

        if record_type:
            statement = statement.where(GenerationRecord.record_type == record_type)
        if status:
            statement = statement.where(GenerationRecord.status == status)

        statement = statement.order_by(GenerationRecord.created_at.desc()).limit(limit)

        db_records = session.exec(statement).all()

        return [
            GR(
                id=r.id,
                record_type=r.record_type,
                panel_id=r.panel_id,
                status=r.status,
                created_at=r.created_at.isoformat() if r.created_at else "",
            )
            for r in db_records
        ]

    def get_pending_count(
        self,
        session: Session,
        episode_id: int,
        record_type: Optional[str] = None
    ) -> int:
        """获取待处理记录数量"""
        statement = select(GenerationRecord).where(
            GenerationRecord.episode_id == episode_id,
            GenerationRecord.status == "pending"
        )

        if record_type:
            statement = statement.where(GenerationRecord.record_type == record_type)

        return len(session.exec(statement).all())

    def get_completed_stats(
        self,
        session: Session,
        episode_id: int
    ) -> dict:
        """获取已完成统计"""
        statement = select(GenerationRecord).where(
            GenerationRecord.episode_id == episode_id,
            GenerationRecord.status == "completed"
        )

        records = session.exec(statement).all()

        image_count = sum(1 for r in records if r.record_type == "image")
        video_count = sum(1 for r in records if r.record_type == "video")
        audio_count = sum(1 for r in records if r.record_type == "audio")

        return {
            "total": len(records),
            "images": image_count,
            "videos": video_count,
            "audios": audio_count,
        }
