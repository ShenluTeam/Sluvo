"""
神鹿AI导演核心服务

负责会话管理、消息处理、任务执行等核心逻辑。
复用 storyboard_director_service 的拆镜能力。

集成 ArcReel 风格编排器：
- orchestrator: 工作流编排
- subagent: 推理代理
- tools: 确定性工具
"""

import asyncio
import json
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from sqlmodel import Session, select

from database import get_session
from models import (
    DirectorAgentSession,
    DirectorAgentMessage,
    Episode,
    Panel,
    Script,
    SharedResource,
    User,
)
from services.director_agent_rules import (
    DirectorAgentRules,
    TaskType,
    ActionType,
    get_task_title,
    get_task_description,
)
from core.config import settings
from services.director_agent.orchestrator import ShenluWorkflowOrchestrator


class DirectorAgentService:
    """神鹿AI导演核心服务"""

    DEFAULT_SESSION_TITLE = "新对话"

    def __init__(self, session: Session = None):
        # 如果传入的是 dict 或 None，从 get_session() 重新获取
        if session is None or isinstance(session, dict):
            self._owns_session = True
            self._session_gen = get_session()
            self.session = next(self._session_gen)
        else:
            self._owns_session = False
            self.session = session
        self._orchestrator = None

    def close(self):
        """关闭服务时释放 session"""
        if self._owns_session and self._session_gen:
            try:
                next(self._session_gen)
            except StopIteration:
                pass

    # ==================== 会话管理 ====================

    def create_session(
        self,
        *,
        user: User,
        script_id: int,
        episode_id: Optional[int] = None,
        title: Optional[str] = None
    ) -> DirectorAgentSession:
        """创建新会话"""
        # 获取用户的团队ID
        team_id = self._get_user_team_id(user, script_id)

        # 构建上下文快照
        context_snapshot = self._build_context_snapshot(script_id, episode_id)

        session_obj = DirectorAgentSession(
            script_id=script_id,
            episode_id=episode_id,
            user_id=user.id,
            team_id=team_id,
            title=title or self.DEFAULT_SESSION_TITLE,
            context_snapshot_json=json.dumps(context_snapshot, ensure_ascii=False),
            status="active"
        )
        self.session.add(session_obj)
        self.session.commit()
        self.session.refresh(session_obj)
        return session_obj

    def _derive_session_title(self, user_message: str) -> str:
        text = " ".join(str(user_message or "").strip().split())
        if not text:
            return self.DEFAULT_SESSION_TITLE
        if len(text) <= 24:
            return text
        return f"{text[:24].rstrip()}..."

    def _touch_session(
        self,
        session_obj: DirectorAgentSession,
        *,
        user_message: Optional[str] = None,
        action_type: Optional[str] = None,
    ) -> None:
        now = datetime.utcnow()
        session_obj.updated_at = now
        session_obj.last_message_at = now
        if action_type:
            session_obj.last_action_type = action_type
        if user_message is not None and (not session_obj.title or session_obj.title == self.DEFAULT_SESSION_TITLE):
            session_obj.title = self._derive_session_title(user_message)
        self.session.add(session_obj)

    def get_session(self, session_id: int) -> Optional[DirectorAgentSession]:
        """获取会话"""
        return self.session.get(DirectorAgentSession, session_id)

    def get_or_create_session(
        self,
        *,
        user: User,
        script_id: int,
        episode_id: Optional[int] = None
    ) -> DirectorAgentSession:
        """获取或创建会话（同一剧本同一用户复用会话）"""
        # 查找现有的活跃会话
        statement = select(DirectorAgentSession).where(
            DirectorAgentSession.script_id == script_id,
            DirectorAgentSession.user_id == user.id,
            DirectorAgentSession.status == "active"
        )
        if episode_id:
            statement = statement.where(DirectorAgentSession.episode_id == episode_id)

        existing = self.session.exec(statement).first()
        if existing:
            # 更新上下文
            existing.context_snapshot_json = json.dumps(
                self._build_context_snapshot(script_id, episode_id),
                ensure_ascii=False
            )
            existing.updated_at = datetime.utcnow()
            self.session.add(existing)
            self.session.commit()
            self.session.refresh(existing)
            return existing

        return self.create_session(
            user=user,
            script_id=script_id,
            episode_id=episode_id
        )

    def get_session_messages(
        self,
        session_id: int,
        limit: int = 50
    ) -> List[DirectorAgentMessage]:
        """获取会话消息列表"""
        statement = (
            select(DirectorAgentMessage)
            .where(DirectorAgentMessage.session_id == session_id)
            .order_by(DirectorAgentMessage.created_at.desc())
            .limit(limit)
        )
        messages = self.session.exec(statement).all()
        return list(reversed(messages))

    # ==================== 消息处理 ====================

    def process_message(
        self,
        *,
        session_id: int,
        user_message: str,
        additional_context: Optional[Dict[str, Any]] = None,
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> DirectorAgentMessage:
        """处理用户消息，返回Agent回复

        Args:
            session_id: 会话ID
            user_message: 用户消息
            additional_context: 额外上下文
            stream_callback: 流式回调，用于实时推送 reasoning_content
        """

        # 获取 session_obj
        session_obj = self.session.get(DirectorAgentSession, session_id)
        if not session_obj:
            raise ValueError("会话不存在")

        # 保存用户消息
        user_msg = DirectorAgentMessage(
            session_id=session_id,
            role="user",
            content=user_message,
            message_type="text"
        )
        self.session.add(user_msg)
        self._touch_session(session_obj, user_message=user_message, action_type="send_message")
        self.session.commit()
        self.session.refresh(session_obj)

        # 使用新的编排器处理消息
        try:
            orchestrator = self._get_orchestrator(session_obj)
            agent_message = orchestrator.run(user_message, stream_callback=stream_callback)
            return agent_message
        except Exception as e:
            # 如果编排器出错，回退到原有逻辑
            return self._process_message_legacy(session_obj, user_message, additional_context)

    def _get_orchestrator(self, session_obj: DirectorAgentSession) -> ShenluWorkflowOrchestrator:
        """获取或创建编排器实例"""
        if self._orchestrator is None:
            self._orchestrator = ShenluWorkflowOrchestrator(self.session, session_obj)
        return self._orchestrator

    def _process_message_legacy(
        self,
        session_obj: DirectorAgentSession,
        user_message: str,
        additional_context: Optional[Dict[str, Any]] = None
    ) -> DirectorAgentMessage:
        """回退的消息处理逻辑（使用原有规则引擎）"""

        # 获取当前上下文
        context = json.loads(session_obj.context_snapshot_json or "{}")
        if additional_context:
            context.update(additional_context)

        # 使用规则评估请求
        rule_result = DirectorAgentRules.evaluate_request(user_message, context)

        # 检查上下文缺失
        if rule_result.missing_context:
            return self._create_context_missing_message(
                session_obj, rule_result
            )

        # 根据任务类型处理
        if rule_result.task_type == TaskType.STORYBOARD_PLANNING:
            return self._handle_storyboard_planning(session_obj, rule_result, context)
        elif rule_result.task_type == TaskType.SEGMENT_PLANNING:
            return self._handle_segment_planning(session_obj, rule_result, context)
        elif rule_result.task_type == TaskType.IMAGE_GENERATION_PLANNING:
            return self._handle_image_planning(session_obj, rule_result, context)
        elif rule_result.task_type == TaskType.VIDEO_GENERATION_PLANNING:
            return self._handle_video_planning(session_obj, rule_result, context)
        elif rule_result.task_type == TaskType.DUBBING_PLANNING:
            return self._handle_dubbing_planning(session_obj, rule_result, context)
        else:
            return self._handle_mixed_workflow(session_obj, rule_result, context)

    def confirm_action(
        self,
        *,
        message: DirectorAgentMessage,
        action: str,
        modifications: Optional[Dict[str, Any]] = None,
        user: User
    ) -> DirectorAgentMessage:
        """确认执行动作"""
        if message.confirmation_status != "pending":
            raise ValueError("消息不处于待确认状态")

        if action == "reject":
            message.confirmation_status = "rejected"
            message.task_status = "rejected"
            session_obj = self.session.get(DirectorAgentSession, message.session_id)
            if session_obj:
                self._touch_session(session_obj, action_type="reject")
            self.session.add(message)
            self.session.commit()
            self.session.refresh(message)
            return message

        # 获取 session_obj
        session_id = message.session_id
        session_obj = self.session.get(DirectorAgentSession, session_id)
        if not session_obj:
            raise ValueError("Session not found")

        # 尝试使用新的编排器处理确认
        try:
            orchestrator = self._get_orchestrator(session_obj)
            subagent_name = self._get_subagent_name_from_task_type(message.task_type)

            if message.message_type == "confirm":
                # confirm 卡片表示结果已准备好，只差最后一步写入。
                agent_message = orchestrator.execute_write(
                    subagent_name=subagent_name,
                    confirmed=True,
                    modifications=modifications,
                )
            else:
                # plan 卡片表示“继续执行”，不应直接跳到写库阶段。
                agent_message = orchestrator.run_with_confirmation(
                    subagent_name=subagent_name,
                    confirmed=True,
                    modifications=modifications,
                )

            # 更新原始消息状态
            message.confirmation_status = "confirmed"
            message.confirmed_at = datetime.utcnow()
            message.confirmed_by_user_id = user.id
            message.execution_result_json = json.dumps({"result_message_id": agent_message.id}, ensure_ascii=False)
            message.task_status = "completed"
            message.message_type = "result"

            self._touch_session(session_obj, action_type=action)
            self.session.add(message)
            self.session.commit()
            self.session.refresh(message)

            return agent_message

        except Exception as e:
            # 回退到原有逻辑
            return self._confirm_action_legacy(message, action, modifications, user)

    def _confirm_action_legacy(
        self,
        message: DirectorAgentMessage,
        action: str,
        modifications: Optional[Dict[str, Any]],
        user: User
    ) -> DirectorAgentMessage:
        """回退的确认动作处理"""
        payload = json.loads(message.payload_json or "{}")
        task_type = TaskType(message.task_type)

        try:
            result = self._execute_confirmed_action(task_type, payload, modifications)

            # 更新消息状态
            message.confirmation_status = "confirmed"
            message.confirmed_at = datetime.utcnow()
            message.confirmed_by_user_id = user.id
            message.execution_result_json = json.dumps(result, ensure_ascii=False)
            message.task_status = "completed"
            message.message_type = "result"

            session_obj = self.session.get(DirectorAgentSession, message.session_id)
            if session_obj:
                self._touch_session(session_obj, action_type=action)
            self.session.add(message)
            self.session.commit()
            self.session.refresh(message)
            return message

        except Exception as e:
            message.task_status = "failed"
            message.execution_result_json = json.dumps({
                "error": str(e),
                "status": "failed"
            }, ensure_ascii=False)
            self.session.add(message)
            self.session.commit()
            self.session.refresh(message)
            raise

    def _get_subagent_name_from_task_type(self, task_type: str) -> str:
        """从任务类型获取 Subagent 名称"""
        mapping = {
            "script_analysis": "analyze-story-context",
            "segment_planning": "split-story-segments",
            "storyboard_planning": "plan-storyboard",
        }
        return mapping.get(task_type, "analyze-story-context")

    # ==================== 任务处理方法 ====================

    def _handle_storyboard_planning(
        self,
        session_obj: DirectorAgentSession,
        rule_result,
        context: Dict[str, Any]
    ) -> DirectorAgentMessage:
        """处理分镜规划请求"""
        episode_id = session_obj.episode_id
        if not episode_id:
            return self._create_error_message(
                session_obj, "请先选择一个剧集"
            )

        episode = self.session.get(Episode, episode_id)
        if not episode or not episode.source_text:
            return self._create_error_message(
                session_obj, "当前剧集缺少剧本原文"
            )

        # 需要确认才能执行
        preview = self._get_storyboard_preview(episode)

        payload = {
            "task_type": TaskType.STORYBOARD_PLANNING.value,
            "title": get_task_title(TaskType.STORYBOARD_PLANNING),
            "description": f"为「{episode.title}」生成分镜拆解方案",
            "estimated_items": preview.get("estimated_panels", 0),
            "estimated_cost": 0,
            "requires_confirmation": True,
            "preview": preview,
            "actions": [
                {"action_type": "confirm", "label": "确认执行"},
                {"action_type": "modify", "label": "调整参数"},
                {"action_type": "cancel", "label": "取消"}
            ]
        }

        message = DirectorAgentMessage(
            session_id=session_obj.id,
            role="agent",
            content=f"已为「{episode.title}」准备好分镜方案，预计生成 {preview.get('estimated_panels', 0)} 个分镜。请确认后执行。",
            message_type="plan",
            payload_json=json.dumps(payload, ensure_ascii=False),
            task_type=TaskType.STORYBOARD_PLANNING.value,
            task_status="pending",
            requires_confirmation=True,
            confirmation_status="pending"
        )

        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _handle_segment_planning(
        self,
        session_obj: DirectorAgentSession,
        rule_result,
        context: Dict[str, Any]
    ) -> DirectorAgentMessage:
        """处理剧情片段拆分请求"""
        episode_id = session_obj.episode_id
        if not episode_id:
            return self._create_error_message(
                session_obj, "请先选择一个剧集"
            )

        episode = self.session.get(Episode, episode_id)
        if not episode or not episode.source_text:
            return self._create_error_message(
                session_obj, "当前剧集缺少剧本原文"
            )

        preview = self._get_segment_preview(episode)

        payload = {
            "task_type": TaskType.SEGMENT_PLANNING.value,
            "title": get_task_title(TaskType.SEGMENT_PLANNING),
            "description": f"分析「{episode.title}」的剧情片段",
            "estimated_items": preview.get("estimated_segments", 0),
            "estimated_cost": 0,
            "requires_confirmation": True,
            "preview": preview,
            "actions": [
                {"action_type": "confirm", "label": "确认执行"},
                {"action_type": "cancel", "label": "取消"}
            ]
        }

        message = DirectorAgentMessage(
            session_id=session_obj.id,
            role="agent",
            content=f"已分析「{episode.title}」的剧情结构，预计拆分为 {preview.get('estimated_segments', 0)} 个剧情片段。",
            message_type="plan",
            payload_json=json.dumps(payload, ensure_ascii=False),
            task_type=TaskType.SEGMENT_PLANNING.value,
            task_status="pending",
            requires_confirmation=True,
            confirmation_status="pending"
        )

        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _handle_image_planning(
        self,
        session_obj: DirectorAgentSession,
        rule_result,
        context: Dict[str, Any]
    ) -> DirectorAgentMessage:
        """处理图片生成规划请求"""
        panels_summary = context.get("panels_summary", {})

        payload = {
            "task_type": TaskType.IMAGE_GENERATION_PLANNING.value,
            "title": get_task_title(TaskType.IMAGE_GENERATION_PLANNING),
            "description": "分析分镜并给出图片生成建议",
            "estimated_items": panels_summary.get("without_images_count", 0),
            "estimated_cost": panels_summary.get("without_images_count", 0) * 3,
            "requires_confirmation": True,
            "preview": {
                "total_panels": panels_summary.get("total", 0),
                "panels_with_images": panels_summary.get("with_images_count", 0),
                "panels_without_images": panels_summary.get("without_images_count", 0)
            },
            "actions": [
                {"action_type": "confirm", "label": "查看建议"},
                {"action_type": "cancel", "label": "取消"}
            ]
        }

        message = DirectorAgentMessage(
            session_id=session_obj.id,
            role="agent",
            content=f"当前有 {panels_summary.get('without_images_count', 0)} 个分镜待生成图片，预估消耗 {payload['estimated_cost']} 灵感值。",
            message_type="plan",
            payload_json=json.dumps(payload, ensure_ascii=False),
            task_type=TaskType.IMAGE_GENERATION_PLANNING.value,
            task_status="pending",
            requires_confirmation=True,
            confirmation_status="pending"
        )

        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _handle_video_planning(
        self,
        session_obj: DirectorAgentSession,
        rule_result,
        context: Dict[str, Any]
    ) -> DirectorAgentMessage:
        """处理视频生成规划请求"""
        panels_summary = context.get("panels_summary", {})

        payload = {
            "task_type": TaskType.VIDEO_GENERATION_PLANNING.value,
            "title": get_task_title(TaskType.VIDEO_GENERATION_PLANNING),
            "description": "分析分镜并给出视频生成建议",
            "estimated_items": panels_summary.get("without_videos_count", 0),
            "estimated_cost": panels_summary.get("without_videos_count", 0) * 10,
            "requires_confirmation": True,
            "preview": {
                "total_panels": panels_summary.get("total", 0),
                "panels_with_images": panels_summary.get("with_images_count", 0),
                "panels_without_videos": panels_summary.get("without_videos_count", 0)
            },
            "actions": [
                {"action_type": "confirm", "label": "查看建议"},
                {"action_type": "cancel", "label": "取消"}
            ]
        }

        message = DirectorAgentMessage(
            session_id=session_obj.id,
            role="agent",
            content=f"当前有 {panels_summary.get('without_videos_count', 0)} 个分镜可生成视频，预估消耗 {payload['estimated_cost']} 灵感值。",
            message_type="plan",
            payload_json=json.dumps(payload, ensure_ascii=False),
            task_type=TaskType.VIDEO_GENERATION_PLANNING.value,
            task_status="pending",
            requires_confirmation=True,
            confirmation_status="pending"
        )

        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _handle_dubbing_planning(
        self,
        session_obj: DirectorAgentSession,
        rule_result,
        context: Dict[str, Any]
    ) -> DirectorAgentMessage:
        """处理配音规划请求"""
        episode = context.get("episode", {})

        payload = {
            "task_type": TaskType.DUBBING_PLANNING.value,
            "title": get_task_title(TaskType.DUBBING_PLANNING),
            "description": "分析当前剧集的配音需求",
            "estimated_items": 0,
            "estimated_cost": 0,
            "requires_confirmation": False,
            "preview": {
                "has_source_text": episode.get("has_source_text", False),
                "source_text_length": len(episode.get("source_text_preview", ""))
            },
            "actions": []
        }

        message = DirectorAgentMessage(
            session_id=session_obj.id,
            role="agent",
            content="配音功能正在开发中，敬请期待。",
            message_type="text",
            payload_json=json.dumps(payload, ensure_ascii=False),
            task_type=TaskType.DUBBING_PLANNING.value,
            task_status="completed"
        )

        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _handle_mixed_workflow(
        self,
        session_obj: DirectorAgentSession,
        rule_result,
        context: Dict[str, Any]
    ) -> DirectorAgentMessage:
        """处理混合工作流请求"""
        suggestions = rule_result.suggestions if rule_result.suggestions else []

        payload = {
            "task_type": TaskType.MIXED_WORKFLOW.value,
            "title": get_task_title(TaskType.MIXED_WORKFLOW),
            "description": "根据需求执行综合工作流",
            "suggestions": suggestions
        }

        content = "我理解您的需求。以下是一些建议：\n\n"
        for i, suggestion in enumerate(suggestions, 1):
            content += f"{i}. {suggestion}\n"
        content += "\n请告诉我您想执行哪项操作？"

        message = DirectorAgentMessage(
            session_id=session_obj.id,
            role="agent",
            content=content,
            message_type="text",
            payload_json=json.dumps(payload, ensure_ascii=False),
            task_type=TaskType.MIXED_WORKFLOW.value
        )

        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    # ==================== 辅助方法 ====================

    def _build_context_snapshot(
        self,
        script_id: int,
        episode_id: Optional[int]
    ) -> Dict[str, Any]:
        """构建上下文快照"""
        script = self.session.get(Script, script_id)
        if not script:
            return {}

        context = {
            "script": {
                "id": script_id,
                "name": script.name,
                "aspect_ratio": script.aspect_ratio,
                "style_preset": script.style_preset,
                "has_source_text": bool(script.source_text)
            },
            "episode": None,
            "panels_summary": {},
            "shared_resources": {}
        }

        # 获取剧集信息
        if episode_id:
            episode = self.session.get(Episode, episode_id)
            if episode:
                context["episode"] = {
                    "id": episode_id,
                    "title": episode.title,
                    "sequence_num": episode.sequence_num,
                    "has_source_text": bool(episode.source_text),
                    "source_text_preview": (episode.source_text or "")[:200]
                }

                # 获取分镜统计
                panels = self.session.exec(
                    select(Panel).where(Panel.episode_id == episode_id)
                ).all()
                panels_with_images = sum(1 for p in panels if p.image_url)
                panels_with_videos = sum(1 for p in panels if p.video_url)
                nine_grid_count = sum(1 for p in panels if p.panel_type == "nine_grid")

                context["panels_summary"] = {
                    "total": len(panels),
                    "with_images_count": panels_with_images,
                    "without_images_count": len(panels) - panels_with_images,
                    "with_videos_count": panels_with_videos,
                    "without_videos_count": len(panels) - panels_with_videos,
                    "nine_grid_count": nine_grid_count,
                    "normal_count": len(panels) - nine_grid_count,
                    "has_images": panels_with_images > 0
                }

        # 获取共享资源统计
        resources = self.session.exec(
            select(SharedResource).where(SharedResource.script_id == script_id)
        ).all()

        characters = [r for r in resources if r.resource_type == "character"]
        scenes = [r for r in resources if r.resource_type == "scene"]
        props = [r for r in resources if r.resource_type == "prop"]

        context["shared_resources"] = {
            "characters": [{"id": r.id, "name": r.name, "has_image": bool(r.file_url)} for r in characters],
            "scenes": [{"id": r.id, "name": r.name, "has_image": bool(r.file_url)} for r in scenes],
            "props": [{"id": r.id, "name": r.name, "has_image": bool(r.file_url)} for r in props]
        }

        return context

    def _get_user_team_id(self, user: User, script_id: int) -> int:
        """获取用户在剧本所属团队的ID"""
        script = self.session.get(Script, script_id)
        if script:
            return script.team_id
        # 如果用户没有团队，返回默认团队ID（需要在实际场景中处理）
        if user.teams:
            return user.teams[0].id
        raise ValueError("用户没有关联的团队")

    def _create_context_missing_message(
        self,
        session_obj: DirectorAgentSession,
        rule_result
    ) -> DirectorAgentMessage:
        """创建上下文缺失提示消息"""
        missing_text = "\n".join(f"- {m}" for m in rule_result.missing_context)
        suggestions_text = "\n".join(f"- {s}" for s in rule_result.suggestions) if rule_result.suggestions else ""

        content = f"⚠️ 当前上下文不完整：\n\n{missing_text}\n\n"
        if suggestions_text:
            content += f"💡 建议：\n\n{suggestions_text}"

        message = DirectorAgentMessage(
            session_id=session_obj.id,
            role="agent",
            content=content,
            message_type="text",
            task_type=rule_result.task_type.value
        )

        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _create_error_message(
        self,
        session_obj: DirectorAgentSession,
        error_text: str
    ) -> DirectorAgentMessage:
        """创建错误消息"""
        message = DirectorAgentMessage(
            session_id=session_obj.id,
            role="agent",
            content=f"❌ {error_text}",
            message_type="text"
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _get_storyboard_preview(self, episode: Episode) -> Dict[str, Any]:
        """获取分镜预览"""
        # 简单预估：每段文字约生成 1-3 个分镜
        text_length = len(episode.source_text or "")
        estimated_panels = max(1, text_length // 200)

        return {
            "episode_title": episode.title,
            "source_text_length": text_length,
            "estimated_panels": estimated_panels,
            "estimated_segments": max(1, estimated_panels // 3)
        }

    def _get_segment_preview(self, episode: Episode) -> Dict[str, Any]:
        """获取剧情片段预览"""
        text_length = len(episode.source_text or "")
        # 简单预估：每 500 字约一个剧情片段
        estimated_segments = max(1, text_length // 500)

        return {
            "episode_title": episode.title,
            "source_text_length": text_length,
            "estimated_segments": estimated_segments
        }

    def _execute_confirmed_action(
        self,
        task_type: TaskType,
        payload: Dict[str, Any],
        modifications: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """执行确认后的动作"""
        # 这里后续会对接实际的执行逻辑
        # 第一阶段先返回模拟结果

        return {
            "status": "completed",
            "summary": f"{get_task_title(task_type)} 已完成",
            "items_created": payload.get("estimated_items", 0),
            "refresh_hints": {
                "panels": task_type in [TaskType.STORYBOARD_PLANNING, TaskType.SEGMENT_PLANNING],
                "resources": task_type == TaskType.STORYBOARD_PLANNING,
                "episodes": False
            }
        }
