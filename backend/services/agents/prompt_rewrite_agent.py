from __future__ import annotations

import json
import re
import uuid
from decimal import Decimal, ROUND_CEILING
from typing import Any, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, HTTPException
from openai import OpenAI
from sqlmodel import Session, select

from core.config import settings
from core.security import encode_id
from models import Episode, GenerationRecord, Panel, SharedResource
from services.billing_service import deduct_inspiration_points
from services.deepseek_hybrid_router import estimate_text_tokens
from services.deepseek_model_policy import (
    DEEPSEEK_V4_FLASH_MODEL,
    calculate_deepseek_v4_flash_usage_cost_cny,
    normalize_deepseek_model,
    normalize_deepseek_request_kwargs,
)
from services.generation_record_service import (
    RECORD_TYPE_IMAGE,
    RECORD_TYPE_VIDEO,
    TARGET_TYPE_PANEL,
    _estimate_image_public_params,
    _estimate_video_public_params,
)
from services.panel_revision_service import update_panel_with_revision
from services.story_segment_service import build_episode_segment_workspace

from .base_agent import BaseAgent
from .generation_agent import GenerationAgent


POINTS_UNIT_CNY = Decimal("0.1")


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _json_loads(raw: Any, fallback: Any) -> Any:
    if not raw:
        return fallback
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return fallback


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _points_from_cost(cost_cny: Decimal) -> int:
    if cost_cny <= 0:
        return 0
    return int((cost_cny / POINTS_UNIT_CNY).to_integral_value(rounding=ROUND_CEILING)) + 1


def _response_usage_to_dict(response: Any, *, prompt_text: str, output_text: str) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    raw: Dict[str, Any] = {}
    if usage is not None:
        if hasattr(usage, "model_dump"):
            raw = usage.model_dump()
        elif hasattr(usage, "dict"):
            raw = usage.dict()
        elif isinstance(usage, dict):
            raw = usage
    prompt_tokens = int(raw.get("prompt_tokens") or 0)
    hit_tokens = int(
        raw.get("prompt_cache_hit_tokens")
        or ((raw.get("prompt_tokens_details") or {}).get("cached_tokens") if isinstance(raw.get("prompt_tokens_details"), dict) else 0)
        or 0
    )
    miss_tokens = int(raw.get("prompt_cache_miss_tokens") or max(prompt_tokens - hit_tokens, 0))
    completion_tokens = int(raw.get("completion_tokens") or 0)
    if not any([prompt_tokens, hit_tokens, miss_tokens, completion_tokens]):
        prompt_tokens = max(int(len(prompt_text.encode("utf-8")) / 3), 1)
        miss_tokens = prompt_tokens
        completion_tokens = max(int(len(str(output_text or "").encode("utf-8")) / 3), 1)
    return {
        "prompt_tokens": prompt_tokens,
        "prompt_cache_hit_tokens": hit_tokens,
        "prompt_cache_miss_tokens": miss_tokens,
        "completion_tokens": completion_tokens,
    }


def _prompt_summary(prompt: str, limit: int = 160) -> str:
    normalized = " ".join(_clean_text(prompt).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1] + "…"


def _normalize_target_kind(value: Any) -> str:
    normalized = _clean_text(value).lower()
    if normalized in {"image", "video", "both"}:
        return normalized
    if "视频" in normalized:
        return "video"
    if "图" in normalized or "图片" in normalized:
        return "image"
    return "both"


def _normalize_scope(value: Any) -> str:
    normalized = _clean_text(value).lower()
    if normalized in {"current_panel", "selected_panels", "current_episode"}:
        return normalized
    return "selected_panels"


def _normalize_generate_after(value: Any, target_kind: str) -> str:
    normalized = _clean_text(value).lower()
    if normalized in {"none", "image", "video", "both"}:
        return normalized
    if target_kind in {"image", "video"}:
        return target_kind
    return "none"


