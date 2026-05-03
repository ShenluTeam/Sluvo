from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from core.security import decode_id, encode_id
from models import (
    RoleEnum,
    SluvoAgentAction,
    SluvoAgentEvent,
    SluvoAgentSession,
    SluvoCanvas,
    SluvoCanvasAsset,
    SluvoCanvasEdge,
    SluvoCanvasMutation,
    SluvoCanvasNode,
    SluvoProject,
    SluvoProjectMember,
    StorageObject,
    Team,
    TeamMemberLink,
    User,
)
from schemas import (
    SLUVO_MEMBER_ROLE_EDITOR,
    SLUVO_MEMBER_ROLE_OWNER,
    SLUVO_MEMBER_ROLE_VIEWER,
    SLUVO_PROJECT_STATUS_DELETED,
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
    normalize_sluvo_edge_type,
    normalize_sluvo_member_role,
    normalize_sluvo_node_type,
    normalize_sluvo_project_status,
    normalize_sluvo_project_visibility,
)

SLUVO_PERMISSION_READ = "read"
SLUVO_PERMISSION_WRITE = "write"
SLUVO_PERMISSION_MANAGE = "manage"
SLUVO_PERMISSION_AGENT = "agent"
SLUVO_UPLOAD_MAX_BYTES = 20 * 1024 * 1024

SLUVO_UPLOAD_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
    "video/mp4",
    "video/webm",
    "video/quicktime",
    "video/x-matroska",
    "audio/mpeg",
    "audio/mp3",
    "audio/wav",
    "audio/x-wav",
    "audio/mp4",
    "audio/aac",
    "audio/ogg",
    "audio/webm",
}

_ROLE_PERMISSIONS = {
    SLUVO_MEMBER_ROLE_OWNER: {SLUVO_PERMISSION_READ, SLUVO_PERMISSION_WRITE, SLUVO_PERMISSION_MANAGE, SLUVO_PERMISSION_AGENT},
    SLUVO_MEMBER_ROLE_EDITOR: {SLUVO_PERMISSION_READ, SLUVO_PERMISSION_WRITE, SLUVO_PERMISSION_AGENT},
    SLUVO_MEMBER_ROLE_VIEWER: {SLUVO_PERMISSION_READ},
}


def _has_team_manage_role(role: Any) -> bool:
    value = str(role.value if hasattr(role, "value") else role)
    return value == RoleEnum.ADMIN.value


def _utc_now() -> datetime:
    return datetime.utcnow()


def _json_dump(value: Any, fallback: Any = None) -> str:
    try:
        return json.dumps(value if value is not None else fallback, ensure_ascii=False)
    except Exception:
        return json.dumps(fallback if fallback is not None else {}, ensure_ascii=False)


