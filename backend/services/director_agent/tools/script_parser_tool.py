from typing import Any, Dict

from sqlmodel import Session

from core.config import settings
from database import engine
from models import Episode
from services.resource_extraction_service import load_structured_assets_from_shared_resources
from services.storyboard_director_service import (
    call_director_model,
    call_story_segment_model_v2,
    extract_json_payload,
    normalize_story_segment_payload_v2,
    normalize_structured_asset_items,
)
from services.storyboard_split_runtime import run_storyboard_split_runtime


class ScriptParserTool:
    """剧本解析工具。"""

    def __init__(self):
        self.api_key = settings.DEEPSEEK_API_KEY

    def parse_script_for_segments(self, source_text: str) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        director_raw = call_director_model(source_text, self.api_key)
        parsed = extract_json_payload(director_raw)

        return {
            "segments": parsed.get("segments", []),
            "paragraphs": parsed.get("paragraphs", []),
            "warnings": parsed.get("warnings", []),
        }

    def parse_story_segments_v3_full(self, episode_id: int, source_text: str) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        with Session(engine) as session:
            episode = session.get(Episode, episode_id)
            if not episode:
                raise ValueError("Episode not found")
            result = run_storyboard_split_runtime(
                episode_id=episode_id,
                text=source_text,
                storyboard_mode=episode.storyboard_mode,
                api_key=self.api_key,
                commit_segments=False,
                charge_enabled=False,
            )
            structured_draft = result.get("structured_draft") or {}
            return {
                "characters": structured_draft.get("characters") or [],
                "scenes": structured_draft.get("scenes") or [],
                "props": structured_draft.get("props") or [],
                "story_segments": structured_draft.get("story_segments") or [],
                "warnings": structured_draft.get("warnings") or [],
                "billing": result.get("billing") or {},
            }

            structured_assets_raw = load_structured_assets_from_shared_resources(session, episode.script_id)
            characters = normalize_structured_asset_items(structured_assets_raw.get("characters") or [], "character")
            scenes = normalize_structured_asset_items(structured_assets_raw.get("scenes") or [], "scene")
            props = normalize_structured_asset_items(structured_assets_raw.get("props") or [], "prop")

            if not (characters or scenes or props):
                raise ValueError("请先完成资产提取后再拆分分镜")

            normalized = normalize_story_segment_payload_v2(
                call_story_segment_model_v2(
                    source_text,
                    self.api_key,
                    structured_assets={
                        "characters": characters,
                        "scenes": scenes,
                        "props": props,
                    },
                    storyboard_mode=episode.storyboard_mode,
                ),
                episode=episode,
                structured_assets={
                    "characters": characters,
                    "scenes": scenes,
                    "props": props,
                },
                session=session,
                storyboard_mode=episode.storyboard_mode,
            )

        warnings = list(normalized.get("warnings") or [])
        if not characters:
            warnings.append("未提取到角色草稿，请手动审核资产")
        if not scenes:
            warnings.append("未提取到场景草稿，请手动审核资产")
        if not props:
            warnings.append("未提取到道具草稿，请手动审核资产")

        return {
            "characters": characters,
            "scenes": scenes,
            "props": props,
            "story_segments": normalized.get("story_segments") or [],
            "warnings": warnings,
        }

    def parse_script_simple(self, source_text: str) -> Dict[str, Any]:
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is not configured")

        director_raw = call_director_model(source_text, self.api_key)
        return extract_json_payload(director_raw)
