from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from models import Episode, Panel, PanelGridCell, Script, SharedResource, SharedResourceVersion, TaskStatusEnum
from schemas import STORYBOARD_MODE_COMIC, normalize_grid_count, normalize_storyboard_mode
from services.panel_asset_binding_service import bind_assets
from services.storyboard_director_service import _build_comic_seedance_reference_mapping, _build_segment_continuity_state, _is_low_information_text, _render_comic_seedance_video_line, build_segment_layout_spec, build_segment_prompt_locks, clamp_segment_total_duration, infer_performance_focus, normalize_segment_timing, render_gridcell_image_prompt, render_gridcell_video_prompt, render_segment_multi_shot_prompt, render_segment_scene_prompt, render_segment_video_timeline_prompt, resolve_gridcell_video_prompt_structured
from services.storyboard_mode_service import recompute_episode_dependencies
from services.workflow_preset_service import resolve_effective_workflow_profile


def _json_loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _json_dumps(value: Any, fallback: Any) -> str:
    try:
        return json.dumps(value if value is not None else fallback, ensure_ascii=False)
    except Exception:
        return json.dumps(fallback, ensure_ascii=False)


VALID_SPEECH_TYPES = {"spoken", "inner_monologue", "narration", "offscreen_voice"}


def _normalize_speech_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SPEECH_TYPES else "spoken"


def _normalize_speech_items(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("line") or "").strip()
        speaker_name = str(item.get("speaker_name") or item.get("speaker") or "").strip()
        speaker_ref = str(item.get("speaker_ref") or "").strip()
        speech_type = _normalize_speech_type(item.get("speech_type"))
        emotion = str(item.get("emotion") or "").strip()
        intensity = str(item.get("intensity") or "medium").strip().lower() or "medium"
        mouth_sync_required = bool(
            item.get("mouth_sync_required")
            if item.get("mouth_sync_required") is not None
            else speech_type == "spoken"
        )
        if not text and not speaker_name and not speaker_ref:
            continue
        normalized.append(
            {
                "speaker_name": speaker_name or None,
                "speaker_ref": speaker_ref or None,
                "speech_type": speech_type,
                "text": text,
                "emotion": emotion or None,
                "intensity": intensity if intensity in {"low", "medium", "high"} else "medium",
                "mouth_sync_required": mouth_sync_required,
            }
        )
    return normalized


def _speech_item_display_prefix(item: Dict[str, Any]) -> str:
    speech_type = _normalize_speech_type(item.get("speech_type"))
    speaker = str(item.get("speaker_name") or item.get("speaker_ref") or "").strip()
    if speech_type == "inner_monologue":
        return f"OS：{speaker}" if speaker else "OS"
    if speech_type == "narration":
        return f"旁白：{speaker}" if speaker else "旁白"
    if speech_type == "offscreen_voice":
        return f"画外音：{speaker}" if speaker else "画外音"
    return speaker


def _speech_items_to_dialogue_excerpt(items: Any) -> str:
    rows: List[str] = []
    for item in _normalize_speech_items(items):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        prefix = _speech_item_display_prefix(item)
        rows.append(f"{prefix}：{text}" if prefix else text)
    return "\n".join(rows).strip()


