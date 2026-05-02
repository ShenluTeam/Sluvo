from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Tuple

from sqlmodel import Session, select

from models import Panel, PanelRevision
from schemas import normalize_panel_type
from services.storyboard_mode_service import normalize_panel_storyboard_payload

SNAPSHOT_FIELDS = (
    "title",
    "panel_type",
    "storyboard_mode",
    "text_span_json",
    "recommended_duration_seconds",
    "grid_count",
    "pacing",
    "rhythm",
    "continuity_note",
    "scene_prompt",
    "multi_shot_prompt",
    "multi_shot_video_prompt",
    "reference_assets_json",
    "reference_images_json",
    "auto_asset_reference_enabled",
    "segment_no",
    "segment_summary",
    "narrative_purpose",
    "panel_type_reason",
    "segment_prompt_summary",
    "narration_text",
    "dialogue_text",
    "segment_break",
    "dependency_panel_id",
    "shot_type",
    "camera_motion",
    "composition",
    "previous_storyboard_path",
    "transition_to_next",
    "scene",
    "character",
    "prop",
    "prompt",
    "nine_grid_prompt",
    "video_prompt",
    "image_framing",
    "original_text",
    "entity_bindings_json",
    "generation_status",
    "note",
)


def _normalize_bindings(raw: Any) -> str:
    if raw is None:
        return "{}"
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            return json.dumps(parsed, ensure_ascii=False, sort_keys=True)
        except Exception:
            return "{}"
    if isinstance(raw, dict):
        return json.dumps(raw, ensure_ascii=False, sort_keys=True)
    return "{}"


def _build_snapshot(panel: Panel, payload: Dict[str, Any]) -> Dict[str, Any]:
    snapshot = {
        "title": panel.title or "",
        "panel_type": normalize_panel_type(panel.panel_type),
        "storyboard_mode": panel.storyboard_mode or "commentary",
        "text_span_json": panel.text_span_json or "{}",
        "recommended_duration_seconds": panel.recommended_duration_seconds or 6,
        "grid_count": panel.grid_count or 1,
        "pacing": panel.pacing or "",
        "rhythm": panel.rhythm or "",
        "continuity_note": panel.continuity_note or "",
        "scene_prompt": panel.scene_prompt or "",
        "multi_shot_prompt": panel.multi_shot_prompt or "",
        "multi_shot_video_prompt": panel.multi_shot_video_prompt or "",
        "reference_assets_json": panel.reference_assets_json or "[]",
        "reference_images_json": panel.reference_images_json or "[]",
        "auto_asset_reference_enabled": bool(panel.auto_asset_reference_enabled),
        "segment_no": panel.segment_no,
        "segment_summary": panel.segment_summary or "",
        "narrative_purpose": panel.narrative_purpose or "",
        "panel_type_reason": panel.panel_type_reason or "",
        "segment_prompt_summary": panel.segment_prompt_summary or "",
        "narration_text": panel.narration_text or "",
        "dialogue_text": panel.dialogue_text or "",
        "segment_break": bool(panel.segment_break),
        "dependency_panel_id": panel.dependency_panel_id,
        "shot_type": panel.shot_type or "",
        "camera_motion": panel.camera_motion or "",
        "composition": panel.composition or "",
        "previous_storyboard_path": panel.previous_storyboard_path or "",
        "transition_to_next": panel.transition_to_next or "",
        "scene": panel.scene or "",
        "character": panel.character or "",
        "prop": panel.prop or "",
        "prompt": panel.prompt or "",
        "nine_grid_prompt": panel.nine_grid_prompt or "",
        "video_prompt": panel.video_prompt or "",
        "image_framing": panel.image_framing or "",
        "original_text": panel.original_text or "",
        "entity_bindings_json": _normalize_bindings(panel.entity_bindings_json),
        "generation_status": panel.generation_status or "idle",
        "note": panel.note or "",
    }

    if "entity_bindings" in payload and payload["entity_bindings"] is not None:
        snapshot["entity_bindings_json"] = _normalize_bindings(payload["entity_bindings"])

    merged_payload = dict(snapshot)
    merged_payload.update(payload)
    normalized = normalize_panel_storyboard_payload(merged_payload, fallback_mode=snapshot["storyboard_mode"])
    snapshot.update(normalized)
    snapshot["panel_type"] = normalize_panel_type(snapshot["panel_type"])
    snapshot["entity_bindings_json"] = _normalize_bindings(snapshot.get("entity_bindings_json"))
    return snapshot


