from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from core.security import decode_id
from database import get_session
from dependencies import get_current_team, get_current_user, require_team_permission
from models import Team, TeamMemberLink, User
from schemas import CanvasEdgeCreateRequest, CanvasEdgeUpdateRequest, CanvasNodeActionRequest, CanvasNodeCreateRequest, CanvasNodeSyncRequest, CanvasNodeUpdateRequest, CanvasWorkspacePatchRequest
from services.access_service import require_script_team_access
from services.canvas_action_service import run_canvas_node_action
from services.canvas_service import (
    archive_canvas_node,
    bootstrap_workspace,
    create_bootstrap_workspace,
    create_canvas_edge,
    create_canvas_node,
    delete_canvas_edge,
    delete_canvas_node,
    find_workspace_nodes_by_type,
    get_workspace_by_script_id,
    list_workspace_edges,
    list_workspace_nodes,
    push_node_to_source,
    reconcile_workspace,
    refresh_node_from_source,
    require_canvas_edge,
    require_canvas_node,
    require_workspace,
    serialize_canvas_edge,
    serialize_canvas_node,
    serialize_workspace,
    update_canvas_edge,
    update_canvas_node,
)

router = APIRouter()


def _workspace_bundle(session: Session, workspace_id: int) -> dict:
    workspace = require_workspace(session, workspace_id)
    return {
        "workspace": serialize_workspace(workspace),
        "nodes": [serialize_canvas_node(node) for node in list_workspace_nodes(session, workspace.id)],
        "edges": [serialize_canvas_edge(edge) for edge in list_workspace_edges(session, workspace.id)],
    }


