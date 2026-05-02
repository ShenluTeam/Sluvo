"""Subagent: 提取项目资产"""
from typing import List

from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage
from ..schemas.subagent_schemas import TaskType, UserIntent
from .base import BaseSubagent, SubagentResult, WriteOperation


class ExtractProjectAssetsSubagent(BaseSubagent):
    """从剧本原文中提取角色、场景、道具资产"""

    name = "extract-project-assets"
    description = "分析剧本原文，提取可复用的角色、场景和道具资产"
    task_type = TaskType.MIXED_WORKFLOW

    def required_stage(self) -> ProjectStage:
        return ProjectStage.SCRIPT_READY

    def required_context_fields(self) -> List[str]:
        return ["script", "episode", "source_text"]

    def supported_intents(self) -> List[UserIntent]:
        return [UserIntent.MIXED_WORKFLOW]

    def requires_confirmation_before_execution(self) -> bool:
        return False

    def requires_confirmation_after_result(self) -> bool:
        return True

    def estimate_cost(self) -> int:
        return 0

    def run(self, context: ProjectContext) -> SubagentResult:
        from services.resource_extraction_service import extract_script_assets_structured
        from database import engine
        from sqlmodel import Session

        source_text = context.episode.source_text if context.episode else ""
        if not source_text:
            return SubagentResult(
                success=False,
                data={},
                summary="剧集缺少剧本原文，无法提取资产",
            )

        try:
            with Session(engine) as session:
                assets = extract_script_assets_structured(
                    session=session,
                    script_id=context.script_id,
                    source_text=source_text,
                    style_prompt="",
                    style_label="",
                )
        except Exception as e:
            return SubagentResult(
                success=False,
                data={},
                summary=f"资产提取失败: {e}",
            )

        characters = assets.get("characters", [])
        scenes = assets.get("scenes", [])
        props = assets.get("props", [])

        summary = (
            f"提取完成：{len(characters)} 个角色、{len(scenes)} 个场景、{len(props)} 个道具。"
            "确认后将写入共享资产库。"
        )

        write_op = WriteOperation(
            type="CREATE_RESOURCES",
            target="resources",
            data=assets,
            sync_resources=True,
            replace_existing=False,
        )

        return SubagentResult(
            success=True,
            data={
                **assets,
                "task_type": self.task_type.value,
                "tools_used": ["resource_extractor"],
            },
            summary=summary,
            next_actions=["生成角色参考图", "生成场景参考图", "继续生成分镜"],
            write_operations=[write_op],
        )
