from __future__ import annotations

import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, HTTPException
from sqlmodel import select

from core.security import encode_id
from database import session_scope
from models import AssistantPendingQuestion, AssistantSession, AssistantTranscriptEvent, Episode, GenerationRecord, Panel, Script, SharedResource, Team, User
from services.agent_stage_service import (
    ACTIVE_AGENT_LABELS,
    CREATIVE_STAGE_LABELS,
    STAGE_AGENT_MAP,
    get_next_stage_after_action,
)
from services.agents.router import build_agent_context, execute_agent_action as execute_structured_agent_action, run_active_agent
from services.audio_model_registry import ABILITY_NARRATION, ABILITY_REALTIME, VOICE_SOURCE_SYSTEM
from services.agent_workflow_service import AgentWorkflowService
from services.director_agent_service import DirectorAgentService
from services.external_agent_service import append_chat_message
from services.image_model_registry import normalize_image_model_code
from services.generation_record_service import (
    _run_audio_async_job,
    _run_image_generation_job,
    _run_video_generation_job,
    list_voice_assets,
    submit_audio_generation,
    submit_image_generation,
    submit_video_generation,
)
from services.storyboard_director_service import StorySegmentParseError
from services.storyboard_mode_service import get_panel_latest_image
from services.video_model_registry import GENERATION_TYPE_LABELS
from .tool_display_registry import build_tool_card, get_tool_display
from .public_reasoning_templates import (
    public_reasoning_phase_key_for_length,
    select_public_reasoning_template,
)
from .deepseek_tool_runtime import (
    TOOL_NAME_TO_ACTION_TYPE,
    execute_internal_director_tool,
    extract_explicit_tool_intent,
    run_internal_director_tool_loop,
)

from .service import (
    AssistantRuntimeService,
    _derive_title,
    _iso,
    _json_dumps,
    _json_loads,
    _normalize_target,
    _utc_now,
)
from .panel_selection import build_selected_panels_payload, format_selected_panel_display, resolve_panel_selection
from .video_model_selector import (
    build_model_unavailable_message,
    build_video_model_options,
    choose_video_model,
    infer_audio_enabled,
    infer_video_generation_type,
    resolve_explicit_video_model_request,
)
from .video_skill_planner import (
    build_video_execution_plan_payload as build_video_execution_plan_state,
    build_video_generation_field_options as resolve_video_generation_field_options,
)
from .video_task_executor import (
    attachment_media_urls as normalize_attachment_media_urls,
    build_panel_video_payload as create_panel_video_payload,
    coerce_bool as coerce_runtime_bool,
    derive_panel_video_prompt as resolve_panel_video_prompt,
    panel_has_video as detect_panel_has_video,
    panel_latest_image as resolve_panel_latest_image,
    panel_video_duration as resolve_panel_video_duration,
    submit_panel_video_generation_tasks as dispatch_panel_video_generation_tasks,
)
from .video_skill_runtime import (
    answer_generate_panel_video_question_v2 as delegated_answer_generate_panel_video_question_v2,
    create_panel_video_wizard_v2 as delegated_create_panel_video_wizard_v2,
    execute_generate_panel_video_skill_v2 as delegated_execute_generate_panel_video_skill_v2,
    submit_panel_video_generation_v2 as delegated_submit_panel_video_generation_v2,
)

_ORIGINAL_SERIALIZE_SESSION_META = AssistantRuntimeService.serialize_session_meta


def _match_smalltalk_reply(content: str) -> Optional[str]:
    text = " ".join(str(content or "").strip().split())
    lowered = text.lower()
    if not lowered:
        return None

    if lowered in {"你好", "您好", "嗨", "hi", "hello", "hey", "哈喽"}:
        return "你好，我在。你可以直接告诉我你想做哪一步，比如剧情策划、拆分镜、出图、视频或配音。"
    if any(token in lowered for token in ["你是谁", "介绍一下", "你能做什么", "你会什么", "你会干什么"]):
        return (
            "我是你的神鹿 AI 导演，专门辅助短剧和漫剧创作。"
            "神鹿影视 AI 是面向一人创作的多智能体协同 AI 原生漫剧创作引擎；"
            "我可以按当前项目进度调用不同创作 Agent，协助你完成剧本润色、角色场景道具设计、分镜规划与拆分、提示词优化、资产参考图、分镜图、镜头视频和配音旁白。"
        )
    if lowered in {"谢谢", "谢了", "thanks", "thank you"}:
        return "不客气。你下一步想继续做剧、重做当前环节，还是优化某个镜头，都可以直接说。"
    return None


def _looks_like_status_query(content: str) -> bool:
    text = " ".join(str(content or "").strip().split()).lower()
    if not text:
        return False
    keywords = [
        "当前状态",
        "项目状态",
        "做到哪一步",
        "做到了哪一步",
        "到哪一步",
        "进行到哪",
        "进度",
        "当前进度",
        "目前进度",
        "现在到哪了",
        "现在什么阶段",
        "看看当前",
        "看下当前",
        "看一下当前",
        "看看项目",
        "看下项目",
        "状态如何",
        "进展如何",
    ]
    return any(keyword in text for keyword in keywords)


def _looks_like_script_source_message(content: str) -> bool:
    text = str(content or "").strip()
    if len(text) < 180:
        return False
    line_count = len([line for line in text.splitlines() if line.strip()])
    marker_hits = 0
    for pattern in (
        r"【\s*剧本正文\s*】",
        r"场景[一二三四五六七八九十\d]+",
        r"片尾画面",
        r"[内外][\.·/][日夜晨昏]",
        r"（[^）]{1,32}）",
        r"“[^”]{1,80}”",
    ):
        if re.search(pattern, text):
            marker_hits += 1
    return line_count >= 6 and marker_hits >= 2


