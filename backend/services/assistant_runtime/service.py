from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime
from queue import Empty, Queue
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy import desc
from sqlmodel import Session, select

from core.security import encode_id
from database import session_scope
from models import (
    AssistantPendingQuestion,
    AssistantSession,
    AssistantTranscriptEvent,
    DirectorAgentMessage,
    DirectorAgentSession,
    Episode,
    ExternalAgentSession,
    Script,
    SharedResource,
    Team,
    User,
)
from services.access_service import require_episode_team_access, require_script_team_access
from services.agent_workflow_service import AgentWorkflowService
from services.director_agent_service import DirectorAgentService
from services.external_agent_import_service import (
    import_character_assets,
    import_panels_to_episode,
    import_script_content,
)
from services.external_agent_service import append_chat_message
from .video_model_selector import build_video_skill_metadata


def _utc_now() -> datetime:
    return datetime.utcnow()


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


def _json_loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _normalize_target(target: Optional[str], session_obj: AssistantSession) -> str:
    text = str(target or "").strip().lower()
    if text in {"internal", "external"}:
        return text
    if session_obj.profile == "openclaw_public":
        return "internal"
    if session_obj.channel == "external" or session_obj.profile in {"project_bridge", "openclaw"}:
        return "external"
    return "internal"


def _derive_title(content: str, default_title: str) -> str:
    text = " ".join(str(content or "").strip().split())
    if not text:
        return default_title
    if len(text) <= 24:
        return text
    return "{0}...".format(text[:24].rstrip())


def _derive_title_from_payload(
    content: Optional[str],
    attachments: Optional[List[Dict[str, Any]]],
    default_title: str,
) -> str:
    text_title = _derive_title(str(content or ""), "")
    if text_title:
        return text_title
    return default_title


def _build_attachment_only_message(attachments: Optional[List[Dict[str, Any]]]) -> str:
    count = len(attachments or [])
    if count <= 0:
        return ""
    if count == 1:
        return "我上传了 1 张参考图片，请结合它继续处理当前任务。"
    return "我上传了 {0} 张参考图片，请结合这些参考图继续处理当前任务。".format(count)


SKILL_CATALOG = [
    {
        "id": "read_project_context",
        "label": "读项目上下文",
        "description": "读取当前项目、剧集、分镜和资源概览。",
        "slash_command": "/项目",
        "category": "context",
        "requires_confirmation": False,
    },
    {
        "id": "split_episode_source",
        "label": "拆分镜",
        "description": "分析剧集原文并规划拆镜路径。",
        "slash_command": "/拆分镜",
        "category": "storyboard",
        "requires_confirmation": True,
    },
    {
        "id": "parse_story_segments",
        "label": "写分镜",
        "description": "生成结构化导演稿和分镜草稿。",
        "slash_command": "/写分镜",
        "category": "storyboard",
        "requires_confirmation": True,
    },
    {
        "id": "generate_panel_image",
        "label": "出图",
        "description": "为分镜发起图片生成任务。",
        "slash_command": "/出图",
        "category": "generation",
        "requires_confirmation": True,
    },
    {
        "id": "generate_panel_video",
        "label": "视频",
        "description": "为分镜发起视频生成任务。",
        "slash_command": "/视频",
        "category": "generation",
        "requires_confirmation": True,
    },
    {
        "id": "generate_episode_dubbing",
        "label": "配音",
        "description": "为当前剧集生成配音或旁白任务。",
        "slash_command": "/配音",
        "category": "generation",
        "requires_confirmation": True,
    },
    {
        "id": "extract_project_assets",
        "label": "提取角色",
        "description": "从剧本中提取角色、场景、道具等资产建议。",
        "slash_command": "/提取角色",
        "category": "asset",
        "requires_confirmation": True,
    },
    {
        "id": "delegate_to_external_agent",
        "label": "站外协作",
        "description": "把当前任务委托给已绑定的站外 Agent。",
        "slash_command": "/站外协作",
        "category": "bridge",
        "requires_confirmation": False,
    },
]

SKILL_ID_MAP = dict((item["id"], item) for item in SKILL_CATALOG if item.get("id"))
SKILL_ALIAS_MAP = dict((item["slash_command"], item) for item in SKILL_CATALOG if item.get("slash_command"))
NATURAL_LANGUAGE_SKILL_KEYWORDS = {
    "split_episode_source": ["拆分镜", "拆分镜头", "拆镜", "分镜拆分"],
    "parse_storyboard_draft": ["写分镜", "生成分镜", "规划分镜", "做分镜"],
    "generate_panel_image": ["出图", "生图", "生成图片", "生成配图", "做图", "画图"],
    "generate_panel_video": ["做视频", "生成视频", "出视频", "做成视频", "生成一段视频", "视频化", "转视频", "动起来"],
    "generate_episode_dubbing": ["配音", "配个音", "做配音", "生成配音", "生成旁白", "做旁白", "朗读", "念出来", "念一下", "生成音频", "生成语音"],
    "extract_project_assets": ["提取角色", "提取资产", "提取场景", "提取道具", "抽角色", "抽资产"],
    "delegate_to_external_agent": ["站外协作", "站外agent", "外部agent", "委托给站外", "同步到站外"],
}
NATURAL_LANGUAGE_SKILL_PATTERNS = {
    "generate_panel_video": [
        re.compile(r"(帮我|给我|给|把).{0,24}(做|生成|出|转成).{0,12}(视频|短片|动起来)", re.IGNORECASE),
        re.compile(r"(视频|短片).{0,18}(做|生成|出|转成)", re.IGNORECASE),
        re.compile(r"(分镜|镜头|第\s*\d+镜).{0,18}(视频|动起来)", re.IGNORECASE),
    ],
    "generate_panel_image": [
        re.compile(r"(帮我|给我|给|把).{0,24}(出图|生图|生成图片|画图|做图)", re.IGNORECASE),
        re.compile(r"(生成|做|出).{0,18}(分镜|镜头|第\s*\d+镜).{0,12}(图片|配图|图像|插图)", re.IGNORECASE),
        re.compile(r"(分镜|镜头|第\s*\d+镜).{0,18}(图片|配图|图像|插图)", re.IGNORECASE),
    ],
    "generate_episode_dubbing": [
        re.compile(r"(帮我|给我|给|把).{0,24}(配音|旁白|朗读|生成语音|生成音频)", re.IGNORECASE),
        re.compile(r"(分镜|剧集|这一集|这集).{0,18}(配音|旁白|朗读|音频|语音)", re.IGNORECASE),
    ],
}
SKILL_INTENT_QUESTION_KEYWORDS = ("怎么", "如何", "收费", "价格", "多少钱", "是否", "能不能", "支持", "是什么", "有哪些")
SKILL_INTENT_NEGATION_PATTERN = re.compile(
    r"(?:不要|先别|暂时别|先不用|不用).{0,6}(?:拆分镜|写分镜|出图|生图|图片|视频|配音|旁白|朗读|提取角色|站外)",
    re.IGNORECASE,
)


def _skill_hint_from_definition(
    skill: Optional[Dict[str, Any]],
    *,
    match_source: str = "slash",
    matched_text: str = "",
) -> Optional[Dict[str, Any]]:
    if not skill:
        return None
    hint = {
        "id": skill.get("id"),
        "label": skill.get("label"),
        "slash_command": skill.get("slash_command"),
        "category": skill.get("category"),
    }
    if match_source:
        hint["match_source"] = match_source
    if matched_text:
        hint["matched_text"] = matched_text
    return hint


def _looks_like_capability_question(text: str) -> bool:
    normalized = " ".join(str(text or "").strip().split()).lower()
    if not normalized:
        return False
    return any(keyword in normalized for keyword in SKILL_INTENT_QUESTION_KEYWORDS)


def _detect_media_skill_intent(text: str) -> Optional[str]:
    normalized = " ".join(str(text or "").strip().split()).lower()
    if not normalized:
        return None

    has_panel_scope = bool(re.search(r"(\d+\s*[-~到至]\s*\d+)|(\d+\s*[，,、]\s*\d+)|前\s*\d+\s*镜|最后\s*\d+\s*镜|偶数镜|奇数镜|分镜|镜头|第\s*\d+\s*镜", normalized))
    has_image_words = any(keyword in normalized for keyword in ["图片", "配图", "图像", "插图", "出图", "生图", "画图", "做图"])
    has_video_words = any(keyword in normalized for keyword in ["视频", "短片", "动起来", "视频化", "转视频"])
    has_audio_words = any(keyword in normalized for keyword in ["配音", "旁白", "朗读", "语音", "音频"])

    if has_video_words and has_panel_scope:
        return "generate_panel_video"
    if has_image_words and has_panel_scope:
        return "generate_panel_image"
    if has_audio_words:
        return "generate_episode_dubbing"
    return None


class AssistantRuntimeEventManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers = {}
        self._history = {}
        self._event_seq = {}
        self._history_limit = 200

    def subscribe(self, session_key: str) -> Queue:
        queue = Queue(maxsize=200)
        with self._lock:
            self._subscribers.setdefault(session_key, []).append(queue)
        return queue

    def unsubscribe(self, session_key: str, queue: Queue) -> None:
        with self._lock:
            subscribers = list(self._subscribers.get(session_key, []))
            if queue in subscribers:
                subscribers.remove(queue)
            if subscribers:
                self._subscribers[session_key] = subscribers
            elif session_key in self._subscribers:
                del self._subscribers[session_key]

    def publish(self, session_key: str, event: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            seq = int(self._event_seq.get(session_key) or 0) + 1
            self._event_seq[session_key] = seq
            payload = dict(event or {})
            payload["event_id"] = seq
            history = list(self._history.get(session_key) or [])
            history.append(payload)
            if len(history) > self._history_limit:
                history = history[-self._history_limit :]
            self._history[session_key] = history
            subscribers = list(self._subscribers.get(session_key, []))
        for queue in subscribers:
            try:
                queue.put_nowait(payload)
            except Exception:
                try:
                    queue.get_nowait()
                except Exception:
                    pass
                try:
                    queue.put_nowait(payload)
                except Exception:
                    pass
        return payload

    def get_events_since(self, session_key: str, since_event_id: int) -> List[Dict[str, Any]]:
        with self._lock:
            history = list(self._history.get(session_key) or [])
        return [dict(item) for item in history if int(item.get("event_id") or 0) > int(since_event_id or 0)]

    def get_last_event_id(self, session_key: str) -> int:
        with self._lock:
            return int(self._event_seq.get(session_key) or 0)

    def get_event(self, queue: Queue, timeout: float = 30.0) -> Optional[Dict[str, Any]]:
        try:
            return queue.get(timeout=timeout)
        except Empty:
            return None


assistant_runtime_event_manager = AssistantRuntimeEventManager()


class AssistantRuntimeService:
    DEFAULT_SESSION_TITLE = "新对话"

    def __init__(self, session: Session):
        self.session = session

    # ==================== session lifecycle ====================

    def list_script_sessions(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        channel: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        require_script_team_access(self.session, team, script_id)
        statement = (
            select(AssistantSession)
            .where(
                AssistantSession.script_id == script_id,
                AssistantSession.user_id == user.id,
            )
            .order_by(desc(AssistantSession.updated_at), desc(AssistantSession.id))
        )
        items = self.session.exec(statement).all()
        result = []
        for item in items:
            if channel and item.channel != channel:
                continue
            if profile and item.profile != profile:
                continue
            result.append(self.serialize_session_meta(item))
        return result

    def list_skills(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
    ) -> List[Dict[str, Any]]:
        require_script_team_access(self.session, team, script_id)
        result: List[Dict[str, Any]] = []
        for item in SKILL_CATALOG:
            payload = dict(item or {})
            if payload.get("id") == "generate_panel_video":
                payload.update(build_video_skill_metadata())
            result.append(payload)
        grouped = AgentWorkflowService(self.session).grouped_capabilities()
        for item in grouped.get("process_capabilities") or []:
            payload = dict(item or {})
            payload["group"] = "process"
            result.append(payload)
        for item in grouped.get("optimization_capabilities") or []:
            payload = dict(item or {})
            payload["group"] = "optimization"
            result.append(payload)
        return result

    def create_session(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: Optional[int] = None,
        title: Optional[str] = None,
        channel: str = "internal",
        profile: str = "director",
        linked_external_session_id: Optional[int] = None,
    ) -> AssistantSession:
        require_script_team_access(self.session, team, script_id)
        if episode_id:
            episode = require_episode_team_access(self.session, team, episode_id)
            if episode.script_id != script_id:
                raise HTTPException(status_code=400, detail="当前剧集不属于该会话所在项目")
        now = _utc_now()
        metadata = {
            "version": "assistant_v2",
            "created_from": "assistant_runtime",
        }

        legacy_session = None
        if channel == "internal" and profile == "director":
            director_service = DirectorAgentService(self.session)
            legacy_session = director_service.create_session(
                user=user,
                script_id=script_id,
                episode_id=episode_id,
                title=title or self.DEFAULT_SESSION_TITLE,
            )
            metadata["legacy_director_session_id"] = legacy_session.id

        default_external_session = None
        if linked_external_session_id:
            default_external_session = self._require_external_session(
                user=user,
                script_id=script_id,
                external_session_id=linked_external_session_id,
            )
        else:
            default_external_session = self._find_default_external_session(
                script_id=script_id,
                user_id=user.id,
                episode_id=episode_id,
            )

        item = AssistantSession(
            script_id=script_id,
            episode_id=episode_id,
            user_id=user.id,
            team_id=team.id,
            channel=str(channel or "internal").strip() or "internal",
            profile=str(profile or "director").strip() or "director",
            status="idle",
            title=(title or (legacy_session.title if legacy_session else None) or self.DEFAULT_SESSION_TITLE),
            linked_external_session_id=default_external_session.id if default_external_session else None,
            metadata_json=_json_dumps(metadata),
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        self.session.commit()
        self.session.refresh(item)
        script = self.session.get(Script, script_id)
        if script:
            workflow_service = AgentWorkflowService(self.session)
            workflow_service.ensure_script_states(script=script)
            if episode_id:
                episode = self.session.get(Episode, episode_id)
                if episode:
                    workflow_service.ensure_episode_state_for_episode(script=script, episode=episode)
            self.session.commit()
        return item

    def get_or_create_openclaw_bridge_session(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: int,
        external_session: ExternalAgentSession,
    ) -> AssistantSession:
        require_script_team_access(self.session, team, script_id)
        statement = (
            select(AssistantSession)
            .where(
                AssistantSession.script_id == script_id,
                AssistantSession.user_id == user.id,
                AssistantSession.episode_id == episode_id,
                AssistantSession.channel == "external",
                AssistantSession.profile == "openclaw",
                AssistantSession.linked_external_session_id == external_session.id,
            )
            .order_by(desc(AssistantSession.updated_at), desc(AssistantSession.id))
        )
        existing = self.session.exec(statement).first()
        if existing:
            return existing
        return self.create_session(
            user=user,
            team=team,
            script_id=script_id,
            episode_id=episode_id,
            title=external_session.base_name or self.DEFAULT_SESSION_TITLE,
            channel="external",
            profile="openclaw",
            linked_external_session_id=external_session.id,
        )

    def get_or_create_openclaw_public_session(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: Optional[int],
        session_id: Optional[int] = None,
        title: Optional[str] = None,
    ) -> AssistantSession:
        require_script_team_access(self.session, team, script_id)
        if session_id:
            existing = self.require_session(session_id=session_id, user=user)
            if existing.script_id != script_id or existing.profile != "openclaw_public":
                raise HTTPException(status_code=404, detail="OpenClaw public session not found")
            if episode_id and existing.episode_id != episode_id:
                raise HTTPException(status_code=404, detail="OpenClaw public session not found")
            return existing

        statement = (
            select(AssistantSession)
            .where(
                AssistantSession.script_id == script_id,
                AssistantSession.user_id == user.id,
                AssistantSession.channel == "external",
                AssistantSession.profile == "openclaw_public",
            )
            .order_by(desc(AssistantSession.updated_at), desc(AssistantSession.id))
        )
        items = self.session.exec(statement).all()
        for item in items:
            if episode_id is None or item.episode_id == episode_id:
                return item

        return self.create_session(
            user=user,
            team=team,
            script_id=script_id,
            episode_id=episode_id,
            title=title or self.DEFAULT_SESSION_TITLE,
            channel="external",
            profile="openclaw_public",
        )

    def require_session(self, *, session_id: int, user: User) -> AssistantSession:
        item = self.session.get(AssistantSession, session_id)
        if not item:
            raise HTTPException(status_code=404, detail="会话不存在")
        if item.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问当前会话")
        return item

    def update_session_context(
        self,
        *,
        session_obj: AssistantSession,
        user: User,
        team: Team,
        episode_id: Optional[int],
        automation_mode: Optional[str] = None,
    ) -> AssistantSession:
        require_script_team_access(self.session, team, session_obj.script_id)
        if session_obj.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权修改当前会话")
        if session_obj.status == "running":
            raise HTTPException(status_code=409, detail="当前会话仍在处理中，请稍后再试")

        next_episode_id: Optional[int] = None
        if episode_id:
            episode = require_episode_team_access(self.session, team, episode_id)
            if episode.script_id != session_obj.script_id:
                raise HTTPException(status_code=400, detail="当前剧集不属于该会话所在项目")
            next_episode_id = episode.id

        if session_obj.episode_id == next_episode_id and automation_mode is None:
            return session_obj

        if automation_mode is not None:
            meta = _json_loads(session_obj.metadata_json, {})
            meta["automation_mode"] = automation_mode
            session_obj.metadata_json = _json_dumps(meta)
            # 同步写入 legacy DirectorAgentSession
            legacy_meta = self._get_session_metadata(session_obj)
            legacy_session_id = legacy_meta.get("legacy_director_session_id")
            if legacy_session_id:
                legacy_session = self.session.get(DirectorAgentSession, int(legacy_session_id))
                if legacy_session:
                    legacy_config = _json_loads(legacy_session.session_config_json, {})
                    legacy_config["automation_mode"] = automation_mode
                    legacy_session.session_config_json = _json_dumps(legacy_config)
                    self.session.add(legacy_session)

        session_obj.episode_id = next_episode_id
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)

        metadata = self._get_session_metadata(session_obj)
        legacy_session_id = metadata.get("legacy_director_session_id")
        if legacy_session_id:
            legacy_session = self.session.get(DirectorAgentSession, int(legacy_session_id))
            if legacy_session:
                legacy_session.episode_id = next_episode_id
                legacy_session.context_snapshot_json = _json_dumps(
                    self._build_context_snapshot(
                        script_id=session_obj.script_id,
                        episode_id=next_episode_id,
                    )
                )
                legacy_session.updated_at = session_obj.updated_at
                self.session.add(legacy_session)

        self.session.commit()
        self.session.refresh(session_obj)
        self.publish_snapshot(session_obj.id)
        return session_obj

    def delete_session(self, *, session_obj: AssistantSession) -> None:
        metadata = _json_loads(session_obj.metadata_json, {})
        legacy_session_id = metadata.get("legacy_director_session_id")

        events = self.session.exec(
            select(AssistantTranscriptEvent).where(AssistantTranscriptEvent.session_id == session_obj.id)
        ).all()
        for item in events:
            self.session.delete(item)

        questions = self.session.exec(
            select(AssistantPendingQuestion).where(AssistantPendingQuestion.session_id == session_obj.id)
        ).all()
        for item in questions:
            self.session.delete(item)

        if legacy_session_id:
            legacy_messages = self.session.exec(
                select(DirectorAgentMessage).where(DirectorAgentMessage.session_id == legacy_session_id)
            ).all()
            for item in legacy_messages:
                self.session.delete(item)
            legacy_session = self.session.get(DirectorAgentSession, legacy_session_id)
            if legacy_session:
                self.session.delete(legacy_session)

        self.session.delete(session_obj)
        self.session.commit()

    def _get_session_metadata(self, session_obj: AssistantSession) -> Dict[str, Any]:
        return _json_loads(session_obj.metadata_json, {})

    def _write_session_metadata(
        self,
        session_obj: AssistantSession,
        metadata: Dict[str, Any],
        *,
        commit: bool = False,
    ) -> Dict[str, Any]:
        session_obj.metadata_json = _json_dumps(metadata)
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        if commit:
            self.session.commit()
            self.session.refresh(session_obj)
        return metadata

    def _get_runtime_state(self, session_obj: AssistantSession) -> Dict[str, Any]:
        metadata = self._get_session_metadata(session_obj)
        return dict(metadata.get("runtime_state") or {})

    def _update_runtime_state(
        self,
        session_obj: AssistantSession,
        *,
        draft_turn: Any = None,
        status_detail: Any = None,
        tool_activity: Any = None,
        project_changes: Any = None,
        skill_hint: Any = None,
        pending_question_wizard: Any = None,
        running_started_at: Any = None,
        execution_stage: Any = None,
        selected_panels: Any = None,
        resolved_model_choice: Any = None,
        selection_reason: Any = None,
        resume_hint: Any = None,
        creative_stage: Any = None,
        creative_stage_label: Any = None,
        active_agent: Any = None,
        active_agent_label: Any = None,
        next_stage_hint: Any = None,
        latest_artifacts: Any = None,
        runtime_feed: Any = None,
        reasoning_public_phase: Any = None,
        reasoning_public_phase_index: Any = None,
        reasoning_public_phase_started_ms: Any = None,
        public_reasoning_intent: Any = None,
        public_reasoning_phase: Any = None,
        public_reasoning_template_id: Any = None,
        public_reasoning_recent_template_ids: Any = None,
        commit: bool = False,
        clear_keys: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        metadata = self._get_session_metadata(session_obj)
        runtime_state = dict(metadata.get("runtime_state") or {})
        updates = {
            "draft_turn": draft_turn,
            "status_detail": status_detail,
            "tool_activity": tool_activity,
            "project_changes": project_changes,
            "skill_hint": skill_hint,
            "pending_question_wizard": pending_question_wizard,
            "running_started_at": running_started_at,
            "execution_stage": execution_stage,
            "selected_panels": selected_panels,
            "resolved_model_choice": resolved_model_choice,
            "selection_reason": selection_reason,
            "resume_hint": resume_hint,
            "creative_stage": creative_stage,
            "creative_stage_label": creative_stage_label,
            "active_agent": active_agent,
            "active_agent_label": active_agent_label,
            "next_stage_hint": next_stage_hint,
            "latest_artifacts": latest_artifacts,
            "runtime_feed": runtime_feed,
            "reasoning_public_phase": reasoning_public_phase,
            "reasoning_public_phase_index": reasoning_public_phase_index,
            "reasoning_public_phase_started_ms": reasoning_public_phase_started_ms,
            "public_reasoning_intent": public_reasoning_intent,
            "public_reasoning_phase": public_reasoning_phase,
            "public_reasoning_template_id": public_reasoning_template_id,
            "public_reasoning_recent_template_ids": public_reasoning_recent_template_ids,
        }
        for key, value in updates.items():
            if value is None:
                continue
            runtime_state[key] = value
        for key in clear_keys or []:
            runtime_state.pop(key, None)
        metadata["runtime_state"] = runtime_state
        self._write_session_metadata(session_obj, metadata, commit=commit)
        return runtime_state

    def _clear_runtime_state(self, session_obj: AssistantSession, *, commit: bool = False) -> Dict[str, Any]:
        return self._update_runtime_state(
            session_obj,
            commit=commit,
            clear_keys=[
                "draft_turn",
                "status_detail",
                "tool_activity",
                "pending_question_wizard",
                "skill_hint",
                "running_started_at",
                "execution_stage",
                "selected_panels",
                "resolved_model_choice",
                "selection_reason",
                "resume_hint",
                "creative_stage",
                "creative_stage_label",
                "active_agent",
                "active_agent_label",
                "next_stage_hint",
                "latest_artifacts",
                "runtime_feed",
                "reasoning_public_phase",
                "reasoning_public_phase_index",
                "reasoning_public_phase_started_ms",
                "public_reasoning_intent",
                "public_reasoning_phase",
                "public_reasoning_template_id",
            ],
        )

    def _get_runtime_feed(self, session_obj: AssistantSession) -> List[Dict[str, Any]]:
        runtime_state = self._get_runtime_state(session_obj)
        return [dict(item) for item in list(runtime_state.get("runtime_feed") or []) if isinstance(item, dict)]

    def _set_runtime_feed(self, session_obj: AssistantSession, feed: List[Dict[str, Any]], *, commit: bool = False) -> List[Dict[str, Any]]:
        normalized = [dict(item) for item in list(feed or []) if isinstance(item, dict)]
        self._update_runtime_state(session_obj, runtime_feed=normalized, commit=commit)
        return normalized

    def _upsert_runtime_feed_item(self, session_obj: AssistantSession, item: Dict[str, Any], *, publish: bool = True) -> Dict[str, Any]:
        item_id = str(item.get("id") or item.get("card_id") or uuid.uuid4().hex).strip()
        next_item = {"id": item_id, **dict(item or {})}
        feed = self._get_runtime_feed(session_obj)
        index = next((idx for idx, current in enumerate(feed) if str(current.get("id") or "") == item_id), -1)
        if index >= 0:
            feed[index] = {**feed[index], **next_item}
        else:
            feed.append(next_item)
        self._set_runtime_feed(session_obj, feed, commit=False)
        if publish:
            self.publish_event(session_obj.id, {"type": "runtime_feed_delta", "op": "upsert_item", "item": next_item})
        return next_item

    def _patch_runtime_feed_item(self, session_obj: AssistantSession, item_id: str, patch: Dict[str, Any], *, publish: bool = True) -> Optional[Dict[str, Any]]:
        feed = self._get_runtime_feed(session_obj)
        current = None
        for index, item in enumerate(feed):
            if str(item.get("id") or "") != str(item_id or ""):
                continue
            current = {**item, **dict(patch or {})}
            feed[index] = current
            break
        if current is None:
            return None
        self._set_runtime_feed(session_obj, feed, commit=False)
        if publish:
            self.publish_event(session_obj.id, {"type": "runtime_feed_delta", "op": "patch_item", "item_id": str(item_id), "patch": dict(patch or {})})
        return current

    def _append_runtime_feed_text(self, session_obj: AssistantSession, item_id: str, text: str, *, publish: bool = True) -> Optional[Dict[str, Any]]:
        feed = self._get_runtime_feed(session_obj)
        current = None
        for index, item in enumerate(feed):
            if str(item.get("id") or "") != str(item_id or ""):
                continue
            next_item = dict(item)
            next_item["markdown"] = "{0}{1}".format(str(item.get("markdown") or ""), str(text or ""))
            feed[index] = next_item
            current = next_item
            break
        if current is None:
            return None
        self._set_runtime_feed(session_obj, feed, commit=False)
        if publish and text:
            self.publish_event(session_obj.id, {"type": "runtime_feed_delta", "op": "append_text", "item_id": str(item_id), "text": str(text)})
        return current

    def _append_runtime_feed_rows(self, session_obj: AssistantSession, item_id: str, rows: List[List[Any]], *, publish: bool = True) -> Optional[Dict[str, Any]]:
        normalized_rows = [list(row) for row in list(rows or []) if isinstance(row, (list, tuple))]
        if not normalized_rows:
            return None
        feed = self._get_runtime_feed(session_obj)
        current = None
        for index, item in enumerate(feed):
            if str(item.get("id") or "") != str(item_id or ""):
                continue
            next_item = dict(item)
            current_rows = [list(row) for row in list(item.get("rows") or []) if isinstance(row, (list, tuple))]
            next_item["rows"] = current_rows + normalized_rows
            feed[index] = next_item
            current = next_item
            break
        if current is None:
            return None
        self._set_runtime_feed(session_obj, feed, commit=False)
        if publish:
            self.publish_event(session_obj.id, {"type": "runtime_feed_delta", "op": "append_rows", "item_id": str(item_id), "rows": normalized_rows})
        return current

    def _complete_runtime_feed_item(self, session_obj: AssistantSession, item_id: str, patch: Optional[Dict[str, Any]] = None, *, publish: bool = True) -> Optional[Dict[str, Any]]:
        next_patch = {"status": "completed", **dict(patch or {})}
        current = self._patch_runtime_feed_item(session_obj, item_id, next_patch, publish=False)
        if current is not None and publish:
            self.publish_event(session_obj.id, {"type": "runtime_feed_delta", "op": "complete_item", "item_id": str(item_id), "patch": next_patch})
        return current

    def _remove_runtime_feed_item(self, session_obj: AssistantSession, item_id: str, *, publish: bool = True) -> None:
        feed = [item for item in self._get_runtime_feed(session_obj) if str(item.get("id") or "") != str(item_id or "")]
        self._set_runtime_feed(session_obj, feed, commit=False)
        if publish:
            self.publish_event(session_obj.id, {"type": "runtime_feed_delta", "op": "remove_item", "item_id": str(item_id)})

    def _publish_status(self, session_obj: AssistantSession) -> None:
        runtime_state = self._get_runtime_state(session_obj)
        self.publish_event(
            session_obj.id,
            {
                "type": "status",
                "status": session_obj.status,
                "detail": runtime_state.get("status_detail") or "",
                "running_started_at": runtime_state.get("running_started_at"),
            },
        )

    def _publish_runtime_delta(self, session_obj: AssistantSession) -> None:
        runtime_state = self._get_runtime_state(session_obj)
        self.publish_event(
            session_obj.id,
            {
                "type": "delta",
                "draft_turn": runtime_state.get("draft_turn"),
                "status_detail": runtime_state.get("status_detail") or "",
                "tool_activity": runtime_state.get("tool_activity") or [],
                "project_changes": runtime_state.get("project_changes") or [],
                "pending_question_wizard": runtime_state.get("pending_question_wizard"),
                "running_started_at": runtime_state.get("running_started_at"),
                "execution_stage": runtime_state.get("execution_stage") or "",
                "selected_panels": runtime_state.get("selected_panels") or [],
                "resolved_model_choice": runtime_state.get("resolved_model_choice"),
                "selection_reason": runtime_state.get("selection_reason") or "",
                "resume_hint": runtime_state.get("resume_hint") or "",
            },
        )

    def _sanitize_attachments(self, attachments: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for item in attachments or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            normalized.append(
                {
                    "id": str(item.get("id") or uuid.uuid4().hex),
                    "type": str(item.get("type") or "image"),
                    "url": url,
                    "thumbnail_url": str(item.get("thumbnail_url") or "").strip() or None,
                    "name": str(item.get("name") or "").strip() or None,
                    "mime_type": str(item.get("mime_type") or "").strip() or None,
                    "size_bytes": item.get("size_bytes"),
                    "metadata": item.get("metadata") or {},
                }
            )
        return normalized

    def _extract_skill_hint(self, content: str) -> Optional[Dict[str, Any]]:
        text = " ".join(str(content or "").strip().split())
        token = text.split(" ", 1)[0].strip()
        if not token:
            return None
        skill = SKILL_ALIAS_MAP.get(token)
        if skill:
            return _skill_hint_from_definition(skill, match_source="slash", matched_text=token)

        lowered = text.lower()
        if not lowered or _looks_like_capability_question(lowered) or SKILL_INTENT_NEGATION_PATTERN.search(lowered):
            return None

        for skill_id, patterns in NATURAL_LANGUAGE_SKILL_PATTERNS.items():
            if any(pattern.search(text) for pattern in patterns):
                return _skill_hint_from_definition(
                    SKILL_ID_MAP.get(skill_id),
                    match_source="natural_language_pattern",
                    matched_text=text,
                )

        matches: List[str] = []
        for skill_id, keywords in NATURAL_LANGUAGE_SKILL_KEYWORDS.items():
            if any(keyword.lower() in lowered for keyword in keywords):
                matches.append(skill_id)
        if len(matches) != 1:
            return None
        return _skill_hint_from_definition(
            SKILL_ID_MAP.get(matches[0]),
            match_source="natural_language",
            matched_text=text,
        )

    def _build_tool_activity(self, skill_hint: Optional[Dict[str, Any]], session_obj: AssistantSession) -> List[Dict[str, Any]]:
        if skill_hint:
            label = skill_hint.get("label") or "执行任务"
            return [
                {"id": "{0}-ctx".format(skill_hint.get("id") or "skill"), "label": "读取项目上下文", "status": "completed"},
                {"id": "{0}-plan".format(skill_hint.get("id") or "skill"), "label": "规划 {0}".format(label), "status": "running"},
                {"id": "{0}-result".format(skill_hint.get("id") or "skill"), "label": "整理结果并回写工作区", "status": "pending"},
            ]
        target_label = "站外协作" if _normalize_target(None, session_obj) == "external" else "导演工具链"
        return [
            {"id": "context", "label": "读取项目上下文", "status": "completed"},
            {"id": "planner", "label": "分析需求并选择{0}".format(target_label), "status": "running"},
            {"id": "summary", "label": "整理结果与刷新提示", "status": "pending"},
        ]

    def _build_draft_turn(
        self,
        *,
        content: str,
        skill_hint: Optional[Dict[str, Any]],
        tool_activity: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        label = skill_hint.get("label") if skill_hint else "导演任务"
        return self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "task_progress",
                    "title": label or "导演任务",
                    "description": "正在结合当前项目上下文规划执行路径。",
                    "task_type": skill_hint.get("id") if skill_hint else None,
                    "status": "running",
                },
                {
                    "id": uuid.uuid4().hex,
                    "type": "reasoning_summary",
                    "summary": "已接收你的请求，正在分析上下文、挑选工具并整理执行步骤。",
                },
            ],
            metadata={
                "draft": True,
                "source_user_message": content,
                "tool_activity": tool_activity,
                "skill_hint": skill_hint or {},
            },
        )

    def _build_user_blocks(self, content_text: str, attachments: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        blocks = [
            {
                "id": uuid.uuid4().hex,
                "type": "text",
                "text": content_text,
            }
        ]
        for attachment in self._sanitize_attachments(attachments):
            blocks.append(
                {
                    "id": attachment["id"],
                    "type": attachment.get("type") or "image",
                    "url": attachment.get("url"),
                    "thumbnail_url": attachment.get("thumbnail_url"),
                    "alt": attachment.get("name") or "attachment",
                    "metadata": attachment.get("metadata") or {},
                }
            )
        return blocks

    def _extract_project_changes_from_turn(self, turn: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        changes: List[Dict[str, Any]] = []
        for block in (turn or {}).get("blocks") or []:
            result = block.get("result") if isinstance(block, dict) else {}
            if not isinstance(result, dict):
                result = {}
            refresh_hints = result.get("refresh_hints") or block.get("refresh_hints") or {}
            if not any(refresh_hints.values()):
                continue
            changes.append(
                {
                    "block_id": block.get("id"),
                    "tool_name": block.get("tool_name") or block.get("task_type"),
                    "summary": result.get("summary") or block.get("summary") or block.get("title") or "",
                    "refresh_hints": refresh_hints,
                }
            )
        return changes

    def _update_reasoning_progress(
        self,
        session_obj: AssistantSession,
        *,
        content: str,
        skill_hint: Optional[Dict[str, Any]],
        reasoning_text: str,
    ) -> None:
        length = len(str(reasoning_text or ""))
        if length < 60:
            detail = "正在分析项目上下文"
            active_index = 1
        elif length < 180:
            detail = "正在拆解需求并匹配导演工具"
            active_index = 1
        else:
            detail = "正在整理执行方案与结果摘要"
            active_index = 2
        tool_activity = self._build_tool_activity(skill_hint, session_obj)
        for index, item in enumerate(tool_activity):
            if index < active_index:
                item["status"] = "completed"
            elif index == active_index:
                item["status"] = "running"
            else:
                item["status"] = "pending"
        draft_turn = self._build_draft_turn(content=content, skill_hint=skill_hint, tool_activity=tool_activity)
        self._update_runtime_state(
            session_obj,
            draft_turn=draft_turn,
            status_detail=detail,
            tool_activity=tool_activity,
        )
        self.publish_event(
            session_obj.id,
            {
                "type": "delta",
                "draft_turn": draft_turn,
                "status_detail": detail,
                "tool_activity": tool_activity,
                "running_started_at": self._get_runtime_state(session_obj).get("running_started_at"),
            },
        )

    # ==================== snapshot / serialization ====================

    def serialize_session_meta(self, session_obj: AssistantSession) -> Dict[str, Any]:
        runtime_state = self._get_runtime_state(session_obj)
        workflow_fields = AgentWorkflowService(self.session).build_snapshot_fields(
            script_id=session_obj.script_id,
            episode_id=session_obj.episode_id,
        )
        return {
            "id": encode_id(session_obj.id),
            "script_id": encode_id(session_obj.script_id),
            "episode_id": encode_id(session_obj.episode_id) if session_obj.episode_id else None,
            "channel": session_obj.channel,
            "profile": session_obj.profile,
            "status": session_obj.status,
            "status_detail": runtime_state.get("status_detail") or "",
            "running_started_at": runtime_state.get("running_started_at"),
            "title": session_obj.title or self.DEFAULT_SESSION_TITLE,
            "linked_external_session_id": encode_id(session_obj.linked_external_session_id)
            if session_obj.linked_external_session_id
            else None,
            "metadata": self._sanitize_metadata(_json_loads(session_obj.metadata_json, {})),
            "created_at": _iso(session_obj.created_at),
            "updated_at": _iso(session_obj.updated_at),
            **workflow_fields,
        }

    def get_snapshot(self, *, session_obj: AssistantSession) -> Dict[str, Any]:
        statement = (
            select(AssistantTranscriptEvent)
            .where(AssistantTranscriptEvent.session_id == session_obj.id)
            .order_by(AssistantTranscriptEvent.sequence_no.asc(), AssistantTranscriptEvent.id.asc())
        )
        events = self.session.exec(statement).all()
        turns = []
        for event in events:
            if event.event_type != "turn":
                continue
            payload = _json_loads(event.payload_json, {})
            if payload:
                turns.append(payload)

        pending_questions = self.session.exec(
            select(AssistantPendingQuestion)
            .where(
                AssistantPendingQuestion.session_id == session_obj.id,
                AssistantPendingQuestion.status == "pending",
            )
            .order_by(AssistantPendingQuestion.created_at.asc(), AssistantPendingQuestion.id.asc())
        ).all()
        runtime_state = self._get_runtime_state(session_obj)
        pending_question_list = [self._serialize_pending_question(item) for item in pending_questions]
        pending_question_wizard = None
        for item in pending_question_list:
            if item.get("question_type") == "wizard":
                pending_question_wizard = item
                break

        return {
            "session": self.serialize_session_meta(session_obj),
            "context": self._build_runtime_context(session_obj),
            "turns": turns,
            "draft_turn": runtime_state.get("draft_turn"),
            "status_detail": runtime_state.get("status_detail") or "",
            "tool_activity": runtime_state.get("tool_activity") or [],
            "project_changes": runtime_state.get("project_changes") or [],
            "pending_questions": pending_question_list,
            "pending_question_wizard": pending_question_wizard,
            "running_started_at": runtime_state.get("running_started_at"),
            "execution_stage": runtime_state.get("execution_stage") or "",
            "selected_panels": runtime_state.get("selected_panels") or [],
            "resolved_model_choice": runtime_state.get("resolved_model_choice"),
            "selection_reason": runtime_state.get("selection_reason") or "",
            "resume_hint": runtime_state.get("resume_hint") or "",
            "bridge_state": self.get_bridge_state(session_obj=session_obj),
            "workflow": self._build_workflow_snapshot(session_obj),
            "runtime_feed": self._get_runtime_feed(session_obj),
            "last_event_id": assistant_runtime_event_manager.get_last_event_id(encode_id(session_obj.id)),
        }

    def get_snapshot_by_id(self, session_id: int) -> Dict[str, Any]:
        session_obj = self.session.get(AssistantSession, session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="会话不存在")
        return self.get_snapshot(session_obj=session_obj)

    # ==================== message lifecycle ====================

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
            raise HTTPException(status_code=400, detail="消息不能为空")
        execution_text = content_text or _build_attachment_only_message(normalized_attachments)
        if session_obj.status == "running":
            raise HTTPException(status_code=409, detail="当前会话仍在处理中，请稍后再试或先中断")

        now = _utc_now()
        if not session_obj.title or session_obj.title == self.DEFAULT_SESSION_TITLE:
            session_obj.title = _derive_title_from_payload(
                execution_text,
                normalized_attachments,
                self.DEFAULT_SESSION_TITLE,
            )
        session_obj.status = "running"
        session_obj.updated_at = now
        self.session.add(session_obj)

        user_blocks: List[Dict[str, Any]] = []
        if content_text:
            user_blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": content_text,
                }
            )
        for attachment in normalized_attachments:
            user_blocks.append(
                {
                    "id": attachment.get("id") or uuid.uuid4().hex,
                    "type": "image",
                    "url": attachment.get("url"),
                    "thumbnail_url": attachment.get("thumbnail_url") or attachment.get("url"),
                    "alt": attachment.get("name") or "attachment",
                    "name": attachment.get("name"),
                    "mime_type": attachment.get("mime_type"),
                    "size_bytes": attachment.get("size_bytes"),
                    "metadata": attachment.get("metadata") or {},
                }
            )

        execution_context = dict(context or {})
        if normalized_attachments:
            execution_context["attachments"] = normalized_attachments

        user_turn = self._build_turn(
            role="user",
            blocks=user_blocks,
        )
        self._insert_turn_event(session_obj=session_obj, turn=user_turn)
        self.session.commit()
        self.session.refresh(session_obj)

        self.publish_event(session_obj.id, {"type": "patch", "turn": user_turn})
        self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
        self.publish_snapshot(session_obj.id)

        if async_mode:
            worker = threading.Thread(
                target=self.run_background_worker,
                kwargs={
                    "assistant_session_id": session_obj.id,
                    "user_id": user.id,
                    "content": execution_text,
                    "context": execution_context,
                    "target": target,
                },
                daemon=True,
            )
            worker.start()
            return {"snapshot": self.get_snapshot(session_obj=session_obj), "queued": True}

        result = self._execute_message(
            assistant_session_id=session_obj.id,
            user_id=user.id,
            content=execution_text,
            context=execution_context,
            target=target,
        )
        return {
            "snapshot": self.get_snapshot_by_id(session_obj.id),
            "queued": False,
            **result,
        }

    @classmethod
    def run_background_worker(
        cls,
        *,
        assistant_session_id: int,
        user_id: int,
        content: str,
        context: Dict[str, Any],
        target: Optional[str],
    ) -> None:
        with session_scope() as db_session:
            service = cls(db_session)
            service._execute_message(
                assistant_session_id=assistant_session_id,
                user_id=user_id,
                content=content,
                context=context,
                target=target,
            )

    def _execute_message(
        self,
        *,
        assistant_session_id: int,
        user_id: int,
        content: str,
        context: Dict[str, Any],
        target: Optional[str],
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
                )
            else:
                result = self._execute_internal_director_message(
                    session_obj=session_obj,
                    user=user,
                    content=content,
                    context=context or {},
                )

            self.session.refresh(session_obj)
            if session_obj.status == "interrupted":
                self.publish_snapshot(session_obj.id)
                return {"interrupted": True}

            session_obj.status = "completed"
            session_obj.updated_at = _utc_now()
            self.session.add(session_obj)
            self.session.commit()
            self.session.refresh(session_obj)

            bridge_event = result.get("bridge_event")
            question_event = result.get("question_event")
            if bridge_event:
                self.publish_event(session_obj.id, bridge_event)
            if question_event:
                self.publish_event(session_obj.id, question_event)
            self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
            self.publish_snapshot(session_obj.id)
            return result
        except HTTPException as exc:
            self._append_error_turn(session_obj=session_obj, error_text=self._http_exception_message(exc))
            session_obj.status = "error"
            session_obj.updated_at = _utc_now()
            self.session.add(session_obj)
            self.session.commit()
            self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
            self.publish_snapshot(session_obj.id)
            raise
        except Exception as exc:
            self._append_error_turn(session_obj=session_obj, error_text=str(exc))
            session_obj.status = "error"
            session_obj.updated_at = _utc_now()
            self.session.add(session_obj)
            self.session.commit()
            self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
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
        answers_payload = dict(answers or {})
        normalized_modifications = dict(modifications or {})
        if not normalized_modifications and answers_payload:
            normalized_modifications = answers_payload

        question.status = "answered"
        question.answer_json = _json_dumps(
            {
                "action": action_value,
                "answer": answer,
                "modifications": normalized_modifications,
                "answers": answers_payload,
            }
        )
        question.updated_at = _utc_now()
        question.answered_at = _utc_now()
        self.session.add(question)

        session_obj.status = "running" if action_value != "reject" else "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
        self.publish_snapshot(session_obj.id)

        should_queue = (
            async_mode
            and action_value != "reject"
            and metadata.get("source") in {"director_legacy", "bridge_import"}
        )
        if should_queue:
            worker = threading.Thread(
                target=self.run_answer_question_worker,
                kwargs={
                    "assistant_session_id": session_obj.id,
                    "user_id": user.id,
                    "question_id": question.id,
                    "action": action_value,
                    "modifications": normalized_modifications,
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
            modifications=normalized_modifications,
        )

        if metadata.get("source") == "director_legacy":
            result = self._answer_director_question(
                session_obj=session_obj,
                user=user,
                legacy_message_id=metadata.get("legacy_message_id"),
                action=action_value,
                modifications=modifications or {},
            )
            self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
            self.publish_snapshot(session_obj.id)
            return result

        if metadata.get("source") == "bridge_import":
            result = self._answer_bridge_import_question(
                session_obj=session_obj,
                user=user,
                action=action_value,
                question_payload=payload,
            )
            self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
            self.publish_snapshot(session_obj.id)
            return result

        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "已记录你的回答。当前问题已关闭。",
                }
            ],
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
        self.publish_snapshot(session_obj.id)
        return {"snapshot": self.get_snapshot(session_obj=session_obj)}

    @classmethod
    def run_answer_question_worker(
        cls,
        *,
        assistant_session_id: int,
        user_id: int,
        question_id: int,
        action: str,
        modifications: Dict[str, Any],
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
                    answer=None,
                    modifications=modifications or {},
                )
            except HTTPException as exc:
                if session_obj:
                    service._append_error_turn(session_obj=session_obj, error_text=service._http_exception_message(exc))
                    session_obj.status = "error"
                    session_obj.updated_at = _utc_now()
                    db_session.add(session_obj)
                    db_session.commit()
                    service.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
                    service.publish_snapshot(session_obj.id)
            except Exception as exc:
                if session_obj:
                    service._append_error_turn(session_obj=session_obj, error_text=str(exc))
                    session_obj.status = "error"
                    session_obj.updated_at = _utc_now()
                    db_session.add(session_obj)
                    db_session.commit()
                    service.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
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
            self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
            self.publish_snapshot(session_obj.id)
            return result

        if metadata.get("source") == "bridge_import":
            result = self._answer_bridge_import_question(
                session_obj=session_obj,
                user=user,
                action=action,
                question_payload=payload,
            )
            self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
            self.publish_snapshot(session_obj.id)
            return result

        assistant_turn = self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "已记录你的回答。当前问题已关闭。",
                }
            ],
        )
        self._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
        self.publish_snapshot(session_obj.id)
        return {"snapshot": self.get_snapshot(session_obj=session_obj)}

    def interrupt_session(self, *, session_obj: AssistantSession) -> Dict[str, Any]:
        session_obj.status = "interrupted"
        session_obj.updated_at = _utc_now()
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
        self.publish_event(session_obj.id, {"type": "status", "status": session_obj.status})
        self.publish_snapshot(session_obj.id)
        return {"snapshot": self.get_snapshot(session_obj=session_obj)}

    # ==================== bridge ====================

    def link_bridge(
        self,
        *,
        session_obj: AssistantSession,
        user: User,
        external_session_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        external_session = None
        if external_session_id:
            external_session = self._require_external_session(
                user=user,
                script_id=session_obj.script_id,
                external_session_id=external_session_id,
            )
        else:
            external_session = self._find_default_external_session(
                script_id=session_obj.script_id,
                user_id=user.id,
                episode_id=session_obj.episode_id,
            )
        if not external_session:
            raise HTTPException(status_code=404, detail="当前项目暂未找到可绑定的站外 Agent 会话")

        session_obj.linked_external_session_id = external_session.id
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()

        bridge_state = self.get_bridge_state(session_obj=session_obj)
        self.publish_event(session_obj.id, {"type": "bridge_update", "bridge_state": bridge_state})
        self.publish_snapshot(session_obj.id)
        return bridge_state

    def request_bridge_import(
        self,
        *,
        session_obj: AssistantSession,
        user: User,
        import_type: str,
        mode: Optional[str] = None,
        episode_id: Optional[int] = None,
        name: Optional[str] = None,
        external_session_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        if session_obj.status == "running":
            raise HTTPException(status_code=409, detail="当前会话仍在处理中，请先等待当前运行结束")

        if external_session_id:
            external_session = self._require_external_session(
                user=user,
                script_id=session_obj.script_id,
                external_session_id=external_session_id,
            )
            session_obj.linked_external_session_id = external_session.id
        else:
            external_session = self._resolve_external_bridge(session_obj=session_obj, user=user)
        normalized_import_type = self._normalize_bridge_import_type(import_type)
        question = self._create_bridge_import_question(
            session_obj=session_obj,
            external_session=external_session,
            import_type=normalized_import_type,
            mode=mode,
            episode_id=episode_id,
            name=name,
        )
        turn = self._build_bridge_import_turn(question=question, import_type=normalized_import_type)

        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self._insert_turn_event(session_obj=session_obj, turn=turn)
        self.session.commit()

        self.publish_event(session_obj.id, {"type": "patch", "turn": turn})
        self.publish_snapshot(session_obj.id)
        return {"snapshot": self.get_snapshot(session_obj=session_obj)}

    def unlink_bridge(self, *, session_obj: AssistantSession) -> Dict[str, Any]:
        session_obj.linked_external_session_id = None
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        bridge_state = self.get_bridge_state(session_obj=session_obj)
        self.publish_event(session_obj.id, {"type": "bridge_update", "bridge_state": bridge_state})
        self.publish_snapshot(session_obj.id)
        return bridge_state

    def get_bridge_state(self, *, session_obj: AssistantSession) -> Dict[str, Any]:
        if not session_obj.linked_external_session_id:
            return {
                "linked": False,
                "external_session_id": None,
                "provider": None,
                "status": "unlinked",
                "workspace_summary": {"file_count": 0, "files": []},
                "last_reply_text": "",
                "updated_at": None,
            }

        external_session = self.session.get(ExternalAgentSession, session_obj.linked_external_session_id)
        if not external_session:
            return {
                "linked": False,
                "external_session_id": None,
                "provider": None,
                "status": "missing",
                "workspace_summary": {"file_count": 0, "files": []},
                "last_reply_text": "",
                "updated_at": None,
            }

        snapshot = _json_loads(external_session.workspace_snapshot_json, {})
        files = list(snapshot.get("files") or [])
        preview_files = []
        for item in files[:5]:
            record_count = item.get("record_count")
            if record_count is None:
                records = item.get("records") or []
                record_count = len(records) if isinstance(records, list) else 0
            preview_files.append(
                {
                    "file_id": str(item.get("file_id") or item.get("id") or ""),
                    "name": str(item.get("name") or ""),
                    "docu_type": str(item.get("docu_type") or item.get("type") or ""),
                    "record_count": int(record_count or 0),
                }
            )

        return {
            "linked": True,
            "external_session_id": encode_id(external_session.id),
            "provider": external_session.provider,
            "base_name": external_session.base_name or "",
            "provider_episode_id": external_session.provider_episode_id or "",
            "session_id": external_session.session_id or "",
            "status": external_session.status,
            "is_active": external_session.is_active,
            "workspace_summary": {
                "file_count": len(files),
                "files": preview_files,
            },
            "last_reply_text": external_session.last_reply_text or "",
            "updated_at": _iso(external_session.updated_at),
        }

    # ==================== execution handlers ====================

    def _execute_internal_director_message(
        self,
        *,
        session_obj: AssistantSession,
        user: User,
        content: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        director_service = DirectorAgentService(self.session)
        legacy_session_id = self._ensure_legacy_director_session(session_obj=session_obj, user=user)
        merged_context = self._build_runtime_context(session_obj)
        if context:
            merged_context.update(context)
        legacy_message = director_service.process_message(
            session_id=legacy_session_id,
            user_message=content,
            additional_context=merged_context or None,
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
        question_block = self._find_block_by_type(assistant_turn, "question")
        if question_block:
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
        }

    def _execute_external_message(
        self,
        *,
        session_obj: AssistantSession,
        user: User,
        content: str,
    ) -> Dict[str, Any]:
        external_session = self._resolve_external_bridge(session_obj=session_obj, user=user)
        result = append_chat_message(
            self.session,
            user=user,
            session_obj=external_session,
            message=content,
        )
        reply = result["provider_result"].get("reply") or {}
        actions = result["provider_result"].get("actions") or []
        workspace = result["provider_result"].get("workspace") or {}

        blocks = []
        reply_text = str(reply.get("text") or "").strip()
        if reply_text:
            blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": reply_text,
                }
            )

        blocks.append(
            {
                "id": uuid.uuid4().hex,
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
                "tool_name": "delegate_to_external_agent",
                "summary": "站外 Agent 已返回 {0} 条动作建议。".format(len(actions)),
                "result": {
                    "actions": actions,
                    "workspace": workspace,
                    "refresh_hints": {},
                },
            }
        )

        assistant_turn = self._build_turn(role="assistant", blocks=blocks)
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
        }

    def _answer_director_question(
        self,
        *,
        session_obj: AssistantSession,
        user: User,
        legacy_message_id: Optional[int],
        action: str,
        modifications: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not legacy_message_id:
            raise HTTPException(status_code=400, detail="当前确认请求缺少底层消息映射")

        legacy_message = self.session.get(DirectorAgentMessage, int(legacy_message_id))
        if not legacy_message:
            raise HTTPException(status_code=404, detail="底层确认消息不存在")

        director_service = DirectorAgentService(self.session)
        result_message = director_service.confirm_action(
            message=legacy_message,
            action=action,
            modifications=modifications or None,
            user=user,
        )

        if action == "reject":
            turn = self._build_turn(
                role="assistant",
                blocks=[
                    {
                        "id": uuid.uuid4().hex,
                        "type": "interrupt_notice",
                        "text": "已取消本次执行，不会继续写入当前项目。",
                    }
                ],
            )
        else:
            turn = self._build_director_turn(
                session_obj=session_obj,
                legacy_message=result_message,
            )

        self._insert_turn_event(session_obj=session_obj, turn=turn)
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()

        self.publish_event(session_obj.id, {"type": "patch", "turn": turn})
        return {"snapshot": self.get_snapshot(session_obj=session_obj)}

    def _answer_bridge_import_question(
        self,
        *,
        session_obj: AssistantSession,
        user: User,
        action: str,
        question_payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        metadata = question_payload.get("metadata") or {}
        import_type = self._normalize_bridge_import_type(metadata.get("import_type"))

        if action == "reject":
            turn = self._build_turn(
                role="assistant",
                blocks=[
                    {
                        "id": uuid.uuid4().hex,
                        "type": "interrupt_notice",
                        "text": "已取消本次站外导入写入，当前项目不会发生变更。",
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

        team = self.session.get(Team, session_obj.team_id)
        if not team:
            raise HTTPException(status_code=404, detail="当前会话所属团队不存在")

        external_session = self._resolve_external_bridge(session_obj=session_obj, user=user)
        tool_name = "import_external_{0}".format(import_type)
        refresh_hints: Dict[str, Any] = {}
        result_payload: Dict[str, Any]
        summary: str

        if import_type == "script":
            mode = str(metadata.get("mode") or "current_script_source").strip() or "current_script_source"
            import_result = import_script_content(
                self.session,
                team=team,
                external_session=external_session,
                mode=mode,
                name=metadata.get("name"),
            )
            result_payload = {
                "mode": mode,
                "script_id": encode_id(import_result["script_id"]) if import_result.get("script_id") else None,
                "episode_id": encode_id(import_result["episode_id"]) if import_result.get("episode_id") else None,
            }
            if mode == "create_new_script":
                summary = "已将站外剧本导入为新剧本。"
            else:
                summary = "已将站外剧本写入当前项目原文。"
                refresh_hints = {"script_source": True}
        elif import_type == "characters":
            import_result = import_character_assets(
                self.session,
                team=team,
                external_session=external_session,
            )
            result_payload = {
                "created_count": import_result["created_count"],
                "resource_ids": [encode_id(resource_id) for resource_id in import_result["resource_ids"]],
            }
            summary = "已导入 {0} 个角色资产。".format(import_result["created_count"])
            refresh_hints = {"resources": True}
        else:
            target_episode_id = metadata.get("episode_id") or external_session.episode_id or session_obj.episode_id
            if not target_episode_id:
                raise HTTPException(status_code=400, detail="请先绑定目标分集后再导入分镜")
            episode = self.session.get(Episode, int(target_episode_id))
            if not episode or episode.script_id != session_obj.script_id:
                raise HTTPException(status_code=400, detail="目标分集不属于当前项目")
            import_result = import_panels_to_episode(
                self.session,
                external_session=external_session,
                episode_id=int(target_episode_id),
            )
            result_payload = {
                "created_count": import_result["created_count"],
                "panel_ids": [encode_id(panel_id) for panel_id in import_result["panel_ids"]],
                "episode_id": encode_id(int(target_episode_id)),
            }
            summary = "已导入 {0} 个分镜到目标剧集。".format(import_result["created_count"])
            refresh_hints = {"panels": True}

        blocks: List[Dict[str, Any]] = [
            {
                "id": uuid.uuid4().hex,
                "type": "tool_result",
                "tool_name": tool_name,
                "summary": summary,
                "result": {
                    **result_payload,
                    "refresh_hints": refresh_hints,
                },
            }
        ]
        if refresh_hints:
            blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "reasoning_summary",
                    "summary": "已完成站外产物导入，可按需刷新当前工作区数据。",
                    "refresh_hints": refresh_hints,
                }
            )

        turn = self._build_turn(role="assistant", blocks=blocks)
        self._insert_turn_event(session_obj=session_obj, turn=turn)
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()

        self.publish_event(session_obj.id, {"type": "patch", "turn": turn})
        return {"snapshot": self.get_snapshot(session_obj=session_obj)}

    # ==================== turn / question builders ====================

    def _normalize_bridge_import_type(self, import_type: Optional[str]) -> str:
        text = str(import_type or "").strip().lower()
        if text not in {"script", "characters", "panels"}:
            raise HTTPException(status_code=400, detail="import_type 仅支持 script / characters / panels")
        return text

    def _create_bridge_import_question(
        self,
        *,
        session_obj: AssistantSession,
        external_session: ExternalAgentSession,
        import_type: str,
        mode: Optional[str],
        episode_id: Optional[int],
        name: Optional[str],
    ) -> AssistantPendingQuestion:
        workspace_summary = self.get_bridge_state(session_obj=session_obj).get("workspace_summary") or {}
        normalized_mode = str(mode or "current_script_source").strip() or "current_script_source"
        target_episode_id = int(episode_id) if episode_id else None
        title_map = {
            "script": "确认导入站外剧本",
            "characters": "确认导入站外角色",
            "panels": "确认导入站外分镜",
        }
        prompt_map = {
            "script": "站外 Agent 已经准备好剧本内容，确认后将写入当前项目或创建新剧本。",
            "characters": "站外 Agent 已经准备好角色产物，确认后将导入当前项目共享资源。",
            "panels": "站外 Agent 已经准备好分镜产物，确认后将写入目标剧集。",
        }
        preview: Dict[str, Any] = {
            "workspace_file_count": int(workspace_summary.get("file_count") or 0),
            "workspace_files": workspace_summary.get("files") or [],
            "external_session_id": encode_id(external_session.id),
        }
        if import_type == "script":
            preview["mode"] = normalized_mode
            if name:
                preview["name"] = name
        if import_type == "panels":
            preview["episode_id"] = encode_id(target_episode_id) if target_episode_id else None

        question = AssistantPendingQuestion(
            session_id=session_obj.id,
            question_type="confirm_write",
            status="pending",
            title=title_map[import_type],
            prompt_text=prompt_map[import_type],
            payload_json=_json_dumps(
                {
                    "import_type": import_type,
                    "options": [
                        {"action": "confirm", "label": "确认导入"},
                        {"action": "reject", "label": "取消"},
                    ],
                    "preview": preview,
                    "metadata": {
                        "source": "bridge_import",
                        "import_type": import_type,
                        "mode": normalized_mode,
                        "episode_id": target_episode_id,
                        "name": name,
                    },
                }
            ),
            answer_json=_json_dumps({}),
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        self.session.add(question)
        self.session.flush()
        return question

    def _build_bridge_import_turn(
        self,
        *,
        question: AssistantPendingQuestion,
        import_type: str,
    ) -> Dict[str, Any]:
        question_payload = self._serialize_pending_question(question)
        title_map = {
            "script": "导入站外剧本",
            "characters": "导入站外角色",
            "panels": "导入站外分镜",
        }
        return self._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "tool_use",
                    "tool_name": "import_external_{0}".format(import_type),
                    "title": title_map[import_type],
                    "status": "pending",
                    "description": question.prompt_text or "",
                },
                {
                    "id": uuid.uuid4().hex,
                    "type": "question",
                    "question_id": question.question_key,
                    "question_type": question.question_type,
                    "title": question.title or "",
                    "prompt": question.prompt_text or "",
                    "options": question_payload.get("options") or [],
                },
            ],
            metadata={
                "source": "bridge_import",
                "import_type": import_type,
            },
        )

    def _build_director_turn(
        self,
        *,
        session_obj: AssistantSession,
        legacy_message: DirectorAgentMessage,
    ) -> Dict[str, Any]:
        payload = _json_loads(legacy_message.payload_json, {})
        execution_result = _json_loads(legacy_message.execution_result_json, {})
        blocks = []

        if legacy_message.content:
            blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": legacy_message.content,
                }
            )

        if legacy_message.message_type in {"plan", "confirm"}:
            blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "task_progress",
                    "title": payload.get("title") or "待确认操作",
                    "description": payload.get("description") or legacy_message.content or "",
                    "task_type": legacy_message.task_type,
                    "estimated_items": payload.get("estimated_items"),
                    "estimated_cost": payload.get("estimated_cost"),
                    "preview": payload.get("preview") or {},
                }
            )
        elif legacy_message.message_type == "result":
            blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "tool_result",
                    "tool_name": legacy_message.task_type or payload.get("task_type") or "director_action",
                    "summary": execution_result.get("summary") or payload.get("summary") or legacy_message.content or "已完成",
                    "result": execution_result or payload or {},
                }
            )
            refresh_hints = execution_result.get("refresh_hints") or {}
            if refresh_hints:
                blocks.append(
                    {
                        "id": uuid.uuid4().hex,
                        "type": "reasoning_summary",
                        "summary": "已更新项目数据，可按需刷新分镜、资源或剧集上下文。",
                        "refresh_hints": refresh_hints,
                    }
                )
        elif payload.get("suggestions"):
            blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "reasoning_summary",
                    "summary": "已根据当前项目上下文给出下一步建议。",
                    "suggestions": payload.get("suggestions") or [],
                }
            )

        if legacy_message.requires_confirmation and legacy_message.confirmation_status == "pending":
            question = self._get_or_create_pending_question_for_legacy_message(
                session_obj=session_obj,
                legacy_message=legacy_message,
                payload=payload,
            )
            blocks.append(
                {
                    "id": uuid.uuid4().hex,
                    "type": "question",
                    "question_id": question.question_key,
                    "question_type": question.question_type,
                    "title": question.title or "需要确认",
                    "prompt": question.prompt_text or legacy_message.content or "",
                    "options": self._serialize_pending_question(question).get("options") or [],
                }
            )

        return self._build_turn(
            role="assistant",
            blocks=blocks,
            metadata={
                "source": "director_legacy",
                "legacy_message_id": legacy_message.id,
                "legacy_message_type": legacy_message.message_type,
            },
        )

    def _get_or_create_pending_question_for_legacy_message(
        self,
        *,
        session_obj: AssistantSession,
        legacy_message: DirectorAgentMessage,
        payload: Dict[str, Any],
    ) -> AssistantPendingQuestion:
        questions = self.session.exec(
            select(AssistantPendingQuestion).where(
                AssistantPendingQuestion.session_id == session_obj.id,
                AssistantPendingQuestion.status == "pending",
            )
        ).all()
        for item in questions:
            question_payload = _json_loads(item.payload_json, {})
            metadata = question_payload.get("metadata") or {}
            if metadata.get("legacy_message_id") == legacy_message.id:
                return item

        options = payload.get("actions") or [
            {"action": "confirm", "label": "确认执行"},
            {"action": "reject", "label": "取消本次操作"},
        ]
        normalized_options = []
        for item in options:
            if isinstance(item, dict):
                normalized_options.append(
                    {
                        "action": item.get("action") or item.get("action_type") or "confirm",
                        "label": item.get("label") or item.get("action_type") or "确认",
                    }
                )

        question = AssistantPendingQuestion(
            session_id=session_obj.id,
            question_type="confirm_write",
            status="pending",
            title=payload.get("title") or "需要确认写入",
            prompt_text=legacy_message.content or payload.get("description") or "",
            payload_json=_json_dumps(
                {
                    "options": normalized_options,
                    "preview": payload.get("preview") or {},
                    "task_type": legacy_message.task_type,
                    "metadata": {
                        "source": "director_legacy",
                        "legacy_message_id": legacy_message.id,
                    },
                }
            ),
            answer_json=_json_dumps({}),
            created_at=_utc_now(),
            updated_at=_utc_now(),
        )
        self.session.add(question)
        self.session.flush()
        return question

    def _build_turn(
        self,
        *,
        role: str,
        blocks: List[Dict[str, Any]],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": uuid.uuid4().hex,
            "role": role,
            "created_at": _iso(_utc_now()),
            "blocks": blocks,
            "metadata": metadata or {},
        }

    def _insert_turn_event(self, *, session_obj: AssistantSession, turn: Dict[str, Any]) -> AssistantTranscriptEvent:
        event = AssistantTranscriptEvent(
            session_id=session_obj.id,
            turn_id=str(turn.get("id") or uuid.uuid4().hex),
            role=str(turn.get("role") or ""),
            event_type="turn",
            block_type=None,
            sequence_no=self._next_sequence_no(session_obj.id),
            payload_json=_json_dumps(turn),
            created_at=_utc_now(),
        )
        self.session.add(event)
        return event

    def _append_error_turn(self, *, session_obj: AssistantSession, error_text: str) -> None:
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

    def _serialize_pending_question(self, question: AssistantPendingQuestion) -> Dict[str, Any]:
        payload = _json_loads(question.payload_json, {})
        return {
            "id": question.question_key,
            "question_type": question.question_type,
            "status": question.status,
            "title": question.title or "需要确认",
            "prompt": question.prompt_text or "",
            "options": payload.get("options") or [],
            "preview": payload.get("preview") or {},
            "task_type": payload.get("task_type"),
            "created_at": _iso(question.created_at),
            "updated_at": _iso(question.updated_at),
        }

    # ==================== helpers ====================

    def _build_runtime_context(self, session_obj: AssistantSession) -> Dict[str, Any]:
        metadata = _json_loads(session_obj.metadata_json, {})
        legacy_session_id = metadata.get("legacy_director_session_id")
        base_context: Dict[str, Any]
        if legacy_session_id:
            legacy_session = self.session.get(DirectorAgentSession, legacy_session_id)
            if legacy_session:
                base_context = _json_loads(legacy_session.context_snapshot_json, {})
            else:
                base_context = self._build_context_snapshot(
                    script_id=session_obj.script_id,
                    episode_id=session_obj.episode_id,
                )
        else:
            base_context = self._build_context_snapshot(
                script_id=session_obj.script_id,
                episode_id=session_obj.episode_id,
            )

        bridge_state = self.get_bridge_state(session_obj=session_obj)
        base_context["bridge"] = {
            "linked": bool(bridge_state.get("linked")),
            "provider": bridge_state.get("provider"),
            "status": bridge_state.get("status"),
            "base_name": bridge_state.get("base_name"),
            "workspace_summary": bridge_state.get("workspace_summary") or {"file_count": 0, "files": []},
            "last_reply_text": bridge_state.get("last_reply_text") or "",
        }
        workflow_snapshot = self._build_workflow_snapshot(session_obj)
        if workflow_snapshot:
            base_context["workflow"] = workflow_snapshot
        return base_context

    def _build_workflow_snapshot(self, session_obj: AssistantSession) -> Dict[str, Any]:
        service = AgentWorkflowService(self.session)
        if session_obj.episode_id:
            try:
                return service.get_episode_workflow_read_model(
                    user=self.session.get(User, session_obj.user_id),
                    team=self.session.get(Team, session_obj.team_id),
                    script_id=session_obj.script_id,
                    episode_id=session_obj.episode_id,
                )
            except Exception:
                pass
        try:
            return service.get_script_workflow_read_model(
                user=self.session.get(User, session_obj.user_id),
                team=self.session.get(Team, session_obj.team_id),
                script_id=session_obj.script_id,
            )
        except Exception:
            return {}

    def _build_context_snapshot(self, *, script_id: int, episode_id: Optional[int]) -> Dict[str, Any]:
        script = self.session.get(Script, script_id)
        if not script:
            return {}

        context = {
            "script": {
                "id": script_id,
                "name": script.name,
                "aspect_ratio": script.aspect_ratio,
                "style_preset": script.style_preset,
                "has_source_text": bool(script.source_text),
            },
            "episode": None,
            "panels_summary": {},
            "shared_resources": {},
        }

        director_service = DirectorAgentService(self.session)
        try:
            legacy_context = director_service._build_context_snapshot(script_id, episode_id)
            if legacy_context.get("episode") is not None:
                context["episode"] = legacy_context.get("episode")
            if legacy_context.get("panels_summary") is not None:
                context["panels_summary"] = legacy_context.get("panels_summary") or {}
            if legacy_context.get("shared_resources") is not None:
                context["shared_resources"] = legacy_context.get("shared_resources") or {}
        except Exception:
            pass

        if not context["shared_resources"]:
            resources = self.session.exec(
                select(SharedResource).where(SharedResource.script_id == script_id)
            ).all()
            characters = [item for item in resources if item.resource_type == "character"]
            scenes = [item for item in resources if item.resource_type == "scene"]
            props = [item for item in resources if item.resource_type == "prop"]
            context["shared_resources"] = {
                "characters": [{"id": item.id, "name": item.name, "has_image": bool(item.file_url)} for item in characters],
                "scenes": [{"id": item.id, "name": item.name, "has_image": bool(item.file_url)} for item in scenes],
                "props": [{"id": item.id, "name": item.name, "has_image": bool(item.file_url)} for item in props],
            }
        return context

    def _ensure_legacy_director_session(self, *, session_obj: AssistantSession, user: User) -> int:
        metadata = _json_loads(session_obj.metadata_json, {})
        legacy_session_id = metadata.get("legacy_director_session_id")
        if legacy_session_id:
            return int(legacy_session_id)

        director_service = DirectorAgentService(self.session)
        legacy_session = director_service.create_session(
            user=user,
            script_id=session_obj.script_id,
            episode_id=session_obj.episode_id,
            title=session_obj.title or self.DEFAULT_SESSION_TITLE,
        )
        metadata["legacy_director_session_id"] = legacy_session.id
        session_obj.metadata_json = _json_dumps(metadata)
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        self.session.commit()
        self.session.refresh(session_obj)
        return legacy_session.id

    def _require_external_session(
        self,
        *,
        user: User,
        script_id: int,
        external_session_id: int,
    ) -> ExternalAgentSession:
        item = self.session.get(ExternalAgentSession, external_session_id)
        if not item:
            raise HTTPException(status_code=404, detail="站外 Agent 会话不存在")
        if item.user_id != user.id or item.script_id != script_id:
            raise HTTPException(status_code=403, detail="无权绑定当前站外 Agent 会话")
        return item

    def _find_default_external_session(
        self,
        *,
        script_id: int,
        user_id: int,
        episode_id: Optional[int] = None,
    ) -> Optional[ExternalAgentSession]:
        items = self.session.exec(
            select(ExternalAgentSession)
            .where(
                ExternalAgentSession.script_id == script_id,
                ExternalAgentSession.user_id == user_id,
            )
            .order_by(
                desc(ExternalAgentSession.is_active),
                desc(ExternalAgentSession.updated_at),
                desc(ExternalAgentSession.id),
            )
        ).all()
        if not items:
            return None
        if episode_id:
            for item in items:
                if item.episode_id == episode_id:
                    return item
        return items[0]

    def _resolve_external_bridge(self, *, session_obj: AssistantSession, user: User) -> ExternalAgentSession:
        external_session = None
        if session_obj.linked_external_session_id:
            external_session = self.session.get(ExternalAgentSession, session_obj.linked_external_session_id)
        if not external_session:
            external_session = self._find_default_external_session(
                script_id=session_obj.script_id,
                user_id=user.id,
                episode_id=session_obj.episode_id,
            )
        if not external_session:
            raise HTTPException(status_code=404, detail="当前项目尚未绑定可用的站外 Agent 会话")
        if external_session.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问当前站外 Agent 会话")
        session_obj.linked_external_session_id = external_session.id
        session_obj.updated_at = _utc_now()
        self.session.add(session_obj)
        return external_session

    def _next_sequence_no(self, assistant_session_id: int) -> int:
        latest = self.session.exec(
            select(AssistantTranscriptEvent)
            .where(AssistantTranscriptEvent.session_id == assistant_session_id)
            .order_by(desc(AssistantTranscriptEvent.sequence_no), desc(AssistantTranscriptEvent.id))
            .limit(1)
        ).first()
        if not latest:
            return 1
        return int(latest.sequence_no or 0) + 1

    def _sanitize_metadata(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(metadata or {})
        result.pop("legacy_director_session_id", None)
        return result

    def _find_block_by_type(self, turn: Dict[str, Any], block_type: str) -> Optional[Dict[str, Any]]:
        for item in turn.get("blocks") or []:
            if item.get("type") == block_type:
                return item
        return None

    def publish_event(self, assistant_session_id: int, event: Dict[str, Any]) -> Dict[str, Any]:
        return assistant_runtime_event_manager.publish(encode_id(assistant_session_id), event)

    def publish_snapshot(self, assistant_session_id: int) -> None:
        snapshot = self.get_snapshot_by_id(assistant_session_id)
        self.publish_event(assistant_session_id, {"type": "snapshot", "snapshot": snapshot})

    def _http_exception_message(self, exc: HTTPException) -> str:
        detail = exc.detail
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("detail") or detail.get("error") or "请求失败")
        return str(detail or "请求失败")
