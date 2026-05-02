from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from .base_agent import BaseAgent
from .stage_action_registry import post_save_script_actions, script_empty_actions, script_ready_actions


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _strip_save_prefix(value: str) -> str:
    text = _clean_text(value)
    for prefix in ("保存剧本：", "保存剧本:", "保存原文：", "保存原文:", "剧本：", "剧本:"):
        if text.startswith(prefix):
            return text[len(prefix):].strip()
    return text


class DirectorAgent(BaseAgent):
    agent_name = "director_agent"
    agent_label = "编剧专家"

    def _script_text(self, context: Dict[str, Any]) -> str:
        return _clean_text(context.get("current_script"))

    def _candidate_script_draft(self, context: Dict[str, Any], payload: Optional[Dict[str, Any]] = None) -> str:
        payload = payload or {}
        latest_artifacts = context.get("latest_artifacts") if isinstance(context.get("latest_artifacts"), dict) else {}
        latest_script_artifact = latest_artifacts.get("script_draft") if isinstance(latest_artifacts.get("script_draft"), dict) else {}
        agent_preview = context.get("agent_context_preview") if isinstance(context.get("agent_context_preview"), dict) else {}
        preview_script_artifact = (
            agent_preview.get("latest_script_artifact")
            if isinstance(agent_preview.get("latest_script_artifact"), dict)
            else {}
        )
        candidates = [
            payload.get("script_draft"),
            payload.get("source_text"),
            payload.get("text"),
            payload.get("content"),
            latest_script_artifact.get("content"),
            latest_script_artifact.get("script_draft"),
            preview_script_artifact.get("content"),
            preview_script_artifact.get("script_draft"),
            context.get("current_script"),
            context.get("latest_user_message"),
        ]
        for item in candidates:
            text = _strip_save_prefix(_clean_text(item))
            if text:
                return text
        return ""

    def _fallback_response(self, context: Dict[str, Any]) -> Dict[str, Any]:
        stage = _clean_text(context.get("creative_stage")) or "script_empty"
        stage_label = _clean_text(context.get("creative_stage_label")) or "剧本创作"
        script_draft = self._script_text(context) or _strip_save_prefix(_clean_text(context.get("latest_user_message")))
        has_script = bool(script_draft)
        actions = script_ready_actions(script_draft) if has_script else script_empty_actions(script_draft)
        message = (
            "我已经识别到当前剧本内容，可以先保存为本集原文，再进入角色、场景和道具提取。"
            if has_script
            else "当前分集还没有可用剧本。你可以先给我灵感或原文，我会帮你整理成可保存的剧本草稿。"
        )
        artifacts = {}
        if script_draft:
            artifacts["script_draft"] = {
                "artifact_type": "script_draft",
                "content": script_draft,
                "summary": "可用于保存为本集原文的剧本草稿。",
            }
        return self.build_response(
            stage=stage,
            stage_label=stage_label,
            message=message,
            suggested_actions=actions,
            artifacts=artifacts,
            next_stage_hint=stage or "script_empty",
            refresh_hints={},
        )

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        fallback = self._fallback_response(context)
        return self.try_llm_response(
            context=context,
            task_goal="请判断用户输入是否可形成剧本，并给出可继续推进到保存剧本或资产提取的结构化结果。",
            latest_instruction=_clean_text(context.get("latest_user_message")),
            action_space=fallback["suggested_actions"],
            fallback_response=fallback,
        )

    def execute_action(self, context: Dict[str, Any], action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        script = context.get("script")
        episode = context.get("episode")
        if script is None:
            raise ValueError("当前动作需要绑定到剧本项目。")

        if action == "save_script":
            script_draft = self._candidate_script_draft(context, payload)
            if not script_draft:
                raise ValueError("没有可保存的剧本文本，请先输入剧本或灵感内容。")

            now = datetime.utcnow()
            if episode is not None:
                episode.source_text = script_draft
                episode.updated_at = now
                self.session.add(episode)
            else:
                script.source_text = script_draft
            script.updated_at = now
            self.session.add(script)
            self.session.commit()

            return {
                "message": "剧本已保存为当前原文。下一步可以提取人物、场景和道具资产。",
                "result": {
                    "artifact_type": "script_draft",
                    "content": script_draft,
                    "summary": "剧本已写入项目工作区。",
                },
                "artifacts": {
                    "script_draft": {
                        "artifact_type": "script_draft",
                        "content": script_draft,
                        "summary": "剧本已写入项目工作区。",
                    }
                },
                "refresh_hints": {"script_source": True, "episodes": True},
                "suggested_actions": post_save_script_actions(script_draft),
                "next_stage_hint": "assets_pending",
            }

        if action == "rewrite_script":
            script_draft = self._candidate_script_draft(context, payload)
            if not script_draft:
                raise ValueError("没有可改写的剧本文本，请先输入剧本或灵感内容。")
            message = "我已整理出一版可继续完善的剧本草稿。确认满意后，可以保存为当前分集原文。"
            return {
                "message": message,
                "result": {
                    "artifact_type": "script_draft",
                    "content": script_draft,
                    "summary": "剧本草稿已整理，尚未写入项目。",
                },
                "artifacts": {
                    "script_draft": {
                        "artifact_type": "script_draft",
                        "content": script_draft,
                        "summary": "剧本草稿已整理，尚未写入项目。",
                    }
                },
                "refresh_hints": {},
                "suggested_actions": script_ready_actions(script_draft),
                "next_stage_hint": context.get("creative_stage") or "script_ready",
            }

        raise ValueError(f"编剧专家暂不支持这个动作：{action}")
