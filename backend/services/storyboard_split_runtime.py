from __future__ import annotations

import concurrent.futures
import json
import math
import re
import threading
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlmodel import Session

from core.config import settings
from core.security import encode_id
from database import engine
from models import Episode, Panel, Script, Team, User
from services.billing_service import deduct_inspiration_points
from services.deepseek_hybrid_router import resolve_deepseek_agent_route
from services.deepseek_model_policy import calculate_deepseek_v4_flash_usage_cost_cny, normalize_deepseek_model
from services.resource_extraction_service import load_structured_assets_from_shared_resources
from services.story_segment_service import commit_story_segments_with_cells
from services.storyboard_director_service import (
    _apply_story_segment_consistency,
    StorySegmentParseError,
    _build_segment_continuity_state,
    _continuity_state_summary,
    _response_usage_to_dict,
    _select_language_beats_for_segment,
    call_story_grid_batch_expander,
    call_story_grid_expander,
    call_story_language_beat_extractor,
    call_story_segment_planner,
    clamp_segment_total_duration,
    constrain_segment_grid_count,
    estimate_deepseek_tokens,
    estimate_language_beat_min_duration_seconds,
    expand_language_beats_for_timing,
    normalize_story_segment_payload_v2,
    normalize_structured_asset_items,
    normalize_storyboard_mode,
    repair_story_segments_semantically,
)
from services.task_job_service import (
    TASK_STATUS_CANCELLED,
    get_task_job,
    is_task_cancel_requested,
    mark_task_job_succeeded,
    update_task_job,
)
from services.workflow_preset_service import resolve_effective_workflow_profile

POINTS_UNIT_CNY = Decimal("0.1")
POINTS_STATUS_FREE = "free"
POINTS_STATUS_DEDUCTED = "deducted"
DEFAULT_STORYBOARD_CHUNK_TOKENS = 12000


def storyboard_split_billing_rule() -> str:
    return "if actual_cost_cny > 0 then ceil(actual_cost_cny / 0.1) + 1 else 0"


def _round_cost(cost: Decimal) -> Decimal:
    return cost.quantize(Decimal("0.000001"))


def _compute_points_from_cost(cost_cny: Decimal) -> int:
    if cost_cny <= 0:
        return 0
    return int((cost_cny / POINTS_UNIT_CNY).to_integral_value(rounding=ROUND_CEILING)) + 1


def _calculate_usage_cost_cny(model: str, usage: Dict[str, int]) -> Decimal:
    return _round_cost(calculate_deepseek_v4_flash_usage_cost_cny(usage))


def _resolve_planner_route(source_text: str, asset_count: int, *, deep_thinking: bool = False) -> Tuple[str, bool, str]:
    if deep_thinking:
        model, thinking_enabled = normalize_deepseek_model(settings.DEEPSEEK_AGENT_REASONER_MODEL, thinking_enabled=True)
        return model, thinking_enabled, "manual_flash_thinking"
    route = resolve_deepseek_agent_route(
        {
            "task_kind": "storyboard_planning",
            "estimated_text_tokens": estimate_deepseek_tokens(source_text),
            "segment_count": 0,
            "character_count": int(asset_count or 0),
            "expected_tool_calls": 2,
            "user_intent_flags": ["storyboard"],
            "previous_failures": 0,
            "json_mode_enabled": True,
            "strict_tools_enabled": False,
        }
    )
    model, thinking_enabled = normalize_deepseek_model(route["model"], thinking_enabled=bool(route["thinking_enabled"]))
    return model, thinking_enabled, str(route["route_tag"])


def _ceil_seconds(value: Any, minimum: int = 0) -> int:
    try:
        return max(int(math.ceil(float(value or 0.0))), minimum)
    except Exception:
        return minimum


def _segment_min_duration_from_beats(beats: List[Dict[str, Any]]) -> int:
    return _ceil_seconds(sum(float(estimate_language_beat_min_duration_seconds(item) or 0.0) for item in beats), 0)


def _speech_type_targets_from_beats(beats: List[Dict[str, Any]]) -> List[str]:
    targets: List[str] = []
    for beat in beats:
        event_type = str(beat.get("event_type") or "").strip().lower()
        mapped = ""
        if event_type == "spoken_dialogue":
            mapped = "spoken"
        elif event_type in {"inner_monologue", "narration", "offscreen_voice"}:
            mapped = event_type
        if mapped and mapped not in targets:
            targets.append(mapped)
    return targets


def _preferred_segment_duration_seconds(beats: List[Dict[str, Any]], requested_duration: Any) -> int:
    base_duration = max(int(requested_duration or 6), _segment_min_duration_from_beats(beats), 4)
    if not beats:
        return base_duration

    speech_targets = _speech_type_targets_from_beats(beats)
    speech_count = sum(
        1
        for beat in beats
        if str(beat.get("event_type") or "").strip().lower()
        in {"spoken_dialogue", "inner_monologue", "narration", "offscreen_voice"}
    )
    complexity_score = sum(
        1
        for beat in beats
        if str(beat.get("split_recommendation") or "").strip().lower() in {"prefer_new_cell", "prefer_new_segment"}
    )
    complexity_score += sum(
        1 for beat in beats if str(beat.get("visual_priority") or "").strip().lower() == "high"
    )

    if base_duration < 6 and (speech_count >= 2 or len(speech_targets) >= 2):
        base_duration = 6
    if base_duration < 8 and (speech_count >= 4 or complexity_score >= 5 or len(beats) >= 5):
        base_duration = 8
    if base_duration == 5:
        base_duration = 6
    return min(max(base_duration, 4), 15)


def _desired_grid_count_from_beats(beats: List[Dict[str, Any]], fallback: Any, duration_seconds: int) -> int:
    if not beats:
        return constrain_segment_grid_count(duration_seconds, fallback)
    desired = 0
    speech_events = 0
    for beat in beats:
        split_recommendation = str(beat.get("split_recommendation") or "").strip().lower()
        event_type = str(beat.get("event_type") or "").strip().lower()
        visual_priority = str(beat.get("visual_priority") or "").strip().lower()
        if split_recommendation in {"prefer_new_cell", "prefer_new_segment"}:
            desired += 1
        elif event_type in {"spoken_dialogue", "inner_monologue", "narration", "offscreen_voice"}:
            desired += 1
            speech_events += 1
        elif visual_priority == "high":
            desired += 1
    speech_targets = _speech_type_targets_from_beats(beats)
    desired = max(desired, 1)
    requested = max(int(fallback or 1), desired)
    if duration_seconds >= 14 and (desired >= 8 or speech_events >= 6):
        requested = max(requested, 9)
    elif duration_seconds >= 9 and (desired >= 4 or speech_events >= 3 or len(speech_targets) >= 2):
        requested = max(requested, 6)
    elif duration_seconds >= 6 and (desired >= 3 or speech_events >= 2 or len(speech_targets) >= 1):
        requested = max(requested, 4)
    elif desired >= 2:
        requested = max(requested, 2)

    requested = constrain_segment_grid_count(duration_seconds, requested)
    if requested == 9 and not (duration_seconds >= 14 and (desired >= 8 or speech_events >= 6)):
        requested = constrain_segment_grid_count(duration_seconds, 6)
    if requested == 1 and duration_seconds >= 6 and (desired >= 3 or speech_events >= 2 or len(speech_targets) >= 1):
        requested = constrain_segment_grid_count(duration_seconds, 4)
    return requested


def _join_chunk_excerpt(chunk: List[Dict[str, Any]], fallback: str) -> str:
    rows = []
    seen: set[str] = set()
    for beat in chunk:
        excerpt = str(beat.get("source_excerpt") or beat.get("text") or "").strip()
        if excerpt and excerpt not in seen:
            seen.add(excerpt)
            rows.append(excerpt)
    return " ".join(rows).strip() or fallback