def _json_load(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _upload_bytes_to_oss_with_meta(*args, **kwargs) -> Dict[str, Any]:
    from services.oss_service import upload_bytes_to_oss_with_meta

    return upload_bytes_to_oss_with_meta(*args, **kwargs)


def _decode_optional(value: Optional[str]) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    return decode_id(str(value))


def _require_active_project(session: Session, project_id: int) -> SluvoProject:
    project = session.get(SluvoProject, project_id)
    if not project or project.deleted_at is not None or project.status == SLUVO_PROJECT_STATUS_DELETED:
        raise HTTPException(status_code=404, detail="Sluvo 项目不存在")
    return project


def _require_canvas(session: Session, canvas_id: int) -> SluvoCanvas:
    canvas = session.get(SluvoCanvas, canvas_id)
    if not canvas:
        raise HTTPException(status_code=404, detail="Sluvo 画布不存在")
    return canvas


def _require_node(session: Session, node_id: int) -> SluvoCanvasNode:
    node = session.get(SluvoCanvasNode, node_id)
    if not node or node.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Sluvo 节点不存在")
    return node


def _require_edge(session: Session, edge_id: int) -> SluvoCanvasEdge:
    edge = session.get(SluvoCanvasEdge, edge_id)
    if not edge or edge.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Sluvo 连线不存在")
    return edge


def _check_revision(actual: int, expected: Optional[int], label: str) -> None:
    if expected is not None and int(actual or 0) != int(expected):
        raise HTTPException(status_code=409, detail=f"{label} revision 已过期，请刷新后重试")


def _assert_same_canvas(item_canvas_id: int, canvas_id: int, label: str) -> None:
    if int(item_canvas_id) != int(canvas_id):
        raise HTTPException(status_code=400, detail=f"{label} 不属于当前画布")


def get_sluvo_project_first_image_url(session: Session, project_id: int) -> Optional[str]:
    asset = session.exec(
        select(SluvoCanvasAsset)
        .where(
            SluvoCanvasAsset.project_id == project_id,
            SluvoCanvasAsset.deleted_at == None,
            SluvoCanvasAsset.media_type == "image",
        )
        .order_by(SluvoCanvasAsset.created_at.asc(), SluvoCanvasAsset.id.asc())
    ).first()
    if not asset:
        return None
    return asset.thumbnail_url or asset.url


def serialize_sluvo_project(
    project: SluvoProject,
    member_role: Optional[str] = None,
    first_image_url: Optional[str] = None,
) -> Dict[str, Any]:
    cover_url = first_image_url or project.cover_url
    return {
        "id": encode_id(project.id),
        "ownerUserId": encode_id(project.owner_user_id),
        "teamId": encode_id(project.team_id),
        "title": project.title,
        "description": project.description,
        "status": project.status,
        "visibility": project.visibility,
        "settings": _json_load(project.settings_json, {}),
        "coverUrl": cover_url,
        "firstImageUrl": first_image_url,
        "memberRole": member_role,
        "lastOpenedAt": project.last_opened_at.isoformat() if project.last_opened_at else None,
        "createdAt": project.created_at.isoformat() if project.created_at else None,
        "updatedAt": project.updated_at.isoformat() if project.updated_at else None,
    }


def serialize_sluvo_member(session: Session, member: SluvoProjectMember) -> Dict[str, Any]:
    user = session.get(User, member.user_id)
    return {
        "id": encode_id(member.id),
        "projectId": encode_id(member.project_id),
        "userId": encode_id(member.user_id),
        "nickname": user.nickname if user else "",
        "email": user.email if user else "",
        "role": member.role,
        "invitedByUserId": encode_id(member.invited_by_user_id) if member.invited_by_user_id else None,
        "createdAt": member.created_at.isoformat() if member.created_at else None,
        "updatedAt": member.updated_at.isoformat() if member.updated_at else None,
    }


def serialize_sluvo_canvas(canvas: SluvoCanvas) -> Dict[str, Any]:
    return {
        "id": encode_id(canvas.id),
        "projectId": encode_id(canvas.project_id),
        "canvasKey": canvas.canvas_key,
        "title": canvas.title,
        "viewport": _json_load(canvas.viewport_json, {}),
        "snapshot": _json_load(canvas.snapshot_json, {}),
        "schemaVersion": canvas.schema_version,
        "revision": canvas.revision,
        "createdAt": canvas.created_at.isoformat() if canvas.created_at else None,
        "updatedAt": canvas.updated_at.isoformat() if canvas.updated_at else None,
    }


def serialize_sluvo_node(node: SluvoCanvasNode) -> Dict[str, Any]:
    return {
        "id": encode_id(node.id),
        "canvasId": encode_id(node.canvas_id),
        "parentNodeId": encode_id(node.parent_node_id) if node.parent_node_id else None,
        "nodeType": node.node_type,
        "title": node.title,
        "position": {"x": node.position_x, "y": node.position_y},
        "size": {"width": node.width, "height": node.height},
        "zIndex": node.z_index,
        "rotation": node.rotation,
        "status": node.status,
        "hidden": node.hidden,
        "locked": node.locked,
        "collapsed": node.collapsed,
        "data": _json_load(node.data_json, {}),
        "ports": _json_load(node.ports_json, {}),
        "aiConfig": _json_load(node.ai_config_json, {}),
        "style": _json_load(node.style_json, {}),
        "revision": node.revision,
        "createdByUserId": encode_id(node.created_by_user_id) if node.created_by_user_id else None,
        "updatedByUserId": encode_id(node.updated_by_user_id) if node.updated_by_user_id else None,
        "createdAt": node.created_at.isoformat() if node.created_at else None,
        "updatedAt": node.updated_at.isoformat() if node.updated_at else None,
    }


def serialize_sluvo_edge(edge: SluvoCanvasEdge) -> Dict[str, Any]:
    return {
        "id": encode_id(edge.id),
        "canvasId": encode_id(edge.canvas_id),
        "sourceNodeId": encode_id(edge.source_node_id),
        "targetNodeId": encode_id(edge.target_node_id),
        "sourcePortId": edge.source_port_id,
        "targetPortId": edge.target_port_id,
        "edgeType": edge.edge_type,
        "label": edge.label,
        "data": _json_load(edge.data_json, {}),
        "style": _json_load(edge.style_json, {}),
        "hidden": edge.hidden,
        "revision": edge.revision,
        "createdAt": edge.created_at.isoformat() if edge.created_at else None,
        "updatedAt": edge.updated_at.isoformat() if edge.updated_at else None,
    }


def serialize_sluvo_asset(asset: SluvoCanvasAsset) -> Dict[str, Any]:
    return {
        "id": encode_id(asset.id),
        "projectId": encode_id(asset.project_id),
        "canvasId": encode_id(asset.canvas_id) if asset.canvas_id else None,
        "nodeId": encode_id(asset.node_id) if asset.node_id else None,
        "ownerUserId": encode_id(asset.owner_user_id),
        "mediaType": asset.media_type,
        "sourceType": asset.source_type,
        "url": asset.url,
        "thumbnailUrl": asset.thumbnail_url,
        "storageObjectId": encode_id(asset.storage_object_id) if asset.storage_object_id else None,
        "mimeType": asset.mime_type,
        "fileSize": asset.file_size,
        "width": asset.width,
        "height": asset.height,
        "durationSeconds": asset.duration_seconds,
        "metadata": _json_load(asset.metadata_json, {}),
        "createdAt": asset.created_at.isoformat() if asset.created_at else None,
        "updatedAt": asset.updated_at.isoformat() if asset.updated_at else None,
    }


def serialize_sluvo_agent_session(session_item: SluvoAgentSession) -> Dict[str, Any]:
    return {
        "id": encode_id(session_item.id),
        "projectId": encode_id(session_item.project_id),
        "canvasId": encode_id(session_item.canvas_id),
        "targetNodeId": encode_id(session_item.target_node_id) if session_item.target_node_id else None,
        "userId": encode_id(session_item.user_id),
        "teamId": encode_id(session_item.team_id),
        "title": session_item.title,
        "agentProfile": session_item.agent_profile,
        "mode": session_item.mode,
        "status": session_item.status,
        "contextSnapshot": _json_load(session_item.context_snapshot_json, {}),
        "lastEventAt": session_item.last_event_at.isoformat() if session_item.last_event_at else None,
        "createdAt": session_item.created_at.isoformat() if session_item.created_at else None,
        "updatedAt": session_item.updated_at.isoformat() if session_item.updated_at else None,
    }


def serialize_sluvo_agent_event(event: SluvoAgentEvent) -> Dict[str, Any]:
    return {
        "id": encode_id(event.id),
        "sessionId": encode_id(event.session_id),
        "turnId": event.turn_id,
        "role": event.role,
        "eventType": event.event_type,
        "sequenceNo": event.sequence_no,
        "payload": _json_load(event.payload_json, {}),
        "createdAt": event.created_at.isoformat() if event.created_at else None,
    }


def serialize_sluvo_agent_action(action: SluvoAgentAction) -> Dict[str, Any]:
    return {
        "id": encode_id(action.id),
        "sessionId": encode_id(action.session_id),
        "projectId": encode_id(action.project_id),
        "canvasId": encode_id(action.canvas_id),
        "targetNodeId": encode_id(action.target_node_id) if action.target_node_id else None,
        "actionType": action.action_type,
        "status": action.status,
        "input": _json_load(action.input_json, {}),
        "patch": _json_load(action.patch_json, {}),
        "result": _json_load(action.result_json, {}),
        "error": _json_load(action.error_json, {}),
        "approvedByUserId": encode_id(action.approved_by_user_id) if action.approved_by_user_id else None,
        "executedAt": action.executed_at.isoformat() if action.executed_at else None,
        "createdAt": action.created_at.isoformat() if action.created_at else None,
        "updatedAt": action.updated_at.isoformat() if action.updated_at else None,
    }


def get_project_member(session: Session, project_id: int, user_id: int) -> Optional[SluvoProjectMember]:
    return session.exec(
        select(SluvoProjectMember).where(SluvoProjectMember.project_id == project_id, SluvoProjectMember.user_id == user_id)
    ).first()


def require_sluvo_project_access(
    session: Session,
    *,
    user: User,
    team: Team,
    team_member: TeamMemberLink,
    project_id: int,
    permission: str,
) -> tuple[SluvoProject, Optional[SluvoProjectMember]]:
    project = _require_active_project(session, project_id)
    if int(project.team_id) != int(team.id):
        raise HTTPException(status_code=403, detail="无权限访问该 Sluvo 项目")

    member = get_project_member(session, project.id, user.id)
    if member and permission in _ROLE_PERMISSIONS.get(member.role, set()):
        return project, member

    if _has_team_manage_role(team_member.role):
        return project, member

    if project.visibility == "team" and permission == SLUVO_PERMISSION_READ:
        return project, member

    raise HTTPException(status_code=403, detail="当前账号没有该 Sluvo 项目的权限")


def get_or_create_main_canvas(session: Session, project: SluvoProject) -> SluvoCanvas:
    canvas = session.exec(
        select(SluvoCanvas).where(SluvoCanvas.project_id == project.id, SluvoCanvas.canvas_key == "main")
    ).first()
    if canvas:
        return canvas
    now = _utc_now()
    canvas = SluvoCanvas(
        project_id=project.id,
        canvas_key="main",
        title="Main Canvas",
        viewport_json=_json_dump({"x": 0, "y": 0, "zoom": 1}),
        snapshot_json=_json_dump({"nodes": [], "edges": []}),
        schema_version=1,
        revision=1,
        created_at=now,
        updated_at=now,
    )
    session.add(canvas)
    session.commit()
    session.refresh(canvas)
    return canvas


def create_sluvo_project(session: Session, *, user: User, team: Team, payload: SluvoProjectCreateRequest) -> Dict[str, Any]:
    now = _utc_now()
    project = SluvoProject(
        owner_user_id=user.id,
        team_id=team.id,
        title=payload.title.strip() or "Untitled Sluvo Project",
        description=payload.description,
        status="active",
        visibility=normalize_sluvo_project_visibility(payload.visibility),
        settings_json=_json_dump(payload.settings),
        cover_url=payload.coverUrl,
        created_at=now,
        updated_at=now,
    )
    session.add(project)
    session.commit()
    session.refresh(project)

    member = SluvoProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=SLUVO_MEMBER_ROLE_OWNER,
        invited_by_user_id=user.id,
        created_at=now,
        updated_at=now,
    )
    session.add(member)
    session.commit()
    session.refresh(member)
    canvas = get_or_create_main_canvas(session, project)
    return {"project": serialize_sluvo_project(project, member.role), "canvas": serialize_sluvo_canvas(canvas)}


