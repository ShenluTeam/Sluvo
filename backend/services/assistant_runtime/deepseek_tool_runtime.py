from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks, HTTPException
from sqlmodel import select

from core.config import settings
from core.security import encode_id
from models import AssistantSession, Episode, GenerationRecord, Panel, Script, SharedResource, Team, User
from services.agent_stage_service import ACTIVE_AGENT_LABELS, CREATIVE_STAGE_LABELS, STAGE_AGENT_MAP, build_creative_stage_read_model
from services.agents.asset_planner_agent import AssetPlannerAgent
from services.agents.director_agent import DirectorAgent
from services.agents.generation_agent import GenerationAgent
from services.agents.llm_client import chat_json_with_tools
from services.agents.prompt_rewrite_agent import PromptRewriteAgent
from services.agents.router import build_agent_context
from services.agents.storyboard_agent import StoryboardAgent
from services.audio_model_registry import ABILITY_NARRATION, ABILITY_REALTIME, VOICE_SOURCE_SYSTEM
from services.deepseek_hybrid_router import estimate_text_tokens, extract_user_intent_flags, resolve_deepseek_agent_route
from services.generation_record_service import _run_audio_async_job, list_voice_assets, submit_audio_generation
from services.resource_extraction_service import extract_script_assets_structured, sync_structured_assets_into_shared_resources
from services.resource_task_service import ResourceExtractionBillingTracker
from services.assistant_runtime.tool_display_registry import build_tool_card
from services.workflow_preset_service import (
    build_style_prompt,
    get_style_display_label,
    resolve_asset_extraction_storyboard_mode,
    resolve_effective_workflow_profile,
)


TOOL_LOOP_ASSISTANT_NAME = "tool_loop_assistant"
TOOL_LOOP_ASSISTANT_LABEL = "神鹿助手"
TOOL_LOOP_MAX_STEPS = 8

TOOL_NAME_TO_ACTION_TYPE = {
    "save_script": "save_script",
    "rewrite_script": "rewrite_script",
    "extract_assets": "extract_assets",
    "save_assets": "save_assets",
    "save_storyboard": "save_storyboard",
    "generate_asset_images": "generate_asset_images",
    "generate_storyboard_images": "generate_storyboard_images",
    "generate_video": "generate_video",
    "rewrite_generation_prompts": "rewrite_generation_prompts",
}

SKILL_HINT_TO_TOOL_NAME = {
    "split_episode_source": "extract_storyboard",
    "extract_project_assets": "extract_assets",
    "extract_assets": "extract_assets",
    "parse_story_segments": "extract_storyboard",
    "parse_storyboard_draft": "extract_storyboard",
    "generate_panel_image": "generate_storyboard_images",
    "generate_panel_video": "generate_video",
    "rewrite_generation_prompts": "rewrite_generation_prompts",
    "generate_episode_dubbing": "generate_audio",
}

EXPLICIT_TOOL_PATTERNS: List[tuple[str, List[re.Pattern[str]]]] = [
    (
        "rewrite_generation_prompts",
        [
            re.compile(r"(改写|修改|优化|调整|重写).{0,8}(提示词|prompt)", re.IGNORECASE),
            re.compile(r"(第?\s*\d+\s*(镜|分镜).{0,16}(改成|变成|换成|调成|更|加强))", re.IGNORECASE),
            re.compile(r"(更电影感|更可爱|更稳定|镜头更稳|改成雨夜|改成夜景)", re.IGNORECASE),
        ],
    ),
    (
        "generate_storyboard_images",
        [
            re.compile(r"(生成|做|出).{0,8}(分镜|镜头).{0,4}(图|图片|配图|图像)", re.IGNORECASE),
            re.compile(r"(分镜|镜头).{0,8}(出图|生图|图片|配图|图像)", re.IGNORECASE),
        ],
    ),
    (
        "generate_video",
        [
            re.compile(r"(生成|做|出|转成).{0,8}(视频|短片|动画)", re.IGNORECASE),
            re.compile(r"(分镜|镜头).{0,12}(视频|动起来)", re.IGNORECASE),
        ],
    ),
    (
        "generate_audio",
        [
            re.compile(r"(配音|旁白|朗读|生成音频|生成语音|做配音)", re.IGNORECASE),
        ],
    ),
    (
        "extract_assets",
        [
            re.compile(r"(提取|抽取|抽).{0,6}(资产|角色|场景|道具)", re.IGNORECASE),
        ],
    ),
    (
        "save_script",
        [
            re.compile(r"(保存|写入).{0,4}(剧本|原文)", re.IGNORECASE),
        ],
    ),
    (
        "rewrite_script",
        [
            re.compile(r"(改写|润色|重写|完善|续写).{0,6}(剧本|原文)?", re.IGNORECASE),
        ],
    ),
    (
        "save_storyboard",
        [
            re.compile(r"(保存|写入|生成).{0,6}(分镜板)", re.IGNORECASE),
            re.compile(r"(保存|写入).{0,6}(分镜)", re.IGNORECASE),
        ],
    ),
    (
        "extract_storyboard",
        [
            re.compile(r"(提取|拆分|拆|写|整理|规划).{0,6}(分镜|镜头)", re.IGNORECASE),
            re.compile(r"\bstoryboard\b", re.IGNORECASE),
        ],
    ),
]


