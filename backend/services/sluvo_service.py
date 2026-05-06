from __future__ import annotations

import json
import re
from datetime import datetime
from decimal import Decimal, ROUND_CEILING
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from core.config import settings
from core.security import decode_id, encode_id
from models import (
    GenerationRecord,
    RoleEnum,
    SluvoAgentAction,
    SluvoAgentArtifact,
    SluvoAgentEvent,
    SluvoAgentRun,
    SluvoAgentSession,
    SluvoAgentStep,
    SluvoAgentTemplate,
    SluvoCanvas,
    SluvoCanvasAsset,
    SluvoCanvasEdge,
    SluvoCanvasMutation,
    SluvoCanvasNode,
    SluvoCommunityAgent,
    SluvoCommunityCanvas,
    SluvoProject,
    SluvoProjectMember,
    StorageObject,
    Team,
    TeamMemberLink,
    User,
)
from services.agents.llm_client import chat_json
from services.deepseek_hybrid_router import estimate_text_tokens
from services.deepseek_model_policy import calculate_deepseek_v4_flash_usage_cost_cny
from schemas import (
    SLUVO_MEMBER_ROLE_EDITOR,
    SLUVO_MEMBER_ROLE_OWNER,
    SLUVO_MEMBER_ROLE_VIEWER,
    SLUVO_COMMUNITY_CANVAS_STATUS_PUBLISHED,
    SLUVO_COMMUNITY_CANVAS_STATUS_UNPUBLISHED,
    SLUVO_COMMUNITY_AGENT_STATUS_PUBLISHED,
    SLUVO_COMMUNITY_AGENT_STATUS_UNPUBLISHED,
    SLUVO_PROJECT_STATUS_ACTIVE,
    SLUVO_PROJECT_STATUS_DELETED,
    SluvoAgentTemplateCreateRequest,
    SluvoAgentTemplateUpdateRequest,
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
    SluvoTextNodeAnalyzeRequest,
    SluvoProjectUpdateRequest,
    normalize_sluvo_edge_type,
    normalize_sluvo_agent_model_code,
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
SLUVO_TEXT_NODE_ANALYZE_MAX_TOKENS = 1400
SLUVO_TEXT_NODE_POINTS_UNIT_CNY = Decimal("0.1")

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

SLUVO_OFFICIAL_AGENT_PROFILES = {
    "onboarding": {
        "name": "Onboarding Agent",
        "description": "理解创作目标、输入素材和边界，并决定进入哪条创作流水线。",
        "tools": ["read_canvas", "route_agents"],
    },
    "director": {
        "name": "Director Agent",
        "description": "规划故事方向、视听风格、节奏和后续 Agent 的工作边界。",
        "tools": ["read_canvas", "propose_canvas_patch"],
    },
    "scriptwriter": {
        "name": "Scriptwriter Agent",
        "description": "创作剧本、角色关系、场景节拍和可拆分镜头结构。",
        "tools": ["read_canvas", "propose_canvas_patch"],
    },
    "character_artist": {
        "name": "Character Artist Agent",
        "description": "生成角色外观、服装、道具和一致性视觉锚点。",
        "tools": ["read_canvas", "propose_canvas_patch"],
    },
    "storyboard_artist": {
        "name": "Storyboard Artist Agent",
        "description": "规划分镜首帧、构图、景别和画面提示词。",
        "tools": ["read_canvas", "propose_canvas_patch"],
    },
    "video_generator": {
        "name": "Video Generator Agent",
        "description": "基于首帧和镜头动作创建视频生成任务，并等待扣费确认。",
        "tools": ["read_canvas", "propose_canvas_patch", "estimate_cost"],
    },
    "video_merger": {
        "name": "Video Merger Agent",
        "description": "拼接视频片段，整理最终预览、导出和交付状态。",
        "tools": ["read_canvas", "propose_report"],
    },
    "review": {
        "name": "Review Agent",
        "description": "处理用户反馈，判断应从哪位 Agent 重新进入流水线。",
        "tools": ["read_canvas", "route_agents"],
    },
    "canvas_agent": {
        "name": "画布协作 Agent",
        "description": "读取选区和上下文，生成可审阅的画布提案。",
        "tools": ["read_canvas", "propose_canvas_patch"],
    },
    "story_director": {
        "name": "故事发展 Agent",
        "description": "把创意扩写为故事结构、人物关系和冲突节奏。",
        "tools": ["read_canvas", "propose_canvas_patch"],
    },
    "storyboard_director": {
        "name": "分镜导演 Agent",
        "description": "把剧本或文本节点拆成镜头节点和生成链路。",
        "tools": ["read_canvas", "propose_canvas_patch"],
    },
    "prompt_polisher": {
        "name": "Prompt 精修 Agent",
        "description": "把口语化描述改写为适合生成节点的提示词。",
        "tools": ["read_canvas", "propose_canvas_patch"],
    },
    "consistency_checker": {
        "name": "一致性检查 Agent",
        "description": "检查角色、场景、道具和风格是否在画布中漂移。",
        "tools": ["read_canvas", "propose_report"],
    },
    "production_planner": {
        "name": "制片调度 Agent",
        "description": "整理缺失输入、可运行节点、失败任务和下一步计划。",
        "tools": ["read_canvas", "propose_report"],
    },
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


def _decode_optional_safe(value: Optional[str]) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return decode_id(str(value))
    except HTTPException:
        return None


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


def _item_client_id(item: Dict[str, Any]) -> str:
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    return str(data.get("clientId") or item.get("clientId") or "").strip()


def _resolve_batch_node_id(
    session: Session,
    canvas: SluvoCanvas,
    value: Optional[str],
    client_id: Optional[str],
    client_node_ids: Dict[str, int],
    label: str,
) -> int:
    raw_value = str(value or "").strip()
    node_id = _decode_optional_safe(raw_value)
    if node_id:
        node = _require_node(session, node_id)
        _assert_same_canvas(node.canvas_id, canvas.id, label)
        return node.id
    for client_key in (str(client_id or "").strip(), raw_value):
        if client_key and client_key in client_node_ids:
            return client_node_ids[client_key]
    raise HTTPException(status_code=400, detail=f"{label} cannot be resolved")


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


def get_sluvo_project_community_publication(session: Session, project_id: int) -> Optional[SluvoCommunityCanvas]:
    return session.exec(
        select(SluvoCommunityCanvas).where(
            SluvoCommunityCanvas.source_project_id == project_id,
            SluvoCommunityCanvas.status == SLUVO_COMMUNITY_CANVAS_STATUS_PUBLISHED,
        )
    ).first()


def serialize_sluvo_project(
    project: SluvoProject,
    member_role: Optional[str] = None,
    first_image_url: Optional[str] = None,
    community_publication: Optional[SluvoCommunityCanvas] = None,
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
        "communityPublication": {
            "id": encode_id(community_publication.id),
            "status": community_publication.status,
            "publishedAt": community_publication.published_at.isoformat() if community_publication.published_at else None,
        } if community_publication else None,
        "memberRole": member_role,
        "lastOpenedAt": project.last_opened_at.isoformat() if project.last_opened_at else None,
        "deletedAt": project.deleted_at.isoformat() if project.deleted_at else None,
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


def _serialize_community_author(user: Optional[User]) -> Dict[str, Any]:
    return {
        "nickname": (user.nickname if user else "") or "Sluvo 创作者",
        "avatarUrl": user.avatar_url if user else None,
    }


def _normalize_community_tags(tags: List[Any]) -> List[str]:
    result: List[str] = []
    for item in tags or []:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text[:24])
        if len(result) >= 8:
            break
    return result


def _normalize_agent_tools(tools: List[Any]) -> List[str]:
    allowed = {
        "read_canvas",
        "propose_canvas_patch",
        "propose_report",
        "rewrite_prompt",
        "plan_workflow",
        "run_generation_with_approval",
    }
    result: List[str] = []
    for item in tools or []:
        value = str(item or "").strip()
        if value in allowed and value not in result:
            result.append(value)
    return result or ["read_canvas", "propose_canvas_patch"]


def _public_agent_snapshot(item: SluvoAgentTemplate) -> Dict[str, Any]:
    data = serialize_sluvo_agent_template(item)
    data.pop("memory", None)
    data.pop("ownerUserId", None)
    data.pop("teamId", None)
    return data


def serialize_sluvo_community_canvas(item: SluvoCommunityCanvas, *, detail: bool = False) -> Dict[str, Any]:
    owner = None
    # The session-backed detail serializer below can fill this; keep this helper safe for tests.
    return _serialize_sluvo_community_canvas_payload(item, owner=owner, detail=detail)


def serialize_sluvo_community_canvas_with_session(
    session: Session,
    item: SluvoCommunityCanvas,
    *,
    detail: bool = False,
) -> Dict[str, Any]:
    owner = session.get(User, item.owner_user_id) if item.owner_user_id else None
    return _serialize_sluvo_community_canvas_payload(item, owner=owner, detail=detail)


def _serialize_sluvo_community_canvas_payload(
    item: SluvoCommunityCanvas,
    *,
    owner: Optional[User],
    detail: bool = False,
) -> Dict[str, Any]:
    payload = {
        "id": encode_id(item.id),
        "sourceProjectId": encode_id(item.source_project_id),
        "sourceCanvasId": encode_id(item.source_canvas_id),
        "title": item.title,
        "description": item.description or "",
        "coverUrl": item.cover_url,
        "tags": _json_load(item.tags_json, []),
        "status": item.status,
        "author": _serialize_community_author(owner),
        "viewCount": int(item.view_count or 0),
        "forkCount": int(item.fork_count or 0),
        "publishedAt": item.published_at.isoformat() if item.published_at else None,
        "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
    }
    if detail:
        payload.update(
            {
                "canvas": {
                    "id": encode_id(item.source_canvas_id),
                    "projectId": encode_id(item.source_project_id),
                    "canvasKey": "community",
                    "title": item.title,
                    "viewport": _json_load(item.viewport_json, {}),
                    "snapshot": _json_load(item.snapshot_json, {}),
                    "schemaVersion": item.schema_version,
                    "revision": 1,
                },
                "nodes": _json_load(item.nodes_json, []),
                "edges": _json_load(item.edges_json, []),
            }
        )
    return payload


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


def _serialize_sluvo_generation_record(record: Optional[GenerationRecord]) -> Optional[Dict[str, Any]]:
    if not record:
        return None
    return {
        "id": encode_id(record.id),
        "recordType": record.record_type,
        "status": record.status,
        "targetType": record.target_type,
        "targetId": encode_id(record.target_id) if record.target_id else None,
        "taskId": record.task_id,
        "prompt": record.prompt,
        "previewUrl": record.preview_url,
        "thumbnailUrl": record.thumbnail_url,
        "estimatePoints": record.estimate_points,
        "pointsStatus": record.points_status,
        "errorMessage": record.error_message_public,
        "createdAt": record.created_at.isoformat() if record.created_at else None,
        "updatedAt": record.updated_at.isoformat() if record.updated_at else None,
    }


def serialize_sluvo_agent_artifact(session: Session, artifact: SluvoAgentArtifact) -> Dict[str, Any]:
    record = session.get(GenerationRecord, artifact.generation_record_id) if artifact.generation_record_id else None
    return {
        "id": encode_id(artifact.id),
        "runId": encode_id(artifact.run_id),
        "stepId": encode_id(artifact.step_id),
        "canvasNodeId": encode_id(artifact.canvas_node_id) if artifact.canvas_node_id else None,
        "generationRecordId": encode_id(artifact.generation_record_id) if artifact.generation_record_id else None,
        "generationRecord": _serialize_sluvo_generation_record(record),
        "title": artifact.title,
        "artifactType": artifact.artifact_type,
        "status": artifact.status,
        "payload": _json_load(artifact.payload_json, {}),
        "preview": _json_load(artifact.preview_json, {}),
        "writePolicy": artifact.write_policy,
        "createdAt": artifact.created_at.isoformat() if artifact.created_at else None,
        "updatedAt": artifact.updated_at.isoformat() if artifact.updated_at else None,
    }


def serialize_sluvo_agent_step(session: Session, step: SluvoAgentStep) -> Dict[str, Any]:
    artifacts = session.exec(
        select(SluvoAgentArtifact)
        .where(SluvoAgentArtifact.step_id == step.id)
        .order_by(SluvoAgentArtifact.id.asc())
    ).all()
    action = session.get(SluvoAgentAction, step.action_id) if step.action_id else None
    return {
        "id": encode_id(step.id),
        "runId": encode_id(step.run_id),
        "sessionId": encode_id(step.session_id) if step.session_id else None,
        "agentTemplateId": encode_id(step.agent_template_id) if step.agent_template_id else None,
        "actionId": encode_id(step.action_id) if step.action_id else None,
        "action": serialize_sluvo_agent_action(action) if action else None,
        "stepKey": step.step_key,
        "agentName": step.agent_name,
        "agentProfile": step.agent_profile,
        "modelCode": step.model_code,
        "title": step.title,
        "status": step.status,
        "input": _json_load(step.input_json, {}),
        "output": _json_load(step.output_json, {}),
        "error": _json_load(step.error_json, {}),
        "orderIndex": step.order_index,
        "artifacts": [serialize_sluvo_agent_artifact(session, item) for item in artifacts],
        "createdAt": step.created_at.isoformat() if step.created_at else None,
        "updatedAt": step.updated_at.isoformat() if step.updated_at else None,
        "finishedAt": step.finished_at.isoformat() if step.finished_at else None,
    }


def serialize_sluvo_agent_run(run: SluvoAgentRun) -> Dict[str, Any]:
    return {
        "id": encode_id(run.id),
        "projectId": encode_id(run.project_id),
        "canvasId": encode_id(run.canvas_id),
        "sessionId": encode_id(run.session_id) if run.session_id else None,
        "targetNodeId": encode_id(run.target_node_id) if run.target_node_id else None,
        "userId": encode_id(run.user_id),
        "teamId": encode_id(run.team_id),
        "title": run.title,
        "goal": run.goal,
        "sourceSurface": run.source_surface,
        "status": run.status,
        "mode": run.mode,
        "approvalPolicy": _json_load(run.approval_policy_json, {}),
        "contextSnapshot": _json_load(run.context_snapshot_json, {}),
        "summary": _json_load(run.summary_json, {}),
        "createdAt": run.created_at.isoformat() if run.created_at else None,
        "updatedAt": run.updated_at.isoformat() if run.updated_at else None,
        "finishedAt": run.finished_at.isoformat() if run.finished_at else None,
    }


def _serialize_agent_run_timeline(session: Session, run: SluvoAgentRun) -> Dict[str, Any]:
    steps = session.exec(
        select(SluvoAgentStep)
        .where(SluvoAgentStep.run_id == run.id)
        .order_by(SluvoAgentStep.order_index.asc(), SluvoAgentStep.id.asc())
    ).all()
    session_item = session.get(SluvoAgentSession, run.session_id) if run.session_id else None
    events = []
    if session_item:
        session_events = session.exec(
            select(SluvoAgentEvent)
            .where(SluvoAgentEvent.session_id == session_item.id)
            .order_by(SluvoAgentEvent.sequence_no.asc(), SluvoAgentEvent.id.asc())
        ).all()
        events = [serialize_sluvo_agent_event(item) for item in session_events]
    return {
        "run": serialize_sluvo_agent_run(run),
        "steps": [serialize_sluvo_agent_step(session, item) for item in steps],
        "events": events,
        "latestSession": serialize_sluvo_agent_session(session_item) if session_item else None,
    }


def serialize_sluvo_agent_template(template: SluvoAgentTemplate) -> Dict[str, Any]:
    return {
        "id": encode_id(template.id),
        "ownerUserId": encode_id(template.owner_user_id),
        "teamId": encode_id(template.team_id),
        "name": template.name,
        "description": template.description,
        "avatarUrl": template.avatar_url,
        "coverUrl": template.cover_url,
        "profileKey": template.profile_key,
        "modelCode": normalize_sluvo_agent_model_code(template.model_code),
        "rolePrompt": template.role_prompt,
        "useCases": _json_load(template.use_cases_json, []),
        "inputTypes": _json_load(template.input_types_json, []),
        "outputTypes": _json_load(template.output_types_json, []),
        "tools": _json_load(template.tools_json, []),
        "approvalPolicy": _json_load(template.approval_policy_json, {}),
        "examples": _json_load(template.examples_json, []),
        "memory": _json_load(template.memory_json, {}),
        "status": template.status,
        "forkedFromPublicationId": encode_id(template.forked_from_publication_id) if template.forked_from_publication_id else None,
        "createdAt": template.created_at.isoformat() if template.created_at else None,
        "updatedAt": template.updated_at.isoformat() if template.updated_at else None,
    }


def _serialize_agent_session_timeline(
    session: Session,
    session_item: SluvoAgentSession,
    *,
    event_limit: int = 8,
    action_limit: int = 5,
) -> Dict[str, Any]:
    events = session.exec(
        select(SluvoAgentEvent)
        .where(SluvoAgentEvent.session_id == session_item.id)
        .order_by(SluvoAgentEvent.sequence_no.desc(), SluvoAgentEvent.id.desc())
        .limit(max(1, int(event_limit or 8)))
    ).all()
    actions = session.exec(
        select(SluvoAgentAction)
        .where(SluvoAgentAction.session_id == session_item.id)
        .order_by(SluvoAgentAction.updated_at.desc(), SluvoAgentAction.id.desc())
        .limit(max(1, int(action_limit or 5)))
    ).all()
    ordered_events = list(reversed(events))
    ordered_actions = list(reversed(actions))
    latest_action = actions[0] if actions else None
    pending_action = next((item for item in actions if item.status in {"proposed", "approved", "failed"}), None)
    return {
        "session": serialize_sluvo_agent_session(session_item),
        "events": [serialize_sluvo_agent_event(item) for item in ordered_events],
        "actions": [serialize_sluvo_agent_action(item) for item in ordered_actions],
        "latestAction": serialize_sluvo_agent_action(latest_action) if latest_action else None,
        "pendingAction": serialize_sluvo_agent_action(pending_action) if pending_action else None,
    }


def serialize_sluvo_community_agent_with_session(
    session: Session,
    item: SluvoCommunityAgent,
    *,
    detail: bool = False,
) -> Dict[str, Any]:
    owner = session.get(User, item.owner_user_id)
    payload = {
        "id": encode_id(item.id),
        "sourceAgentId": encode_id(item.source_agent_id),
        "title": item.title,
        "description": item.description,
        "coverUrl": item.cover_url,
        "tags": _json_load(item.tags_json, []),
        "status": item.status,
        "author": {
            "id": encode_id(owner.id),
            "nickname": owner.nickname,
            "avatarUrl": owner.avatar_url,
        } if owner else None,
        "viewCount": int(item.view_count or 0),
        "forkCount": int(item.fork_count or 0),
        "publishedAt": item.published_at.isoformat() if item.published_at else None,
        "updatedAt": item.updated_at.isoformat() if item.updated_at else None,
    }
    if detail:
        payload["template"] = _json_load(item.template_snapshot_json, {})
    return payload


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
    include_deleted: bool = False,
) -> tuple[SluvoProject, Optional[SluvoProjectMember]]:
    project = session.get(SluvoProject, project_id) if include_deleted else _require_active_project(session, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Sluvo 项目不存在")
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
    include_deleted: bool = False,
) -> List[Dict[str, Any]]:
    deleted_condition = SluvoProject.deleted_at != None if include_deleted else SluvoProject.deleted_at == None
    projects = session.exec(
        select(SluvoProject).where(SluvoProject.team_id == team.id, deleted_condition).order_by(SluvoProject.updated_at.desc())
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
        publication = get_sluvo_project_community_publication(session, project.id)
        result.append(serialize_sluvo_project(project, member.role if member else None, first_image_url, publication))
    return result


def get_sluvo_project_bundle(session: Session, project: SluvoProject, member: Optional[SluvoProjectMember]) -> Dict[str, Any]:
    canvas = get_or_create_main_canvas(session, project)
    first_image_url = get_sluvo_project_first_image_url(session, project.id)
    publication = get_sluvo_project_community_publication(session, project.id)
    return {
        "project": serialize_sluvo_project(project, member.role if member else None, first_image_url, publication),
        "canvas": serialize_sluvo_canvas(canvas),
    }


def list_sluvo_community_canvases(session: Session, *, limit: int = 24, sort: str = "latest") -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 24), 60))
    order_by = SluvoCommunityCanvas.fork_count.desc() if str(sort or "").lower() == "popular" else SluvoCommunityCanvas.published_at.desc()
    items = session.exec(
        select(SluvoCommunityCanvas)
        .where(SluvoCommunityCanvas.status == SLUVO_COMMUNITY_CANVAS_STATUS_PUBLISHED)
        .order_by(order_by, SluvoCommunityCanvas.id.desc())
        .limit(limit)
    ).all()
    return [serialize_sluvo_community_canvas_with_session(session, item) for item in items]


