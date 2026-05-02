from __future__ import annotations

import base64
import binascii

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from core.security import decode_id, encode_id
from database import get_session
from dependencies import get_current_team, get_current_team_member, get_current_user, require_team_permission
from models import Team, TeamMemberLink, User
from schemas import (
    SluvoAgentMessageSendRequest,
    SluvoAgentSessionCreateRequest,
    SluvoCanvasAssetBase64UploadRequest,
    SluvoCanvasBatchRequest,
    SluvoCanvasEdgeCreateRequest,
    SluvoCanvasEdgeUpdateRequest,
    SluvoCanvasNodeCreateRequest,
    SluvoCanvasNodeUpdateRequest,
    SluvoCanvasPatchRequest,
    SluvoProjectCreateRequest,
    SluvoProjectMemberCreateRequest,
    SluvoProjectMemberUpdateRequest,
    SluvoProjectUpdateRequest,
)
from services.sluvo_service import (
    SLUVO_PERMISSION_AGENT,
    SLUVO_PERMISSION_MANAGE,
    SLUVO_PERMISSION_READ,
    SLUVO_PERMISSION_WRITE,
    add_sluvo_project_member,
    append_sluvo_agent_event,
    apply_sluvo_canvas_batch,
    approve_sluvo_agent_action,
    cancel_sluvo_agent_action,
    canvas_bundle,
    create_sluvo_agent_action,
    create_sluvo_agent_session,
    create_sluvo_canvas_asset_upload,
    create_sluvo_edge,
    create_sluvo_node,
    create_sluvo_project,
    get_or_create_main_canvas,
    get_sluvo_project_bundle,
    list_sluvo_project_members,
    list_sluvo_projects,
    remove_sluvo_project_member,
    require_sluvo_agent_action,
    require_sluvo_agent_session,
    require_sluvo_project_access,
    serialize_sluvo_agent_action,
    serialize_sluvo_agent_event,
    serialize_sluvo_agent_session,
    serialize_sluvo_edge,
    serialize_sluvo_member,
    serialize_sluvo_node,
    serialize_sluvo_project,
    soft_delete_sluvo_project,
    update_sluvo_canvas,
    update_sluvo_edge,
    update_sluvo_node,
    update_sluvo_project,
    update_sluvo_project_member,
)
from services.sluvo_service import _require_canvas, _require_edge, _require_node

router = APIRouter()


def _access_project(
    session: Session,
    *,
    user: User,
    team: Team,
    team_member: TeamMemberLink,
    project_id: str,
    permission: str,
):
    return require_sluvo_project_access(
        session,
        user=user,
        team=team,
        team_member=team_member,
        project_id=decode_id(project_id),
        permission=permission,
    )


def _access_canvas_project(
    session: Session,
    *,
    user: User,
    team: Team,
    team_member: TeamMemberLink,
    canvas,
    permission: str,
):
    return _access_project(
        session,
        user=user,
        team=team,
        team_member=team_member,
        project_id=encode_id(canvas.project_id),
        permission=permission,
    )


