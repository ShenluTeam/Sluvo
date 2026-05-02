"""Tool: 读取项目数据（确定性操作）"""
from typing import List, Optional

from sqlmodel import Session, select

from models import Episode, Panel, Script, SharedResource, GenerationRecord
from ..schemas.orchestrator_schemas import (
    ProjectContext, ScriptInfo, EpisodeInfo, PanelInfo,
    PanelsSummary, SharedResources, SharedResource as SR,
    GenerationRecord as GR, ProjectStage
)


class ProjectReaderTool:
    """读取项目相关数据（确定性 Tool）"""

    def get_project_context(
        self,
        session: Session,
        script_id: int,
        episode_id: Optional[int] = None
    ) -> ProjectContext:
        """获取完整项目上下文"""
        # 读取 Script
        script = session.get(Script, script_id)
        script_info = None
        if script:
            script_info = ScriptInfo(
                id=script.id,
                name=script.name,
                aspect_ratio=script.aspect_ratio or "16:9",
                style_preset=script.style_preset or "默认写实",
                has_source_text=bool(script.source_text),
            )

        # 读取 Episode
        episode = None
        episode_info = None
        if episode_id:
            episode = session.get(Episode, episode_id)
            if episode:
                episode_info = EpisodeInfo(
                    id=episode.id,
                    title=episode.title or f"第{episode.sequence_num}集",
                    sequence_num=episode.sequence_num,
                    has_source_text=bool(episode.source_text),
                    source_text=episode.source_text,  # 完整剧本原文
                    source_text_preview=episode.source_text[:200] if episode.source_text else None,
                )

        # 读取 Panels
        panels = []
        panels_summary = PanelsSummary(
            total=0, with_images=0, without_images=0,
            with_videos=0, without_videos=0,
            nine_grid_count=0, normal_count=0
        )
        if episode_id:
            panel_statement = select(Panel).where(Panel.episode_id == episode_id)
            db_panels = session.exec(panel_statement).all()
            for p in db_panels:
                panel_info = PanelInfo(
                    id=p.id,
                    panel_no=p.sequence_num,
                    segment_summary=p.segment_summary,
                    panel_type=f"grid_{getattr(p, 'grid_count', 1) or 1}",
                    has_image=bool(p.image_url),
                    has_video=bool(p.video_url),
                    image_url=p.image_url,
                )
                panels.append(panel_info)

            panels_summary = PanelsSummary(
                total=len(panels),
                with_images=sum(1 for p in panels if p.has_image),
                without_images=sum(1 for p in panels if not p.has_image),
                with_videos=sum(1 for p in panels if p.has_video),
                without_videos=sum(1 for p in panels if not p.has_video),
                nine_grid_count=sum(1 for p in panels if str(p.panel_type).endswith("9")),
                normal_count=sum(1 for p in panels if str(p.panel_type).endswith("1")),
            )

        # 读取 SharedResources
        resource_statement = select(SharedResource).where(SharedResource.script_id == script_id)
        db_resources = session.exec(resource_statement).all()
        characters = [SR(id=r.id, name=r.name, resource_type=r.resource_type, has_image=bool(r.thumbnail_url)) for r in db_resources if r.resource_type == "character"]
        scenes = [SR(id=r.id, name=r.name, resource_type=r.resource_type, has_image=bool(r.thumbnail_url)) for r in db_resources if r.resource_type == "scene"]
        props = [SR(id=r.id, name=r.name, resource_type=r.resource_type, has_image=bool(r.thumbnail_url)) for r in db_resources if r.resource_type == "prop"]
        shared_resources = SharedResources(characters=characters, scenes=scenes, props=props)

        # 读取 GenerationRecords
        generation_records = []
        if episode_id:
            from models import GenerationRecord
            record_statement = select(GenerationRecord).where(GenerationRecord.episode_id == episode_id)
            db_records = session.exec(record_statement).all()
            for r in db_records:
                generation_records.append(GR(
                    id=r.id,
                    record_type=r.record_type,
                    panel_id=r.target_id if r.target_type == "panel" else None,
                    status=r.status,
                    created_at=r.created_at.isoformat() if r.created_at else "",
                ))

        # 检测项目阶段
        stage = self._detect_stage(episode_info, panels_summary)

        # 检查缺失的上下文
        missing = self._check_missing_context(episode_info, panels, shared_resources)

        return ProjectContext(
            script_id=script_id,
            episode_id=episode_id,
            script=script_info,
            episode=episode_info,
            panels=panels,
            panels_summary=panels_summary,
            shared_resources=shared_resources,
            generation_records=generation_records,
            stage=stage,
            missing_context=missing,
        )

    def get_episode_source_text(self, session: Session, episode_id: int) -> str:
        """获取剧集剧本原文"""
        episode = session.get(Episode, episode_id)
        return episode.source_text or "" if episode else ""

    def get_panels_summary(self, session: Session, episode_id: int) -> PanelsSummary:
        """获取分镜统计"""
        panel_statement = select(Panel).where(Panel.episode_id == episode_id)
        db_panels = session.exec(panel_statement).all()

        panels = []
        for p in db_panels:
            panels.append(PanelInfo(
                id=p.id,
                panel_no=p.sequence_num,
                segment_summary=p.segment_summary,
                panel_type=f"grid_{getattr(p, 'grid_count', 1) or 1}",
                has_image=bool(p.image_url),
                has_video=bool(p.video_url),
            ))

        return PanelsSummary(
            total=len(panels),
            with_images=sum(1 for p in panels if p.has_image),
            without_images=sum(1 for p in panels if not p.has_image),
            with_videos=sum(1 for p in panels if p.has_video),
            without_videos=sum(1 for p in panels if not p.has_video),
            nine_grid_count=sum(1 for p in panels if str(p.panel_type).endswith("9")),
            normal_count=sum(1 for p in panels if str(p.panel_type).endswith("1")),
        )

    def get_shared_resources(self, session: Session, script_id: int) -> SharedResources:
        """获取共享资源"""
        resource_statement = select(SharedResource).where(SharedResource.script_id == script_id)
        db_resources = session.exec(resource_statement).all()

        characters = [SR(id=r.id, name=r.name, resource_type=r.resource_type, has_image=bool(r.thumbnail_url)) for r in db_resources if r.resource_type == "character"]
        scenes = [SR(id=r.id, name=r.name, resource_type=r.resource_type, has_image=bool(r.thumbnail_url)) for r in db_resources if r.resource_type == "scene"]
        props = [SR(id=r.id, name=r.name, resource_type=r.resource_type, has_image=bool(r.thumbnail_url)) for r in db_resources if r.resource_type == "prop"]

        return SharedResources(characters=characters, scenes=scenes, props=props)

    def _detect_stage(self, episode: Optional[EpisodeInfo], panels_summary: PanelsSummary) -> ProjectStage:
        """检测项目阶段"""
        if not episode or not episode.has_source_text:
            return ProjectStage.PROJECT_EMPTY
        if panels_summary.total == 0:
            return ProjectStage.SCRIPT_READY
        if panels_summary.with_images == 0:
            return ProjectStage.STORYBOARD_READY
        if panels_summary.with_images > 0 and panels_summary.with_videos == 0:
            return ProjectStage.HAS_IMAGES
        if panels_summary.with_videos > 0:
            return ProjectStage.HAS_VIDEOS
        return ProjectStage.STORYBOARD_READY

    def _check_missing_context(self, episode: Optional[EpisodeInfo], panels: List[PanelInfo], shared_resources: SharedResources) -> List[str]:
        """检查缺失的上下文"""
        missing = []
        if not episode:
            missing.append("缺少剧集信息")
        elif not episode.has_source_text:
            missing.append("剧集缺少剧本原文")
        if not shared_resources.characters:
            missing.append("缺少角色资产")
        if not shared_resources.scenes:
            missing.append("缺少场景资产")
        return missing