def list_sluvo_agent_templates(session: Session, *, user: User, team: Team) -> List[Dict[str, Any]]:
    items = session.exec(
        select(SluvoAgentTemplate)
        .where(
            SluvoAgentTemplate.team_id == team.id,
            SluvoAgentTemplate.owner_user_id == user.id,
            SluvoAgentTemplate.deleted_at == None,
        )
        .order_by(SluvoAgentTemplate.updated_at.desc(), SluvoAgentTemplate.id.desc())
    ).all()
    return [serialize_sluvo_agent_template(item) for item in items]


def list_sluvo_project_agent_sessions(
    session: Session,
    *,
    project: SluvoProject,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 12), 40))
    items = session.exec(
        select(SluvoAgentSession)
        .where(SluvoAgentSession.project_id == project.id)
        .order_by(SluvoAgentSession.updated_at.desc(), SluvoAgentSession.id.desc())
        .limit(limit)
    ).all()
    return [_serialize_agent_session_timeline(session, item) for item in items]


def list_sluvo_project_agent_runs(
    session: Session,
    *,
    project: SluvoProject,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 12), 40))
    items = session.exec(
        select(SluvoAgentRun)
        .where(SluvoAgentRun.project_id == project.id)
        .order_by(SluvoAgentRun.updated_at.desc(), SluvoAgentRun.id.desc())
        .limit(limit)
    ).all()
    return [_serialize_agent_run_timeline(session, item) for item in items]


def require_sluvo_agent_run(session: Session, run_id: int) -> SluvoAgentRun:
    run = session.get(SluvoAgentRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Sluvo Agent Run 不存在")
    return run


def require_sluvo_agent_step(session: Session, step_id: int) -> SluvoAgentStep:
    step = session.get(SluvoAgentStep, step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Sluvo Agent Step 不存在")
    return step


def get_sluvo_agent_run_timeline(session: Session, run: SluvoAgentRun) -> Dict[str, Any]:
    return _serialize_agent_run_timeline(session, run)


def _agent_run_prompt(goal: str, context_snapshot: Dict[str, Any]) -> str:
    selected_nodes = context_snapshot.get("selectedNodes") if isinstance(context_snapshot, dict) else []
    node_lines = []
    if isinstance(selected_nodes, list):
        for item in selected_nodes[:6]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "未命名节点").strip()
            prompt = str(item.get("prompt") or "").strip()
            node_lines.append(f"- {title}: {prompt[:180]}")
    source = "\n".join(node_lines) or "暂无选区，按项目画布目标展开。"
    previous = context_snapshot.get("previousArtifacts") if isinstance(context_snapshot, dict) else []
    artifact_lines = []
    if isinstance(previous, list):
        for item in previous[:6]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "上一步产物").strip()
            body = str(item.get("body") or "").strip()
            if body:
                artifact_lines.append(f"- {title}: {body[:420]}")
    artifact_context = "\n".join(artifact_lines) or "暂无已生成产物。"
    media_config = _agent_media_config(context_snapshot) if isinstance(context_snapshot, dict) else {}
    duration_line = ""
    if media_config:
        duration_mode = "1分钟以内" if media_config.get("durationMode") == "under_60s" else "大于1分钟"
        duration_line = f"\n\n全局配置：成片时长 {duration_mode} / {media_config.get('durationSeconds')} 秒；图片 {media_config.get('image', {}).get('model_code')} {media_config.get('image', {}).get('aspect_ratio')}；视频 {media_config.get('video', {}).get('model_code')} {media_config.get('video', {}).get('resolution')}。"
    return f"{goal.strip()}\n\n画布上下文：\n{source}\n\n已生成产物：\n{artifact_context}{duration_line}"


def _agent_run_context_count(context_snapshot: Dict[str, Any]) -> int:
    selected = context_snapshot.get("selectedNodes") if isinstance(context_snapshot, dict) else []
    return len(selected) if isinstance(selected, list) else 0


def _agent_run_previous_artifacts(session: Session, run: SluvoAgentRun, limit: int = 8) -> List[Dict[str, Any]]:
    artifacts = session.exec(
        select(SluvoAgentArtifact)
        .where(SluvoAgentArtifact.run_id == run.id)
        .order_by(SluvoAgentArtifact.id.asc())
    ).all()
    result: List[Dict[str, Any]] = []
    for artifact in artifacts:
        if len(result) >= limit:
            break
        payload = _json_load(artifact.payload_json, {})
        body = str(payload.get("body") or payload.get("prompt") or "").strip()
        if not body:
            continue
        result.append({
            "title": artifact.title,
            "artifactType": artifact.artifact_type,
            "body": _compact_story_source(body, 1000),
        })
    return result


def _agent_run_origin(context_snapshot: Dict[str, Any]) -> tuple[float, float]:
    selected = context_snapshot.get("selectedNodes") if isinstance(context_snapshot, dict) else []
    if isinstance(selected, list):
        return _agent_patch_origin(selected)
    return 180.0, 180.0


def _classify_agent_goal(goal: str) -> Dict[str, str]:
    text = re.sub(r"\s+", " ", str(goal or "").strip())
    lower = text.lower()
    question_markers = ("?", "？", "是什么", "是谁", "怎么", "如何", "为什么", "能不能", "可以吗", "介绍", "说明")
    creative_markers = ("故事", "剧本", "分镜", "角色", "场景", "道具", "镜头", "短片", "动画", "漫画", "漫剧", "生成", "画面", "剧情")
    script_markers = ("第", "幕", "场", "镜", "旁白", "对白", "台词", "内景", "外景", "角色：", "场景：", "镜头")
    if not text:
        return {"intent": "question", "label": "询问", "reason": "空输入"}
    is_question = text.endswith(("?", "？")) or any(marker in text for marker in question_markers)
    has_creative = any(marker in text for marker in creative_markers)
    if is_question and not has_creative:
        return {"intent": "question", "label": "询问", "reason": "普通问题"}
    if any(marker in text for marker in script_markers) or len(text) >= 160:
        return {"intent": "script", "label": "剧本", "reason": "包含剧本/镜头结构"}
    return {"intent": "inspiration", "label": "灵感", "reason": "创作灵感或简短目标"}


def _agent_question_answer(goal: str) -> str:
    text = str(goal or "").strip()
    if re.search(r"(你是谁|你是誰|who are you)", text, flags=re.IGNORECASE):
        return "我是 Sluvo 画布里的创作总监，负责理解你的输入，判断它是普通询问、创作灵感还是已有剧本。普通问题我会直接回答；创作灵感我会先扩成剧本；已有剧本我会继续拆角色、场景、道具、分镜和生成任务。"
    return f"我先按普通询问处理：{text}\n\n如果你想进入创作流程，可以直接输入一个灵感或贴一段剧本，我会先识别意图，再决定是否扩写剧本、提取角色/场景/道具或继续做分镜。"


def _story_title_from_goal(goal: str) -> str:
    source = re.sub(r"\s+", "", str(goal or "").strip())
    source = re.sub(r"[#*_`《》\"“”'，。！？、：；,.!?;:]", "", source)
    if not source:
        return "未命名故事"
    if len(source) <= 12:
        return source
    return source[:12]


def _story_mood_from_goal(goal: str) -> str:
    text = str(goal or "")
    if any(word in text for word in ("雨", "夜", "凌晨", "霓虹")):
        return "潮湿、低照度、带一点危险感和都市悬疑感"
    if any(word in text for word in ("校园", "少年", "夏")):
        return "青春、明亮，但有尚未说出口的秘密"
    if any(word in text for word in ("废墟", "末日", "逃")):
        return "压迫、荒凉、动作节奏强"
    return "保留原始灵感的情绪，把它转成可被镜头捕捉的悬念"


def _story_scene_anchor_from_goal(goal: str) -> str:
    text = str(goal or "")
    if "迈巴赫" in text:
        return "雨夜街口、黑色迈巴赫车内外、被雨水拉长的车灯反光"
    if "雨" in text or "夜" in text:
        return "雨夜街道、昏暗灯牌、湿冷反光的路面"
    if "校园" in text:
        return "放学后的校园、走廊、操场边缘或天台"
    return "从输入中最有画面感的地点建立主场景，并固定时间、天气和光线"


def _story_prop_from_goal(goal: str) -> str:
    text = str(goal or "")
    if "迈巴赫" in text:
        return "黑色迈巴赫、后座半开的车窗、车内冷光、被雨水打湿的车门把手"
    if "信号" in text:
        return "异常信号、手机屏幕、闪烁的定位点"
    if "钥匙" in text:
        return "钥匙、门禁卡或能打开秘密空间的小物件"
    return "提取输入里最能推动剧情的物件，作为角色行动和镜头特写的核心"


def _story_protagonist_from_goal(goal: str) -> str:
    text = str(goal or "")
    if any(word in text for word in ("少年", "男孩", "女孩", "少女")):
        return "一个被夜色和秘密推着向前的年轻主角"
    if "迈巴赫" in text:
        return "一个在雨夜撞见豪车秘密的人，身份可以是代驾、学生、记者或被追踪者"
    return "一个必须在短时间内做选择的人，目标要和输入中的核心意象直接相关"


def _story_concept_from_goal(goal: str) -> str:
    title = _story_title_from_goal(goal)
    if "迈巴赫" in goal:
        return f"雨夜里，一辆不该出现的迈巴赫停在主角面前。它像邀请，也像陷阱。主角必须弄清车里藏着的人、信息或交易，才知道自己是旁观者还是已经被卷入局中。"
    return f"围绕「{goal.strip() or title}」建立一个可拍摄的短片开端：主角先被一个强画面吸引，随后发现它背后有更具体的目标、阻碍和危险。"


def _story_scene_from_goal(goal: str) -> str:
    title = _story_title_from_goal(goal)
    scene = _story_scene_anchor_from_goal(goal)
    prop = _story_prop_from_goal(goal)
    protagonist = _story_protagonist_from_goal(goal)
    mood = _story_mood_from_goal(goal)
    return (
        f"### 场 1：{scene}\n"
        f"雨声或环境声压低城市的底噪。{protagonist}停在画面边缘，注意到{prop}。镜头先不解释原因，只让观众看到主角的迟疑。\n\n"
        f"### 场 2：接近\n"
        "主角试图绕开，却发现这件事和自己有关：一条消息、一个熟悉的名字、或车内一瞬间露出的影子，把主角拉回现场。"
        f"画面情绪保持{mood}。\n\n"
        f"### 场 3：转折\n"
        f"当主角靠近「{title}」的核心线索时，车灯、手机或环境突然变化。主角意识到这不是偶遇，而是有人故意让自己看见。"
    )


def _build_script_seed(goal: str, context_snapshot: Dict[str, Any], model_code: str) -> str:
    classification = context_snapshot.get("intent") if isinstance(context_snapshot, dict) else {}
    intent = classification.get("intent") if isinstance(classification, dict) else "inspiration"
    source = _compact_story_source(goal, 900)
    title = _story_title_from_goal(source)
    if intent == "script":
        return (
            f"# 《{title}》剧本整理\n\n"
            "## 故事核心\n"
            f"{source}\n\n"
            "## 可拍摄场次\n"
            f"1. 开场：用一个强画面建立「{title}」的地点、时间和情绪。\n"
            "2. 对抗：让主角在具体动作中遭遇阻力，冲突需要能被镜头看见。\n"
            "3. 转折：用人物选择、关键道具或环境变化留下下一场的钩子。\n\n"
            "## 下一步拆解\n"
            "从这版剧本继续提取角色、场景、道具和分镜。"
        )
    return (
        f"# 《{title}》短片剧本草案\n\n"
        f"## 概念\n{_story_concept_from_goal(source)}\n\n"
        "## 剧本\n"
        f"{_story_scene_from_goal(source)}\n\n"
        "## 继续拆解锚点\n"
        f"- 主角：{_story_protagonist_from_goal(source)}\n"
        f"- 场景：{_story_scene_anchor_from_goal(source)}\n"
        f"- 道具：{_story_prop_from_goal(source)}\n"
        f"- 情绪：{_story_mood_from_goal(source)}"
    )


SLUVO_AGENT_WORKFLOW_SPECS = [
    {
        "stepKey": "onboarding",
        "stage": "overview",
        "groupKey": "overview",
        "groupLabel": "总览",
        "agentName": "Onboarding Agent",
        "agentProfile": "onboarding",
        "title": "确认创作目标与全局配置",
        "completed": "已确认创作目标、时长和全局生成配置",
        "next": "接下来 Scriptwriter Agent 会生成或整理剧本正文",
        "question": "灵感/剧本、时长和全局配置是否正确？",
        "artifacts": [("需求规划", "planning_brief", "readonly")],
    },
    {
        "stepKey": "scriptwriter",
        "stage": "script",
        "groupKey": "script",
        "groupLabel": "剧本",
        "agentName": "Scriptwriter Agent",
        "agentProfile": "scriptwriter",
        "title": "生成剧本正文",
        "completed": "已完成剧本正文",
        "next": "接下来 Visual Asset Agent 会提取角色、场景和道具",
        "question": "剧本正文是否可以继续拆解角色、场景和道具？",
        "artifacts": [("剧本正文", "script_body", "auto_canvas")],
    },
    {
        "stepKey": "asset_artist",
        "stage": "assets",
        "groupKey": "assets",
        "groupLabel": "角色/场景/道具",
        "agentName": "Visual Asset Agent",
        "agentProfile": "character_artist",
        "title": "提取角色、场景和道具",
        "completed": "已完成角色、场景和道具提取",
        "next": "接下来 Storyboard Artist Agent 会生成分镜表格",
        "question": "角色、场景、道具及对应图片占位是否可以继续？",
        "artifacts": [
            ("角色设定", "character_brief", "auto_canvas"),
            ("角色图占位", "character_image_placeholder", "auto_canvas"),
            ("场景设定", "scene_brief", "auto_canvas"),
            ("场景图占位", "scene_image_placeholder", "auto_canvas"),
            ("道具设定", "prop_brief", "auto_canvas"),
            ("道具图占位", "prop_image_placeholder", "auto_canvas"),
        ],
    },
    {
        "stepKey": "storyboard_artist",
        "stage": "storyboard",
        "groupKey": "storyboard",
        "groupLabel": "分镜",
        "agentName": "Storyboard Artist Agent",
        "agentProfile": "storyboard_artist",
        "title": "生成分镜表格",
        "completed": "已完成分镜表格",
        "next": "接下来 Image Generator Agent 会生成分镜图占位",
        "question": "分镜表格是否可以进入分镜图生成？",
        "artifacts": [("分镜表格", "storyboard_table", "auto_canvas")],
    },
    {
        "stepKey": "image_generator",
        "stage": "image",
        "groupKey": "image",
        "groupLabel": "图片",
        "agentName": "Image Generator Agent",
        "agentProfile": "storyboard_artist",
        "title": "生成分镜图",
        "completed": "已完成分镜图占位",
        "next": "接下来 Video Generator Agent 会根据分镜图生成分镜视频",
        "question": "分镜图提示和占位是否可以进入视频生成？",
        "artifacts": [("分镜图占位", "storyboard_image_placeholder", "auto_canvas")],
    },
    {
        "stepKey": "video_generator",
        "stage": "video",
        "groupKey": "video",
        "groupLabel": "视频",
        "agentName": "Video Generator Agent",
        "agentProfile": "video_generator",
        "title": "生成分镜视频与合成视频",
        "completed": "已创建分镜视频和合成视频任务",
        "next": "确认后提交生成任务并整理成片",
        "question": "是否确认消耗灵感值并提交分镜视频和合成视频生成？",
        "artifacts": [("分镜视频占位", "shot_video_placeholder", "requires_cost_confirmation"), ("合成视频占位", "merged_video_placeholder", "requires_cost_confirmation")],
    },
]


def _agent_workflow_public_specs() -> List[Dict[str, Any]]:
    return [
        {
            "stepKey": item["stepKey"],
            "stage": item["stage"],
            "groupKey": item.get("groupKey") or item["stage"],
            "groupLabel": item.get("groupLabel") or item["stage"],
            "agentName": item["agentName"],
            "agentProfile": item["agentProfile"],
            "title": item["title"],
            "completed": item["completed"],
            "next": item["next"],
            "question": item["question"],
            "artifacts": [
                {"title": artifact_title, "artifactType": artifact_type, "writePolicy": policy}
                for artifact_title, artifact_type, policy in item["artifacts"]
            ],
        }
        for item in SLUVO_AGENT_WORKFLOW_SPECS
    ]


def _agent_template_for_step(session: Session, context_snapshot: Dict[str, Any], step_key: str) -> Optional[SluvoAgentTemplate]:
    assignments = context_snapshot.get("agentAssignments") if isinstance(context_snapshot, dict) else {}
    if not isinstance(assignments, dict):
        return None
    template_ref = str(assignments.get(step_key) or "").strip()
    template_id = _decode_optional_safe(template_ref)
    if not template_id:
        return None
    template = session.get(SluvoAgentTemplate, template_id)
    if template and template.deleted_at is None:
        return template
    return None


def _resolve_agent_for_workflow_step(
    session: Session,
    *,
    context_snapshot: Dict[str, Any],
    spec: Dict[str, Any],
    order_index: int,
    root_template: Optional[SluvoAgentTemplate],
    model_code: str,
) -> Dict[str, Any]:
    step_template = _agent_template_for_step(session, context_snapshot, str(spec["stepKey"]))
    active_template = step_template or (root_template if order_index == 0 else None)
    return {
        "stepKey": str(spec["stepKey"]),
        "stage": str(spec["stage"]),
        "agentName": active_template.name if active_template else str(spec["agentName"]),
        "agentProfile": active_template.profile_key if active_template else str(spec["agentProfile"]),
        "agentTemplateId": encode_id(active_template.id) if active_template else None,
        "agentTemplate": active_template,
        "modelCode": normalize_sluvo_agent_model_code(active_template.model_code if active_template else model_code),
        "source": "custom" if active_template else "official",
    }


