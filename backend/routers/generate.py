from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Tuple
import uuid
import asyncio
import time
from datetime import datetime
from types import SimpleNamespace

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, File, UploadFile
from sqlmodel import Session, select

from database import get_session, engine
from dependencies import get_current_user, get_current_team, require_team_permission
from core.security import decode_id, encode_id
from core.config import settings
from models import User, Team, TeamMemberLink, Panel, Episode, Script, ChannelSettings, TaskStatusEnum, VIPTierEnum
from schemas import (
    GenerateRequest,
    Img2ImgRequest,
    NanoBananaRequest,
    GenerateImageV2Request,
    ImageEstimateRequest,
    GenerateAssetImageRequest,
    GenerateVideoRequest,
    VideoEstimateRequest,
    PANEL_TYPE_NINE_GRID,
    STORYBOARD_MODE_COMMENTARY,
    STORYBOARD_MODE_COMIC,
    normalize_panel_type,
)
from services.access_service import require_episode_team_access, require_panel_team_access
from services.billing_service import deduct_inspiration_points
from services.runninghub_service import poll_runninghub_task, poll_runninghub_img2img, dispatch_runninghub_task_v2
from services.grsai_service import poll_nano_task_v1, dispatch_grsai_task_v2, poll_standalone_task
from services.suchuang_service import dispatch_suchuang_task_v2
from services.suchuang_video_service import suchuang_video_service
from services.runninghub_video_service import runninghub_video_service
from services.task_registry import nano_tasks, standalone_tasks, video_tasks
from services.panel_video_service import upsert_panel_video_history
from services.storyboard_mode_service import (
    get_panel_reference_images,
    hydrate_panel_storyboard_fields,
    recompute_episode_dependencies,
)
from services.storyboard_director_service import build_segment_layout_spec
from services.generation_record_service import (
    _create_generation_record,
    estimate_video_generation as estimate_productized_video_generation,
    get_generation_record_detail,
    submit_video_generation as submit_productized_video_generation,
)
from services.task_job_service import create_task_job, enqueue_task_job, get_task_job, serialize_task_job
from services.workflow_preset_service import augment_prompt_with_style, resolve_effective_workflow_profile
from services.image_model_registry import estimate_image_price, normalize_image_model_code, normalize_image_request


import requests
from sqlalchemy import func
from services.oss_service import build_oss_video_snapshot_url, upload_bytes_to_oss

router = APIRouter()

# 模型分级计费表
NANO_MODEL_COSTS = {
    "nano-banana-pro": 3,
    "nano-banana-pro-vt": 3,
    "nano-banana-pro-cl": 5,
    "nano-banana-pro-vip": 9,
    "nano-banana-2": 2,
    "suchuang-nanobanana2": 2,
    "nano-banana-pro-4k-vip": 10,
}

# ==========================================
# 官方通道分辨率动态计费表
# ==========================================
OFFICIAL_RESOLUTION_COSTS = {
    "1k": 6,
    "2k": 8,
    "4k": 10,
}

IMAGE_ROUTE_CONCURRENCY_THRESHOLD = 500

IMAGE_TIER_RESOLUTION_COSTS = {
    "shenlu-image-fast": {"1k": 2, "2k": 2, "4k": 3},
    "shenlu-image-stable": {"1k": 9, "2k": 11, "4k": 13},
}

IMAGE_FAST_ALIASES = {
    "shenlu-image-fast",
    "shenlu-sketch-v2",
}

IMAGE_STABLE_ALIASES = {
    "shenlu-image-stable",
    "shenlu-standard-v1",
    "shenlu-pro-v1",
    "shenlu-flagship-v1",
    "nano-banana-pro",
    "suchuang-nanobanana-pro",
}

PUBLIC_IMAGE_TIER_LABELS = {
    "shenlu-image-fast": "低价版",
    "shenlu-image-stable": "稳定版",
}

PUBLIC_VIDEO_MODEL_LABELS = {
    "runninghub-vidu-q2-pro": "Vidu Q2",
    "runninghub-vidu-q3-pro": "Vidu Q3",
    "suchuang-digital-human": "数字人",
    "shenlu-neu-character": "数字人",
}


def _normalize_resolution_key(resolution: Optional[str]) -> str:
    key = (resolution or "1k").strip().lower()
    if key in {"1k", "2k", "4k"}:
        return key
    return "1k"


def _get_highest_supported_image_resolution() -> str:
    return "4k"


def _resolve_panel_generation_resolution(panel: Panel, requested: Optional[str], default_resolution: str) -> str:
    if requested:
        return _normalize_resolution_key(requested)
    if False and normalize_panel_type(panel.panel_type) == PANEL_TYPE_NINE_GRID:
        return _get_highest_supported_image_resolution()
    return _normalize_resolution_key(default_resolution)


def _resolve_panel_generation_prompt(panel: Panel, requested: str, *, aspect_ratio: Optional[str] = None) -> str:
    if False and normalize_panel_type(panel.panel_type) == PANEL_TYPE_NINE_GRID:
        return (panel.nine_grid_prompt or requested or "").strip()
    return _compile_strict_multigrid_prompt(panel, requested, aspect_ratio=aspect_ratio or _get_panel_storyboard_aspect_ratio(panel))


def _is_strict_multigrid_panel(panel: Panel) -> bool:
    hydrate_panel_storyboard_fields(panel)
    return (
        str(getattr(panel, "storyboard_mode", STORYBOARD_MODE_COMMENTARY) or "").strip().lower() == STORYBOARD_MODE_COMIC
        and int(getattr(panel, "grid_count", 1) or 1) in {2, 4, 6, 9}
    )


def _compile_strict_multigrid_prompt(panel: Panel, requested: str, *, aspect_ratio: str) -> str:
    base_prompt = str(requested or panel.multi_shot_prompt or panel.prompt or "").strip()
    if not base_prompt or not _is_strict_multigrid_panel(panel):
        return base_prompt
    layout_spec = build_segment_layout_spec(
        grid_count=getattr(panel, "grid_count", 1),
        aspect_ratio=aspect_ratio,
        storyboard_mode=getattr(panel, "storyboard_mode", None),
    )
    if not layout_spec.get("is_multigrid"):
        return base_prompt
    if "版式要求：" in base_prompt and str(layout_spec.get("layout_prompt") or "").strip() in base_prompt:
        return base_prompt
    layout_lines = ["版式要求：", str(layout_spec.get("layout_prompt") or "").strip()]
    layout_lines.extend([str(item or "").strip() for item in (layout_spec.get("layout_requirements") or []) if str(item or "").strip()])
    layout_lines.append("文字限制：严格去掉所有可见文字元素，不允许在宫格内外出现任何字幕、标签、景别字样、对白气泡、注释、水印、logo 或说明文字。")
    return f"{base_prompt}\n\n" + "\n".join([item for item in layout_lines if item]).strip()


def _get_storyboard_default_aspect_ratio(storyboard_mode: Optional[str]) -> str:
    if str(storyboard_mode or "").strip().lower() == STORYBOARD_MODE_COMIC:
        return "16:9"
    return "9:16"


def _get_panel_storyboard_aspect_ratio(panel: Panel) -> str:
    hydrate_panel_storyboard_fields(panel)
    return _get_storyboard_default_aspect_ratio(getattr(panel, "storyboard_mode", STORYBOARD_MODE_COMMENTARY))


