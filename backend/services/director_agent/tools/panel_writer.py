"""Tool: write panel drafts into the current episode via the shared storyboard commit path."""

from dataclasses import dataclass
from typing import Any, Dict, List

from sqlmodel import Session

from models import Episode
from services.storyboard_mode_service import commit_storyboard_panel_drafts


@dataclass
class CommitResult:
    success: bool
    panels_created: int
    resources_synced: int
    warnings: List[str]


class PanelWriterTool:
    """Legacy director-agent adapter for panel persistence."""

    def commit_panel_drafts(
        self,
        session: Session,
        episode_id: int,
        panel_drafts: List[Dict[str, Any]],
        sync_resources: bool = True,
        replace_existing: bool = False,
    ) -> CommitResult:
        del sync_resources  # bindings are resolved in the shared commit helper

        episode = session.get(Episode, episode_id)
        if not episode:
            return CommitResult(
                success=False,
                panels_created=0,
                resources_synced=0,
                warnings=["Episode not found"],
            )

        try:
            created_panels = commit_storyboard_panel_drafts(
                session,
                episode=episode,
                panel_drafts=panel_drafts or [],
                replace_existing=replace_existing,
            )
        except Exception as exc:
            return CommitResult(
                success=False,
                panels_created=0,
                resources_synced=0,
                warnings=[str(exc)],
            )

        return CommitResult(
            success=True,
            panels_created=len(created_panels),
            resources_synced=0,
            warnings=[],
        )

    def create_segment_only(
        self,
        session: Session,
        episode_id: int,
        segments: List[Dict[str, Any]],
    ) -> CommitResult:
        episode = session.get(Episode, episode_id)
        if not episode:
            return CommitResult(
                success=False,
                panels_created=0,
                resources_synced=0,
                warnings=["Episode not found"],
            )

        panel_drafts = []
        for index, segment in enumerate(segments or [], start=1):
            panel_drafts.append(
                {
                    "sequence": index,
                    "storyboard_mode": getattr(episode, "storyboard_mode", "commentary") or "commentary",
                    "panel_type": "normal",
                    "segment_no": int(segment.get("segment_no") or index),
                    "segment_summary": str(segment.get("summary") or ""),
                    "narrative_purpose": str(segment.get("narrative_purpose") or ""),
                    "original_text": str(segment.get("summary") or ""),
                    "prompt": str(segment.get("prompt") or ""),
                    "prompt_zh": str(segment.get("prompt_zh") or segment.get("prompt") or ""),
                    "video_prompt": str(segment.get("video_prompt") or ""),
                    "image_framing": str(segment.get("image_framing") or ""),
                    "scene_refs": segment.get("scene_refs") or [],
                    "character_refs": segment.get("character_refs") or [],
                    "prop_refs": segment.get("prop_refs") or [],
                }
            )

        return self.commit_panel_drafts(
            session,
            episode_id,
            panel_drafts,
            sync_resources=True,
            replace_existing=False,
        )
