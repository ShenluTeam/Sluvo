from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import Session, select

from core.config import settings
from core.security import decode_id, encode_id
from database import get_session
from dependencies import get_current_team, get_current_user, require_team_permission
from models import (
    CanvasNode,
    CanvasWorkspace,
    Episode,
    EpisodeAssetLink,
    GenerationRecord,
    GenerationUnit,
    GenerationUnitInput,
    Panel,
    Script,
    SharedResource,
    SharedResourceVersion,
    StoryboardShotAssetLink,
    TaskJob,
    Team,
    TeamMemberLink,
    User,
)
from routers.ai_director import parse_story_segments_v3
from routers.generate import generate_image_v2
from routers.resource import generate_resource_image
from schemas import (
    AssetPatchRequest,
    CanvasNodeVisibilityRequest,
    EpisodeScriptPatchRequest,
    GenerationUnitCreateRequest,
    GenerationUnitInputCreateRequest,
    GenerationUnitRunRequest,
    GenerateImageV2Request,
    GenerateSharedResourceImageRequest,
    ParseScriptV2Request,
    ProjectCreateRequest,
    ProjectEpisodeCreateRequest,
    StoryboardShotPatchRequest,
)
from services.access_service import (
    require_episode_team_access,
    require_panel_team_access,
    require_resource_team_access,
    require_script_team_access,
)
from services.canvas_projection_service import (
    ensure_asset_table_projection,
    ensure_episode_projection,
    ensure_generation_input_edge,
    ensure_generation_unit_projection,
    ensure_project_projection,
    ensure_storyboard_table_projection,
    rebuild_project_projection,
)
from services.generation_record_service import submit_video_generation
from services.project_workspace_service import (
    append_domain_event,
    build_project_workspace,
    sync_storyboard_asset_links_for_panel,
)
from services.resource_service import (
    create_resource_version,
    delete_resource,
    update_resource,
    update_resource_version,
)
from services.script_service import create_script as create_script_service
from services.story_segment_service import update_segment_fields

router = APIRouter()


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def _assert_not_stale(current_value: Optional[datetime], submitted_value: Optional[str], field_name: str = "updatedAt") -> None:
    if not submitted_value:
        return
    parsed = _parse_iso_datetime(submitted_value)
    current = current_value or datetime.utcnow()
    if parsed is None:
        return
    if parsed != current:
        raise HTTPException(status_code=409, detail=f"{field_name} 已过期，请刷新后重试")


def _default_resource_version(session: Session, resource_id: int) -> Optional[SharedResourceVersion]:
    versions = session.exec(
        select(SharedResourceVersion)
        .where(SharedResourceVersion.resource_id == resource_id)
        .order_by(SharedResourceVersion.created_at.desc(), SharedResourceVersion.id.desc())
    ).all()
    for item in versions:
        if item.is_default:
            return item
    return versions[0] if versions else None


def _touch_canvas_hidden(node: CanvasNode, hidden: bool) -> CanvasNode:
    node.hidden = hidden
    node.revision = int(node.revision or 1) + 1
    node.updated_at = datetime.utcnow()
    return node


def _latest_generation_unit(
    session: Session,
    *,
    script_id: int,
    owner_type: str,
    owner_id: int,
    unit_type: str,
    require_media: bool = False,
) -> Optional[GenerationUnit]:
    units = session.exec(
        select(GenerationUnit)
        .where(
            GenerationUnit.script_id == script_id,
            GenerationUnit.owner_type == owner_type,
            GenerationUnit.owner_id == owner_id,
            GenerationUnit.unit_type == unit_type,
        )
        .order_by(GenerationUnit.updated_at.desc(), GenerationUnit.id.desc())
    ).all()
    for item in units:
        if require_media and not item.current_media_id:
            continue
        return item
    return None


def _next_generation_unit_name(owner_label: str, unit_type: str) -> str:
    mapping = {"image": "图片", "video": "视频", "audio": "音频"}
    return f"{owner_label} · {mapping.get(unit_type, unit_type)}"


