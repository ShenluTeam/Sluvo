import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from core.security import decode_id
from database import get_session, session_scope
from dependencies import get_current_team, get_current_user
from models import Team, TeamMemberLink, User
from schemas import (
    AssistantAgentActionRequest,
    AssistantBridgeImportRequest,
    AssistantBridgeLinkRequest,
    AssistantMessageSendRequest,
    AssistantQuestionAnswerRequest,
    AssistantSessionCreateRequest,
    AssistantSessionUpdateRequest,
)
from services.access_service import require_script_team_access
from services.assistant_runtime import AssistantRuntimeService, assistant_runtime_event_manager
from services.assistant_runtime.task_read_model import list_script_tasks, retry_script_task

router = APIRouter()
logger = logging.getLogger(__name__)


def _model_to_dict(model: Any, **kwargs) -> Dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(**kwargs)
    if hasattr(model, "dict"):
        return model.dict(**kwargs)
    return dict(model or {})


def _resolve_optional_id(encoded_id: Optional[str]) -> Optional[int]:
    if not encoded_id:
        return None
    return decode_id(encoded_id)


def _resolve_stream_user(session: Session, token: Optional[str], authorization: Optional[str]) -> User:
    auth_token = token
    if not auth_token and authorization:
        auth_token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization
    if not auth_token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")

    user = session.exec(select(User).where(User.session_token == auth_token)).first()
    if not user:
        raise HTTPException(status_code=401, detail="登录已过期，请重新登录")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账号已被禁用")
    return user


def _resolve_stream_team(session: Session, user: User) -> Team:
    link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user.id)).first()
    if not link:
        raise HTTPException(status_code=403, detail="当前账号未加入任何团队")
    team = session.get(Team, link.team_id)
    if not team:
        raise HTTPException(status_code=404, detail="团队不存在")
    return team


def _load_script_tasks_snapshot(script_id: int, user_id: int, active_only: bool, limit: int) -> Dict[str, Any]:
    with session_scope() as db_session:
        user = db_session.get(User, user_id)
        if not user:
            return {"tasks": []}
        return {
            "tasks": list_script_tasks(
                db_session,
                user=user,
                script_id=script_id,
                active_only=active_only,
                limit=limit,
            )
        }


