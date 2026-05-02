from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import BackgroundTasks
from sqlmodel import select

from core.security import encode_id
from models import Panel, SharedResource
from services.asset_prompt_builder import (
    build_default_asset_reference_prompt,
    default_asset_reference_aspect_ratio,
)
from services.generation_record_service import submit_asset_generation, submit_image_generation, submit_video_generation
from services.image_model_registry import DEFAULT_IMAGE_MODEL_CODE, normalize_image_model_code
from services.storyboard_mode_service import get_panel_reference_images

from .base_agent import BaseAgent
from .stage_action_registry import (
    asset_reference_followup_actions,
    asset_reference_generation_actions,
    images_pending_actions,
    images_ready_actions,
    storyboard_ready_actions,
    videos_pending_actions,
    videos_ready_actions,
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_asset_image_model(value: Any) -> str:
    return normalize_image_model_code(value or DEFAULT_IMAGE_MODEL_CODE)


def _normalize_asset_kind(value: Any) -> str:
    normalized = _clean_text(value).lower()
    if normalized in {"character", "scene", "prop"}:
        return normalized
    if "character" in normalized:
        return "character"
    if "scene" in normalized:
        return "scene"
    if "prop" in normalized:
        return "prop"
    return "character"


def _json_loads(raw: Any, fallback: Any) -> Any:
    if not raw:
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return fallback


def _mark_agent_generation_record(session, record: Any, context: Dict[str, Any]) -> None:
    assistant_session_id = context.get("assistant_session_id")
    if not assistant_session_id or record is None:
        return
    params_public = _json_loads(getattr(record, "params_public_json", None), {})
    params_internal = _json_loads(getattr(record, "params_internal_json", None), {})
    if not isinstance(params_public, dict):
        params_public = {}
    if not isinstance(params_internal, dict):
        params_internal = {}
    params_public["source"] = "agent"
    params_internal.update(
        {
            "source": "agent",
            "assistant_session_id": assistant_session_id,
            "assistant_session_profile": context.get("assistant_session_profile") or "",
            "assistant_session_channel": context.get("assistant_session_channel") or "",
        }
    )
    try:
        record.params_public_json = json.dumps(params_public, ensure_ascii=False)
        record.params_internal_json = json.dumps(params_internal, ensure_ascii=False)
        session.add(record)
    except Exception:
        return


class GenerationAgent(BaseAgent):
    agent_name = "generation_agent"
    agent_label = "生成助手"

    IMAGE_MODEL_LABELS = {
        "nano-banana-2": "nano-banana-2",
        "nano-banana-2-低价版": "nano-banana-2-低价版",
        "nano-banana-pro": "nano-banana-pro",
        "nano-banana-pro-低价版": "nano-banana-pro-低价版",
        "gpt-image-2-fast": "gpt-image-2-fast",
        "gpt-image-2": "gpt-image-2",
    }

    def _artifact_bundle(self, context: Dict[str, Any]) -> Dict[str, Any]:
        facts = context.get("stage_read_model", {}).get("facts") or {}
        workflow_profile = context.get("workflow_profile") or {}
        video_profile = (workflow_profile.get("video") or {}) if isinstance(workflow_profile, dict) else {}
        image_profile = (workflow_profile.get("image") or {}) if isinstance(workflow_profile, dict) else {}
        image_model = _normalize_asset_image_model(image_profile.get("model_code") or image_profile.get("model"))
        return {
            "generation_bundle": {
                "artifact_type": "generation_bundle",
                "prompt_preview": [],
                "model_suggestions": [
                    {
                        "model_name": self.IMAGE_MODEL_LABELS.get(image_model, "当前图片模型"),
                        "use_case": "资产参考图",
                        "description": "使用当前平台已接入的图片模型生成角色、场景和道具参考图。",
                    },
                    {
                        "model_name": str(video_profile.get("model_code") or "").strip() or "当前视频模型",
                        "use_case": "分镜视频",
                        "description": "用于后续分镜动画或镜头视频生成。",
                    },
                ],
                "generation_targets": [
                    {
                        "name": "资产参考图",
                        "type": "图片生成",
                        "summary": "优先为当前项目中尚未生成参考图的人物、场景和道具补齐视觉参考。",
                    }
                ],
                "generation_summary": "已根据当前分镜与工作流配置整理生成建议。",
                "facts": {
                    "panel_count": int(facts.get("panel_count") or 0),
                    "panels_with_images": int(facts.get("panels_with_images") or 0),
                    "panels_with_videos": int(facts.get("panels_with_videos") or 0),
                },
            }
        }

    def merge_llm_response(self, *, fallback_response: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
        merged = super().merge_llm_response(fallback_response=fallback_response, llm_payload=llm_payload)
        merged["artifacts"] = fallback_response.get("artifacts") or {}
        message = _clean_text(merged.get("message"))
        if any(token in message for token in ("SDXL", "SD 1.5", "generation_bundle", "artifact type")):
            merged["message"] = fallback_response.get("message") or message
        return merged

    def _first_missing_resource(self, script_id: int) -> Optional[SharedResource]:
        resources = self.session.exec(
            select(SharedResource)
            .where(SharedResource.script_id == script_id)
            .order_by(SharedResource.created_at.asc(), SharedResource.id.asc())
        ).all()
        for item in resources:
            if not _clean_text(getattr(item, "file_url", None)):
                return item
        return resources[0] if resources else None

    def _resources_for_generation_scope(self, script_id: int, generation_scope: str) -> List[SharedResource]:
        resources = self.session.exec(
            select(SharedResource)
            .where(SharedResource.script_id == script_id)
            .order_by(SharedResource.created_at.asc(), SharedResource.id.asc())
        ).all()
        normalized_scope = _clean_text(generation_scope).lower()
        if normalized_scope in {"character", "scene", "prop"}:
            resources = [item for item in resources if _clean_text(getattr(item, "resource_type", None)).lower() == normalized_scope]
        missing_only = [item for item in resources if not _clean_text(getattr(item, "file_url", None))]
        return missing_only or resources

    def _resources_by_ids(self, script_id: int, resource_ids: Any) -> List[SharedResource]:
        normalized_ids: List[int] = []
        for item in resource_ids or []:
            try:
                value = int(item)
            except Exception:
                continue
            if value > 0 and value not in normalized_ids:
                normalized_ids.append(value)
        if not normalized_ids:
            return []
        resources = self.session.exec(
            select(SharedResource)
            .where(SharedResource.script_id == script_id)
            .where(SharedResource.id.in_(normalized_ids))
            .order_by(SharedResource.created_at.asc(), SharedResource.id.asc())
        ).all()
        resource_map = {int(getattr(item, "id", 0) or 0): item for item in resources}
        return [resource_map[item_id] for item_id in normalized_ids if item_id in resource_map]

    def _list_episode_panels(self, episode_id: int) -> List[Panel]:
        return self.session.exec(
            select(Panel).where(Panel.episode_id == episode_id).order_by(Panel.sequence_num.asc(), Panel.id.asc())
        ).all()

    def _pending_storyboard_image_sequences(self, episode_id: int) -> List[int]:
        sequences: List[int] = []
        for panel in self._list_episode_panels(episode_id):
            sequence = int(getattr(panel, "sequence_num", 0) or 0)
            if sequence <= 0 or _clean_text(getattr(panel, "image_url", None)):
                continue
            if sequence not in sequences:
                sequences.append(sequence)
        return sequences

    def _panel_reference_images_for_generation(self, panel: Panel) -> List[str]:
        merged: List[str] = []
        seen = set()

        try:
            semantic_refs = json.loads(str(getattr(panel, "reference_images_json", "[]") or "[]"))
        except Exception:
            semantic_refs = []

        for item in list(semantic_refs or []) + list(get_panel_reference_images(self.session, panel) or []):
            url = _clean_text(item)
            if not url or url in seen:
                continue
            seen.add(url)
            merged.append(url)
        return merged

    def _first_storyboard_panel(self, episode_id: int, *, want_video: bool = False) -> Optional[Panel]:
        panels = self._list_episode_panels(episode_id)
        for panel in panels:
            if want_video:
                if _clean_text(getattr(panel, "image_url", None)) and not _clean_text(getattr(panel, "video_url", None)):
                    return panel
            else:
                if not _clean_text(getattr(panel, "image_url", None)):
                    return panel
        return panels[0] if panels else None

    def _panel_by_sequence(self, episode_id: int, sequence_num: Any) -> Optional[Panel]:
        try:
            target_sequence = int(sequence_num)
        except Exception:
            return None
        return next(
            (item for item in self._list_episode_panels(episode_id) if int(getattr(item, "sequence_num", 0) or 0) == target_sequence),
            None,
        )

    def _panels_by_sequences(self, episode_id: int, sequences: Any) -> List[Panel]:
        normalized_sequences: List[int] = []
        for item in sequences or []:
            try:
                value = int(item)
            except Exception:
                continue
            if value > 0 and value not in normalized_sequences:
                normalized_sequences.append(value)
        if not normalized_sequences:
            return []
        panel_map = {
            int(getattr(item, "sequence_num", 0) or 0): item
            for item in self._list_episode_panels(episode_id)
        }
        return [panel_map[value] for value in normalized_sequences if value in panel_map]

    def _fallback_response(self, context: Dict[str, Any]) -> Dict[str, Any]:
        stage = context["creative_stage"]
        stage_label = context["creative_stage_label"]
        actions: List[Dict[str, Any]] = []
        next_stage_hint = "images_pending"
        episode = context.get("episode")
        pending_storyboard_sequences = self._pending_storyboard_image_sequences(episode.id) if episode is not None else []
        if stage in {"assets_ready", "asset_images_pending"}:
            actions.extend(asset_reference_generation_actions())
            next_stage_hint = "asset_images_pending"
        elif stage == "storyboard_ready":
            actions.extend(storyboard_ready_actions(pending_storyboard_sequences))
            next_stage_hint = "storyboard_ready"
        elif stage == "images_pending":
            actions.extend(images_pending_actions(pending_storyboard_sequences))
            next_stage_hint = "images_pending"
        elif stage == "images_ready":
            actions.extend(images_ready_actions(pending_storyboard_sequences))
            next_stage_hint = "images_ready"
        elif stage == "videos_pending":
            actions.extend(videos_pending_actions())
            next_stage_hint = "videos_pending"
        elif stage == "videos_ready":
            actions.extend(videos_ready_actions())
            next_stage_hint = "videos_ready"
        return self.build_response(
            stage=stage,
            stage_label=stage_label,
            message="我已经把这一阶段的生成建议整理好了。接下来可以先补主体设定图，或者继续推进到分镜图与视频生成。",
            suggested_actions=actions,
            artifacts=self._artifact_bundle(context),
            next_stage_hint=next_stage_hint,
        )

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        fallback = self._fallback_response(context)
        return self.try_llm_response(
            context=context,
            task_goal="请根据当前阶段产出图片或视频生成建议、模型建议与下一步动作。",
            latest_instruction=_clean_text(context.get("latest_user_message")),
            action_space=fallback["suggested_actions"],
            fallback_response=fallback,
        )

    def _submit_storyboard_image_jobs(
        self,
        *,
        context: Dict[str, Any],
        script,
        episode,
        user,
        team,
        image_profile: Dict[str, Any],
        workflow_profile: Dict[str, Any],
        background_tasks: BackgroundTasks,
        target_panels: List[Panel],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        submitted_records = []
        prompt_preview = []
        all_pending_sequences = self._pending_storyboard_image_sequences(episode.id)
        for panel in target_panels:
            prompt = (
                _clean_text(payload.get("prompt"))
                or _clean_text(getattr(panel, "multi_shot_prompt", None))
                or _clean_text(getattr(panel, "scene_prompt", None))
                or _clean_text(getattr(panel, "prompt", None))
            )
            if not prompt:
                continue
            record = submit_image_generation(
                self.session,
                background_tasks=background_tasks,
                user=user,
                team=team,
                payload={
                    "ownership_mode": "project",
                    "project_id": encode_id(script.id),
                    "episode_id": encode_id(episode.id),
                    "target_type": "panel",
                    "target_id": encode_id(panel.id),
                    "mode": "text_to_image",
                    "model_code": payload.get("model_code") or payload.get("image_model_code") or image_profile.get("model_code") or DEFAULT_IMAGE_MODEL_CODE,
                    "resolution": payload.get("resolution") or payload.get("image_resolution") or image_profile.get("resolution") or "2k",
                    "quality": payload.get("quality") or payload.get("image_quality") or image_profile.get("quality") or "medium",
                    "aspect_ratio": payload.get("aspect_ratio") or workflow_profile.get("aspect_ratio") or "16:9",
                    "reference_images": self._panel_reference_images_for_generation(panel),
                    "prompt": prompt,
                },
            )
            _mark_agent_generation_record(self.session, record, context)
            submitted_records.append((panel, record))
            prompt_preview.append({"kind": "image", "panel_sequence": int(panel.sequence_num or 0), "prompt": prompt})
        if not submitted_records:
            raise ValueError("当前目标分镜缺少可用图片提示词")
        self.session.commit()
        submitted_panel_sequences = [int(panel.sequence_num or 0) for panel, _ in submitted_records]
        remaining_panel_sequences = [
            sequence for sequence in all_pending_sequences if sequence not in submitted_panel_sequences
        ]
        if len(submitted_records) == 1:
            message = f"已经为第 {submitted_records[0][0].sequence_num} 镜发起图片生成任务。"
        else:
            message = f"已为当前选中的 {len(submitted_records)} 个分镜提交图片生成任务。"
        return {
            "message": message,
            "result": {
                **self._artifact_bundle(context)["generation_bundle"],
                "prompt_preview": prompt_preview[:12],
                "generation_summary": "已提交 {0} 个分镜图片任务".format(len(submitted_records)),
                "submitted_count": len(submitted_records),
                "submitted_panel_sequences": submitted_panel_sequences,
                "submitted_panels": [
                    {
                        "panel_sequence": int(panel.sequence_num or 0),
                        "task_id": str(record.task_id or ""),
                        "name": f"第 {int(panel.sequence_num or 0)} 镜",
                    }
                    for panel, record in submitted_records[:24]
                ],
                "remaining_panel_sequences": remaining_panel_sequences,
                "task_ids": [str(record.task_id or "") for _, record in submitted_records if _clean_text(getattr(record, "task_id", None))],
            },
            "refresh_hints": {"panels": True, "segment_workspace": True, "generation_tasks": True},
            "next_stage_hint": "images_pending",
        }

    def _submit_storyboard_video_jobs(
        self,
        *,
        context: Dict[str, Any],
        script,
        episode,
        user,
        team,
        video_profile: Dict[str, Any],
        workflow_profile: Dict[str, Any],
        background_tasks: BackgroundTasks,
        target_panels: List[Panel],
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        submitted_records = []
        prompt_preview = []
        for panel in target_panels:
            prompt = (
                _clean_text(payload.get("prompt"))
                or _clean_text(getattr(panel, "multi_shot_video_prompt", None))
                or _clean_text(getattr(panel, "video_prompt", None))
                or _clean_text(getattr(panel, "scene_prompt", None))
            )
            if not prompt or not _clean_text(getattr(panel, "image_url", None)):
                continue
            record = submit_video_generation(
                self.session,
                background_tasks=background_tasks,
                user=user,
                team=team,
                payload={
                    "ownership_mode": "project",
                    "project_id": encode_id(script.id),
                    "episode_id": encode_id(episode.id),
                    "target_type": "panel",
                    "target_id": encode_id(panel.id),
                    "model_code": payload.get("model_code") or payload.get("video_model_code") or video_profile.get("model_code") or "runninghub-vidu-q2-pro",
                    "channel_id": payload.get("channel_id") or payload.get("model_code") or payload.get("video_model_code") or video_profile.get("model_code") or "runninghub-vidu-q2-pro",
                    "prompt": prompt,
                    "reference_images": [_clean_text(getattr(panel, "image_url", None))] if _clean_text(getattr(panel, "image_url", None)) else [],
                    "duration": int(payload.get("duration") or video_profile.get("duration") or getattr(panel, "recommended_duration_seconds", None) or 5),
                    "resolution": payload.get("resolution") or payload.get("video_resolution") or video_profile.get("resolution") or "720p",
                    "aspect_ratio": payload.get("aspect_ratio") or workflow_profile.get("aspect_ratio") or "16:9",
                    "audio": bool(payload.get("audio") if payload.get("audio") is not None else video_profile.get("audio_enabled")),
                    "generation_type": payload.get("generation_type") or video_profile.get("generation_type"),
                },
            )
            _mark_agent_generation_record(self.session, record, context)
            submitted_records.append((panel, record))
            prompt_preview.append({"kind": "video", "panel_sequence": int(panel.sequence_num or 0), "prompt": prompt})
        if not submitted_records:
            raise ValueError("当前目标分镜缺少可用视频提示词或可用分镜图")
        self.session.commit()
        if len(submitted_records) == 1:
            message = f"已经为第 {submitted_records[0][0].sequence_num} 镜发起视频生成任务。"
        else:
            message = f"已为当前选中的 {len(submitted_records)} 个分镜提交视频生成任务。"
        return {
            "message": message,
            "result": {
                **self._artifact_bundle(context)["generation_bundle"],
                "prompt_preview": prompt_preview[:12],
                "generation_summary": "已提交 {0} 个分镜视频任务".format(len(submitted_records)),
                "submitted_count": len(submitted_records),
                "submitted_panel_sequences": [int(panel.sequence_num or 0) for panel, _ in submitted_records],
                "task_ids": [str(record.task_id or "") for _, record in submitted_records if _clean_text(getattr(record, "task_id", None))],
            },
            "refresh_hints": {"panels": True, "segment_workspace": True, "generation_tasks": True},
            "next_stage_hint": "videos_pending",
        }

    def execute_action(self, context: Dict[str, Any], action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        script = context["script"]
        episode = context.get("episode")
        user = context["user"]
        team = context["team"]
        workflow_profile = context.get("workflow_profile") or {}
        image_profile = (workflow_profile.get("image") or {}) if isinstance(workflow_profile, dict) else {}
        video_profile = (workflow_profile.get("video") or {}) if isinstance(workflow_profile, dict) else {}
        background_tasks = BackgroundTasks()

        if action == "generate_asset_images":
            generation_scope = _clean_text(payload.get("generation_scope")) or "all"
            requested_resource_ids = payload.get("resource_ids") if isinstance(payload.get("resource_ids"), list) else []
            resources = self._resources_by_ids(script.id, requested_resource_ids) if requested_resource_ids else self._resources_for_generation_scope(script.id, generation_scope)
            if not resources:
                raise ValueError("当前项目还没有可生成参考图的资产")
            submitted = []
            for resource in resources:
                prompt = _clean_text(payload.get("prompt")) or build_default_asset_reference_prompt(
                    resource,
                    script=script,
                    episode=episode,
                    workflow_profile=workflow_profile,
                )
                record = submit_asset_generation(
                    self.session,
                    background_tasks=background_tasks,
                    user=user,
                    team=team,
                    payload={
                        "ownership_mode": "project",
                        "project_id": encode_id(script.id),
                        "episode_id": encode_id(episode.id) if episode else None,
                        "target_type": "shared_resource",
                        "target_id": encode_id(resource.id),
                        "asset_type": _normalize_asset_kind(getattr(resource, "resource_type", None)),
                        "name": resource.name,
                        "description": getattr(resource, "description", None),
                        "trigger_word": getattr(resource, "trigger_word", None),
                        "aliases": getattr(resource, "aliases", None) or [],
                        "model_code": _normalize_asset_image_model(image_profile.get("model_code") or image_profile.get("model")),
                        "resolution": image_profile.get("resolution") or "2k",
                        "aspect_ratio": default_asset_reference_aspect_ratio(resource),
                        "prompt": prompt,
                    },
                )
                _mark_agent_generation_record(self.session, record, context)
                submitted.append((resource, record))
            self.session.commit()
            scope_label = {
                "all": "全部资产",
                "character": "人物",
                "scene": "场景",
                "prop": "道具",
            }.get(generation_scope.lower(), "全部资产")
            return {
                "message": f"已经为{scope_label}提交 {len(submitted)} 个资产参考图任务。",
                "result": {
                    **self._artifact_bundle(context)["generation_bundle"],
                    "generation_summary": f"已提交 {len(submitted)} 个资产参考图任务",
                    "submitted_count": len(submitted),
                    "submitted_assets": [
                        {
                            "name": resource.name,
                            "resource_type": _normalize_asset_kind(getattr(resource, "resource_type", None)),
                            "task_id": str(record.task_id or ""),
                        }
                        for resource, record in submitted[:24]
                    ],
                },
                "refresh_hints": {"resources": True, "generation_tasks": True},
                "suggested_actions": asset_reference_followup_actions(generation_scope),
                "next_stage_hint": "asset_images_pending",
            }

        if action == "generate_storyboard_images":
            if episode is None:
                raise ValueError("当前动作需要绑定到具体分集")
            target_panels = self._panels_by_sequences(episode.id, payload.get("selected_panel_sequences"))
            if not target_panels:
                panel = self._panel_by_sequence(episode.id, payload.get("panel_sequence")) or self._first_storyboard_panel(episode.id, want_video=False)
                target_panels = [panel] if panel is not None else []
            if not target_panels:
                raise ValueError("当前分集还没有可出图的分镜")
            return self._submit_storyboard_image_jobs(
                context=context,
                script=script,
                episode=episode,
                user=user,
                team=team,
                image_profile=image_profile,
                workflow_profile=workflow_profile,
                background_tasks=background_tasks,
                target_panels=target_panels,
                payload=payload,
            )

        if action == "generate_video":
            if episode is None:
                raise ValueError("当前动作需要绑定到具体分集")
            target_panels = self._panels_by_sequences(episode.id, payload.get("selected_panel_sequences"))
            if not target_panels:
                panel = self._panel_by_sequence(episode.id, payload.get("panel_sequence")) or self._first_storyboard_panel(episode.id, want_video=True)
                target_panels = [panel] if panel is not None else []
            if not target_panels:
                raise ValueError("当前还没有可做视频的分镜，请先确保至少有一张分镜图")
            return self._submit_storyboard_video_jobs(
                context=context,
                script=script,
                episode=episode,
                user=user,
                team=team,
                video_profile=video_profile,
                workflow_profile=workflow_profile,
                background_tasks=background_tasks,
                target_panels=target_panels,
                payload=payload,
            )

        raise ValueError(f"生成助手不支持动作 {action}")