@router.post("/api/sluvo/projects")
async def post_sluvo_project(
    payload: SluvoProjectCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    return create_sluvo_project(session, user=user, team=team, payload=payload)


@router.get("/api/sluvo/projects")
async def get_sluvo_projects(
    includeArchived: bool = False,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    return {"items": list_sluvo_projects(session, user=user, team=team, team_member=team_member, include_archived=includeArchived)}


@router.get("/api/sluvo/projects/{project_id}")
async def get_sluvo_project(
    project_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, member = _access_project(
        session,
        user=user,
        team=team,
        team_member=team_member,
        project_id=project_id,
        permission=SLUVO_PERMISSION_READ,
    )
    return get_sluvo_project_bundle(session, project, member)


@router.patch("/api/sluvo/projects/{project_id}")
async def patch_sluvo_project(
    project_id: str,
    payload: SluvoProjectUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, member = _access_project(
        session,
        user=user,
        team=team,
        team_member=team_member,
        project_id=project_id,
        permission=SLUVO_PERMISSION_WRITE,
    )
    project = update_sluvo_project(session, project, payload)
    return {"project": serialize_sluvo_project(project, member.role if member else None)}


@router.delete("/api/sluvo/projects/{project_id}")
async def delete_sluvo_project(
    project_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, _ = _access_project(
        session,
        user=user,
        team=team,
        team_member=team_member,
        project_id=project_id,
        permission=SLUVO_PERMISSION_MANAGE,
    )
    soft_delete_sluvo_project(session, project)
    return {"status": "success", "deletedProjectId": project_id}


@router.get("/api/sluvo/projects/{project_id}/canvas")
async def get_sluvo_project_canvas(
    project_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, member = _access_project(
        session,
        user=user,
        team=team,
        team_member=team_member,
        project_id=project_id,
        permission=SLUVO_PERMISSION_READ,
    )
    canvas = get_or_create_main_canvas(session, project)
    return {
        "project": serialize_sluvo_project(project, member.role if member else None),
        **canvas_bundle(session, canvas),
    }


@router.patch("/api/sluvo/canvases/{canvas_id}")
async def patch_sluvo_canvas(
    canvas_id: str,
    payload: SluvoCanvasPatchRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    canvas = _require_canvas(session, decode_id(canvas_id))
    _access_canvas_project(
        session,
        user=user,
        team=team,
        team_member=team_member,
        canvas=canvas,
        permission=SLUVO_PERMISSION_WRITE,
    )
    return update_sluvo_canvas(session, canvas, payload, user=user)


@router.post("/api/sluvo/canvases/{canvas_id}/nodes")
async def post_sluvo_canvas_node(
    canvas_id: str,
    payload: SluvoCanvasNodeCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    canvas = _require_canvas(session, decode_id(canvas_id))
    _access_canvas_project(session, user=user, team=team, team_member=team_member, canvas=canvas, permission=SLUVO_PERMISSION_WRITE)
    node = create_sluvo_node(session, canvas, payload, user=user)
    return {"node": serialize_sluvo_node(node)}


@router.patch("/api/sluvo/canvases/{canvas_id}/nodes/{node_id}")
async def patch_sluvo_canvas_node(
    canvas_id: str,
    node_id: str,
    payload: SluvoCanvasNodeUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    canvas = _require_canvas(session, decode_id(canvas_id))
    _access_canvas_project(session, user=user, team=team, team_member=team_member, canvas=canvas, permission=SLUVO_PERMISSION_WRITE)
    node = _require_node(session, decode_id(node_id))
    return {"node": serialize_sluvo_node(update_sluvo_node(session, canvas, node, payload, user=user))}


@router.post("/api/sluvo/canvases/{canvas_id}/edges")
async def post_sluvo_canvas_edge(
    canvas_id: str,
    payload: SluvoCanvasEdgeCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    canvas = _require_canvas(session, decode_id(canvas_id))
    _access_canvas_project(session, user=user, team=team, team_member=team_member, canvas=canvas, permission=SLUVO_PERMISSION_WRITE)
    edge = create_sluvo_edge(session, canvas, payload)
    return {"edge": serialize_sluvo_edge(edge)}


@router.patch("/api/sluvo/canvases/{canvas_id}/edges/{edge_id}")
async def patch_sluvo_canvas_edge(
    canvas_id: str,
    edge_id: str,
    payload: SluvoCanvasEdgeUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    canvas = _require_canvas(session, decode_id(canvas_id))
    _access_canvas_project(session, user=user, team=team, team_member=team_member, canvas=canvas, permission=SLUVO_PERMISSION_WRITE)
    edge = _require_edge(session, decode_id(edge_id))
    return {"edge": serialize_sluvo_edge(update_sluvo_edge(session, canvas, edge, payload))}


@router.post("/api/sluvo/canvases/{canvas_id}/batch")
async def post_sluvo_canvas_batch(
    canvas_id: str,
    payload: SluvoCanvasBatchRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    canvas = _require_canvas(session, decode_id(canvas_id))
    _access_canvas_project(session, user=user, team=team, team_member=team_member, canvas=canvas, permission=SLUVO_PERMISSION_WRITE)
    return apply_sluvo_canvas_batch(session, canvas, payload, user=user)


@router.post("/api/sluvo/canvases/{canvas_id}/assets/upload")
async def post_sluvo_canvas_asset_upload(
    canvas_id: str,
    file: UploadFile = File(...),
    mediaType: str | None = Form(default=None),
    nodeId: str | None = Form(default=None),
    width: int | None = Form(default=None),
    height: int | None = Form(default=None),
    durationSeconds: float | None = Form(default=None),
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    canvas = _require_canvas(session, decode_id(canvas_id))
    _access_canvas_project(session, user=user, team=team, team_member=team_member, canvas=canvas, permission=SLUVO_PERMISSION_WRITE)
    content = await file.read()
    return create_sluvo_canvas_asset_upload(
        session,
        canvas=canvas,
        user=user,
        content=content,
        filename=str(file.filename or "upload.bin"),
        content_type=str(file.content_type or "application/octet-stream"),
        media_type=mediaType,
        node_id=nodeId,
        width=width,
        height=height,
        duration_seconds=durationSeconds,
        metadata={"uploadMode": "multipart"},
    )


@router.post("/api/sluvo/canvases/{canvas_id}/assets/upload/base64")
async def post_sluvo_canvas_asset_upload_base64(
    canvas_id: str,
    payload: SluvoCanvasAssetBase64UploadRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    canvas = _require_canvas(session, decode_id(canvas_id))
    _access_canvas_project(session, user=user, team=team, team_member=team_member, canvas=canvas, permission=SLUVO_PERMISSION_WRITE)
    raw = str(payload.dataBase64 or "").strip()
    if "," in raw:
        raw = raw.split(",", 1)[1]
    try:
        content = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(status_code=400, detail="上传文件内容无法解析")
    return create_sluvo_canvas_asset_upload(
        session,
        canvas=canvas,
        user=user,
        content=content,
        filename=payload.filename,
        content_type=payload.contentType,
        media_type=payload.mediaType,
        node_id=payload.nodeId,
        width=payload.width,
        height=payload.height,
        duration_seconds=payload.durationSeconds,
        metadata={**payload.metadata, "uploadMode": "base64"},
    )


@router.get("/api/sluvo/projects/{project_id}/members")
async def get_sluvo_members(
    project_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, _ = _access_project(session, user=user, team=team, team_member=team_member, project_id=project_id, permission=SLUVO_PERMISSION_READ)
    return {"items": list_sluvo_project_members(session, project)}


@router.post("/api/sluvo/projects/{project_id}/members")
async def post_sluvo_member(
    project_id: str,
    payload: SluvoProjectMemberCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, _ = _access_project(session, user=user, team=team, team_member=team_member, project_id=project_id, permission=SLUVO_PERMISSION_MANAGE)
    member = add_sluvo_project_member(session, project=project, inviter=user, payload=payload)
    return {"member": serialize_sluvo_member(session, member)}


@router.patch("/api/sluvo/projects/{project_id}/members/{user_id}")
async def patch_sluvo_member(
    project_id: str,
    user_id: str,
    payload: SluvoProjectMemberUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, _ = _access_project(session, user=user, team=team, team_member=team_member, project_id=project_id, permission=SLUVO_PERMISSION_MANAGE)
    member = update_sluvo_project_member(session, project=project, user_id=decode_id(user_id), payload=payload)
    return {"member": serialize_sluvo_member(session, member)}


@router.delete("/api/sluvo/projects/{project_id}/members/{user_id}")
async def delete_sluvo_member(
    project_id: str,
    user_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, _ = _access_project(session, user=user, team=team, team_member=team_member, project_id=project_id, permission=SLUVO_PERMISSION_MANAGE)
    remove_sluvo_project_member(session, project=project, user_id=decode_id(user_id))
    return {"status": "success", "deletedUserId": user_id}


@router.post("/api/sluvo/projects/{project_id}/agent/sessions")
async def post_sluvo_agent_session(
    project_id: str,
    payload: SluvoAgentSessionCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, _ = _access_project(session, user=user, team=team, team_member=team_member, project_id=project_id, permission=SLUVO_PERMISSION_AGENT)
    item = create_sluvo_agent_session(
        session,
        project=project,
        user=user,
        team=team,
        canvas_id=decode_id(payload.canvasId) if payload.canvasId else None,
        target_node_id=decode_id(payload.targetNodeId) if payload.targetNodeId else None,
        title=payload.title,
        agent_profile=payload.agentProfile,
        mode=payload.mode,
        context_snapshot=payload.contextSnapshot,
    )
    return {"session": serialize_sluvo_agent_session(item)}


@router.get("/api/sluvo/agent/sessions/{session_id}")
async def get_sluvo_agent_session(
    session_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    item = require_sluvo_agent_session(session, decode_id(session_id))
    _access_project(session, user=user, team=team, team_member=team_member, project_id=encode_id(item.project_id), permission=SLUVO_PERMISSION_READ)
    return {"session": serialize_sluvo_agent_session(item)}


@router.post("/api/sluvo/agent/sessions/{session_id}/messages")
async def post_sluvo_agent_message(
    session_id: str,
    payload: SluvoAgentMessageSendRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    item = require_sluvo_agent_session(session, decode_id(session_id))
    _access_project(session, user=user, team=team, team_member=team_member, project_id=encode_id(item.project_id), permission=SLUVO_PERMISSION_AGENT)
    event = append_sluvo_agent_event(
        session,
        agent_session=item,
        role="user",
        event_type="message",
        payload={"content": payload.content, **payload.payload},
        turn_id=payload.turnId,
    )
    action = create_sluvo_agent_action(session, agent_session=item, action_payload=payload.proposedAction) if payload.proposedAction else None
    return {
        "event": serialize_sluvo_agent_event(event),
        "action": serialize_sluvo_agent_action(action) if action else None,
    }


@router.post("/api/sluvo/agent/actions/{action_id}/approve")
async def approve_sluvo_action(
    action_id: str,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    action = require_sluvo_agent_action(session, decode_id(action_id))
    _access_project(session, user=user, team=team, team_member=team_member, project_id=encode_id(action.project_id), permission=SLUVO_PERMISSION_AGENT)
    return {"action": serialize_sluvo_agent_action(approve_sluvo_agent_action(session, action, user=user))}


@router.post("/api/sluvo/agent/actions/{action_id}/cancel")
async def cancel_sluvo_action(
    action_id: str,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    action = require_sluvo_agent_action(session, decode_id(action_id))
    _access_project(session, user=user, team=team, team_member=team_member, project_id=encode_id(action.project_id), permission=SLUVO_PERMISSION_AGENT)
    return {"action": serialize_sluvo_agent_action(cancel_sluvo_agent_action(session, action))}