def _segment_speech_summary(grid_cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = {
        "spoken_count": 0,
        "inner_monologue_count": 0,
        "narration_count": 0,
        "offscreen_voice_count": 0,
        "speakers": [],
    }
    speakers: List[str] = []
    seen_speakers: set[str] = set()
    for cell in grid_cells or []:
        for item in _normalize_speech_items(cell.get("speech_items") or []):
            speech_type = _normalize_speech_type(item.get("speech_type"))
            key = f"{speech_type}_count"
            if key in summary:
                summary[key] += 1
            speaker = str(item.get("speaker_name") or item.get("speaker_ref") or "").strip()
            if speaker and speaker not in seen_speakers:
                seen_speakers.add(speaker)
                speakers.append(speaker)
    summary["speakers"] = speakers
    return summary


def _sanitize_media_url(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("ERROR:"):
        return ""
    if text.startswith(("http://", "https://", "data:", "blob:", "/")):
        return text
    return ""


def _sanitize_media_list(values: Any) -> List[str]:
    if not isinstance(values, list):
        return []
    sanitized: List[str] = []
    seen: set[str] = set()
    for item in values:
        url = _sanitize_media_url(item)
        if not url or url in seen:
            continue
        seen.add(url)
        sanitized.append(url)
    return sanitized


def _allowed_grid_count(count: Optional[int]) -> int:
    return normalize_grid_count(count)


def _sync_segment_storyboard_fields(panel: Panel) -> None:
    panel.storyboard_mode = normalize_storyboard_mode(getattr(panel, "storyboard_mode", None))
    panel.grid_count = _allowed_grid_count(getattr(panel, "grid_count", 1))
    panel.recommended_duration_seconds = clamp_segment_total_duration(getattr(panel, "recommended_duration_seconds", 6), getattr(panel, "grid_count", 1))
    panel.text_span_json = str(getattr(panel, "text_span_json", "{}") or "{}")
    panel.generation_status = str(getattr(panel, "generation_status", "") or getattr(panel, "status", "idle"))
    panel.reference_assets_json = str(getattr(panel, "reference_assets_json", "[]") or "[]")
    panel.reference_images_json = str(getattr(panel, "reference_images_json", "[]") or "[]")
    panel.auto_asset_reference_enabled = bool(getattr(panel, "auto_asset_reference_enabled", True))
    if getattr(panel, "status", None):
        panel.generation_status = str(panel.status.value if hasattr(panel.status, "value") else panel.status or "idle")


def _thumb(resource: Optional[SharedResource]) -> str:
    source = str(
        getattr(resource, "thumbnail_url", "")
        or _resource_file_url(resource)
        or ""
    ).strip()
    if not source or source.startswith("data:") or "x-oss-process=" in source:
        return source
    return f"{source}{'&' if '?' in source else '?'}x-oss-process=image/resize,m_lfit,w_400,h_400"


def _resource_file_url(resource: Optional[SharedResource]) -> str:
    return str(
        getattr(resource, "file_url", "")
        or getattr(resource, "_default_version_file_url", "")
        or getattr(resource, "_latest_version_file_url", "")
        or ""
    ).strip()


def _resource_lookup(session: Session, script_id: int) -> Dict[str, SharedResource]:
    resources = session.exec(select(SharedResource).where(SharedResource.script_id == script_id)).all()
    resource_map = {item.id: item for item in resources if item.id is not None}
    resource_ids = [item.id for item in resources if item.id is not None]
    if resource_ids:
        versions = session.exec(
            select(SharedResourceVersion)
            .where(SharedResourceVersion.resource_id.in_(resource_ids))
            .order_by(
                SharedResourceVersion.resource_id.asc(),
                SharedResourceVersion.is_default.desc(),
                SharedResourceVersion.created_at.desc(),
                SharedResourceVersion.id.desc(),
            )
        ).all()
        first_by_resource: Dict[int, SharedResourceVersion] = {}
        for version in versions:
            if version.resource_id not in first_by_resource:
                first_by_resource[version.resource_id] = version
            if version.is_default and version.resource_id in resource_map:
                setattr(
                    resource_map[version.resource_id],
                    "_default_version_file_url",
                    str(version.file_url or "").strip(),
                )
        for resource in resources:
            matched = first_by_resource.get(resource.id)
            if matched:
                setattr(resource, "_latest_version_file_url", str(matched.file_url or "").strip())
                if not getattr(resource, "_default_version_file_url", ""):
                    setattr(resource, "_default_version_file_url", str(matched.file_url or "").strip())
    return {str(r.id): r for r in resources}


def _normalize_binding_list(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows = []
    for item in value:
        if isinstance(item, dict):
            rows.append({"name": str(item.get("name") or "").strip(), "asset_id": item.get("asset_id"), "match_type": str(item.get("match_type") or "unmatched")})
        else:
            text = str(item or "").strip()
            if text:
                rows.append({"name": text, "asset_id": None, "match_type": "unmatched"})
    return [row for row in rows if row["name"] or row["asset_id"] is not None]


def _reference_assets(bindings: Dict[str, Any], lookup: Dict[str, SharedResource], panel_id: Optional[int]) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for key, kind in (("scenes", "scene"), ("characters", "character"), ("props", "prop")):
        for idx, item in enumerate(_normalize_binding_list(bindings.get(key))):
            res = lookup.get(str(item.get("asset_id"))) if item.get("asset_id") is not None else None
            name = str(getattr(res, "name", "") or item.get("name") or "").strip()
            uniq = f"{kind}:{item.get('asset_id') or name}"
            if not name or uniq in seen:
                continue
            seen.add(uniq)
            refs.append({
                "key": f"{panel_id or 'segment'}:{kind}:{item.get('asset_id') or idx}",
                "panel_id": panel_id,
                "resource_type": kind,
                "asset_id": item.get("asset_id"),
                "name": name,
                "trigger_word": str(getattr(res, "trigger_word", "") or "").strip(),
                "description": str(getattr(res, "description", "") or "").strip(),
                "match_type": item.get("match_type") or "unmatched",
                "image_url": _thumb(res),
                "original_url": _resource_file_url(res),
                "image_ref_url": str(_resource_file_url(res) or _thumb(res) or "").strip(),
                "has_image": bool(str(_resource_file_url(res) or _thumb(res) or "").strip()),
            })
    return refs


def _reference_images(refs: List[Dict[str, Any]]) -> List[str]:
    seen: set[str] = set()
    urls: List[str] = []
    for item in refs:
        url = str(item.get("image_ref_url") or item.get("original_url") or item.get("image_url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def _panel_refs(panel: Panel) -> tuple[List[str], List[str], List[str]]:
    bindings = _json_loads(panel.entity_bindings_json, {})
    scenes = [i.get("name") for i in bindings.get("scenes", []) if isinstance(i, dict) and i.get("name") and i.get("asset_id") is not None] or [i.strip() for i in str(panel.scene or "").split(",") if i.strip()]
    chars = [i.get("name") for i in bindings.get("characters", []) if isinstance(i, dict) and i.get("name") and i.get("asset_id") is not None] or [i.strip() for i in str(panel.character or "").split(",") if i.strip()]
    props = [i.get("name") for i in bindings.get("props", []) if isinstance(i, dict) and i.get("name") and i.get("asset_id") is not None] or [i.strip() for i in str(panel.prop or "").split(",") if i.strip()]
    return scenes, chars, props


def _default_scene_prompt(panel: Panel) -> str:
    scenes, chars, props = _panel_refs(panel)
    return render_segment_scene_prompt(summary=panel.segment_summary or panel.original_text or "", scene_constraint=panel.continuity_note or panel.segment_prompt_summary or "", scene_refs=scenes, character_refs=chars, prop_refs=props)


def _resolve_segment_prompt_context(
    session: Session,
    *,
    episode: Optional[Episode],
    panel: Panel,
    payloads: List[Dict[str, Any]],
    effective_workflow_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    aspect_ratio = str(
        (effective_workflow_profile or {}).get("aspect_ratio")
        or ("16:9" if panel.storyboard_mode == STORYBOARD_MODE_COMIC else "9:16")
    ).strip()
    scenes, chars, props = _panel_refs(panel)
    continuity_segment = {
        "summary": panel.segment_summary or panel.original_text or "",
        "scene_constraint": panel.continuity_note or panel.segment_prompt_summary or "",
        "scene_prompt": panel.scene_prompt or "",
        "continuity_note": panel.continuity_note or "",
        "segment_prompt_summary": panel.segment_prompt_summary or "",
        "text_span": _json_loads(panel.text_span_json, {}),
        "character_refs": chars,
        "scene_refs": scenes,
        "prop_refs": props,
        "grid_count": panel.grid_count or 1,
        "grid_cells": payloads,
    }
    continuity_state = _build_segment_continuity_state(continuity_segment)
    continuity_segment["continuity_state"] = continuity_state
    layout_spec = build_segment_layout_spec(
        grid_count=panel.grid_count or 1,
        aspect_ratio=aspect_ratio,
        storyboard_mode=panel.storyboard_mode,
    )
    prompt_locks = build_segment_prompt_locks(
        continuity_segment,
        aspect_ratio=aspect_ratio,
        storyboard_mode=panel.storyboard_mode,
    )
    return {
        "aspect_ratio": aspect_ratio,
        "layout_spec": layout_spec,
        "prompt_locks": prompt_locks,
        "continuity_state": continuity_state,
    }


def _default_cell_payload(panel: Panel) -> Dict[str, Any]:
    refs = _json_loads(panel.entity_bindings_json, {})
    total = float(clamp_segment_total_duration(panel.recommended_duration_seconds, panel.grid_count or 1))
    shot_description = panel.segment_summary or panel.original_text or panel.narration_text or panel.dialogue_text or ""
    if _is_low_information_text(shot_description):
        shot_description = panel.original_text or panel.dialogue_text or panel.narration_text or ""
    action_description = panel.narrative_purpose or ""
    if _is_low_information_text(action_description):
        action_description = ""
    return {
        "id": None, "cell_index": 1, "start_second": 0.0, "end_second": total, "duration_seconds": total,
        "shot_description": shot_description,
        "action_description": action_description, "dialogue_excerpt": panel.dialogue_text or panel.narration_text or panel.original_text or "",
        "speech_items": [],
        "performance_focus": "",
        "mouth_sync_required": False,
        "shot_type": panel.shot_type or "", "camera_motion": panel.camera_motion or "", "composition": panel.composition or "", "lighting": "", "ambiance": "",
        "camera_position": "", "camera_direction": "", "shot_purpose": "",
        "image_prompt": panel.prompt or panel.prompt_zh or "", "video_prompt": panel.video_prompt or "",
        "image_prompt_structured": {}, "video_prompt_structured": {},
        "character_refs": [i.get("name") for i in refs.get("characters", []) if isinstance(i, dict) and i.get("name")] or [i.strip() for i in str(panel.character or "").split(",") if i.strip()],
        "scene_refs": [i.get("name") for i in refs.get("scenes", []) if isinstance(i, dict) and i.get("name")] or [i.strip() for i in str(panel.scene or "").split(",") if i.strip()],
        "prop_refs": [i.get("name") for i in refs.get("props", []) if isinstance(i, dict) and i.get("name")] or [i.strip() for i in str(panel.prop or "").split(",") if i.strip()],
        "segment_grid_count": panel.grid_count or 1,
        "asset_status": panel.generation_status or "idle", "image_url": _sanitize_media_url(panel.image_url or panel.file_url or ""), "image_history": _sanitize_media_list(_json_loads(panel.history_urls_json, [])),
        "video_url": panel.video_url or "", "video_thumbnail_url": panel.video_thumbnail_url or "", "video_history": _json_loads(panel.video_history_json, []),
        "binding_suggestions": refs, "note": panel.note or "", "legacy_source": "historical_nine_grid" if (panel.nine_grid_prompt or "").strip() or str(panel.panel_type or "").strip().lower() == "nine_grid" else None,
    }


def list_segment_cells(session: Session, panel_id: int) -> List[PanelGridCell]:
    return session.exec(select(PanelGridCell).where(PanelGridCell.panel_id == panel_id).order_by(PanelGridCell.cell_index.asc(), PanelGridCell.id.asc())).all()


def ensure_default_cell(session: Session, panel: Panel) -> List[PanelGridCell]:
    cells = list_segment_cells(session, panel.id)
    return cells if cells else []


def _cell_payload(cell: PanelGridCell) -> Dict[str, Any]:
    speech_items = _normalize_speech_items(_json_loads(cell.speech_items_json, []))
    dialogue_excerpt = _speech_items_to_dialogue_excerpt(speech_items) or ("" if _is_low_information_text(cell.dialogue_excerpt) else (cell.dialogue_excerpt or ""))
    return {
        "cell_index": cell.cell_index, "start_second": float(cell.start_second or 0.0), "end_second": float(cell.end_second or 0.0), "duration_seconds": float(cell.duration_seconds or 0.0),
        "shot_description": "" if _is_low_information_text(cell.shot_description) else (cell.shot_description or ""),
        "action_description": "" if _is_low_information_text(cell.action_description) else (cell.action_description or ""),
        "dialogue_excerpt": dialogue_excerpt,
        "speech_items": speech_items,
        "performance_focus": cell.performance_focus or "",
        "mouth_sync_required": bool(cell.mouth_sync_required),
        "shot_type": cell.shot_type or "", "camera_motion": cell.camera_motion or "", "composition": cell.composition or "", "lighting": cell.lighting or "", "ambiance": cell.ambiance or "",
        "camera_position": cell.camera_position or "", "camera_direction": cell.camera_direction or "", "shot_purpose": cell.shot_purpose or "",
        "image_prompt": "" if _is_low_information_text(cell.image_prompt) else (cell.image_prompt or ""),
        "video_prompt": "" if _is_low_information_text(cell.video_prompt) else (cell.video_prompt or ""),
        "image_prompt_structured": _json_loads(cell.image_prompt_structured_json, {}), "video_prompt_structured": _json_loads(cell.video_prompt_structured_json, {}),
        "character_refs": _json_loads(cell.character_refs_json, []), "scene_refs": _json_loads(cell.scene_refs_json, []), "prop_refs": _json_loads(cell.prop_refs_json, []),
        "asset_status": cell.asset_status or "idle", "image_url": _sanitize_media_url(cell.image_url or ""), "image_history": _sanitize_media_list(_json_loads(cell.image_history_json, [])),
        "video_url": cell.video_url or "", "video_thumbnail_url": cell.video_thumbnail_url or "", "video_history": _json_loads(cell.video_history_json, []),
        "binding_suggestions": _json_loads(cell.binding_suggestions_json, {}), "note": cell.note or "",
    }


def serialize_grid_cell(cell: PanelGridCell, *, reference_assets: Optional[List[Dict[str, Any]]] = None, reference_images: Optional[List[str]] = None) -> Dict[str, Any]:
    data = _cell_payload(cell)
    data["id"] = cell.id
    data["reference_assets"] = reference_assets or []
    data["reference_images"] = reference_images or []
    return data


def serialize_segment_workspace_item(session: Session, panel: Panel, *, dependency_sequence: Optional[int] = None, script_id: Optional[int] = None) -> Dict[str, Any]:
    _sync_segment_storyboard_fields(panel)
    bindings = _json_loads(panel.entity_bindings_json, {})
    lookup = _resource_lookup(session, script_id) if script_id else {}
    refs = _reference_assets(bindings, lookup, panel.id)
    ref_images = _reference_images(refs)
    cell_rows = ensure_default_cell(session, panel)
    grid_cells = [serialize_grid_cell(c, reference_assets=refs, reference_images=ref_images) for c in cell_rows] if cell_rows else [{**_default_cell_payload(panel), "reference_assets": refs, "reference_images": ref_images}]
    for cell in grid_cells:
        cell["segment_grid_count"] = panel.grid_count or 1
    text_span = _json_loads(panel.text_span_json, {})
    if not isinstance(text_span, dict):
        text_span = {}
    text_span.setdefault("source_excerpt", panel.original_text or panel.narration_text or panel.dialogue_text or panel.segment_summary or "")
    if (panel.nine_grid_prompt or "").strip() or str(panel.panel_type or "").strip().lower() == "nine_grid":
        panel.grid_count = 9
    script = session.get(Script, script_id) if script_id else None
    episode = session.get(Episode, panel.episode_id) if script else None
    effective_workflow_profile = resolve_effective_workflow_profile(script, episode=episode, storyboard_mode=panel.storyboard_mode) if script else None
    prompt_context = _resolve_segment_prompt_context(
        session,
        episode=episode,
        panel=panel,
        payloads=grid_cells,
        effective_workflow_profile=effective_workflow_profile,
    )
    scene_prompt = panel.scene_prompt or render_segment_scene_prompt(
        summary=panel.segment_summary or panel.original_text or "",
        scene_constraint=panel.continuity_note or panel.segment_prompt_summary or "",
        scene_refs=_panel_refs(panel)[0],
        character_refs=_panel_refs(panel)[1],
        prop_refs=_panel_refs(panel)[2],
        prompt_locks=prompt_context["prompt_locks"],
    )
    multi_shot_prompt = panel.multi_shot_prompt or render_segment_multi_shot_prompt(
        scene_prompt,
        grid_cells,
        layout_spec=prompt_context["layout_spec"],
    )
    multi_shot_video_prompt = panel.multi_shot_video_prompt or (
        _render_comic_segment_video_prompt(grid_cells, transition_to_next=panel.transition_to_next or "cut")
        if panel.storyboard_mode == STORYBOARD_MODE_COMIC
        else render_segment_video_timeline_prompt(grid_cells, transition_to_next=panel.transition_to_next or "cut", storyboard_mode=panel.storyboard_mode)
    )
    warning_items: List[str] = []
    raw_note = str(panel.note or "").strip()
    if raw_note.startswith("连续性检查："):
        payload = raw_note.split("连续性检查：", 1)[1]
        warning_items = [item.strip() for item in payload.split("；") if item.strip()]
    return {
        "id": panel.id, "segment_id": panel.id, "sequence_num": panel.sequence_num, "storyboard_mode": panel.storyboard_mode,
        "title": panel.title or panel.segment_summary or panel.narrative_purpose or f"片段 {panel.sequence_num}",
        "summary": panel.segment_summary or panel.original_text or panel.narration_text or panel.dialogue_text or "",
        "text_span": text_span, "recommended_duration_seconds": panel.recommended_duration_seconds, "grid_count": _allowed_grid_count(panel.grid_count),
        "pacing": panel.pacing or "", "rhythm": panel.rhythm or "", "scene_prompt": scene_prompt, "multi_shot_prompt": multi_shot_prompt, "multi_shot_video_prompt": multi_shot_video_prompt,
        "continuity_note": panel.continuity_note or "", "transition_to_next": panel.transition_to_next or "", "dependency_segment_sequence": dependency_sequence or None,
        "characters": [i.strip() for i in str(panel.character or "").split(",") if i.strip()], "scenes": [i.strip() for i in str(panel.scene or "").split(",") if i.strip()], "props": [i.strip() for i in str(panel.prop or "").split(",") if i.strip()],
        "reference_assets": refs, "reference_images": ref_images, "reference_image_count": len(ref_images), "has_reference_images": bool(ref_images), "auto_asset_reference_enabled": bool(panel.auto_asset_reference_enabled),
        "binding_status": str(bindings.get("binding_status") or "unmatched"), "segment_prompt_summary": panel.segment_prompt_summary or panel.prompt or "",
        "generation_status": panel.generation_status or (panel.status.value if hasattr(panel.status, "value") else str(panel.status or "idle")), "note": panel.note or "",
        "warnings": warning_items,
        "layout_spec": prompt_context["layout_spec"],
        "prompt_locks": prompt_context["prompt_locks"],
        "image_url": _sanitize_media_url(panel.image_url or panel.file_url or ""), "image_history": _sanitize_media_list(_json_loads(panel.history_urls_json, [])),
        "video_url": panel.video_url or "", "video_thumbnail_url": panel.video_thumbnail_url or "", "video_history": _json_loads(panel.video_history_json, []),
        "effective_workflow_profile": effective_workflow_profile,
        "legacy_flags": {"historical_nine_grid": bool((panel.nine_grid_prompt or "").strip() or str(panel.panel_type or "").strip().lower() == "nine_grid"), "default_single_cell_projection": not bool(cell_rows)},
        "grid_cells": grid_cells,
        "speech_summary": _segment_speech_summary(grid_cells),
    }


def build_episode_segment_workspace(session: Session, episode: Episode, panels: List[Panel], dependency_sequences: Dict[int, int]) -> Dict[str, Any]:
    # Workspace reads normalize legacy panel fields for response compatibility. Keep
    # those in-memory adjustments from being flushed by nested lookup queries.
    with session.no_autoflush:
        items = [serialize_segment_workspace_item(session, p, dependency_sequence=dependency_sequences.get(p.id), script_id=episode.script_id) for p in panels]
    return {"episode": {"id": episode.id, "title": episode.title, "storyboard_mode": episode.storyboard_mode}, "storyboard_mode": episode.storyboard_mode, "segments": items, "warnings": [], "legacy_flags": {"has_historical_nine_grid": any(i["legacy_flags"]["historical_nine_grid"] for i in items), "has_single_cell_segments": any(i["grid_count"] == 1 for i in items)}}


def _build_segment_bindings(session: Session, episode: Episode, segment: Dict[str, Any]) -> Dict[str, Any]:
    return bind_assets(session, script_id=episode.script_id, scene_refs=segment.get("scene_refs") or [], character_refs=segment.get("character_refs") or [], prop_refs=segment.get("prop_refs") or [])


def _build_panel_from_segment(episode: Episode, sequence_num: int, segment: Dict[str, Any], bindings: Dict[str, Any]) -> Panel:
    summary = str(segment.get("summary") or "").strip()
    multi_shot_prompt = str(segment.get("multi_shot_prompt") or "").strip()
    multi_shot_video_prompt = str(segment.get("multi_shot_video_prompt") or "").strip()
    grid_count = _allowed_grid_count(segment.get("grid_count"))
    return Panel(
        episode_id=episode.id, sequence_num=sequence_num, title=str(segment.get("title") or summary or f"片段 {sequence_num}").strip(), storyboard_mode=normalize_storyboard_mode(segment.get("storyboard_mode") or episode.storyboard_mode),
        text_span_json=_json_dumps(segment.get("text_span") or {}, {}), recommended_duration_seconds=clamp_segment_total_duration(segment.get("recommended_duration_seconds") or 6, grid_count), grid_count=grid_count,
        pacing=str(segment.get("pacing") or "").strip() or None, rhythm=str(segment.get("rhythm") or "").strip() or None, continuity_note=str(segment.get("continuity_note") or "").strip() or None,
        scene_prompt=str(segment.get("scene_prompt") or "").strip() or None, multi_shot_prompt=multi_shot_prompt or None, multi_shot_video_prompt=multi_shot_video_prompt or None,
        reference_assets_json=_json_dumps(segment.get("reference_assets") or [], []), reference_images_json=_json_dumps(segment.get("reference_images") or [], []), auto_asset_reference_enabled=bool(segment.get("auto_asset_reference_enabled", True)),
        segment_summary=summary or None, narrative_purpose=str(segment.get("segment_prompt_summary") or "").strip() or None, segment_prompt_summary=str(segment.get("segment_prompt_summary") or "").strip() or None,
        transition_to_next=str(segment.get("transition_to_next") or "").strip() or None, scene=", ".join(segment.get("scene_refs") or []), character=", ".join(segment.get("character_refs") or []), prop=", ".join(segment.get("prop_refs") or []),
        entity_bindings_json=_json_dumps(bindings, {}), generation_status=str(segment.get("generation_status") or "idle"), status=TaskStatusEnum.IDLE, original_text=str((segment.get("text_span") or {}).get("source_excerpt") or segment.get("summary") or "").strip(),
        prompt=multi_shot_prompt or "", prompt_zh=multi_shot_prompt or None, video_prompt=multi_shot_video_prompt or None, note=str(segment.get("note") or "").strip() or None,
    )


def _build_grid_cell(panel_id: int, cell_data: Dict[str, Any], bindings: Dict[str, Any], fallback_index: int) -> PanelGridCell:
    normalized_speech_items = _normalize_speech_items(cell_data.get("speech_items") or [])
    compiled_dialogue_excerpt = _speech_items_to_dialogue_excerpt(normalized_speech_items) or str(cell_data.get("dialogue_excerpt") or "").strip()
    return PanelGridCell(
        panel_id=panel_id, cell_index=max(int(cell_data.get("cell_index") or fallback_index), 1), start_second=float(cell_data.get("start_second") or 0.0), end_second=float(cell_data.get("end_second") or 0.0), duration_seconds=float(cell_data.get("duration_seconds") or 0.0),
        shot_description=str(cell_data.get("shot_description") or "").strip() or None, action_description=str(cell_data.get("action_description") or "").strip() or None, dialogue_excerpt=compiled_dialogue_excerpt or None,
        speech_items_json=_json_dumps(normalized_speech_items, []), performance_focus=(str(cell_data.get("performance_focus") or "").strip() or infer_performance_focus(normalized_speech_items, storyboard_mode=cell_data.get("storyboard_mode"))), mouth_sync_required=bool(cell_data.get("mouth_sync_required") if cell_data.get("mouth_sync_required") is not None else any(item.get("mouth_sync_required") for item in normalized_speech_items)),
        shot_type=str(cell_data.get("shot_type") or "").strip() or None, camera_motion=str(cell_data.get("camera_motion") or "").strip() or None, composition=str(cell_data.get("composition") or "").strip() or None, lighting=str(cell_data.get("lighting") or "").strip() or None, ambiance=str(cell_data.get("ambiance") or "").strip() or None,
        camera_position=str(cell_data.get("camera_position") or "").strip() or None, camera_direction=str(cell_data.get("camera_direction") or "").strip() or None, shot_purpose=str(cell_data.get("shot_purpose") or "").strip() or None,
        image_prompt=str(cell_data.get("image_prompt") or "").strip() or None, video_prompt=str(cell_data.get("video_prompt") or "").strip() or None,
        image_prompt_structured_json=_json_dumps(cell_data.get("image_prompt_structured") or {}, {}), video_prompt_structured_json=_json_dumps(cell_data.get("video_prompt_structured") or {}, {}),
        character_refs_json=_json_dumps(cell_data.get("character_refs") or [], []), scene_refs_json=_json_dumps(cell_data.get("scene_refs") or [], []), prop_refs_json=_json_dumps(cell_data.get("prop_refs") or [], []),
        asset_status=str(cell_data.get("asset_status") or "idle"), image_url=str(cell_data.get("image_url") or "").strip() or None, image_history_json=_json_dumps(cell_data.get("image_history") or [], []),
        video_url=str(cell_data.get("video_url") or "").strip() or None, video_thumbnail_url=str(cell_data.get("video_thumbnail_url") or "").strip() or None, video_history_json=_json_dumps(cell_data.get("video_history") or [], []),
        binding_suggestions_json=_json_dumps(cell_data.get("binding_suggestions") or bindings, {}), note=str(cell_data.get("note") or "").strip() or None,
    )


def _render_comic_segment_video_prompt(payloads: List[Dict[str, Any]], *, transition_to_next: str = "cut") -> str:
    if not payloads:
        return ""
    structured_rows = []
    total = len(payloads)
    for index, payload in enumerate(payloads):
      structured_rows.append(
          resolve_gridcell_video_prompt_structured(
              {
                  **payload,
                  "storyboard_mode": STORYBOARD_MODE_COMIC,
              },
              next_cell=payloads[index + 1] if index + 1 < total else None,
              transition_to_next=transition_to_next if index == total - 1 else "cut",
          )
      )

    section_lines: List[str] = []
    scene_context = next((str(item.get("scene_context") or "").strip() for item in structured_rows if str(item.get("scene_context") or "").strip()), "")
    style_aesthetics = next((str(item.get("style_aesthetics") or "").strip() for item in structured_rows if str(item.get("style_aesthetics") or "").strip()), "")
    segment_setting_parts: List[str] = []
    if merged_character_refs := list(dict.fromkeys([
        str(name or "").strip()
        for payload in payloads
        for name in (payload.get("character_refs") or [])
        if str(name or "").strip()
    ])):
        segment_setting_parts.append("、".join(f"@{name}" for name in merged_character_refs) + "保持人物外观、服装与表情连续")
    if merged_prop_refs := list(dict.fromkeys([
        str(name or "").strip()
        for payload in payloads
        for name in (payload.get("prop_refs") or [])
        if str(name or "").strip()
    ])):
        segment_setting_parts.append("、".join(f"@{name}" for name in merged_prop_refs) + "保持关键道具状态连续")
    if merged_scene_refs := list(dict.fromkeys([
        str(name or "").strip()
        for payload in payloads
        for name in (payload.get("scene_refs") or [])
        if str(name or "").strip()
    ])):
        segment_setting_parts.append("、".join(f"@{name}" for name in merged_scene_refs) + "保持场景空间方向稳定")
    if scene_context:
        segment_setting_parts.append(scene_context)
    if style_aesthetics:
        segment_setting_parts.append(style_aesthetics)
    continuity_anchor = next((str(item.get("continuity_notes") or "").strip() for item in structured_rows if str(item.get("continuity_notes") or "").strip()), "")
    if continuity_anchor and continuity_anchor not in segment_setting_parts:
        segment_setting_parts.append(continuity_anchor)
    segment_setting = "；".join([item for item in segment_setting_parts if item])
    if segment_setting:
        section_lines.append("分镜设定：" + segment_setting)

    reference_mapping = _build_comic_seedance_reference_mapping(
        scene_refs=merged_scene_refs,
        character_refs=merged_character_refs,
        prop_refs=merged_prop_refs,
        has_dialogue=any(bool(item.get("dialogue")) for item in structured_rows),
    )
    if reference_mapping:
        section_lines.append("参考映射：\n" + reference_mapping)

    section_lines.append("时间轴：")
    for index, payload in enumerate(payloads):
        start = int(round(float(payload.get("start_second") or 0.0)))
        end = int(round(float(payload.get("end_second") or 0.0)))
        if end <= start:
            continue
        structured = structured_rows[index]
        content = str(payload.get("video_prompt") or "").strip()
        if not content or _is_low_information_text(content):
            content = _render_comic_seedance_video_line(structured)
        if not content:
            continue
        section_lines.append(f"{start}-{end}秒：{content}")

    quality_constraints = "；".join(
        dict.fromkeys([str(item.get("negative_constraints") or "").strip() for item in structured_rows if str(item.get("negative_constraints") or "").strip()])
    )
    if quality_constraints:
        section_lines.append("质量约束：" + quality_constraints)

    return "\n".join([item for item in section_lines if item]).strip()


def sync_segment_prompt_bundle(session: Session, panel: Panel) -> Panel:
    _sync_segment_storyboard_fields(panel)
    cells = list_segment_cells(session, panel.id)
    if not cells:
        return panel
    payloads = [_cell_payload(c) for c in cells]
    timing = normalize_segment_timing(payloads, panel.recommended_duration_seconds, storyboard_mode=panel.storyboard_mode)
    panel.recommended_duration_seconds = max(
        int(panel.recommended_duration_seconds or 0),
        int(math.ceil(sum(float(item["duration_seconds"] or 0.0) for item in timing)))
    )
    for idx, cell in enumerate(cells):
        cell.start_second = timing[idx]["start_second"]; cell.end_second = timing[idx]["end_second"]; cell.duration_seconds = timing[idx]["duration_seconds"]
        payloads[idx].update(timing[idx])
        current = _cell_payload(cell)
        current.update(timing[idx])
        current["storyboard_mode"] = panel.storyboard_mode
        current["segment_grid_count"] = panel.grid_count or 1
        next_payload = payloads[idx + 1] if idx + 1 < len(payloads) else None
        current["video_prompt_structured"] = resolve_gridcell_video_prompt_structured(
            current,
            next_cell=next_payload,
            transition_to_next=(panel.transition_to_next or "cut") if idx == len(cells) - 1 else "cut",
        )
        cell.video_prompt_structured_json = _json_dumps(current.get("video_prompt_structured") or {}, {})
        payloads[idx] = current
        if not str(cell.image_prompt or "").strip() or _is_low_information_text(cell.image_prompt):
            cell.image_prompt = render_gridcell_image_prompt(current)
        if not str(cell.video_prompt or "").strip() or _is_low_information_text(cell.video_prompt):
            cell.video_prompt = (
                _render_comic_seedance_video_line(current["video_prompt_structured"])
                if panel.storyboard_mode == STORYBOARD_MODE_COMIC
                else render_gridcell_video_prompt(
                    current,
                    next_cell=next_payload,
                    transition_to_next=(panel.transition_to_next or "cut") if idx == len(cells) - 1 else "cut",
                )
            )
        session.add(cell)
    if not str(panel.scene_prompt or "").strip():
        context_episode = session.get(Episode, panel.episode_id)
        context_script = session.get(Script, context_episode.script_id) if context_episode else None
        effective_workflow_profile = resolve_effective_workflow_profile(context_script, episode=context_episode, storyboard_mode=panel.storyboard_mode) if context_script else None
        prompt_context = _resolve_segment_prompt_context(
            session,
            episode=context_episode,
            panel=panel,
            payloads=payloads,
            effective_workflow_profile=effective_workflow_profile,
        )
        scenes, chars, props = _panel_refs(panel)
        panel.scene_prompt = render_segment_scene_prompt(
            summary=panel.segment_summary or panel.original_text or "",
            scene_constraint=panel.continuity_note or panel.segment_prompt_summary or "",
            scene_refs=scenes,
            character_refs=chars,
            prop_refs=props,
            prompt_locks=prompt_context["prompt_locks"],
        )
    else:
        context_episode = session.get(Episode, panel.episode_id)
        context_script = session.get(Script, context_episode.script_id) if context_episode else None
        effective_workflow_profile = resolve_effective_workflow_profile(context_script, episode=context_episode, storyboard_mode=panel.storyboard_mode) if context_script else None
        prompt_context = _resolve_segment_prompt_context(
            session,
            episode=context_episode,
            panel=panel,
            payloads=payloads,
            effective_workflow_profile=effective_workflow_profile,
        )
    episode = context_episode
    bindings = _json_loads(panel.entity_bindings_json, {})
    refs = _reference_assets(bindings, _resource_lookup(session, episode.script_id), panel.id) if episode else []
    ref_images = _reference_images(refs)
    panel.multi_shot_prompt = render_segment_multi_shot_prompt(panel.scene_prompt or "", payloads, layout_spec=prompt_context["layout_spec"])
    panel.multi_shot_video_prompt = (
        _render_comic_segment_video_prompt(payloads, transition_to_next=panel.transition_to_next or "cut")
        if panel.storyboard_mode == STORYBOARD_MODE_COMIC
        else render_segment_video_timeline_prompt(payloads, transition_to_next=panel.transition_to_next or "cut", storyboard_mode=panel.storyboard_mode)
    )
    panel.prompt = panel.multi_shot_prompt or ""; panel.prompt_zh = panel.multi_shot_prompt or None; panel.video_prompt = panel.multi_shot_video_prompt or None
    panel.reference_assets_json = _json_dumps(refs, []); panel.reference_images_json = _json_dumps(ref_images, [])
    session.add(panel)
    return panel


def commit_story_segments_with_cells(session: Session, *, episode: Episode, story_segments: List[Dict[str, Any]], replace_existing: bool = False) -> List[Panel]:
    if replace_existing:
        for cell in session.exec(select(PanelGridCell).join(Panel, PanelGridCell.panel_id == Panel.id).where(Panel.episode_id == episode.id)).all():
            session.delete(cell)
        for panel in session.exec(select(Panel).where(Panel.episode_id == episode.id)).all():
            session.delete(panel)
        session.flush(); next_seq = 1
    else:
        last = session.exec(select(Panel).where(Panel.episode_id == episode.id).order_by(Panel.sequence_num.desc(), Panel.id.desc())).first()
        next_seq = (last.sequence_num + 1) if last else 1
    created: List[Panel] = []
    for segment in sorted(story_segments or [], key=lambda item: int(item.get("sequence_num") or 0)):
        bindings = _build_segment_bindings(session, episode, segment)
        panel = _build_panel_from_segment(episode, next_seq, segment, bindings)
        session.add(panel); session.flush(); session.refresh(panel)
        fallback_shot = str((segment.get("text_span") or {}).get("source_excerpt") or segment.get("summary") or "").strip()
        if _is_low_information_text(fallback_shot):
            fallback_shot = str(segment.get("summary") or "").strip()
        fallback_action = str(segment.get("segment_prompt_summary") or "").strip()
        if _is_low_information_text(fallback_action):
            fallback_action = ""
        grid_cells = segment.get("grid_cells") or [{"cell_index": 1, "shot_description": fallback_shot, "action_description": fallback_action, "dialogue_excerpt": (segment.get("text_span") or {}).get("source_excerpt") or "", "speech_items": [], "performance_focus": "", "mouth_sync_required": False, "image_prompt": "", "video_prompt": "", "character_refs": segment.get("character_refs") or [], "scene_refs": segment.get("scene_refs") or [], "prop_refs": segment.get("prop_refs") or [], "binding_suggestions": bindings}]
        for idx, cell in enumerate(grid_cells, start=1):
            session.add(_build_grid_cell(panel.id, cell, bindings, idx))
        created.append(panel); next_seq += 1
    session.flush()
    for panel in created:
        sync_segment_prompt_bundle(session, panel)
    session.commit()
    for panel in created:
        session.refresh(panel)
    recompute_episode_dependencies(session, episode.id); session.commit()
    for panel in created:
        session.refresh(panel)
    return created


def update_segment_fields(panel: Panel, payload: Dict[str, Any]) -> Panel:
    if "title" in payload: panel.title = str(payload.get("title") or "").strip() or None
    if "summary" in payload: panel.segment_summary = str(payload.get("summary") or "").strip() or None
    if "grid_count" in payload: panel.grid_count = _allowed_grid_count(payload.get("grid_count"))
    if "recommended_duration_seconds" in payload and payload.get("recommended_duration_seconds") is not None: panel.recommended_duration_seconds = clamp_segment_total_duration(payload.get("recommended_duration_seconds") or 6, panel.grid_count or 1)
    if "pacing" in payload: panel.pacing = str(payload.get("pacing") or "").strip() or None
    if "rhythm" in payload: panel.rhythm = str(payload.get("rhythm") or "").strip() or None
    if "scene_prompt" in payload: panel.scene_prompt = str(payload.get("scene_prompt") or "").strip() or None
    if "continuity_note" in payload: panel.continuity_note = str(payload.get("continuity_note") or "").strip() or None
    if "transition_to_next" in payload: panel.transition_to_next = str(payload.get("transition_to_next") or "").strip() or None
    if "segment_prompt_summary" in payload: panel.segment_prompt_summary = str(payload.get("segment_prompt_summary") or "").strip() or None
    if "multi_shot_prompt" in payload: panel.multi_shot_prompt = str(payload.get("multi_shot_prompt") or "").strip() or None
    if "multi_shot_video_prompt" in payload: panel.multi_shot_video_prompt = str(payload.get("multi_shot_video_prompt") or "").strip() or None
    if "image_url" in payload: panel.image_url = str(payload.get("image_url") or "").strip() or None
    if "image_history" in payload: panel.history_urls_json = _json_dumps(payload.get("image_history") or [], [])
    if "video_url" in payload: panel.video_url = str(payload.get("video_url") or "").strip() or None
    if "video_thumbnail_url" in payload: panel.video_thumbnail_url = str(payload.get("video_thumbnail_url") or "").strip() or None
    if "video_history" in payload: panel.video_history_json = _json_dumps(payload.get("video_history") or [], [])
    if "auto_asset_reference_enabled" in payload: panel.auto_asset_reference_enabled = bool(payload.get("auto_asset_reference_enabled"))
    if "note" in payload: panel.note = str(payload.get("note") or "").strip() or None
    return panel


def update_segment_cell_fields(cell: PanelGridCell, payload: Dict[str, Any]) -> PanelGridCell:
    content_changed = False
    for name in ("shot_description", "action_description", "dialogue_excerpt", "shot_type", "camera_motion", "composition", "lighting", "ambiance", "camera_position", "camera_direction", "shot_purpose", "note", "performance_focus"):
        if name in payload:
            setattr(cell, name, str(payload.get(name) or "").strip() or None); content_changed = True
    for name in ("start_second", "end_second", "duration_seconds"):
        if name in payload and payload.get(name) is not None:
            setattr(cell, name, float(payload.get(name) or 0.0)); content_changed = True
    if "speech_items" in payload:
        speech_items = _normalize_speech_items(payload.get("speech_items") or [])
        cell.speech_items_json = _json_dumps(speech_items, [])
        compiled_excerpt = _speech_items_to_dialogue_excerpt(speech_items)
        cell.performance_focus = str(payload.get("performance_focus") or "").strip() or infer_performance_focus(speech_items, storyboard_mode=None)
        if compiled_excerpt:
            cell.dialogue_excerpt = compiled_excerpt
        elif "dialogue_excerpt" not in payload:
            cell.dialogue_excerpt = None
        if "mouth_sync_required" not in payload:
            cell.mouth_sync_required = any(item.get("mouth_sync_required") for item in speech_items)
        content_changed = True
    if "mouth_sync_required" in payload:
        cell.mouth_sync_required = bool(payload.get("mouth_sync_required"))
        content_changed = True
    if "image_prompt" in payload: cell.image_prompt = str(payload.get("image_prompt") or "").strip() or None
    if "video_prompt" in payload: cell.video_prompt = str(payload.get("video_prompt") or "").strip() or None
    if content_changed and "image_prompt" not in payload: cell.image_prompt = render_gridcell_image_prompt(_cell_payload(cell))
    if content_changed and "video_prompt" not in payload: cell.video_prompt = render_gridcell_video_prompt(_cell_payload(cell))
    if content_changed or "image_prompt" in payload or "video_prompt" in payload: cell.updated_at = datetime.utcnow()
    return cell
