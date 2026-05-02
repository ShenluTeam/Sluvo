from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from core.security import decode_id, encode_id
from models import CanvasEdge, CanvasNode, CanvasWorkspace, Episode, Panel, Script, SharedResource, SharedResourceVersion, Team, User
from schemas import (
    CANVAS_EDGE_TYPE_DATA_FLOW,
    CANVAS_EDGE_TYPE_REFERENCE,
    CANVAS_NODE_TYPE_ASSET_TABLE,
    CANVAS_NODE_TYPE_IMAGE,
    CANVAS_NODE_TYPE_SCRIPT,
    CANVAS_NODE_TYPE_STORYBOARD_TABLE,
    CANVAS_SYNC_STATUS_CLEAN,
    CANVAS_SYNC_STATUS_CONFLICT,
    CANVAS_SYNC_STATUS_DIRTY_LOCAL,
    CANVAS_SYNC_STATUS_ORPHANED,
    CANVAS_SYNC_STATUS_STALE,
    CanvasEdgeCreateRequest,
    CanvasEdgeUpdateRequest,
    CanvasNodeCreateRequest,
    CanvasNodeUpdateRequest,
    normalize_canvas_edge_type,
    normalize_canvas_node_type,
    normalize_canvas_sync_status,
)
from services.panel_revision_service import update_panel_with_revision
from services.panel_service import create_panel as create_panel_service, delete_panel as delete_panel_service
from services.resource_service import create_resource as create_resource_service, create_resource_version as create_resource_version_service, delete_resource as delete_resource_service, list_resource_versions as list_resource_versions_service, update_resource as update_resource_service, update_resource_version as update_resource_version_service
from services.storyboard_mode_service import recompute_episode_dependencies

SOURCE_SCRIPT = "script"
SOURCE_SCRIPT_ASSETS = "script_assets"
SOURCE_EPISODE_STORYBOARD = "episode_storyboard"
SOURCE_STORYBOARD_IMAGE = "storyboard_image"
DEFAULT_SIZES = {CANVAS_NODE_TYPE_SCRIPT: (360, 260), CANVAS_NODE_TYPE_ASSET_TABLE: (360, 260), CANVAS_NODE_TYPE_STORYBOARD_TABLE: (440, 320), CANVAS_NODE_TYPE_IMAGE: (320, 260)}
ALLOWED_EDGE_PAIRS = {
    (CANVAS_NODE_TYPE_SCRIPT, CANVAS_NODE_TYPE_ASSET_TABLE): CANVAS_EDGE_TYPE_DATA_FLOW,
    (CANVAS_NODE_TYPE_SCRIPT, CANVAS_NODE_TYPE_STORYBOARD_TABLE): CANVAS_EDGE_TYPE_DATA_FLOW,
    (CANVAS_NODE_TYPE_ASSET_TABLE, CANVAS_NODE_TYPE_STORYBOARD_TABLE): CANVAS_EDGE_TYPE_REFERENCE,
    (CANVAS_NODE_TYPE_STORYBOARD_TABLE, CANVAS_NODE_TYPE_IMAGE): CANVAS_EDGE_TYPE_DATA_FLOW,
}


def _utc_now() -> datetime:
    return datetime.utcnow()