def _resolve_storyboard_aspect_ratio(requested: Optional[str], storyboard_mode: Optional[str]) -> str:
    default_ratio = _get_storyboard_default_aspect_ratio(storyboard_mode)
    requested_ratio = str(requested or "").strip()
    if requested_ratio in {"16:9", "9:16"}:
        return requested_ratio
    return default_ratio


def _resolve_effective_image_workflow_profile(session: Session, episode: Episode, panel: Optional[Panel] = None) -> Dict[str, Any]:
    script = session.get(Script, episode.script_id)
    storyboard_mode = getattr(panel, "storyboard_mode", None) if panel is not None else getattr(episode, "storyboard_mode", None)
    if not script:
        return {
            "aspect_ratio": _get_storyboard_default_aspect_ratio(storyboard_mode),
            "image": {"model_code": "nano-banana-pro", "resolution": "2k"},
            "video": {},
            "style": {},
        }
    return resolve_effective_workflow_profile(script, episode=episode, storyboard_mode=storyboard_mode)


def _merge_reference_images(*groups: List[str]) -> List[str]:
    merged: List[str] = []
    seen = set()
    for group in groups:
        for item in group or []:
            value = str(item or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            merged.append(value)
    return merged


def _resolve_image_tier(channel: str) -> Optional[str]:
    if channel in IMAGE_FAST_ALIASES:
        return "shenlu-image-fast"
    if channel in IMAGE_STABLE_ALIASES:
        return "shenlu-image-stable"
    return None


def _count_rh_official_concurrent_tasks(session: Session) -> int:
    active_statuses = [TaskStatusEnum.PROCESSING, TaskStatusEnum.PENDING]
    statement = (
        select(func.count(Panel.id))
        .where(Panel.status.in_(active_statuses))
        .where(Panel.task_id.like("v2-rh-v2-official-%"))
    )
    result = session.exec(statement).one()
    return int(result or 0)


def _format_public_image_quality_label(resolution: Optional[str]) -> str:
    return _normalize_resolution_key(resolution).upper()


def _format_public_video_resolution_label(resolution: Optional[str]) -> str:
    value = (resolution or "720p").strip().lower()
    if value.endswith("k"):
        return value.upper()
    return value


def _format_public_duration_label(duration: Optional[int]) -> str:
    seconds = max(int(duration or 1), 1)
    return f"{seconds}秒"


def _resolve_public_image_tier_label(channel: str) -> str:
    tier = _resolve_image_tier(channel)
    return PUBLIC_IMAGE_TIER_LABELS.get(tier or "", "稳定版")


def _resolve_video_channel_id(channel_id: str, duration: int) -> str:
    if channel_id == "shenlu-physics-engine":
        return "runninghub-vidu-q3-pro" if duration > 10 else "runninghub-vidu-q2-pro"
    if channel_id == "shenlu-neu-character":
        return "suchuang-digital-human"
    return channel_id


def _resolve_public_video_model_label(channel_id: str, duration: int) -> str:
    resolved_channel = _resolve_video_channel_id(channel_id, duration)
    return PUBLIC_VIDEO_MODEL_LABELS.get(resolved_channel, "视频生成")


def _legacy_video_model_code(channel_id: str, duration: int) -> Optional[str]:
    resolved_channel = _resolve_video_channel_id(channel_id, duration)
    if resolved_channel == "runninghub-vidu-q2-pro":
        return "vidu_q2_pro"
    if resolved_channel == "runninghub-vidu-q3-pro":
        return "vidu_q3_pro"
    if resolved_channel == "suchuang-veo3.1-pro":
        return "veo_31_pro_official"
    return None


def _legacy_video_generation_type(
    *,
    model_code: str,
    first_frame: Optional[str],
    last_frame: Optional[str],
    image_refs: List[str],
    video_refs: List[str],
) -> str:
    if model_code in {"vidu_q2_pro", "kling_o1"}:
        if video_refs or len(image_refs) > 1:
            return "reference_to_video"
        if last_frame:
            return "start_end_to_video"
        return "image_to_video"
    if model_code in {"veo_31_pro_official", "veo_31_fast_official"}:
        return "image_to_video" if (first_frame or image_refs or last_frame) else "text_to_video"
    if model_code in {"vidu_q3_pro"}:
        if last_frame:
            return "start_end_to_video"
        return "image_to_video" if (first_frame or image_refs) else "text_to_video"
    return "image_to_video" if (first_frame or image_refs or video_refs) else "text_to_video"


def _build_legacy_video_productized_payload(
    *,
    req: GenerateVideoRequest | VideoEstimateRequest,
    project_id: Optional[str] = None,
    episode_id: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
) -> Dict[str, Any]:
    model_code = _legacy_video_model_code(getattr(req, "channel_id", None) or getattr(req, "channel", None), int(req.duration))
    if not model_code:
        raise HTTPException(status_code=400, detail="当前 legacy 视频通道暂未纳入新的模型目录")
    image_refs = [str(item).strip() for item in (getattr(req, "reference_images", None) or []) if str(item).strip()]
    video_refs = [str(item).strip() for item in (getattr(req, "reference_videos", None) or []) if str(item).strip()]
    first_frame = str(getattr(req, "start_frame", None) or getattr(req, "image_url", None) or "").strip()
    last_frame = str(getattr(req, "end_frame", None) or "").strip()
    generation_type = _legacy_video_generation_type(
        model_code=model_code,
        first_frame=first_frame,
        last_frame=last_frame,
        image_refs=image_refs,
        video_refs=video_refs,
    )
    payload: Dict[str, Any] = {
        "ownership_mode": "project" if episode_id else "standalone",
        "project_id": project_id,
        "episode_id": episode_id,
        "target_type": target_type,
        "target_id": target_id,
        "model_code": model_code,
        "generation_type": generation_type,
        "duration": int(req.duration),
        "resolution": str(req.resolution or "720p").strip(),
        "aspect_ratio": str(getattr(req, "aspect_ratio", None) or "16:9").strip(),
        "image_refs": image_refs,
        "video_refs": video_refs,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "audio_enabled": bool(getattr(req, "audio", None)),
        "motion_strength": str(getattr(req, "movement_amplitude", None) or "auto").strip(),
        "audio_url": str(getattr(req, "audio_url", None) or "").strip(),
    }
    if hasattr(req, "prompt"):
        payload["prompt"] = str(getattr(req, "prompt") or "").strip()
    if generation_type == "reference_to_video" and model_code == "vidu_q3_pro":
        payload["model_code"] = "vidu_q2_pro"
        payload["generation_type"] = "reference_to_video"
    return payload


def _resolve_image_generation_channel(session: Session, requested_channel: str, resolution_key: str, has_ref: bool):
    virtual_tier = _resolve_image_tier(requested_channel)
    actual_channel = requested_channel

    if virtual_tier == "shenlu-image-fast":
        actual_channel = "nano-banana-2"
    elif virtual_tier == "shenlu-image-stable":
        rh_concurrent = _count_rh_official_concurrent_tasks(session)
        use_rh = rh_concurrent <= IMAGE_ROUTE_CONCURRENCY_THRESHOLD
        if use_rh:
            actual_channel = "rh-v2-official-img2img" if has_ref else "rh-v2-official-text2img"
        else:
            actual_channel = "nano-banana-pro-4k-vip" if resolution_key == "4k" else "nano-banana-pro-vip"

    statement = select(ChannelSettings).where(ChannelSettings.channel_id == actual_channel)
    channel_info = session.exec(statement).first()
    if not channel_info or not channel_info.is_active:
        if virtual_tier is None and requested_channel.startswith("shenlu-"):
            fallback_st = select(ChannelSettings).where(ChannelSettings.channel_id == "rh-v2-text2img")
            channel_info = session.exec(fallback_st).first()
            actual_channel = "rh-v2-text2img"
        if not channel_info:
            raise HTTPException(status_code=400, detail="所选图片生成引擎当前不可用")

    return virtual_tier, actual_channel, channel_info


def _calculate_image_generation_cost(
    session: Session,
    requested_channel: str,
    resolution: Optional[str],
    has_ref: bool,
) -> Tuple[int, str, str]:
    resolution_key = _normalize_resolution_key(resolution)
    virtual_tier, actual_channel, channel_info = _resolve_image_generation_channel(
        session=session,
        requested_channel=requested_channel,
        resolution_key=resolution_key,
        has_ref=has_ref,
    )

    if virtual_tier in IMAGE_TIER_RESOLUTION_COSTS:
        cost_points = IMAGE_TIER_RESOLUTION_COSTS[virtual_tier].get(
            resolution_key,
            IMAGE_TIER_RESOLUTION_COSTS[virtual_tier]["1k"],
        )
    elif actual_channel.startswith("rh-v2-official"):
        cost_points = OFFICIAL_RESOLUTION_COSTS.get(resolution_key, OFFICIAL_RESOLUTION_COSTS["1k"])
    else:
        cost_points = channel_info.cost_points

    return cost_points, actual_channel, channel_info.name


def _calculate_video_generation_cost(
    session: Session,
    channel_id: str,
    resolution: str,
    duration: int,
    audio: bool,
    reference_image_count: int,
    reference_video_count: int,
) -> Tuple[int, str]:
    resolved_channel_id = _resolve_video_channel_id(channel_id, duration)
    channel = session.exec(select(ChannelSettings).where(ChannelSettings.channel_id == resolved_channel_id)).first()
    if not channel or not channel.is_active:
        raise HTTPException(status_code=400, detail="鎵€閫夎棰戠敓鎴愬紩鎿庡綋鍓嶄笉鍙敤")

    has_advanced_reference = reference_image_count > 1 or reference_video_count > 0
    resolution_key = (resolution or "720p").strip().lower()

    if resolved_channel_id == "runninghub-vidu-q2-pro" and has_advanced_reference:
        table = VIDU_PRICING.get(resolution_key) or VIDU_PRICING.get("720p")
        final_cost = table.get(duration) or table.get(max(table.keys() if table else [1]))
    else:
        base_price = channel.cost_points
        resolution_fee = 1 if resolution_key in {"1080p", "2k", "4k"} else 0
        audio_fee = 1 if audio else 0
        final_cost = (base_price + resolution_fee + audio_fee) * duration

    return final_cost, resolved_channel_id


@router.post("/api/generate/image-estimate")
async def estimate_image_generation(
    req: ImageEstimateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del user, team
    normalized = normalize_image_request(
        {
            "model_code": req.model_code or req.channel,
            "mode": req.mode,
            "resolution": req.resolution,
            "quality": req.quality,
            "aspect_ratio": req.aspect_ratio,
            "reference_images": ["placeholder"] if req.has_reference_images else [],
            "prompt": "estimate",
        }
    )
    price = estimate_image_price(normalized["model_code"], normalized["generation_type"], normalized)

    return {
        "success": True,
        "estimate_points": int(price["sell_price_points"]),
        "currency_label": "灵感值",
        "resolved": {
            "mode_label": normalized["generation_type_label"],
            "model_label": normalized["model_name"],
            "quality": normalized.get("quality"),
            "quality_label": None
            if normalized["model_code"] == "gpt-image-2-fast"
            else " · ".join([part for part in [normalized.get("quality_label"), normalized["resolution"].upper()] if part]),
            "aspect_ratio_label": normalized["aspect_ratio"],
            "pricing_rule_type": price["pricing_rule_type"],
            "pricing_note": price["pricing_note"],
        },
        "notes": [],
    }


@router.post("/api/generate/video-estimate")
async def estimate_video_generation(
    req: VideoEstimateRequest,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    del user, team
    if _legacy_video_model_code(req.channel, req.duration):
        payload = _build_legacy_video_productized_payload(req=req)
        return estimate_productized_video_generation(session, payload)
    if req.duration < 1:
        raise HTTPException(status_code=400, detail="duration must be >= 1")
    if req.reference_image_count < 0 or req.reference_video_count < 0:
        raise HTTPException(status_code=400, detail="reference counts must be >= 0")

    cost_points, resolved_channel_id = _calculate_video_generation_cost(
        session=session,
        channel_id=req.channel,
        resolution=req.resolution,
        duration=req.duration,
        audio=bool(req.audio),
        reference_image_count=req.reference_image_count,
        reference_video_count=req.reference_video_count,
    )

    return {
        "success": True,
        "estimate_points": cost_points,
        "currency_label": "灵感值",
        "resolved": {
            "model_label": _resolve_public_video_model_label(resolved_channel_id, req.duration),
            "resolution_label": _format_public_video_resolution_label(req.resolution),
            "duration_label": _format_public_duration_label(req.duration),
            "aspect_ratio_label": req.aspect_ratio or "16:9",
        },
        "notes": [],
    }

'# =========================================='
'# =========================================='
'# 分镜管理页生成接口'
'# =========================================='
@router.post("/api/generate")
async def generate_panel(
    req: GenerateRequest, 
    background_tasks: BackgroundTasks, 
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session)
):
    real_panel_id = decode_id(req.panel_id)
    panel = require_panel_team_access(session, team, real_panel_id)
    hydrate_panel_storyboard_fields(panel)
    episode = require_episode_team_access(session, team, panel.episode_id)
    workflow_profile = _resolve_effective_image_workflow_profile(session, episode, panel)
    resolution_key = _resolve_panel_generation_resolution(panel, req.resolution, "1k")
    effective_prompt = _resolve_panel_generation_prompt(panel, req.prompt, aspect_ratio=req.aspectRatio or _get_panel_storyboard_aspect_ratio(panel))
    submit_prompt = augment_prompt_with_style(effective_prompt, workflow_profile, label_fallback="")
    reference_images = get_panel_reference_images(session, panel)
    if not submit_prompt:
        raise HTTPException(status_code=400, detail="褰撳墠鍒嗛暅缂哄皯鍙敤鐨勫浘鐗囨彁绀鸿瘝")
    if False and normalize_panel_type(panel.panel_type) == PANEL_TYPE_NINE_GRID:
        raise HTTPException(status_code=400, detail="褰撳墠鍒嗛暅绫诲瀷涓轰節瀹牸锛岃璧颁節瀹牸鐢熸垚妯″紡")
    cost_points = 1  # 鍏ㄨ兘鍥剧墖V2-鏂囩敓鍥惧畾浠?鐏垫劅鍊?
    cost_points = OFFICIAL_RESOLUTION_COSTS.get(resolution_key, OFFICIAL_RESOLUTION_COSTS["1k"])
    deduct_inspiration_points(user=user, team=team, cost=cost_points,
        action_type="generate_image_rh_v2",
        description=f"鍏ㄨ兘鍥剧墖V2-鏂囩敓鍥?1鐏垫劅鍊? 鈥?鍒嗛暅闀滃彿 {panel.sequence_num}",
        session=session)
    task_uuid = str(uuid.uuid4())
    panel.task_id = task_uuid
    panel.prompt = effective_prompt
    panel.status = TaskStatusEnum.PROCESSING
    session.add(panel)
    session.commit()

    dispatch_runninghub_task_v2(
        panel.id,
        task_uuid,
        SimpleNamespace(
            channel="rh-v2-official-img2img" if reference_images else "rh-v2-official-text2img",
            prompt=submit_prompt,
            resolution=resolution_key,
            aspectRatio=str(workflow_profile.get("aspect_ratio") or _get_panel_storyboard_aspect_ratio(panel)),
            imageUrls=reference_images,
        ),
    )
    return {"task_id": task_uuid, "status": "processing", "msg": "宸叉墸闄?鐏垫劅鍊硷紝鍏ㄨ兘鍥剧墖V2姝ｅ湪鐢熸垚..."}

@router.post("/api/generate_img2img")
async def generate_img2img(
    req: Img2ImgRequest, 
    background_tasks: BackgroundTasks, 
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session)
):
    real_episode_id = decode_id(req.episode_id)
    require_episode_team_access(session, team, real_episode_id)
    episode = session.get(Episode, real_episode_id)
    cost_points = 5
    deduct_inspiration_points(user=user, team=team, cost=cost_points,
        action_type="generate_img2img_rh",
        description=f"RunningHub 鍥剧敓鍥?5鐏垫劅鍊? 鈥?鍓ч泦 ID {req.episode_id}",
        session=session)
    statement = select(Panel).where(Panel.episode_id == real_episode_id).order_by(Panel.sequence_num.desc())
    last_panel = session.exec(statement).first()
    next_seq = (last_panel.sequence_num + 1) if last_panel else 1
    task_uuid = str(uuid.uuid4())
    new_panel = Panel(episode_id=real_episode_id, sequence_num=next_seq,
        panel_type="normal", task_id=task_uuid, prompt=req.prompt, status=TaskStatusEnum.PROCESSING)
    session.add(new_panel)
    session.commit()
    session.refresh(new_panel)
    background_tasks.add_task(poll_runninghub_img2img, new_panel.id, req.prompt, req.ref_images, req.ratio, req.resolution)
    return {"task_id": task_uuid, "status": "processing", "msg": "宸叉墸闄ょ伒鎰熷€硷紝鍥剧敓鍥句换鍔″惎鍔?.."}

    return {"task_id": task_uuid, "status": "processing", "msg": "宸叉墸闄ょ伒鎰熷€硷紝鍥剧敓鍥句换鍔″惎鍔?.."}

async def poll_video_task(backend_task_id: str, local_task_id: str, real_episode_id: int, channel_id: str):
    """
    閫氱敤瑙嗛浠诲姟杞
    """
    max_retries = 120 # 鍋囪鏈€澶?10 鍒嗛挓 (120*5 = 600)
    for _ in range(max_retries):
        await asyncio.sleep(8)
        try:
            if channel_id.startswith("suchuang"):
                resp = await suchuang_video_service.query_task(backend_task_id)
                code = resp.get("code")
                data = resp.get("data", {})
                # SuChuang 任务详情：status=2 表示成功，status=3 表示失败
                status = data.get("status")
                
                if code == 200 and status == 2:
                    video_url = data.get("url") or data.get("videoUrl")
                    if not video_url:
                        continue # Still processing or malformed
                    thumbnail_url = build_oss_video_snapshot_url(video_url)
                    video_tasks.update(local_task_id, status="completed", url=video_url)
                    
                    with Session(engine) as session:
                        panel = session.exec(select(Panel).where(Panel.task_id == local_task_id)).first()
                        if panel:
                            previous_video_url = str(panel.video_url or "").strip()
                            panel.video_history_json = upsert_panel_video_history(
                                panel.video_history_json,
                                preview_url=video_url,
                                thumbnail_url=thumbnail_url,
                                replace_url=previous_video_url,
                            )
                            panel.video_url = video_url
                            panel.video_thumbnail_url = thumbnail_url or None
                            panel.status = TaskStatusEnum.COMPLETED
                            session.add(panel)
                            session.commit()
                            
                            from services.oss_service import _async_upload_video_to_oss
                            if panel.video_url:
                                threading.Thread(target=_async_upload_video_to_oss, args=(panel.id, panel.video_url), daemon=True).start()
                    return
                elif code in (200, 2):
                    continue
                else:
                    video_tasks.update(local_task_id, status="failed")
                    return
            
            elif channel_id.startswith("runninghub"):
                resp = await runninghub_video_service.query_task(backend_task_id)
                status = resp.get("status")
                if status == "SUCCESS":
                    results = resp.get("results", [])
                    final_url = results[0]["url"] if results else ""
                    thumbnail_url = build_oss_video_snapshot_url(final_url)
                    video_tasks.update(local_task_id, status="completed", url=final_url)
                    
                    with Session(engine) as session:
                        panel = session.exec(select(Panel).where(Panel.task_id == local_task_id)).first()
                        if panel:
                            previous_video_url = str(panel.video_url or "").strip()
                            panel.video_history_json = upsert_panel_video_history(
                                panel.video_history_json,
                                preview_url=final_url,
                                thumbnail_url=thumbnail_url,
                                replace_url=previous_video_url,
                            )
                            panel.video_url = final_url
                            panel.video_thumbnail_url = thumbnail_url or None
                            panel.status = TaskStatusEnum.COMPLETED
                            session.add(panel)
                            session.commit()
                            
                            import threading
                            from services.oss_service import _async_upload_video_to_oss
                            if final_url:
                                threading.Thread(target=_async_upload_video_to_oss, args=(panel.id, final_url), daemon=True).start()
                    return
                elif status in ("RUNNING", "QUEUED"):
                    continue
                else:
                    video_tasks.update(local_task_id, status="failed")
                    return
                    
        except Exception as e:
            print(f"Polling error for video task {local_task_id}: {e}")
            continue

    video_tasks.update(local_task_id, status="failed")


def _build_runninghub_image_refs(req: GenerateVideoRequest) -> List[str]:
    refs: List[str] = []
    if req.reference_images:
        refs.extend([u for u in req.reference_images if u])
    else:
        if req.start_frame:
            refs.append(req.start_frame)
        if req.end_frame:
            refs.append(req.end_frame)
    if not refs and req.image_url:
        refs.append(req.image_url)
    deduped: List[str] = []
    seen = set()
    for u in refs:
        if u and u not in seen:
            deduped.append(u)
            seen.add(u)
    return deduped

VIDU_PRICING = {
    "540p": {1: 7, 2: 8, 3: 9, 4: 10, 5: 11, 6: 12, 7: 13, 8: 14, 9: 15, 10: 16},
    "720p": {1: 9, 2: 10, 3: 11, 4: 12, 5: 13, 6: 14, 7: 15, 8: 16, 9: 18, 10: 19},
    "1080p": {1: 21, 2: 23, 3: 26, 4: 28, 5: 30, 6: 32, 7: 34, 8: 36, 9: 39, 10: 41},
}

@router.post("/api/generate_video")
async def generate_video(
    req: GenerateVideoRequest,
    background_tasks: BackgroundTasks, 
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session)
):
    # 神鹿视频虚拟引擎重写逻辑
    virtual_id = req.channel_id
    real_channel_id = virtual_id # 榛樿涓哄師鏍?
    
    if virtual_id in ("shenlu-storyboard-fast", "suchuang-veo3.1-fast"):
        raise HTTPException(status_code=400, detail="娓叉煋寮曟搸 shenlu-storyboard-fast 宸蹭笅绾匡紝璇蜂娇鐢ㄥ叾浠栬棰戦€氶亾")
    elif virtual_id == "shenlu-physics-engine":
        # 影视级物理引擎：根据时长自动路由 Q2 / Q3
        if req.duration > 10:
            real_channel_id = "runninghub-vidu-q3-pro"
        else:
            real_channel_id = "runninghub-vidu-q2-pro"
    elif virtual_id == "shenlu-neu-character":
        real_channel_id = "suchuang-digital-human"

    channel = session.exec(select(ChannelSettings).where(ChannelSettings.channel_id == real_channel_id)).first()
    if not channel or not channel.is_active:
        raise HTTPException(status_code=400, detail=f"所选视频生成引擎 {virtual_id} 当前不可用")

    real_episode_id = decode_id(req.episode_id)
    require_episode_team_access(session, team, real_episode_id)

    productized_model_code = _legacy_video_model_code(virtual_id, req.duration)
    if productized_model_code:
        episode = session.get(Episode, real_episode_id)
        if not episode:
            raise HTTPException(status_code=404, detail="剧集不存在")

        target_panel = None
        if req.panel_id:
            real_panel_id = decode_id(req.panel_id)
            target_panel = require_panel_team_access(session, team, real_panel_id)
        else:
            statement = select(Panel).where(Panel.episode_id == real_episode_id).order_by(Panel.sequence_num.desc())
            last_panel = session.exec(statement).first()
            next_seq = (last_panel.sequence_num + 1) if last_panel else 1
            target_panel = Panel(
                episode_id=real_episode_id,
                sequence_num=next_seq,
                panel_type="normal",
                video_prompt=req.prompt,
                status=TaskStatusEnum.PROCESSING,
            )
            session.add(target_panel)
            session.commit()
            session.refresh(target_panel)

        productized_payload = _build_legacy_video_productized_payload(
            req=req,
            project_id=encode_id(episode.script_id),
            episode_id=req.episode_id,
            target_type="panel",
            target_id=encode_id(target_panel.id),
        )
        record = submit_productized_video_generation(
            session,
            background_tasks=background_tasks,
            user=user,
            team=team,
            payload=productized_payload,
        )
        target_panel.video_prompt = req.prompt
        target_panel.status = TaskStatusEnum.PROCESSING
        target_panel.task_id = str(record.task_id)
        session.add(target_panel)
        session.commit()
        return {"task_id": str(record.task_id), "status": "processing", "msg": "视频任务已提交，正在生成中"}

    # 根据参考图、参考视频、分辨率和音频动态计算价格
    image_refs = _build_runninghub_image_refs(req)
    video_refs = [u for u in (req.reference_videos or []) if u]

    # 特殊定价：Vidu Q2 多参考图或参考视频模式
    if real_channel_id == "runninghub-vidu-q2-pro" and (len(image_refs) > 1 or len(video_refs) > 0):
        res_key = req.resolution.lower()
        dur_key = req.duration
        table = VIDU_PRICING.get(res_key) or VIDU_PRICING.get("720p")
        final_cost = table.get(dur_key) or table.get(max(table.keys() if table else [1]))
    # 兼容旧逻辑的二次计算分支
    image_refs = _build_runninghub_image_refs(req)
    video_refs = [u for u in (req.reference_videos or []) if u]

    # 特殊定价：Vidu Q2 多参考图或参考视频模式
    if real_channel_id == "runninghub-vidu-q2-pro" and (len(image_refs) > 1 or len(video_refs) > 0):
        res_key = req.resolution.lower()
        dur_key = req.duration
        table = VIDU_PRICING.get(res_key) or VIDU_PRICING.get("720p")
        final_cost = table.get(dur_key) or table.get(max(table.keys() if table else [1]))
    else:
        base_price = channel.cost_points
        res_fee = 1 if req.resolution in ["1080p", "2k", "4k"] else 0
        audio_fee = 1 if req.audio else 0
        final_cost = (base_price + res_fee + audio_fee) * req.duration
    
    deduct_inspiration_points(user=user, team=team, cost=final_cost,
        action_type="generate_video",
        description=f"视频生成任务({virtual_id}, {req.resolution}, {req.duration}秒) 消耗 {final_cost}灵感值",
        session=session)

    # 入库占位
    task_uuid = str(uuid.uuid4())
    if req.panel_id:
        real_panel_id = decode_id(req.panel_id)
        new_panel = require_panel_team_access(session, team, real_panel_id)
        new_panel.video_prompt = req.prompt
        new_panel.task_id = task_uuid
        new_panel.status = TaskStatusEnum.PROCESSING
        session.add(new_panel)
        session.commit()
    else:
        statement = select(Panel).where(Panel.episode_id == real_episode_id).order_by(Panel.sequence_num.desc())
        last_panel = session.exec(statement).first()
        next_seq = (last_panel.sequence_num + 1) if last_panel else 1
        new_panel = Panel(episode_id=real_episode_id, sequence_num=next_seq,
            panel_type="normal", task_id=task_uuid, video_prompt=req.prompt, status=TaskStatusEnum.PROCESSING)
        session.add(new_panel)
        session.commit()

    record = _create_generation_record(
        session,
        user=user,
        team=team,
        record_type="video",
        ownership_mode="project",
        script_id=episode.script_id if episode else None,
        episode_id=real_episode_id,
        target_type="panel",
        target_id=new_panel.id,
        prompt=req.prompt,
        negative_prompt=None,
        params_internal={
            "legacy_video": True,
            "channel_id": real_channel_id,
            "start_frame": req.start_frame,
            "end_frame": req.end_frame,
            "image_url": req.image_url,
            "reference_images": image_refs,
            "reference_videos": video_refs,
            "duration": req.duration,
            "resolution": req.resolution,
            "audio": bool(req.audio),
            "aspect_ratio": getattr(req, "aspect_ratio", None) or "16:9",
            "movement_amplitude": getattr(req, "movement_amplitude", None) or "auto",
            "audio_url": req.audio_url,
        },
        params_public={
            "model": real_channel_id,
            "resolution": req.resolution,
            "duration": req.duration,
            "prompt_summary": str(req.prompt or "")[:42],
            "source": "webui",
        },
        estimate_points=final_cost,
    )
    record.task_id = task_uuid
    session.add(record)
    session.commit()
    job = create_task_job(
        session,
        task_id=task_uuid,
        task_type="media.generate_video",
        queue_name="media",
        provider=real_channel_id,
        team_id=team.id,
        user_id=user.id,
        script_id=episode.script_id if episode else None,
        episode_id=real_episode_id,
        ownership_mode="project",
        scope_type="panel",
        scope_id=new_panel.id,
        task_category="media",
        generation_record_id=record.id,
        payload={
            "kind": "legacy_video",
            "record_id": record.id,
            "panel_id": new_panel.id,
            "channel_id": real_channel_id,
            "prompt": req.prompt,
            "start_frame": req.start_frame,
            "end_frame": req.end_frame,
            "image_url": req.image_url,
            "reference_images": image_refs,
            "reference_videos": video_refs,
            "duration": req.duration,
            "resolution": req.resolution,
            "audio": bool(req.audio),
            "aspect_ratio": getattr(req, "aspect_ratio", None) or "16:9",
            "movement_amplitude": getattr(req, "movement_amplitude", None) or "auto",
            "audio_url": req.audio_url,
        },
        message="视频任务已提交",
        max_retries=2,
    )
    enqueue_task_job(job)
    return {"task_id": task_uuid, "status": "processing", "msg": "视频任务已提交，正在生成中"}

    try:
        # 统一处理首帧逻辑：优先使用 image_url / start_frame
        first_frame = req.start_frame or req.image_url
        
        # 处理 Base64 音频：如以前端 data:audio 开头，则先转存 OSS 再交给第三方 API
        audio_url = req.audio_url
        if audio_url and audio_url.startswith("data:audio/"):
            import base64
            from io import BytesIO
            try:
                # data:audio/wav;base64,xxxx
                header, encoded = audio_url.split(",", 1)
                ext = header.split(";")[0].split("/")[1]
                audio_bytes = base64.b64decode(encoded)
                # 临时上传 OSS
                audio_url = upload_bytes_to_oss(audio_bytes, f"temp_audio_{int(time.time())}.{ext}")
            except Exception as ae:
                print(f"Base64 闊抽瑙ｆ瀽鎴栦笂浼犲け璐? {ae}")
                # 失败时保留原始值，第三方接口会自行报错

        if real_channel_id == "suchuang-veo3.1-pro":
            resp = await suchuang_video_service.generate_veo3_1_pro(
                prompt=req.prompt, first_frame_url=first_frame, 
                last_frame_url=req.end_frame, size=req.resolution
            )
            backend_task_id = resp["data"]["id"]
        elif real_channel_id == "suchuang-digital-human":
            # 数字人模式：需要人物视频或首帧地址，以及音频地址
            if not first_frame or not audio_url:
                raise HTTPException(status_code=400, detail="鏁板瓧浜轰换鍔″繀椤绘彁渚涜棰戝湴鍧€鍜岄煶棰戝湴鍧€")
            resp = await suchuang_video_service.generate_digital_human(
                video_name=f"dh_{int(time.time())}", video_url=first_frame, audio_url=audio_url
            )
            backend_task_id = resp["data"]["id"]
        elif real_channel_id == "runninghub-vidu-q3-pro":
            if len(image_refs) > 1 or len(video_refs) > 0:
                raise HTTPException(
                    status_code=400,
                    detail="runninghub-vidu-q3-pro 褰撳墠浠呭紑鏀惧崟鍥剧敓瑙嗛锛屼笉鏀寔棣栧熬甯?澶氬抚鍙傝€?鍙傝€冭棰戯紝璇锋敼鐢?Vidu Q2 Pro"
                )
            resp = await runninghub_video_service.generate_vidu_q3_pro(
                prompt=req.prompt, image_urls=image_refs, 
                duration=str(req.duration), resolution=req.resolution, audio=req.audio
            )
            backend_task_id = resp.get("taskId")
        elif real_channel_id == "runninghub-vidu-q2-pro":
            resp = await runninghub_video_service.generate_vidu_q2_pro(
                prompt=req.prompt, image_urls=image_refs, video_urls=video_refs,
                duration=str(req.duration), resolution=req.resolution, bgm=req.audio,
                aspect_ratio=req.aspect_ratio, movement_amplitude=req.movement_amplitude
            )
            backend_task_id = resp.get("taskId")
        elif real_channel_id == "runninghub-vidu-q2-pro":
            resp = await runninghub_video_service.generate_vidu_q2_pro(
                prompt=req.prompt, image_urls=[first_frame] if first_frame else [], 
                duration=str(req.duration), resolution=req.resolution, bgm=req.audio
            )
            backend_task_id = resp.get("taskId")
        else:
            raise HTTPException(status_code=400, detail=f"视频生成引擎内核 {real_channel_id} 当前不可用")

        if not backend_task_id:
            raise Exception("娓叉煋寮曟搸鍐呮牳鏈繑鍥炴湁鏁堢殑浠诲姟 ID")

    except Exception as e:
        new_panel.status = TaskStatusEnum.FAILED
        session.add(new_panel)
        session.commit()
        raise HTTPException(status_code=500, detail=f"娓叉煋浠诲姟鍒嗘祦澶辫触: {str(e)}")

    video_tasks.create(
        task_uuid,
        status="processing",
        url="",
        progress=0,
        error="",
        script_id=episode.script_id if episode else None,
        episode_id=real_episode_id,
        user_id=user.id,
        kind="video",
        source="webui",
        title="视频生成",
        summary=(req.prompt or "").strip()[:60],
    )
    background_tasks.add_task(poll_video_task, backend_task_id, task_uuid, real_episode_id, real_channel_id)
    return {"task_id": task_uuid, "status": "processing", "msg": "视频任务已提交，正在生成中"}

