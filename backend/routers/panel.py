from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from core.security import decode_id, encode_id
from database import get_session
from dependencies import get_current_team, get_current_user, require_team_permission
import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from models import Episode, Panel, PanelGridCell, PanelRevision, Team, TeamMemberLink, User
from schemas import (
    PanelContentUpdateRequest,
    PanelCreate,
    PanelEntityBindingsUpdateRequest,
    ReorderRequest,
    SegmentCellUpdateRequest,
    SegmentUpdateRequest,
    UploadImageRequest,
)
from services.access_service import require_episode_team_access, require_panel_team_access
from services.panel_asset_binding_service import bind_assets
from services.panel_revision_service import list_panel_revisions, restore_panel_revision, update_panel_with_revision
from services.panel_service import (
    create_panel as create_panel_service,
    delete_extra_image as delete_extra_image_service,
    delete_panel as delete_panel_service,
    list_extra_images as list_extra_images_service,
    list_panels as list_panels_service,
    reorder_panels as reorder_panels_service,
    upload_extra_image as upload_extra_image_service,
)
from services.storyboard_mode_service import (
    dependency_sequence_lookup,
    hydrate_panel_storyboard_fields,
    recompute_episode_dependencies,
)
from services.user_dashboard_service import mark_script_access_by_episode_id
from services.story_segment_service import (
    build_episode_segment_workspace,
    list_segment_cells,
    sync_segment_prompt_bundle,
    update_segment_cell_fields,
    update_segment_fields,
)

router = APIRouter()


