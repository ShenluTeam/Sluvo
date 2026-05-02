"""Subagent 基类和协议定义"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from typing_extensions import Protocol

from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage
from ..schemas.subagent_schemas import UserIntent, TaskType


@dataclass
class WriteOperation:
    """写入操作定义"""
    type: str  # CREATE_PANELS / UPDATE_PANELS / CREATE_RESOURCES / etc.
    target: str  # panels / resources / etc.
    data: Any  # 具体数据
    sync_resources: bool = True
    replace_existing: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "target": self.target,
            "data": self.data,
            "sync_resources": self.sync_resources,
            "replace_existing": self.replace_existing,
        }


@dataclass
class SubagentResult:
    """Subagent 执行结果"""
    success: bool
    data: Any  # Subagent 特有输出数据
    summary: str  # 人类可读的摘要
    warnings: List[str] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)
    stage_change: Optional[ProjectStage] = None  # 执行后阶段是否变化
    write_operations: List[WriteOperation] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "summary": self.summary,
            "warnings": self.warnings,
            "next_actions": self.next_actions,
            "stage_change": self.stage_change.value if self.stage_change else None,
            "write_operations": [w.to_dict() for w in self.write_operations],
        }


class Subagent(Protocol):
    """Subagent 协议"""

    name: str
    description: str

    @property
    def task_type(self) -> TaskType:
        """对应的任务类型"""
        ...

    def required_stage(self) -> ProjectStage:
        """所需的前置项目阶段"""
        ...

    def required_context_fields(self) -> List[str]:
        """所需的上下文字段"""
        ...

    def supported_intents(self) -> List[UserIntent]:
        """支持的意图类型"""
        ...

    def requires_confirmation_before_execution(self) -> bool:
        """执行前是否需要确认（显示 plan card）"""
        ...

    def requires_confirmation_after_result(self) -> bool:
        """结果出来后是否需要确认（显示 confirm card，写入前）"""
        ...

    def estimate_cost(self) -> int:
        """预估灵感值消耗"""
        ...

    def run(self, context: ProjectContext) -> SubagentResult:
        """运行 Subagent"""
        ...


class BaseSubagent:
    """Subagent 基类"""

    name: str = "base-subagent"
    description: str = "基础 Subagent"
    task_type: TaskType = TaskType.MIXED_WORKFLOW

    def required_stage(self) -> ProjectStage:
        """默认任意阶段都可执行"""
        return ProjectStage.PROJECT_EMPTY

    def required_context_fields(self) -> List[str]:
        """默认需要剧本上下文"""
        return ["script"]

    def supported_intents(self) -> List[UserIntent]:
        """默认支持混合工作流"""
        return [UserIntent.MIXED_WORKFLOW]

    def requires_confirmation_before_execution(self) -> bool:
        """默认不需要执行前确认"""
        return False

    def requires_confirmation_after_result(self) -> bool:
        """默认不需要结果后确认"""
        return False

    def estimate_cost(self) -> int:
        """默认无消耗"""
        return 0

    def check_context(self, context: ProjectContext) -> List[str]:
        """检查上下文是否满足要求"""
        missing = []
        for field in self.required_context_fields():
            if field == "script" and not context.script:
                missing.append("缺少剧本信息")
            elif field == "episode" and not context.episode:
                missing.append("缺少剧集信息")
            elif field == "source_text" and context.episode and not context.episode.has_source_text:
                missing.append("剧集缺少剧本原文")
        return missing