def _json_load(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _json_dump(value: Any, fallback: str) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return fallback


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _enc(value: Optional[int]) -> Optional[str]:
    return encode_id(value) if value else None


def _dec(value: Optional[str]) -> Optional[int]:
    text = str(value or "").strip()
    return decode_id(text) if text else None


def _max_dt(items: Iterable[Optional[datetime]]) -> Optional[datetime]:
    values = [item for item in items if item is not None]
    return max(values) if values else None


def _aliases(raw: Optional[str]) -> List[str]:
    data = _json_load(raw, [])
    return [str(item).strip() for item in data if str(item or "").strip()] if isinstance(data, list) else []


def _bindings(raw: Optional[str]) -> Dict[str, List[Dict[str, Any]]]:
    data = _json_load(raw, {})
    if not isinstance(data, dict):
        return {"characters": [], "scenes": [], "props": []}
    return {key: data.get(key) if isinstance(data.get(key), list) else [] for key in ("characters", "scenes", "props")}


def _txt_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    return [item.strip() for item in str(value or "").replace("，", ",").split(",") if item.strip()]


def _size(node_type: str) -> tuple[float, float]:
    width, height = DEFAULT_SIZES.get(node_type, (320, 220))
    return float(width), float(height)


def _bootstrap_key(node_type: str, source_id: int) -> str:
    if node_type == CANVAS_NODE_TYPE_SCRIPT:
        return f"{SOURCE_SCRIPT}:{source_id}"
    if node_type == CANVAS_NODE_TYPE_ASSET_TABLE:
        return f"{SOURCE_SCRIPT_ASSETS}:{source_id}"
    return f"{SOURCE_EPISODE_STORYBOARD}:{source_id}"


def _default_version(versions: List[SharedResourceVersion]) -> Optional[SharedResourceVersion]:
    return next((item for item in versions if item.is_default), None) or (versions[0] if versions else None)


def _row(panel: Panel) -> Dict[str, Any]:
    bindings = _bindings(panel.entity_bindings_json)
    characters = [item.get("name") for item in bindings["characters"] if item.get("name")] or _txt_list(panel.character)
    return {
        "id": encode_id(panel.id),
        "panelId": encode_id(panel.id),
        "sequence": int(panel.sequence_num or 0),
        "scriptSegment": panel.original_text or "",
        "scene": panel.scene or "",
        "characters": characters,
        "shotType": panel.shot_type or "",
        "cameraAngle": panel.camera_motion or "",
        "composition": panel.composition or "",
        "action": panel.narration_text or "",
        "dialogue": panel.dialogue_text or "",
        "duration": int(panel.recommended_duration_seconds or 0),
        "imagePrompt": panel.prompt or panel.prompt_zh or "",
        "videoPrompt": panel.video_prompt or "",
        "assetRefs": {
            "characterIds": [_enc(item.get("asset_id")) for item in bindings["characters"] if item.get("asset_id")],
            "sceneIds": [_enc(item.get("asset_id")) for item in bindings["scenes"] if item.get("asset_id")],
            "propIds": [_enc(item.get("asset_id")) for item in bindings["props"] if item.get("asset_id")],
        },
        "status": str(panel.status or "idle").lower(),
        "imageUrl": panel.image_url or panel.file_url or "",
    }


def build_script_node_data(script: Script, episodes: Iterable[Episode]) -> Dict[str, Any]:
    content = script.source_text or ""
    return {
        "projectId": _enc(script.id),
        "scriptId": _enc(script.id),
        "title": script.name,
        "content": content,
        "summary": content[:280],
        "episodes": [{"id": _enc(item.id), "title": item.title, "content": item.source_text or ""} for item in episodes],
        "tags": [],
        "styleProfile": {"targetPlatform": "", "tone": "", "genre": "", "audience": ""},
    }


def build_asset_table_node_data(session: Session, script: Script, resources: Iterable[SharedResource]) -> Dict[str, Any]:
    resources = list(resources)
    versions = session.exec(select(SharedResourceVersion).where(SharedResourceVersion.resource_id.in_([item.id for item in resources]))).all() if resources else []
    versions_map: Dict[int, List[SharedResourceVersion]] = {}
    for version in versions:
        versions_map.setdefault(version.resource_id, []).append(version)
    result = {"characters": [], "scenes": [], "props": []}
    for resource in resources:
        version = _default_version(versions_map.get(resource.id, []))
        prompt = str(version.appearance_prompt).strip() if version and str(version.appearance_prompt or "").strip() else str(resource.description or "").strip()
        item = {"id": _enc(resource.id), "name": resource.name, "description": resource.description or "", "aliases": _aliases(resource.aliases), "prompt": prompt, "imageRef": resource.thumbnail_url or resource.file_url or "", "triggerWord": resource.trigger_word or ""}
        if resource.resource_type == "character":
            result["characters"].append(item)
        elif resource.resource_type == "scene":
            result["scenes"].append(item)
        elif resource.resource_type == "prop":
            result["props"].append(item)
    return {"scriptId": _enc(script.id), **result, "summaryCounts": {"characters": len(result["characters"]), "scenes": len(result["scenes"]), "props": len(result["props"])} }


def build_storyboard_table_node_data(script: Script, episode: Episode, panels: Iterable[Panel]) -> Dict[str, Any]:
    rows = [_row(panel) for panel in panels]
    return {"scriptId": _enc(script.id), "episodeId": _enc(episode.id), "title": episode.title, "rows": rows, "rowCount": len(rows)}


def build_image_node_data(script: Script, episode: Episode, panel: Panel) -> Dict[str, Any]:
    image_url = panel.image_url or panel.file_url or ""
    result_images = [image_url] if image_url else []
    return {"projectId": _enc(script.id), "episodeId": _enc(episode.id), "sourcePanelId": _enc(panel.id), "sourceStoryboardRowId": _enc(panel.id), "prompt": panel.prompt or panel.prompt_zh or "", "negativePrompt": panel.negative_prompt or "", "model": "nano-banana-pro", "mode": "text_to_image", "params": {"aspectRatio": "16:9", "quality": "2k"}, "referenceImages": [], "resultImages": result_images, "selectedImage": result_images[0] if result_images else "", "sourceSequence": int(panel.sequence_num or 0)}

def _script_snapshot(session: Session, script: Script) -> tuple[Dict[str, Any], Optional[datetime]]:
    episodes = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc())).all()
    return build_script_node_data(script, episodes), script.updated_at or script.created_at


def _asset_snapshot(session: Session, script: Script) -> tuple[Dict[str, Any], Optional[datetime]]:
    resources = session.exec(select(SharedResource).where(SharedResource.script_id == script.id).order_by(SharedResource.created_at.desc())).all()
    updated_at = _max_dt([script.updated_at or script.created_at] + [item.updated_at or item.created_at for item in resources])
    return build_asset_table_node_data(session, script, resources), updated_at


def _storyboard_snapshot(session: Session, script: Script, episode_id: int) -> tuple[Optional[Dict[str, Any]], Optional[datetime]]:
    episode = session.get(Episode, episode_id)
    if not episode or episode.script_id != script.id:
        return None, None
    panels = session.exec(select(Panel).where(Panel.episode_id == episode.id).order_by(Panel.sequence_num.asc(), Panel.id.asc())).all()
    updated_at = _max_dt([episode.updated_at or episode.created_at] + [item.updated_at or item.created_at for item in panels])
    return build_storyboard_table_node_data(script, episode, panels), updated_at


def _image_snapshot(session: Session, script: Script, episode_id: int, panel_id: int) -> tuple[Optional[Dict[str, Any]], Optional[datetime]]:
    episode = session.get(Episode, episode_id)
    panel = session.get(Panel, panel_id)
    if not episode or not panel or panel.episode_id != episode.id or episode.script_id != script.id:
        return None, None
    return build_image_node_data(script, episode, panel), panel.updated_at or panel.created_at


def _apply_versions(node: CanvasNode, source_data: Optional[Dict[str, Any]], source_updated_at: Optional[datetime], force_clean: bool = False) -> None:
    snapshot_hash = _hash(_json_load(node.data_json, {}))
    source_hash = _hash(source_data) if source_data is not None else None
    previous_source_hash = node.source_version
    node.snapshot_version = snapshot_hash
    node.source_version = source_hash
    node.source_updated_at = source_updated_at
    if source_data is None:
        node.sync_status = CANVAS_SYNC_STATUS_ORPHANED
    elif force_clean:
        node.sync_status = CANVAS_SYNC_STATUS_CLEAN
        node.last_synced_at = _utc_now()
    elif normalize_canvas_sync_status(node.sync_status) == CANVAS_SYNC_STATUS_DIRTY_LOCAL:
        node.sync_status = CANVAS_SYNC_STATUS_CONFLICT if previous_source_hash and previous_source_hash != source_hash else CANVAS_SYNC_STATUS_DIRTY_LOCAL
    elif snapshot_hash == source_hash:
        node.sync_status = CANVAS_SYNC_STATUS_CLEAN
    else:
        node.sync_status = CANVAS_SYNC_STATUS_STALE