@router.get("/api/video_status/{task_id}")
async def check_video_status(task_id: str, user: User = Depends(get_current_user)):
    job = get_task_job(task_id)
    if job:
        data = serialize_task_job(job)
        result = data.get("result") or {}
        return {
            "status": data.get("legacy_status"),
            "url": result.get("preview_url") or "",
            "thumbnail_url": result.get("thumbnail_url") or "",
        }
    try:
        with Session(engine) as session:
            record = get_generation_record_detail(session, user=user, record_id=task_id)
        if record.get("type") == "video":
            status_map = {
                "queued": "processing",
                "processing": "processing",
                "completed": "completed",
                "failed": "failed",
            }
            return {
                "status": status_map.get(record.get("status"), record.get("status") or "not_found"),
                "url": record.get("preview_url") or "",
                "thumbnail_url": record.get("thumbnail_url") or "",
            }
    except Exception:
        pass
    task = video_tasks.get(task_id)
    if not task:
        return {"status": "not_found"}
    result = {"status": task["status"], "url": task.get("url", "")}
    if task["status"] in ("completed", "failed"):
        video_tasks.pop(task_id)
    return result

# ==========================================
# V1 Nano Banana 独立接口
# ==========================================
@router.post("/api/generate_nano")
async def generate_nano(
    req: NanoBananaRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session)
):
    cost_points = NANO_MODEL_COSTS.get(req.model, 5)
    deduct_inspiration_points(user=user, team=team, cost=cost_points,
        action_type="generate_nano",
        description=f"画布生成({req.model}) 消耗 {cost_points} 灵感值",
        session=session)
    session.commit()
    
    try:
        resp = requests.post(
            settings.NANO_API_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"},
            json={"model": req.model, "prompt": req.prompt,
                  "aspectRatio": req.aspectRatio, "imageSize": req.imageSize,
                  "urls": req.urls, "webHook": "-1"},
            timeout=30
        )
        resp_data = resp.json()
        nano_task_id = resp_data.get("data", {}).get("id", "")
        if not nano_task_id:
            raise HTTPException(status_code=500, detail=f"Nano API 鏈繑鍥炰换鍔?ID: {resp_data}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"鎻愪氦 Nano 浠诲姟澶辫触: {str(e)}")
    
    our_task_id = f"nano-{uuid.uuid4().hex[:12]}"
    real_episode_id = decode_id(req.episode_id)
    require_episode_team_access(session, team, real_episode_id)
    episode = session.get(Episode, real_episode_id)
    nano_tasks.create(
        our_task_id,
        status="processing",
        url="",
        progress=0,
        error="",
        script_id=episode.script_id if episode else None,
        episode_id=real_episode_id,
        user_id=user.id,
        kind="image",
        source="webui",
        title="画布图片生成",
        summary=(req.prompt or "").strip()[:60],
    )
    background_tasks.add_task(poll_nano_task_v1, nano_task_id, our_task_id, real_episode_id, req.prompt)
    return {"task_id": our_task_id, "status": "processing", "msg": f"已扣除 {cost_points} 灵感值，正在生成中..."}

@router.get("/api/nano_status/{task_id}")
async def check_nano_status(task_id: str, user: User = Depends(get_current_user)):
    task = nano_tasks.get(task_id)
    if not task:
        return {"status": "not_found"}
    result = {"status": task["status"], "url": task.get("url", ""), "progress": task.get("progress", 0)}
    if task["status"] in ("completed", "failed"):
        nano_tasks.pop(task_id)
    return result

# ==========================================
# 独立资源参考图生成 (Asset Reference Image)
# ==========================================
@router.post("/api/generate_standalone_image")
async def generate_standalone_image(
    req: GenerateAssetImageRequest,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session)
):
    cost_points = 5  # 鍥哄畾鎵ｈ垂
    deduct_inspiration_points(user=user, team=team, cost=cost_points,
        action_type="generate_asset_image",
        description=f"生成资产参考图({req.channel}) 消耗 {cost_points} 灵感值",
        session=session)
    session.commit()
    
    try:
        resp = requests.post(
            settings.NANO_API_URL,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"},
            json={"model": req.channel, "prompt": req.prompt,
                  "aspectRatio": req.aspectRatio, "imageSize": "1K",
                  "urls": [], "webHook": "-1"},
            timeout=30
        )
        resp_data = resp.json()
        nano_task_id = resp_data.get("data", {}).get("id", "")
        if not nano_task_id:
            raise HTTPException(status_code=500, detail=f"Nano API 鏈繑鍥炰换鍔?ID: {resp_data}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"鎻愪氦鐢熸垚浠诲姟澶辫触: {str(e)}")
    
    our_task_id = f"standalone-{uuid.uuid4().hex[:8]}"
    
    standalone_tasks.create(
        our_task_id,
        status="processing",
        url="",
        error="",
        user_id=user.id,
        kind="asset",
        source="webui",
        title="资产参考图生成",
        summary=(req.prompt or "").strip()[:60],
    )
    background_tasks.add_task(poll_standalone_task, nano_task_id, our_task_id)
    return {"task_id": our_task_id, "status": "processing", "msg": f"已扣除 {cost_points} 灵感值，正在生成参考图..."}

@router.get("/api/standalone_status/{task_id}")
async def check_standalone_status(task_id: str, user: User = Depends(get_current_user)):
    task = standalone_tasks.get(task_id)
    if not task:
        return {"status": "not_found"}
    result = {"status": task["status"], "url": task.get("url", ""), "error": task.get("error", "")}
    if task["status"] in ("completed", "failed"):
        standalone_tasks.pop(task_id)
    return result

# ==========================================
# 局部更新分镜信息接口（用于无感自动保存）
# ==========================================
@router.patch("/api/panels/{panel_id}")
async def update_panel_partial(
    panel_id: str,
    update_data: dict,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session)
):
    real_panel_id = decode_id(panel_id)
    panel = require_panel_team_access(session, team, real_panel_id)
    episode = session.get(Episode, panel.episode_id)
    
    # 支持局部更新的白名单字段
    allowed_fields = [
        "panel_type",
        "storyboard_mode",
        "prompt",
        "prompt_zh",
        "scene",
        "character",
        "prop",
        "image_framing",
        "video_prompt",
        "nine_grid_prompt",
        "entity_bindings_json",
        "original_text",
        "narration_text",
        "dialogue_text",
        "segment_break",
        "shot_type",
        "camera_motion",
        "composition",
        "previous_storyboard_path",
        "transition_to_next",
    ]
    dependency_related_fields = {
        "storyboard_mode",
        "segment_break",
        "narration_text",
        "dialogue_text",
        "original_text",
        "shot_type",
        "camera_motion",
        "composition",
        "previous_storyboard_path",
        "transition_to_next",
        "image_framing",
    }
    touched_fields = set()

    for key, value in update_data.items():
        if key in allowed_fields:
            if key == "panel_type":
                value = normalize_panel_type(value)
            if key == "segment_break":
                value = bool(value)
            setattr(panel, key, value)
            touched_fields.add(key)

    if episode:
        hydrate_panel_storyboard_fields(panel, fallback_mode=episode.storyboard_mode)
    if touched_fields:
        panel.updated_at = datetime.utcnow()
    session.add(panel)
    if touched_fields & dependency_related_fields:
        recompute_episode_dependencies(session, panel.episode_id)
    session.commit()
    session.refresh(panel)
    return {"status": "success", "msg": "鏇存柊鎴愬姛", "panel_id": panel.id}