def _looks_like_scene_heading(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if re.match(r"^\d+\s*[-—:：]", value):
        return True
    if any(token in value for token in ["内景", "外景", "日", "夜", "崖顶", "悬崖", "场景", "【画面】"]):
        return True
    return False


def _split_large_storyboard_block(block_text: str, *, max_tokens: int) -> List[str]:
    text = str(block_text or "").strip()
    if not text:
        return []
    if estimate_deepseek_tokens(text) <= max_tokens:
        return [text]
    parts = re.split(r"(?<=[。！？!?；;])", text)
    chunks: List[str] = []
    current: List[str] = []
    current_tokens = 0
    for part in parts:
        piece = str(part or "").strip()
        if not piece:
            continue
        piece_tokens = estimate_deepseek_tokens(piece)
        if current and current_tokens + piece_tokens > max_tokens:
            chunks.append("".join(current).strip())
            current = []
            current_tokens = 0
        current.append(piece)
        current_tokens += piece_tokens
    if current:
        chunks.append("".join(current).strip())
    return [item for item in chunks if item]


def _split_text_into_storyboard_chunks(source_text: str, *, max_chunk_tokens: int = DEFAULT_STORYBOARD_CHUNK_TOKENS) -> List[str]:
    text = str(source_text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    raw_blocks = [item.strip() for item in re.split(r"\n\s*\n+", text) if item.strip()]
    blocks: List[str] = []
    for block in raw_blocks:
        blocks.extend(_split_large_storyboard_block(block, max_tokens=max_chunk_tokens))

    chunks: List[str] = []
    current_blocks: List[str] = []
    current_tokens = 0
    for block in blocks:
        block_tokens = estimate_deepseek_tokens(block)
        start_new = bool(
            current_blocks
            and (
                current_tokens + block_tokens > max_chunk_tokens
                or (_looks_like_scene_heading(block) and current_tokens >= int(max_chunk_tokens * 0.55))
            )
        )
        if start_new:
            chunks.append("\n\n".join(current_blocks).strip())
            current_blocks = []
            current_tokens = 0
        current_blocks.append(block)
        current_tokens += block_tokens
    if current_blocks:
        chunks.append("\n\n".join(current_blocks).strip())
    return [item for item in chunks if item]


def _retime_segment_plans_with_language_beats(
    segment_plans: List[Dict[str, Any]],
    language_beats: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    adjusted: List[Dict[str, Any]] = []
    for segment_plan in segment_plans:
        selected_beats = _select_language_beats_for_segment(segment_plan, language_beats)
        if not selected_beats:
            requested_duration = int(segment_plan.get("recommended_duration_seconds") or 6)
            segment_plan["recommended_duration_seconds"] = requested_duration
            segment_plan["grid_count"] = constrain_segment_grid_count(requested_duration, segment_plan.get("grid_count"))
            adjusted.append(segment_plan)
            continue

        chunks: List[List[Dict[str, Any]]] = []
        current_chunk: List[Dict[str, Any]] = []
        current_seconds = 0.0
        for beat in selected_beats:
            beat_seconds = max(float(estimate_language_beat_min_duration_seconds(beat) or 0.0), 0.8)
            split_recommendation = str(beat.get("split_recommendation") or "").strip().lower()
            should_break = bool(
                current_chunk
                and (
                    current_seconds + beat_seconds > 15.0
                    or split_recommendation == "prefer_new_segment"
                )
            )
            if should_break:
                chunks.append(current_chunk)
                current_chunk = []
                current_seconds = 0.0
            current_chunk.append(beat)
            current_seconds += beat_seconds
        if current_chunk:
            chunks.append(current_chunk)

        base_title = str(segment_plan.get("title") or "").strip()
        base_summary = str(segment_plan.get("summary") or "").strip()
        source_excerpt = str((segment_plan.get("text_span") or {}).get("source_excerpt") or base_summary).strip()
        for chunk_index, chunk in enumerate(chunks, start=1):
            requested_duration = _preferred_segment_duration_seconds(
                chunk,
                segment_plan.get("recommended_duration_seconds") or 6,
            )
            chunk_excerpt = _join_chunk_excerpt(chunk, source_excerpt)
            speech_targets = _speech_type_targets_from_beats(chunk)
            adjusted_plan = {
                **segment_plan,
                "title": (
                    f"{base_title}（{chunk_index}/{len(chunks)}）"
                    if len(chunks) > 1 and base_title
                    else base_title
                ),
                "summary": base_summary or chunk_excerpt,
                "text_span": {
                    **(segment_plan.get("text_span") or {}),
                    "source_excerpt": chunk_excerpt,
                },
                "recommended_duration_seconds": requested_duration,
                "beat_ids": [str(item.get("beat_id") or "").strip() for item in chunk if str(item.get("beat_id") or "").strip()],
                "grid_count": _desired_grid_count_from_beats(chunk, segment_plan.get("grid_count"), requested_duration),
                "language_focus_summary": str(segment_plan.get("language_focus_summary") or chunk_excerpt).strip(),
                "speech_coverage_targets": speech_targets,
            }
            adjusted.append(adjusted_plan)

    for index, item in enumerate(adjusted, start=1):
        item["sequence_num"] = index
    return adjusted


def validate_story_segments_semantics(story_segments: List[Dict[str, Any]]) -> List[str]:
    errors: List[str] = []
    if not story_segments:
        return ["story_segments is empty"]

    normalized = sorted(
        [item for item in story_segments if isinstance(item, dict)],
        key=lambda item: int(item.get("sequence_num") or 0),
    )
    seen_sequences: set[int] = set()
    for expected_sequence, segment in enumerate(normalized, start=1):
        sequence_num = int(segment.get("sequence_num") or 0)
        if sequence_num in seen_sequences:
            errors.append(f"duplicate sequence_num: {sequence_num}")
        seen_sequences.add(sequence_num)
        if sequence_num != expected_sequence:
            errors.append(f"sequence_num should be contiguous starting from 1, found {sequence_num} at position {expected_sequence}")

        text_span = segment.get("text_span") or {}
        source_excerpt = str(text_span.get("source_excerpt") or segment.get("summary") or "").strip()
        if not source_excerpt:
            errors.append(f"segment {sequence_num} missing text_span.source_excerpt")

        prompt_summary = str(segment.get("segment_prompt_summary") or "").strip()
        if not prompt_summary:
            errors.append(f"segment {sequence_num} missing segment_prompt_summary")

        grid_count = int(segment.get("grid_count") or 0)
        cells = [cell for cell in (segment.get("grid_cells") or []) if isinstance(cell, dict)]
        if len(cells) != grid_count:
            errors.append(f"segment {sequence_num} grid_cells count {len(cells)} does not match grid_count {grid_count}")

        recommended_duration = float(segment.get("recommended_duration_seconds") or 0)
        total_duration = round(sum(float(cell.get("duration_seconds") or 0) for cell in cells), 3)
        if cells and round(recommended_duration, 3) != total_duration:
            errors.append(
                f"segment {sequence_num} total grid duration {total_duration} does not match recommended_duration_seconds {recommended_duration}"
            )
        if grid_count == 1 and recommended_duration >= 8:
            errors.append(
                f"segment {sequence_num} uses a long single-grid duration {recommended_duration}; prefer 4 or 6 cells for medium/long segments"
            )
        if grid_count == 9 and recommended_duration < 14:
            errors.append(
                f"segment {sequence_num} uses grid_count 9 too early; prefer 4 or 6 cells before nine-grid"
            )

        for ref_key in ("character_refs", "scene_refs", "prop_refs"):
            refs = segment.get(ref_key) or []
            cleaned = [str(item or "").strip() for item in refs if str(item or "").strip()]
            if len(cleaned) != len(refs):
                errors.append(f"segment {sequence_num} has blank items in {ref_key}")
            if len(set(cleaned)) != len(cleaned):
                errors.append(f"segment {sequence_num} has duplicate items in {ref_key}")

        speech_targets = {
            str(item or "").strip()
            for item in (segment.get("speech_coverage_targets") or [])
            if str(item or "").strip()
        }
        covered_speech_types = {
            str(speech_item.get("speech_type") or "").strip()
            for cell in cells
            for speech_item in (cell.get("speech_items") or [])
            if isinstance(speech_item, dict) and str(speech_item.get("speech_type") or "").strip()
        }
        missing_targets = sorted(speech_targets - covered_speech_types)
        if missing_targets:
            errors.append(
                f"segment {sequence_num} is missing speech coverage for {', '.join(missing_targets)}"
            )

        previous_end = 0.0
        for cell_index, cell in enumerate(sorted(cells, key=lambda item: int(item.get("cell_index") or 0)), start=1):
            if int(cell.get("cell_index") or 0) != cell_index:
                errors.append(f"segment {sequence_num} has non-contiguous cell_index at position {cell_index}")
            start_second = float(cell.get("start_second") or 0)
            end_second = float(cell.get("end_second") or 0)
            duration_seconds = float(cell.get("duration_seconds") or 0)
            if end_second < start_second:
                errors.append(f"segment {sequence_num} cell {cell_index} has end_second < start_second")
            if round(end_second - start_second, 3) != round(duration_seconds, 3):
                errors.append(
                    f"segment {sequence_num} cell {cell_index} duration mismatch: end-start={round(end_second - start_second, 3)} vs duration_seconds={duration_seconds}"
                )
            if start_second < previous_end:
                errors.append(f"segment {sequence_num} cell {cell_index} overlaps previous cell")
            previous_end = end_second
            for field_name in ("shot_description", "action_description"):
                if not str(cell.get(field_name) or "").strip():
                    errors.append(f"segment {sequence_num} cell {cell_index} missing {field_name}")
    return errors


def _blocking_story_segment_validation_errors(errors: List[str]) -> List[str]:
    blocking_markers = (
        "story_segments is empty",
        "duplicate sequence_num",
        "sequence_num should be contiguous",
        "missing text_span.source_excerpt",
        "missing segment_prompt_summary",
        "grid_cells count",
        "total grid duration",
        "has blank items",
        "has duplicate items",
        "non-contiguous cell_index",
        "end_second < start_second",
        "duration mismatch",
        "overlaps previous cell",
        "missing shot_description",
        "missing action_description",
    )
    return [
        str(item or "").strip()
        for item in errors or []
        if str(item or "").strip() and any(marker in str(item) for marker in blocking_markers)
    ]


def _local_clean_string_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        value = [value] if value is not None else []
    cleaned: List[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        cleaned.append(text)
    return cleaned


def _local_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _retime_local_grid_cells(cells: List[Dict[str, Any]], total_duration: float) -> None:
    if not cells:
        return
    total = max(float(total_duration or 0), float(len(cells)), 4.0)
    previous_end = 0.0
    rounded_total = int(round(total))
    if abs(total - rounded_total) < 0.001 and rounded_total >= len(cells):
        base = max(rounded_total // len(cells), 1)
        remainder = max(rounded_total - (base * len(cells)), 0)
        for index, cell in enumerate(cells, start=1):
            duration_seconds = base + (1 if index <= remainder else 0)
            start_second = previous_end
            end_second = start_second + duration_seconds
            cell["cell_index"] = index
            cell["start_second"] = int(start_second)
            cell["end_second"] = int(end_second)
            cell["duration_seconds"] = int(duration_seconds)
            previous_end = end_second
        return
    for index, cell in enumerate(cells, start=1):
        start_second = previous_end
        end_second = total if index == len(cells) else round(total * index / len(cells), 3)
        duration_seconds = round(end_second - start_second, 3)
        cell["cell_index"] = index
        cell["start_second"] = round(start_second, 3)
        cell["end_second"] = round(end_second, 3)
        cell["duration_seconds"] = duration_seconds
        previous_end = end_second


def _lock_story_segments_to_confirmed_durations(
    story_segments: List[Dict[str, Any]],
    locked_durations_by_sequence: Dict[int, int],
) -> None:
    if not locked_durations_by_sequence:
        return
    for index, segment in enumerate(story_segments, start=1):
        if not isinstance(segment, dict):
            continue
        try:
            sequence_num = int(segment.get("sequence_num") or index)
        except Exception:
            sequence_num = index
        if sequence_num not in locked_durations_by_sequence:
            continue
        cells = [cell for cell in (segment.get("grid_cells") or []) if isinstance(cell, dict)]
        locked_duration = clamp_segment_total_duration(
            locked_durations_by_sequence[sequence_num],
            len(cells) or segment.get("grid_count") or 1,
        )
        segment["recommended_duration_seconds"] = int(locked_duration)
        if cells:
            _retime_local_grid_cells(cells, locked_duration)
            segment["grid_cells"] = cells


def _clone_local_grid_cell(source: Dict[str, Any], *, fallback_text: str) -> Dict[str, Any]:
    cloned = dict(source or {})
    cloned.setdefault("shot_description", fallback_text)
    cloned.setdefault("action_description", cloned.get("shot_description") or fallback_text)
    cloned.setdefault("dialogue_excerpt", fallback_text)
    cloned.setdefault("speech_items", [])
    return cloned


def _fit_local_grid_cells(
    cells: List[Dict[str, Any]],
    *,
    target_count: int,
    fallback_text: str,
) -> List[Dict[str, Any]]:
    target = max(int(target_count or 1), 1)
    normalized_cells = [dict(cell) for cell in cells if isinstance(cell, dict)]
    if not normalized_cells:
        normalized_cells = [
            {
                "shot_description": fallback_text,
                "action_description": fallback_text,
                "dialogue_excerpt": fallback_text,
                "speech_items": [],
            }
        ]

    if len(normalized_cells) == target:
        return normalized_cells

    if len(normalized_cells) > target:
        kept = normalized_cells[:target]
        overflow = normalized_cells[target:]
        if overflow:
            last = kept[-1]
            for key in ("shot_description", "action_description", "dialogue_excerpt"):
                merged = [
                    str(last.get(key) or "").strip(),
                    *[str(cell.get(key) or "").strip() for cell in overflow],
                ]
                last[key] = " ".join(item for item in merged if item).strip() or fallback_text
            speech_items = []
            for cell in [last, *overflow]:
                speech_items.extend([item for item in (cell.get("speech_items") or []) if isinstance(item, dict)])
            last["speech_items"] = speech_items
        return kept

    expanded: List[Dict[str, Any]] = []
    source_count = len(normalized_cells)
    for index in range(target):
        source_index = min(int(index * source_count / target), source_count - 1)
        expanded.append(_clone_local_grid_cell(normalized_cells[source_index], fallback_text=fallback_text))
    return expanded


def _ensure_local_speech_coverage(segment: Dict[str, Any], cells: List[Dict[str, Any]], source_excerpt: str) -> None:
    targets = _local_clean_string_list(segment.get("speech_coverage_targets"))
    if not targets or not cells:
        segment["speech_coverage_targets"] = targets
        return

    covered = {
        str(item.get("speech_type") or "").strip()
        for cell in cells
        for item in (cell.get("speech_items") or [])
        if isinstance(item, dict) and str(item.get("speech_type") or "").strip()
    }
    speaker_name = (segment.get("character_refs") or [""])[0] if isinstance(segment.get("character_refs"), list) else ""
    for index, speech_type in enumerate(targets):
        if speech_type in covered:
            continue
        cell = cells[index % len(cells)]
        speech_items = [item for item in (cell.get("speech_items") or []) if isinstance(item, dict)]
        speech_items.append(
            {
                "speaker_name": str(speaker_name or "").strip(),
                "speech_type": speech_type,
                "text": str(cell.get("dialogue_excerpt") or source_excerpt or cell.get("shot_description") or "").strip(),
                "mouth_sync_required": speech_type == "spoken",
            }
        )
        cell["speech_items"] = speech_items
    segment["speech_coverage_targets"] = targets


def _repair_story_segments_locally(
    story_segments: List[Dict[str, Any]],
    validation_errors: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Repair deterministic shape/timing errors after model critic repair fails."""

    repaired: List[Dict[str, Any]] = []
    source_errors = [str(item or "").strip() for item in (validation_errors or []) if str(item or "").strip()]
    if warnings is not None and source_errors:
        warnings.append("storyboard local semantic repair applied: " + "; ".join(source_errors[:5]))

    for sequence_num, raw_segment in enumerate([item for item in story_segments if isinstance(item, dict)], start=1):
        segment = dict(raw_segment)
        segment["sequence_num"] = sequence_num

        summary = str(segment.get("summary") or segment.get("title") or f"Segment {sequence_num}").strip()
        text_span = segment.get("text_span") if isinstance(segment.get("text_span"), dict) else {}
        source_excerpt = str(text_span.get("source_excerpt") or summary).strip() or summary
        segment["summary"] = summary
        segment["text_span"] = {
            **text_span,
            "source_excerpt": source_excerpt,
        }
        segment["segment_prompt_summary"] = str(segment.get("segment_prompt_summary") or summary or source_excerpt).strip()

        for ref_key in ("character_refs", "scene_refs", "prop_refs"):
            segment[ref_key] = _local_clean_string_list(segment.get(ref_key))

        raw_cells = [dict(cell) for cell in (segment.get("grid_cells") or []) if isinstance(cell, dict)]
        requested_duration = max(
            int(round(_local_float(segment.get("recommended_duration_seconds"), 0.0))),
            len(raw_cells) or 1,
            4,
        )
        requested_grid_count = constrain_segment_grid_count(
            requested_duration,
            segment.get("grid_count") or len(raw_cells) or 1,
        )
        if requested_grid_count == 1 and requested_duration >= 8:
            requested_grid_count = constrain_segment_grid_count(requested_duration, 4)
        if requested_grid_count == 9 and requested_duration < 14:
            requested_grid_count = constrain_segment_grid_count(requested_duration, 6)

        cells = _fit_local_grid_cells(
            raw_cells,
            target_count=requested_grid_count,
            fallback_text=source_excerpt or summary,
        )
        for cell in cells:
            shot_description = str(cell.get("shot_description") or cell.get("visual_content") or source_excerpt or summary).strip()
            action_description = str(cell.get("action_description") or cell.get("action") or shot_description or source_excerpt).strip()
            cell["shot_description"] = shot_description or summary
            cell["action_description"] = action_description or cell["shot_description"]
            cell["dialogue_excerpt"] = str(cell.get("dialogue_excerpt") or cell.get("dialogue_text") or source_excerpt).strip()
            for ref_key in ("character_refs", "scene_refs", "prop_refs"):
                if ref_key in cell:
                    cell[ref_key] = _local_clean_string_list(cell.get(ref_key))
        _ensure_local_speech_coverage(segment, cells, source_excerpt)
        _retime_local_grid_cells(cells, requested_duration)

        segment["grid_count"] = len(cells)
        segment["recommended_duration_seconds"] = round(sum(float(cell.get("duration_seconds") or 0.0) for cell in cells), 3)
        segment["grid_cells"] = cells
        repaired.append(segment)

    return repaired


@dataclass
class StoryboardSplitBillingTracker:
    user_id: Optional[int]
    team_id: Optional[int]
    task_id: Optional[str]
    charge_enabled: bool = True
    actual_cost_cny: Decimal = field(default_factory=lambda: Decimal("0"))
    charged_points: int = 0
    actual_points: int = 0
    points_status: str = POINTS_STATUS_FREE
    billing_detail: List[Dict[str, Any]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "charged_points": int(self.charged_points),
            "actual_points": int(self.actual_points),
            "actual_cost_cny": float(_round_cost(self.actual_cost_cny)),
            "points_status": self.points_status,
            "billing_rule": storyboard_split_billing_rule(),
            "billing_detail": list(self.billing_detail),
        }

    def _sync_task_job(self) -> None:
        if not self.task_id:
            return
        update_task_job(
            self.task_id,
            actual_cost_cny=float(_round_cost(self.actual_cost_cny)),
            charged_points=int(self.charged_points),
            actual_points=int(self.actual_points),
            points_status=self.points_status,
            billing_detail=self.billing_detail,
        )

    def record_usage(self, phase: str, model: str, response: Any) -> None:
        usage = _response_usage_to_dict(response)
        cost_cny = _calculate_usage_cost_cny(model, usage)
        with self._lock:
            if cost_cny <= 0 and not any(int(usage.get(key) or 0) for key in usage):
                self._sync_task_job()
                return

            self.actual_cost_cny = _round_cost(self.actual_cost_cny + cost_cny)
            target_points = _compute_points_from_cost(self.actual_cost_cny)
            delta = target_points - self.charged_points if self.charge_enabled else 0

            if delta > 0:
                with Session(engine) as session:
                    user = session.get(User, self.user_id) if self.user_id else None
                    team = session.get(Team, self.team_id) if self.team_id else None
                    if not user or not team:
                        raise StorySegmentParseError("billing_context_missing", "分镜拆分计费上下文缺失")
                    try:
                        deduct_inspiration_points(
                            user=user,
                            team=team,
                            cost=delta,
                            action_type="storyboard_split" if self.charged_points == 0 else "storyboard_split_delta",
                            description=f"剧情分镜拆分 {phase}",
                            session=session,
                        )
                        session.commit()
                    except HTTPException as exc:
                        raise StorySegmentParseError(
                            "billing_insufficient",
                            f"分镜拆分灵感值不足：{exc.detail}",
                            detail=str(exc.detail),
                        ) from exc
                self.charged_points = target_points

            self.actual_points = target_points
            self.points_status = POINTS_STATUS_DEDUCTED if self.charged_points > 0 else POINTS_STATUS_FREE
            self.billing_detail.append(
                {
                    "phase": phase,
                    "model": model,
                    "prompt_cache_hit_tokens": int(usage.get("prompt_cache_hit_tokens") or 0),
                    "prompt_cache_miss_tokens": int(usage.get("prompt_cache_miss_tokens") or 0),
                    "completion_tokens": int(usage.get("completion_tokens") or 0),
                    "thinking_enabled": bool(usage.get("thinking_enabled")),
                    "cost_cny": float(cost_cny),
                    "charged_points_after_call": int(self.charged_points),
                }
            )
            self._sync_task_job()


def _ensure_not_cancelled(task_id: Optional[str]) -> None:
    if task_id and is_task_cancel_requested(task_id):
        raise StorySegmentParseError("task_cancelled", "剧情片段拆分已取消")


def _update_task_progress(task_id: Optional[str], *, stage: str, progress: int, message: str, current_segment: int = 0, segment_count: Optional[int] = None) -> None:
    if not task_id:
        return
    update_task_job(
        task_id,
        status="running",
        stage=stage,
        progress=int(progress),
        message=message,
        result={
            "current_segment": int(current_segment),
            "segment_count": segment_count,
        },
    )


def _extract_plan_rows(plan_bundle: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(plan_bundle, dict):
        return []
    rows = plan_bundle.get("rows")
    if not isinstance(rows, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        story_fragment = str(row.get("story_fragment") or row.get("summary") or row.get("description") or row.get("title") or "").strip()
        if not story_fragment:
            continue
        normalized.append(
            {
                "sequence_num": int(row.get("sequence_num") or index),
                "story_fragment": story_fragment,
                "dialogue": str(row.get("dialogue") or "").strip(),
                "estimated_duration_seconds": row.get("estimated_duration_seconds")
                or row.get("duration_seconds")
                or row.get("recommended_duration_seconds")
                or 6,
                "source_excerpt": str(row.get("source_excerpt") or row.get("text") or story_fragment).strip(),
                "grid_count": row.get("grid_count") or row.get("estimated_grid_count") or 0,
            }
        )
    return normalized


def _coerce_duration_seconds(value: Any) -> int:
    if value is None or isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(int(math.ceil(float(value))), 0)
    text = str(value or "").strip()
    if not text:
        return 0
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return 0
    try:
        return max(int(math.ceil(float(match.group(0)))), 0)
    except Exception:
        return 0


def _total_plan_duration_seconds(rows: List[Dict[str, Any]]) -> int:
    return sum(_coerce_duration_seconds(row.get("estimated_duration_seconds")) for row in rows if isinstance(row, dict))


def _dialogue_from_beats(beats: List[Dict[str, Any]], fallback: str = "") -> str:
    speech_parts: List[str] = []
    for beat in beats or []:
        if not isinstance(beat, dict):
            continue
        event_type = str(beat.get("event_type") or "").strip().lower()
        if event_type not in {"spoken_dialogue", "inner_monologue", "narration", "offscreen_voice"}:
            continue
        text = str(beat.get("source_excerpt") or beat.get("text") or "").strip()
        if text and text not in speech_parts:
            speech_parts.append(text)
    return " / ".join(speech_parts[:4]) or fallback


_SPEECH_BEAT_TYPES = {"spoken_dialogue", "inner_monologue", "narration", "offscreen_voice"}


def _beat_event_type(beat: Dict[str, Any]) -> str:
    return str((beat or {}).get("event_type") or "").strip().lower()


def _row_dialogue_text(row: Dict[str, Any]) -> str:
    return str((row or {}).get("dialogue") or "").strip()


def _confirmed_row_internal_excerpt(row: Dict[str, Any], rows: List[Dict[str, Any]], index: int) -> str:
    story_fragment = str(row.get("story_fragment") or "").strip()
    dialogue = _row_dialogue_text(row)
    source_excerpt = str(row.get("source_excerpt") or row.get("text") or "").strip()
    base_excerpt = source_excerpt or dialogue or story_fragment
    previous_fragment = str((rows[index - 2] if index > 1 else {}).get("story_fragment") or "").strip()
    next_fragment = str((rows[index] if index < len(rows) else {}).get("story_fragment") or "").strip()
    same_scene_neighbor = story_fragment and (story_fragment == previous_fragment or story_fragment == next_fragment)
    if same_scene_neighbor and not dialogue:
        return (
            f"{base_excerpt}\n"
            "无对白动作/情绪延展段：承接相邻剧情片段，但不要重复相邻片段的对白；"
            "优先表现后续动作、反应、停顿、象征画面或情绪收束。"
        ).strip()
    if same_scene_neighbor and dialogue:
        return (
            f"{base_excerpt}\n"
            "对白节拍段：优先覆盖本段对白，同时为相邻无对白动作段留下动作延展空间。"
        ).strip()
    return base_excerpt


def _select_beats_for_confirmed_row(row: Dict[str, Any], rows: List[Dict[str, Any]], index: int, language_beats: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    story_fragment = str(row.get("story_fragment") or "").strip()
    dialogue = _row_dialogue_text(row)
    source_excerpt = _confirmed_row_internal_excerpt(row, rows, index)
    pseudo_segment = {
        "summary": story_fragment,
        "text_span": {"source_excerpt": source_excerpt},
    }
    selected_beats = _select_language_beats_for_segment(pseudo_segment, language_beats)
    if dialogue:
        dialogue_matches = []
        for beat in language_beats or []:
            if not isinstance(beat, dict):
                continue
            beat_text = str(beat.get("source_excerpt") or beat.get("text") or "").strip()
            if beat_text and (beat_text in dialogue or dialogue in beat_text):
                dialogue_matches.append(beat)
        selected_by_id: Dict[str, Dict[str, Any]] = {}
        for beat in [*dialogue_matches, *selected_beats]:
            key = str(beat.get("beat_id") or beat.get("source_excerpt") or beat.get("text") or id(beat))
            selected_by_id[key] = beat
        return list(selected_by_id.values())
    non_speech = [beat for beat in selected_beats if _beat_event_type(beat) not in _SPEECH_BEAT_TYPES]
    return non_speech


def _plan_rows_from_segment_plans(
    segment_plans: List[Dict[str, Any]],
    language_beats: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for index, segment_plan in enumerate(segment_plans, start=1):
        selected_beats = _select_language_beats_for_segment(segment_plan, language_beats)
        source_excerpt = str(
            (segment_plan.get("text_span") or {}).get("source_excerpt")
            or segment_plan.get("summary")
            or ""
        ).strip()
        rows.append(
            {
                "sequence_num": int(segment_plan.get("sequence_num") or index),
                "story_fragment": str(segment_plan.get("summary") or segment_plan.get("title") or source_excerpt).strip(),
                "dialogue": _dialogue_from_beats(selected_beats),
                "estimated_duration_seconds": segment_plan.get("recommended_duration_seconds")
                or segment_plan.get("duration_seconds")
                or _preferred_segment_duration_seconds(selected_beats, 6),
                "source_excerpt": source_excerpt,
                "grid_count": segment_plan.get("grid_count") or _desired_grid_count_from_beats(selected_beats, 4, 6),
            }
        )
    return rows


def _segment_plans_from_confirmed_rows(
    rows: List[Dict[str, Any]],
    language_beats: List[Dict[str, Any]],
    *,
    route_tag: str,
) -> List[Dict[str, Any]]:
    segment_plans: List[Dict[str, Any]] = []
    previous_state: Optional[Dict[str, Any]] = None
    for index, row in enumerate(rows, start=1):
        source_excerpt = _confirmed_row_internal_excerpt(row, rows, index)
        selected_beats = _select_beats_for_confirmed_row(row, rows, index, language_beats)
        duration = _preferred_segment_duration_seconds(selected_beats, row.get("estimated_duration_seconds") or 6)
        grid_count = _desired_grid_count_from_beats(selected_beats, row.get("grid_count") or 4, duration)
        dialogue = _row_dialogue_text(row)
        language_focus = dialogue or (
            "无对白动作/情绪延展：不要重复相邻对白，重点拆后续动作、反应、停顿和象征画面。"
            if str(row.get("story_fragment") or "").strip() in {
                str((rows[index - 2] if index > 1 else {}).get("story_fragment") or "").strip(),
                str((rows[index] if index < len(rows) else {}).get("story_fragment") or "").strip(),
            }
            else ""
        )
        segment_plan: Dict[str, Any] = {
            "sequence_num": int(row.get("sequence_num") or index),
            "title": f"剧情片段 {index}",
            "summary": str(row.get("story_fragment") or source_excerpt or f"剧情片段 {index}").strip(),
            "segment_prompt_summary": str(source_excerpt or row.get("story_fragment") or "").strip(),
            "text_span": {"source_excerpt": source_excerpt},
            "recommended_duration_seconds": duration,
            "grid_count": grid_count,
            "speech_coverage_targets": _speech_type_targets_from_beats(selected_beats),
            "language_focus_summary": language_focus,
            "character_refs": [],
            "scene_refs": [],
            "prop_refs": [],
            "planner_route": route_tag,
        }
        segment_plan["continuity_state"] = _build_segment_continuity_state(segment_plan, previous_state=previous_state)
        segment_plan["previous_continuity_summary"] = _continuity_state_summary(previous_state)
        previous_state = segment_plan["continuity_state"]
        segment_plans.append(segment_plan)
    return segment_plans


def build_storyboard_plan_bundle(
    *,
    episode_id: int,
    text: str,
    api_key: str,
    storyboard_mode: Optional[str],
    previous_plan_bundle: Optional[Dict[str, Any]] = None,
    revision_instruction: Optional[str] = None,
    billing_tracker: Optional[StoryboardSplitBillingTracker] = None,
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    with Session(engine) as session:
        episode = session.get(Episode, episode_id)
        if not episode:
            raise ValueError("Episode not found")
        script = session.get(Script, episode.script_id)
        effective_workflow_profile = resolve_effective_workflow_profile(
            script,
            episode=episode,
            storyboard_mode=storyboard_mode or episode.storyboard_mode,
        ) if script else {"storyboard": {"deep_thinking": False}}
        resolved_storyboard_mode = normalize_storyboard_mode(storyboard_mode or episode.storyboard_mode)
        structured_assets_raw = load_structured_assets_from_shared_resources(session, episode.script_id)
        characters = normalize_structured_asset_items(structured_assets_raw.get("characters") or [], "character")
        scenes = normalize_structured_asset_items(structured_assets_raw.get("scenes") or [], "scene")
        props = normalize_structured_asset_items(structured_assets_raw.get("props") or [], "prop")
        if not (characters or scenes or props):
            raise ValueError("请先完成资产提取后再拆分分镜")

    usage_callback = billing_tracker.record_usage if billing_tracker else None
    total_assets = len(characters) + len(scenes) + len(props)
    deep_thinking_enabled = bool(((effective_workflow_profile or {}).get("storyboard") or {}).get("deep_thinking"))
    planner_model, planner_thinking, route_tag = _resolve_planner_route(text, total_assets, deep_thinking=deep_thinking_enabled)
    previous_rows = _extract_plan_rows(previous_plan_bundle)
    planner_text = text
    instruction = str(revision_instruction or "").strip()
    if instruction and previous_rows:
        previous_table = "\n".join(
            f"{row['sequence_num']}. {row['story_fragment']} | 对话：{row.get('dialogue') or '无'} | 时长：{row.get('estimated_duration_seconds')}"
            for row in previous_rows
        )
        planner_text = f"{text}\n\n【上一版剧情片段规划】\n{previous_table}\n\n【用户修改意见】\n{instruction}\n请只调整剧情片段规划，不要输出图片提示词、视频提示词或内部推理。"

    language_beats_payload = call_story_language_beat_extractor(
        planner_text,
        api_key,
        structured_assets={"characters": characters, "scenes": scenes, "props": props},
        storyboard_mode=resolved_storyboard_mode,
        model=planner_model,
        provider_timeout_seconds=provider_timeout_seconds,
        json_fix_timeout_seconds=json_fix_timeout_seconds,
        usage_callback=usage_callback,
    )
    language_beats = expand_language_beats_for_timing(
        [item for item in (language_beats_payload.get("language_beats") or []) if isinstance(item, dict)]
    )
    if not language_beats:
        raise StorySegmentParseError("language_beats_invalid_json", "语言事件提取结果为空")

    planner_payload = call_story_segment_planner(
        planner_text,
        api_key,
        structured_assets={"characters": characters, "scenes": scenes, "props": props},
        storyboard_mode=resolved_storyboard_mode,
        language_beats=language_beats,
        model=planner_model,
        thinking_enabled=planner_thinking,
        provider_timeout_seconds=provider_timeout_seconds,
        json_fix_timeout_seconds=json_fix_timeout_seconds,
        usage_callback=usage_callback,
        previous_chunk_continuity_summary="",
    )
    segment_plans = [item for item in (planner_payload.get("story_segments") or []) if isinstance(item, dict)]
    if not segment_plans:
        raise StorySegmentParseError("planner_invalid_json", "剧情片段规划结果为空")
    segment_plans = _retime_segment_plans_with_language_beats(segment_plans, language_beats)
    rows = _plan_rows_from_segment_plans(segment_plans, language_beats)
    total_estimated_duration_seconds = _total_plan_duration_seconds(rows)
    return {
        "artifact_type": "storyboard_plan_bundle",
        "plan_id": uuid.uuid4().hex,
        "version": int((previous_plan_bundle or {}).get("version") or 0) + 1,
        "rows": rows,
        "total_estimated_duration_seconds": total_estimated_duration_seconds,
        "total_duration_seconds": total_estimated_duration_seconds,
        "source_episode_id": episode_id,
        "status": "ready",
        "storyboard_mode": resolved_storyboard_mode,
        "language_beats": language_beats,
        "planner_route": route_tag,
    }


def build_storyboard_split_structured_draft(
    *,
    episode_id: int,
    text: str,
    api_key: str,
    storyboard_mode: Optional[str],
    confirmed_plan_bundle: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
    billing_tracker: Optional[StoryboardSplitBillingTracker] = None,
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
    preview_callback=None,
    split_progress_callback=None,
) -> Dict[str, Any]:
    warnings: List[str] = []
    with Session(engine) as session:
        episode = session.get(Episode, episode_id)
        if not episode:
            raise ValueError("Episode not found")
        script = session.get(Script, episode.script_id)
        effective_workflow_profile = resolve_effective_workflow_profile(
            script,
            episode=episode,
            storyboard_mode=storyboard_mode or episode.storyboard_mode,
        ) if script else {"storyboard": {"deep_thinking": False}}
        resolved_storyboard_mode = normalize_storyboard_mode(storyboard_mode or episode.storyboard_mode)
        structured_assets_raw = load_structured_assets_from_shared_resources(session, episode.script_id)
        characters = normalize_structured_asset_items(structured_assets_raw.get("characters") or [], "character")
        scenes = normalize_structured_asset_items(structured_assets_raw.get("scenes") or [], "scene")
        props = normalize_structured_asset_items(structured_assets_raw.get("props") or [], "prop")
        if not (characters or scenes or props):
            raise ValueError("请先完成资产提取后再拆分分镜")
        if not characters:
            warnings.append("缺少人物资产")
        if not scenes:
            warnings.append("缺少场景资产")
        if not props:
            warnings.append("缺少道具资产")

    usage_callback = billing_tracker.record_usage if billing_tracker else None
    total_assets = len(characters) + len(scenes) + len(props)
    deep_thinking_enabled = bool(((effective_workflow_profile or {}).get("storyboard") or {}).get("deep_thinking"))
    planner_model, planner_thinking, route_tag = _resolve_planner_route(text, total_assets, deep_thinking=deep_thinking_enabled)
    confirmed_plan_rows = _extract_plan_rows(confirmed_plan_bundle)
    text_chunks = [text] if confirmed_plan_rows else _split_text_into_storyboard_chunks(text)
    if not text_chunks:
        raise StorySegmentParseError("planner_invalid_json", "剧情片段规划结果为空")

    story_segments: List[Dict[str, Any]] = []
    previous_chunk_state: Optional[Dict[str, Any]] = None
    locked_durations_by_sequence: Dict[int, int] = {}

    for chunk_index, chunk_text in enumerate(text_chunks, start=1):
        _ensure_not_cancelled(task_id)
        _update_task_progress(
            task_id,
            stage="extracting_language_beats",
            progress=min(20, 5 + int((chunk_index - 1) / max(len(text_chunks), 1) * 10)),
            current_segment=len(story_segments),
            segment_count=None,
            message=f"正在分析第 {chunk_index}/{len(text_chunks)} 段剧情的语言节拍...",
        )
        language_beats_payload = call_story_language_beat_extractor(
            chunk_text,
            api_key,
            structured_assets={"characters": characters, "scenes": scenes, "props": props},
            storyboard_mode=resolved_storyboard_mode,
            model=planner_model,
            provider_timeout_seconds=provider_timeout_seconds,
            json_fix_timeout_seconds=json_fix_timeout_seconds,
            usage_callback=usage_callback,
        )
        language_beats = expand_language_beats_for_timing(
            [item for item in (language_beats_payload.get("language_beats") or []) if isinstance(item, dict)]
        )
        if not language_beats:
            raise StorySegmentParseError("language_beats_invalid_json", "语言事件提取结果为空")
        _update_task_progress(
            task_id,
            stage="planning_segments",
            progress=min(35, 12 + int((chunk_index - 1) / max(len(text_chunks), 1) * 10)),
            current_segment=len(story_segments),
            segment_count=None,
            message=f"正在规划第 {chunk_index}/{len(text_chunks)} 段剧情片段...",
        )
        if confirmed_plan_rows:
            segment_plans = _segment_plans_from_confirmed_rows(
                confirmed_plan_rows,
                language_beats,
                route_tag=str((confirmed_plan_bundle or {}).get("planner_route") or route_tag),
            )
        else:
            planner_payload = call_story_segment_planner(
                chunk_text,
                api_key,
                structured_assets={"characters": characters, "scenes": scenes, "props": props},
                storyboard_mode=resolved_storyboard_mode,
                language_beats=language_beats,
                model=planner_model,
                thinking_enabled=planner_thinking,
                provider_timeout_seconds=provider_timeout_seconds,
                json_fix_timeout_seconds=json_fix_timeout_seconds,
                usage_callback=usage_callback,
                previous_chunk_continuity_summary=_continuity_state_summary(previous_chunk_state),
            )
            segment_plans = [item for item in (planner_payload.get("story_segments") or []) if isinstance(item, dict)]
        if not segment_plans:
            raise StorySegmentParseError("planner_invalid_json", "剧情片段规划结果为空")
        segment_plans = _retime_segment_plans_with_language_beats(segment_plans, language_beats)
        if confirmed_plan_rows:
            sequence_offset = len(story_segments)
            for local_index, segment_plan in enumerate(segment_plans, start=1):
                locked_duration = _coerce_duration_seconds(segment_plan.get("recommended_duration_seconds"))
                if locked_duration:
                    locked_durations_by_sequence[sequence_offset + local_index] = locked_duration
        for index, segment_plan in enumerate(segment_plans, start=1):
            local_previous_state = segment_plans[index - 2].get("continuity_state") if index > 1 else previous_chunk_state
            continuity_state = _build_segment_continuity_state(segment_plan, previous_state=local_previous_state)
            segment_plan["continuity_state"] = continuity_state
            segment_plan["previous_continuity_summary"] = _continuity_state_summary(local_previous_state)
            segment_plan["planner_route"] = route_tag

        _ensure_not_cancelled(task_id)
        segment_count = len(segment_plans)
        _update_task_progress(
            task_id,
            stage="expanding_grids",
            progress=min(85, 20 + int(((chunk_index - 1) / max(len(text_chunks), 1)) * 50)),
            current_segment=len(story_segments),
            segment_count=len(story_segments) + segment_count,
            message=f"正在细化第 {chunk_index}/{len(text_chunks)} 段剧情的宫格镜头...",
        )

        expanded_cells: Dict[int, List[Dict[str, Any]]] = {}
        split_status: Dict[int, str] = {index: "等待中" for index in range(1, len(segment_plans) + 1)}

        def _emit_split_progress() -> None:
            if not callable(split_progress_callback):
                return
            rows = []
            for index, segment_plan in enumerate(segment_plans, start=1):
                rows.append(
                    {
                        "sequence_num": len(story_segments) + index,
                        "story_fragment": str(segment_plan.get("summary") or segment_plan.get("title") or "").strip(),
                        "grid_count": segment_plan.get("grid_count") or "",
                        "status": split_status.get(index) or "等待中",
                    }
                )
            try:
                split_progress_callback(rows)
            except Exception:
                pass

        _emit_split_progress()

        def _expand_one_segment(index: int, segment_plan: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
            result = call_story_grid_expander(
                segment_plan,
                api_key,
                structured_assets={"characters": characters, "scenes": scenes, "props": props},
                storyboard_mode=resolved_storyboard_mode,
                segment_text=str(
                    (segment_plan.get("text_span") or {}).get("source_excerpt")
                    or segment_plan.get("summary")
                    or ""
                ),
                language_beats=language_beats,
                model=settings.DEEPSEEK_STORY_GRID_EXPANDER_MODEL,
                provider_timeout_seconds=provider_timeout_seconds,
                json_fix_timeout_seconds=json_fix_timeout_seconds,
                usage_callback=usage_callback,
            )
            return index, list(result.get("grid_cells") or [])

        batch_expander_used = False
        if segment_plans:
            for running_index in range(1, len(segment_plans) + 1):
                split_status[running_index] = "整版细化中"
            _emit_split_progress()
            try:
                batch_result = call_story_grid_batch_expander(
                    segment_plans,
                    api_key,
                    structured_assets={"characters": characters, "scenes": scenes, "props": props},
                    storyboard_mode=resolved_storyboard_mode,
                    full_text=chunk_text,
                    language_beats=language_beats,
                    model=settings.DEEPSEEK_STORY_GRID_EXPANDER_MODEL,
                    provider_timeout_seconds=provider_timeout_seconds,
                    json_fix_timeout_seconds=json_fix_timeout_seconds,
                    usage_callback=usage_callback,
                )
                for item in batch_result.get("grid_segments") or []:
                    if not isinstance(item, dict):
                        continue
                    try:
                        sequence_num = int(item.get("sequence_num") or 0)
                    except Exception:
                        sequence_num = 0
                    if 1 <= sequence_num <= len(segment_plans):
                        cells = [cell for cell in (item.get("grid_cells") or []) if isinstance(cell, dict)]
                        if cells:
                            expanded_cells[sequence_num] = cells
                            split_status[sequence_num] = "已细化"
                missing_indexes = [index for index in range(1, len(segment_plans) + 1) if index not in expanded_cells]
                if not missing_indexes:
                    batch_expander_used = True
                    warnings.append("storyboard grid expander used full-plan batch context")
                    _emit_split_progress()
            except StorySegmentParseError as exc:
                warnings.append(f"storyboard batch grid expander fallback: {exc.error_code}")
            except Exception as exc:
                warnings.append(f"storyboard batch grid expander fallback: {type(exc).__name__}")

        missing_indexes = [index for index in range(1, len(segment_plans) + 1) if index not in expanded_cells]
        if missing_indexes:
            for index in missing_indexes:
                split_status[index] = "等待中"
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                for running_index in missing_indexes[:2]:
                    split_status[running_index] = "拆分中"
                _emit_split_progress()
                futures = [executor.submit(_expand_one_segment, index, segment_plans[index - 1]) for index in missing_indexes]
                completed = 0
                for future in concurrent.futures.as_completed(futures):
                    _ensure_not_cancelled(task_id)
                    index, cells = future.result()
                    expanded_cells[index] = cells
                    completed += 1
                    split_status[index] = "已细化"
                    next_waiting = next((pending_index for pending_index in missing_indexes if split_status.get(pending_index) == "等待中"), None)
                    if next_waiting is not None:
                        split_status[next_waiting] = "拆分中"
                    _emit_split_progress()
                    if callable(preview_callback):
                        try:
                            preview_callback(story_segments + segment_plans[:completed], len(story_segments) + segment_count)
                        except Exception:
                            pass
                    _update_task_progress(
                        task_id,
                        stage="expanding_grids",
                        progress=min(85, 20 + int((((chunk_index - 1) + (completed / max(segment_count, 1))) / max(len(text_chunks), 1)) * 65)),
                        current_segment=len(story_segments) + completed,
                        segment_count=len(story_segments) + segment_count,
                        message=f"正在补跑分镜细化 {len(story_segments) + min(completed + 1, len(missing_indexes))}/{len(story_segments) + len(missing_indexes)}...",
                    )
        elif batch_expander_used:
            _update_task_progress(
                task_id,
                stage="expanding_grids",
                progress=min(85, 20 + int((chunk_index / max(len(text_chunks), 1)) * 65)),
                current_segment=len(story_segments) + segment_count,
                segment_count=len(story_segments) + segment_count,
                message=f"整版分镜细化完成，正在校验 {len(story_segments) + segment_count} 个片段...",
            )

        assembled_segments = []
        for index, segment_plan in enumerate(segment_plans, start=1):
            assembled_segments.append({**segment_plan, "grid_cells": expanded_cells.get(index) or []})

        with Session(engine) as session:
            episode = session.get(Episode, episode_id)
            if not episode:
                raise ValueError("Episode not found")
            normalized = normalize_story_segment_payload_v2(
                {"story_segments": assembled_segments},
                episode=episode,
                structured_assets={"characters": characters, "scenes": scenes, "props": props},
                session=session,
                storyboard_mode=resolved_storyboard_mode,
            )
        warnings.extend(normalized.get("warnings") or [])
        chunk_story_segments = normalized.get("story_segments") or []
        if not chunk_story_segments:
            raise StorySegmentParseError("grid_invalid_json", "剧情片段细化结果为空")
        _apply_story_segment_consistency(
            chunk_story_segments,
            warnings,
            storyboard_mode=resolved_storyboard_mode,
            initial_previous_state=previous_chunk_state,
        )
        if chunk_story_segments and isinstance(chunk_story_segments[-1], dict):
            previous_chunk_state = chunk_story_segments[-1].get("continuity_state") if isinstance(chunk_story_segments[-1].get("continuity_state"), dict) else previous_chunk_state
        story_segments.extend(chunk_story_segments)

    for index, item in enumerate(story_segments, start=1):
        item["sequence_num"] = index
    _lock_story_segments_to_confirmed_durations(story_segments, locked_durations_by_sequence)
    _apply_story_segment_consistency(story_segments, warnings, storyboard_mode=resolved_storyboard_mode)
    if not story_segments:
        raise StorySegmentParseError("grid_invalid_json", "剧情片段细化结果为空")

    def _emit_overall_split_progress(status: str, *, public_summary: str = "") -> None:
        if not callable(split_progress_callback):
            return
        rows = []
        public_text = str(public_summary or "").strip()
        for index, segment in enumerate(story_segments, start=1):
            if not isinstance(segment, dict):
                continue
            rows.append(
                {
                    "sequence_num": segment.get("sequence_num") or index,
                    "story_fragment": str(segment.get("summary") or segment.get("title") or "").strip(),
                    "grid_count": segment.get("grid_count") or len(segment.get("grid_cells") or []),
                    "status": status,
                    "public_summary": public_text,
                }
            )
        try:
            split_progress_callback(rows)
        except Exception:
            pass

    _emit_overall_split_progress("校验中")
    validation_errors = validate_story_segments_semantics(story_segments)
    if validation_errors:
        locally_repaired_segments = _repair_story_segments_locally(
            story_segments,
            validation_errors=validation_errors,
            warnings=warnings,
        )
        with Session(engine) as session:
            episode = session.get(Episode, episode_id)
            if not episode:
                raise ValueError("Episode not found")
            normalized = normalize_story_segment_payload_v2(
                {"story_segments": locally_repaired_segments},
                episode=episode,
                structured_assets={"characters": characters, "scenes": scenes, "props": props},
                session=session,
                storyboard_mode=resolved_storyboard_mode,
            )
        warnings.extend(normalized.get("warnings") or [])
        story_segments = normalized.get("story_segments") or []
        validation_errors = validate_story_segments_semantics(story_segments)

    if validation_errors:
        critic_error: Optional[StorySegmentParseError] = None
        _emit_overall_split_progress("修复中", public_summary="正在自动校准分镜时长和宫格结构，不需要你处理。")
        try:
            repaired = repair_story_segments_semantically(
                story_segments=story_segments,
                validation_errors=validation_errors,
                api_key=api_key,
                storyboard_mode=resolved_storyboard_mode,
                provider_timeout_seconds=provider_timeout_seconds,
                json_fix_timeout_seconds=json_fix_timeout_seconds,
                usage_callback=usage_callback,
            )
        except StorySegmentParseError as exc:
            critic_error = exc
            repaired = {
                "story_segments": _repair_story_segments_locally(
                    story_segments,
                    validation_errors=validation_errors + [f"critic repair failed: {exc.error_code}"],
                    warnings=warnings,
                )
            }
        with Session(engine) as session:
            episode = session.get(Episode, episode_id)
            if not episode:
                raise ValueError("Episode not found")
            normalized = normalize_story_segment_payload_v2(
                {"story_segments": repaired.get("story_segments") or []},
                episode=episode,
                structured_assets={"characters": characters, "scenes": scenes, "props": props},
                session=session,
                storyboard_mode=resolved_storyboard_mode,
            )
        warnings.extend(normalized.get("warnings") or [])
        story_segments = normalized.get("story_segments") or []
        _lock_story_segments_to_confirmed_durations(story_segments, locked_durations_by_sequence)
        validation_errors = validate_story_segments_semantics(story_segments)
        if validation_errors:
            locally_repaired_segments = _repair_story_segments_locally(
                story_segments,
                validation_errors=validation_errors,
                warnings=warnings,
            )
            with Session(engine) as session:
                episode = session.get(Episode, episode_id)
                if not episode:
                    raise ValueError("Episode not found")
                normalized = normalize_story_segment_payload_v2(
                    {"story_segments": locally_repaired_segments},
                    episode=episode,
                    structured_assets={"characters": characters, "scenes": scenes, "props": props},
                    session=session,
                    storyboard_mode=resolved_storyboard_mode,
                )
            warnings.extend(normalized.get("warnings") or [])
            story_segments = normalized.get("story_segments") or []
            _lock_story_segments_to_confirmed_durations(story_segments, locked_durations_by_sequence)
            validation_errors = validate_story_segments_semantics(story_segments)
        if validation_errors:
            blocking_errors = _blocking_story_segment_validation_errors(validation_errors)
            if blocking_errors:
                final_repaired_segments = _repair_story_segments_locally(
                    story_segments,
                    validation_errors=blocking_errors,
                    warnings=warnings,
                )
                with Session(engine) as session:
                    episode = session.get(Episode, episode_id)
                    if not episode:
                        raise ValueError("Episode not found")
                    normalized = normalize_story_segment_payload_v2(
                        {"story_segments": final_repaired_segments},
                        episode=episode,
                        structured_assets={"characters": characters, "scenes": scenes, "props": props},
                        session=session,
                        storyboard_mode=resolved_storyboard_mode,
                    )
                warnings.extend(normalized.get("warnings") or [])
                story_segments = normalized.get("story_segments") or []
                _lock_story_segments_to_confirmed_durations(story_segments, locked_durations_by_sequence)
                final_validation_errors = validate_story_segments_semantics(story_segments)
                final_blocking_errors = _blocking_story_segment_validation_errors(final_validation_errors)
                if final_blocking_errors:
                    fatal_errors = [
                        item for item in final_blocking_errors
                        if "story_segments is empty" in item
                    ]
                    if fatal_errors or not story_segments:
                        _emit_overall_split_progress("需要修复", public_summary="自动校准没有完全通过，请调整规划后重试。")
                        raise StorySegmentParseError(
                            "semantic_validation_failed",
                            "分镜语义校验失败",
                            detail="; ".join(final_blocking_errors[:10]),
                        )
                    warnings.append("storyboard semantic hard warnings downgraded after local repair: " + "; ".join(final_blocking_errors[:5]))
                non_blocking_errors = [
                    item for item in final_validation_errors
                    if item not in set(final_blocking_errors)
                ]
                if non_blocking_errors:
                    warnings.append("storyboard semantic advisories: " + "; ".join(non_blocking_errors[:5]))
            else:
                warnings.append("storyboard semantic advisories: " + "; ".join(validation_errors[:5]))
    _emit_overall_split_progress("校验通过")

    if callable(preview_callback):
        try:
            preview_callback(story_segments, len(story_segments))
        except Exception:
            pass

    return {
        "storyboard_mode": resolved_storyboard_mode,
        "characters": characters,
        "scenes": scenes,
        "props": props,
        "language_beats": language_beats,
        "director_draft": {},
        "panel_drafts": [],
        "story_segments": story_segments,
        "warnings": warnings,
    }


def run_storyboard_split_runtime(
    *,
    episode_id: int,
    text: str,
    storyboard_mode: Optional[str],
    api_key: str,
    task_id: Optional[str] = None,
    confirmed_plan_bundle: Optional[Dict[str, Any]] = None,
    commit_segments: bool = True,
    charge_enabled: bool = True,
    user_id: Optional[int] = None,
    team_id: Optional[int] = None,
) -> Dict[str, Any]:
    billing_tracker = StoryboardSplitBillingTracker(
        user_id=user_id,
        team_id=team_id,
        task_id=task_id,
        charge_enabled=charge_enabled,
    )
    if task_id:
        update_task_job(
            task_id,
            status="running",
            stage="planning_segments",
            progress=0,
            message="正在拆分剧情片段与多宫格镜头...",
            actual_cost_cny=0.0,
            charged_points=0,
            actual_points=0,
            points_status=POINTS_STATUS_FREE,
            billing_detail=[],
        )

    structured_draft = build_storyboard_split_structured_draft(
        episode_id=episode_id,
        text=text,
        api_key=api_key,
        storyboard_mode=storyboard_mode,
        confirmed_plan_bundle=confirmed_plan_bundle,
        task_id=task_id,
        billing_tracker=billing_tracker,
        provider_timeout_seconds=None,
        json_fix_timeout_seconds=None,
    )
    story_segments = list(structured_draft.get("story_segments") or [])
    if not story_segments:
        raise StorySegmentParseError("grid_invalid_json", "剧情片段细化结果为空")

    commit_result: Dict[str, Any] = {
        "auto_committed": False,
        "redirect_target": "table",
        "segment_count": 0,
        "grid_distribution": {},
        "average_duration_seconds": 0,
        "storyboard_mode": structured_draft.get("storyboard_mode"),
        "segments": [],
    }
    if commit_segments:
        _ensure_not_cancelled(task_id)
        _update_task_progress(
            task_id,
            stage="committing",
            progress=90,
            current_segment=len(story_segments),
            segment_count=len(story_segments),
            message="正在写入分镜表...",
        )
        with Session(engine) as session:
            episode = session.get(Episode, episode_id)
            if not episode:
                raise ValueError("Episode not found")
            created_panels = commit_story_segments_with_cells(
                session,
                episode=episode,
                story_segments=story_segments,
                replace_existing=True,
            )
            segment_count = len(created_panels)
            if segment_count <= 0:
                raise StorySegmentParseError("commit_failed", "剧情片段写入失败，未创建任何分镜片段")
            grid_distribution: Dict[str, int] = {}
            total_duration = 0
            for panel in created_panels:
                grid_key = str(panel.grid_count or 1)
                grid_distribution[grid_key] = grid_distribution.get(grid_key, 0) + 1
                total_duration += int(panel.recommended_duration_seconds or 0)
            commit_result = {
                "auto_committed": True,
                "redirect_target": "table",
                "segment_count": segment_count,
                "grid_distribution": grid_distribution,
                "average_duration_seconds": round(total_duration / segment_count, 2) if segment_count else 0,
                "storyboard_mode": structured_draft.get("storyboard_mode"),
                "segments": [
                    {
                        "id": encode_id(panel.id),
                        "sequence_num": panel.sequence_num,
                        "grid_count": panel.grid_count,
                    }
                    for panel in created_panels
                ],
            }

    result = {
        "structured_draft": structured_draft,
        "warnings": structured_draft.get("warnings") or [],
        **commit_result,
        "billing": billing_tracker.snapshot(),
    }
    if task_id:
        mark_task_job_succeeded(
            task_id,
            result=result,
            message=f"剧情片段拆分完成，已生成 {len(story_segments)} 个片段。",
        )
        update_task_job(
            task_id,
            actual_cost_cny=result["billing"]["actual_cost_cny"],
            charged_points=result["billing"]["charged_points"],
            actual_points=result["billing"]["actual_points"],
            points_status=result["billing"]["points_status"],
            billing_detail=result["billing"]["billing_detail"],
        )
    return result
