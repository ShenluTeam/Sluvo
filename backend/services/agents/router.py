from __future__ import annotations

from typing import Any, Dict, Optional

from sqlmodel import Session

from services.agent_stage_service import STAGE_AGENT_MAP, build_creative_stage_read_model_from_facts
from services.workflow_preset_service import resolve_effective_workflow_profile

from .asset_planner_agent import AssetPlannerAgent
from .context_builder import build_agent_specific_context, build_workspace_facts
from .director_agent import DirectorAgent
from .generation_agent import GenerationAgent
from .prompt_rewrite_agent import PromptRewriteAgent
from .storyboard_agent import StoryboardAgent


AGENT_CLASS_MAP = {
    "director_agent": DirectorAgent,
    "asset_planner_agent": AssetPlannerAgent,
    "storyboard_agent": StoryboardAgent,
    "generation_agent": GenerationAgent,
    "prompt_rewrite_agent": PromptRewriteAgent,
}

ACTION_AGENT_MAP = {
    "save_script": "director_agent",
    "rewrite_script": "director_agent",
    "extract_assets": "asset_planner_agent",
    "save_assets": "asset_planner_agent",
    "save_storyboard": "storyboard_agent",
    "generate_asset_images": "generation_agent",
    "generate_storyboard_images": "generation_agent",
    "generate_video": "generation_agent",
    "rewrite_generation_prompts": "prompt_rewrite_agent",
}


def build_agent_context(
    session: Session,
    *,
    user,
    team,
    script,
    episode=None,
    latest_user_message: str = "",
    conversation_history: Optional[list[dict[str, Any]]] = None,
    workflow: Optional[Dict[str, Any]] = None,
    page_context: Optional[Dict[str, Any]] = None,
    latest_artifacts: Optional[Dict[str, Any]] = None,
    explicit_action_intent: Optional[Dict[str, Any]] = None,
    stream_callback=None,
    runtime_event_callback=None,
    now=None,
) -> Dict[str, Any]:
    workspace_facts = build_workspace_facts(session, script=script, episode=episode)
    stage_read_model = build_creative_stage_read_model_from_facts(
        script=script,
        episode=episode,
        workspace_facts=workspace_facts,
    )
    active_agent = stage_read_model["active_agent"]
    workflow_profile = resolve_effective_workflow_profile(
        script,
        episode=episode,
        storyboard_mode=getattr(episode, "storyboard_mode", None) if episode is not None else None,
    )
    available_actions = [
        {"type": key, "label": key}
        for key, agent_name in ACTION_AGENT_MAP.items()
        if agent_name == active_agent
    ]
    base_context = {
        "creative_stage": stage_read_model["creative_stage"],
        "creative_stage_label": stage_read_model["creative_stage_label"],
        "latest_user_message": latest_user_message,
        "available_actions": available_actions,
    }
    agent_context = build_agent_specific_context(
        agent_name=active_agent,
        base_context=base_context,
        workspace_facts=workspace_facts,
        latest_artifacts=latest_artifacts,
        workflow_profile=workflow_profile,
    )
    current_script = str(workspace_facts.get("current_script") or "").strip()
    return {
        "session": session,
        "user": user,
        "team": team,
        "script": script,
        "episode": episode,
        "script_id": script.id,
        "episode_id": episode.id if episode else None,
        "creative_stage": stage_read_model["creative_stage"],
        "creative_stage_label": stage_read_model["creative_stage_label"],
        "latest_user_message": latest_user_message,
        "current_script": current_script,
        "conversation_history": conversation_history or [],
        "workflow": workflow or {},
        "page_context": page_context or {},
        "stage_read_model": stage_read_model,
        "workflow_profile": workflow_profile,
        "latest_artifacts": latest_artifacts or {},
        "explicit_action_intent": explicit_action_intent or {},
        "available_actions": available_actions,
        "agent_context_preview": agent_context,
        "workspace_facts_preview": workspace_facts,
        "stream_callback": stream_callback,
        "runtime_event_callback": runtime_event_callback,
        "now": now,
    }


def resolve_active_agent_name(context: Dict[str, Any]) -> str:
    return STAGE_AGENT_MAP.get(context.get("creative_stage"), "director_agent")


def create_agent(agent_name: str, session: Session):
    agent_cls = AGENT_CLASS_MAP.get(agent_name, DirectorAgent)
    return agent_cls(session)


def run_active_agent(context: Dict[str, Any]) -> Dict[str, Any]:
    agent_name = resolve_active_agent_name(context)
    return create_agent(agent_name, context["session"]).run(context)


def execute_agent_action(context: Dict[str, Any], action_type: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    agent_name = ACTION_AGENT_MAP.get(action_type) or resolve_active_agent_name(context)
    return create_agent(agent_name, context["session"]).execute_action(context, action_type, payload=payload or {})