@router.get("/scripts/{script_id}/sessions")
def list_assistant_sessions(
    script_id: str,
    channel: Optional[str] = None,
    profile: Optional[str] = None,
    user: User = Depends(get_current_user),
    team=Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    return {
        "success": True,
        "data": service.list_script_sessions(
            user=user,
            team=team,
            script_id=decode_id(script_id),
            channel=channel,
            profile=profile,
        ),
    }


@router.post("/scripts/{script_id}/sessions")
def create_assistant_session(
    script_id: str,
    payload: AssistantSessionCreateRequest,
    user: User = Depends(get_current_user),
    team=Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.create_session(
        user=user,
        team=team,
        script_id=decode_id(script_id),
        episode_id=_resolve_optional_id(payload.episode_id),
        title=payload.title,
        channel=payload.channel,
        profile=payload.profile,
        linked_external_session_id=_resolve_optional_id(payload.linked_external_session_id),
    )
    return {"success": True, "data": service.get_snapshot(session_obj=item)}


@router.get("/scripts/{script_id}/skills")
def list_assistant_skills(
    script_id: str,
    user: User = Depends(get_current_user),
    team=Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    return {
        "success": True,
        "data": service.list_skills(
            user=user,
            team=team,
            script_id=decode_id(script_id),
        ),
    }


@router.get("/scripts/{script_id}/tasks")
def list_assistant_tasks(
    script_id: str,
    active_only: bool = True,
    limit: int = 20,
    user: User = Depends(get_current_user),
    team=Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_script_id = decode_id(script_id)
    require_script_team_access(session, team, real_script_id)
    return {
        "success": True,
        "data": {
            "tasks": list_script_tasks(
                session,
                user=user,
                script_id=real_script_id,
                active_only=active_only,
                limit=max(1, min(limit, 100)),
            )
        },
    }


@router.post("/scripts/{script_id}/tasks/{task_id}/retry")
def retry_assistant_task(
    script_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    team=Depends(get_current_team),
    session: Session = Depends(get_session),
):
    real_script_id = decode_id(script_id)
    require_script_team_access(session, team, real_script_id)
    try:
        task = retry_script_task(
            session,
            user=user,
            team=team,
            script_id=real_script_id,
            task_id=task_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "data": {"task": task}}


@router.get("/sessions/{session_id}")
def get_assistant_session(
    session_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    return {"success": True, "data": service.get_snapshot(session_obj=item)}


@router.patch("/sessions/{session_id}")
def update_assistant_session(
    session_id: str,
    payload: AssistantSessionUpdateRequest,
    user: User = Depends(get_current_user),
    team=Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    item = service.update_session_context(
        session_obj=item,
        user=user,
        team=team,
        episode_id=_resolve_optional_id(payload.episode_id),
        automation_mode=payload.automation_mode,
    )
    return {"success": True, "data": service.get_snapshot(session_obj=item)}


@router.get("/sessions/{session_id}/snapshot")
def get_assistant_snapshot(
    session_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    return {"success": True, "data": service.get_snapshot(session_obj=item)}


@router.delete("/sessions/{session_id}")
def delete_assistant_session(
    session_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    service.delete_session(session_obj=item)
    return {"success": True, "data": {"deleted": True}}


@router.post("/sessions/{session_id}/messages")
def send_assistant_message(
    session_id: str,
    payload: AssistantMessageSendRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    result = service.start_message(
        session_obj=item,
        user=user,
        content=payload.content,
        context=payload.context,
        target=payload.target,
        attachments=[_model_to_dict(attachment) for attachment in payload.attachments],
        async_mode=True,
    )
    return {"success": True, "data": result}


@router.post("/sessions/{session_id}/agent-actions")
def execute_assistant_agent_action(
    session_id: str,
    payload: AssistantAgentActionRequest,
    user: User = Depends(get_current_user),
    team=Depends(get_current_team),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    try:
        result = service.execute_agent_action(
            session_obj=item,
            user=user,
            team=team,
            action_type=payload.action_type,
            payload=payload.payload,
        )
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.exception("assistant agent action failed: session_id=%s action=%s", session_id, payload.action_type)
        raise HTTPException(status_code=500, detail=str(exc) or "assistant agent action failed")
    return {"success": True, "data": result}


@router.post("/sessions/{session_id}/interrupt")
def interrupt_assistant_session(
    session_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    return {"success": True, "data": service.interrupt_session(session_obj=item)}


@router.post("/sessions/{session_id}/questions/{question_id}/answer")
def answer_assistant_question(
    session_id: str,
    question_id: str,
    payload: AssistantQuestionAnswerRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    result = service.answer_question(
        session_obj=item,
        user=user,
        question_key=question_id,
        action=payload.action,
        answer=payload.answer,
        modifications=payload.modifications,
        answers=payload.answers,
    )
    return {"success": True, "data": result}


@router.post("/sessions/{session_id}/bridge/link")
def link_assistant_bridge(
    session_id: str,
    payload: AssistantBridgeLinkRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    bridge_state = service.link_bridge(
        session_obj=item,
        user=user,
        external_session_id=_resolve_optional_id(payload.external_session_id),
    )
    return {"success": True, "data": bridge_state}


@router.post("/sessions/{session_id}/bridge/unlink")
def unlink_assistant_bridge(
    session_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    return {"success": True, "data": service.unlink_bridge(session_obj=item)}


@router.get("/sessions/{session_id}/bridge/state")
def get_assistant_bridge_state(
    session_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    return {"success": True, "data": service.get_bridge_state(session_obj=item)}


@router.post("/sessions/{session_id}/bridge/imports")
def request_assistant_bridge_import(
    session_id: str,
    payload: AssistantBridgeImportRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    service = AssistantRuntimeService(session)
    item = service.require_session(session_id=decode_id(session_id), user=user)
    result = service.request_bridge_import(
        session_obj=item,
        user=user,
        import_type=payload.import_type,
        mode=payload.mode,
        episode_id=_resolve_optional_id(payload.episode_id),
        name=payload.name,
        external_session_id=_resolve_optional_id(payload.external_session_id),
    )
    return {"success": True, "data": result}


@router.get("/sessions/{session_id}/stream")
async def stream_assistant_session(
    session_id: str,
    since_event_id: Optional[int] = None,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
    last_event_id: Optional[str] = Header(None, alias="Last-Event-ID"),
):
    with session_scope() as stream_session:
        user = _resolve_stream_user(stream_session, token, authorization)
        service = AssistantRuntimeService(stream_session)
        item = service.require_session(session_id=decode_id(session_id), user=user)
        try:
            initial_snapshot = service.get_snapshot(session_obj=item)
            initial_error = None
        except Exception as exc:
            initial_snapshot = None
            initial_error = str(exc)
    session_key = session_id

    async def event_generator():
        queue = assistant_runtime_event_manager.subscribe(session_key)
        loop = asyncio.get_event_loop()
        try:
            if initial_error:
                yield "event: status\ndata: {0}\n\n".format(
                    json.dumps(
                        {"type": "status", "status": "error", "detail": initial_error},
                        ensure_ascii=False,
                    )
                )
                return
            if initial_snapshot is not None:
                yield "event: snapshot\ndata: {0}\n\n".format(
                    json.dumps({"type": "snapshot", "snapshot": initial_snapshot}, ensure_ascii=False)
                )

            cursor = None
            try:
                cursor = int(str(last_event_id or "").strip()) if str(last_event_id or "").strip() else None
            except ValueError:
                cursor = None
            if cursor is None:
                cursor = since_event_id
            if cursor is not None:
                replay_events = assistant_runtime_event_manager.get_events_since(session_key, cursor)
                for replay_event in replay_events:
                    replay_type = str(replay_event.get("type") or "patch")
                    if replay_type == "snapshot":
                        continue
                    replay_id = replay_event.get("event_id")
                    if replay_id is not None:
                        yield "id: {0}\n".format(replay_id)
                    yield "event: {0}\ndata: {1}\n\n".format(
                        replay_type,
                        json.dumps(replay_event, ensure_ascii=False, default=str),
                    )

            while True:
                try:
                    event = await loop.run_in_executor(
                        None,
                        assistant_runtime_event_manager.get_event,
                        queue,
                        10.0,
                    )
                    if event is None:
                        yield "event: heartbeat\ndata: {0}\n\n".format(
                            json.dumps({"type": "heartbeat"}, ensure_ascii=False)
                        )
                        continue

                    event_type = str(event.get("type") or "patch")
                    event_id_value = event.get("event_id")
                    if event_id_value is not None:
                        yield "id: {0}\n".format(event_id_value)
                    yield "event: {0}\ndata: {1}\n\n".format(
                        event_type,
                        json.dumps(event, ensure_ascii=False, default=str),
                    )
                except Exception as exc:
                    yield "event: status\ndata: {0}\n\n".format(
                        json.dumps(
                            {"type": "status", "status": "error", "detail": str(exc)},
                            ensure_ascii=False,
                        )
                    )
                    return
        finally:
            assistant_runtime_event_manager.unsubscribe(session_key, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/scripts/{script_id}/tasks/stream")
async def stream_assistant_tasks(
    script_id: str,
    active_only: bool = True,
    limit: int = 20,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    real_script_id = decode_id(script_id)
    safe_limit = max(1, min(limit, 100))
    with session_scope() as stream_session:
        user = _resolve_stream_user(stream_session, token, authorization)
        team = _resolve_stream_team(stream_session, user)
        require_script_team_access(stream_session, team, real_script_id)
        user_id = int(user.id)
    initial = _load_script_tasks_snapshot(real_script_id, user_id, active_only, safe_limit)

    async def event_generator():
        loop = asyncio.get_event_loop()
        previous_tasks = {
            str(task.get("task_id") or ""): task
            for task in (initial.get("tasks") or [])
        }
        yield "event: snapshot\ndata: {0}\n\n".format(
            json.dumps({"type": "snapshot", "tasks": list(previous_tasks.values())}, ensure_ascii=False, default=str)
        )

        while True:
            await asyncio.sleep(3)
            snapshot = await loop.run_in_executor(
                None,
                lambda: _load_script_tasks_snapshot(real_script_id, user_id, active_only, safe_limit),
            )
            tasks = snapshot.get("tasks") or []
            current_tasks = {str(task.get("task_id") or ""): task for task in tasks}
            changed = False

            for task_id_key, task in current_tasks.items():
                if previous_tasks.get(task_id_key) != task:
                    changed = True
                    yield "event: task\ndata: {0}\n\n".format(
                        json.dumps({"type": "task", "task": task}, ensure_ascii=False, default=str)
                    )

            for task_id_key in previous_tasks.keys():
                if task_id_key not in current_tasks:
                    changed = True
                    yield "event: task\ndata: {0}\n\n".format(
                        json.dumps(
                            {"type": "task", "task": {"task_id": task_id_key, "removed": True}},
                            ensure_ascii=False,
                            default=str,
                        )
                    )

            if changed:
                previous_tasks = current_tasks
                yield "event: snapshot\ndata: {0}\n\n".format(
                    json.dumps({"type": "snapshot", "tasks": tasks}, ensure_ascii=False, default=str)
                )
            else:
                yield "event: heartbeat\ndata: {0}\n\n".format(
                    json.dumps({"type": "heartbeat"}, ensure_ascii=False)
                )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
