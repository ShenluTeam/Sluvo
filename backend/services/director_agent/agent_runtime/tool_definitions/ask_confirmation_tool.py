"""AskConfirmationTool - 请求用户确认（对标 ArcReil 的 AskUserQuestion 工具）"""
import json
from typing import Any

from langchain.tools import Tool


class AskConfirmationTool:
    """请求用户确认操作"""

    name = "ask_confirmation"
    description = "请求用户确认操作。输入 JSON: {type: 'confirm', title: '确认写入', description: '...', impact: {...}}"

    def __init__(self):
        self.pending_confirmations = {}

    def run(self, input_str: str) -> str:
        """请求确认"""
        try:
            data = json.loads(input_str)

            confirmation_id = f"conf_{len(self.pending_confirmations) + 1}"

            confirmation = {
                "id": confirmation_id,
                "type": data.get("type", "confirm"),
                "title": data.get("title", "确认操作"),
                "description": data.get("description", ""),
                "impact": data.get("impact", {}),
                "status": "pending",
            }

            self.pending_confirmations[confirmation_id] = confirmation

            return json.dumps({
                "pending": True,
                "confirmation_id": confirmation_id,
                "confirmation": confirmation,
            }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Ask confirmation error: {str(e)}",
            }, ensure_ascii=False)

    def get_confirmation(self, confirmation_id: str) -> dict:
        """获取确认状态"""
        return self.pending_confirmations.get(confirmation_id)

    def update_confirmation_status(self, confirmation_id: str, status: str) -> bool:
        """更新确认状态"""
        if confirmation_id in self.pending_confirmations:
            self.pending_confirmations[confirmation_id]["status"] = status
            return True
        return False


def get_ask_confirmation_tool() -> Tool:
    """获取 AskConfirmationTool"""
    tool_instance = AskConfirmationTool()
    return Tool(
        name=tool_instance.name,
        description=tool_instance.description,
        func=tool_instance.run,
    )
