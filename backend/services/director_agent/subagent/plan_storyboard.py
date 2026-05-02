from typing import Any, Dict, List

from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage
from ..schemas.subagent_schemas import TaskType, UserIntent
from ..tools.script_parser_tool import ScriptParserTool
from .base import BaseSubagent, SubagentResult, WriteOperation


class PlanStoryboardSubagent(BaseSubagent):
    """规划多宫格剧情片段方案。"""

    name = "plan-storyboard"
    description = "为剧集生成多宫格连续剧情片段方案"
    task_type = TaskType.STORYBOARD_PLANNING

    def required_stage(self) -> ProjectStage:
        return ProjectStage.SCRIPT_READY

    def required_context_fields(self) -> List[str]:
        return ["script", "episode", "source_text"]

    def supported_intents(self) -> List[UserIntent]:
        return [UserIntent.STORYBOARD_PLANNING, UserIntent.MIXED_WORKFLOW]

    def requires_confirmation_before_execution(self) -> bool:
        return True

    def requires_confirmation_after_result(self) -> bool:
        return True

    def estimate_cost(self) -> int:
        return 0

    def get_preview(self, context: ProjectContext) -> Dict[str, Any]:
        preview = {
            "episode_title": context.episode.title if context.episode else "未选择剧集",
            "source_text_length": len(context.episode.source_text) if context.episode and context.episode.source_text else 0,
        }
        text_length = preview["source_text_length"]
        preview["estimated_segments"] = max(3, min(24, max(text_length // 180, 1))) if text_length > 0 else 0
        preview["resource_counts"] = {
            "characters": len(context.shared_resources.characters),
            "scenes": len(context.shared_resources.scenes),
            "props": len(context.shared_resources.props),
        }
        return preview

    def run(self, context: ProjectContext) -> SubagentResult:
        missing_fields = self.check_context(context)
        if missing_fields:
            return SubagentResult(
                success=False,
                data=None,
                summary="上下文不足，无法生成剧情片段方案",
                warnings=missing_fields,
                next_actions=["补充剧本信息后重试"],
                stage_change=None,
                write_operations=[],
            )

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
            tool = ScriptParserTool()
            result = tool.parse_story_segments_v3_full(
                episode_id=episode.id,
                source_text=episode.source_text,
            )

            story_segments = result.get("story_segments") or []
            warnings = result.get("warnings", [])
            grid_distribution: Dict[str, int] = {}
            segment_summaries = []
            for segment in story_segments:
                grid_count = int(segment.get("grid_count") or 1)
                grid_distribution[str(grid_count)] = grid_distribution.get(str(grid_count), 0) + 1
                segment_summaries.append({
                    "sequence_num": segment.get("sequence_num", 0),
                    "title": segment.get("title", ""),
                    "summary": segment.get("summary", ""),
                    "grid_count": grid_count,
                    "character_refs": segment.get("character_refs", []),
                    "scene_refs": segment.get("scene_refs", []),
                    "has_image_prompt": bool(segment.get("segment_prompt_summary")),
                })

            write_op = WriteOperation(
                type="CREATE_PANELS",
                target="panels",
                data=story_segments,
                sync_resources=True,
                replace_existing=False,
            )

            return SubagentResult(
                success=True,
                data={
                    "task_type": self.task_type.value,
                    "story_segments": segment_summaries,
                    "segment_count": len(story_segments),
                    "grid_distribution": grid_distribution,
                    "characters": result.get("characters", []),
                    "scenes": result.get("scenes", []),
                    "props": result.get("props", []),
                    "billing": result.get("billing", {}),
                    "warnings": warnings,
                    "tools_used": ["script_parser", "plan-storyboard"],
                },
                summary=f"生成了 {len(story_segments)} 个剧情片段草稿，宫格分布：{grid_distribution}",
                warnings=warnings,
                next_actions=["确认后写入片段", "预览并调整宫格", "重新生成"],
                stage_change=ProjectStage.STORYBOARD_READY,
                write_operations=[write_op],
            )
        except Exception as e:
            return SubagentResult(
                success=False,
                data=None,
                summary=f"剧情片段规划失败：{e}",
                warnings=[str(e)],
                next_actions=["检查原文与资产后重试"],
                stage_change=None,
                write_operations=[],
            )
