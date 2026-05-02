"""消息卡片 Payload 数据结构"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ActionOption:
    """操作选项"""
    action_type: str  # confirm / modify / cancel
    label: str


@dataclass
class ToolCall:
    """工具调用"""
    tool: str
    input: str
    output: Optional[str] = None


@dataclass
class TaskStep:
    """任务步骤（思维链）"""
    id: str
    title: str
    description: str
    status: str  # completed / in-progress / pending / failed
    priority: str
    tools: List[str] = field(default_factory=list)
    subtasks: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class PlanPayload:
    """计划卡片 Payload"""
    task_type: str
    title: str
    description: str
    estimated_items: int
    estimated_cost: int
    requires_confirmation: bool
    preview: Dict[str, Any]
    actions: List[ActionOption] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_type": self.task_type,
            "title": self.title,
            "description": self.description,
            "estimated_items": self.estimated_items,
            "estimated_cost": self.estimated_cost,
            "requires_confirmation": self.requires_confirmation,
            "preview": self.preview,
            "actions": [{"action_type": a.action_type, "label": a.label} for a in self.actions],
        }


@dataclass
class ConfirmPayload:
    """确认操作卡片 Payload"""
    title: str
    description: str
    action_type: str  # PROJECT_WRITE / HIGH_COST
    impact: Dict[str, int]  # panels_to_create, resources_to_sync, estimated_points
    write_operation: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "description": self.description,
            "action_type": self.action_type,
            "impact": self.impact,
            "write_operation": self.write_operation,
        }


@dataclass
class NextAction:
    """下一步操作"""
    label: str
    action: str  # 命令/意图标识


@dataclass
class ResultPayload:
    """结果卡片 Payload"""
    status: str  # completed / failed
    summary: str
    items_created: int = 0
    warnings: List[str] = field(default_factory=list)
    next_actions: List[NextAction] = field(default_factory=list)
    refresh_hints: Dict[str, bool] = field(default_factory=dict)
    segment_list: Optional[List[Dict[str, Any]]] = None  # 片段列表
    panel_drafts: Optional[List[Dict[str, Any]]] = None  # 分镜草稿
    task_chain: List[Dict[str, Any]] = field(default_factory=list)  # 思维链/工具链

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "items_created": self.items_created,
            "warnings": self.warnings,
            "next_actions": [{"label": n.label, "action": n.action} for n in self.next_actions],
            "refresh_hints": self.refresh_hints,
            "segment_list": self.segment_list,
            "panel_drafts": self.panel_drafts,
            "task_chain": self.task_chain,
        }
