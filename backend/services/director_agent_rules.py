"""
神鹿AI导演判断规则模块

将所有判断规则独立封装，不散落在 service 中。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class TaskType(str, Enum):
    """任务类型枚举"""
    SCRIPT_ANALYSIS = "script_analysis"
    SEGMENT_PLANNING = "segment_planning"
    STORYBOARD_PLANNING = "storyboard_planning"
    IMAGE_GENERATION_PLANNING = "image_generation_planning"
    VIDEO_GENERATION_PLANNING = "video_generation_planning"
    DUBBING_PLANNING = "dubbing_planning"
    MIXED_WORKFLOW = "mixed_workflow"


class ActionType(str, Enum):
    """动作类型枚举"""
    READ_ONLY = "read_only"           # 只读，无需确认
    LOW_COST = "low_cost"             # 低成本，无需确认
    HIGH_COST = "high_cost"           # 高成本，需要确认
    PROJECT_WRITE = "project_write"   # 写入项目，需要确认


@dataclass
class RuleResult:
    """规则判断结果"""
    task_type: TaskType
    action_type: ActionType
    requires_confirmation: bool = False
    missing_context: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    estimated_cost: int = 0
    execution_plan: Dict[str, Any] = field(default_factory=dict)


class DirectorAgentRules:
    """
    神鹿AI导演判断规则集合

    包含所有业务判断逻辑，独立于服务层。
    """

    # 九宫格分镜的指示词
    NINE_GRID_INDICATORS = [
        "连续动作", "情绪推进", "多节点", "完整剧情段",
        "冲突升级", "转折过程", "快节奏", "蒙太奇",
        "时间流逝", "空间转换"
    ]

    # 普通分镜的指示词
    NORMAL_INDICATORS = [
        "特写", "反应", "强调", "过渡", "单一瞬间",
        "定格", "留白", "关键帧", "建立镜头", "定场"
    ]

    # 高成本任务类型
    HIGH_COST_TASKS = {
        TaskType.IMAGE_GENERATION_PLANNING,
        TaskType.VIDEO_GENERATION_PLANNING,
        TaskType.DUBBING_PLANNING
    }

    # 单位成本（灵感值）
    UNIT_COSTS = {
        TaskType.IMAGE_GENERATION_PLANNING: 3,
        TaskType.VIDEO_GENERATION_PLANNING: 10,
        TaskType.DUBBING_PLANNING: 5,
        TaskType.STORYBOARD_PLANNING: 0,
        TaskType.SEGMENT_PLANNING: 0,
        TaskType.SCRIPT_ANALYSIS: 0,
        TaskType.MIXED_WORKFLOW: 0,
    }

    # 执行顺序优先级
    EXECUTION_ORDER = {
        TaskType.SCRIPT_ANALYSIS: 1,
        TaskType.SEGMENT_PLANNING: 2,
        TaskType.STORYBOARD_PLANNING: 3,
        TaskType.IMAGE_GENERATION_PLANNING: 4,
        TaskType.VIDEO_GENERATION_PLANNING: 5,
        TaskType.DUBBING_PLANNING: 6,
        TaskType.MIXED_WORKFLOW: 3,
    }

    # ==================== 规则1：上下文缺失判断 ====================

    @staticmethod
    def check_context_requirements(
        task_type: TaskType,
        context: Dict[str, Any]
    ) -> List[str]:
        """
        检查上下文是否满足任务需求

        Args:
            task_type: 任务类型
            context: 当前上下文，包含 script, episode, panels_summary, shared_resources

        Returns:
            缺失的上下文列表
        """
        missing = []

        # 分镜规划和剧情片段需要剧本原文
        if task_type in [TaskType.STORYBOARD_PLANNING, TaskType.SEGMENT_PLANNING]:
            episode = context.get("episode", {})
            if not episode:
                missing.append("请先选择一个剧集")
            elif not episode.get("has_source_text"):
                missing.append("当前剧集缺少剧本原文，请先在剧本源文页面添加内容")

            # 检查资产库
            resources = context.get("shared_resources", {})
            if not resources.get("characters"):
                missing.append("尚未创建角色设定，拆镜时可能无法自动绑定角色（可继续执行）")

        # 图片生成需要分镜
        if task_type == TaskType.IMAGE_GENERATION_PLANNING:
            panels = context.get("panels_summary", {})
            if not panels.get("total"):
                missing.append("当前剧集尚无分镜，请先拆分镜")
            elif panels.get("without_images_count", 0) == 0:
                missing.append("所有分镜已生成图片，无需重复生成")

        # 视频生成需要有图片的分镜
        if task_type == TaskType.VIDEO_GENERATION_PLANNING:
            panels = context.get("panels_summary", {})
            if not panels.get("total"):
                missing.append("当前剧集尚无分镜，请先拆分镜")
            elif not panels.get("has_images"):
                missing.append("存在未生成图片的分镜，建议先生成图片再制作视频")
            elif panels.get("without_videos_count", 0) == 0:
                missing.append("所有分镜已生成视频，无需重复生成")

        # 配音需要剧本或分镜
        if task_type == TaskType.DUBBING_PLANNING:
            episode = context.get("episode", {})
            panels = context.get("panels_summary", {})
            if not episode.get("has_source_text") and not panels.get("total"):
                missing.append("当前剧集缺少剧本原文和分镜，无法规划配音")

        return missing

    # ==================== 规则2：normal / nine_grid 判断 ====================

    @classmethod
    def determine_panel_type(
        cls,
        segment_content: str,
        narrative_purpose: str,
        emotion_intensity: float = 0.5
    ) -> Dict[str, Any]:
        """
        判断分镜类型（普通 vs 九宫格）

        Args:
            segment_content: 剧情片段内容
            narrative_purpose: 叙事目的
            emotion_intensity: 情绪强度 (0-1)

        Returns:
            包含 panel_type 和 reason 的字典
        """
        content_lower = segment_content.lower() if segment_content else ""
        purpose_lower = narrative_purpose.lower() if narrative_purpose else ""

        # 计算九宫格和普通分镜的得分
        nine_grid_score = sum(
            1 for ind in cls.NINE_GRID_INDICATORS
            if ind in content_lower or ind in purpose_lower
        )
        normal_score = sum(
            1 for ind in cls.NORMAL_INDICATORS
            if ind in content_lower or ind in purpose_lower
        )

        # 情绪强度高时倾向九宫格
        if emotion_intensity > 0.7:
            nine_grid_score += 2

        # 做出判断
        if nine_grid_score > normal_score:
            return {
                "panel_type": "nine_grid",
                "reason": "该剧情片段包含连续动作或多节点推进，更适合九宫格分镜来表达完整的过程",
                "confidence": min(0.9, 0.5 + nine_grid_score * 0.1)
            }
        elif normal_score > nine_grid_score:
            return {
                "panel_type": "normal",
                "reason": "该剧情片段更适合用单一瞬间或强调镜头来表达",
                "confidence": min(0.9, 0.5 + normal_score * 0.1)
            }
        else:
            # 得分相同时，默认普通分镜
            return {
                "panel_type": "normal",
                "reason": "该剧情片段没有明确的连续动作特征，建议使用普通分镜",
                "confidence": 0.5
            }

    # ==================== 规则3：写入项目前确认规则 ====================

    @staticmethod
    def requires_project_confirmation(
        action_type: ActionType,
        payload: Dict[str, Any]
    ) -> bool:
        """
        判断是否需要确认才能写入项目

        Args:
            action_type: 动作类型
            payload: 操作载荷

        Returns:
            是否需要确认
        """
        # 写入项目类型必须确认
        if action_type == ActionType.PROJECT_WRITE:
            return True

        # 高成本操作，数量超过阈值需要确认
        if action_type == ActionType.HIGH_COST:
            items_count = payload.get("items_count", 0)
            return items_count > 5

        return False

    # ==================== 规则4：高成本动作确认规则 ====================

    @classmethod
    def check_high_cost_action(
        cls,
        task_type: TaskType,
        payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        检查高成本动作

        Args:
            task_type: 任务类型
            payload: 操作载荷

        Returns:
            包含成本信息和是否需要确认的字典
        """
        if task_type not in cls.HIGH_COST_TASKS:
            return {
                "is_high_cost": False,
                "estimated_points": 0,
                "requires_confirmation": False
            }

        # 计算预估消耗
        count = payload.get("items_count", 1)
        unit_cost = cls.UNIT_COSTS.get(task_type, 0)
        total_cost = count * unit_cost

        # 超过阈值需要确认
        threshold = 10  # 10 灵感值

        return {
            "is_high_cost": total_cost > threshold,
            "estimated_points": total_cost,
            "requires_confirmation": total_cost > threshold,
            "unit_cost": unit_cost,
            "items_count": count
        }

    # ==================== 规则5：默认执行顺序规则 ====================

    @classmethod
    def get_execution_order(
        cls,
        tasks: List[TaskType]
    ) -> List[TaskType]:
        """
        确定任务执行顺序

        Args:
            tasks: 任务列表

        Returns:
            按优先级排序的任务列表
        """
        return sorted(tasks, key=lambda t: cls.EXECUTION_ORDER.get(t, 99))

    # ==================== 意图分类 ====================

    @classmethod
    def classify_user_intent(cls, message: str) -> TaskType:
        """
        分类用户意图

        Args:
            message: 用户消息

        Returns:
            识别出的任务类型
        """
        message_lower = message.lower()

        # 关键词匹配
        intent_keywords = {
            TaskType.SEGMENT_PLANNING: ["拆剧情", "分片段", "分段", "剧情片段", "拆分剧情"],
            TaskType.STORYBOARD_PLANNING: ["分镜", "拆镜", "镜头", "拆分镜", "生成分镜", "分镜方案"],
            TaskType.IMAGE_GENERATION_PLANNING: ["图片", "生图", "画面", "生成图片", "图片建议"],
            TaskType.VIDEO_GENERATION_PLANNING: ["视频", "动起来", "动画", "生成视频", "视频建议"],
            TaskType.DUBBING_PLANNING: ["配音", "声音", "语音", "配音建议", "配音任务"],
            TaskType.SCRIPT_ANALYSIS: ["分析剧本", "剧本分析", "解读剧本", "理解剧本"],
        }

        for task_type, keywords in intent_keywords.items():
            if any(kw in message_lower for kw in keywords):
                return task_type

        # 默认为混合工作流
        return TaskType.MIXED_WORKFLOW

    # ==================== 确定动作类型 ====================

    @classmethod
    def determine_action_type(cls, task_type: TaskType) -> ActionType:
        """
        根据任务类型确定动作类型

        Args:
            task_type: 任务类型

        Returns:
            动作类型
        """
        # 写入项目的任务
        if task_type in [TaskType.STORYBOARD_PLANNING, TaskType.SEGMENT_PLANNING]:
            return ActionType.PROJECT_WRITE

        # 高成本任务
        if task_type in cls.HIGH_COST_TASKS:
            return ActionType.HIGH_COST

        # 只读任务
        if task_type == TaskType.SCRIPT_ANALYSIS:
            return ActionType.READ_ONLY

        # 默认低成本低
        return ActionType.LOW_COST

    # ==================== 综合判断 ====================

    @classmethod
    def evaluate_request(
        cls,
        user_message: str,
        context: Dict[str, Any]
    ) -> RuleResult:
        """
        综合评估用户请求

        Args:
            user_message: 用户消息
            context: 当前上下文

        Returns:
            规则判断结果
        """
        # 1. 分类意图
        task_type = cls.classify_user_intent(user_message)

        # 2. 确定动作类型
        action_type = cls.determine_action_type(task_type)

        # 3. 检查上下文
        missing_context = cls.check_context_requirements(task_type, context)

        # 4. 判断是否需要确认
        requires_confirmation = cls.requires_project_confirmation(
            action_type,
            {"task_type": task_type.value}
        )

        # 5. 计算预估成本
        cost_info = cls.check_high_cost_action(task_type, {"items_count": 1})

        # 6. 生成建议
        suggestions = cls._generate_suggestions(task_type, context, missing_context)

        return RuleResult(
            task_type=task_type,
            action_type=action_type,
            requires_confirmation=requires_confirmation or cost_info.get("requires_confirmation", False),
            missing_context=missing_context,
            suggestions=suggestions,
            estimated_cost=cost_info.get("estimated_points", 0),
            execution_plan=cls._build_execution_plan(task_type, context)
        )

    @classmethod
    def _generate_suggestions(
        cls,
        task_type: TaskType,
        context: Dict[str, Any],
        missing_context: List[str]
    ) -> List[str]:
        """生成操作建议"""
        suggestions = []

        if missing_context:
            # 根据缺失内容生成建议
            for missing in missing_context:
                if "剧本原文" in missing:
                    suggestions.append("建议先前往剧本源文页面添加或导入剧本内容")
                elif "剧集" in missing:
                    suggestions.append("请在左侧剧集列表中选择一个剧集")
                elif "角色" in missing:
                    suggestions.append("可以在资产库页面创建角色设定以提升分镜质量")
                elif "分镜" in missing:
                    suggestions.append("建议先执行分镜拆解")
                elif "图片" in missing:
                    suggestions.append("建议先为分镜生成图片")

        # 根据任务类型生成额外建议
        if task_type == TaskType.STORYBOARD_PLANNING:
            resources = context.get("shared_resources", {})
            if resources.get("characters"):
                suggestions.append(f"已检测到 {len(resources['characters'])} 个角色设定，将自动绑定到分镜")
            if resources.get("scenes"):
                suggestions.append(f"已检测到 {len(resources['scenes'])} 个场景设定")

        return suggestions

    @classmethod
    def _build_execution_plan(
        cls,
        task_type: TaskType,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """构建执行计划"""
        plan = {
            "task_type": task_type.value,
            "steps": [],
            "dependencies": []
        }

        if task_type == TaskType.STORYBOARD_PLANNING:
            plan["steps"] = [
                {"step": 1, "action": "parse_story_segments_v3", "description": "解析剧本生成剧情片段草稿"},
                {"step": 2, "action": "extract_assets", "description": "提取角色场景资产"},
                {"step": 3, "action": "normalize_draft", "description": "规范化导演草稿"},
                {"step": 4, "action": "commit_panels", "description": "提交分镜到项目"}
            ]
        elif task_type == TaskType.SEGMENT_PLANNING:
            plan["steps"] = [
                {"step": 1, "action": "analyze_segments", "description": "分析剧情片段"},
                {"step": 2, "action": "suggest_panel_types", "description": "建议分镜类型"}
            ]
        elif task_type == TaskType.IMAGE_GENERATION_PLANNING:
            plan["steps"] = [
                {"step": 1, "action": "analyze_panels", "description": "分析待生成图片的分镜"},
                {"step": 2, "action": "estimate_cost", "description": "预估灵感值消耗"},
                {"step": 3, "action": "suggest_parameters", "description": "建议生成参数"}
            ]
        elif task_type == TaskType.VIDEO_GENERATION_PLANNING:
            plan["steps"] = [
                {"step": 1, "action": "analyze_panels", "description": "分析待生成视频的分镜"},
                {"step": 2, "action": "check_images", "description": "检查参考图状态"},
                {"step": 3, "action": "estimate_cost", "description": "预估灵感值消耗"}
            ]
        elif task_type == TaskType.DUBBING_PLANNING:
            plan["steps"] = [
                {"step": 1, "action": "analyze_text", "description": "分析配音文本"},
                {"step": 2, "action": "suggest_voices", "description": "建议音色选择"},
                {"step": 3, "action": "estimate_cost", "description": "预估灵感值消耗"}
            ]

        return plan


# ==================== 任务类型标题和描述映射 ====================

TASK_TYPE_TITLES = {
    TaskType.SCRIPT_ANALYSIS: "剧本分析",
    TaskType.SEGMENT_PLANNING: "剧情片段拆分",
    TaskType.STORYBOARD_PLANNING: "分镜方案生成",
    TaskType.IMAGE_GENERATION_PLANNING: "图片生成建议",
    TaskType.VIDEO_GENERATION_PLANNING: "视频生成建议",
    TaskType.DUBBING_PLANNING: "配音任务建议",
    TaskType.MIXED_WORKFLOW: "综合工作流",
}

TASK_TYPE_DESCRIPTIONS = {
    TaskType.SCRIPT_ANALYSIS: "分析剧本内容，提取关键信息",
    TaskType.SEGMENT_PLANNING: "将剧本拆分为剧情片段，建议分镜类型",
    TaskType.STORYBOARD_PLANNING: "为当前剧集生成分镜拆解方案",
    TaskType.IMAGE_GENERATION_PLANNING: "分析分镜并给出图片生成建议",
    TaskType.VIDEO_GENERATION_PLANNING: "分析分镜并给出视频生成建议",
    TaskType.DUBBING_PLANNING: "分析当前剧集的配音需求",
    TaskType.MIXED_WORKFLOW: "根据需求执行综合工作流",
}


def get_task_title(task_type: TaskType) -> str:
    """获取任务类型标题"""
    return TASK_TYPE_TITLES.get(task_type, "未知任务")


def get_task_description(task_type: TaskType) -> str:
    """获取任务类型描述"""
    return TASK_TYPE_DESCRIPTIONS.get(task_type, "")
