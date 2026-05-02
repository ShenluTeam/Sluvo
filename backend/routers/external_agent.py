from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from core.security import decode_id, encode_id
from database import get_session
from dependencies import get_current_team, get_current_user, require_team_permission
from models import Team, TeamMemberLink, User
from schemas import (
    EXTERNAL_PROVIDER_SHENLU_AGENT,
    ExternalAgentChatRequest,
    ExternalAgentImportCharactersRequest,
    ExternalAgentImportPanelsRequest,
    ExternalAgentImportScriptRequest,
    ExternalAgentSessionCreateRequest,
    ExternalAgentSettingsUpdateRequest,
    ExternalProviderCredentialPermissionUpdateRequest,
    ExternalProviderCredentialUpdateRequest,
)
from services.access_service import require_episode_team_access, require_script_team_access
from services.external_agent_import_service import (
    import_character_assets,
    import_panels_to_episode,
    import_script_content,
)
from services.external_agent_service import (
    activate_external_session,
    append_chat_message,
    create_external_session,
    generate_user_credential,
    get_session_detail,
    get_supported_providers,
    get_user_credential,
    list_script_sessions,
    list_workspace_files,
    require_script_session,
    serialize_credential,
    serialize_external_session,
    upsert_user_credential,
    save_external_session_settings,
    set_user_credential_openclaw_enabled,
)

router = APIRouter()


def _model_to_dict(model, **kwargs):
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    if hasattr(model, "dict"):
        return model.dict(**kwargs)
    return dict(model or {})


