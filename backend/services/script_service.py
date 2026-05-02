from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlmodel import Session, select

from models import Episode, Script, Team
from services.access_service import require_script_team_access
from services.agent_workflow_service import AgentWorkflowService
from services.delete_cleanup_service import cleanup_script_dependencies
from services.workflow_preset_service import (
    get_style_display_label,
    resolve_default_storyboard_mode,
    resolve_effective_workflow_profile,
    workflow_settings_to_json,
)


def create_script(
    session: Session,
    team: Team,
    name: str,
    description: str | None,
    aspect_ratio: str,
    style_preset: str,
    default_storyboard_mode: str = "commentary",
    workflow_settings_json: dict | None = None,
) -> Script:
    now = datetime.utcnow()
    workflow_settings_value = workflow_settings_to_json(
        workflow_settings_json,
        legacy_aspect_ratio=aspect_ratio,
        legacy_style_preset=style_preset,
        default_storyboard_mode=default_storyboard_mode,
    )
    new_script = Script(
        name=name,
        description=description,
        aspect_ratio=aspect_ratio,
        style_preset=style_preset,
        workflow_settings_json=workflow_settings_value,
        team_id=team.id,
        updated_at=now,
    )
    default_profile = resolve_effective_workflow_profile(new_script, storyboard_mode=default_storyboard_mode)
    new_script.aspect_ratio = default_profile["aspect_ratio"]
    new_script.style_preset = get_style_display_label(default_profile.get("style"), style_preset)

    first_episode = Episode(
        title="第1集",
        sequence_num=1,
        storyboard_mode=default_storyboard_mode,
        updated_at=now,
    )
    new_script.episodes.append(first_episode)
    session.add(new_script)
    session.commit()
    session.refresh(new_script)
    AgentWorkflowService(session).ensure_script_states(script=new_script)
    session.commit()
    return new_script


def list_scripts(session: Session, team: Team):
    statement = (
        select(Script)
        .where(Script.team_id == team.id)
        .order_by(func.coalesce(Script.last_accessed_at, Script.created_at).desc())
    )
    return session.exec(statement).all()


def update_script(
    session: Session,
    team: Team,
    script_id: int,
    *,
    aspect_ratio: str | None,
    style_preset: str | None,
    default_storyboard_mode: str | None = None,
    workflow_settings_json: dict | None = None,
) -> Script:
    script = require_script_team_access(session, team, script_id)
    previous_default_storyboard_mode = resolve_default_storyboard_mode(script)
    if aspect_ratio is not None or style_preset is not None or workflow_settings_json is not None or default_storyboard_mode is not None:
        script.workflow_settings_json = workflow_settings_to_json(
            workflow_settings_json if workflow_settings_json is not None else script.workflow_settings_json,
            legacy_aspect_ratio=aspect_ratio or script.aspect_ratio,
            legacy_style_preset=style_preset or script.style_preset,
            default_storyboard_mode=default_storyboard_mode,
        )
        default_profile = resolve_effective_workflow_profile(script, storyboard_mode=default_storyboard_mode)
        script.aspect_ratio = default_profile["aspect_ratio"]
        script.style_preset = get_style_display_label(default_profile.get("style"), style_preset or script.style_preset)
        next_default_storyboard_mode = resolve_default_storyboard_mode(script)
        if next_default_storyboard_mode != previous_default_storyboard_mode:
            episodes = session.exec(select(Episode).where(Episode.script_id == script.id)).all()
            for episode in episodes:
                if str(getattr(episode, "storyboard_mode", "") or "").strip().lower() == previous_default_storyboard_mode:
                    episode.storyboard_mode = next_default_storyboard_mode
                    episode.updated_at = datetime.utcnow()
                    session.add(episode)
    script.updated_at = datetime.utcnow()
    session.add(script)
    session.commit()
    session.refresh(script)
    AgentWorkflowService(session).ensure_script_states(script=script)
    session.commit()
    return script


def delete_script(session: Session, team: Team, script_id: int) -> None:
    script = require_script_team_access(session, team, script_id)
    cleanup_script_dependencies(session, script.id)
    session.delete(script)
    session.commit()
