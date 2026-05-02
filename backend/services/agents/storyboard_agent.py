from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.config import settings
from services.story_segment_service import build_episode_segment_workspace, commit_story_segments_with_cells
from services.storyboard_split_runtime import (
    StoryboardSplitBillingTracker,
    build_storyboard_plan_bundle,
    build_storyboard_split_structured_draft,
)
from services.workflow_preset_service import resolve_storyboard_extraction_storyboard_mode

from .base_agent import BaseAgent
from .stage_action_registry import storyboard_pending_actions, storyboard_ready_actions


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_list(values: Any) -> List[str]:
    if isinstance(values, list):
        return [str(item or "").strip() for item in values if str(item or "").strip()]
    text = _clean_text(values)
    if not text:
        return []
    return [item.strip() for item in text.replace("，", ",").split(",") if item.strip()]


def _safe_int(value: Any, fallback: int = 1) -> int:
    try:
        result = int(value or fallback)
    except Exception:
        result = fallback
    return result if result > 0 else fallback


def _duration_seconds(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(int(float(value)), 0)
    except Exception:
        match = re.search(r"\d+(?:\.\d+)?", str(value or ""))
        if not match:
            return 0
        try:
            return max(int(float(match.group(0))), 0)
        except Exception:
            return 0


def _plan_total_duration_seconds(plan_bundle: Dict[str, Any], rows: List[Dict[str, Any]]) -> int:
    explicit_total = _duration_seconds(
        plan_bundle.get("total_estimated_duration_seconds") or plan_bundle.get("total_duration_seconds")
    )
    if explicit_total:
        return explicit_total
    return sum(_duration_seconds(row.get("estimated_duration_seconds") or row.get("duration_seconds")) for row in rows)


def _segment_title(item: Dict[str, Any], index: int) -> str:
    title = _clean_text(item.get("title"))
    if title:
        return title
    summary = _clean_text(item.get("summary") or item.get("description") or item.get("scene_prompt"))
    if summary:
        return summary[:24]
    return f"分镜 {index}"


def _normalize_storyboard_segment(item: Dict[str, Any], index: int) -> Dict[str, Any]:
    summary = _clean_text(
        item.get("summary")
        or item.get("description")
        or item.get("segment_summary")
        or item.get("scene_prompt")
        or item.get("title")
    )
    scene_name = _clean_text(item.get("scene_name") or item.get("scene"))
    character_refs = _clean_list(item.get("character_refs") or item.get("characters") or item.get("character"))
    scene_refs = _clean_list(item.get("scene_refs") or ([scene_name] if scene_name else []))
    prop_refs = _clean_list(item.get("prop_refs") or item.get("props") or item.get("prop"))
    duration = item.get("recommended_duration_seconds") or item.get("duration_seconds") or 6
    grid_cells = item.get("grid_cells") if isinstance(item.get("grid_cells"), list) else []
    if not grid_cells:
        grid_cells = [
            {
                "cell_index": 1,
                "shot_description": summary,
                "action_description": _clean_text(item.get("action_description")),
                "dialogue_excerpt": _clean_text(item.get("dialogue_excerpt")),
                "speech_items": item.get("speech_items") if isinstance(item.get("speech_items"), list) else [],
                "performance_focus": _clean_text(item.get("performance_focus")),
                "mouth_sync_required": bool(item.get("mouth_sync_required")),
                "character_refs": character_refs,
                "scene_refs": scene_refs,
                "prop_refs": prop_refs,
                "duration_seconds": duration,
                "image_prompt": _clean_text(item.get("image_prompt")),
                "video_prompt": _clean_text(item.get("video_prompt")),
            }
        ]
    return {
        "sequence_num": _safe_int(item.get("sequence_num") or item.get("segment_no") or index),
        "title": _segment_title(item, index),
        "summary": summary,
        "grid_count": _safe_int(item.get("grid_count") or len(grid_cells) or 1),
        "recommended_duration_seconds": duration,
        "scene_refs": scene_refs,
        "character_refs": character_refs,
        "prop_refs": prop_refs,
        "text_span": item.get("text_span") if isinstance(item.get("text_span"), dict) else {"source_excerpt": summary},
        "grid_cells": grid_cells,
    }


def _storyboard_rows_from_segments(story_segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, item in enumerate(story_segments[:20], start=1):
        rows.append(
            {
                "sequence_num": _safe_int(item.get("sequence_num") or index),
                "description": _clean_text(item.get("summary") or item.get("description") or item.get("title")),
                "scene_name": _clean_text(
                    (item.get("scene_refs") or [None])[0]
                    or item.get("scene_name")
                    or item.get("scene")
                ),
                "duration_seconds": item.get("recommended_duration_seconds") or item.get("duration_seconds") or "",
            }
        )
    return rows


def _storyboard_plan_actions(plan_id: str) -> List[Dict[str, Any]]:
    return [
        {
            "type": "extract_storyboard",
            "label": "根据规划计划分镜",
            "payload": {"mode": "split_confirmed", "confirmed_plan_id": plan_id},
        },
        {
            "type": "extract_storyboard",
            "label": "增加时长",
            "payload": {"mode": "plan_first", "plan_revision_instruction": "整体增加每个剧情片段的预计时长，保留剧情顺序。"},
        },
        {
            "type": "extract_storyboard",
            "label": "增加分镜",
            "payload": {"mode": "plan_first", "plan_revision_instruction": "增加剧情片段数量，把关键动作拆得更细。"},
        },
        {
            "type": "extract_storyboard",
            "label": "减少分镜",
            "payload": {"mode": "plan_first", "plan_revision_instruction": "减少剧情片段数量，合并节奏相近的片段。"},
        },
        {
            "type": "extract_storyboard",
            "label": "细分某段",
            "payload": {"mode": "plan_first", "plan_revision_instruction": "请细分用户指定的剧情片段；如果没有指定，优先细分信息量最大的片段。"},
        },
        {
            "type": "extract_storyboard",
            "label": "合并某几段",
            "payload": {"mode": "plan_first", "plan_revision_instruction": "请合并用户指定或节奏相近的剧情片段。"},
        },
    ]


def _plan_bundle_from_context(context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    latest_artifacts = context.get("latest_artifacts") if isinstance(context.get("latest_artifacts"), dict) else {}
    bundle = latest_artifacts.get("storyboard_plan_bundle")
    if isinstance(bundle, dict) and isinstance(bundle.get("rows"), list):
        return bundle
    return None


def _plan_rows_for_runtime(plan_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, row in enumerate(list(plan_bundle.get("rows") or []), start=1):
        if not isinstance(row, dict):
            continue
        rows.append(
            {
                "sequence_num": _safe_int(row.get("sequence_num") or index),
                "story_fragment": _clean_text(row.get("story_fragment") or row.get("summary") or row.get("description")),
                "dialogue": _clean_text(row.get("dialogue")),
                "estimated_duration_seconds": row.get("estimated_duration_seconds") or row.get("duration_seconds") or "",
            }
        )
    return rows


def _billing_tracker_from_context(context: Dict[str, Any]) -> Optional[StoryboardSplitBillingTracker]:
    user = context.get("user")
    team = context.get("team")
    user_id = getattr(user, "id", None)
    team_id = getattr(team, "id", None)
    if user_id is None or team_id is None:
        return None
    return StoryboardSplitBillingTracker(
        user_id=int(user_id),
        team_id=int(team_id),
        task_id=None,
        charge_enabled=True,
    )


def _pending_storyboard_image_sequences_from_segments(story_segments: List[Dict[str, Any]]) -> List[int]:
    sequences: List[int] = []
    for item in story_segments or []:
        if not isinstance(item, dict):
            continue
        try:
            sequence = int(item.get("sequence_num") or 0)
        except Exception:
            continue
        if sequence > 0 and sequence not in sequences:
            sequences.append(sequence)
    return sequences


_SCRIPT_SCENE_HEADING_RE = re.compile(r"^\s*(场景[一二三四五六七八九十百\d]+[：:].+|片尾画面[：:]?)\s*$")


def _script_source_blocks(text: str) -> List[Dict[str, str]]:
    source = str(text or "").replace("\r\n", "\n").strip()
    source = re.sub(r"^【\s*剧本正文\s*】\s*", "", source).strip()
    if not source:
        return []

    blocks: List[Dict[str, str]] = []
    current_title = ""
    current_lines: List[str] = []

    def _flush() -> None:
        nonlocal current_title, current_lines
        body = "\n".join([line.strip() for line in current_lines if line.strip()]).strip()
        if current_title or body:
            blocks.append({"title": current_title or f"剧情片段{len(blocks) + 1}", "body": body or current_title})
        current_title = ""
        current_lines = []

    for raw_line in source.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _SCRIPT_SCENE_HEADING_RE.match(line):
            _flush()
            current_title = line.rstrip("：:")
            continue
        current_lines.append(line)
    _flush()

    if blocks:
        return blocks[:60]

    paragraphs = [item.strip() for item in re.split(r"\n{2,}", source) if item.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [item.strip() for item in source.splitlines() if item.strip()]
    return [
        {"title": f"剧情片段{index}", "body": paragraph}
        for index, paragraph in enumerate(paragraphs[:60], start=1)
    ]


def _short_summary(text: str, limit: int = 56) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def _scene_ref_from_title(title: str) -> List[str]:
    text = str(title or "").strip()
    if not text:
        return []
    if "：" in text:
        text = text.split("：", 1)[1]
    elif ":" in text:
        text = text.split(":", 1)[1]
    text = re.split(r"[·/｜| ]", text.strip(), maxsplit=1)[0].strip()
    return [text] if text else []


def _fallback_story_segments_from_script(text: str) -> List[Dict[str, Any]]:
    segments: List[Dict[str, Any]] = []
    for index, block in enumerate(_script_source_blocks(text), start=1):
        title = _clean_text(block.get("title")) or f"剧情片段{index}"
        body = _clean_text(block.get("body")) or title
        summary = _short_summary(body)
        duration = 6 if len(body) >= 80 else 4
        scene_refs = _scene_ref_from_title(title)
        segments.append(
            {
                "sequence_num": index,
                "title": title,
                "summary": summary,
                "segment_prompt_summary": summary,
                "recommended_duration_seconds": duration,
                "grid_count": 1,
                "scene_refs": scene_refs,
                "character_refs": [],
                "prop_refs": [],
                "text_span": {"source_excerpt": body},
                "grid_cells": [
                    {
                        "cell_index": 1,
                        "start_second": 0,
                        "end_second": duration,
                        "duration_seconds": duration,
                        "shot_description": summary,
                        "action_description": summary,
                        "dialogue_excerpt": "",
                        "speech_items": [],
                        "character_refs": [],
                        "scene_refs": scene_refs,
                        "prop_refs": [],
                    }
                ],
            }
        )
    return segments


def _looks_like_storyboard_request(text: str) -> bool:
    normalized = _clean_text(text).lower()
    if not normalized:
        return False
    keywords = [
        "提取分镜",
        "拆分镜",
        "拆镜",
        "生成分镜",
        "整理分镜",
        "分镜拆解",
        "分镜板",
        "storyboard",
    ]
    return any(token in normalized for token in keywords)


class StoryboardAgent(BaseAgent):
    agent_name = "storyboard_agent"
    agent_label = "分镜导演"

    def _artifact_bundle(
        self,
        context: Dict[str, Any],
        *,
        structured_draft: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        episode = context.get("episode")
        if episode is None:
            return {}
        if structured_draft:
            story_segments = list(structured_draft.get("story_segments") or [])
            rows = _storyboard_rows_from_segments(story_segments)
            return {
                "storyboard_bundle": {
                    "artifact_type": "storyboard_bundle",
                    "storyboard_rows": rows,
                    "segment_draft": story_segments[:20],
                    "gridcell_draft": [],
                    "storyboard_summary": f"已整理 {len(story_segments)} 个分镜片段",
                }
            }

        from services.panel_service import list_panels as list_panels_service
        from services.storyboard_mode_service import dependency_sequence_lookup

        panels = list_panels_service(self.session, context["team"], episode.id)
        workspace = build_episode_segment_workspace(
            self.session,
            episode,
            panels,
            dependency_sequence_lookup(self.session, episode.id),
        )
        segments = workspace.get("segments") or []
        rows = [
            {
                "sequence_num": item.get("sequence_num"),
                "description": _clean_text(item.get("segment_summary") or item.get("scene_prompt")),
                "scene_name": _clean_text(item.get("scene_name") or item.get("scene")),
                "duration_seconds": item.get("recommended_duration_seconds") or "",
            }
            for item in segments[:20]
        ]
        return {
            "storyboard_bundle": {
                "artifact_type": "storyboard_bundle",
                "storyboard_rows": rows,
                "segment_draft": [],
                "gridcell_draft": [],
                "storyboard_summary": f"当前分镜数：{len(segments)}",
            }
        }

    def _run_plan_storyboard(self, context: Dict[str, Any], payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        script_text = _clean_text(context.get("current_script"))
        script = context.get("script")
        episode = context.get("episode")
        payload = payload or {}
        if episode is None:
            raise ValueError("当前动作需要绑定到具体分集。")
        if not script_text:
            raise ValueError("当前分集还没有可拆解的剧本文本。")
        if not settings.DEEPSEEK_API_KEY:
            raise ValueError("当前分镜拆解服务暂时不可用，请稍后重试。")
        runtime_event_callback = context.get("runtime_event_callback")
        billing_tracker = _billing_tracker_from_context(context)
        revision_instruction = _clean_text(payload.get("plan_revision_instruction"))
        if not revision_instruction:
            latest_message = _clean_text(context.get("latest_user_message"))
            if _plan_bundle_from_context(context) and latest_message and not _looks_like_storyboard_request(latest_message):
                revision_instruction = latest_message
        previous_plan_bundle = _plan_bundle_from_context(context)
        plan_bundle = build_storyboard_plan_bundle(
            episode_id=episode.id,
            text=script_text,
            api_key=settings.DEEPSEEK_API_KEY,
            storyboard_mode=resolve_storyboard_extraction_storyboard_mode(script) if script is not None else getattr(episode, "storyboard_mode", None),
            previous_plan_bundle=previous_plan_bundle,
            revision_instruction=revision_instruction,
            billing_tracker=billing_tracker,
        )
        rows = _plan_rows_for_runtime(plan_bundle)
        total_duration_seconds = _plan_total_duration_seconds(plan_bundle, rows)
        if callable(runtime_event_callback):
            runtime_event_callback(
                "storyboard_plan_delta",
                {
                    "artifact_type": "storyboard_plan_bundle",
                    "title": "剧情片段规划",
                    "summary": f"已生成第 {plan_bundle.get('version')} 版规划，共 {len(rows)} 段。",
                    "rows": rows,
                    "total_estimated_duration_seconds": total_duration_seconds,
                    "total_duration_seconds": total_duration_seconds,
                    "storyboard_plan_bundle": plan_bundle,
                },
            )
            runtime_event_callback(
                "storyboard_plan_ready",
                {
                    "plan_id": plan_bundle.get("plan_id"),
                    "version": plan_bundle.get("version"),
                    "status": "ready",
                },
            )
        return {
            "message": "剧情片段规划粗稿已经生成。你可以直接确认进入正式分镜，也可以继续提出调整意见。",
            "result": plan_bundle,
            "artifacts": {"storyboard_plan_bundle": plan_bundle},
            "refresh_hints": {},
            "next_stage_hint": "storyboard_pending",
            "suggested_actions": _storyboard_plan_actions(_clean_text(plan_bundle.get("plan_id"))),
            "billing": billing_tracker.snapshot() if billing_tracker else None,
        }

    def _run_split_from_confirmed_plan(self, context: Dict[str, Any], payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        script_text = _clean_text(context.get("current_script"))
        script = context.get("script")
        episode = context.get("episode")
        payload = payload or {}
        if episode is None:
            raise ValueError("当前动作需要绑定到具体分集。")
        if not script_text:
            raise ValueError("当前分集还没有可拆解的剧本文本。")
        if not settings.DEEPSEEK_API_KEY:
            raise ValueError("当前分镜拆解服务暂时不可用，请稍后重试。")
        runtime_event_callback = context.get("runtime_event_callback")
        billing_tracker = _billing_tracker_from_context(context)
        confirmed_plan = payload.get("storyboard_plan_bundle") if isinstance(payload.get("storyboard_plan_bundle"), dict) else None
        if confirmed_plan is None:
            confirmed_plan = _plan_bundle_from_context(context)
        confirmed_plan_id = _clean_text(payload.get("confirmed_plan_id"))
        if not confirmed_plan or not isinstance(confirmed_plan.get("rows"), list):
            raise ValueError("还没有可确认的剧情片段规划，请先生成规划粗稿。")
        if confirmed_plan_id and _clean_text(confirmed_plan.get("plan_id")) and confirmed_plan_id != _clean_text(confirmed_plan.get("plan_id")):
            raise ValueError("当前确认的规划版本和会话里的最新规划不一致，请先刷新规划后再确认。")

        def split_progress_callback(rows: List[Dict[str, Any]]) -> None:
            if callable(runtime_event_callback):
                runtime_event_callback(
                    "storyboard_split_progress_delta",
                    {
                        "title": "正式分镜拆分进度",
                        "rows": rows,
                        "plan_id": confirmed_plan.get("plan_id"),
                    },
                )

        structured_draft = build_storyboard_split_structured_draft(
            episode_id=episode.id,
            text=script_text,
            api_key=settings.DEEPSEEK_API_KEY,
            storyboard_mode=resolve_storyboard_extraction_storyboard_mode(script) if script is not None else getattr(episode, "storyboard_mode", None),
            confirmed_plan_bundle=confirmed_plan,
            billing_tracker=billing_tracker,
            split_progress_callback=split_progress_callback,
        )
        story_segments = list(structured_draft.get("story_segments") or [])
        if not story_segments:
            raise ValueError("当前分镜拆解结果为空，暂时无法继续。")
        normalized_story_segments = [
            _normalize_storyboard_segment(item, index)
            for index, item in enumerate(story_segments, start=1)
            if isinstance(item, dict)
        ]
        workspace_write_error = None
        try:
            commit_story_segments_with_cells(
                self.session,
                episode=episode,
                story_segments=normalized_story_segments,
                replace_existing=True,
            )
            self.session.commit()
            if callable(runtime_event_callback):
                runtime_event_callback(
                    "storyboard_split_progress_delta",
                    {
                        "title": "正式分镜拆分进度",
                        "rows": [
                            {
                                "sequence_num": segment.get("sequence_num") or index,
                                "story_fragment": _clean_text(segment.get("summary") or segment.get("title")),
                                "grid_count": segment.get("grid_count") or len(segment.get("grid_cells") or []),
                                "status": "拆分完成",
                            }
                            for index, segment in enumerate(normalized_story_segments, start=1)
                        ],
                        "plan_id": confirmed_plan.get("plan_id"),
                    },
                )
                runtime_event_callback(
                    "storyboard_workspace_delta",
                    {
                        "refresh_hints": {
                            "panels": True,
                            "segment_workspace": True,
                            "open_storyboard": True,
                        }
                    },
                )
        except Exception as exc:
            workspace_write_error = str(exc)
            if callable(runtime_event_callback):
                runtime_event_callback("storyboard_workspace_error", {"message": str(exc)})
            raise ValueError(f"分镜草稿已生成，但写入分镜工作区失败：{exc}") from exc
        scene_names = sorted({
            _clean_text((segment.get("scene_refs") or [None])[0] or segment.get("scene_name") or segment.get("scene"))
            for segment in story_segments
            if _clean_text((segment.get("scene_refs") or [None])[0] or segment.get("scene_name") or segment.get("scene"))
        })
        character_names = sorted({
            name
            for segment in story_segments
            for name in _clean_list(segment.get("character_refs") or segment.get("characters") or segment.get("character"))
        })
        prop_names = sorted({
            name
            for segment in story_segments
            for name in _clean_list(segment.get("prop_refs") or segment.get("props") or segment.get("prop"))
        })
        message_parts = [
            f"已成功从剧本中拆解出结构化分镜，共整理 {len(story_segments)} 个分镜镜头。"
        ]
        if scene_names:
            message_parts.append(f"覆盖场景：{'、'.join(scene_names)}。")
        if character_names:
            message_parts.append(f"涉及角色：{'、'.join(character_names[:6])}。")
        if prop_names:
            message_parts.append(f"关键道具：{'、'.join(prop_names[:6])}。")
        if workspace_write_error:
            message_parts.append("期间出现过一次工作区写回异常，已经在最终整批写入时自动重试。")
        message_parts.append("正式分镜已经写入工作区，你现在可以打开分镜表继续调整，或者开始生成分镜图。")
        pending_sequences = _pending_storyboard_image_sequences_from_segments(normalized_story_segments)
        result_bundle = self._artifact_bundle(context, structured_draft=structured_draft)["storyboard_bundle"]
        return {
            "message": "".join(message_parts),
            "result": result_bundle,
            "artifacts": {"storyboard_bundle": result_bundle},
            "refresh_hints": {"panels": True, "segment_workspace": True, "open_storyboard": True},
            "next_stage_hint": "storyboard_ready",
            "suggested_actions": storyboard_ready_actions(pending_sequences),
            "billing": billing_tracker.snapshot() if billing_tracker else None,
        }

    def _run_extract_storyboard(self, context: Dict[str, Any], payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = payload or {}
        mode = _clean_text(payload.get("mode") or "plan_first")
        if mode == "split_confirmed":
            return self._run_split_from_confirmed_plan(context, payload)
        return self._run_plan_storyboard(context, payload)

    def _preview_response(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        latest_instruction = _clean_text(context.get("latest_user_message"))
        episode = context.get("episode")
        has_pending_plan = _plan_bundle_from_context(context) is not None
        if episode is None or not (_looks_like_storyboard_request(latest_instruction) or (has_pending_plan and latest_instruction)):
            return None
        mode = "split_confirmed" if has_pending_plan and any(token in latest_instruction for token in ["根据规划", "确认", "计划分镜", "正式分镜"]) else "plan_first"
        result = self._run_extract_storyboard(context, {"mode": mode})
        return self.build_response(
            stage=context["creative_stage"],
            stage_label=context["creative_stage_label"],
            message=result["message"],
            suggested_actions=result.get("suggested_actions") or storyboard_pending_actions(),
            artifacts=result.get("artifacts") or {"storyboard_plan_bundle": result["result"]},
            next_stage_hint=result.get("next_stage_hint") or "storyboard_ready",
        )

    def _fallback_response(self, context: Dict[str, Any]) -> Dict[str, Any]:
        stage = context["creative_stage"]
        stage_label = context["creative_stage_label"]
        facts = context.get("stage_read_model", {}).get("facts") or {}
        panel_count = int(facts.get("panel_count") or 0)
        pending_sequences = []
        if context.get("episode") is not None and panel_count > 0:
            try:
                from services.panel_service import list_panels as list_panels_service

                pending_sequences = [
                    int(getattr(item, "sequence_num", 0) or 0)
                    for item in list_panels_service(self.session, context["team"], context["episode"].id)
                    if int(getattr(item, "sequence_num", 0) or 0) > 0 and not _clean_text(getattr(item, "image_url", None))
                ]
            except Exception:
                pending_sequences = []
        message = (
            "我已经读过这集现有的分镜结果。现在可以继续补细分镜，或者直接进入分镜图生成。"
            if panel_count > 0
            else "剧本和资产已经具备，我现在可以继续为你整理分镜草稿，并把结果写回工作区。"
        )
        return self.build_response(
            stage=stage,
            stage_label=stage_label,
            message=message,
            suggested_actions=storyboard_ready_actions(pending_sequences) if panel_count > 0 else storyboard_pending_actions(),
            artifacts=self._artifact_bundle(context),
            next_stage_hint="storyboard_ready" if panel_count > 0 else "storyboard_pending",
        )

    def merge_llm_response(self, *, fallback_response: Dict[str, Any], llm_payload: Dict[str, Any]) -> Dict[str, Any]:
        merged = super().merge_llm_response(fallback_response=fallback_response, llm_payload=llm_payload)
        merged["artifacts"] = fallback_response.get("artifacts") or {}
        return merged

    def run(self, context: Dict[str, Any]) -> Dict[str, Any]:
        preview = self._preview_response(context)
        if preview:
            return preview
        fallback = self._fallback_response(context)
        return self.try_llm_response(
            context=context,
            task_goal="请产出可写入分镜系统的结构化分镜摘要，并给出下一步动作。",
            latest_instruction=_clean_text(context.get("latest_user_message")),
            action_space=fallback["suggested_actions"],
            fallback_response=fallback,
        )

    def _resolve_storyboard_draft(
        self,
        context: Dict[str, Any],
        payload: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        source_candidates: List[Any] = []
        payload = payload or {}
        if isinstance(payload.get("structured_storyboard"), dict):
            source_candidates.append(payload.get("structured_storyboard"))
        if isinstance(payload.get("storyboard_bundle"), dict):
            source_candidates.append(payload.get("storyboard_bundle"))
        if isinstance(payload.get("segment_draft"), list):
            source_candidates.append({"segment_draft": payload.get("segment_draft")})
        latest_artifacts = context.get("latest_artifacts") if isinstance(context.get("latest_artifacts"), dict) else {}
        if isinstance(latest_artifacts.get("storyboard_bundle"), dict):
            source_candidates.append(latest_artifacts.get("storyboard_bundle"))

        for candidate in source_candidates:
            if not isinstance(candidate, dict):
                continue
            raw_segments = candidate.get("story_segments") or candidate.get("segment_draft")
            if isinstance(raw_segments, list) and raw_segments:
                normalized = [
                    _normalize_storyboard_segment(item, index)
                    for index, item in enumerate(raw_segments, start=1)
                    if isinstance(item, dict)
                ]
                if normalized:
                    return normalized
            raw_rows = candidate.get("storyboard_rows")
            if isinstance(raw_rows, list) and raw_rows:
                normalized_rows = [
                    _normalize_storyboard_segment(item, index)
                    for index, item in enumerate(raw_rows, start=1)
                    if isinstance(item, dict)
                ]
                if normalized_rows:
                    return normalized_rows
        return []

    def execute_action(self, context: Dict[str, Any], action: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        episode = context.get("episode")
        script = context.get("script")
        script_text = _clean_text(context.get("current_script"))
        if episode is None:
            raise ValueError("当前动作需要绑定到具体分集。")
        if action == "extract_storyboard":
            return self._run_extract_storyboard(context, payload)
        if action != "save_storyboard":
            raise ValueError(f"分镜导演暂不支持这个动作：{action}")

        story_segments = self._resolve_storyboard_draft(context, payload)
        structured_draft: Optional[Dict[str, Any]] = None

        if not story_segments:
            if not script_text:
                raise ValueError("当前分集还没有可拆解的剧本文本。")
            if not settings.DEEPSEEK_API_KEY:
                raise ValueError("当前分镜拆解服务暂时不可用，请稍后重试。")
            structured_draft = build_storyboard_split_structured_draft(
                episode_id=episode.id,
                text=script_text,
                api_key=settings.DEEPSEEK_API_KEY,
                storyboard_mode=resolve_storyboard_extraction_storyboard_mode(script) if script is not None else getattr(episode, "storyboard_mode", None),
            )
            story_segments = [
                _normalize_storyboard_segment(item, index)
                for index, item in enumerate(structured_draft.get("story_segments") or [], start=1)
                if isinstance(item, dict)
            ]

        if not story_segments:
            raise ValueError("当前分镜拆解结果为空，暂时无法写入分镜表。")

        created_panels = commit_story_segments_with_cells(
            self.session,
            episode=episode,
            story_segments=story_segments,
            replace_existing=True,
        )
        self.session.commit()
        result_bundle = self._artifact_bundle(
            context,
            structured_draft=structured_draft or {"story_segments": story_segments},
        )["storyboard_bundle"]
        return {
            "message": f"分镜板已拆解完成，共生成 {len(created_panels)} 个分镜片段，接下来可以继续生成分镜图。",
            "result": result_bundle,
            "refresh_hints": {"panels": True, "segment_workspace": True, "open_storyboard": True},
            "next_stage_hint": "storyboard_ready",
            "suggested_actions": [
                {"type": "open_storyboard", "label": "打开分镜表"},
                {"type": "rewrite_script", "label": "按我的需求继续调整分镜"},
                {"type": "generate_storyboard_images", "label": "开始生成分镜图"},
            ],
        }
