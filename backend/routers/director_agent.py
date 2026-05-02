"""
神鹿AI导演 Agent 路由

提供创建会话、发送消息、确认动作等接口。
"""

import asyncio
import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from core.security import decode_id, encode_id
from database import get_session as get_db_session, session_scope
from dependencies import get_current_team, get_current_user
from models import DirectorAgentSession, DirectorAgentMessage, User, Team
from schemas import (
    DirectorAgentSessionCreateRequest,
    DirectorAgentMessageSendRequest,
    DirectorAgentMessageConfirmRequest,
)
from services.director_agent_service import DirectorAgentService

router = APIRouter()

# SSE event types
SSE_EVENT_AGENT_MESSAGE = "agent_message"
SSE_EVENT_SESSION_UPDATE = "session_update"
SSE_EVENT_ERROR = "error"
SSE_EVENT_HEARTBEAT = "heartbeat"


def _encode_session_id(id: int) -> str:
    """编码会话ID"""
    return encode_id(id)


def _decode_session_id(encoded_id: str) -> int:
    """解码会话ID"""
    return decode_id(encoded_id)


def _encode_message_id(id: int) -> str:
    """编码消息ID"""
    return encode_id(id)


def _decode_message_id(encoded_id: str) -> int:
    """解码消息ID"""
    return decode_id(encoded_id)