def _utc_now() -> datetime:
    return datetime.utcnow()


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _asset_bundle_items(items: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not isinstance(items, list):
        return rows
    for item in items:
        if not isinstance(item, dict):
            continue
        name = _clean_text(item.get("name"))
        if not name:
            continue
        rows.append(
            {
                "name": name,
                "description": _clean_text(item.get("description") or item.get("role_identity")),
                "trigger_word": _clean_text(item.get("trigger_word")),
                "has_image": False,
            }
        )
    return rows


def _asset_bundle_from_structured_assets(structured_assets: Dict[str, Any]) -> Dict[str, Any]:
    characters = _asset_bundle_items((structured_assets or {}).get("characters"))
    scenes = _asset_bundle_items((structured_assets or {}).get("scenes"))
    props = _asset_bundle_items((structured_assets or {}).get("props"))
    return {
        "artifact_type": "asset_bundle",
        "characters": characters,
        "scenes": scenes,
        "props": props,
        "asset_summary": f"人物 {len(characters)} / 场景 {len(scenes)} / 道具 {len(props)}",
    }


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _tool_function(name: str, description: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


def build_internal_director_tools() -> List[Dict[str, Any]]:
    narrow_object = {"type": "object", "properties": {}, "additionalProperties": False}
    asset_item = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "trigger_word": {"type": "string"},
        },
        "required": ["name"],
        "additionalProperties": False,
    }
    return [
        _tool_function(
            "save_script",
            "保存当前剧本或原文草稿到项目。",
            {
                "type": "object",
                "properties": {
                    "script_draft": {"type": "string", "description": "要保存的剧本文本；留空则使用当前上下文中的剧本。"},
                },
                "additionalProperties": False,
            },
        ),
        _tool_function(
            "rewrite_script",
            "继续完善、润色或改写当前剧本。",
            {
                "type": "object",
                "properties": {
                    "script_draft": {"type": "string", "description": "可选的改写草稿。"},
                },
                "additionalProperties": False,
            },
        ),
        _tool_function("extract_assets", "从当前剧本提取角色、场景、道具资产。", narrow_object),
        _tool_function(
            "save_assets",
            "把结构化资产结果写入项目资产库。",
            {
                "type": "object",
                "properties": {
                    "structured_assets": {
                        "type": "object",
                        "properties": {
                            "characters": {"type": "array", "items": asset_item},
                            "scenes": {"type": "array", "items": asset_item},
                            "props": {"type": "array", "items": asset_item},
                        },
                        "additionalProperties": False,
                    },
                },
                "additionalProperties": False,
            },
        ),
        _tool_function(
            "extract_storyboard",
            "基于当前剧本和资产先生成剧情片段规划，确认后再正式拆分并写入工作区。",
            {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["plan_first", "split_confirmed"],
                        "description": "默认 plan_first：先生成剧情片段规划；用户确认后用 split_confirmed 正式拆分。",
                    },
                    "plan_revision_instruction": {
                        "type": "string",
                        "description": "用户对当前规划的修改意见，仅在 plan_first 调整规划时使用。",
                    },
                    "confirmed_plan_id": {
                        "type": "string",
                        "description": "用户确认的规划版本 id。",
                    },
                    "force_without_asset_images": {
                        "type": "boolean",
                        "description": "如果当前资产还没有参考图，是否仍然直接继续提取分镜。",
                    },
                },
                "additionalProperties": False,
            },
        ),
        _tool_function(
            "save_storyboard",
            "把已有分镜草稿写入分镜系统。",
            {
                "type": "object",
                "properties": {
                    "segment_draft": {"type": "array", "items": {"type": "object"}},
                    "storyboard_bundle": {"type": "object"},
                    "structured_storyboard": {"type": "object"},
                },
                "additionalProperties": False,
            },
        ),
        _tool_function(
            "generate_asset_images",
            "为资产库中的角色、场景或道具生成参考图。",
            {
                "type": "object",
                "properties": {
                    "generation_scope": {"type": "string", "enum": ["all", "character", "scene", "prop"]},
                    "resource_name": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _tool_function(
            "generate_storyboard_images",
            "为当前剧集分镜生成图片。",
            {
                "type": "object",
                "properties": {
                    "panel_sequence": {"type": "integer"},
                    "prompt": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _tool_function(
            "generate_video",
            "为当前剧集分镜生成视频。",
            {
                "type": "object",
                "properties": {
                    "panel_sequence": {"type": "integer"},
                    "prompt": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
        _tool_function(
            "rewrite_generation_prompts",
            "按用户要求改写当前分镜的标准图片/视频提示词，先输出预览，确认后再保存或生成。",
            {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["preview", "apply", "apply_and_generate", "cancel", "restore_last_generated"],
                        "description": "默认 preview；确认保存用 apply；保存并生成用 apply_and_generate。",
                    },
                    "target_kind": {"type": "string", "enum": ["image", "video", "both"]},
                    "scope": {"type": "string", "enum": ["current_panel", "selected_panels", "current_episode"]},
                    "panel_sequence": {"type": "integer"},
                    "selected_panel_sequences": {"type": "array", "items": {"type": "integer"}},
                    "rewrite_instruction": {"type": "string"},
                    "generate_after": {"type": "string", "enum": ["none", "image", "video", "both"]},
                    "rewrite_id": {"type": "string"},
                    "use_recommended_model": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        ),
        _tool_function(
            "generate_audio",
            "为当前剧集生成配音、旁白或音频。",
            {
                "type": "object",
                "properties": {
                    "voice_id": {"type": "string"},
                    "ability_type": {"type": "string", "enum": [ABILITY_REALTIME, ABILITY_NARRATION]},
                    "tier_code": {"type": "string", "enum": ["hd", "turbo"]},
                    "emotion": {"type": "string"},
                    "script_text": {"type": "string"},
                },
                "additionalProperties": False,
            },
        ),
    ]


def extract_explicit_tool_intent(text: str, *, skill_hint: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return None
    skill_id = str((skill_hint or {}).get("id") or "").strip()
    mapped_tool_name = SKILL_HINT_TO_TOOL_NAME.get(skill_id)
    if mapped_tool_name:
        return {
            "tool_name": mapped_tool_name,
            "source": "skill_hint",
            "matched_text": normalized,
        }
    for tool_name, patterns in EXPLICIT_TOOL_PATTERNS:
        if any(pattern.search(normalized) for pattern in patterns):
            return {
                "tool_name": tool_name,
                "source": "explicit_intent",
                "matched_text": normalized,
            }
    return None


def _refresh_hints_to_project_changes(refresh_hints: Dict[str, Any], *, summary: str) -> List[Dict[str, Any]]:
    if not isinstance(refresh_hints, dict) or not any(bool(value) for value in refresh_hints.values()):
        return []
    return [
        {
            "block_id": uuid.uuid4().hex,
            "tool_name": "tool_loop",
            "summary": summary or "工作区已更新",
            "refresh_hints": dict(refresh_hints),
        }
    ]


def _artifact_map_from_result(result: Dict[str, Any]) -> Dict[str, Any]:
    artifact = result.get("result") if isinstance(result.get("result"), dict) else {}
    artifact_type = str(artifact.get("artifact_type") or "").strip()
    if artifact_type:
        return {artifact_type: artifact}
    return {}


def _build_post_context_brief(session, *, script_id: int, episode_id: Optional[int]) -> Dict[str, Any]:
    stage_read_model = build_creative_stage_read_model(session, script_id=script_id, episode_id=episode_id)
    return {
        "creative_stage": stage_read_model.get("creative_stage"),
        "creative_stage_label": stage_read_model.get("creative_stage_label"),
        "active_agent": stage_read_model.get("active_agent"),
        "active_agent_label": stage_read_model.get("active_agent_label"),
        "facts": stage_read_model.get("facts") or {},
    }


def _load_project_resources(session, *, script_id: int) -> List[SharedResource]:
    return session.exec(
        select(SharedResource)
        .where(SharedResource.script_id == script_id)
        .order_by(SharedResource.created_at.asc(), SharedResource.id.asc())
    ).all()


def _resource_reference_stats(resources: List[SharedResource]) -> Dict[str, int]:
    tracked = [
        item for item in resources
        if _clean_text(getattr(item, "resource_type", None)).lower() in {"character", "scene", "prop"}
    ]
    with_images = [
        item for item in tracked
        if _clean_text(getattr(item, "file_url", None))
    ]
    return {
        "resource_total": len(tracked),
        "resource_with_images": len(with_images),
    }


def _resource_map_by_id(resources: List[SharedResource]) -> Dict[int, SharedResource]:
    return {
        int(item.id): item
        for item in resources
        if getattr(item, "id", None) is not None
    }


def _load_episode_panels(session, *, episode_id: int) -> List[Panel]:
    return session.exec(
        select(Panel)
        .where(Panel.episode_id == episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()


def _resolve_target_storyboard_panel(panels: List[Panel], *, requested_sequence: Optional[int], want_video: bool = False) -> Optional[Panel]:
    if requested_sequence is not None:
        return next((item for item in panels if int(getattr(item, "sequence_num", 0) or 0) == int(requested_sequence)), None)
    for panel in panels:
        if want_video:
            if _clean_text(getattr(panel, "image_url", None)) and not _clean_text(getattr(panel, "video_url", None)):
                return panel
        else:
            if not _clean_text(getattr(panel, "image_url", None)):
                return panel
    return panels[0] if panels else None


def _bound_assets_missing_images(panel: Panel, *, resource_map: Dict[int, SharedResource]) -> List[Dict[str, Any]]:
    bindings = _json_loads(getattr(panel, "entity_bindings_json", None), {})
    missing: List[Dict[str, Any]] = []
    for group_key, type_label in (("characters", "人物"), ("scenes", "场景"), ("props", "道具")):
        for item in list((bindings.get(group_key) or [])):
            if not isinstance(item, dict):
                continue
            asset_id = item.get("asset_id")
            if asset_id is None:
                continue
            resource = resource_map.get(int(asset_id))
            if resource is None:
                continue
            if _clean_text(getattr(resource, "file_url", None)):
                continue
            missing.append(
                {
                    "asset_id": int(asset_id),
                    "name": _clean_text(item.get("name")) or _clean_text(getattr(resource, "name", None)) or "未命名资产",
                    "resource_type": _clean_text(getattr(resource, "resource_type", None)) or group_key,
                    "resource_type_label": type_label,
                }
            )
    return missing


def _derive_episode_dubbing_text(session, episode: Optional[Episode]) -> str:
    if not episode:
        return ""
    source_text = _clean_text(getattr(episode, "source_text", None))
    if source_text:
        return source_text
    panels = session.exec(
        select(Panel)
        .where(Panel.episode_id == episode.id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    lines: List[str] = []
    for panel in panels:
        storyboard_mode = _clean_text(getattr(panel, "storyboard_mode", None)).lower()
        text = _clean_text(panel.dialogue_text if storyboard_mode == "comic" else panel.narration_text)
        if not text:
            text = _clean_text(getattr(panel, "original_text", None))
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


def _infer_dubbing_ability(content: str, script_text: str, episode: Optional[Episode]) -> str:
    lowered = _clean_text(content).lower()
    text = _clean_text(script_text)
    storyboard_mode = _clean_text(getattr(episode, "storyboard_mode", None)).lower()
    long_text = len(text) >= 160 or text.count("\n") >= 2
    if any(keyword in lowered for keyword in ["旁白", "解说", "朗读", "念出来"]):
        return ABILITY_NARRATION if len(text) >= 80 or storyboard_mode == "commentary" else ABILITY_REALTIME
    if any(keyword in lowered for keyword in ["对白", "台词", "配音"]):
        return ABILITY_REALTIME if len(text) <= 220 else ABILITY_NARRATION
    if storyboard_mode == "commentary":
        return ABILITY_NARRATION if long_text or len(text) >= 80 else ABILITY_REALTIME
    return ABILITY_NARRATION if long_text else ABILITY_REALTIME


def _find_recent_audio_choice(session, *, session_obj: AssistantSession, user: User) -> Dict[str, Any]:
    records = session.exec(
        select(GenerationRecord)
        .where(
            GenerationRecord.user_id == user.id,
            GenerationRecord.record_type == "audio",
            GenerationRecord.script_id == session_obj.script_id,
        )
        .order_by(GenerationRecord.updated_at.desc(), GenerationRecord.id.desc())
        .limit(10)
    ).all()
    for record in records:
        params_public = _json_loads(record.params_public_json, {})
        voice_id = _clean_text(params_public.get("voice_id"))
        if not voice_id:
            continue
        return {
            "voice_id": voice_id,
            "voice_source_type": _clean_text(params_public.get("voice_source_type")) or VOICE_SOURCE_SYSTEM,
            "ability_type": _clean_text(params_public.get("ability_type")),
            "tier_code": _clean_text(params_public.get("tier_code")),
        }
    return {}


def _load_voice_assets_for_tool(session, *, user: User, limit: int = 12) -> List[Dict[str, Any]]:
    try:
        payload = list_voice_assets(session, user=user)
    except Exception:
        return []
    assets = payload.get("assets") if isinstance(payload, dict) else []
    if not isinstance(assets, list):
        return []
    result: List[Dict[str, Any]] = []
    seen_ids = set()
    for item in assets:
        if not isinstance(item, dict):
            continue
        voice_id = _clean_text(item.get("voice_id"))
        if not voice_id or voice_id in seen_ids:
            continue
        seen_ids.add(voice_id)
        result.append(
            {
                "voice_id": voice_id,
                "source_type": _clean_text(item.get("source_type")) or VOICE_SOURCE_SYSTEM,
                "label": _clean_text(item.get("display_name")) or voice_id,
            }
        )
        if len(result) >= limit:
            break
    return result


def _resolve_voice_source_type(voice_assets: List[Dict[str, Any]], voice_id: str, fallback: str = VOICE_SOURCE_SYSTEM) -> str:
    resolved_voice_id = _clean_text(voice_id)
    for item in voice_assets:
        if _clean_text(item.get("voice_id")) == resolved_voice_id:
            return _clean_text(item.get("source_type")) or fallback
    return fallback


class InternalDirectorToolExecutor:
    def __init__(
        self,
        *,
        service,
        session_obj: AssistantSession,
        user: User,
        team: Team,
        base_context: Dict[str, Any],
    ) -> None:
        self.service = service
        self.session = service.session
        self.session_obj = session_obj
        self.user = user
        self.team = team
        self.base_context = dict(base_context or {})
        self.latest_artifacts = dict(self.base_context.get("latest_artifacts") or {})

    def build_tools(self) -> List[Dict[str, Any]]:
        return build_internal_director_tools()

    def refresh_context(self, *, latest_user_message: str = "") -> Dict[str, Any]:
        script = self.session.get(Script, self.session_obj.script_id)
        episode = self.session.get(Episode, self.session_obj.episode_id) if self.session_obj.episode_id else None
        if not script:
            raise HTTPException(status_code=404, detail="当前项目不存在")
        context = build_agent_context(
            self.session,
            user=self.user,
            team=self.team,
            script=script,
            episode=episode,
            latest_user_message=latest_user_message,
            workflow=self.base_context.get("workflow") if isinstance(self.base_context.get("workflow"), dict) else {},
            page_context=self.base_context.get("page_context") if isinstance(self.base_context.get("page_context"), dict) else {},
            latest_artifacts=self.latest_artifacts,
            runtime_event_callback=self.base_context.get("runtime_event_callback"),
            now=self.base_context.get("now"),
        )
        context["assistant_session_id"] = getattr(self.session_obj, "id", None)
        context["assistant_session_profile"] = getattr(self.session_obj, "profile", "") or ""
        context["assistant_session_channel"] = getattr(self.session_obj, "channel", "") or ""
        return context

    def _persist_script_draft_if_present(self, arguments: Dict[str, Any]) -> bool:
        script_draft = _clean_text((arguments or {}).get("script_draft"))
        if not script_draft:
            return False
        script = self.session.get(Script, self.session_obj.script_id)
        episode = self.session.get(Episode, self.session_obj.episode_id) if self.session_obj.episode_id else None
        if not script:
            raise HTTPException(status_code=404, detail="current script missing")
        now = self.base_context.get("now") or _utc_now()
        script.source_text = script_draft
        script.updated_at = now
        self.session.add(script)
        if episode is not None:
            episode.source_text = script_draft
            episode.updated_at = now
            self.session.add(episode)
        self.session.commit()
        return True

    def _asset_table_rows(self, items: Any) -> List[List[str]]:
        rows: List[List[str]] = []
        for index, item in enumerate(items or [], start=1):
            if not isinstance(item, dict):
                continue
            name = _clean_text(item.get("name"))
            if not name:
                continue
            rows.append(
                [
                    str(index),
                    name,
                    _clean_text(item.get("description")),
                    _clean_text(item.get("trigger_word")),
                ]
            )
        return rows

    def _asset_quality_warning_summary(self, warnings: Optional[List[Dict[str, Any]]]) -> str:
        items = [item for item in (warnings or []) if isinstance(item, dict) and _clean_text(item.get("name"))]
        if not items:
            return ""
        kind_labels = {
            "character": "人物",
            "scene": "场景",
            "prop": "道具",
        }
        lines = [
            "已提取出资产，但下面这些资产原文信息较少，系统已先生成临时可用设定。建议到资产页面补充细节后再批量出图。"
        ]
        for item in items[:8]:
            kind = kind_labels.get(_clean_text(item.get("kind")), "资产")
            name = _clean_text(item.get("name"))
            issue = _clean_text(item.get("issue")) or "信息较少。"
            suggestion = _clean_text(item.get("suggestion")) or "建议到资产页面丰富设定。"
            lines.append(f"- {kind} `{name}`：{issue} {suggestion}")
        if len(items) > 8:
            lines.append(f"- 还有 {len(items) - 8} 个资产也建议在资产页面检查。")
        return "\n".join(lines)

    def _emit_asset_extract_runtime_state(
        self,
        *,
        stage: str,
        progress: int,
        message: str,
        partial_assets: Optional[Dict[str, List[Dict[str, str]]]] = None,
        quality_warnings: Optional[List[Dict[str, Any]]] = None,
        completed: bool = False,
    ) -> None:
        service = self.service
        session_obj = self.session_obj
        status = "completed" if completed else "running"
        title = "资产提取完成" if completed else "资产提取进度"
        summary = ""
        if isinstance(partial_assets, dict):
            character_count = len(partial_assets.get("characters") or [])
            scene_count = len(partial_assets.get("scenes") or [])
            prop_count = len(partial_assets.get("props") or [])
            summary = f"人物 {character_count} / 场景 {scene_count} / 道具 {prop_count}"
        service._patch_runtime_feed_item(
            session_obj,
            "status-main",
            {
                "title": title,
                "body": message,
                "status": status,
            },
            publish=True,
        )
        service._upsert_runtime_feed_item(
            session_obj,
            {
                "id": "asset-extract-summary",
                "type": "result_card" if completed else "status_card",
                "title": title,
                "body": summary or message,
                "summary": summary or message,
                "status": status,
                "progress": int(progress or 0),
                "stage": stage,
            },
            publish=True,
        )
        if quality_warnings is None and isinstance(partial_assets, dict):
            quality_warnings = partial_assets.get("_asset_quality_warnings") or partial_assets.get("asset_quality_warnings") or []
        warning_summary = self._asset_quality_warning_summary(quality_warnings)
        if warning_summary:
            service._upsert_runtime_feed_item(
                session_obj,
                {
                    "id": "asset-extract-quality-warning",
                    "type": "result_card",
                    "title": "资产待完善提醒",
                    "summary": warning_summary,
                    "status": status,
                    "stage": stage,
                },
                publish=True,
            )
        if not isinstance(partial_assets, dict):
            return
        sections = [
            ("characters", "人物提取结果"),
            ("scenes", "场景提取结果"),
            ("props", "道具提取结果"),
        ]
        for key, section_title in sections:
            rows = self._asset_table_rows(partial_assets.get(key) or [])
            if not rows:
                continue
            service._upsert_runtime_feed_item(
                session_obj,
                {
                    "id": f"asset-extract-{key}",
                    "type": "table_card",
                    "title": section_title,
                    "columns": ["序号", "名称", "说明", "触发词"],
                    "rows": rows,
                    "status": status,
                    "stage": stage,
                },
                publish=True,
            )

    def _execute_extract_assets_live(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        context = self.refresh_context(latest_user_message="")
        source_text = _clean_text(context.get("current_script"))
        if not source_text:
            return {
                "message": "当前分集还没有可提取资产的剧本原文。请先保存原文，再继续提取资产。",
                "result": {
                    "artifact_type": "asset_bundle",
                    "status": "failed",
                    "reason": "missing_script_source",
                    "characters": [],
                    "scenes": [],
                    "props": [],
                    "asset_summary": "请先保存原文",
                },
                "refresh_hints": {"script_source": True},
                "next_stage_hint": "script_ready",
                "suggested_actions": [
                    {"type": "save_script", "label": "保存原文"},
                    {"type": "rewrite_script", "label": "继续修改"},
                ],
            }
        if not settings.DEEPSEEK_API_KEY:
            raise ValueError("当前资产提取服务不可用，请稍后重试")

        script = context["script"]
        episode = context.get("episode")
        workflow_profile = context.get("workflow_profile") or resolve_effective_workflow_profile(
            script,
            episode=episode,
            storyboard_mode=resolve_asset_extraction_storyboard_mode(script, episode=episode),
        )
        style_prompt = build_style_prompt(
            workflow_profile.get("style"),
            fallback=getattr(script, "style_preset", ""),
        )
        style_label = get_style_display_label(
            workflow_profile.get("style"),
            getattr(script, "style_preset", "默认写实"),
        )
        billing_tracker = ResourceExtractionBillingTracker(
            user_id=getattr(self.user, "id", None),
            team_id=getattr(self.team, "id", None),
            task_id=None,
        )
        latest_partial_assets: Dict[str, Any] = {
            "characters": [],
            "scenes": [],
            "props": [],
            "_asset_quality_warnings": [],
        }

        def _stage_callback(stage: str, progress: int, message: str, _extra: Optional[Dict[str, Any]] = None) -> None:
            self._emit_asset_extract_runtime_state(
                stage=stage,
                progress=int(progress or 0),
                message=_clean_text(message) or "正在提取资产...",
                partial_assets=latest_partial_assets,
            )

        def _sync_callback(stage: str, partial_assets: Dict[str, List[Dict[str, str]]]) -> None:
            latest_partial_assets["characters"] = list(partial_assets.get("characters") or [])
            latest_partial_assets["scenes"] = list(partial_assets.get("scenes") or [])
            latest_partial_assets["props"] = list(partial_assets.get("props") or [])
            latest_partial_assets["_asset_quality_warnings"] = list(partial_assets.get("_asset_quality_warnings") or partial_assets.get("asset_quality_warnings") or [])
            self._emit_asset_extract_runtime_state(
                stage=stage,
                progress=0,
                message="正在整理角色、场景和道具...",
                partial_assets=latest_partial_assets,
            )

        structured_assets = extract_script_assets_structured(
            source_text,
            settings.DEEPSEEK_API_KEY,
            style_prompt=style_prompt,
            style_label=style_label,
            stage_callback=_stage_callback,
            usage_callback=billing_tracker.record_usage,
            sync_callback=_sync_callback,
        )
        extracted_total = (
            len(structured_assets.get("characters") or [])
            + len(structured_assets.get("scenes") or [])
            + len(structured_assets.get("props") or [])
        )
        if extracted_total <= 0:
            raise ValueError("未识别到可写入资产库的人物、场景或道具，请调整原文后重试")

        persisted = sync_structured_assets_into_shared_resources(
            script.id,
            structured_assets,
        )
        latest_partial_assets["characters"] = list(structured_assets.get("characters") or [])
        latest_partial_assets["scenes"] = list(structured_assets.get("scenes") or [])
        latest_partial_assets["props"] = list(structured_assets.get("props") or [])
        latest_partial_assets["_asset_quality_warnings"] = list(structured_assets.get("_asset_quality_warnings") or structured_assets.get("asset_quality_warnings") or [])
        self._emit_asset_extract_runtime_state(
            stage="completed",
            progress=100,
            message="资产提取完成，已写入资产库。",
            partial_assets=latest_partial_assets,
            completed=True,
        )

        final_bundle = _asset_bundle_from_structured_assets(structured_assets)
        final_bundle = {
            **final_bundle,
            "artifact_type": "asset_bundle",
            "status": "completed",
            "created_count": int(persisted.get("created_count") or 0),
            "updated_count": int(persisted.get("updated_count") or 0),
            "billing": billing_tracker.snapshot(),
            "asset_quality_warnings": list(latest_partial_assets.get("_asset_quality_warnings") or []),
        }
        character_count = len(final_bundle.get("characters") or [])
        scene_count = len(final_bundle.get("scenes") or [])
        prop_count = len(final_bundle.get("props") or [])
        warning_summary = self._asset_quality_warning_summary(latest_partial_assets.get("_asset_quality_warnings") or [])
        final_message = f"我已经为这份剧本整理出 {character_count} 个人物、{scene_count} 个场景、{prop_count} 个道具，并已写入资产库。"
        if warning_summary:
            final_message += "\n\n" + warning_summary
        return {
            "message": final_message,
            "result": final_bundle,
            "refresh_hints": {"resources": True, "assets": True, "open_assets": True},
            "next_stage_hint": "asset_images_pending",
            "suggested_actions": [
                {"type": "generate_asset_images", "label": "一键生成全部资产参考图", "payload": {"generation_scope": "all"}},
                {"type": "generate_asset_images", "label": "仅生成人物参考图", "payload": {"generation_scope": "character"}},
                {"type": "generate_asset_images", "label": "仅生成场景参考图", "payload": {"generation_scope": "scene"}},
                {"type": "generate_asset_images", "label": "仅生成道具参考图", "payload": {"generation_scope": "prop"}},
                {"type": "extract_storyboard", "label": "先规划分镜"},
            ],
        }

    def _storyboard_extract_prerequisite_result(self, *, force_without_asset_images: bool = False) -> Optional[Dict[str, Any]]:
        context = self.refresh_context(latest_user_message="")
        current_script = _clean_text(context.get("current_script"))
        if not current_script:
            return {
                "message": "当前还没有可用的剧本原文。请先保存或完善当前剧本，再继续提取分镜。",
                "result": {
                    "artifact_type": "storyboard_prerequisite_check",
                    "status": "failed",
                    "reason": "missing_script_source",
                },
                "refresh_hints": {"script_source": True},
                "next_stage_hint": "script_ready",
                "suggested_actions": [
                    {"type": "save_script", "label": "保存剧本"},
                    {"type": "rewrite_script", "label": "继续完善剧本"},
                ],
            }

        resources = _load_project_resources(self.session, script_id=self.session_obj.script_id)
        stats = _resource_reference_stats(resources)
        if stats["resource_total"] <= 0:
            return {
                "message": "当前还没有已提取的角色、场景或道具资产。请先提取资产，再继续拆分镜头。",
                "result": {
                    "artifact_type": "storyboard_prerequisite_check",
                    "status": "failed",
                    "reason": "missing_extracted_assets",
                    **stats,
                },
                "refresh_hints": {"resources": True},
                "next_stage_hint": "assets_pending",
                "suggested_actions": [
                    {"type": "extract_assets", "label": "提取资产"},
                ],
            }

        if False and stats["resource_with_images"] <= 0 and not force_without_asset_images:
            return {
                "message": "当前资产已提取，但还没有资产参考图。你可以先生成资产参考图，再提取分镜；也可以直接继续提取分镜，但角色和场景一致性可能会更弱。",
                "result": {
                    "artifact_type": "storyboard_prerequisite_check",
                    "status": "requires_confirmation",
                    "reason": "missing_asset_reference_images",
                    **stats,
                },
                "refresh_hints": {"resources": True},
                "next_stage_hint": "asset_images_pending",
                "suggested_actions": [
                    {"type": "generate_asset_images", "label": "先生成资产参考图"},
                    {"type": "extract_storyboard", "label": "直接规划分镜", "payload": {"force_without_asset_images": True}},
                ],
            }
        return None

    def _storyboard_image_prerequisite_result(self, *, panel_sequence: Optional[int] = None, panel_sequences: Optional[List[int]] = None) -> Optional[Dict[str, Any]]:
        resources = _load_project_resources(self.session, script_id=self.session_obj.script_id)
        stats = _resource_reference_stats(resources)
        if stats["resource_total"] <= 0:
            return {
                "message": "当前还没有已提取的资产，无法生成分镜图片。请先提取资产，再生成资产参考图。",
                "result": {
                    "artifact_type": "storyboard_image_prerequisite_check",
                    "status": "failed",
                    "reason": "missing_extracted_assets",
                    **stats,
                },
                "refresh_hints": {"resources": True},
                "next_stage_hint": "assets_pending",
                "suggested_actions": [
                    {"type": "extract_assets", "label": "提取资产"},
                ],
            }
        if not self.session_obj.episode_id:
            return {
                "message": "请先选中一个具体剧集，我才能继续生成分镜图片。",
                "result": {
                    "artifact_type": "storyboard_image_prerequisite_check",
                    "status": "failed",
                    "reason": "missing_episode",
                    **stats,
                },
                "refresh_hints": {},
                "next_stage_hint": self.base_context.get("creative_stage") or "",
                "suggested_actions": [],
            }
        panels = _load_episode_panels(self.session, episode_id=int(self.session_obj.episode_id))
        requested_sequences: List[int] = []
        for item in panel_sequences or []:
            try:
                value = int(item)
            except Exception:
                continue
            if value > 0 and value not in requested_sequences:
                requested_sequences.append(value)
        if requested_sequences:
            panel_map = {int(getattr(item, "sequence_num", 0) or 0): item for item in panels}
            target_panels = [panel_map[value] for value in requested_sequences if value in panel_map]
        else:
            target_panel = _resolve_target_storyboard_panel(panels, requested_sequence=panel_sequence, want_video=False)
            target_panels = [target_panel] if target_panel is not None else []
        if not target_panels:
            return {
                "message": "当前剧集还没有可生成图片的分镜，请先提取分镜。",
                "result": {
                    "artifact_type": "storyboard_image_prerequisite_check",
                    "status": "failed",
                    "reason": "missing_storyboard_panels",
                    **stats,
                },
                "refresh_hints": {"panels": True},
                "next_stage_hint": "storyboard_pending",
                "suggested_actions": [
                    {"type": "extract_storyboard", "label": "先规划分镜"},
                ],
            }
        if stats["resource_with_images"] <= 0:
            return {
                "message": "当前还没有资产参考图，暂时不能直接生成分镜图片。请先生成资产参考图，再继续生成分镜图片。",
                "result": {
                    "artifact_type": "storyboard_image_prerequisite_check",
                    "status": "failed",
                    "reason": "missing_asset_reference_images",
                    **stats,
                },
                "refresh_hints": {"resources": True, "open_assets": True},
                "next_stage_hint": "asset_images_pending",
                "suggested_actions": [
                    {"type": "generate_asset_images", "label": "生成资产参考图"},
                ],
            }
        resource_map = _resource_map_by_id(resources)
        for target_panel in target_panels:
            missing_assets = _bound_assets_missing_images(
                target_panel,
                resource_map=resource_map,
            )
            if not missing_assets:
                continue
            missing_summary = "、".join(
                "{0}“{1}”".format(item.get("resource_type_label") or "资产", item.get("name") or "未命名资产")
                for item in missing_assets[:6]
            )
            return {
                "message": "当前分镜绑定的部分资产还没有参考图，暂时不能直接生成分镜图片。请先补齐这些资产参考图：{0}".format(missing_summary),
                "result": {
                    "artifact_type": "storyboard_image_prerequisite_check",
                    "status": "failed",
                    "reason": "missing_bound_asset_reference_images",
                    "panel_id": int(getattr(target_panel, "id", 0) or 0),
                    "panel_sequence": int(getattr(target_panel, "sequence_num", 0) or 0),
                    "missing_assets": missing_assets,
                    **stats,
                },
                "refresh_hints": {"resources": True, "open_assets": True},
                "next_stage_hint": "asset_images_pending",
                "suggested_actions": [
                    {"type": "generate_asset_images", "label": "生成资产参考图"},
                ],
            }
        return None

    def _execute_action_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        action_type = TOOL_NAME_TO_ACTION_TYPE[tool_name]
        if tool_name == "extract_assets":
            self._persist_script_draft_if_present(arguments)
            return self._execute_extract_assets_live(arguments)
        context = self.refresh_context(latest_user_message="")
        if tool_name == "generate_storyboard_images":
            prerequisite_result = self._storyboard_image_prerequisite_result(
                panel_sequence=arguments.get("panel_sequence"),
                panel_sequences=arguments.get("selected_panel_sequences"),
            )
            if prerequisite_result:
                return prerequisite_result
        agent_cls = {
            "save_script": DirectorAgent,
            "rewrite_script": DirectorAgent,
            "extract_assets": AssetPlannerAgent,
            "save_assets": AssetPlannerAgent,
            "save_storyboard": StoryboardAgent,
            "generate_asset_images": GenerationAgent,
            "generate_storyboard_images": GenerationAgent,
            "generate_video": GenerationAgent,
            "rewrite_generation_prompts": PromptRewriteAgent,
        }.get(action_type)
        if agent_cls is None:
            raise ValueError(f"unsupported tool action: {tool_name}")
        return agent_cls(self.session).execute_action(context, action_type, payload=arguments or {})

    def _execute_extract_storyboard(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        self._persist_script_draft_if_present(arguments)
        prerequisite_result = self._storyboard_extract_prerequisite_result(
            force_without_asset_images=bool(arguments.get("force_without_asset_images"))
        )
        if prerequisite_result:
            return prerequisite_result
        if not _clean_text(arguments.get("mode")):
            latest_message = _clean_text(self.base_context.get("latest_user_message"))
            has_plan = isinstance(self.latest_artifacts.get("storyboard_plan_bundle"), dict)
            if has_plan and any(token in latest_message for token in ["根据规划", "确认", "计划分镜", "正式分镜"]):
                arguments["mode"] = "split_confirmed"
            else:
                arguments["mode"] = "plan_first"
        context = self.refresh_context(latest_user_message="")
        return StoryboardAgent(self.session).execute_action(context, "extract_storyboard", payload=arguments or {})

    def _execute_generate_audio(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.session_obj.episode_id:
            return {
                "message": "请先选中一个具体剧集，我才能为当前剧集生成配音或旁白。",
                "result": {
                    "artifact_type": "audio_generation_result",
                    "status": "failed",
                    "reason": "missing_episode",
                },
                "refresh_hints": {},
                "next_stage_hint": self.base_context.get("creative_stage") or "",
            }
        episode = self.session.get(Episode, self.session_obj.episode_id)
        if not episode:
            raise HTTPException(status_code=404, detail="当前剧集不存在或已被删除")

        voice_assets = _load_voice_assets_for_tool(self.session, user=self.user)
        recent_choice = _find_recent_audio_choice(self.session, session_obj=self.session_obj, user=self.user)
        script_text = _clean_text(arguments.get("script_text")) or _derive_episode_dubbing_text(self.session, episode)
        default_ability_type = _infer_dubbing_ability(_clean_text(arguments.get("request_summary")), script_text, episode)
        voice_id = _clean_text(arguments.get("voice_id")) or _clean_text(recent_choice.get("voice_id"))
        if not voice_id:
            return {
                "message": "当前还缺少可直接提交的音色。我已经整理出最近可用的音色选项，你确认后我就能继续生成配音。",
                "result": {
                    "artifact_type": "audio_voice_options",
                    "status": "requires_confirmation",
                    "voice_options": voice_assets,
                    "default_ability_type": default_ability_type,
                },
                "refresh_hints": {},
                "next_stage_hint": self.base_context.get("creative_stage") or "",
            }

        resolved_voice_source_type = _resolve_voice_source_type(
            voice_assets,
            voice_id,
            fallback=_clean_text(arguments.get("voice_source_type")) or _clean_text(recent_choice.get("voice_source_type")) or VOICE_SOURCE_SYSTEM,
        )
        resolved_ability_type = _clean_text(arguments.get("ability_type")) or _clean_text(recent_choice.get("ability_type")) or default_ability_type
        if resolved_ability_type not in {ABILITY_REALTIME, ABILITY_NARRATION}:
            resolved_ability_type = default_ability_type
        resolved_tier_code = _clean_text(arguments.get("tier_code")) or _clean_text(recent_choice.get("tier_code")) or "hd"
        if resolved_tier_code not in {"hd", "turbo"}:
            resolved_tier_code = "hd"
        emotion = _clean_text(arguments.get("emotion"))

        team = self.session.get(Team, self.session_obj.team_id)
        if not team:
            raise HTTPException(status_code=404, detail="当前会话所属团队不存在")

        payload = {
            "ownership_mode": "project",
            "project_id": encode_id(self.session_obj.script_id),
            "episode_id": encode_id(episode.id),
            "target_type": "episode_record",
            "ability_type": resolved_ability_type,
            "tier_code": resolved_tier_code,
            "voice_id": voice_id,
            "voice_source_type": resolved_voice_source_type,
            "script_text": script_text,
            "audio_format": "mp3",
        }
        if emotion:
            payload["emotion"] = emotion

        record = submit_audio_generation(
            self.session,
            background_tasks=BackgroundTasks(),
            user=self.user,
            team=team,
            payload=payload,
        )
        if hasattr(self.service, "_mark_generation_record_source"):
            record = self.service._mark_generation_record_source(session_obj=self.session_obj, record=record)
        if resolved_ability_type == ABILITY_NARRATION:
            threading.Thread(target=_run_audio_async_job, args=(record.id,), daemon=True).start()

        return {
            "message": "已为当前剧集提交配音任务。",
            "result": {
                "artifact_type": "audio_generation_result",
                "status": _clean_text(getattr(record, "status", None)) or ("queued" if resolved_ability_type == ABILITY_NARRATION else "completed"),
                "task_id": _clean_text(getattr(record, "task_id", None)),
                "record_id": encode_id(record.id) if getattr(record, "id", None) else None,
                "episode_id": encode_id(episode.id),
                "voice_id": voice_id,
                "voice_source_type": resolved_voice_source_type,
                "ability_type": resolved_ability_type,
                "tier_code": resolved_tier_code,
                "preview_url": _clean_text(getattr(record, "preview_url", None)) or None,
            },
            "refresh_hints": {"generation_tasks": True, "panels": True},
            "next_stage_hint": "audio_generation",
        }

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        normalized_name = _clean_text(tool_name)
        normalized_arguments = dict(arguments or {})
        if normalized_name in TOOL_NAME_TO_ACTION_TYPE:
            result = self._execute_action_tool(normalized_name, normalized_arguments)
        elif normalized_name == "extract_storyboard":
            result = self._execute_extract_storyboard(normalized_arguments)
        elif normalized_name == "generate_audio":
            result = self._execute_generate_audio(normalized_arguments)
        else:
            raise ValueError(f"unknown tool: {normalized_name}")

        self.latest_artifacts.update(_artifact_map_from_result(result))
        return {
            "tool_name": normalized_name,
            "status": "completed",
            "summary": _clean_text(result.get("message")) or _clean_text((result.get("result") or {}).get("summary")) or normalized_name,
            "message": _clean_text(result.get("message")),
            "result": result.get("result") if isinstance(result.get("result"), dict) else {},
            "refresh_hints": result.get("refresh_hints") if isinstance(result.get("refresh_hints"), dict) else {},
            "next_stage_hint": _clean_text(result.get("next_stage_hint")),
            "suggested_actions": result.get("suggested_actions") if isinstance(result.get("suggested_actions"), list) else [],
            "artifacts": _artifact_map_from_result(result),
            "post_context": _build_post_context_brief(
                self.session,
                script_id=self.session_obj.script_id,
                episode_id=self.session_obj.episode_id,
            ),
        }


def execute_internal_director_tool(
    *,
    service,
    session_obj: AssistantSession,
    user: User,
    team: Team,
    context: Dict[str, Any],
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    executor = InternalDirectorToolExecutor(
        service=service,
        session_obj=session_obj,
        user=user,
        team=team,
        base_context=context,
    )
    return executor.execute(tool_name, dict(arguments or {}))


def _tool_loop_route_context(context: Dict[str, Any], explicit_tool_intent: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    workspace_facts = context.get("workspace_facts_preview") or {}
    resource_counts = workspace_facts.get("resource_counts") or {}
    return {
        "task_kind": "tool_execution",
        "agent_name": TOOL_LOOP_ASSISTANT_NAME,
        "estimated_text_tokens": estimate_text_tokens(_clean_text(context.get("current_script"))),
        "segment_count": int(workspace_facts.get("panel_count") or 0),
        "character_count": int(resource_counts.get("characters") or 0),
        "expected_tool_calls": 2,
        "user_intent_flags": extract_user_intent_flags(_clean_text(context.get("latest_user_message"))),
        "previous_failures": int(context.get("llm_failures") or 0),
        "json_mode_enabled": True,
        "strict_tools_enabled": True,
        "explicit_tool_name": _clean_text((explicit_tool_intent or {}).get("tool_name")),
    }


def _tool_loop_system_prompt(*, context: Dict[str, Any], tools: List[Dict[str, Any]], explicit_tool_intent: Optional[Dict[str, Any]]) -> str:
    tool_names = [
        str(((item.get("function") or {}).get("name") if isinstance(item, dict) else "") or "").strip()
        for item in tools
    ]
    return (
        "你是神鹿 AI 导演，面向短剧和漫画创作者提供项目推进帮助。\n"
        "你的职责是：读取当前项目上下文，判断用户意图，优先选择合适的工具执行，并在拿到工具结果后继续思考，直到给出最终答案。\n"
        "只要用户表达的是明确动作意图，你就应该优先调用对应工具，而不是只给建议。\n"
        "如果工具返回前置不足或需要确认，也要基于该工具结果继续解释和引导，不要静默切换到别的工具。\n"
        "工具名、action 名、函数名只供内部调用，最终 message 中禁止出现 save_script、rewrite_script、extract_assets、save_assets、extract_storyboard、save_storyboard、generate_asset_images、generate_storyboard_images、generate_video、rewrite_generation_prompts、generate_audio 等内部英文标识。\n"
        "当用户问“你是谁 / 你会做什么 / 你会干什么”时，不要罗列内部工具名，要用创作者能理解的产品语言说明能力：剧本整理、资产设计、分镜规划、提示词优化、参考图、分镜图、镜头视频、配音旁白。\n"
        "当前不提供联网搜索或外部参考资料检索能力；提到配音或旁白时，应说明通常需要当前剧集文本和可用音色。\n"
        "可用工具：{0}\n"
        "显式意图：{1}\n"
        "你最终必须返回一个 JSON 对象，字段包括：\n"
        "- message\n"
        "- suggested_actions\n"
        "- artifacts\n"
        "- next_stage_hint\n"
        "- refresh_hints\n"
        "- stage\n"
        "- stage_label\n"
        "- active_agent\n"
        "- active_agent_label\n"
        "其中 suggested_actions 是数组；artifacts 和 refresh_hints 必须是对象。\n"
        "如果本轮需要调用工具，就先发起工具调用；只有在不需要更多工具时才输出最终 JSON。"
    ).format(
        "、".join(item for item in tool_names if item) or "无",
        _clean_text((explicit_tool_intent or {}).get("tool_name")) or "无",
    )


def _tool_loop_user_prompt(*, context: Dict[str, Any], explicit_tool_intent: Optional[Dict[str, Any]]) -> str:
    workspace_facts = context.get("workspace_facts_preview") or {}
    payload = {
        "workspace_facts": workspace_facts,
        "workflow_profile": context.get("workflow_profile") or {},
        "latest_artifacts": context.get("latest_artifacts") or {},
    }
    return (
        "【用户最新输入】\n{0}\n\n"
        "【显式动作意图】\n{1}\n\n"
        "【当前项目上下文】\n{2}"
    ).format(
        _clean_text(context.get("latest_user_message")) or "无",
        _clean_text((explicit_tool_intent or {}).get("tool_name")) or "无",
        json.dumps(payload, ensure_ascii=False),
    )


def _assistant_tool_message(tool_calls: List[Dict[str, Any]], *, reasoning_content: str = "") -> Dict[str, Any]:
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": _clean_text(item.get("id")) or uuid.uuid4().hex,
                "type": _clean_text(item.get("type")) or "function",
                "function": {
                    "name": _clean_text((item.get("function") or {}).get("name")),
                    "arguments": _clean_text((item.get("function") or {}).get("arguments")),
                },
            }
            for item in tool_calls
        ],
    }
    if _clean_text(reasoning_content):
        message["reasoning_content"] = _clean_text(reasoning_content)
    return message


def _safe_json_arguments(raw_arguments: Any) -> Dict[str, Any]:
    text = _clean_text(raw_arguments)
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"tool arguments are invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("tool arguments must be a JSON object")
    return payload


def _merge_final_payload(
    *,
    context: Dict[str, Any],
    latest_artifacts: Dict[str, Any],
    accumulated_refresh_hints: Dict[str, bool],
    payload: Optional[Dict[str, Any]],
    last_tool_result: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    stage = _clean_text(context.get("creative_stage")) or "script_ready"
    stage_label = _clean_text(context.get("creative_stage_label")) or CREATIVE_STAGE_LABELS.get(stage, stage)
    result = {
        "active_agent": TOOL_LOOP_ASSISTANT_NAME,
        "active_agent_label": TOOL_LOOP_ASSISTANT_LABEL,
        "stage": stage,
        "stage_label": stage_label,
        "message": _clean_text((last_tool_result or {}).get("message")) or "已处理当前创作请求。",
        "suggested_actions": list((last_tool_result or {}).get("suggested_actions") or []),
        "artifacts": dict(latest_artifacts or {}),
        "next_stage_hint": _clean_text((last_tool_result or {}).get("next_stage_hint")) or stage,
        "refresh_hints": dict(accumulated_refresh_hints or {}),
    }
    if isinstance(payload, dict):
        for key in ("active_agent", "active_agent_label", "stage", "stage_label", "message", "next_stage_hint"):
            value = payload.get(key)
            if value not in (None, ""):
                result[key] = value
        if isinstance(payload.get("suggested_actions"), list):
            result["suggested_actions"] = payload.get("suggested_actions") or []
        if isinstance(payload.get("artifacts"), dict) and payload.get("artifacts"):
            result["artifacts"] = payload.get("artifacts") or {}
        if isinstance(payload.get("refresh_hints"), dict) and payload.get("refresh_hints"):
            result["refresh_hints"] = {str(key): bool(value) for key, value in payload.get("refresh_hints", {}).items()}
    return result


def run_internal_director_tool_loop(
    *,
    service,
    session_obj: AssistantSession,
    user: User,
    team: Team,
    context: Dict[str, Any],
    explicit_tool_intent: Optional[Dict[str, Any]],
    stream_skill_hint: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    tools = build_internal_director_tools()
    executor = InternalDirectorToolExecutor(
        service=service,
        session_obj=session_obj,
        user=user,
        team=team,
        base_context=context,
    )
    route_context = _tool_loop_route_context(context, explicit_tool_intent)
    route = resolve_deepseek_agent_route(route_context)
    service._update_runtime_state(
        session_obj,
        resolved_model_choice=str(route.get("model") or ""),
        selection_reason=str(route.get("route_tag") or ""),
        execution_stage="tool_loop",
        commit=False,
    )
    service._publish_runtime_delta(session_obj)

    messages: List[Dict[str, Any]] = [
        {
            "role": "system",
            "content": _tool_loop_system_prompt(context=context, tools=tools, explicit_tool_intent=explicit_tool_intent),
        },
        {
            "role": "user",
            "content": _tool_loop_user_prompt(context=context, explicit_tool_intent=explicit_tool_intent),
        },
    ]
    accumulated_refresh_hints: Dict[str, bool] = {}
    accumulated_project_changes: List[Dict[str, Any]] = []
    latest_artifacts = dict(context.get("latest_artifacts") or {})
    last_tool_result: Optional[Dict[str, Any]] = None
    final_payload: Optional[Dict[str, Any]] = None

    for loop_index in range(1, TOOL_LOOP_MAX_STEPS + 1):
        response = chat_json_with_tools(
            model=str(route.get("model") or settings.DEEPSEEK_AGENT_DEFAULT_MODEL or "deepseek-v4-flash"),
            messages=messages,
            tools=tools,
            thinking_enabled=bool(route.get("thinking_enabled")),
            max_tokens=int(route.get("max_tokens") or settings.DEEPSEEK_AGENT_PLANNING_MAX_TOKENS),
            strict_tools=bool(route.get("strict_tools_enabled", True)),
            tool_choice=(
                {
                    "type": "function",
                    "function": {"name": _clean_text((explicit_tool_intent or {}).get("tool_name"))},
                }
                if loop_index == 1 and _clean_text((explicit_tool_intent or {}).get("tool_name"))
                else None
            ),
            route_tag=str(route.get("route_tag") or ""),
            on_reasoning_delta=(
                lambda delta_text, full_text: service._update_reasoning_progress(
                    session_obj,
                    content=_clean_text(context.get("latest_user_message")) or "请参考当前项目上下文",
                    skill_hint=stream_skill_hint,
                    reasoning_text=full_text,
                    reasoning_delta=delta_text,
                )
            ),
        )
        if response.get("tool_calls"):
            tool_calls = response.get("tool_calls") or []
            messages.append(_assistant_tool_message(tool_calls, reasoning_content=str(response.get("reasoning") or "")))
            if loop_index == 1:
                service._remove_runtime_feed_item(session_obj, "thought-plan", publish=True)
                service._patch_runtime_feed_item(
                    session_obj,
                    "status-main",
                    {
                        "title": "开始执行工具",
                        "body": "我已经完成思考，接下来会按顺序执行选中的工具。",
                        "status": "running",
                    },
                    publish=True,
                )
            for tool_call in tool_calls:
                tool_name = _clean_text((tool_call.get("function") or {}).get("name"))
                tool_call_id = _clean_text(tool_call.get("id")) or uuid.uuid4().hex
                display = build_tool_card(tool_name, status="running")
                tool_card_id = "tool-call-{0}".format(tool_call_id)
                service._upsert_runtime_feed_item(
                    session_obj,
                    {
                        "id": tool_card_id,
                        **display,
                        "status": "running",
                        "summary": "正在执行 {0}".format(display.get("title_cn") or tool_name),
                    },
                    publish=True,
                )
                service.publish_event(
                    session_obj.id,
                    {
                        "type": "tool_call_started",
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "loop_index": loop_index,
                        "arguments": _clean_text((tool_call.get("function") or {}).get("arguments")),
                    },
                )
                try:
                    arguments = _safe_json_arguments((tool_call.get("function") or {}).get("arguments"))
                    tool_result = executor.execute(tool_name, arguments)
                    last_tool_result = tool_result
                    latest_artifacts.update(tool_result.get("artifacts") or {})
                    refresh_hints = tool_result.get("refresh_hints") if isinstance(tool_result.get("refresh_hints"), dict) else {}
                    for key, value in refresh_hints.items():
                        accumulated_refresh_hints[str(key)] = accumulated_refresh_hints.get(str(key), False) or bool(value)
                    changes = _refresh_hints_to_project_changes(refresh_hints, summary=tool_result.get("message") or tool_result.get("summary") or "")
                    if changes:
                        accumulated_project_changes.extend(changes)
                        service.publish_event(session_obj.id, {"type": "project_change", "project_changes": changes})
                    summary = _clean_text(tool_result.get("summary")) or _clean_text(tool_result.get("message")) or "工具执行完成"
                    service._complete_runtime_feed_item(
                        session_obj,
                        tool_card_id,
                        {
                            "status": "completed",
                            "summary": summary,
                        },
                        publish=True,
                    )
                    service.publish_event(
                        session_obj.id,
                        {
                            "type": "tool_call_completed",
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "loop_index": loop_index,
                            "summary": summary,
                            "result": tool_result.get("result") or {},
                        },
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": _json_dumps(tool_result),
                        }
                    )
                except Exception as exc:
                    error_text = _clean_text(exc) or "工具执行失败"
                    service._complete_runtime_feed_item(
                        session_obj,
                        tool_card_id,
                        {
                            "status": "failed",
                            "summary": error_text,
                        },
                        publish=True,
                    )
                    service.publish_event(
                        session_obj.id,
                        {
                            "type": "tool_call_failed",
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "loop_index": loop_index,
                            "error": error_text,
                        },
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "name": tool_name,
                            "content": _json_dumps(
                                {
                                    "tool_name": tool_name,
                                    "status": "failed",
                                    "summary": error_text,
                                    "message": error_text,
                                    "result": {"status": "failed", "error": error_text},
                                    "refresh_hints": {},
                                    "next_stage_hint": "",
                                    "artifacts": {},
                                }
                            ),
                        }
                    )
                    last_tool_result = {
                        "tool_name": tool_name,
                        "status": "failed",
                        "summary": error_text,
                        "message": error_text,
                        "result": {"status": "failed", "error": error_text},
                        "refresh_hints": {},
                        "next_stage_hint": "",
                        "artifacts": {},
                    }
            continue

        final_payload = response.get("payload") if isinstance(response.get("payload"), dict) else None
        break

    if final_payload is None:
        final_payload = _merge_final_payload(
            context=context,
            latest_artifacts=latest_artifacts,
            accumulated_refresh_hints=accumulated_refresh_hints,
            payload=None,
            last_tool_result=last_tool_result,
        )
        final_payload["message"] = _clean_text(final_payload.get("message")) or "本轮工具调用已达到循环上限，我先把目前结果整理给你。"

    final_result = _merge_final_payload(
        context=context,
        latest_artifacts=latest_artifacts,
        accumulated_refresh_hints=accumulated_refresh_hints,
        payload=final_payload,
        last_tool_result=last_tool_result,
    )
    service._complete_runtime_feed_item(
        session_obj,
        "thought-plan",
        {
            "title": "判断完成",
            "status": "completed",
        },
        publish=True,
    )
    service._complete_runtime_feed_item(
        session_obj,
        "status-main",
        {
            "title": "已完成本轮判断",
            "body": "我已经整理好当前回复和下一步建议。",
            "status": "completed",
        },
        publish=True,
    )
    if isinstance(final_result.get("suggested_actions"), list) and final_result.get("suggested_actions"):
        service._upsert_runtime_feed_item(
            session_obj,
            {
                "id": "actions-final",
                "type": "action_card",
                "actions": final_result.get("suggested_actions") or [],
                "status": "completed",
            },
            publish=True,
        )

    return {
        "final_payload": final_result,
        "latest_artifacts": latest_artifacts,
        "project_changes": accumulated_project_changes,
        "explicit_tool_intent": explicit_tool_intent or {},
        "model_route": route,
    }
