"""Tool: LLM Agent planner for Shenlu director orchestration."""
import json
import re
from typing import Any, Callable, Dict, List, Optional

from openai import OpenAI

from core.config import settings


SUPPORTED_ACTIONS = [
    "analyze-story-context",
    "split-story-segments",
    "plan-storyboard",
    "extract-project-assets",
    "generate-panel-image",
    "generate-panel-video",
    "generate-episode-dubbing",
]

ACTION_ALIASES = {
    "analyze": "analyze-story-context",
    "analyze-story-context": "analyze-story-context",
    "script_analysis": "analyze-story-context",
    "status": "analyze-story-context",
    "read_project_context": "analyze-story-context",
    "split": "split-story-segments",
    "split-story-segments": "split-story-segments",
    "segment_planning": "split-story-segments",
    "split_story_segments": "split-story-segments",
    "plan-storyboard": "plan-storyboard",
    "storyboard_planning": "plan-storyboard",
    "parse_story_segments": "plan-storyboard",
    "extract-project-assets": "extract-project-assets",
    "extract_assets": "extract-project-assets",
    "asset_extraction": "extract-project-assets",
    "generate-panel-image": "generate-panel-image",
    "generate_image": "generate-panel-image",
    "image_generation": "generate-panel-image",
    "generate-panel-video": "generate-panel-video",
    "generate_video": "generate-panel-video",
    "video_generation": "generate-panel-video",
    "generate-episode-dubbing": "generate-episode-dubbing",
    "generate_dubbing": "generate-episode-dubbing",
    "dubbing_planning": "generate-episode-dubbing",
}

ACTION_LABELS = {
    "analyze-story-context": "分析项目状态",
    "split-story-segments": "拆分剧情片段",
    "plan-storyboard": "生成分镜方案",
    "extract-project-assets": "提取角色场景道具",
    "generate-panel-image": "生成分镜图片",
    "generate-panel-video": "生成分镜视频",
    "generate-episode-dubbing": "生成剧集配音",
}

ACTION_CONFIRMATION_DEFAULTS = {
    "analyze-story-context": (False, False),
    "split-story-segments": (True, False),
    "plan-storyboard": (True, True),
    "extract-project-assets": (False, True),
    "generate-panel-image": (False, False),
    "generate-panel-video": (False, False),
    "generate-episode-dubbing": (False, False),
}

RESPONSE_MODES = {"answer", "clarify", "plan", "execute"}

CENTRAL_AGENT_SYSTEM_PROMPT = """你是神鹿 AI Director 的编排器，不是单纯聊天机器人。

你的工作像一个优秀的创作总控：
1. 先压缩理解上下文，只抓和当前请求最相关的事实
2. 把复杂需求拆成最少的几个可执行步骤
3. 只选择“当前第一步”去执行，不要一次把所有动作混在一起
4. 明确哪些步骤需要确认、哪些可以直接继续
5. 如果上下文不足，先用最短的话问清或指出阻塞点

请始终输出 JSON，不要输出 Markdown。

输出结构：
{
  "reasoning": "简短推理，不要冗长",
  "reasoning_summary": "给前端展示的一句话总结",
  "intent": "greeting/script_analysis/segment_planning/storyboard_planning/image_generation/video_generation/dubbing_planning/asset_extraction/general_chat/mixed_workflow",
  "response_mode": "answer/clarify/plan/execute",
  "recommended_action": "当前第一步动作",
  "follow_up_actions": ["后续动作1", "后续动作2"],
  "requires_confirmation_before": true,
  "requires_confirmation_after": false,
  "context_missing": ["缺失项"],
  "confidence": 0.0,
  "response": "面向用户的简洁回复",
  "plan": {
    "goal": "整体目标",
    "why_this_first_step": "为什么先做这一步",
    "steps": [
      {"id": "step_1", "action": "动作", "goal": "步骤目标", "needs_confirmation": true}
    ],
    "expected_outcome": "完成这一轮后用户会得到什么"
  }
}

规则：
- 如果用户是闲聊、问你是谁、问项目状态，优先 answer
- 如果缺少剧本、分镜或图片等关键前置条件，优先 clarify
- 如果用户要求的是多步复杂任务，输出 plan，但 recommended_action 只给第一步
- follow_up_actions 只保留 1-3 个最关键动作
- 不要发明不存在的动作，只能从 available_actions 中选
- 对高风险写入或批量生成，要把确认点说清楚
"""