def _resolved_agent_team(
    session: Session,
    *,
    context_snapshot: Dict[str, Any],
    root_template: Optional[SluvoAgentTemplate],
    model_code: str,
) -> List[Dict[str, Any]]:
    team: List[Dict[str, Any]] = []
    for index, spec in enumerate(SLUVO_AGENT_WORKFLOW_SPECS):
        resolved = _resolve_agent_for_workflow_step(
            session,
            context_snapshot=context_snapshot,
            spec=spec,
            order_index=index,
            root_template=root_template,
            model_code=model_code,
        )
        team.append({key: value for key, value in resolved.items() if key != "agentTemplate"})
    return team


def _workflow_step_count(session: Session, run: SluvoAgentRun) -> int:
    workflow_keys = {str(item["stepKey"]) for item in SLUVO_AGENT_WORKFLOW_SPECS}
    steps = session.exec(select(SluvoAgentStep).where(SluvoAgentStep.run_id == run.id)).all()
    return len([step for step in steps if step.step_key in workflow_keys])


def _agent_run_artifact_count(session: Session, run: SluvoAgentRun) -> int:
    return len(session.exec(select(SluvoAgentArtifact).where(SluvoAgentArtifact.run_id == run.id)).all())


def _append_agent_workflow_step(
    session: Session,
    *,
    run: SluvoAgentRun,
    user: User,
    spec_index: int,
    goal: str,
    context_snapshot: Dict[str, Any],
    root_template: Optional[SluvoAgentTemplate],
    model_code: str,
    feedback: str = "",
) -> List[SluvoAgentArtifact]:
    spec = SLUVO_AGENT_WORKFLOW_SPECS[spec_index]
    resolved = _resolve_agent_for_workflow_step(
        session,
        context_snapshot=context_snapshot,
        spec=spec,
        order_index=spec_index,
        root_template=root_template,
        model_code=model_code,
    )
    next_agent_name = None
    if spec_index + 1 < len(SLUVO_AGENT_WORKFLOW_SPECS):
        next_spec = SLUVO_AGENT_WORKFLOW_SPECS[spec_index + 1]
        next_agent = _resolve_agent_for_workflow_step(
            session,
            context_snapshot=context_snapshot,
            spec=next_spec,
            order_index=spec_index + 1,
            root_template=root_template,
            model_code=model_code,
        )
        next_agent_name = next_agent["agentName"]
    if spec_index > 0:
        previous_spec = SLUVO_AGENT_WORKFLOW_SPECS[spec_index - 1]
        _append_sluvo_run_event(
            session,
            run=run,
            role="agent",
            event_type="agent_handoff",
            payload={
                "from_agent": previous_spec["stepKey"],
                "to_agent": spec["stepKey"],
                "message": f"@{previous_spec['stepKey']} 邀请 @{spec['stepKey']} 加入了群聊",
            },
        )
    step = _create_agent_run_step(
        session,
        run=run,
        step_key=str(spec["stepKey"]),
        agent_name=str(resolved["agentName"]),
        agent_profile=str(resolved["agentProfile"]),
        model_code=str(resolved["modelCode"]),
        title=str(spec["title"]),
        order_index=spec_index,
        agent_template_id=_decode_optional_safe(str(resolved.get("agentTemplateId") or "")),
        input_payload={
            "goal": goal,
            "content": feedback,
            "contextCount": _agent_run_context_count(context_snapshot or {}),
            "stage": spec["stage"],
            "groupKey": spec.get("groupKey") or spec["stage"],
            "groupLabel": spec.get("groupLabel") or spec["stage"],
            "handoffFrom": SLUVO_AGENT_WORKFLOW_SPECS[spec_index - 1]["agentName"] if spec_index > 0 else None,
            "handoffTo": resolved["agentName"],
        },
    )
    artifact_goal = goal
    clean_feedback = str(feedback or "").strip()
    if clean_feedback and clean_feedback not in {"继续", "继续下一步", "满意，继续下一步"}:
        artifact_goal = f"{goal}\n\n用户确认 / 补充：{clean_feedback}"
    artifacts = []
    for artifact_title, artifact_type, policy in spec["artifacts"]:
        generation_params = _agent_generation_params_for_artifact(artifact_type, context_snapshot or {})
        artifacts.append(
            _create_agent_run_artifact(
                session,
                run=run,
                step=step,
                title=artifact_title,
                artifact_type=artifact_type,
                body=_artifact_body(artifact_type, artifact_goal, context_snapshot or {}, str(resolved["modelCode"])),
                write_policy=policy,
                preview={
                    "estimatedWrite": "canvas_node",
                    "estimatePoints": _agent_generation_estimate_points(artifact_type, generation_params),
                    "generationParams": generation_params,
                },
            )
        )
    _finish_agent_run_step(
        session,
        step,
        output={
            "artifactCount": len(artifacts),
            "stage": spec["stage"],
            "groupKey": spec.get("groupKey") or spec["stage"],
            "groupLabel": spec.get("groupLabel") or spec["stage"],
            "completed": spec["completed"],
            "next": spec["next"],
            "question": spec["question"],
            "handoffTo": next_agent_name,
        },
        status="succeeded",
    )
    session.commit()
    _write_agent_run_artifacts_to_canvas(session, run=run, user=user, artifacts=artifacts)
    _append_sluvo_run_event(
        session,
        run=run,
        role="agent",
        event_type="run_progress",
        payload={
            "current_agent": spec["stepKey"],
            "currentAgent": spec["stepKey"],
            "stage": spec["stage"],
            "groupKey": spec.get("groupKey") or spec["stage"],
            "groupLabel": spec.get("groupLabel") or spec["stage"],
            "progress": min((spec_index + 1) / max(len(SLUVO_AGENT_WORKFLOW_SPECS), 1), 1),
        },
    )
    planning_artifact = next((artifact for artifact in artifacts if artifact.artifact_type == "planning_brief"), None)
    planning_payload = _json_load(planning_artifact.payload_json, {}) if planning_artifact else {}
    message_content = str(planning_payload.get("body") or "").strip() if planning_payload else ""
    if not message_content:
        message_content = f"{spec['completed']}：{spec['next']}"
    _append_sluvo_run_event(
        session,
        run=run,
        role="agent",
        event_type="run_message",
        payload={
            "agent": spec["stepKey"],
            "agentName": resolved["agentName"],
            "stage": spec["stage"],
            "groupKey": spec.get("groupKey") or spec["stage"],
            "groupLabel": spec.get("groupLabel") or spec["stage"],
            "content": message_content,
            "stepId": encode_id(step.id),
        },
    )
    return artifacts


def _build_agent_planning_brief(goal: str, context_snapshot: Dict[str, Any]) -> str:
    selected_nodes = context_snapshot.get("selectedNodes") if isinstance(context_snapshot, dict) else []
    selected_count = len(selected_nodes) if isinstance(selected_nodes, list) else 0
    clean_goal = goal.strip()
    media_config = _agent_media_config(context_snapshot)
    duration_mode = str(media_config.get("durationMode") or "under_60s")
    duration_seconds = int(media_config.get("durationSeconds") or media_config.get("video", {}).get("duration") or 45)
    duration_label = "1分钟以内" if duration_mode == "under_60s" else f"大于1分钟，目标约 {duration_seconds} 秒"
    context_line = f"已读取 {selected_count} 个选中节点作为上下文。" if selected_count else "当前先以你刚发送的灵感作为创作起点。"
    return (
        "我先整理这次任务的总览，不会立刻把完整剧本写进画布。\n\n"
        f"1. 输入目标：{clean_goal}\n"
        f"2. 上下文：{context_line}\n"
        f"3. 时长：{duration_label}\n"
        f"4. 全局图片：{media_config['image'].get('model_code')} / {media_config['image'].get('resolution')} / {media_config['image'].get('aspect_ratio')}\n"
        f"5. 全局视频：{media_config['video'].get('model_code')} / {media_config['video'].get('resolution')} / {media_config['video'].get('aspect_ratio')}\n"
        "6. 执行顺序：剧本正文 → 角色/场景/道具 → 分镜表格 → 分镜图 → 分镜视频 → 合成视频。\n"
        "7. 需要你确认：输入理解、时长和全局配置是否需要补充。"
    )


def _agent_media_config(context_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    raw = context_snapshot.get("onboardingConfig") if isinstance(context_snapshot, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    image = raw.get("image") if isinstance(raw.get("image"), dict) else {}
    video = raw.get("video") if isinstance(raw.get("video"), dict) else {}
    duration_mode = str(raw.get("durationMode") or raw.get("duration_mode") or "under_60s").strip() or "under_60s"
    duration_seconds = int(raw.get("durationSeconds") or raw.get("duration_seconds") or video.get("duration") or 45)
    if duration_mode == "under_60s":
        duration_seconds = min(max(duration_seconds, 5), 60)
    else:
        duration_seconds = max(duration_seconds, 61)
    return {
        "durationMode": duration_mode,
        "durationSeconds": duration_seconds,
        "image": {
            "model_code": str(image.get("model_code") or raw.get("image_model_code") or "nano-banana-pro").strip(),
            "generation_type": "text_to_image",
            "resolution": str(image.get("resolution") or raw.get("image_resolution") or "2k").strip().lower(),
            "aspect_ratio": str(image.get("aspect_ratio") or raw.get("image_aspect_ratio") or "16:9").strip(),
            "reference_images": [],
        },
        "video": {
            "model_code": str(video.get("model_code") or raw.get("video_model_code") or "seedance_20_fast").strip(),
            "generation_type": str(video.get("generation_type") or raw.get("video_generation_type") or "text_to_video").strip(),
            "duration": duration_seconds,
            "resolution": str(video.get("resolution") or raw.get("video_resolution") or "720p").strip().lower(),
            "aspect_ratio": str(video.get("aspect_ratio") or raw.get("video_aspect_ratio") or "adaptive").strip(),
            "audio_enabled": bool(video.get("audio_enabled", raw.get("video_audio_enabled", False))),
            "real_person_mode": bool(video.get("real_person_mode", raw.get("video_real_person_mode", False))),
            "web_search": bool(video.get("web_search", raw.get("video_web_search", False))),
        },
    }


def _agent_image_estimate_points(params: Dict[str, Any]) -> int:
    model_code = str(params.get("model_code") or "").strip()
    resolution = str(params.get("resolution") or "2k").strip().lower()
    if model_code == "nano-banana-2-低价版":
        return {"1k": 2, "2k": 2, "4k": 3}.get(resolution, 2)
    if model_code == "nano-banana-2":
        return {"1k": 5, "2k": 6, "4k": 8}.get(resolution, 6)
    if model_code == "gpt-image-2-fast":
        return 3
    if model_code == "gpt-image-2":
        return {"1k": 12, "2k": 18, "4k": 28}.get(resolution, 18)
    return {"1k": 9, "2k": 11, "4k": 13}.get(resolution, 11)


def _agent_video_estimate_points(params: Dict[str, Any]) -> int:
    duration = max(int(params.get("duration") or 5), 1)
    resolution = str(params.get("resolution") or "720p").strip().lower()
    resolution_multiplier = {"480p": 0.8, "720p": 1.0, "1080p": 1.35, "2k": 1.8, "4k": 2.4}.get(resolution, 1.0)
    return max(int(round(duration * 4 * resolution_multiplier)), 1)


def _agent_generation_params_for_artifact(artifact_type: str, context_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    media_config = _agent_media_config(context_snapshot)
    if artifact_type in {"image_placeholder", "character_image_placeholder", "scene_image_placeholder", "prop_image_placeholder", "storyboard_image_placeholder"}:
        return media_config["image"]
    if artifact_type in {"video_placeholder", "shot_video_placeholder", "merged_video_placeholder"}:
        return media_config["video"]
    return {}


def _agent_generation_estimate_points(artifact_type: str, generation_params: Dict[str, Any]) -> int:
    if artifact_type in {"image_placeholder", "character_image_placeholder", "scene_image_placeholder", "prop_image_placeholder", "storyboard_image_placeholder"}:
        return _agent_image_estimate_points(generation_params)
    if artifact_type in {"video_placeholder", "shot_video_placeholder", "merged_video_placeholder"}:
        return _agent_video_estimate_points(generation_params)
    return 0


def _artifact_body(artifact_type: str, goal: str, context_snapshot: Dict[str, Any], model_code: str) -> str:
    prompt = _agent_run_prompt(goal, context_snapshot)
    if artifact_type == "planning_brief":
        return _build_agent_planning_brief(goal, context_snapshot)
    llm_body = _try_deepseek_agent_artifact_body(
        artifact_type=artifact_type,
        goal=goal,
        context_snapshot=context_snapshot,
        model_code=model_code,
    )
    if llm_body:
        return llm_body
    if artifact_type in {"text_node", "script_body"}:
        return _build_script_seed(goal, context_snapshot, model_code)
    if artifact_type == "report":
        return _agent_question_answer(goal)
    if artifact_type == "character_brief":
        return (
            "# 角色设定\n\n"
            f"## 主角\n{_story_protagonist_from_goal(goal)}。外观应能匹配「{_story_mood_from_goal(goal)}」的气质，动作目标围绕「{goal.strip()}」展开。\n\n"
            "## 对手 / 压力\n"
            "对手不一定马上露脸，可以先表现为车内影子、陌生来电、监控视角、追踪者或环境压力。\n\n"
            "## 一致性锚点\n"
            f"- 服装与色彩：贴合{_story_mood_from_goal(goal)}。\n"
            f"- 关键物件：{_story_prop_from_goal(goal)}。\n"
            "- 表演重点：先克制观察，再被迫行动。"
        )
    if artifact_type == "scene_brief":
        return (
            "# 场景设定\n\n"
            f"## 主场景\n{_story_scene_anchor_from_goal(goal)}。\n\n"
            "## 光线与空间\n"
            "使用低照度、局部高亮和前后景遮挡，让观众先看到线索，再看到人物反应。\n\n"
            "## 连续性锚点\n"
            f"- 情绪：{_story_mood_from_goal(goal)}。\n"
            f"- 核心道具：{_story_prop_from_goal(goal)}。\n"
            "- 镜头约束：湿润反光、近景表情、车窗/门缝/屏幕等框中框构图。"
        )
    if artifact_type == "prop_brief":
        return (
            "# 道具设定\n\n"
            f"## 核心道具\n{_story_prop_from_goal(goal)}。\n\n"
            "## 剧情功能\n"
            "道具不是背景装饰，而是让主角接近真相或陷入危险的触发器。\n\n"
            "## 特写建议\n"
            "- 水滴、反光、指纹、屏幕亮光或门把手动作。\n"
            "- 先给局部细节，再用反应镜头说明它对主角的意义。"
        )
    if artifact_type in {"storyboard_plan", "storyboard_table"}:
        return _build_storyboard_plan(prompt, model_code)
    if artifact_type == "prompt":
        return f"精修 Prompt\n{_build_first_frame_prompt(prompt)}"
    if artifact_type == "character_image_placeholder":
        return f"角色图生成提示：{_story_protagonist_from_goal(goal)}，保持{_story_mood_from_goal(goal)}气质，关键道具为{_story_prop_from_goal(goal)}。"
    if artifact_type == "scene_image_placeholder":
        return f"场景图生成提示：{_story_scene_anchor_from_goal(goal)}，低照度、局部高亮、空间层次清晰，氛围{_story_mood_from_goal(goal)}。"
    if artifact_type == "prop_image_placeholder":
        return f"道具图生成提示：{_story_prop_from_goal(goal)}，适合特写，细节清晰，能推动剧情。"
    if artifact_type in {"image_placeholder", "storyboard_image_placeholder"}:
        return _build_first_frame_prompt(prompt)
    if artifact_type in {"video_placeholder", "shot_video_placeholder"}:
        return _build_video_prompt(prompt)
    if artifact_type == "merged_video_placeholder":
        return f"合成视频任务：按已确认剧本、角色/场景/道具、分镜图和分镜视频顺序合成完整短片。\n\n{_build_video_prompt(prompt)}"
    return prompt


def _try_deepseek_agent_artifact_body(
    *,
    artifact_type: str,
    goal: str,
    context_snapshot: Dict[str, Any],
    model_code: str,
) -> Optional[str]:
    if not settings.DEEPSEEK_API_KEY:
        return None
    if artifact_type in {"image_placeholder", "character_image_placeholder", "scene_image_placeholder", "prop_image_placeholder", "storyboard_image_placeholder", "video_placeholder", "shot_video_placeholder", "merged_video_placeholder", "report", "planning_brief"}:
        return None
    type_labels = {
        "text_node": "短片剧本草案",
        "script_body": "剧本正文",
        "storyboard_plan": "故事结构或分镜计划",
        "storyboard_table": "分镜表格",
        "character_brief": "角色设定",
        "scene_brief": "场景设定",
        "prop_brief": "道具设定",
        "prompt": "首帧/视频生成提示词",
    }
    label = type_labels.get(artifact_type, "创作产物")
    selected_nodes = context_snapshot.get("selectedNodes") if isinstance(context_snapshot, dict) else []
    context_lines = []
    if isinstance(selected_nodes, list):
        for item in selected_nodes[:6]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "未命名节点").strip()
            content = str(item.get("prompt") or item.get("body") or item.get("content") or "").strip()
            if content:
                context_lines.append(f"- {title}: {content[:600]}")
    previous_artifacts = context_snapshot.get("previousArtifacts") if isinstance(context_snapshot, dict) else []
    if isinstance(previous_artifacts, list):
        for item in previous_artifacts[:6]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "上一步产物").strip()
            body = str(item.get("body") or "").strip()
            if body:
                context_lines.append(f"- {title}: {body[:900]}")
    context_text = "\n".join(context_lines) or "暂无上游节点。"
    try:
        payload = chat_json(
            model=normalize_sluvo_agent_model_code(model_code),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 Sluvo 画布 Agent Team 的创作成员。"
                        "请输出 JSON 对象，字段只有 body。body 是可直接写入画布文本节点的 Markdown 正文。"
                        "不要写模板说明、不要写占位指令、不要提模型、不要提“下一步由谁处理”。"
                        "必须围绕用户输入生成具体故事内容、角色/场景/道具或分镜信息。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"用户输入：{goal.strip()}\n"
                        f"当前要生成的产物类型：{label}\n"
                        f"上游上下文：\n{context_text}\n\n"
                        "要求：\n"
                        "1. 内容要具体，能被画面拍出来。\n"
                        "2. 如果是剧本草案，要包含故事概念、2-4 个场次或剧情段落、角色/场景/道具锚点。\n"
                        "3. 如果是角色/场景/道具设定，要从输入里提取具体名称、外观、功能和一致性锚点。\n"
                        "4. 如果是分镜计划，要列出镜号、景别、画面、动作、声音/情绪和生成提示。\n"
                    ),
                },
            ],
            thinking_enabled=normalize_sluvo_agent_model_code(model_code) == "deepseek-v4-pro",
            max_tokens=1800,
            temperature=0.36,
            route_tag="sluvo_agent_artifact",
        )
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    body = str(payload.get("body") or "").strip()
    if not body or len(body) < 24:
        return None
    forbidden = ("核心输入：", "故事钩子：保留用户原始表达", "模型：", "模板", "占位")
    if any(item in body for item in forbidden):
        return None
    return body[:16000]


