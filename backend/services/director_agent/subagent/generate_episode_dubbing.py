"""Subagent: 生成剧集配音（wizard 模式）"""
from typing import List

from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage
from ..schemas.subagent_schemas import TaskType, UserIntent
from .base import BaseSubagent, SubagentResult


class GenerateEpisodeDubbingSubagent(BaseSubagent):
    """为剧集生成配音，返回 wizard payload 由前端弹出向导"""

    name = "generate-episode-dubbing"
    description = "为剧集分镜生成配音，支持音色选择和批量提交"
    task_type = TaskType.DUBBING_PLANNING

    def required_stage(self) -> ProjectStage:
        return ProjectStage.HAS_IMAGES

    def required_context_fields(self) -> List[str]:
        return ["script", "episode"]

    def supported_intents(self) -> List[UserIntent]:
        return [UserIntent.DUBBING_PLANNING, UserIntent.MIXED_WORKFLOW]

    def requires_confirmation_before_execution(self) -> bool:
        return False

    def requires_confirmation_after_result(self) -> bool:
        return False

    def estimate_cost(self) -> int:
        return 0

    def run(self, context: ProjectContext) -> SubagentResult:
        panels_with_image = [
            {"id": p.id, "panel_no": p.panel_no, "summary": p.segment_summary}
            for p in context.panels
            if p.has_image
        ]

        summary = (
            f"共 {len(panels_with_image)} 个分镜已有图片，可生成配音。"
            "请在向导中选择音色和生成范围。"
        )

        return SubagentResult(
            success=True,
            data={
                "wizard_type": "dubbing_generation",
                "episode_id": context.episode_id,
                "panels_with_image": panels_with_image,
                "task_type": self.task_type.value,
                "tools_used": ["generate-episode-dubbing"],
            },
            summary=summary,
            next_actions=["选择音色开始配音", "查看已有配音"],
            write_operations=[],
        )