def list_sluvo_projects(
    session: Session,
    *,
    user: User,
    team: Team,
    team_member: Optional[TeamMemberLink] = None,
    include_archived: bool = False,
) -> List[Dict[str, Any]]:
    projects = session.exec(
        select(SluvoProject).where(SluvoProject.team_id == team.id, SluvoProject.deleted_at == None).order_by(SluvoProject.updated_at.desc())
    ).all()
    result: List[Dict[str, Any]] = []
    can_manage_team = bool(team_member and _has_team_manage_role(team_member.role))
    for project in projects:
        if not include_archived and project.status == "archived":
            continue
        member = get_project_member(session, project.id, user.id)
        if not member and project.visibility != "team" and not can_manage_team:
            continue
        first_image_url = get_sluvo_project_first_image_url(session, project.id)
        result.append(serialize_sluvo_project(project, member.role if member else None, first_image_url))
    return result


def get_sluvo_project_bundle(session: Session, project: SluvoProject, member: Optional[SluvoProjectMember]) -> Dict[str, Any]:
    canvas = get_or_create_main_canvas(session, project)
    first_image_url = get_sluvo_project_first_image_url(session, project.id)
    return {
        "project": serialize_sluvo_project(project, member.role if member else None, first_image_url),
        "canvas": serialize_sluvo_canvas(canvas),
    }


