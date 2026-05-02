from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session, select

from core.security import encode_id
from models import (
    Episode,
    EpisodeWorkflowState,
    GenerationRecord,
    Panel,
    Script,
    ScriptWorkflowState,
    SharedResource,
    Team,
    User,
)
from services.access_service import require_episode_team_access, require_script_team_access
from services.workflow_preset_service import resolve_effective_workflow_profile


SCRIPT_STEPS = [
    ("INIT", "demand_understanding"),
    ("STORY_PLANNING", "story_planning"),
    ("EPISODE_SPLITTING", "episode_splitting"),
]

EPISODE_STEPS = [
    ("ASSET_EXTRACTION", "asset_extraction"),
    ("STORYBOARDING", "storyboarding"),
    ("PROMPT_OPTIMIZATION", "prompt_optimization"),
    ("IMAGE_GENERATION", "image_generation"),
    ("VIDEO_GENERATION", "video_generation"),
    ("AUDIO_GENERATION", "audio_generation"),
    ("REVIEW", "review_optimization"),
]

STEP_LABELS = {
    "demand_understanding": "需求理解",
    "story_planning": "剧情策划",
    "episode_splitting": "分集拆分",
    "asset_extraction": "资产提取",
    "storyboarding": "分镜拆分",
    "prompt_optimization": "提示词与模型推荐",
    "image_generation": "图片生成执行",
    "video_generation": "视频生成执行",
    "audio_generation": "音频生成执行",
    "review_optimization": "结果评估与二次优化",
}

STATUS_LABELS = {
    "idle": "待开始",
    "ready": "可开始",
    "waiting_confirmation": "等待确认",
    "execution_dispatched": "已提交执行",
    "blocked": "前置不足",
    "completed": "已完成",
    "failed": "执行失败",
}

SCRIPT_STEP_KIND = {
    "demand_understanding": "insight",
    "story_planning": "insight",
    "episode_splitting": "insight",
}

EPISODE_STEP_KIND = {
    "asset_extraction": "assistant_execution",
    "storyboarding": "assistant_execution",
    "prompt_optimization": "insight",
    "image_generation": "assistant_execution",
    "video_generation": "assistant_execution",
    "audio_generation": "assistant_execution",
    "review_optimization": "insight",
}

STEP_ASSISTANT_ACTION = {
    "asset_extraction": "/提取角色",
    "storyboarding": "/写分镜",
    "image_generation": "/出图",
    "video_generation": "/视频",
    "audio_generation": "/配音",
}

PROCESS_CAPABILITIES = [
    {"id": "workflow_one_click", "label": "一键做剧", "description": "从原文一路推进到样片。"},
    {"id": "workflow_stepwise", "label": "分步做剧", "description": "按阶段逐步推进并随时确认。"},
    {"id": "workflow_auto_progress", "label": "自动推进", "description": "在低风险节点自动流转。"},
    {"id": "workflow_pause_confirm", "label": "节点暂停确认", "description": "在关键节点把控制权交给你。"},
]

OPTIMIZATION_CAPABILITIES = [
    {"id": "optimize_prompt", "label": "优化提示词", "description": "润色图片和视频提示词。"},
    {"id": "recommend_model", "label": "推荐模型", "description": "根据目标镜头和预算推荐模型。"},
    {"id": "optimize_storyboard", "label": "优化分镜拆分", "description": "重拆镜头并调整节奏。"},
    {"id": "rewrite_story", "label": "剧情改写", "description": "重写、压缩或增强情节。"},
    {"id": "continue_story", "label": "剧情续写", "description": "补全后续剧情与反转。"},
    {"id": "boost_hook", "label": "提升爆点", "description": "增强爽点和钩子结尾。"},
    {"id": "boost_twist", "label": "加强反转", "description": "补强冲突和逆转节点。"},
    {"id": "tighten_pacing", "label": "提高节奏感", "description": "压缩慢镜头并前置爆点。"},
    {"id": "unify_character_style", "label": "统一角色风格", "description": "提升角色形象一致性。"},
    {"id": "improve_continuity", "label": "提高镜头连贯性", "description": "修正上下镜头承接。"},
    {"id": "control_budget", "label": "控制预算 / 灵感值", "description": "优先给出省成本的生成策略。"},
]


def _utc_now() -> datetime:
    return datetime.utcnow()


