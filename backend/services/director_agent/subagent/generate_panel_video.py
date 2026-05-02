"""Subagent: 生成分镜视频（wizard 模式）"""
from typing import List

from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage
from ..schemas.subagent_schemas import TaskType, UserIntent
from .base import BaseSubagent, SubagentResult


class GeneratePanelVideoSubagent(BaseSubagent):
    """为已有图片的分镜生成视频，返回 wizard payload。"""

    name = "generate-panel-video"
    description = "为已有图片的分镜生成视频，支持批量选择和模型建议"
    task_type = TaskType.VIDEO_GENERATION_PLANNING

    def required_stage(self) -> ProjectStage:
        return ProjectStage.HAS_IMAGES

    def required_context_fields(self) -> List[str]:
        return ["script", "episode"]

    def supported_intents(self) -> List[UserIntent]:
        return [UserIntent.VIDEO_GENERATION, UserIntent.MIXED_WORKFLOW]

    def requires_confirmation_before_execution(self) -> bool:
        return False

    def requires_confirmation_after_result(self) -> bool:
        return False

    def estimate_cost(self) -> int:
        return 0

    def run(self, context: ProjectContext) -> SubagentResult:
        panels_with_image = [
            {"id": p.id, "panel_no": p.panel_no, "summary": p.segment_summary, "has_video": p.has_video}
            for p in context.panels
            if p.has_image
        ]
        pending_panels = [item for item in panels_with_image if not item.get("has_video")]
        total = context.panels_summary.total
        pending = len(pending_panels)

        summary = (
            f"共 {total} 个分镜，其中 {len(panels_with_image)} 个已有图片，"
            f"{pending} 个还可以继续生成视频。请在向导中选择范围和模型。"
        )

        return SubagentResult(
            success=True,
            data={
                "wizard_type": "video_generation",
                "episode_id": context.episode_id,
                "panels_with_image": panels_with_image,
                "pending_panels": pending_panels,
                "total_panels": total,
                "pending_count": pending,
                "task_type": self.task_type.value,
                "tools_used": ["generate-panel-video"],
            },
            summary=summary,
            next_actions=["选择全部可用分镜生成视频", "选择部分分镜生成视频"],
            write_operations=[],
        )