def _create_agent_run_step(
    session: Session,
    *,
    run: SluvoAgentRun,
    step_key: str,
    agent_name: str,
    agent_profile: str,
    model_code: str,
    title: str,
    order_index: int,
    agent_template_id: Optional[int] = None,
    input_payload: Optional[Dict[str, Any]] = None,
) -> SluvoAgentStep:
    now = _utc_now()
    step = SluvoAgentStep(
        run_id=run.id,
        session_id=run.session_id,
        agent_template_id=agent_template_id,
        step_key=step_key,
        agent_name=agent_name,
        agent_profile=agent_profile,
        model_code=normalize_sluvo_agent_model_code(model_code),
        title=title,
        status="running",
        input_json=_json_dump(input_payload or {}),
        output_json="{}",
        error_json="{}",
        order_index=order_index,
        created_at=now,
        updated_at=now,
    )
    session.add(step)
    session.flush()
    return step


def _create_agent_run_artifact(
    session: Session,
    *,
    run: SluvoAgentRun,
    step: SluvoAgentStep,
    title: str,
    artifact_type: str,
    body: str,
    write_policy: str,
    status: str = "ready",
    preview: Optional[Dict[str, Any]] = None,
) -> SluvoAgentArtifact:
    now = _utc_now()
    artifact = SluvoAgentArtifact(
        run_id=run.id,
        step_id=step.id,
        title=title,
        artifact_type=artifact_type,
        status=status,
        payload_json=_json_dump({"body": body, "prompt": body}),
        preview_json=_json_dump(preview or {}),
        write_policy=write_policy,
        created_at=now,
        updated_at=now,
    )
    session.add(artifact)
    session.flush()
    return artifact


def _append_sluvo_run_event(
    session: Session,
    *,
    run: SluvoAgentRun,
    role: str,
    event_type: str,
    payload: Dict[str, Any],
) -> Optional[SluvoAgentEvent]:
    if not run.session_id:
        return None
    agent_session = session.get(SluvoAgentSession, run.session_id)
    if not agent_session:
        return None
    return append_sluvo_agent_event(
        session,
        agent_session=agent_session,
        role=role,
        event_type=event_type,
        payload={"runId": encode_id(run.id), "run_id": encode_id(run.id), "eventType": event_type, **(payload or {})},
    )


def _agent_run_node_payload(artifact: SluvoAgentArtifact, *, index: int, origin: tuple[float, float]) -> Dict[str, Any]:
    payload = _json_load(artifact.payload_json, {})
    preview = _json_load(artifact.preview_json, {})
    generation_params = preview.get("generationParams") if isinstance(preview.get("generationParams"), dict) else {}
    body = str(payload.get("body") or payload.get("prompt") or "").strip()
    x, y = origin
    position = {"x": x + (index % 2) * 360, "y": y + (index // 2) * 260}
    common = {
        "agentRunId": encode_id(artifact.run_id),
        "agentArtifactId": encode_id(artifact.id),
        "writePolicy": artifact.write_policy,
    }
    if artifact.artifact_type in {"image_placeholder", "character_image_placeholder", "scene_image_placeholder", "prop_image_placeholder", "storyboard_image_placeholder"}:
        return _agent_patch_node(
            client_id=f"agent-run-{artifact.run_id}-artifact-{artifact.id}",
            node_type="image",
            direct_type="image_unit",
            title=artifact.title,
            icon="▧",
            position=position,
            prompt=body,
            size={"width": 420, "height": 340},
            data={
                **common,
                "generationStatus": "waiting_confirmation",
                "generationMessage": "等待确认灵感值后生成图片",
                "imageEstimatePoints": int(preview.get("estimatePoints") or _agent_image_estimate_points(generation_params)),
                "imageParams": generation_params,
                "modelCode": generation_params.get("model_code"),
                "resolution": generation_params.get("resolution"),
                "aspectRatio": generation_params.get("aspect_ratio"),
            },
        )
    if artifact.artifact_type in {"video_placeholder", "shot_video_placeholder", "merged_video_placeholder"}:
        return _agent_patch_node(
            client_id=f"agent-run-{artifact.run_id}-artifact-{artifact.id}",
            node_type="video",
            direct_type="video_unit",
            title=artifact.title,
            icon="▣",
            position=position,
            prompt=body,
            size={"width": 420, "height": 340},
            data={
                **common,
                "generationStatus": "waiting_confirmation",
                "generationMessage": "等待确认灵感值后生成视频",
                "videoEstimatePoints": int(preview.get("estimatePoints") or _agent_video_estimate_points(generation_params)),
                "videoParams": generation_params,
                "modelCode": generation_params.get("model_code"),
                "generationType": generation_params.get("generation_type"),
                "duration": generation_params.get("duration"),
                "resolution": generation_params.get("resolution"),
                "aspectRatio": generation_params.get("aspect_ratio"),
            },
        )
    direct_type = "script_episode" if artifact.artifact_type == "script_body" else "storyboard_table" if artifact.artifact_type == "storyboard_table" else "prompt_note"
    width = 480 if direct_type in {"script_episode", "storyboard_table"} else 330
    height = 520 if direct_type in {"script_episode", "storyboard_table"} else 230
    return _agent_patch_node(
        client_id=f"agent-run-{artifact.run_id}-artifact-{artifact.id}",
        node_type="text",
        direct_type=direct_type,
        title=artifact.title,
        icon="✦",
        position=position,
        prompt=body,
        size={"width": width, "height": height},
        data=common,
    )


def _latest_agent_run_canvas_node(
    session: Session,
    run: SluvoAgentRun,
    *,
    exclude_artifact_ids: Optional[set[int]] = None,
) -> Optional[SluvoCanvasNode]:
    excluded = exclude_artifact_ids or set()
    previous_artifacts = session.exec(
        select(SluvoAgentArtifact)
        .where(SluvoAgentArtifact.run_id == run.id)
        .where(SluvoAgentArtifact.canvas_node_id != None)
        .order_by(SluvoAgentArtifact.id.desc())
    ).all()
    for artifact in previous_artifacts:
        if artifact.id in excluded or not artifact.canvas_node_id:
            continue
        node = session.get(SluvoCanvasNode, artifact.canvas_node_id)
        if node and node.deleted_at is None:
            return node
    return None


def _reuse_revision_canvas_nodes(session: Session, artifacts: List[SluvoAgentArtifact]) -> None:
    now = _utc_now()
    for artifact in artifacts:
        preview = _json_load(artifact.preview_json, {})
        if not preview.get("revision") or artifact.canvas_node_id:
            continue
        previous = session.exec(
            select(SluvoAgentArtifact)
            .where(SluvoAgentArtifact.run_id == artifact.run_id)
            .where(SluvoAgentArtifact.id != artifact.id)
            .where(SluvoAgentArtifact.artifact_type == artifact.artifact_type)
            .where(SluvoAgentArtifact.canvas_node_id != None)
            .order_by(SluvoAgentArtifact.id.desc())
        ).first()
        if not previous or not previous.canvas_node_id:
            continue
        node = session.get(SluvoCanvasNode, previous.canvas_node_id)
        if not node or node.deleted_at is not None:
            continue
        payload = _json_load(artifact.payload_json, {})
        body = str(payload.get("body") or payload.get("prompt") or "").strip()
        data = _json_load(node.data_json, {})
        if isinstance(data, dict):
            data.update({
                "agentArtifactId": encode_id(artifact.id),
                "prompt": body,
                "body": body,
                "title": artifact.title,
                "revisionSourceArtifactId": encode_id(previous.id),
            })
            node.data_json = _json_dump(data)
        node.title = artifact.title or node.title
        node.updated_at = now
        node.revision = int(node.revision or 1) + 1
        session.add(node)
        artifact.canvas_node_id = node.id
        artifact.status = "waiting_cost_confirmation" if artifact.write_policy == "requires_cost_confirmation" else "written"
        artifact.updated_at = now
        session.add(artifact)
    session.flush()


def _write_agent_run_artifacts_to_canvas(
    session: Session,
    *,
    run: SluvoAgentRun,
    user: User,
    artifacts: List[SluvoAgentArtifact],
) -> None:
    _reuse_revision_canvas_nodes(session, artifacts)
    writable = [item for item in artifacts if item.write_policy in {"auto_canvas", "requires_cost_confirmation"} and not item.canvas_node_id]
    if not writable:
        return
    canvas = _require_canvas(session, run.canvas_id)
    context_snapshot = _json_load(run.context_snapshot_json, {})
    previous_node = _latest_agent_run_canvas_node(
        session,
        run,
        exclude_artifact_ids={int(item.id or 0) for item in writable if item.id},
    )
    if previous_node:
        origin = (float(previous_node.position_x) + float(previous_node.width or 330) + 140, float(previous_node.position_y))
    else:
        origin = _agent_run_origin(context_snapshot)
    nodes = [_agent_run_node_payload(item, index=index, origin=origin) for index, item in enumerate(writable)]
    edges = []
    if previous_node and nodes:
        edges.append(_agent_patch_edge_from_node(encode_id(previous_node.id), nodes[0]["clientId"], "dependency", "上一步"))
    for index in range(1, len(nodes)):
        edges.append(_agent_patch_edge(nodes[index - 1]["clientId"], nodes[index]["clientId"], "dependency", "Agent 产物"))
    batch = SluvoCanvasBatchRequest(expectedRevision=canvas.revision, nodes=nodes, edges=edges)
    result = apply_sluvo_canvas_batch(
        session,
        canvas,
        batch,
        user=user,
        actor_type="agent",
        agent_session_id=run.session_id,
    )
    node_map: Dict[str, str] = {}
    for node in result.get("nodes", []):
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        client_id = str(data.get("clientId") or node.get("clientId") or "").strip()
        if client_id:
            node_map[client_id] = node.get("id")
    now = _utc_now()
    for artifact in writable:
        node_id = _decode_optional_safe(node_map.get(f"agent-run-{artifact.run_id}-artifact-{artifact.id}"))
        if node_id:
            artifact.canvas_node_id = node_id
            artifact.status = "waiting_cost_confirmation" if artifact.write_policy == "requires_cost_confirmation" else "written"
            artifact.updated_at = now
            session.add(artifact)
    session.commit()


def _finish_agent_run_step(session: Session, step: SluvoAgentStep, *, output: Optional[Dict[str, Any]] = None, status: str = "succeeded") -> None:
    now = _utc_now()
    step.status = status
    step.output_json = _json_dump(output or {})
    step.updated_at = now
    step.finished_at = now
    session.add(step)


def create_sluvo_agent_run(
    session: Session,
    *,
    project: SluvoProject,
    user: User,
    team: Team,
    canvas_id: Optional[int],
    target_node_id: Optional[int],
    goal: str,
    source_surface: str,
    agent_profile: str,
    agent_template_id: Optional[int],
    model_code: str,
    mode: str,
    context_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    clean_goal = str(goal or "").strip()
    if not clean_goal:
        raise HTTPException(status_code=400, detail="Agent Run 目标不能为空")
    intent = _classify_agent_goal(clean_goal)
    context_with_intent = {**(context_snapshot or {}), "intent": intent}
    resolved_agent_profile = encode_id(agent_template_id) if agent_template_id else (agent_profile or "auto")
    agent_session = create_sluvo_agent_session(
        session,
        project=project,
        user=user,
        team=team,
        canvas_id=canvas_id,
        target_node_id=target_node_id,
        title=clean_goal[:80],
        agent_profile=resolved_agent_profile,
        model_code=model_code,
        mode=mode,
        context_snapshot={**context_with_intent, "sourceSurface": source_surface, "targetNodeId": encode_id(target_node_id) if target_node_id else (context_snapshot or {}).get("targetNodeId")},
    )
    normalized_model = normalize_sluvo_agent_model_code(model_code)
    template = session.get(SluvoAgentTemplate, agent_template_id) if agent_template_id else _resolve_agent_template(session, agent_profile)
    agent_name = template.name if template else _agent_profile_label(session, agent_profile or "auto", _resolve_agent_profile_key(session, agent_profile or "auto"))
    now = _utc_now()
    run = SluvoAgentRun(
        project_id=project.id,
        canvas_id=agent_session.canvas_id,
        session_id=agent_session.id,
        target_node_id=target_node_id,
        user_id=user.id,
        team_id=team.id,
        title=clean_goal[:80],
        goal=clean_goal,
        source_surface=str(source_surface or "panel").strip() or "panel",
        status="running",
        mode=mode or "semi_auto",
        approval_policy_json=_json_dump({"autoCanvas": True, "costConfirmation": True}),
        context_snapshot_json=_json_dump(context_with_intent),
        summary_json=_json_dump({"contextCount": _agent_run_context_count(context_with_intent), "agentName": agent_name, "modelCode": normalized_model, "intent": intent}),
        created_at=now,
        updated_at=now,
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    append_sluvo_agent_event(session, agent_session=agent_session, role="user", event_type="run_goal", payload={"content": clean_goal, "runId": encode_id(run.id)})
    _append_sluvo_run_event(session, run=run, role="user", event_type="user_message", payload={"content": clean_goal})
    _append_sluvo_run_event(session, run=run, role="system", event_type="run_started", payload={"projectId": encode_id(project.id)})

    if intent["intent"] == "question":
        step = _create_agent_run_step(
            session,
            run=run,
            step_key="answer_question",
            agent_name="创作总监",
            agent_profile="canvas_agent",
            model_code=normalized_model,
            title="直接回答",
            order_index=0,
            agent_template_id=template.id if template else None,
            input_payload={"goal": clean_goal, "intent": intent},
        )
        _create_agent_run_artifact(
            session,
            run=run,
            step=step,
            title="回答",
            artifact_type="report",
            body=_agent_question_answer(clean_goal),
            write_policy="readonly",
            preview={"estimatedWrite": "none", "intent": intent["intent"]},
        )
        _finish_agent_run_step(session, step, output={"artifactCount": 1, "completed": "已回答你的问题", "stage": "ideate"}, status="succeeded")
        run.status = "succeeded"
        run.finished_at = _utc_now()
        run.updated_at = run.finished_at
        run.summary_json = _json_dump({
            "contextCount": _agent_run_context_count(context_with_intent),
            "agentName": "创作总监",
            "modelCode": normalized_model,
            "intent": intent,
            "artifactCount": 1,
            "nodeCount": 0,
            "edgeCount": 0,
            "estimatePoints": 0,
            "workflow": [],
            "agentTeam": [],
            "nextQuestion": "",
        })
        session.add(run)
        session.commit()
        append_sluvo_agent_event(session, agent_session=agent_session, role="agent", event_type="run_answer", payload={"content": _agent_question_answer(clean_goal), "runId": encode_id(run.id)})
        _append_sluvo_run_event(
            session,
            run=run,
            role="agent",
            event_type="run_message",
            payload={"agent": "onboarding", "agentName": "Onboarding Agent", "stage": "ideate", "content": _agent_question_answer(clean_goal)},
        )
        _append_sluvo_run_event(session, run=run, role="system", event_type="run_completed", payload={})
        session.refresh(run)
        return _serialize_agent_run_timeline(session, run)

    used_agents = _resolved_agent_team(session, context_snapshot=context_with_intent, root_template=template, model_code=normalized_model)
    try:
        step_artifacts = _append_agent_workflow_step(
            session,
            run=run,
            user=user,
            spec_index=0,
            goal=clean_goal,
            context_snapshot=context_with_intent,
            root_template=template,
            model_code=normalized_model,
        )
        next_agent = used_agents[1]["agentName"] if len(used_agents) > 1 else None
        run.status = "waiting_user"
        run.summary_json = _json_dump({
            "contextCount": _agent_run_context_count(context_with_intent),
            "agentName": agent_name,
            "modelCode": normalized_model,
            "intent": intent,
            "artifactCount": len([artifact for artifact in step_artifacts if artifact.write_policy != "readonly"]),
            "nodeCount": len([artifact for artifact in step_artifacts if artifact.write_policy not in {"readonly", "requires_cost_confirmation"}]),
            "edgeCount": 0,
            "estimatePoints": 0,
            "workflow": _agent_workflow_public_specs(),
            "agentTeam": used_agents,
            "currentStepIndex": 0,
            "nextStepIndex": 1,
            "awaitingAgent": next_agent,
            "nextQuestion": SLUVO_AGENT_WORKFLOW_SPECS[0]["question"],
        })
        run.updated_at = _utc_now()
        session.add(run)
        session.commit()
        _append_sluvo_run_event(
            session,
            run=run,
            role="agent",
            event_type="run_awaiting_confirm",
            payload={
                "agent": SLUVO_AGENT_WORKFLOW_SPECS[0]["stepKey"],
                "agentName": SLUVO_AGENT_WORKFLOW_SPECS[0]["agentName"],
                "stage": SLUVO_AGENT_WORKFLOW_SPECS[0]["stage"],
                "groupKey": SLUVO_AGENT_WORKFLOW_SPECS[0].get("groupKey") or SLUVO_AGENT_WORKFLOW_SPECS[0]["stage"],
                "groupLabel": SLUVO_AGENT_WORKFLOW_SPECS[0].get("groupLabel") or SLUVO_AGENT_WORKFLOW_SPECS[0]["stage"],
                "message": SLUVO_AGENT_WORKFLOW_SPECS[0]["question"],
                "question": SLUVO_AGENT_WORKFLOW_SPECS[0]["question"],
                "next_step": SLUVO_AGENT_WORKFLOW_SPECS[0]["next"],
                "artifactCount": len(step_artifacts),
            },
        )
    except Exception as exc:
        session.rollback()
        run = require_sluvo_agent_run(session, run.id)
        run.status = "failed"
        run.summary_json = _json_dump({"error": str(exc)})
        run.updated_at = _utc_now()
        run.finished_at = run.updated_at
        session.add(run)
        session.commit()
    session.refresh(run)
    return _serialize_agent_run_timeline(session, run)


def continue_sluvo_agent_run(
    session: Session,
    *,
    run: SluvoAgentRun,
    user: User,
    content: str,
    context_snapshot: Dict[str, Any],
    action: Optional[str] = "continue",
) -> Dict[str, Any]:
    clean_content = str(content or "").strip()
    normalized_action = str(action or "continue").strip().lower()
    normalized_continue_text = clean_content.replace("，", ",").replace(" ", "").replace("\n", "")
    if normalized_action in {"revise", "feedback", "补充", "修改"} and normalized_continue_text in {"继续", "继续下一步", "满意,继续下一步"}:
        normalized_action = "continue"
    if not clean_content and normalized_action in {"revise", "feedback", "补充", "修改"}:
        raise HTTPException(status_code=400, detail="补充需求不能为空")
    if not clean_content and normalized_action == "continue":
        clean_content = "继续下一步"
    _append_sluvo_run_event(session, run=run, role="user", event_type="user_message", payload={"content": clean_content, "action": normalized_action})
    existing_steps = session.exec(select(SluvoAgentStep).where(SluvoAgentStep.run_id == run.id).order_by(SluvoAgentStep.order_index)).all()
    summary = _json_load(run.summary_json, {})
    model_code = normalize_sluvo_agent_model_code(summary.get("modelCode") or "deepseek-v4-flash")
    base_context = _json_load(run.context_snapshot_json, {})
    previous_artifacts = _agent_run_previous_artifacts(session, run)
    merged_context = {**base_context, **(context_snapshot or {}), "previousArtifacts": previous_artifacts}
    if isinstance(context_snapshot, dict) and context_snapshot.get("onboardingConfig"):
        persisted_context = {**base_context, **context_snapshot}
        run.context_snapshot_json = _json_dump(persisted_context)
    root_template_id = _decode_optional_safe(str(base_context.get("agentTemplateId") or ""))
    root_template = session.get(SluvoAgentTemplate, root_template_id) if root_template_id else None
    intent = summary.get("intent") if isinstance(summary.get("intent"), dict) else base_context.get("intent") if isinstance(base_context.get("intent"), dict) else {}
    if intent.get("intent") == "question":
        step = _create_agent_run_step(
            session,
            run=run,
            step_key=f"answer_{len(existing_steps) + 1}",
            agent_name="创作总监",
            agent_profile="canvas_agent",
            model_code=model_code,
            title="继续回答",
            order_index=len(existing_steps),
            input_payload={"content": clean_content, "intent": intent},
        )
        _create_agent_run_artifact(
            session,
            run=run,
            step=step,
            title="回答",
            artifact_type="report",
            body=_agent_question_answer(clean_content),
            write_policy="readonly",
            preview={"estimatedWrite": "none", "intent": "question"},
        )
        _finish_agent_run_step(session, step, output={"artifactCount": 1, "completed": "已回答你的问题", "stage": "ideate"})
        run.status = "succeeded"
        run.updated_at = _utc_now()
        run.finished_at = run.updated_at
        run.summary_json = _json_dump({**summary, "artifactCount": _agent_run_artifact_count(session, run), "nodeCount": 0})
        session.add(run)
        session.commit()
        session.refresh(run)
        _append_sluvo_run_event(
            session,
            run=run,
            role="agent",
            event_type="run_message",
            payload={"agent": "onboarding", "agentName": "Onboarding Agent", "stage": "ideate", "content": _agent_question_answer(clean_content)},
        )
        _append_sluvo_run_event(session, run=run, role="system", event_type="run_completed", payload={})
        return _serialize_agent_run_timeline(session, run)
    workflow_index = _workflow_step_count(session, run)
    if normalized_action in {"revise", "feedback", "补充", "修改"} and workflow_index > 0:
        current_index = max(workflow_index - 1, 0)
        spec = SLUVO_AGENT_WORKFLOW_SPECS[current_index]
        _append_sluvo_run_event(
            session,
            run=run,
            role="agent",
            event_type="run_message",
            payload={
                "agent": "review",
                "agentName": "Review Agent",
                "stage": "ideate",
                "content": f"Review Agent 已收到反馈：{clean_content}。我会把修改重路由给 {spec['agentName']}。",
            },
        )
        _append_sluvo_run_event(
            session,
            run=run,
            role="agent",
            event_type="agent_handoff",
            payload={"from_agent": "review", "to_agent": spec["stepKey"], "message": f"@review 邀请 @{spec['stepKey']} 重新加入群聊"},
        )
        resolved = _resolve_agent_for_workflow_step(
            session,
            context_snapshot=merged_context,
            spec=spec,
            order_index=current_index,
            root_template=root_template,
            model_code=model_code,
        )
        revision_goal = f"{run.goal}\n\n用户补充 / 修改：{clean_content}"
        step = _create_agent_run_step(
            session,
            run=run,
            step_key=f"revise_{spec['stepKey']}_{len(existing_steps) + 1}",
            agent_name=str(resolved["agentName"]),
            agent_profile=str(resolved["agentProfile"]),
            model_code=str(resolved["modelCode"]),
            title=f"更新{spec['title']}",
            order_index=len(existing_steps),
            agent_template_id=_decode_optional_safe(str(resolved.get("agentTemplateId") or "")),
            input_payload={
                "goal": run.goal,
                "content": clean_content,
                "action": "revise",
                "stage": spec["stage"],
                "groupKey": spec.get("groupKey") or spec["stage"],
                "groupLabel": spec.get("groupLabel") or spec["stage"],
                "contextCount": _agent_run_context_count(merged_context),
            },
        )
        artifacts = []
        for artifact_title, artifact_type, policy in spec["artifacts"]:
            generation_params = _agent_generation_params_for_artifact(artifact_type, merged_context)
            artifacts.append(
                _create_agent_run_artifact(
                    session,
                    run=run,
                    step=step,
                    title=artifact_title,
                    artifact_type=artifact_type,
                    body=_artifact_body(artifact_type, revision_goal, merged_context, str(resolved["modelCode"])),
                    write_policy=policy,
                    preview={
                        "estimatedWrite": "canvas_node",
                        "revision": True,
                        "estimatePoints": _agent_generation_estimate_points(artifact_type, generation_params),
                        "generationParams": generation_params,
                    },
                )
            )
        _finish_agent_run_step(
            session,
            step,
            output={
                "artifactCount": len(artifacts),
                "stage": spec["stage"],
                "groupKey": spec.get("groupKey") or spec["stage"],
                "groupLabel": spec.get("groupLabel") or spec["stage"],
                "completed": "已根据补充更新当前阶段",
                "question": spec["question"],
                "revision": True,
            },
        )
        session.commit()
        _write_agent_run_artifacts_to_canvas(session, run=run, user=user, artifacts=artifacts)
        used_agents = summary.get("agentTeam") if isinstance(summary.get("agentTeam"), list) else _resolved_agent_team(session, context_snapshot=base_context, root_template=root_template, model_code=model_code)
        next_agent = used_agents[workflow_index]["agentName"] if workflow_index < len(used_agents) else None
        run.status = "waiting_user"
        run.summary_json = _json_dump({
            **summary,
            "contextCount": _agent_run_context_count(base_context),
            "modelCode": model_code,
            "artifactCount": _agent_run_artifact_count(session, run),
            "nodeCount": _agent_run_artifact_count(session, run),
            "workflow": _agent_workflow_public_specs(),
            "agentTeam": used_agents,
            "currentStepIndex": current_index,
            "nextStepIndex": workflow_index if workflow_index < len(SLUVO_AGENT_WORKFLOW_SPECS) else None,
            "awaitingAgent": next_agent,
            "nextQuestion": spec["question"],
            "estimatePoints": 0,
        })
        run.updated_at = _utc_now()
        session.add(run)
        session.commit()
        session.refresh(run)
        _append_sluvo_run_event(
            session,
            run=run,
            role="agent",
            event_type="run_awaiting_confirm",
            payload={
                "agent": spec["stepKey"],
                "agentName": spec["agentName"],
                "stage": spec["stage"],
                "groupKey": spec.get("groupKey") or spec["stage"],
                "groupLabel": spec.get("groupLabel") or spec["stage"],
                "message": spec["question"],
                "question": spec["question"],
                "next_step": spec["next"],
            },
        )
        return _serialize_agent_run_timeline(session, run)

    if workflow_index < len(SLUVO_AGENT_WORKFLOW_SPECS):
        _append_sluvo_run_event(session, run=run, role="system", event_type="run_confirmed", payload={"message": "已确认，继续下一位 Agent。"})
        artifacts = _append_agent_workflow_step(
            session,
            run=run,
            user=user,
            spec_index=workflow_index,
            goal=run.goal,
            context_snapshot=merged_context,
            root_template=root_template,
            model_code=model_code,
            feedback=clean_content,
        )
        waiting_cost = any(item.write_policy == "requires_cost_confirmation" for item in artifacts)
        estimate_points = sum(int((_json_load(item.preview_json, {}) or {}).get("estimatePoints") or 0) for item in artifacts)
        used_agents = summary.get("agentTeam") if isinstance(summary.get("agentTeam"), list) else _resolved_agent_team(session, context_snapshot=base_context, root_template=root_template, model_code=model_code)
        next_agent = used_agents[workflow_index + 1]["agentName"] if workflow_index + 1 < len(used_agents) else None
        run.status = "waiting_cost_confirmation" if waiting_cost else "waiting_user"
        run.summary_json = _json_dump({
            **summary,
            "contextCount": _agent_run_context_count(base_context),
            "modelCode": model_code,
            "artifactCount": _agent_run_artifact_count(session, run),
            "nodeCount": _agent_run_artifact_count(session, run),
            "workflow": _agent_workflow_public_specs(),
            "agentTeam": used_agents,
            "currentStepIndex": workflow_index,
            "nextStepIndex": workflow_index + 1 if workflow_index + 1 < len(SLUVO_AGENT_WORKFLOW_SPECS) else None,
            "awaitingAgent": next_agent,
            "nextQuestion": SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]["question"],
            "estimatePoints": estimate_points if waiting_cost else 0,
        })
        status_event_payload = {
            "agent": SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]["stepKey"],
            "agentName": SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]["agentName"],
            "stage": SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]["stage"],
            "groupKey": SLUVO_AGENT_WORKFLOW_SPECS[workflow_index].get("groupKey") or SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]["stage"],
            "groupLabel": SLUVO_AGENT_WORKFLOW_SPECS[workflow_index].get("groupLabel") or SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]["stage"],
            "message": SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]["question"],
            "question": SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]["question"],
            "next_step": SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]["next"],
        }
        _append_sluvo_run_event(
            session,
            run=run,
            role="agent",
            event_type="run_awaiting_confirm",
            payload=status_event_payload,
        )
    else:
        step = _create_agent_run_step(
            session,
            run=run,
            step_key=f"continue_{len(existing_steps) + 1}",
            agent_name="创作总监",
            agent_profile="canvas_agent",
            model_code=model_code,
            title="继续补充",
            order_index=len(existing_steps),
            input_payload={"content": clean_content},
        )
        artifact = _create_agent_run_artifact(
            session,
            run=run,
            step=step,
            title="补充建议",
            artifact_type="text_node",
            body=_artifact_body("text_node", clean_content, merged_context, model_code),
            write_policy="auto_canvas",
        )
        _finish_agent_run_step(session, step, output={"artifactCount": 1, "completed": "已整理补充建议"})
        session.commit()
        _write_agent_run_artifacts_to_canvas(session, run=run, user=user, artifacts=[artifact])
        run.status = "succeeded"
        run.summary_json = _json_dump({**summary, "artifactCount": _agent_run_artifact_count(session, run), "nodeCount": _agent_run_artifact_count(session, run)})
    run.updated_at = _utc_now()
    if run.status == "succeeded":
        run.finished_at = run.updated_at
    session.add(run)
    session.commit()
    if run.session_id:
        agent_session = require_sluvo_agent_session(session, run.session_id)
        append_sluvo_agent_event(session, agent_session=agent_session, role="user", event_type="run_continue", payload={"content": clean_content, "runId": encode_id(run.id)})
    if run.status == "succeeded":
        _append_sluvo_run_event(session, run=run, role="system", event_type="run_completed", payload={})
    session.refresh(run)
    return _serialize_agent_run_timeline(session, run)


