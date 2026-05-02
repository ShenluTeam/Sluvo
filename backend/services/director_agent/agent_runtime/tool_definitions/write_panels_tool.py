"""WritePanelsTool - 写入分镜数据（对标 ArcReil 的 Write 工具）"""
import json
from typing import Any

from langchain.tools import Tool

from services.director_agent.tools.panel_writer import PanelWriterTool


class WritePanelsTool:
    """写入分镜数据到数据库"""

    name = "write_panels"
    description = "写入分镜数据到数据库。输入 JSON: {episode_id: 1, panels: [...], sync_resources: true}"

    def __init__(self):
        self._panel_writer = PanelWriterTool()

    def run(self, input_str: str) -> str:
        """执行写入"""
        try:
            data = json.loads(input_str)

            episode_id = data.get("episode_id")
            panel_drafts = data.get("panels", [])
            sync_resources = data.get("sync_resources", True)

            if not episode_id:
                return json.dumps({
                    "success": False,
                    "error": "episode_id is required",
                }, ensure_ascii=False)

            if not panel_drafts:
                return json.dumps({
                    "success": False,
                    "error": "panels is required",
                }, ensure_ascii=False)

            from database import get_session

            gen = get_session()
            session = next(gen)

            try:
                result = self._panel_writer.commit_panel_drafts(
                    session=session,
                    episode_id=episode_id,
                    panel_drafts=panel_drafts,
                    sync_resources=sync_resources,
                    replace_existing=False,
                )

                return json.dumps({
                    "success": result.success,
                    "panels_created": result.panels_created,
                    "resources_synced": result.resources_synced,
                    "warnings": result.warnings,
                }, ensure_ascii=False, default=str)

            finally:
                try:
                    next(gen)
                except StopIteration:
                    pass

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Write panels error: {str(e)}",
            }, ensure_ascii=False)


def get_write_panels_tool() -> Tool:
    """获取 WritePanelsTool"""
    return Tool(
        name=WritePanelsTool.name,
        description=WritePanelsTool.description,
        func=WritePanelsTool().run,
    )
