from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from sqlmodel import Session, select

from models import (
    CanvasEdge,
    CanvasNode,
    Episode,
    EpisodeAssetLink,
    GenerationUnit,
    GenerationUnitInput,
    Panel,
    Script,
)
from schemas import (
    CANVAS_EDGE_TYPE_GENERATION,
    CANVAS_EDGE_TYPE_REFERENCE,
    CANVAS_EDGE_TYPE_SEQUENCE,
    CANVAS_EDGE_TYPE_STRUCTURE,
    CANVAS_NODE_TYPE_ASSET_TABLE,
    CANVAS_NODE_TYPE_IMAGE,
    CANVAS_NODE_TYPE_PROJECT_ROOT,
    CANVAS_NODE_TYPE_SCRIPT_EPISODE,
    CANVAS_NODE_TYPE_STORYBOARD_TABLE,
    CANVAS_NODE_TYPE_VIDEO,
)
from services.canvas_service import get_or_create_workspace


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _utc_now() -> datetime:
    return datetime.utcnow()


def _projection_key(node_type: str, domain_type: str, domain_id: int) -> str:
    return f"projection:{node_type}:{domain_type}:{domain_id}"


def _default_node_size(node_type: str) -> Tuple[float, float]:
    if node_type == CANVAS_NODE_TYPE_PROJECT_ROOT:
        return 300.0, 140.0
    if node_type == CANVAS_NODE_TYPE_SCRIPT_EPISODE:
        return 320.0, 180.0
    if node_type == CANVAS_NODE_TYPE_ASSET_TABLE:
        return 420.0, 320.0
    if node_type == CANVAS_NODE_TYPE_STORYBOARD_TABLE:
        return 460.0, 360.0
    return 320.0, 220.0


def _find_projection_node(session: Session, workspace_id: int, node_type: str, domain_type: str, domain_id: int) -> Optional[CanvasNode]:
    bootstrap_key = _projection_key(node_type, domain_type, domain_id)
    return session.exec(
        select(CanvasNode).where(CanvasNode.workspace_id == workspace_id, CanvasNode.bootstrap_key == bootstrap_key)
    ).first()


