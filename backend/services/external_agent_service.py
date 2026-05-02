from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from core.security import encode_id
from models import ExternalAgentMessage, ExternalAgentSession, ExternalProviderCredential, Episode, Script, Team, User
from schemas import EXTERNAL_PROVIDER_SHENLU_AGENT
from services.access_service import require_script_team_access
from services.external_agent_crypto import decrypt_token, encrypt_token, mask_token
from services.external_agent_providers.shenlu_agent_provider import ShenluAgentProvider
from services.openclaw_api_key_service import apply_api_key_fingerprint, find_openclaw_credential_by_api_key

TOKEN_VALID_DAYS = 30


def _json_loads(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _provider_registry() -> Dict[str, ShenluAgentProvider]:
    provider = ShenluAgentProvider()
    return {provider.provider_key: provider}


def get_supported_providers() -> List[Dict[str, str]]:
    return [{"key": EXTERNAL_PROVIDER_SHENLU_AGENT, "label": "神鹿AI导演助理"}]


def _utc_now() -> datetime:
    return datetime.utcnow()


def _build_expiry() -> datetime:
    return _utc_now() + timedelta(days=TOKEN_VALID_DAYS)


def _generate_api_token(provider: str) -> str:
    prefix = str(provider or "shenlu_agent").replace("_agent", "").replace("_", "-")
    return f"{prefix}-{secrets.token_urlsafe(24)}"


def _looks_like_local_stub(result: Dict[str, Any]) -> bool:
    raw = result.get("raw") or {}
    return str(raw.get("fallback_mode") or "").strip() == "local_stub"


def _extract_script_text_from_chat_message(message: str) -> str:
    text = str(message or "").strip()
    if len(text) < 20:
        return ""

    first_line = text.splitlines()[0].strip()
    for separator in ("：", ":"):
        if separator in first_line:
            prefix, suffix = text.split(separator, 1)
            if any(keyword in prefix.lower() for keyword in ("剧本", "原文", "script", "screenplay")):
                candidate = suffix.strip()
                if len(candidate) >= 20:
                    return candidate

    lowered = text.lower()
    screenplay_signals = ("【画面】", "场", "内", "外", "screenplay", "剧本", "原文")
    if any(signal.lower() in lowered for signal in screenplay_signals) and ("\n" in text or len(text) >= 60):
        return text
    return ""


def _merge_workspace_file(
    workspace: Dict[str, Any],
    *,
    file_id: str,
    name: str,
    docu_type: str,
    records: List[Dict[str, Any]],
    updated_at: datetime,
) -> Dict[str, Any]:
    files = list((workspace or {}).get("files") or [])
    normalized_record_count = len(records)
    next_file = {
        "file_id": file_id,
        "name": name,
        "docu_type": docu_type,
        "record_count": normalized_record_count,
        "updated_at": _iso(updated_at),
        "records": records,
    }
    replaced = False
    for index, item in enumerate(files):
        current_id = str(item.get("file_id") or item.get("id") or "")
        if current_id == file_id:
            files[index] = next_file
            replaced = True
            break
    if not replaced:
        files.append(next_file)
    next_workspace = dict(workspace or {})
    next_workspace["files"] = files
    return next_workspace


def _apply_local_stub_chat_effects(
    session: Session,
    *,
    session_obj: ExternalAgentSession,
    message: str,
    result: Dict[str, Any],
) -> Dict[str, Any]:
    if not _looks_like_local_stub(result):
        return result

    script_text = _extract_script_text_from_chat_message(message)
    if not script_text:
        return result

    updated_at = datetime.utcnow()
    script = session.get(Script, session_obj.script_id)
    episode = session.get(Episode, session_obj.episode_id) if session_obj.episode_id else None

    if episode and episode.script_id == session_obj.script_id:
        episode.source_text = script_text
        session.add(episode)

    if script:
        if not str(script.source_text or "").strip():
            script.source_text = script_text
            session.add(script)
        elif episode and str(script.source_text or "").strip() == str(episode.source_text or "").strip():
            script.source_text = script_text
            session.add(script)
        elif episode:
            episode_count = len(session.exec(select(Episode).where(Episode.script_id == script.id)).all())
            if episode_count <= 1:
                script.source_text = script_text
                session.add(script)

    workspace = dict(result.get("workspace") or {})
    target_name = (episode.title if episode and episode.title else "剧本原文")
    file_id = f"script-{session_obj.id}-{session_obj.episode_id or 'project'}"
    records = [
        {
            "text": script_text,
            "script_id": session_obj.script_id,
            "episode_id": session_obj.episode_id,
            "source": "openclaw_local_chat",
        }
    ]
    result["workspace"] = _merge_workspace_file(
        workspace,
        file_id=file_id,
        name=target_name,
        docu_type="script",
        records=records,
        updated_at=updated_at,
    )
    result["reply"] = {
        **(result.get("reply") or {}),
        "agent": str((result.get("reply") or {}).get("agent") or "shenlu_agent"),
        "text": "已接收并保存当前剧集的剧本原文。你可以继续保存 settings、创建下一集，或继续让神鹿整理角色与分镜。",
    }
    return result


def get_provider(provider_key: str):
    provider = _provider_registry().get(str(provider_key or "").strip())
    if not provider:
        raise HTTPException(status_code=400, detail="不支持的AI导演助理 provider")
    return provider


def upsert_user_credential(session: Session, *, user: User, provider: str, token: str) -> ExternalProviderCredential:
    existing = session.exec(
        select(ExternalProviderCredential).where(
            ExternalProviderCredential.user_id == user.id,
            ExternalProviderCredential.provider == provider,
        )
    ).first()
    encrypted = encrypt_token(token)
    masked = mask_token(token)
    if existing:
        existing.token_encrypted = encrypted
        existing.token_masked = masked
        apply_api_key_fingerprint(existing, token)
        existing.is_active = True
        existing.openclaw_api_enabled = True
        existing.expires_at = _build_expiry()
        existing.updated_at = _utc_now()
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    credential = ExternalProviderCredential(
        user_id=user.id,
        provider=provider,
        token_encrypted=encrypted,
        token_masked=masked,
        token_hash=None,
        token_prefix=None,
        is_active=True,
        openclaw_api_enabled=True,
        expires_at=_build_expiry(),
        updated_at=_utc_now(),
    )
    apply_api_key_fingerprint(credential, token)
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return credential


def generate_user_credential(session: Session, *, user: User, provider: str) -> Tuple[ExternalProviderCredential, str]:
    existing = get_user_credential(session, user_id=user.id, provider=provider)
    if existing:
        if existing.expires_at is None or existing.expires_at > _utc_now():
            expiry_text = existing.expires_at.strftime("%Y-%m-%d") if existing.expires_at else "当前周期结束"
            raise HTTPException(
                status_code=409,
                detail=f"当前 API Key 仍在有效期内，请在 {expiry_text} 到期后再手动生成新的 Key",
            )
    plain_token = _generate_api_token(provider)
    credential = upsert_user_credential(session, user=user, provider=provider, token=plain_token)
    return credential, plain_token


def get_user_credential(session: Session, *, user_id: int, provider: str) -> Optional[ExternalProviderCredential]:
    return session.exec(
        select(ExternalProviderCredential).where(
            ExternalProviderCredential.user_id == user_id,
            ExternalProviderCredential.provider == provider,
            ExternalProviderCredential.is_active == True,
        )
    ).first()


def require_user_credential(session: Session, *, user: User, provider: str) -> ExternalProviderCredential:
    credential = get_user_credential(session, user_id=user.id, provider=provider)
    if not credential:
        raise HTTPException(status_code=400, detail="请先在账户设置中配置AI导演助理 Token")
    if credential.expires_at and credential.expires_at <= _utc_now():
        raise HTTPException(status_code=400, detail="API Key 已过期，请先在账户设置中手动生成新的 Key")
    return credential


def set_user_credential_openclaw_enabled(
    session: Session,
    *,
    user: User,
    provider: str,
    enabled: bool,
) -> ExternalProviderCredential:
    credential = get_user_credential(session, user_id=user.id, provider=provider)
    if not credential:
        raise HTTPException(status_code=404, detail="API Key 不存在，请先在用户中心生成")
    credential.openclaw_api_enabled = bool(enabled)
    credential.updated_at = _utc_now()
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return credential


def find_openclaw_credential_by_token(
    session: Session,
    *,
    token: str,
    provider: str = EXTERNAL_PROVIDER_SHENLU_AGENT,
) -> Optional[ExternalProviderCredential]:
    normalized = str(token or "").strip()
    if not normalized:
        return None
    credentials = session.exec(
        select(ExternalProviderCredential).where(
            ExternalProviderCredential.provider == provider,
            ExternalProviderCredential.is_active == True,
        )
    ).all()
    for credential in credentials:
        try:
            plain_token = decrypt_token(credential.token_encrypted)
        except Exception:
            continue
        if plain_token == normalized:
            return credential
    return None


def serialize_credential(
    credential: Optional[ExternalProviderCredential],
    provider: str,
    plain_token: Optional[str] = None,
) -> Dict[str, Any]:
    expires_at = credential.expires_at.isoformat() if credential and credential.expires_at else None
    is_expired = bool(credential and credential.expires_at and credential.expires_at <= _utc_now())
    token_value = plain_token or ""
    if not token_value and credential and credential.token_encrypted:
        try:
            token_value = decrypt_token(credential.token_encrypted)
        except Exception:
            token_value = ""
    return {
        "provider": provider,
        "configured": bool(credential),
        "token_masked": credential.token_masked if credential else "",
        "openclaw_api_enabled": bool(credential and credential.openclaw_api_enabled),
        "expires_at": expires_at,
        "is_expired": is_expired,
        "token_value": token_value,
    }


def generate_user_credential(session: Session, *, user: User, provider: str) -> Tuple[ExternalProviderCredential, str]:
    existing = get_user_credential(session, user_id=user.id, provider=provider)
    if existing and (existing.expires_at is None or existing.expires_at > _utc_now()):
        expiry_text = existing.expires_at.strftime("%Y-%m-%d") if existing.expires_at else "当前周期结束"
        raise HTTPException(status_code=409, detail=f"当前 API Key 仍在有效期内，请在 {expiry_text} 到期后再手动生成新的 Key")
    plain_token = _generate_api_token(provider)
    credential = upsert_user_credential(session, user=user, provider=provider, token=plain_token)
    return credential, plain_token


def require_user_credential(session: Session, *, user: User, provider: str) -> ExternalProviderCredential:
    credential = get_user_credential(session, user_id=user.id, provider=provider)
    if not credential:
        raise HTTPException(status_code=400, detail="请先在账户设置中生成 OpenClaw API Key")
    if credential.expires_at and credential.expires_at <= _utc_now():
        raise HTTPException(status_code=400, detail="OpenClaw API Key 已过期，请先在账户设置中手动生成新的 Key")
    return credential


def set_user_credential_openclaw_enabled(
    session: Session,
    *,
    user: User,
    provider: str,
    enabled: bool,
) -> ExternalProviderCredential:
    credential = get_user_credential(session, user_id=user.id, provider=provider)
    if not credential:
        raise HTTPException(status_code=404, detail="API Key 不存在，请先在用户中心生成")
    credential.openclaw_api_enabled = bool(enabled)
    credential.updated_at = _utc_now()
    session.add(credential)
    session.commit()
    session.refresh(credential)
    return credential


def find_openclaw_credential_by_token(
    session: Session,
    *,
    token: str,
    provider: str = EXTERNAL_PROVIDER_SHENLU_AGENT,
) -> Optional[ExternalProviderCredential]:
    return find_openclaw_credential_by_api_key(session, api_key=token, provider=provider)


def serialize_credential(
    credential: Optional[ExternalProviderCredential],
    provider: str,
    plain_token: Optional[str] = None,
) -> Dict[str, Any]:
    expires_at = credential.expires_at.isoformat() if credential and credential.expires_at else None
    is_expired = bool(credential and credential.expires_at and credential.expires_at <= _utc_now())
    token_value = plain_token or ""
    if not token_value and credential and credential.token_encrypted:
        try:
            token_value = decrypt_token(credential.token_encrypted)
        except Exception:
            token_value = ""
    return {
        "provider": provider,
        "configured": bool(credential),
        "token_masked": credential.token_masked if credential else "",
        "api_key_masked": credential.token_masked if credential else "",
        "openclaw_api_enabled": bool(credential and credential.openclaw_api_enabled),
        "expires_at": expires_at,
        "is_expired": is_expired,
        "token_value": token_value,
        "api_key_value": token_value,
    }


def serialize_external_session(session_obj: ExternalAgentSession) -> Dict[str, Any]:
    return {
        "id": encode_id(session_obj.id),
        "script_id": encode_id(session_obj.script_id),
        "episode_id": encode_id(session_obj.episode_id) if session_obj.episode_id else None,
        "provider": session_obj.provider,
        "base_id": session_obj.base_id,
        "base_name": session_obj.base_name or "",
        "provider_episode_id": session_obj.provider_episode_id or "",
        "session_id": session_obj.session_id or "",
        "settings": _json_loads(session_obj.settings_json, {}),
        "workspace_snapshot": _json_loads(session_obj.workspace_snapshot_json, {}),
        "last_reply_text": session_obj.last_reply_text or "",
        "status": session_obj.status,
        "is_active": session_obj.is_active,
        "last_synced_at": session_obj.last_synced_at.isoformat() if session_obj.last_synced_at else None,
        "created_at": session_obj.created_at.isoformat() if session_obj.created_at else None,
        "updated_at": session_obj.updated_at.isoformat() if session_obj.updated_at else None,
    }


def serialize_external_message(message: ExternalAgentMessage) -> Dict[str, Any]:
    return {
        "id": encode_id(message.id),
        "role": message.role,
        "message": message.message,
        "reply_text": message.reply_text or "",
        "reply_json": _json_loads(message.reply_json, {}),
        "actions_json": _json_loads(message.actions_json, []),
        "workspace_snapshot_json": _json_loads(message.workspace_snapshot_json, {}),
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


def list_script_sessions(session: Session, *, team: Team, script_id: int) -> List[ExternalAgentSession]:
    require_script_team_access(session, team, script_id)
    return session.exec(
        select(ExternalAgentSession)
        .where(ExternalAgentSession.script_id == script_id)
        .order_by(ExternalAgentSession.is_active.desc(), ExternalAgentSession.updated_at.desc(), ExternalAgentSession.id.desc())
    ).all()


def require_script_session(session: Session, *, team: Team, session_id: int, script_id: int | None = None) -> ExternalAgentSession:
    item = session.get(ExternalAgentSession, session_id)
    if not item:
        raise HTTPException(status_code=404, detail="AI导演助理会话不存在")
    require_script_team_access(session, team, item.script_id)
    if script_id is not None and item.script_id != script_id:
        raise HTTPException(status_code=403, detail="当前会话不属于该剧本")
    return item


def _ensure_only_one_active(session: Session, *, script_id: int, target_session_id: int | None) -> None:
    items = session.exec(select(ExternalAgentSession).where(ExternalAgentSession.script_id == script_id)).all()
    for item in items:
        should_activate = target_session_id is not None and item.id == target_session_id
        if item.is_active != should_activate:
            item.is_active = should_activate
            item.updated_at = datetime.utcnow()
            session.add(item)


def create_external_session(
    session: Session,
    *,
    team: Team,
    user: User,
    script_id: int,
    provider_key: str,
    name: str | None,
    episode_id: int | None,
) -> ExternalAgentSession:
    require_script_team_access(session, team, script_id)
    provider = get_provider(provider_key)
    credential = require_user_credential(session, user=user, provider=provider_key)
    provider_result = provider.create_project(decrypt_token(credential.token_encrypted), name=name)

    item = ExternalAgentSession(
        script_id=script_id,
        episode_id=episode_id,
        user_id=user.id,
        provider=provider_key,
        base_id=provider_result["base_id"],
        base_name=provider_result.get("base_name"),
        provider_episode_id=provider_result.get("provider_episode_id"),
        status="created",
        is_active=False,
        workspace_snapshot_json=_dump_json({}),
        settings_json=_dump_json({}),
        last_synced_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(item)
    session.flush()
    _ensure_only_one_active(session, script_id=script_id, target_session_id=item.id)
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def activate_external_session(session: Session, *, team: Team, session_id: int, script_id: int | None = None) -> ExternalAgentSession:
    item = require_script_session(session, team=team, session_id=session_id, script_id=script_id)
    _ensure_only_one_active(session, script_id=item.script_id, target_session_id=item.id)
    item.is_active = True
    item.updated_at = datetime.utcnow()
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def create_external_episode_session(
    session: Session,
    *,
    user: User,
    script_id: int,
    episode_id: int,
    provider_key: str,
    base_id: str,
    base_name: str | None,
    provider_episode_id: str,
    activate: bool = False,
) -> ExternalAgentSession:
    item = ExternalAgentSession(
        script_id=script_id,
        episode_id=episode_id,
        user_id=user.id,
        provider=provider_key,
        base_id=base_id,
        base_name=base_name,
        provider_episode_id=provider_episode_id,
        status="created",
        is_active=False,
        workspace_snapshot_json=_dump_json({}),
        settings_json=_dump_json({}),
        last_synced_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(item)
    session.flush()
    if activate:
        _ensure_only_one_active(session, script_id=script_id, target_session_id=item.id)
        item.is_active = True
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def save_external_session_settings(
    session: Session,
    *,
    user: User,
    session_obj: ExternalAgentSession,
    settings_payload: Dict[str, Any],
    episode_id: int | None,
) -> ExternalAgentSession:
    provider = get_provider(session_obj.provider)
    credential = require_user_credential(session, user=user, provider=session_obj.provider)
    settings_data = provider.save_settings(
        decrypt_token(credential.token_encrypted),
        base_id=session_obj.base_id,
        settings=settings_payload,
    )
    session_obj.settings_json = _dump_json(settings_data)
    if episode_id is not None:
        episode = session.get(Episode, episode_id)
        if not episode or episode.script_id != session_obj.script_id:
            raise HTTPException(status_code=400, detail="目标分集不属于当前剧本")
        session_obj.episode_id = episode_id
    session_obj.updated_at = datetime.utcnow()
    session_obj.last_synced_at = datetime.utcnow()
    session.add(session_obj)
    session.commit()
    session.refresh(session_obj)
    return session_obj


def append_chat_message(
    session: Session,
    *,
    user: User,
    session_obj: ExternalAgentSession,
    message: str,
) -> Dict[str, Any]:
    provider = get_provider(session_obj.provider)
    credential = require_user_credential(session, user=user, provider=session_obj.provider)
    provider_episode_id = session_obj.provider_episode_id or ""
    if not provider_episode_id:
        raise HTTPException(status_code=400, detail="当前会话缺少外部分集标识，无法继续对话")
    result = provider.chat(
        decrypt_token(credential.token_encrypted),
        base_id=session_obj.base_id,
        provider_episode_id=provider_episode_id,
        message=message,
        session_id=session_obj.session_id,
    )
    result = _apply_local_stub_chat_effects(
        session,
        session_obj=session_obj,
        message=message,
        result=result,
    )
    reply = result.get("reply") or {}
    actions = result.get("actions") or []
    workspace = result.get("workspace") or {}

    session_obj.session_id = result.get("session_id") or session_obj.session_id
    session_obj.workspace_snapshot_json = _dump_json(workspace)
    session_obj.last_reply_text = str(reply.get("text") or "")
    session_obj.status = "ready"
    session_obj.last_synced_at = datetime.utcnow()
    session_obj.updated_at = datetime.utcnow()
    session.add(session_obj)

    row = ExternalAgentMessage(
        session_ref_id=session_obj.id,
        role="user",
        message=message,
        reply_text=str(reply.get("text") or ""),
        reply_json=_dump_json(reply),
        actions_json=_dump_json(actions),
        workspace_snapshot_json=_dump_json(workspace),
    )
    session.add(row)
    session.commit()
    session.refresh(session_obj)
    session.refresh(row)
    return {"session": session_obj, "message": row, "provider_result": result}


def get_session_detail(session: Session, *, user: User, session_obj: ExternalAgentSession) -> Dict[str, Any]:
    settings_data = _json_loads(session_obj.settings_json, {})

    messages = session.exec(
        select(ExternalAgentMessage)
        .where(ExternalAgentMessage.session_ref_id == session_obj.id)
        .order_by(ExternalAgentMessage.created_at.asc(), ExternalAgentMessage.id.asc())
    ).all()
    payload = serialize_external_session(session_obj)
    payload["settings"] = settings_data
    payload["messages"] = [serialize_external_message(item) for item in messages]
    return payload


def list_workspace_files(session: Session, *, user: User, session_obj: ExternalAgentSession) -> List[Dict[str, Any]]:
    provider = get_provider(session_obj.provider)
    credential = require_user_credential(session, user=user, provider=session_obj.provider)
    snapshot = _json_loads(session_obj.workspace_snapshot_json, {})
    files = provider.list_workspace_files(
        decrypt_token(credential.token_encrypted),
        base_id=session_obj.base_id,
        provider_episode_id=session_obj.provider_episode_id or "",
        workspace_snapshot=snapshot,
    )
    next_snapshot = dict(snapshot)
    next_snapshot["files"] = files
    session_obj.workspace_snapshot_json = _dump_json(next_snapshot)
    session_obj.updated_at = datetime.utcnow()
    session_obj.last_synced_at = datetime.utcnow()
    session.add(session_obj)
    session.commit()
    session.refresh(session_obj)
    return files
