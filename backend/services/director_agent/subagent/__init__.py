"""子代理层"""
from .base import Subagent, SubagentResult, WriteOperation
from .analyze_story_context import AnalyzeStoryContextSubagent
from .split_story_segments import SplitStorySegmentsSubagent
from .plan_storyboard import PlanStoryboardSubagent
from .extract_project_assets import ExtractProjectAssetsSubagent
from .generate_panel_image import GeneratePanelImageSubagent
from .generate_panel_video import GeneratePanelVideoSubagent
from .generate_episode_dubbing import GenerateEpisodeDubbingSubagent

# Subagent 注册表（使用实例）
SUBAGENT_REGISTRY = {
    "analyze-story-context": AnalyzeStoryContextSubagent(),
    "split-story-segments": SplitStorySegmentsSubagent(),
    "plan-storyboard": PlanStoryboardSubagent(),
    "extract-project-assets": ExtractProjectAssetsSubagent(),
    "generate-panel-image": GeneratePanelImageSubagent(),
    "generate-panel-video": GeneratePanelVideoSubagent(),
    "generate-episode-dubbing": GenerateEpisodeDubbingSubagent(),
}