def serialize_workspace(workspace: CanvasWorkspace) -> Dict[str, Any]:
    return {"id": _enc(workspace.id), "scriptId": _enc(workspace.script_id), "title": workspace.title, "description": workspace.description or "", "viewport": _json_load(workspace.viewport_json, {"x": 0, "y": 0, "zoom": 1}), "createdAt": workspace.created_at.isoformat() if workspace.created_at else None, "updatedAt": workspace.updated_at.isoformat() if workspace.updated_at else None}


def serialize_canvas_node(node: CanvasNode) -> Dict[str, Any]:
    return {
        "id": _enc(node.id), "type": node.type, "title": node.title,
        "position": {"x": float(node.position_x or 0), "y": float(node.position_y or 0)},
        "size": {"width": float(node.width or 0), "height": float(node.height or 0)},
        "status": node.status, "source_type": node.source_type, "source_id": _enc(node.source_id), "source_sub_id": _enc(node.source_sub_id),
        "bootstrap_key": node.bootstrap_key, "sync_status": node.sync_status, "snapshot_version": node.snapshot_version, "source_version": node.source_version,
        "domain_type": node.domain_type, "domain_id": _enc(node.domain_id), "parent_node_id": _enc(node.parent_node_id),
        "collapsed": bool(getattr(node, "collapsed", False)), "hidden": bool(getattr(node, "hidden", False)), "locked": bool(getattr(node, "locked", False)),
        "viewData": _json_load(getattr(node, "view_data_json", "{}"), {}),
        "revision": int(getattr(node, "revision", 1) or 1),
        "source_updated_at": node.source_updated_at.isoformat() if node.source_updated_at else None,
        "last_synced_at": node.last_synced_at.isoformat() if node.last_synced_at else None,
        "archived_at": node.archived_at.isoformat() if node.archived_at else None,
        "data": _json_load(node.data_json, {}), "context": _json_load(node.context_json, {}), "aiConfig": _json_load(node.ai_config_json, {}), "meta": _json_load(node.meta_json, {}),
        "createdAt": node.created_at.isoformat() if node.created_at else None, "updatedAt": node.updated_at.isoformat() if node.updated_at else None,
    }


def serialize_canvas_edge(edge: CanvasEdge) -> Dict[str, Any]:
    return {
        "id": _enc(edge.id), "source": _enc(edge.source_node_id), "target": _enc(edge.target_node_id), "type": edge.edge_type,
        "sourcePortId": getattr(edge, "source_port_id", None) or "", "targetPortId": getattr(edge, "target_port_id", None) or "",
        "role": getattr(edge, "role", None) or "", "domainType": getattr(edge, "domain_type", None), "domainId": _enc(getattr(edge, "domain_id", None)),
        "isProjection": bool(getattr(edge, "is_projection", True)), "hidden": bool(getattr(edge, "hidden", False)),
        "viewData": _json_load(getattr(edge, "view_data_json", "{}"), {}),
        "mapping": _json_load(edge.mapping_json, []), "label": edge.label or "",
        "createdAt": edge.created_at.isoformat() if edge.created_at else None, "updatedAt": edge.updated_at.isoformat() if edge.updated_at else None,
    }


def list_workspace_nodes(session: Session, workspace_id: int, include_archived: bool = False) -> List[CanvasNode]:
    query = select(CanvasNode).where(CanvasNode.workspace_id == workspace_id)
    if not include_archived:
        query = query.where(CanvasNode.archived_at == None)
    return session.exec(query.order_by(CanvasNode.created_at.asc(), CanvasNode.id.asc())).all()


def list_workspace_edges(session: Session, workspace_id: int) -> List[CanvasEdge]:
    return session.exec(select(CanvasEdge).where(CanvasEdge.workspace_id == workspace_id).order_by(CanvasEdge.created_at.asc(), CanvasEdge.id.asc())).all()


def get_workspace_by_script_id(session: Session, script_id: int) -> Optional[CanvasWorkspace]:
    return session.exec(select(CanvasWorkspace).where(CanvasWorkspace.script_id == script_id)).first()


def require_workspace(session: Session, workspace_id: int) -> CanvasWorkspace:
    workspace = session.get(CanvasWorkspace, workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail={"needs_bootstrap": True, "message": "画布工作区不存在"})
    return workspace


def require_canvas_node(session: Session, node_id: int) -> CanvasNode:
    node = session.get(CanvasNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="画布节点不存在")
    return node


def require_canvas_edge(session: Session, edge_id: int) -> CanvasEdge:
    edge = session.get(CanvasEdge, edge_id)
    if not edge:
        raise HTTPException(status_code=404, detail="画布连线不存在")
    return edge


def get_or_create_workspace(session: Session, script: Script) -> CanvasWorkspace:
    workspace = get_workspace_by_script_id(session, script.id)
    if workspace:
        return workspace
    now = _utc_now()
    workspace = CanvasWorkspace(script_id=script.id, title=f"{script.name} · AI 原生画布", description="", viewport_json=_json_dump({"x": 0, "y": 0, "zoom": 1}, "{}"), created_at=now, updated_at=now)
    session.add(workspace)
    session.commit()
    session.refresh(workspace)
    return workspace


