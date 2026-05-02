from __future__ import annotations

from typing import Any, Dict, Optional

from sqlmodel import Session, select

from models import Episode, Panel, Script, SharedResource


CREATIVE_STAGE_LABELS: Dict[str, str] = {
    "script_empty": "剧本创作",
    "script_ready": "剧本已就绪",
    "assets_pending": "资产提取",
    "assets_ready": "资产已就绪",
    "asset_images_pending": "资产参考图生成",
    "storyboard_pending": "分镜拆解",
    "storyboard_ready": "分镜已就绪",
    "images_pending": "分镜图生成",
    "images_ready": "图片已就绪",
    "videos_pending": "视频生成",
    "videos_ready": "视频已就绪",
}

ACTIVE_AGENT_LABELS: Dict[str, str] = {
    "director_agent": "编剧专家",
    "asset_planner_agent": "资产设计专家",
    "storyboard_agent": "分镜导演",
    "generation_agent": "生成助手",
}

STAGE_AGENT_MAP: Dict[str, str] = {
    "script_empty": "director_agent",
    "script_ready": "director_agent",
    "assets_pending": "asset_planner_agent",
    "assets_ready": "generation_agent",
    "asset_images_pending": "generation_agent",
    "storyboard_pending": "storyboard_agent",
    "storyboard_ready": "generation_agent",
    "images_pending": "generation_agent",
    "images_ready": "generation_agent",
    "videos_pending": "generation_agent",
    "videos_ready": "generation_agent",
}


def _is_safe_media_url(value: Optional[str]) -> bool:
    text = str(value or "").strip()
    if not text or text.startswith("ERROR:"):
        return False
    return text.startswith(("http://", "https://", "data:", "blob:", "/"))


def _resource_type_counts(resources: list[SharedResource]) -> Dict[str, int]:
    counts = {"character": 0, "scene": 0, "prop": 0}
    for item in resources:
        key = str(getattr(item, "resource_type", "") or "").strip().lower()
        if key in counts:
            counts[key] += 1
    return counts


def build_creative_stage_read_model_from_facts(
    *,
    script,
    episode: Optional[Episode],
    workspace_facts: Dict[str, Any],
) -> Dict[str, Any]:
    source_text = str((workspace_facts or {}).get("current_script") or "").strip()
    resource_total = int((workspace_facts or {}).get("resource_total") or 0)
    resource_counts = dict((workspace_facts or {}).get("resource_counts") or {})
    asset_image_count = int((workspace_facts or {}).get("asset_image_count") or 0)
    panel_count = int((workspace_facts or {}).get("panel_count") or 0)
    panels_with_images = int((workspace_facts or {}).get("panels_with_images") or 0)
    panels_with_videos = int((workspace_facts or {}).get("panels_with_videos") or 0)

    if not source_text:
        stage = "script_empty"
    elif episode is None:
        stage = "script_ready"
    elif resource_total <= 0:
        stage = "assets_pending"
    elif panel_count <= 0:
        if asset_image_count <= 0:
            stage = "assets_ready"
        elif asset_image_count < resource_total:
            stage = "asset_images_pending"
        else:
            stage = "storyboard_pending"
    elif panels_with_images <= 0:
        stage = "storyboard_ready"
    elif panels_with_images < panel_count:
        stage = "images_pending"
    elif panels_with_videos <= 0:
        stage = "images_ready"
    elif panels_with_videos < panel_count:
        stage = "videos_pending"
    else:
        stage = "videos_ready"

    active_agent = STAGE_AGENT_MAP.get(stage, "director_agent")
    return {
        "creative_stage": stage,
        "creative_stage_label": CREATIVE_STAGE_LABELS.get(stage, stage),
        "active_agent": active_agent,
        "active_agent_label": ACTIVE_AGENT_LABELS.get(active_agent, active_agent),
        "script_id": getattr(script, "id", None),
        "episode_id": getattr(episode, "id", None) if episode else None,
        "facts": {
            "script_name": getattr(script, "name", None),
            "episode_title": getattr(episode, "title", None) if episode else None,
            "has_source_text": bool(source_text),
            "source_text_length": len(source_text),
            "resource_total": resource_total,
            "resource_counts": resource_counts,
            "asset_image_count": asset_image_count,
            "panel_count": panel_count,
            "panels_with_images": panels_with_images,
            "panels_with_videos": panels_with_videos,
        },
    }