def _build_workflow_status_reply(self, *, session_obj: AssistantSession, user: User) -> Optional[Dict[str, Any]]:
    team = self.session.get(Team, session_obj.team_id)
    if not team:
        return None
    workflow_service = AgentWorkflowService(self.session)
    if session_obj.episode_id:
        workflow_data = workflow_service.get_episode_workflow_read_model(
            user=user,
            team=team,
            script_id=session_obj.script_id,
            episode_id=session_obj.episode_id,
        )
    else:
        workflow_data = workflow_service.get_script_workflow_read_model(
            user=user,
            team=team,
            script_id=session_obj.script_id,
        )

    script_workflow = workflow_data.get("script_workflow") or {}
    episode_workflow = workflow_data.get("episode_workflow") or {}
    current_node = workflow_data.get("current_node") or {}
    quality = workflow_data.get("quality_assessment") or current_node.get("quality") or {}
    next_recommendation = workflow_data.get("next_recommendation") or current_node.get("next_recommendation") or ""

    lines = []
    if script_workflow.get("current_step_label"):
        lines.append(f"整剧进度：{script_workflow['current_step_label']}（{script_workflow.get('stage_status_label') or script_workflow.get('stage_status') or '未知'}）")
    if episode_workflow.get("current_step_label"):
        title = episode_workflow.get("episode_title") or "当前分集"
        lines.append(f"{title}：{episode_workflow['current_step_label']}（{episode_workflow.get('stage_status_label') or episode_workflow.get('stage_status') or '未知'}）")
    if current_node.get("summary"):
        lines.append(f"本轮结果：{current_node['summary']}")
    if quality.get("assessment"):
        lines.append(f"当前判断：{quality['assessment']}")
    if next_recommendation:
        lines.append(f"下一步建议：{next_recommendation}")

    if not lines:
        lines.append("当前项目还没有足够的流程信息。你可以先告诉我你想从剧情策划、分镜拆分、出图还是视频开始。")

    text_block = {
        "id": uuid.uuid4().hex,
        "type": "text",
        "text": "\n".join(lines),
    }
    summary_block = {
        "id": uuid.uuid4().hex,
        "type": "reasoning_summary",
        "summary": "我直接读取了当前项目的流程状态，没有额外走导演重推理。",
    }
    assistant_turn = self._build_turn(
        role="assistant",
        blocks=[text_block, summary_block],
        metadata={"source": "workflow_status_fastpath"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "project_changes": [],
    }


def _generation_record_source(session_obj: AssistantSession) -> str:
    return "openclaw_agent" if session_obj.profile == "openclaw_public" else "agent"


def _display_action_label(action_type: str, payload: Optional[Dict[str, Any]] = None) -> str:
    explicit = str((payload or {}).get("action_label") or "").strip()
    code_like = bool(explicit) and (re.fullmatch(r"[A-Za-z0-9_]+", explicit) is not None or explicit == action_type)
    if explicit and not code_like:
        return explicit
    return {
        "save_script": "保存剧本",
        "rewrite_script": "继续完善现有剧本",
        "extract_assets": "提取资产",
        "save_assets": "保存资产",
        "save_storyboard": "生成分镜板",
        "generate_asset_images": "生成全部主体设定图",
        "generate_storyboard_images": "生成全部分镜图",
        "generate_video": "生成视频",
        "rewrite_generation_prompts": "改写生成提示词",
    }.get(str(action_type or "").strip(), explicit or action_type or "继续下一步")


def _mark_generation_record_source(
    self,
    *,
    session_obj: AssistantSession,
    record: GenerationRecord,
    params_public_updates: Optional[Dict[str, Any]] = None,
    params_internal_updates: Optional[Dict[str, Any]] = None,
) -> GenerationRecord:
    params_public = _json_loads(record.params_public_json, {})
    params_internal = _json_loads(record.params_internal_json, {})
    source = _generation_record_source(session_obj)
    params_public["source"] = source
    params_internal["source"] = source
    params_internal["assistant_session_id"] = session_obj.id
    params_internal["assistant_session_profile"] = session_obj.profile
    params_internal["assistant_session_channel"] = session_obj.channel
    if params_public_updates:
        params_public.update(params_public_updates)
    if params_internal_updates:
        params_internal.update(params_internal_updates)
    record.params_public_json = _json_dumps(params_public)
    record.params_internal_json = _json_dumps(params_internal)
    self.session.add(record)
    self.session.commit()
    self.session.refresh(record)
    return record


def _build_tool_activity(self, skill_hint: Optional[Dict[str, Any]], session_obj: AssistantSession) -> List[Dict[str, Any]]:
    context_summary = _summarize_project_context_for_runtime(self, session_obj)
    if skill_hint:
        label = skill_hint.get("label") or "执行任务"
        return [
            {"id": "{0}-ctx".format(skill_hint.get("id") or "skill"), "label": "读取项目上下文", "status": "running", "description": context_summary},
            {"id": "{0}-plan".format(skill_hint.get("id") or "skill"), "label": "规划{0}".format(label), "status": "pending"},
            {"id": "{0}-result".format(skill_hint.get("id") or "skill"), "label": "整理结果并回写工作区", "status": "pending"},
        ]
    target_label = "站外协作" if _normalize_target(None, session_obj) == "external" else "导演工具链"
    return [
        {"id": "context", "label": "读取项目上下文", "status": "running", "description": context_summary},
        {"id": "planner", "label": "分析需求并选择{0}".format(target_label), "status": "pending"},
        {"id": "summary", "label": "整理结果与刷新提示", "status": "pending"},
    ]


def _summarize_project_context_for_runtime(self, session_obj: AssistantSession) -> str:
    script = self.session.get(Script, session_obj.script_id) if session_obj.script_id else None
    episode = self.session.get(Episode, session_obj.episode_id) if session_obj.episode_id else None

    script_title = str(getattr(script, "name", "") or "").strip() or "当前项目"
    episode_title = str(getattr(episode, "title", "") or "").strip() or "当前分集"
    source_text = str(
        getattr(episode, "source_text", None)
        or getattr(script, "source_text", None)
        or ""
    ).strip()
    source_status = "已读取剧本文本" if source_text else "尚未读取到剧本文本"

    try:
        asset_count = len(self.session.exec(select(SharedResource).where(SharedResource.script_id == session_obj.script_id)).all())
    except Exception:
        asset_count = 0

    panel_count = 0
    if session_obj.episode_id:
        try:
            panel_count = len(self.session.exec(select(Panel).where(Panel.episode_id == session_obj.episode_id)).all())
        except Exception:
            panel_count = 0

    return "项目：《%s》；分集：《%s》；%s；已有资产 %s 项；已有分镜 %s 条" % (
        script_title,
        episode_title,
        source_status,
        asset_count,
        panel_count,
    )


def _runtime_feed_status_card(*, card_id: str, title: str, body: str, status: str = "running") -> Dict[str, Any]:
    return {
        "id": card_id,
        "type": "status_card",
        "title": title,
        "body": body,
        "status": status,
    }


def _runtime_feed_thought_card(
    *,
    card_id: str,
    variant: str,
    body: str,
    title: str = "思考中",
    persona: str = "",
    template_id: str = "",
) -> Dict[str, Any]:
    return {
        "id": card_id,
        "type": "thought_card",
        "title": "思考中",
        "variant": variant,
        "persona": persona,
        "template_id": template_id,
        "title": title or "思考中",
        "body": body,
        "status": "running",
    }


REASONING_PUBLIC_PHASE_MIN_MS = 2200


def _public_reasoning_phase(*, content: str, skill_hint: Optional[Dict[str, Any]], length: int) -> Dict[str, Any]:
    text = str(content or "").strip()
    skill_id = str((skill_hint or {}).get("id") or "").strip()
    lowered = text.lower()
    is_next_step_query = any(token in lowered for token in ["下一步", "接下来", "然后呢", "做什么", "怎么推进"])

    if is_next_step_query:
        phase_bodies = [
            "正在确认当前项目进度：剧本、资产、分镜、图片和视频分别完成到哪一步。",
            "正在核对可推进条件：优先判断是否已经具备进入分镜、出图或视频生成的条件。",
            "正在整理下一步建议：给出当前最适合推进的动作，并准备可点击的继续选项。",
        ]
    elif skill_id:
        label = str((skill_hint or {}).get("label") or skill_id).strip()
        phase_bodies = [
            f"正在理解你要推进的“{label}”任务，并读取相关项目状态。",
            "正在核对执行前条件，避免跳过必要的剧本、资产或分镜依赖。",
            "正在整理执行方案与结果摘要，完成后会给出清晰的下一步选择。",
        ]
    else:
        phase_bodies = [
            "正在理解你的需求，并判断它是咨询、修改，还是需要进入具体创作动作。",
            "正在结合当前项目状态，确认是否需要调用剧本、资产、分镜或生成工具。",
            "正在整理回复和后续建议，尽量把可执行的下一步放到结果卡里。",
        ]

    if length < 60:
        return {"detail": "正在分析项目上下文", "active_index": 0, "variant": "my_understanding", "body": phase_bodies[0]}
    if length < 180:
        return {"detail": "正在拆解需求并匹配导演工具", "active_index": 1, "variant": "my_plan", "body": phase_bodies[1]}
    return {"detail": "正在整理执行方案与结果摘要", "active_index": 2, "variant": "my_judgment", "body": phase_bodies[2]}


def _select_public_reasoning_phase(
    *,
    content: str,
    skill_hint: Optional[Dict[str, Any]],
    length: int,
    runtime_state: Optional[Dict[str, Any]] = None,
    fallback_intent: str = "general_project_question",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    phase_key = public_reasoning_phase_key_for_length(length)
    return select_public_reasoning_template(
        content=content,
        skill_hint=skill_hint,
        phase=phase_key,
        runtime_state=runtime_state or {},
        fallback_intent=fallback_intent,
    )


def _public_reasoning_phase(*, content: str, skill_hint: Optional[Dict[str, Any]], length: int) -> Dict[str, Any]:
    public_phase, _updates = _select_public_reasoning_phase(
        content=content,
        skill_hint=skill_hint,
        length=length,
    )
    return public_phase


def _runtime_feed_tool_card(
    *,
    card_id: str,
    tool_key: str,
    status: str,
    summary: str = "",
    fallback_label: str = "",
    actions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    card = build_tool_card(tool_key, status=status, summary=summary, fallback_label=fallback_label, actions=actions)
    card["id"] = card_id
    return card


def _compact_runtime_text(value: Any, limit: int = 96) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _runtime_fact_item_name(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("name") or item.get("trigger_word") or "").strip()


def _runtime_fact_asset_names(workspace_facts: Dict[str, Any], facts: Dict[str, Any]) -> str:
    groups = [
        ("人物", (workspace_facts.get("characters") or facts.get("characters") or [])[:6]),
        ("场景", (workspace_facts.get("scenes") or facts.get("scenes") or [])[:5]),
        ("道具", (workspace_facts.get("props") or facts.get("props") or [])[:6]),
    ]
    parts: List[str] = []
    for label, items in groups:
        names = [_runtime_fact_item_name(item) for item in items]
        names = [name for name in names if name]
        if names:
            parts.append("{0}：{1}".format(label, "、".join(names)))
    return "；".join(parts)


def _runtime_fact_panel_summary(workspace_facts: Dict[str, Any], facts: Dict[str, Any]) -> str:
    panels = workspace_facts.get("panels") or facts.get("panels") or []
    parts: List[str] = []
    for item in panels[:3]:
        if not isinstance(item, dict):
            continue
        sequence = item.get("sequence_num")
        summary = _compact_runtime_text(item.get("summary"), 56)
        if not summary:
            continue
        prefix = "第 {0} 镜".format(sequence) if sequence else "分镜"
        parts.append("{0}：{1}".format(prefix, summary))
    return "；".join(parts)


def _turn_text_content(turn: Dict[str, Any]) -> str:
    parts: List[str] = []
    for block in turn.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        if str(block.get("type") or "").strip() != "text":
            continue
        text = str(block.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _latest_user_message_before_agent_action(self, session_obj: AssistantSession) -> str:
    statement = (
        select(AssistantTranscriptEvent)
        .where(
            AssistantTranscriptEvent.session_id == session_obj.id,
            AssistantTranscriptEvent.event_type == "turn",
            AssistantTranscriptEvent.role == "user",
        )
        .order_by(AssistantTranscriptEvent.sequence_no.desc(), AssistantTranscriptEvent.id.desc())
        .limit(12)
    )
    for event in self.session.exec(statement).all():
        turn = _json_loads(event.payload_json, {})
        if not isinstance(turn, dict):
            continue
        metadata = turn.get("metadata") if isinstance(turn.get("metadata"), dict) else {}
        if metadata.get("agent_action"):
            continue
        text = _turn_text_content(turn)
        if text:
            return text
    return ""


def _runtime_feed_facts_cards(context_summary: Dict[str, Any]) -> List[Dict[str, Any]]:
    workspace_facts = context_summary.get("workspace_facts") or {}
    facts = context_summary.get("stage_facts") or {}
    script_name = str(workspace_facts.get("script_name") or facts.get("script_name") or "当前项目").strip()
    episode_title = str(workspace_facts.get("episode_title") or facts.get("episode_title") or "当前分集").strip()
    source_saved = bool(workspace_facts.get("episode_has_source_text") or workspace_facts.get("script_has_source_text") or facts.get("has_source_text"))
    source_preview = str(workspace_facts.get("current_script") or facts.get("current_script") or "").strip()
    if source_preview:
        compact_source_preview = " ".join(source_preview.split())
        source_body = "已读取当前剧本：{0}".format(
            compact_source_preview[:96] + ("..." if len(compact_source_preview) > 96 else "")
        )
    elif source_saved:
        source_body = "已读取当前分集剧本内容，正在结合剧情推进、人物关系和场景信息判断下一步。"
    else:
        source_body = "当前分集还没有可阅读的剧本内容，请先补充本集剧情后再继续。"
    resource_counts = workspace_facts.get("resource_counts") or facts.get("resource_counts") or {}
    asset_image_count = int(workspace_facts.get("asset_image_count") or facts.get("asset_image_count") or 0)
    panel_count = int(workspace_facts.get("panel_count") or facts.get("panel_count") or 0)
    panels_with_images = int(workspace_facts.get("panels_with_images") or facts.get("panels_with_images") or 0)
    panels_with_videos = int(workspace_facts.get("panels_with_videos") or facts.get("panels_with_videos") or 0)
    asset_names = _runtime_fact_asset_names(workspace_facts, facts)
    asset_body = "人物 {0} / 场景 {1} / 道具 {2}；参考图 {3} 张".format(
        int(resource_counts.get("characters") or 0),
        int(resource_counts.get("scenes") or 0),
        int(resource_counts.get("props") or 0),
        asset_image_count,
    )
    if asset_names:
        asset_body = "{0}。资产名单：{1}".format(asset_body, asset_names)
    panel_summary = _runtime_fact_panel_summary(workspace_facts, facts)
    storyboard_body = "当前已有 {0} 个分镜；分镜图 {1} 张；视频 {2} 条".format(
        panel_count,
        panels_with_images,
        panels_with_videos,
    )
    if panel_summary:
        storyboard_body = "{0}。分镜摘要：{1}".format(storyboard_body, panel_summary)
    return [
        _runtime_feed_status_card(
            card_id="facts-script",
            title="正在读取当前剧本和当前分集",
            body=f"当前剧本：《{script_name}》；当前分集：《{episode_title}》",
            status="completed",
        ),
        _runtime_feed_status_card(
            card_id="facts-source",
            title="正在查看剧本",
            body=source_body,
            status="completed",
        ),
        _runtime_feed_status_card(
            card_id="facts-assets",
            title="已提取资产数量",
            body=asset_body,
            status="completed",
        ),
        _runtime_feed_status_card(
            card_id="facts-storyboard",
            title="当前有没有分镜、图片、视频结果",
            body=storyboard_body,
            status="completed",
        ),
    ]


def _initial_runtime_feed(
    session_obj: AssistantSession,
    skill_hint: Optional[Dict[str, Any]],
    normalized_target: str,
    public_phase: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    phase = public_phase or {}
    if phase:
        return [
            _runtime_feed_status_card(
                card_id="status-main",
                title="已收到你的需求",
                body=str(phase.get("detail") or "正在理解创作需求"),
                status="running",
            ),
            _runtime_feed_thought_card(
                card_id="thought-plan",
                variant=str(phase.get("variant") or "thinking"),
                title=str(phase.get("title") or "思考中"),
                persona=str(phase.get("persona") or ""),
                template_id=str(phase.get("template_id") or ""),
                body=str(phase.get("body") or "我先理解你的问题。"),
            ),
        ]
    return [
        _runtime_feed_status_card(
            card_id="status-main",
            title="已收到你的需求",
            body="我正在结合当前项目资料判断最合适的推进方式。",
            status="running",
        ),
        _runtime_feed_thought_card(
            card_id="thought-plan",
            variant=str(phase.get("variant") or "thinking"),
            title=str(phase.get("title") or "思考中"),
            persona=str(phase.get("persona") or ""),
            template_id=str(phase.get("template_id") or ""),
            body="我正在分析你的需求，并准备选择合适的工具。",
        ),
    ]


def _duration_seconds_from_value(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(int(float(value)), 0)
    except Exception:
        match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
        if not match:
            return 0
        try:
            return max(int(float(match.group(0))), 0)
        except Exception:
            return 0


def _storyboard_plan_total_seconds(data: Dict[str, Any], rows: List[List[str]]) -> int:
    explicit_total = _duration_seconds_from_value(
        data.get("total_estimated_duration_seconds") or data.get("total_duration_seconds")
    )
    if explicit_total:
        return explicit_total
    plan_bundle = data.get("storyboard_plan_bundle") if isinstance(data.get("storyboard_plan_bundle"), dict) else {}
    bundle_total = _duration_seconds_from_value(
        plan_bundle.get("total_estimated_duration_seconds") or plan_bundle.get("total_duration_seconds")
    )
    if bundle_total:
        return bundle_total
    return sum(_duration_seconds_from_value(row[3] if len(row) > 3 else "") for row in rows)


def _build_draft_turn(
    self,
    *,
    content: str,
    skill_hint: Optional[Dict[str, Any]],
    tool_activity: List[Dict[str, Any]],
    reasoning_text: str = "",
) -> Dict[str, Any]:
    label = skill_hint.get("label") if skill_hint else "导演任务"
    blocks: List[Dict[str, Any]] = [
        {
            "id": uuid.uuid4().hex,
            "type": "task_progress",
            "title": label or "导演任务",
            "description": "正在结合当前项目上下文规划执行路径。",
            "task_type": skill_hint.get("id") if skill_hint else None,
            "status": "running",
        }
    ]
    if reasoning_text:
        blocks.append(
            {
                "id": uuid.uuid4().hex,
                "type": "reasoning_stream",
                "summary": "正在实时接收 DeepSeek 思考内容",
                "text": str(reasoning_text or ""),
            }
        )
    else:
        blocks.append(
            {
                "id": uuid.uuid4().hex,
                "type": "reasoning_summary",
                "summary": "已接收你的请求，正在分析上下文、选择工具链并整理执行步骤。",
            }
        )
    return self._build_turn(
        role="assistant",
        blocks=blocks,
        metadata={
            "draft": True,
            "source_user_message": content,
            "tool_activity": tool_activity,
            "skill_hint": skill_hint or {},
        },
    )


def _append_error_turn(self, *, session_obj: AssistantSession, error_text: str) -> Dict[str, Any]:
    turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "text",
                "text": "执行失败：{0}".format(error_text or "未知错误"),
            }
        ],
    )
    self._insert_turn_event(session_obj=session_obj, turn=turn)
    return turn


def _serialize_pending_question(self, question: AssistantPendingQuestion) -> Dict[str, Any]:
    payload = _json_loads(question.payload_json, {})
    answer_payload = _json_loads(question.answer_json, {})
    data = {
        "id": question.question_key,
        "question_type": question.question_type,
        "status": question.status,
        "title": question.title or "需要你确认",
        "prompt": question.prompt_text or "",
        "options": payload.get("options") or [],
        "preview": payload.get("preview") or {},
        "task_type": payload.get("task_type"),
        "metadata": payload.get("metadata") or {},
        "answer": answer_payload.get("answer"),
        "answers": answer_payload.get("answers") or {},
        "created_at": question.created_at.isoformat() if question.created_at else None,
        "updated_at": question.updated_at.isoformat() if question.updated_at else None,
    }
    if question.question_type == "wizard":
        wizard_payload = payload.get("wizard") if isinstance(payload.get("wizard"), dict) else {}
        data["wizard"] = {
            "title": wizard_payload.get("title") or data["title"],
            "description": wizard_payload.get("description") or data["prompt"],
            "steps": wizard_payload.get("steps") or [],
            "submit_label": wizard_payload.get("submit_label") or "提交",
            "cancel_label": wizard_payload.get("cancel_label") or "取消",
            "values": answer_payload.get("answers") or {},
        }
    return data


def _update_reasoning_progress(
    self,
    session_obj: AssistantSession,
    *,
    content: str,
    skill_hint: Optional[Dict[str, Any]],
    reasoning_text: str,
    reasoning_delta: str = "",
) -> None:
    runtime_state = self._get_runtime_state(session_obj)
    previous_tool_activity = list((runtime_state.get("tool_activity") or []))
    length = len(str(reasoning_text or ""))
    public_phase, public_reasoning_updates = _select_public_reasoning_phase(
        content=content,
        skill_hint=skill_hint,
        length=length,
        runtime_state=runtime_state,
    )
    now_ms = int(time.time() * 1000)
    previous_phase = runtime_state.get("reasoning_public_phase") if isinstance(runtime_state.get("reasoning_public_phase"), dict) else {}
    previous_phase_index = runtime_state.get("reasoning_public_phase_index")
    try:
        previous_phase_index = int(previous_phase_index)
    except Exception:
        previous_phase_index = None
    try:
        previous_phase_started_ms = int(runtime_state.get("reasoning_public_phase_started_ms") or 0)
    except Exception:
        previous_phase_started_ms = 0
    desired_phase_index = int(public_phase.get("active_index") or 0)
    phase_elapsed_ms = now_ms - previous_phase_started_ms if previous_phase_started_ms else REASONING_PUBLIC_PHASE_MIN_MS
    if (
        previous_phase
        and previous_phase_index is not None
        and desired_phase_index != previous_phase_index
        and phase_elapsed_ms < REASONING_PUBLIC_PHASE_MIN_MS
    ):
        public_phase = previous_phase
        public_reasoning_updates = {}
        desired_phase_index = previous_phase_index
    phase_started_ms = (
        previous_phase_started_ms
        if previous_phase_index == desired_phase_index and previous_phase_started_ms
        else now_ms
    )
    detail = str(public_phase.get("detail") or "正在整理当前任务")
    active_index = int(public_phase.get("active_index") or 0)
    thought_variant = str(public_phase.get("variant") or "thinking")
    thought_body = str(public_phase.get("body") or "正在整理当前任务的处理思路。")

    tool_activity = self._build_tool_activity(skill_hint, session_obj)
    for index, item in enumerate(tool_activity):
        if index < active_index:
            item["status"] = "completed"
        elif index == active_index:
            item["status"] = "running"
        else:
            item["status"] = "pending"

    draft_turn = self._build_draft_turn(
        content=content,
        skill_hint=skill_hint,
        tool_activity=tool_activity,
        reasoning_text=thought_body,
    )
    feed_by_id = {str(item.get("id") or ""): item for item in self._get_runtime_feed(session_obj)}
    status_patch = {
        "title": "已收到你的需求",
        "body": detail,
        "status": "running",
    }
    current_status = feed_by_id.get("status-main") or {}
    did_publish_status = False
    if any(current_status.get(key) != value for key, value in status_patch.items()):
        self._patch_runtime_feed_item(
            session_obj,
            "status-main",
            status_patch,
            publish=True,
        )
        did_publish_status = True
    thought_patch = {
        "title": "正在判断",
        "variant": thought_variant,
        "persona": str(public_phase.get("persona") or ""),
        "template_id": str(public_phase.get("template_id") or ""),
        "title": str(public_phase.get("title") or "思考中"),
        "body": thought_body,
        "status": "running",
    }
    current_thought = feed_by_id.get("thought-plan") or {}
    did_publish_thought = False
    if any(current_thought.get(key) != value for key, value in thought_patch.items()):
        self._patch_runtime_feed_item(
            session_obj,
            "thought-plan",
            thought_patch,
            publish=True,
        )
        did_publish_thought = True
    if reasoning_delta and did_publish_thought:
        self.publish_event(
            session_obj.id,
            {
                "type": "reasoning_delta",
                "delta_text": "",
                "full_text": thought_body,
            },
        )
    previous_map = {str(item.get("id") or ""): item for item in previous_tool_activity if isinstance(item, dict)}
    did_publish_tool_step = False
    for item in tool_activity:
        step_id = str(item.get("id") or "")
        if not step_id:
            continue
        previous = previous_map.get(step_id) or {}
        previous_status = str(previous.get("status") or "")
        current_status = str(item.get("status") or "")
        if previous_status == current_status:
            continue
        event_type = "runtime_step_updated"
        if not previous_status:
            event_type = "runtime_step_started"
        elif current_status == "completed":
            event_type = "runtime_step_completed"
        self.publish_event(
            session_obj.id,
            {
                "type": event_type,
                "step_id": step_id,
                "label": item.get("label") or "",
                "status": current_status,
                "summary": detail,
                "created_at": _iso(_utc_now()),
            },
        )
        did_publish_tool_step = True
    self._update_runtime_state(
        session_obj,
        draft_turn=draft_turn,
        status_detail=detail,
        tool_activity=tool_activity,
        reasoning_public_phase=public_phase,
        reasoning_public_phase_index=active_index,
        reasoning_public_phase_started_ms=phase_started_ms,
        public_reasoning_intent=public_reasoning_updates.get("public_reasoning_intent"),
        public_reasoning_phase=public_reasoning_updates.get("public_reasoning_phase"),
        public_reasoning_template_id=public_reasoning_updates.get("public_reasoning_template_id"),
        public_reasoning_recent_template_ids=public_reasoning_updates.get("public_reasoning_recent_template_ids"),
    )
    self._publish_runtime_delta(session_obj)


def _build_question_resolved_turn(
    self,
    *,
    action: str,
    question_data: Dict[str, Any],
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if action == "reject":
        return self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "interrupt_notice",
                    "text": "已取消本次操作，不会继续执行写入。",
                }
            ],
        )

    answer_items = []
    for key, value in list((answers or {}).items())[:3]:
        if value in (None, "", []):
            continue
        answer_items.append("{0}: {1}".format(key, value))
    summary = "已记录你的补充信息，后续会按这些条件继续执行。"
    if answer_items:
        summary = "{0} {1}".format(summary, "；".join(answer_items))

    return self._build_turn(
        role="assistant",
        blocks=[
            {"id": uuid.uuid4().hex, "type": "reasoning_summary", "summary": summary},
            {"id": uuid.uuid4().hex, "type": "text", "text": question_data.get("title") or "已记录本轮回答。"},
        ],
    )


def start_message(
    self,
    *,
    session_obj: Optional[AssistantSession] = None,
    user: Optional[User] = None,
    content: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    target: Optional[str] = None,
    attachments: Optional[List[Dict[str, Any]]] = None,
    async_mode: bool = True,
) -> Dict[str, Any]:
    if not session_obj or not user:
        raise HTTPException(status_code=400, detail="消息发送缺少会话或用户上下文")

    normalized_attachments = self._sanitize_attachments(attachments)
    content_text = str(content or "").strip()
    if not content_text and not normalized_attachments:
        raise HTTPException(status_code=400, detail="消息内容和附件不能同时为空")
    if session_obj.status == "running":
        raise HTTPException(status_code=409, detail="当前会话仍在处理中，请稍后再试或先中断")

    normalized_target = _normalize_target(target, session_obj)
    smalltalk_reply = _match_smalltalk_reply(content_text) if normalized_target == "internal" and not normalized_attachments else None
    if smalltalk_reply:
        now = _utc_now()
        if not session_obj.title or session_obj.title == self.DEFAULT_SESSION_TITLE:
            session_obj.title = _derive_title(content_text or self.DEFAULT_SESSION_TITLE, self.DEFAULT_SESSION_TITLE)

        user_turn = self._build_turn(
            role="user",
            blocks=self._build_user_blocks(content_text, normalized_attachments),
            metadata={"target": normalized_target, "attachments": normalized_attachments},
        )
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": smalltalk_reply,
                }
            ],
            metadata={"source": "smalltalk_fastpath"},
        )
        session_obj.status = "completed"
        session_obj.updated_at = now
        self._update_runtime_state(
            session_obj,
            draft_turn=None,
            status_detail="",
            tool_activity=[],
            project_changes=[],
            skill_hint={},
            runtime_feed=[],
            clear_keys=[
                "draft_turn",
                "pending_question_wizard",
                "execution_stage",
                "selected_panels",
            "resolved_model_choice",
            "selection_reason",
            "resume_hint",
            "reasoning_public_phase",
            "reasoning_public_phase_index",
            "reasoning_public_phase_started_ms",
            "public_reasoning_intent",
            "public_reasoning_phase",
            "public_reasoning_template_id",
            "running_started_at",
        ],
            commit=False,
        )
        self.session.add(session_obj)
        self._insert_turn_event(session_obj=session_obj, turn=user_turn)
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.session.refresh(session_obj)

        self.publish_event(session_obj.id, {"type": "patch", "turn": user_turn})
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        self._publish_status(session_obj)
        self._publish_runtime_delta(session_obj)
        self.publish_snapshot(session_obj.id)
        return {
            "snapshot": self.get_snapshot(session_obj=session_obj),
            "queued": False,
            "assistant_turn": assistant_turn,
            "project_changes": [],
        }

    skill_hint = self._extract_skill_hint(content_text)
    if normalized_target == "external" and not skill_hint:
        skill_hint = {
            "id": "delegate_to_external_agent",
            "label": "站外协作",
            "slash_command": "/站外协作",
            "category": "bridge",
        }
    tool_activity = self._build_tool_activity(skill_hint, session_obj)
    public_reasoning_state = self._get_runtime_state(session_obj)
    public_reasoning_state.pop("public_reasoning_intent", None)
    public_reasoning_state.pop("public_reasoning_phase", None)
    public_reasoning_state.pop("public_reasoning_template_id", None)
    public_phase, public_reasoning_updates = _select_public_reasoning_phase(
        content=content_text,
        skill_hint=skill_hint,
        length=0,
        runtime_state=public_reasoning_state,
    )
    runtime_feed = _initial_runtime_feed(session_obj, skill_hint, normalized_target, public_phase=public_phase)
    draft_turn = self._build_draft_turn(
        content=content_text or "请参考附件",
        skill_hint=skill_hint,
        tool_activity=tool_activity,
    )

    now = _utc_now()
    if not session_obj.title or session_obj.title == self.DEFAULT_SESSION_TITLE:
        title_source = content_text or self.DEFAULT_SESSION_TITLE
        session_obj.title = _derive_title(title_source, self.DEFAULT_SESSION_TITLE)

    session_obj.status = "running"
    session_obj.updated_at = now
    self._update_runtime_state(
        session_obj,
        draft_turn=draft_turn,
        status_detail="正在读取项目上下文" if normalized_target == "internal" else "正在准备站外协作",
        tool_activity=tool_activity,
        project_changes=[],
        skill_hint=skill_hint or {},
        running_started_at=_iso(now),
        runtime_feed=runtime_feed,
        reasoning_public_phase=public_phase,
        reasoning_public_phase_index=public_phase.get("active_index"),
        public_reasoning_intent=public_reasoning_updates.get("public_reasoning_intent"),
        public_reasoning_phase=public_reasoning_updates.get("public_reasoning_phase"),
        public_reasoning_template_id=public_reasoning_updates.get("public_reasoning_template_id"),
        public_reasoning_recent_template_ids=public_reasoning_updates.get("public_reasoning_recent_template_ids"),
        clear_keys=[
            "pending_question_wizard",
            "execution_stage",
            "selected_panels",
            "resolved_model_choice",
            "selection_reason",
            "resume_hint",
        ],
        commit=False,
    )
    self.session.add(session_obj)

    user_turn = self._build_turn(
        role="user",
        blocks=self._build_user_blocks(content_text or "请参考附件", normalized_attachments),
        metadata={"target": normalized_target, "attachments": normalized_attachments},
    )
    self._insert_turn_event(session_obj=session_obj, turn=user_turn)
    self.session.commit()
    self.session.refresh(session_obj)

    self.publish_event(session_obj.id, {"type": "patch", "turn": user_turn})
    self._publish_status(session_obj)
    self._publish_runtime_delta(session_obj)
    self.publish_snapshot(session_obj.id)

    if async_mode:
        worker = threading.Thread(
            target=self.run_background_worker,
            kwargs={
                "assistant_session_id": session_obj.id,
                "user_id": user.id,
                "content": content_text,
                "context": context or {},
                "target": normalized_target,
                "attachments": normalized_attachments,
            },
            daemon=True,
        )
        worker.start()
        return {"snapshot": self.get_snapshot(session_obj=session_obj), "queued": True}

    result = self._execute_message(
        assistant_session_id=session_obj.id,
        user_id=user.id,
        content=content_text,
        context=context or {},
        target=normalized_target,
        attachments=normalized_attachments,
    )
    return {"snapshot": self.get_snapshot_by_id(session_obj.id), "queued": False, **result}


