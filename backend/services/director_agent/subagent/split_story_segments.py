"""Subagent: 拆分剧情片段"""
from typing import Any, Dict, List

from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage
from ..schemas.subagent_schemas import TaskType, UserIntent
from ..tools.project_reader import ProjectReaderTool
from ..tools.script_parser_tool import ScriptParserTool
from .base import BaseSubagent, SubagentResult


class SplitStorySegmentsSubagent(BaseSubagent):
    """拆分剧情片段"""

    name = "split-story-segments"
    description = "将剧本文本拆分为剧情片段，分析叙事结构"
    task_type = TaskType.SEGMENT_PLANNING

    def required_stage(self) -> ProjectStage:
        """需要剧本就绪"""
        return ProjectStage.SCRIPT_READY

    def required_context_fields(self) -> List[str]:
        return ["script", "episode", "source_text"]

    def supported_intents(self) -> List[UserIntent]:
        return [
            UserIntent.SEGMENT_PLANNING,
            UserIntent.MIXED_WORKFLOW,
        ]

    def requires_confirmation_before_execution(self) -> bool:
        """拆分是免费操作，但仍需告知用户"""
        return True

    def requires_confirmation_after_result(self) -> bool:
        """拆分结果不需要写入确认"""
        return False

    def estimate_cost(self) -> int:
        """拆分不消耗灵感值"""
        return 0

    def get_preview(self, context: ProjectContext) -> Dict[str, Any]:
        """获取预览信息（用于 plan card）"""
        preview = {
            "episode_title": context.episode.title if context.episode else "未选择剧集",
            "source_text_length": len(context.episode.source_text) if context.episode and context.episode.source_text else 0,
        }

        # 估算片段数量（基于文本长度）
        text_length = preview["source_text_length"]
        if text_length > 0:
            # 简单估算：每 500 字一个片段
            preview["estimated_segments"] = max(3, min(30, text_length // 500))
        else:
            preview["estimated_segments"] = 0

        return preview

    def run(self, context: ProjectContext) -> SubagentResult:
        """执行片段拆分"""
        # 检查上下文
        missing_fields = self.check_context(context)
        if missing_fields:
            return SubagentResult(
                success=False,
                data=None,
                summary="上下文不足，无法执行片段拆分",
                warnings=missing_fields,
                next_actions=["补充剧本信息后重试"],
                stage_change=None,
                write_operations=[],
            )

        # 获取剧本文本
        episode = context.episode
        if not episode or not episode.source_text:
            return SubagentResult(
                success=False,
                data=None,
                summary="剧集缺少剧本原文",
                warnings=["剧集缺少剧本原文"],
                next_actions=["上传剧本原文后重试"],
                stage_change=None,
                write_operations=[],
            )

        try:
            # 调用解析工具
            tool = ScriptParserTool()
            result = tool.parse_script_for_segments(episode.source_text)

            segments = result.get("segments", [])
            warnings = result.get("warnings", [])

            # 格式化片段摘要
            segment_summaries = []
            for seg in segments:
                segment_summaries.append({
                    "segment_no": seg.get("segment_no", 0),
                    "summary": seg.get("summary", ""),
                    "narrative_purpose": seg.get("narrative_purpose", ""),
                    "emotion": seg.get("emotion", ""),
                    "recommended_panel_type": seg.get("recommended_panel_type", "normal"),
                    "reason": seg.get("reason", ""),
                })

            return SubagentResult(
                success=True,
                data={
                    "task_type": self.task_type.value,
                    "segments": segment_summaries,
                    "total_segments": len(segments),
                    "warnings": warnings,
                    "tools_used": ["script_parser"],
                },
                summary=f"分析完成，共识别 {len(segments)} 个剧情片段",
                warnings=warnings,
                next_actions=["确认后生成分镜方案", "调整片段划分", "重新分析剧本"],
                stage_change=ProjectStage.SEGMENTS_READY,
                write_operations=[],  # 不自动写入，需要用户确认
            )

        except Exception as e:
            return SubagentResult(
                success=False,
                data=None,
                summary=f"片段拆分失败: {str(e)}",
                warnings=[str(e)],
                next_actions=["检查剧本格式后重试"],
                stage_change=None,
                write_operations=[],
            )
