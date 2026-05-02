"""Orchestrator 数据结构"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ProjectStage(str, Enum):
    """项目阶段枚举"""
    PROJECT_EMPTY = "project_empty"       # 无剧本
    SCRIPT_READY = "script_ready"         # 有剧本，无 segments
    SEGMENTS_READY = "segments_ready"     # 有 segments
    STORYBOARD_READY = "storyboard_ready" # 有 panel_drafts
    HAS_IMAGES = "has_images"             # 部分/全部面板有图片
    HAS_VIDEOS = "has_videos"             # 部分/全部面板有视频
    AUDIO_READY = "audio_ready"           # 有配音
    REVIEW = "review"                     # 审核中
    FINALIZE = "finalize"                 # 终稿


@dataclass
class ScriptInfo:
    """剧本信息"""
    id: int
    name: str
    aspect_ratio: str
    style_preset: str
    has_source_text: bool


@dataclass
class EpisodeInfo:
    """剧集信息"""
    id: int
    title: str
    sequence_num: int
    has_source_text: bool
    source_text: Optional[str] = None  # 完整剧本原文
    source_text_preview: Optional[str] = None


@dataclass
class PanelInfo:
    """分镜信息"""
    id: int
    panel_no: int
    segment_summary: Optional[str]
    panel_type: str  # normal / nine_grid
    has_image: bool
    has_video: bool
    image_url: Optional[str] = None


@dataclass
class PanelsSummary:
    """分镜统计"""
    total: int
    with_images: int
    without_images: int
    with_videos: int
    without_videos: int
    nine_grid_count: int
    normal_count: int


@dataclass
class SharedResource:
    """共享资源"""
    id: int
    name: str
    resource_type: str  # character / scene / prop
    has_image: bool


@dataclass
class SharedResources:
    """共享资源汇总"""
    characters: List[SharedResource]
    scenes: List[SharedResource]
    props: List[SharedResource]


@dataclass
class GenerationRecord:
    """生成记录"""
    id: int
    record_type: str  # image / video / audio
    panel_id: Optional[int]
    status: str  # pending / completed / failed
    created_at: str


@dataclass
class ProjectContext:
    """项目上下文"""
    script_id: int
    episode_id: Optional[int]
    script: Optional[ScriptInfo]
    episode: Optional[EpisodeInfo]
    panels: List[PanelInfo]
    panels_summary: PanelsSummary
    shared_resources: SharedResources
    generation_records: List[GenerationRecord]
    stage: ProjectStage = ProjectStage.PROJECT_EMPTY
    missing_context: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "script_id": self.script_id,
            "episode_id": self.episode_id,
            "script": self.script.__dict__ if self.script else None,
            "episode": self.episode.__dict__ if self.episode else None,
            "panels": [p.__dict__ for p in self.panels],
            "panels_summary": self.panels_summary.__dict__,
            "shared_resources": {
                "characters": [c.__dict__ for c in self.shared_resources.characters],
                "scenes": [s.__dict__ for s in self.shared_resources.scenes],
                "props": [p.__dict__ for p in self.shared_resources.props],
            },
            "generation_records": [r.__dict__ for r in self.generation_records],
            "stage": self.stage.value,
            "missing_context": self.missing_context,
        }