def build_creative_stage_read_model(
    session: Session,
    *,
    script_id: int,
    episode_id: Optional[int] = None,
) -> Dict[str, Any]:
    script = session.get(Script, script_id)
    if not script:
        stage = "script_empty"
        return {
            "creative_stage": stage,
            "creative_stage_label": CREATIVE_STAGE_LABELS[stage],
            "active_agent": STAGE_AGENT_MAP[stage],
            "active_agent_label": ACTIVE_AGENT_LABELS[STAGE_AGENT_MAP[stage]],
            "script_id": script_id,
            "episode_id": episode_id,
            "facts": {},
        }

    episode = session.get(Episode, episode_id) if episode_id else None
    if episode is None and episode_id is None:
        episode = session.exec(
            select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc(), Episode.id.asc())
        ).first()

    resources = session.exec(
        select(SharedResource)
        .where(SharedResource.script_id == script.id)
        .order_by(SharedResource.created_at.asc(), SharedResource.id.asc())
    ).all()
    panels = []
    if episode is not None:
        panels = session.exec(
            select(Panel).where(Panel.episode_id == episode.id).order_by(Panel.sequence_num.asc(), Panel.id.asc())
        ).all()

    source_text = str((episode.source_text if episode else "") or script.source_text or "").strip()
    resource_counts = _resource_type_counts(resources)
    asset_image_count = sum(1 for item in resources if _is_safe_media_url(getattr(item, "file_url", None)))
    panel_count = len(panels)
    panels_with_images = sum(1 for item in panels if _is_safe_media_url(getattr(item, "image_url", None)))
    panels_with_videos = sum(1 for item in panels if _is_safe_media_url(getattr(item, "video_url", None)))

    if not source_text:
        stage = "script_empty"
    elif episode is None:
        stage = "script_ready"
    elif not resources:
        stage = "assets_pending"
    elif panel_count <= 0:
        if asset_image_count <= 0:
            stage = "assets_ready"
        elif asset_image_count < len(resources):
            stage = "asset_images_pending"
        else:
            stage = "storyboard_pending"
    elif panels_with_images <= 0:
        stage = "storyboard_ready"
    elif panels_with_images < panel_count:
        stage = "images_pending"
    elif panels_with_videos <= 0:
        stage = "images_ready"
    elif panels_with_videos < panel_count:
        stage = "videos_pending"
    else:
        stage = "videos_ready"

    active_agent = STAGE_AGENT_MAP.get(stage, "director_agent")
    return {
        "creative_stage": stage,
        "creative_stage_label": CREATIVE_STAGE_LABELS.get(stage, stage),
        "active_agent": active_agent,
        "active_agent_label": ACTIVE_AGENT_LABELS.get(active_agent, active_agent),
        "script_id": script.id,
        "episode_id": episode.id if episode else None,
        "facts": {
            "script_name": script.name,
            "episode_title": episode.title if episode else None,
            "has_source_text": bool(source_text),
            "source_text_length": len(source_text),
            "resource_total": len(resources),
            "resource_counts": resource_counts,
            "asset_image_count": asset_image_count,
            "panel_count": panel_count,
            "panels_with_images": panels_with_images,
            "panels_with_videos": panels_with_videos,
        },
    }


def get_next_stage_after_action(
    *,
    action_type: str,
    current_stage: str,
    action_result: Optional[Dict[str, Any]] = None,
    facts: Optional[Dict[str, Any]] = None,
) -> str:
    action_result = action_result or {}
    facts = facts or {}

    if action_type == "save_script":
        return "assets_pending"
    if action_type in {"extract_assets", "save_assets"}:
        if action_result.get("next_stage_hint") == "asset_images_pending":
            return "asset_images_pending"
        return "assets_ready"
    if action_type == "generate_asset_images":
        if int(facts.get("asset_image_count") or 0) <= 0:
            return "asset_images_pending"
        return "storyboard_pending"
    if action_type == "save_storyboard":
        return "storyboard_ready"
    if action_type == "generate_storyboard_images":
        if action_result.get("next_stage_hint") == "images_ready":
            return "images_ready"
        return "images_pending"
    if action_type == "generate_video":
        if action_result.get("next_stage_hint") == "videos_ready":
            return "videos_ready"
        return "videos_pending"
    return current_stage or "script_empty"