def confirm_sluvo_agent_run_cost(
    session: Session,
    *,
    run: SluvoAgentRun,
    user: User,
    team: Team,
    artifact_ids: List[int],
    confirmed: bool,
) -> Dict[str, Any]:
    if not confirmed:
        run.status = "cancelled"
        run.finished_at = _utc_now()
        run.updated_at = run.finished_at
        session.add(run)
        session.commit()
        return _serialize_agent_run_timeline(session, run)
    statement = select(SluvoAgentArtifact).where(
        SluvoAgentArtifact.run_id == run.id,
        SluvoAgentArtifact.write_policy == "requires_cost_confirmation",
    )
    artifacts = session.exec(statement).all()
    if artifact_ids:
        allowed = set(artifact_ids)
        artifacts = [item for item in artifacts if item.id in allowed]
    now = _utc_now()
    for artifact in artifacts:
        if artifact.generation_record_id:
            continue
        payload = _json_load(artifact.payload_json, {})
        preview = _json_load(artifact.preview_json, {})
        generation_params = preview.get("generationParams") if isinstance(preview.get("generationParams"), dict) else {}
        record_type = "video" if artifact.artifact_type in {"video_placeholder", "shot_video_placeholder", "merged_video_placeholder"} else "image" if artifact.artifact_type in {"image_placeholder", "character_image_placeholder", "scene_image_placeholder", "prop_image_placeholder", "storyboard_image_placeholder"} else "asset"
        record = GenerationRecord(
            user_id=user.id,
            team_id=team.id,
            record_type=record_type,
            ownership_mode="sluvo",
            script_id=None,
            target_type="sluvo_canvas_node",
            target_id=artifact.canvas_node_id,
            status="queued",
            prompt=str(payload.get("prompt") or payload.get("body") or ""),
            params_internal_json=_json_dump({
                "source": "sluvo_agent_run",
                "runId": encode_id(run.id),
                "artifactId": encode_id(artifact.id),
                "request_payload": {
                    **generation_params,
                    "prompt": str(payload.get("prompt") or payload.get("body") or ""),
                },
            }),
            params_public_json=_json_dump({
                "title": artifact.title,
                "artifactType": artifact.artifact_type,
                **generation_params,
            }),
            estimate_points=int(preview.get("estimatePoints") or (20 if record_type == "video" else 8)),
            points_status="confirmed",
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        session.flush()
        artifact.generation_record_id = record.id
        artifact.status = "submitted"
        artifact.updated_at = now
        session.add(artifact)
        if artifact.canvas_node_id:
            node = session.get(SluvoCanvasNode, artifact.canvas_node_id)
            if node:
                data = _json_load(node.data_json, {})
                if isinstance(data, dict):
                    data.update({
                        "generationStatus": "queued",
                        "generationMessage": "媒体生成已确认，等待生成队列处理",
                        "generationRecordId": encode_id(record.id),
                    })
                    if record_type == "image":
                        data["imageEstimateStatus"] = "confirmed"
                        data["imageParams"] = generation_params
                    if record_type == "video":
                        data["videoEstimateStatus"] = "confirmed"
                        data["videoParams"] = generation_params
                    node.data_json = _json_dump(data)
                    node.status = "queued"
                    node.revision = int(node.revision or 1) + 1
                    node.updated_at = now
                    session.add(node)
    _append_sluvo_run_event(
        session,
        run=run,
        role="system",
        event_type="run_confirmed",
        payload={"agent": "video_generator", "message": "媒体生成已确认，任务进入队列"},
    )
    summary = _json_load(run.summary_json, {})
    context_snapshot = _json_load(run.context_snapshot_json, {})
    model_code = normalize_sluvo_agent_model_code(summary.get("modelCode") or "deepseek-v4-flash")
    workflow_index = _workflow_step_count(session, run)
    if workflow_index < len(SLUVO_AGENT_WORKFLOW_SPECS):
        root_template_id = _decode_optional_safe(str(context_snapshot.get("agentTemplateId") or ""))
        root_template = session.get(SluvoAgentTemplate, root_template_id) if root_template_id else None
        _append_agent_workflow_step(
            session,
            run=run,
            user=user,
            spec_index=workflow_index,
            goal=run.goal,
            context_snapshot=context_snapshot,
            root_template=root_template,
            model_code=model_code,
        )
        spec = SLUVO_AGENT_WORKFLOW_SPECS[workflow_index]
        run.status = "waiting_user"
        run.summary_json = _json_dump({
            **summary,
            "artifactCount": _agent_run_artifact_count(session, run),
            "nodeCount": _agent_run_artifact_count(session, run),
            "currentStepIndex": workflow_index,
            "nextStepIndex": workflow_index + 1 if workflow_index + 1 < len(SLUVO_AGENT_WORKFLOW_SPECS) else None,
            "awaitingAgent": None,
            "nextQuestion": spec["question"],
            "estimatePoints": 0,
        })
        _append_sluvo_run_event(
            session,
            run=run,
            role="agent",
            event_type="run_awaiting_confirm",
            payload={"agent": spec["stepKey"], "agentName": spec["agentName"], "stage": spec["stage"], "groupKey": spec.get("groupKey") or spec["stage"], "groupLabel": spec.get("groupLabel") or spec["stage"], "message": spec["question"], "question": spec["question"], "next_step": spec["next"]},
        )
    else:
        run.status = "succeeded"
        run.finished_at = now
        _append_sluvo_run_event(session, run=run, role="system", event_type="run_completed", payload={})
    run.updated_at = _utc_now()
    session.add(run)
    session.commit()
    session.refresh(run)
    return _serialize_agent_run_timeline(session, run)


def retry_sluvo_agent_step(session: Session, *, step: SluvoAgentStep, user: User) -> Dict[str, Any]:
    run = require_sluvo_agent_run(session, step.run_id)
    if step.status not in {"failed", "cancelled"}:
        return _serialize_agent_run_timeline(session, run)
    now = _utc_now()
    step.status = "running"
    step.error_json = "{}"
    step.updated_at = now
    session.add(step)
    artifacts = session.exec(select(SluvoAgentArtifact).where(SluvoAgentArtifact.step_id == step.id)).all()
    _write_agent_run_artifacts_to_canvas(session, run=run, user=user, artifacts=artifacts)
    _finish_agent_run_step(session, step, output={"retried": True, "artifactCount": len(artifacts)})
    run.status = "waiting_cost_confirmation" if any(item.write_policy == "requires_cost_confirmation" for item in artifacts) else "succeeded"
    run.updated_at = _utc_now()
    session.add(run)
    session.commit()
    session.refresh(run)
    return _serialize_agent_run_timeline(session, run)


def create_sluvo_agent_template(
    session: Session,
    *,
    user: User,
    team: Team,
    payload: SluvoAgentTemplateCreateRequest,
) -> SluvoAgentTemplate:
    now = _utc_now()
    item = SluvoAgentTemplate(
        owner_user_id=user.id,
        team_id=team.id,
        name=str(payload.name or "").strip()[:255] or "未命名 Agent",
        description=payload.description,
        avatar_url=payload.avatarUrl,
        cover_url=payload.coverUrl,
        profile_key=str(payload.profileKey or "custom_agent").strip()[:64] or "custom_agent",
        model_code=normalize_sluvo_agent_model_code(payload.modelCode),
        role_prompt=str(payload.rolePrompt or ""),
        use_cases_json=_json_dump(payload.useCases, []),
        input_types_json=_json_dump(payload.inputTypes, []),
        output_types_json=_json_dump(payload.outputTypes, []),
        tools_json=_json_dump(_normalize_agent_tools(payload.tools), []),
        approval_policy_json=_json_dump(payload.approvalPolicy, {}),
        examples_json=_json_dump(payload.examples, []),
        memory_json="{}",
        status="active",
        created_at=now,
        updated_at=now,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def require_sluvo_agent_template(session: Session, agent_id: str) -> SluvoAgentTemplate:
    item = session.get(SluvoAgentTemplate, decode_id(agent_id))
    if not item or item.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Sluvo Agent 模板不存在")
    return item


def update_sluvo_agent_template(
    session: Session,
    *,
    item: SluvoAgentTemplate,
    payload: SluvoAgentTemplateUpdateRequest,
) -> SluvoAgentTemplate:
    if payload.name is not None:
        item.name = str(payload.name or "").strip()[:255] or item.name
    if payload.description is not None:
        item.description = payload.description
    if payload.avatarUrl is not None:
        item.avatar_url = payload.avatarUrl
    if payload.coverUrl is not None:
        item.cover_url = payload.coverUrl
    if payload.profileKey is not None:
        item.profile_key = str(payload.profileKey or "custom_agent").strip()[:64] or "custom_agent"
    if payload.modelCode is not None:
        item.model_code = normalize_sluvo_agent_model_code(payload.modelCode)
    if payload.rolePrompt is not None:
        item.role_prompt = payload.rolePrompt
    if payload.useCases is not None:
        item.use_cases_json = _json_dump(payload.useCases, [])
    if payload.inputTypes is not None:
        item.input_types_json = _json_dump(payload.inputTypes, [])
    if payload.outputTypes is not None:
        item.output_types_json = _json_dump(payload.outputTypes, [])
    if payload.tools is not None:
        item.tools_json = _json_dump(_normalize_agent_tools(payload.tools), [])
    if payload.approvalPolicy is not None:
        item.approval_policy_json = _json_dump(payload.approvalPolicy, {})
    if payload.examples is not None:
        item.examples_json = _json_dump(payload.examples, [])
    if payload.memory is not None:
        item.memory_json = _json_dump(payload.memory, {})
    item.updated_at = _utc_now()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def delete_sluvo_agent_template(session: Session, *, item: SluvoAgentTemplate) -> None:
    item.deleted_at = _utc_now()
    item.status = "deleted"
    item.updated_at = item.deleted_at
    session.add(item)
    session.commit()


def list_sluvo_community_agents(session: Session, *, limit: int = 24, sort: str = "latest") -> List[Dict[str, Any]]:
    limit = max(1, min(int(limit or 24), 60))
    order_by = SluvoCommunityAgent.fork_count.desc() if str(sort or "").lower() == "popular" else SluvoCommunityAgent.published_at.desc()
    items = session.exec(
        select(SluvoCommunityAgent)
        .where(SluvoCommunityAgent.status == SLUVO_COMMUNITY_AGENT_STATUS_PUBLISHED)
        .order_by(order_by, SluvoCommunityAgent.id.desc())
        .limit(limit)
    ).all()
    return [serialize_sluvo_community_agent_with_session(session, item) for item in items]


def require_sluvo_community_agent(
    session: Session,
    publication_id: str,
    *,
    include_unpublished: bool = False,
) -> SluvoCommunityAgent:
    item = session.get(SluvoCommunityAgent, decode_id(publication_id))
    if not item or (not include_unpublished and item.status != SLUVO_COMMUNITY_AGENT_STATUS_PUBLISHED):
        raise HTTPException(status_code=404, detail="社区 Agent 不存在")
    return item


def get_sluvo_community_agent_detail(session: Session, item: SluvoCommunityAgent) -> Dict[str, Any]:
    item.view_count = int(item.view_count or 0) + 1
    item.updated_at = _utc_now()
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"publication": serialize_sluvo_community_agent_with_session(session, item, detail=True)}


def publish_sluvo_agent_to_community(
    session: Session,
    *,
    item: SluvoAgentTemplate,
    user: User,
    team: Team,
    payload: SluvoCommunityAgentPublishRequest,
) -> Dict[str, Any]:
    now = _utc_now()
    title = str(payload.title or item.name or "").strip()[:255] or item.name or "未命名 Agent"
    snapshot = _public_agent_snapshot(item)
    publication = session.exec(
        select(SluvoCommunityAgent).where(SluvoCommunityAgent.source_agent_id == item.id)
    ).first()
    if not publication:
        publication = SluvoCommunityAgent(
            source_agent_id=item.id,
            owner_user_id=user.id,
            team_id=team.id,
            created_at=now,
        )
    publication.owner_user_id = user.id
    publication.team_id = team.id
    publication.title = title
    publication.description = str(payload.description if payload.description is not None else item.description or "").strip()
    publication.cover_url = str(payload.coverUrl or "").strip() or item.cover_url or item.avatar_url
    publication.tags_json = _json_dump(_normalize_community_tags(payload.tags), [])
    publication.template_snapshot_json = _json_dump(snapshot, {})
    publication.status = SLUVO_COMMUNITY_AGENT_STATUS_PUBLISHED
    publication.unpublished_at = None
    publication.published_at = publication.published_at or now
    publication.updated_at = now
    session.add(publication)
    session.commit()
    session.refresh(publication)
    return {"publication": serialize_sluvo_community_agent_with_session(session, publication, detail=True)}


def fork_sluvo_community_agent(
    session: Session,
    *,
    item: SluvoCommunityAgent,
    user: User,
    team: Team,
) -> Dict[str, Any]:
    snapshot = _json_load(item.template_snapshot_json, {})
    now = _utc_now()
    template = SluvoAgentTemplate(
        owner_user_id=user.id,
        team_id=team.id,
        name=f"Fork 自 {item.title}"[:255],
        description=snapshot.get("description") or item.description,
        avatar_url=snapshot.get("avatarUrl"),
        cover_url=item.cover_url or snapshot.get("coverUrl"),
        profile_key=snapshot.get("profileKey") or "custom_agent",
        model_code=normalize_sluvo_agent_model_code(snapshot.get("modelCode")),
        role_prompt=snapshot.get("rolePrompt") or "",
        use_cases_json=_json_dump(snapshot.get("useCases") or [], []),
        input_types_json=_json_dump(snapshot.get("inputTypes") or [], []),
        output_types_json=_json_dump(snapshot.get("outputTypes") or [], []),
        tools_json=_json_dump(_normalize_agent_tools(snapshot.get("tools") or []), []),
        approval_policy_json=_json_dump(snapshot.get("approvalPolicy") or {}, {}),
        examples_json=_json_dump(snapshot.get("examples") or [], []),
        memory_json="{}",
        status="active",
        forked_from_publication_id=item.id,
        created_at=now,
        updated_at=now,
    )
    session.add(template)
    item.fork_count = int(item.fork_count or 0) + 1
    item.updated_at = now
    session.add(item)
    session.commit()
    session.refresh(template)
    return {"agent": serialize_sluvo_agent_template(template)}


def unpublish_sluvo_community_agent(
    session: Session,
    *,
    item: SluvoCommunityAgent,
    user: User,
    team_member: TeamMemberLink,
) -> Dict[str, Any]:
    is_team_admin = item.team_id == team_member.team_id and _has_team_manage_role(team_member.role)
    if item.owner_user_id != user.id and not is_team_admin:
        raise HTTPException(status_code=403, detail="只有发布者或团队管理员可以取消发布")
    item.status = SLUVO_COMMUNITY_AGENT_STATUS_UNPUBLISHED
    item.unpublished_at = _utc_now()
    item.updated_at = item.unpublished_at
    session.add(item)
    session.commit()
    return {"status": "success", "publicationId": encode_id(item.id)}


def require_sluvo_community_canvas(
    session: Session,
    publication_id: str,
    *,
    include_unpublished: bool = False,
) -> SluvoCommunityCanvas:
    item = session.get(SluvoCommunityCanvas, decode_id(publication_id))
    if not item or (not include_unpublished and item.status != SLUVO_COMMUNITY_CANVAS_STATUS_PUBLISHED):
        raise HTTPException(status_code=404, detail="社区画布不存在")
    return item


def publish_sluvo_project_to_community(
    session: Session,
    *,
    project: SluvoProject,
    user: User,
    team: Team,
    payload: SluvoCommunityCanvasPublishRequest,
) -> Dict[str, Any]:
    canvas = get_or_create_main_canvas(session, project)
    bundle = canvas_bundle(session, canvas)
    now = _utc_now()
    title = str(payload.title or project.title or "").strip()[:255] or project.title or "未命名画布"
    description = str(payload.description if payload.description is not None else project.description or "").strip()
    tags = _normalize_community_tags(payload.tags)
    cover_url = str(payload.coverUrl or "").strip() or get_sluvo_project_first_image_url(session, project.id) or project.cover_url
    snapshot = {
        "project": serialize_sluvo_project(project),
        "canvas": bundle["canvas"],
        "nodes": bundle["nodes"],
        "edges": bundle["edges"],
        "publishedAt": now.isoformat(),
    }
    item = session.exec(
        select(SluvoCommunityCanvas).where(SluvoCommunityCanvas.source_project_id == project.id)
    ).first()
    if not item:
        item = SluvoCommunityCanvas(
            source_project_id=project.id,
            source_canvas_id=canvas.id,
            owner_user_id=user.id,
            team_id=team.id,
            created_at=now,
        )
    item.source_canvas_id = canvas.id
    item.owner_user_id = user.id
    item.team_id = team.id
    item.title = title
    item.description = description
    item.cover_url = cover_url
    item.tags_json = _json_dump(tags, [])
    item.status = SLUVO_COMMUNITY_CANVAS_STATUS_PUBLISHED
    item.snapshot_json = _json_dump(snapshot, {})
    item.nodes_json = _json_dump(bundle["nodes"], [])
    item.edges_json = _json_dump(bundle["edges"], [])
    item.viewport_json = _json_dump(bundle["canvas"].get("viewport") or {}, {})
    item.schema_version = int(bundle["canvas"].get("schemaVersion") or 1)
    item.unpublished_at = None
    item.published_at = item.published_at or now
    item.updated_at = now
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"publication": serialize_sluvo_community_canvas_with_session(session, item, detail=True)}