def rebuild_workspace_contexts(session: Session, workspace_id: int) -> None:
    nodes = list_workspace_nodes(session, workspace_id)
    edges = list_workspace_edges(session, workspace_id)
    node_map = {node.id: node for node in nodes}
    incoming = {node.id: [] for node in nodes}
    outgoing = {node.id: [] for node in nodes}
    for edge in edges:
        incoming.setdefault(edge.target_node_id, []).append(edge.source_node_id)
        outgoing.setdefault(edge.source_node_id, []).append(edge.target_node_id)
    for node in nodes:
        data = _json_load(node.data_json, {})
        context = _json_load(node.context_json, {})
        context["upstreamNodeIds"] = [_enc(item) for item in incoming.get(node.id, [])]
        context["downstreamNodeIds"] = [_enc(item) for item in outgoing.get(node.id, [])]
        if node.type == CANVAS_NODE_TYPE_STORYBOARD_TABLE:
            assets = {"characters": [], "scenes": [], "props": []}
            for upstream_id in incoming.get(node.id, []):
                upstream = node_map.get(upstream_id)
                if upstream and upstream.type == CANVAS_NODE_TYPE_ASSET_TABLE:
                    upstream_data = _json_load(upstream.data_json, {})
                    assets["characters"] = [item.get("name") for item in upstream_data.get("characters", []) if item.get("name")]
                    assets["scenes"] = [item.get("name") for item in upstream_data.get("scenes", []) if item.get("name")]
                    assets["props"] = [item.get("name") for item in upstream_data.get("props", []) if item.get("name")]
            context["inheritedAssets"] = assets
            context["inheritedStoryboardRows"] = [item.get("id") for item in data.get("rows", []) if item.get("id")]
        elif node.type == CANVAS_NODE_TYPE_IMAGE:
            context["inheritedStoryboardRows"] = [data.get("sourceStoryboardRowId")] if data.get("sourceStoryboardRowId") else []
            context["referencedMedia"] = list(data.get("resultImages") or [])
        elif node.type == CANVAS_NODE_TYPE_SCRIPT:
            context["inheritedScriptSegments"] = [data.get("content")] if data.get("content") else []
        node.context_json = _json_dump(context, "{}")
        node.updated_at = _utc_now()
        session.add(node)
    session.commit()

def refresh_node_snapshot(session: Session, workspace: CanvasWorkspace, node: CanvasNode, force_clean: bool = False) -> CanvasNode:
    script = session.get(Script, workspace.script_id)
    if not script:
        raise HTTPException(status_code=404, detail="关联剧本不存在")
    source_data = None
    source_updated_at = None
    if node.source_type == SOURCE_SCRIPT or node.type == CANVAS_NODE_TYPE_SCRIPT:
        source_data, source_updated_at = _script_snapshot(session, script)
        node.source_type = SOURCE_SCRIPT
        node.source_id = script.id
        node.source_sub_id = None
        node.bootstrap_key = _bootstrap_key(CANVAS_NODE_TYPE_SCRIPT, script.id)
        node.title = script.name or node.title
    elif node.source_type == SOURCE_SCRIPT_ASSETS or node.type == CANVAS_NODE_TYPE_ASSET_TABLE:
        source_data, source_updated_at = _asset_snapshot(session, script)
        node.source_type = SOURCE_SCRIPT_ASSETS
        node.source_id = script.id
        node.source_sub_id = None
        node.bootstrap_key = _bootstrap_key(CANVAS_NODE_TYPE_ASSET_TABLE, script.id)
        node.title = "资产表"
    elif node.source_type == SOURCE_EPISODE_STORYBOARD or node.type == CANVAS_NODE_TYPE_STORYBOARD_TABLE:
        episode_id = node.source_id or _dec(_json_load(node.data_json, {}).get("episodeId"))
        if episode_id:
            source_data, source_updated_at = _storyboard_snapshot(session, script, episode_id)
            node.source_type = SOURCE_EPISODE_STORYBOARD
            node.source_id = episode_id
            node.source_sub_id = None
            node.bootstrap_key = _bootstrap_key(CANVAS_NODE_TYPE_STORYBOARD_TABLE, episode_id)
            node.title = (source_data or {}).get("title") or node.title
    elif node.source_type == SOURCE_STORYBOARD_IMAGE or node.type == CANVAS_NODE_TYPE_IMAGE:
        raw = _json_load(node.data_json, {})
        episode_id = node.source_id or _dec(raw.get("episodeId"))
        panel_id = node.source_sub_id or _dec(raw.get("sourcePanelId"))
        if episode_id and panel_id:
            source_data, source_updated_at = _image_snapshot(session, script, episode_id, panel_id)
            node.source_type = SOURCE_STORYBOARD_IMAGE
            node.source_id = episode_id
            node.source_sub_id = panel_id
            if source_data:
                node.title = f"图片 · #{source_data.get('sourceSequence') or 0}"
    if source_data is not None:
        node.data_json = _json_dump(source_data, "{}")
    _apply_versions(node, source_data, source_updated_at, force_clean=force_clean)
    node.updated_at = _utc_now()
    session.add(node)
    session.commit()
    session.refresh(node)
    rebuild_workspace_contexts(session, workspace.id)
    session.refresh(node)
    return node


def update_node_meta(session: Session, node: CanvasNode, patch: Dict[str, Any]) -> CanvasNode:
    meta = _json_load(node.meta_json, {})
    meta.update(patch or {})
    node.meta_json = _json_dump(meta, "{}")
    node.updated_at = _utc_now()
    session.add(node)
    session.commit()
    session.refresh(node)
    return node


def mark_downstream_nodes_needs_refresh(session: Session, workspace_id: int, source_node_ids: List[int], reason: str) -> None:
    target_ids = {edge.target_node_id for edge in list_workspace_edges(session, workspace_id) if edge.source_node_id in source_node_ids}
    for node_id in target_ids:
        node = session.get(CanvasNode, node_id)
        if not node or node.archived_at is not None:
            continue
        meta = _json_load(node.meta_json, {})
        meta["needsRefresh"] = True
        meta["refreshReason"] = reason
        node.meta_json = _json_dump(meta, "{}")
        if normalize_canvas_sync_status(node.sync_status) == CANVAS_SYNC_STATUS_CLEAN:
            node.sync_status = CANVAS_SYNC_STATUS_STALE
        node.updated_at = _utc_now()
        session.add(node)
    session.commit()