def _run_background_worker(
    cls,
    *,
    assistant_session_id: int,
    user_id: int,
    content: str,
    context: Dict[str, Any],
    target: Optional[str],
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> None:
    with session_scope() as db_session:
        service = cls(db_session)
        try:
            service._execute_message(
                assistant_session_id=assistant_session_id,
                user_id=user_id,
                content=content,
                context=context,
                target=target,
                attachments=attachments or [],
            )
        except HTTPException:
            pass
        except Exception:
            pass


def _execute_message(
    self,
    *,
    assistant_session_id: int,
    user_id: int,
    content: str,
    context: Dict[str, Any],
    target: Optional[str],
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    session_obj = self.session.get(AssistantSession, assistant_session_id)
    user = self.session.get(User, user_id)
    if not session_obj or not user:
        return {}
    if session_obj.status == "interrupted":
        self.publish_snapshot(session_obj.id)
        return {"interrupted": True}

    try:
        normalized_target = _normalize_target(target, session_obj)
        if normalized_target == "external":
            result = self._execute_external_message(
                session_obj=session_obj,
                user=user,
                content=content,
                attachments=attachments or [],
            )
        else:
            result = self._execute_internal_director_message(
                session_obj=session_obj,
                user=user,
                content=content,
                context=context or {},
                attachments=attachments or [],
            )

        self.session.refresh(session_obj)
        if session_obj.status == "interrupted":
            self.publish_snapshot(session_obj.id)
            return {"interrupted": True}

        project_changes = result.get("project_changes")
        if project_changes is None:
            project_changes = self._extract_project_changes_from_turn(result.get("assistant_turn"))

        clear_keys = ["draft_turn", "tool_activity", "skill_hint", "running_started_at"]
        pending_question_wizard = result.get("pending_question_wizard")
        execution_plan = result.get("execution_plan") if isinstance(result.get("execution_plan"), dict) else {}
        status_detail = ""
        if pending_question_wizard:
            status_detail = "等待你补充信息"
        elif result.get("question_event"):
            status_detail = "等待你确认"
            clear_keys.append("pending_question_wizard")
        else:
            clear_keys.append("pending_question_wizard")
        if not execution_plan:
            clear_keys.extend([
                "execution_stage",
                "selected_panels",
                "resolved_model_choice",
                "selection_reason",
                "resume_hint",
            ])

        self._update_runtime_state(
            session_obj,
            project_changes=project_changes or [],
            status_detail=status_detail,
            pending_question_wizard=pending_question_wizard if pending_question_wizard else None,
            execution_stage=execution_plan.get("execution_stage"),
            selected_panels=execution_plan.get("selected_panels"),
            resolved_model_choice=execution_plan.get("resolved_model_choice"),
            selection_reason=execution_plan.get("selection_reason"),
            resume_hint=execution_plan.get("resume_hint"),
            clear_keys=clear_keys,
            commit=False,
        )
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.session.refresh(session_obj)

        if result.get("bridge_event"):
            self.publish_event(session_obj.id, result["bridge_event"])
        if result.get("question_event"):
            self.publish_event(session_obj.id, result["question_event"])
        if project_changes:
            self.publish_event(session_obj.id, {"type": "project_change", "project_changes": project_changes})
        self._publish_status(session_obj)
        self._publish_runtime_delta(session_obj)
        self.publish_snapshot(session_obj.id)
        return result
    except HTTPException as exc:
        error_turn = self._append_error_turn(session_obj=session_obj, error_text=self._http_exception_message(exc))
        self._update_runtime_state(
            session_obj,
            project_changes=[],
            status_detail=self._http_exception_message(exc),
            clear_keys=[
                "draft_turn",
                "tool_activity",
                "pending_question_wizard",
                "skill_hint",
                "running_started_at",
                "execution_stage",
                "selected_panels",
                "resolved_model_choice",
                "selection_reason",
                "resume_hint",
            ],
            commit=False,
        )
        session_obj.status = "error"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": error_turn})
        self._publish_status(session_obj)
        self._publish_runtime_delta(session_obj)
        self.publish_snapshot(session_obj.id)
        raise
    except Exception as exc:
        error_turn = self._append_error_turn(session_obj=session_obj, error_text=str(exc))
        self._update_runtime_state(
            session_obj,
            project_changes=[],
            status_detail=str(exc),
            clear_keys=[
                "draft_turn",
                "tool_activity",
                "pending_question_wizard",
                "skill_hint",
                "running_started_at",
                "execution_stage",
                "selected_panels",
                "resolved_model_choice",
                "selection_reason",
                "resume_hint",
            ],
            commit=False,
        )
        session_obj.status = "error"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": error_turn})
        self._publish_status(session_obj)
        self._publish_runtime_delta(session_obj)
        self.publish_snapshot(session_obj.id)
        raise


def answer_question(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    question_key: str,
    action: str,
    answer: Optional[str] = None,
    modifications: Optional[Dict[str, Any]] = None,
    answers: Optional[Dict[str, Any]] = None,
    async_mode: bool = True,
) -> Dict[str, Any]:
    question = self.session.exec(
        select(AssistantPendingQuestion).where(
            AssistantPendingQuestion.session_id == session_obj.id,
            AssistantPendingQuestion.question_key == question_key,
            AssistantPendingQuestion.status == "pending",
        )
    ).first()
    if not question:
        raise HTTPException(status_code=404, detail="待处理问题不存在或已完成")

    payload = _json_loads(question.payload_json, {})
    metadata = payload.get("metadata") or {}
    action_value = str(action or "confirm").strip().lower() or "confirm"
    answer_payload = {
        "action": action_value,
        "answer": answer,
        "modifications": modifications or {},
        "answers": answers or {},
    }

    question.status = "answered"
    question.answer_json = _json_dumps(answer_payload)
    question.updated_at = _utc_now()
    question.answered_at = _utc_now()
    self.session.add(question)

    should_continue = action_value != "reject" and metadata.get("source") in {"director_legacy", "bridge_import"}
    session_obj.status = "running" if should_continue else "completed"
    session_obj.updated_at = _utc_now()
    runtime_started_at = _iso(_utc_now()) if should_continue else None
    self._update_runtime_state(
        session_obj,
        running_started_at=runtime_started_at,
        status_detail="正在继续执行" if should_continue else "",
        clear_keys=["pending_question_wizard"],
        commit=False,
    )
    self.session.add(session_obj)
    self.session.commit()

    self._publish_status(session_obj)
    self._publish_runtime_delta(session_obj)
    self.publish_snapshot(session_obj.id)

    if async_mode and should_continue:
        worker = threading.Thread(
            target=self.run_answer_question_worker,
            kwargs={
                "assistant_session_id": session_obj.id,
                "user_id": user.id,
                "question_id": question.id,
                "action": action_value,
                "answer": answer,
                "modifications": modifications or {},
                "answers": answers or {},
            },
            daemon=True,
        )
        worker.start()
        return {"snapshot": self.get_snapshot(session_obj=session_obj), "queued": True}

    return self._continue_answer_question(
        session_obj=session_obj,
        user=user,
        payload=payload,
        action=action_value,
        answer=answer,
        modifications=modifications or {},
        answers=answers or {},
    )


def _run_answer_question_worker(
    cls,
    *,
    assistant_session_id: int,
    user_id: int,
    question_id: int,
    action: str,
    answer: Optional[str] = None,
    modifications: Optional[Dict[str, Any]] = None,
    answers: Optional[Dict[str, Any]] = None,
) -> None:
    with session_scope() as db_session:
        service = cls(db_session)
        session_obj = None
        try:
            session_obj = db_session.get(AssistantSession, assistant_session_id)
            user = db_session.get(User, user_id)
            question = db_session.get(AssistantPendingQuestion, question_id)
            if not session_obj or not user or not question:
                return

            payload = _json_loads(question.payload_json, {})
            service._continue_answer_question(
                session_obj=session_obj,
                user=user,
                payload=payload,
                action=action,
                answer=answer,
                modifications=modifications or {},
                answers=answers or {},
            )
        except HTTPException as exc:
            if session_obj:
                error_turn = service._append_error_turn(session_obj=session_obj, error_text=service._http_exception_message(exc))
                service._update_runtime_state(
                    session_obj,
                    status_detail=service._http_exception_message(exc),
                    clear_keys=["draft_turn", "tool_activity", "pending_question_wizard", "skill_hint", "running_started_at"],
                    commit=False,
                )
                session_obj.status = "error"
                session_obj.updated_at = _utc_now()
                db_session.add(session_obj)
                db_session.commit()
                service.publish_event(session_obj.id, {"type": "patch", "turn": error_turn})
                service._publish_status(session_obj)
                service._publish_runtime_delta(session_obj)
                service.publish_snapshot(session_obj.id)
        except Exception as exc:
            if session_obj:
                error_turn = service._append_error_turn(session_obj=session_obj, error_text=str(exc))
                service._update_runtime_state(
                    session_obj,
                    status_detail=str(exc),
                    clear_keys=["draft_turn", "tool_activity", "pending_question_wizard", "skill_hint", "running_started_at"],
                    commit=False,
                )
                session_obj.status = "error"
                session_obj.updated_at = _utc_now()
                db_session.add(session_obj)
                db_session.commit()
                service.publish_event(session_obj.id, {"type": "patch", "turn": error_turn})
                service._publish_status(session_obj)
                service._publish_runtime_delta(session_obj)
                service.publish_snapshot(session_obj.id)


def _continue_answer_question(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    payload: Dict[str, Any],
    action: str,
    answer: Optional[str],
    modifications: Dict[str, Any],
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = payload.get("metadata") or {}

    if metadata.get("source") == "director_legacy":
        result = self._answer_director_question(
            session_obj=session_obj,
            user=user,
            legacy_message_id=metadata.get("legacy_message_id"),
            action=action,
            modifications=modifications,
        )
        self._update_runtime_state(
            session_obj,
            status_detail="",
            clear_keys=["draft_turn", "tool_activity", "pending_question_wizard", "skill_hint", "running_started_at"],
            commit=False,
        )
        self._publish_status(session_obj)
        self._publish_runtime_delta(session_obj)
        self.publish_snapshot(session_obj.id)
        return result

    if metadata.get("source") == "assistant_generate_panel_image":
        result = self._answer_generate_panel_image_question(
            session_obj=session_obj,
            user=user,
            action=action,
            question_payload=payload,
            answers=answers or {},
        )
        self._update_runtime_state(
            session_obj,
            status_detail="",
            clear_keys=["draft_turn", "tool_activity", "pending_question_wizard", "skill_hint", "running_started_at"],
            commit=False,
        )
        self._publish_status(session_obj)
        self._publish_runtime_delta(session_obj)
        self.publish_snapshot(session_obj.id)
        return result

    if metadata.get("source") == "assistant_generate_panel_video":
        result = self._answer_generate_panel_video_question(
            session_obj=session_obj,
            user=user,
            action=action,
            question_payload=payload,
            answers=answers or {},
        )
        execution_plan = result.get("execution_plan") if isinstance(result.get("execution_plan"), dict) else {}
        self._update_runtime_state(
            session_obj,
            status_detail="",
            execution_stage=execution_plan.get("execution_stage"),
            selected_panels=execution_plan.get("selected_panels"),
            resolved_model_choice=execution_plan.get("resolved_model_choice"),
            selection_reason=execution_plan.get("selection_reason"),
            resume_hint=execution_plan.get("resume_hint"),
            clear_keys=["draft_turn", "tool_activity", "pending_question_wizard", "skill_hint", "running_started_at"],
            commit=False,
        )
        self._publish_status(session_obj)
        self._publish_runtime_delta(session_obj)
        self.publish_snapshot(session_obj.id)
        return result

    if metadata.get("source") == "assistant_generate_episode_dubbing":
        result = self._answer_generate_episode_dubbing_question(
            session_obj=session_obj,
            user=user,
            action=action,
            question_payload=payload,
            answers=answers or {},
        )
        self._update_runtime_state(
            session_obj,
            status_detail="",
            clear_keys=["draft_turn", "tool_activity", "pending_question_wizard", "skill_hint", "running_started_at"],
            commit=False,
        )
        self._publish_status(session_obj)
        self._publish_runtime_delta(session_obj)
        self.publish_snapshot(session_obj.id)
        return result

    if metadata.get("source") == "bridge_import":
        result = self._answer_bridge_import_question(
            session_obj=session_obj,
            user=user,
            action=action,
            question_payload=payload,
        )
        self._update_runtime_state(
            session_obj,
            status_detail="",
            clear_keys=["draft_turn", "tool_activity", "pending_question_wizard", "skill_hint", "running_started_at"],
            commit=False,
        )
        self._publish_status(session_obj)
        self._publish_runtime_delta(session_obj)
        self.publish_snapshot(session_obj.id)
        return result

    question_data = {
        "title": payload.get("wizard", {}).get("title") if isinstance(payload.get("wizard"), dict) else payload.get("title"),
        "prompt": payload.get("prompt") or "",
    }
    assistant_turn = self._build_question_resolved_turn(
        action=action,
        question_data=question_data,
        answers=answers or {},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    session_obj.status = "completed"
    session_obj.updated_at = _utc_now()
    self._update_runtime_state(
        session_obj,
        status_detail="",
        clear_keys=[
            "draft_turn",
            "tool_activity",
            "pending_question_wizard",
            "skill_hint",
            "running_started_at",
            "execution_stage",
            "selected_panels",
            "resolved_model_choice",
            "selection_reason",
            "resume_hint",
        ],
        commit=False,
    )
    self.session.add(session_obj)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    self._publish_status(session_obj)
    self._publish_runtime_delta(session_obj)
    self.publish_snapshot(session_obj.id)
    return {"snapshot": self.get_snapshot(session_obj=session_obj)}


def _panel_option_label(panel: Panel) -> str:
    summary = (
        str(panel.segment_summary or "").strip()
        or str(panel.narration_text or "").strip()
        or str(panel.dialogue_text or "").strip()
        or str(panel.original_text or "").strip()
    )
    if len(summary) > 28:
        summary = "{0}...".format(summary[:28].rstrip())
    if summary:
        return "第{0}镜 · {1}".format(panel.sequence_num, summary)
    return "第{0}镜".format(panel.sequence_num)


def _panel_has_image(panel: Panel) -> bool:
    return bool(str(panel.image_url or panel.file_url or "").strip())


def _panel_aspect_ratio(panel: Panel) -> str:
    storyboard_mode = str(getattr(panel, "storyboard_mode", "") or "").strip().lower()
    return "16:9" if storyboard_mode == "comic" else "9:16"


def _attachment_media_urls(attachments: Optional[List[Dict[str, Any]]]) -> Dict[str, List[str]]:
    return attachment_media_urls(attachments)


def _coerce_bool(value: Any, default: bool = False) -> bool:
    return coerce_bool(value, default)


def _format_selected_panel_display(panels: List[Panel]) -> str:
    selected = build_selected_panels_payload(panels)
    sequences = [int(item.get("panel_sequence") or 0) for item in selected if int(item.get("panel_sequence") or 0) > 0]
    if not sequences:
        return "当前分镜"
    if len(sequences) == 1:
        return "第 {0} 镜".format(sequences[0])
    if sequences == list(range(sequences[0], sequences[-1] + 1)):
        return "第 {0}-{1} 镜".format(sequences[0], sequences[-1])
    return "第 {0} 镜".format(" / ".join(str(value) for value in sequences))


def _merge_video_prompt(panel: Panel, prompt_override: Optional[str]) -> str:
    base_prompt = _derive_panel_video_prompt(panel)
    extra_prompt = str(prompt_override or "").strip()
    if base_prompt and extra_prompt:
        return "{0}\n补充要求：{1}".format(base_prompt, extra_prompt)
    return extra_prompt or base_prompt


def _panel_latest_image(panel: Panel) -> str:
    return str(get_panel_latest_image(panel) or panel.file_url or "").strip()


def _build_panel_video_payload(
    self,
    *,
    session_obj: AssistantSession,
    panel: Panel,
    prompt_override: Optional[str],
    model_code: str,
    generation_type: str,
    duration: int,
    resolution: str,
    audio_enabled: bool,
    attachment_image_urls: List[str],
    attachment_video_urls: List[str],
) -> Dict[str, Any]:
    prompt = _merge_video_prompt(panel, prompt_override)
    if not prompt:
        raise HTTPException(status_code=400, detail="当前分镜缺少可用视频提示词，请先补充分镜描述或在向导里填写补充要求")

    latest_image = _panel_latest_image(panel)
    panel_reference_images = [
        str(item).strip()
        for item in (get_panel_reference_images(self.session, panel) or [])
        if str(item).strip()
    ]
    image_refs = [str(item).strip() for item in attachment_image_urls if str(item).strip()]
    video_refs = [str(item).strip() for item in attachment_video_urls if str(item).strip()]
    first_frame = ""
    last_frame = ""

    if generation_type == "image_to_video":
        first_frame = (image_refs[0] if image_refs else latest_image) or ""
        image_refs = [first_frame] if first_frame else []
    elif generation_type == "reference_to_video":
        if not image_refs:
            image_refs = panel_reference_images[:7]
        if not image_refs and latest_image:
            image_refs = [latest_image]
        image_refs = image_refs[:7]
        video_refs = video_refs[:2]
    elif generation_type == "start_end_to_video":
        if len(image_refs) >= 2:
            first_frame = image_refs[0]
            last_frame = image_refs[1]
        else:
            first_frame = latest_image or (image_refs[0] if image_refs else "")
            last_frame = image_refs[1] if len(image_refs) > 1 else ""

    return {
        "ownership_mode": "project",
        "project_id": encode_id(session_obj.script_id),
        "episode_id": encode_id(panel.episode_id),
        "target_type": "panel",
        "target_id": encode_id(panel.id),
        "model_code": model_code,
        "generation_type": generation_type,
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "aspect_ratio": _panel_aspect_ratio(panel),
        "image_refs": image_refs,
        "video_refs": video_refs,
        "first_frame": first_frame,
        "last_frame": last_frame,
        "audio_enabled": audio_enabled,
        "motion_strength": "auto",
    }


def _video_generation_field_options(model_code: str, generation_type: str) -> Dict[str, Any]:
    model = get_video_model_or_none(model_code) or {}
    feature = ((model.get("features") or {}).get(generation_type) if isinstance(model, dict) else None) or {}
    defaults = feature.get("defaults") or {}
    pricing_rules = feature.get("pricing_rules") or []

    duration_values = sorted(
        {
            int(item.get("duration"))
            for item in pricing_rules
            if item.get("duration") not in (None, "")
        }
    )
    resolution_values = [
        value
        for value in ["720p", "1080p", "2k"]
        if value
        in {
            str(item.get("resolution") or "").strip().lower()
            for item in pricing_rules
            if str(item.get("resolution") or "").strip()
        }
    ]

    if not duration_values:
        duration_values = [4, 5, 6, 8, 10, 12]
    if not resolution_values:
        resolution_values = ["720p", "1080p"]

    return {
        "defaults": defaults,
        "duration_options": [{"value": str(item), "label": "{0} 秒".format(item)} for item in duration_values],
        "resolution_options": [{"value": item, "label": item.upper() if item.endswith("k") else item} for item in resolution_values],
    }


def _parse_requested_panel_sequence(content: str) -> Optional[int]:
    text = str(content or "").strip()
    patterns = [
        r"第\s*(\d+)\s*[镜格张幕]",
        r"(?:分镜|镜头)\s*(\d+)",
        r"^/出图\s+(\d+)\b",
        r"^/视频\s+(\d+)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        try:
            return int(match.group(1))
        except Exception:
            continue
    return None


def _derive_panel_image_prompt(panel: Panel) -> str:
    for value in [
        panel.prompt,
        panel.prompt_zh,
        panel.image_framing,
        panel.composition,
        panel.original_text,
        panel.narration_text,
        panel.dialogue_text,
    ]:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _panel_has_video(panel: Panel) -> bool:
    if str(panel.video_url or "").strip():
        return True
    return str(getattr(panel, "video_history_json", "") or "").strip() not in {"", "[]", "null"}


def _panel_video_duration(panel: Panel) -> int:
    storyboard_mode = str(getattr(panel, "storyboard_mode", "") or "").strip().lower()
    return 8 if storyboard_mode == "comic" else 6


def _derive_panel_video_prompt(panel: Panel) -> str:
    for value in [
        panel.video_prompt,
        panel.prompt,
        panel.prompt_zh,
        panel.image_framing,
        panel.composition,
        panel.original_text,
        panel.narration_text,
        panel.dialogue_text,
    ]:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _derive_episode_dubbing_text(self, episode: Optional[Episode]) -> str:
    if not episode:
        return ""
    source_text = str(getattr(episode, "source_text", "") or "").strip()
    if source_text:
        return source_text

    panels = self.session.exec(
        select(Panel)
        .where(Panel.episode_id == episode.id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    lines: List[str] = []
    for panel in panels:
        storyboard_mode = str(getattr(panel, "storyboard_mode", "") or "").strip().lower()
        text = (
            str(panel.dialogue_text or "").strip()
            if storyboard_mode == "comic"
            else str(panel.narration_text or "").strip()
        )
        if not text:
            text = str(panel.original_text or "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines).strip()


def _infer_dubbing_ability(content: str, script_text: str, episode: Optional[Episode]) -> str:
    lowered = str(content or "").strip().lower()
    text = str(script_text or "").strip()
    storyboard_mode = str(getattr(episode, "storyboard_mode", "") or "").strip().lower()
    long_text = len(text) >= 160 or text.count("\n") >= 2
    if any(keyword in lowered for keyword in ["旁白", "解说", "朗读", "念出来"]):
        return ABILITY_NARRATION if len(text) >= 80 or storyboard_mode == "commentary" else ABILITY_REALTIME
    if any(keyword in lowered for keyword in ["对白", "台词", "配音"]):
        return ABILITY_REALTIME if len(text) <= 220 else ABILITY_NARRATION
    if storyboard_mode == "commentary":
        return ABILITY_NARRATION if long_text or len(text) >= 80 else ABILITY_REALTIME
    return ABILITY_NARRATION if long_text else ABILITY_REALTIME


def _find_recent_audio_choice(self, *, session_obj: AssistantSession, user: User) -> Dict[str, Any]:
    records = self.session.exec(
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
        voice_id = str(params_public.get("voice_id") or "").strip()
        if not voice_id:
            continue
        return {
            "voice_id": voice_id,
            "voice_source_type": str(params_public.get("voice_source_type") or VOICE_SOURCE_SYSTEM).strip() or VOICE_SOURCE_SYSTEM,
            "ability_type": str(params_public.get("ability_type") or "").strip(),
            "tier_code": str(params_public.get("tier_code") or "").strip(),
        }
    return {}


def _load_voice_assets_for_wizard(self, *, user: User, limit: int = 40) -> List[Dict[str, Any]]:
    try:
        payload = list_voice_assets(self.session, user=user)
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
        voice_id = str(item.get("voice_id") or "").strip()
        if not voice_id or voice_id in seen_ids:
            continue
        seen_ids.add(voice_id)
        display_name = str(item.get("display_name") or voice_id).strip()
        source_label = str(item.get("source_label") or "").strip()
        style_label = str(item.get("style_label") or "").strip()
        label_parts = [display_name]
        if source_label:
            label_parts.append(source_label)
        if style_label:
            label_parts.append(style_label)
        result.append(
            {
                "voice_id": voice_id,
                "source_type": str(item.get("source_type") or VOICE_SOURCE_SYSTEM).strip() or VOICE_SOURCE_SYSTEM,
                "label": " · ".join(label_parts[:3]),
            }
        )
        if len(result) >= limit:
            break
    return result


def _resolve_voice_source_type(
    voice_assets: List[Dict[str, Any]],
    *,
    voice_id: Optional[str],
    fallback: Optional[str] = None,
) -> str:
    resolved_voice_id = str(voice_id or "").strip()
    for item in voice_assets or []:
        if str(item.get("voice_id") or "").strip() == resolved_voice_id:
            return str(item.get("source_type") or fallback or VOICE_SOURCE_SYSTEM).strip() or VOICE_SOURCE_SYSTEM
    return str(fallback or VOICE_SOURCE_SYSTEM).strip() or VOICE_SOURCE_SYSTEM


def _create_panel_image_wizard(
    self,
    *,
    session_obj: AssistantSession,
    title: str,
    description: str,
    panels: List[Panel],
    candidates: List[Panel],
    selected_panel: Optional[Panel],
    prompt_required: bool,
) -> Dict[str, Any]:
    default_panel = selected_panel or (candidates[0] if candidates else (panels[0] if panels else None))
    selectable_panels = candidates or panels
    steps: List[Dict[str, Any]] = []

    if not selected_panel:
        steps.append(
            {
                "id": "panel_sequence",
                "label": "选择分镜",
                "description": "请选择这次要处理的目标分镜。",
                "type": "select",
                "required": True,
                "default": str(default_panel.sequence_num) if default_panel else "",
                "options": [
                    {"value": str(item.sequence_num), "label": _panel_option_label(item)}
                    for item in selectable_panels[:40]
                ],
            }
        )

    steps.append(
        {
            "id": "prompt_override",
            "label": "补充提示词",
            "description": "可补充角色、场景、情绪或镜头风格；留空则使用分镜现有提示词。",
            "type": "textarea",
            "required": bool(prompt_required),
            "placeholder": "例如：雨夜古堡走廊，冷色电影光，人物回头警觉特写",
            "default": "",
        }
    )
    steps.append(
        {
            "id": "model",
            "label": "图片模型",
            "description": "统一使用新的图片模型目录；nano-banana 系列优先走 RunningHub。",
            "type": "select",
            "required": True,
            "default": "nano-banana-pro",
            "options": [
                {"value": "nano-banana-2", "label": "nano-banana-2"},
                {"value": "nano-banana-2-低价版", "label": "nano-banana-2-低价版"},
                {"value": "nano-banana-pro", "label": "nano-banana-pro"},
                {"value": "nano-banana-pro-低价版", "label": "nano-banana-pro-低价版"},
                {"value": "gpt-image-2-fast", "label": "gpt-image-2-fast"},
                {"value": "gpt-image-2", "label": "gpt-image-2"},
            ],
        }
    )
    steps.append(
        {
            "id": "resolution",
            "label": "画质",
            "description": "默认 2K；分辨率越高，消耗越高。",
            "type": "select",
            "required": True,
            "default": "2k",
            "options": [
                {"value": "1k", "label": "1K"},
                {"value": "2k", "label": "2K"},
                {"value": "4k", "label": "4K"},
            ],
        }
    )

    question = AssistantPendingQuestion(
        session_id=session_obj.id,
        question_type="wizard",
        status="pending",
        title=title,
        prompt_text=description,
        payload_json=_json_dumps(
            {
                "preview": {
                    "total_panels": len(panels),
                    "panels_without_images": len(candidates),
                    "selected_panel_sequence": default_panel.sequence_num if default_panel else None,
                },
                "wizard": {
                    "title": title,
                    "description": description,
                    "submit_label": "提交出图任务",
                    "cancel_label": "取消",
                    "steps": steps,
                },
                "metadata": {
                    "source": "assistant_generate_panel_image",
                    "default_panel_sequence": default_panel.sequence_num if default_panel else None,
                },
            }
        ),
        answer_json=_json_dumps({}),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    self.session.add(question)
    self.session.flush()

    assistant_turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": "生成图片",
                "description": description,
                "task_type": "generate_panel_image",
                "status": "pending",
                "preview": {
                    "total_panels": len(panels),
                    "panels_without_images": len(candidates),
                },
            },
            {
                "id": uuid.uuid4().hex,
                "type": "question",
                "question_id": question.question_key,
                "question_type": "wizard",
                "title": title,
                "prompt": description,
                "options": [],
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_panel_image"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "question_event": {
            "type": "question",
            "question": {
                "question_id": question.question_key,
                "question_type": "wizard",
            },
        },
        "pending_question_wizard": self._serialize_pending_question(question),
        "project_changes": [],
    }


def _submit_panel_image_generation(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    panel: Panel,
    prompt_override: Optional[str] = None,
    model: Optional[str] = None,
    resolution: Optional[str] = None,
) -> Dict[str, Any]:
    team = self.session.get(Team, session_obj.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="当前会话所属团队不存在")

    prompt = str(prompt_override or "").strip() or _derive_panel_image_prompt(panel)
    if not prompt:
        raise HTTPException(status_code=400, detail="当前分镜缺少可用提示词，请先补充分镜提示词后再试")

    resolved_model = normalize_image_model_code(model or "nano-banana-pro")

    resolved_resolution = str(resolution or "2k").strip().lower()
    if resolved_resolution not in {"1k", "2k", "4k"}:
        resolved_resolution = "2k"

    reference_images = get_panel_reference_images(self.session, panel)
    payload = {
        "ownership_mode": "project",
        "project_id": encode_id(session_obj.script_id),
        "episode_id": encode_id(panel.episode_id),
        "target_type": "panel",
        "target_id": encode_id(panel.id),
        "mode": "image_to_image" if reference_images else "text_to_image",
        "model_code": resolved_model,
        "resolution": resolved_resolution,
        "aspect_ratio": _panel_aspect_ratio(panel),
        "prompt": prompt,
        "reference_images": reference_images,
    }

    background_tasks = BackgroundTasks()
    record = submit_image_generation(
        self.session,
        background_tasks=background_tasks,
        user=user,
        team=team,
        payload=payload,
    )
    record = _mark_generation_record_source(self, session_obj=session_obj, record=record)

    threading.Thread(target=_run_image_generation_job, args=(record.id,), daemon=True).start()

    tool_use_id = uuid.uuid4().hex
    summary = "已为第 {0} 镜提交图片生成任务。".format(panel.sequence_num)
    refresh_hints = {"panels": True}
    result_payload = {
        "task_id": str(record.task_id or ""),
        "record_id": encode_id(record.id) if record.id else None,
        "panel_id": encode_id(panel.id) if panel.id else None,
        "panel_sequence": panel.sequence_num,
        "status": str(record.status or "queued"),
        "estimate_points": record.estimate_points,
        "model": resolved_model,
        "resolution": resolved_resolution,
        "aspect_ratio": payload["aspect_ratio"],
        "reference_image_count": len(reference_images),
        "source": _generation_record_source(session_obj),
        "refresh_hints": refresh_hints,
        "summary": summary,
    }
    assistant_turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "text",
                "text": "{0} 任务已进入队列，你可以在任务面板里继续跟踪进度。".format(summary),
            },
            {
                "id": tool_use_id,
                "type": "tool_use",
                "tool_name": "generate_panel_image",
                "title": "提交图片生成任务",
                "status": "completed",
                "description": "已读取分镜提示词、画幅和参考图，并提交到图片生成任务队列。",
                "task_id": str(record.task_id or ""),
            },
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": "图片任务已提交",
                "description": "第 {0} 镜正在排队出图。".format(panel.sequence_num),
                "task_type": "generate_panel_image",
                "status": "running",
                "task_id": str(record.task_id or ""),
            },
            {
                "id": uuid.uuid4().hex,
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "tool_name": "generate_panel_image",
                "summary": summary,
                "task_id": str(record.task_id or ""),
                "result": result_payload,
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_panel_image"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "project_changes": [
            {
                "block_id": tool_use_id,
                "tool_name": "generate_panel_image",
                "summary": summary,
                "refresh_hints": refresh_hints,
            }
        ],
    }


def _answer_generate_panel_image_question(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    action: str,
    question_payload: Dict[str, Any],
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if action == "reject":
        turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "interrupt_notice",
                    "text": "已取消本次出图任务，不会继续提交生成。",
                }
            ],
        )
        self._insert_turn_event(session_obj=session_obj, turn=turn)
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": turn})
        return {"snapshot": self.get_snapshot(session_obj=session_obj)}

    if not session_obj.episode_id:
        raise HTTPException(status_code=400, detail="请先进入具体剧集，再让 AI 帮你出图")

    metadata = question_payload.get("metadata") or {}
    answer_data = answers or {}
    requested_sequence = answer_data.get("panel_sequence")
    if requested_sequence in (None, ""):
        requested_sequence = metadata.get("default_panel_sequence")
    try:
        requested_sequence_int = int(requested_sequence)
    except Exception:
        raise HTTPException(status_code=400, detail="请选择有效的分镜镜号")

    panels = self.session.exec(
        select(Panel)
        .where(Panel.episode_id == session_obj.episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    panel = next((item for item in panels if int(item.sequence_num or 0) == requested_sequence_int), None)
    if not panel:
        raise HTTPException(status_code=404, detail="目标分镜不存在或已被删除")

    result = self._submit_panel_image_generation(
        session_obj=session_obj,
        user=user,
        panel=panel,
        prompt_override=answer_data.get("prompt_override"),
        model=answer_data.get("model"),
        resolution=answer_data.get("resolution"),
    )
    session_obj.status = "completed"
    session_obj.updated_at = _utc_now()
    self.session.add(session_obj)
    self.session.commit()
    return {"snapshot": self.get_snapshot(session_obj=session_obj), **result}


def _execute_generate_panel_image_skill(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    content: str,
) -> Dict[str, Any]:
    if not session_obj.episode_id:
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "请先选中一个具体剧集，我才能按当前分镜范围为你提交出图任务。",
                }
            ],
            metadata={"source": "assistant_skill", "skill": "generate_panel_image"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {"assistant_turn": assistant_turn, "project_changes": []}

    panels = self.session.exec(
        select(Panel)
        .where(Panel.episode_id == session_obj.episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    if not panels:
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "当前剧集还没有分镜，先拆分镜或写分镜后，我再帮你出图。",
                }
            ],
            metadata={"source": "assistant_skill", "skill": "generate_panel_image"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {"assistant_turn": assistant_turn, "project_changes": []}

    candidates = [panel for panel in panels if not _panel_has_image(panel)]
    selected_panel = None
    requested_sequence = _parse_requested_panel_sequence(content)
    if requested_sequence is not None:
        selected_panel = next((item for item in panels if int(item.sequence_num or 0) == requested_sequence), None)
        if not selected_panel:
            raise HTTPException(status_code=404, detail="没有找到你指定的分镜镜号")
    elif len(candidates) == 1:
        selected_panel = candidates[0]

    if not candidates and not selected_panel:
        selected_panel = panels[0]

    if selected_panel and _derive_panel_image_prompt(selected_panel):
        return self._submit_panel_image_generation(
            session_obj=session_obj,
            user=user,
            panel=selected_panel,
        )

    pending_count = len(candidates)
    description = (
        "当前剧集共有 {0} 个分镜，其中 {1} 个还没有图片。请补充镜号和生成参数后继续。".format(len(panels), pending_count)
        if pending_count
        else "当前剧集的分镜都已有图片；如需重绘，请选择目标镜号并补充参数。"
    )
    return _create_panel_image_wizard(
        self,
        session_obj=session_obj,
        title="补充分镜出图参数",
        description=description,
        panels=panels,
        candidates=candidates,
        selected_panel=selected_panel,
        prompt_required=not bool(_derive_panel_image_prompt(selected_panel)) if selected_panel else False,
    )


def _create_panel_video_wizard(
    self,
    *,
    session_obj: AssistantSession,
    title: str,
    description: str,
    panels: List[Panel],
    candidates: List[Panel],
    selected_panel: Optional[Panel],
    prompt_required: bool,
) -> Dict[str, Any]:
    default_panel = selected_panel or (candidates[0] if candidates else (panels[0] if panels else None))
    selectable_panels = candidates or panels
    steps: List[Dict[str, Any]] = []

    if not selected_panel:
        steps.append(
            {
                "id": "panel_sequence",
                "label": "选择分镜",
                "description": "请选择这次要处理的目标分镜。",
                "type": "select",
                "required": True,
                "default": str(default_panel.sequence_num) if default_panel else "",
                "options": [
                    {"value": str(item.sequence_num), "label": _panel_option_label(item)}
                    for item in selectable_panels[:40]
                ],
            }
        )

    steps.extend(
        [
            {
                "id": "prompt_override",
                "label": "补充视频提示词",
                "description": "可补充动作、镜头运动、表演节奏；留空则使用分镜现有视频提示词。",
                "type": "textarea",
                "required": bool(prompt_required),
                "placeholder": "例如：人物缓慢转身，镜头轻推近，衣摆和发丝随风摆动",
                "default": "",
            },
            {
                "id": "model_code",
                "label": "视频模型",
                "description": "快速版更适合预演，稳定版画面更稳。",
                "type": "select",
                "required": True,
                "default": "seedance_v15_fast",
                "options": [
                    {"value": "seedance_v15_fast", "label": "快速版"},
                    {"value": "seedance_v15_pro", "label": "稳定版"},
                ],
            },
            {
                "id": "duration",
                "label": "视频时长",
                "description": "默认会按当前分镜模式带出推荐时长。",
                "type": "select",
                "required": True,
                "default": str(_panel_video_duration(default_panel)) if default_panel else "6",
                "options": [
                    {"value": "4", "label": "4 秒"},
                    {"value": "5", "label": "5 秒"},
                    {"value": "6", "label": "6 秒"},
                    {"value": "8", "label": "8 秒"},
                    {"value": "10", "label": "10 秒"},
                    {"value": "12", "label": "12 秒"},
                ],
            },
            {
                "id": "resolution",
                "label": "清晰度",
                "description": "默认 720p；1080p 更清晰但成本更高。",
                "type": "select",
                "required": True,
                "default": "720p",
                "options": [
                    {"value": "720p", "label": "720p"},
                    {"value": "1080p", "label": "1080p"},
                ],
            },
        ]
    )

    question = AssistantPendingQuestion(
        session_id=session_obj.id,
        question_type="wizard",
        status="pending",
        title=title,
        prompt_text=description,
        payload_json=_json_dumps(
            {
                "preview": {
                    "total_panels": len(panels),
                    "panels_without_videos": len(candidates),
                    "selected_panel_sequence": default_panel.sequence_num if default_panel else None,
                },
                "wizard": {
                    "title": title,
                    "description": description,
                    "submit_label": "提交视频任务",
                    "cancel_label": "取消",
                    "steps": steps,
                },
                "metadata": {
                    "source": "assistant_generate_panel_video",
                    "default_panel_sequence": default_panel.sequence_num if default_panel else None,
                },
            }
        ),
        answer_json=_json_dumps({}),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    self.session.add(question)
    self.session.flush()

    assistant_turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": "生成视频",
                "description": description,
                "task_type": "generate_panel_video",
                "status": "pending",
                "preview": {
                    "total_panels": len(panels),
                    "panels_without_videos": len(candidates),
                },
            },
            {
                "id": uuid.uuid4().hex,
                "type": "question",
                "question_id": question.question_key,
                "question_type": "wizard",
                "title": title,
                "prompt": description,
                "options": [],
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "question_event": {
            "type": "question",
            "question": {
                "question_id": question.question_key,
                "question_type": "wizard",
            },
        },
        "pending_question_wizard": self._serialize_pending_question(question),
        "project_changes": [],
    }


def _submit_panel_video_generation(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    panel: Panel,
    prompt_override: Optional[str] = None,
    model_code: Optional[str] = None,
    duration: Optional[Any] = None,
    resolution: Optional[str] = None,
) -> Dict[str, Any]:
    team = self.session.get(Team, session_obj.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="当前会话所属团队不存在")

    prompt = str(prompt_override or "").strip() or _derive_panel_video_prompt(panel)
    if not prompt:
        raise HTTPException(status_code=400, detail="当前分镜缺少可用视频提示词，请先补充分镜描述后再试")

    resolved_model_code = str(model_code or "seedance_v15_fast").strip().lower()
    if resolved_model_code not in {"seedance_v15_fast", "seedance_v15_pro"}:
        resolved_model_code = "seedance_v15_fast"

    try:
        resolved_duration = int(duration or _panel_video_duration(panel))
    except Exception:
        resolved_duration = _panel_video_duration(panel)
    if resolved_duration not in {4, 5, 6, 8, 10, 12}:
        resolved_duration = _panel_video_duration(panel)

    resolved_resolution = str(resolution or "720p").strip().lower()
    if resolved_resolution not in {"720p", "1080p"}:
        resolved_resolution = "720p"

    latest_image = str(get_panel_latest_image(panel) or panel.file_url or "").strip()
    generation_type = "image_to_video" if latest_image else "text_to_video"
    payload = {
        "ownership_mode": "project",
        "project_id": encode_id(session_obj.script_id),
        "episode_id": encode_id(panel.episode_id),
        "target_type": "panel",
        "target_id": encode_id(panel.id),
        "model_code": resolved_model_code,
        "generation_type": generation_type,
        "prompt": prompt,
        "duration": resolved_duration,
        "resolution": resolved_resolution,
        "aspect_ratio": _panel_aspect_ratio(panel),
        "first_frame": latest_image if generation_type == "image_to_video" else "",
        "audio_enabled": False,
    }

    background_tasks = BackgroundTasks()
    record = submit_video_generation(
        self.session,
        background_tasks=background_tasks,
        user=user,
        team=team,
        payload=payload,
    )
    record = _mark_generation_record_source(self, session_obj=session_obj, record=record)

    threading.Thread(target=_run_video_generation_job, args=(record.id,), daemon=True).start()

    tool_use_id = uuid.uuid4().hex
    summary = "已为第 {0} 镜提交视频生成任务。".format(panel.sequence_num)
    refresh_hints = {"panels": True, "canvas": True}
    result_payload = {
        "task_id": str(record.task_id or ""),
        "record_id": encode_id(record.id) if record.id else None,
        "panel_id": encode_id(panel.id) if panel.id else None,
        "panel_sequence": panel.sequence_num,
        "status": str(record.status or "queued"),
        "model_code": resolved_model_code,
        "generation_type": generation_type,
        "duration": resolved_duration,
        "resolution": resolved_resolution,
        "aspect_ratio": payload["aspect_ratio"],
        "has_first_frame": bool(latest_image),
        "source": _generation_record_source(session_obj),
        "refresh_hints": refresh_hints,
        "summary": summary,
    }
    assistant_turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "text",
                "text": "{0} 任务已进入队列，你可以在任务面板里继续跟踪进度。".format(summary),
            },
            {
                "id": tool_use_id,
                "type": "tool_use",
                "tool_name": "generate_panel_video",
                "title": "提交视频生成任务",
                "status": "completed",
                "description": "已整理镜头提示词、时长和参考帧，并提交到视频生成任务队列。",
                "task_id": str(record.task_id or ""),
            },
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": "视频任务已提交",
                "description": "第 {0} 镜正在排队生成视频。".format(panel.sequence_num),
                "task_type": "generate_panel_video",
                "status": "running",
                "task_id": str(record.task_id or ""),
            },
            {
                "id": uuid.uuid4().hex,
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "tool_name": "generate_panel_video",
                "summary": summary,
                "task_id": str(record.task_id or ""),
                "result": result_payload,
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "project_changes": [
            {
                "block_id": tool_use_id,
                "tool_name": "generate_panel_video",
                "summary": summary,
                "refresh_hints": refresh_hints,
            }
        ],
    }


def _answer_generate_panel_video_question(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    action: str,
    question_payload: Dict[str, Any],
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if action == "reject":
        turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "interrupt_notice",
                    "text": "已取消本次视频任务，不会继续提交生成。",
                }
            ],
        )
        self._insert_turn_event(session_obj=session_obj, turn=turn)
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": turn})
        return {"snapshot": self.get_snapshot(session_obj=session_obj)}

    if not session_obj.episode_id:
        raise HTTPException(status_code=400, detail="请先进入具体剧集，再让 AI 帮你生成视频")

    metadata = question_payload.get("metadata") or {}
    answer_data = answers or {}
    requested_sequence = answer_data.get("panel_sequence")
    if requested_sequence in (None, ""):
        requested_sequence = metadata.get("default_panel_sequence")
    try:
        requested_sequence_int = int(requested_sequence)
    except Exception:
        raise HTTPException(status_code=400, detail="请选择有效的分镜镜号")

    panels = self.session.exec(
        select(Panel)
        .where(Panel.episode_id == session_obj.episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    panel = next((item for item in panels if int(item.sequence_num or 0) == requested_sequence_int), None)
    if not panel:
        raise HTTPException(status_code=404, detail="目标分镜不存在或已被删除")

    result = self._submit_panel_video_generation(
        session_obj=session_obj,
        user=user,
        panel=panel,
        prompt_override=answer_data.get("prompt_override"),
        model_code=answer_data.get("model_code"),
        duration=answer_data.get("duration"),
        resolution=answer_data.get("resolution"),
    )
    session_obj.status = "completed"
    session_obj.updated_at = _utc_now()
    self.session.add(session_obj)
    self.session.commit()
    return {"snapshot": self.get_snapshot(session_obj=session_obj), **result}


def _execute_generate_panel_video_skill(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    content: str,
) -> Dict[str, Any]:
    if not session_obj.episode_id:
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "请先选中一个具体剧集，我才能按当前分镜范围为你提交视频任务。",
                }
            ],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {"assistant_turn": assistant_turn, "project_changes": []}

    panels = self.session.exec(
        select(Panel)
        .where(Panel.episode_id == session_obj.episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    if not panels:
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "当前剧集还没有分镜，先拆分镜或写分镜后，我再帮你做视频。",
                }
            ],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {"assistant_turn": assistant_turn, "project_changes": []}

    candidates = [panel for panel in panels if not _panel_has_video(panel)]
    selected_panel = None
    requested_sequence = _parse_requested_panel_sequence(content)
    if requested_sequence is not None:
        selected_panel = next((item for item in panels if int(item.sequence_num or 0) == requested_sequence), None)
        if not selected_panel:
            raise HTTPException(status_code=404, detail="没有找到你指定的分镜镜号")
    elif len(candidates) == 1:
        selected_panel = candidates[0]

    if not candidates and not selected_panel:
        selected_panel = panels[0]

    if selected_panel and _derive_panel_video_prompt(selected_panel):
        return self._submit_panel_video_generation(
            session_obj=session_obj,
            user=user,
            panel=selected_panel,
        )

    pending_count = len(candidates)
    description = (
        "当前剧集共有 {0} 个分镜，其中 {1} 个还没有视频。请补充镜号和生成参数后继续。".format(len(panels), pending_count)
        if pending_count
        else "当前剧集的分镜都已有视频；如需重做，请选择目标镜号并补充参数。"
    )
    return _create_panel_video_wizard(
        self,
        session_obj=session_obj,
        title="补充分镜视频参数",
        description=description,
        panels=panels,
        candidates=candidates,
        selected_panel=selected_panel,
        prompt_required=not bool(_derive_panel_video_prompt(selected_panel)) if selected_panel else False,
    )


def _build_video_execution_plan_payload(
    *,
    execution_stage: str,
    selected_panels: List[Panel],
    model_choice: Optional[Dict[str, Any]] = None,
    selection_reason: str = "",
    resume_hint: str = "",
) -> Dict[str, Any]:
    return build_video_execution_plan_state(
        execution_stage=execution_stage,
        selected_panels=selected_panels,
        model_choice=model_choice,
        selection_reason=selection_reason,
        resume_hint=resume_hint,
    )


def _create_panel_video_wizard_v2(
    self,
    *,
    session_obj: AssistantSession,
    title: str,
    description: str,
    panels: List[Panel],
    candidates: List[Panel],
    selected_panels: List[Panel],
    prompt_required: bool,
    generation_type: str,
    audio_enabled: bool,
    default_model_choice: Optional[Dict[str, Any]],
    attachment_image_urls: Optional[List[str]] = None,
    attachment_video_urls: Optional[List[str]] = None,
) -> Dict[str, Any]:
    selectable_panels = candidates or panels
    default_panel = (selected_panels[0] if selected_panels else None) or (selectable_panels[0] if selectable_panels else None)
    selected_display = _format_selected_panel_display(selected_panels)
    attachment_image_urls = [str(item).strip() for item in (attachment_image_urls or []) if str(item).strip()]
    attachment_video_urls = [str(item).strip() for item in (attachment_video_urls or []) if str(item).strip()]
    default_model = (default_model_choice or {}).get("model") or {}
    default_model_code = str(default_model.get("model_code") or "").strip() or "seedance_v15_fast"
    field_options = resolve_video_generation_field_options(default_model_code, generation_type)
    duration_default = str(field_options["defaults"].get("duration") or (resolve_panel_video_duration(default_panel) if default_panel else 6))
    resolution_default = str(field_options["defaults"].get("resolution") or "720p").strip().lower() or "720p"
    latest_image = resolve_panel_latest_image(default_panel) if default_panel else ""

    inferred_generation_types = ["text_to_video"]
    if latest_image or attachment_image_urls:
        inferred_generation_types.append("image_to_video")
    if len(attachment_image_urls) >= 2:
        inferred_generation_types.extend(["reference_to_video", "start_end_to_video"])
    if attachment_video_urls and (attachment_image_urls or latest_image):
        inferred_generation_types.append("reference_to_video")
    generation_type_options = [
        {"value": item, "label": GENERATION_TYPE_LABELS.get(item, item)}
        for item in dict.fromkeys([generation_type] + inferred_generation_types)
    ]
    model_options = build_video_model_options(
        generation_type=generation_type,
        audio_enabled=audio_enabled,
    )

    steps: List[Dict[str, Any]] = []
    if not selected_panels:
        steps.append(
            {
                "id": "panel_scope",
                "label": "分镜范围",
                "description": "支持 2-4、2,3,5、前3镜、最后2镜、偶数镜、当前没有视频的分镜。",
                "type": "text",
                "required": True,
                "default": "",
                "placeholder": "例如：2-4",
            }
        )

    steps.extend(
        [
            {
                "id": "generation_type",
                "label": "生成方式",
                "description": "会根据参考图、参考视频和当前分镜素材自动推荐，也可以手动切换。",
                "type": "select",
                "required": True,
                "default": generation_type,
                "options": generation_type_options,
            },
            {
                "id": "prompt_override",
                "label": "补充视频提示词",
                "description": "可补充动作、镜头运动、表演节奏；留空则继续使用分镜现有视频提示词。",
                "type": "textarea",
                "required": bool(prompt_required),
                "placeholder": "例如：人物缓慢转身，镜头轻推近，衣摆和发丝随风摆动",
                "default": "",
            },
            {
                "id": "model_code",
                "label": "视频模型",
                "description": "模型列表来自神鹿当前真实接入的视频模型注册表。",
                "type": "select",
                "required": True,
                "default": default_model_code,
                "options": model_options,
            },
            {
                "id": "audio_enabled",
                "label": "保留音频",
                "description": "仅支持音频的模型会在模型选项中显示对应标签。",
                "type": "boolean",
                "required": False,
                "default": bool(audio_enabled),
            },
            {
                "id": "duration",
                "label": "视频时长",
                "description": "时长选项按当前模型能力与价格规则生成。",
                "type": "select",
                "required": True,
                "default": duration_default,
                "options": field_options["duration_options"],
            },
            {
                "id": "resolution",
                "label": "分辨率",
                "description": "分辨率选项按当前模型能力与价格规则生成。",
                "type": "select",
                "required": True,
                "default": resolution_default,
                "options": field_options["resolution_options"],
            },
        ]
    )

    question = AssistantPendingQuestion(
        session_id=session_obj.id,
        question_type="wizard",
        status="pending",
        title=title,
        prompt_text=description,
        payload_json=_json_dumps(
            {
                "preview": {
                    "total_panels": len(panels),
                    "panels_without_videos": len(candidates),
                    "selected_panel_count": len(selected_panels),
                    "selected_panel_display": selected_display or None,
                    "selected_panels": build_selected_panels_payload(selected_panels),
                    "generation_type": generation_type,
                    "generation_type_label": GENERATION_TYPE_LABELS.get(generation_type, generation_type),
                },
                "wizard": {
                    "title": title,
                    "description": description,
                    "submit_label": "提交视频任务",
                    "cancel_label": "取消",
                    "steps": steps,
                },
                "metadata": {
                    "source": "assistant_generate_panel_video",
                    "selected_panel_sequences": [int(item.sequence_num or 0) for item in selected_panels if int(item.sequence_num or 0) > 0],
                    "selected_panel_display": selected_display,
                    "generation_type": generation_type,
                    "audio_enabled": bool(audio_enabled),
                    "attachment_image_urls": attachment_image_urls,
                    "attachment_video_urls": attachment_video_urls,
                    "default_model_code": default_model_code,
                    "selection_reason": str((default_model_choice or {}).get("selection_reason") or "").strip(),
                    "selection_mode": str((default_model_choice or {}).get("selection_mode") or "").strip(),
                },
            }
        ),
        answer_json=_json_dumps({}),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    self.session.add(question)
    self.session.flush()

    assistant_turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": "生成视频",
                "description": description,
                "task_type": "generate_panel_video",
                "status": "pending",
                "preview": {
                    "total_panels": len(panels),
                    "panels_without_videos": len(candidates),
                    "selected_panel_count": len(selected_panels),
                    "selected_panel_display": selected_display or None,
                    "generation_type": GENERATION_TYPE_LABELS.get(generation_type, generation_type),
                },
            },
            {
                "id": uuid.uuid4().hex,
                "type": "question",
                "question_id": question.question_key,
                "question_type": "wizard",
                "title": title,
                "prompt": description,
                "options": [],
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "question_event": {
            "type": "question",
            "question": {
                "question_id": question.question_key,
                "question_type": "wizard",
            },
        },
        "pending_question_wizard": self._serialize_pending_question(question),
        "project_changes": [],
    }


def _submit_panel_video_generation_v2(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    selected_panels: List[Panel],
    prompt_override: Optional[str] = None,
    model_choice: Optional[Dict[str, Any]] = None,
    duration: Optional[Any] = None,
    resolution: Optional[str] = None,
    generation_type: Optional[str] = None,
    audio_enabled: bool = False,
    attachments: Optional[List[Dict[str, Any]]] = None,
    selection_reason: str = "",
    selection_mode: str = "auto",
    resume_hint: str = "",
) -> Dict[str, Any]:
    team = self.session.get(Team, session_obj.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="当前会话所属团队不存在")
    if not selected_panels:
        raise HTTPException(status_code=400, detail="请先选择要处理的分镜范围")

    resolved_model = (model_choice or {}).get("model") or {}
    resolved_model_code = str(resolved_model.get("model_code") or "").strip().lower()
    if not resolved_model_code:
        raise HTTPException(status_code=400, detail="当前没有可用的视频模型，请先调整模型或生成方式")

    attachment_urls = normalize_attachment_media_urls(attachments)
    attachment_image_urls = attachment_urls["image_urls"]
    attachment_video_urls = attachment_urls["video_urls"]
    resolved_generation_type = str(generation_type or resolved_model.get("generation_type") or "text_to_video").strip().lower()
    field_options = resolve_video_generation_field_options(resolved_model_code, resolved_generation_type)
    try:
        resolved_duration = int(duration or field_options["defaults"].get("duration") or resolve_panel_video_duration(selected_panels[0]))
    except Exception:
        resolved_duration = int(field_options["defaults"].get("duration") or resolve_panel_video_duration(selected_panels[0]))
    allowed_durations = {int(item["value"]) for item in field_options["duration_options"]}
    if allowed_durations and resolved_duration not in allowed_durations:
        resolved_duration = sorted(allowed_durations)[0]

    resolved_resolution = str(resolution or field_options["defaults"].get("resolution") or "720p").strip().lower()
    allowed_resolutions = {str(item["value"]).strip().lower() for item in field_options["resolution_options"]}
    if allowed_resolutions and resolved_resolution not in allowed_resolutions:
        resolved_resolution = sorted(allowed_resolutions)[0]

    selected_display = _format_selected_panel_display(selected_panels)
    task_items: List[Dict[str, Any]] = []
    refresh_hints = {"panels": True, "canvas": True}
    selected_panel_payload = build_selected_panels_payload(selected_panels)
    execution_plan = _build_video_execution_plan_payload(
        execution_stage="submitted_video_tasks",
        selected_panels=selected_panels,
        model_choice=model_choice,
        selection_reason=selection_reason,
        resume_hint=resume_hint or "已按 {0} 提交视频任务。".format(selected_display),
    )

    for panel in selected_panels:
        payload = _build_panel_video_payload(
            self,
            session_obj=session_obj,
            panel=panel,
            prompt_override=prompt_override,
            model_code=resolved_model_code,
            generation_type=resolved_generation_type,
            duration=resolved_duration,
            resolution=resolved_resolution,
            audio_enabled=audio_enabled,
            attachment_image_urls=attachment_image_urls,
            attachment_video_urls=attachment_video_urls,
        )
        background_tasks = BackgroundTasks()
        record = submit_video_generation(
            self.session,
            background_tasks=background_tasks,
            user=user,
            team=team,
            payload=payload,
        )
        record = _mark_generation_record_source(
            self,
            session_obj=session_obj,
            record=record,
            params_public_updates={
                "selected_panels": selected_panel_payload,
                "selected_panel_sequences": [int(item.sequence_num or 0) for item in selected_panels if int(item.sequence_num or 0) > 0],
                "selected_panel_count": len(selected_panels),
                "selected_panel_display": selected_display,
                "selection_reason": selection_reason,
                "selection_mode": selection_mode,
                "resolved_model_choice": execution_plan.get("resolved_model_choice"),
            },
            params_internal_updates={
                "selected_panels": selected_panel_payload,
                "selection_reason": selection_reason,
                "selection_mode": selection_mode,
                "resume_hint": resume_hint,
                "assistant_execution_plan": execution_plan,
                "attachment_image_urls": attachment_image_urls,
                "attachment_video_urls": attachment_video_urls,
            },
        )
        threading.Thread(target=_run_video_generation_job, args=(record.id,), daemon=True).start()
        task_items.append(
            {
                "task_id": str(record.task_id or ""),
                "record_id": encode_id(record.id) if record.id else None,
                "panel_id": encode_id(panel.id) if panel.id else None,
                "panel_sequence": int(panel.sequence_num or 0),
                "status": str(record.status or "queued"),
            }
        )

    tool_use_id = uuid.uuid4().hex
    model_name = str(resolved_model.get("model_name") or resolved_model_code)
    summary = "已为 {0} 提交 {1} 个视频任务，当前使用 {2}。".format(selected_display, len(task_items), model_name)
    assistant_turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "text",
                "text": "{0} 你可以在任务面板里继续跟进进度。".format(summary),
            },
            {
                "id": tool_use_id,
                "type": "tool_use",
                "tool_name": "generate_panel_video",
                "title": "提交视频生成任务",
                "status": "completed",
                "description": "已完成分镜范围解析、视频模型选择与任务冻结，并提交到视频生成队列。",
            },
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": "视频任务已提交",
                "description": summary,
                "task_type": "generate_panel_video",
                "status": "running",
                "preview": {
                    "selected_panel_display": selected_display,
                    "selected_panel_count": len(task_items),
                    "generation_type": GENERATION_TYPE_LABELS.get(resolved_generation_type, resolved_generation_type),
                    "model_name": model_name,
                },
            },
            {
                "id": uuid.uuid4().hex,
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "tool_name": "generate_panel_video",
                "summary": summary,
                "result": {
                    "tasks": task_items,
                    "selection_reason": selection_reason,
                    "selected_panels": selected_panel_payload,
                    "resolved_model_choice": execution_plan.get("resolved_model_choice"),
                    "refresh_hints": refresh_hints,
                },
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "project_changes": [
            {
                "block_id": tool_use_id,
                "tool_name": "generate_panel_video",
                "summary": summary,
                "refresh_hints": refresh_hints,
            }
        ],
        "execution_plan": execution_plan,
    }


