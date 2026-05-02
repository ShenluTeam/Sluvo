from services.director_agent.tools.llm_agent_tool import LLMAgentTool


def _tool() -> LLMAgentTool:
    tool = LLMAgentTool()
    tool.api_key = ""
    return tool


def test_reason_plans_first_step_for_multi_stage_request():
    tool = _tool()
    result = tool.reason(
        "先拆镜再出图",
        {
            "stage": "script_ready",
            "episode": {"has_source_text": True, "title": "第一集"},
            "panels_summary": {"total": 0, "with_images": 0, "without_images": 0, "with_videos": 0, "without_videos": 0},
            "shared_resources": {"characters": [], "scenes": [], "props": []},
        },
        available_actions=[
            "analyze-story-context",
            "split-story-segments",
            "plan-storyboard",
            "generate-panel-image",
        ],
    )

    assert result["recommended_action"] == "split-story-segments"
    assert "plan-storyboard" in result["follow_up_actions"]
    assert result["response_mode"] == "plan"


def test_reason_repairs_video_request_when_images_missing():
    tool = _tool()
    result = tool.reason(
        "给这集做视频",
        {
            "stage": "storyboard_ready",
            "episode": {"has_source_text": True, "title": "第一集"},
            "panels_summary": {"total": 6, "with_images": 0, "without_images": 6, "with_videos": 0, "without_videos": 6},
            "shared_resources": {"characters": [], "scenes": [], "props": []},
        },
        available_actions=[
            "analyze-story-context",
            "plan-storyboard",
            "generate-panel-image",
            "generate-panel-video",
        ],
    )

    assert result["recommended_action"] == "generate-panel-image"
    assert "generate-panel-video" in result["follow_up_actions"]


def test_reason_clarifies_when_source_text_missing():
    tool = _tool()
    result = tool.reason(
        "帮我提取角色设定",
        {
            "stage": "project_empty",
            "episode": {"has_source_text": False, "title": "第一集"},
            "panels_summary": {"total": 0, "with_images": 0, "without_images": 0, "with_videos": 0, "without_videos": 0},
            "shared_resources": {"characters": [], "scenes": [], "props": []},
        },
        available_actions=[
            "analyze-story-context",
            "extract-project-assets",
        ],
    )

    assert result["response_mode"] == "clarify"
    assert "剧本原文" in "".join(result["context_missing"])
