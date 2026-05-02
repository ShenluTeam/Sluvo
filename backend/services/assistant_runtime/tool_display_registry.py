from __future__ import annotations

from typing import Any, Dict, List, Optional


TOOL_DISPLAY_REGISTRY: Dict[str, Dict[str, Any]] = {
    "read_project_context": {
        "title_cn": "读取项目资料",
        "purpose_cn": "确认当前项目已有剧本、资产、分镜和生成结果，避免重复生成。",
        "risk_level": "low",
        "requires_confirmation": False,
    },
    "save_script": {
        "title_cn": "保存剧本",
        "purpose_cn": "把当前剧本或原文草稿写回项目工作区。",
        "risk_level": "medium",
        "requires_confirmation": True,
    },
    "rewrite_script": {
        "title_cn": "改写剧本",
        "purpose_cn": "继续完善、润色或重写当前剧本内容。",
        "risk_level": "medium",
        "requires_confirmation": False,
    },
    "extract_assets": {
        "title_cn": "提取资产",
        "purpose_cn": "识别剧本中的角色、场景和道具，为后续分镜与生成做准备。",
        "risk_level": "medium",
        "requires_confirmation": True,
    },
    "save_assets": {
        "title_cn": "保存资产方案",
        "purpose_cn": "把当前整理好的资产结果写回项目资产库。",
        "risk_level": "medium",
        "requires_confirmation": True,
    },
    "extract_storyboard": {
        "title_cn": "规划分镜",
        "purpose_cn": "基于当前剧本和资产实时拆分分镜，并持续写回工作区。",
        "risk_level": "medium",
        "requires_confirmation": False,
    },
    "save_storyboard": {
        "title_cn": "保存分镜方案",
        "purpose_cn": "把当前分镜草稿写回工作区，作为后续出图和视频的基础。",
        "risk_level": "medium",
        "requires_confirmation": True,
    },
    "generate_asset_images": {
        "title_cn": "创建资产参考图任务",
        "purpose_cn": "为人物、场景或道具生成参考图结果，并回写到项目里。",
        "risk_level": "high",
        "requires_confirmation": True,
    },
    "generate_storyboard_images": {
        "title_cn": "创建分镜出图任务",
        "purpose_cn": "为当前分镜生成图片结果，并回写到项目里。",
        "risk_level": "high",
        "requires_confirmation": True,
    },
    "generate_video": {
        "title_cn": "创建视频生成任务",
        "purpose_cn": "为当前分镜生成视频结果，并回写到项目里。",
        "risk_level": "high",
        "requires_confirmation": True,
    },
    "rewrite_generation_prompts": {
        "title_cn": "改写生成提示词",
        "purpose_cn": "按用户要求改写当前分镜的图片或视频提示词，并先给出可确认预览。",
        "risk_level": "medium",
        "requires_confirmation": True,
    },
    "generate_audio": {
        "title_cn": "创建音频生成任务",
        "purpose_cn": "为当前剧集生成配音、旁白或音频内容。",
        "risk_level": "high",
        "requires_confirmation": True,
    },
    "generate_panel_image": {
        "title_cn": "创建分镜出图任务",
        "purpose_cn": "为当前分镜生成图片结果，并回写到项目里。",
        "risk_level": "high",
        "requires_confirmation": True,
    },
    "generate_panel_video": {
        "title_cn": "创建视频生成任务",
        "purpose_cn": "为当前分镜生成视频结果，并回写到项目里。",
        "risk_level": "high",
        "requires_confirmation": True,
    },
    "generate_episode_dubbing": {
        "title_cn": "创建音频生成任务",
        "purpose_cn": "为当前剧集生成配音、旁白或音频内容。",
        "risk_level": "high",
        "requires_confirmation": True,
    },
    "delegate_to_external_agent": {
        "title_cn": "站外协作",
        "purpose_cn": "把当前项目资料同步给已绑定的站外 Agent 协同处理。",
        "risk_level": "medium",
        "requires_confirmation": False,
    },
}


def get_tool_display(tool_key: Optional[str], *, fallback_label: str = "") -> Dict[str, Any]:
    key = str(tool_key or "").strip()
    payload = dict(TOOL_DISPLAY_REGISTRY.get(key) or {})
    if not payload:
        display = str(fallback_label or key or "执行动作").strip() or "执行动作"
        payload = {
            "title_cn": display,
            "purpose_cn": "继续处理当前创作任务。",
            "risk_level": "low",
            "requires_confirmation": False,
        }
    return payload


def build_tool_card(
    tool_key: Optional[str],
    *,
    status: str,
    summary: str = "",
    fallback_label: str = "",
    actions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    display = get_tool_display(tool_key, fallback_label=fallback_label)
    return {
        "type": "tool_card",
        "tool_key": str(tool_key or "").strip() or "tool",
        "title_cn": display["title_cn"],
        "purpose_cn": display["purpose_cn"],
        "risk_level": display.get("risk_level") or "low",
        "requires_confirmation": bool(display.get("requires_confirmation")),
        "status": status,
        "summary": str(summary or "").strip(),
        "actions": actions or [],
    }