def _answer_generate_panel_video_question_v2(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    action: str,
    question_payload: Dict[str, Any],
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = question_payload.get("metadata") or {}
    answer_data = answers or {}
    selected_sequences = [
        int(item)
        for item in (metadata.get("selected_panel_sequences") or [])
        if str(item).strip()
    ]

    if action == "reject":
        turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "interrupt_notice",
                    "text": "已取消本次视频任务，不会继续提交生成。",
                }
            ],
        )
        self._insert_turn_event(session_obj=session_obj, turn=turn)
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": turn})
        return {
            "snapshot": self.get_snapshot(session_obj=session_obj),
            "execution_plan": _build_video_execution_plan_payload(
                execution_stage="canceled",
                selected_panels=[],
                selection_reason="已取消本次视频任务。",
                resume_hint="重新发起请求时可以继续指定分镜范围和模型。",
            ),
        }

    if not session_obj.episode_id:
        raise HTTPException(status_code=400, detail="请先进入具体剧集，再让 AI 帮你生成视频")

    panels = self.session.exec(
        select(Panel)
        .where(Panel.episode_id == session_obj.episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    if not panels:
        raise HTTPException(status_code=400, detail="当前剧集还没有分镜，请先拆分或编写分镜")

    candidates = [panel for panel in panels if not _panel_has_video(panel)]
    if not selected_sequences:
        selection_text = str(answer_data.get("panel_scope") or "").strip()
        selection = resolve_panel_selection(
            selection_text,
            panels,
            panels_without_videos=candidates,
            fallback_when_single=True,
        )
        if not selection or not selection.get("panel_sequences"):
            raise HTTPException(status_code=400, detail="请用 2-4、2,3,5、前3镜 这类格式指定分镜范围")
        selected_sequences = [int(item) for item in selection["panel_sequences"]]

    selected_panels = [
        panel
        for panel in panels
        if int(panel.sequence_num or 0) in set(selected_sequences)
    ]
    if not selected_panels:
        raise HTTPException(status_code=404, detail="目标分镜不存在或已被删除")

    attachment_image_urls = [str(item).strip() for item in (metadata.get("attachment_image_urls") or []) if str(item).strip()]
    attachment_video_urls = [str(item).strip() for item in (metadata.get("attachment_video_urls") or []) if str(item).strip()]
    default_latest_image = resolve_panel_latest_image(selected_panels[0]) if selected_panels and all(resolve_panel_latest_image(panel) for panel in selected_panels) else ""
    resolved_generation_type = str(
        answer_data.get("generation_type")
        or metadata.get("generation_type")
        or infer_video_generation_type(
            content="",
            latest_image=default_latest_image,
            attachment_image_urls=attachment_image_urls,
            attachment_video_urls=attachment_video_urls,
        )
    ).strip().lower()
    resolved_audio_enabled = coerce_runtime_bool(answer_data.get("audio_enabled"), bool(metadata.get("audio_enabled")))
    explicit_model_code = str(answer_data.get("model_code") or metadata.get("default_model_code") or "").strip()
    explicit_request = None
    if explicit_model_code:
        explicit_request = resolve_explicit_video_model_request(explicit_model_code) or {
            "requested_text": explicit_model_code,
            "model_code": explicit_model_code,
            "connected": True,
            "model_name": explicit_model_code,
        }

    model_choice = choose_video_model(
        content="",
        generation_type=resolved_generation_type,
        duration=int(answer_data.get("duration") or resolve_panel_video_duration(selected_panels[0])),
        audio_enabled=resolved_audio_enabled,
        image_ref_count=len(attachment_image_urls),
        video_ref_count=len(attachment_video_urls),
        explicit_request=explicit_request,
    )
    if not model_choice.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=build_model_unavailable_message(
                reason=str(model_choice.get("reason") or "当前没有可用的视频模型。"),
                alternatives=model_choice.get("alternatives") or [],
            ),
        )

    result = _submit_panel_video_generation_v2(
        self,
        session_obj=session_obj,
        user=user,
        selected_panels=selected_panels,
        prompt_override=answer_data.get("prompt_override"),
        model_choice=model_choice,
        duration=answer_data.get("duration"),
        resolution=answer_data.get("resolution"),
        generation_type=resolved_generation_type,
        audio_enabled=resolved_audio_enabled,
        attachments=[
            *({"type": "image", "url": url} for url in attachment_image_urls),
            *({"type": "video", "url": url} for url in attachment_video_urls),
        ],
        selection_reason=str(model_choice.get("selection_reason") or metadata.get("selection_reason") or "").strip(),
        selection_mode=str(model_choice.get("selection_mode") or metadata.get("selection_mode") or "explicit").strip(),
        resume_hint="已按 {0} 继续提交视频任务。".format(_format_selected_panel_display(selected_panels)),
    )
    session_obj.status = "completed"
    session_obj.updated_at = _utc_now()
    self.session.add(session_obj)
    self.session.commit()
    return {"snapshot": self.get_snapshot(session_obj=session_obj), **result}


def _execute_generate_panel_video_skill_v2(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    content: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not session_obj.episode_id:
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "请先选中一个具体剧集，我才能按当前分镜范围为你提交视频任务。",
                }
            ],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {"assistant_turn": assistant_turn, "project_changes": []}

    panels = self.session.exec(
        select(Panel)
        .where(Panel.episode_id == session_obj.episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    if not panels:
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "当前剧集还没有分镜，先拆分分镜或写分镜后，我再帮你做视频。",
                }
            ],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {"assistant_turn": assistant_turn, "project_changes": []}

    candidates = [panel for panel in panels if not _panel_has_video(panel)]
    selection = resolve_panel_selection(
        content,
        panels,
        panels_without_videos=candidates,
        fallback_when_single=True,
    )
    selected_panels = []
    if selection and selection.get("panel_sequences"):
        selected_sequences = {int(item) for item in selection["panel_sequences"]}
        selected_panels = [panel for panel in panels if int(panel.sequence_num or 0) in selected_sequences]

    attachment_urls = _attachment_media_urls(attachments)
    attachment_image_urls = attachment_urls["image_urls"]
    attachment_video_urls = attachment_urls["video_urls"]
    latest_image = _panel_latest_image(selected_panels[0]) if selected_panels and all(_panel_latest_image(panel) for panel in selected_panels) else ""
    generation_type = infer_video_generation_type(
        content=content,
        latest_image=latest_image,
        attachment_image_urls=attachment_image_urls,
        attachment_video_urls=attachment_video_urls,
    )
    audio_enabled = infer_audio_enabled(content)
    explicit_request = resolve_explicit_video_model_request(content)
    duration_hint = _panel_video_duration(selected_panels[0]) if selected_panels else (6 if candidates else _panel_video_duration(panels[0]))
    model_choice = choose_video_model(
        content=content,
        generation_type=generation_type,
        duration=duration_hint,
        audio_enabled=audio_enabled,
        image_ref_count=len(attachment_image_urls),
        video_ref_count=len(attachment_video_urls),
        explicit_request=explicit_request,
    )

    if explicit_request and not model_choice.get("ok"):
        reason_text = build_model_unavailable_message(
            reason=str(model_choice.get("reason") or "当前没有可用的视频模型。"),
            alternatives=model_choice.get("alternatives") or [],
        )
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[{"id": uuid.uuid4().hex, "type": "text", "text": reason_text}],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {
            "assistant_turn": assistant_turn,
            "project_changes": [],
            "execution_plan": _build_video_execution_plan_payload(
                execution_stage="needs_model_change",
                selected_panels=selected_panels,
                selection_reason=reason_text,
                resume_hint=(selection or {}).get("resume_hint") or "换成可用模型后可继续执行。",
            ),
        }

    if not model_choice.get("ok"):
        reason_text = str(model_choice.get("reason") or "当前没有可用的视频模型。")
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[{"id": uuid.uuid4().hex, "type": "text", "text": reason_text}],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {
            "assistant_turn": assistant_turn,
            "project_changes": [],
            "execution_plan": _build_video_execution_plan_payload(
                execution_stage="needs_model_change",
                selected_panels=selected_panels,
                selection_reason=reason_text,
                resume_hint=(selection or {}).get("resume_hint") or "请调整生成方式、音频要求或模型偏好后重试。",
            ),
        }

    prompt_required = bool(selected_panels) and any(not _derive_panel_video_prompt(panel) for panel in selected_panels)
    if selected_panels and not prompt_required:
        return _submit_panel_video_generation_v2(
            self,
            session_obj=session_obj,
            user=user,
            selected_panels=selected_panels,
            model_choice=model_choice,
            duration=duration_hint,
            resolution=None,
            generation_type=generation_type,
            audio_enabled=audio_enabled,
            attachments=attachments,
            selection_reason=str(model_choice.get("selection_reason") or "").strip(),
            selection_mode=str(model_choice.get("selection_mode") or "auto").strip(),
            resume_hint=(selection or {}).get("resume_hint") or "已直接按当前解析结果提交视频任务。",
        )

    pending_count = len(candidates)
    selected_display = _format_selected_panel_display(selected_panels)
    if selected_panels and prompt_required:
        description = "已解析到 {0}，但其中至少有一个分镜缺少视频提示词，请补充后继续。".format(selected_display)
    elif selected_panels:
        description = "已解析到 {0}，你也可以在继续前手动调整生成方式、模型和时长。".format(selected_display)
    else:
        description = (
            "当前剧集共有 {0} 个分镜，其中 {1} 个还没有视频。请补充分镜范围和生成参数后继续。".format(len(panels), pending_count)
            if pending_count
            else "当前剧集的分镜都已有视频；如需重做，请指定分镜范围和生成参数。"
        )

    wizard_result = _create_panel_video_wizard_v2(
        self,
        session_obj=session_obj,
        title="补充分镜视频参数",
        description=description,
        panels=panels,
        candidates=candidates,
        selected_panels=selected_panels,
        prompt_required=prompt_required,
        generation_type=generation_type,
        audio_enabled=audio_enabled,
        default_model_choice=model_choice,
        attachment_image_urls=attachment_image_urls,
        attachment_video_urls=attachment_video_urls,
    )
    wizard_result["execution_plan"] = _build_video_execution_plan_payload(
        execution_stage="awaiting_video_parameters",
        selected_panels=selected_panels,
        model_choice=model_choice,
        selection_reason=str(model_choice.get("selection_reason") or "").strip(),
        resume_hint=(selection or {}).get("resume_hint") or "补齐参数后会继续按当前范围提交视频任务。",
    )
    return wizard_result


