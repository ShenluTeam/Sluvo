from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI

from core.config import settings
from services.deepseek_model_policy import DEEPSEEK_V4_FLASH_MODEL, normalize_deepseek_model, normalize_deepseek_request_kwargs


DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_AGENT_MODEL_MAP: Dict[str, str] = {
    "director_agent": DEEPSEEK_V4_FLASH_MODEL,
    "asset_planner_agent": DEEPSEEK_V4_FLASH_MODEL,
    "storyboard_agent": DEEPSEEK_V4_FLASH_MODEL,
    "generation_agent": DEEPSEEK_V4_FLASH_MODEL,
}


def default_model_for_agent(agent_name: str) -> str:
    return DEFAULT_AGENT_MODEL_MAP.get(agent_name, DEEPSEEK_V4_FLASH_MODEL)


def build_client() -> OpenAI:
    return OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
        timeout=float(settings.DEEPSEEK_AGENT_STREAM_TIMEOUT_SECONDS or 120),
    )


def _read_delta_field(delta: Any, field: str) -> str:
    if delta is None:
        return ""
    value = delta.get(field) if isinstance(delta, dict) else getattr(delta, field, None)
    if value is None:
        return ""
    if isinstance(value, list):
        parts: List[str] = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(getattr(item, "text", None) or getattr(item, "content", None) or item or ""))
        return "".join(parts)
    return str(value)


def _read_tool_calls_delta(delta: Any) -> List[Any]:
    if delta is None:
        return []
    value = delta.get("tool_calls") if isinstance(delta, dict) else getattr(delta, "tool_calls", None)
    return list(value or [])


