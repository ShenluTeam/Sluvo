from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from models import Episode, Panel, SharedResource, TaskStatusEnum
from schemas import (
    PANEL_TYPE_NORMAL,
    STORYBOARD_MODE_COMMENTARY,
    STORYBOARD_MODE_COMIC,
    normalize_panel_type,
    normalize_storyboard_mode,
)
from services.panel_asset_binding_service import bind_assets


def stringify_composition(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value).strip()


def build_image_framing_text(
    shot_type: Optional[str],
    camera_motion: Optional[str],
    composition: Any,
    fallback: Optional[str] = None,
) -> str:
    fallback_text = str(fallback or "").strip()
    if fallback_text:
        return fallback_text

    parts = [
        str(shot_type or "").strip(),
        str(camera_motion or "").strip(),
        stringify_composition(composition),
    ]
    return " / ".join([part for part in parts if part])


def normalize_storyboard_texts(
    storyboard_mode: Optional[str],
    *,
    narration_text: Optional[str] = None,
    dialogue_text: Optional[str] = None,
    original_text: Optional[str] = None,
) -> Dict[str, Optional[str]]:
    mode = normalize_storyboard_mode(storyboard_mode)
    narration = str(narration_text or "").strip()
    dialogue = str(dialogue_text or "").strip()
    original = str(original_text or "").strip()

    if mode == STORYBOARD_MODE_COMIC:
        if not dialogue:
            dialogue = original or narration
        if not original:
            original = dialogue
    else:
        if not narration:
            narration = original or dialogue
        if not original:
            original = narration

    return {
        "storyboard_mode": mode,
        "narration_text": narration or None,
        "dialogue_text": dialogue or None,
        "original_text": original or "",
    }


def normalize_panel_storyboard_payload(
    payload: Dict[str, Any],
    *,
    fallback_mode: Optional[str] = None,
    force_mode: Optional[str] = None,
) -> Dict[str, Any]:
    next_payload = dict(payload or {})
    mode = normalize_storyboard_mode(force_mode or next_payload.get("storyboard_mode") or fallback_mode)

    text_fields = normalize_storyboard_texts(
        mode,
        narration_text=next_payload.get("narration_text"),
        dialogue_text=next_payload.get("dialogue_text"),
        original_text=next_payload.get("original_text"),
    )
    next_payload.update(text_fields)
    next_payload["storyboard_mode"] = mode

    if "segment_break" in next_payload:
        next_payload["segment_break"] = bool(next_payload.get("segment_break"))

    if "panel_type" in next_payload:
        next_payload["panel_type"] = normalize_panel_type(next_payload.get("panel_type"))

    if "composition" in next_payload or mode:
        next_payload["composition"] = stringify_composition(next_payload.get("composition"))

    if not str(next_payload.get("image_framing") or "").strip():
        next_payload["image_framing"] = build_image_framing_text(
            next_payload.get("shot_type"),
            next_payload.get("camera_motion"),
            next_payload.get("composition"),
            next_payload.get("image_framing"),
        )

    if mode != STORYBOARD_MODE_COMIC:
        next_payload["dependency_panel_id"] = None
        next_payload["previous_storyboard_path"] = None
        next_payload["transition_to_next"] = None
    else:
        transition = str(next_payload.get("transition_to_next") or "").strip()
        next_payload["transition_to_next"] = transition or None

    return next_payload


def hydrate_panel_storyboard_fields(panel: Panel, *, fallback_mode: Optional[str] = None) -> None:
    normalized = normalize_panel_storyboard_payload(
        {
            "storyboard_mode": getattr(panel, "storyboard_mode", None),
            "narration_text": getattr(panel, "narration_text", None),
            "dialogue_text": getattr(panel, "dialogue_text", None),
            "original_text": getattr(panel, "original_text", None),
            "segment_break": getattr(panel, "segment_break", False),
            "panel_type": getattr(panel, "panel_type", PANEL_TYPE_NORMAL),
            "shot_type": getattr(panel, "shot_type", None),
            "camera_motion": getattr(panel, "camera_motion", None),
            "composition": getattr(panel, "composition", None),
            "image_framing": getattr(panel, "image_framing", None),
            "transition_to_next": getattr(panel, "transition_to_next", None),
            "dependency_panel_id": getattr(panel, "dependency_panel_id", None),
            "previous_storyboard_path": getattr(panel, "previous_storyboard_path", None),
        },
        fallback_mode=fallback_mode,
    )

    panel.storyboard_mode = normalized["storyboard_mode"]
    panel.narration_text = normalized.get("narration_text")
    panel.dialogue_text = normalized.get("dialogue_text")
    panel.original_text = normalized.get("original_text") or ""
    panel.segment_break = bool(normalized.get("segment_break"))
    panel.panel_type = normalize_panel_type(normalized.get("panel_type") or panel.panel_type)
    panel.shot_type = normalized.get("shot_type") or None
    panel.camera_motion = normalized.get("camera_motion") or None
    panel.composition = normalized.get("composition") or None
    panel.image_framing = normalized.get("image_framing") or ""
    panel.transition_to_next = normalized.get("transition_to_next")
    if panel.storyboard_mode != STORYBOARD_MODE_COMIC:
        panel.dependency_panel_id = None
        panel.previous_storyboard_path = None


