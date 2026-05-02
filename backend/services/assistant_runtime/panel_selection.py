from __future__ import annotations

from typing import List

from models import Panel

from .video_orchestration import (
    ResolvedPanelSelection,
    build_selected_panels_payload,
    resolve_panel_selection,
)

__all__ = [
    "ResolvedPanelSelection",
    "build_selected_panels_payload",
    "format_selected_panel_display",
    "resolve_panel_selection",
]


def format_selected_panel_display(panels: List[Panel]) -> str:
    selected = build_selected_panels_payload(panels)
    sequences = [int(item.get("panel_sequence") or 0) for item in selected if int(item.get("panel_sequence") or 0) > 0]
    if not sequences:
        return "当前分镜"
    if len(sequences) == 1:
        return "第 {0} 镜".format(sequences[0])
    if sequences == list(range(sequences[0], sequences[-1] + 1)):
        return "第 {0}-{1} 镜".format(sequences[0], sequences[-1])
    return "第 {0} 镜".format(" / ".join(str(value) for value in sequences))
