from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session

from models import Episode, Panel, Script, SharedResource, SharedResourceVersion, Team


def get_script_or_404(session: Session, script_id: int) -> Script:
    script = session.get(Script, script_id)
    if not script:
        raise HTTPException(status_code=404, detail="剧本不存在")
    return script


def get_episode_or_404(session: Session, episode_id: int) -> Episode:
    episode = session.get(Episode, episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="剧集不存在")
    return episode


def get_panel_or_404(session: Session, panel_id: int) -> Panel:
    panel = session.get(Panel, panel_id)
    if not panel:
        raise HTTPException(status_code=404, detail="分镜不存在")
    return panel


def require_script_team_access(session: Session, team: Team, script_id: int) -> Script:
    script = get_script_or_404(session, script_id)
    if script.team_id != team.id:
        raise HTTPException(status_code=403, detail="无权限访问该剧本")
    return script


def require_episode_team_access(session: Session, team: Team, episode_id: int) -> Episode:
    episode = get_episode_or_404(session, episode_id)
    require_script_team_access(session, team, episode.script_id)
    return episode


def require_panel_team_access(session: Session, team: Team, panel_id: int) -> Panel:
    panel = get_panel_or_404(session, panel_id)
    require_episode_team_access(session, team, panel.episode_id)
    return panel


def require_resource_team_access(session: Session, team: Team, resource_id: int) -> SharedResource:
    resource = session.get(SharedResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="资产不存在")
    require_script_team_access(session, team, resource.script_id)
    return resource


def require_resource_version_team_access(session: Session, team: Team, version_id: int) -> SharedResourceVersion:
    version = session.get(SharedResourceVersion, version_id)
    if not version:
        raise HTTPException(status_code=404, detail="资产版本不存在")
    require_resource_team_access(session, team, version.resource_id)
    return version
