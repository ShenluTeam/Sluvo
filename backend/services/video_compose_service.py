import json
import mimetypes
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from core.config import settings

CANVAS_SIZE_BY_RATIO = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "4:3": (1440, 1080),
}

TRANSITION_FILTERS = {
    "cut": "fade",
    "fade": "fade",
    "dissolve": "dissolve",
    "wipe": "wipeleft",
}

DEFAULT_STILL_CLIP_DURATION = 5.0


def _format_number(value: float, *, digits: int = 3) -> str:
    text = ("{0:." + str(digits) + "f}").format(float(value or 0.0))
    return text.rstrip("0").rstrip(".") or "0"


def _guess_remote_filename(url: str, content_type: str, fallback_ext: str = ".mp4") -> str:
    basename = Path(str(url or "").split("?", 1)[0]).name
    if basename and "." in basename:
        return basename
    guessed = mimetypes.guess_extension(content_type or "") or fallback_ext
    return "editing_{0}{1}".format(uuid.uuid4().hex, guessed)


class VideoComposeService(object):
    def __init__(self):
        self.ffmpeg_bin = getattr(settings, "FFMPEG_BINARY", "") or "ffmpeg"
        self.ffprobe_bin = getattr(settings, "FFPROBE_BINARY", "") or "ffprobe"

    def _run_command(self, command: List[str], *, error_prefix: str) -> subprocess.CompletedProcess:
        completed = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )
        if completed.returncode != 0:
            error_text = (completed.stderr or completed.stdout or "").strip()
            if len(error_text) > 800:
                error_text = error_text[-800:]
            raise RuntimeError("{0}: {1}".format(error_prefix, error_text or "unknown ffmpeg error"))
        return completed

    def _check_binary(self, binary_name: str) -> bool:
        try:
            completed = subprocess.run(
                [binary_name, "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )
        except Exception:
            return False
        return completed.returncode == 0

    def get_dependency_state(self) -> Dict[str, bool]:
        return {
            "ffmpeg": self._check_binary(self.ffmpeg_bin),
            "ffprobe": self._check_binary(self.ffprobe_bin),
        }

    def probe_local_media(self, media_path: str) -> Dict[str, Any]:
        command = [
            self.ffprobe_bin,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            "-show_format",
            str(media_path),
        ]
        completed = self._run_command(command, error_prefix="媒体探测失败")
        payload = json.loads(completed.stdout or "{}")
        streams = payload.get("streams") or []
        format_info = payload.get("format") or {}
        duration = float(format_info.get("duration") or 0.0)
        width = None
        height = None
        has_audio = False
        for stream in streams:
            if stream.get("codec_type") == "video" and width is None:
                width = int(stream.get("width") or 0) or None
                height = int(stream.get("height") or 0) or None
            if stream.get("codec_type") == "audio":
                has_audio = True
        return {
            "duration_seconds": duration,
            "width": width,
            "height": height,
            "has_audio": has_audio,
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

    def _resolve_canvas_size(self, clip_infos: List[Dict[str, Any]], preferred_aspect_ratio: str = "") -> Tuple[int, int]:
        ratio = str(preferred_aspect_ratio or "").strip()
        if ratio in CANVAS_SIZE_BY_RATIO:
            return CANVAS_SIZE_BY_RATIO[ratio]
        first_clip = clip_infos[0] if clip_infos else {}
        width = int(first_clip.get("width") or 0)
        height = int(first_clip.get("height") or 0)
        if width and height and height > width:
            return CANVAS_SIZE_BY_RATIO["9:16"]
        return CANVAS_SIZE_BY_RATIO["16:9"]

    def _resolve_clip_source_url(self, clip: Dict[str, Any]) -> str:
        return str(clip.get("video_url") or clip.get("image_url") or "").strip()

    def _is_image_clip(self, clip: Dict[str, Any]) -> bool:
        source_kind = str(clip.get("source_kind") or "").strip().lower()
        if source_kind.endswith("_image"):
            return True
        return bool(clip.get("image_url") and not clip.get("video_url"))

    def _probe_local_media_safe(self, media_path: str) -> Dict[str, Any]:
        try:
            return self.probe_local_media(media_path)
        except Exception:
            return {}

    def _normalize_clip(
        self,
        source_path: str,
        output_path: str,
        *,
        width: int,
        height: int,
        has_audio: bool,
        trim_in_seconds: float = 0.0,
        trim_out_seconds: Optional[float] = None,
        fps: int = 30,
    ) -> None:
        scale_filter = (
            "scale={0}:{1}:force_original_aspect_ratio=decrease,"
            "pad={0}:{1}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "fps={2},format=yuv420p"
        ).format(width, height, fps)
        segment_duration = None
        if trim_out_seconds is not None and trim_out_seconds > trim_in_seconds:
            segment_duration = trim_out_seconds - trim_in_seconds

        trim_args: List[str] = []
        if trim_in_seconds > 0:
            trim_args.extend(["-ss", _format_number(trim_in_seconds)])
        if segment_duration and segment_duration > 0:
            trim_args.extend(["-t", _format_number(segment_duration)])

        if has_audio:
            command = [
                self.ffmpeg_bin,
                "-y",
                *trim_args,
                "-i",
                str(source_path),
                "-vf",
                scale_filter,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        else:
            command = [
                self.ffmpeg_bin,
                "-y",
                *trim_args,
                "-i",
                str(source_path),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
                "-shortest",
                "-vf",
                scale_filter,
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(fps),
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        self._run_command(command, error_prefix="片段归一化失败")

    def _normalize_image_clip(
        self,
        source_path: str,
        output_path: str,
        *,
        width: int,
        height: int,
        duration_seconds: float,
        fps: int = 30,
    ) -> None:
        scale_filter = (
            "scale={0}:{1}:force_original_aspect_ratio=decrease,"
            "pad={0}:{1}:(ow-iw)/2:(oh-ih)/2:color=black,"
            "fps={2},format=yuv420p"
        ).format(width, height, fps)
        command = [
            self.ffmpeg_bin,
            "-y",
            "-loop",
            "1",
            "-i",
            str(source_path),
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t",
            _format_number(max(float(duration_seconds or DEFAULT_STILL_CLIP_DURATION), 0.1)),
            "-shortest",
            "-vf",
            scale_filter,
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(fps),
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        self._run_command(command, error_prefix="静态素材归一化失败")

    def _concat_simple(self, clip_paths: List[str], output_path: str) -> None:
        command = [self.ffmpeg_bin, "-y"]
        for clip_path in clip_paths:
            command.extend(["-i", str(clip_path)])
        concat_inputs = "".join("[{0}:v][{0}:a]".format(index) for index in range(len(clip_paths)))
        filter_complex = "{0}concat=n={1}:v=1:a=1[vout][aout]".format(concat_inputs, len(clip_paths))
        command.extend(
            [
                "-filter_complex",
                filter_complex,
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        self._run_command(command, error_prefix="视频拼接失败")

    def _concat_with_transitions(
        self,
        clip_paths: List[str],
        clip_infos: List[Dict[str, Any]],
        transitions: List[str],
        output_path: str,
        *,
        transition_duration: float,
    ) -> None:
        command = [self.ffmpeg_bin, "-y"]
        for clip_path in clip_paths:
            command.extend(["-i", str(clip_path)])

        filter_parts = []
        for index in range(len(clip_paths)):
            filter_parts.append("[{0}:v]settb=AVTB,setpts=PTS-STARTPTS[v{0}]".format(index))
            filter_parts.append("[{0}:a]aresample=48000,asetpts=PTS-STARTPTS[a{0}]".format(index))

        current_video = "v0"
        current_audio = "a0"
        current_duration = float(clip_infos[0].get("duration_seconds") or 0.0)

        for index in range(1, len(clip_paths)):
            transition_key = str(transitions[index - 1] or "cut").strip().lower()
            transition_name = TRANSITION_FILTERS.get(transition_key, "fade")
            next_duration = float(clip_infos[index].get("duration_seconds") or 0.0)
            max_overlap = min(current_duration, next_duration)
            effective_duration = 0.01 if transition_key == "cut" else min(max(float(transition_duration or 0.5), 0.1), max_overlap)
            offset = max(0.0, current_duration - effective_duration)
            next_video = "vx{0}".format(index)
            next_audio = "ax{0}".format(index)

            filter_parts.append(
                "[{0}][v{1}]xfade=transition={2}:duration={3}:offset={4}[{5}]".format(
                    current_video,
                    index,
                    transition_name,
                    _format_number(effective_duration),
                    _format_number(offset),
                    next_video,
                )
            )
            filter_parts.append(
                "[{0}][a{1}]acrossfade=d={2}:c1=tri:c2=tri[{3}]".format(
                    current_audio,
                    index,
                    _format_number(effective_duration),
                    next_audio,
                )
            )
            current_video = next_video
            current_audio = next_audio
            current_duration = offset + next_duration

        command.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[{0}]".format(current_video),
                "-map",
                "[{0}]".format(current_audio),
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        self._run_command(command, error_prefix="转场拼接失败")

    def _mix_background_music(
        self,
        video_path: str,
        music_path: str,
        output_path: str,
        *,
        music_volume: float,
        music_start_seconds: float = 0.0,
        music_duration_seconds: Optional[float] = None,
    ) -> None:
        delay_ms = max(int(float(music_start_seconds or 0.0) * 1000), 0)
        bgm_filters = []
        if music_duration_seconds is not None and float(music_duration_seconds) > 0:
            bgm_filters.append("atrim=start=0:end={0}".format(_format_number(float(music_duration_seconds))))
            bgm_filters.append("asetpts=N/SR/TB")
        if delay_ms > 0:
            bgm_filters.append("adelay={0}|{0}".format(delay_ms))
        bgm_filters.append("volume={0}".format(_format_number(max(min(float(music_volume or 0.3), 1.0), 0.0))))
        filter_chain = ",".join(bgm_filters)
        command = [
            self.ffmpeg_bin,
            "-y",
            "-i",
            str(video_path),
            "-stream_loop",
            "-1",
            "-i",
            str(music_path),
            "-filter_complex",
            "[1:a]{0}[bgm];[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]".format(filter_chain),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        self._run_command(command, error_prefix="背景音乐混音失败")

    def materialize_timeline_clips(
        self,
        *,
        clips: List[Dict[str, Any]],
        preferred_aspect_ratio: str = "",
        workspace_prefix: str = "shenlu_editing_compose_",
    ) -> Dict[str, Any]:
        dependency_state = self.get_dependency_state()
        if not dependency_state.get("ffmpeg"):
            raise RuntimeError("服务器暂未安装 ffmpeg，当前无法执行素材归一化")
        if not dependency_state.get("ffprobe"):
            raise RuntimeError("服务器暂未安装 ffprobe，当前无法读取片段媒体信息")

        enabled_clips = [
            dict(item)
            for item in clips
            if bool(item.get("enabled", True)) and self._resolve_clip_source_url(item)
        ]
        if not enabled_clips:
            raise RuntimeError("当前时间线没有可用于合成的素材")

        temp_root = Path(tempfile.mkdtemp(prefix=workspace_prefix))
        staging_dir = temp_root / "staging"
        normalized_dir = temp_root / "normalized"
        output_dir = temp_root / "output"
        staging_dir.mkdir(parents=True)
        normalized_dir.mkdir(parents=True)
        output_dir.mkdir(parents=True)

        try:
            source_infos = []
            for index, clip in enumerate(enabled_clips):
                is_image_clip = self._is_image_clip(clip)
                filename_hint = "clip_{0:03d}{1}".format(index + 1, ".png" if is_image_clip else ".mp4")
                local_source = self._download_remote_file(
                    self._resolve_clip_source_url(clip),
                    str(staging_dir),
                    filename_hint=filename_hint,
                )
                media_info = self._probe_local_media_safe(local_source) if is_image_clip else self.probe_local_media(local_source)
                source_duration = float(media_info.get("duration_seconds") or 0.0)
                trim_in_seconds = max(float(clip.get("source_in_seconds") or 0.0), 0.0)
                trim_out_seconds = clip.get("source_out_seconds")
                trim_out_seconds = float(trim_out_seconds) if trim_out_seconds not in (None, "") else None

                if is_image_clip:
                    render_duration_seconds = max(
                        float(clip.get("duration_seconds") or clip.get("play_duration_seconds") or 0.0) or DEFAULT_STILL_CLIP_DURATION,
                        0.1,
                    )
                    clip["duration_seconds"] = render_duration_seconds
                    source_infos.append(
                        {
                            **media_info,
                            "local_source": local_source,
                            "media_type": "image",
                            "has_audio": False,
                            "render_duration_seconds": render_duration_seconds,
                            "trim_in_seconds": 0.0,
                            "trim_out_seconds": None,
                        }
                    )
                    continue

                if trim_out_seconds is None or trim_out_seconds <= 0 or trim_out_seconds > source_duration:
                    trim_out_seconds = source_duration or None
                if trim_out_seconds is not None and trim_out_seconds <= trim_in_seconds:
                    trim_out_seconds = min(source_duration, trim_in_seconds + max(float(clip.get("duration_seconds") or 0.1), 0.1))

                clip["duration_seconds"] = float(
                    clip.get("duration_seconds")
                    or ((trim_out_seconds - trim_in_seconds) if trim_out_seconds is not None else max(source_duration - trim_in_seconds, 0.0))
                    or source_duration
                    or 0.0
                )
                source_infos.append(
                    {
                        **media_info,
                        "local_source": local_source,
                        "media_type": "video",
                        "trim_in_seconds": trim_in_seconds,
                        "trim_out_seconds": trim_out_seconds,
                    }
                )

            width, height = self._resolve_canvas_size(source_infos, preferred_aspect_ratio=preferred_aspect_ratio)

            normalized_paths = []
            normalized_infos = []
            for index, source_info in enumerate(source_infos):
                normalized_path = normalized_dir / "clip_{0:03d}.mp4".format(index + 1)
                if source_info.get("media_type") == "image":
                    self._normalize_image_clip(
                        str(source_info["local_source"]),
                        str(normalized_path),
                        width=width,
                        height=height,
                        duration_seconds=float(source_info.get("render_duration_seconds") or DEFAULT_STILL_CLIP_DURATION),
                    )
                else:
                    self._normalize_clip(
                        str(source_info["local_source"]),
                        str(normalized_path),
                        width=width,
                        height=height,
                        has_audio=bool(source_info.get("has_audio")),
                        trim_in_seconds=float(source_info.get("trim_in_seconds") or 0.0),
                        trim_out_seconds=source_info.get("trim_out_seconds"),
                    )
                normalized_paths.append(str(normalized_path))
                normalized_infos.append(self.probe_local_media(str(normalized_path)))

            return {
                "workspace_dir": str(temp_root),
                "staging_dir": str(staging_dir),
                "normalized_dir": str(normalized_dir),
                "output_dir": str(output_dir),
                "clips": enabled_clips,
                "normalized_paths": normalized_paths,
                "normalized_infos": normalized_infos,
                "width": width,
                "height": height,
            }
        except Exception:
            shutil.rmtree(str(temp_root), ignore_errors=True)
            raise

    def compose(
        self,
        *,
        clips: List[Dict[str, Any]],
        music_audio_url: Optional[str] = None,
        music_volume: float = 0.3,
        music_start_seconds: float = 0.0,
        music_duration_seconds: Optional[float] = None,
        use_transitions: bool = True,
        transition_duration: float = 0.5,
        preferred_aspect_ratio: str = "",
        output_basename: str = "",
    ) -> Dict[str, Any]:
        workspace_dir = ""
        try:
            materialized = self.materialize_timeline_clips(
                clips=clips,
                preferred_aspect_ratio=preferred_aspect_ratio,
                workspace_prefix="shenlu_editing_compose_",
            )
            workspace_dir = str(materialized.get("workspace_dir") or "")
            enabled_clips = materialized.get("clips") or []
            normalized_paths = materialized.get("normalized_paths") or []
            normalized_infos = materialized.get("normalized_infos") or []
            staging_dir = Path(materialized["staging_dir"])
            output_dir = Path(materialized["output_dir"])
            width = int(materialized.get("width") or 0)
            height = int(materialized.get("height") or 0)

            raw_output_path = output_dir / "{0}_raw.mp4".format(output_basename or uuid.uuid4().hex)
            transition_values = [
                str(clip.get("transition_to_next") or "cut").strip().lower()
                for clip in enabled_clips[:-1]
            ]
            has_visual_transition = bool(
                use_transitions and any(value not in {"", "cut"} for value in transition_values)
            )

            if len(normalized_paths) == 1:
                shutil.copyfile(normalized_paths[0], str(raw_output_path))
            elif has_visual_transition:
                self._concat_with_transitions(
                    normalized_paths,
                    normalized_infos,
                    transition_values,
                    str(raw_output_path),
                    transition_duration=transition_duration,
                )
            else:
                self._concat_simple(normalized_paths, str(raw_output_path))

            final_output_path = output_dir / "{0}.mp4".format(output_basename or uuid.uuid4().hex)
            if str(music_audio_url or "").strip():
                music_local_path = self._download_remote_file(
                    str(music_audio_url or "").strip(),
                    str(staging_dir),
                    filename_hint="music_{0}.mp3".format(uuid.uuid4().hex[:8]),
                )
                self._mix_background_music(
                    str(raw_output_path),
                    music_local_path,
                    str(final_output_path),
                    music_volume=music_volume,
                    music_start_seconds=music_start_seconds,
                    music_duration_seconds=music_duration_seconds,
                )
            else:
                shutil.copyfile(str(raw_output_path), str(final_output_path))

            final_info = self.probe_local_media(str(final_output_path))
            return {
                "local_path": str(final_output_path),
                "duration_seconds": float(final_info.get("duration_seconds") or 0.0),
                "width": width,
                "height": height,
                "clip_count": len(enabled_clips),
                "workspace_dir": workspace_dir,
            }
        except Exception:
            self.cleanup(workspace_dir)
            raise

    def cleanup(self, workspace_dir: str) -> None:
        if not workspace_dir:
            return
        shutil.rmtree(str(workspace_dir), ignore_errors=True)


video_compose_service = VideoComposeService()
