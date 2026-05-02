from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Optional, Set, Tuple

from sqlalchemy import func
from sqlmodel import Session, select

from core.security import encode_id
from models import Episode, Panel, PointLog, Script, TeamMemberLink, User

IMAGE_ACTIONS: Set[str] = {
    "generate_image",
    "generate_image_rh_v2",
    "generate_nano",
    "generate_asset_image",
    "creative_image_generate",
}
IMG2IMG_ACTIONS: Set[str] = {
    "generate_img2img",
    "generate_img2img_rh",
}
VIDEO_ACTIONS: Set[str] = {
    "generate_video",
    "creative_video_generate",
}
ASSET_ACTIONS: Set[str] = {
    "creative_asset_generate",
}

POINT_INCOME_LABELS: Dict[str, str] = {
    "top_up": "灵感值充值",
    "admin_grant": "灵感值赠送",
    "daily_bonus": "每日盲盒",
}

RESOLUTION_PATTERN = re.compile(r"\b(360p|540p|720p|1080p|1k|2k|4k)\b", re.IGNORECASE)
RATIO_PATTERN = re.compile(r"\b(\d{1,2}:\d{1,2})\b")
DURATION_PATTERN = re.compile(r"(\d+)\s*(?:秒|s|sec|seconds?)", re.IGNORECASE)

LOW_COST_KEYWORDS = ("low_cost", "低价", "shenlu-image-fast", "nano-banana-2", "nano-banana-2-低价版", "nano-banana-pro-低价版")
STABLE_KEYWORDS = (
    "stable",
    "稳定",
    "shenlu-image-stable",
    "nano-banana-pro",
    "nano-banana-pro-vip",
    "nano-banana-pro-4k-vip",
    "全能图片",
)
VIDEO_Q2_KEYWORDS = ("vidu q2", "vidu_q2", "vidu-q2", "runninghub-vidu-q2-pro")
VIDEO_Q3_KEYWORDS = ("vidu q3", "vidu_q3", "vidu-q3", "runninghub-vidu-q3-pro")
DIGITAL_HUMAN_KEYWORDS = ("digital_human", "数字人", "suchuang-digital-human", "shenlu-neu-character")
CHARACTER_KEYWORDS = ("人物", "角色", "character")
SCENE_KEYWORDS = ("场景", "scene")
PROP_KEYWORDS = ("道具", "prop")


def _to_iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _extract_resolution(text: str) -> str:
    match = RESOLUTION_PATTERN.search(text or "")
    if not match:
        return ""
    resolution = match.group(1).lower()
    return resolution.upper() if resolution.endswith("k") else resolution


def _extract_ratio(text: str) -> str:
    match = RATIO_PATTERN.search(text or "")
    return match.group(1) if match else ""


def _extract_duration(text: str) -> Optional[int]:
    match = DURATION_PATTERN.search(text or "")
    if not match:
        return None
    try:
        return max(int(match.group(1)), 1)
    except (TypeError, ValueError):
        return None


def _resolve_feature(action_type: str, description: str, change_amount: int) -> Tuple[str, str]:
    action = (action_type or "").strip().lower()
    desc = (description or "").lower()

    if action in VIDEO_ACTIONS:
        return "video_generation", "视频生成"
    if action in ASSET_ACTIONS:
        return "asset_generation", "资产生成"
    if action in IMG2IMG_ACTIONS:
        return "image_to_image", "图生图"
    if action in IMAGE_ACTIONS:
        if "图生图" in desc or "img2img" in desc:
            return "image_to_image", "图生图"
        return "text_to_image", "图片生成"
    if change_amount > 0:
        return "point_income", POINT_INCOME_LABELS.get(action, "灵感值入账")
    if change_amount < 0:
        return "point_consume", "灵感值消耗"
    return "other", "其他"


def _resolve_image_tier_label(action_type: str, description: str) -> str:
    raw = f"{action_type} {description}".lower()
    if any(keyword in raw for keyword in LOW_COST_KEYWORDS):
        return "低价版"
    if any(keyword in raw for keyword in STABLE_KEYWORDS):
        return "稳定版"
    return "稳定版"


def _resolve_video_model_label(description: str) -> str:
    raw = (description or "").lower()
    duration = _extract_duration(raw) or 5
    if any(keyword in raw for keyword in DIGITAL_HUMAN_KEYWORDS):
        return "数字人"
    if any(keyword in raw for keyword in VIDEO_Q3_KEYWORDS):
        return "Vidu Q3"
    if any(keyword in raw for keyword in VIDEO_Q2_KEYWORDS):
        return "Vidu Q2"
    if "shenlu-physics-engine" in raw:
        return "Vidu Q3" if duration > 10 else "Vidu Q2"
    return "视频生成"


def _resolve_asset_type_label(description: str) -> str:
    raw = (description or "").lower()
    if any(keyword.lower() in raw for keyword in CHARACTER_KEYWORDS):
        return "人物"
    if any(keyword.lower() in raw for keyword in SCENE_KEYWORDS):
        return "场景"
    if any(keyword.lower() in raw for keyword in PROP_KEYWORDS):
        return "道具"
    return "资产"


def _build_generation_spec_summary(feature_key: str, action_type: str, description: str) -> str:
    resolution = _extract_resolution(description)
    duration = _extract_duration(description)

    if feature_key in {"text_to_image", "image_to_image"}:
        return f"{_resolve_image_tier_label(action_type, description)} · {resolution or '2K'}"

    if feature_key == "video_generation":
        model_label = _resolve_video_model_label(description)
        resolution_label = resolution or "720p"
        duration_label = f"{duration or 5}秒"
        return f"{model_label} · {resolution_label} · {duration_label}"

    if feature_key == "asset_generation":
        asset_type_label = _resolve_asset_type_label(description)
        resolution_label = resolution or "2K"
        return f"{asset_type_label} · 稳定版 · {resolution_label}"

    if feature_key == "point_income":
        return "灵感值入账"

    if feature_key == "point_consume":
        return "灵感值消耗"

    ratio = _extract_ratio(description)
    return ratio or ""