def _revision_to_snapshot(revision: PanelRevision) -> Dict[str, Any]:
    return {
        "title": revision.title or "",
        "panel_type": normalize_panel_type(revision.panel_type),
        "storyboard_mode": revision.storyboard_mode or "commentary",
        "text_span_json": revision.text_span_json or "{}",
        "recommended_duration_seconds": revision.recommended_duration_seconds or 6,
        "grid_count": revision.grid_count or 1,
        "pacing": revision.pacing or "",
        "rhythm": revision.rhythm or "",
        "continuity_note": revision.continuity_note or "",
        "scene_prompt": revision.scene_prompt or "",
        "multi_shot_prompt": revision.multi_shot_prompt or "",
        "multi_shot_video_prompt": revision.multi_shot_video_prompt or "",
        "reference_assets_json": revision.reference_assets_json or "[]",
        "reference_images_json": revision.reference_images_json or "[]",
        "auto_asset_reference_enabled": bool(revision.auto_asset_reference_enabled),
        "segment_no": revision.segment_no,
        "segment_summary": revision.segment_summary or "",
        "narrative_purpose": revision.narrative_purpose or "",
        "panel_type_reason": revision.panel_type_reason or "",
        "segment_prompt_summary": revision.segment_prompt_summary or "",
        "narration_text": revision.narration_text or "",
        "dialogue_text": revision.dialogue_text or "",
        "segment_break": bool(revision.segment_break),
        "dependency_panel_id": revision.dependency_panel_id,
        "shot_type": revision.shot_type or "",
        "camera_motion": revision.camera_motion or "",
        "composition": revision.composition or "",
        "previous_storyboard_path": revision.previous_storyboard_path or "",
        "transition_to_next": revision.transition_to_next or "",
        "scene": revision.scene or "",
        "character": revision.character or "",
        "prop": revision.prop or "",
        "prompt": revision.prompt or "",
        "nine_grid_prompt": revision.nine_grid_prompt or "",
        "video_prompt": revision.video_prompt or "",
        "image_framing": revision.image_framing or "",
        "original_text": revision.original_text or "",
        "entity_bindings_json": _normalize_bindings(revision.entity_bindings_json),
        "generation_status": revision.generation_status or "idle",
        "note": revision.note or "",
    }


def _snapshot_hash(snapshot: Dict[str, Any]) -> str:
    payload = {key: snapshot.get(key, "") for key in SNAPSHOT_FIELDS}
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _apply_snapshot_to_panel(panel: Panel, snapshot: Dict[str, Any]) -> None:
    panel.title = snapshot.get("title") or None
    panel.panel_type = normalize_panel_type(snapshot.get("panel_type"))
    panel.storyboard_mode = snapshot.get("storyboard_mode") or "commentary"
    panel.text_span_json = snapshot.get("text_span_json") or "{}"
    panel.recommended_duration_seconds = int(snapshot.get("recommended_duration_seconds") or 6)
    panel.grid_count = int(snapshot.get("grid_count") or 1)
    panel.pacing = snapshot.get("pacing") or None
    panel.rhythm = snapshot.get("rhythm") or None
    panel.continuity_note = snapshot.get("continuity_note") or None
    panel.scene_prompt = snapshot.get("scene_prompt") or None
    panel.multi_shot_prompt = snapshot.get("multi_shot_prompt") or None
    panel.multi_shot_video_prompt = snapshot.get("multi_shot_video_prompt") or None
    panel.reference_assets_json = snapshot.get("reference_assets_json") or "[]"
    panel.reference_images_json = snapshot.get("reference_images_json") or "[]"
    panel.auto_asset_reference_enabled = bool(snapshot.get("auto_asset_reference_enabled", True))
    panel.segment_no = snapshot.get("segment_no")
    panel.segment_summary = snapshot.get("segment_summary") or ""
    panel.narrative_purpose = snapshot.get("narrative_purpose") or ""
    panel.panel_type_reason = snapshot.get("panel_type_reason") or ""
    panel.segment_prompt_summary = snapshot.get("segment_prompt_summary") or ""
    panel.narration_text = snapshot.get("narration_text") or None
    panel.dialogue_text = snapshot.get("dialogue_text") or None
    panel.segment_break = bool(snapshot.get("segment_break"))
    panel.dependency_panel_id = snapshot.get("dependency_panel_id")
    panel.shot_type = snapshot.get("shot_type") or None
    panel.camera_motion = snapshot.get("camera_motion") or None
    panel.composition = snapshot.get("composition") or None
    panel.previous_storyboard_path = snapshot.get("previous_storyboard_path") or None
    panel.transition_to_next = snapshot.get("transition_to_next") or None
    panel.scene = snapshot["scene"] or ""
    panel.character = snapshot["character"] or ""
    panel.prop = snapshot["prop"] or ""
    panel.prompt = snapshot["prompt"] or ""
    panel.nine_grid_prompt = snapshot["nine_grid_prompt"] or ""
    panel.video_prompt = snapshot["video_prompt"] or ""
    panel.image_framing = snapshot["image_framing"] or ""
    panel.original_text = snapshot["original_text"] or ""
    panel.entity_bindings_json = snapshot["entity_bindings_json"] or "{}"
    panel.generation_status = snapshot.get("generation_status") or "idle"
    panel.note = snapshot.get("note") or None


