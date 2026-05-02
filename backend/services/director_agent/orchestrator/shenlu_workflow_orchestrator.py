"""Orchestrator: 神鹿工作流编排器."""
import json
from typing import Any, Callable, Dict, List, Optional

from sqlmodel import Session, select

from models import DirectorAgentSession, DirectorAgentMessage
from ..schemas.orchestrator_schemas import ProjectContext, ProjectStage
from ..schemas.subagent_schemas import UserIntent, TaskType
from ..schemas.message_schemas import PlanPayload, ConfirmPayload, ResultPayload
from ..subagent.base import Subagent, SubagentResult
from ..subagent.analyze_story_context import AnalyzeStoryContextSubagent
from ..subagent.split_story_segments import SplitStorySegmentsSubagent
from ..subagent.plan_storyboard import PlanStoryboardSubagent
from ..subagent.extract_project_assets import ExtractProjectAssetsSubagent
from ..subagent.generate_panel_image import GeneratePanelImageSubagent
from ..subagent.generate_panel_video import GeneratePanelVideoSubagent
from ..subagent.generate_episode_dubbing import GenerateEpisodeDubbingSubagent
from ..tools.panel_writer import PanelWriterTool
from ..tools.llm_agent_tool import LLMAgentTool
from .context_builder import ContextBuilder
from .stage_detector import StageDetector
from .confirmation_gate import ConfirmationGate


