"""Orchestrator: 构建项目上下文"""
from typing import Optional

from sqlmodel import Session

from ..schemas.orchestrator_schemas import ProjectContext
from ..tools.project_reader import ProjectReaderTool


class ContextBuilder:
    """构建项目上下文"""

    def __init__(self):
        self.tool = ProjectReaderTool()

    def build(
        self,
        session: Session,
        script_id: int,
        episode_id: Optional[int] = None
    ) -> ProjectContext:
        """
        构建项目上下文

        Args:
            session: 数据库会话
            script_id: 剧本 ID
            episode_id: 剧集 ID（可选）

        Returns:
            ProjectContext: 项目上下文对象
        """
        return self.tool.get_project_context(session, script_id, episode_id)

    def rebuild(
        self,
        session: Session,
        context: ProjectContext
    ) -> ProjectContext:
        """
        重建上下文（刷新数据）

        用于用户确认执行后，重新获取最新数据
        """
        return self.tool.get_project_context(
            session,
            context.script_id,
            context.episode_id,
        )