def _ensure_projection_node(
    session: Session,
    *,
    workspace_id: int,
    node_type: str,
    title: str,
    domain_type: str,
    domain_id: int,
    position_x: float,
    position_y: float,
    width: Optional[float] = None,
    height: Optional[float] = None,
    source_type: Optional[str] = None,
    source_id: Optional[int] = None,
    source_sub_id: Optional[int] = None,
    view_data: Optional[Dict[str, Any]] = None,
) -> CanvasNode:
    existing = _find_projection_node(session, workspace_id, node_type, domain_type, domain_id)
    if existing:
        existing.title = title or existing.title
        existing.domain_type = domain_type
        existing.domain_id = domain_id
        existing.source_type = source_type
        existing.source_id = source_id
        existing.source_sub_id = source_sub_id
        if view_data is not None and not str(existing.view_data_json or "").strip():
            existing.view_data_json = _json_dump(view_data)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    default_width, default_height = _default_node_size(node_type)
    item = CanvasNode(
        workspace_id=workspace_id,
        type=node_type,
        title=title,
        position_x=position_x,
        position_y=position_y,
        width=width if width is not None else default_width,
        height=height if height is not None else default_height,
        status="idle",
        source_type=source_type,
        source_id=source_id,
        source_sub_id=source_sub_id,
        bootstrap_key=_projection_key(node_type, domain_type, domain_id),
        sync_status="clean",
        domain_type=domain_type,
        domain_id=domain_id,
        collapsed=False,
        hidden=False,
        locked=False,
        revision=1,
        data_json="{}",
        context_json="{}",
        ai_config_json="{}",
        meta_json="{}",
        view_data_json=_json_dump(view_data or {}),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _find_edge(
    session: Session,
    *,
    workspace_id: int,
    source_node_id: int,
    target_node_id: int,
    edge_type: str,
    source_port_id: Optional[str],
    target_port_id: Optional[str],
) -> Optional[CanvasEdge]:
    statement = select(CanvasEdge).where(
        CanvasEdge.workspace_id == workspace_id,
        CanvasEdge.source_node_id == source_node_id,
        CanvasEdge.target_node_id == target_node_id,
        CanvasEdge.edge_type == edge_type,
    )
    if source_port_id is None:
        statement = statement.where(CanvasEdge.source_port_id == None)
    else:
        statement = statement.where(CanvasEdge.source_port_id == source_port_id)
    if target_port_id is None:
        statement = statement.where(CanvasEdge.target_port_id == None)
    else:
        statement = statement.where(CanvasEdge.target_port_id == target_port_id)
    return session.exec(statement).first()


def _ensure_edge(
    session: Session,
    *,
    workspace_id: int,
    source_node_id: int,
    target_node_id: int,
    edge_type: str,
    source_port_id: Optional[str] = None,
    target_port_id: Optional[str] = None,
    role: Optional[str] = None,
    domain_type: Optional[str] = None,
    domain_id: Optional[int] = None,
    is_projection: bool = True,
    label: Optional[str] = None,
    view_data: Optional[Dict[str, Any]] = None,
) -> CanvasEdge:
    existing = _find_edge(
        session,
        workspace_id=workspace_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type=edge_type,
        source_port_id=source_port_id,
        target_port_id=target_port_id,
    )
    if existing:
        existing.role = role or existing.role
        existing.domain_type = domain_type or existing.domain_type
        existing.domain_id = domain_id or existing.domain_id
        existing.is_projection = is_projection
        existing.label = label or existing.label
        if view_data is not None and not str(existing.view_data_json or "").strip():
            existing.view_data_json = _json_dump(view_data)
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    item = CanvasEdge(
        workspace_id=workspace_id,
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        edge_type=edge_type,
        source_port_id=source_port_id,
        target_port_id=target_port_id,
        role=role,
        domain_type=domain_type,
        domain_id=domain_id,
        is_projection=is_projection,
        hidden=False,
        mapping_json="[]",
        label=label,
        view_data_json=_json_dump(view_data or {}),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def ensure_project_projection(session: Session, script_id: int) -> CanvasNode:
    script = session.get(Script, script_id)
    if not script:
        raise ValueError("script not found")
    workspace = get_or_create_workspace(session, script)
    return _ensure_projection_node(
        session,
        workspace_id=workspace.id,
        node_type=CANVAS_NODE_TYPE_PROJECT_ROOT,
        title=script.name or "项目",
        domain_type="project",
        domain_id=script.id,
        position_x=0.0,
        position_y=0.0,
        source_type="script",
        source_id=script.id,
        view_data={"columnWidths": {}, "collapsedGroups": []},
    )


def ensure_episode_projection(session: Session, script_id: int, episode_id: int) -> CanvasNode:
    script = session.get(Script, script_id)
    episode = session.get(Episode, episode_id)
    if not script or not episode or episode.script_id != script.id:
        raise ValueError("episode not found")
    workspace = get_or_create_workspace(session, script)
    root_node = ensure_project_projection(session, script.id)
    episode_y = float(int(episode.sequence_num or 1) * 260)
    episode_node = _ensure_projection_node(
        session,
        workspace_id=workspace.id,
        node_type=CANVAS_NODE_TYPE_SCRIPT_EPISODE,
        title=episode.title or f"第 {episode.sequence_num} 集",
        domain_type="episode",
        domain_id=episode.id,
        position_x=360.0,
        position_y=episode_y,
        source_type="episode",
        source_id=episode.id,
    )
    _ensure_edge(
        session,
        workspace_id=workspace.id,
        source_node_id=root_node.id,
        target_node_id=episode_node.id,
        edge_type=CANVAS_EDGE_TYPE_STRUCTURE,
        domain_type="episode",
        domain_id=episode.id,
        label="结构",
    )

    episodes = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc(), Episode.id.asc())).all()
    previous_node: Optional[CanvasNode] = None
    for item in episodes:
        current_node = _ensure_projection_node(
            session,
            workspace_id=workspace.id,
            node_type=CANVAS_NODE_TYPE_SCRIPT_EPISODE,
            title=item.title or f"第 {item.sequence_num} 集",
            domain_type="episode",
            domain_id=item.id,
            position_x=360.0,
            position_y=float(int(item.sequence_num or 1) * 260),
            source_type="episode",
            source_id=item.id,
        )
        if previous_node is not None:
            _ensure_edge(
                session,
                workspace_id=workspace.id,
                source_node_id=previous_node.id,
                target_node_id=current_node.id,
                edge_type=CANVAS_EDGE_TYPE_SEQUENCE,
                domain_type="episode",
                domain_id=current_node.domain_id or item.id,
                label="顺序",
            )
        previous_node = current_node
    return episode_node


