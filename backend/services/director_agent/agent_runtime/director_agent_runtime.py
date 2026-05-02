"""DirectorAgentRuntime - DeepSeek Agent SDK 风格的编排器

对标 ArcReil 的 Claude Agent SDK 编排能力：
- 轻量级 Director：只持有项目状态摘要 + 对话历史
- Tool 调用：dispatch_subagent, read_project, write_panels, ask_confirmation
- Phase-based 状态检测
"""
import json
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field

from langchain.agents import Agent
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import Tool
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage

from core.config import settings
from services.director_agent.schemas.orchestrator_schemas import ProjectContext, ProjectStage
from services.director_agent.agent_runtime.tool_definitions import (
    DispatchTool,
    ReadProjectTool,
    WritePanelsTool,
    AskConfirmationTool,
)


# Agent System Prompt
AGENT_SYSTEM_PROMPT = """你是神鹿AI导演，一个专业的视频内容创作助手。

## 你的职责
1. 理解用户需求
2. 分析当前项目状态
3. 决定下一步操作
4. 在必要时请求用户确认

## 项目阶段
- project_empty: 项目为空，无剧本
- script_ready: 剧本已就绪，可以开始创作
- segments_ready: 片段已拆分，可生成分镜
- storyboard_ready: 分镜已生成，等待生成媒体
- has_images: 部分分镜已有图片
- has_videos: 已有视频内容

## 可用工具
1. dispatch_subagent: 派发专注任务给 subagent
2. read_project: 读取项目当前状态
3. write_panels: 写入分镜到数据库
4. ask_confirmation: 请求用户确认

## 重要原则
- 先理解用户需求，再决定操作
- 如果缺少必要上下文，先告知用户
- 高成本操作（写入项目、生成媒体）需要用户确认
- 保持对话简洁专业
"""


@dataclass
class Turn:
    """对话轮次"""
    type: str  # "user" | "assistant" | "tool" | "system"
    content: str
    tool_calls: List[Dict] = field(default_factory=list)
    tool_results: List[Dict] = field(default_factory=list)