def _upsert_unit_prompt_from_owner(session: Session, unit: GenerationUnit) -> None:
    if unit.owner_type == "asset" and unit.owner_id:
        resource = session.get(SharedResource, unit.owner_id)
        version = _default_resource_version(session, resource.id) if resource else None
        unit.prompt = unit.prompt or str(version.appearance_prompt or resource.description or "").strip() if resource else unit.prompt
    elif unit.owner_type == "storyboard_shot" and unit.owner_id:
        panel = session.get(Panel, unit.owner_id)
        if not panel:
            return
        if unit.unit_type == "image":
            unit.prompt = unit.prompt or str(panel.prompt or panel.prompt_zh or panel.multi_shot_prompt or "").strip()
        elif unit.unit_type == "video":
            unit.prompt = unit.prompt or str(panel.video_prompt or panel.multi_shot_video_prompt or "").strip()


@router.get("/api/projects/{project_id}/workspace")
async def get_project_workspace(
    project_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    script = require_script_team_access(session, team, decode_id(project_id))
    return build_project_workspace(session, script)


@router.post("/api/projects")
async def create_project(
    payload: ProjectCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    script = create_script_service(
        session,
        team,
        name=payload.title,
        description=payload.description,
        aspect_ratio=payload.aspect_ratio,
        style_preset=payload.style_preset,
        default_storyboard_mode=payload.default_storyboard_mode,
        workflow_settings_json=payload.workflow_settings_json,
    )
    ensure_project_projection(session, script.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="project.created",
        entity_type="project",
        entity_id=script.id,
        payload={"title": script.name},
        created_by_user_id=user.id,
    )
    return build_project_workspace(session, script)


@router.post("/api/projects/{project_id}/episodes")
async def create_project_episode(
    project_id: str,
    payload: ProjectEpisodeCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:manage")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    script = require_script_team_access(session, team, decode_id(project_id))
    episodes = session.exec(select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc(), Episode.id.asc())).all()
    next_seq = int(payload.episodeNo or ((episodes[-1].sequence_num + 1) if episodes else 1))
    insert_after_id = decode_id(payload.insertAfterEpisodeId) if payload.insertAfterEpisodeId else None
    now = datetime.utcnow()
    if insert_after_id:
        anchor = require_episode_team_access(session, team, insert_after_id)
        if anchor.script_id != script.id:
            raise HTTPException(status_code=400, detail="插入位置不属于当前剧本")
        next_seq = int(anchor.sequence_num or 0) + 1
        to_shift = session.exec(
            select(Episode)
            .where(Episode.script_id == script.id, Episode.sequence_num >= next_seq)
            .order_by(Episode.sequence_num.desc())
        ).all()
        for item in to_shift:
            item.sequence_num = int(item.sequence_num or 0) + 1
            item.updated_at = now
            session.add(item)
    episode = Episode(
        script_id=script.id,
        sequence_num=next_seq,
        title=payload.title,
        source_text=payload.rawScript or None,
        storyboard_mode=getattr(script, "default_storyboard_mode", "commentary"),
        created_at=now,
        updated_at=now,
    )
    session.add(episode)
    session.commit()
    session.refresh(episode)
    ensure_episode_projection(session, script.id, episode.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="episode.created",
        entity_type="episode",
        entity_id=episode.id,
        payload={"title": episode.title, "sequence_num": episode.sequence_num},
        created_by_user_id=user.id,
    )
    return build_project_workspace(session, script)


@router.patch("/api/episodes/{episode_id}/script")
async def patch_episode_script(
    episode_id: str,
    payload: EpisodeScriptPatchRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    episode = require_episode_team_access(session, team, decode_id(episode_id))
    script = require_script_team_access(session, team, episode.script_id)
    _assert_not_stale(episode.updated_at, payload.updatedAt)
    episode.source_text = payload.rawScript or None
    episode.updated_at = datetime.utcnow()
    session.add(episode)
    session.commit()
    ensure_episode_projection(session, script.id, episode.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="episode.script.updated",
        entity_type="episode",
        entity_id=episode.id,
        payload={"updated_at": episode.updated_at.isoformat()},
        created_by_user_id=user.id,
    )
    return build_project_workspace(session, script)


@router.post("/api/episodes/{episode_id}/extract-assets")
async def extract_episode_assets(
    episode_id: str,
    member_link: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    if not settings.DEEPSEEK_API_KEY:
        raise HTTPException(status_code=500, detail="服务端未配置 DEEPSEEK_API_KEY")
    episode = require_episode_team_access(session, team, decode_id(episode_id))
    script = require_script_team_access(session, team, episode.script_id)
    if not str(episode.source_text or "").strip():
        raise HTTPException(status_code=400, detail="请先保存当前集原文")

    from services.workflow_preset_service import build_style_prompt, get_style_display_label, resolve_effective_workflow_profile
    from services.task_job_service import create_task_job, enqueue_task_job

    workflow_profile = resolve_effective_workflow_profile(
        script,
        episode=episode,
        storyboard_mode=getattr(episode, "storyboard_mode", None),
    )
    task_id = f"asset-{script.id}-{episode.id}-{datetime.utcnow().strftime('%H%M%S%f')}"
    job = create_task_job(
        session,
        task_id=task_id,
        task_type="resource.extract",
        queue_name="resource",
        provider="deepseek",
        team_id=team.id,
        user_id=user.id,
        script_id=script.id,
        episode_id=episode.id,
        ownership_mode="project",
        scope_type="episode",
        scope_id=episode.id,
        task_category="resource",
        payload={
            "script_id": script.id,
            "source_text": str(episode.source_text or "").strip(),
            "style_prompt": build_style_prompt(workflow_profile.get("style"), fallback=getattr(script, "style_preset", "")),
            "style_label": get_style_display_label(workflow_profile.get("style"), getattr(script, "style_preset", "默认写实")),
            "user_id": user.id,
            "team_id": team.id,
        },
        message="资产提取任务已提交",
        max_retries=1,
    )
    enqueue_task_job(job)
    ensure_asset_table_projection(session, script.id, episode.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="assets.extracted.submitted",
        entity_type="episode",
        entity_id=episode.id,
        payload={"task_id": task_id},
        created_by_user_id=user.id,
    )
    return {"task_id": task_id, "status": "submitted", "workspace": build_project_workspace(session, script)}


@router.patch("/api/assets/{asset_id}")
async def patch_asset(
    asset_id: str,
    payload: AssetPatchRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    resource = require_resource_team_access(session, team, decode_id(asset_id))
    script = require_script_team_access(session, team, resource.script_id)
    _assert_not_stale(resource.updated_at, payload.updatedAt)
    updated = update_resource(
        session,
        team,
        resource.id,
        name=payload.name if payload.name is not None else resource.name,
        file_url=resource.file_url,
        trigger_word=resource.trigger_word,
        aliases=None,
        description=resource.description,
    )
    default_version = _default_resource_version(session, updated.id)
    if payload.prompt is not None:
        if default_version:
            update_resource_version(
                session,
                team,
                default_version.id,
                appearance_prompt=payload.prompt,
            )
        else:
            create_resource_version(
                session,
                team,
                resource_id=updated.id,
                version_tag="v1",
                appearance_prompt=payload.prompt,
                file_url=updated.file_url,
                trigger_word=updated.trigger_word,
                start_seq=None,
                end_seq=None,
                is_default=True,
            )
    if payload.sortOrder is not None:
        links = session.exec(select(EpisodeAssetLink).where(EpisodeAssetLink.resource_id == updated.id)).all()
        now = datetime.utcnow()
        for item in links:
            item.sort_order = int(payload.sortOrder)
            item.revision = int(item.revision or 1) + 1
            item.updated_at = now
            session.add(item)
        session.commit()
    append_domain_event(
        session,
        script_id=script.id,
        event_type="asset.updated",
        entity_type="asset",
        entity_id=updated.id,
        payload={"name": updated.name},
        created_by_user_id=user.id,
    )
    rebuild_project_projection(session, script.id)
    return build_project_workspace(session, script)


@router.delete("/api/assets/{asset_id}")
async def remove_asset(
    asset_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    resource = require_resource_team_access(session, team, decode_id(asset_id))
    script = require_script_team_access(session, team, resource.script_id)
    session.exec(select(EpisodeAssetLink).where(EpisodeAssetLink.resource_id == resource.id)).all()
    for link in session.exec(select(EpisodeAssetLink).where(EpisodeAssetLink.resource_id == resource.id)).all():
        session.delete(link)
    for link in session.exec(select(StoryboardShotAssetLink).where(StoryboardShotAssetLink.resource_id == resource.id)).all():
        session.delete(link)
    for unit in session.exec(select(GenerationUnit).where(GenerationUnit.owner_type == "asset", GenerationUnit.owner_id == resource.id)).all():
        for item in session.exec(
            select(GenerationUnitInput).where(
                (GenerationUnitInput.target_unit_id == unit.id) | (GenerationUnitInput.source_unit_id == unit.id)
            )
        ).all():
            session.delete(item)
        session.delete(unit)
    session.commit()
    delete_resource(session, team, resource.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="asset.deleted",
        entity_type="asset",
        entity_id=resource.id,
        payload={"name": resource.name},
        created_by_user_id=user.id,
    )
    rebuild_project_projection(session, script.id)
    return build_project_workspace(session, script)


@router.post("/api/episodes/{episode_id}/generate-storyboard")
async def generate_episode_storyboard(
    episode_id: str,
    member_link: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    episode = require_episode_team_access(session, team, decode_id(episode_id))
    script = require_script_team_access(session, team, episode.script_id)
    response = parse_story_segments_v3(
        episode_id=encode_id(episode.id),
        req=ParseScriptV2Request(text=str(episode.source_text or "").strip(), storyboard_mode=episode.storyboard_mode),
        _=member_link,
        team=team,
        session=session,
    )
    ensure_storyboard_table_projection(session, script.id, episode.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="storyboard.generated.submitted",
        entity_type="episode",
        entity_id=episode.id,
        payload={"task_id": response.get("task_id")},
        created_by_user_id=user.id,
    )
    return {"task_id": response.get("task_id"), "status": response.get("status"), "workspace": build_project_workspace(session, script)}


@router.patch("/api/storyboard-shots/{shot_id}")
async def patch_storyboard_shot(
    shot_id: str,
    payload: StoryboardShotPatchRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(shot_id))
    episode = require_episode_team_access(session, team, panel.episode_id)
    script = require_script_team_access(session, team, episode.script_id)
    _assert_not_stale(panel.updated_at, payload.updatedAt)
    update_segment_fields(
        panel,
        {
            "title": payload.shotNo if payload.shotNo is not None else panel.title,
            "summary": payload.description if payload.description is not None else panel.segment_summary,
            "multi_shot_prompt": payload.imagePrompt if payload.imagePrompt is not None else panel.multi_shot_prompt,
            "multi_shot_video_prompt": payload.videoPrompt if payload.videoPrompt is not None else panel.multi_shot_video_prompt,
            "recommended_duration_seconds": payload.durationSec if payload.durationSec is not None else panel.recommended_duration_seconds,
        },
    )
    if payload.imagePrompt is not None:
        panel.prompt = payload.imagePrompt
        panel.prompt_zh = payload.imagePrompt
    if payload.videoPrompt is not None:
        panel.video_prompt = payload.videoPrompt
    if payload.sortOrder is not None:
        panel.sequence_num = int(payload.sortOrder)
    panel.updated_at = datetime.utcnow()
    session.add(panel)
    session.commit()
    append_domain_event(
        session,
        script_id=script.id,
        event_type="storyboard.updated",
        entity_type="storyboardShot",
        entity_id=panel.id,
        payload={"sequence_num": panel.sequence_num},
        created_by_user_id=user.id,
    )
    rebuild_project_projection(session, script.id)
    return build_project_workspace(session, script)


@router.delete("/api/storyboard-shots/{shot_id}")
async def remove_storyboard_shot(
    shot_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(shot_id))
    episode = require_episode_team_access(session, team, panel.episode_id)
    script = require_script_team_access(session, team, episode.script_id)
    for link in session.exec(select(StoryboardShotAssetLink).where(StoryboardShotAssetLink.panel_id == panel.id)).all():
        session.delete(link)
    for unit in session.exec(select(GenerationUnit).where(GenerationUnit.owner_type == "storyboard_shot", GenerationUnit.owner_id == panel.id)).all():
        for item in session.exec(
            select(GenerationUnitInput).where(
                (GenerationUnitInput.target_unit_id == unit.id) | (GenerationUnitInput.source_unit_id == unit.id)
            )
        ).all():
            session.delete(item)
        session.delete(unit)
    session.delete(panel)
    session.commit()
    append_domain_event(
        session,
        script_id=script.id,
        event_type="storyboard.deleted",
        entity_type="storyboardShot",
        entity_id=panel.id,
        payload={"episode_id": episode.id},
        created_by_user_id=user.id,
    )
    rebuild_project_projection(session, script.id)
    return build_project_workspace(session, script)


def _create_generation_unit(
    session: Session,
    *,
    script_id: int,
    episode_id: Optional[int],
    unit_type: str,
    owner_type: str,
    owner_id: int,
    name: str,
    prompt: str,
    negative_prompt: Optional[str],
    model_id: Optional[str],
    params: Dict[str, Any],
) -> GenerationUnit:
    item = GenerationUnit(
        script_id=script_id,
        episode_id=episode_id,
        unit_type=unit_type,
        name=name,
        owner_type=owner_type,
        owner_id=owner_id,
        prompt=prompt or "",
        negative_prompt=negative_prompt,
        model_id=model_id,
        params_json=json.dumps(params or {}, ensure_ascii=False),
        status="empty",
        versions_json="[]",
        revision=1,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.post("/api/assets/{asset_id}/image-units")
async def create_asset_image_unit(
    asset_id: str,
    payload: GenerationUnitCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    resource = require_resource_team_access(session, team, decode_id(asset_id))
    script = require_script_team_access(session, team, resource.script_id)
    version = _default_resource_version(session, resource.id)
    episode_link = session.exec(
        select(EpisodeAssetLink).where(EpisodeAssetLink.resource_id == resource.id).order_by(EpisodeAssetLink.sort_order.asc(), EpisodeAssetLink.id.asc())
    ).first()
    unit = _create_generation_unit(
        session,
        script_id=script.id,
        episode_id=episode_link.episode_id if episode_link else None,
        unit_type="image",
        owner_type="asset",
        owner_id=resource.id,
        name=payload.name or _next_generation_unit_name(resource.name, "image"),
        prompt=payload.prompt or str(version.appearance_prompt or resource.description or "").strip(),
        negative_prompt=payload.negativePrompt,
        model_id=payload.modelId,
        params=payload.params,
    )
    ensure_generation_unit_projection(session, script.id, unit.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="generation_unit.created",
        entity_type="generationUnit",
        entity_id=unit.id,
        payload={"owner_type": unit.owner_type, "owner_id": unit.owner_id, "unit_type": unit.unit_type},
        created_by_user_id=user.id,
    )
    return build_project_workspace(session, script)


@router.post("/api/storyboard-shots/{shot_id}/image-units")
async def create_shot_image_unit(
    shot_id: str,
    payload: GenerationUnitCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(shot_id))
    episode = require_episode_team_access(session, team, panel.episode_id)
    script = require_script_team_access(session, team, episode.script_id)
    sync_storyboard_asset_links_for_panel(session, panel)
    unit = _create_generation_unit(
        session,
        script_id=script.id,
        episode_id=episode.id,
        unit_type="image",
        owner_type="storyboard_shot",
        owner_id=panel.id,
        name=payload.name or _next_generation_unit_name(panel.title or f"镜头 {panel.sequence_num}", "image"),
        prompt=payload.prompt or str(panel.prompt or panel.prompt_zh or panel.multi_shot_prompt or "").strip(),
        negative_prompt=payload.negativePrompt,
        model_id=payload.modelId,
        params=payload.params,
    )
    asset_links = session.exec(select(StoryboardShotAssetLink).where(StoryboardShotAssetLink.panel_id == panel.id).order_by(StoryboardShotAssetLink.sort_order.asc())).all()
    for item in asset_links:
        source_unit = _latest_generation_unit(
            session,
            script_id=script.id,
            owner_type="asset",
            owner_id=item.resource_id,
            unit_type="image",
            require_media=True,
        )
        if not source_unit:
            continue
        link = GenerationUnitInput(
            script_id=script.id,
            target_unit_id=unit.id,
            source_unit_id=source_unit.id,
            source_media_id=source_unit.current_media_id,
            input_type="image",
            role=item.role or "",
            weight=None,
            sort_order=item.sort_order,
            metadata_json="{}",
            created_at=datetime.utcnow(),
        )
        session.add(link)
    session.commit()
    ensure_generation_unit_projection(session, script.id, unit.id)
    for item in session.exec(select(GenerationUnitInput).where(GenerationUnitInput.target_unit_id == unit.id)).all():
        if item.source_unit_id:
            ensure_generation_input_edge(session, script.id, item.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="generation_unit.created",
        entity_type="generationUnit",
        entity_id=unit.id,
        payload={"owner_type": unit.owner_type, "owner_id": unit.owner_id, "unit_type": unit.unit_type},
        created_by_user_id=user.id,
    )
    return build_project_workspace(session, script)


@router.post("/api/storyboard-shots/{shot_id}/video-units")
async def create_shot_video_unit(
    shot_id: str,
    payload: GenerationUnitCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(shot_id))
    episode = require_episode_team_access(session, team, panel.episode_id)
    script = require_script_team_access(session, team, episode.script_id)
    unit = _create_generation_unit(
        session,
        script_id=script.id,
        episode_id=episode.id,
        unit_type="video",
        owner_type="storyboard_shot",
        owner_id=panel.id,
        name=payload.name or _next_generation_unit_name(panel.title or f"镜头 {panel.sequence_num}", "video"),
        prompt=payload.prompt or str(panel.video_prompt or panel.multi_shot_video_prompt or "").strip(),
        negative_prompt=payload.negativePrompt,
        model_id=payload.modelId,
        params=payload.params,
    )
    image_unit = _latest_generation_unit(
        session,
        script_id=script.id,
        owner_type="storyboard_shot",
        owner_id=panel.id,
        unit_type="image",
        require_media=True,
    )
    if image_unit:
        session.add(
            GenerationUnitInput(
                script_id=script.id,
                target_unit_id=unit.id,
                source_unit_id=image_unit.id,
                source_media_id=image_unit.current_media_id,
                input_type="image",
                role="firstFrame",
                weight=None,
                sort_order=1,
                metadata_json="{}",
                created_at=datetime.utcnow(),
            )
        )
        session.commit()
    ensure_generation_unit_projection(session, script.id, unit.id)
    for item in session.exec(select(GenerationUnitInput).where(GenerationUnitInput.target_unit_id == unit.id)).all():
        if item.source_unit_id:
            ensure_generation_input_edge(session, script.id, item.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="generation_unit.created",
        entity_type="generationUnit",
        entity_id=unit.id,
        payload={"owner_type": unit.owner_type, "owner_id": unit.owner_id, "unit_type": unit.unit_type},
        created_by_user_id=user.id,
    )
    return build_project_workspace(session, script)


@router.post("/api/generation-units/{target_unit_id}/inputs")
async def create_generation_unit_input(
    target_unit_id: str,
    payload: GenerationUnitInputCreateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    target_unit = session.get(GenerationUnit, decode_id(target_unit_id))
    if not target_unit:
        raise HTTPException(status_code=404, detail="生成单元不存在")
    script = require_script_team_access(session, team, target_unit.script_id)
    source_unit_id = decode_id(payload.sourceUnitId) if payload.sourceUnitId else None
    source_media_id = decode_id(payload.sourceMediaId) if payload.sourceMediaId else None
    item = GenerationUnitInput(
        script_id=script.id,
        target_unit_id=target_unit.id,
        source_unit_id=source_unit_id,
        source_media_id=source_media_id,
        input_type=payload.inputType,
        role=payload.role,
        weight=payload.weight,
        sort_order=int(payload.sortOrder or 0),
        metadata_json="{}",
        created_at=datetime.utcnow(),
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    if item.source_unit_id:
        ensure_generation_input_edge(session, script.id, item.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="generation_input.created",
        entity_type="generationUnitInput",
        entity_id=item.id,
        payload={"target_unit_id": item.target_unit_id, "source_unit_id": item.source_unit_id},
        created_by_user_id=user.id,
    )
    return build_project_workspace(session, script)


@router.delete("/api/generation-unit-inputs/{input_id}")
async def remove_generation_unit_input(
    input_id: str,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    item = session.get(GenerationUnitInput, decode_id(input_id))
    if not item:
        raise HTTPException(status_code=404, detail="生成参考不存在")
    script = require_script_team_access(session, team, item.script_id)
    session.delete(item)
    session.commit()
    rebuild_project_projection(session, script.id)
    return build_project_workspace(session, script)


@router.post("/api/generation-units/{unit_id}/run")
async def run_generation_unit(
    unit_id: str,
    payload: GenerationUnitRunRequest,
    member_link: TeamMemberLink = Depends(require_team_permission("generate:run")),
    team: Team = Depends(get_current_team),
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    unit = session.get(GenerationUnit, decode_id(unit_id))
    if not unit:
        raise HTTPException(status_code=404, detail="生成单元不存在")
    script = require_script_team_access(session, team, unit.script_id)
    if payload.prompt is not None:
        unit.prompt = payload.prompt
    if payload.modelId is not None:
        unit.model_id = payload.modelId
    if payload.params:
        unit.params_json = json.dumps(payload.params, ensure_ascii=False)
    _upsert_unit_prompt_from_owner(session, unit)
    reference_inputs = session.exec(
        select(GenerationUnitInput).where(GenerationUnitInput.target_unit_id == unit.id).order_by(GenerationUnitInput.sort_order.asc(), GenerationUnitInput.id.asc())
    ).all()
    reference_urls: List[str] = []
    from models import MediaAsset
    for item in reference_inputs:
        source_unit = session.get(GenerationUnit, item.source_unit_id) if item.source_unit_id else None
        if item.source_media_id:
            media_item = session.get(MediaAsset, item.source_media_id)
            if media_item and str(media_item.url or "").strip():
                reference_urls.append(str(media_item.url or "").strip())
                continue
        if source_unit and source_unit.current_media_id:
            media_item = session.get(MediaAsset, source_unit.current_media_id)
            if media_item and str(media_item.url or "").strip():
                reference_urls.append(str(media_item.url or "").strip())

    if unit.unit_type == "image":
        unit_params = json.loads(unit.params_json or "{}") or {}
        if unit.owner_type == "asset" and unit.owner_id:
            response = await generate_resource_image(
                resource_id=encode_id(unit.owner_id),
                payload=GenerateSharedResourceImageRequest(
                    prompt=unit.prompt or "",
                    model_code=unit.model_id or "nano-banana-pro",
                    resolution=str(unit_params.get("resolution") or "2k"),
                    quality=str(unit_params.get("quality") or "medium"),
                    aspectRatio=str(unit_params.get("aspectRatio") or "1:1"),
                    reference_images=reference_urls,
                ),
                _=member_link,
                session=session,
                user=user,
                team=team,
            )
            task_id = response.get("task_id")
        elif unit.owner_type == "storyboard_shot" and unit.owner_id:
            panel = require_panel_team_access(session, team, unit.owner_id)
            response = await generate_image_v2(
                episode_id=encode_id(panel.episode_id),
                req=GenerateImageV2Request(
                    prompt=unit.prompt or "",
                    resolution=str(unit_params.get("resolution") or "2k"),
                    quality=str(unit_params.get("quality") or "medium"),
                    aspectRatio=str(unit_params.get("aspectRatio") or "16:9"),
                    model_code=unit.model_id or "nano-banana-pro",
                    imageUrls=reference_urls,
                    panel_id=encode_id(panel.id),
                ),
                background_tasks=BackgroundTasks(),
                _=member_link,
                user=user,
                team=team,
                session=session,
            )
            task_id = response.get("task_id")
        else:
            raise HTTPException(status_code=400, detail="当前图片单元暂不支持运行")
        record = session.exec(select(GenerationRecord).where(GenerationRecord.task_id == task_id)).first()
    elif unit.unit_type == "video":
        if unit.owner_type != "storyboard_shot" or not unit.owner_id:
            raise HTTPException(status_code=400, detail="当前视频单元暂不支持运行")
        panel = require_panel_team_access(session, team, unit.owner_id)
        record = submit_video_generation(
            session,
            background_tasks=BackgroundTasks(),
            user=user,
            team=team,
            payload={
                "ownership_mode": "project",
                "project_id": encode_id(script.id),
                "episode_id": encode_id(panel.episode_id),
                "target_type": "panel",
                "target_id": encode_id(panel.id),
                "prompt": unit.prompt or panel.video_prompt or "",
                "model_code": unit.model_id or "seedance_20",
                "generation_type": "reference_to_video",
                "duration": int(panel.recommended_duration_seconds or 5),
                "resolution": str((json.loads(unit.params_json or "{}") or {}).get("resolution") or "720p"),
                "aspect_ratio": str((json.loads(unit.params_json or "{}") or {}).get("aspectRatio") or "16:9"),
                "image_refs": reference_urls,
                "video_refs": [],
                "audio_refs": [],
                "real_person_mode": False,
                "web_search": False,
                "audio_enabled": False,
            },
        )
        task_id = record.task_id
    else:
        raise HTTPException(status_code=400, detail="当前单元类型暂不支持运行")

    if not record and task_id:
        record = session.exec(select(GenerationRecord).where(GenerationRecord.task_id == task_id)).first()
    if not record:
        raise HTTPException(status_code=500, detail="生成任务已提交，但未找到记录")
    unit.generation_record_id = record.id
    unit.status = str(record.status or "queued")
    unit.revision = int(unit.revision or 1) + 1
    unit.updated_at = datetime.utcnow()
    session.add(unit)
    session.commit()
    ensure_generation_unit_projection(session, script.id, unit.id)
    append_domain_event(
        session,
        script_id=script.id,
        event_type="generation_unit.run.submitted",
        entity_type="generationUnit",
        entity_id=unit.id,
        payload={"record_id": record.id, "task_id": task_id},
        created_by_user_id=user.id,
    )
    return {"taskId": task_id, "recordId": encode_id(record.id), "workspace": build_project_workspace(session, script)}


@router.post("/api/canvas/nodes/{node_id}/hide")
async def hide_canvas_node(
    node_id: str,
    payload: CanvasNodeVisibilityRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    node = session.get(CanvasNode, decode_id(node_id))
    if not node:
        raise HTTPException(status_code=404, detail="画布节点不存在")
    workspace = session.get(CanvasWorkspace, node.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="画布工作区不存在")
    script = require_script_team_access(session, team, workspace.script_id)
    _touch_canvas_hidden(node, bool(payload.hidden))
    session.add(node)
    session.commit()
    return build_project_workspace(session, script)


@router.post("/api/canvas/nodes/{node_id}/restore")
async def restore_canvas_node(
    node_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    node = session.get(CanvasNode, decode_id(node_id))
    if not node:
        raise HTTPException(status_code=404, detail="画布节点不存在")
    workspace = session.get(CanvasWorkspace, node.workspace_id)
    if not workspace:
        raise HTTPException(status_code=404, detail="画布工作区不存在")
    script = require_script_team_access(session, team, workspace.script_id)
    _touch_canvas_hidden(node, False)
    session.add(node)
    session.commit()
    return build_project_workspace(session, script)
