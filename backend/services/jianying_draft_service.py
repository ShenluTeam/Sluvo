import json
import logging
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.config import settings
from services.video_compose_service import (
    CANVAS_SIZE_BY_RATIO,
    DEFAULT_STILL_CLIP_DURATION,
    _guess_remote_filename,
    video_compose_service,
)

logger = logging.getLogger(__name__)

try:
    import pyJianYingDraft as _jianying_draft
    from pyJianYingDraft import ClipSettings, TextBorder, TextSegment, TextShadow, TextStyle, TrackType, VideoMaterial, VideoSegment, trange
except Exception:
    _jianying_draft = None
    ClipSettings = None
    TextBorder = None
    TextSegment = None
    TextShadow = None
    TextStyle = None
    TrackType = None
    VideoMaterial = None
    VideoSegment = None
    trange = None


def _safe_realpath(path_value: str) -> str:
    return os.path.realpath(str(path_value or ""))


def _replace_paths_in_json(json_path: str, source_prefix: str, target_prefix: str) -> None:
    with open(json_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    def walk(node: Any) -> Any:
        if isinstance(node, str) and source_prefix in node:
            return node.replace(source_prefix, target_prefix)
        if isinstance(node, dict):
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(item) for item in node]
        return node

    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(walk(payload), handle, ensure_ascii=False)


