from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List

from fastapi import HTTPException
from sqlmodel import Session, select

from models import (
    ExternalAgentFileMapping,
    ExternalAgentMessage,
    ExternalAgentSession,
    Panel,
    Script,
    TaskStatusEnum,
    Team,
)
from schemas import PANEL_TYPE_NINE_GRID, PANEL_TYPE_NORMAL, normalize_panel_type
from services.oss_service import build_oss_thumbnail_url, upload_remote_image_to_oss
from services.resource_service import create_resource as create_resource_service
from services.script_service import create_script as create_script_service


def _json_loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _iter_message_payloads(session: Session, external_session_id: int) -> Iterable[Dict[str, Any]]:
    messages = session.exec(
        select(ExternalAgentMessage)
        .where(ExternalAgentMessage.session_ref_id == external_session_id)
        .order_by(ExternalAgentMessage.created_at.desc(), ExternalAgentMessage.id.desc())
    ).all()
    for message in messages:
        yield {
            "reply": _json_loads(message.reply_json, {}),
            "actions": _json_loads(message.actions_json, []),
            "workspace": _json_loads(message.workspace_snapshot_json, {}),
        }


def _extract_text_candidates(value: Any) -> List[str]:
    results: List[str] = []
    if value is None:
        return results
    if isinstance(value, str):
        text = value.strip()
        if text:
            results.append(text)
        return results
    if isinstance(value, dict):
        for key in ("content", "ui_display_content", "text", "final_text", "screenplay", "data"):
            results.extend(_extract_text_candidates(value.get(key)))
        return results
    if isinstance(value, list):
        for item in value:
            results.extend(_extract_text_candidates(item))
    return results


def _select_script_text(payloads: Iterable[Dict[str, Any]]) -> str:
    keywords = ("screenplay", "script", "剧本")
    for payload in payloads:
        workspace = payload.get("workspace") or {}
        for file_item in workspace.get("files") or []:
            docu_type = str(file_item.get("docu_type") or file_item.get("type") or "").lower()
            if docu_type not in ("script", "screenplay", "text"):
                continue
            candidates = _extract_text_candidates(file_item.get("records"))
            if candidates:
                return max(candidates, key=len)
            candidates = _extract_text_candidates(file_item)
            if candidates:
                return max(candidates, key=len)
        for action in payload.get("actions") or []:
            tool_name = str(action.get("tool_name") or "").lower()
            if any(keyword in tool_name for keyword in keywords):
                candidates = _extract_text_candidates(action.get("result"))
                if candidates:
                    return max(candidates, key=len)
        reply_text = str((payload.get("reply") or {}).get("text") or "").strip()
        if len(reply_text) > 30:
            return reply_text
    raise HTTPException(status_code=400, detail="当前会话里没有可导入的剧本文本")


def _safe_json_parse(text: str) -> Any:
    raw = (text or "").strip()
    if not raw:
        return None
    if "```json" in raw:
        raw = raw.split("```json", 1)[1].split("```", 1)[0].strip()
    try:
        return json.loads(raw)
    except Exception:
        return None


