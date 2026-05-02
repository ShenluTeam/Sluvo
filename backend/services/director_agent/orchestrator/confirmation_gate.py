"""Orchestrator: 确认门禁"""
from typing import Any, Dict, List, Optional

from ..schemas.message_schemas import ActionOption, ConfirmPayload, PlanPayload, ResultPayload, NextAction
from ..subagent.base import Subagent, SubagentResult


class ConfirmationGate:
    """确认门禁 - 管理用户确认流程"""

    def create_plan_message(
        self,
        subagent: Subagent,
        preview: dict
    ) -> PlanPayload:
        """
        创建计划卡片 Payload

        Args:
            subagent: 要执行的 Subagent
            preview: 预览信息

        Returns:
            PlanPayload: 计划卡片数据
        """
        actions = [
            ActionOption(action_type="confirm", label="确认执行"),
            ActionOption(action_type="cancel", label="取消"),
        ]

        return PlanPayload(
            task_type=subagent.task_type.value,
            title=self._get_task_title(subagent),
            description=self._get_task_description(subagent),
            estimated_items=preview.get("estimated_panels", 0) or preview.get("estimated_segments", 0),
            estimated_cost=subagent.estimate_cost(),
            requires_confirmation=True,
            preview=preview,
            actions=actions,
        )

    def create_confirm_message(
        self,
        subagent_result: SubagentResult,
        write_operation: dict
    ) -> ConfirmPayload:
        """
        创建确认操作卡片 Payload

        Args:
            subagent_result: Subagent 执行结果
            write_operation: 待写入的操作

        Returns:
            ConfirmPayload: 确认卡片数据
        """
        impact = {
            "panels_to_create": 0,
            "resources_to_sync": 0,
            "resources_to_create": 0,
            "estimated_points": subagent_result.data.get("estimated_cost", 0) if subagent_result.data else 0,
        }

        # 计算影响
        if write_operation.get("target") == "panels":
            panel_drafts = write_operation.get("data", [])
            impact["panels_to_create"] = len(panel_drafts)
            # 统计涉及的资源数量
            resources = set()
            for panel in panel_drafts:
                resources.update(panel.get("character_refs", []))
                resources.update(panel.get("scene_refs", []))
            impact["resources_to_sync"] = len(resources)
        elif write_operation.get("target") == "resources":
            data = write_operation.get("data", {}) or {}
            impact["resources_to_create"] = (
                len(data.get("characters", []) or [])
                + len(data.get("scenes", []) or [])
                + len(data.get("props", []) or [])
            )

        return ConfirmPayload(
            title=self._get_write_title(subagent_result),
            description="确认后将执行以下操作：",
            action_type="PROJECT_WRITE",
            impact=impact,
            write_operation=write_operation,
        )

    def create_result_message(
        self,
        subagent_result: SubagentResult
    ) -> ResultPayload:
        """
        创建结果卡片 Payload

        Args:
            subagent_result: Subagent 执行结果

        Returns:
            ResultPayload: 结果卡片数据
        """
        # 构建下一步操作
        next_actions = []
        for action in subagent_result.next_actions:
            next_actions.append(NextAction(
                label=action,
                action=self._action_to_intent(action),
            ))

        # 构建刷新提示
        refresh_hints = {
            "panels": bool(subagent_result.write_operations),
            "resources": any(
                op.sync_resources for op in subagent_result.write_operations
            ),
        }

        # 构建思维链/工具链
        task_chain = self._build_task_chain(subagent_result)

        return ResultPayload(
            status="completed" if subagent_result.success else "failed",
            summary=subagent_result.summary,
            items_created=len(subagent_result.data.get("panel_drafts", [])) if subagent_result.data else 0,
            warnings=subagent_result.warnings,
            next_actions=next_actions,
            refresh_hints=refresh_hints,
            task_chain=task_chain,
        )

    def _build_task_chain(self, subagent_result: SubagentResult) -> List[Dict[str, Any]]:
        """构建思维链/工具链数据"""
        task_chain = []

        # 主任务
        task_id = subagent_result.data.get("task_type", "unknown") if subagent_result.data else "unknown"
        task_chain.append({
            "id": task_id,
            "title": self._get_task_title_by_type(task_id),
            "description": subagent_result.summary,
            "status": "completed" if subagent_result.success else "failed",
            "priority": "high",
            "tools": self._extract_tools(subagent_result),
            "dependencies": [],
            "subtasks": self._build_subtasks(subagent_result),
        })

        return task_chain

    def _get_task_title_by_type(self, task_type: str) -> str:
        """根据任务类型获取标题"""
        titles = {
            "analyze-story-context": "分析项目阶段",
            "split-story-segments": "拆分剧情片段",
            "plan-storyboard": "规划分镜方案",
            "extract-project-assets": "提取共享资产",
            "generate-panel-image": "规划图片生成",
            "generate-panel-video": "规划视频生成",
            "generate-episode-dubbing": "规划剧集配音",
            "script_analysis": "分析剧本",
            "segment_planning": "规划片段",
            "storyboard_planning": "规划分镜",
            "image_generation_planning": "规划图片生成",
            "video_generation_planning": "规划视频生成",
            "dubbing_planning": "规划配音",
        }
        return titles.get(task_type, "执行任务")

    def _extract_tools(self, subagent_result: SubagentResult) -> List[str]:
        """提取使用的工具"""
        tools = []
        if subagent_result.data:
            # 从 data 中提取工具使用信息
            if subagent_result.data.get("tools_used"):
                tools.extend(subagent_result.data.get("tools_used", []))
            # 常见工具映射
            if subagent_result.data.get("panel_drafts"):
                tools.extend(["plan-storyboard", "write_panels"])
            if subagent_result.data.get("segments"):
                tools.extend(["split-story-segments"])
        # 默认添加工具
        if not tools:
            tools = ["dispatch_subagent", "read_project"]
        return list(set(tools))[:5]  # 最多5个工具

    def _build_subtasks(self, subagent_result: SubagentResult) -> List[Dict[str, Any]]:
        """构建子任务列表"""
        subtasks = []

        if subagent_result.data:
            # 根据数据类型构建子任务
            if subagent_result.data.get("panel_drafts"):
                # 分镜规划子任务
                subtasks = [
                    {
                        "id": "1",
                        "title": "解析剧本文本",
                        "description": "将剧本文本解析为结构化片段",
                        "status": "completed",
                        "priority": "high",
                        "tools": ["script_parser"],
                    },
                    {
                        "id": "2",
                        "title": "提取角色和场景",
                        "description": "从剧本中识别并提取角色和场景信息",
                        "status": "completed",
                        "priority": "high",
                        "tools": ["project_reader"],
                    },
                    {
                        "id": "3",
                        "title": "生成分镜方案",
                        "description": "基于解析结果生成分镜草稿",
                        "status": "completed" if subagent_result.success else "in-progress",
                        "priority": "high",
                        "tools": ["dispatch_subagent"],
                    },
                    {
                        "id": "4",
                        "title": "写入数据库",
                        "description": "将分镜方案写入项目数据库",
                        "status": "completed" if subagent_result.success else "pending",
                        "priority": "high",
                        "tools": ["write_panels"],
                    },
                ]
            elif subagent_result.data.get("segments"):
                # 片段拆分子任务
                subtasks = [
                    {
                        "id": "1",
                        "title": "分析剧本结构",
                        "description": "识别剧本中的剧情节点和转折点",
                        "status": "completed",
                        "priority": "high",
                        "tools": ["script_parser"],
                    },
                    {
                        "id": "2",
                        "title": "拆分剧情片段",
                        "description": "将剧本拆分为独立的剧情片段",
                        "status": "completed" if subagent_result.success else "in-progress",
                        "priority": "high",
                        "tools": ["dispatch_subagent"],
                    },
                ]

        return subtasks

    def _get_task_title(self, subagent: Subagent) -> str:
        """获取任务标题"""
        titles = {
            "analyze-story-context": "项目阶段分析",
            "split-story-segments": "剧情片段拆分",
            "plan-storyboard": "分镜方案生成",
            "extract-project-assets": "共享资产提取",
            "generate-panel-image": "分镜图片生成",
            "generate-panel-video": "分镜视频生成",
            "generate-episode-dubbing": "剧集配音生成",
        }
        return titles.get(subagent.name, "执行任务")

    def _get_task_description(self, subagent: Subagent) -> str:
        """获取任务描述"""
        descriptions = {
            "analyze-story-context": "分析当前项目状态，确定创作阶段",
            "split-story-segments": "将剧本文本拆分为叙事片段，分析剧情结构",
            "plan-storyboard": "为剧集生成分镜方案，包括画面构图和提示词",
            "extract-project-assets": "从剧本中提取可复用的角色、场景和道具资产",
            "generate-panel-image": "基于已有分镜内容规划图片生成范围和模型",
            "generate-panel-video": "基于已有图片规划视频生成范围和模型",
            "generate-episode-dubbing": "为当前剧集规划配音范围和音色方案",
        }
        return descriptions.get(subagent.name, subagent.description)

    def _get_write_title(self, result: SubagentResult) -> str:
        """获取写入操作标题"""
        if "segments" in result.data:
            return "写入剧情片段"
        if "panel_drafts" in result.data or "story_segments" in result.data:
            return "写入分镜方案"
        if any(key in result.data for key in ("characters", "scenes", "props")):
            return "写入共享资产"
        return "写入项目数据"

    def _action_to_intent(self, action: str) -> str:
        """将操作文本转换为意图标识"""
        action_lower = action.lower()
        if "分镜" in action_lower:
            return "plan-storyboard"
        if "片段" in action_lower:
            return "split-story-segments"
        if "图片" in action_lower:
            return "image-generation"
        if "视频" in action_lower:
            return "video-generation"
        if "配音" in action_lower:
            return "dubbing"
        return "general"