class JianyingDraftService(object):
    def __init__(self):
        self.draft_path_placeholder = getattr(settings, "JIANYING_DRAFT_PATH_PLACEHOLDER", "") or "C:/Users/YourName/Documents/JianyingPro/Drafts"
        self.mediainfo_bin = getattr(settings, "MEDIAINFO_BINARY", "") or "mediainfo"

    def is_available(self) -> bool:
        return _jianying_draft is not None

    def _check_binary(self, binary_name: str) -> bool:
        try:
            return bool(shutil.which(binary_name))
        except Exception:
            return False

    def has_mediainfo(self) -> bool:
        return self._check_binary(self.mediainfo_bin)

    def get_dependency_state(self) -> Dict[str, bool]:
        return {
            "py_jianying_draft": self.is_available(),
            "mediainfo": self.has_mediainfo(),
        }

    def _download_remote_file(self, url: str, target_dir: str, *, filename_hint: str = "") -> str:
        response = requests.get(str(url or "").strip(), stream=True, timeout=180)
        response.raise_for_status()
        content_type = str(response.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0].strip().lower()
        filename = filename_hint or _guess_remote_filename(url, content_type)
        target_path = Path(target_dir) / filename
        with open(str(target_path), "wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        return str(target_path)

    def _resolve_canvas_size(self, clips: List[Dict[str, Any]], preferred_aspect_ratio: str = "") -> Tuple[int, int]:
        ratio = str(preferred_aspect_ratio or "").strip()
        if ratio in CANVAS_SIZE_BY_RATIO:
            return CANVAS_SIZE_BY_RATIO[ratio]
        first_local_path = str((clips[0] if clips else {}).get("local_path") or "").strip()
        if first_local_path and VideoMaterial is not None:
            material = self._build_video_material(first_local_path, error_prefix="读取首个片段画幅失败")
            if getattr(material, "height", 0) > getattr(material, "width", 0):
                return CANVAS_SIZE_BY_RATIO["9:16"]
        return CANVAS_SIZE_BY_RATIO["16:9"]

    def _build_video_material(self, local_path: str, *, error_prefix: str) -> Any:
        try:
            return VideoMaterial(str(local_path))
        except Exception as exc:
            if not self.has_mediainfo():
                raise RuntimeError("服务器暂未安装 mediainfo，当前无法生成剪映草稿") from exc
            raise RuntimeError("{0}: {1}".format(error_prefix, str(exc) or "unknown mediainfo error")) from exc

    def _resolve_draft_json_path(self, draft_dir: Path, *, jianying_version: str) -> Path:
        prefer_v6 = str(jianying_version or "6").startswith("6")
        candidates = (
            [draft_dir / "draft_info.json", draft_dir / "draft_content.json"]
            if prefer_v6
            else [draft_dir / "draft_content.json", draft_dir / "draft_info.json"]
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        raise RuntimeError("剪映草稿文件生成失败，未找到 draft_info.json 或 draft_content.json")

    def _build_text_style(self, *, portrait: bool) -> Dict[str, Any]:
        if TextStyle is None:
            return {}
        return {
            "style": TextStyle(
                size=12.0 if portrait else 8.0,
                color=(1.0, 1.0, 1.0),
                align=1,
                bold=True,
                auto_wrapping=True,
                max_line_width=0.82 if portrait else 0.6,
            ),
            "border": TextBorder(color=(0.0, 0.0, 0.0), width=30.0) if TextBorder is not None else None,
            "shadow": TextShadow(
                color=(0.0, 0.0, 0.0),
                alpha=0.7,
                diffuse=8.0,
                distance=3.0,
                angle=-45.0,
            ) if TextShadow is not None else None,
            "settings": ClipSettings(transform_y=-0.75 if portrait else -0.8) if ClipSettings is not None else None,
        }

    def _append_optional_music_track(
        self,
        script_file: Any,
        *,
        music_local_path: str,
        total_duration_us: int,
        start_seconds: float = 0.0,
        duration_seconds: Optional[float] = None,
    ) -> None:
        if not music_local_path or not script_file or TrackType is None:
            return
        audio_track_type = getattr(TrackType, "audio", None)
        if audio_track_type is None:
            return
        audio_material_cls = getattr(_jianying_draft, "AudioMaterial", None)
        audio_segment_cls = getattr(_jianying_draft, "AudioSegment", None)
        if audio_material_cls is None or audio_segment_cls is None or trange is None:
            return
        script_file.add_track(audio_track_type, "背景音乐")
        start_us = max(int(float(start_seconds or 0.0) * 1000000), 0)
        if start_us >= total_duration_us:
            return
        segment_duration_us = total_duration_us - start_us
        if duration_seconds is not None and float(duration_seconds) > 0:
            segment_duration_us = min(segment_duration_us, int(float(duration_seconds) * 1000000))
        if segment_duration_us <= 0:
            return
        material = audio_material_cls(str(music_local_path))
        segment = audio_segment_cls(material, trange(start_us, segment_duration_us))
        script_file.add_segment(segment)

    def _try_add_transition(self, segment: Any, transition_key: str, duration_seconds: float) -> None:
        method = getattr(segment, "add_transition", None)
        if method is None:
            return
        transition_name = str(transition_key or "cut").strip().lower()
        if transition_name in {"", "cut"}:
            return
        duration_value = max(float(duration_seconds or 0.0), 0.1)
        for args, kwargs in [
            ((transition_name,), {"duration": duration_value}),
            ((transition_name, duration_value), {}),
        ]:
            try:
                method(*args, **kwargs)
                return
            except Exception:
                continue

    def _is_image_clip(self, clip: Dict[str, Any]) -> bool:
        source_kind = str(clip.get("source_kind") or "").strip().lower()
        if source_kind.endswith("_image"):
            return True
        return bool(clip.get("image_url") and not clip.get("video_url"))

    def export_timeline(
        self,
        *,
        clips: List[Dict[str, Any]],
        draft_name: str,
        draft_path: str,
        include_subtitles: bool = True,
        jianying_version: str = "6",
        preferred_aspect_ratio: str = "",
        music_audio_url: Optional[str] = None,
        music_start_seconds: float = 0.0,
        music_duration_seconds: Optional[float] = None,
        use_transitions: bool = True,
        transition_duration: float = 0.5,
    ) -> Dict[str, Any]:
        if _jianying_draft is None or VideoMaterial is None or VideoSegment is None or trange is None:
            raise RuntimeError("服务器暂未安装 pyJianYingDraft，当前无法导出剪映草稿")
        if not self.has_mediainfo():
            raise RuntimeError("服务器暂未安装 mediainfo，当前无法生成剪映草稿")

        enabled_clips = [
            dict(item)
            for item in clips
            if bool(item.get("enabled", True)) and str(item.get("video_url") or item.get("image_url") or "").strip()
        ]
        if not enabled_clips:
            raise RuntimeError("当前时间线没有可用于导出的片段")

        target_draft_path = str(draft_path or "").strip() or self.draft_path_placeholder
        temp_root = Path(tempfile.mkdtemp(prefix="shenlu_jianying_"))
        staging_dir = temp_root / "staging"
        draft_dir = temp_root / draft_name
        staging_dir.mkdir(parents=True)
        materialized_workspace_dir = ""

        try:
            local_clips = []
            has_image_clip = any(self._is_image_clip(clip) for clip in enabled_clips)
            if has_image_clip:
                dependency_state = video_compose_service.get_dependency_state()
                if not dependency_state.get("ffmpeg") or not dependency_state.get("ffprobe"):
                    raise RuntimeError("ffmpeg/ffprobe is required when exporting image-based Jianying drafts")
                materialized = video_compose_service.materialize_timeline_clips(
                    clips=enabled_clips,
                    preferred_aspect_ratio=preferred_aspect_ratio,
                    workspace_prefix="shenlu_jianying_materialize_",
                )
                materialized_workspace_dir = str(materialized.get("workspace_dir") or "")
                width = int(materialized.get("width") or 0)
                height = int(materialized.get("height") or 0)
                normalized_paths = materialized.get("normalized_paths") or []
                normalized_infos = materialized.get("normalized_infos") or []
                materialized_clips = materialized.get("clips") or []

                for index, clip in enumerate(materialized_clips):
                    staging_path = staging_dir / "segment_{0:03d}.mp4".format(index + 1)
                    shutil.copyfile(str(normalized_paths[index]), str(staging_path))
                    normalized_info = normalized_infos[index] if index < len(normalized_infos) else {}
                    segment_duration = float(
                        (normalized_info or {}).get("duration_seconds")
                        or clip.get("duration_seconds")
                        or clip.get("play_duration_seconds")
                        or DEFAULT_STILL_CLIP_DURATION
                    )
                    local_clips.append(
                        dict(
                            clip,
                            local_path=str(staging_path),
                            source_in_seconds=0.0,
                            source_out_seconds=segment_duration,
                            duration_seconds=segment_duration,
                        )
                    )
            else:
                for index, clip in enumerate(enabled_clips):
                    local_path = self._download_remote_file(
                        str(clip.get("video_url") or "").strip(),
                        str(staging_dir),
                        filename_hint="segment_{0:03d}.mp4".format(index + 1),
                    )
                    local_clips.append(dict(clip, local_path=local_path))

            music_local_path = ""
            if str(music_audio_url or "").strip():
                music_local_path = self._download_remote_file(
                    str(music_audio_url or "").strip(),
                    str(staging_dir),
                    filename_hint="music_{0}.mp3".format(draft_name[:8] or "bgm"),
                )

            if not has_image_clip:
                width, height = self._resolve_canvas_size(local_clips, preferred_aspect_ratio=preferred_aspect_ratio)
            folder = _jianying_draft.DraftFolder(str(draft_dir.parent))
            script_file = folder.create_draft(draft_name, width=width, height=height, allow_replace=True)
            script_file.add_track(TrackType.video)

            has_subtitles = bool(include_subtitles and TextSegment is not None and any(str(item.get("caption_text") or "").strip() for item in local_clips))
            text_assets = self._build_text_style(portrait=height > width)
            if has_subtitles:
                script_file.add_track(TrackType.text, "字幕")

            offset_us = 0
            for clip in local_clips:
                material = self._build_video_material(str(clip["local_path"]), error_prefix="读取片段时长失败")
                source_duration_us = int(getattr(material, "duration", 0) or 0)
                source_in_us = int(float(clip.get("source_in_seconds") or 0.0) * 1000000)
                source_out_seconds = clip.get("source_out_seconds")
                source_out_us = int(float(source_out_seconds) * 1000000) if source_out_seconds not in (None, "") else source_duration_us
                if source_duration_us > 0:
                    source_out_us = min(source_out_us, source_duration_us)
                if source_out_us <= source_in_us:
                    fallback_duration_us = int(float(clip.get("duration_seconds") or 5.0) * 1000000)
                    source_out_us = source_in_us + max(fallback_duration_us, 1)
                actual_duration_us = max(source_out_us - source_in_us, 1)
                video_segment = VideoSegment(
                    material,
                    target_timerange=trange(offset_us, actual_duration_us),
                    source_timerange=trange(source_in_us, actual_duration_us),
                )
                if use_transitions:
                    self._try_add_transition(
                        video_segment,
                        str(clip.get("transition_to_next") or "cut").strip().lower(),
                        min(float(transition_duration or 0.5), actual_duration_us / 1000000.0),
                    )
                script_file.add_segment(video_segment)

                caption_text = str(clip.get("caption_text") or "").strip()
                if has_subtitles and caption_text:
                    text_segment = TextSegment(
                        text=caption_text,
                        timerange=trange(offset_us, actual_duration_us),
                        style=text_assets.get("style"),
                        border=text_assets.get("border"),
                        shadow=text_assets.get("shadow"),
                        clip_settings=text_assets.get("settings"),
                    )
                    script_file.add_segment(text_segment)
                clip["duration_seconds"] = actual_duration_us / 1000000.0
                offset_us += actual_duration_us

            self._append_optional_music_track(
                script_file,
                music_local_path=music_local_path,
                total_duration_us=offset_us,
                start_seconds=music_start_seconds,
                duration_seconds=music_duration_seconds,
            )

            script_file.save()

            assets_dir = draft_dir / "assets"
            assets_dir.mkdir(exist_ok=True)
            for clip in local_clips:
                src = Path(str(clip["local_path"]))
                dst = assets_dir / src.name
                shutil.move(str(src), str(dst))
                clip["asset_path"] = str(dst)
            if music_local_path:
                music_src = Path(music_local_path)
                if music_src.exists():
                    shutil.move(str(music_src), str(assets_dir / music_src.name))

            draft_json_path = self._resolve_draft_json_path(draft_dir, jianying_version=jianying_version)
            target_prefix = "{0}/{1}/assets".format(target_draft_path.rstrip("/\\"), draft_name)
            _replace_paths_in_json(
                str(draft_json_path),
                _safe_realpath(str(staging_dir)),
                target_prefix.replace("\\", "/"),
            )

            if str(jianying_version or "6").startswith("6") and draft_json_path.name == "draft_content.json":
                draft_info_path = draft_dir / "draft_info.json"
                draft_json_path.rename(draft_info_path)
            elif not str(jianying_version or "6").startswith("6") and draft_json_path.name == "draft_info.json":
                draft_content_path = draft_dir / "draft_content.json"
                draft_json_path.rename(draft_content_path)

            zip_path = temp_root / "{0}.zip".format(draft_name)
            media_suffixes = {".mp4", ".webm", ".mov", ".avi", ".mkv", ".mp3", ".wav", ".m4a"}
            with zipfile.ZipFile(str(zip_path), "w") as archive:
                for file_path in draft_dir.rglob("*"):
                    if not file_path.is_file():
                        continue
                    arcname = "{0}/{1}".format(draft_name, str(file_path.relative_to(draft_dir)).replace("\\", "/"))
                    compression = zipfile.ZIP_STORED if file_path.suffix.lower() in media_suffixes else zipfile.ZIP_DEFLATED
                    archive.write(str(file_path), arcname=arcname, compress_type=compression)

            return {
                "local_path": str(zip_path),
                "workspace_dir": str(temp_root),
                "clip_count": len(local_clips),
                "draft_name": draft_name,
                "draft_path_hint": target_draft_path,
            }
        except Exception:
            logger.exception("剪映草稿导出失败: draft_name=%s draft_path=%s", draft_name, draft_path)
            shutil.rmtree(str(temp_root), ignore_errors=True)
            raise
        finally:
            if materialized_workspace_dir:
                video_compose_service.cleanup(materialized_workspace_dir)

    def cleanup(self, workspace_dir: str) -> None:
        if not workspace_dir:
            return
        shutil.rmtree(str(workspace_dir), ignore_errors=True)


jianying_draft_service = JianyingDraftService()
