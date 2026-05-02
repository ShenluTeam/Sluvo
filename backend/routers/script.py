from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from core.security import decode_id, encode_id
from database import get_session
from dependencies import get_current_team, require_team_permission
from models import Episode, Team, TeamMemberLink
from schemas import (
    EpisodeCreate,
    EpisodeSplitCommitRequest,
    EpisodeSplitPreviewRequest,
    EpisodeUpdateRequest,
    ScriptCreate,
    ScriptSourceUpdateRequest,
    ScriptUpdate,
)
from services.access_service import require_episode_team_access, require_script_team_access
from services.agent_workflow_service import AgentWorkflowService
from services.delete_cleanup_service import cleanup_episode_dependencies
from services.episode_ai_split_service import build_ai_split_preview
from services.episode_split_service import build_split_preview, commit_episode_splits
from services.script_service import (
    create_script as create_script_service,
    delete_script as delete_script_service,
    list_scripts,
    update_script as update_script_service,
)
from services.storyboard_mode_service import sync_episode_storyboard_mode
from services.user_dashboard_service import mark_script_access_by_script_id
from services.workflow_preset_service import (
    normalize_workflow_settings,
    serialize_episode_workflow,
    serialize_script_workflow,
    workflow_override_to_json,
)

router = APIRouter()


def _serialize_script(script):
    return {
        **script.dict(),
        "id": encode_id(script.id),
        "hash_id": encode_id(script.id),
        **serialize_script_workflow(script),
    }


def _serialize_episode(script, episode):
    return {
        **episode.dict(),
        "id": encode_id(episode.id),
        "hash_id": encode_id(episode.id),
        **serialize_episode_workflow(script, episode),
    }


def _get_script_or_404(script_id: str, team: Team, session: Session):
    return require_script_team_access(session, team, decode_id(script_id))