def _parse_character_lines(text: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for line in str(text or "").splitlines():
        clean = line.strip().lstrip("-").lstrip("*").strip()
        if not clean:
            continue
        if "：" in clean:
            name, description = clean.split("：", 1)
        elif ":" in clean:
            name, description = clean.split(":", 1)
        else:
            name, description = clean, ""
        if name.strip():
            items.append({"name": name.strip(), "description": description.strip()})
    return items


def _extract_character_items(payloads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for payload in payloads:
        for action in payload.get("actions") or []:
            tool_name = str(action.get("tool_name") or "").lower()
            if "character" not in tool_name and "角色" not in tool_name:
                continue
            result = action.get("result")
            parsed = _safe_json_parse("\n".join(_extract_text_candidates(result)))
            if isinstance(parsed, list):
                for entry in parsed:
                    if isinstance(entry, dict) and str(entry.get("name") or "").strip():
                        items.append(entry)
            else:
                for text in _extract_text_candidates(result):
                    items.extend(_parse_character_lines(text))
    deduped: Dict[str, Dict[str, Any]] = {}
    for item in items:
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        deduped[name.lower()] = {
            "name": name,
            "description": str(item.get("description") or item.get("summary") or "").strip(),
            "trigger_word": str(item.get("trigger_word") or item.get("triggerWord") or name).strip(),
            "file_url": str(item.get("image_url") or item.get("imageUrl") or item.get("file_url") or "").strip(),
            "raw": item,
        }
    if not deduped:
        raise HTTPException(status_code=400, detail="当前会话里没有可导入的角色结果")
    return list(deduped.values())


def _maybe_parse_panel_list(text: str) -> List[Dict[str, Any]]:
    parsed = _safe_json_parse(text)
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]

    items: List[Dict[str, Any]] = []
    for idx, line in enumerate([line.strip() for line in str(text or "").splitlines() if line.strip()], start=1):
        if not re.match(r"^(\d+[\.\)]|shot\s*\d+|镜头\s*\d+|分镜\s*\d+)", line, re.IGNORECASE):
            continue
        if "：" in line:
            _, content = line.split("：", 1)
        elif ":" in line:
            _, content = line.split(":", 1)
        else:
            content = line
        content = content.strip()
        items.append(
            {
                "sequence_num": idx,
                "original_text": content,
                "prompt": content,
                "video_prompt": content,
                "image_framing": "",
                "panel_type": PANEL_TYPE_NINE_GRID if "九宫格" in content else PANEL_TYPE_NORMAL,
                "nine_grid_prompt": content if "九宫格" in content else "",
            }
        )
    return items


def _extract_panel_items(payloads: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for payload in payloads:
        for action in payload.get("actions") or []:
            tool_name = str(action.get("tool_name") or "").lower()
            if not any(keyword in tool_name for keyword in ("storyboard", "shot", "panel", "分镜", "镜头")):
                continue
            for text in _extract_text_candidates(action.get("result")):
                items.extend(_maybe_parse_panel_list(text))
    if not items:
        raise HTTPException(status_code=400, detail="当前会话里没有可导入的分镜结果")
    return items


def _normalize_import_panel_sequence(existing_max: int, raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sortable: List[tuple[int, int, Dict[str, Any]]] = []
    for index, item in enumerate(raw_items):
        try:
            sequence = int(item.get("sequence_num"))
        except Exception:
            sequence = 10_000_000 + index
        sortable.append((sequence, index, item))
    sortable.sort(key=lambda row: (row[0], row[1]))

    normalized: List[Dict[str, Any]] = []
    next_sequence = existing_max + 1
    for _, _, item in sortable:
        payload = dict(item)
        payload["sequence_num"] = next_sequence
        payload["panel_type"] = normalize_panel_type(payload.get("panel_type"))
        if payload["panel_type"] == PANEL_TYPE_NINE_GRID and not str(payload.get("nine_grid_prompt") or "").strip():
            payload["nine_grid_prompt"] = str(payload.get("prompt") or payload.get("original_text") or "").strip()
        normalized.append(payload)
        next_sequence += 1
    return normalized


def _create_file_mapping(
    session: Session,
    external_session: ExternalAgentSession,
    *,
    provider_file_id: str,
    provider_docu_type: str,
    provider_name: str,
    internal_target_type: str,
    internal_target_id: int,
    snapshot: Dict[str, Any],
) -> None:
    mapping = ExternalAgentFileMapping(
        session_ref_id=external_session.id,
        provider_file_id=provider_file_id,
        provider_docu_type=provider_docu_type,
        provider_name=provider_name,
        internal_target_type=internal_target_type,
        internal_target_id=internal_target_id,
        snapshot_json=_dump_json(snapshot),
        updated_at=datetime.utcnow(),
    )
    session.add(mapping)


def import_script_content(
    session: Session,
    *,
    team: Team,
    external_session: ExternalAgentSession,
    mode: str,
    name: str | None,
) -> Dict[str, Any]:
    script_text = _select_script_text(_iter_message_payloads(session, external_session.id))
    if mode == "create_new_script":
        new_script = create_script_service(
            session,
            team,
            name=name or external_session.base_name or "AI导演助理导入剧本",
            description="由AI导演助理导入创建",
            aspect_ratio="16:9",
            style_preset="默认写实",
        )
        new_script.source_text = script_text
        session.add(new_script)
        session.flush()
        _create_file_mapping(
            session,
            external_session,
            provider_file_id=f"script-{external_session.id}",
            provider_docu_type="text",
            provider_name="剧本",
            internal_target_type="script",
            internal_target_id=new_script.id,
            snapshot={"mode": mode, "text_length": len(script_text)},
        )
        session.commit()
        session.refresh(new_script)
        return {"script_id": new_script.id, "episode_id": new_script.episodes[0].id if new_script.episodes else None}

    script = session.get(Script, external_session.script_id)
    if not script:
        raise HTTPException(status_code=404, detail="目标剧本不存在")
    script.source_text = script_text
    session.add(script)
    _create_file_mapping(
        session,
        external_session,
        provider_file_id=f"script-{external_session.id}",
        provider_docu_type="text",
        provider_name="剧本",
        internal_target_type="script_source",
        internal_target_id=script.id,
        snapshot={"mode": mode, "text_length": len(script_text)},
    )
    session.commit()
    return {"script_id": script.id}


def import_character_assets(
    session: Session,
    *,
    team: Team,
    external_session: ExternalAgentSession,
) -> Dict[str, Any]:
    created_ids: List[int] = []
    for index, item in enumerate(_extract_character_items(_iter_message_payloads(session, external_session.id)), start=1):
        file_url = item.get("file_url") or ""
        persisted_url = ""
        if file_url:
            persisted_url = upload_remote_image_to_oss(
                file_url,
                owner_user_id=external_session.user_id,
                source_type="external_agent_character_import",
                source_id=external_session.id,
            )
        resource = create_resource_service(
            session,
            team,
            script_id=external_session.script_id,
            resource_type="character",
            name=item["name"],
            file_url=persisted_url,
            trigger_word=item.get("trigger_word"),
            aliases=None,
            description=item.get("description"),
            owner_user_id=external_session.user_id,
        )
        if persisted_url:
            resource.thumbnail_url = build_oss_thumbnail_url(persisted_url)
            session.add(resource)
        created_ids.append(resource.id)
        _create_file_mapping(
            session,
            external_session,
            provider_file_id=f"character-{external_session.id}-{index}",
            provider_docu_type="character",
            provider_name=item["name"],
            internal_target_type="shared_resource",
            internal_target_id=resource.id,
            snapshot=item.get("raw") or item,
        )
    session.commit()
    return {"created_count": len(created_ids), "resource_ids": created_ids}


def import_panels_to_episode(
    session: Session,
    *,
    external_session: ExternalAgentSession,
    episode_id: int,
) -> Dict[str, Any]:
    raw_items = _extract_panel_items(_iter_message_payloads(session, external_session.id))
    last_panel = session.exec(
        select(Panel).where(Panel.episode_id == episode_id).order_by(Panel.sequence_num.desc(), Panel.id.desc())
    ).first()
    existing_max = int(getattr(last_panel, "sequence_num", 0) or 0)
    normalized_items = _normalize_import_panel_sequence(existing_max, raw_items)
    created_ids: List[int] = []
    for index, item in enumerate(normalized_items, start=1):
        panel = Panel(
            episode_id=episode_id,
            sequence_num=item["sequence_num"],
            original_text=str(item.get("original_text") or ""),
            image_framing=str(item.get("image_framing") or ""),
            prompt=str(item.get("prompt") or item.get("original_text") or ""),
            prompt_zh=str(item.get("prompt") or item.get("original_text") or ""),
            video_prompt=str(item.get("video_prompt") or item.get("prompt") or ""),
            panel_type=normalize_panel_type(item.get("panel_type")),
            nine_grid_prompt=str(item.get("nine_grid_prompt") or ""),
            status=TaskStatusEnum.IDLE,
        )
        session.add(panel)
        session.flush()
        created_ids.append(panel.id)
        _create_file_mapping(
            session,
            external_session,
            provider_file_id=f"panel-{external_session.id}-{index}",
            provider_docu_type="storyboard",
            provider_name=f"分镜{panel.sequence_num}",
            internal_target_type="panel",
            internal_target_id=panel.id,
            snapshot=item,
        )
    session.commit()
    return {"created_count": len(created_ids), "panel_ids": created_ids}