def create_canvas_node(session: Session, workspace: CanvasWorkspace, payload: CanvasNodeCreateRequest) -> CanvasNode:
    node_type = normalize_canvas_node_type(payload.type)
    width, height = _size(node_type)
    position = payload.position or {}
    size = payload.size or {}
    node = CanvasNode(
        workspace_id=workspace.id,
        type=node_type,
        title=payload.title or "未命名节点",
        position_x=float(position.get("x", 0)),
        position_y=float(position.get("y", 0)),
        width=float(size.get("width", width)),
        height=float(size.get("height", height)),
        status=payload.status or "idle",
        source_type=str(payload.source_type or "").strip() or None,
        source_id=_dec(payload.source_id),
        source_sub_id=_dec(payload.source_sub_id),
        bootstrap_key=payload.bootstrap_key or None,
        sync_status=normalize_canvas_sync_status(payload.sync_status),
        data_json=_json_dump(payload.data, "{}"),
        context_json=_json_dump(payload.context, "{}"),
        ai_config_json=_json_dump(payload.ai_config, "{}"),
        meta_json=_json_dump(payload.meta, "{}"),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    _apply_versions(node, _json_load(node.data_json, {}), None, force_clean=normalize_canvas_sync_status(node.sync_status) == CANVAS_SYNC_STATUS_CLEAN)
    session.add(node)
    session.commit()
    session.refresh(node)
    rebuild_workspace_contexts(session, workspace.id)
    return node


def update_canvas_node(session: Session, node: CanvasNode, payload: CanvasNodeUpdateRequest) -> CanvasNode:
    data_changed = False
    if payload.title is not None:
        node.title = payload.title or node.title
    if payload.position is not None:
        node.position_x = float(payload.position.get("x", node.position_x or 0))
        node.position_y = float(payload.position.get("y", node.position_y or 0))
    if payload.size is not None:
        node.width = float(payload.size.get("width", node.width or 0))
        node.height = float(payload.size.get("height", node.height or 0))
    if payload.status is not None:
        node.status = payload.status
    if payload.source_type is not None:
        node.source_type = str(payload.source_type or "").strip() or None
    if payload.source_id is not None:
        node.source_id = _dec(payload.source_id)
    if payload.source_sub_id is not None:
        node.source_sub_id = _dec(payload.source_sub_id)
    if payload.bootstrap_key is not None:
        node.bootstrap_key = payload.bootstrap_key or None
    if payload.data is not None:
        node.data_json = _json_dump(payload.data, "{}")
        data_changed = True
    if payload.context is not None:
        node.context_json = _json_dump(payload.context, "{}")
    if payload.ai_config is not None:
        node.ai_config_json = _json_dump(payload.ai_config, "{}")
    if payload.meta is not None:
        node.meta_json = _json_dump(payload.meta, "{}")
    if payload.sync_status is not None:
        node.sync_status = normalize_canvas_sync_status(payload.sync_status)
    elif data_changed and normalize_canvas_sync_status(node.sync_status) == CANVAS_SYNC_STATUS_CLEAN:
        node.sync_status = CANVAS_SYNC_STATUS_DIRTY_LOCAL
    node.snapshot_version = _hash(_json_load(node.data_json, {}))
    node.updated_at = _utc_now()
    session.add(node)
    session.commit()
    session.refresh(node)
    rebuild_workspace_contexts(session, node.workspace_id)
    session.refresh(node)
    return node


def delete_canvas_node(session: Session, node: CanvasNode) -> None:
    for edge in session.exec(select(CanvasEdge).where((CanvasEdge.source_node_id == node.id) | (CanvasEdge.target_node_id == node.id))).all():
        session.delete(edge)
    workspace_id = node.workspace_id
    session.delete(node)
    session.commit()
    rebuild_workspace_contexts(session, workspace_id)


def archive_canvas_node(session: Session, node: CanvasNode) -> CanvasNode:
    if node.archived_at is None:
        node.archived_at = _utc_now()
    for edge in session.exec(select(CanvasEdge).where((CanvasEdge.source_node_id == node.id) | (CanvasEdge.target_node_id == node.id))).all():
        session.delete(edge)
    node.updated_at = _utc_now()
    session.add(node)
    session.commit()
    session.refresh(node)
    rebuild_workspace_contexts(session, node.workspace_id)
    return node


def create_canvas_edge(session: Session, workspace: CanvasWorkspace, payload: CanvasEdgeCreateRequest) -> CanvasEdge:
    source_id = decode_id(payload.source)
    target_id = decode_id(payload.target)
    source_node = require_canvas_node(session, source_id)
    target_node = require_canvas_node(session, target_id)
    if source_node.workspace_id != workspace.id or target_node.workspace_id != workspace.id:
        raise HTTPException(status_code=400, detail="连线节点不属于当前工作区")
    expected_type = ALLOWED_EDGE_PAIRS.get((source_node.type, target_node.type))
    edge_type = normalize_canvas_edge_type(payload.type)
    if not expected_type or expected_type != edge_type:
        raise HTTPException(status_code=400, detail="当前节点之间不允许该语义连线")
    existing = session.exec(select(CanvasEdge).where(CanvasEdge.workspace_id == workspace.id, CanvasEdge.source_node_id == source_id, CanvasEdge.target_node_id == target_id)).first()
    if existing:
        raise HTTPException(status_code=400, detail="当前节点之间已存在连线")
    edge = CanvasEdge(workspace_id=workspace.id, source_node_id=source_id, target_node_id=target_id, edge_type=edge_type, mapping_json=_json_dump(payload.mapping, "[]"), label=payload.label, created_at=_utc_now(), updated_at=_utc_now())
    session.add(edge)
    session.commit()
    session.refresh(edge)
    rebuild_workspace_contexts(session, workspace.id)
    return edge


def update_canvas_edge(session: Session, edge: CanvasEdge, payload: CanvasEdgeUpdateRequest) -> CanvasEdge:
    if payload.type is not None:
        source_node = require_canvas_node(session, edge.source_node_id)
        target_node = require_canvas_node(session, edge.target_node_id)
        expected_type = ALLOWED_EDGE_PAIRS.get((source_node.type, target_node.type))
        edge_type = normalize_canvas_edge_type(payload.type)
        if not expected_type or expected_type != edge_type:
            raise HTTPException(status_code=400, detail="当前节点之间不允许该语义连线")
        edge.edge_type = edge_type
    if payload.mapping is not None:
        edge.mapping_json = _json_dump(payload.mapping, "[]")
    if payload.label is not None:
        edge.label = payload.label
    edge.updated_at = _utc_now()
    session.add(edge)
    session.commit()
    session.refresh(edge)
    rebuild_workspace_contexts(session, edge.workspace_id)
    return edge


def delete_canvas_edge(session: Session, edge: CanvasEdge) -> None:
    workspace_id = edge.workspace_id
    session.delete(edge)
    session.commit()
    rebuild_workspace_contexts(session, workspace_id)

def find_workspace_nodes_by_type(session: Session, workspace_id: int, node_type: str, include_archived: bool = False) -> List[CanvasNode]:
    query = select(CanvasNode).where(CanvasNode.workspace_id == workspace_id, CanvasNode.type == node_type)
    if not include_archived:
        query = query.where(CanvasNode.archived_at == None)
    return session.exec(query.order_by(CanvasNode.created_at.asc(), CanvasNode.id.asc())).all()


def find_image_node_by_panel(session: Session, workspace_id: int, encoded_panel_id: str) -> Optional[CanvasNode]:
    for node in find_workspace_nodes_by_type(session, workspace_id, CANVAS_NODE_TYPE_IMAGE):
        if str(_json_load(node.data_json, {}).get("sourcePanelId") or "") == str(encoded_panel_id):
            return node
    return None


def upsert_image_node_for_panel(session: Session, workspace: CanvasWorkspace, script: Script, episode: Episode, panel: Panel, anchor_storyboard_node: Optional[CanvasNode] = None) -> CanvasNode:
    existing = find_image_node_by_panel(session, workspace.id, encode_id(panel.id))
    if existing:
        return refresh_node_snapshot(session, workspace, existing, force_clean=True)
    image_nodes = find_workspace_nodes_by_type(session, workspace.id, CANVAS_NODE_TYPE_IMAGE)
    x = float(anchor_storyboard_node.position_x or 0) + 520 + len(image_nodes) * 340 if anchor_storyboard_node else 980
    y = float(anchor_storyboard_node.position_y or 0) if anchor_storyboard_node else 380
    width, height = _size(CANVAS_NODE_TYPE_IMAGE)
    node = CanvasNode(workspace_id=workspace.id, type=CANVAS_NODE_TYPE_IMAGE, title=f"图片 · #{panel.sequence_num}", position_x=x, position_y=y, width=width, height=height, status="idle", source_type=SOURCE_STORYBOARD_IMAGE, source_id=episode.id, source_sub_id=panel.id, bootstrap_key=None, sync_status=CANVAS_SYNC_STATUS_CLEAN, data_json=_json_dump(build_image_node_data(script, episode, panel), "{}"), context_json="{}", ai_config_json=_json_dump({"agentName": "神鹿 AI", "defaultModel": "nano-banana-pro", "capabilityBindings": {"image_generate": "generate-image", "image_regenerate": "regenerate-image"}}, "{}"), meta_json="{}", created_at=_utc_now(), updated_at=_utc_now())
    _apply_versions(node, _json_load(node.data_json, {}), panel.updated_at or panel.created_at, force_clean=True)
    session.add(node)
    session.commit()
    session.refresh(node)
    if anchor_storyboard_node and not session.exec(select(CanvasEdge).where(CanvasEdge.workspace_id == workspace.id, CanvasEdge.source_node_id == anchor_storyboard_node.id, CanvasEdge.target_node_id == node.id)).first():
        edge = CanvasEdge(workspace_id=workspace.id, source_node_id=anchor_storyboard_node.id, target_node_id=node.id, edge_type=CANVAS_EDGE_TYPE_DATA_FLOW, mapping_json=_json_dump([{"fromField": "rows[].imagePrompt", "toField": "prompt", "mode": "replace"}], "[]"), label="镜头提示词", created_at=_utc_now(), updated_at=_utc_now())
        session.add(edge)
        session.commit()
    rebuild_workspace_contexts(session, workspace.id)
    session.refresh(node)
    return node


def bootstrap_workspace(session: Session, script: Script, workspace: CanvasWorkspace, preferred_episode_id: Optional[int] = None, focus_panel_id: Optional[int] = None) -> Dict[str, Any]:
    added_nodes = 0
    added_edges = 0
    script_key = _bootstrap_key(CANVAS_NODE_TYPE_SCRIPT, script.id)
    if not session.exec(select(CanvasNode).where(CanvasNode.workspace_id == workspace.id, CanvasNode.bootstrap_key == script_key)).first():
        width, height = _size(CANVAS_NODE_TYPE_SCRIPT)
        node = CanvasNode(workspace_id=workspace.id, type=CANVAS_NODE_TYPE_SCRIPT, title=script.name or "剧本节点", position_x=80, position_y=120, width=width, height=height, status="idle", source_type=SOURCE_SCRIPT, source_id=script.id, source_sub_id=None, bootstrap_key=script_key, sync_status=CANVAS_SYNC_STATUS_CLEAN, data_json="{}", context_json="{}", ai_config_json=_json_dump({"agentName": "神鹿 AI", "defaultModel": "deepseek", "capabilityBindings": {"asset_extract": "extract-assets", "storyboard_generate": "generate-storyboard"}}, "{}"), meta_json="{}", created_at=_utc_now(), updated_at=_utc_now())
        session.add(node)
        session.commit()
        session.refresh(node)
        refresh_node_snapshot(session, workspace, node, force_clean=True)
        added_nodes += 1
    asset_key = _bootstrap_key(CANVAS_NODE_TYPE_ASSET_TABLE, script.id)
    if not session.exec(select(CanvasNode).where(CanvasNode.workspace_id == workspace.id, CanvasNode.bootstrap_key == asset_key)).first():
        width, height = _size(CANVAS_NODE_TYPE_ASSET_TABLE)
        node = CanvasNode(workspace_id=workspace.id, type=CANVAS_NODE_TYPE_ASSET_TABLE, title="资产表", position_x=500, position_y=80, width=width, height=height, status="idle", source_type=SOURCE_SCRIPT_ASSETS, source_id=script.id, source_sub_id=None, bootstrap_key=asset_key, sync_status=CANVAS_SYNC_STATUS_CLEAN, data_json="{}", context_json="{}", ai_config_json=_json_dump({"agentName": "神鹿 AI", "capabilityBindings": {"asset_extract": "extract-assets"}}, "{}"), meta_json="{}", created_at=_utc_now(), updated_at=_utc_now())
        session.add(node)
        session.commit()
        session.refresh(node)
        refresh_node_snapshot(session, workspace, node, force_clean=True)
        added_nodes += 1
    episodes = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc())).all()
    if preferred_episode_id:
        episodes.sort(key=lambda item: (0 if item.id == preferred_episode_id else 1, item.sequence_num))
    for index, episode in enumerate(episodes):
        storyboard_key = _bootstrap_key(CANVAS_NODE_TYPE_STORYBOARD_TABLE, episode.id)
        if session.exec(select(CanvasNode).where(CanvasNode.workspace_id == workspace.id, CanvasNode.bootstrap_key == storyboard_key)).first():
            continue
        width, height = _size(CANVAS_NODE_TYPE_STORYBOARD_TABLE)
        node = CanvasNode(workspace_id=workspace.id, type=CANVAS_NODE_TYPE_STORYBOARD_TABLE, title=episode.title or "分镜表", position_x=500, position_y=360 + index * 380, width=width, height=height, status="idle", source_type=SOURCE_EPISODE_STORYBOARD, source_id=episode.id, source_sub_id=None, bootstrap_key=storyboard_key, sync_status=CANVAS_SYNC_STATUS_CLEAN, data_json="{}", context_json="{}", ai_config_json=_json_dump({"agentName": "神鹿 AI", "defaultModel": "nano-banana-pro", "capabilityBindings": {"storyboard_generate": "generate-storyboard", "image_generate": "generate-image"}}, "{}"), meta_json="{}", created_at=_utc_now(), updated_at=_utc_now())
        session.add(node)
        session.commit()
        session.refresh(node)
        refresh_node_snapshot(session, workspace, node, force_clean=True)
        added_nodes += 1
    nodes = list_workspace_nodes(session, workspace.id)
    script_node = next((node for node in nodes if node.type == CANVAS_NODE_TYPE_SCRIPT), None)
    asset_node = next((node for node in nodes if node.type == CANVAS_NODE_TYPE_ASSET_TABLE), None)
    storyboard_nodes = [node for node in nodes if node.type == CANVAS_NODE_TYPE_STORYBOARD_TABLE]
    if script_node and asset_node and not session.exec(select(CanvasEdge).where(CanvasEdge.workspace_id == workspace.id, CanvasEdge.source_node_id == script_node.id, CanvasEdge.target_node_id == asset_node.id)).first():
        session.add(CanvasEdge(workspace_id=workspace.id, source_node_id=script_node.id, target_node_id=asset_node.id, edge_type=CANVAS_EDGE_TYPE_DATA_FLOW, mapping_json=_json_dump([{"fromField": "content", "toField": "scriptInput", "mode": "replace"}], "[]"), label="剧本文本", created_at=_utc_now(), updated_at=_utc_now()))
        session.commit()
        added_edges += 1
    for storyboard_node in storyboard_nodes:
        if script_node and not session.exec(select(CanvasEdge).where(CanvasEdge.workspace_id == workspace.id, CanvasEdge.source_node_id == script_node.id, CanvasEdge.target_node_id == storyboard_node.id)).first():
            session.add(CanvasEdge(workspace_id=workspace.id, source_node_id=script_node.id, target_node_id=storyboard_node.id, edge_type=CANVAS_EDGE_TYPE_DATA_FLOW, mapping_json=_json_dump([{"fromField": "content", "toField": "storyInput", "mode": "replace"}], "[]"), label="剧情输入", created_at=_utc_now(), updated_at=_utc_now()))
            session.commit()
            added_edges += 1
        if asset_node and not session.exec(select(CanvasEdge).where(CanvasEdge.workspace_id == workspace.id, CanvasEdge.source_node_id == asset_node.id, CanvasEdge.target_node_id == storyboard_node.id)).first():
            session.add(CanvasEdge(workspace_id=workspace.id, source_node_id=asset_node.id, target_node_id=storyboard_node.id, edge_type=CANVAS_EDGE_TYPE_REFERENCE, mapping_json=_json_dump([{"fromField": "assets", "toField": "assetRefs", "mode": "reference"}], "[]"), label="资产引用", created_at=_utc_now(), updated_at=_utc_now()))
            session.commit()
            added_edges += 1
    if focus_panel_id:
        panel = session.get(Panel, focus_panel_id)
        episode = session.get(Episode, panel.episode_id) if panel else None
        anchor = next((node for node in storyboard_nodes if node.source_id == getattr(episode, "id", None)), None)
        if panel and episode:
            upsert_image_node_for_panel(session, workspace, script, episode, panel, anchor)
    rebuild_workspace_contexts(session, workspace.id)
    return {"added_nodes": added_nodes, "added_edges": added_edges}