@router.post("/api/scripts")
async def create_script(
    script: ScriptCreate,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    new_script = create_script_service(
        session,
        team,
        name=script.name,
        description=script.description,
        aspect_ratio=script.aspect_ratio,
        style_preset=script.style_preset,
        default_storyboard_mode=script.default_storyboard_mode,
        workflow_settings_json=script.workflow_settings_json,
    )
    return _serialize_script(new_script)


@router.get("/api/scripts")
async def get_scripts(
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    scripts = list_scripts(session, team)
    return [_serialize_script(script) for script in scripts]


@router.delete("/api/scripts/{script_id}")
async def delete_script(
    script_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    delete_script_service(session, team, decode_id(script_id))
    return {"status": "success"}


@router.put("/api/scripts/{script_id}")
async def update_script(
    script_id: str,
    update_data: ScriptUpdate,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = update_script_service(
        session,
        team,
        decode_id(script_id),
        aspect_ratio=update_data.aspect_ratio,
        style_preset=update_data.style_preset,
        default_storyboard_mode=update_data.default_storyboard_mode,
        workflow_settings_json=update_data.workflow_settings_json,
    )
    return _serialize_script(script)


@router.get("/api/scripts/{script_id}/episodes")
async def get_episodes(
    script_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = _get_script_or_404(script_id, team, session)
    mark_script_access_by_script_id(session, script.id)
    session.commit()
    episodes = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc())).all()
    return [_serialize_episode(script, episode) for episode in episodes]


@router.post("/api/episodes")
async def create_episode(
    ep: EpisodeCreate,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    now = datetime.utcnow()
    script = require_script_team_access(session, team, decode_id(ep.script_id))
    workflow_settings = normalize_workflow_settings(
        getattr(script, "workflow_settings_json", "{}"),
        legacy_aspect_ratio=getattr(script, "aspect_ratio", None),
        legacy_style_preset=getattr(script, "style_preset", None),
    )
    default_storyboard_mode = workflow_settings.get("default_storyboard_mode") or "comic"
    insert_after_episode_id = (ep.insert_after_episode_id or "").strip()

    if insert_after_episode_id:
        anchor_episode = require_episode_team_access(session, team, decode_id(insert_after_episode_id))
        if anchor_episode.script_id != script.id:
            raise HTTPException(status_code=400, detail="插入位置不属于当前剧本")

        episodes_to_shift = session.exec(
            select(Episode)
            .where(Episode.script_id == script.id, Episode.sequence_num > anchor_episode.sequence_num)
            .order_by(Episode.sequence_num.desc())
        ).all()
        for episode in episodes_to_shift:
            episode.sequence_num += 1
            episode.updated_at = now
            session.add(episode)

        next_seq = anchor_episode.sequence_num + 1
    else:
        last_ep = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.desc())).first()
        next_seq = (last_ep.sequence_num + 1) if last_ep else 1

    new_episode = Episode(
        script_id=script.id,
        title=ep.title,
        sequence_num=next_seq,
        storyboard_mode=default_storyboard_mode,
        updated_at=now
    )
    script.updated_at = now
    mark_script_access_by_script_id(session, script.id)
    session.add(script)
    session.add(new_episode)
    session.commit()
    session.refresh(new_episode)
    session.refresh(script)
    AgentWorkflowService(session).ensure_episode_state_for_episode(script=script, episode=new_episode)
    session.commit()
    return _serialize_episode(script, new_episode)


@router.put("/api/episodes/{episode_id}")
async def update_episode(
    episode_id: str,
    payload: EpisodeUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    episode = require_episode_team_access(session, team, decode_id(episode_id))

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=400, detail="分集标题不能为空")
        episode.title = title

    if payload.source_text is not None:
        episode.source_text = payload.source_text or None

    if payload.storyboard_mode is not None:
        sync_episode_storyboard_mode(session, episode, payload.storyboard_mode)
    if payload.clear_workflow_override:
        episode.workflow_override_json = "{}"
    elif payload.workflow_override_json is not None:
        episode.workflow_override_json = workflow_override_to_json(payload.workflow_override_json)

    episode.updated_at = datetime.utcnow()
    mark_script_access_by_script_id(session, episode.script_id)
    session.add(episode)
    session.commit()
    session.refresh(episode)
    script = require_script_team_access(session, team, episode.script_id)
    AgentWorkflowService(session).ensure_episode_state_for_episode(script=script, episode=episode)
    session.commit()
    return _serialize_episode(script, episode)


@router.delete("/api/episodes/{episode_id}")
async def delete_episode(
    episode_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    episode = require_episode_team_access(session, team, decode_id(episode_id))
    mark_script_access_by_script_id(session, episode.script_id)
    cleanup_episode_dependencies(session, episode.id)
    session.delete(episode)
    session.commit()
    return {"status": "success"}


@router.get("/api/scripts/{script_id}/source")
async def get_script_source(
    script_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = _get_script_or_404(script_id, team, session)
    mark_script_access_by_script_id(session, script.id)
    session.commit()
    episode_count = session.exec(select(Episode).where(Episode.script_id == script.id)).all()
    return {"script_id": encode_id(script.id), "source_text": script.source_text or "", "episode_count": len(episode_count)}


@router.put("/api/scripts/{script_id}/source")
async def update_script_source(
    script_id: str,
    payload: ScriptSourceUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = _get_script_or_404(script_id, team, session)
    script.source_text = payload.source_text or None
    script.updated_at = datetime.utcnow()
    mark_script_access_by_script_id(session, script.id)
    session.add(script)
    session.commit()
    session.refresh(script)
    return {"script_id": encode_id(script.id), "source_text": script.source_text or "", "msg": "剧本原文已保存"}


@router.post("/api/scripts/{script_id}/episode-splits/preview")
async def preview_episode_splits(
    script_id: str,
    payload: EpisodeSplitPreviewRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = _get_script_or_404(script_id, team, session)
    mark_script_access_by_script_id(session, script.id)
    session.commit()

    source_text = payload.source_text if payload.source_text is not None else (script.source_text or "")
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="请先输入剧本原文后再执行拆分")

    split_mode = (payload.split_mode or "rule").strip().lower()
    if split_mode == "ai":
        result = build_ai_split_preview(source_text, payload.requirements)
    elif split_mode == "rule":
        result = build_split_preview(source_text)
    else:
        raise HTTPException(status_code=400, detail="不支持的拆分模式，请使用 rule 或 ai")

    return {
        "script_id": encode_id(script.id),
        "split_mode": split_mode,
        "source_text": source_text,
        "episodes": result.get("episodes", []),
        "warnings": result.get("warnings", []),
    }


@router.post("/api/scripts/{script_id}/episode-splits/commit")
async def commit_episode_splits_api(
    script_id: str,
    payload: EpisodeSplitCommitRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = _get_script_or_404(script_id, team, session)
    mark_script_access_by_script_id(session, script.id)

    if not payload.episodes:
        raise HTTPException(status_code=400, detail="没有可提交的拆分结果，请先预览")

    source_text = payload.source_text if payload.source_text is not None else (script.source_text or "")
    if not source_text.strip():
        source_text = "\n\n".join([f"{item.title}\n{(item.source_text or '').strip()}".strip() for item in payload.episodes]).strip()

    script.source_text = source_text or None
    script.updated_at = datetime.utcnow()
    episodes_payload = [{"title": item.title, "source_text": item.source_text} for item in payload.episodes]

    try:
        commit_result = commit_episode_splits(
            session=session,
            script=script,
            episodes=episodes_payload,
            replace_existing=payload.replace_existing,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    session.add(script)
    session.commit()
    created_episodes = commit_result["created_episodes"]

    return {
        "script_id": encode_id(script.id),
        "replace_existing": payload.replace_existing,
        "deleted_count": commit_result["deleted_count"],
        "created_count": len(created_episodes),
        "episodes": [
            {
                "id": encode_id(episode.id),
                "hash_id": encode_id(episode.id),
                "sequence_num": episode.sequence_num,
                "title": episode.title,
                "source_text": episode.source_text or "",
            }
            for episode in created_episodes
        ],
        "msg": f"已生成 {len(created_episodes)} 个剧集",
    }


@router.post("/api/scripts/{script_id}/episode-splits/ai-preview")
async def preview_episode_splits_ai(
    script_id: str,
    payload: EpisodeSplitPreviewRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = _get_script_or_404(script_id, team, session)
    mark_script_access_by_script_id(session, script.id)
    session.commit()

    source_text = payload.source_text if payload.source_text is not None else (script.source_text or "")
    if not source_text.strip():
        raise HTTPException(status_code=400, detail="请先输入剧本原文后再执行 AI 拆分")

    result = build_ai_split_preview(source_text, payload.requirements)
    return {
        "script_id": encode_id(script.id),
        "split_mode": "ai",
        "source_text": source_text,
        "episodes": result.get("episodes", []),
        "warnings": result.get("warnings", []),
    }