def get_sluvo_community_canvas_detail(session: Session, item: SluvoCommunityCanvas) -> Dict[str, Any]:
    item.view_count = int(item.view_count or 0) + 1
    item.updated_at = _utc_now()
    session.add(item)
    session.commit()
    session.refresh(item)
    return {"publication": serialize_sluvo_community_canvas_with_session(session, item, detail=True)}


def unpublish_sluvo_community_canvas(
    session: Session,
    *,
    item: SluvoCommunityCanvas,
    user: User,
    team_member: TeamMemberLink,
) -> Dict[str, Any]:
    is_team_admin = item.team_id == team_member.team_id and _has_team_manage_role(team_member.role)
    if item.owner_user_id != user.id and not is_team_admin:
        raise HTTPException(status_code=403, detail="只有发布者或团队管理员可以取消发布")
    item.status = SLUVO_COMMUNITY_CANVAS_STATUS_UNPUBLISHED
    item.unpublished_at = _utc_now()
    item.updated_at = item.unpublished_at
    session.add(item)
    session.commit()
    return {"status": "success", "publicationId": encode_id(item.id)}


def fork_sluvo_community_canvas(
    session: Session,
    *,
    item: SluvoCommunityCanvas,
    user: User,
    team: Team,
) -> Dict[str, Any]:
    now = _utc_now()
    project = SluvoProject(
        owner_user_id=user.id,
        team_id=team.id,
        title=f"Fork 自 {item.title}"[:255],
        description=item.description,
        status="active",
        visibility="project_members",
        settings_json=_json_dump(
            {
                "source": "community_fork",
                "publicationId": encode_id(item.id),
                "sourceProjectId": encode_id(item.source_project_id),
            }
        ),
        cover_url=item.cover_url,
        created_at=now,
        updated_at=now,
        last_opened_at=now,
    )
    session.add(project)
    session.flush()
    member = SluvoProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=SLUVO_MEMBER_ROLE_OWNER,
        created_at=now,
        updated_at=now,
    )
    session.add(member)
    canvas = SluvoCanvas(
        project_id=project.id,
        canvas_key="main",
        title=item.title or "Main Canvas",
        viewport_json=item.viewport_json or "{}",
        snapshot_json=item.snapshot_json or "{}",
        schema_version=int(item.schema_version or 1),
        revision=1,
        created_at=now,
        updated_at=now,
    )
    session.add(canvas)
    session.flush()

    node_id_map: Dict[str, int] = {}
    for index, node_payload in enumerate(_json_load(item.nodes_json, [])):
        position = node_payload.get("position") or {}
        size = node_payload.get("size") or {}
        node = SluvoCanvasNode(
            canvas_id=canvas.id,
            node_type=normalize_sluvo_node_type(node_payload.get("nodeType")),
            title=node_payload.get("title") or "",
            position_x=float(position.get("x", 0.0)),
            position_y=float(position.get("y", 0.0)),
            width=size.get("width"),
            height=size.get("height"),
            z_index=int(node_payload.get("zIndex") if node_payload.get("zIndex") is not None else index),
            rotation=float(node_payload.get("rotation") or 0.0),
            status=node_payload.get("status") or "idle",
            hidden=bool(node_payload.get("hidden") or False),
            locked=bool(node_payload.get("locked") or False),
            collapsed=bool(node_payload.get("collapsed") or False),
            data_json=_json_dump(node_payload.get("data") or {}),
            ports_json=_json_dump(node_payload.get("ports") or {}),
            ai_config_json=_json_dump(node_payload.get("aiConfig") or {}),
            style_json=_json_dump(node_payload.get("style") or {}),
            revision=1,
            created_by_user_id=user.id,
            updated_by_user_id=user.id,
            created_at=now,
            updated_at=now,
        )
        session.add(node)
        session.flush()
        old_id = str(node_payload.get("id") or "")
        if old_id:
            node_id_map[old_id] = node.id

    for edge_payload in _json_load(item.edges_json, []):
        source_id = node_id_map.get(str(edge_payload.get("sourceNodeId") or ""))
        target_id = node_id_map.get(str(edge_payload.get("targetNodeId") or ""))
        if not source_id or not target_id:
            continue
        edge = SluvoCanvasEdge(
            canvas_id=canvas.id,
            source_node_id=source_id,
            target_node_id=target_id,
            source_port_id=edge_payload.get("sourcePortId"),
            target_port_id=edge_payload.get("targetPortId"),
            edge_type=normalize_sluvo_edge_type(edge_payload.get("edgeType")),
            label=edge_payload.get("label"),
            data_json=_json_dump(edge_payload.get("data") or {}),
            style_json=_json_dump(edge_payload.get("style") or {}),
            hidden=bool(edge_payload.get("hidden") or False),
            revision=1,
            created_at=now,
            updated_at=now,
        )
        session.add(edge)

    for asset in session.exec(
        select(SluvoCanvasAsset).where(SluvoCanvasAsset.project_id == item.source_project_id, SluvoCanvasAsset.deleted_at == None)
    ).all():
        next_node_id = node_id_map.get(encode_id(asset.node_id)) if asset.node_id else None
        session.add(
            SluvoCanvasAsset(
                project_id=project.id,
                canvas_id=canvas.id,
                node_id=next_node_id,
                owner_user_id=user.id,
                media_type=asset.media_type,
                source_type="community_reference",
                url=asset.url,
                thumbnail_url=asset.thumbnail_url,
                storage_object_id=asset.storage_object_id,
                mime_type=asset.mime_type,
                file_size=asset.file_size,
                width=asset.width,
                height=asset.height,
                duration_seconds=asset.duration_seconds,
                metadata_json=_json_dump(
                    {
                        **_json_load(asset.metadata_json, {}),
                        "forkedFromPublicationId": encode_id(item.id),
                        "sourceAssetId": encode_id(asset.id),
                    }
                ),
                created_at=now,
                updated_at=now,
            )
        )

    item.fork_count = int(item.fork_count or 0) + 1
    item.updated_at = now
    session.add(item)
    session.commit()
    session.refresh(project)
    session.refresh(canvas)
    return {
        "project": serialize_sluvo_project(project, SLUVO_MEMBER_ROLE_OWNER, item.cover_url),
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


def restore_sluvo_project(session: Session, project: SluvoProject) -> SluvoProject:
    if project.deleted_at is None and project.status != SLUVO_PROJECT_STATUS_DELETED:
        return project
    now = _utc_now()
    project.status = SLUVO_PROJECT_STATUS_ACTIVE
    project.deleted_at = None
    project.updated_at = now
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def permanently_delete_sluvo_project(session: Session, project: SluvoProject) -> None:
    if project.deleted_at is None and project.status != SLUVO_PROJECT_STATUS_DELETED:
        raise HTTPException(status_code=400, detail="只能彻底删除回收站中的项目")

    def delete_and_flush(items: List[Any]) -> None:
        for item in items:
            session.delete(item)
        if items:
            session.flush()

    canvases = session.exec(select(SluvoCanvas).where(SluvoCanvas.project_id == project.id)).all()
    canvas_ids = [item.id for item in canvases if item.id is not None]
    nodes = session.exec(
        select(SluvoCanvasNode).where(SluvoCanvasNode.canvas_id.in_(canvas_ids))
    ).all() if canvas_ids else []
    sessions = session.exec(select(SluvoAgentSession).where(SluvoAgentSession.project_id == project.id)).all()
    session_ids = [item.id for item in sessions if item.id is not None]
    actions = session.exec(select(SluvoAgentAction).where(SluvoAgentAction.project_id == project.id)).all()
    action_ids = [item.id for item in actions if item.id is not None]

    delete_and_flush(session.exec(select(SluvoCanvasMutation).where(SluvoCanvasMutation.project_id == project.id)).all())
    if session_ids:
        delete_and_flush(session.exec(select(SluvoAgentEvent).where(SluvoAgentEvent.session_id.in_(session_ids))).all())
    if action_ids:
        delete_and_flush(session.exec(select(SluvoAgentAction).where(SluvoAgentAction.id.in_(action_ids))).all())
    if session_ids:
        delete_and_flush(session.exec(select(SluvoAgentSession).where(SluvoAgentSession.id.in_(session_ids))).all())

    delete_and_flush(session.exec(select(SluvoCommunityCanvas).where(SluvoCommunityCanvas.source_project_id == project.id)).all())
    delete_and_flush(session.exec(select(SluvoCanvasAsset).where(SluvoCanvasAsset.project_id == project.id)).all())
    if canvas_ids:
        delete_and_flush(session.exec(select(SluvoCanvasEdge).where(SluvoCanvasEdge.canvas_id.in_(canvas_ids))).all())

    if nodes:
        for node in nodes:
            node.parent_node_id = None
            session.add(node)
        session.flush()
        delete_and_flush(nodes)

    delete_and_flush(canvases)
    delete_and_flush(session.exec(select(SluvoProjectMember).where(SluvoProjectMember.project_id == project.id)).all())
    session.delete(project)
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

    client_node_ids: Dict[str, int] = {}

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
            session.flush()

        client_id = _item_client_id(item)
        if client_id:
            client_node_ids[client_id] = node.id

    session.flush()
    for existing_node in session.exec(
        select(SluvoCanvasNode).where(SluvoCanvasNode.canvas_id == canvas.id, SluvoCanvasNode.deleted_at == None)
    ).all():
        existing_client_id = str(_json_load(existing_node.data_json, {}).get("clientId") or "").strip()
        if existing_client_id:
            client_node_ids.setdefault(existing_client_id, existing_node.id)

    for edge_id in payload.deletedEdgeIds:
        edge = _require_edge(session, decode_id(edge_id))
        _assert_same_canvas(edge.canvas_id, canvas.id, "连线")
        edge.deleted_at = _utc_now()
        edge.revision = int(edge.revision or 1) + 1
        edge.updated_at = _utc_now()
        session.add(edge)

    for item in payload.edges:
        edge_id = _decode_optional(item.get("id"))
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        source_node_id = _resolve_batch_node_id(
            session,
            canvas,
            item.get("sourceNodeId"),
            data.get("sourceClientId"),
            client_node_ids,
            "source node",
        )
        target_node_id = _resolve_batch_node_id(
            session,
            canvas,
            item.get("targetNodeId"),
            data.get("targetClientId"),
            client_node_ids,
            "target node",
        )
        resolved_item = {
            **item,
            "sourceNodeId": encode_id(source_node_id),
            "targetNodeId": encode_id(target_node_id),
        }
        if edge_id:
            edge = _require_edge(session, edge_id)
            update_payload = SluvoCanvasEdgeUpdateRequest(**{k: v for k, v in resolved_item.items() if k != "id"})
            _assert_same_canvas(edge.canvas_id, canvas.id, "连线")
            _check_revision(edge.revision, update_payload.expectedRevision, "连线")
            edge.source_node_id = source_node_id
            edge.target_node_id = target_node_id
            if update_payload.sourcePortId is not None:
                edge.source_port_id = update_payload.sourcePortId
            if update_payload.targetPortId is not None:
                edge.target_port_id = update_payload.targetPortId
            if update_payload.edgeType is not None:
                edge.edge_type = normalize_sluvo_edge_type(update_payload.edgeType)
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
            create_payload = SluvoCanvasEdgeCreateRequest(**resolved_item)
            edge = SluvoCanvasEdge(
                canvas_id=canvas.id,
                source_node_id=source_node_id,
                target_node_id=target_node_id,
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
    model_code: str,
    mode: str,
    context_snapshot: Dict[str, Any],
) -> SluvoAgentSession:
    canvas = _require_canvas(session, canvas_id) if canvas_id else get_or_create_main_canvas(session, project)
    if canvas.project_id != project.id:
        raise HTTPException(status_code=400, detail="Agent 画布不属于当前项目")
    agent_template = _resolve_agent_template(session, agent_profile)
    if target_node_id:
        node = _require_node(session, target_node_id)
        _assert_same_canvas(node.canvas_id, canvas.id, "目标节点")
    normalized_context = {
        **(context_snapshot or {}),
        "agentTemplateId": encode_id(agent_template.id) if agent_template else (context_snapshot or {}).get("agentTemplateId"),
        "agentName": agent_template.name if agent_template else (context_snapshot or {}).get("agentName"),
        "modelCode": normalize_sluvo_agent_model_code(model_code or (context_snapshot or {}).get("modelCode") or (agent_template.model_code if agent_template else None)),
    }
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
        context_snapshot_json=_json_dump(normalized_context),
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


def process_sluvo_agent_message(
    session: Session,
    *,
    agent_session: SluvoAgentSession,
    content: Optional[str],
    payload: Dict[str, Any],
    turn_id: Optional[str] = None,
    proposed_action: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    user_event = append_sluvo_agent_event(
        session,
        agent_session=agent_session,
        role="user",
        event_type="message",
        payload={"content": content, **(payload or {})},
        turn_id=turn_id,
    )
    if proposed_action:
        action = create_sluvo_agent_action(session, agent_session=agent_session, action_payload=proposed_action)
        agent_event = append_sluvo_agent_event(
            session,
            agent_session=agent_session,
            role="agent",
            event_type="proposal",
            payload={
                "content": "已收到一条外部 Agent 提案，请审阅后决定是否写入画布。",
                "actionId": encode_id(action.id),
            },
            turn_id=turn_id,
        )
        return {"event": user_event, "agentEvent": agent_event, "action": action}

    action_payload, reply = build_sluvo_agent_action_payload(
        session,
        agent_session=agent_session,
        content=content,
        payload=payload or {},
    )
    action = create_sluvo_agent_action(session, agent_session=agent_session, action_payload=action_payload)
    agent_event = append_sluvo_agent_event(
        session,
        agent_session=agent_session,
        role="agent",
        event_type="proposal",
        payload={**reply, "actionId": encode_id(action.id)},
        turn_id=turn_id,
    )
    return {"event": user_event, "agentEvent": agent_event, "action": action}


def analyze_sluvo_text_node(payload: SluvoTextNodeAnalyzeRequest) -> Dict[str, Any]:
    source = str(payload.content or "").strip()
    instruction = str(payload.instruction or "").strip()
    title = str(payload.nodeTitle or "文本节点").strip() or "文本节点"
    model_code = normalize_sluvo_agent_model_code(payload.modelCode)
    estimate = estimate_sluvo_text_node_points(payload)
    llm_content = _try_deepseek_text_node_analysis(
        model_code=model_code,
        title=title,
        source=source,
        instruction=instruction,
    )
    content = llm_content or _build_text_node_analysis_fallback(
        title=title,
        source=source,
        instruction=instruction,
    )
    return {
        "content": content,
        "modelCode": model_code,
        "llmUsed": bool(llm_content),
        "estimatePoints": estimate["estimatePoints"],
        "pricing": estimate["pricing"],
        "summary": "已更新文本节点",
    }


def estimate_sluvo_text_node_points(payload: SluvoTextNodeAnalyzeRequest) -> Dict[str, Any]:
    source = str(payload.content or "").strip()
    instruction = str(payload.instruction or "").strip()
    title = str(payload.nodeTitle or "文本节点").strip() or "文本节点"
    model_code = normalize_sluvo_agent_model_code(payload.modelCode)
    messages = _build_sluvo_text_node_analysis_messages(title=title, source=source, instruction=instruction)
    prompt_text = "\n".join(str(message.get("content") or "") for message in messages)
    prompt_tokens = estimate_text_tokens(prompt_text)
    usage = {
        "prompt_tokens": prompt_tokens,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": prompt_tokens,
        "completion_tokens": SLUVO_TEXT_NODE_ANALYZE_MAX_TOKENS,
    }
    cost_cny = calculate_deepseek_v4_flash_usage_cost_cny(usage)
    estimate_points = 0
    if cost_cny > 0:
        estimate_points = int((cost_cny / SLUVO_TEXT_NODE_POINTS_UNIT_CNY).to_integral_value(rounding=ROUND_CEILING)) + 1
    return {
        "modelCode": model_code,
        "estimatePoints": estimate_points,
        "pricing": {
            "unit": "inspiration_points",
            "source": "deepseek_v4_usage_estimate",
            "actualCostCny": float(cost_cny),
            "usage": usage,
        },
    }


def build_sluvo_agent_action_payload(
    session: Session,
    *,
    agent_session: SluvoAgentSession,
    content: Optional[str],
    payload: Dict[str, Any],
) -> tuple[Dict[str, Any], Dict[str, Any]]:
    canvas = _require_canvas(session, agent_session.canvas_id)
    context = payload.get("contextSnapshot") if isinstance(payload.get("contextSnapshot"), dict) else _json_load(agent_session.context_snapshot_json, {})
    selected_nodes = context.get("selectedNodes") if isinstance(context.get("selectedNodes"), list) else []
    requested_profile = payload.get("agentProfile") or context.get("agentTemplateId") or agent_session.agent_profile
    agent_template = _resolve_agent_template(session, context.get("agentTemplateId") or requested_profile)
    model_code = normalize_sluvo_agent_model_code(context.get("modelCode") or payload.get("modelCode") or context.get("agentModelCode") or (agent_template.model_code if agent_template else None))
    prompt = str(content or payload.get("content") or "").strip()
    route = resolve_sluvo_agent_route(
        session,
        requested_profile=requested_profile,
        prompt=prompt,
        context=context,
        selected_nodes=selected_nodes,
    )
    profile_key = route["profile"]
    action_type = route["actionType"]
    llm_payload = _try_deepseek_canvas_agent_payload(
        model_code=model_code,
        profile_key=profile_key,
        action_type=action_type,
        prompt=prompt,
        selected_nodes=selected_nodes,
        agent_template=agent_template,
    )
    if isinstance(llm_payload, dict):
        action_type = str(llm_payload.get("actionType") or action_type)
    patch = _build_agent_canvas_patch(
        canvas=canvas,
        action_type=action_type,
        profile_key=profile_key,
        model_code=model_code,
        prompt=prompt,
        selected_nodes=selected_nodes,
        llm_payload=llm_payload,
    )
    profile_label = _agent_profile_label(session, context.get("agentTemplateId") or agent_session.agent_profile, profile_key)
    agent_template_id = encode_id(agent_template.id) if agent_template else context.get("agentTemplateId")
    agent_name = agent_template.name if agent_template else profile_label
    source_surface = str(context.get("sourceSurface") or payload.get("sourceSurface") or "panel")
    target_node_id = context.get("targetNodeId") or (encode_id(agent_session.target_node_id) if agent_session.target_node_id else None)
    node_count = len(patch.get("nodes") or [])
    edge_count = len(patch.get("edges") or [])
    reply = {
        "content": f"创作总监已协调{agent_name}，基于当前画布生成 {node_count} 个节点、{edge_count} 条连线的提案。",
        "modelCode": model_code,
        "profile": profile_key,
        "resolvedProfile": profile_key,
        "resolvedProfileLabel": profile_label,
        "agentTemplateId": agent_template_id,
        "agentName": agent_name,
        "resolvedActionType": action_type,
        "routingReason": route["reason"],
        "requiresApproval": True,
        "summary": _agent_action_summary(action_type),
        "llmUsed": bool(llm_payload),
    }
    return {
        "actionType": action_type,
        "targetNodeId": target_node_id,
        "input": {
            "content": prompt,
            "contextSummary": {
                "selectedNodeCount": len(selected_nodes),
                "modelCode": model_code,
                "profile": profile_key,
                "requestedProfile": agent_session.agent_profile,
                "resolvedProfile": profile_key,
                "resolvedProfileLabel": profile_label,
                "agentTemplateId": agent_template_id,
                "agentName": agent_name,
                "sourceSurface": source_surface,
                "targetNodeId": target_node_id,
                "resolvedActionType": action_type,
                "routingReason": route["reason"],
            },
        },
        "patch": patch,
    }, reply


def resolve_sluvo_agent_route(
    session: Session,
    *,
    requested_profile: Optional[str],
    prompt: str,
    context: Dict[str, Any],
    selected_nodes: List[Dict[str, Any]],
) -> Dict[str, str]:
    requested = str(requested_profile or "auto").strip() or "auto"
    if requested not in {"auto", "creative_director"}:
        profile_key = _resolve_agent_profile_key(session, requested)
        return {
            "profile": profile_key,
            "actionType": _infer_agent_action_type(profile_key, prompt),
            "reason": "已按高级设置使用指定 Agent。",
        }

    searchable_parts = [prompt]
    project = context.get("project") if isinstance(context.get("project"), dict) else {}
    searchable_parts.append(str(project.get("title") or ""))
    for item in selected_nodes[:8]:
        if not isinstance(item, dict):
            continue
        searchable_parts.extend([
            str(item.get("title") or ""),
            str(item.get("directType") or item.get("nodeType") or ""),
            str(item.get("prompt") or "")[:500],
        ])
    text = "\n".join(searchable_parts).lower()

    def has_any(*keywords: str) -> bool:
        return any(keyword.lower() in text for keyword in keywords)

    if has_any("prompt", "提示词", "精修", "改写", "润色"):
        return {"profile": "prompt_polisher", "actionType": "prompt.rewrite", "reason": "识别到提示词优化需求。"}
    if has_any("一致", "检查", "角色漂移", "风格漂移", "设定冲突", "检查一致性"):
        return {"profile": "consistency_checker", "actionType": "agent.report", "reason": "识别到一致性检查需求。"}
    if has_any("任务", "排期", "缺口", "失败", "重试", "成本", "制片", "整理工作流"):
        return {"profile": "production_planner", "actionType": "agent.report", "reason": "识别到制片调度或任务整理需求。"}
    if has_any("灵感", "创意", "剧本", "故事", "短片", "动画", "角色", "场景", "道具", "提取"):
        return {"profile": "story_director", "actionType": "workflow.plan", "reason": "识别到从灵感或剧本启动制片规划的需求。"}
    if has_any("分镜", "镜头", "storyboard", "下游", "首帧", "视频链路", "拆分"):
        return {"profile": "storyboard_director", "actionType": "workflow.plan", "reason": "识别到分镜或下游生成链路需求。"}
    if has_any("剧情", "大纲", "对白", "角色关系", "冲突"):
        return {"profile": "story_director", "actionType": "canvas.patch", "reason": "识别到故事结构或剧本创作需求。"}
    return {"profile": "canvas_agent", "actionType": "canvas.patch", "reason": "未命中特定专业任务，使用通用画布协作。"}


def _resolve_agent_profile_key(session: Session, agent_profile: str) -> str:
    value = str(agent_profile or "canvas_agent").strip()
    if value in {"auto", "creative_director"}:
        return "canvas_agent"
    if value in SLUVO_OFFICIAL_AGENT_PROFILES:
        return value
    template = _resolve_agent_template(session, value)
    if template:
        return template.profile_key or "custom_agent"
    return "custom_agent" if value else "canvas_agent"


def _resolve_agent_template(session: Session, agent_profile: Optional[str]) -> Optional[SluvoAgentTemplate]:
    value = str(agent_profile or "").strip()
    if not value or value in {"auto", "creative_director"} or value in SLUVO_OFFICIAL_AGENT_PROFILES:
        return None
    try:
        template = session.get(SluvoAgentTemplate, decode_id(value))
    except Exception:
        return None
    if template and template.deleted_at is None:
        return template
    return None


def _agent_profile_label(session: Session, agent_profile: str, profile_key: str) -> str:
    official = SLUVO_OFFICIAL_AGENT_PROFILES.get(profile_key)
    if official:
        return official["name"]
    template = _resolve_agent_template(session, agent_profile)
    if template:
        return template.name
    return "自定义 Agent"


def _infer_agent_action_type(profile_key: str, prompt: str) -> str:
    text = prompt.lower()
    if profile_key == "consistency_checker" or "检查" in prompt or "一致" in prompt:
        return "agent.report"
    if profile_key == "prompt_polisher" or "prompt" in text or "提示词" in prompt:
        return "prompt.rewrite"
    if profile_key in {"storyboard_director", "production_planner"} or "分镜" in prompt or "下游" in prompt:
        return "workflow.plan"
    return "canvas.patch"


def _try_deepseek_canvas_agent_payload(
    *,
    model_code: str,
    profile_key: str,
    action_type: str,
    prompt: str,
    selected_nodes: List[Dict[str, Any]],
    agent_template: Optional[SluvoAgentTemplate] = None,
) -> Optional[Dict[str, Any]]:
    if not settings.DEEPSEEK_API_KEY:
        return None
    try:
        payload = chat_json(
            model=model_code,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 Sluvo 无限画布创作 Agent。请只输出 JSON 对象，字段包括 "
                        "actionType、outputTitle、outputPrompt。actionType 只能是 "
                        "canvas.patch、agent.report、prompt.rewrite、workflow.plan 之一。"
                    ),
                },
                {
                    "role": "user",
                    "content": _build_deepseek_agent_prompt(
                        profile_key=profile_key,
                        action_type=action_type,
                        prompt=prompt,
                        selected_nodes=selected_nodes,
                        agent_template=agent_template,
                    ),
                },
            ],
            thinking_enabled=model_code == "deepseek-v4-pro",
            max_tokens=900,
            temperature=0.2,
            route_tag="sluvo_canvas_agent",
        )
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    safe_action = str(payload.get("actionType") or action_type)
    if safe_action not in {"canvas.patch", "agent.report", "prompt.rewrite", "workflow.plan"}:
        safe_action = action_type
    return {
        "actionType": safe_action,
        "outputTitle": str(payload.get("outputTitle") or "").strip()[:80],
        "outputPrompt": str(payload.get("outputPrompt") or "").strip(),
    }


