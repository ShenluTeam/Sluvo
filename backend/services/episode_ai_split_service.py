import json
import re
from typing import Any, Dict, List, Optional

from core.config import settings
from services.episode_split_service import build_split_preview


def _extract_json_array(content: str) -> List[Dict[str, Any]]:
    if not content:
        return []

    raw = content.strip()
    fenced = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
    if fenced:
        raw = fenced.group(1).strip()
    else:
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end >= 0 and end > start:
            raw = raw[start : end + 1]

    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise ValueError("AI 返回格式错误：不是数组")
    return parsed


def _normalize_ai_items(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for idx, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip() or f"第{idx}集"
        source_text = str(item.get("source_text") or item.get("content") or "").strip()
        result.append(
            {
                "sequence_num": idx,
                "title": title,
                "source_text": source_text,
                "char_count": len(source_text),
            }
        )
    return result


def _try_call_deepseek_preview(source_text: str, requirements: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    if not settings.DEEPSEEK_API_KEY:
        return None

    try:
        from openai import OpenAI
    except Exception:
        return None

    requirement_text = (requirements or "").strip()
    user_prompt = (
        "请将以下完整剧本拆分为分集，输出 JSON 数组，每项包含 title 和 source_text。"
        "\n要求："
        f"\n- 标题必须是“第X集”或“第X章 + 副标题”风格"
        "\n- source_text 保留该集完整正文"
        "\n- 不要输出额外说明"
    )
    if requirement_text:
        user_prompt += f"\n- 额外拆分要求：{requirement_text}"
    user_prompt += f"\n\n原文：\n{source_text}"

    client = OpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com",
        timeout=180.0,
    )

    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {
                "role": "system",
                "content": "你是剧本拆分助手，只返回合法 JSON 数组。",
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        extra_body={"thinking": {"type": "enabled"}},
    )

    content = response.choices[0].message.content or ""
    parsed = _extract_json_array(content)
    normalized = _normalize_ai_items(parsed)
    return normalized if normalized else None


def build_ai_split_preview(source_text: str, requirements: Optional[str] = None) -> Dict[str, Any]:
    warnings: List[str] = []

    if not (source_text or "").strip():
        return {
            "episodes": [],
            "warnings": ["剧本原文为空，无法拆分。"],
        }

    try:
        ai_episodes = _try_call_deepseek_preview(source_text, requirements)
        if ai_episodes:
            return {
                "episodes": ai_episodes,
                "warnings": warnings,
            }
        warnings.append("AI 服务未配置或未返回有效结果，已回退为规则拆分。")
    except Exception as e:
        warnings.append(f"AI 拆分失败，已回退规则拆分：{str(e)}")

    fallback = build_split_preview(source_text)
    return {
        "episodes": fallback.get("episodes", []),
        "warnings": warnings + fallback.get("warnings", []),
    }
