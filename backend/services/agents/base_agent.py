from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core.config import settings
from services.deepseek_hybrid_router import (
    estimate_text_tokens,
    extract_user_intent_flags,
    resolve_deepseek_agent_route,
)

from .llm_client import chat_json
from .prompt_registry import (
    get_agent_persona,
    get_agent_prompt_bundle,
    get_agent_role_hint,
    get_agent_system_rules,
)

TASK_KIND_BY_AGENT = {
    "director_agent": "simple_chat",
    "asset_planner_agent": "structured_extract",
    "storyboard_agent": "storyboard_planning",
    "generation_agent": "tool_execution",
    "prompt_rewrite_agent": "tool_execution",
}


class BaseAgent:
    agent_name = "base_agent"
    agent_label = "基础 Agent"
    default_output_schema_hint = """
返回一个 JSON 对象，必须包含：
- active_agent
- stage
- message
- suggested_actions
- artifacts
- next_stage_hint
- refresh_hints

其中：
- suggested_actions 是数组，每项包含 type、label，可选 payload
- artifacts 必须是对象
- refresh_hints 必须是对象，值为布尔值
""".strip()

    def __init__(self, session):
        self.session = session
        self.persona = get_agent_persona(self.agent_name)
        self.system_rules = get_agent_system_rules(self.agent_name)
        self.role_hint = get_agent_role_hint(self.agent_name)

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    def execute_action(self, context: Dict[str, Any], action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        raise NotImplementedError

    def build_response(
        self,
        *,
        stage: str,
        stage_label: str,
        message: str,
        suggested_actions: Optional[List[Dict[str, Any]]] = None,
        artifacts: Optional[Dict[str, Any]] = None,
        next_stage_hint: Optional[str] = None,
        refresh_hints: Optional[Dict[str, bool]] = None,
        debug_meta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "active_agent": self.agent_name,
            "active_agent_label": self.agent_label,
            "stage": stage,
            "stage_label": stage_label,
            "message": message,
            "suggested_actions": suggested_actions or [],
            "artifacts": artifacts or {},
            "next_stage_hint": next_stage_hint or stage,
            "refresh_hints": refresh_hints or {},
            "agent_prompt_meta": {
                "persona": self.persona,
                "system_rules": self.system_rules,
                "role_hint": self.role_hint,
                **(debug_meta or {}),
            },
        }

    def build_system_prompt(
        self,
        *,
        context: Dict[str, Any],
        action_space: List[Dict[str, Any]],
        output_schema_hint: Optional[str] = None,
    ) -> str:
        stage = str(context.get("creative_stage_label") or context.get("creative_stage") or "").strip()
        action_text = json.dumps(action_space or [], ensure_ascii=False, indent=2)
        return (
            f"{get_agent_prompt_bundle(self.agent_name)}\n\n"
            f"【当前阶段】\n{stage}\n\n"
            f"【允许动作】\n{action_text}\n\n"
            f"【输出格式要求】\n{output_schema_hint or self.default_output_schema_hint}"
        ).strip()

    def build_user_prompt(
        self,
        *,
        task_goal: str,
        latest_instruction: str,
        agent_context: Dict[str, Any],
    ) -> str:
        context_text = json.dumps(agent_context, ensure_ascii=False, indent=2)
        return (
            f"【当前任务目标】\n{task_goal}\n\n"
            f"【用户最新输入】\n{latest_instruction or '无'}\n\n"
            f"【当前上下文】\n{context_text}\n\n"
            "请基于以上上下文直接输出结构化 JSON，不要输出额外解释。"
        ).strip()

    def build_messages(
        self,
        *,
        context: Dict[str, Any],
        task_goal: str,
        latest_instruction: str,
        action_space: List[Dict[str, Any]],
        output_schema_hint: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        agent_context = context.get("agent_context_preview") or context.get("agent_context") or {}
        return [
            {
                "role": "system",
                "content": self.build_system_prompt(
                    context=context,
                    action_space=action_space,
                    output_schema_hint=output_schema_hint,
                ),
            },
            {
                "role": "user",
                "content": self.build_user_prompt(
                    task_goal=task_goal,
                    latest_instruction=latest_instruction,
                    agent_context=agent_context,
                ),
            },
        ]

    def build_prompt_bundle(
        self,
        *,
        context: Dict[str, Any],
        task_goal: str,
        latest_instruction: str,
        action_space: List[Dict[str, Any]],
        output_schema_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        route_context = self.build_route_context(
            context=context,
            latest_instruction=latest_instruction,
            action_space=action_space,
        )
        route = resolve_deepseek_agent_route(route_context)
        messages = self.build_messages(
            context=context,
            task_goal=task_goal,
            latest_instruction=latest_instruction,
            action_space=action_space,
            output_schema_hint=output_schema_hint,
        )
        return {
            "llm_model_used": route["model"],
            "llm_route": route,
            "llm_route_context": route_context,
            "prompt_bundle_preview": {
                "system_prompt": messages[0]["content"],
                "user_prompt": messages[1]["content"],
            },
            "messages_preview": messages,
        }

    def build_route_context(
        self,
        *,
        context: Dict[str, Any],
        latest_instruction: str,
        action_space: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        workspace_facts = context.get("workspace_facts_preview") or {}
        resource_counts = workspace_facts.get("resource_counts") or {}
        segment_count = int(workspace_facts.get("panel_count") or 0)
        character_count = int(resource_counts.get("characters") or len(workspace_facts.get("characters") or []))
        script_text = str(context.get("current_script") or workspace_facts.get("current_script") or "")
        estimated_text_tokens = estimate_text_tokens(script_text)
        user_intent_flags = extract_user_intent_flags(latest_instruction)
        task_kind = TASK_KIND_BY_AGENT.get(self.agent_name, "simple_chat")
        if self.agent_name == "director_agent" and any(flag in {"planning", "storyboard"} for flag in user_intent_flags):
            task_kind = "planning"
        return {
            "task_kind": task_kind,
            "agent_name": self.agent_name,
            "estimated_text_tokens": estimated_text_tokens,
            "segment_count": segment_count,
            "character_count": character_count,
            "expected_tool_calls": max(0, len(action_space)),
            "user_intent_flags": user_intent_flags,
            "previous_failures": int((context.get("llm_failures") or 0)),
            "json_mode_enabled": True,
            "strict_tools_enabled": task_kind == "tool_execution",
        }

    def try_llm_response(
        self,
        *,
        context: Dict[str, Any],
        task_goal: str,
        latest_instruction: str,
        action_space: List[Dict[str, Any]],
        fallback_response: Dict[str, Any],
        output_schema_hint: Optional[str] = None,
    ) -> Dict[str, Any]:
        prompt_bundle = self.build_prompt_bundle(
            context=context,
            task_goal=task_goal,
            latest_instruction=latest_instruction,
            action_space=action_space,
            output_schema_hint=output_schema_hint,
        )
        debug_meta = {
            "llm_model_used": prompt_bundle["llm_model_used"],
            "llm_route": prompt_bundle.get("llm_route") or {},
            "prompt_bundle_preview": prompt_bundle["prompt_bundle_preview"],
            "messages_preview": prompt_bundle["messages_preview"],
            "agent_context_preview": context.get("agent_context_preview") or context.get("agent_context") or {},
        }
        if context.get("disable_llm"):
            response = dict(fallback_response)
            response.setdefault("agent_prompt_meta", {}).update({**debug_meta, "llm_skipped": True})
            return response
        if not settings.DEEPSEEK_API_KEY:
            response = dict(fallback_response)
            response.setdefault("agent_prompt_meta", {}).update(debug_meta)
            return response

        try:
            stream_callback = context.get("stream_callback")
            on_reasoning_delta = None
            if callable(stream_callback):
                def on_reasoning_delta(delta_text, full_text):
                    try:
                        stream_callback(delta_text, full_text)
                    except TypeError:
                        stream_callback(full_text)
            base_route = dict(prompt_bundle.get("llm_route") or {})
            attempt_routes = [base_route]
            if not bool(base_route.get("thinking_enabled")):
                attempt_routes.append(
                    {
                        **base_route,
                        "model": str(settings.DEEPSEEK_AGENT_REASONER_MODEL or "deepseek-v4-flash"),
                        "thinking_enabled": True,
                        "route_tag": "{0}_thinking_retry".format(str(base_route.get("route_tag") or "retry")),
                    }
                )
            llm_payload = None
            last_exc = None
            for route in attempt_routes:
                try:
                    llm_payload = chat_json(
                        model=str(route.get("model") or prompt_bundle["llm_model_used"]),
                        messages=prompt_bundle["messages_preview"],
                        thinking_enabled=bool(route.get("thinking_enabled")),
                        max_tokens=route.get("max_tokens"),
                        temperature=float(settings.DEEPSEEK_AGENT_JSON_RETRY_TEMPERATURE or 0.1),
                        strict_tools=bool(route.get("strict_tools_enabled")),
                        route_tag=str(route.get("route_tag") or ""),
                        on_reasoning_delta=on_reasoning_delta,
                    )
                    break
                except Exception as exc:
                    last_exc = exc
            if llm_payload is None and last_exc is not None:
                raise last_exc
            merged = self.merge_llm_response(fallback_response=fallback_response, llm_payload=llm_payload)
            merged.setdefault("agent_prompt_meta", {}).update(debug_meta)
            return merged
        except Exception as exc:
            response = dict(fallback_response)
            response.setdefault("agent_prompt_meta", {}).update({**debug_meta, "llm_error": str(exc)})
            return response

    def merge_llm_response(self, *, fallback_response: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(fallback_response)
        for key in ["message", "next_stage_hint", "stage", "active_agent"]:
            value = llm_payload.get(key)
            if value not in (None, ""):
                merged[key] = value
        if isinstance(llm_payload.get("suggested_actions"), list) and llm_payload["suggested_actions"]:
            merged["suggested_actions"] = llm_payload["suggested_actions"]
        if isinstance(llm_payload.get("artifacts"), dict) and llm_payload["artifacts"]:
            merged["artifacts"] = llm_payload["artifacts"]
        if isinstance(llm_payload.get("refresh_hints"), dict):
            merged["refresh_hints"] = {
                str(key): bool(value) for key, value in llm_payload["refresh_hints"].items()
            }
        if isinstance(llm_payload.get("agent_prompt_meta"), dict):
            merged.setdefault("agent_prompt_meta", {}).update(llm_payload["agent_prompt_meta"])
        return merged