def ensure_asset_table_projection(session: Session, script_id: int, episode_id: int) -> CanvasNode:
    script = session.get(Script, script_id)
    episode = session.get(Episode, episode_id)
    if not script or not episode or episode.script_id != script.id:
        raise ValueError("episode not found")
    workspace = get_or_create_workspace(session, script)
    episode_node = ensure_episode_projection(session, script.id, episode.id)
    episode_y = float(int(episode.sequence_num or 1) * 260)
    asset_node = _ensure_projection_node(
        session,
        workspace_id=workspace.id,
        node_type=CANVAS_NODE_TYPE_ASSET_TABLE,
        title=f"{episode.title or '当前集'} · 资产表",
        domain_type="episode",
        domain_id=episode.id,
        position_x=760.0,
        position_y=episode_y - 120.0,
        source_type="episode_assets",
        source_id=script.id,
        source_sub_id=episode.id,
        view_data={"columnWidths": {}, "collapsedGroups": []},
    )
    _ensure_edge(
        session,
        workspace_id=workspace.id,
        source_node_id=episode_node.id,
        target_node_id=asset_node.id,
        edge_type=CANVAS_EDGE_TYPE_STRUCTURE,
        domain_type="episode",
        domain_id=episode.id,
        label="资产表",
    )
    return asset_node


def ensure_storyboard_table_projection(session: Session, script_id: int, episode_id: int) -> CanvasNode:
    script = session.get(Script, script_id)
    episode = session.get(Episode, episode_id)
    if not script or not episode or episode.script_id != script.id:
        raise ValueError("episode not found")
    workspace = get_or_create_workspace(session, script)
    episode_node = ensure_episode_projection(session, script.id, episode.id)
    episode_y = float(int(episode.sequence_num or 1) * 260)
    storyboard_node = _ensure_projection_node(
        session,
        workspace_id=workspace.id,
        node_type=CANVAS_NODE_TYPE_STORYBOARD_TABLE,
        title=f"{episode.title or '当前集'} · 分镜表",
        domain_type="episode",
        domain_id=episode.id,
        position_x=760.0,
        position_y=episode_y + 180.0,
        source_type="episode_storyboard",
        source_id=episode.id,
        view_data={"columnWidths": {}, "collapsedGroups": []},
    )
    _ensure_edge(
        session,
        workspace_id=workspace.id,
        source_node_id=episode_node.id,
        target_node_id=storyboard_node.id,
        edge_type=CANVAS_EDGE_TYPE_STRUCTURE,
        domain_type="episode",
        domain_id=episode.id,
        label="分镜表",
    )
    return storyboard_node


def _resolve_asset_projection_anchor(session: Session, script_id: int, owner_id: int) -> Tuple[CanvasNode, int]:
    link = session.exec(
        select(EpisodeAssetLink)
        .where(EpisodeAssetLink.script_id == script_id, EpisodeAssetLink.resource_id == owner_id)
        .order_by(EpisodeAssetLink.episode_id.asc(), EpisodeAssetLink.sort_order.asc(), EpisodeAssetLink.id.asc())
    ).first()
    if link:
        return ensure_asset_table_projection(session, script_id, link.episode_id), int(link.sort_order or 1)
    episode = session.exec(select(Episode).where(Episode.script_id == script_id).order_by(Episode.sequence_num.asc(), Episode.id.asc())).first()
    if not episode:
        raise ValueError("script has no episode")
    return ensure_asset_table_projection(session, script_id, episode.id), 1


def _resolve_storyboard_projection_anchor(session: Session, script_id: int, owner_id: int) -> Tuple[CanvasNode, Panel]:
    panel = session.get(Panel, owner_id)
    if not panel:
        raise ValueError("panel not found")
    episode = session.get(Episode, panel.episode_id)
    if not episode or episode.script_id != script_id:
        raise ValueError("panel not found")
    return ensure_storyboard_table_projection(session, script_id, episode.id), panel


