"""Subagent 数据结构"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class UserIntent(str, Enum):
    """用户意图枚举"""
    SCRIPT_ANALYSIS = "script_analysis"
    SEGMENT_PLANNING = "segment_planning"
    STORYBOARD_PLANNING = "storyboard_planning"
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    DUBBING_PLANNING = "dubbing_planning"
    MIXED_WORKFLOW = "mixed_workflow"
    GENERAL_CHAT = "general_chat"  # 非任务类对话


class TaskType(str, Enum):
    """任务类型枚举"""
    SCRIPT_ANALYSIS = "script_analysis"
    SEGMENT_PLANNING = "segment_planning"
    STORYBOARD_PLANNING = "storyboard_planning"
    IMAGE_GENERATION_PLANNING = "image_generation_planning"
    VIDEO_GENERATION_PLANNING = "video_generation_planning"
    DUBBING_PLANNING = "dubbing_planning"
    MIXED_WORKFLOW = "mixed_workflow"