def _create_episode_dubbing_wizard(
    self,
    *,
    session_obj: AssistantSession,
    episode: Episode,
    script_text: str,
    default_ability_type: str,
    default_voice_choice: Dict[str, Any],
    voice_assets: List[Dict[str, Any]],
) -> Dict[str, Any]:
    default_voice_id = str(default_voice_choice.get("voice_id") or "").strip()
    if not default_voice_id and len(voice_assets) == 1:
        default_voice_id = str(voice_assets[0].get("voice_id") or "").strip()
    default_tier_code = str(default_voice_choice.get("tier_code") or "hd").strip().lower() or "hd"
    if default_tier_code not in {"hd", "turbo"}:
        default_tier_code = "hd"

    voice_step: Dict[str, Any] = {
        "id": "voice_id",
        "label": "选择音色",
        "description": "优先选择你最近用过或当前可用的音色。",
        "required": True,
        "default": default_voice_id,
    }
    if voice_assets:
        voice_step["type"] = "select"
        voice_step["options"] = [
            {"value": str(item.get("voice_id") or ""), "label": str(item.get("label") or item.get("voice_id") or "")}
            for item in voice_assets
        ]
    else:
        voice_step["type"] = "text"
        voice_step["placeholder"] = "请输入可用的 voice_id"

    steps = [
        voice_step,
        {
            "id": "ability_type",
            "label": "配音方式",
            "description": "短台词更适合实时配音，长段落更适合旁白生成。",
            "type": "select",
            "required": True,
            "default": default_ability_type,
            "options": [
                {"value": ABILITY_REALTIME, "label": "实时配音"},
                {"value": ABILITY_NARRATION, "label": "长文本旁白"},
            ],
        },
        {
            "id": "tier_code",
            "label": "质量档位",
            "description": "高保真音质更稳，极速版更省时。",
            "type": "select",
            "required": True,
            "default": default_tier_code,
            "options": [
                {"value": "hd", "label": "高保真"},
                {"value": "turbo", "label": "极速版"},
            ],
        },
        {
            "id": "script_text",
            "label": "配音文本",
            "description": script_text and "留空则使用当前剧集正文；如需改写，可在这里覆盖。" or "当前剧集缺少可直接配音的文本，请补充本次配音内容。",
            "type": "textarea",
            "required": not bool(script_text),
            "placeholder": "请输入本次需要配音的文本",
            "default": "",
        },
        {
            "id": "emotion",
            "label": "情绪",
            "description": "可选；不填则保持模型默认。",
            "type": "select",
            "required": False,
            "default": "",
            "options": [
                {"value": "", "label": "默认"},
                {"value": "calm", "label": "平静"},
                {"value": "fluent", "label": "流畅"},
                {"value": "happy", "label": "开心"},
                {"value": "sad", "label": "伤感"},
            ],
        },
    ]

    title = "补充配音参数"
    description = "我已经定位到当前剧集，补齐音色和配音方式后就可以继续提交任务。"
    question = AssistantPendingQuestion(
        session_id=session_obj.id,
        question_type="wizard",
        status="pending",
        title=title,
        prompt_text=description,
        payload_json=_json_dumps(
            {
                "preview": {
                    "episode_title": episode.title,
                    "source_text_length": len(script_text),
                    "mode": getattr(episode, "storyboard_mode", None),
                },
                "wizard": {
                    "title": title,
                    "description": description,
                    "submit_label": "提交配音任务",
                    "cancel_label": "取消",
                    "steps": steps,
                },
                "metadata": {
                    "source": "assistant_generate_episode_dubbing",
                    "default_voice_id": default_voice_id,
                    "default_voice_source_type": str(default_voice_choice.get("voice_source_type") or VOICE_SOURCE_SYSTEM).strip() or VOICE_SOURCE_SYSTEM,
                    "default_ability_type": default_ability_type,
                    "default_tier_code": default_tier_code,
                },
            }
        ),
        answer_json=_json_dumps({}),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    self.session.add(question)
    self.session.flush()

    assistant_turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": "生成配音",
                "description": description,
                "task_type": "generate_episode_dubbing",
                "status": "pending",
                "preview": {
                    "episode_title": episode.title,
                    "source_text_length": len(script_text),
                    "mode": getattr(episode, "storyboard_mode", None),
                },
            },
            {
                "id": uuid.uuid4().hex,
                "type": "question",
                "question_id": question.question_key,
                "question_type": "wizard",
                "title": title,
                "prompt": description,
                "options": [],
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_episode_dubbing"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "question_event": {
            "type": "question",
            "question": {
                "question_id": question.question_key,
                "question_type": "wizard",
            },
        },
        "pending_question_wizard": self._serialize_pending_question(question),
        "project_changes": [],
    }