def update_sluvo_project(session: Session, project: SluvoProject, payload: SluvoProjectUpdateRequest) -> SluvoProject:
    if payload.title is not None:
        project.title = payload.title.strip() or project.title
    if payload.description is not None:
        project.description = payload.description
    if payload.status is not None:
        project.status = normalize_sluvo_project_status(payload.status)
    if payload.visibility is not None:
        project.visibility = normalize_sluvo_project_visibility(payload.visibility)
    if payload.settings is not None:
        project.settings_json = _json_dump(payload.settings)
    if payload.coverUrl is not None:
        project.cover_url = payload.coverUrl
    project.updated_at = _utc_now()
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def soft_delete_sluvo_project(session: Session, project: SluvoProject) -> None:
    now = _utc_now()
    project.status = SLUVO_PROJECT_STATUS_DELETED
    project.deleted_at = now
    project.updated_at = now
    session.add(project)
    session.commit()


def list_sluvo_project_members(session: Session, project: SluvoProject) -> List[Dict[str, Any]]:
    members = session.exec(
        select(SluvoProjectMember).where(SluvoProjectMember.project_id == project.id).order_by(SluvoProjectMember.created_at.asc())
    ).all()
    return [serialize_sluvo_member(session, item) for item in members]


def _find_target_user(session: Session, payload: SluvoProjectMemberCreateRequest) -> User:
    if payload.userId:
        user = session.get(User, decode_id(payload.userId))
    elif payload.email:
        user = session.exec(select(User).where(User.email == payload.email)).first()
    else:
        user = None
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    return user


def add_sluvo_project_member(
    session: Session,
    *,
    project: SluvoProject,
    inviter: User,
    payload: SluvoProjectMemberCreateRequest,
) -> SluvoProjectMember:
    user = _find_target_user(session, payload)
    team_link = session.exec(
        select(TeamMemberLink).where(TeamMemberLink.team_id == project.team_id, TeamMemberLink.user_id == user.id)
    ).first()
    if not team_link:
        raise HTTPException(status_code=400, detail="只能添加同团队成员到 Sluvo 项目")
    existing = get_project_member(session, project.id, user.id)
    if existing:
        raise HTTPException(status_code=409, detail="用户已在项目中")
    now = _utc_now()
    member = SluvoProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=normalize_sluvo_member_role(payload.role),
        invited_by_user_id=inviter.id,
        created_at=now,
        updated_at=now,
    )
    session.add(member)
    session.commit()
    session.refresh(member)
    return member


def _owner_count(session: Session, project_id: int) -> int:
    return len(
        session.exec(
            select(SluvoProjectMember).where(
                SluvoProjectMember.project_id == project_id,
                SluvoProjectMember.role == SLUVO_MEMBER_ROLE_OWNER,
            )
        ).all()
    )


def update_sluvo_project_member(
    session: Session,
    *,
    project: SluvoProject,
    user_id: int,
    payload: SluvoProjectMemberUpdateRequest,
) -> SluvoProjectMember:
    member = get_project_member(session, project.id, user_id)
    if not member:
        raise HTTPException(status_code=404, detail="项目成员不存在")
    next_role = normalize_sluvo_member_role(payload.role)
    if member.role == SLUVO_MEMBER_ROLE_OWNER and next_role != SLUVO_MEMBER_ROLE_OWNER and _owner_count(session, project.id) <= 1:
        raise HTTPException(status_code=400, detail="项目至少需要保留一个 owner")
    member.role = next_role
    member.updated_at = _utc_now()
    session.add(member)
    session.commit()
    session.refresh(member)
    return member


def remove_sluvo_project_member(session: Session, *, project: SluvoProject, user_id: int) -> None:
    member = get_project_member(session, project.id, user_id)
    if not member:
        raise HTTPException(status_code=404, detail="项目成员不存在")
    if member.role == SLUVO_MEMBER_ROLE_OWNER and _owner_count(session, project.id) <= 1:
        raise HTTPException(status_code=400, detail="项目至少需要保留一个 owner")
    session.delete(member)
    session.commit()


def _touch_canvas(
    session: Session,
    canvas: SluvoCanvas,
    *,
    mutation_type: str,
    actor_type: str = "user",
    actor_user_id: Optional[int] = None,
    agent_session_id: Optional[int] = None,
    agent_action_id: Optional[int] = None,
    patch: Optional[Dict[str, Any]] = None,
) -> SluvoCanvas:
    previous_revision = int(canvas.revision or 1)
    canvas.revision = previous_revision + 1
    canvas.updated_at = _utc_now()
    session.add(canvas)
    session.flush()
    session.add(
        SluvoCanvasMutation(
            project_id=canvas.project_id,
            canvas_id=canvas.id,
            actor_type=actor_type,
            actor_user_id=actor_user_id,
            agent_session_id=agent_session_id,
            agent_action_id=agent_action_id,
            mutation_type=mutation_type,
            revision_from=previous_revision,
            revision_to=canvas.revision,
            patch_json=_json_dump(patch or {}),
            created_at=_utc_now(),
        )
    )
    return canvas


