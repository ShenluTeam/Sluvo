from __future__ import annotations

from typing import Any, Dict, List, Optional

from models import Panel
from services.video_model_registry import get_video_model_or_none

from .panel_selection import build_selected_panels_payload


def build_video_execution_plan_payload(
    *,
    execution_stage: str,
    selected_panels: List[Panel],
    model_choice: Optional[Dict[str, Any]] = None,
    selection_reason: str = "",
    resume_hint: str = "",
) -> Dict[str, Any]:
    resolved_model_choice = None
    if model_choice and model_choice.get("model"):
        resolved_model_choice = dict(model_choice["model"])
        resolved_model_choice["selection_mode"] = model_choice.get("selection_mode")
    return {
        "execution_stage": execution_stage,
        "selected_panels": build_selected_panels_payload(selected_panels),
        "resolved_model_choice": resolved_model_choice,
        "selection_reason": selection_reason,
        "resume_hint": resume_hint,
    }


def build_video_generation_field_options(model_code: str, generation_type: str) -> Dict[str, Any]:
    model = get_video_model_or_none(model_code) or {}
    feature = ((model.get("features") or {}).get(generation_type) if isinstance(model, dict) else None) or {}
    defaults = feature.get("defaults") or {}
    pricing_rules = feature.get("pricing_rules") or []

    duration_values = sorted(
        {
            int(item.get("duration"))
            for item in pricing_rules
            if item.get("duration") not in (None, "")
        }
    )
    resolution_values = [
        value
        for value in ["720p", "1080p", "2k"]
        if value in {
            str(item.get("resolution") or "").strip().lower()
            for item in pricing_rules
            if str(item.get("resolution") or "").strip()
        }
    ]

    if not duration_values:
        duration_values = [4, 5, 6, 8, 10, 12]
    if not resolution_values:
        resolution_values = ["720p", "1080p"]

    return {
        "defaults": defaults,
        "duration_options": [{"value": str(item), "label": "{0} 秒".format(item)} for item in duration_values],
        "resolution_options": [{"value": item, "label": item.upper() if item.endswith("k") else item} for item in resolution_values],
    }