class ShenluWorkflowOrchestrator:
    """神鹿导演工作流编排器"""

    def __init__(self, session: Session, session_obj: DirectorAgentSession):
        self.session = session
        self.session_obj = session_obj
        self.context_builder = ContextBuilder()
        self.stage_detector = StageDetector()
        self.confirmation_gate = ConfirmationGate()
        self.panel_writer = PanelWriterTool()

        # Subagent 注册表
        self.subagents: Dict[str, Subagent] = {
            "analyze-story-context": AnalyzeStoryContextSubagent(),
            "split-story-segments": SplitStorySegmentsSubagent(),
            "plan-storyboard": PlanStoryboardSubagent(),
            "extract-project-assets": ExtractProjectAssetsSubagent(),
            "generate-panel-image": GeneratePanelImageSubagent(),
            "generate-panel-video": GeneratePanelVideoSubagent(),
            "generate-episode-dubbing": GenerateEpisodeDubbingSubagent(),
        }
        # LLM Agent 工具（用于中央推理决策）
        self.llm_agent = LLMAgentTool()

    def run(
        self,
        user_message: str,
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> DirectorAgentMessage:
        """
        主入口：接收用户消息，返回 Agent 消息

        Args:
            user_message: 用户输入的消息
            stream_callback: 回调函数，接收 reasoning_content 增量，用于流式推送思考过程

        Returns:
            DirectorAgentMessage: Agent 回复消息
        """
        # Step 1: 构建上下文
        try:
            project_context = self._load_or_build_context()
        except Exception as e:
            import traceback
            print(f"[Orchestrator] _load_or_build_context error: {e}")
            print(f"[Orchestrator] Traceback: {traceback.format_exc()}")
            return self._create_text_message(f"加载上下文失败: {str(e)}")

        # Step 2: 使用 LLM Agent 进行推理决策
        try:
            context_dict = project_context.to_dict()
        except Exception as e:
            # 如果 to_dict 失败，使用简化上下文
            context_dict = {
                "stage": project_context.stage.value if project_context.stage else "unknown",
                "script": {"name": "未知剧本"} if project_context.script else None,
                "episode": {"title": "未知剧集"} if project_context.episode else None,
            }

        available_actions = self._build_available_actions(project_context)
        recent_messages = self._collect_recent_messages()

        try:
            # 优先使用流式推理（有回调时）
            if stream_callback:
                llm_result = self.llm_agent.stream_reason(
                    user_message=user_message,
                    context=context_dict,
                    stream_callback=stream_callback,
                    available_actions=available_actions,
                    recent_messages=recent_messages,
                )
            else:
                llm_result = self.llm_agent.reason(
                    user_message=user_message,
                    context=context_dict,
                    available_actions=available_actions,
                    recent_messages=recent_messages,
                )
        except Exception as e:
            import traceback
            print(f"[Orchestrator] LLM reason error: {e}")
            print(f"[Orchestrator] Traceback: {traceback.format_exc()}")
            # LLM 调用失败，返回文本回复
            return self._create_text_message(f"AI 服务暂时不可用，请稍后重试。错误: {str(e)}")

        # 检查 LLM 是否出错
        if llm_result.get("intent") == "error":
            return self._create_text_message(llm_result.get("response", "服务暂时不可用"))

        # Step 3: 解析 LLM 决策
        recommended_action = llm_result.get("recommended_action", "analyze-story-context")
        follow_up_actions = llm_result.get("follow_up_actions") or []
        requires_confirmation_before = llm_result.get("requires_confirmation_before", False)
        requires_confirmation_after = llm_result.get("requires_confirmation_after", False)
        response_text = llm_result.get("response", "")
        intent = llm_result.get("intent", "general_chat")
        response_mode = llm_result.get("response_mode", "execute")
        orchestration_meta = self._build_orchestration_meta(llm_result)

        # 根据 automation_mode 覆盖确认逻辑
        automation_mode = self._get_automation_mode()
        if automation_mode == "auto":
            requires_confirmation_before = False
            requires_confirmation_after = False
        elif automation_mode == "step":
            requires_confirmation_before = True
            requires_confirmation_after = True
        # "semi" 保持 LLM 决策原值

        # 如果 LLM 明确要求先回答或澄清，则避免盲目执行。
        if response_text and (intent in ["greeting", "general_chat", "introduction"] or response_mode == "answer"):
            return self._create_text_message(response_text)

        # 获取对应的 Subagent
        subagent = self._resolve_subagent(recommended_action, intent, project_context)

        # 编排层先检查关键上下文，避免把明显不满足条件的请求直接扔给 subagent。
        missing_context = self._validate_subagent_context(subagent, project_context, llm_result)
        if missing_context:
            return self._create_text_message(
                response_text
                or "这一步暂时还不能继续，当前缺少：{0}。".format("、".join(missing_context))
            )

        # 如果需要执行前确认，先返回计划卡片
        if requires_confirmation_before:
            return self._create_plan_message_with_response(
                subagent,
                project_context,
                response_text,
                orchestration_meta=orchestration_meta,
            )

        # Step 4: 运行 Subagent
        result = self._run_subagent(subagent, project_context)

        # Step 5: 检查是否需要结果后确认（写入）
        if requires_confirmation_after or subagent.requires_confirmation_after_result():
            if result.write_operations:
                return self._create_confirm_message(
                    subagent,
                    result,
                    response_text,
                    orchestration_meta=orchestration_meta,
                )

        # Step 6: 创建结果消息
        if follow_up_actions and response_mode == "plan" and response_text:
            response_text = "{0} 后续建议：{1}".format(
                response_text.rstrip("。"),
                " -> ".join(self._action_label(item) for item in follow_up_actions[:3]),
            )
        return self._create_result_message(
            result,
            response_text,
            task_type=subagent.task_type.value,
            orchestration_meta=orchestration_meta,
        )

    def run_with_confirmation(
        self,
        subagent_name: str,
        confirmed: bool,
        modifications: Optional[Dict[str, Any]] = None
    ) -> DirectorAgentMessage:
        """
        执行确认后的操作

        Args:
            subagent_name: Subagent 名称
            confirmed: 用户是否确认
            modifications: 用户修改的参数

        Returns:
            DirectorAgentMessage: Agent 回复消息
        """
        if not confirmed:
            return self._create_rejected_message(subagent_name)

        subagent = self.subagents.get(subagent_name)
        if not subagent:
            return self._create_error_message(f"Unknown subagent: {subagent_name}")

        project_context = self._load_or_build_context()
        result = self._run_subagent(subagent, project_context, modifications)

        # 如果需要写入确认
        if subagent.requires_confirmation_after_result() and result.write_operations:
            return self._create_confirm_message(subagent, result)

        return self._create_result_message(result, task_type=subagent.task_type.value)

    def execute_write(
        self,
        subagent_name: str,
        confirmed: bool,
        modifications: Optional[Dict[str, Any]] = None
    ) -> DirectorAgentMessage:
        """
        执行写入操作

        Args:
            subagent_name: Subagent 名称
            confirmed: 用户是否确认写入
            modifications: 用户修改的参数

        Returns:
            DirectorAgentMessage: Agent 回复消息
        """
        if not confirmed:
            return self._create_cancelled_write_message(subagent_name)

        subagent = self.subagents.get(subagent_name)
        if not subagent:
            return self._create_error_message(f"Unknown subagent: {subagent_name}")

        project_context = self._load_or_build_context()
        result = self._run_subagent(subagent, project_context, modifications)

        # 执行写入
        write_result = self._execute_write_operations(result)

        return self._create_write_result_message(result, write_result)

    # ---- 私有方法 ----

    def _load_or_build_context(self) -> ProjectContext:
        """加载或构建项目上下文"""
        # 从 session 获取 context_snapshot
        context_json = self.session_obj.context_snapshot_json
        if context_json:
            try:
                data = json.loads(context_json)
                script_id = data.get("script_id") or self.session_obj.script_id
                episode_id = data.get("episode_id") or self.session_obj.episode_id
                return self.context_builder.build(self.session, script_id, episode_id)
            except:
                pass

        # 重新构建
        return self.context_builder.build(
            self.session,
            self.session_obj.script_id,
            self.session_obj.episode_id,
        )

    def _classify_user_intent(self, message: str, context: ProjectContext) -> UserIntent:
        """分类用户意图"""
        msg_lower = message.lower()

        # 意图关键词匹配
        if any(kw in msg_lower for kw in ["分析", "当前阶段", "什么阶段", "状态"]):
            return UserIntent.SCRIPT_ANALYSIS

        if any(kw in msg_lower for kw in ["拆分", "拆解", "片段", "分割剧情"]):
            return UserIntent.SEGMENT_PLANNING

        if any(kw in msg_lower for kw in ["分镜", "拆镜", "生成分镜", "规划分镜"]):
            return UserIntent.STORYBOARD_PLANNING

        if any(kw in msg_lower for kw in ["图片", "生成图", "生图"]):
            return UserIntent.IMAGE_GENERATION

        if any(kw in msg_lower for kw in ["视频", "生成视频", "生视频"]):
            return UserIntent.VIDEO_GENERATION

        if any(kw in msg_lower for kw in ["配音", "语音"]):
            return UserIntent.DUBBING_PLANNING

        # 根据上下文推断
        if context.stage == ProjectStage.PROJECT_EMPTY:
            return UserIntent.SCRIPT_ANALYSIS
        elif context.stage == ProjectStage.SCRIPT_READY:
            if not context.episode or not context.episode.has_source_text:
                return UserIntent.SCRIPT_ANALYSIS
            return UserIntent.STORYBOARD_PLANNING
        elif context.stage == ProjectStage.SEGMENTS_READY:
            return UserIntent.STORYBOARD_PLANNING

        return UserIntent.GENERAL_CHAT

    def _select_subagent(self, intent: UserIntent, context: ProjectContext) -> Subagent:
        """选择 Subagent"""
        # 根据意图选择
        if intent == UserIntent.SCRIPT_ANALYSIS:
            return self.subagents["analyze-story-context"]

        if intent == UserIntent.SEGMENT_PLANNING:
            return self.subagents["split-story-segments"]

        if intent == UserIntent.STORYBOARD_PLANNING:
            return self.subagents["plan-storyboard"]

        # 默认分析
        return self.subagents["analyze-story-context"]

    def _run_subagent(
        self,
        subagent: Subagent,
        context: ProjectContext,
        modifications: Optional[Dict[str, Any]] = None
    ) -> SubagentResult:
        """运行 Subagent"""
        return subagent.run(context)

    def _execute_write_operations(self, result: SubagentResult) -> Dict[str, Any]:
        """执行写入操作"""
        write_results = []

        for op in result.write_operations:
            if op.target == "panels":
                # 获取 episode_id
                episode_id = self.session_obj.episode_id
                if not episode_id:
                    write_results.append({"success": False, "error": "No episode_id"})
                    continue

                # 提交 panel_drafts
                commit_result = self.panel_writer.commit_panel_drafts(
                    session=self.session,
                    episode_id=episode_id,
                    panel_drafts=op.data,
                    sync_resources=op.sync_resources,
                    replace_existing=op.replace_existing,
                )

                write_results.append({
                    "success": commit_result.success,
                    "panels_created": commit_result.panels_created,
                    "resources_synced": commit_result.resources_synced,
                    "warnings": commit_result.warnings,
                })
            elif op.target == "resources":
                from models import Team
                from services.resource_service import create_resource as create_resource_service

                team = self.session.get(Team, self.session_obj.team_id)
                if not team:
                    write_results.append({"success": False, "error": "No team found"})
                    continue

                assets = op.data or {}
                created_count = 0
                for resource_type, key in (
                    ("character", "characters"),
                    ("scene", "scenes"),
                    ("prop", "props"),
                ):
                    for item in assets.get(key, []) or []:
                        name = str(item.get("name") or item.get("label") or "").strip()
                        if not name:
                            continue
                        create_resource_service(
                            self.session,
                            team,
                            script_id=self.session_obj.script_id,
                            resource_type=resource_type,
                            name=name,
                            file_url=str(item.get("file_url") or "").strip(),
                            trigger_word=str(item.get("trigger_word") or "").strip() or None,
                            aliases=item.get("aliases") or [],
                            description=str(item.get("description") or item.get("summary") or "").strip() or None,
                            owner_user_id=int(self.session_obj.user_id),
                        )
                        created_count += 1

                write_results.append({
                    "success": True,
                    "resources_created": created_count,
                    "warnings": [],
                })

        return {"operations": write_results}

    def _create_plan_message(
        self,
        subagent: Subagent,
        context: ProjectContext,
        orchestration_meta: Optional[Dict[str, Any]] = None,
    ) -> DirectorAgentMessage:
        """创建计划卡片消息"""
        preview = {}
        if hasattr(subagent, "get_preview"):
            preview = subagent.get_preview(context)

        payload = self.confirmation_gate.create_plan_message(subagent, preview)
        payload_dict = payload.to_dict()
        if orchestration_meta:
            payload_dict.setdefault("preview", {})
            payload_dict["preview"]["orchestration"] = orchestration_meta

        message = DirectorAgentMessage(
            session_id=self.session_obj.id,
            role="agent",
            content=payload.description,
            message_type="plan",
            payload_json=json.dumps(payload_dict, ensure_ascii=False),
            task_type=subagent.task_type.value,
            task_status="pending",
            requires_confirmation=True,
            confirmation_status="pending",
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _create_plan_message_with_response(
        self,
        subagent: Subagent,
        context: ProjectContext,
        llm_response: str,
        orchestration_meta: Optional[Dict[str, Any]] = None,
    ) -> DirectorAgentMessage:
        """创建带 LLM 回复的计划卡片消息"""
        preview = {}
        if hasattr(subagent, "get_preview"):
            preview = subagent.get_preview(context)

        payload = self.confirmation_gate.create_plan_message(subagent, preview)
        payload_dict = payload.to_dict()
        if orchestration_meta:
            payload_dict.setdefault("preview", {})
            payload_dict["preview"]["orchestration"] = orchestration_meta

        # 同时保存 LLM 的原始回复
        message = DirectorAgentMessage(
            session_id=self.session_obj.id,
            role="agent",
            content=llm_response or payload.description,
            message_type="plan",
            payload_json=json.dumps(payload_dict, ensure_ascii=False),
            task_type=subagent.task_type.value,
            task_status="pending",
            requires_confirmation=True,
            confirmation_status="pending",
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _create_text_message(self, content: str) -> DirectorAgentMessage:
        """创建普通文本消息"""
        message = DirectorAgentMessage(
            session_id=self.session_obj.id,
            role="agent",
            content=content,
            message_type="text",
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _create_confirm_message(
        self,
        subagent: Subagent,
        result: SubagentResult,
        llm_response: str = "",
        orchestration_meta: Optional[Dict[str, Any]] = None,
    ) -> DirectorAgentMessage:
        """创建确认卡片消息"""
        if not result.write_operations:
            return self._create_result_message(
                result,
                llm_response,
                task_type=subagent.task_type.value,
                orchestration_meta=orchestration_meta,
            )

        write_op = result.write_operations[0]
        payload = self.confirmation_gate.create_confirm_message(result, write_op.to_dict())
        payload_dict = payload.to_dict()
        if orchestration_meta:
            payload_dict["orchestration"] = orchestration_meta

        message = DirectorAgentMessage(
            session_id=self.session_obj.id,
            role="agent",
            content=llm_response or payload.description,
            message_type="confirm",
            payload_json=json.dumps(payload_dict, ensure_ascii=False),
            task_type=subagent.task_type.value,
            task_status="pending",
            requires_confirmation=True,
            confirmation_status="pending",
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _create_result_message(
        self,
        result: SubagentResult,
        llm_response: str = "",
        *,
        task_type: str = "mixed_workflow",
        orchestration_meta: Optional[Dict[str, Any]] = None,
    ) -> DirectorAgentMessage:
        """创建结果卡片消息"""
        payload = self.confirmation_gate.create_result_message(result)
        payload_dict = payload.to_dict()
        if orchestration_meta:
            payload_dict["orchestration"] = orchestration_meta

        # 优先使用 LLM 回复，否则使用 result.summary
        content = llm_response if llm_response else result.summary

        message = DirectorAgentMessage(
            session_id=self.session_obj.id,
            role="agent",
            content=content,
            message_type="result",
            payload_json=json.dumps(payload_dict, ensure_ascii=False),
            task_type=task_type or "mixed_workflow",
            task_status="completed" if result.success else "failed",
            requires_confirmation=False,
            confirmation_status=None,
            execution_result_json=json.dumps(result.data, ensure_ascii=False) if result.data else None,
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _collect_recent_messages(self, limit: int = 8) -> List[Dict[str, str]]:
        items = self.session.exec(
            select(DirectorAgentMessage)
            .where(DirectorAgentMessage.session_id == self.session_obj.id)
            .order_by(DirectorAgentMessage.created_at.desc(), DirectorAgentMessage.id.desc())
            .limit(limit)
        ).all()
        result: List[Dict[str, str]] = []
        for item in reversed(items):
            content = str(item.content or "").strip()
            if not content:
                continue
            result.append({"role": item.role, "content": content})
        return result

    def _build_available_actions(self, context: ProjectContext) -> List[str]:
        actions = ["analyze-story-context"]
        if context.episode and context.episode.has_source_text:
            actions.extend(["split-story-segments", "plan-storyboard", "extract-project-assets"])
        if context.panels_summary.total > 0:
            actions.append("generate-panel-image")
        if context.panels_summary.with_images > 0:
            actions.extend(["generate-panel-video", "generate-episode-dubbing"])
        deduped: List[str] = []
        for action in actions:
            if action in self.subagents and action not in deduped:
                deduped.append(action)
        return deduped

    def _resolve_subagent(self, recommended_action: str, intent: str, context: ProjectContext) -> Subagent:
        subagent = self.subagents.get(recommended_action)
        if subagent:
            return subagent
        intent_map = {
            "segment_planning": "split-story-segments",
            "storyboard_planning": "plan-storyboard",
            "image_generation": "generate-panel-image",
            "video_generation": "generate-panel-video",
            "dubbing_planning": "generate-episode-dubbing",
            "asset_extraction": "extract-project-assets",
        }
        return self.subagents.get(intent_map.get(intent, ""), self.subagents["analyze-story-context"])

    def _validate_subagent_context(
        self,
        subagent: Subagent,
        context: ProjectContext,
        llm_result: Dict[str, Any],
    ) -> List[str]:
        missing: List[str] = []
        if hasattr(subagent, "check_context"):
            missing.extend(subagent.check_context(context))
        for item in llm_result.get("context_missing") or []:
            if item and item not in missing:
                missing.append(item)
        return missing

    def _build_orchestration_meta(self, llm_result: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "response_mode": llm_result.get("response_mode") or "execute",
            "recommended_action": llm_result.get("recommended_action") or "analyze-story-context",
            "follow_up_actions": list(llm_result.get("follow_up_actions") or [])[:3],
            "confidence": llm_result.get("confidence"),
            "reasoning_summary": llm_result.get("reasoning_summary") or "",
            "plan": llm_result.get("plan") if isinstance(llm_result.get("plan"), dict) else {},
        }

    def _action_label(self, action: str) -> str:
        labels = {
            "analyze-story-context": "分析项目状态",
            "split-story-segments": "拆分剧情片段",
            "plan-storyboard": "生成分镜方案",
            "extract-project-assets": "提取共享资产",
            "generate-panel-image": "生成分镜图片",
            "generate-panel-video": "生成分镜视频",
            "generate-episode-dubbing": "生成剧集配音",
        }
        return labels.get(action, action)

    def _create_rejected_message(self, subagent_name: str) -> DirectorAgentMessage:
        """创建拒绝消息"""
        message = DirectorAgentMessage(
            session_id=self.session_obj.id,
            role="agent",
            content="已取消操作",
            message_type="text",
            task_type="mixed_workflow",
            task_status="rejected",
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _create_cancelled_write_message(self, subagent_name: str) -> DirectorAgentMessage:
        """创建取消写入消息"""
        message = DirectorAgentMessage(
            session_id=self.session_obj.id,
            role="agent",
            content="已取消写入操作，分镜数据未保存",
            message_type="text",
            task_type="mixed_workflow",
            task_status="rejected",
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _create_write_result_message(
        self,
        result: SubagentResult,
        write_result: Dict[str, Any]
    ) -> DirectorAgentMessage:
        """创建写入结果消息"""
        # 统计写入结果
        total_panels = 0
        for op_result in write_result.get("operations", []):
            total_panels += op_result.get("panels_created", 0)

        summary = f"写入完成！共创建 {total_panels} 个分镜"

        # 构建 next_actions（从字符串列表转换为 NextAction 对象列表）
        from ..schemas.message_schemas import NextAction
        next_actions = []
        for action in result.next_actions:
            next_actions.append(NextAction(
                label=action,
                action=self._action_to_intent(action),
            ))

        # 构建思维链/工具链
        task_chain = self._build_task_chain(result)

        result_payload = ResultPayload(
            status="completed",
            summary=summary,
            items_created=total_panels,
            warnings=result.warnings,
            next_actions=next_actions,
            refresh_hints={"panels": True, "resources": True},
            task_chain=task_chain,
        )

        message = DirectorAgentMessage(
            session_id=self.session_obj.id,
            role="agent",
            content=summary,
            message_type="result",
            payload_json=json.dumps(result_payload.to_dict(), ensure_ascii=False),
            task_type=result.data.get("task_type", "mixed_workflow") if result.data else "mixed_workflow",
            task_status="completed",
            requires_confirmation=False,
            confirmation_status="confirmed",
            execution_result_json=json.dumps(write_result, ensure_ascii=False),
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _create_error_message(self, error: str) -> DirectorAgentMessage:
        """创建错误消息"""
        message = DirectorAgentMessage(
            session_id=self.session_obj.id,
            role="agent",
            content=f"执行出错: {error}",
            message_type="text",
            task_type="mixed_workflow",
            task_status="failed",
        )
        self.session.add(message)
        self.session.commit()
        self.session.refresh(message)
        return message

    def _action_to_intent(self, action: str) -> str:
        """将操作文本转换为意图标识"""
        action_lower = action.lower()
        if "分镜" in action_lower:
            return "plan-storyboard"
        if "片段" in action_lower:
            return "split-story-segments"
        if "图片" in action_lower:
            return "image-generation"
        if "视频" in action_lower:
            return "video-generation"
        if "配音" in action_lower:
            return "dubbing"
        return "general"

    def _build_task_chain(self, result: SubagentResult) -> List[Dict[str, Any]]:
        """构建思维链/工具链数据"""
        from ..schemas.message_schemas import NextAction

        task_chain = []
        task_id = result.data.get("task_type", "unknown") if result.data else "unknown"

        # 根据任务类型获取标题
        task_titles = {
            "analyze-story-context": "分析项目阶段",
            "split-story-segments": "拆分剧情片段",
            "plan-storyboard": "规划分镜方案",
            "script_analysis": "分析剧本",
            "segment_planning": "规划片段",
            "storyboard_planning": "规划分镜",
        }
        task_title = task_titles.get(task_id, "执行任务")

        # 提取工具
        tools = self._extract_tools_from_result(result)

        # 构建子任务
        subtasks = self._build_subtasks_from_result(result)

        task_chain.append({
            "id": task_id,
            "title": task_title,
            "description": result.summary,
            "status": "completed" if result.success else "failed",
            "priority": "high",
            "tools": tools,
            "dependencies": [],
            "subtasks": subtasks,
        })

        return task_chain

    def _extract_tools_from_result(self, result: SubagentResult) -> List[str]:
        """从结果中提取工具使用"""
        tools = []
        if result.data:
            if result.data.get("panel_drafts"):
                tools.extend(["plan-storyboard", "write_panels", "read_project", "dispatch_subagent"])
            elif result.data.get("segments"):
                tools.extend(["split-story-segments", "read_project", "dispatch_subagent"])
            elif result.data.get("characters") or result.data.get("scenes"):
                tools.extend(["analyze-story-context", "read_project", "dispatch_subagent"])
        if not tools:
            tools = ["dispatch_subagent", "read_project"]
        return list(set(tools))[:5]

    def _build_subtasks_from_result(self, result: SubagentResult) -> List[Dict[str, Any]]:
        """从结果构建子任务"""
        subtasks = []

        if not result.data:
            return subtasks

        if result.data.get("panel_drafts"):
            panel_count = len(result.data.get("panel_drafts", []))
            subtasks = [
                {
                    "id": "1",
                    "title": "解析剧本文本",
                    "description": "将剧本文本解析为结构化片段",
                    "status": "completed",
                    "priority": "high",
                    "tools": ["script_parser"],
                },
                {
                    "id": "2",
                    "title": "提取角色和场景",
                    "description": "从剧本中识别并提取角色和场景信息",
                    "status": "completed",
                    "priority": "high",
                    "tools": ["project_reader"],
                },
                {
                    "id": "3",
                    "title": f"生成分镜方案 ({panel_count} 个分镜)",
                    "description": "基于解析结果生成分镜草稿",
                    "status": "completed" if result.success else "in-progress",
                    "priority": "high",
                    "tools": ["dispatch_subagent"],
                },
                {
                    "id": "4",
                    "title": "写入数据库",
                    "description": "将分镜方案写入项目数据库",
                    "status": "completed" if result.success else "pending",
                    "priority": "high",
                    "tools": ["write_panels"],
                },
            ]
        elif result.data.get("segments"):
            segment_count = len(result.data.get("segments", []))
            subtasks = [
                {
                    "id": "1",
                    "title": "分析剧本结构",
                    "description": "识别剧本中的剧情节点和转折点",
                    "status": "completed",
                    "priority": "high",
                    "tools": ["script_parser"],
                },
                {
                    "id": "2",
                    "title": f"拆分剧情片段 ({segment_count} 个片段)",
                    "description": "将剧本拆分为独立的剧情片段",
                    "status": "completed" if result.success else "in-progress",
                    "priority": "high",
                    "tools": ["dispatch_subagent"],
                },
            ]

        return subtasks

    def _get_automation_mode(self) -> str:
        """从 session_config_json 读取工作模式，默认 semi"""
        try:
            config = self.session_obj.session_config_json
            if config:
                data = json.loads(config) if isinstance(config, str) else config
                return data.get("automation_mode", "semi")
        except Exception:
            pass
        return "semi"