def _try_deepseek_text_node_analysis(
    *,
    model_code: str,
    title: str,
    source: str,
    instruction: str,
) -> Optional[str]:
    if not settings.DEEPSEEK_API_KEY:
        return None
    try:
        payload = chat_json(
            model=model_code,
            messages=_build_sluvo_text_node_analysis_messages(title=title, source=source, instruction=instruction),
            thinking_enabled=model_code == "deepseek-v4-pro",
            max_tokens=SLUVO_TEXT_NODE_ANALYZE_MAX_TOKENS,
            temperature=0.24,
            route_tag="sluvo_text_node",
        )
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    content = str(payload.get("content") or payload.get("markdown") or "").strip()
    return content[:12000] if content else None


def _build_sluvo_text_node_analysis_messages(*, title: str, source: str, instruction: str) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "你是 Sluvo 文本节点内的局部创作助手。你只服务当前文本节点，"
                "不要生成画布 patch，不要提及右侧 Agent 面板。请只输出 JSON 对象，"
                "字段为 content，content 必须是可以直接放进文本节点渲染的 Markdown。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"节点标题：{title}\n"
                f"用户指令：{instruction or '请分析这段内容，并给出可继续创作的结构化结果。'}\n\n"
                f"当前节点内容：\n{source or '（空）'}"
            ),
        },
    ]


def _build_text_node_analysis_fallback(*, title: str, source: str, instruction: str) -> str:
    clean_source = source.strip()
    clean_instruction = instruction.strip()
    if not clean_source and clean_instruction:
        clean_source = clean_instruction

    text = f"{clean_instruction}\n{clean_source}".lower()

    if any(keyword in text for keyword in ["提示词", "prompt", "优化", "精修", "润色"]):
        seed = clean_source or clean_instruction or title
        return "\n".join(
            [
                f"## {title}",
                "",
                "### 优化后的提示词",
                _build_polished_prompt(seed),
                "",
                "### 继续调整方向",
                "- 明确主体、动作、环境、光线和镜头运动。",
                "- 保留适合图片和视频生成的具体视觉信息。",
                "- 避免抽象形容词堆叠，优先使用可被画面执行的描述。",
            ]
        )

    if any(keyword in text for keyword in ["分镜", "镜头", "拆分", "storyboard"]):
        seed = clean_source or clean_instruction or title
        return "\n".join(
            [
                f"## {title} 分镜草案",
                "",
                _build_storyboard_plan(seed),
                "",
                "### 下一步",
                "- 为每个镜头补充首帧画面提示词。",
                "- 标注角色、场景和道具在镜头间的连续性。",
            ]
        )

    seed = clean_source or clean_instruction or title
    return "\n".join(
        [
            f"## {title} 分析",
            "",
            "### 核心内容",
            seed[:1200],
            "",
            "### 角色",
            _build_character_prop_brief(seed),
            "",
            "### 场景",
            _build_scene_brief(seed),
            "",
            "### 下一步创作",
            "- 把核心创意整理成故事总览。",
            "- 提取角色、场景和关键道具，形成独立节点。",
            "- 再根据故事节奏拆成分镜、首帧图片和视频生成链路。",
        ]
    )


def _build_deepseek_agent_prompt(
    *,
    profile_key: str,
    action_type: str,
    prompt: str,
    selected_nodes: List[Dict[str, Any]],
    agent_template: Optional[SluvoAgentTemplate] = None,
) -> str:
    node_brief = [
        {
            "title": item.get("title"),
            "type": item.get("directType") or item.get("nodeType"),
            "prompt": str(item.get("prompt") or "")[:500],
        }
        for item in selected_nodes[:8]
        if isinstance(item, dict)
    ]
    template_payload = None
    if agent_template:
        template_payload = {
            "name": agent_template.name,
            "description": agent_template.description,
            "profileKey": agent_template.profile_key,
            "rolePrompt": agent_template.role_prompt,
            "useCases": _json_load(agent_template.use_cases_json, []),
            "inputTypes": _json_load(agent_template.input_types_json, []),
            "outputTypes": _json_load(agent_template.output_types_json, []),
            "tools": _json_load(agent_template.tools_json, []),
            "approvalPolicy": _json_load(agent_template.approval_policy_json, {}),
        }
    return _json_dump(
        {
            "agentProfile": profile_key,
            "agentTemplate": template_payload,
            "preferredActionType": action_type,
            "userRequest": prompt,
            "selectedNodes": node_brief,
            "task": (
                "生成真正要沉淀到画布的创作产物，不要输出操作说明。"
                "如果提供了 agentTemplate，必须遵守其中的 rolePrompt、用例、输入输出类型和工具边界。"
                "prompt.rewrite 直接输出优化后的提示词；workflow.plan 输出精简分镜计划；"
                "agent.report 输出检查报告；canvas.patch 输出下一步创作建议。"
            ),
        },
        {},
    )


