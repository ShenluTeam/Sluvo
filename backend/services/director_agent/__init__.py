"""
神鹿AI导演 Agent 系统

目录结构：
- orchestrator/   : 编排层（工作流编排、上下文构建、阶段检测、确认门禁）
- subagent/       : 子代理（项目分析、片段拆分、分镜规划）
- tools/          : 工具层（读取项目、解析剧本、写入面板、查询记录）
- schemas/        : 数据结构定义
"""

from .orchestrator import ShenluWorkflowOrchestrator
from .subagent.base import Subagent, SubagentResult, WriteOperation
from .schemas.orchestrator_schemas import ProjectStage, ProjectContext
