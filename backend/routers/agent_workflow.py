from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlmodel import Session

from core.security import decode_id
from database import get_session
from dependencies import get_current_team, get_current_user, require_team_permission
from models import Team, TeamMemberLink, User
from schemas import AgentWorkflowConfirmRequest, AgentWorkflowMutationRequest
from services.agent_workflow_service import AgentWorkflowService

router = APIRouter()


@router.get("/api/agent-workflow/scripts/{script_id}")
def get_script_workflow(
    script_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AgentWorkflowService(session)
    return {"success": True, "data": service.get_script_workflow_read_model(user=user, team=team, script_id=decode_id(script_id))}


@router.get("/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}")
def get_episode_workflow(
    script_id: str,
    episode_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:read")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AgentWorkflowService(session)
    return {
        "success": True,
        "data": service.get_episode_workflow_read_model(
            user=user,
            team=team,
            script_id=decode_id(script_id),
            episode_id=decode_id(episode_id),
        ),
    }


@router.post("/api/agent-workflow/scripts/{script_id}/advance")
def advance_script_workflow(
    script_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AgentWorkflowService(session)
    return {"success": True, "data": service.advance_script_workflow(user=user, team=team, script_id=decode_id(script_id))}


@router.post("/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/advance")
def advance_episode_workflow(
    script_id: str,
    episode_id: str,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AgentWorkflowService(session)
    return {
        "success": True,
        "data": service.advance_episode_workflow(
            user=user,
            team=team,
            script_id=decode_id(script_id),
            episode_id=decode_id(episode_id),
        ),
    }


@router.post("/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/redo")
def redo_episode_workflow(
    script_id: str,
    episode_id: str,
    payload: AgentWorkflowMutationRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AgentWorkflowService(session)
    return {
        "success": True,
        "data": service.redo_episode_workflow(
            user=user,
            team=team,
            script_id=decode_id(script_id),
            episode_id=decode_id(episode_id),
            instruction=payload.instruction,
        ),
    }


@router.post("/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/adjust")
def adjust_episode_workflow(
    script_id: str,
    episode_id: str,
    payload: AgentWorkflowMutationRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AgentWorkflowService(session)
    return {
        "success": True,
        "data": service.adjust_episode_workflow(
            user=user,
            team=team,
            script_id=decode_id(script_id),
            episode_id=decode_id(episode_id),
            instruction=payload.instruction,
        ),
    }


@router.post("/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/optimize")
def optimize_episode_workflow(
    script_id: str,
    episode_id: str,
    payload: AgentWorkflowMutationRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AgentWorkflowService(session)
    return {
        "success": True,
        "data": service.optimize_episode_workflow(
            user=user,
            team=team,
            script_id=decode_id(script_id),
            episode_id=decode_id(episode_id),
            instruction=payload.instruction,
        ),
    }


@router.post("/api/agent-workflow/scripts/{script_id}/episodes/{episode_id}/confirm")
def confirm_episode_workflow(
    script_id: str,
    episode_id: str,
    payload: AgentWorkflowConfirmRequest,
    _: TeamMemberLink = Depends(require_team_permission("project:write")),
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AgentWorkflowService(session)
    return {
        "success": True,
        "data": service.confirm_episode_workflow(
            user=user,
            team=team,
            script_id=decode_id(script_id),
            episode_id=decode_id(episode_id),
            action=payload.action,
            instruction=payload.instruction,
        ),
    }