def canvas_bundle(session: Session, canvas: SluvoCanvas) -> Dict[str, Any]:
    nodes = session.exec(
        select(SluvoCanvasNode).where(SluvoCanvasNode.canvas_id == canvas.id, SluvoCanvasNode.deleted_at == None).order_by(SluvoCanvasNode.z_index.asc(), SluvoCanvasNode.id.asc())
    ).all()
    edges = session.exec(
        select(SluvoCanvasEdge).where(SluvoCanvasEdge.canvas_id == canvas.id, SluvoCanvasEdge.deleted_at == None).order_by(SluvoCanvasEdge.id.asc())
    ).all()
    return {
        "canvas": serialize_sluvo_canvas(canvas),
        "nodes": [serialize_sluvo_node(item) for item in nodes],
        "edges": [serialize_sluvo_edge(item) for item in edges],
    }


def update_sluvo_canvas(session: Session, canvas: SluvoCanvas, payload: SluvoCanvasPatchRequest, *, user: User) -> Dict[str, Any]:
    _check_revision(canvas.revision, payload.expectedRevision, "画布")
    if payload.title is not None:
        canvas.title = payload.title.strip() or canvas.title
    if payload.viewport is not None:
        canvas.viewport_json = _json_dump(payload.viewport)
    if payload.snapshot is not None:
        canvas.snapshot_json = _json_dump(payload.snapshot)
    if payload.schemaVersion is not None:
        canvas.schema_version = int(payload.schemaVersion or canvas.schema_version)
    _touch_canvas(session, canvas, mutation_type="canvas.update", actor_user_id=user.id, patch=payload.model_dump())
    session.commit()
    session.refresh(canvas)
    return canvas_bundle(session, canvas)