def _submit_episode_dubbing_generation(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    episode: Episode,
    script_text: str,
    voice_id: str,
    voice_source_type: str,
    ability_type: str,
    tier_code: Optional[str] = None,
    emotion: Optional[str] = None,
) -> Dict[str, Any]:
    team = self.session.get(Team, session_obj.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="当前会话所属团队不存在")

    resolved_text = str(script_text or "").strip()
    if not resolved_text:
        raise HTTPException(status_code=400, detail="当前剧集缺少可直接配音的文本，请先补充正文或在向导中输入配音文本")

    resolved_voice_id = str(voice_id or "").strip()
    if not resolved_voice_id:
        raise HTTPException(status_code=400, detail="请先选择一个可用音色")

    resolved_voice_source_type = str(voice_source_type or VOICE_SOURCE_SYSTEM).strip().lower() or VOICE_SOURCE_SYSTEM
    resolved_ability_type = str(ability_type or ABILITY_REALTIME).strip().lower() or ABILITY_REALTIME
    if resolved_ability_type not in {ABILITY_REALTIME, ABILITY_NARRATION}:
        resolved_ability_type = ABILITY_REALTIME

    resolved_tier_code = str(tier_code or "hd").strip().lower() or "hd"
    if resolved_tier_code not in {"hd", "turbo"}:
        resolved_tier_code = "hd"

    payload = {
        "ownership_mode": "project",
        "project_id": encode_id(session_obj.script_id),
        "episode_id": encode_id(episode.id),
        "target_type": "episode_record",
        "ability_type": resolved_ability_type,
        "tier_code": resolved_tier_code,
        "voice_id": resolved_voice_id,
        "voice_source_type": resolved_voice_source_type,
        "script_text": resolved_text,
        "audio_format": "mp3",
    }
    resolved_emotion = str(emotion or "").strip()
    if resolved_emotion:
        payload["emotion"] = resolved_emotion

    background_tasks = BackgroundTasks()
    record = submit_audio_generation(
        self.session,
        background_tasks=background_tasks,
        user=user,
        team=team,
        payload=payload,
    )
    record = _mark_generation_record_source(self, session_obj=session_obj, record=record)

    if resolved_ability_type == ABILITY_NARRATION:
        threading.Thread(target=_run_audio_async_job, args=(record.id,), daemon=True).start()

    tool_use_id = uuid.uuid4().hex
    is_async = resolved_ability_type == ABILITY_NARRATION
    summary = (
        "已为《{0}》提交配音任务。".format(episode.title or "当前剧集")
        if is_async
        else "已为《{0}》生成配音。".format(episode.title or "当前剧集")
    )
    result_payload = {
        "task_id": str(record.task_id or ""),
        "record_id": encode_id(record.id) if record.id else None,
        "episode_id": encode_id(episode.id) if episode.id else None,
        "status": str(record.status or ("queued" if is_async else "completed")),
        "ability_type": resolved_ability_type,
        "tier_code": resolved_tier_code,
        "voice_id": resolved_voice_id,
        "voice_source_type": resolved_voice_source_type,
        "source": _generation_record_source(session_obj),
        "summary": summary,
        "refresh_hints": {},
        "preview_url": str(getattr(record, "preview_url", "") or "").strip() or None,
    }
    assistant_turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "text",
                "text": is_async and "{0} 任务已进入队列，你可以在任务面板或配音中心继续跟踪进度。".format(summary) or "{0} 你可以直接去配音中心试听结果。".format(summary),
            },
            {
                "id": tool_use_id,
                "type": "tool_use",
                "tool_name": "generate_episode_dubbing",
                "title": "提交配音任务",
                "status": "completed",
                "description": "已整理剧集文本、音色和配音方式，并提交到配音任务链路。",
                "task_id": str(record.task_id or ""),
            },
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": is_async and "配音任务已提交" or "配音已生成",
                "description": is_async and "当前剧集正在排队生成音频。" or "当前剧集的配音已经生成完成。",
                "task_type": "generate_episode_dubbing",
                "status": is_async and "running" or "completed",
                "task_id": str(record.task_id or ""),
            },
            {
                "id": uuid.uuid4().hex,
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "tool_name": "generate_episode_dubbing",
                "summary": summary,
                "task_id": str(record.task_id or ""),
                "result": result_payload,
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_episode_dubbing"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "project_changes": [
            {
                "block_id": tool_use_id,
                "tool_name": "generate_episode_dubbing",
                "summary": summary,
                "refresh_hints": {},
            }
        ],
    }


def _answer_generate_episode_dubbing_question(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    action: str,
    question_payload: Dict[str, Any],
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if action == "reject":
        turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "interrupt_notice",
                    "text": "已取消本次配音任务，不会继续提交生成。",
                }
            ],
        )
        self._insert_turn_event(session_obj=session_obj, turn=turn)
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": turn})
        return {"snapshot": self.get_snapshot(session_obj=session_obj)}

    if not session_obj.episode_id:
        raise HTTPException(status_code=400, detail="请先进入具体剧集，再让 AI 帮你配音")

    episode = self.session.get(Episode, session_obj.episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="当前剧集不存在或已被删除")

    metadata = question_payload.get("metadata") or {}
    answer_data = answers or {}
    voice_assets = _load_voice_assets_for_wizard(self, user=user)
    voice_id = str(answer_data.get("voice_id") or metadata.get("default_voice_id") or "").strip()
    if not voice_id:
        raise HTTPException(status_code=400, detail="请选择一个可用音色")

    script_text = str(answer_data.get("script_text") or "").strip() or _derive_episode_dubbing_text(self, episode)
    voice_source_type = _resolve_voice_source_type(
        voice_assets,
        voice_id=voice_id,
        fallback=answer_data.get("voice_source_type") or metadata.get("default_voice_source_type"),
    )
    result = self._submit_episode_dubbing_generation(
        session_obj=session_obj,
        user=user,
        episode=episode,
        script_text=script_text,
        voice_id=voice_id,
        voice_source_type=voice_source_type,
        ability_type=answer_data.get("ability_type") or metadata.get("default_ability_type") or ABILITY_REALTIME,
        tier_code=answer_data.get("tier_code") or metadata.get("default_tier_code") or "hd",
        emotion=answer_data.get("emotion"),
    )
    session_obj.status = "completed"
    session_obj.updated_at = _utc_now()
    self.session.add(session_obj)
    self.session.commit()
    return {"snapshot": self.get_snapshot(session_obj=session_obj), **result}


def _execute_generate_episode_dubbing_skill(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    content: str,
) -> Dict[str, Any]:
    if not session_obj.episode_id:
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "请先选中一个具体剧集，我才能按当前剧集内容为你提交配音任务。",
                }
            ],
            metadata={"source": "assistant_skill", "skill": "generate_episode_dubbing"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {"assistant_turn": assistant_turn, "project_changes": []}

    episode = self.session.get(Episode, session_obj.episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="当前剧集不存在或已被删除")

    script_text = _derive_episode_dubbing_text(self, episode)
    default_ability_type = _infer_dubbing_ability(content, script_text, episode)
    recent_choice = _find_recent_audio_choice(self, session_obj=session_obj, user=user)

    if script_text and recent_choice.get("voice_id"):
        return self._submit_episode_dubbing_generation(
            session_obj=session_obj,
            user=user,
            episode=episode,
            script_text=script_text,
            voice_id=str(recent_choice.get("voice_id") or "").strip(),
            voice_source_type=str(recent_choice.get("voice_source_type") or VOICE_SOURCE_SYSTEM).strip() or VOICE_SOURCE_SYSTEM,
            ability_type=recent_choice.get("ability_type") or default_ability_type,
            tier_code=recent_choice.get("tier_code") or "hd",
        )

    voice_assets = _load_voice_assets_for_wizard(self, user=user)
    return _create_episode_dubbing_wizard(
        self,
        session_obj=session_obj,
        episode=episode,
        script_text=script_text,
        default_ability_type=default_ability_type,
        default_voice_choice=recent_choice,
        voice_assets=voice_assets,
    )


def _execute_internal_director_message(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    content: str,
    context: Dict[str, Any],
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    smalltalk_reply = _match_smalltalk_reply(content or "")
    if smalltalk_reply and not attachments:
        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": smalltalk_reply,
                }
            ],
            metadata={"source": "smalltalk_fastpath"},
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {
            "assistant_turn": assistant_turn,
            "project_changes": [],
        }

    if _looks_like_status_query(content or "") and not attachments:
        workflow_status_result = _build_workflow_status_reply(self, session_obj=session_obj, user=user)
        if workflow_status_result:
            return workflow_status_result

    director_service = DirectorAgentService(self.session)
    legacy_session_id = self._ensure_legacy_director_session(session_obj=session_obj, user=user)
    merged_context = self._build_runtime_context(session_obj)
    if context:
        merged_context.update(context)
    if attachments:
        merged_context["assistant_attachments"] = attachments
        merged_context["reference_attachment_urls"] = [item.get("url") for item in attachments if item.get("url")]

    runtime_state = self._get_runtime_state(session_obj)
    skill_hint = runtime_state.get("skill_hint") if isinstance(runtime_state.get("skill_hint"), dict) else self._extract_skill_hint(content)
    explicit_tool_intent = extract_explicit_tool_intent(content or "", skill_hint=skill_hint)

    script = self.session.get(Script, session_obj.script_id)
    episode = self.session.get(Episode, session_obj.episode_id) if session_obj.episode_id else None
    if script is not None:
        workflow_snapshot = self._build_workflow_snapshot(session_obj)
        active_agent_key = (
            str((explicit_tool_intent or {}).get("tool_name") or "").strip()
            or STAGE_AGENT_MAP.get(runtime_state.get("creative_stage") or "", "director_agent")
        )
        active_agent_label = ACTIVE_AGENT_LABELS.get(
            STAGE_AGENT_MAP.get(runtime_state.get("creative_stage") or "", "director_agent"),
            "神鹿 Agent",
        )
        stream_skill_hint = {
            "id": active_agent_key,
            "label": get_tool_display(active_agent_key, fallback_label=active_agent_label).get("title_cn") or active_agent_label,
        }

        def stream_callback(reasoning_delta: str, reasoning_text: Optional[str] = None) -> None:
            full_text = reasoning_text if reasoning_text is not None else reasoning_delta
            self._update_reasoning_progress(
                session_obj,
                content=content or "请参考当前项目上下文",
                skill_hint=stream_skill_hint,
                reasoning_text=full_text,
                reasoning_delta=reasoning_delta,
            )

        def runtime_event_callback(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
            data = dict(payload or {})
            data["type"] = event_type
            if event_type == "storyboard_plan_delta":
                rows = []
                for row in list(data.get("rows") or []):
                    if not isinstance(row, dict):
                        continue
                    rows.append(
                        [
                            str(row.get("sequence_num") or ""),
                            str(row.get("story_fragment") or ""),
                            str(row.get("dialogue") or ""),
                            str(row.get("estimated_duration_seconds") or ""),
                        ]
                    )
                total_duration_seconds = _storyboard_plan_total_seconds(data, rows)
                summary = str(data.get("summary") or "").strip()
                total_summary = f"\u603b\u9884\u8ba1\u65f6\u957f\uff1a{total_duration_seconds} \u79d2" if total_duration_seconds else ""
                if total_summary:
                    summary = f"{summary}\n\n{total_summary}" if summary else total_summary
                    rows.append(["\u5408\u8ba1", "", "", f"{total_duration_seconds} \u79d2"])
                table_patch = {
                    "type": "table_card",
                    "title": data.get("title") or "剧情片段规划",
                    "columns": ["序号", "剧情片段", "对话", "预计时长"],
                    "rows": rows,
                    "summary": summary,
                    "total_estimated_duration_seconds": total_duration_seconds,
                    "status": "completed" if rows else "running",
                }
                if not self._patch_runtime_feed_item(session_obj, "storyboard-plan-table", table_patch, publish=True):
                    self._upsert_runtime_feed_item(session_obj, {"id": "storyboard-plan-table", **table_patch}, publish=True)
            elif event_type == "storyboard_plan_ready":
                plan_id = str(data.get("plan_id") or "").strip()
                actions = [
                    {"type": "extract_storyboard", "label": "根据规划计划分镜", "payload": {"mode": "split_confirmed", "confirmed_plan_id": plan_id}},
                    {"type": "extract_storyboard", "label": "增加时长", "payload": {"mode": "plan_first", "plan_revision_instruction": "整体增加每个剧情片段的预计时长，保留剧情顺序。"}},
                    {"type": "extract_storyboard", "label": "增加分镜", "payload": {"mode": "plan_first", "plan_revision_instruction": "增加剧情片段数量，把关键动作拆得更细。"}},
                    {"type": "extract_storyboard", "label": "减少分镜", "payload": {"mode": "plan_first", "plan_revision_instruction": "减少剧情片段数量，合并节奏相近的片段。"}},
                    {"type": "extract_storyboard", "label": "细分某段", "payload": {"mode": "plan_first", "plan_revision_instruction": "请细分用户指定的剧情片段；如果没有指定，优先细分信息量最大的片段。"}},
                    {"type": "extract_storyboard", "label": "合并某几段", "payload": {"mode": "plan_first", "plan_revision_instruction": "请合并用户指定或节奏相近的剧情片段。"}},
                ]
                self._upsert_runtime_feed_item(
                    session_obj,
                    {
                        "id": "storyboard-plan-actions",
                        "type": "action_card",
                        "actions": actions,
                        "status": "completed",
                    },
                    publish=True,
                )
            elif event_type == "storyboard_split_progress_delta":
                rows = []
                public_summaries = []
                event_summary = str(data.get("summary") or data.get("public_summary") or "").strip()
                if event_summary:
                    public_summaries.append(event_summary)
                for row in list(data.get("rows") or []):
                    if not isinstance(row, dict):
                        continue
                    row.pop("error_summary", None)
                    public_summary = str(row.get("public_summary") or row.get("summary") or "").strip()
                    if public_summary and public_summary not in public_summaries:
                        public_summaries.append(public_summary)
                    rows.append(
                        [
                            str(row.get("sequence_num") or ""),
                            str(row.get("story_fragment") or ""),
                            str(row.get("grid_count") or ""),
                            str(row.get("status") or "等待中"),
                        ]
                    )
                table_patch = {
                    "type": "table_card",
                    "title": data.get("title") or "正式分镜拆分进度",
                    "columns": ["序号", "剧情片段", "宫格数", "状态"],
                    "rows": rows,
                    "summary": "\n".join(public_summaries[:2]),
                    "status": "running",
                }
                if not self._patch_runtime_feed_item(session_obj, "storyboard-split-progress", table_patch, publish=True):
                    self._upsert_runtime_feed_item(session_obj, {"id": "storyboard-split-progress", **table_patch}, publish=True)
            elif event_type == "storyboard_preview_delta":
                rows = []
                for row in list(data.get("rows") or []):
                    if not isinstance(row, dict):
                        continue
                    rows.append(
                        [
                            str(row.get("sequence_num") or ""),
                            str(row.get("description") or ""),
                            str(row.get("scene_name") or ""),
                            str(row.get("duration_seconds") or ""),
                        ]
                    )
                if not self._patch_runtime_feed_item(
                    session_obj,
                    "table-main",
                    {
                        "type": "table_card",
                        "title": data.get("title") or "分镜草稿",
                        "columns": ["镜头", "画面内容", "场景", "建议时长"],
                        "rows": rows,
                        "status": "running",
                    },
                    publish=True,
                ):
                    self._upsert_runtime_feed_item(
                        session_obj,
                        {
                            "id": "table-main",
                            "type": "table_card",
                            "title": data.get("title") or "分镜草稿",
                            "columns": ["镜头", "画面内容", "场景", "建议时长"],
                            "rows": rows,
                            "status": "running",
                        },
                        publish=True,
                    )
            self.publish_event(session_obj.id, data)

        structured_context = build_agent_context(
            self.session,
            user=user,
            team=self.session.get(Team, session_obj.team_id),
            script=script,
            episode=episode,
            latest_user_message=content or "",
            conversation_history=[],
            workflow=workflow_snapshot if isinstance(workflow_snapshot, dict) else {},
            page_context=context or {},
            latest_artifacts=runtime_state.get("latest_artifacts") if isinstance(runtime_state.get("latest_artifacts"), dict) else {},
            explicit_action_intent=explicit_tool_intent,
            stream_callback=stream_callback,
            runtime_event_callback=runtime_event_callback,
            now=_utc_now(),
        )
        facts_cards = _runtime_feed_facts_cards(
            {
                "workspace_facts": structured_context.get("workspace_facts_preview") or {},
                "stage_facts": (structured_context.get("stage_read_model") or {}).get("facts") or {},
            }
        )
        for card in facts_cards:
            self._upsert_runtime_feed_item(session_obj, card, publish=True)
        if _looks_like_script_source_message(content or "") and not explicit_tool_intent:
            structured_context = {
                **structured_context,
                "disable_llm": True,
                "creative_stage": "script_ready",
                "creative_stage_label": "剧本创作",
                "stage_read_model": {
                    **(structured_context.get("stage_read_model") or {}),
                    "creative_stage": "script_ready",
                    "creative_stage_label": "剧本创作",
                    "active_agent": "director_agent",
                    "active_agent_label": ACTIVE_AGENT_LABELS.get("director_agent", "编剧专家"),
                },
            }
            agent_response = run_active_agent(structured_context)
            project_changes = []
        else:
            try:
                tool_loop_result = run_internal_director_tool_loop(
                    service=self,
                    session_obj=session_obj,
                    user=user,
                    team=self.session.get(Team, session_obj.team_id),
                    context=structured_context,
                    explicit_tool_intent=explicit_tool_intent,
                    stream_skill_hint=stream_skill_hint,
                )
                agent_response = tool_loop_result.get("final_payload") or {}
                project_changes = tool_loop_result.get("project_changes") or []
            except Exception:
                agent_response = run_active_agent(structured_context)
                project_changes = _refresh_hints_to_project_changes(agent_response.get("refresh_hints") or {}, summary=agent_response.get("message") or "")
        agent_response = _ensure_next_step_suggested_actions(
            content=content or "",
            agent_response=agent_response,
            context=structured_context,
        )
        assistant_turn = _build_structured_agent_turn(
            self,
            agent_response=agent_response,
            turn_source="structured_agent_runtime",
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        self._update_runtime_state(
            session_obj,
            creative_stage=agent_response.get("stage"),
            creative_stage_label=agent_response.get("stage_label"),
            active_agent=agent_response.get("active_agent"),
            active_agent_label=agent_response.get("active_agent_label"),
            next_stage_hint=agent_response.get("next_stage_hint"),
            latest_artifacts={
                **(runtime_state.get("latest_artifacts") if isinstance(runtime_state.get("latest_artifacts"), dict) else {}),
                **(agent_response.get("artifacts") if isinstance(agent_response.get("artifacts"), dict) else {}),
            },
            project_changes=project_changes,
            commit=False,
        )
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {
            "assistant_turn": assistant_turn,
            "project_changes": project_changes,
        }

    team = self.session.get(Team, session_obj.team_id)
    if team:
        workflow_payload = AgentWorkflowService(self.session).handle_conversation_message(
            user=user,
            team=team,
            script_id=session_obj.script_id,
            episode_id=session_obj.episode_id,
            message=content or "继续下一步",
        )
        if workflow_payload:
            current_node = (workflow_payload.get("workflow_data") or {}).get("current_node") or {}
            blocks = list(workflow_payload.get("blocks") or [])
            if current_node.get("summary"):
                blocks.insert(
                    0,
                    {
                        "id": uuid.uuid4().hex,
                        "type": "task_progress",
                        "title": current_node.get("summary_title") or current_node.get("step_label") or "流程推进",
                        "description": current_node.get("summary") or "",
                        "task_type": current_node.get("step_key"),
                        "status": "completed" if current_node.get("can_continue") else "running",
                    },
                )
            assistant_turn = self._build_turn(
                role="assistant",
                blocks=blocks,
                metadata={"source": "workflow_state", "step_key": current_node.get("step_key")},
            )
            self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
            self.session.commit()
            self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
            return {
                "assistant_turn": assistant_turn,
                "project_changes": [],
            }

    def stream_callback(reasoning_text: str) -> None:
        self._update_reasoning_progress(
            session_obj,
            content=content or "请参考附件",
            skill_hint=skill_hint,
            reasoning_text=reasoning_text,
        )

    legacy_message = director_service.process_message(
        session_id=legacy_session_id,
        user_message=content or "请参考附件",
        additional_context=merged_context or None,
        stream_callback=stream_callback,
    )

    legacy_session = director_service.get_session(legacy_session_id)
    if legacy_session:
        session_obj.title = legacy_session.title or session_obj.title
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)

    assistant_turn = self._build_director_turn(
        session_obj=session_obj,
        legacy_message=legacy_message,
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()

    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})

    question_event = None
    pending_question_wizard = None
    question_block = self._find_block_by_type(assistant_turn, "question")
    if question_block:
        question_obj = self.session.exec(
            select(AssistantPendingQuestion).where(
                AssistantPendingQuestion.session_id == session_obj.id,
                AssistantPendingQuestion.question_key == question_block.get("question_id"),
            )
        ).first()
        if question_obj and question_obj.question_type == "wizard":
            pending_question_wizard = self._serialize_pending_question(question_obj)
        question_event = {
            "type": "question",
            "question": {
                "question_id": question_block.get("question_id"),
                "question_type": question_block.get("question_type"),
            },
        }

    return {
        "assistant_turn": assistant_turn,
        "legacy_message": legacy_message,
        "question_event": question_event,
        "pending_question_wizard": pending_question_wizard,
        "project_changes": self._extract_project_changes_from_turn(assistant_turn),
    }