def _normalize_operation(value: Any) -> str:
    normalized = _clean_text(value).lower()
    aliases = {
        "save": "apply",
        "confirm": "apply",
        "apply_and_generate": "apply_and_generate",
        "save_and_generate": "apply_and_generate",
        "revise": "preview",
        "continue": "preview",
        "cancel": "cancel",
        "restore": "restore_last_generated",
        "restore_last_generated": "restore_last_generated",
    }
    if normalized in {"preview", "apply", "apply_and_generate", "cancel", "restore_last_generated"}:
        return normalized
    return aliases.get(normalized, "preview")


def _extract_at_names(prompt: str) -> List[str]:
    names: List[str] = []
    for match in re.finditer(r"@([\w\u4e00-\u9fff·\-\s]{1,40})", prompt or ""):
        name = match.group(1).strip()
        name = re.split(r"[\s,，。；;：:、/）)\]}】]", name)[0].strip()
        if name and name not in names:
            names.append(name)
    return names


def _sanitize_asset_mentions(prompt: str, valid_names: set[str]) -> str:
    def repl(match: re.Match[str]) -> str:
        raw = match.group(1).strip()
        suffix = ""
        name = raw
        split_match = re.search(r"[\s,，。；;：:、/）)\]}】]", raw)
        if split_match:
            name = raw[: split_match.start()].strip()
            suffix = raw[split_match.start():]
        if not name:
            return match.group(0)
        return f"@{name}{suffix}" if name in valid_names else f"{name}{suffix}"

    return re.sub(r"@([\w\u4e00-\u9fff·\-\s]{1,40})", repl, prompt or "")