@router.get("/api/canvas/scripts/{script_id}/workspace")
async def get_script_canvas_workspace(
    script_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = require_script_team_access(session, team, decode_id(script_id))
    workspace = get_workspace_by_script_id(session, script.id)
    if not workspace:
        return {"needs_bootstrap": True, "workspace": None, "nodes": [], "edges": []}
    return _workspace_bundle(session, workspace.id)


@router.post("/api/canvas/scripts/{script_id}/bootstrap")
async def post_script_canvas_bootstrap(
    script_id: str,
    episode_id: str | None = Query(default=None),
    focusPanelId: str | None = Query(default=None),
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = require_script_team_access(session, team, decode_id(script_id))
    workspace, summary = create_bootstrap_workspace(
        session,
        script,
        preferred_episode_id=decode_id(episode_id) if episode_id else None,
        focus_panel_id=decode_id(focusPanelId) if focusPanelId else None,
    )
    bundle = _workspace_bundle(session, workspace.id)
    bundle["summary"] = summary
    bundle["needs_bootstrap"] = False
    return bundle


@router.post("/api/canvas/workspaces/{workspace_id}/reconcile")
async def post_canvas_reconcile(
    workspace_id: str,
    focusPanelId: str | None = Query(default=None),
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    workspace = require_workspace(session, decode_id(workspace_id))
    script = require_script_team_access(session, team, workspace.script_id)
    summary = reconcile_workspace(session, workspace, script, focus_panel_id=decode_id(focusPanelId) if focusPanelId else None)
    return {"summary": summary, **_workspace_bundle(session, workspace.id)}


@router.patch("/api/canvas/workspaces/{workspace_id}")
async def patch_canvas_workspace(
    workspace_id: str,
    payload: CanvasWorkspacePatchRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    workspace = require_workspace(session, decode_id(workspace_id))
    require_script_team_access(session, team, workspace.script_id)
    if payload.title is not None:
        workspace.title = payload.title or workspace.title
    if payload.description is not None:
        workspace.description = payload.description or ""
    if payload.viewport is not None:
        workspace.viewport_json = json.dumps(payload.viewport.model_dump(), ensure_ascii=False)
    session.add(workspace)
    session.commit()
    session.refresh(workspace)
    return {"workspace": serialize_workspace(workspace)}


@router.post("/api/canvas/workspaces/{workspace_id}/nodes")
async def post_canvas_node(
    workspace_id: str,
    payload: CanvasNodeCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    workspace = require_workspace(session, decode_id(workspace_id))
    require_script_team_access(session, team, workspace.script_id)
    return {"node": serialize_canvas_node(create_canvas_node(session, workspace, payload))}


@router.patch("/api/canvas/nodes/{node_id}")
async def patch_canvas_node(
    node_id: str,
    payload: CanvasNodeUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    node = require_canvas_node(session, decode_id(node_id))
    workspace = require_workspace(session, node.workspace_id)
    require_script_team_access(session, team, workspace.script_id)
    return {"node": serialize_canvas_node(update_canvas_node(session, node, payload))}


@router.delete("/api/canvas/nodes/{node_id}")
async def remove_canvas_node(
    node_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    node = require_canvas_node(session, decode_id(node_id))
    workspace = require_workspace(session, node.workspace_id)
    require_script_team_access(session, team, workspace.script_id)
    delete_canvas_node(session, node)
    return {"status": "success", "deleted_node_id": node_id}


@router.post("/api/canvas/nodes/{node_id}/archive")
async def post_canvas_archive(
    node_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    node = require_canvas_node(session, decode_id(node_id))
    workspace = require_workspace(session, node.workspace_id)
    require_script_team_access(session, team, workspace.script_id)
    return {"node": serialize_canvas_node(archive_canvas_node(session, node))}


@router.post("/api/canvas/workspaces/{workspace_id}/edges")
async def post_canvas_edge(
    workspace_id: str,
    payload: CanvasEdgeCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    workspace = require_workspace(session, decode_id(workspace_id))
    require_script_team_access(session, team, workspace.script_id)
    return {"edge": serialize_canvas_edge(create_canvas_edge(session, workspace, payload))}


@router.patch("/api/canvas/edges/{edge_id}")
async def patch_canvas_edge(
    edge_id: str,
    payload: CanvasEdgeUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    edge = require_canvas_edge(session, decode_id(edge_id))
    workspace = require_workspace(session, edge.workspace_id)
    require_script_team_access(session, team, workspace.script_id)
    return {"edge": serialize_canvas_edge(update_canvas_edge(session, edge, payload))}


@router.delete("/api/canvas/edges/{edge_id}")
async def remove_canvas_edge(
    edge_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    edge = require_canvas_edge(session, decode_id(edge_id))
    workspace = require_workspace(session, edge.workspace_id)
    require_script_team_access(session, team, workspace.script_id)
    delete_canvas_edge(session, edge)
    return {"status": "success", "deleted_edge_id": edge_id}


@router.post("/api/canvas/nodes/{node_id}/refresh-from-source")
async def post_refresh_from_source(
    node_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    node = require_canvas_node(session, decode_id(node_id))
    workspace = require_workspace(session, node.workspace_id)
    require_script_team_access(session, team, workspace.script_id)
    return {"node": serialize_canvas_node(refresh_node_from_source(session, workspace, node))}


@router.post("/api/canvas/nodes/{node_id}/push-to-source")
async def post_push_to_source(
    node_id: str,
    request: CanvasNodeSyncRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    node = require_canvas_node(session, decode_id(node_id))
    workspace = require_workspace(session, node.workspace_id)
    require_script_team_access(session, team, workspace.script_id)
    if request.payload:
        node = update_canvas_node(session, node, CanvasNodeUpdateRequest(data=request.payload, sync_status="dirty_local"))
    return {"node": serialize_canvas_node(push_node_to_source(session, workspace, node, team, user))}


@router.post("/api/canvas/nodes/{node_id}/actions/{action_name}")
async def run_node_action(
    node_id: str,
    action_name: str,
    request: CanvasNodeActionRequest,
    member_link: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    node = require_canvas_node(session, decode_id(node_id))
    workspace = require_workspace(session, node.workspace_id)
    require_script_team_access(session, team, workspace.script_id)
    result = await run_canvas_node_action(session, workspace=workspace, node=node, action_name=action_name, payload=request.payload or {}, team=team, member_link=member_link, user=user)
    refreshed_node = require_canvas_node(session, decode_id(node_id))
    return {
        "status": result.get("status") or "success",
        "node": serialize_canvas_node(refreshed_node),
        "updated_nodes": [serialize_canvas_node(item) for item in result.get("updated_nodes", []) if getattr(item, "archived_at", None) is None],
        "suggested_actions": result.get("suggested_actions", []),
    }