def _json_loads(raw: Optional[str], fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _status_label(value: str) -> str:
    return STATUS_LABELS.get(value, value or "未知")


class AgentWorkflowService:
    def __init__(self, session: Session):
        self.session = session

    # ===== lifecycle =====
    def ensure_script_states(self, *, script: Script) -> Tuple[ScriptWorkflowState, List[EpisodeWorkflowState]]:
        script_state = self._ensure_script_state(script=script)
        episode_states: List[EpisodeWorkflowState] = []
        episodes = self.session.exec(
            select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc(), Episode.id.asc())
        ).all()
        for episode in episodes:
            episode_states.append(self._ensure_episode_state(script=script, episode=episode))
        return script_state, episode_states

    def ensure_episode_state_for_episode(self, *, script: Script, episode: Episode) -> EpisodeWorkflowState:
        item = self._ensure_episode_state(script=script, episode=episode)
        return item

    def _ensure_script_state(self, *, script: Script) -> ScriptWorkflowState:
        item = self.session.exec(
            select(ScriptWorkflowState).where(ScriptWorkflowState.script_id == script.id)
        ).first()
        if item:
            return item
        now = _utc_now()
        item = ScriptWorkflowState(
            script_id=script.id,
            team_id=script.team_id,
            current_stage="INIT",
            stage_status="idle",
            current_step_key="demand_understanding",
            mode="semi_auto",
            pause_policy="stage_boundary_and_cost",
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def _ensure_episode_state(self, *, script: Script, episode: Episode) -> EpisodeWorkflowState:
        item = self.session.exec(
            select(EpisodeWorkflowState).where(EpisodeWorkflowState.episode_id == episode.id)
        ).first()
        if item:
            return item
        now = _utc_now()
        item = EpisodeWorkflowState(
            script_id=script.id,
            episode_id=episode.id,
            team_id=script.team_id,
            current_stage="ASSET_EXTRACTION",
            stage_status="idle",
            current_step_key="asset_extraction",
            mode="semi_auto",
            pause_policy="stage_boundary_and_cost",
            created_at=now,
            updated_at=now,
        )
        self.session.add(item)
        self.session.flush()
        return item

    # ===== read model =====
    def get_script_workflow_read_model(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
    ) -> Dict[str, Any]:
        script = require_script_team_access(self.session, team, script_id)
        script_state, episode_states = self.ensure_script_states(script=script)
        script_state = self._sync_script_state(script=script, state=script_state)
        episodes = self.session.exec(
            select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc(), Episode.id.asc())
        ).all()
        episode_items = []
        for episode, episode_state in zip(episodes, episode_states):
            synced_state = self._sync_episode_state(script=script, episode=episode, state=episode_state)
            episode_items.append(self._serialize_episode_workflow(script=script, episode=episode, state=synced_state))
        self.session.commit()
        current_node = self._build_script_current_node(script=script, state=script_state, episodes=episodes)
        return {
            "script_workflow": self._serialize_script_workflow(script=script, state=script_state, episode_items=episode_items),
            "episode_workflow": episode_items[0] if episode_items else None,
            "current_node": current_node,
            "available_actions": current_node.get("available_actions") or [],
            "recent_results": self._recent_results(state=script_state),
            "quality_assessment": current_node.get("quality") or {},
            "next_recommendation": current_node.get("next_recommendation") or "",
        }

    def get_episode_workflow_read_model(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: int,
    ) -> Dict[str, Any]:
        script = require_script_team_access(self.session, team, script_id)
        episode = require_episode_team_access(self.session, team, episode_id)
        if episode.script_id != script.id:
            raise HTTPException(status_code=400, detail="目标剧集不属于当前剧本")
        script_state, _ = self.ensure_script_states(script=script)
        episode_state = self._ensure_episode_state(script=script, episode=episode)
        script_state = self._sync_script_state(script=script, state=script_state)
        episode_state = self._sync_episode_state(script=script, episode=episode, state=episode_state)
        self.session.commit()
        current_node = self._build_episode_current_node(script=script, episode=episode, state=episode_state)
        return {
            "script_workflow": self._serialize_script_workflow(script=script, state=script_state),
            "episode_workflow": self._serialize_episode_workflow(script=script, episode=episode, state=episode_state),
            "current_node": current_node,
            "available_actions": current_node.get("available_actions") or [],
            "recent_results": self._recent_results(state=episode_state),
            "quality_assessment": current_node.get("quality") or {},
            "next_recommendation": current_node.get("next_recommendation") or "",
        }

    # ===== mutate =====
    def advance_script_workflow(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
    ) -> Dict[str, Any]:
        script = require_script_team_access(self.session, team, script_id)
        script_state, _ = self.ensure_script_states(script=script)
        script_state = self._sync_script_state(script=script, state=script_state)
        next_step = self._next_script_step_key(script_state.current_step_key) if self._can_move_forward_script(script_state) else script_state.current_step_key
        if next_step != script_state.current_step_key:
            self._advance_script_state_to_step(script_state, next_step)
        self._execute_script_step(script=script, state=script_state)
        self.session.commit()
        return self.get_script_workflow_read_model(user=user, team=team, script_id=script_id)

    def advance_episode_workflow(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: int,
    ) -> Dict[str, Any]:
        script = require_script_team_access(self.session, team, script_id)
        episode = require_episode_team_access(self.session, team, episode_id)
        if episode.script_id != script.id:
            raise HTTPException(status_code=400, detail="目标剧集不属于当前剧本")
        episode_state = self._ensure_episode_state(script=script, episode=episode)
        episode_state = self._sync_episode_state(script=script, episode=episode, state=episode_state)
        next_step = self._next_episode_step_key(episode_state.current_step_key) if self._can_move_forward_episode(script, episode, episode_state) else episode_state.current_step_key
        if next_step != episode_state.current_step_key:
            self._advance_episode_state_to_step(episode_state, next_step)
        self._execute_episode_step(script=script, episode=episode, state=episode_state)
        self.session.commit()
        return self.get_episode_workflow_read_model(user=user, team=team, script_id=script_id, episode_id=episode_id)

    def redo_episode_workflow(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: int,
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        script = require_script_team_access(self.session, team, script_id)
        episode = require_episode_team_access(self.session, team, episode_id)
        state = self._ensure_episode_state(script=script, episode=episode)
        state = self._sync_episode_state(script=script, episode=episode, state=state)
        self._append_history_snapshot(state, action="redo", instruction=instruction)
        self._execute_episode_step(script=script, episode=episode, state=state, instruction=instruction, force_rebuild=True)
        self.session.commit()
        return self.get_episode_workflow_read_model(user=user, team=team, script_id=script_id, episode_id=episode_id)

    def adjust_episode_workflow(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: int,
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._mutate_episode_with_instruction(
            user=user,
            team=team,
            script_id=script_id,
            episode_id=episode_id,
            instruction=instruction,
            action="adjust",
        )

    def optimize_episode_workflow(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: int,
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self._mutate_episode_with_instruction(
            user=user,
            team=team,
            script_id=script_id,
            episode_id=episode_id,
            instruction=instruction,
            action="optimize",
        )

    def _mutate_episode_with_instruction(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: int,
        instruction: Optional[str],
        action: str,
    ) -> Dict[str, Any]:
        script = require_script_team_access(self.session, team, script_id)
        episode = require_episode_team_access(self.session, team, episode_id)
        state = self._ensure_episode_state(script=script, episode=episode)
        state = self._sync_episode_state(script=script, episode=episode, state=state)
        self._append_history_snapshot(state, action=action, instruction=instruction)
        self._execute_episode_step(script=script, episode=episode, state=state, instruction=instruction, force_rebuild=True)
        self.session.commit()
        return self.get_episode_workflow_read_model(user=user, team=team, script_id=script_id, episode_id=episode_id)

    def confirm_episode_workflow(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: int,
        action: str = "confirm",
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        script = require_script_team_access(self.session, team, script_id)
        episode = require_episode_team_access(self.session, team, episode_id)
        state = self._ensure_episode_state(script=script, episode=episode)
        state = self._sync_episode_state(script=script, episode=episode, state=state)
        pending_confirmation = _json_loads(state.pending_confirmation_json, {})
        assistant_action = None
        if action != "confirm":
            state.stage_status = "waiting_confirmation"
            state.last_user_decision_at = _utc_now()
            pending_confirmation["last_decision"] = action
            state.pending_confirmation_json = _json_dumps(pending_confirmation)
        else:
            assistant_action = pending_confirmation.get("assistant_action") or self._assistant_action_for_step(state.current_step_key, episode=episode)
            state.stage_status = "execution_dispatched"
            state.last_user_decision_at = _utc_now()
            pending_confirmation["last_decision"] = "confirm"
            state.pending_confirmation_json = _json_dumps(pending_confirmation)
            self._write_result_summary(
                state,
                {
                    "title": STEP_LABELS.get(state.current_step_key, state.current_step_key),
                    "summary": "已确认执行，本轮会进入正式任务提交或等待结果回写。",
                    "kind": "dispatch",
                },
            )
        state.version += 1
        state.updated_at = _utc_now()
        self.session.add(state)
        self.session.commit()
        data = self.get_episode_workflow_read_model(user=user, team=team, script_id=script_id, episode_id=episode_id)
        if assistant_action:
            data["assistant_action"] = assistant_action
        return data

    # ===== assistant integration =====
    def build_snapshot_fields(self, *, script_id: int, episode_id: Optional[int]) -> Dict[str, Any]:
        script = self.session.get(Script, script_id)
        if not script:
            return {}
        script_state, _ = self.ensure_script_states(script=script)
        script_state = self._sync_script_state(script=script, state=script_state)
        if episode_id:
            episode = self.session.get(Episode, episode_id)
            if episode and episode.script_id == script.id:
                episode_state = self._ensure_episode_state(script=script, episode=episode)
                episode_state = self._sync_episode_state(script=script, episode=episode, state=episode_state)
                return {
                    "workflow_state_version": int(episode_state.version or 1),
                    "workflow_stage": episode_state.current_stage,
                    "workflow_step_key": episode_state.current_step_key,
                    "workflow_pending_confirmation": bool((_json_loads(episode_state.pending_confirmation_json, {}) or {}).get("assistant_action")),
                }
        return {
            "workflow_state_version": int(script_state.version or 1),
            "workflow_stage": script_state.current_stage,
            "workflow_step_key": script_state.current_step_key,
            "workflow_pending_confirmation": False,
        }

    def grouped_capabilities(self) -> Dict[str, Any]:
        return {
            "process_capabilities": PROCESS_CAPABILITIES,
            "optimization_capabilities": OPTIMIZATION_CAPABILITIES,
        }

    def handle_conversation_message(
        self,
        *,
        user: User,
        team: Team,
        script_id: int,
        episode_id: Optional[int],
        message: str,
    ) -> Optional[Dict[str, Any]]:
        text = " ".join(str(message or "").strip().split())
        lowered = text.lower()
        if not text:
            return None
        if any(token in lowered for token in ["继续下一步", "继续", "推进", "下一步", "开始做剧", "开始规划"]):
            if episode_id:
                data = self.advance_episode_workflow(user=user, team=team, script_id=script_id, episode_id=episode_id)
            else:
                data = self.advance_script_workflow(user=user, team=team, script_id=script_id)
            return self._build_assistant_payload(data, intro="我已经按当前流程推进了下一步。")
        if episode_id and any(token in lowered for token in ["重做", "重来", "重拆", "重新做"]):
            data = self.redo_episode_workflow(user=user, team=team, script_id=script_id, episode_id=episode_id, instruction=text)
            return self._build_assistant_payload(data, intro="我已经按你的要求重做当前环节。")
        if episode_id and any(token in lowered for token in ["优化", "改得更", "调整", "压缩节奏", "统一风格", "省预算"]):
            data = self.optimize_episode_workflow(user=user, team=team, script_id=script_id, episode_id=episode_id, instruction=text)
            return self._build_assistant_payload(data, intro="我先按你的调优要求重算当前环节。")
        return None

    def _build_assistant_payload(self, data: Dict[str, Any], *, intro: str) -> Dict[str, Any]:
        current_node = data.get("current_node") or {}
        blocks = [
            {
                "id": "workflow-summary",
                "type": "reasoning_summary",
                "summary": intro,
            }
        ]
        if current_node.get("summary"):
            blocks.append(
                {
                    "id": "workflow-result",
                    "type": "tool_result",
                    "tool_name": current_node.get("step_key") or "workflow_step",
                    "summary": current_node.get("summary"),
                    "result": {
                        "detail": current_node.get("detail") or {},
                        "quality": current_node.get("quality") or {},
                        "recommended_actions": current_node.get("recommended_actions") or [],
                        "refresh_hints": current_node.get("refresh_hints") or {},
                    },
                }
            )
        return {"workflow_data": data, "blocks": blocks}

    # ===== execute step =====
    def _execute_script_step(self, *, script: Script, state: ScriptWorkflowState) -> None:
        current_step = state.current_step_key
        state.last_agent_run_at = _utc_now()
        state.updated_at = _utc_now()
        state.version += 1
        if current_step == "demand_understanding":
            result = self._result_for_demand_understanding(script)
        elif current_step == "story_planning":
            result = self._result_for_story_planning(script)
        else:
            result = self._result_for_episode_splitting(script)
        self._apply_result_to_state(state, result, step_kind=SCRIPT_STEP_KIND.get(current_step, "insight"))
        self.session.add(state)

    def _execute_episode_step(
        self,
        *,
        script: Script,
        episode: Episode,
        state: EpisodeWorkflowState,
        instruction: Optional[str] = None,
        force_rebuild: bool = False,
    ) -> None:
        current_step = state.current_step_key
        metrics = self._episode_metrics(script=script, episode=episode)
        if not force_rebuild and EPISODE_STEP_KIND.get(current_step) == "assistant_execution":
            if self._is_execution_step_complete(current_step, metrics):
                result = self._result_from_existing_facts(script=script, episode=episode, step_key=current_step, metrics=metrics)
                self._apply_result_to_state(state, result, step_kind="assistant_execution", execution_completed=True)
                self.session.add(state)
                return
        state.last_agent_run_at = _utc_now()
        state.updated_at = _utc_now()
        state.version += 1
        result = self._build_episode_step_result(script=script, episode=episode, step_key=current_step, metrics=metrics, instruction=instruction)
        execution_completed = EPISODE_STEP_KIND.get(current_step) == "assistant_execution" and self._is_execution_step_complete(current_step, metrics)
        self._apply_result_to_state(state, result, step_kind=EPISODE_STEP_KIND.get(current_step, "insight"), execution_completed=execution_completed)
        self.session.add(state)

    def _apply_result_to_state(
        self,
        state: ScriptWorkflowState | EpisodeWorkflowState,
        result: Dict[str, Any],
        *,
        step_kind: str,
        execution_completed: bool = False,
    ) -> None:
        self._write_result_summary(state, result.get("summary") or {})
        state.result_detail_json = _json_dumps(result.get("detail") or {})
        state.quality_assessment_json = _json_dumps(result.get("quality") or {})
        state.recommended_actions_json = _json_dumps(result.get("recommended_actions") or [])
        state.adjustment_actions_json = _json_dumps(result.get("adjustment_actions") or [])
        pending_confirmation = result.get("pending_confirmation") or {}
        if step_kind == "assistant_execution" and not execution_completed and pending_confirmation.get("assistant_action"):
            state.stage_status = "waiting_confirmation"
        elif result.get("blocked"):
            state.stage_status = "blocked"
        else:
            state.stage_status = "waiting_confirmation"
        state.pending_confirmation_json = _json_dumps(pending_confirmation)
        state.last_agent_run_at = _utc_now()
        state.updated_at = _utc_now()

    def _write_result_summary(self, state: ScriptWorkflowState | EpisodeWorkflowState, payload: Dict[str, Any]) -> None:
        state.result_summary_json = _json_dumps(payload or {})

    def _append_history_snapshot(
        self,
        state: ScriptWorkflowState | EpisodeWorkflowState,
        *,
        action: str,
        instruction: Optional[str],
    ) -> None:
        history = _json_loads(state.history_versions_json, [])
        history.append(
            {
                "version": int(state.version or 1),
                "captured_at": _utc_now().isoformat(),
                "action": action,
                "instruction": instruction or "",
                "stage": state.current_stage,
                "step_key": state.current_step_key,
                "summary": _json_loads(state.result_summary_json, {}),
            }
        )
        state.history_versions_json = _json_dumps(history[-12:])

    # ===== result builders =====
    def _result_for_demand_understanding(self, script: Script) -> Dict[str, Any]:
        source_text = (script.source_text or "").strip()
        text_length = len(source_text)
        if text_length <= 0:
            summary = "当前项目还没有可分析的原文，建议先补充故事想法、小说片段或现成剧本。"
            return self._node_payload(
                step_key="demand_understanding",
                stage="INIT",
                status="blocked",
                summary=summary,
                detail={"source_text_length": 0, "project_name": script.name},
                quality={"assessment": "信息不足", "risk": "缺少创作输入，后续剧情策划无法推进。"},
                recommended_actions=["先补充剧本原文", "给一句话灵感后再开始"],
                next_stage="STORY_PLANNING",
                can_continue=False,
                needs_confirmation=True,
                blocked=True,
            )
        estimated_episodes = max(1, min(12, math.ceil(text_length / 1800)))
        recommended_path = "快速模式" if text_length < 1500 else "标准模式" if text_length < 5000 else "精修模式"
        summary = f"我已完成需求理解：当前项目更适合按“{recommended_path}”推进，预计可整理出约 {estimated_episodes} 集的漫剧骨架。"
        return self._node_payload(
            step_key="demand_understanding",
            stage="INIT",
            status="waiting_confirmation",
            summary=summary,
            detail={
                "project_name": script.name,
                "source_text_length": text_length,
                "recommended_path": recommended_path,
                "estimated_episode_count": estimated_episodes,
                "input_preview": source_text[:180],
            },
            quality={"assessment": "可进入剧情策划", "strength": "原文长度足够支持首轮剧情整理。"},
            recommended_actions=["继续剧情策划", "先压缩设定", "先明确题材与画风"],
            next_stage="STORY_PLANNING",
            can_continue=True,
            needs_confirmation=True,
        )

    def _result_for_story_planning(self, script: Script) -> Dict[str, Any]:
        source_text = (script.source_text or "").strip()
        key_sentences = [line.strip() for line in source_text.splitlines() if line.strip()][:3]
        hook_strength = "中等"
        if any(token in source_text for token in ["反转", "复仇", "逆袭", "危机", "真相"]):
            hook_strength = "较强"
        summary = "剧情策划已整理完成：我已经把当前原文压成适合漫剧生产的故事骨架，并标出后续分集时最值得保留的冲突点。"
        return self._node_payload(
            step_key="story_planning",
            stage="STORY_PLANNING",
            status="waiting_confirmation",
            summary=summary,
            detail={
                "story_core": key_sentences[0] if key_sentences else source_text[:120],
                "key_conflicts": key_sentences[1:3],
                "hook_strength": hook_strength,
                "suggested_goal": "保留爽点和冲突节奏，再进入分集拆分。",
            },
            quality={"assessment": "适合进入分集拆分", "risk": "如果希望更爽或更短，建议在这一轮先调整。"},
            recommended_actions=["继续分集拆分", "改得更短", "增强爽感与反转"],
            adjustment_actions=["剧情改写", "剧情续写", "提升爆点", "加强反转"],
            next_stage="EPISODE_SPLITTING",
            can_continue=True,
            needs_confirmation=True,
        )

    def _result_for_episode_splitting(self, script: Script) -> Dict[str, Any]:
        episodes = self.session.exec(
            select(Episode).where(Episode.script_id == script.id).order_by(Episode.sequence_num.asc(), Episode.id.asc())
        ).all()
        summary = f"分集拆分阶段已准备好：当前项目有 {len(episodes)} 集，你可以先从当前分集进入资产提取和分镜生产。"
        return self._node_payload(
            step_key="episode_splitting",
            stage="EPISODE_SPLITTING",
            status="waiting_confirmation",
            summary=summary,
            detail={
                "episode_count": len(episodes),
                "episodes": [
                    {"episode_id": encode_id(item.id), "title": item.title, "sequence_num": item.sequence_num}
                    for item in episodes[:12]
                ],
            },
            quality={"assessment": "项目已具备按分集推进的条件", "risk": "如果要重新拆集，建议先在这里调整节奏和钩子。"},
            recommended_actions=["进入当前分集资产提取", "补强分集钩子", "重新拆分分集"],
            next_stage="ASSET_EXTRACTION",
            can_continue=True,
            needs_confirmation=True,
        )

    def _build_episode_step_result(
        self,
        *,
        script: Script,
        episode: Episode,
        step_key: str,
        metrics: Dict[str, Any],
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        if step_key == "asset_extraction":
            return self._result_for_asset_extraction(script=script, episode=episode, metrics=metrics, instruction=instruction)
        if step_key == "storyboarding":
            return self._result_for_storyboarding(script=script, episode=episode, metrics=metrics, instruction=instruction)
        if step_key == "prompt_optimization":
            return self._result_for_prompt_optimization(script=script, episode=episode, metrics=metrics, instruction=instruction)
        if step_key == "image_generation":
            return self._result_for_image_generation(script=script, episode=episode, metrics=metrics)
        if step_key == "video_generation":
            return self._result_for_video_generation(script=script, episode=episode, metrics=metrics)
        if step_key == "audio_generation":
            return self._result_for_audio_generation(script=script, episode=episode, metrics=metrics)
        return self._result_for_review(script=script, episode=episode, metrics=metrics, instruction=instruction)

    def _result_for_asset_extraction(
        self,
        *,
        script: Script,
        episode: Episode,
        metrics: Dict[str, Any],
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        resource_total = metrics["resource_total"]
        if resource_total > 0:
            summary = f"资产提取已具备基础：当前项目已有 {resource_total} 个共享资产，可以直接继续进入分镜拆分。"
            return self._node_payload(
                step_key="asset_extraction",
                stage="ASSET_EXTRACTION",
                status="waiting_confirmation",
                summary=summary,
                detail={"resource_counts": metrics["resource_counts"], "instruction": instruction or ""},
                quality={"assessment": "角色和场景已有基础", "risk": "若人物辨识度不够，可先补强人设。"},
                recommended_actions=["继续分镜拆分", "补强角色设定", "统一场景与服装风格"],
                adjustment_actions=["角色设定增强", "统一角色风格", "提高资产复用率"],
                next_stage="STORYBOARDING",
                can_continue=True,
                needs_confirmation=True,
            )
        source_text = (episode.source_text or script.source_text or "").strip()
        if not source_text:
            return self._node_payload(
                step_key="asset_extraction",
                stage="ASSET_EXTRACTION",
                status="blocked",
                summary="当前剧集还没有可用原文，暂时不能提取角色、场景和道具。",
                detail={"resource_counts": metrics["resource_counts"]},
                quality={"assessment": "前置不足", "risk": "请先补充剧集原文。"},
                recommended_actions=["先补充剧本原文"],
                next_stage="STORYBOARDING",
                can_continue=False,
                needs_confirmation=True,
                blocked=True,
            )
        return self._node_payload(
            step_key="asset_extraction",
            stage="ASSET_EXTRACTION",
            status="waiting_confirmation",
            summary="资产提取已准备好：我建议先从当前剧集提取人物、场景和道具，再进入分镜拆分。",
            detail={"resource_counts": metrics["resource_counts"], "instruction": instruction or ""},
            quality={"assessment": "适合先做资产梳理", "risk": "如果跳过这一步，后续分镜绑定和画风统一会变弱。"},
            recommended_actions=["开始提取资产", "先看现有资源", "补充角色外观要求"],
            adjustment_actions=["角色设定增强", "统一角色风格", "控制预算 / 灵感值"],
            next_stage="STORYBOARDING",
            can_continue=False,
            needs_confirmation=True,
            pending_confirmation={
                "assistant_action": self._assistant_action_for_step("asset_extraction", episode=episode),
                "label": "确认提取资产",
            },
        )

    def _result_for_storyboarding(
        self,
        *,
        script: Script,
        episode: Episode,
        metrics: Dict[str, Any],
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        if metrics["panel_total"] > 0:
            summary = f"当前分集已有 {metrics['panel_total']} 个分镜，可继续进入提示词与模型推荐。"
            return self._node_payload(
                step_key="storyboarding",
                stage="STORYBOARDING",
                status="waiting_confirmation",
                summary=summary,
                detail={
                    "panel_total": metrics["panel_total"],
                    "with_images": metrics["panels_with_images"],
                    "with_videos": metrics["panels_with_videos"],
                    "instruction": instruction or "",
                },
                quality={"assessment": "分镜基础已建立", "risk": "如果镜头过碎或节奏偏慢，建议先重拆。"},
                recommended_actions=["继续提示词与模型推荐", "重拆当前分镜", "压缩镜头节奏"],
                adjustment_actions=["优化分镜拆分", "提高镜头连贯性", "提高节奏感"],
                next_stage="PROMPT_OPTIMIZATION",
                can_continue=True,
                needs_confirmation=True,
            )
        if not (episode.source_text or script.source_text):
            return self._node_payload(
                step_key="storyboarding",
                stage="STORYBOARDING",
                status="blocked",
                summary="当前剧集没有可用原文，暂时无法生成分镜。",
                detail={"panel_total": 0},
                quality={"assessment": "前置不足", "risk": "需要先补充原文或完成剧情策划。"},
                recommended_actions=["先补充剧本原文"],
                next_stage="PROMPT_OPTIMIZATION",
                can_continue=False,
                needs_confirmation=True,
                blocked=True,
            )
        return self._node_payload(
            step_key="storyboarding",
            stage="STORYBOARDING",
            status="waiting_confirmation",
            summary="分镜拆分已准备好：我建议先把当前剧集转成可生成的镜头语言，再进入提示词与模型推荐。",
            detail={"panel_total": 0, "instruction": instruction or ""},
            quality={"assessment": "适合生成结构化分镜", "risk": "跳过分镜拆分会让后续模型推荐和生成策略失真。"},
            recommended_actions=["开始生成分镜", "先优化剧情节奏", "补充角色与场景约束"],
            adjustment_actions=["优化分镜拆分", "剧情改写", "提高节奏感"],
            next_stage="PROMPT_OPTIMIZATION",
            can_continue=False,
            needs_confirmation=True,
            pending_confirmation={
                "assistant_action": self._assistant_action_for_step("storyboarding", episode=episode),
                "label": "确认生成分镜",
            },
        )

    def _result_for_prompt_optimization(
        self,
        *,
        script: Script,
        episode: Episode,
        metrics: Dict[str, Any],
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        profile = resolve_effective_workflow_profile(script, episode=episode, storyboard_mode=getattr(episode, "storyboard_mode", None))
        image_profile = profile.get("image") or {}
        video_profile = profile.get("video") or {}
        strategy = "建议先出图再做视频" if metrics["panel_total"] > 1 and metrics["panels_with_images"] < metrics["panel_total"] else "已有图像基础，可直接衔接视频生成"
        summary = "提示词与模型推荐已完成：我已经根据当前分镜完成度、画幅和默认工作流给出下一步生成策略。"
        return self._node_payload(
            step_key="prompt_optimization",
            stage="PROMPT_OPTIMIZATION",
            status="waiting_confirmation",
            summary=summary,
            detail={
                "recommended_image_model": image_profile.get("model"),
                "recommended_video_model": video_profile.get("model_code"),
                "recommended_video_duration": video_profile.get("duration"),
                "recommended_video_resolution": video_profile.get("resolution"),
                "estimated_panel_count": metrics["panel_total"],
                "strategy": strategy,
                "instruction": instruction or "",
            },
            quality={"assessment": "推荐策略可直接指导正式生成", "risk": "若预算敏感，建议先做低成本试跑。"},
            recommended_actions=["继续图片生成", "推荐更省预算的模型", "继续优化提示词"],
            adjustment_actions=["优化提示词", "推荐模型", "控制预算 / 灵感值"],
            next_stage="IMAGE_GENERATION",
            can_continue=True,
            needs_confirmation=True,
        )

    def _result_for_image_generation(self, *, script: Script, episode: Episode, metrics: Dict[str, Any]) -> Dict[str, Any]:
        if metrics["panels_with_images"] > 0:
            summary = f"当前分集已有 {metrics['panels_with_images']} 个分镜图，可继续进入视频生成。"
            return self._node_payload(
                step_key="image_generation",
                stage="IMAGE_GENERATION",
                status="waiting_confirmation",
                summary=summary,
                detail={"panels_with_images": metrics["panels_with_images"], "panels_without_images": metrics["panels_without_images"]},
                quality={"assessment": "图像基础已建立", "risk": "如需统一风格，可先补做角色或重出关键镜头。"},
                recommended_actions=["继续视频生成", "补足缺失分镜图", "优化提示词后重出图"],
                adjustment_actions=["优化提示词", "推荐模型", "统一角色风格"],
                next_stage="VIDEO_GENERATION",
                can_continue=True,
                needs_confirmation=True,
            )
        if metrics["panel_total"] <= 0:
            return self._node_payload(
                step_key="image_generation",
                stage="IMAGE_GENERATION",
                status="blocked",
                summary="当前分集还没有分镜，暂时不能进入正式图片生成。",
                detail={"panels_with_images": 0, "panels_without_images": 0},
                quality={"assessment": "前置不足", "risk": "请先完成分镜拆分。"},
                recommended_actions=["先生成分镜"],
                next_stage="VIDEO_GENERATION",
                can_continue=False,
                needs_confirmation=True,
                blocked=True,
            )
        return self._node_payload(
            step_key="image_generation",
            stage="IMAGE_GENERATION",
            status="waiting_confirmation",
            summary=f"当前分集有 {metrics['panels_without_images']} 个分镜待出图，建议先做小批量试跑，再决定是否正式批量生成。",
            detail={"panels_with_images": metrics["panels_with_images"], "panels_without_images": metrics["panels_without_images"]},
            quality={"assessment": "适合进入正式出图", "risk": "正式出图属于高成本节点，建议确认后再提交。"},
            recommended_actions=["确认正式出图", "先做低成本试跑", "优化提示词后再出图"],
            adjustment_actions=["优化提示词", "推荐模型", "控制预算 / 灵感值"],
            next_stage="VIDEO_GENERATION",
            can_continue=False,
            needs_confirmation=True,
            pending_confirmation={
                "assistant_action": self._assistant_action_for_step("image_generation", episode=episode),
                "label": "确认正式出图",
            },
        )

    def _result_for_video_generation(self, *, script: Script, episode: Episode, metrics: Dict[str, Any]) -> Dict[str, Any]:
        if metrics["panels_with_videos"] > 0:
            summary = f"当前分集已有 {metrics['panels_with_videos']} 个视频结果，可继续进入配音和复查。"
            return self._node_payload(
                step_key="video_generation",
                stage="VIDEO_GENERATION",
                status="waiting_confirmation",
                summary=summary,
                detail={"panels_with_videos": metrics["panels_with_videos"], "panels_without_videos": metrics["panels_without_videos"]},
                quality={"assessment": "视频结果已开始沉淀", "risk": "如果动作和情绪不到位，建议先重做关键镜头。"},
                recommended_actions=["继续音频生成", "重做视频结果", "切换更强动作模型"],
                adjustment_actions=["推荐模型", "提高镜头连贯性", "控制预算 / 灵感值"],
                next_stage="AUDIO_GENERATION",
                can_continue=True,
                needs_confirmation=True,
            )
        if metrics["panels_with_images"] <= 0:
            return self._node_payload(
                step_key="video_generation",
                stage="VIDEO_GENERATION",
                status="blocked",
                summary="当前分集还没有可用分镜图，暂时不能进入视频生成。",
                detail={"panels_with_videos": 0},
                quality={"assessment": "前置不足", "risk": "建议先完成图片生成。"},
                recommended_actions=["先完成图片生成"],
                next_stage="AUDIO_GENERATION",
                can_continue=False,
                needs_confirmation=True,
                blocked=True,
            )
        return self._node_payload(
            step_key="video_generation",
            stage="VIDEO_GENERATION",
            status="waiting_confirmation",
            summary=f"当前分集有 {metrics['panels_with_images']} 个镜头可进入视频生成，建议确认模型和镜头范围后正式提交。",
            detail={"panels_with_images": metrics["panels_with_images"], "panels_without_videos": metrics["panels_without_videos"]},
            quality={"assessment": "适合进入正式视频生成", "risk": "正式视频生成为高成本节点，建议先选重点镜头。"},
            recommended_actions=["确认正式生成视频", "先做重点镜头", "优化动作与模型再提交"],
            adjustment_actions=["推荐模型", "提高镜头连贯性", "控制预算 / 灵感值"],
            next_stage="AUDIO_GENERATION",
            can_continue=False,
            needs_confirmation=True,
            pending_confirmation={
                "assistant_action": self._assistant_action_for_step("video_generation", episode=episode),
                "label": "确认正式生成视频",
            },
        )

    def _result_for_audio_generation(self, *, script: Script, episode: Episode, metrics: Dict[str, Any]) -> Dict[str, Any]:
        if metrics["audio_completed"] > 0:
            summary = f"当前分集已有 {metrics['audio_completed']} 条音频结果，可继续进入最终复查。"
            return self._node_payload(
                step_key="audio_generation",
                stage="AUDIO_GENERATION",
                status="waiting_confirmation",
                summary=summary,
                detail={"audio_completed": metrics["audio_completed"]},
                quality={"assessment": "配音基础已建立", "risk": "若音色不统一，建议在复查阶段调整。"},
                recommended_actions=["继续最终复查", "补做配音", "优化音色策略"],
                adjustment_actions=["推荐模型", "统一角色风格", "控制预算 / 灵感值"],
                next_stage="REVIEW",
                can_continue=True,
                needs_confirmation=True,
            )
        text_available = bool((episode.source_text or "").strip() or metrics["panel_total"] > 0)
        if not text_available:
            return self._node_payload(
                step_key="audio_generation",
                stage="AUDIO_GENERATION",
                status="blocked",
                summary="当前分集缺少可用于配音的正文或分镜内容，暂时不能进入音频生成。",
                detail={"audio_completed": 0},
                quality={"assessment": "前置不足", "risk": "建议先补充正文或完成分镜。"},
                recommended_actions=["先补充正文", "先完成分镜"],
                next_stage="REVIEW",
                can_continue=False,
                needs_confirmation=True,
                blocked=True,
            )
        return self._node_payload(
            step_key="audio_generation",
            stage="AUDIO_GENERATION",
            status="waiting_confirmation",
            summary="音频生成已准备好：建议先确认音色和文本策略，再正式提交配音或旁白任务。",
            detail={"audio_completed": metrics["audio_completed"], "panel_total": metrics["panel_total"]},
            quality={"assessment": "适合进入正式音频生成", "risk": "正式音频生成属于高成本节点，建议先确认音色。"},
            recommended_actions=["确认正式配音", "先试听少量片段", "优化文本和音色"],
            adjustment_actions=["推荐模型", "控制预算 / 灵感值", "提高节奏感"],
            next_stage="REVIEW",
            can_continue=False,
            needs_confirmation=True,
            pending_confirmation={
                "assistant_action": self._assistant_action_for_step("audio_generation", episode=episode),
                "label": "确认正式配音",
            },
        )

    def _result_for_review(
        self,
        *,
        script: Script,
        episode: Episode,
        metrics: Dict[str, Any],
        instruction: Optional[str] = None,
    ) -> Dict[str, Any]:
        score = 0
        if metrics["resource_total"] > 0:
            score += 1
        if metrics["panel_total"] > 0:
            score += 1
        if metrics["panels_with_images"] > 0:
            score += 1
        if metrics["panels_with_videos"] > 0:
            score += 1
        if metrics["audio_completed"] > 0:
            score += 1
        summary = f"当前分集已完成 {score}/5 个关键制作要素，可以开始做最终复查与局部优化。"
        return self._node_payload(
            step_key="review_optimization",
            stage="REVIEW",
            status="waiting_confirmation",
            summary=summary,
            detail={"resource_counts": metrics["resource_counts"], "panel_total": metrics["panel_total"], "audio_completed": metrics["audio_completed"], "instruction": instruction or ""},
            quality={"assessment": "适合进入二次优化与成片整理", "risk": "若关键镜头还未稳定，建议先重做再收尾。"},
            recommended_actions=["重做薄弱镜头", "统一角色风格", "继续成片整理"],
            adjustment_actions=["优化提示词", "提高镜头连贯性", "统一角色风格"],
            next_stage="FINALIZE",
            can_continue=True,
            needs_confirmation=True,
        )

    def _result_from_existing_facts(self, *, script: Script, episode: Episode, step_key: str, metrics: Dict[str, Any]) -> Dict[str, Any]:
        if step_key == "asset_extraction":
            return self._result_for_asset_extraction(script=script, episode=episode, metrics=metrics)
        if step_key == "storyboarding":
            return self._result_for_storyboarding(script=script, episode=episode, metrics=metrics)
        if step_key == "image_generation":
            return self._result_for_image_generation(script=script, episode=episode, metrics=metrics)
        if step_key == "video_generation":
            return self._result_for_video_generation(script=script, episode=episode, metrics=metrics)
        if step_key == "audio_generation":
            return self._result_for_audio_generation(script=script, episode=episode, metrics=metrics)
        if step_key == "prompt_optimization":
            return self._result_for_prompt_optimization(script=script, episode=episode, metrics=metrics)
        return self._result_for_review(script=script, episode=episode, metrics=metrics)

    def _node_payload(
        self,
        *,
        step_key: str,
        stage: str,
        status: str,
        summary: str,
        detail: Dict[str, Any],
        quality: Dict[str, Any],
        recommended_actions: List[str],
        next_stage: str,
        can_continue: bool,
        needs_confirmation: bool,
        adjustment_actions: Optional[List[str]] = None,
        pending_confirmation: Optional[Dict[str, Any]] = None,
        blocked: bool = False,
    ) -> Dict[str, Any]:
        return {
            "step_key": step_key,
            "stage": stage,
            "status": status,
            "summary": {"title": STEP_LABELS.get(step_key, step_key), "summary": summary, "kind": step_key},
            "detail": detail,
            "quality": quality,
            "recommended_actions": recommended_actions,
            "adjustment_actions": adjustment_actions or [],
            "next_stage": next_stage,
            "can_continue": can_continue,
            "needs_confirmation": needs_confirmation,
            "pending_confirmation": pending_confirmation or {},
            "blocked": blocked,
            "refresh_hints": self._refresh_hints_for_step(step_key),
        }

    # ===== sync / derive =====
    def _sync_script_state(self, *, script: Script, state: ScriptWorkflowState) -> ScriptWorkflowState:
        state.updated_at = state.updated_at or _utc_now()
        return state

    def _sync_episode_state(self, *, script: Script, episode: Episode, state: EpisodeWorkflowState) -> EpisodeWorkflowState:
        metrics = self._episode_metrics(script=script, episode=episode)
        if EPISODE_STEP_KIND.get(state.current_step_key) == "assistant_execution" and self._is_execution_step_complete(state.current_step_key, metrics):
            result = self._result_from_existing_facts(script=script, episode=episode, step_key=state.current_step_key, metrics=metrics)
            self._apply_result_to_state(state, result, step_kind="assistant_execution", execution_completed=True)
        elif state.stage_status == "idle":
            state.stage_status = "ready"
            state.updated_at = _utc_now()
        return state

    def _episode_metrics(self, *, script: Script, episode: Episode) -> Dict[str, Any]:
        panels = self.session.exec(select(Panel).where(Panel.episode_id == episode.id)).all()
        resources = self.session.exec(select(SharedResource).where(SharedResource.script_id == script.id)).all()
        audio_records = self.session.exec(
            select(GenerationRecord).where(
                GenerationRecord.script_id == script.id,
                GenerationRecord.episode_id == episode.id,
                GenerationRecord.record_type == "audio",
                GenerationRecord.status.in_(["completed", "success"]),
            )
        ).all()
        resource_counts = {
            "characters": len([item for item in resources if item.resource_type == "character"]),
            "scenes": len([item for item in resources if item.resource_type == "scene"]),
            "props": len([item for item in resources if item.resource_type == "prop"]),
        }
        panels_with_images = len([item for item in panels if str(item.image_url or "").strip()])
        panels_with_videos = len([item for item in panels if str(item.video_url or "").strip()])
        return {
            "panel_total": len(panels),
            "panels_with_images": panels_with_images,
            "panels_without_images": max(0, len(panels) - panels_with_images),
            "panels_with_videos": panels_with_videos,
            "panels_without_videos": max(0, len(panels) - panels_with_videos),
            "resource_counts": resource_counts,
            "resource_total": sum(resource_counts.values()),
            "audio_completed": len(audio_records),
        }

    def _is_execution_step_complete(self, step_key: str, metrics: Dict[str, Any]) -> bool:
        if step_key == "asset_extraction":
            return metrics["resource_total"] > 0
        if step_key == "storyboarding":
            return metrics["panel_total"] > 0
        if step_key == "image_generation":
            return metrics["panels_with_images"] > 0
        if step_key == "video_generation":
            return metrics["panels_with_videos"] > 0
        if step_key == "audio_generation":
            return metrics["audio_completed"] > 0
        return False

    # ===== serialization =====
    def _serialize_script_workflow(
        self,
        *,
        script: Script,
        state: ScriptWorkflowState,
        episode_items: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return {
            "id": encode_id(state.id) if state.id else None,
            "script_id": encode_id(script.id),
            "current_stage": state.current_stage,
            "current_step_key": state.current_step_key,
            "current_step_label": STEP_LABELS.get(state.current_step_key, state.current_step_key),
            "stage_status": state.stage_status,
            "stage_status_label": _status_label(state.stage_status),
            "mode": state.mode,
            "pause_policy": state.pause_policy,
            "version": int(state.version or 1),
            "last_agent_run_at": state.last_agent_run_at.isoformat() if state.last_agent_run_at else None,
            "last_user_decision_at": state.last_user_decision_at.isoformat() if state.last_user_decision_at else None,
            "episodes": episode_items or [],
        }

    def _serialize_episode_workflow(self, *, script: Script, episode: Episode, state: EpisodeWorkflowState) -> Dict[str, Any]:
        return {
            "id": encode_id(state.id) if state.id else None,
            "script_id": encode_id(script.id),
            "episode_id": encode_id(episode.id),
            "episode_title": episode.title,
            "current_stage": state.current_stage,
            "current_step_key": state.current_step_key,
            "current_step_label": STEP_LABELS.get(state.current_step_key, state.current_step_key),
            "stage_status": state.stage_status,
            "stage_status_label": _status_label(state.stage_status),
            "mode": state.mode,
            "pause_policy": state.pause_policy,
            "version": int(state.version or 1),
            "last_agent_run_at": state.last_agent_run_at.isoformat() if state.last_agent_run_at else None,
            "last_user_decision_at": state.last_user_decision_at.isoformat() if state.last_user_decision_at else None,
        }

    def _build_script_current_node(self, *, script: Script, state: ScriptWorkflowState, episodes: List[Episode]) -> Dict[str, Any]:
        summary = _json_loads(state.result_summary_json, {})
        detail = _json_loads(state.result_detail_json, {})
        quality = _json_loads(state.quality_assessment_json, {})
        recommended = _json_loads(state.recommended_actions_json, [])
        adjustments = _json_loads(state.adjustment_actions_json, [])
        return {
            "scope": "script",
            "step_key": state.current_step_key,
            "step_label": STEP_LABELS.get(state.current_step_key, state.current_step_key),
            "stage": state.current_stage,
            "status": state.stage_status,
            "status_label": _status_label(state.stage_status),
            "summary": summary.get("summary") or "",
            "summary_title": summary.get("title") or STEP_LABELS.get(state.current_step_key, state.current_step_key),
            "detail": detail,
            "quality": quality,
            "recommended_actions": recommended,
            "adjustment_actions": adjustments,
            "next_stage": self._next_script_stage(state.current_step_key),
            "can_continue": state.stage_status in {"waiting_confirmation", "completed", "ready"},
            "needs_confirmation": True,
            "pending_confirmation": _json_loads(state.pending_confirmation_json, {}),
            "refresh_hints": self._refresh_hints_for_step(state.current_step_key),
            "next_recommendation": self._next_script_recommendation(episodes=episodes, current_step_key=state.current_step_key),
            "available_actions": self._build_available_actions(scope="script", state=state),
        }

    def _build_episode_current_node(self, *, script: Script, episode: Episode, state: EpisodeWorkflowState) -> Dict[str, Any]:
        summary = _json_loads(state.result_summary_json, {})
        detail = _json_loads(state.result_detail_json, {})
        quality = _json_loads(state.quality_assessment_json, {})
        recommended = _json_loads(state.recommended_actions_json, [])
        adjustments = _json_loads(state.adjustment_actions_json, [])
        pending_confirmation = _json_loads(state.pending_confirmation_json, {})
        assistant_action = pending_confirmation.get("assistant_action")
        return {
            "scope": "episode",
            "episode_id": encode_id(episode.id),
            "episode_title": episode.title,
            "step_key": state.current_step_key,
            "step_label": STEP_LABELS.get(state.current_step_key, state.current_step_key),
            "stage": state.current_stage,
            "status": state.stage_status,
            "status_label": _status_label(state.stage_status),
            "summary": summary.get("summary") or "",
            "summary_title": summary.get("title") or STEP_LABELS.get(state.current_step_key, state.current_step_key),
            "detail": detail,
            "quality": quality,
            "recommended_actions": recommended,
            "adjustment_actions": adjustments,
            "next_stage": self._next_episode_stage(state.current_step_key),
            "can_continue": self._can_move_forward_episode(script, episode, state),
            "needs_confirmation": True,
            "pending_confirmation": pending_confirmation,
            "assistant_action": assistant_action,
            "refresh_hints": self._refresh_hints_for_step(state.current_step_key),
            "next_recommendation": self._next_episode_recommendation(state.current_step_key),
            "available_actions": self._build_available_actions(scope="episode", state=state),
        }

    def _build_available_actions(
        self,
        *,
        scope: str,
        state: ScriptWorkflowState | EpisodeWorkflowState,
    ) -> List[Dict[str, Any]]:
        actions: List[Dict[str, Any]] = []
        if scope == "script":
            actions.append({"id": "advance", "label": "继续下一步", "kind": "advance", "primary": True})
            return actions

        actions.append({"id": "redo", "label": "重做", "kind": "redo", "primary": False})
        actions.append({"id": "adjust", "label": "修改后再生成", "kind": "adjust", "primary": False})
        actions.append({"id": "advance", "label": "继续下一步", "kind": "advance", "primary": True})
        actions.append({"id": "optimize", "label": "优化本环节", "kind": "optimize", "primary": False})
        actions.append({"id": "view_detail", "label": "查看详细参数", "kind": "view_detail", "primary": False})
        pending_confirmation = _json_loads(state.pending_confirmation_json, {})
        if pending_confirmation.get("assistant_action"):
            actions.append({"id": "confirm", "label": pending_confirmation.get("label") or "确认执行", "kind": "confirm", "primary": True})
        return actions

    def _recent_results(self, *, state: ScriptWorkflowState | EpisodeWorkflowState) -> List[Dict[str, Any]]:
        history = _json_loads(state.history_versions_json, [])
        return list(reversed(history[-5:]))

    # ===== helpers =====
    def _advance_script_state_to_step(self, state: ScriptWorkflowState, step_key: str) -> None:
        for stage, key in SCRIPT_STEPS:
            if key == step_key:
                state.current_stage = stage
                state.current_step_key = key
                state.stage_status = "ready"
                state.pending_confirmation_json = "{}"
                return

    def _advance_episode_state_to_step(self, state: EpisodeWorkflowState, step_key: str) -> None:
        for stage, key in EPISODE_STEPS:
            if key == step_key:
                state.current_stage = stage
                state.current_step_key = key
                state.stage_status = "ready"
                state.pending_confirmation_json = "{}"
                return

    def _next_script_step_key(self, current_step_key: str) -> str:
        keys = [item[1] for item in SCRIPT_STEPS]
        try:
            index = keys.index(current_step_key)
        except ValueError:
            return keys[0]
        return keys[min(index + 1, len(keys) - 1)]

    def _next_episode_step_key(self, current_step_key: str) -> str:
        keys = [item[1] for item in EPISODE_STEPS]
        try:
            index = keys.index(current_step_key)
        except ValueError:
            return keys[0]
        return keys[min(index + 1, len(keys) - 1)]

    def _next_script_stage(self, current_step_key: str) -> str:
        next_key = self._next_script_step_key(current_step_key)
        for stage, key in SCRIPT_STEPS:
            if key == next_key:
                return stage
        return "EPISODE_SPLITTING"

    def _next_episode_stage(self, current_step_key: str) -> str:
        next_key = self._next_episode_step_key(current_step_key)
        for stage, key in EPISODE_STEPS:
            if key == next_key:
                return stage
        return "REVIEW"

    def _can_move_forward_script(self, state: ScriptWorkflowState) -> bool:
        return state.stage_status in {"waiting_confirmation", "completed", "ready"}

    def _can_move_forward_episode(self, script: Script, episode: Episode, state: EpisodeWorkflowState) -> bool:
        step_kind = EPISODE_STEP_KIND.get(state.current_step_key)
        if step_kind == "assistant_execution":
            metrics = self._episode_metrics(script=script, episode=episode)
            return self._is_execution_step_complete(state.current_step_key, metrics)
        return state.stage_status in {"waiting_confirmation", "completed", "ready"}

    def _next_script_recommendation(self, *, episodes: List[Episode], current_step_key: str) -> str:
        if current_step_key == "episode_splitting" and episodes:
            return f"下一步建议先进入「{episodes[0].title}」做资产提取和分镜生产。"
        return "你可以继续推进下一步，也可以先在当前阶段做调优。"

    def _next_episode_recommendation(self, current_step_key: str) -> str:
        mapping = {
            "asset_extraction": "建议先建立角色和场景资产，再进入分镜拆分。",
            "storyboarding": "建议先把剧情转成镜头语言，再做提示词和模型推荐。",
            "prompt_optimization": "建议先确认模型策略，再进入正式生成。",
            "image_generation": "建议先做小批量试跑，再决定是否正式批量出图。",
            "video_generation": "建议优先处理关键镜头，再逐步扩到整集。",
            "audio_generation": "建议先统一音色策略，再进入最终复查。",
            "review_optimization": "建议把薄弱镜头重做后，再做成片整理。",
        }
        return mapping.get(current_step_key, "你可以继续推进下一步，也可以先在当前阶段做调优。")

    def _assistant_action_for_step(self, step_key: str, *, episode: Episode) -> Optional[Dict[str, Any]]:
        command = STEP_ASSISTANT_ACTION.get(step_key)
        if not command:
            return None
        return {
            "content": command,
            "target": "internal",
            "episode_id": encode_id(episode.id),
        }

    def _refresh_hints_for_step(self, step_key: str) -> Dict[str, bool]:
        mapping = {
            "asset_extraction": {"resources": True},
            "storyboarding": {"panels": True},
            "prompt_optimization": {"panels": True},
            "image_generation": {"panels": True},
            "video_generation": {"panels": True},
            "audio_generation": {"panels": True},
            "review_optimization": {"panels": True, "resources": True},
        }
        return mapping.get(step_key, {"script_source": True})