def list_panel_revisions(session: Session, panel_id: int):
    statement = (
        select(PanelRevision)
        .where(PanelRevision.panel_id == panel_id)
        .order_by(PanelRevision.revision_no.desc())
    )
    return session.exec(statement).all()


def update_panel_with_revision(
    session: Session,
    panel: Panel,
    payload: Dict[str, Any],
    *,
    created_by_user_id: int | None = None,
) -> Tuple[Panel, PanelRevision]:
    snapshot = _build_snapshot(panel, payload)
    revisions = list_panel_revisions(session, panel.id)
    latest = revisions[0] if revisions else None

    should_create = True
    if latest:
        latest_hash = _snapshot_hash(_revision_to_snapshot(latest))
        current_hash = _snapshot_hash(snapshot)
        should_create = latest_hash != current_hash

    source = payload.get("source") or "content"
    current_revision = latest
    if should_create:
        next_no = (latest.revision_no + 1) if latest else 1
        current_revision = PanelRevision(
            panel_id=panel.id,
            revision_no=next_no,
            source=source,
            title=snapshot["title"],
            panel_type=snapshot["panel_type"],
            storyboard_mode=snapshot["storyboard_mode"],
            text_span_json=snapshot["text_span_json"],
            recommended_duration_seconds=snapshot["recommended_duration_seconds"],
            grid_count=snapshot["grid_count"],
            pacing=snapshot["pacing"],
            rhythm=snapshot["rhythm"],
            continuity_note=snapshot["continuity_note"],
            scene_prompt=snapshot["scene_prompt"],
            multi_shot_prompt=snapshot["multi_shot_prompt"],
            multi_shot_video_prompt=snapshot["multi_shot_video_prompt"],
            reference_assets_json=snapshot["reference_assets_json"],
            reference_images_json=snapshot["reference_images_json"],
            auto_asset_reference_enabled=bool(snapshot["auto_asset_reference_enabled"]),
            segment_no=snapshot["segment_no"],
            segment_summary=snapshot["segment_summary"],
            narrative_purpose=snapshot["narrative_purpose"],
            panel_type_reason=snapshot["panel_type_reason"],
            segment_prompt_summary=snapshot["segment_prompt_summary"],
            narration_text=snapshot["narration_text"],
            dialogue_text=snapshot["dialogue_text"],
            segment_break=bool(snapshot["segment_break"]),
            dependency_panel_id=snapshot["dependency_panel_id"],
            shot_type=snapshot["shot_type"],
            camera_motion=snapshot["camera_motion"],
            composition=snapshot["composition"],
            previous_storyboard_path=snapshot["previous_storyboard_path"],
            transition_to_next=snapshot["transition_to_next"],
            scene=snapshot["scene"],
            character=snapshot["character"],
            prop=snapshot["prop"],
            prompt=snapshot["prompt"],
            nine_grid_prompt=snapshot["nine_grid_prompt"],
            video_prompt=snapshot["video_prompt"],
            image_framing=snapshot["image_framing"],
            original_text=snapshot["original_text"],
            entity_bindings_json=snapshot["entity_bindings_json"],
            generation_status=snapshot["generation_status"],
            note=snapshot["note"],
            created_by_user_id=created_by_user_id,
        )
        session.add(current_revision)
        session.flush()

    _apply_snapshot_to_panel(panel, snapshot)
    panel.updated_at = datetime.utcnow()
    if current_revision:
        panel.current_revision_id = current_revision.id
    session.add(panel)
    session.commit()
    session.refresh(panel)
    if current_revision:
        session.refresh(current_revision)
    return panel, current_revision


def restore_panel_revision(session: Session, panel: Panel, revision: PanelRevision) -> Panel:
    if revision.panel_id != panel.id:
        raise ValueError("revision does not belong to panel")
    snapshot = _revision_to_snapshot(revision)
    _apply_snapshot_to_panel(panel, snapshot)
    panel.updated_at = datetime.utcnow()
    panel.current_revision_id = revision.id
    session.add(panel)
    session.commit()
    session.refresh(panel)
    return panel