class DirectorAgentRuntime:
    """神鹿AI导演 Agent 运行时

    使用 LangChain + DeepSeek 实现对标 ArcReil 的 Agent SDK 编排能力
    """

    def __init__(self, session_id: int, script_id: int, episode_id: Optional[int] = None):
        self.session_id = session_id
        self.script_id = script_id
        self.episode_id = episode_id

        # LangChain DeepSeek LLM
        self.llm = self._create_llm()

        # Tools
        self.tools = self._create_tools()

        # Agent
        self.agent = self._create_agent()

        # Conversation history
        self.turns: List[Turn] = []

        # Pending confirmation
        self.pending_confirmation: Optional[Dict] = None

    def _create_llm(self):
        """创建 DeepSeek LLM"""
        try:
            from langchain_deepseek import ChatDeepSeek
            return ChatDeepSeek(
                model="deepseek-v4-flash",
                api_key=settings.DEEPSEEK_API_KEY,
                temperature=0.7,
                model_kwargs={"thinking": {"type": "disabled"}},
            )
        except ImportError:
            # Fallback to direct OpenAI compatible API
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model="deepseek-v4-flash",
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
                temperature=0.7,
                model_kwargs={"thinking": {"type": "disabled"}},
            )

    def _create_tools(self) -> List[Tool]:
        """创建 Agent Tools"""
        return [
            Tool(
                name="dispatch_subagent",
                description="派发专注任务给 subagent。输入 subagent 名称和任务参数。",
                func=self._dispatch_subagent,
            ),
            Tool(
                name="read_project",
                description="读取项目当前状态，包括剧本、剧集、分镜、资产等信息。",
                func=self._read_project,
            ),
            Tool(
                name="write_panels",
                description="写入分镜数据到数据库。输入分镜列表。",
                func=self._write_panels,
            ),
            Tool(
                name="ask_confirmation",
                description="请求用户确认操作。输入确认类型和描述。",
                func=self._ask_confirmation,
            ),
        ]

    def _create_agent(self) -> Agent:
        """创建 LangChain Agent"""
        from langchain.agents import create_structured_chat_agent

        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=AGENT_SYSTEM_PROMPT),
            MessagesPlaceholder(variable_name="chat_history", optional=True),
            HumanMessage(content="{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ])

        agent = create_structured_chat_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt,
        )

        return agent

    def _dispatch_subagent(self, input_str: str) -> str:
        """派发 subagent 任务"""
        # 解析输入
        try:
            if isinstance(input_str, str):
                data = json.loads(input_str)
            else:
                data = input_str
        except json.JSONDecodeError:
            data = {"subagent": input_str}

        subagent_name = data.get("subagent", "")
        context = data.get("context", {})

        # 获取 subagent
        from services.director_agent.subagent import SUBAGENT_REGISTRY
        subagent = SUBAGENT_REGISTRY.get(subagent_name)

        if not subagent:
            return f"Unknown subagent: {subagent_name}"

        # 执行 subagent
        try:
            # 构建 ProjectContext
            project_context = self._build_project_context()

            # 运行 subagent
            result = subagent.run(project_context)

            return json.dumps({
                "success": result.success,
                "summary": result.summary,
                "data": result.data,
                "warnings": result.warnings,
                "next_actions": result.next_actions,
            }, ensure_ascii=False)
        except Exception as e:
            return f"Subagent execution error: {str(e)}"

    def _read_project(self, input_str: str = "") -> str:
        """读取项目状态"""
        try:
            project_context = self._build_project_context()
            return json.dumps(project_context.to_dict(), ensure_ascii=False, default=str)
        except Exception as e:
            return f"Read project error: {str(e)}"

    def _write_panels(self, input_str: str) -> str:
        """写入分镜"""
        try:
            data = json.loads(input_str)
            panel_drafts = data.get("panels", [])
            sync_resources = data.get("sync_resources", True)

            # 调用 panel_writer
            from services.director_agent.tools.panel_writer import PanelWriterTool
            writer = PanelWriterTool()

            result = writer.commit_panel_drafts(
                session=None,  # 会从 context 获取
                episode_id=self.episode_id,
                panel_drafts=panel_drafts,
                sync_resources=sync_resources,
                replace_existing=False,
            )

            return json.dumps({
                "success": result.success,
                "panels_created": result.panels_created,
                "resources_synced": result.resources_synced,
                "warnings": result.warnings,
            }, ensure_ascii=False)
        except Exception as e:
            return f"Write panels error: {str(e)}"

    def _ask_confirmation(self, input_str: str) -> str:
        """请求用户确认"""
        try:
            data = json.loads(input_str)
            self.pending_confirmation = {
                "type": data.get("type", "confirm"),
                "title": data.get("title", "确认操作"),
                "description": data.get("description", ""),
                "impact": data.get("impact", {}),
            }
            return json.dumps({
                "pending": True,
                "confirmation": self.pending_confirmation,
            }, ensure_ascii=False)
        except Exception as e:
            return f"Ask confirmation error: {str(e)}"

    def _build_project_context(self) -> ProjectContext:
        """构建项目上下文"""
        from services.director_agent.tools.project_reader import ProjectReaderTool

        reader = ProjectReaderTool()
        from database import get_session

        gen = get_session()
        session = next(gen)

        try:
            return reader.get_project_context(session, self.script_id, self.episode_id)
        finally:
            try:
                next(gen)
            except StopIteration:
                pass

    def run(self, user_message: str) -> Dict[str, Any]:
        """运行 Agent 处理用户消息"""
        from langchain.agents import AgentExecutor

        # 创建 Agent Executor
        agent_executor = AgentExecutor(
            agent=self.agent,
            tools=self.tools,
            verbose=True,
            handle_parsing_errors=True,
        )

        try:
            # 执行 Agent
            result = agent_executor.invoke({
                "input": user_message,
                "chat_history": self._get_chat_history(),
            })

            response = result.get("output", "")

            # 检查是否有 pending confirmation
            if self.pending_confirmation:
                return {
                    "type": "confirmation",
                    "content": response,
                    "confirmation": self.pending_confirmation,
                }

            return {
                "type": "text",
                "content": response,
            }

        except Exception as e:
            return {
                "type": "error",
                "content": f"Agent execution error: {str(e)}",
            }

    def _get_chat_history(self) -> List:
        """获取对话历史"""
        history = []
        for turn in self.turns[-10:]:  # 最近 10 轮
            if turn.type == "user":
                history.append(HumanMessage(content=turn.content))
            elif turn.type == "assistant":
                history.append(AIMessage(content=turn.content))
        return history

    def add_turn(self, turn: Turn):
        """添加对话轮次"""
        self.turns.append(turn)

    def get_pending_confirmation(self) -> Optional[Dict]:
        """获取待确认信息"""
        return self.pending_confirmation

    def clear_pending_confirmation(self):
        """清除待确认信息"""
        self.pending_confirmation = None