def _execute_external_message(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    content: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    external_session = self._resolve_external_bridge(session_obj=session_obj, user=user)
    runtime_state = self._get_runtime_state(session_obj)
    skill_hint = runtime_state.get("skill_hint") if isinstance(runtime_state.get("skill_hint"), dict) else None
    if not skill_hint:
        skill_hint = {
            "id": "delegate_to_external_agent",
            "label": "站外协作",
            "slash_command": "/站外协作",
            "category": "bridge",
        }

    tool_activity = self._build_tool_activity(skill_hint, session_obj)
    if len(tool_activity) > 1:
        tool_activity[1]["label"] = "委托站外 Agent"
    self._update_runtime_state(
        session_obj,
        status_detail="正在委托站外 Agent",
        tool_activity=tool_activity,
        commit=False,
    )
    self._publish_runtime_delta(session_obj)

    outbound_content = content or ""
    if attachments:
        attachment_lines = []
        for item in attachments:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            label = str(item.get("name") or item.get("type") or "attachment").strip() or "attachment"
            attachment_lines.append("- {0}: {1}".format(label, url))
        if attachment_lines:
            outbound_content = "{0}\n\n参考附件：\n{1}".format(
                outbound_content or "请参考这些附件继续处理。",
                "\n".join(attachment_lines),
            )

    result = append_chat_message(
        self.session,
        user=user,
        session_obj=external_session,
        message=outbound_content,
    )
    reply = result["provider_result"].get("reply") or {}
    actions = result["provider_result"].get("actions") or []
    workspace = result["provider_result"].get("workspace") or {}
    tool_use_id = uuid.uuid4().hex

    blocks = []
    reply_text = str(reply.get("text") or "").strip()
    if reply_text:
        blocks.append({"id": uuid.uuid4().hex, "type": "text", "text": reply_text})

    blocks.append(
        {
            "id": tool_use_id,
            "type": "tool_use",
            "tool_name": "delegate_to_external_agent",
            "title": "委托站外 Agent",
            "status": "completed",
            "description": "已把当前项目上下文与本轮需求发送给站外协作 Agent。",
        }
    )
    blocks.append(
        {
            "id": uuid.uuid4().hex,
            "type": "bridge_update",
            "title": "站外协作已更新",
            "provider": external_session.provider,
            "workspace": workspace,
            "actions": actions,
            "reply_text": reply_text,
        }
    )
    blocks.append(
        {
            "id": uuid.uuid4().hex,
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "tool_name": "delegate_to_external_agent",
            "summary": "站外 Agent 已返回 {0} 条动作建议。".format(len(actions)),
            "result": {
                "actions": actions,
                "workspace": workspace,
                "refresh_hints": {},
                "project_changes": [],
            },
        }
    )

    assistant_turn = self._build_turn(
        role="assistant",
        blocks=blocks,
        metadata={"source": "external_bridge"},
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    self.session.commit()

    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "session": result["session"],
        "provider_result": result["provider_result"],
        "bridge_event": {
            "type": "bridge_update",
            "bridge_state": self.get_bridge_state(session_obj=session_obj),
        },
        "project_changes": [],
    }


def interrupt_session(self, *, session_obj: AssistantSession) -> Dict[str, Any]:
    session_obj.status = "interrupted"
    session_obj.updated_at = _utc_now()
    self._update_runtime_state(
        session_obj,
        status_detail="已中断当前执行",
        clear_keys=[
            "draft_turn",
            "tool_activity",
            "pending_question_wizard",
            "skill_hint",
            "running_started_at",
            "execution_stage",
            "selected_panels",
            "resolved_model_choice",
            "selection_reason",
            "resume_hint",
        ],
        commit=False,
    )
    self.session.add(session_obj)

    turn = self._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "interrupt_notice",
                "text": "已停止当前运行。你可以继续补充要求，或重新发起下一步。",
            }
        ],
    )
    self._insert_turn_event(session_obj=session_obj, turn=turn)
    self.session.commit()

    self.publish_event(session_obj.id, {"type": "patch", "turn": turn})
    self._publish_status(session_obj)
    self._publish_runtime_delta(session_obj)
    self.publish_snapshot(session_obj.id)
    return {"snapshot": self.get_snapshot(session_obj=session_obj)}


def _serialize_session_meta_with_agent_state(self, session_obj: AssistantSession) -> Dict[str, Any]:
    data = _ORIGINAL_SERIALIZE_SESSION_META(self, session_obj)
    runtime_state = self._get_runtime_state(session_obj)
    if not runtime_state.get("creative_stage") and session_obj.script_id:
        try:
            script = self.session.get(Script, session_obj.script_id)
            episode = self.session.get(Episode, session_obj.episode_id) if session_obj.episode_id else None
            if script is not None:
                context = build_agent_context(
                    self.session,
                    user=self.session.get(User, session_obj.user_id),
                    team=self.session.get(Team, session_obj.team_id),
                    script=script,
                    episode=episode,
                    latest_user_message="",
                    workflow=self._build_workflow_snapshot(session_obj),
                    page_context={},
                    latest_artifacts=runtime_state.get("latest_artifacts") if isinstance(runtime_state.get("latest_artifacts"), dict) else {},
                    now=_utc_now(),
                )
                runtime_state.update(
                    {
                        "creative_stage": context.get("creative_stage"),
                        "creative_stage_label": context.get("creative_stage_label"),
                        "active_agent": context.get("stage_read_model", {}).get("active_agent"),
                        "active_agent_label": context.get("stage_read_model", {}).get("active_agent_label"),
                    }
                )
        except Exception:
            pass
    data["creative_stage"] = runtime_state.get("creative_stage") or ""
    data["creative_stage_label"] = runtime_state.get("creative_stage_label") or ""
    data["active_agent"] = runtime_state.get("active_agent") or ""
    data["active_agent_label"] = runtime_state.get("active_agent_label") or ""
    data["next_stage_hint"] = runtime_state.get("next_stage_hint") or ""
    data["latest_artifacts"] = runtime_state.get("latest_artifacts") or {}
    return data


def _refresh_hints_to_project_changes(refresh_hints: Dict[str, Any], *, summary: str) -> List[Dict[str, Any]]:
    if not isinstance(refresh_hints, dict) or not any(bool(value) for value in refresh_hints.values()):
        return []
    return [
        {
            "block_id": uuid.uuid4().hex,
            "tool_name": "agent_action",
            "summary": summary or "工作区已更新",
            "refresh_hints": dict(refresh_hints),
        }
    ]


def _include_followup_artifacts_for_action(action_type: str) -> bool:
    normalized = str(action_type or "").strip()
    if normalized in {"save_script", "extract_assets", "generate_asset_images", "generate_storyboard_images", "generate_video", "generate_audio", "rewrite_generation_prompts"}:
        return False
    return True


def _include_result_artifacts_for_action(action_type: str) -> bool:
    normalized = str(action_type or "").strip()
    if normalized == "extract_assets":
        return False
    return True


DISPLAY_ARTIFACT_TYPES = {
    "script_draft",
    "characters",
    "scenes",
    "props",
    "asset_bundle",
    "storyboard_summary",
    "storyboard_bundle",
    "storyboard_plan_bundle",
    "prompt_rewrite_bundle",
    "generation_bundle",
    "reference_search_results",
}


def _iter_display_artifacts(artifacts: Dict[str, Any], limit: int) -> List[Tuple[str, Any]]:
    rows: List[Tuple[str, Any]] = []
    seen: set[str] = set()
    for key, value in list((artifacts or {}).items()):
        artifact_key = str(key or "").strip()
        if artifact_key not in DISPLAY_ARTIFACT_TYPES:
            continue
        if value in (None, "", [], {}):
            continue
        signature = "{0}:{1}".format(artifact_key, _json_dumps(value)[:500])
        if signature in seen:
            continue
        seen.add(signature)
        rows.append((artifact_key, value))
        if len(rows) >= limit:
            break
    return rows


def _merge_suggested_actions(
    primary_actions: Optional[List[Dict[str, Any]]],
    secondary_actions: Optional[List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen_keys = set()
    primary_type_set = {
        str(item.get("type") or item.get("action_type") or item.get("action") or "").strip()
        for item in (primary_actions or [])
        if isinstance(item, dict) and str(item.get("type") or item.get("action_type") or item.get("action") or "").strip()
    }
    for collection_index, collection in enumerate((primary_actions or [], secondary_actions or [])):
        for item in collection or []:
            if not isinstance(item, dict):
                continue
            action_type = str(item.get("type") or item.get("action_type") or item.get("action") or "").strip()
            if collection_index == 1 and action_type in primary_type_set:
                continue
            payload_key = _json_dumps(item.get("payload") or {}) if isinstance(item.get("payload"), dict) else ""
            dedupe_key = (action_type, payload_key)
            if not action_type or dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            merged.append({"type": action_type, **item})
    return merged


def _looks_like_next_step_request(content: str) -> bool:
    text = str(content or "").strip().lower()
    if not text:
        return False
    if text in {"继续", "继续下一步", "下一步"}:
        return True
    return any(
        token in text
        for token in [
            "下一步",
            "接下来",
            "然后呢",
            "继续推进",
            "怎么推进",
            "做什么",
            "下一步怎么",
            "下一步做什么",
        ]
    )


def _ensure_next_step_suggested_actions(
    *,
    content: str,
    agent_response: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    if not _looks_like_next_step_request(content):
        return agent_response
    current_actions = agent_response.get("suggested_actions")
    if isinstance(current_actions, list) and current_actions:
        return agent_response

    fallback_context = {
        **context,
        "disable_llm": True,
        "latest_user_message": content or context.get("latest_user_message") or "",
    }
    try:
        stage_response = run_active_agent(fallback_context)
    except Exception:
        return agent_response

    stage_actions = stage_response.get("suggested_actions")
    if not isinstance(stage_actions, list) or not stage_actions:
        return agent_response

    merged_response = dict(stage_response)
    for key, value in (agent_response or {}).items():
        if key == "artifacts" and isinstance(value, dict):
            merged_response[key] = {
                **(stage_response.get("artifacts") if isinstance(stage_response.get("artifacts"), dict) else {}),
                **value,
            }
        elif key != "suggested_actions" and value not in (None, "", [], {}):
            merged_response[key] = value
    merged_response["suggested_actions"] = stage_actions
    return merged_response


def _should_delay_followup_actions_for_action(action_type: str, result: Optional[Dict[str, Any]]) -> bool:
    normalized = str(action_type or "").strip()
    payload = result.get("result") if isinstance(result, dict) and isinstance(result.get("result"), dict) else {}
    if normalized == "generate_asset_images" and isinstance(payload.get("submitted_assets"), list) and payload.get("submitted_assets"):
        return True
    if normalized == "generate_storyboard_images" and isinstance(payload.get("submitted_panels"), list) and payload.get("submitted_panels"):
        return True
    return False


def _build_structured_agent_turn(
    self,
    *,
    agent_response: Dict[str, Any],
    turn_source: str,
    message_override: Optional[str] = None,
    result_artifacts: Optional[Dict[str, Any]] = None,
    include_followup_artifacts: bool = True,
) -> Dict[str, Any]:
    message = str(message_override or agent_response.get("message") or "").strip()
    blocks: List[Dict[str, Any]] = []
    if message:
        blocks.append(
            {
                "id": uuid.uuid4().hex,
                "type": "text",
                "text": message,
            }
        )
    elif agent_response.get("stage_label"):
        blocks.append(
            {
                "id": uuid.uuid4().hex,
                "type": "reasoning_summary",
                "summary": "我已经整理好当前结果，可以继续推进下一步创作。",
            }
        )
    if include_followup_artifacts:
        artifacts = agent_response.get("artifacts") if isinstance(agent_response.get("artifacts"), dict) else {}
        for key, value in _iter_display_artifacts(artifacts, 6):
            blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "artifact_preview",
                    "artifact_type": key,
                    "title": key,
                    "data": value,
                }
            )
    if (
        isinstance(result_artifacts, dict)
        and str(result_artifacts.get("artifact_type") or "").strip() in DISPLAY_ARTIFACT_TYPES
    ):
        blocks.append(
            {
                "id": uuid.uuid4().hex,
                "type": "artifact_preview",
                "artifact_type": result_artifacts.get("artifact_type"),
                "title": result_artifacts.get("artifact_type"),
                "data": result_artifacts,
            }
        )
    elif isinstance(result_artifacts, dict):
        for key, value in _iter_display_artifacts(result_artifacts, 4):
            blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "artifact_preview",
                    "artifact_type": key,
                    "title": key,
                    "data": value,
                }
            )
    suggested_actions = agent_response.get("suggested_actions") if isinstance(agent_response.get("suggested_actions"), list) else []
    if suggested_actions:
        blocks.append(
            {
                "id": uuid.uuid4().hex,
                "type": "agent_actions",
                "actions": suggested_actions,
            }
        )
    return self._build_turn(
        role="assistant",
        blocks=blocks,
        metadata={
            "source": turn_source,
            "active_agent": agent_response.get("active_agent"),
            "stage": agent_response.get("stage"),
        },
    )


def _workspace_action_source_label(page_context: Dict[str, Any]) -> str:
    source_module = str((page_context or {}).get("source_module") or "").strip()
    return {
        "script_source": "原文页",
        "segment_table": "分镜表",
        "segment_media_workbench": "镜头工作台",
        "assets_module": "资产页",
    }.get(source_module, "工作区")


def _workspace_action_status_detail(action_label: str, page_context: Dict[str, Any]) -> str:
    source_label = _workspace_action_source_label(page_context)
    return f"已收到来自{source_label}的“{action_label or '工作区动作'}”请求，正在准备执行。"


def _should_queue_agent_action(action_type: str) -> bool:
    normalized = str(action_type or "").strip()
    return normalized in {"extract_assets", "extract_storyboard"}


