from __future__ import annotations

from typing import Any, Dict, List

from core.config import settings
from services.deepseek_model_policy import normalize_deepseek_model


PLANNING_TASK_KINDS = {
    "planning",
    "storyboard_planning",
    "storyboard",
    "storyboard_hard_case",
}

STRICT_TOOL_TASK_KINDS = {
    "tool_execution",
}


def estimate_text_tokens(text: str) -> int:
    normalized = str(text or "").strip()
    if not normalized:
        return 0
    return max(1, len(normalized) // 4)


def extract_user_intent_flags(text: str) -> List[str]:
    normalized = str(text or "").strip().lower()
    flags: List[str] = []
    if any(token in normalized for token in ["重构", "重写", "改结构", "多线", "逻辑", "推理", "严密"]):
        flags.append("deep_reasoning")
    if any(token in normalized for token in ["规划", "下一步", "怎么做", "建议", "评估", "优化"]):
        flags.append("planning")
    if any(token in normalized for token in ["分镜", "镜头", "剧情", "大纲"]):
        flags.append("storyboard")
    if any(token in normalized for token in ["工具", "执行", "调用", "保存", "生成", "任务"]):
        flags.append("tool_execution")
    return flags


def resolve_deepseek_agent_route(task_context: Dict[str, Any]) -> Dict[str, Any]:
    task_kind = str(task_context.get("task_kind") or "simple_chat").strip().lower()
    estimated_text_tokens = int(task_context.get("estimated_text_tokens") or 0)
    segment_count = int(task_context.get("segment_count") or 0)
    character_count = int(task_context.get("character_count") or 0)
    expected_tool_calls = int(task_context.get("expected_tool_calls") or 0)
    previous_failures = int(task_context.get("previous_failures") or 0)
    user_intent_flags = {str(item).strip().lower() for item in list(task_context.get("user_intent_flags") or []) if str(item).strip()}

    json_mode_enabled = bool(task_context.get("json_mode_enabled", True))
    strict_tools_enabled = bool(task_context.get("strict_tools_enabled", task_kind in STRICT_TOOL_TASK_KINDS))

    hard_case = (
        estimated_text_tokens >= int(settings.DEEPSEEK_AGENT_REASONER_TEXT_TOKENS)
        or segment_count >= int(settings.DEEPSEEK_AGENT_REASONER_SEGMENT_COUNT)
        or character_count >= int(settings.DEEPSEEK_AGENT_REASONER_CHARACTER_COUNT)
        or expected_tool_calls >= int(settings.DEEPSEEK_AGENT_REASONER_TOOL_CALL_COUNT)
        or previous_failures >= int(settings.DEEPSEEK_AGENT_REASONER_JSON_RETRY_COUNT)
        or "deep_reasoning" in user_intent_flags
    )

    if hard_case:
        model, thinking_enabled = normalize_deepseek_model(
            settings.DEEPSEEK_AGENT_REASONER_MODEL,
            thinking_enabled=True,
        )
        return {
            "model": model,
            "thinking_enabled": thinking_enabled,
            "max_tokens": int(settings.DEEPSEEK_AGENT_REASONER_MAX_TOKENS),
            "route_tag": "flash_thinking_hard_case",
            "json_mode_enabled": json_mode_enabled,
            "strict_tools_enabled": strict_tools_enabled,
        }

    if task_kind in PLANNING_TASK_KINDS or "planning" in user_intent_flags or "storyboard" in user_intent_flags:
        model, thinking_enabled = normalize_deepseek_model(
            settings.DEEPSEEK_AGENT_THINKING_MODEL,
            thinking_enabled=bool(settings.DEEPSEEK_AGENT_PLANNING_THINKING_ENABLED),
        )
        return {
            "model": model,
            "thinking_enabled": thinking_enabled,
            "max_tokens": int(settings.DEEPSEEK_AGENT_PLANNING_MAX_TOKENS),
            "route_tag": "flash_thinking_planning",
            "json_mode_enabled": json_mode_enabled,
            "strict_tools_enabled": strict_tools_enabled,
        }

    model, thinking_enabled = normalize_deepseek_model(
        settings.DEEPSEEK_AGENT_DEFAULT_MODEL,
        thinking_enabled=bool(settings.DEEPSEEK_AGENT_DEFAULT_THINKING_ENABLED),
    )
    return {
        "model": model,
        "thinking_enabled": thinking_enabled,
        "max_tokens": int(settings.DEEPSEEK_AGENT_SIMPLE_MAX_TOKENS),
        "route_tag": "flash_default",
        "json_mode_enabled": json_mode_enabled,
        "strict_tools_enabled": strict_tools_enabled,
    }
