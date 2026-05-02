"""Orchestrator: 检测项目阶段"""
from typing import List

from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage


class StageDetector:
    """检测项目阶段"""

    def detect(self, context: ProjectContext) -> ProjectStage:
        """
        检测当前项目阶段

        Args:
            context: 项目上下文

        Returns:
            ProjectStage: 当前阶段
        """
        # 按优先级检测
        if not context.episode or not context.episode.has_source_text:
            return ProjectStage.PROJECT_EMPTY

        if context.panels_summary.total == 0:
            return ProjectStage.SCRIPT_READY

        # 检查是否有 segment_only 标记的分镜
        has_segments = any(
            p.segment_summary and not p.has_image
            for p in context.panels
        )

        if has_segments and context.panels_summary.with_images == 0:
            return ProjectStage.SEGMENTS_READY

        if context.panels_summary.with_images == 0:
            return ProjectStage.STORYBOARD_READY

        if context.panels_summary.with_images > 0 and context.panels_summary.with_videos == 0:
            return ProjectStage.HAS_IMAGES

        if context.panels_summary.with_videos > 0:
            return ProjectStage.HAS_VIDEOS

        return ProjectStage.STORYBOARD_READY

    def get_stage_description(self, stage: ProjectStage) -> str:
        """获取阶段的描述文本"""
        descriptions = {
            ProjectStage.PROJECT_EMPTY: "项目为空，请先导入剧本",
            ProjectStage.SCRIPT_READY: "剧本已就绪，可以开始创作",
            ProjectStage.SEGMENTS_READY: "片段已拆分，可生成分镜",
            ProjectStage.STORYBOARD_READY: "分镜已生成，等待生成媒体",
            ProjectStage.HAS_IMAGES: "部分分镜已有图片",
            ProjectStage.HAS_VIDEOS: "已有视频内容",
            ProjectStage.AUDIO_READY: "配音已生成",
            ProjectStage.REVIEW: "审核中",
            ProjectStage.FINALIZE: "已完成终稿",
        }
        return descriptions.get(stage, "未知阶段")

    def get_next_recommended_actions(self, stage: ProjectStage) -> List[str]:
        """获取当前阶段的推荐操作"""
        actions = {
            ProjectStage.PROJECT_EMPTY: ["导入剧本原文"],
            ProjectStage.SCRIPT_READY: ["拆分剧情片段", "生成分镜方案", "提取项目资产"],
            ProjectStage.SEGMENTS_READY: ["生成分镜方案", "调整片段"],
            ProjectStage.STORYBOARD_READY: ["生成图片", "生成视频"],
            ProjectStage.HAS_IMAGES: ["生成视频", "补充图片", "生成配音"],
            ProjectStage.HAS_VIDEOS: ["合成完整视频", "添加配音"],
            ProjectStage.AUDIO_READY: ["合成完整视频", "导出成片"],
            ProjectStage.REVIEW: ["确认成片", "修改调整"],
            ProjectStage.FINALIZE: ["导出项目"],
        }
        return actions.get(stage, [])
