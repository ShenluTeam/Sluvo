"""ToolRegistry - Agent Tools 注册表"""
from typing import Dict, List, Type
from langchain.tools import Tool

from services.director_agent.agent_runtime.tool_definitions import (
    DispatchTool,
    ReadProjectTool,
    WritePanelsTool,
    AskConfirmationTool,
)


class ToolRegistry:
    """工具注册表 - 管理 Agent 可用的所有工具"""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._tool_classes: Dict[str, Type] = {
            "dispatch_subagent": DispatchTool,
            "read_project": ReadProjectTool,
            "write_panels": WritePanelsTool,
            "ask_confirmation": AskConfirmationTool,
        }
        self._initialize_tools()

    def _initialize_tools(self):
        """初始化所有工具"""
        for name, tool_class in self._tool_classes.items():
            self._tools[name] = tool_class()

    def get_tool(self, name: str) -> Tool:
        """获取指定工具"""
        return self._tools.get(name)

    def get_all_tools(self) -> List[Tool]:
        """获取所有工具"""
        return list(self._tools.values())

    def get_tool_names(self) -> List[str]:
        """获取所有工具名称"""
        return list(self._tools.keys())


# 全局工具注册表
GLOBAL_TOOL_REGISTRY = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    """获取全局工具注册表"""
    return GLOBAL_TOOL_REGISTRY
