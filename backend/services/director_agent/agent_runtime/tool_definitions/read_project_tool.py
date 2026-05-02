"""ReadProjectTool - 读取项目状态（对标 ArcReil 的 Read 工具）"""
import json
from typing import Any

from langchain.tools import Tool

from services.director_agent.tools.project_reader import ProjectReaderTool


class ReadProjectTool:
    """读取项目当前状态"""

    name = "read_project"
    description = "读取项目当前状态，包括剧本、剧集、分镜、资产等信息。不需要输入参数。"

    def __init__(self):
        self._project_reader = ProjectReaderTool()

    def run(self, input_str: str = "") -> str:
        """执行读取"""
        try:
            from database import get_session

            gen = get_session()
            session = next(gen)

            try:
                # 从 session context 获取 script_id 和 episode_id
                # 这里需要通过 context 传递
                context = json.loads(input_str) if input_str else {}
                script_id = context.get("script_id")
                episode_id = context.get("episode_id")

                if not script_id:
                    return json.dumps({
                        "success": False,
                        "error": "script_id is required",
                    }, ensure_ascii=False)

                project_context = self._project_reader.get_project_context(
                    session, script_id, episode_id
                )

                return json.dumps(project_context.to_dict(), ensure_ascii=False, default=str)

            finally:
                try:
                    next(gen)
                except StopIteration:
                    pass

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Read project error: {str(e)}",
            }, ensure_ascii=False)


def get_read_project_tool() -> Tool:
    """获取 ReadProjectTool"""
    return Tool(
        name=ReadProjectTool.name,
        description=ReadProjectTool.description,
        func=ReadProjectTool().run,
    )