def reconcile_workspace(session: Session, workspace: CanvasWorkspace, script: Script, focus_panel_id: Optional[int] = None) -> Dict[str, Any]:
    summary = {"added": 0, "refreshed": 0, "skipped": 0, "orphaned": 0}
    bootstrap_result = bootstrap_workspace(session, script, workspace, focus_panel_id=focus_panel_id)
    summary["added"] += bootstrap_result["added_nodes"]
    for node in list_workspace_nodes(session, workspace.id):
        previous = node.sync_status
        refresh_node_snapshot(session, workspace, node)
        if node.sync_status == CANVAS_SYNC_STATUS_ORPHANED:
            summary["orphaned"] += 1
        elif node.sync_status != previous or node.last_synced_at is not None:
            summary["refreshed"] += 1
        else:
            summary["skipped"] += 1
    return summary


def create_bootstrap_workspace(session: Session, script: Script, preferred_episode_id: Optional[int] = None, focus_panel_id: Optional[int] = None) -> tuple[CanvasWorkspace, Dict[str, Any]]:
    workspace = get_or_create_workspace(session, script)
    return workspace, bootstrap_workspace(session, script, workspace, preferred_episode_id=preferred_episode_id, focus_panel_id=focus_panel_id)

def refresh_node_from_source(session: Session, workspace: CanvasWorkspace, node: CanvasNode) -> CanvasNode:
    return refresh_node_snapshot(session, workspace, node, force_clean=True)