class PromptRewriteAgent(BaseAgent):
    agent_name = "prompt_rewrite_agent"
    agent_label = "提示词导演"

    def _list_episode_panels(self, episode_id: int) -> List[Panel]:
        return self.session.exec(
            select(Panel).where(Panel.episode_id == episode_id).order_by(Panel.sequence_num.asc(), Panel.id.asc())
        ).all()

    def _panels_by_payload(self, episode: Episode, payload: Dict[str, Any]) -> List[Panel]:
        panels = self._list_episode_panels(episode.id)
        scope = _normalize_scope(payload.get("scope"))
        if scope == "current_episode":
            return panels
        selected: List[int] = []
        for item in payload.get("selected_panel_sequences") or []:
            try:
                value = int(item)
            except Exception:
                continue
            if value > 0 and value not in selected:
                selected.append(value)
        if not selected:
            try:
                value = int(payload.get("panel_sequence") or 0)
            except Exception:
                value = 0
            if value > 0:
                selected.append(value)
        if not selected and panels:
            selected.append(int(getattr(panels[0], "sequence_num", 0) or 0))
        panel_map = {int(getattr(item, "sequence_num", 0) or 0): item for item in panels}
        return [panel_map[value] for value in selected if value in panel_map]

    def _valid_asset_names(self, script_id: int) -> set[str]:
        resources = self.session.exec(select(SharedResource).where(SharedResource.script_id == script_id)).all()
        names: set[str] = set()
        for resource in resources:
            name = _clean_text(getattr(resource, "name", None))
            if name:
                names.add(name)
            for alias in _json_loads(getattr(resource, "aliases", None), []):
                alias_text = _clean_text(alias)
                if alias_text:
                    names.add(alias_text)
            trigger = _clean_text(getattr(resource, "trigger_word", None))
            if trigger:
                names.add(trigger)
        return names

    def _workspace_items(self, episode: Episode) -> Dict[int, Dict[str, Any]]:
        panels = self._list_episode_panels(episode.id)
        dependency_sequences = {int(getattr(panel, "id", 0) or 0): None for panel in panels}
        try:
            workspace = build_episode_segment_workspace(self.session, episode, panels, dependency_sequences)
        except Exception:
            workspace = {}
        items = workspace.get("items") if isinstance(workspace, dict) else []
        rows: Dict[int, Dict[str, Any]] = {}
        for item in items or []:
            if not isinstance(item, dict):
                continue
            try:
                sequence = int(item.get("sequence_num") or 0)
            except Exception:
                sequence = 0
            if sequence > 0:
                rows[sequence] = item
        return rows

    def _panel_context_rows(self, *, episode: Episode, panels: List[Panel], target_kind: str) -> List[Dict[str, Any]]:
        workspace_items = self._workspace_items(episode)
        rows: List[Dict[str, Any]] = []
        for panel in panels:
            sequence = int(getattr(panel, "sequence_num", 0) or 0)
            item = workspace_items.get(sequence) or {}
            rows.append(
                {
                    "panel_id": int(getattr(panel, "id", 0) or 0),
                    "sequence_num": sequence,
                    "title": _clean_text(getattr(panel, "title", None)) or f"第 {sequence} 镜",
                    "summary": _clean_text(getattr(panel, "segment_summary", None) or getattr(panel, "scene_prompt", None)),
                    "grid_count": int(getattr(panel, "grid_count", None) or 1),
                    "recommended_duration_seconds": int(getattr(panel, "recommended_duration_seconds", None) or 0),
                    "reference_assets": item.get("reference_assets") if isinstance(item.get("reference_assets"), list) else [],
                    "grid_cells": item.get("grid_cells") if isinstance(item.get("grid_cells"), list) else [],
                    "original_image_prompt": _clean_text(getattr(panel, "multi_shot_prompt", None) or getattr(panel, "prompt", None)),
                    "original_video_prompt": _clean_text(getattr(panel, "multi_shot_video_prompt", None) or getattr(panel, "video_prompt", None)),
                    "target_kind": target_kind,
                }
            )
        return rows

    def _fallback_rewrite_row(self, row: Dict[str, Any], instruction: str, target_kind: str, valid_names: set[str]) -> Dict[str, Any]:
        image_prompt = row.get("original_image_prompt") or ""
        video_prompt = row.get("original_video_prompt") or ""
        suffix = f"\n\n用户改写要求：{instruction}" if instruction else ""
        return {
            "sequence_num": int(row.get("sequence_num") or 0),
            "target": {"image": target_kind in {"image", "both"}, "video": target_kind in {"video", "both"}},
            "original_image_prompt": image_prompt,
            "new_image_prompt": _sanitize_asset_mentions(f"{image_prompt}{suffix}".strip(), valid_names) if target_kind in {"image", "both"} else "",
            "original_video_prompt": video_prompt,
            "new_video_prompt": _sanitize_asset_mentions(f"{video_prompt}{suffix}".strip(), valid_names) if target_kind in {"video", "both"} else "",
            "rewrite_note": "DeepSeek 不可用时按用户要求追加为显式约束。",
            "status": "ready",
        }

    def _call_rewrite_model(
        self,
        *,
        target_kind: str,
        instruction: str,
        panel_rows: List[Dict[str, Any]],
        workflow_profile: Dict[str, Any],
        valid_names: set[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        system_prompt = """
你是神鹿 AI 短剧平台的提示词导演。你的任务是按用户要求改写现有分镜图片/视频提示词。
必须只输出 JSON 对象，不要输出解释。
规则：
1. 不改变剧情事实、宫格数、分镜顺序、参考资产绑定、模型参数。
2. 图片提示词保持“分镜设定 + [宫格1]...[宫格N]”的标准展示态。
3. 视频提示词保持“分镜设定 / 参考映射 / 时间轴 / 质量约束”的标准展示态。
4. 只能保留资产白名单中存在的 @资产名，不得创造新的 @引用。
5. 对话、旁白、内心 OS 只能来自当前分镜事实或用户明确要求。
返回格式：
{
  "rows": [
    {
      "sequence_num": 1,
      "new_image_prompt": "...",
      "new_video_prompt": "...",
      "rewrite_note": "..."
    }
  ],
  "model_suggestion": {"reason": "..."}
}
""".strip()
        user_payload = {
            "target_kind": target_kind,
            "rewrite_instruction": instruction,
            "asset_name_whitelist": sorted(valid_names),
            "workflow_profile": workflow_profile,
            "panels": panel_rows,
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _json_dumps(user_payload)},
        ]
        prompt_text = "\n".join(item["content"] for item in messages)
        if not settings.DEEPSEEK_API_KEY:
            return (
                [self._fallback_rewrite_row(row, instruction, target_kind, valid_names) for row in panel_rows],
                {
                    "usage": {
                        "prompt_tokens": estimate_text_tokens(prompt_text),
                        "prompt_cache_hit_tokens": 0,
                        "prompt_cache_miss_tokens": estimate_text_tokens(prompt_text),
                        "completion_tokens": 0,
                    },
                    "actual_cost_cny": 0.0,
                    "charged_points": 0,
                    "points_status": "free",
                    "model": DEEPSEEK_V4_FLASH_MODEL,
                    "fallback": True,
                },
            )
        model, thinking_enabled = normalize_deepseek_model(settings.DEEPSEEK_AGENT_DEFAULT_MODEL or DEEPSEEK_V4_FLASH_MODEL)
        client = OpenAI(api_key=settings.DEEPSEEK_API_KEY, base_url="https://api.deepseek.com", timeout=180.0)
        last_error: Optional[Exception] = None
        for attempt in range(3):
            try:
                request_kwargs = normalize_deepseek_request_kwargs(
                    {
                        "model": model,
                        "messages": messages,
                        "response_format": {"type": "json_object"},
                        "temperature": 0.1,
                        "max_tokens": 12000,
                    },
                    thinking_enabled=thinking_enabled,
                )
                response = client.chat.completions.create(**request_kwargs)
                content = ""
                if response.choices and response.choices[0].message:
                    content = _clean_text(response.choices[0].message.content)
                if not content:
                    raise RuntimeError("empty_response:deepseek-v4-flash")
                payload = json.loads(content)
                raw_rows = payload.get("rows") if isinstance(payload, dict) else []
                if not isinstance(raw_rows, list) or not raw_rows:
                    raise RuntimeError("prompt_rewrite_empty_rows")
                usage = _response_usage_to_dict(response, prompt_text=prompt_text, output_text=content)
                cost_cny = calculate_deepseek_v4_flash_usage_cost_cny(usage)
                points = _points_from_cost(cost_cny)
                return raw_rows, {
                    "usage": usage,
                    "actual_cost_cny": float(cost_cny),
                    "charged_points": points,
                    "points_status": "deducted" if points > 0 else "free",
                    "model": model,
                    "fallback": False,
                    "attempt": attempt + 1,
                    "model_suggestion_raw": payload.get("model_suggestion") if isinstance(payload.get("model_suggestion"), dict) else {},
                }
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"提示词改写返回了非法 JSON：{last_error}")

    def _normalize_rewrite_rows(
        self,
        *,
        raw_rows: List[Dict[str, Any]],
        source_rows: List[Dict[str, Any]],
        target_kind: str,
        valid_names: set[str],
    ) -> List[Dict[str, Any]]:
        source_by_sequence = {int(row.get("sequence_num") or 0): row for row in source_rows}
        raw_by_sequence: Dict[int, Dict[str, Any]] = {}
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            try:
                sequence = int(item.get("sequence_num") or 0)
            except Exception:
                sequence = 0
            if sequence > 0:
                raw_by_sequence[sequence] = item
        normalized: List[Dict[str, Any]] = []
        for sequence, source in source_by_sequence.items():
            item = raw_by_sequence.get(sequence) or {}
            original_image = _clean_text(source.get("original_image_prompt"))
            original_video = _clean_text(source.get("original_video_prompt"))
            new_image = _clean_text(item.get("new_image_prompt"))
            new_video = _clean_text(item.get("new_video_prompt"))
            if target_kind in {"image", "both"} and not new_image:
                new_image = original_image
            if target_kind in {"video", "both"} and not new_video:
                new_video = original_video
            normalized.append(
                {
                    "sequence_num": sequence,
                    "target_label": {"image": "图片", "video": "视频", "both": "图片+视频"}.get(target_kind, "图片+视频"),
                    "target": {"image": target_kind in {"image", "both"}, "video": target_kind in {"video", "both"}},
                    "original_image_prompt": original_image,
                    "original_video_prompt": original_video,
                    "original_prompt_summary": _prompt_summary(original_image if target_kind == "image" else original_video if target_kind == "video" else original_image or original_video),
                    "new_image_prompt": _sanitize_asset_mentions(new_image, valid_names) if target_kind in {"image", "both"} else "",
                    "new_video_prompt": _sanitize_asset_mentions(new_video, valid_names) if target_kind in {"video", "both"} else "",
                    "new_prompt": _sanitize_asset_mentions(new_image if target_kind == "image" else new_video if target_kind == "video" else new_image or new_video, valid_names),
                    "rewrite_note": _clean_text(item.get("rewrite_note") or item.get("reason")) or "已按用户要求改写。",
                    "status": "ready",
                }
            )
        return normalized

    def _estimate_current_model(self, *, context: Dict[str, Any], target_kind: str, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        script = context["script"]
        episode = context.get("episode")
        workflow_profile = context.get("workflow_profile") or {}
        image_profile = workflow_profile.get("image") if isinstance(workflow_profile.get("image"), dict) else {}
        video_profile = workflow_profile.get("video") if isinstance(workflow_profile.get("video"), dict) else {}
        first_row = rows[0] if rows else {}
        image_points = 0
        video_points = 0
        try:
            if target_kind in {"image", "both"}:
                _, image_points = _estimate_image_public_params(
                    self.session,
                    {
                        "ownership_mode": "project",
                        "project_id": encode_id(script.id),
                        "episode_id": encode_id(episode.id) if episode else None,
                        "target_type": "panel",
                        "target_id": encode_id(int(first_row.get("panel_id") or 0)) if first_row.get("panel_id") else None,
                        "mode": "text_to_image",
                        "model_code": image_profile.get("model_code"),
                        "resolution": image_profile.get("resolution"),
                        "aspect_ratio": workflow_profile.get("aspect_ratio") or "16:9",
                        "prompt": first_row.get("original_image_prompt") or "prompt",
                    },
                )
            if target_kind in {"video", "both"}:
                _, video_points = _estimate_video_public_params(
                    self.session,
                    {
                        "ownership_mode": "project",
                        "project_id": encode_id(script.id),
                        "episode_id": encode_id(episode.id) if episode else None,
                        "target_type": "panel",
                        "target_id": encode_id(int(first_row.get("panel_id") or 0)) if first_row.get("panel_id") else None,
                        "model_code": video_profile.get("model_code"),
                        "generation_type": video_profile.get("generation_type"),
                        "duration": video_profile.get("duration") or first_row.get("recommended_duration_seconds") or 5,
                        "resolution": video_profile.get("resolution"),
                        "aspect_ratio": workflow_profile.get("aspect_ratio") or "16:9",
                        "prompt": first_row.get("original_video_prompt") or "prompt",
                    },
                )
        except Exception:
            pass
        if target_kind == "video":
            current_name = _clean_text(video_profile.get("model_code")) or "当前视频模型"
            points = video_points
            detail = f"{current_name} / {video_profile.get('resolution') or '默认清晰度'} / {video_profile.get('duration') or '自动'}秒"
        else:
            current_name = _clean_text(image_profile.get("model_code")) or "当前图片模型"
            points = image_points
            detail = f"{current_name} / {image_profile.get('resolution') or '默认清晰度'}"
        return {
            "current": {
                "model_name": current_name,
                "detail": detail,
                "estimate_points": int(points or 0),
            },
            "recommended": {
                "model_name": current_name,
                "detail": detail,
                "estimate_points": int(points or 0),
                "reason": "默认沿用当前项目模型，避免静默改变预算和结果风格。",
                "payload": {},
                "price_delta_points": 0,
            },
        }

    def _charge_rewrite_points(self, *, context: Dict[str, Any], billing: Dict[str, Any]) -> Dict[str, Any]:
        points = int(billing.get("charged_points") or 0)
        if points <= 0:
            return billing
        try:
            deduct_inspiration_points(
                user=context["user"],
                team=context["team"],
                cost=points,
                action_type="prompt_rewrite",
                description="Agent 提示词改写",
                session=self.session,
            )
            self.session.commit()
        except HTTPException as exc:
            raise ValueError(f"提示词改写灵感值不足：{exc.detail}") from exc
        return billing

    def _build_actions(self, bundle: Dict[str, Any], *, generate_after: str) -> List[Dict[str, Any]]:
        base_payload = {
            "operation": "apply_and_generate",
            "rewrite_id": bundle.get("rewrite_id"),
            "generate_after": generate_after if generate_after != "none" else bundle.get("target_kind") or "image",
        }
        return [
            {"type": "rewrite_generation_prompts", "label": "保存提示词并生成", "payload": base_payload},
            {"type": "rewrite_generation_prompts", "label": "仅保存提示词", "payload": {"operation": "apply", "rewrite_id": bundle.get("rewrite_id")}},
            {"type": "rewrite_generation_prompts", "label": "继续调整", "payload": {"operation": "preview", "rewrite_id": bundle.get("rewrite_id")}},
            {"type": "rewrite_generation_prompts", "label": "取消", "payload": {"operation": "cancel", "rewrite_id": bundle.get("rewrite_id")}},
            {"type": "rewrite_generation_prompts", "label": "用上次生成提示词恢复", "payload": {"operation": "restore_last_generated", "target_kind": bundle.get("target_kind")}},
            {
                "type": "rewrite_generation_prompts",
                "label": "采用推荐模型并生成",
                "payload": {**base_payload, "use_recommended_model": True},
            },
        ]

    def _preview(self, context: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        episode = context.get("episode")
        if episode is None:
            raise ValueError("请先选中一个具体剧集，我才能改写分镜提示词")
        target_kind = _normalize_target_kind(payload.get("target_kind"))
        instruction = _clean_text(payload.get("rewrite_instruction") or payload.get("instruction") or context.get("latest_user_message"))
        latest_bundle = (context.get("latest_artifacts") or {}).get("prompt_rewrite_bundle")
        if not instruction and isinstance(latest_bundle, dict):
            instruction = _clean_text(latest_bundle.get("rewrite_instruction"))
        if not instruction:
            raise ValueError("请告诉我这次希望怎样改写提示词，例如“更电影感”“改成雨夜”“动作更激烈”。")
        panels = self._panels_by_payload(episode, payload)
        if not panels:
            raise ValueError("当前没有找到可改写的分镜")
        source_rows = self._panel_context_rows(episode=episode, panels=panels, target_kind=target_kind)
        valid_names = self._valid_asset_names(context["script"].id)
        callback = context.get("runtime_event_callback")
        if callable(callback):
            callback(
                "prompt_rewrite_delta",
                {
                    "title": "提示词改写预览",
                    "rows": [
                        {"sequence_num": row["sequence_num"], "target_label": {"image": "图片", "video": "视频", "both": "图片+视频"}.get(target_kind, "图片+视频"), "status": "改写中"}
                        for row in source_rows
                    ],
                },
            )
        raw_rows, billing = self._call_rewrite_model(
            target_kind=target_kind,
            instruction=instruction,
            panel_rows=source_rows,
            workflow_profile=context.get("workflow_profile") or {},
            valid_names=valid_names,
        )
        billing = self._charge_rewrite_points(context=context, billing=billing)
        rows = self._normalize_rewrite_rows(raw_rows=raw_rows, source_rows=source_rows, target_kind=target_kind, valid_names=valid_names)
        model_suggestion = self._estimate_current_model(context=context, target_kind=target_kind, rows=source_rows)
        latest_version = int(latest_bundle.get("version") or 0) if isinstance(latest_bundle, dict) else 0
        bundle = {
            "artifact_type": "prompt_rewrite_bundle",
            "rewrite_id": uuid.uuid4().hex,
            "version": latest_version + 1,
            "status": "ready",
            "target_kind": target_kind,
            "source_episode_id": encode_id(episode.id),
            "rewrite_instruction": instruction,
            "rows": rows,
            "billing": {
                "charged_points": int(billing.get("charged_points") or 0),
                "actual_cost_cny": float(billing.get("actual_cost_cny") or 0),
                "usage": billing.get("usage") or {},
                "points_status": billing.get("points_status") or "free",
                "display": f"✦ {int(billing.get('charged_points') or 0)}",
            },
            "model_suggestion": model_suggestion,
        }
        if callable(callback):
            callback("prompt_rewrite_delta", {"title": "提示词改写预览", "rows": rows, "billing": bundle["billing"], "prompt_rewrite_bundle": bundle})
            callback("prompt_rewrite_ready", {"rewrite_id": bundle["rewrite_id"], "rows": rows, "prompt_rewrite_bundle": bundle})
        generate_after = _normalize_generate_after(payload.get("generate_after"), target_kind)
        return {
            "message": "提示词改写预览已经生成。你可以确认保存并生成，也可以继续提出调整意见。",
            "result": bundle,
            "artifacts": {"prompt_rewrite_bundle": bundle},
            "suggested_actions": self._build_actions(bundle, generate_after=generate_after),
            "refresh_hints": {},
            "next_stage_hint": context.get("creative_stage") or "storyboard_ready",
        }

    def _bundle_from_context(self, context: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        bundle = payload.get("prompt_rewrite_bundle") if isinstance(payload.get("prompt_rewrite_bundle"), dict) else None
        if bundle:
            return dict(bundle)
        latest = (context.get("latest_artifacts") or {}).get("prompt_rewrite_bundle")
        if isinstance(latest, dict):
            if not _clean_text(payload.get("rewrite_id")) or _clean_text(payload.get("rewrite_id")) == _clean_text(latest.get("rewrite_id")):
                return dict(latest)
        raise ValueError("没有找到可确认的提示词改写预览，请先让 Agent 改写一次提示词。")

    def _apply_bundle(self, context: Dict[str, Any], payload: Dict[str, Any], *, generate: bool = False) -> Dict[str, Any]:
        episode = context.get("episode")
        if episode is None:
            raise ValueError("请先选中一个具体剧集")
        bundle = self._bundle_from_context(context, payload)
        rows = [row for row in bundle.get("rows") or [] if isinstance(row, dict)]
        if not rows:
            raise ValueError("提示词改写预览为空，无法保存")
        panel_map = {int(getattr(panel, "sequence_num", 0) or 0): panel for panel in self._list_episode_panels(episode.id)}
        saved_sequences: List[int] = []
        for row in rows:
            sequence = int(row.get("sequence_num") or 0)
            panel = panel_map.get(sequence)
            if not panel:
                continue
            payload_update: Dict[str, Any] = {"source": "agent_prompt_rewrite"}
            if row.get("target", {}).get("image") and _clean_text(row.get("new_image_prompt")):
                payload_update["multi_shot_prompt"] = _clean_text(row.get("new_image_prompt"))
                payload_update["prompt"] = payload_update["multi_shot_prompt"]
                payload_update["prompt_zh"] = payload_update["multi_shot_prompt"]
            if row.get("target", {}).get("video") and _clean_text(row.get("new_video_prompt")):
                payload_update["multi_shot_video_prompt"] = _clean_text(row.get("new_video_prompt"))
                payload_update["video_prompt"] = payload_update["multi_shot_video_prompt"]
            update_panel_with_revision(
                self.session,
                panel,
                payload_update,
                created_by_user_id=getattr(context.get("user"), "id", None),
            )
            saved_sequences.append(sequence)
        bundle["status"] = "applied"
        callback = context.get("runtime_event_callback")
        if callable(callback):
            callback("prompt_rewrite_applied", {"rewrite_id": bundle.get("rewrite_id"), "rows": rows})
            callback("storyboard_workspace_delta", {"episode_id": encode_id(episode.id), "refresh_hints": {"segment_workspace": True, "panels": True}})
        result: Dict[str, Any] = {
            "message": f"已保存 {len(saved_sequences)} 个分镜的改写提示词。",
            "result": bundle,
            "artifacts": {"prompt_rewrite_bundle": bundle},
            "refresh_hints": {"panels": True, "segment_workspace": True},
            "next_stage_hint": context.get("creative_stage") or "storyboard_ready",
            "suggested_actions": [],
        }
        if generate:
            generate_after = _normalize_generate_after(payload.get("generate_after"), _clean_text(bundle.get("target_kind")) or "both")
            generation_payload: Dict[str, Any] = {"selected_panel_sequences": saved_sequences}
            if payload.get("use_recommended_model"):
                recommendation = bundle.get("model_suggestion", {}).get("recommended") if isinstance(bundle.get("model_suggestion"), dict) else {}
                if isinstance(recommendation, dict) and isinstance(recommendation.get("payload"), dict):
                    generation_payload.update(recommendation.get("payload") or {})
            generator = GenerationAgent(self.session)
            generation_results: List[Dict[str, Any]] = []
            if generate_after in {"image", "both"}:
                generation_results.append(generator.execute_action(context, "generate_storyboard_images", payload=generation_payload))
            if generate_after in {"video", "both"}:
                generation_results.append(generator.execute_action(context, "generate_video", payload=generation_payload))
            submitted = sum(int((item.get("result") or {}).get("submitted_count") or 0) for item in generation_results)
            result["message"] = f"已保存改写提示词，并提交 {submitted} 个生成任务。"
            result["refresh_hints"] = {"panels": True, "segment_workspace": True, "generation_tasks": True}
            result["next_stage_hint"] = generation_results[-1].get("next_stage_hint") if generation_results else result["next_stage_hint"]
        return result

    def _restore_last_generated(self, context: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        episode = context.get("episode")
        if episode is None:
            raise ValueError("请先选中一个具体剧集")
        target_kind = _normalize_target_kind(payload.get("target_kind"))
        panels = self._panels_by_payload(episode, payload)
        if not panels:
            raise ValueError("当前没有找到可恢复的分镜")
        restored_sequences: List[int] = []
        for panel in panels:
            record_types = []
            if target_kind in {"image", "both"}:
                record_types.append(RECORD_TYPE_IMAGE)
            if target_kind in {"video", "both"}:
                record_types.append(RECORD_TYPE_VIDEO)
            updates: Dict[str, Any] = {"source": "agent_prompt_restore"}
            for record_type in record_types:
                record = self.session.exec(
                    select(GenerationRecord)
                    .where(GenerationRecord.episode_id == episode.id)
                    .where(GenerationRecord.target_type == TARGET_TYPE_PANEL)
                    .where(GenerationRecord.target_id == panel.id)
                    .where(GenerationRecord.record_type == record_type)
                    .order_by(GenerationRecord.id.desc())
                ).first()
                prompt = _clean_text(getattr(record, "prompt", None)) if record else ""
                if not prompt:
                    continue
                if record_type == RECORD_TYPE_IMAGE:
                    updates["multi_shot_prompt"] = prompt
                    updates["prompt"] = prompt
                    updates["prompt_zh"] = prompt
                else:
                    updates["multi_shot_video_prompt"] = prompt
                    updates["video_prompt"] = prompt
            if len(updates) > 1:
                update_panel_with_revision(self.session, panel, updates, created_by_user_id=getattr(context.get("user"), "id", None))
                restored_sequences.append(int(getattr(panel, "sequence_num", 0) or 0))
        return {
            "message": f"已从历史生成记录恢复 {len(restored_sequences)} 个分镜的提示词。",
            "result": {
                "artifact_type": "prompt_rewrite_bundle",
                "status": "restored",
                "target_kind": target_kind,
                "rows": [{"sequence_num": item, "status": "已恢复"} for item in restored_sequences],
            },
            "refresh_hints": {"panels": True, "segment_workspace": True},
            "next_stage_hint": context.get("creative_stage") or "storyboard_ready",
        }

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return self.build_response(
            stage=context.get("creative_stage") or "storyboard_ready",
            stage_label=context.get("creative_stage_label") or "分镜提示词",
            message="你可以告诉我想怎样调整图片或视频提示词，我会先给出可确认的改写预览。",
            suggested_actions=[],
            artifacts={},
            next_stage_hint=context.get("creative_stage") or "storyboard_ready",
        )

    def execute_action(self, context: Dict[str, Any], action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = dict(payload or {})
        operation = _normalize_operation(payload.get("operation"))
        if operation == "cancel":
            return {
                "message": "已取消本次提示词改写，分镜表不会发生变化。",
                "result": {"artifact_type": "prompt_rewrite_bundle", "status": "cancelled"},
                "refresh_hints": {},
                "next_stage_hint": context.get("creative_stage") or "storyboard_ready",
            }
        if operation == "restore_last_generated":
            return self._restore_last_generated(context, payload)
        if operation == "apply":
            return self._apply_bundle(context, payload, generate=False)
        if operation == "apply_and_generate":
            return self._apply_bundle(context, payload, generate=True)
        return self._preview(context, payload)