@router.get("/api/external-agent/providers")
async def get_external_agent_providers(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    providers = []
    for item in get_supported_providers():
        credential = get_user_credential(session, user_id=user.id, provider=item["key"])
        providers.append({**item, **serialize_credential(credential, item["key"])})
    return providers


@router.get("/api/external-agent/credentials/{provider}")
async def get_external_agent_credential(
    provider: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    credential = get_user_credential(session, user_id=user.id, provider=provider)
    return serialize_credential(credential, provider)


@router.put("/api/external-agent/credentials/{provider}")
async def save_external_agent_credential(
    provider: str,
    payload: ExternalProviderCredentialUpdateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    token = str(payload.token or "").strip()
    if not token:
        raise HTTPException(status_code=400, detail="Token 不能为空")
    credential = upsert_user_credential(session, user=user, provider=provider, token=token)
    return serialize_credential(credential, provider)


@router.patch("/api/external-agent/credentials/{provider}/permissions")
async def update_external_agent_credential_permissions(
    provider: str,
    payload: ExternalProviderCredentialPermissionUpdateRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    credential = set_user_credential_openclaw_enabled(
        session,
        user=user,
        provider=provider,
        enabled=payload.openclaw_api_enabled,
    )
    return serialize_credential(credential, provider)


@router.post("/api/external-agent/credentials/{provider}/generate")
async def generate_external_agent_credential(
    provider: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    try:
        credential, plain_token = generate_user_credential(session, user=user, provider=provider)
        return serialize_credential(credential, provider, plain_token=plain_token)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"无法生成 token 密钥: {exc}")


@router.post("/api/external-agent/credentials/{provider}/refresh")
async def refresh_external_agent_credential(
    provider: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    raise HTTPException(status_code=410, detail="API Key 不支持续期刷新，请在用户中心手动生成新的 Key")


@router.get("/api/scripts/{script_id}/external-agent/sessions")
async def get_script_external_sessions(
    script_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    items = list_script_sessions(session, team=team, script_id=decode_id(script_id))
    return [serialize_external_session(item) for item in items]


@router.post("/api/scripts/{script_id}/external-agent/sessions")
async def create_script_external_session(
    script_id: str,
    payload: ExternalAgentSessionCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    real_script_id = decode_id(script_id)
    require_script_team_access(session, team, real_script_id)
    real_episode_id = decode_id(payload.episode_id) if payload.episode_id else None
    if real_episode_id is not None:
        episode = require_episode_team_access(session, team, real_episode_id)
        if episode.script_id != real_script_id:
            raise HTTPException(status_code=400, detail="目标分集不属于当前剧本")
    item = create_external_session(
        session,
        team=team,
        user=user,
        script_id=real_script_id,
        provider_key=payload.provider or EXTERNAL_PROVIDER_SHENLU_AGENT,
        name=payload.name,
        episode_id=real_episode_id,
    )
    return serialize_external_session(item)


@router.post("/api/external-agent/sessions/{session_id}/activate")
async def activate_script_external_session(
    session_id: str,
    script_id: Optional[str] = None,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    item = activate_external_session(
        session,
        team=team,
        session_id=decode_id(session_id),
        script_id=decode_id(script_id) if script_id else None,
    )
    return serialize_external_session(item)


@router.patch("/api/external-agent/sessions/{session_id}/settings")
async def update_external_agent_settings(
    session_id: str,
    payload: ExternalAgentSettingsUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    item = require_script_session(session, team=team, session_id=decode_id(session_id))
    updated = save_external_session_settings(
        session,
        user=user,
        session_obj=item,
        settings_payload=_model_to_dict(payload.settings, exclude_none=True),
        episode_id=decode_id(payload.episode_id) if payload.episode_id else None,
    )
    return serialize_external_session(updated)


@router.post("/api/external-agent/sessions/{session_id}/chat")
async def send_external_agent_chat(
    session_id: str,
    payload: ExternalAgentChatRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    item = require_script_session(session, team=team, session_id=decode_id(session_id))
    result = append_chat_message(session, user=user, session_obj=item, message=payload.message)
    return {
        "session": serialize_external_session(result["session"]),
        "message": {"id": encode_id(result["message"].id), "reply_text": result["message"].reply_text or ""},
        "reply": result["provider_result"].get("reply") or {},
        "actions": result["provider_result"].get("actions") or [],
        "workspace": result["provider_result"].get("workspace") or {},
    }


@router.get("/api/external-agent/sessions/{session_id}")
async def get_external_agent_session_detail(
    session_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    item = require_script_session(session, team=team, session_id=decode_id(session_id))
    return get_session_detail(session, user=user, session_obj=item)


@router.get("/api/external-agent/sessions/{session_id}/files")
async def get_external_agent_workspace_files(
    session_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    item = require_script_session(session, team=team, session_id=decode_id(session_id))
    return {"files": list_workspace_files(session, user=user, session_obj=item)}


@router.post("/api/external-agent/sessions/{session_id}/import/script")
async def import_external_agent_script(
    session_id: str,
    payload: ExternalAgentImportScriptRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    item = require_script_session(session, team=team, session_id=decode_id(session_id))
    result = import_script_content(session, team=team, external_session=item, mode=payload.mode, name=payload.name)
    return {
        "status": "success",
        "mode": payload.mode,
        "script_id": encode_id(result["script_id"]) if result.get("script_id") else None,
        "episode_id": encode_id(result["episode_id"]) if result.get("episode_id") else None,
    }


@router.post("/api/external-agent/sessions/{session_id}/import/characters")
async def import_external_agent_characters(
    session_id: str,
    payload: ExternalAgentImportCharactersRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    item = require_script_session(session, team=team, session_id=decode_id(session_id))
    result = import_character_assets(session, team=team, external_session=item)
    return {
        "status": "success",
        "created_count": result["created_count"],
        "resource_ids": [encode_id(resource_id) for resource_id in result["resource_ids"]],
    }


@router.post("/api/external-agent/sessions/{session_id}/import/panels")
async def import_external_agent_panels(
    session_id: str,
    payload: ExternalAgentImportPanelsRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    item = require_script_session(session, team=team, session_id=decode_id(session_id))
    target_episode_id = decode_id(payload.episode_id) if payload.episode_id else item.episode_id
    if not target_episode_id:
        raise HTTPException(status_code=400, detail="请先绑定目标分集后再导入分镜")
    episode = require_episode_team_access(session, team, target_episode_id)
    if episode.script_id != item.script_id:
        raise HTTPException(status_code=400, detail="目标分集不属于当前剧本")
    result = import_panels_to_episode(session, external_session=item, episode_id=target_episode_id)
    return {
        "status": "success",
        "created_count": result["created_count"],
        "panel_ids": [encode_id(panel_id) for panel_id in result["panel_ids"]],
        "episode_id": encode_id(target_episode_id),
    }