def _sync_asset_prompt(session: Session, team: Team, resource: SharedResource, prompt: str) -> None:
    normalized_prompt = str(prompt or "").strip()
    versions = list_resource_versions_service(session, team, resource.id)
    default_version = next((item for item in versions if item.is_default), None)
    if default_version:
        update_resource_version_service(session, team, default_version.id, appearance_prompt=normalized_prompt, trigger_word=resource.trigger_word, is_default=True)
    elif normalized_prompt:
        create_resource_version_service(session, team, resource_id=resource.id, version_tag="v1", appearance_prompt=normalized_prompt, file_url=resource.file_url, trigger_word=resource.trigger_word, start_seq=None, end_seq=None, is_default=True)


def _push_asset_node(session: Session, workspace: CanvasWorkspace, node: CanvasNode, script: Script, team: Team) -> CanvasNode:
    data = _json_load(node.data_json, {})
    resources = session.exec(select(SharedResource).where(SharedResource.script_id == script.id)).all()
    existing = {encode_id(item.id): item for item in resources}
    seen: set[str] = set()
    for resource_type, key in (("character", "characters"), ("scene", "scenes"), ("prop", "props")):
        for item in data.get(key) if isinstance(data.get(key), list) else []:
            resource_id = str(item.get("id") or "").strip()
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            description = str(item.get("description") or "").strip()
            prompt = str(item.get("prompt") or "").strip()
            aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
            image_ref = str(item.get("imageRef") or "").strip()
            trigger_word = str(item.get("triggerWord") or "").strip() or None
            if resource_id and resource_id in existing:
                resource = update_resource_service(session, team, existing[resource_id].id, name=name, file_url=image_ref or existing[resource_id].file_url or "", trigger_word=trigger_word or existing[resource_id].trigger_word, aliases=aliases, description=description, owner_user_id=int(user.id) if user and user.id else None)
                _sync_asset_prompt(session, team, resource, prompt)
                seen.add(resource_id)
            else:
                resource = create_resource_service(session, team, script_id=script.id, resource_type=resource_type, name=name, file_url=image_ref or "", trigger_word=trigger_word, aliases=aliases, description=description, owner_user_id=int(user.id) if user and user.id else None)
                _sync_asset_prompt(session, team, resource, prompt)
                seen.add(encode_id(resource.id))
    for resource_id, resource in existing.items():
        if resource_id not in seen:
            delete_resource_service(session, team, resource.id)
    refreshed = refresh_node_snapshot(session, workspace, node, force_clean=True)
    mark_downstream_nodes_needs_refresh(session, workspace.id, [node.id], "资产节点已推送，建议刷新下游分镜")
    return refreshed


