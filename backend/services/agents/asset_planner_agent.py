from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from core.config import settings
from models import SharedResource
from services.task_job_service import create_task_job, enqueue_task_job
from services.task_registry import resource_extract_tasks
from services.resource_extraction_service import sync_structured_assets_into_shared_resources
from services.workflow_preset_service import (
    build_style_prompt,
    get_style_display_label,
    resolve_asset_extraction_storyboard_mode,
    resolve_effective_workflow_profile,
)

from .base_agent import BaseAgent
from .stage_action_registry import assets_missing_actions, assets_ready_actions


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


class AssetPlannerAgent(BaseAgent):
    agent_name = "asset_planner_agent"
    agent_label = "资产设计专家"

    def _fetch_resources(self, script_id: int) -> List[SharedResource]:
        from sqlmodel import select

        return self.session.exec(
            select(SharedResource)
            .where(SharedResource.script_id == script_id)
            .order_by(SharedResource.created_at.asc(), SharedResource.id.asc())
        ).all()

    def _artifact_bundle(self, script_id: int) -> Dict[str, Any]:
        resources = self._fetch_resources(script_id)
        characters = []
        scenes = []
        props = []
        for item in resources:
            payload = {
                "name": _clean_text(getattr(item, "name", None)),
                "description": _clean_text(getattr(item, "description", None)),
                "trigger_word": _clean_text(getattr(item, "trigger_word", None)),
                "has_image": bool(_clean_text(getattr(item, "file_url", None))),
            }
            resource_type = _clean_text(getattr(item, "resource_type", None)).lower()
            if resource_type == "character":
                characters.append(payload)
            elif resource_type == "scene":
                scenes.append(payload)
            elif resource_type == "prop":
                props.append(payload)
        return {
            "asset_bundle": {
                "artifact_type": "asset_bundle",
                "characters": characters,
                "scenes": scenes,
                "props": props,
                "asset_summary": f"人物 {len(characters)} / 场景 {len(scenes)} / 道具 {len(props)}",
            }
        }

    def _normalize_structured_asset_items(self, items: Any) -> List[Dict[str, str]]:
        normalized: List[Dict[str, str]] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            name = _clean_text(item.get("name"))
            description = _clean_text(item.get("description") or item.get("role_identity"))
            if not name:
                continue
            payload: Dict[str, str] = {
                "name": name,
                "description": description,
            }
            trigger_word = _clean_text(item.get("trigger_word"))
            if trigger_word:
                payload["trigger_word"] = trigger_word
            normalized.append(payload)
        return normalized

    def _resolve_structured_assets(self, payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        direct_assets = payload.get("structured_assets")
        if isinstance(direct_assets, dict) and direct_assets:
            return direct_assets

        latest_artifacts = context.get("latest_artifacts") if isinstance(context.get("latest_artifacts"), dict) else {}
        bundle = latest_artifacts.get("asset_bundle") if isinstance(latest_artifacts.get("asset_bundle"), dict) else {}

        characters = payload.get("characters")
        scenes = payload.get("scenes")
        props = payload.get("props")
        if not isinstance(characters, list):
            characters = latest_artifacts.get("characters") if isinstance(latest_artifacts.get("characters"), list) else bundle.get("characters")
        if not isinstance(scenes, list):
            scenes = latest_artifacts.get("scenes") if isinstance(latest_artifacts.get("scenes"), list) else bundle.get("scenes")
        if not isinstance(props, list):
            props = latest_artifacts.get("props") if isinstance(latest_artifacts.get("props"), list) else bundle.get("props")

        resolved = {
            "characters": self._normalize_structured_asset_items(characters),
            "scenes": self._normalize_structured_asset_items(scenes),
            "props": self._normalize_structured_asset_items(props),
        }
        if any(resolved.values()):
            return resolved
        return {}

    def _submit_extract_task(self, *, context: Dict[str, Any], source_text: str) -> Dict[str, Any]:
        script = context["script"]
        episode = context.get("episode")
        team = context["team"]
        user = context["user"]
        workflow_profile = context.get("workflow_profile") or resolve_effective_workflow_profile(
            script,
            episode=episode,
            storyboard_mode=resolve_asset_extraction_storyboard_mode(script, episode=episode),
        )
        style_prompt = build_style_prompt(workflow_profile.get("style"), fallback=getattr(script, "style_preset", ""))
        style_label = get_style_display_label(workflow_profile.get("style"), getattr(script, "style_preset", "默认写实"))

        task_id = f"asset-{uuid.uuid4().hex[:12]}"
        job = create_task_job(
            self.session,
            task_id=task_id,
            task_type="resource.extract",
            queue_name="resource",
            provider="deepseek",
            team_id=team.id,
            user_id=user.id,
            script_id=script.id,
            ownership_mode="project",
            scope_type="script",
            scope_id=script.id,
            task_category="resource",
            payload={
                "script_id": script.id,
                "source_text": source_text,
                "style_prompt": style_prompt,
                "style_label": style_label,
                "script_name": script.name,
                "user_id": user.id,
                "team_id": team.id,
            },
            message="资产提取任务已提交",
            max_retries=1,
        )
        enqueue_task_job(job)
        resource_extract_tasks.create(
            task_id,
            status="submitted",
            msg="资产提取任务已提交，正在排队...",
            character_count=0,
            scene_count=0,
            prop_count=0,
            created_count=0,
            updated_count=0,
            script_id=script.id,
            user_id=user.id,
            kind="asset_extract",
            source="agent",
            title="提取项目资产",
            summary=script.name,
            refresh_hints={"resources": True},
        )
        return {"task_id": task_id, "status": "submitted"}

    def _fallback_response(self, *, context: Dict[str, Any]) -> Dict[str, Any]:
        stage = context["creative_stage"]
        stage_label = context["creative_stage_label"]
        script = context["script"]
        facts = context.get("stage_read_model", {}).get("facts") or {}
        has_resources = int(facts.get("resource_total") or 0) > 0

        suggested_actions = assets_missing_actions() if not has_resources else assets_ready_actions()

        artifacts = (
            {
                "asset_bundle": {
                    "artifact_type": "asset_bundle",
                    "characters": [],
                    "scenes": [],
                    "props": [],
                    "asset_summary": f"当前资产数：{int(facts.get('resource_total') or 0)}",
                }
            }
            if not has_resources
            else self._artifact_bundle(script.id)
        )

        message = (
            "我已经准备好根据这份剧本整理角色、场景和道具了。下一步建议先开始角色与场景设计。"
            if not has_resources
            else "我已经为这份剧本整理出主要角色、核心场景和关键道具。下一步建议先生成主体设定图，或者直接进入分镜板。"
        )

        return self.build_response(
            stage=stage,
            stage_label=stage_label,
            message=message,
            suggested_actions=suggested_actions,
            artifacts=artifacts,
            next_stage_hint="assets_ready",
        )

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        fallback = self._fallback_response(context=context)
        return self.try_llm_response(
            context=context,
            task_goal="请产出可入库的角色、场景、道具资产摘要，并给出下一步动作。",
            latest_instruction=_clean_text(context.get("latest_user_message")),
            action_space=fallback["suggested_actions"],
            fallback_response=fallback,
        )

    def execute_action(self, context: Dict[str, Any], action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        script = context["script"]
        source_text = _clean_text(context.get("current_script"))
        if not source_text:
            raise ValueError("当前分集还没有可提取资产的剧本文本")

        if action == "extract_assets":
            if not settings.DEEPSEEK_API_KEY:
                raise ValueError("当前资产提取服务不可用，请稍后重试")
            task = self._submit_extract_task(context=context, source_text=source_text)
            return {
                "message": "我已经开始为这份剧本整理角色、场景和道具。整理完成后会自动写入资产库，并跳转到资产页面。",
                "result": {
                    "artifact_type": "asset_bundle",
                    "characters": [],
                    "scenes": [],
                    "props": [],
                    "asset_summary": f"资产提取任务已提交：{task['task_id']}",
                    "task_id": task["task_id"],
                },
                "refresh_hints": {"resources": True, "assets": True, "open_assets": True, "generation_tasks": True},
                "next_stage_hint": "assets_pending",
            }

        if action == "save_assets":
            structured_assets = self._resolve_structured_assets(payload, context)
            if structured_assets:
                sync_structured_assets_into_shared_resources(script.id, structured_assets)
                self.session.commit()
                return {
                    "message": "保存资产成功，已写入资产库。",
                    "result": self._artifact_bundle(script.id)["asset_bundle"],
                    "refresh_hints": {"resources": True, "assets": True, "open_assets": True},
                    "suggested_actions": assets_ready_actions(),
                    "next_stage_hint": "assets_ready",
                }

            existing_bundle = self._artifact_bundle(script.id).get("asset_bundle") or {}
            if any(existing_bundle.get(key) for key in ("characters", "scenes", "props")):
                return {
                    "message": "这些资产已经在资产库里了，我已为你刷新资产视图。接下来可以直接生成主体设定图或进入分镜板。",
                    "result": existing_bundle,
                    "refresh_hints": {"resources": True, "assets": True, "open_assets": True},
                    "suggested_actions": assets_ready_actions(),
                    "next_stage_hint": "assets_ready",
                }

            return {
                "message": "当前还没有可写入的资产结果，请先等待资产提取任务完成。",
                "result": {
                    "artifact_type": "asset_bundle",
                    "characters": [],
                    "scenes": [],
                    "props": [],
                    "asset_summary": "请先等待资产提取任务完成",
                },
                "refresh_hints": {"resources": True, "assets": True},
                "suggested_actions": assets_missing_actions(),
                "next_stage_hint": "assets_pending",
            }

        raise ValueError(f"资产设计专家不支持动作: {action}")
