"""Subagent: 分析故事上下文"""
from typing import List

from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage
from ..schemas.subagent_schemas import TaskType, UserIntent
from .base import BaseSubagent, SubagentResult


class AnalyzeStoryContextSubagent(BaseSubagent):
    """分析故事上下文，确定项目阶段"""

    name = "analyze-story-context"
    description = "分析项目当前阶段，建议下一步操作"
    task_type = TaskType.SCRIPT_ANALYSIS

    def required_stage(self) -> ProjectStage:
        """任意阶段都可执行分析"""
        return ProjectStage.PROJECT_EMPTY

    def required_context_fields(self) -> List[str]:
        return ["script"]

    def supported_intents(self) -> List[UserIntent]:
        return [
            UserIntent.SCRIPT_ANALYSIS,
            UserIntent.GENERAL_CHAT,
            UserIntent.MIXED_WORKFLOW,
        ]

    def requires_confirmation_before_execution(self) -> bool:
        """分析是只读操作，不需要确认"""
        return False

    def requires_confirmation_after_result(self) -> bool:
        return False

    def estimate_cost(self) -> int:
        """分析不消耗灵感值"""
        return 0

    def run(self, context: ProjectContext) -> SubagentResult:
        """执行分析"""
        stage = context.stage
        suggestions = []

        # 根据当前阶段给出建议
        if stage == ProjectStage.PROJECT_EMPTY:
            suggestions = [
                "导入剧本原文开始创作",
                "从现有剧本选择一个剧集",
            ]
        elif stage == ProjectStage.SCRIPT_READY:
            suggestions = [
                "拆分剧情片段，梳理叙事结构",
                "直接生成分镜方案",
                "分析角色和场景需求",
            ]
        elif stage == ProjectStage.SEGMENTS_READY:
            suggestions = [
                "生成分镜方案",
                "调整片段划分",
                "查看已有分镜草稿",
            ]
        elif stage == ProjectStage.STORYBOARD_READY:
            suggestions = [
                "生成第 N 张分镜图片",
                "生成配套视频",
                "为分镜添加配音",
            ]
        elif stage == ProjectStage.HAS_IMAGES:
            suggestions = [
                "生成视频片段",
                "补充缺失的分镜图片",
                "调整现有图片",
            ]
        elif stage == ProjectStage.HAS_VIDEOS:
            suggestions = [
                "合成完整视频",
                "添加字幕和配音",
                "导出最终成品",
            ]

        # 构建上下文摘要
        context_summary = []
        if context.script:
            context_summary.append(f"剧本《{context.script.name}》")
        if context.episode:
            context_summary.append(f"第{context.episode.sequence_num}集《{context.episode.title}》")
        if context.panels_summary.total > 0:
            context_summary.append(f"已有{context.panels_summary.total}个分镜")
        if context.shared_resources.characters:
            context_summary.append(f"{len(context.shared_resources.characters)}个角色")
        if context.shared_resources.scenes:
            context_summary.append(f"{len(context.shared_resources.scenes)}个场景")

        summary_text = "、".join(context_summary) if context_summary else "项目为空"
        stage_text = {
            ProjectStage.PROJECT_EMPTY: "项目为空，请先导入剧本",
            ProjectStage.SCRIPT_READY: "剧本已就绪，可以开始创作",
            ProjectStage.SEGMENTS_READY: "片段已拆分，可生成分镜",
            ProjectStage.STORYBOARD_READY: "分镜已生成，等待生成媒体",
            ProjectStage.HAS_IMAGES: "部分分镜已有图片",
            ProjectStage.HAS_VIDEOS: "已有视频内容",
        }.get(stage, "未知阶段")

        return SubagentResult(
            success=True,
            data={
                "current_stage": stage.value,
                "task_type": self.task_type.value,
                "stage_description": stage_text,
                "context_summary": summary_text,
                "suggestions": suggestions,
                "missing_context": context.missing_context,
                "tools_used": ["read_project"],
                "panels_summary": context.panels_summary.__dict__ if context.panels_summary else None,
                "resource_counts": {
                    "characters": len(context.shared_resources.characters),
                    "scenes": len(context.shared_resources.scenes),
                    "props": len(context.shared_resources.props),
                },
            },
            summary=f"{summary_text}。{stage_text}",
            warnings=context.missing_context if context.missing_context else [],
            next_actions=suggestions,
            stage_change=None,  # 分析不改变阶段
            write_operations=[],  # 分析不产生写入操作
        )