def _build_public_description(feature_key: str, description: str) -> str:
    if feature_key == "text_to_image":
        return "已提交图片生成任务"
    if feature_key == "image_to_image":
        return "已提交图生图任务"
    if feature_key == "video_generation":
        return "已提交数字人生成任务" if _resolve_video_model_label(description) == "数字人" else "已提交视频生成任务"
    if feature_key == "asset_generation":
        return f"已提交{_resolve_asset_type_label(description)}资产生成任务"
    if feature_key == "point_income":
        return "灵感值已到账"
    if feature_key == "point_consume":
        return "灵感值已消耗"
    return description or "灵感值记录"


def build_user_point_log_item(log: PointLog) -> dict:
    feature_key, feature_name = _resolve_feature(log.action_type or "", log.description or "", log.change_amount)
    return {
        "id": log.id,
        "change_amount": log.change_amount,
        "balance_after": log.balance_after,
        "action_type": log.action_type or "",
        "feature_key": feature_key,
        "feature_name": feature_name,
        "spec_summary": _build_generation_spec_summary(feature_key, log.action_type or "", log.description or ""),
        "description": _build_public_description(feature_key, log.description or ""),
        "created_at": _to_iso(log.created_at),
    }


def is_generation_feature(feature_key: str) -> bool:
    return feature_key in {"text_to_image", "image_to_image", "video_generation", "asset_generation"}


def get_action_types_for_feature(feature_type: str) -> Set[str]:
    key = (feature_type or "").strip()
    if key == "text_to_image":
        return set(IMAGE_ACTIONS)
    if key == "image_to_image":
        return set(IMG2IMG_ACTIONS)
    if key == "video_generation":
        return set(VIDEO_ACTIONS)
    if key == "asset_generation":
        return set(ASSET_ACTIONS)
    return set()


def mark_script_access_by_script_id(session: Session, script_id: int) -> None:
    script = session.get(Script, script_id)
    if not script:
        return
    script.last_accessed_at = datetime.utcnow()
    session.add(script)


def mark_script_access_by_episode_id(session: Session, episode_id: int) -> None:
    episode = session.get(Episode, episode_id)
    if not episode:
        return
    mark_script_access_by_script_id(session, episode.script_id)


def mark_script_access_by_panel_id(session: Session, panel_id: int) -> None:
    panel = session.get(Panel, panel_id)
    if not panel:
        return
    mark_script_access_by_episode_id(session, panel.episode_id)


def get_user_dashboard_data(session: Session, user: User) -> dict:
    link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user.id)).first()
    team_id = link.team_id if link else None

    project_count = 0
    total_episode_count = 0
    total_panel_count = 0
    recent_projects = []

    if team_id:
        project_count = session.exec(select(func.count()).select_from(Script).where(Script.team_id == team_id)).one() or 0
        total_episode_count = (
            session.exec(
                select(func.count()).select_from(Episode).join(Script, Episode.script_id == Script.id).where(Script.team_id == team_id)
            ).one()
            or 0
        )
        total_panel_count = (
            session.exec(
                select(func.count())
                .select_from(Panel)
                .join(Episode, Panel.episode_id == Episode.id)
                .join(Script, Episode.script_id == Script.id)
                .where(Script.team_id == team_id)
            ).one()
            or 0
        )

        recent_scripts = session.exec(
            select(Script)
            .where(Script.team_id == team_id)
            .order_by(func.coalesce(Script.last_accessed_at, Script.created_at).desc())
            .limit(8)
        ).all()

        script_ids = [script.id for script in recent_scripts if script.id]
        episode_count_map = {}
        if script_ids:
            rows = session.exec(
                select(Episode.script_id, func.count(Episode.id)).where(Episode.script_id.in_(script_ids)).group_by(Episode.script_id)
            ).all()
            episode_count_map = {script_id: count for script_id, count in rows}

        recent_projects = [
            {
                "id": encode_id(script.id),
                "name": script.name,
                "description": script.description,
                "episode_count": episode_count_map.get(script.id, 0),
                "created_at": _to_iso(script.created_at),
                "last_accessed_at": _to_iso(script.last_accessed_at),
            }
            for script in recent_scripts
        ]

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_logs = session.exec(select(PointLog).where(PointLog.user_id == user.id, PointLog.created_at >= today_start)).all()
    today_consumed = sum(abs(log.change_amount) for log in today_logs if log.change_amount < 0)
    today_added = sum(log.change_amount for log in today_logs if log.change_amount > 0)

    recent_logs = session.exec(
        select(PointLog).where(PointLog.user_id == user.id, PointLog.change_amount < 0).order_by(PointLog.id.desc()).limit(12)
    ).all()
    recent_generations = []
    for log in recent_logs:
        item = build_user_point_log_item(log)
        if is_generation_feature(item["feature_key"]):
            recent_generations.append(item)

    total_points = user.permanent_points + user.temporary_points
    return {
        "project_summary": {
            "total_projects": project_count,
            "total_episodes": total_episode_count,
            "total_panels": total_panel_count,
        },
        "recent_projects": recent_projects,
        "points_summary": {
            "total_points": total_points,
            "permanent_points": user.permanent_points,
            "temporary_points": user.temporary_points,
            "today_consumed": today_consumed,
            "today_added": today_added,
        },
        "recent_generations": recent_generations,
    }
