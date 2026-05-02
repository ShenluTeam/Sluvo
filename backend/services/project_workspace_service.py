from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from core.security import encode_id
from models import (
    CanvasEdge,
    CanvasNode,
    Episode,
    EpisodeAssetLink,
    GenerationRecord,
    GenerationUnit,
    GenerationUnitInput,
    MediaAsset,
    Panel,
    Script,
    SharedResource,
    SharedResourceVersion,
    StoryboardShotAssetLink,
    DomainEvent,
)
from services.canvas_service import get_or_create_workspace
from services.story_segment_service import build_episode_segment_workspace
from services.storyboard_mode_service import dependency_sequence_lookup


def _json_load(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _json_dump(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({}, ensure_ascii=False)


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _encode(value: Optional[int]) -> Optional[str]:
    return encode_id(value) if value else None


def _serialize_aliases(raw: Optional[str]) -> List[str]:
    data = _json_load(raw, [])
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _default_version_map(session: Session, resource_ids: List[int]) -> Dict[int, SharedResourceVersion]:
    if not resource_ids:
        return {}
    versions = session.exec(
        select(SharedResourceVersion)
        .where(SharedResourceVersion.resource_id.in_(resource_ids))
        .order_by(SharedResourceVersion.resource_id.asc(), SharedResourceVersion.created_at.desc(), SharedResourceVersion.id.desc())
    ).all()
    default_map: Dict[int, SharedResourceVersion] = {}
    latest_map: Dict[int, SharedResourceVersion] = {}
    for item in versions:
        latest_map.setdefault(item.resource_id, item)
        if item.is_default and item.resource_id not in default_map:
            default_map[item.resource_id] = item
    for resource_id, version in latest_map.items():
        default_map.setdefault(resource_id, version)
    return default_map


def ensure_default_episode_asset_links(session: Session, script_id: int) -> None:
    episodes = session.exec(select(Episode).where(Episode.script_id == script_id).order_by(Episode.sequence_num.asc(), Episode.id.asc())).all()
    resources = session.exec(select(SharedResource).where(SharedResource.script_id == script_id).order_by(SharedResource.created_at.asc(), SharedResource.id.asc())).all()
    if not episodes or not resources:
        return

    existing = session.exec(
        select(EpisodeAssetLink).where(EpisodeAssetLink.script_id == script_id)
    ).all()
    existing_keys = {(item.episode_id, item.resource_id) for item in existing}
    now = datetime.utcnow()
    changed = False
    for episode in episodes:
        for sort_order, resource in enumerate(resources, start=1):
            key = (episode.id, resource.id)
            if key in existing_keys:
                continue
            session.add(
                EpisodeAssetLink(
                    script_id=script_id,
                    episode_id=episode.id,
                    resource_id=resource.id,
                    sort_order=sort_order,
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed = True
    if changed:
        session.commit()


def sync_storyboard_asset_links_for_panel(session: Session, panel: Panel) -> None:
    episode = session.get(Episode, panel.episode_id)
    if not episode:
        return
    bindings = _json_load(panel.entity_bindings_json, {})
    if not isinstance(bindings, dict):
        bindings = {}
    desired: List[Dict[str, Any]] = []
    for role_group, role_value in (("characters", "character"), ("scenes", "scene"), ("props", "prop")):
        for sort_order, item in enumerate(bindings.get(role_group) or [], start=1):
            resource_id = item.get("asset_id")
            if not resource_id:
                continue
            try:
                desired.append(
                    {
                        "resource_id": int(resource_id),
                        "role": str(item.get("match_type") or role_value or "").strip() or role_value,
                        "sort_order": sort_order,
                    }
                )
            except Exception:
                continue

    existing = session.exec(
        select(StoryboardShotAssetLink).where(StoryboardShotAssetLink.panel_id == panel.id)
    ).all()
    existing_by_resource = {item.resource_id: item for item in existing}
    desired_resource_ids = {item["resource_id"] for item in desired}
    now = datetime.utcnow()
    changed = False

    for item in existing:
        if item.resource_id not in desired_resource_ids:
            session.delete(item)
            changed = True

    for item in desired:
        current = existing_by_resource.get(item["resource_id"])
        if current:
            if current.role != item["role"] or int(current.sort_order or 0) != int(item["sort_order"]):
                current.role = item["role"]
                current.sort_order = item["sort_order"]
                current.revision = int(current.revision or 1) + 1
                current.updated_at = now
                session.add(current)
                changed = True
            continue
        session.add(
            StoryboardShotAssetLink(
                script_id=episode.script_id,
                episode_id=panel.episode_id,
                panel_id=panel.id,
                resource_id=item["resource_id"],
                role=item["role"],
                sort_order=item["sort_order"],
                revision=1,
                created_at=now,
                updated_at=now,
            )
        )
        changed = True

    if changed:
        session.commit()


def sync_storyboard_asset_links_for_script(session: Session, script_id: int) -> None:
    panels = session.exec(
        select(Panel).join(Episode, Panel.episode_id == Episode.id).where(Episode.script_id == script_id)
    ).all()
    if not panels:
        return
    episodes = {episode.id: episode for episode in session.exec(select(Episode).where(Episode.script_id == script_id)).all()}
    changed = False
    now = datetime.utcnow()
    for panel in panels:
        panel.episode = episodes.get(panel.episode_id)  # type: ignore[attr-defined]
        bindings = _json_load(panel.entity_bindings_json, {})
        if not isinstance(bindings, dict):
            bindings = {}
        desired: Dict[int, Dict[str, Any]] = {}
        for role_group, role_value in (("characters", "character"), ("scenes", "scene"), ("props", "prop")):
            for sort_order, item in enumerate(bindings.get(role_group) or [], start=1):
                resource_id = item.get("asset_id")
                if not resource_id:
                    continue
                try:
                    desired[int(resource_id)] = {
                        "role": str(item.get("match_type") or role_value or "").strip() or role_value,
                        "sort_order": sort_order,
                    }
                except Exception:
                    continue
        existing = session.exec(select(StoryboardShotAssetLink).where(StoryboardShotAssetLink.panel_id == panel.id)).all()
        existing_by_resource = {item.resource_id: item for item in existing}
        for item in existing:
            if item.resource_id not in desired:
                session.delete(item)
                changed = True
        for resource_id, meta in desired.items():
            current = existing_by_resource.get(resource_id)
            if current:
                if current.role != meta["role"] or int(current.sort_order or 0) != int(meta["sort_order"]):
                    current.role = meta["role"]
                    current.sort_order = meta["sort_order"]
                    current.revision = int(current.revision or 1) + 1
                    current.updated_at = now
                    session.add(current)
                    changed = True
                continue
            session.add(
                StoryboardShotAssetLink(
                    script_id=script_id,
                    episode_id=panel.episode_id,
                    panel_id=panel.id,
                    resource_id=resource_id,
                    role=meta["role"],
                    sort_order=meta["sort_order"],
                    revision=1,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed = True
    if changed:
        session.commit()


def append_domain_event(
    session: Session,
    *,
    script_id: int,
    event_type: str,
    entity_type: str,
    entity_id: int,
    payload: Optional[Dict[str, Any]] = None,
    created_by_user_id: Optional[int] = None,
) -> DomainEvent:
    event = DomainEvent(
        script_id=script_id,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload_json=_json_dump(payload or {}),
        created_by_user_id=created_by_user_id,
        created_at=datetime.utcnow(),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _upsert_media_asset_from_record(session: Session, script_id: int, unit_type: str, record: GenerationRecord) -> Optional[MediaAsset]:
    preview_url = str(record.preview_url or "").strip()
    if not preview_url:
        return None
    existing = session.exec(
        select(MediaAsset).where(MediaAsset.source_record_id == record.id)
    ).first()
    if existing:
        existing.url = preview_url
        existing.thumbnail_url = str(record.thumbnail_url or "").strip() or existing.thumbnail_url
        existing.media_type = unit_type
        existing.metadata_json = _json_dump({"record_id": _encode(record.id), "status": str(record.status or "")})
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing
    item = MediaAsset(
        script_id=script_id,
        media_type=unit_type,
        url=preview_url,
        thumbnail_url=str(record.thumbnail_url or "").strip() or None,
        source_record_id=record.id,
        metadata_json=_json_dump({"record_id": _encode(record.id), "status": str(record.status or "")}),
        created_at=datetime.utcnow(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def sync_generation_unit_runtime_state(session: Session, script_id: int) -> None:
    units = session.exec(select(GenerationUnit).where(GenerationUnit.script_id == script_id)).all()
    if not units:
        return
    changed = False
    now = datetime.utcnow()
    for unit in units:
        unit_changed = False
        if not unit.generation_record_id:
            continue
        record = session.get(GenerationRecord, unit.generation_record_id)
        if not record:
            continue
        next_status = str(record.status or unit.status or "empty")
        media = None
        if next_status == "completed":
            media = _upsert_media_asset_from_record(session, script_id, unit.unit_type, record)
        if unit.status != next_status:
            unit.status = next_status
            unit_changed = True
        if media and unit.current_media_id != media.id:
            unit.current_media_id = media.id
            unit_changed = True
        version_entries = _json_load(unit.versions_json, [])
        if media and isinstance(version_entries, list):
            current_url = str(media.url or "").strip()
            if current_url and not any(str(item.get("url") or "").strip() == current_url for item in version_entries if isinstance(item, dict)):
                version_entries.append(
                    {
                        "recordId": _encode(record.id),
                        "mediaId": _encode(media.id),
                        "url": current_url,
                        "thumbnailUrl": media.thumbnail_url,
                        "createdAt": _to_iso(now),
                    }
                )
                unit.versions_json = _json_dump(version_entries)
                unit_changed = True
        if unit_changed:
            unit.updated_at = now
            session.add(unit)
            changed = True
    if changed:
        session.commit()


def serialize_project(script: Script) -> Dict[str, Any]:
    return {
        "id": _encode(script.id),
        "project_id": _encode(script.id),
        "hash_id": _encode(script.id),
        "title": script.name,
        "name": script.name,
        "description": script.description or "",
        "aspect_ratio": script.aspect_ratio,
        "style_preset": script.style_preset,
        "created_at": _to_iso(script.created_at),
        "updated_at": _to_iso(script.updated_at),
    }


def serialize_episode(script: Script, episode: Episode) -> Dict[str, Any]:
    return {
        "id": _encode(episode.id),
        "episode_id": _encode(episode.id),
        "hash_id": _encode(episode.id),
        "project_id": _encode(script.id),
        "episode_no": int(episode.sequence_num or 0),
        "sequence_num": int(episode.sequence_num or 0),
        "title": episode.title,
        "raw_script": episode.source_text or "",
        "source_text": episode.source_text or "",
        "storyboard_mode": episode.storyboard_mode or "commentary",
        "workflow_override_json": _json_load(episode.workflow_override_json, {}),
        "updated_at": _to_iso(episode.updated_at),
        "created_at": _to_iso(episode.created_at),
    }


def serialize_asset(resource: SharedResource, default_version: Optional[SharedResourceVersion]) -> Dict[str, Any]:
    prompt = str(default_version.appearance_prompt or "").strip() if default_version else ""
    return {
        "id": _encode(resource.id),
        "asset_id": _encode(resource.id),
        "hash_id": _encode(resource.id),
        "name": resource.name,
        "resource_type": resource.resource_type,
        "asset_type": resource.resource_type,
        "description": resource.description or "",
        "trigger_word": resource.trigger_word or "",
        "aliases": _serialize_aliases(resource.aliases),
        "file_url": resource.file_url,
        "thumbnail_url": resource.thumbnail_url,
        "prompt": prompt,
        "negative_prompt": "",
        "updated_at": _to_iso(resource.updated_at),
        "created_at": _to_iso(resource.created_at),
    }


def serialize_episode_asset_link(item: EpisodeAssetLink) -> Dict[str, Any]:
    return {
        "id": _encode(item.id),
        "episodeId": _encode(item.episode_id),
        "assetId": _encode(item.resource_id),
        "sortOrder": int(item.sort_order or 0),
        "revision": int(item.revision or 1),
        "updatedAt": _to_iso(item.updated_at),
    }


def serialize_storyboard_shot_asset_link(item: StoryboardShotAssetLink) -> Dict[str, Any]:
    return {
        "id": _encode(item.id),
        "shotId": _encode(item.panel_id),
        "assetId": _encode(item.resource_id),
        "role": item.role or "",
        "sortOrder": int(item.sort_order or 0),
        "revision": int(item.revision or 1),
        "updatedAt": _to_iso(item.updated_at),
    }


def serialize_generation_unit(item: GenerationUnit) -> Dict[str, Any]:
    return {
        "id": _encode(item.id),
        "projectId": _encode(item.script_id),
        "episodeId": _encode(item.episode_id),
        "unitType": item.unit_type,
        "name": item.name,
        "ownerType": item.owner_type,
        "ownerId": _encode(item.owner_id),
        "prompt": item.prompt or "",
        "negativePrompt": item.negative_prompt or "",
        "modelId": item.model_id or "",
        "params": _json_load(item.params_json, {}),
        "status": item.status,
        "currentMediaId": _encode(item.current_media_id),
        "generationRecordId": _encode(item.generation_record_id),
        "versions": _json_load(item.versions_json, []),
        "revision": int(item.revision or 1),
        "createdAt": _to_iso(item.created_at),
        "updatedAt": _to_iso(item.updated_at),
    }


def serialize_generation_unit_input(item: GenerationUnitInput) -> Dict[str, Any]:
    return {
        "id": _encode(item.id),
        "targetUnitId": _encode(item.target_unit_id),
        "sourceUnitId": _encode(item.source_unit_id),
        "sourceMediaId": _encode(item.source_media_id),
        "inputType": item.input_type,
        "role": item.role or "",
        "weight": item.weight,
        "sortOrder": int(item.sort_order or 0),
        "metadata": _json_load(item.metadata_json, {}),
        "createdAt": _to_iso(item.created_at),
    }


def serialize_media_asset(item: MediaAsset) -> Dict[str, Any]:
    return {
        "id": _encode(item.id),
        "projectId": _encode(item.script_id),
        "mediaType": item.media_type,
        "url": item.url,
        "thumbnailUrl": item.thumbnail_url,
        "width": item.width,
        "height": item.height,
        "durationSec": item.duration_seconds,
        "sourceRecordId": _encode(item.source_record_id),
        "metadata": _json_load(item.metadata_json, {}),
        "createdAt": _to_iso(item.created_at),
    }


def serialize_canvas_node(item: CanvasNode) -> Dict[str, Any]:
    return {
        "id": _encode(item.id),
        "workspaceId": _encode(item.workspace_id),
        "nodeType": item.type,
        "type": item.type,
        "title": item.title,
        "domainType": item.domain_type,
        "domainId": _encode(item.domain_id),
        "parentNodeId": _encode(item.parent_node_id),
        "x": float(item.position_x or 0.0),
        "y": float(item.position_y or 0.0),
        "width": float(item.width or 0.0) if item.width is not None else None,
        "height": float(item.height or 0.0) if item.height is not None else None,
        "collapsed": bool(item.collapsed),
        "hidden": bool(item.hidden),
        "locked": bool(item.locked),
        "viewData": _json_load(item.view_data_json, {}),
        "revision": int(item.revision or 1),
        "createdAt": _to_iso(item.created_at),
        "updatedAt": _to_iso(item.updated_at),
    }


def serialize_canvas_edge(item: CanvasEdge) -> Dict[str, Any]:
    return {
        "id": _encode(item.id),
        "workspaceId": _encode(item.workspace_id),
        "sourceNodeId": _encode(item.source_node_id),
        "targetNodeId": _encode(item.target_node_id),
        "sourcePortId": item.source_port_id or "",
        "targetPortId": item.target_port_id or "",
        "edgeType": item.edge_type,
        "role": item.role or "",
        "domainType": item.domain_type,
        "domainId": _encode(item.domain_id),
        "isProjection": bool(item.is_projection),
        "hidden": bool(item.hidden),
        "viewData": _json_load(item.view_data_json, {}),
        "label": item.label or "",
        "createdAt": _to_iso(item.created_at),
        "updatedAt": _to_iso(item.updated_at),
    }


def build_project_workspace(session: Session, script: Script) -> Dict[str, Any]:
    ensure_default_episode_asset_links(session, script.id)
    sync_storyboard_asset_links_for_script(session, script.id)
    sync_generation_unit_runtime_state(session, script.id)

    from services.canvas_projection_service import rebuild_project_projection  # local import to avoid cycle

    rebuild_project_projection(session, script.id)

    episodes = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc(), Episode.id.asc())).all()
    resources = session.exec(select(SharedResource).where(SharedResource.script_id == script.id).order_by(SharedResource.created_at.asc(), SharedResource.id.asc())).all()
    resource_ids = [item.id for item in resources]
    default_versions = _default_version_map(session, resource_ids)
    episode_asset_links = session.exec(
        select(EpisodeAssetLink)
        .where(EpisodeAssetLink.script_id == script.id)
        .order_by(EpisodeAssetLink.episode_id.asc(), EpisodeAssetLink.sort_order.asc(), EpisodeAssetLink.id.asc())
    ).all()
    shot_asset_links = session.exec(
        select(StoryboardShotAssetLink)
        .where(StoryboardShotAssetLink.script_id == script.id)
        .order_by(StoryboardShotAssetLink.episode_id.asc(), StoryboardShotAssetLink.panel_id.asc(), StoryboardShotAssetLink.sort_order.asc())
    ).all()
    units = session.exec(
        select(GenerationUnit).where(GenerationUnit.script_id == script.id).order_by(GenerationUnit.created_at.asc(), GenerationUnit.id.asc())
    ).all()
    unit_inputs = session.exec(
        select(GenerationUnitInput).where(GenerationUnitInput.script_id == script.id).order_by(GenerationUnitInput.created_at.asc(), GenerationUnitInput.id.asc())
    ).all()
    media_assets = session.exec(
        select(MediaAsset).where(MediaAsset.script_id == script.id).order_by(MediaAsset.created_at.asc(), MediaAsset.id.asc())
    ).all()

    shots: List[Dict[str, Any]] = []
    for episode in episodes:
        panels = session.exec(select(Panel).where(Panel.episode_id == episode.id).order_by(Panel.sequence_num.asc(), Panel.id.asc())).all()
        dependency_sequences = dependency_sequence_lookup(session, episode.id)
        segment_workspace = build_episode_segment_workspace(session, episode, panels, dependency_sequences)
        for item in segment_workspace.get("segments") or []:
            shot = dict(item)
            raw_id = shot.get("id")
            if raw_id:
                shot["id"] = _encode(int(raw_id))
                shot["shotId"] = shot["id"]
                shot["segment_id"] = shot["id"]
            shot["episodeId"] = _encode(episode.id)
            shot["shotNo"] = shot.get("title") or f"镜头 {shot.get('sequence_num') or shot.get('sequence') or ''}".strip()
            shot["description"] = shot.get("summary") or shot.get("segment_summary") or ""
            shot["imagePrompt"] = shot.get("multi_shot_prompt") or shot.get("prompt") or ""
            shot["videoPrompt"] = shot.get("multi_shot_video_prompt") or shot.get("video_prompt") or ""
            shot["durationSec"] = shot.get("recommended_duration_seconds") or 0
            normalized_cells: List[Dict[str, Any]] = []
            for cell in shot.get("grid_cells") or []:
                next_cell = dict(cell)
                if next_cell.get("id"):
                    next_cell["id"] = _encode(int(next_cell["id"]))
                normalized_cells.append(next_cell)
            shot["grid_cells"] = normalized_cells
            shots.append(shot)

    workspace = get_or_create_workspace(session, script)
    raw_canvas_nodes = session.exec(
        select(CanvasNode).where(CanvasNode.workspace_id == workspace.id, CanvasNode.archived_at == None).order_by(CanvasNode.created_at.asc(), CanvasNode.id.asc())
    ).all()
    allowed_node_ids = {
        item.id
        for item in raw_canvas_nodes
        if str(item.type or "") in {"project_root", "script_episode"} or str(item.domain_type or "").strip()
    }
    canvas_nodes = [item for item in raw_canvas_nodes if item.id in allowed_node_ids]
    raw_canvas_edges = session.exec(
        select(CanvasEdge).where(CanvasEdge.workspace_id == workspace.id).order_by(CanvasEdge.created_at.asc(), CanvasEdge.id.asc())
    ).all()
    canvas_edges = [
        item for item in raw_canvas_edges
        if item.source_node_id in allowed_node_ids and item.target_node_id in allowed_node_ids
    ]

    return {
        "project": serialize_project(script),
        "episodes": [serialize_episode(script, item) for item in episodes],
        "assets": [serialize_asset(item, default_versions.get(item.id)) for item in resources],
        "episodeAssetLinks": [serialize_episode_asset_link(item) for item in episode_asset_links],
        "storyboardShots": shots,
        "storyboardShotAssetLinks": [serialize_storyboard_shot_asset_link(item) for item in shot_asset_links],
        "audioItems": [],
        "generationUnits": [serialize_generation_unit(item) for item in units],
        "generationUnitInputs": [serialize_generation_unit_input(item) for item in unit_inputs],
        "mediaAssets": [serialize_media_asset(item) for item in media_assets],
        "canvasNodes": [serialize_canvas_node(item) for item in canvas_nodes],
        "canvasEdges": [serialize_canvas_edge(item) for item in canvas_edges],
    }