def ensure_generation_unit_projection(session: Session, script_id: int, unit_id: int) -> CanvasNode:
    unit = session.get(GenerationUnit, unit_id)
    script = session.get(Script, script_id)
    if not unit or not script or unit.script_id != script.id:
        raise ValueError("generation unit not found")
    workspace = get_or_create_workspace(session, script)

    if unit.unit_type == "image":
        node_type = CANVAS_NODE_TYPE_IMAGE
    elif unit.unit_type == "video":
        node_type = CANVAS_NODE_TYPE_VIDEO
    else:
        node_type = unit.unit_type

    position_x = 1200.0 if unit.unit_type == "image" else 1600.0
    position_y = 360.0
    source_node: Optional[CanvasNode] = None
    source_port_id: Optional[str] = None
    target_port_id = f"{unit.unit_type}:{unit.id}:main-in"

    if unit.owner_type == "asset" and unit.owner_id:
        asset_node, row_index = _resolve_asset_projection_anchor(session, script.id, unit.owner_id)
        source_node = asset_node
        position_x = 1200.0
        position_y = float(asset_node.position_y or 0.0) + (max(row_index, 1) - 1) * 180.0
        source_port_id = f"asset-row:{unit.owner_id}:image-out"
    elif unit.owner_type == "storyboard_shot" and unit.owner_id:
        storyboard_node, panel = _resolve_storyboard_projection_anchor(session, script.id, unit.owner_id)
        source_node = storyboard_node
        position_x = 1200.0 if unit.unit_type == "image" else 1600.0
        position_y = float(storyboard_node.position_y or 0.0) + max(int(panel.sequence_num or 1) - 1, 0) * 220.0
        source_port_id = f"shot-row:{panel.id}:{'image-out' if unit.unit_type == 'image' else 'video-out'}"

    node = _ensure_projection_node(
        session,
        workspace_id=workspace.id,
        node_type=node_type,
        title=unit.name or f"{unit.unit_type} 节点",
        domain_type="generation_unit",
        domain_id=unit.id,
        position_x=position_x,
        position_y=position_y,
        source_type="generation_unit",
        source_id=unit.id,
        source_sub_id=unit.owner_id,
        view_data={"columnWidths": {}, "collapsedGroups": []},
    )
    if source_node is not None:
        _ensure_edge(
            session,
            workspace_id=workspace.id,
            source_node_id=source_node.id,
            target_node_id=node.id,
            edge_type=CANVAS_EDGE_TYPE_GENERATION,
            source_port_id=source_port_id,
            target_port_id=target_port_id,
            domain_type="generation_unit",
            domain_id=unit.id,
            label="生成",
        )
    return node


def ensure_generation_input_edge(session: Session, script_id: int, input_id: int) -> CanvasEdge:
    item = session.get(GenerationUnitInput, input_id)
    script = session.get(Script, script_id)
    if not item or not script or item.script_id != script.id:
        raise ValueError("generation input not found")
    if not item.source_unit_id:
        raise ValueError("source unit is required")
    workspace = get_or_create_workspace(session, script)
    source_node = ensure_generation_unit_projection(session, script.id, item.source_unit_id)
    target_node = ensure_generation_unit_projection(session, script.id, item.target_unit_id)
    return _ensure_edge(
        session,
        workspace_id=workspace.id,
        source_node_id=source_node.id,
        target_node_id=target_node.id,
        edge_type=CANVAS_EDGE_TYPE_REFERENCE,
        source_port_id=f"{source_node.type}:{item.source_unit_id}:ref-out",
        target_port_id=f"{target_node.type}:{item.target_unit_id}:ref-in",
        role=item.role or None,
        domain_type="generation_unit_input",
        domain_id=item.id,
        label=item.role or "参考",
    )


def rebuild_project_projection(session: Session, script_id: int) -> None:
    script = session.get(Script, script_id)
    if not script:
        raise ValueError("script not found")
    workspace = get_or_create_workspace(session, script)
    ensure_project_projection(session, script.id)
    episodes = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc(), Episode.id.asc())).all()
    for episode in episodes:
        ensure_episode_projection(session, script.id, episode.id)
        ensure_asset_table_projection(session, script.id, episode.id)
        ensure_storyboard_table_projection(session, script.id, episode.id)
    units = session.exec(select(GenerationUnit).where(GenerationUnit.script_id == script.id).order_by(GenerationUnit.created_at.asc(), GenerationUnit.id.asc())).all()
    for unit in units:
        ensure_generation_unit_projection(session, script.id, unit.id)
    inputs = session.exec(select(GenerationUnitInput).where(GenerationUnitInput.script_id == script.id).order_by(GenerationUnitInput.created_at.asc(), GenerationUnitInput.id.asc())).all()
    for item in inputs:
        if item.source_unit_id:
            ensure_generation_input_edge(session, script.id, item.id)
    valid_episode_ids = {item.id for item in episodes}
    valid_unit_ids = {item.id for item in units}
    for node in session.exec(select(CanvasNode).where(CanvasNode.workspace_id == workspace.id)).all():
        should_hide = False
        if node.type == CANVAS_NODE_TYPE_SCRIPT_EPISODE and node.domain_id not in valid_episode_ids:
            should_hide = True
        elif node.type in {CANVAS_NODE_TYPE_ASSET_TABLE, CANVAS_NODE_TYPE_STORYBOARD_TABLE} and node.domain_id not in valid_episode_ids:
            should_hide = True
        elif node.domain_type == "generation_unit" and node.domain_id not in valid_unit_ids:
            should_hide = True
        if should_hide and not node.hidden:
            node.hidden = True
            node.updated_at = _utc_now()
            node.revision = int(node.revision or 1) + 1
            session.add(node)
    session.commit()
