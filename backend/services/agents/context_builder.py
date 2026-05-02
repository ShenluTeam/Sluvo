from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlmodel import Session, select

from models import Panel, SharedResource


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _shorten(value: Any, limit: int = 220) -> str:
    text = _clean_text(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _resource_item(resource: SharedResource) -> Dict[str, Any]:
    return {
        "id": getattr(resource, "id", None),
        "name": _clean_text(getattr(resource, "name", None)),
        "resource_type": _clean_text(getattr(resource, "resource_type", None)),
        "trigger_word": _clean_text(getattr(resource, "trigger_word", None)),
        "description": _shorten(getattr(resource, "description", None), 180),
        "has_image": bool(_clean_text(getattr(resource, "file_url", None))),
    }


def _panel_item(panel: Panel) -> Dict[str, Any]:
    return {
        "id": getattr(panel, "id", None),
        "sequence_num": getattr(panel, "sequence_num", None),
        "grid_count": getattr(panel, "grid_count", None),
        "summary": _shorten(
            getattr(panel, "segment_summary", None)
            or getattr(panel, "scene_prompt", None)
            or getattr(panel, "prompt", None),
            180,
        ),
        "has_image": bool(_clean_text(getattr(panel, "image_url", None))),
        "has_video": bool(_clean_text(getattr(panel, "video_url", None))),
    }


def _load_resources(session: Session, script_id: int) -> List[SharedResource]:
    return session.exec(
        select(SharedResource)
        .where(SharedResource.script_id == script_id)
        .order_by(SharedResource.created_at.asc(), SharedResource.id.asc())
    ).all()


def _load_panels(session: Session, episode_id: Optional[int]) -> List[Panel]:
    if not episode_id:
        return []
    return session.exec(
        select(Panel)
        .where(Panel.episode_id == episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()


def build_workspace_facts(
    session: Session,
    *,
    script,
    episode=None,
) -> Dict[str, Any]:
    resources = _load_resources(session, script.id)
    panels = _load_panels(session, getattr(episode, "id", None))

    characters = [_resource_item(item) for item in resources if _clean_text(getattr(item, "resource_type", None)).lower() == "character"]
    scenes = [_resource_item(item) for item in resources if _clean_text(getattr(item, "resource_type", None)).lower() == "scene"]
    props = [_resource_item(item) for item in resources if _clean_text(getattr(item, "resource_type", None)).lower() == "prop"]

    return {
        "script_name": _clean_text(getattr(script, "name", None)),
        "episode_title": _clean_text(getattr(episode, "title", None)) if episode is not None else "",
        "script_has_source_text": bool(_clean_text(getattr(script, "source_text", None))),
        "episode_has_source_text": bool(_clean_text(getattr(episode, "source_text", None))) if episode is not None else False,
        "current_script": _shorten((getattr(episode, "source_text", None) if episode is not None else None) or getattr(script, "source_text", None), 1200),
        "resource_total": len(resources),
        "asset_image_count": sum(1 for item in resources if _clean_text(getattr(item, "file_url", None))),
        "resource_counts": {
            "characters": len(characters),
            "scenes": len(scenes),
            "props": len(props),
        },
        "characters": characters[:12],
        "scenes": scenes[:10],
        "props": props[:12],
        "panels": [_panel_item(panel) for panel in panels[:12]],
        "panel_count": len(panels),
        "panels_with_images": sum(1 for panel in panels if _clean_text(getattr(panel, "image_url", None))),
        "panels_with_videos": sum(1 for panel in panels if _clean_text(getattr(panel, "video_url", None))),
    }


def build_agent_specific_context(
    *,
    agent_name: str,
    base_context: Dict[str, Any],
    workspace_facts: Dict[str, Any],
    latest_artifacts: Optional[Dict[str, Any]],
    workflow_profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    latest_artifacts = latest_artifacts or {}
    workflow_profile = workflow_profile or {}
    storyboard_mode = _clean_text(workflow_profile.get("storyboard_mode"))
    style_payload = workflow_profile.get("style") if isinstance(workflow_profile.get("style"), dict) else {}
    base = {
        "creative_stage": base_context.get("creative_stage"),
        "creative_stage_label": base_context.get("creative_stage_label"),
        "latest_user_message": _clean_text(base_context.get("latest_user_message")),
        "available_actions": base_context.get("available_actions") or [],
        "storyboard_mode": storyboard_mode,
        "aspect_ratio": _clean_text(workflow_profile.get("aspect_ratio")),
        "style_label": _clean_text(style_payload.get("label")),
    }

    if agent_name == "director_agent":
        return {
            **base,
            "current_script": workspace_facts.get("current_script", ""),
            "latest_script_artifact": latest_artifacts.get("script_draft") or {},
            "script_name": workspace_facts.get("script_name", ""),
            "episode_title": workspace_facts.get("episode_title", ""),
            "workflow_profile": workflow_profile,
        }

    if agent_name == "asset_planner_agent":
        return {
            **base,
            "current_script": workspace_facts.get("current_script", ""),
            "resource_counts": workspace_facts.get("resource_counts") or {},
            "characters": workspace_facts.get("characters") or [],
            "scenes": workspace_facts.get("scenes") or [],
            "props": workspace_facts.get("props") or [],
            "latest_asset_artifact": latest_artifacts.get("asset_bundle") or {},
        }

    if agent_name == "storyboard_agent":
        return {
            **base,
            "script_summary": _shorten(workspace_facts.get("current_script", ""), 800),
            "characters": workspace_facts.get("characters") or [],
            "scenes": workspace_facts.get("scenes") or [],
            "props": workspace_facts.get("props") or [],
            "panel_count": workspace_facts.get("panel_count") or 0,
            "existing_panels": workspace_facts.get("panels") or [],
            "latest_storyboard_artifact": latest_artifacts.get("storyboard_bundle") or {},
            "workflow_profile": workflow_profile,
        }

    if agent_name == "generation_agent":
        return {
            **base,
            "resource_counts": workspace_facts.get("resource_counts") or {},
            "panels": workspace_facts.get("panels") or [],
            "panels_with_images": workspace_facts.get("panels_with_images") or 0,
            "panels_with_videos": workspace_facts.get("panels_with_videos") or 0,
            "latest_generation_artifact": latest_artifacts.get("generation_bundle") or {},
        }

    return {**base, "workspace_facts": workspace_facts}


def build_agent_context_preview(
    session: Session,
    *,
    agent_name: str,
    script,
    episode=None,
    latest_user_message: str = "",
    creative_stage: str = "",
    creative_stage_label: str = "",
    available_actions: Optional[List[Dict[str, Any]]] = None,
    latest_artifacts: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    workspace_facts = build_workspace_facts(session, script=script, episode=episode)
    base_context = {
        "creative_stage": creative_stage,
        "creative_stage_label": creative_stage_label,
        "latest_user_message": latest_user_message,
        "available_actions": available_actions or [],
    }
    agent_context = build_agent_specific_context(
        agent_name=agent_name,
        base_context=base_context,
        workspace_facts=workspace_facts,
        latest_artifacts=latest_artifacts,
    )
    return {
        "base_context": base_context,
        "workspace_facts": workspace_facts,
        "agent_context": agent_context,
    }
