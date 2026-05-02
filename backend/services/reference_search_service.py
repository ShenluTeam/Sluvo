from __future__ import annotations

import json
from typing import Any, Dict, List
from urllib import error, request

from core.config import settings


TAVILY_SEARCH_URL = "https://api.tavily.com/search"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _truncate(value: Any, limit: int = 180) -> str:
    text = _normalize_text(value)
    if len(text) <= limit:
        return text
    return "{0}...".format(text[:limit].rstrip())


def search_reference_materials(query: str, *, max_results: int | None = None) -> Dict[str, Any]:
    api_key = _normalize_text(settings.TAVILY_API_KEY)
    if not api_key:
        raise RuntimeError("当前还没有配置参考资料搜索服务，请先设置 Tavily API Key。")

    normalized_query = _normalize_text(query)
    if not normalized_query:
        raise RuntimeError("搜索参考资料时缺少查询内容。")

    payload = {
        "api_key": api_key,
        "query": normalized_query,
        "topic": "general",
        "search_depth": "advanced",
        "max_results": int(max_results or settings.TAVILY_MAX_RESULTS or 5),
        "include_answer": False,
        "include_raw_content": False,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        TAVILY_SEARCH_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout_seconds = int(settings.TAVILY_TIMEOUT_SECONDS or 20)
    try:
        with request.urlopen(req, timeout=timeout_seconds) as resp:
            response_text = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError("联网搜索暂时失败，请稍后再试。{0}".format(_truncate(detail, 120))) from exc
    except error.URLError as exc:
        raise RuntimeError("联网搜索服务当前不可用，请检查网络或稍后再试。") from exc

    try:
        payload = json.loads(response_text or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("搜索服务返回内容无法解析，请稍后再试。") from exc

    results: List[Dict[str, Any]] = []
    for item in list(payload.get("results") or [])[: int(max_results or settings.TAVILY_MAX_RESULTS or 5)]:
        if not isinstance(item, dict):
            continue
        title = _normalize_text(item.get("title"))
        url = _normalize_text(item.get("url"))
        content = _truncate(item.get("content") or item.get("snippet") or item.get("raw_content"), 220)
        if not (title or content or url):
            continue
        results.append(
            {
                "title": title or "未命名参考资料",
                "url": url,
                "summary": content or "该资料未返回可展示摘要。",
            }
        )

    return {
        "query": normalized_query,
        "results": results,
        "result_count": len(results),
    }
