"""DispatchTool - 派发 Subagent 任务（对标 ArcReil 的 Task 工具）"""
import json
from typing import Any, Dict

from langchain.tools import Tool


class DispatchTool:
    """派发专注任务给 Subagent"""

    name = "dispatch_subagent"
    description = "派发专注任务给 subagent。输入 JSON: {subagent: 'analyze-story-context', context: {...}}"

    def __init__(self):
        self._subagent_registry = None

    @property
    def subagent_registry(self):
        """懒加载 Subagent 注册表"""
        if self._subagent_registry is None:
            from services.director_agent.subagent import SUBAGENT_REGISTRY
            self._subagent_registry = SUBAGENT_REGISTRY
        return self._subagent_registry

    def run(self, input_str: str) -> str:
        """执行派发"""
        try:
            # 解析输入
            if isinstance(input_str, str):
                data = json.loads(input_str)
            else:
                data = input_str

            subagent_name = data.get("subagent", "")
            context = data.get("context", {})

            # 获取 subagent
            subagent = self.subagent_registry.get(subagent_name)
            if not subagent:
                return json.dumps({
                    "success": False,
                    "error": f"Unknown subagent: {subagent_name}",
                }, ensure_ascii=False)

            # 执行 subagent
            result = subagent.run(context)

            return json.dumps({
                "success": result.success,
                "summary": result.summary,
                "data": result.data,
                "warnings": result.warnings,
                "next_actions": result.next_actions,
            }, ensure_ascii=False, default=str)

        except Exception as e:
            return json.dumps({
                "success": False,
                "error": f"Dispatch error: {str(e)}",
            }, ensure_ascii=False)


def get_dispatch_tool() -> Tool:
    """获取 DispatchTool"""
    return Tool(
        name=DispatchTool.name,
        description=DispatchTool.description,
        func=DispatchTool().run,
    )