class LLMAgentTool:
    """LLM planner with heuristic fallback and context compaction."""

    def __init__(self):
        self.api_key = settings.DEEPSEEK_API_KEY
        self.model = "deepseek-v4-flash"

    def reason(
        self,
        user_message: str,
        context: Dict[str, Any],
        *,
        available_actions: Optional[List[str]] = None,
        recent_messages: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        actions = self._sanitize_available_actions(available_actions)
        if not self.api_key:
            return self._heuristic_decision(
                user_message=user_message,
                context=context,
                available_actions=actions,
            )

        compact_context = self._compact_context_packet(context)
        user_content = json.dumps(
            {
                "project_context": compact_context,
                "recent_messages": self._compact_recent_messages(recent_messages),
                "available_actions": actions,
                "user_message": user_message,
            },
            ensure_ascii=False,
            indent=2,
        )

        try:
            client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com", timeout=60.0)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": CENTRAL_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.2,
                extra_body={"thinking": {"type": "disabled"}},
            )
            content = response.choices[0].message.content or "{}"
            result = self._extract_json(content)
            return self._normalize_decision(
                result,
                user_message=user_message,
                context=context,
                available_actions=actions,
            )
        except Exception:
            return self._heuristic_decision(
                user_message=user_message,
                context=context,
                available_actions=actions,
            )

    def stream_reason(
        self,
        user_message: str,
        context: Dict[str, Any],
        *,
        stream_callback: Optional[Callable[[str], None]] = None,
        available_actions: Optional[List[str]] = None,
        recent_messages: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        actions = self._sanitize_available_actions(available_actions)
        if not self.api_key:
            return self._heuristic_decision(
                user_message=user_message,
                context=context,
                available_actions=actions,
            )

        user_content = json.dumps(
            {
                "project_context": self._compact_context_packet(context),
                "recent_messages": self._compact_recent_messages(recent_messages),
                "available_actions": actions,
                "user_message": user_message,
            },
            ensure_ascii=False,
            indent=2,
        )

        try:
            client = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com", timeout=300.0)
            reasoning_buffer = ""
            content_buffer = ""

            with client.chat.completions.create(
                model="deepseek-v4-flash",
                messages=[
                    {"role": "system", "content": CENTRAL_AGENT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                stream=True,
                extra_body={"thinking": {"type": "enabled"}},
            ) as stream:
                for chunk in stream:
                    delta = chunk.choices[0].delta
                    if getattr(delta, "reasoning_content", None):
                        reasoning_buffer += delta.reasoning_content
                        if stream_callback:
                            stream_callback(reasoning_buffer)
                    if delta.content:
                        content_buffer += delta.content

            result = self._extract_json(content_buffer)
            result["reasoning"] = reasoning_buffer or result.get("reasoning") or ""
            return self._normalize_decision(
                result,
                user_message=user_message,
                context=context,
                available_actions=actions,
            )
        except Exception:
            return self._heuristic_decision(
                user_message=user_message,
                context=context,
                available_actions=actions,
            )

    def _sanitize_available_actions(self, available_actions: Optional[List[str]]) -> List[str]:
        cleaned: List[str] = []
        for action in available_actions or []:
            normalized = self._normalize_action(action, available_actions=SUPPORTED_ACTIONS)
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned or list(SUPPORTED_ACTIONS)

    def _compact_context_packet(self, context: Dict[str, Any]) -> Dict[str, Any]:
        script = context.get("script") or {}
        episode = context.get("episode") or {}
        panels = context.get("panels_summary") or {}
        resources = context.get("shared_resources") or {}
        return {
            "stage": context.get("stage") or "unknown",
            "script": {
                "name": script.get("name") or "",
                "has_source_text": bool(script.get("has_source_text")),
                "aspect_ratio": script.get("aspect_ratio") or "",
            },
            "episode": {
                "title": episode.get("title") or "",
                "sequence_num": episode.get("sequence_num"),
                "has_source_text": bool(episode.get("has_source_text")),
                "source_text_preview": episode.get("source_text_preview") or "",
            },
            "panels_summary": {
                "total": int(panels.get("total") or 0),
                "with_images": int(panels.get("with_images") or 0),
                "without_images": int(panels.get("without_images") or 0),
                "with_videos": int(panels.get("with_videos") or 0),
                "without_videos": int(panels.get("without_videos") or 0),
            },
            "shared_resources": {
                "characters": len(resources.get("characters") or []),
                "scenes": len(resources.get("scenes") or []),
                "props": len(resources.get("props") or []),
            },
            "missing_context": list(context.get("missing_context") or [])[:5],
        }

    def _compact_recent_messages(self, recent_messages: Optional[List[Dict[str, str]]]) -> List[Dict[str, str]]:
        compacted: List[Dict[str, str]] = []
        for item in recent_messages or []:
            role = str(item.get("role") or "").strip()
            content = " ".join(str(item.get("content") or "").split())
            if not role or not content:
                continue
            compacted.append({"role": role, "content": content[:180]})
        return compacted[-6:]

    def _normalize_decision(
        self,
        raw: Dict[str, Any],
        *,
        user_message: str,
        context: Dict[str, Any],
        available_actions: List[str],
    ) -> Dict[str, Any]:
        heuristic = self._heuristic_decision(
            user_message=user_message,
            context=context,
            available_actions=available_actions,
        )
        payload = raw if isinstance(raw, dict) else {}

        intent = str(payload.get("intent") or heuristic["intent"]).strip() or heuristic["intent"]
        recommended_action = self._normalize_action(
            payload.get("recommended_action"),
            available_actions=available_actions,
        ) or heuristic["recommended_action"]

        follow_up_actions = self._normalize_action_list(
            payload.get("follow_up_actions"),
            available_actions=available_actions,
            exclude={recommended_action},
        )
        if not follow_up_actions:
            follow_up_actions = heuristic.get("follow_up_actions", [])

        context_missing = self._normalize_string_list(payload.get("context_missing"))
        if not context_missing:
            context_missing = heuristic.get("context_missing", [])

        response_mode = str(payload.get("response_mode") or heuristic["response_mode"]).strip().lower()
        if response_mode not in RESPONSE_MODES:
            response_mode = heuristic["response_mode"]

        reasoning = str(payload.get("reasoning") or "").strip()
        reasoning_summary = str(payload.get("reasoning_summary") or "").strip()
        if not reasoning_summary:
            reasoning_summary = reasoning[:140] if reasoning else heuristic.get("reasoning_summary", "")

        response_text = str(payload.get("response") or "").strip() or heuristic["response"]
        confidence = self._normalize_confidence(payload.get("confidence"), default=heuristic.get("confidence", 0.6))

        requires_confirmation_before = self._normalize_bool(
            payload.get("requires_confirmation_before"),
            default=ACTION_CONFIRMATION_DEFAULTS.get(recommended_action, (False, False))[0],
        )
        requires_confirmation_after = self._normalize_bool(
            payload.get("requires_confirmation_after"),
            default=ACTION_CONFIRMATION_DEFAULTS.get(recommended_action, (False, False))[1],
        )

        plan = payload.get("plan") if isinstance(payload.get("plan"), dict) else {}
        normalized_plan = self._normalize_plan(
            plan=plan,
            recommended_action=recommended_action,
            follow_up_actions=follow_up_actions,
            response_text=response_text,
            response_mode=response_mode,
        )

        if context_missing and response_mode == "execute":
            response_mode = "clarify"
        if response_mode == "answer" and recommended_action != "analyze-story-context" and intent not in {"greeting", "general_chat"}:
            response_mode = "plan"

        return {
            "reasoning": reasoning or heuristic["reasoning"],
            "reasoning_summary": reasoning_summary or heuristic.get("reasoning_summary", ""),
            "intent": intent,
            "response_mode": response_mode,
            "recommended_action": recommended_action,
            "follow_up_actions": follow_up_actions,
            "requires_confirmation_before": requires_confirmation_before,
            "requires_confirmation_after": requires_confirmation_after,
            "context_missing": context_missing,
            "confidence": confidence,
            "response": response_text,
            "plan": normalized_plan,
        }

    def _normalize_plan(
        self,
        *,
        plan: Dict[str, Any],
        recommended_action: str,
        follow_up_actions: List[str],
        response_text: str,
        response_mode: str,
    ) -> Dict[str, Any]:
        raw_steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
        normalized_steps: List[Dict[str, Any]] = []
        for index, step in enumerate(raw_steps[:4], start=1):
            if not isinstance(step, dict):
                continue
            action = self._normalize_action(step.get("action"), available_actions=SUPPORTED_ACTIONS)
            if not action:
                continue
            normalized_steps.append(
                {
                    "id": str(step.get("id") or f"step_{index}"),
                    "action": action,
                    "label": ACTION_LABELS.get(action, action),
                    "goal": str(step.get("goal") or step.get("description") or "").strip(),
                    "needs_confirmation": self._normalize_bool(
                        step.get("needs_confirmation"),
                        default=ACTION_CONFIRMATION_DEFAULTS.get(action, (False, False))[0],
                    ),
                }
            )

        if not normalized_steps:
            ordered_actions = [recommended_action, *follow_up_actions]
            for index, action in enumerate(ordered_actions[:4], start=1):
                normalized_steps.append(
                    {
                        "id": f"step_{index}",
                        "action": action,
                        "label": ACTION_LABELS.get(action, action),
                        "goal": "执行{0}".format(ACTION_LABELS.get(action, action)),
                        "needs_confirmation": ACTION_CONFIRMATION_DEFAULTS.get(action, (False, False))[0],
                    }
                )

        return {
            "goal": str(plan.get("goal") or response_text or ACTION_LABELS.get(recommended_action, "")).strip(),
            "why_this_first_step": str(plan.get("why_this_first_step") or "").strip(),
            "steps": normalized_steps,
            "expected_outcome": str(plan.get("expected_outcome") or response_text or "").strip(),
            "response_mode": response_mode,
        }

    def _heuristic_decision(
        self,
        *,
        user_message: str,
        context: Dict[str, Any],
        available_actions: List[str],
    ) -> Dict[str, Any]:
        text = " ".join(str(user_message or "").strip().split())
        lowered = text.lower()
        stage = str(context.get("stage") or "").strip()
        episode = context.get("episode") or {}
        panels = context.get("panels_summary") or {}

        has_source_text = bool(episode.get("has_source_text"))
        panel_total = int(panels.get("total") or 0)
        with_images = int(panels.get("with_images") or 0)
        without_images = int(panels.get("without_images") or 0)
        without_videos = int(panels.get("without_videos") or 0)

        requested_actions = self._detect_requested_actions(lowered, available_actions)
        is_greeting = any(token in lowered for token in ["你好", "hello", "hi", "你是谁", "介绍一下"])
        asks_status = any(token in lowered for token in ["当前状态", "什么阶段", "项目状态", "看一下项目", "看看当前"]) and not requested_actions

        if is_greeting:
            return {
                "reasoning": "识别为闲聊或自我介绍请求。",
                "reasoning_summary": "先做对话性回复，不触发执行。",
                "intent": "greeting",
                "response_mode": "answer",
                "recommended_action": "analyze-story-context",
                "follow_up_actions": [],
                "requires_confirmation_before": False,
                "requires_confirmation_after": False,
                "context_missing": [],
                "confidence": 0.95,
                "response": "我是神鹿 AI Director，可以帮你看项目状态、拆镜、生成分镜、提取资产，以及衔接图片、视频和配音流程。",
                "plan": {},
            }

        if asks_status:
            return {
                "reasoning": "识别为项目状态查询。",
                "reasoning_summary": "先分析当前项目阶段，再给出下一步建议。",
                "intent": "script_analysis",
                "response_mode": "execute",
                "recommended_action": "analyze-story-context",
                "follow_up_actions": [],
                "requires_confirmation_before": False,
                "requires_confirmation_after": False,
                "context_missing": [],
                "confidence": 0.9,
                "response": "我先看一下当前项目所处阶段，再给你一个最合适的下一步建议。",
                "plan": {},
            }

        if not requested_actions:
            requested_actions = self._default_actions_from_stage(
                stage=stage,
                has_source_text=has_source_text,
                panel_total=panel_total,
                with_images=with_images,
                without_images=without_images,
                without_videos=without_videos,
                available_actions=available_actions,
            )

        recommended_action, follow_up_actions, missing_context = self._repair_action_chain(
            requested_actions=requested_actions,
            available_actions=available_actions,
            has_source_text=has_source_text,
            panel_total=panel_total,
            with_images=with_images,
            without_images=without_images,
            without_videos=without_videos,
        )

        intent = self._intent_from_action(recommended_action, requested_actions)
        response_mode = "execute"
        if missing_context:
            response_mode = "clarify"
        elif len([recommended_action, *follow_up_actions]) > 1:
            response_mode = "plan"

        before, after = ACTION_CONFIRMATION_DEFAULTS.get(recommended_action, (False, False))
        response = self._build_user_response(
            recommended_action=recommended_action,
            follow_up_actions=follow_up_actions,
            missing_context=missing_context,
            response_mode=response_mode,
        )
        plan = self._normalize_plan(
            plan={},
            recommended_action=recommended_action,
            follow_up_actions=follow_up_actions,
            response_text=response,
            response_mode=response_mode,
        )

        return {
            "reasoning": "使用本地规则对意图、前置条件和执行顺序做了修正。",
            "reasoning_summary": "先确定第一步动作，再保留最关键的后续步骤。",
            "intent": intent,
            "response_mode": response_mode,
            "recommended_action": recommended_action,
            "follow_up_actions": follow_up_actions,
            "requires_confirmation_before": before,
            "requires_confirmation_after": after,
            "context_missing": missing_context,
            "confidence": 0.72,
            "response": response,
            "plan": plan,
        }

    def _detect_requested_actions(self, lowered: str, available_actions: List[str]) -> List[str]:
        detected: List[str] = []
        keyword_map = [
            (["资产", "角色", "场景", "道具", "提取角色", "提取资产"], "extract-project-assets"),
            (["拆镜", "拆分镜头", "拆分剧情", "分段", "剧情片段"], "split-story-segments"),
            (["分镜", "镜头设计", "生成分镜", "做分镜"], "plan-storyboard"),
            (["出图", "生图", "图片", "配图", "画图"], "generate-panel-image"),
            (["视频", "动起来", "做成视频", "生成视频"], "generate-panel-video"),
            (["配音", "旁白", "语音", "朗读"], "generate-episode-dubbing"),
        ]
        for keywords, action in keyword_map:
            if any(keyword in lowered for keyword in keywords):
                normalized = self._normalize_action(action, available_actions=available_actions)
                if normalized and normalized not in detected:
                    detected.append(normalized)
        return detected

    def _default_actions_from_stage(
        self,
        *,
        stage: str,
        has_source_text: bool,
        panel_total: int,
        with_images: int,
        without_images: int,
        without_videos: int,
        available_actions: List[str],
    ) -> List[str]:
        if not has_source_text:
            return ["analyze-story-context"]
        if panel_total <= 0:
            return self._normalize_action_list(
                ["split-story-segments", "plan-storyboard"],
                available_actions=available_actions,
            )
        if with_images <= 0 and without_images > 0:
            return self._normalize_action_list(
                ["generate-panel-image", "generate-panel-video"],
                available_actions=available_actions,
            )
        if without_videos > 0 and with_images > 0:
            return self._normalize_action_list(
                ["generate-panel-video", "generate-episode-dubbing"],
                available_actions=available_actions,
            )
        if stage:
            return ["analyze-story-context"]
        return ["analyze-story-context"]

    def _repair_action_chain(
        self,
        *,
        requested_actions: List[str],
        available_actions: List[str],
        has_source_text: bool,
        panel_total: int,
        with_images: int,
        without_images: int,
        without_videos: int,
    ) -> tuple[str, List[str], List[str]]:
        queue = [action for action in requested_actions if action in available_actions]
        if not queue:
            queue = ["analyze-story-context"]

        missing_context: List[str] = []

        if any(action in queue for action in {"split-story-segments", "plan-storyboard", "extract-project-assets"}) and not has_source_text:
            return "analyze-story-context", [], ["当前剧集缺少剧本原文"]

        if "generate-panel-image" in queue and panel_total <= 0:
            queue = ["plan-storyboard", "generate-panel-image", *[item for item in queue if item != "generate-panel-image"]]

        if "generate-panel-video" in queue and with_images <= 0:
            if panel_total <= 0:
                queue = ["plan-storyboard", "generate-panel-image", "generate-panel-video"]
            else:
                queue = ["generate-panel-image", "generate-panel-video", *[item for item in queue if item != "generate-panel-video"]]

        if "generate-episode-dubbing" in queue and with_images <= 0:
            if panel_total <= 0:
                queue = ["plan-storyboard", "generate-panel-image", "generate-episode-dubbing"]
            else:
                queue = ["generate-panel-image", "generate-episode-dubbing", *[item for item in queue if item != "generate-episode-dubbing"]]

        deduped: List[str] = []
        for action in queue:
            normalized = self._normalize_action(action, available_actions=available_actions)
            if normalized and normalized not in deduped:
                deduped.append(normalized)

        if not deduped:
            deduped = ["analyze-story-context"]

        recommended_action = deduped[0]
        follow_up_actions = deduped[1:4]

        if recommended_action == "generate-panel-image" and without_images <= 0:
            follow_up_actions = [item for item in follow_up_actions if item != "generate-panel-image"]
        if recommended_action == "generate-panel-video" and without_videos <= 0:
            follow_up_actions = [item for item in follow_up_actions if item != "generate-panel-video"]

        return recommended_action, follow_up_actions, missing_context

    def _build_user_response(
        self,
        *,
        recommended_action: str,
        follow_up_actions: List[str],
        missing_context: List[str],
        response_mode: str,
    ) -> str:
        if missing_context:
            return "这一步还不能直接执行，当前缺少：{0}。我建议先补齐这些前置条件。".format("、".join(missing_context))

        first_label = ACTION_LABELS.get(recommended_action, recommended_action)
        if response_mode == "execute":
            return "我先帮你处理“{0}”，完成后再看是否继续下一步。".format(first_label)
        if response_mode == "plan" and follow_up_actions:
            rest = " -> ".join(ACTION_LABELS.get(item, item) for item in follow_up_actions[:2])
            return "我建议先做“{0}”，再继续“{1}”。".format(first_label, rest)
        return "我建议先做“{0}”。".format(first_label)

    def _intent_from_action(self, action: str, requested_actions: List[str]) -> str:
        intent_map = {
            "analyze-story-context": "script_analysis",
            "split-story-segments": "segment_planning",
            "plan-storyboard": "storyboard_planning",
            "extract-project-assets": "asset_extraction",
            "generate-panel-image": "image_generation",
            "generate-panel-video": "video_generation",
            "generate-episode-dubbing": "dubbing_planning",
        }
        if len(requested_actions) > 1:
            return "mixed_workflow"
        return intent_map.get(action, "general_chat")

    def _normalize_action(self, value: Any, *, available_actions: List[str]) -> Optional[str]:
        text = str(value or "").strip().lower()
        if not text:
            return None
        normalized = ACTION_ALIASES.get(text, text)
        return normalized if normalized in available_actions else None

    def _normalize_action_list(
        self,
        value: Any,
        *,
        available_actions: List[str],
        exclude: Optional[set[str]] = None,
    ) -> List[str]:
        result: List[str] = []
        exclude = exclude or set()
        raw_items = value if isinstance(value, list) else []
        for item in raw_items:
            normalized = self._normalize_action(item, available_actions=available_actions)
            if normalized and normalized not in exclude and normalized not in result:
                result.append(normalized)
        return result

    def _normalize_string_list(self, value: Any) -> List[str]:
        result: List[str] = []
        for item in value if isinstance(value, list) else []:
            text = str(item or "").strip()
            if text and text not in result:
                result.append(text)
        return result[:5]

    def _normalize_bool(self, value: Any, *, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in {"true", "1", "yes"}:
                return True
            if lowered in {"false", "0", "no"}:
                return False
        return default

    def _normalize_confidence(self, value: Any, *, default: float) -> float:
        try:
            parsed = float(value)
        except Exception:
            parsed = default
        if parsed < 0:
            return 0.0
        if parsed > 1:
            return 1.0
        return round(parsed, 3)

    def _extract_json(self, content: str) -> Dict[str, Any]:
        try:
            return json.loads(content)
        except Exception:
            pass

        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except Exception:
                pass

        brace_match = re.search(r"\{[\s\S]*\}", content)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except Exception:
                pass

        return {
            "reasoning": "无法解析 LLM 输出，回退到规则编排。",
            "response": content[:500] if content else "",
        }