def get_panel_latest_image(panel: Optional[Panel]) -> Optional[str]:
    if not panel:
        return None

    primary = str(getattr(panel, "image_url", "") or "").strip()
    if primary:
        return primary

    raw_history = getattr(panel, "history_urls_json", "[]") or "[]"
    try:
        history = json.loads(raw_history)
        if isinstance(history, list):
            for item in history:
                if isinstance(item, str) and item.strip():
                    return item.strip()
        return None
    except Exception:
        return None


def recompute_episode_dependencies(session: Session, episode_id: int) -> Dict[int, Optional[int]]:
    panels = session.exec(
        select(Panel)
        .where(Panel.episode_id == episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()

    last_continuity_panel: Optional[Panel] = None
    dependency_map: Dict[int, Optional[int]] = {}

    for panel in panels:
        hydrate_panel_storyboard_fields(panel)
        if panel.storyboard_mode != STORYBOARD_MODE_COMIC:
            panel.dependency_panel_id = None
            panel.previous_storyboard_path = None
            last_continuity_panel = None
        else:
            if panel.segment_break:
                panel.dependency_panel_id = None
                panel.previous_storyboard_path = None
                last_continuity_panel = panel
            else:
                dependency_panel = last_continuity_panel if last_continuity_panel and last_continuity_panel.id != panel.id else None
                panel.dependency_panel_id = dependency_panel.id if dependency_panel else None
                panel.previous_storyboard_path = get_panel_latest_image(dependency_panel)
                last_continuity_panel = panel

        dependency_map[panel.id] = panel.dependency_panel_id
        session.add(panel)

    return dependency_map


def sync_episode_storyboard_mode(session: Session, episode: Episode, storyboard_mode: Optional[str]) -> str:
    normalized_mode = normalize_storyboard_mode(storyboard_mode or getattr(episode, "storyboard_mode", None))
    episode.storyboard_mode = normalized_mode
    session.add(episode)

    panels = session.exec(
        select(Panel)
        .where(Panel.episode_id == episode.id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    for panel in panels:
        panel.storyboard_mode = normalized_mode
        hydrate_panel_storyboard_fields(panel, fallback_mode=normalized_mode)
        if normalized_mode == STORYBOARD_MODE_COMMENTARY and not panel.narration_text:
            panel.narration_text = panel.original_text or panel.dialogue_text
        if normalized_mode == STORYBOARD_MODE_COMIC and not panel.dialogue_text:
            panel.dialogue_text = panel.original_text or panel.narration_text
        session.add(panel)

    recompute_episode_dependencies(session, episode.id)
    return normalized_mode


def build_panel_payload_from_draft(
    *,
    episode: Episode,
    draft: Dict[str, Any],
    sequence_num: int,
    entity_bindings: Dict[str, Any],
) -> Dict[str, Any]:
    mode = normalize_storyboard_mode(draft.get("storyboard_mode") or episode.storyboard_mode)
    payload = normalize_panel_storyboard_payload(
        {
            "episode_id": episode.id,
            "sequence_num": sequence_num,
            "panel_type": draft.get("panel_type") or PANEL_TYPE_NORMAL,
            "storyboard_mode": mode,
            "segment_no": draft.get("segment_no"),
            "segment_summary": draft.get("segment_summary", "") or "",
            "narrative_purpose": draft.get("narrative_purpose", "") or "",
            "panel_type_reason": draft.get("panel_type_reason", "") or "",
            "narration_text": draft.get("narration_text"),
            "dialogue_text": draft.get("dialogue_text"),
            "segment_break": bool(draft.get("segment_break", False)),
            "shot_type": draft.get("shot_type"),
            "camera_motion": draft.get("camera_motion"),
            "composition": draft.get("composition"),
            "transition_to_next": draft.get("transition_to_next"),
            "scene": ", ".join(draft.get("scene_refs") or []),
            "character": ", ".join(draft.get("character_refs") or []),
            "prop": ", ".join(draft.get("prop_refs") or []),
            "prompt": draft.get("prompt", "") or "",
            "prompt_zh": draft.get("prompt_zh", "") or draft.get("prompt", "") or "",
            "nine_grid_prompt": draft.get("nine_grid_prompt", "") or "",
            "video_prompt": draft.get("video_prompt", "") or "",
            "image_framing": draft.get("image_framing", "") or "",
            "original_text": draft.get("original_text", "") or "",
            "entity_bindings_json": json.dumps(entity_bindings, ensure_ascii=False),
            "status": TaskStatusEnum.IDLE,
        },
        fallback_mode=episode.storyboard_mode,
    )
    return payload


def commit_storyboard_panel_drafts(
    session: Session,
    *,
    episode: Episode,
    panel_drafts: List[Dict[str, Any]],
    replace_existing: bool = False,
) -> List[Panel]:
    if replace_existing:
        existing_panels = session.exec(select(Panel).where(Panel.episode_id == episode.id)).all()
        for panel in existing_panels:
            session.delete(panel)
        session.flush()
        next_seq = 1
    else:
        last_panel = session.exec(
            select(Panel).where(Panel.episode_id == episode.id).order_by(Panel.sequence_num.desc())
        ).first()
        next_seq = (last_panel.sequence_num + 1) if last_panel else 1

    created_panels: List[Panel] = []
    for draft in sorted(panel_drafts, key=lambda item: int(item.get("sequence") or 0)):
        scene_refs = draft.get("scene_refs") or []
        character_refs = draft.get("character_refs") or []
        prop_refs = draft.get("prop_refs") or []
        bindings = bind_assets(
            session,
            script_id=episode.script_id,
            scene_refs=scene_refs,
            character_refs=character_refs,
            prop_refs=prop_refs,
        )
        panel_payload = build_panel_payload_from_draft(
            episode=episode,
            draft=draft,
            sequence_num=next_seq,
            entity_bindings=bindings,
        )
        panel = Panel(**panel_payload)
        session.add(panel)
        created_panels.append(panel)
        next_seq += 1

    session.commit()
    for panel in created_panels:
        session.refresh(panel)

    recompute_episode_dependencies(session, episode.id)
    session.commit()
    for panel in created_panels:
        session.refresh(panel)
    return created_panels


def get_panel_reference_images(session: Session, panel: Panel) -> List[str]:
    hydrate_panel_storyboard_fields(panel)
    if panel.storyboard_mode != STORYBOARD_MODE_COMIC:
        return []

    refs: List[str] = []
    if bool(getattr(panel, "auto_asset_reference_enabled", True)):
        for url in _panel_bound_asset_reference_images(session, panel):
            if url:
                refs.append(url)
    if panel.dependency_panel_id:
        dependency_panel = session.get(Panel, panel.dependency_panel_id)
        ref_url = get_panel_latest_image(dependency_panel)
        if ref_url:
            refs.append(ref_url)
    if not refs:
        fallback_url = str(panel.previous_storyboard_path or "").strip()
        if fallback_url:
            refs.append(fallback_url)

    deduped: List[str] = []
    seen = set()
    for item in refs:
        if item and item not in seen:
            deduped.append(item)
            seen.add(item)
    return deduped


def _resource_reference_url(resource: Optional[SharedResource]) -> str:
    return str(
        getattr(resource, "file_url", "")
        or getattr(resource, "_default_version_file_url", "")
        or getattr(resource, "_latest_version_file_url", "")
        or getattr(resource, "thumbnail_url", "")
        or ""
    ).strip()


def _panel_bound_asset_reference_images(session: Session, panel: Panel) -> List[str]:
    try:
        bindings = json.loads(str(getattr(panel, "entity_bindings_json", "{}") or "{}"))
    except Exception:
        bindings = {}
    if not isinstance(bindings, dict):
        return []
    resource_ids: List[int] = []
    seen_ids: set[int] = set()
    for key in ("characters", "scenes", "props"):
        for item in bindings.get(key) or []:
            if not isinstance(item, dict):
                continue
            try:
                asset_id = int(item.get("asset_id"))
            except Exception:
                continue
            if asset_id <= 0 or asset_id in seen_ids:
                continue
            seen_ids.add(asset_id)
            resource_ids.append(asset_id)
    if not resource_ids:
        return []
    resources = session.exec(select(SharedResource).where(SharedResource.id.in_(resource_ids))).all()
    by_id = {int(item.id): item for item in resources if item.id is not None}
    urls: List[str] = []
    seen_urls: set[str] = set()
    for resource_id in resource_ids:
        url = _resource_reference_url(by_id.get(resource_id))
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        urls.append(url)
    return urls


def dependency_sequence_lookup(session: Session, episode_id: int) -> Dict[int, int]:
    panels = session.exec(
        select(Panel)
        .where(Panel.episode_id == episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    sequence_by_id = {panel.id: panel.sequence_num for panel in panels}
    return {panel.id: sequence_by_id.get(panel.dependency_panel_id, 0) for panel in panels}