def _decode_optional_asset_id(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        return decode_id(text)
    except Exception:
        return None


def _normalize_entity_binding_items(items: Any) -> List[Dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for item in items:
        if isinstance(item, dict):
            next_item = dict(item)
            next_item["name"] = str(next_item.get("name") or "").strip()
            next_item["asset_id"] = _decode_optional_asset_id(next_item.get("asset_id"))
            next_item["match_type"] = str(next_item.get("match_type") or ("manual" if next_item["asset_id"] else "unmatched")).strip()
            if next_item["name"] or next_item["asset_id"] is not None:
                normalized.append(next_item)
            continue
        name = str(item or "").strip()
        if name:
            normalized.append({"name": name, "asset_id": None, "match_type": "unmatched"})
    return normalized


def _normalize_entity_bindings_asset_ids(entity_bindings: Dict[str, Any]) -> Dict[str, Any]:
    bindings = entity_bindings if isinstance(entity_bindings, dict) else {}
    scenes = _normalize_entity_binding_items(bindings.get("scenes"))
    characters = _normalize_entity_binding_items(bindings.get("characters"))
    props = _normalize_entity_binding_items(bindings.get("props"))
    status = str(bindings.get("binding_status") or "").strip()
    if not status:
        all_items = scenes + characters + props
        if all_items and all(item.get("asset_id") is not None for item in all_items):
            status = "manual_fixed"
        elif any(item.get("asset_id") is not None for item in all_items):
            status = "partial_matched"
        else:
            status = "unmatched"
    return {
        "scenes": scenes,
        "characters": characters,
        "props": props,
        "binding_status": status,
    }


def _split_ref_names(value: Any) -> List[str]:
    if isinstance(value, list):
        values = value
    else:
        text = str(value or "").strip()
        if not text:
            return []
        for separator in ("，", "、", "|", "/", "\n", "\r"):
            text = text.replace(separator, ",")
        values = text.split(",")
    seen = set()
    result: List[str] = []
    for item in values:
        name = str(item or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _binding_names(raw: str, key: str) -> List[str]:
    try:
        bindings = json.loads(raw or "{}")
    except Exception:
        bindings = {}
    items = bindings.get(key) if isinstance(bindings, dict) else []
    if not isinstance(items, list):
        return []
    return [
        str(item.get("name") or "").strip()
        for item in items
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    ]


def _build_refs(panel: Panel) -> tuple[List[str], List[str], List[str]]:
    scene_refs = _split_ref_names(getattr(panel, "scene", "")) or _binding_names(panel.entity_bindings_json, "scenes")
    character_refs = _split_ref_names(getattr(panel, "character", "")) or _binding_names(panel.entity_bindings_json, "characters")
    prop_refs = _split_ref_names(getattr(panel, "prop", "")) or _binding_names(panel.entity_bindings_json, "props")
    return scene_refs, character_refs, prop_refs


def _is_safe_media_url(value: Optional[str]) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith("ERROR:"):
        return False
    return text.startswith(("http://", "https://", "data:", "blob:", "/"))


def _extract_panel_media_error(panel: Panel) -> str:
    raw = str(panel.image_url or "").strip()
    if raw.startswith("ERROR:"):
        return raw[len("ERROR:"):].strip()
    if str(panel.status or "") == "failed" or getattr(panel.status, "value", None) == "failed":
        return "图片生成失败，请调整提示词后重试"
    return ""


@router.post("/api/panels")
async def create_empty_panel(
    req: PanelCreate,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_episode_id = decode_id(req.episode_id)
    mark_script_access_by_episode_id(session, real_episode_id)
    session.commit()
    return create_panel_service(session, team, real_episode_id, req.insert_at, req.panel_type)


@router.delete("/api/panels/{panel_id}")
async def delete_panel(
    panel_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    delete_panel_service(session, team, decode_id(panel_id))
    return {"msg": "已删除"}


@router.post("/api/panels/reorder")
async def reorder_panels(
    req: ReorderRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    mark_script_access_by_episode_id(session, decode_id(req.episode_id))
    reorder_panels_service(session, team, decode_id(req.episode_id), decode_id(req.panel_id), req.new_index)
    session.commit()
    return {"status": "success"}


@router.get("/api/panels")
async def get_all_panels(
    episode_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_episode_id = decode_id(episode_id)
    mark_script_access_by_episode_id(session, real_episode_id)
    session.commit()
    panels = list_panels_service(session, team, real_episode_id)
    dependency_sequences = dependency_sequence_lookup(session, real_episode_id)
    return [
        {
            **panel.dict(),
            "id": encode_id(panel.id),
            "hash_id": encode_id(panel.id),
            "dependency_panel_sequence": dependency_sequences.get(panel.id) or None,
        }
        for panel in panels
    ]


@router.get("/api/episodes/{episode_id}/segment-workspace")
async def get_segment_workspace(
    episode_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_episode_id = decode_id(episode_id)
    episode = require_episode_team_access(session, team, real_episode_id)
    panels = list_panels_service(session, team, real_episode_id)
    dependency_sequences = dependency_sequence_lookup(session, real_episode_id)
    workspace = build_episode_segment_workspace(session, episode, panels, dependency_sequences)
    workspace["episode"]["id"] = encode_id(episode.id)
    for item in workspace["segments"]:
        item["id"] = encode_id(item["id"])
        item["segment_id"] = encode_id(item["segment_id"])
        for cell in item["grid_cells"]:
            if cell.get("id"):
                cell["id"] = encode_id(cell["id"])
    return workspace


@router.patch("/api/segments/{segment_id}")
async def update_segment(
    segment_id: str,
    payload: SegmentUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(segment_id))
    payload_data = payload.model_dump(exclude_unset=True)
    update_segment_fields(panel, payload_data)
    sync_segment_prompt_bundle(session, panel)
    if "multi_shot_prompt" in payload_data:
        panel.multi_shot_prompt = str(payload_data.get("multi_shot_prompt") or "").strip() or None
        panel.prompt = panel.multi_shot_prompt or ""
        panel.prompt_zh = panel.multi_shot_prompt or None
    if "multi_shot_video_prompt" in payload_data:
        panel.multi_shot_video_prompt = str(payload_data.get("multi_shot_video_prompt") or "").strip() or None
        panel.video_prompt = panel.multi_shot_video_prompt or None
    session.add(panel)
    session.commit()
    session.refresh(panel)
    return {
        "status": "success",
        "segment_id": encode_id(panel.id),
        "scene_prompt": panel.scene_prompt or "",
        "multi_shot_prompt": panel.multi_shot_prompt or "",
        "multi_shot_video_prompt": panel.multi_shot_video_prompt or "",
    }


@router.patch("/api/segments/{segment_id}/cells/{cell_id}")
async def update_segment_cell(
    segment_id: str,
    cell_id: str,
    payload: SegmentCellUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(segment_id))
    cell = session.get(PanelGridCell, decode_id(cell_id))
    if not cell or cell.panel_id != panel.id:
        raise HTTPException(status_code=404, detail="Segment cell not found")
    update_segment_cell_fields(cell, payload.model_dump(exclude_unset=True))
    session.add(cell)
    sync_segment_prompt_bundle(session, panel)
    session.commit()
    session.refresh(cell)
    session.refresh(panel)
    return {
        "status": "success",
        "segment_id": encode_id(panel.id),
        "cell_id": encode_id(cell.id),
        "multi_shot_prompt": panel.multi_shot_prompt or "",
        "multi_shot_video_prompt": panel.multi_shot_video_prompt or "",
    }


@router.get("/api/status/{task_id}")
async def check_status(
    task_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    panel = session.exec(select(Panel).where(Panel.task_id == task_id)).first()
    if not panel:
        return {"status": "not_found"}
    require_episode_team_access(session, team, panel.episode_id)
    image_url = str(panel.image_url or "").strip()
    video_url = str(panel.video_url or "").strip()
    safe_url = image_url if _is_safe_media_url(image_url) else (video_url if _is_safe_media_url(video_url) else "")
    return {
        "status": panel.status,
        "url": safe_url,
        "msg": _extract_panel_media_error(panel),
    }


@router.post("/api/episodes/{episode_id}/upload_image")
async def upload_episode_image(
    episode_id: str,
    req: UploadImageRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_episode_id = decode_id(episode_id)
    mark_script_access_by_episode_id(session, real_episode_id)
    session.commit()
    final_url = upload_extra_image_service(session, team, real_episode_id, req.image_base64, owner_user_id=int(user.id))
    return {"status": "success", "url": final_url}


@router.get("/api/episodes/{episode_id}/extra_images")
async def get_episode_extra_images(
    episode_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_episode_id = decode_id(episode_id)
    mark_script_access_by_episode_id(session, real_episode_id)
    session.commit()
    images = list_extra_images_service(session, team, real_episode_id)
    return [{"id": image.id, "url": image.image_base64} for image in images]


@router.delete("/api/episodes/{episode_id}/extra_images/{image_id}")
async def delete_episode_extra_image(
    episode_id: str,
    image_id: int,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_episode_id = decode_id(episode_id)
    mark_script_access_by_episode_id(session, real_episode_id)
    delete_extra_image_service(session, team, real_episode_id, image_id)
    session.commit()
    return {"status": "success"}


@router.patch("/api/panels/{panel_id}/content")
async def update_panel_content(
    panel_id: str,
    payload: PanelContentUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(panel_id))
    panel, revision = update_panel_with_revision(
        session,
        panel,
        payload.model_dump(),
        created_by_user_id=user.id,
    )
    recompute_episode_dependencies(session, panel.episode_id)
    session.commit()
    return {
        "status": "success",
        "panel_id": encode_id(panel.id),
        "revision_id": encode_id(revision.id) if revision else None,
        "current_revision_id": encode_id(panel.current_revision_id) if panel.current_revision_id else None,
    }


@router.post("/api/panels/{panel_id}/rebind_assets")
async def rebind_panel_assets(
    panel_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(panel_id))
    episode = session.get(Episode, panel.episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")
    hydrate_panel_storyboard_fields(panel, fallback_mode=getattr(episode, "storyboard_mode", "commentary"))

    scene_refs, character_refs, prop_refs = _build_refs(panel)
    bindings = bind_assets(
        session,
        script_id=episode.script_id,
        scene_refs=scene_refs,
        character_refs=character_refs,
        prop_refs=prop_refs,
    )
    panel.entity_bindings_json = json.dumps(bindings, ensure_ascii=False)
    sync_segment_prompt_bundle(session, panel)
    panel.updated_at = datetime.utcnow()
    session.add(panel)
    session.commit()
    session.refresh(panel)
    return {**panel.dict(), "id": encode_id(panel.id), "hash_id": encode_id(panel.id)}


@router.post("/api/episodes/{episode_id}/rebind_panel_assets")
async def rebind_episode_panel_assets(
    episode_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_episode_id = decode_id(episode_id)
    episode = require_episode_team_access(session, team, real_episode_id)
    panels = list_panels_service(session, team, real_episode_id)

    counts = {"auto_matched": 0, "partial_matched": 0, "unmatched": 0}
    for panel in panels:
        existing_bindings = {}
        if getattr(panel, "entity_bindings_json", None):
            try:
                existing_bindings = json.loads(panel.entity_bindings_json or "{}")
            except Exception:
                existing_bindings = {}
        if isinstance(existing_bindings, dict) and existing_bindings.get("binding_status") == "manual_fixed":
            sync_segment_prompt_bundle(session, panel)
            session.add(panel)
            continue
        scene_refs, character_refs, prop_refs = _build_refs(panel)
        bindings = bind_assets(
            session,
            script_id=episode.script_id,
            scene_refs=scene_refs,
            character_refs=character_refs,
            prop_refs=prop_refs,
        )
        status = bindings.get("binding_status") or "unmatched"
        if status in counts:
            counts[status] += 1
        else:
            counts["unmatched"] += 1
        panel.entity_bindings_json = json.dumps(bindings, ensure_ascii=False)
        sync_segment_prompt_bundle(session, panel)
        panel.updated_at = datetime.utcnow()
        session.add(panel)

    session.commit()
    return {
        "status": "success",
        "auto_matched": counts["auto_matched"],
        "partial_matched": counts["partial_matched"],
        "unmatched": counts["unmatched"],
    }


@router.patch("/api/panels/{panel_id}/entity_bindings")
async def update_panel_entity_bindings(
    panel_id: str,
    payload: PanelEntityBindingsUpdateRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(panel_id))
    bindings = _normalize_entity_bindings_asset_ids(payload.entity_bindings or {})
    panel.entity_bindings_json = json.dumps(bindings, ensure_ascii=False)
    sync_segment_prompt_bundle(session, panel)
    panel.updated_at = datetime.utcnow()
    session.add(panel)
    session.commit()
    session.refresh(panel)
    return {**panel.dict(), "id": encode_id(panel.id), "hash_id": encode_id(panel.id)}


@router.get("/api/panels/{panel_id}/revisions")
async def get_panel_revisions(
    panel_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(panel_id))
    revisions = list_panel_revisions(session, panel.id)
    return [
        {
            **item.dict(),
            "id": encode_id(item.id),
            "panel_id": encode_id(item.panel_id),
        }
        for item in revisions
    ]


@router.post("/api/panels/{panel_id}/revisions/{revision_id}/restore")
async def restore_panel_revision_api(
    panel_id: str,
    revision_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    panel = require_panel_team_access(session, team, decode_id(panel_id))
    revision = session.get(PanelRevision, decode_id(revision_id))
    if not revision:
        raise HTTPException(status_code=404, detail="Revision not found")
    if revision.panel_id != panel.id:
        raise HTTPException(status_code=400, detail="Revision does not belong to panel")

    panel = restore_panel_revision(session, panel, revision)
    return {
        "status": "success",
        "panel_id": encode_id(panel.id),
        "current_revision_id": encode_id(panel.current_revision_id) if panel.current_revision_id else None,
    }
