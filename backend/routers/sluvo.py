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
    SluvoAgentTemplateCreateRequest,
    SluvoAgentTemplateUpdateRequest,
    SluvoCanvasAssetBase64UploadRequest,
    SluvoCanvasBatchRequest,
    SluvoCommunityAgentPublishRequest,
    SluvoCommunityCanvasPublishRequest,
    SluvoCanvasEdgeCreateRequest,
    SluvoCanvasEdgeUpdateRequest,
    SluvoCanvasNodeCreateRequest,
    SluvoCanvasNodeUpdateRequest,
    SluvoCanvasPatchRequest,
    SluvoProjectCreateRequest,
    SluvoProjectMemberCreateRequest,
    SluvoProjectMemberUpdateRequest,
    SluvoProjectUpdateRequest,
    SluvoTextNodeAnalyzeRequest,
)
from services.sluvo_service import (
    SLUVO_PERMISSION_AGENT,
    SLUVO_PERMISSION_MANAGE,
    SLUVO_PERMISSION_READ,
    SLUVO_PERMISSION_WRITE,
    add_sluvo_project_member,
    analyze_sluvo_text_node,
    append_sluvo_agent_event,
    apply_sluvo_canvas_batch,
    approve_sluvo_agent_action,
    cancel_sluvo_agent_action,
    canvas_bundle,
    create_sluvo_agent_action,
    create_sluvo_agent_session,
    create_sluvo_agent_template,
    create_sluvo_canvas_asset_upload,
    create_sluvo_edge,
    create_sluvo_node,
    create_sluvo_project,
    delete_sluvo_agent_template,
    fork_sluvo_community_agent,
    fork_sluvo_community_canvas,
    get_sluvo_community_agent_detail,
    get_or_create_main_canvas,
    get_sluvo_community_canvas_detail,
    get_sluvo_project_community_publication,
    get_sluvo_project_first_image_url,
    get_sluvo_project_bundle,
    list_sluvo_agent_templates,
    list_sluvo_community_agents,
    list_sluvo_community_canvases,
    list_sluvo_project_agent_sessions,
    list_sluvo_project_members,
    list_sluvo_projects,
    process_sluvo_agent_message,
    publish_sluvo_agent_to_community,
    publish_sluvo_project_to_community,
    permanently_delete_sluvo_project,
    remove_sluvo_project_member,
    require_sluvo_agent_template,
    require_sluvo_community_agent,
    require_sluvo_community_canvas,
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
    restore_sluvo_project,
    unpublish_sluvo_community_agent,
    unpublish_sluvo_community_canvas,
    update_sluvo_agent_template,
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
    include_deleted: bool = False,
):
    return require_sluvo_project_access(
        session,
        user=user,
        team=team,
        team_member=team_member,
        project_id=decode_id(project_id),
        permission=permission,
        include_deleted=include_deleted,
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
    includeDeleted: bool = False,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    return {"items": list_sluvo_projects(session, user=user, team=team, team_member=team_member, include_archived=includeArchived, include_deleted=includeDeleted)}


@router.get("/api/sluvo/community/canvases")
async def get_sluvo_community_canvases(
    limit: int = 24,
    sort: str = "latest",
    session: Session = Depends(get_session),
):
    return {"items": list_sluvo_community_canvases(session, limit=limit, sort=sort)}


@router.get("/api/sluvo/community/agents")
async def get_sluvo_community_agents(
    limit: int = 24,
    sort: str = "latest",
    session: Session = Depends(get_session),
):
    return {"items": list_sluvo_community_agents(session, limit=limit, sort=sort)}


@router.get("/api/sluvo/community/agents/{publication_id}")
async def get_sluvo_community_agent(
    publication_id: str,
    _: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    publication = require_sluvo_community_agent(session, publication_id)
    return get_sluvo_community_agent_detail(session, publication)


@router.post("/api/sluvo/community/agents/{publication_id}/fork")
async def post_sluvo_community_agent_fork(
    publication_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    publication = require_sluvo_community_agent(session, publication_id)
    return fork_sluvo_community_agent(session, item=publication, user=user, team=team)


@router.post("/api/sluvo/community/agents/{publication_id}/unpublish")
async def post_sluvo_community_agent_unpublish(
    publication_id: str,
    user: User = Depends(get_current_user),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    publication = require_sluvo_community_agent(session, publication_id, include_unpublished=True)
    return unpublish_sluvo_community_agent(session, item=publication, user=user, team_member=team_member)


@router.get("/api/sluvo/community/canvases/{publication_id}")
async def get_sluvo_community_canvas(
    publication_id: str,
    _: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    publication = require_sluvo_community_canvas(session, publication_id)
    return get_sluvo_community_canvas_detail(session, publication)


@router.post("/api/sluvo/community/canvases/{publication_id}/fork")
async def post_sluvo_community_canvas_fork(
    publication_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    publication = require_sluvo_community_canvas(session, publication_id)
    return fork_sluvo_community_canvas(session, item=publication, user=user, team=team)


@router.post("/api/sluvo/community/canvases/{publication_id}/unpublish")
async def post_sluvo_community_canvas_unpublish(
    publication_id: str,
    user: User = Depends(get_current_user),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    publication = require_sluvo_community_canvas(session, publication_id, include_unpublished=True)
    return unpublish_sluvo_community_canvas(session, item=publication, user=user, team_member=team_member)


@router.get("/api/sluvo/agents")
async def get_sluvo_agents(
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    return {"items": list_sluvo_agent_templates(session, user=user, team=team)}


@router.post("/api/sluvo/agents")
async def post_sluvo_agent(
    payload: SluvoAgentTemplateCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    return {"agent": serialize_sluvo_agent_template(create_sluvo_agent_template(session, user=user, team=team, payload=payload))}


@router.get("/api/sluvo/agents/{agent_id}")
async def get_sluvo_agent(
    agent_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    item = require_sluvo_agent_template(session, agent_id)
    if item.owner_user_id != user.id or item.team_id != team.id:
        raise HTTPException(status_code=403, detail="无权访问当前 Agent")
    return {"agent": serialize_sluvo_agent_template(item)}


@router.patch("/api/sluvo/agents/{agent_id}")
async def patch_sluvo_agent(
    agent_id: str,
    payload: SluvoAgentTemplateUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    item = require_sluvo_agent_template(session, agent_id)
    if item.owner_user_id != user.id or item.team_id != team.id:
        raise HTTPException(status_code=403, detail="无权修改当前 Agent")
    return {"agent": serialize_sluvo_agent_template(update_sluvo_agent_template(session, item=item, payload=payload))}


@router.delete("/api/sluvo/agents/{agent_id}")
async def delete_sluvo_agent(
    agent_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    item = require_sluvo_agent_template(session, agent_id)
    if item.owner_user_id != user.id or item.team_id != team.id:
        raise HTTPException(status_code=403, detail="无权删除当前 Agent")
    delete_sluvo_agent_template(session, item=item)
    return {"status": "success", "deletedAgentId": agent_id}


@router.post("/api/sluvo/agents/{agent_id}/community/publish")
async def post_sluvo_agent_community_publish(
    agent_id: str,
    payload: SluvoCommunityAgentPublishRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    item = require_sluvo_agent_template(session, agent_id)
    if item.owner_user_id != user.id or item.team_id != team.id:
        raise HTTPException(status_code=403, detail="无权发布当前 Agent")
    return publish_sluvo_agent_to_community(session, item=item, user=user, team=team, payload=payload)


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


@router.post("/api/sluvo/projects/{project_id}/community/publish")
async def post_sluvo_project_community_publish(
    project_id: str,
    payload: SluvoCommunityCanvasPublishRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
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
        permission=SLUVO_PERMISSION_WRITE,
    )
    return publish_sluvo_project_to_community(session, project=project, user=user, team=team, payload=payload)


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
    first_image_url = get_sluvo_project_first_image_url(session, project.id)
    publication = get_sluvo_project_community_publication(session, project.id)
    return {"project": serialize_sluvo_project(project, member.role if member else None, first_image_url, publication)}


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


@router.post("/api/sluvo/projects/{project_id}/restore")
async def post_sluvo_project_restore(
    project_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
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
        permission=SLUVO_PERMISSION_MANAGE,
        include_deleted=True,
    )
    project = restore_sluvo_project(session, project)
    first_image_url = get_sluvo_project_first_image_url(session, project.id)
    publication = get_sluvo_project_community_publication(session, project.id)
    return {"project": serialize_sluvo_project(project, member.role if member else None, first_image_url, publication)}


@router.delete("/api/sluvo/projects/{project_id}/permanent")
async def delete_sluvo_project_permanent(
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
        include_deleted=True,
    )
    permanently_delete_sluvo_project(session, project)
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
    first_image_url = get_sluvo_project_first_image_url(session, project.id)
    publication = get_sluvo_project_community_publication(session, project.id)
    return {
        "project": serialize_sluvo_project(project, member.role if member else None, first_image_url, publication),
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
        model_code=payload.modelCode,
        mode=payload.mode,
        context_snapshot=payload.contextSnapshot,
    )
    return {"session": serialize_sluvo_agent_session(item)}


@router.get("/api/sluvo/projects/{project_id}/agent/sessions")
async def get_sluvo_project_agent_sessions(
    project_id: str,
    limit: int = 12,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    project, _ = _access_project(session, user=user, team=team, team_member=team_member, project_id=project_id, permission=SLUVO_PERMISSION_READ)
    return {"items": list_sluvo_project_agent_sessions(session, project=project, limit=limit)}


@router.post("/api/sluvo/projects/{project_id}/text-node/analyze")
async def post_sluvo_text_node_analyze(
    project_id: str,
    payload: SluvoTextNodeAnalyzeRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    team_member: TeamMemberLink = Depends(get_current_team_member),
    session: Session = Depends(get_session),
):
    _access_project(session, user=user, team=team, team_member=team_member, project_id=project_id, permission=SLUVO_PERMISSION_AGENT)
    return analyze_sluvo_text_node(payload)


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
    result = process_sluvo_agent_message(
        session,
        agent_session=item,
        content=payload.content,
        payload=payload.payload,
        turn_id=payload.turnId,
        proposed_action=payload.proposedAction,
    )
    return {
        "event": serialize_sluvo_agent_event(result["event"]),
        "agentEvent": serialize_sluvo_agent_event(result["agentEvent"]),
        "action": serialize_sluvo_agent_action(result["action"]) if result.get("action") else None,
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
    serialize_sluvo_agent_template,