def _agent_action_summary(action_type: str) -> str:
    return {
        "agent.report": "生成检查报告节点",
        "prompt.rewrite": "生成精修提示词节点",
        "workflow.plan": "生成可继续执行的创作链路",
        "canvas.patch": "生成画布创作建议",
    }.get(action_type, "生成画布创作建议")


def _build_agent_canvas_patch(
    *,
    canvas: SluvoCanvas,
    action_type: str,
    profile_key: str,
    model_code: str,
    prompt: str,
    selected_nodes: List[Dict[str, Any]],
    llm_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    base_x, base_y = _agent_patch_origin(selected_nodes)
    safe_prompt = prompt or "请基于当前画布继续创作。"
    base_client_id = f"agent-product-{profile_key}-{int(_utc_now().timestamp() * 1000)}"
    output_client_id = f"{base_client_id}-output"
    llm_title = str((llm_payload or {}).get("outputTitle") or "").strip()
    llm_prompt = str((llm_payload or {}).get("outputPrompt") or "").strip()
    source_edges: List[Dict[str, Any]] = []
    first_selected_id = _first_selected_node_id(selected_nodes)
    if first_selected_id:
        source_edges.append(_agent_patch_edge_from_node(first_selected_id, output_client_id, "reference", "来源"))

    def product_data(extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "agentProfile": profile_key,
            "agentLabel": _agent_profile_label_from_key(profile_key),
            "modelCode": model_code,
            "lastProposal": _agent_action_summary(action_type),
            "source": "canvas_agent_panel",
            "generationStatus": "idle",
            **(extra or {}),
        }

    if action_type == "agent.report":
        output = _agent_patch_node(
            client_id=output_client_id,
            node_type="note",
            direct_type="prompt_note",
            title=llm_title or "Agent 一致性检查报告",
            icon="检",
            position={"x": base_x + 360, "y": base_y},
            prompt=llm_prompt or _build_consistency_report(safe_prompt, selected_nodes, model_code),
            data=product_data(),
        )
    elif action_type == "prompt.rewrite":
        output = _agent_patch_node(
            client_id=output_client_id,
            node_type="note",
            direct_type="prompt_note",
            title=llm_title or "精修提示词",
            icon="词",
            position={"x": base_x + 360, "y": base_y},
            prompt=llm_prompt or _build_polished_prompt(safe_prompt, selected_nodes),
            data=product_data(),
        )
    elif action_type == "workflow.plan":
        if _should_build_production_pipeline(profile_key, safe_prompt, selected_nodes):
            return _build_agent_production_pipeline_patch(
                canvas=canvas,
                base_client_id=base_client_id,
                base_x=base_x,
                base_y=base_y,
                safe_prompt=safe_prompt,
                selected_nodes=selected_nodes,
                profile_key=profile_key,
                model_code=model_code,
                llm_title=llm_title,
                llm_prompt=llm_prompt,
                product_data=product_data,
                source_edges=source_edges,
            )
        output = _agent_patch_node(
            client_id=output_client_id,
            node_type="note",
            direct_type="prompt_note",
            title=llm_title or "分镜计划",
            icon="镜",
            position={"x": base_x + 360, "y": base_y},
            prompt=llm_prompt or _build_workflow_plan(safe_prompt, selected_nodes, model_code),
            data=product_data(),
        )
        image_client_id = f"{base_client_id}-image"
        video_client_id = f"{base_client_id}-video"
        return {
            "expectedRevision": canvas.revision,
            "nodes": [
                output,
                _agent_patch_node(
                    client_id=image_client_id,
                    node_type="image",
                    direct_type="image_unit",
                    title="分镜首帧生成",
                    icon="图",
                    position={"x": base_x + 720, "y": base_y - 80},
                    prompt="根据分镜计划生成关键首帧，保持角色、服装和场景连续。",
                    data=product_data(),
                ),
                _agent_patch_node(
                    client_id=video_client_id,
                    node_type="video",
                    direct_type="video_unit",
                    title="镜头视频生成",
                    icon="视",
                    position={"x": base_x + 1080, "y": base_y - 80},
                    prompt="基于首帧生成 5 秒镜头，强调镜头运动、角色动作和情绪节奏。",
                    data=product_data(),
                ),
            ],
            "edges": source_edges + [
                _agent_patch_edge(output_client_id, image_client_id, "dependency", "分镜"),
                _agent_patch_edge(image_client_id, video_client_id, "generation", "首帧"),
            ],
        }
    else:
        output = _agent_patch_node(
            client_id=output_client_id,
            node_type="note",
            direct_type="prompt_note",
            title=llm_title or "Agent 创作建议",
            icon="案",
            position={"x": base_x + 360, "y": base_y},
            prompt=llm_prompt or _build_canvas_suggestion(safe_prompt, selected_nodes, model_code),
            data=product_data(),
        )
    return {
        "expectedRevision": canvas.revision,
        "nodes": [output],
        "edges": source_edges,
    }


def _should_build_production_pipeline(profile_key: str, prompt: str, selected_nodes: List[Dict[str, Any]]) -> bool:
    if not selected_nodes:
        return True
    text = prompt.lower()
    keywords = ("灵感", "创意", "剧本", "故事", "短片", "动画", "角色", "场景", "道具", "提取", "制片")
    return profile_key == "story_director" or any(keyword.lower() in text for keyword in keywords)


def _build_agent_production_pipeline_patch(
    *,
    canvas: SluvoCanvas,
    base_client_id: str,
    base_x: float,
    base_y: float,
    safe_prompt: str,
    selected_nodes: List[Dict[str, Any]],
    profile_key: str,
    model_code: str,
    llm_title: str,
    llm_prompt: str,
    product_data,
    source_edges: List[Dict[str, Any]],
) -> Dict[str, Any]:
    intake_client_id = f"{base_client_id}-intake"
    characters_client_id = f"{base_client_id}-characters"
    scenes_client_id = f"{base_client_id}-scenes"
    storyboard_client_id = f"{base_client_id}-storyboard"
    image_client_id = f"{base_client_id}-image"
    video_client_id = f"{base_client_id}-video"
    story_source = _selected_node_prompt_text(selected_nodes) or safe_prompt
    production_plan = llm_prompt or _build_storyboard_plan(story_source, model_code)

    nodes = [
        _agent_patch_node(
            client_id=intake_client_id,
            node_type="note",
            direct_type="prompt_note",
            title=llm_title or "故事总览",
            icon="总",
            position={"x": base_x + 320, "y": base_y - 180},
            prompt=_build_story_intake(story_source, model_code),
            size={"width": 420, "height": 260},
            data=product_data({"stage": "story_overview", "actions": ["提取角色", "拆分分镜"]}),
        ),
        _agent_patch_node(
            client_id=characters_client_id,
            node_type="note",
            direct_type="prompt_note",
            title="角色 / 道具提取",
            icon="角",
            position={"x": base_x + 320, "y": base_y + 130},
            prompt=_build_character_prop_brief(story_source, model_code),
            size={"width": 420, "height": 300},
            data=product_data({"stage": "characters_props", "actions": ["生成角色图", "继续细化"]}),
        ),
        _agent_patch_node(
            client_id=scenes_client_id,
            node_type="note",
            direct_type="prompt_note",
            title="场景设定",
            icon="景",
            position={"x": base_x + 800, "y": base_y + 130},
            prompt=_build_scene_brief(story_source, model_code),
            size={"width": 420, "height": 300},
            data=product_data({"stage": "scenes", "actions": ["生成场景图", "继续细化"]}),
        ),
        _agent_patch_node(
            client_id=storyboard_client_id,
            node_type="note",
            direct_type="prompt_note",
            title="分镜计划",
            icon="镜",
            position={"x": base_x + 800, "y": base_y - 180},
            prompt=production_plan,
            size={"width": 520, "height": 360},
            data=product_data({"stage": "storyboard_plan", "actions": ["生成首帧", "继续拆分"]}),
        ),
        _agent_patch_node(
            client_id=image_client_id,
            node_type="image",
            direct_type="image_unit",
            title="首帧图片生成",
            icon="图",
            position={"x": base_x + 1380, "y": base_y - 180},
            prompt=_build_first_frame_prompt(story_source),
            size={"width": 420, "height": 320},
            data=product_data({"stage": "first_frame"}),
        ),
        _agent_patch_node(
            client_id=video_client_id,
            node_type="video",
            direct_type="video_unit",
            title="镜头视频生成",
            icon="视",
            position={"x": base_x + 1840, "y": base_y - 180},
            prompt=_build_video_prompt(story_source),
            size={"width": 420, "height": 320},
            data=product_data({"stage": "video_shot"}),
        ),
    ]
    source_id = _first_selected_node_id(selected_nodes)
    edges = list(source_edges)
    if source_id:
        # source_edges points to the default output id; use the actual intake node for this pipeline.
        edges = [_agent_patch_edge_from_node(source_id, intake_client_id, "reference", "灵感")]
    edges.extend([
        _agent_patch_edge(intake_client_id, characters_client_id, "dependency", "角色道具"),
        _agent_patch_edge(intake_client_id, scenes_client_id, "dependency", "场景"),
        _agent_patch_edge(intake_client_id, storyboard_client_id, "dependency", "故事"),
        _agent_patch_edge(characters_client_id, storyboard_client_id, "reference", "角色"),
        _agent_patch_edge(scenes_client_id, storyboard_client_id, "reference", "场景"),
        _agent_patch_edge(storyboard_client_id, image_client_id, "generation", "首帧"),
        _agent_patch_edge(image_client_id, video_client_id, "generation", "视频"),
    ])
    return {
        "expectedRevision": canvas.revision,
        "nodes": nodes,
        "edges": edges,
    }


def _agent_profile_label_from_key(profile_key: str) -> str:
    return SLUVO_OFFICIAL_AGENT_PROFILES.get(profile_key, {}).get("name") or "自定义 Agent"


def _agent_patch_origin(selected_nodes: List[Dict[str, Any]]) -> tuple[float, float]:
    positions = [item.get("position") or {} for item in selected_nodes if isinstance(item, dict)]
    xs = [float(pos.get("x", 0)) for pos in positions if isinstance(pos, dict)]
    ys = [float(pos.get("y", 0)) for pos in positions if isinstance(pos, dict)]
    if xs and ys:
        return max(xs) + 420, min(ys)
    return 180.0, 180.0


def _agent_patch_node(
    *,
    client_id: str,
    node_type: str,
    direct_type: str,
    title: str,
    icon: str,
    position: Dict[str, float],
    prompt: str,
    size: Optional[Dict[str, float]] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "clientId": client_id,
        "nodeType": node_type,
        "title": title,
        "position": position,
        "size": size or {"width": 320, "height": 220},
        "status": "idle",
        "data": {
            "clientId": client_id,
            "directType": direct_type,
            "title": title,
            "icon": icon,
            "prompt": prompt,
            "body": prompt,
            "actions": ["审阅", "继续生成"],
            "generationStatus": "idle",
            **(data or {}),
        },
        "ports": {"left": True, "right": True},
        "style": {},
    }


def _agent_patch_edge(source_client_id: str, target_client_id: str, edge_type: str, label: str) -> Dict[str, Any]:
    return {
        "sourceNodeId": None,
        "targetNodeId": None,
        "sourcePortId": "right",
        "targetPortId": "left",
        "edgeType": edge_type,
        "label": label,
        "data": {
            "sourceClientId": source_client_id,
            "targetClientId": target_client_id,
        },
    }


def _agent_patch_edge_from_node(source_node_id: str, target_client_id: str, edge_type: str, label: str) -> Dict[str, Any]:
    return {
        "sourceNodeId": source_node_id,
        "targetNodeId": None,
        "sourcePortId": "right",
        "targetPortId": "left",
        "edgeType": edge_type,
        "label": label,
        "data": {
            "targetClientId": target_client_id,
        },
    }


def _first_selected_node_id(selected_nodes: List[Dict[str, Any]]) -> str:
    for item in selected_nodes:
        if not isinstance(item, dict):
            continue
        value = str(item.get("id") or item.get("nodeId") or "").strip()
        if value and _decode_optional_safe(value):
            return value
        client_value = str(item.get("clientId") or "").strip()
        if client_value:
            return client_value
        if value:
            return value
    return ""


def _selected_node_prompt_text(selected_nodes: List[Dict[str, Any]]) -> str:
    parts: List[str] = []
    for item in selected_nodes:
        if not isinstance(item, dict):
            continue
        for key in ("prompt", "body", "content", "description"):
            text = str(item.get(key) or "").strip()
            if text:
                parts.append(text)
                break
    return "\n".join(parts[:4]).strip()


def _selected_node_titles(selected_nodes: List[Dict[str, Any]]) -> str:
    titles = [str(item.get("title") or (item.get("data") or {}).get("title") or "").strip() for item in selected_nodes if isinstance(item, dict)]
    titles = [item for item in titles if item]
    return "、".join(titles[:6]) or "当前画布"


def _build_canvas_suggestion(prompt: str, selected_nodes: List[Dict[str, Any]], model_code: str) -> str:
    return f"基于「{_selected_node_titles(selected_nodes)}」的创作建议：\n1. 明确故事目标和主要情绪。\n2. 把可复用角色、场景、风格拆成独立参考节点。\n3. 从关键镜头开始生成图片，再连接视频节点。\n\n用户需求：{prompt}"


def _build_consistency_report(prompt: str, selected_nodes: List[Dict[str, Any]], model_code: str) -> str:
    return f"一致性检查报告：\n- 检查对象：{_selected_node_titles(selected_nodes)}。\n- 建议固定角色外观、服装、道具和光线风格。\n- 后续生成前，请把角色参考图连接到每个图片/视频节点。\n\n检查要求：{prompt}"


def _build_polished_prompt(prompt: str, selected_nodes: List[Dict[str, Any]]) -> str:
    source = _selected_node_prompt_text(selected_nodes) or prompt
    return (
        f"{source}\n\n"
        "优化方向：主体清晰，动作明确，环境、光线、镜头语言和风格连续；"
        "适合图片首帧和视频生成，避免抽象空泛词。"
    )


def _compact_story_source(text: str, limit: int = 900) -> str:
    source = str(text or "").strip()
    if len(source) <= limit:
        return source
    return f"{source[:limit].rstrip()}..."


def _build_story_intake(prompt: str, model_code: str) -> str:
    source = _compact_story_source(prompt)
    return (
        f"# 《{_story_title_from_goal(source)}》项目理解\n\n"
        f"## 故事概念\n{_story_concept_from_goal(source)}\n\n"
        f"## 主场景\n{_story_scene_anchor_from_goal(source)}\n\n"
        f"## 情绪基调\n{_story_mood_from_goal(source)}"
    )


def _build_character_prop_brief(prompt: str, model_code: str) -> str:
    source = _compact_story_source(prompt, 700)
    return (
        "# 角色 / 道具提取\n\n"
        f"- 主角：{_story_protagonist_from_goal(source)}。\n"
        "- 对手：可以先用影子、车内人声、陌生来电或环境监控表现，不急于正面露出。\n"
        f"- 道具：{_story_prop_from_goal(source)}。\n"
        f"- 一致性：服装、光线和表演都服务于「{_story_mood_from_goal(source)}」。"
    )


def _build_scene_brief(prompt: str, model_code: str) -> str:
    source = _compact_story_source(prompt, 700)
    return (
        "# 场景设定\n\n"
        f"- 主场景：{_story_scene_anchor_from_goal(source)}。\n"
        f"- 氛围：{_story_mood_from_goal(source)}。\n"
        "- 画面约束：保持天气、光线方向、反光质感和空间层次连续。\n"
        "- 可生成元素：人物近景、道具特写、环境建立镜头、带遮挡的窥视视角。"
    )


def _build_first_frame_prompt(prompt: str) -> str:
    source = _compact_story_source(prompt, 520)
    return (
        "根据分镜计划生成第一张关键首帧。画面需要主体清晰、角色外观一致、场景信息明确，"
        "保留镜头景别、光线、色彩和情绪。\n\n"
        f"故事来源：{source}"
    )


def _build_video_prompt(prompt: str) -> str:
    source = _compact_story_source(prompt, 520)
    return (
        "基于首帧生成短视频镜头。描述镜头运动、角色动作、节奏、转场和情绪变化，"
        "保持角色、场景和光线连续。\n\n"
        f"故事来源：{source}"
    )


def _build_storyboard_plan(prompt: str, model_code: str) -> str:
    source = _compact_story_source(prompt, 800)
    return (
        "# 分镜计划\n\n"
        f"1. 建立镜头：{_story_scene_anchor_from_goal(source)}，用环境声和远景建立气氛。\n"
        f"2. 发现镜头：主角注意到{_story_prop_from_goal(source)}，镜头切到眼神和手部动作。\n"
        "3. 接近镜头：中近景跟随主角移动，前景遮挡制造不确定感。\n"
        "4. 线索镜头：道具或屏幕出现关键信息，声音突然变弱或被雨声吞没。\n"
        "5. 转折镜头：车灯、门缝、人影或来电打断主角，留下下一镜悬念。"
    )


def _build_workflow_plan(prompt: str, selected_nodes: List[Dict[str, Any]], model_code: str) -> str:
    return f"分镜工作流计划：\n1. 从需求中提取场景目标和角色动作。\n2. 生成 3-5 个关键镜头，每个镜头保留景别、动作、情绪和画面提示词。\n3. 先生成首帧图片，再接视频生成节点。\n\n需求：{prompt}\n来源：{_selected_node_titles(selected_nodes)}"


def create_sluvo_agent_action(
    session: Session,
    *,
    agent_session: SluvoAgentSession,
    action_payload: Dict[str, Any],
) -> SluvoAgentAction:
    target_node_id = _decode_optional_safe(action_payload.get("targetNodeId")) or agent_session.target_node_id
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
        _update_agent_node_execution_state(session, action, status="succeeded", message="提案已写入画布")
    except Exception as exc:
        action.status = "failed"
        action.error_json = _json_dump({"message": str(exc)})
        _update_agent_node_execution_state(session, action, status="failed", message=str(exc))
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
    _update_agent_node_execution_state(session, action, status="cancelled", message="提案已取消")
    session.add(action)
    session.commit()
    session.refresh(action)
    return action


def _update_agent_node_execution_state(session: Session, action: SluvoAgentAction, *, status: str, message: str) -> None:
    if not action.target_node_id:
        return
    node = session.get(SluvoCanvasNode, action.target_node_id)
    if not node or node.deleted_at is not None:
        return
    data = _json_load(node.data_json, {})
    if not isinstance(data, dict):
        data = {}
    summary = _json_load(action.input_json, {}).get("contextSummary") or {}
    data.update(
        {
            "agentLastActionId": encode_id(action.id),
            "agentLastActionStatus": status,
            "agentLastProposal": _agent_action_summary(action.action_type),
            "agentLastMessage": message,
            "agentLastRunAt": _utc_now().isoformat(),
            "agentName": summary.get("agentName") or data.get("agentName"),
            "agentTemplateId": summary.get("agentTemplateId") or data.get("agentTemplateId"),
            "generationStatus": "idle" if status in {"succeeded", "cancelled"} else "error",
            "generationMessage": message,
        }
    )
    node.data_json = _json_dump(data)
    node.revision = int(node.revision or 1) + 1
    node.updated_at = _utc_now()
    session.add(node)
