"""Subagent: 生成分镜图片（wizard 模式）"""
from typing import List

from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage
from ..schemas.subagent_schemas import TaskType, UserIntent
from .base import BaseSubagent, SubagentResult


class GeneratePanelImageSubagent(BaseSubagent):
    """为分镜生成图片，返回 wizard payload 由前端弹出向导"""

    name = "generate-panel-image"
    description = "为分镜方案生成图片，支持批量选择和模型推荐"
    task_type = TaskType.IMAGE_GENERATION_PLANNING

    def required_stage(self) -> ProjectStage:
        return ProjectStage.STORYBOARD_READY

    def required_context_fields(self) -> List[str]:
        return ["script", "episode"]

    def supported_intents(self) -> List[UserIntent]:
        return [UserIntent.IMAGE_GENERATION, UserIntent.MIXED_WORKFLOW]

    def requires_confirmation_before_execution(self) -> bool:
        return False

    def requires_confirmation_after_result(self) -> bool:
        return False

    def estimate_cost(self) -> int:
        return 0

    def run(self, context: ProjectContext) -> SubagentResult:
        panels_without_image = [
            {"id": p.id, "panel_no": p.panel_no, "summary": p.segment_summary}
            for p in context.panels
            if not p.has_image
        ]
        total = context.panels_summary.total
        pending = len(panels_without_image)

        summary = (
            f"共 {total} 个分镜，其中 {pending} 个尚未生成图片。"
            "请在向导中选择生成范围和图片模型。"
        )

        return SubagentResult(
            success=True,
            data={
                "wizard_type": "image_generation",
                "episode_id": context.episode_id,
                "panels_without_image": panels_without_image,
                "total_panels": total,
                "pending_panels": pending,
                "task_type": self.task_type.value,
                "tools_used": ["generate-panel-image"],
            },
            summary=summary,
            next_actions=["选择全部分镜生成", "选择部分分镜生成"],
            write_operations=[],
        )
