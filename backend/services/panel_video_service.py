import json
from typing import Any, Dict, List, Optional


def _normalize_history_entry(item: Any) -> Optional[Dict[str, str]]:
    if isinstance(item, dict):
        url = str(item.get("url") or item.get("file_url") or "").strip()
        thumbnail_url = str(item.get("thumbnail_url") or "").strip()
        cover = str(item.get("cover") or "").strip()
    else:
        url = str(item or "").strip()
        thumbnail_url = ""
        cover = ""

    if not url:
        return None

    normalized: Dict[str, str] = {"url": url}
    if thumbnail_url:
        normalized["thumbnail_url"] = thumbnail_url
    if cover:
        normalized["cover"] = cover
    return normalized


def normalize_panel_video_history(raw_history: Any) -> List[Dict[str, str]]:
    parsed = raw_history
    if isinstance(raw_history, str):
        try:
            parsed = json.loads(raw_history)
        except Exception:
            parsed = []

    if not isinstance(parsed, list):
        return []

    normalized: List[Dict[str, str]] = []
    seen = set()
    for item in parsed:
        payload = _normalize_history_entry(item)
        if not payload:
            continue
        url = payload["url"]
        if url in seen:
            continue
        seen.add(url)
        normalized.append(payload)
    return normalized


def serialize_panel_video_history(items: List[Dict[str, str]]) -> str:
    return json.dumps(items, ensure_ascii=False)


def upsert_panel_video_history(
    raw_history: Any,
    *,
    preview_url: str,
    thumbnail_url: Optional[str] = None,
    replace_url: Optional[str] = None,
) -> str:
    normalized_preview = str(preview_url or "").strip()
    if not normalized_preview:
        return serialize_panel_video_history(normalize_panel_video_history(raw_history))

    normalized_thumbnail = str(thumbnail_url or "").strip()
    normalized_replace = str(replace_url or "").strip()
    items = normalize_panel_video_history(raw_history)

    target_index = None
    if normalized_replace:
        for index, item in enumerate(items):
            if item.get("url") == normalized_replace:
                target_index = index
                break
    if target_index is None:
        for index, item in enumerate(items):
            if item.get("url") == normalized_preview:
                target_index = index
                break

    if target_index is None:
        next_item: Dict[str, str] = {"url": normalized_preview}
        if normalized_thumbnail:
            next_item["thumbnail_url"] = normalized_thumbnail
        items.insert(0, next_item)
    else:
        current = dict(items[target_index])
        current["url"] = normalized_preview
        if normalized_thumbnail:
            current["thumbnail_url"] = normalized_thumbnail
        items[target_index] = current
        if target_index != 0:
            items.insert(0, items.pop(target_index))

    deduped: List[Dict[str, str]] = []
    seen = set()
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(item)
    return serialize_panel_video_history(deduped)