def chat_json(
    *,
    model: str,
    messages: List[Dict[str, str]],
    thinking_enabled: bool = False,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    strict_tools: bool = False,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Dict[str, Any]] = None,
    route_tag: str = "",
    on_reasoning: Optional[Callable[[str], None]] = None,
    on_content: Optional[Callable[[str], None]] = None,
    on_reasoning_delta: Optional[Callable[[str, str], None]] = None,
) -> Dict[str, Any]:
    client = build_client()
    content = ""
    model, thinking_enabled = normalize_deepseek_model(model, thinking_enabled=thinking_enabled)
    request_kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    if max_tokens:
        request_kwargs["max_tokens"] = int(max_tokens)
    if temperature is not None and not thinking_enabled:
        request_kwargs["temperature"] = float(temperature)
    if tools:
        request_kwargs["tools"] = tools
    if tool_choice:
        request_kwargs["tool_choice"] = tool_choice
    if strict_tools and tools:
        request_kwargs["extra_body"] = {
            **(request_kwargs.get("extra_body") or {}),
            "strict_tools": True,
        }
    request_kwargs = normalize_deepseek_request_kwargs(request_kwargs, thinking_enabled=thinking_enabled)
    if on_reasoning or on_content:
        response = client.chat.completions.create(**{**request_kwargs, "stream": True})
        reasoning_parts: List[str] = []
        content_parts: List[str] = []
        for chunk in response:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue
            delta = getattr(choices[0], "delta", None)
            reasoning_piece = _read_delta_field(delta, "reasoning_content") or _read_delta_field(delta, "reasoning")
            if reasoning_piece:
                reasoning_parts.append(reasoning_piece)
                if on_reasoning_delta:
                    on_reasoning_delta(reasoning_piece, "".join(reasoning_parts))
                if on_reasoning:
                    on_reasoning("".join(reasoning_parts))
            content_piece = _read_delta_field(delta, "content")
            if content_piece:
                content_parts.append(content_piece)
                if on_content:
                    on_content("".join(content_parts))
        content = "".join(content_parts).strip()
    else:
        response = client.chat.completions.create(**request_kwargs)
        if response.choices and response.choices[0].message:
            content = str(response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("DeepSeek 返回为空")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DeepSeek JSON 解析失败: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("DeepSeek JSON 顶层必须是对象")
    return payload


def chat_json_with_tools(
    *,
    model: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    thinking_enabled: bool = False,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    strict_tools: bool = True,
    tool_choice: Optional[Dict[str, Any]] = None,
    route_tag: str = "",
    on_reasoning_delta: Optional[Callable[[str, str], None]] = None,
    on_content_delta: Optional[Callable[[str, str], None]] = None,
    on_tool_calls_delta: Optional[Callable[[List[Dict[str, Any]]], None]] = None,
) -> Dict[str, Any]:
    client = build_client()
    model, thinking_enabled = normalize_deepseek_model(model, thinking_enabled=thinking_enabled)
    request_kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "stream": True,
        "response_format": {"type": "json_object"},
    }
    if max_tokens:
        request_kwargs["max_tokens"] = int(max_tokens)
    if temperature is not None and not thinking_enabled:
        request_kwargs["temperature"] = float(temperature)
    if tool_choice:
        request_kwargs["tool_choice"] = tool_choice
    if strict_tools and tools:
        request_kwargs["extra_body"] = {
            **(request_kwargs.get("extra_body") or {}),
            "strict_tools": True,
        }
    request_kwargs = normalize_deepseek_request_kwargs(request_kwargs, thinking_enabled=thinking_enabled)

    response = client.chat.completions.create(**request_kwargs)
    reasoning_parts: List[str] = []
    content_parts: List[str] = []
    finish_reason = ""
    tool_calls_by_index: Dict[int, Dict[str, Any]] = {}

    for chunk in response:
        choices = getattr(chunk, "choices", None) or []
        if not choices:
            continue
        choice = choices[0]
        delta = getattr(choice, "delta", None)
        finish_reason = str(getattr(choice, "finish_reason", None) or finish_reason or "").strip()

        reasoning_piece = _read_delta_field(delta, "reasoning_content") or _read_delta_field(delta, "reasoning")
        if reasoning_piece:
            reasoning_parts.append(reasoning_piece)
            if on_reasoning_delta:
                on_reasoning_delta(reasoning_piece, "".join(reasoning_parts))

        content_piece = _read_delta_field(delta, "content")
        if content_piece:
            content_parts.append(content_piece)
            if on_content_delta:
                on_content_delta(content_piece, "".join(content_parts))

        delta_tool_calls = _read_tool_calls_delta(delta)
        if delta_tool_calls:
            changed_calls: List[Dict[str, Any]] = []
            for raw_call in delta_tool_calls:
                if isinstance(raw_call, dict):
                    index = int(raw_call.get("index") or 0)
                    call_id = str(raw_call.get("id") or "").strip()
                    call_type = str(raw_call.get("type") or "function").strip() or "function"
                    function_payload = raw_call.get("function") or {}
                    function_name = str(function_payload.get("name") or "").strip()
                    arguments_delta = str(function_payload.get("arguments") or "")
                else:
                    index = int(getattr(raw_call, "index", 0) or 0)
                    call_id = str(getattr(raw_call, "id", None) or "").strip()
                    call_type = str(getattr(raw_call, "type", None) or "function").strip() or "function"
                    function = getattr(raw_call, "function", None)
                    function_name = str(getattr(function, "name", None) or "").strip()
                    arguments_delta = str(getattr(function, "arguments", None) or "")

                current = tool_calls_by_index.get(index) or {
                    "id": call_id,
                    "type": call_type,
                    "function": {
                        "name": function_name,
                        "arguments": "",
                    },
                }
                if call_id:
                    current["id"] = call_id
                if call_type:
                    current["type"] = call_type
                if function_name:
                    current.setdefault("function", {})["name"] = function_name
                if arguments_delta:
                    current.setdefault("function", {})["arguments"] = "{0}{1}".format(
                        str((current.get("function") or {}).get("arguments") or ""),
                        arguments_delta,
                    )
                tool_calls_by_index[index] = current
                changed_calls.append(
                    {
                        "index": index,
                        "id": current.get("id"),
                        "type": current.get("type"),
                        "function": {
                            "name": (current.get("function") or {}).get("name"),
                            "arguments": (current.get("function") or {}).get("arguments"),
                        },
                    }
                )
            if changed_calls and on_tool_calls_delta:
                on_tool_calls_delta(changed_calls)

    content = "".join(content_parts).strip()
    tool_calls = [tool_calls_by_index[index] for index in sorted(tool_calls_by_index.keys())]
    payload = None
    if content:
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"DeepSeek JSON 解析失败: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("DeepSeek JSON 顶层必须是对象")
    if payload is None and not tool_calls:
        raise RuntimeError("DeepSeek 返回为空")

    return {
        "payload": payload,
        "content": content,
        "tool_calls": tool_calls,
        "finish_reason": finish_reason or ("tool_calls" if tool_calls else "stop"),
        "reasoning": "".join(reasoning_parts),
        "route_tag": route_tag,
    }