def create_sluvo_node(session: Session, canvas: SluvoCanvas, payload: SluvoCanvasNodeCreateRequest, *, user: User) -> SluvoCanvasNode:
    parent_id = _decode_optional(payload.parentNodeId)
    if parent_id:
        parent = _require_node(session, parent_id)
        _assert_same_canvas(parent.canvas_id, canvas.id, "父节点")
    size = payload.size or {}
    position = payload.position or {}
    node = SluvoCanvasNode(
        canvas_id=canvas.id,
        parent_node_id=parent_id,
        node_type=normalize_sluvo_node_type(payload.nodeType),
        title=payload.title or "",
        position_x=float(position.get("x", 0.0)),
        position_y=float(position.get("y", 0.0)),
        width=size.get("width"),
        height=size.get("height"),
        z_index=int(payload.zIndex or 0),
        rotation=float(payload.rotation or 0.0),
        status=payload.status or "idle",
        hidden=bool(payload.hidden),
        locked=bool(payload.locked),
        collapsed=bool(payload.collapsed),
        data_json=_json_dump(payload.data),
        ports_json=_json_dump(payload.ports),
        ai_config_json=_json_dump(payload.aiConfig),
        style_json=_json_dump(payload.style),
        revision=1,
        created_by_user_id=user.id,
        updated_by_user_id=user.id,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(node)
    session.flush()
    _touch_canvas(session, canvas, mutation_type="node.create", actor_user_id=user.id, patch={"nodeId": encode_id(node.id)})
    session.commit()
    session.refresh(node)
    return node


def update_sluvo_node(session: Session, canvas: SluvoCanvas, node: SluvoCanvasNode, payload: SluvoCanvasNodeUpdateRequest, *, user: User) -> SluvoCanvasNode:
    _assert_same_canvas(node.canvas_id, canvas.id, "节点")
    _check_revision(node.revision, payload.expectedRevision, "节点")
    if payload.deleted:
        node.deleted_at = _utc_now()
    if payload.parentNodeId is not None:
        node.parent_node_id = _decode_optional(payload.parentNodeId)
    if payload.nodeType is not None:
        node.node_type = normalize_sluvo_node_type(payload.nodeType)
    if payload.title is not None:
        node.title = payload.title
    if payload.position is not None:
        node.position_x = float(payload.position.get("x", node.position_x))
        node.position_y = float(payload.position.get("y", node.position_y))
    if payload.size is not None:
        node.width = payload.size.get("width")
        node.height = payload.size.get("height")
    if payload.zIndex is not None:
        node.z_index = int(payload.zIndex)
    if payload.rotation is not None:
        node.rotation = float(payload.rotation)
    if payload.status is not None:
        node.status = payload.status
    if payload.hidden is not None:
        node.hidden = bool(payload.hidden)
    if payload.locked is not None:
        node.locked = bool(payload.locked)
    if payload.collapsed is not None:
        node.collapsed = bool(payload.collapsed)
    if payload.data is not None:
        node.data_json = _json_dump(payload.data)
    if payload.ports is not None:
        node.ports_json = _json_dump(payload.ports)
    if payload.aiConfig is not None:
        node.ai_config_json = _json_dump(payload.aiConfig)
    if payload.style is not None:
        node.style_json = _json_dump(payload.style)
    node.revision = int(node.revision or 1) + 1
    node.updated_by_user_id = user.id
    node.updated_at = _utc_now()
    session.add(node)
    _touch_canvas(session, canvas, mutation_type="node.update", actor_user_id=user.id, patch={"nodeId": encode_id(node.id)})
    session.commit()
    session.refresh(node)
    return node


def create_sluvo_edge(session: Session, canvas: SluvoCanvas, payload: SluvoCanvasEdgeCreateRequest) -> SluvoCanvasEdge:
    source = _require_node(session, decode_id(payload.sourceNodeId))
    target = _require_node(session, decode_id(payload.targetNodeId))
    _assert_same_canvas(source.canvas_id, canvas.id, "源节点")
    _assert_same_canvas(target.canvas_id, canvas.id, "目标节点")
    edge = SluvoCanvasEdge(
        canvas_id=canvas.id,
        source_node_id=source.id,
        target_node_id=target.id,
        source_port_id=payload.sourcePortId,
        target_port_id=payload.targetPortId,
        edge_type=normalize_sluvo_edge_type(payload.edgeType),
        label=payload.label,
        data_json=_json_dump(payload.data),
        style_json=_json_dump(payload.style),
        hidden=bool(payload.hidden),
        revision=1,
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(edge)
    session.flush()
    _touch_canvas(session, canvas, mutation_type="edge.create", patch={"edgeId": encode_id(edge.id)})
    session.commit()
    session.refresh(edge)
    return edge


def update_sluvo_edge(session: Session, canvas: SluvoCanvas, edge: SluvoCanvasEdge, payload: SluvoCanvasEdgeUpdateRequest) -> SluvoCanvasEdge:
    _assert_same_canvas(edge.canvas_id, canvas.id, "连线")
    _check_revision(edge.revision, payload.expectedRevision, "连线")
    if payload.deleted:
        edge.deleted_at = _utc_now()
    if payload.sourceNodeId is not None:
        source = _require_node(session, decode_id(payload.sourceNodeId))
        _assert_same_canvas(source.canvas_id, canvas.id, "源节点")
        edge.source_node_id = source.id
    if payload.targetNodeId is not None:
        target = _require_node(session, decode_id(payload.targetNodeId))
        _assert_same_canvas(target.canvas_id, canvas.id, "目标节点")
        edge.target_node_id = target.id
    if payload.sourcePortId is not None:
        edge.source_port_id = payload.sourcePortId
    if payload.targetPortId is not None:
        edge.target_port_id = payload.targetPortId
    if payload.edgeType is not None:
        edge.edge_type = normalize_sluvo_edge_type(payload.edgeType)
    if payload.label is not None:
        edge.label = payload.label
    if payload.data is not None:
        edge.data_json = _json_dump(payload.data)
    if payload.style is not None:
        edge.style_json = _json_dump(payload.style)
    if payload.hidden is not None:
        edge.hidden = bool(payload.hidden)
    edge.revision = int(edge.revision or 1) + 1
    edge.updated_at = _utc_now()
    session.add(edge)
    _touch_canvas(session, canvas, mutation_type="edge.update", patch={"edgeId": encode_id(edge.id)})
    session.commit()
    session.refresh(edge)
    return edge


def normalize_sluvo_upload_media_type(media_type: Optional[str], content_type: Optional[str]) -> str:
    text = str(media_type or "").strip().lower()
    if text in {"image", "video", "audio"}:
        return text
    content = str(content_type or "").strip().lower()
    if content.startswith("image/"):
        return "image"
    if content.startswith("video/"):
        return "video"
    if content.startswith("audio/"):
        return "audio"
    raise HTTPException(status_code=400, detail="上传文件格式不支持")


def validate_sluvo_upload_content(content: bytes, content_type: Optional[str]) -> str:
    normalized_type = str(content_type or "").strip().lower()
    if normalized_type not in SLUVO_UPLOAD_MIME_TYPES:
        raise HTTPException(status_code=400, detail="上传文件格式不支持")
    if not content:
        raise HTTPException(status_code=400, detail="上传文件内容为空")
    if len(content) > SLUVO_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=400, detail="上传文件不能超过 20MB")
    return normalized_type


def create_sluvo_canvas_asset_upload(
    session: Session,
    *,
    canvas: SluvoCanvas,
    user: User,
    content: bytes,
    filename: str,
    content_type: str,
    media_type: Optional[str] = None,
    node_id: Optional[str] = None,
    width: Optional[int] = None,
    height: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    normalized_content_type = validate_sluvo_upload_content(content, content_type)
    normalized_media_type = normalize_sluvo_upload_media_type(media_type, normalized_content_type)
    decoded_node_id = _decode_optional(node_id)
    if decoded_node_id:
        node = _require_node(session, decoded_node_id)
        _assert_same_canvas(node.canvas_id, canvas.id, "素材节点")

    meta = _upload_bytes_to_oss_with_meta(
        content,
        filename=filename or "upload.bin",
        content_type=normalized_content_type,
        owner_user_id=user.id,
        media_type=normalized_media_type,
        source_type="sluvo_canvas_asset",
    )
    storage_object = session.exec(
        select(StorageObject).where(StorageObject.object_key == meta.get("storage_object_key"))
    ).first()
    now = _utc_now()
    asset = SluvoCanvasAsset(
        project_id=canvas.project_id,
        canvas_id=canvas.id,
        node_id=decoded_node_id,
        owner_user_id=user.id,
        media_type=normalized_media_type,
        source_type="upload",
        url=meta["file_url"],
        thumbnail_url=meta.get("thumbnail_url") or None,
        storage_object_id=storage_object.id if storage_object else None,
        mime_type=normalized_content_type,
        file_size=int(meta.get("file_size") or len(content)),
        width=width,
        height=height,
        duration_seconds=duration_seconds,
        metadata_json=_json_dump(
            {
                **(metadata or {}),
                "originalFilename": meta.get("original_filename") or filename,
                "storageObjectKey": meta.get("storage_object_key"),
            }
        ),
        created_at=now,
        updated_at=now,
    )
    session.add(asset)
    session.commit()
    session.refresh(asset)
    return {
        "success": True,
        "asset": serialize_sluvo_asset(asset),
        "fileUrl": asset.url,
        "thumbnailUrl": asset.thumbnail_url,
        "storageObjectId": encode_id(asset.storage_object_id) if asset.storage_object_id else None,
        "storageObjectKey": meta.get("storage_object_key"),
    }


def apply_sluvo_canvas_batch(
    session: Session,
    canvas: SluvoCanvas,
    payload: SluvoCanvasBatchRequest,
    *,
    user: Optional[User] = None,
    actor_type: str = "user",
    agent_session_id: Optional[int] = None,
    agent_action_id: Optional[int] = None,
) -> Dict[str, Any]:
    _check_revision(canvas.revision, payload.expectedRevision, "画布")
    if payload.title is not None:
        canvas.title = payload.title.strip() or canvas.title
    if payload.viewport is not None:
        canvas.viewport_json = _json_dump(payload.viewport)
    if payload.snapshot is not None:
        canvas.snapshot_json = _json_dump(payload.snapshot)

    for node_id in payload.deletedNodeIds:
        node = _require_node(session, decode_id(node_id))
        _assert_same_canvas(node.canvas_id, canvas.id, "节点")
        node.deleted_at = _utc_now()
        node.revision = int(node.revision or 1) + 1
        if user:
            node.updated_by_user_id = user.id
        node.updated_at = _utc_now()
        session.add(node)

    for item in payload.nodes:
        node_id = _decode_optional(item.get("id"))
        if node_id:
            node = _require_node(session, node_id)
            update_payload = SluvoCanvasNodeUpdateRequest(**{k: v for k, v in item.items() if k != "id"})
            _assert_same_canvas(node.canvas_id, canvas.id, "节点")
            _check_revision(node.revision, update_payload.expectedRevision, "节点")
            if update_payload.title is not None:
                node.title = update_payload.title
            if update_payload.position is not None:
                node.position_x = float(update_payload.position.get("x", node.position_x))
                node.position_y = float(update_payload.position.get("y", node.position_y))
            if update_payload.size is not None:
                node.width = update_payload.size.get("width")
                node.height = update_payload.size.get("height")
            if update_payload.data is not None:
                node.data_json = _json_dump(update_payload.data)
            if update_payload.style is not None:
                node.style_json = _json_dump(update_payload.style)
            node.revision = int(node.revision or 1) + 1
            node.updated_by_user_id = user.id if user else node.updated_by_user_id
            node.updated_at = _utc_now()
            session.add(node)
        else:
            create_payload = SluvoCanvasNodeCreateRequest(**item)
            parent_id = _decode_optional(create_payload.parentNodeId)
            node = SluvoCanvasNode(
                canvas_id=canvas.id,
                parent_node_id=parent_id,
                node_type=normalize_sluvo_node_type(create_payload.nodeType),
                title=create_payload.title,
                position_x=float((create_payload.position or {}).get("x", 0.0)),
                position_y=float((create_payload.position or {}).get("y", 0.0)),
                width=(create_payload.size or {}).get("width"),
                height=(create_payload.size or {}).get("height"),
                z_index=int(create_payload.zIndex or 0),
                rotation=float(create_payload.rotation or 0.0),
                status=create_payload.status or "idle",
                hidden=bool(create_payload.hidden),
                locked=bool(create_payload.locked),
                collapsed=bool(create_payload.collapsed),
                data_json=_json_dump(create_payload.data),
                ports_json=_json_dump(create_payload.ports),
                ai_config_json=_json_dump(create_payload.aiConfig),
                style_json=_json_dump(create_payload.style),
                revision=1,
                created_by_user_id=user.id if user else None,
                updated_by_user_id=user.id if user else None,
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
            session.add(node)

    for edge_id in payload.deletedEdgeIds:
        edge = _require_edge(session, decode_id(edge_id))
        _assert_same_canvas(edge.canvas_id, canvas.id, "连线")
        edge.deleted_at = _utc_now()
        edge.revision = int(edge.revision or 1) + 1
        edge.updated_at = _utc_now()
        session.add(edge)

    for item in payload.edges:
        edge_id = _decode_optional(item.get("id"))
        if edge_id:
            edge = _require_edge(session, edge_id)
            update_payload = SluvoCanvasEdgeUpdateRequest(**{k: v for k, v in item.items() if k != "id"})
            _assert_same_canvas(edge.canvas_id, canvas.id, "连线")
            _check_revision(edge.revision, update_payload.expectedRevision, "连线")
            if update_payload.label is not None:
                edge.label = update_payload.label
            if update_payload.data is not None:
                edge.data_json = _json_dump(update_payload.data)
            if update_payload.style is not None:
                edge.style_json = _json_dump(update_payload.style)
            if update_payload.hidden is not None:
                edge.hidden = update_payload.hidden
            edge.revision = int(edge.revision or 1) + 1
            edge.updated_at = _utc_now()
            session.add(edge)
        else:
            create_payload = SluvoCanvasEdgeCreateRequest(**item)
            source = _require_node(session, decode_id(create_payload.sourceNodeId))
            target = _require_node(session, decode_id(create_payload.targetNodeId))
            _assert_same_canvas(source.canvas_id, canvas.id, "源节点")
            _assert_same_canvas(target.canvas_id, canvas.id, "目标节点")
            edge = SluvoCanvasEdge(
                canvas_id=canvas.id,
                source_node_id=source.id,
                target_node_id=target.id,
                source_port_id=create_payload.sourcePortId,
                target_port_id=create_payload.targetPortId,
                edge_type=normalize_sluvo_edge_type(create_payload.edgeType),
                label=create_payload.label,
                data_json=_json_dump(create_payload.data),
                style_json=_json_dump(create_payload.style),
                hidden=bool(create_payload.hidden),
                revision=1,
                created_at=_utc_now(),
                updated_at=_utc_now(),
            )
            session.add(edge)

    _touch_canvas(
        session,
        canvas,
        mutation_type="canvas.batch",
        actor_type=actor_type,
        actor_user_id=user.id if user else None,
        agent_session_id=agent_session_id,
        agent_action_id=agent_action_id,
        patch=payload.model_dump(),
    )
    session.commit()
    session.refresh(canvas)
    return canvas_bundle(session, canvas)


def create_sluvo_agent_session(
    session: Session,
    *,
    project: SluvoProject,
    user: User,
    team: Team,
    canvas_id: Optional[int],
    target_node_id: Optional[int],
    title: Optional[str],
    agent_profile: str,
    mode: str,
    context_snapshot: Dict[str, Any],
) -> SluvoAgentSession:
    canvas = _require_canvas(session, canvas_id) if canvas_id else get_or_create_main_canvas(session, project)
    if canvas.project_id != project.id:
        raise HTTPException(status_code=400, detail="Agent 画布不属于当前项目")
    if target_node_id:
        node = _require_node(session, target_node_id)
        _assert_same_canvas(node.canvas_id, canvas.id, "目标节点")
    item = SluvoAgentSession(
        project_id=project.id,
        canvas_id=canvas.id,
        target_node_id=target_node_id,
        user_id=user.id,
        team_id=team.id,
        title=title,
        agent_profile=agent_profile or "canvas_agent",
        mode=mode or "semi_auto",
        status="active",
        context_snapshot_json=_json_dump(context_snapshot),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def require_sluvo_agent_session(session: Session, session_id: int) -> SluvoAgentSession:
    item = session.get(SluvoAgentSession, session_id)
    if not item:
        raise HTTPException(status_code=404, detail="Sluvo Agent 会话不存在")
    return item


def append_sluvo_agent_event(
    session: Session,
    *,
    agent_session: SluvoAgentSession,
    role: str,
    event_type: str,
    payload: Dict[str, Any],
    turn_id: Optional[str] = None,
) -> SluvoAgentEvent:
    last = session.exec(
        select(SluvoAgentEvent).where(SluvoAgentEvent.session_id == agent_session.id).order_by(SluvoAgentEvent.sequence_no.desc())
    ).first()
    event = SluvoAgentEvent(
        session_id=agent_session.id,
        turn_id=turn_id,
        role=role,
        event_type=event_type,
        sequence_no=int(last.sequence_no if last else 0) + 1,
        payload_json=_json_dump(payload),
        created_at=_utc_now(),
    )
    agent_session.last_event_at = event.created_at
    agent_session.updated_at = event.created_at
    session.add(event)
    session.add(agent_session)
    session.commit()
    session.refresh(event)
    return event


def create_sluvo_agent_action(
    session: Session,
    *,
    agent_session: SluvoAgentSession,
    action_payload: Dict[str, Any],
) -> SluvoAgentAction:
    target_node_id = _decode_optional(action_payload.get("targetNodeId")) or agent_session.target_node_id
    action = SluvoAgentAction(
        session_id=agent_session.id,
        project_id=agent_session.project_id,
        canvas_id=agent_session.canvas_id,
        target_node_id=target_node_id,
        action_type=str(action_payload.get("actionType") or action_payload.get("type") or "canvas.patch"),
        status="proposed",
        input_json=_json_dump(action_payload.get("input") or {}),
        patch_json=_json_dump(action_payload.get("patch") or {}),
        result_json="{}",
        error_json="{}",
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    session.add(action)
    session.commit()
    session.refresh(action)
    return action


def require_sluvo_agent_action(session: Session, action_id: int) -> SluvoAgentAction:
    action = session.get(SluvoAgentAction, action_id)
    if not action:
        raise HTTPException(status_code=404, detail="Sluvo Agent 操作不存在")
    return action


def approve_sluvo_agent_action(session: Session, action: SluvoAgentAction, *, user: User) -> SluvoAgentAction:
    if action.status not in {"proposed", "approved"}:
        raise HTTPException(status_code=409, detail="当前 Agent 操作状态不可审批")
    agent_session = require_sluvo_agent_session(session, action.session_id)
    canvas = _require_canvas(session, action.canvas_id)
    action.status = "running"
    action.approved_by_user_id = user.id
    action.updated_at = _utc_now()
    session.add(action)
    session.commit()
    try:
        patch = _json_load(action.patch_json, {})
        batch_payload = SluvoCanvasBatchRequest(**patch)
        result = apply_sluvo_canvas_batch(
            session,
            canvas,
            batch_payload,
            user=user,
            actor_type="agent",
            agent_session_id=agent_session.id,
            agent_action_id=action.id,
        )
        action.status = "succeeded"
        action.result_json = _json_dump(result)
        action.error_json = "{}"
        action.executed_at = _utc_now()
    except Exception as exc:
        action.status = "failed"
        action.error_json = _json_dump({"message": str(exc)})
    action.updated_at = _utc_now()
    session.add(action)
    session.commit()
    session.refresh(action)
    return action


def cancel_sluvo_agent_action(session: Session, action: SluvoAgentAction) -> SluvoAgentAction:
    if action.status not in {"proposed", "approved", "running"}:
        raise HTTPException(status_code=409, detail="当前 Agent 操作状态不可取消")
    action.status = "cancelled"
    action.updated_at = _utc_now()
    session.add(action)
    session.commit()
    session.refresh(action)
    return action