def _panel_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    return {"scene": str(row.get("scene") or "").strip(), "character": ", ".join(_txt_list(row.get("characters"))), "prompt": str(row.get("imagePrompt") or "").strip(), "original_text": str(row.get("scriptSegment") or "").strip(), "shot_type": str(row.get("shotType") or "").strip() or None, "camera_motion": str(row.get("cameraAngle") or "").strip() or None, "narration_text": str(row.get("action") or "").strip() or None, "dialogue_text": str(row.get("dialogue") or "").strip() or None, "recommended_duration_seconds": int(row.get("duration") or 0) or 6, "source": "canvas_sync"}


def _push_storyboard_node(session: Session, workspace: CanvasWorkspace, node: CanvasNode, script: Script, team: Team, user: Optional[User]) -> CanvasNode:
    if node.source_id is None:
        raise HTTPException(status_code=400, detail="分镜节点缺少 source_id")
    episode = session.get(Episode, node.source_id)
    if not episode or episode.script_id != script.id:
        raise HTTPException(status_code=404, detail="分镜节点对应剧集不存在")
    data = _json_load(node.data_json, {})
    rows = data.get("rows") if isinstance(data.get("rows"), list) else []
    current = session.exec(select(Panel).where(Panel.episode_id == episode.id).order_by(Panel.sequence_num.asc(), Panel.id.asc())).all()
    current_by_id = {encode_id(panel.id): panel for panel in current}
    result_panels: List[Panel] = []
    for row in rows:
        row = row if isinstance(row, dict) else {}
        row_id = str(row.get("id") or "").strip()
        if row_id and not row_id.startswith("temp:") and row_id in current_by_id:
            panel, _ = update_panel_with_revision(session, current_by_id[row_id], _panel_payload(row), created_by_user_id=user.id if user else None)
        else:
            panel = create_panel_service(session, team, episode.id, insert_at=None, panel_type=None)
            panel, _ = update_panel_with_revision(session, panel, _panel_payload(row), created_by_user_id=user.id if user else None)
        result_panels.append(panel)
    keep_ids = {panel.id for panel in result_panels}
    for panel in current:
        if panel.id not in keep_ids:
            delete_panel_service(session, team, panel.id)
    now = _utc_now()
    panels = session.exec(select(Panel).where(Panel.episode_id == episode.id).order_by(Panel.sequence_num.asc(), Panel.id.asc())).all()
    order = [panel.id for panel in result_panels]
    panels.sort(key=lambda panel: order.index(panel.id) if panel.id in order else len(order))
    for index, panel in enumerate(panels, start=1):
        panel.sequence_num = index
        panel.updated_at = now
        session.add(panel)
    episode.updated_at = now
    session.add(episode)
    session.commit()
    recompute_episode_dependencies(session, episode.id)
    session.commit()
    refreshed = refresh_node_snapshot(session, workspace, node, force_clean=True)
    mark_downstream_nodes_needs_refresh(session, workspace.id, [node.id], "分镜节点已推送，建议刷新图片节点")
    return refreshed


def push_node_to_source(session: Session, workspace: CanvasWorkspace, node: CanvasNode, team: Team, user: Optional[User] = None) -> CanvasNode:
    script = session.get(Script, workspace.script_id)
    if not script:
        raise HTTPException(status_code=404, detail="关联剧本不存在")
    if node.source_type == SOURCE_SCRIPT_ASSETS:
        return _push_asset_node(session, workspace, node, script, team)
    if node.source_type == SOURCE_EPISODE_STORYBOARD:
        return _push_storyboard_node(session, workspace, node, script, team, user)
    raise HTTPException(status_code=400, detail="当前节点暂不支持 push-to-source")