def _format_session(session: DirectorAgentSession) -> Dict[str, Any]:
    """格式化会话响应"""
    import json

    context = json.loads(session.context_snapshot_json or "{}")

    return {
        "id": _encode_session_id(session.id),
        "script_id": encode_id(session.script_id),
        "episode_id": encode_id(session.episode_id) if session.episode_id else None,
        "agent_name": session.agent_name,
        "status": session.status,
        "title": session.title,
        "context": context,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def _format_message(message: DirectorAgentMessage) -> Dict[str, Any]:
    """格式化消息响应"""
    import json

    payload = json.loads(message.payload_json or "{}")
    execution_result = json.loads(message.execution_result_json or "{}")

    return {
        "id": _encode_message_id(message.id),
        "session_id": _encode_session_id(message.session_id),
        "role": message.role,
        "content": message.content,
        "message_type": message.message_type,
        "payload": payload,
        "task_type": message.task_type,
        "task_status": message.task_status,
        "requires_confirmation": message.requires_confirmation,
        "confirmation_status": message.confirmation_status,
        "confirmed_at": message.confirmed_at.isoformat() if message.confirmed_at else None,
        "execution_result": execution_result,
        "agent_name": message.agent_name,
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


@router.post("/sessions")
def create_session(
    request: DirectorAgentSessionCreateRequest,
    user: User = Depends(get_current_user),
    team: Team = Depends(get_current_team),
    session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    创建AI导演会话

    创建一个新的会话用于与AI导演对话。
    """
    service = DirectorAgentService(session)

    # 解码ID
    script_id = decode_id(request.script_id)
    episode_id = decode_id(request.episode_id) if request.episode_id else None

    # 验证权限
    from services.access_service import require_script_team_access
    require_script_team_access(session, team, script_id)

    session_obj = service.create_session(
        user=user,
        script_id=script_id,
        episode_id=episode_id,
        title=request.title
    )

    return {
        "success": True,
        "data": _format_session(session_obj)
    }


@router.get("/sessions/{session_id}")
def get_session_detail(
    session_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    获取会话详情

    包括会话信息和消息列表。
    """
    service = DirectorAgentService(session)

    # 解码ID
    decoded_session_id = _decode_session_id(session_id)

    session_obj = service.get_session(decoded_session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 验证权限
    if session_obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    # 获取消息
    messages = service.get_session_messages(decoded_session_id)

    return {
        "success": True,
        "data": {
            **_format_session(session_obj),
            "messages": [_format_message(m) for m in messages],
            "pending_confirmations": sum(
                1 for m in messages if m.requires_confirmation and m.confirmation_status == "pending"
            )
        }
    }


@router.post("/sessions/{session_id}/messages")
def send_message(
    session_id: str,
    request: DirectorAgentMessageSendRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    发送消息

    向AI导演发送消息并获取回复。
    """
    service = DirectorAgentService(session)

    # 解码ID
    decoded_session_id = _decode_session_id(session_id)

    # 创建流式思考回调：发布 thinking 事件到 SSE
    def stream_thinking_callback(reasoning_content: str):
        """同步回调，在 LLM 流式推理过程中被调用"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.call_soon_threadsafe(
                    lambda: asyncio.create_task(_publish_thinking_event(decoded_session_id, reasoning_content))
                )
            else:
                asyncio.run(_publish_thinking_event(decoded_session_id, reasoning_content))
        except Exception:
            pass  # SSE 发布失败不影响主流程

    # 处理消息（service 内部处理 session 获取和验证）
    agent_message = service.process_message(
        session_id=decoded_session_id,
        user_message=request.content,
        additional_context=request.context,
        stream_callback=stream_thinking_callback
    )

    # 发布 SSE 事件（异步）
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_publish_sse_event(decoded_session_id, agent_message))
        else:
            asyncio.run(_publish_sse_event(decoded_session_id, agent_message))
    except Exception:
        pass  # SSE 发布失败不影响主流程

    return {
        "success": True,
        "data": {
            "session": _format_session(service.get_session(decoded_session_id)),
            "message": _format_message(agent_message),
            "context_updated": True
        }
    }


async def _publish_sse_event(session_id: int, message: DirectorAgentMessage):
    """发布 SSE 事件"""
    try:
        gen = get_db_session()
        db_session = next(gen)
        try:
            session_obj = db_session.get(DirectorAgentSession, session_id)
            if session_obj:
                encoded_session_id = _encode_session_id(session_obj.id)
                await _event_manager.publish(encoded_session_id, {
                    "type": SSE_EVENT_AGENT_MESSAGE,
                    "message": _format_message(message),
                    "session_id": encoded_session_id,
                })
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
    except Exception:
        return


async def _publish_thinking_event(session_id: int, reasoning_content: str):
    """发布 thinking 类型的 SSE 事件"""
    try:
        gen = get_db_session()
        db_session = next(gen)
        try:
            session_obj = db_session.get(DirectorAgentSession, session_id)
            if session_obj:
                encoded_session_id = _encode_session_id(session_obj.id)
                await _event_manager.publish(encoded_session_id, {
                    "type": "thinking",
                    "reasoning": reasoning_content,
                    "session_id": encoded_session_id,
                })
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
    except Exception:
        return


@router.post("/messages/{message_id}/confirm")
def confirm_message(
    message_id: str,
    request: DirectorAgentMessageConfirmRequest,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    确认消息动作

    确认或拒绝待确认的消息动作。
    """
    service = DirectorAgentService(session)

    # 解码ID
    decoded_message_id = _decode_message_id(message_id)

    message = session.get(DirectorAgentMessage, decoded_message_id)
    if not message:
        raise HTTPException(status_code=404, detail="消息不存在")

    # 验证权限
    session_obj = service.get_session(message.session_id)
    if not session_obj or session_obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问此消息")

    try:
        updated_message = service.confirm_action(
            message=message,
            action=request.action,
            modifications=request.modifications,
            user=user
        )

        import json
        execution_result = json.loads(updated_message.execution_result_json or "{}")

        # 发布 SSE 事件
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_publish_sse_event(message.session_id, updated_message))
            else:
                asyncio.run(_publish_sse_event(message.session_id, updated_message))
        except Exception:
            pass

        return {
            "success": True,
            "data": {
                "message": _format_message(updated_message),
                "project_updated": updated_message.task_status == "completed",
                "refresh_hints": execution_result.get("refresh_hints", {})
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise


@router.get("/sessions/{session_id}/context")
def get_session_context(
    session_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    获取会话上下文

    返回当前项目、剧集、分镜等上下文信息。
    """
    service = DirectorAgentService(session)

    # 解码ID
    decoded_session_id = _decode_session_id(session_id)

    session_obj = service.get_session(decoded_session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 验证权限
    if session_obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    import json
    context = json.loads(session_obj.context_snapshot_json or "{}")

    # 计算缺失的上下文
    from services.director_agent_rules import DirectorAgentRules, TaskType
    missing = DirectorAgentRules.check_context_requirements(
        TaskType.MIXED_WORKFLOW,
        context
    )

    return {
        "success": True,
        "data": {
            **context,
            "missing_context": missing
        }
    }


@router.get("/script-sessions/{script_id}")
def get_script_sessions_by_script(
    script_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    获取剧本的所有会话（新路径，备用）
    """
    try:
        from sqlmodel import select
        from models import Team, TeamMemberLink

        # 获取用户的团队
        link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user.id)).first()
        if not link:
            raise HTTPException(status_code=403, detail="当前账号未加入任何团队")

        team = session.get(Team, link.team_id)
        if not team:
            raise HTTPException(status_code=404, detail="团队不存在")

        # 解码ID
        decoded_script_id = decode_id(script_id)

        # 验证权限
        from services.access_service import require_script_team_access
        require_script_team_access(session, team, decoded_script_id)

        # 查询会话
        statement = (
            select(DirectorAgentSession)
            .where(DirectorAgentSession.script_id == decoded_script_id)
            .where(DirectorAgentSession.user_id == user.id)
            .order_by(DirectorAgentSession.updated_at.desc())
        )
        sessions = session.exec(statement).all()

        return {
            "success": True,
            "data": [_format_session(s) for s in sessions]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/scripts/{script_id}/sessions")
def get_script_sessions(
    script_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    获取剧本的所有会话

    返回当前用户在指定剧本下的所有会话。
    """
    try:
        from sqlmodel import select
        from models import Team, TeamMemberLink

        # 获取用户的团队
        link = session.exec(select(TeamMemberLink).where(TeamMemberLink.user_id == user.id)).first()
        if not link:
            raise HTTPException(status_code=403, detail="当前账号未加入任何团队")

        team = session.get(Team, link.team_id)
        if not team:
            raise HTTPException(status_code=404, detail="团队不存在")

        # 解码ID
        decoded_script_id = decode_id(script_id)

        # 验证权限
        from services.access_service import require_script_team_access
        require_script_team_access(session, team, decoded_script_id)

        # 查询会话
        statement = (
            select(DirectorAgentSession)
            .where(DirectorAgentSession.script_id == decoded_script_id)
            .where(DirectorAgentSession.user_id == user.id)
            .order_by(DirectorAgentSession.updated_at.desc())
        )
        sessions = session.exec(statement).all()

        return {
            "success": True,
            "data": [_format_session(s) for s in sessions]
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session)
) -> Dict[str, Any]:
    """
    删除会话

    删除指定的会话及其所有消息。
    """
    # 解码ID
    decoded_session_id = _decode_session_id(session_id)

    # 获取会话
    session_obj = session.get(DirectorAgentSession, decoded_session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 验证权限
    if session_obj.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权删除此会话")

    # 删除会话消息
    from sqlmodel import select
    statement = select(DirectorAgentMessage).where(
        DirectorAgentMessage.session_id == decoded_session_id
    )
    messages = session.exec(statement).all()
    for msg in messages:
        session.delete(msg)

    # 删除会话
    session.delete(session_obj)
    session.commit()

    return {
        "success": True,
        "data": {"deleted": True}
    }


# ==================== SSE 流式推送 ====================

class SessionEventManager:
    """会话事件管理器（内存存储，生产环境应使用 Redis）"""

    def __init__(self):
        self._subscribers: Dict[str, asyncio.Queue] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, session_id: str) -> asyncio.Queue:
        """订阅会话事件"""
        async with self._lock:
            if session_id not in self._subscribers:
                self._subscribers[session_id] = asyncio.Queue(maxsize=100)
            return self._subscribers[session_id]

    async def unsubscribe(self, session_id: str):
        """取消订阅"""
        async with self._lock:
            if session_id in self._subscribers:
                del self._subscribers[session_id]

    async def publish(self, session_id: str, event: Dict[str, Any]):
        """发布事件"""
        async with self._lock:
            if session_id in self._subscribers:
                try:
                    self._subscribers[session_id].put_nowait(event)
                except asyncio.QueueFull:
                    pass  # 队列满时丢弃旧事件

    async def get_event(self, session_id: str, timeout: float = 30) -> Optional[Dict[str, Any]]:
        """获取事件（带超时）"""
        async with self._lock:
            if session_id not in self._subscribers:
                return None
            queue = self._subscribers[session_id]

        try:
            return await asyncio.wait_for(queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None


# 全局事件管理器
_event_manager = SessionEventManager()


@router.get("/sessions/{session_id}/stream")
async def stream_session(
    session_id: str,
    token: Optional[str] = None,
    authorization: Optional[str] = Header(None),
):
    """
    SSE 流式推送端点

    建立与 AI 导演会话的实时事件流连接。
    支持 token 作为 query 参数或 Authorization header。
    """
    # 认证：优先使用 query token，否则使用 header
    auth_token = token
    if not auth_token and authorization:
        auth_token = authorization.replace("Bearer ", "") if authorization.startswith("Bearer ") else authorization

    if not auth_token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")

    with session_scope() as stream_session:
        user = stream_session.exec(select(User).where(User.session_token == auth_token)).first()
        if not user:
            raise HTTPException(status_code=401, detail="登录已过期，请重新登录")

        if not user.is_active:
            raise HTTPException(status_code=403, detail="账号已被禁用")

        decoded_session_id = _decode_session_id(session_id)
        session_obj = stream_session.get(DirectorAgentSession, decoded_session_id)
        if not session_obj:
            raise HTTPException(status_code=404, detail="会话不存在")

        if session_obj.user_id != user.id:
            raise HTTPException(status_code=403, detail="无权访问此会话")

    async def event_generator():
        queue = await _event_manager.subscribe(session_id)

        # 发送连接成功事件
        yield f"event: connected\ndata: {json.dumps({'status': 'connected', 'session_id': session_id})}\n\n"

        try:
            while True:
                # 等待事件（30秒超时后发送心跳）
                event = await _event_manager.get_event(session_id, timeout=30)

                if event is None:
                    # 发送心跳
                    yield f"event: {SSE_EVENT_HEARTBEAT}\ndata: {json.dumps({'type': 'heartbeat'})}\n\n"
                    continue

                event_type = event.get("type", SSE_EVENT_AGENT_MESSAGE)
                yield f"event: {event_type}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            await _event_manager.unsubscribe(session_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


async def publish_agent_message(session_id: int, message: DirectorAgentMessage):
    """发布 Agent 消息到 SSE 流（供 service 调用）"""
    gen = get_db_session()
    db_session = next(gen)

    try:
        session_obj = db_session.get(DirectorAgentSession, session_id)
        if session_obj:
            encoded_session_id = _encode_session_id(session_obj.id)
            await _event_manager.publish(encoded_session_id, {
                "type": SSE_EVENT_AGENT_MESSAGE,
                "message": _format_message(message),
                "session_id": encoded_session_id,
            })
    finally:
        try:
            next(gen)
        except StopIteration:
            pass