def _run_agent_action_worker(
    cls,
    *,
    assistant_session_id: int,
    user_id: int,
    action_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    with session_scope() as db_session:
        service = cls(db_session)
        try:
            service._execute_agent_action_worker(
                assistant_session_id=assistant_session_id,
                user_id=user_id,
                action_type=action_type,
                payload=payload or {},
            )
        except HTTPException:
            pass
        except Exception:
            pass


def _finalize_agent_action_worker_error(
    self,
    *,
    session_obj: AssistantSession,
    action_type: str,
    error_text: str,
) -> None:
    tool_name = action_type if action_type in (set(TOOL_NAME_TO_ACTION_TYPE.keys()) | {"extract_storyboard", "generate_audio"}) else ""
    tool_card_id = f"action-tool-{action_type}"
    self._patch_runtime_feed_item(
        session_obj,
        "status-main",
        {
            "title": "执行失败",
            "body": error_text,
            "status": "failed",
        },
        publish=True,
    )
    failure_phase, failure_updates = select_public_reasoning_template(
        content=error_text,
        skill_hint={"id": "failure_recovery", "label": "现场救场"},
        phase="prepare_result",
        runtime_state=self._get_runtime_state(session_obj),
        fallback_intent="failure_recovery",
    )
    self._upsert_runtime_feed_item(
        session_obj,
        _runtime_feed_thought_card(
            card_id="thought-plan",
            variant=str(failure_phase.get("variant") or "my_judgment"),
            title=str(failure_phase.get("title") or "整理建议"),
            persona=str(failure_phase.get("persona") or "现场救场"),
            template_id=str(failure_phase.get("template_id") or ""),
            body=str(failure_phase.get("body") or "马上给你补救路线。"),
        ),
        publish=True,
    )
    if action_type == "extract_assets":
        self._patch_runtime_feed_item(
            session_obj,
            "asset-extract-summary",
            {
                "title": "资产提取失败",
                "body": error_text,
                "summary": error_text,
                "status": "failed",
            },
            publish=True,
        )
    if tool_name:
        self._complete_runtime_feed_item(
            session_obj,
            tool_card_id,
            {"status": "failed", "summary": error_text},
            publish=True,
        )
        self.publish_event(
            session_obj.id,
            {
                "type": "tool_call_failed",
                "tool_call_id": tool_card_id,
                "tool_name": tool_name,
                "loop_index": 1,
                "error": error_text,
            },
        )

    error_turn = self._append_error_turn(session_obj=session_obj, error_text=error_text)
    self._update_runtime_state(
        session_obj,
        project_changes=[],
        status_detail=error_text,
        clear_keys=[
            "draft_turn",
            "tool_activity",
            "pending_question_wizard",
            "skill_hint",
            "running_started_at",
            "execution_stage",
            "selected_panels",
            "resolved_model_choice",
            "selection_reason",
            "resume_hint",
            "reasoning_public_phase",
            "reasoning_public_phase_index",
            "reasoning_public_phase_started_ms",
            "public_reasoning_intent",
            "public_reasoning_phase",
            "public_reasoning_template_id",
        ],
        commit=False,
    )
    self._update_runtime_state(
        session_obj,
        reasoning_public_phase=failure_phase,
        reasoning_public_phase_index=failure_phase.get("active_index"),
        public_reasoning_intent=failure_updates.get("public_reasoning_intent"),
        public_reasoning_phase=failure_updates.get("public_reasoning_phase"),
        public_reasoning_template_id=failure_updates.get("public_reasoning_template_id"),
        public_reasoning_recent_template_ids=failure_updates.get("public_reasoning_recent_template_ids"),
        commit=False,
    )
    session_obj.status = "error"
    session_obj.updated_at = _utc_now()
    self.session.add(session_obj)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": error_turn})
    self._publish_status(session_obj)
    self._publish_runtime_delta(session_obj)
    self.publish_snapshot(session_obj.id)


def _execute_agent_action_worker(
    self,
    *,
    assistant_session_id: int,
    user_id: int,
    action_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    session_obj = self.session.get(AssistantSession, assistant_session_id)
    user = self.session.get(User, user_id)
    if not session_obj or not user:
        return {}
    team = self.session.get(Team, session_obj.team_id)
    if not team:
        return {}
    try:
        return _continue_execute_agent_action(
            self,
            session_obj=session_obj,
            user=user,
            team=team,
            action_type=action_type,
            payload=payload or {},
        )
    except HTTPException as exc:
        _finalize_agent_action_worker_error(
            self,
            session_obj=session_obj,
            action_type=action_type,
            error_text=self._http_exception_message(exc),
        )
        return {}
    except Exception as exc:
        error_text = str(exc)
        if isinstance(exc, StorySegmentParseError) and str(getattr(exc, "detail", "") or "").strip():
            detail = str(getattr(exc, "detail", "") or "").strip()
            if detail and detail != error_text:
                error_text = f"{error_text}：{detail}"
        _finalize_agent_action_worker_error(
            self,
            session_obj=session_obj,
            action_type=action_type,
            error_text=error_text,
        )
        return {}


def _continue_execute_agent_action(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    team: Team,
    action_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = payload or {}
    page_context = payload.get("page_context") if isinstance(payload.get("page_context"), dict) else {}
    script = self.session.get(Script, session_obj.script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    episode = self.session.get(Episode, session_obj.episode_id) if session_obj.episode_id else None
    runtime_state = self._get_runtime_state(session_obj)
    latest_user_message = _latest_user_message_before_agent_action(self, session_obj)

    def runtime_event_callback(event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        data = dict(payload or {})
        data["type"] = event_type
        if event_type == "storyboard_plan_delta":
            rows = [
                [
                    str(row.get("sequence_num") or ""),
                    str(row.get("story_fragment") or ""),
                    str(row.get("dialogue") or ""),
                    str(row.get("estimated_duration_seconds") or ""),
                ]
                for row in list(data.get("rows") or [])
                if isinstance(row, dict)
            ]
            total_duration_seconds = _storyboard_plan_total_seconds(data, rows)
            summary = str(data.get("summary") or "").strip()
            total_summary = f"\u603b\u9884\u8ba1\u65f6\u957f\uff1a{total_duration_seconds} \u79d2" if total_duration_seconds else ""
            if total_summary:
                summary = f"{summary}\n\n{total_summary}" if summary else total_summary
                rows.append(["\u5408\u8ba1", "", "", f"{total_duration_seconds} \u79d2"])
            table_patch = {
                "type": "table_card",
                "title": data.get("title") or "剧情片段规划",
                "columns": ["序号", "剧情片段", "对话", "预计时长"],
                "rows": rows,
                "summary": summary,
                "total_estimated_duration_seconds": total_duration_seconds,
                "status": "completed" if rows else "running",
            }
            if not self._patch_runtime_feed_item(session_obj, "storyboard-plan-table", table_patch, publish=True):
                self._upsert_runtime_feed_item(session_obj, {"id": "storyboard-plan-table", **table_patch}, publish=True)
        elif event_type == "storyboard_plan_ready":
            plan_id = str(data.get("plan_id") or "").strip()
            self._upsert_runtime_feed_item(
                session_obj,
                {
                    "id": "storyboard-plan-actions",
                    "type": "action_card",
                    "actions": [
                        {"type": "extract_storyboard", "label": "根据规划计划分镜", "payload": {"mode": "split_confirmed", "confirmed_plan_id": plan_id}},
                        {"type": "extract_storyboard", "label": "增加时长", "payload": {"mode": "plan_first", "plan_revision_instruction": "整体增加每个剧情片段的预计时长，保留剧情顺序。"}},
                        {"type": "extract_storyboard", "label": "增加分镜", "payload": {"mode": "plan_first", "plan_revision_instruction": "增加剧情片段数量，把关键动作拆得更细。"}},
                        {"type": "extract_storyboard", "label": "减少分镜", "payload": {"mode": "plan_first", "plan_revision_instruction": "减少剧情片段数量，合并节奏相近的片段。"}},
                        {"type": "extract_storyboard", "label": "细分某段", "payload": {"mode": "plan_first", "plan_revision_instruction": "请细分用户指定的剧情片段；如果没有指定，优先细分信息量最大的片段。"}},
                        {"type": "extract_storyboard", "label": "合并某几段", "payload": {"mode": "plan_first", "plan_revision_instruction": "请合并用户指定或节奏相近的剧情片段。"}},
                    ],
                    "status": "completed",
                },
                publish=True,
            )
        elif event_type == "storyboard_split_progress_delta":
            source_rows = [row for row in list(data.get("rows") or []) if isinstance(row, dict)]
            rows = [
                [
                    str(row.get("sequence_num") or ""),
                    str(row.get("story_fragment") or ""),
                    str(row.get("grid_count") or ""),
                    str(row.get("status") or "等待中"),
                ]
                for row in source_rows
            ]
            public_summaries = []
            event_summary = str(data.get("summary") or data.get("public_summary") or "").strip()
            if event_summary:
                public_summaries.append(event_summary)
            for row in source_rows:
                row.pop("error_summary", None)
                public_summary = str(row.get("public_summary") or row.get("summary") or "").strip()
                if public_summary and public_summary not in public_summaries:
                    public_summaries.append(public_summary)
            table_patch = {
                "type": "table_card",
                "title": data.get("title") or "正式分镜拆分进度",
                "columns": ["序号", "剧情片段", "宫格数", "状态"],
                "rows": rows,
                "summary": "\n".join(public_summaries[:2]),
                "status": "running",
            }
            if not self._patch_runtime_feed_item(session_obj, "storyboard-split-progress", table_patch, publish=True):
                self._upsert_runtime_feed_item(session_obj, {"id": "storyboard-split-progress", **table_patch}, publish=True)
        elif event_type == "prompt_rewrite_delta":
            source_rows = [row for row in list(data.get("rows") or []) if isinstance(row, dict)]
            rows = [
                [
                    str(row.get("sequence_num") or ""),
                    str(row.get("target_label") or row.get("target_kind") or ""),
                    str(row.get("original_prompt_summary") or row.get("original_summary") or ""),
                    str(row.get("new_prompt") or row.get("new_prompt_summary") or ""),
                    str(row.get("status") or "改写中"),
                ]
                for row in source_rows
            ]
            billing = data.get("billing") if isinstance(data.get("billing"), dict) else {}
            summary = str(data.get("summary") or "").strip()
            if billing.get("display"):
                summary = f"{summary}\n\n本次改写消耗 {billing.get('display')}" if summary else f"本次改写消耗 {billing.get('display')}"
            table_patch = {
                "type": "table_card",
                "title": data.get("title") or "提示词改写预览",
                "columns": ["序号", "改写目标", "原提示词摘要", "新提示词", "状态"],
                "rows": rows,
                "summary": summary,
                "status": "completed" if rows and all(str(row[-1]) != "改写中" for row in rows) else "running",
            }
            if not self._patch_runtime_feed_item(session_obj, "prompt-rewrite-preview", table_patch, publish=True):
                self._upsert_runtime_feed_item(session_obj, {"id": "prompt-rewrite-preview", **table_patch}, publish=True)
        elif event_type == "prompt_rewrite_ready":
            rewrite_id = str(data.get("rewrite_id") or "").strip()
            self._upsert_runtime_feed_item(
                session_obj,
                {
                    "id": "prompt-rewrite-actions",
                    "type": "action_card",
                    "actions": [
                        {"type": "rewrite_generation_prompts", "label": "保存提示词并生成", "payload": {"operation": "apply_and_generate", "rewrite_id": rewrite_id}},
                        {"type": "rewrite_generation_prompts", "label": "仅保存提示词", "payload": {"operation": "apply", "rewrite_id": rewrite_id}},
                        {"type": "rewrite_generation_prompts", "label": "继续调整", "payload": {"operation": "preview", "rewrite_id": rewrite_id}},
                        {"type": "rewrite_generation_prompts", "label": "取消", "payload": {"operation": "cancel", "rewrite_id": rewrite_id}},
                        {"type": "rewrite_generation_prompts", "label": "用上次生成提示词恢复", "payload": {"operation": "restore_last_generated"}},
                        {"type": "rewrite_generation_prompts", "label": "采用推荐模型并生成", "payload": {"operation": "apply_and_generate", "rewrite_id": rewrite_id, "use_recommended_model": True}},
                    ],
                    "status": "completed",
                },
                publish=True,
            )
        elif event_type == "prompt_rewrite_applied":
            self._patch_runtime_feed_item(
                session_obj,
                "prompt-rewrite-preview",
                {"status": "completed", "summary": "提示词已保存到当前分镜。"},
                publish=True,
            )
        self.publish_event(session_obj.id, data)

    context = build_agent_context(
        self.session,
        user=user,
        team=team,
        script=script,
        episode=episode,
        latest_user_message=latest_user_message,
        workflow=self._build_workflow_snapshot(session_obj),
        page_context=page_context,
        latest_artifacts=runtime_state.get("latest_artifacts") if isinstance(runtime_state.get("latest_artifacts"), dict) else {},
        runtime_event_callback=runtime_event_callback,
        now=_utc_now(),
    )
    context["assistant_session_id"] = session_obj.id
    context["assistant_session_profile"] = session_obj.profile or ""
    context["assistant_session_channel"] = session_obj.channel or ""

    facts_cards = _runtime_feed_facts_cards(
        {
            "workspace_facts": context.get("workspace_facts_preview") or {},
            "stage_facts": (context.get("stage_read_model") or {}).get("facts") or {},
        }
    )
    for card in facts_cards:
        self._upsert_runtime_feed_item(session_obj, card, publish=True)

    action_label = _display_action_label(action_type, payload)
    tool_name = action_type if action_type in (set(TOOL_NAME_TO_ACTION_TYPE.keys()) | {"extract_storyboard", "generate_audio"}) else ""
    if tool_name:
        self._remove_runtime_feed_item(session_obj, "thought-plan", publish=True)
        self._patch_runtime_feed_item(
            session_obj,
            "status-main",
            {
                "title": "开始执行工具",
                "body": f"正在执行 {action_label or tool_name}。",
                "status": "running",
            },
            publish=True,
        )
        tool_card_id = f"action-tool-{action_type}"
        display = build_tool_card(tool_name, status="running")
        self._upsert_runtime_feed_item(
            session_obj,
            {
                "id": tool_card_id,
                **display,
                "status": "running",
                "summary": f"正在执行 {display.get('title_cn') or action_label or tool_name}",
            },
            publish=True,
        )
        self.publish_event(
            session_obj.id,
            {
                "type": "tool_call_started",
                "tool_call_id": tool_card_id,
                "tool_name": tool_name,
                "loop_index": 1,
                "arguments": _json_dumps(payload),
            },
        )
        try:
            result = execute_internal_director_tool(
                service=self,
                session_obj=session_obj,
                user=user,
                team=team,
                context=context,
                tool_name=tool_name,
                arguments=payload,
            )
        except Exception:
            self._complete_runtime_feed_item(
                session_obj,
                tool_card_id,
                {"status": "failed", "summary": f"{action_label or tool_name} 执行失败"},
                publish=True,
            )
            raise
        self._complete_runtime_feed_item(
            session_obj,
            tool_card_id,
            {
                "status": "completed",
                "summary": str(result.get("summary") or result.get("message") or f"{action_label or tool_name} 已执行完成"),
            },
            publish=True,
        )
        self.publish_event(
            session_obj.id,
            {
                "type": "tool_call_completed",
                "tool_call_id": tool_card_id,
                "tool_name": tool_name,
                "loop_index": 1,
                "summary": str(result.get("summary") or result.get("message") or ""),
                "result": result.get("result") or {},
            },
        )
    else:
        result = execute_structured_agent_action(context, action_type, payload)

    latest_artifacts = dict(runtime_state.get("latest_artifacts") or {})
    if isinstance(result.get("artifacts"), dict) and result.get("artifacts"):
        latest_artifacts.update(result.get("artifacts") or {})
    if isinstance(result.get("result"), dict) and result["result"].get("artifact_type"):
        artifact_key = str(result["result"]["artifact_type"] or "").strip()
        if artifact_key:
            latest_artifacts[artifact_key] = result["result"]

    provisional_stage = get_next_stage_after_action(
        action_type=action_type,
        current_stage=context.get("creative_stage") or "",
        action_result=result,
        facts=context.get("stage_read_model", {}).get("facts") or {},
    )
    provisional_context = dict(context)
    provisional_context["creative_stage"] = provisional_stage
    provisional_context["creative_stage_label"] = CREATIVE_STAGE_LABELS.get(provisional_stage, provisional_stage)
    provisional_context["disable_llm"] = True
    provisional_context["stage_read_model"] = {
        **(context.get("stage_read_model") or {}),
        "creative_stage": provisional_stage,
        "creative_stage_label": CREATIVE_STAGE_LABELS.get(provisional_stage, provisional_stage),
        "active_agent": STAGE_AGENT_MAP.get(provisional_stage, "director_agent"),
        "active_agent_label": ACTIVE_AGENT_LABELS.get(STAGE_AGENT_MAP.get(provisional_stage, "director_agent"), "编剧专家"),
    }
    provisional_context["latest_artifacts"] = latest_artifacts
    agent_response = run_active_agent(provisional_context)
    refreshed_context = build_agent_context(
        self.session,
        user=user,
        team=team,
        script=script,
        episode=episode,
        latest_user_message="",
        workflow=self._build_workflow_snapshot(session_obj),
        page_context=page_context,
        latest_artifacts=latest_artifacts,
        now=_utc_now(),
    )
    refreshed_context["disable_llm"] = True
    final_stage = refreshed_context.get("creative_stage") or ""
    if final_stage and final_stage == provisional_stage:
        next_stage_hint = result.get("next_stage_hint") or agent_response.get("next_stage_hint")
    else:
        final_response = run_active_agent(refreshed_context)
        agent_response = final_response
        next_stage_hint = result.get("next_stage_hint") or final_response.get("next_stage_hint")

    if _should_delay_followup_actions_for_action(action_type, result):
        final_suggested_actions = []
        agent_response = {**agent_response, "suggested_actions": []}
    elif (
        action_type == "extract_storyboard"
        and isinstance(result.get("result"), dict)
        and str(result["result"].get("artifact_type") or "").strip() == "storyboard_plan_bundle"
    ):
        final_suggested_actions = result.get("suggested_actions") if isinstance(result.get("suggested_actions"), list) else []
        agent_response = {**agent_response, "suggested_actions": final_suggested_actions}
    else:
        final_suggested_actions = _merge_suggested_actions(
            result.get("suggested_actions") if isinstance(result.get("suggested_actions"), list) else [],
            agent_response.get("suggested_actions") if isinstance(agent_response.get("suggested_actions"), list) else [],
        )
    if final_suggested_actions:
        agent_response = {**agent_response, "suggested_actions": final_suggested_actions}
    if isinstance(agent_response.get("artifacts"), dict):
        agent_response = {**agent_response, "artifacts": {**latest_artifacts, **(agent_response.get("artifacts") or {})}}

    project_changes = _refresh_hints_to_project_changes(result.get("refresh_hints") or {}, summary=result.get("message") or "")
    assistant_turn = _build_structured_agent_turn(
        self,
        agent_response=agent_response,
        turn_source="structured_agent_action",
        message_override=result.get("message"),
        result_artifacts=(
            result.get("result")
            if _include_result_artifacts_for_action(action_type) and isinstance(result.get("result"), dict)
            else {}
        ),
        include_followup_artifacts=_include_followup_artifacts_for_action(action_type),
    )
    self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    if str(result.get("message") or "").strip():
        self._upsert_runtime_feed_item(
            session_obj,
            {
                "id": "content-final",
                "type": "content_card",
                "title": "阶段总结",
                "markdown": str(result.get("message") or "").strip(),
                "status": "completed",
            },
            publish=True,
        )
    result_payload = result.get("result") if isinstance(result.get("result"), dict) else {}
    result_artifact_type = str(result_payload.get("artifact_type") or "").strip()
    result_status = str(result_payload.get("status") or "").strip()
    skip_final_actions_card = (
        (
            action_type == "extract_storyboard"
            and result_artifact_type == "storyboard_plan_bundle"
        )
        or (
            action_type == "rewrite_generation_prompts"
            and result_artifact_type == "prompt_rewrite_bundle"
            and result_status in {"ready", "cancelled", "applied"}
        )
    )
    if isinstance(final_suggested_actions, list) and final_suggested_actions and not skip_final_actions_card:
        self._upsert_runtime_feed_item(
            session_obj,
            {
                "id": "actions-final",
                "type": "action_card",
                "actions": final_suggested_actions,
                "status": "completed",
            },
            publish=True,
        )
    self._update_runtime_state(
        session_obj,
        creative_stage=agent_response.get("stage"),
        creative_stage_label=agent_response.get("stage_label"),
        active_agent=agent_response.get("active_agent"),
        active_agent_label=agent_response.get("active_agent_label"),
        next_stage_hint=next_stage_hint,
        latest_artifacts=agent_response.get("artifacts") or latest_artifacts,
        project_changes=project_changes,
        status_detail="",
        clear_keys=["running_started_at"],
        commit=False,
    )
    session_obj.status = "completed"
    session_obj.updated_at = _utc_now()
    self.session.add(session_obj)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    if project_changes:
        self.publish_event(session_obj.id, {"type": "project_change", "project_changes": project_changes})
    self._publish_status(session_obj)
    self._publish_runtime_delta(session_obj)
    self.publish_snapshot(session_obj.id)
    return {
        "snapshot": self.get_snapshot(session_obj=session_obj),
        "action_result": result,
        "agent_response": agent_response,
    }


def execute_agent_action(
    self,
    *,
    session_obj: AssistantSession,
    user: User,
    team: Team,
    action_type: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = payload or {}
    page_context = payload.get("page_context") if isinstance(payload.get("page_context"), dict) else {}
    action_label = _display_action_label(action_type, payload)
    script = self.session.get(Script, session_obj.script_id)
    if script is None:
        raise HTTPException(status_code=404, detail="project_not_found")
    episode = self.session.get(Episode, session_obj.episode_id) if session_obj.episode_id else None
    runtime_state = self._get_runtime_state(session_obj)
    latest_user_message = _latest_user_message_before_agent_action(self, session_obj)
    context = build_agent_context(
        self.session,
        user=user,
        team=team,
        script=script,
        episode=episode,
        latest_user_message=latest_user_message,
        workflow=self._build_workflow_snapshot(session_obj),
        page_context=page_context,
        latest_artifacts=runtime_state.get("latest_artifacts") if isinstance(runtime_state.get("latest_artifacts"), dict) else {},
        now=_utc_now(),
    )

    skill_hint = {
        "id": action_type,
        "label": action_label,
        "slash_command": "",
        "category": "workspace_action",
    }
    tool_activity = self._build_tool_activity(skill_hint, session_obj)
    public_reasoning_state = dict(runtime_state or {})
    public_reasoning_state.pop("public_reasoning_intent", None)
    public_reasoning_state.pop("public_reasoning_phase", None)
    public_reasoning_state.pop("public_reasoning_template_id", None)
    public_phase, public_reasoning_updates = _select_public_reasoning_phase(
        content=action_label or action_type,
        skill_hint=skill_hint,
        length=0,
        runtime_state=public_reasoning_state,
    )
    runtime_feed = _initial_runtime_feed(session_obj, skill_hint, "internal", public_phase=public_phase)
    draft_turn = self._build_draft_turn(
        content=action_label or action_type,
        skill_hint=skill_hint,
        tool_activity=tool_activity,
    )

    session_obj.status = "running"
    session_obj.updated_at = _utc_now()
    self._update_runtime_state(
        session_obj,
        draft_turn=draft_turn,
        status_detail=_workspace_action_status_detail(action_label, page_context),
        tool_activity=tool_activity,
        project_changes=[],
        skill_hint=skill_hint,
        running_started_at=_iso(session_obj.updated_at),
        runtime_feed=runtime_feed,
        reasoning_public_phase=public_phase,
        reasoning_public_phase_index=public_phase.get("active_index"),
        public_reasoning_intent=public_reasoning_updates.get("public_reasoning_intent"),
        public_reasoning_phase=public_reasoning_updates.get("public_reasoning_phase"),
        public_reasoning_template_id=public_reasoning_updates.get("public_reasoning_template_id"),
        public_reasoning_recent_template_ids=public_reasoning_updates.get("public_reasoning_recent_template_ids"),
        clear_keys=[
            "pending_question_wizard",
            "execution_stage",
            "selected_panels",
            "resolved_model_choice",
            "selection_reason",
            "resume_hint",
        ],
        commit=False,
    )
    self.session.add(session_obj)

    user_turn = self._build_turn(
        role="user",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "text",
                "text": action_label,
            }
        ],
        metadata={"agent_action": action_type, "payload": payload, "page_context": page_context},
    )
    self._insert_turn_event(session_obj=session_obj, turn=user_turn)
    self.session.commit()
    self.publish_event(session_obj.id, {"type": "patch", "turn": user_turn})
    self._publish_status(session_obj)
    self._publish_runtime_delta(session_obj)
    self.publish_snapshot(session_obj.id)

    if _should_queue_agent_action(action_type):
        worker = threading.Thread(
            target=self.run_agent_action_worker,
            kwargs={
                "assistant_session_id": session_obj.id,
                "user_id": user.id,
                "action_type": action_type,
                "payload": payload,
            },
            daemon=True,
        )
        worker.start()
        return {"snapshot": self.get_snapshot(session_obj=session_obj), "queued": True}

    return _continue_execute_agent_action(
        self,
        session_obj=session_obj,
        user=user,
        team=team,
        action_type=action_type,
        payload=payload,
    )


AssistantRuntimeService._build_tool_activity = _build_tool_activity
AssistantRuntimeService._build_draft_turn = _build_draft_turn
AssistantRuntimeService._append_error_turn = _append_error_turn
AssistantRuntimeService._serialize_pending_question = _serialize_pending_question
AssistantRuntimeService._update_reasoning_progress = _update_reasoning_progress
AssistantRuntimeService._build_question_resolved_turn = _build_question_resolved_turn
AssistantRuntimeService._submit_panel_image_generation = _submit_panel_image_generation
AssistantRuntimeService._answer_generate_panel_image_question = _answer_generate_panel_image_question
AssistantRuntimeService._execute_generate_panel_image_skill = _execute_generate_panel_image_skill
AssistantRuntimeService._create_panel_video_wizard_v2 = delegated_create_panel_video_wizard_v2
AssistantRuntimeService._submit_panel_video_generation = delegated_submit_panel_video_generation_v2
AssistantRuntimeService._answer_generate_panel_video_question = delegated_answer_generate_panel_video_question_v2
AssistantRuntimeService._execute_generate_panel_video_skill = delegated_execute_generate_panel_video_skill_v2
AssistantRuntimeService._submit_episode_dubbing_generation = _submit_episode_dubbing_generation
AssistantRuntimeService._answer_generate_episode_dubbing_question = _answer_generate_episode_dubbing_question
AssistantRuntimeService._execute_generate_episode_dubbing_skill = _execute_generate_episode_dubbing_skill
AssistantRuntimeService.start_message = start_message
AssistantRuntimeService.run_background_worker = classmethod(_run_background_worker)
AssistantRuntimeService._execute_message = _execute_message
AssistantRuntimeService.answer_question = answer_question
AssistantRuntimeService.run_answer_question_worker = classmethod(_run_answer_question_worker)
AssistantRuntimeService._continue_answer_question = _continue_answer_question
AssistantRuntimeService._execute_internal_director_message = _execute_internal_director_message
AssistantRuntimeService._execute_external_message = _execute_external_message
AssistantRuntimeService.interrupt_session = interrupt_session
AssistantRuntimeService.serialize_session_meta = _serialize_session_meta_with_agent_state
AssistantRuntimeService.execute_agent_action = execute_agent_action
AssistantRuntimeService.run_agent_action_worker = classmethod(_run_agent_action_worker)
AssistantRuntimeService._execute_agent_action_worker = _execute_agent_action_worker