# ==========================================
# V2 多通道图片生成网关
# ==========================================
@router.post("/api/episodes/{episode_id}/generate_image_v2")
async def generate_image_v2(
    episode_id: str,
    req: GenerateImageV2Request,
    background_tasks: BackgroundTasks,
    _: TeamMemberLink = Depends(require_team_permission("generate:run")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session)
):
    real_episode_id = decode_id(episode_id)
    episode = require_episode_team_access(session, team, real_episode_id)
    workflow_profile = _resolve_effective_image_workflow_profile(session, episode)

    reference_images = list(req.imageUrls or [])
    panel_for_mode: Optional[Panel] = None
    storyboard_mode = getattr(episode, "storyboard_mode", STORYBOARD_MODE_COMMENTARY)
    if req.panel_id:
        panel_for_mode = require_panel_team_access(session, team, decode_id(req.panel_id))
        hydrate_panel_storyboard_fields(panel_for_mode, fallback_mode=storyboard_mode)
        storyboard_mode = getattr(panel_for_mode, "storyboard_mode", storyboard_mode)
        workflow_profile = _resolve_effective_image_workflow_profile(session, episode, panel_for_mode)
        req.aspectRatio = _resolve_storyboard_aspect_ratio(
            req.aspectRatio or str(workflow_profile.get("aspect_ratio") or ""),
            storyboard_mode,
        )
        req.resolution = _resolve_panel_generation_resolution(panel_for_mode, req.resolution, req.resolution or "2k")
        req.prompt = _resolve_panel_generation_prompt(panel_for_mode, req.prompt, aspect_ratio=req.aspectRatio)
        reference_images = _merge_reference_images(get_panel_reference_images(session, panel_for_mode), reference_images)
    else:
        req.aspectRatio = _resolve_storyboard_aspect_ratio(
            req.aspectRatio or str(workflow_profile.get("aspect_ratio") or ""),
            storyboard_mode,
        )
    req.imageUrls = reference_images
    submit_prompt = augment_prompt_with_style(req.prompt, workflow_profile, label_fallback="")
    requested_model_code = normalize_image_model_code(
        req.model_code or req.channel or ((workflow_profile.get("image") or {}).get("model_code")) or "nano-banana-pro"
    )
    normalized_request = normalize_image_request(
        {
            "model_code": requested_model_code,
            "mode": "image_to_image" if reference_images else "text_to_image",
            "prompt": submit_prompt,
            "resolution": req.resolution,
            "quality": req.quality or ((workflow_profile.get("image") or {}).get("quality")),
            "aspect_ratio": req.aspectRatio,
            "reference_images": reference_images,
        }
    )
    price = estimate_image_price(normalized_request["model_code"], normalized_request["generation_type"], normalized_request)
    cost_points = int(price["sell_price_points"])

    deduct_inspiration_points(
        user=user,
        team=team,
        cost=cost_points,
        action_type="generate_image",
        description=f"图片生成任务({normalized_request['model_name']} {normalized_request['resolution']}) 消耗 {cost_points} 灵感值",
        session=session,
    )

    our_task_id = f"v2-image-{uuid.uuid4().hex[:10]}"
    
    if req.panel_id:
        real_panel_id = decode_id(req.panel_id)
        panel_to_update = panel_for_mode or require_panel_team_access(session, team, real_panel_id)
        panel_to_update.prompt = _resolve_panel_generation_prompt(panel_to_update, req.prompt, aspect_ratio=req.aspectRatio)
        if req.prompt_zh is not None:
            panel_to_update.prompt_zh = req.prompt_zh
        panel_to_update.task_id = our_task_id
        panel_to_update.status = TaskStatusEnum.PROCESSING
        panel_to_update.updated_at = datetime.utcnow()
        session.add(panel_to_update)
        session.commit()
        session.refresh(panel_to_update)
        new_panel = panel_to_update
    else:
        last_panel = session.exec(
            select(Panel).where(Panel.episode_id == real_episode_id)
            .order_by(Panel.sequence_num.desc())
        ).first()
        next_seq = (last_panel.sequence_num + 1) if last_panel else 1
        
        new_panel = Panel(episode_id=real_episode_id, sequence_num=next_seq,
            panel_type="normal",
            storyboard_mode=storyboard_mode,
            task_id=our_task_id,
            prompt=req.prompt,
            prompt_zh=req.prompt_zh,
            status=TaskStatusEnum.PROCESSING,
            updated_at=datetime.utcnow())
        session.add(new_panel)
        session.commit()
        session.refresh(new_panel)
        
        if req.insert_at is not None:
            _handle_panel_insertion(real_episode_id, new_panel.id, req.insert_at)
    
    # 根据实际通道分发到具体 provider
    record = _create_generation_record(
        session,
        user=user,
        team=team,
        record_type="image",
        ownership_mode="project",
        script_id=episode.script_id,
        episode_id=real_episode_id,
        target_type="panel",
        target_id=new_panel.id,
        prompt=req.prompt,
        negative_prompt=None,
        params_internal={
            "legacy_image_v2": True,
            "internal_model": normalized_request["model_code"],
            "model_code": normalized_request["model_code"],
            "generation_type": normalized_request["generation_type"],
            "resolution": normalized_request["resolution"],
            "quality": normalized_request.get("quality"),
            "aspect_ratio": normalized_request["aspect_ratio"],
            "image_urls": list(normalized_request["reference_images"]),
            "request_payload": {
                "model_code": normalized_request["model_code"],
                "mode": normalized_request["generation_type"],
                "generation_type": normalized_request["generation_type"],
                "resolution": normalized_request["resolution"],
                "quality": normalized_request.get("quality"),
                "aspect_ratio": normalized_request["aspect_ratio"],
                "reference_images": list(normalized_request["reference_images"]),
                "prompt": submit_prompt,
            },
            "panel_id": new_panel.id,
        },
        params_public={
            "model_code": normalized_request["model_code"],
            "model": normalized_request["model_code"],
            "model_label": normalized_request["model_name"],
            "generation_type": normalized_request["generation_type"],
            "generation_type_label": normalized_request["generation_type_label"],
            "resolution": normalized_request["resolution"],
            "quality": normalized_request.get("quality"),
            "quality_mode": normalized_request.get("quality"),
            "quality_mode_label": normalized_request.get("quality_label"),
            "quality_label": None
            if normalized_request["model_code"] == "gpt-image-2-fast"
            else " · ".join([part for part in [normalized_request.get("quality_label"), normalized_request["resolution"].upper()] if part]),
            "aspect_ratio": normalized_request["aspect_ratio"],
            "aspect_ratio_label": normalized_request["aspect_ratio"],
            "pricing_rule_type": price["pricing_rule_type"],
            "pricing_note": price["pricing_note"],
            "pricing_details": price["pricing_details"],
            "prompt_summary": str(req.prompt or "")[:42],
            "source": "webui",
        },
        estimate_points=cost_points,
    )
    record.task_id = our_task_id
    session.add(record)
    session.commit()
    job = create_task_job(
        session,
        task_id=our_task_id,
        task_type="media.generate_image",
        queue_name="media",
        provider=normalized_request["model_code"],
        team_id=team.id,
        user_id=user.id,
        script_id=episode.script_id if episode else None,
        episode_id=real_episode_id,
        ownership_mode="project",
        scope_type="panel",
        scope_id=new_panel.id,
        task_category="media",
        generation_record_id=record.id,
        payload={
            "kind": "legacy_image_v2",
            "record_id": record.id,
            "panel_id": new_panel.id,
            "model_code": normalized_request["model_code"],
            "mode": normalized_request["generation_type"],
            "prompt": submit_prompt,
            "resolution": normalized_request["resolution"],
            "quality": normalized_request.get("quality"),
            "aspect_ratio": normalized_request["aspect_ratio"],
            "image_urls": list(normalized_request["reference_images"]),
        },
        message="图片生成任务已提交",
        max_retries=2,
    )
    enqueue_task_job(job)
    return {"task_id": our_task_id, "status": "processing", "panel_id": new_panel.id, "msg": f"任务已提交，消耗了 {cost_points} 灵感值"}

def _handle_panel_insertion(episode_id: int, new_panel_id: int, insert_at: int):
    from database import engine
    from sqlmodel import Session as S
    with S(engine) as s:
        statement = select(Panel).where(Panel.episode_id == episode_id).order_by(Panel.sequence_num.asc())
        panels = s.exec(statement).all()
        target_panel = next((p for p in panels if p.id == new_panel_id), None)
        if target_panel:
            panels.remove(target_panel)
            insert_idx = max(0, min(insert_at - 1, len(panels)))
            panels.insert(insert_idx, target_panel)
            for idx, p in enumerate(panels):
                p.sequence_num = idx + 1
                s.add(p)
            recompute_episode_dependencies(s, episode_id)
            s.commit()

