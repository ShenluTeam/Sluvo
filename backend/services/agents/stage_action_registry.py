from __future__ import annotations

from typing import Any, Dict, List, Optional


def _action(action_type: str, label: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    item: Dict[str, Any] = {
        "type": str(action_type or "").strip(),
        "label": str(label or "").strip(),
    }
    if payload:
        item["payload"] = dict(payload)
    return item


STAGE_ACTION_PRIORITY: Dict[str, List[str]] = {
    "script_empty": ["save_script", "rewrite_script", "extract_assets"],
    "script_ready": ["save_script", "rewrite_script", "extract_assets"],
    "post_save_script": ["extract_assets", "rewrite_script"],
    "assets_pending": ["extract_assets"],
    "assets_ready": ["generate_asset_images", "extract_storyboard", "open_assets_upload", "open_assets_create"],
    "asset_images_pending": ["generate_asset_images", "extract_storyboard", "open_assets_upload", "open_assets_create"],
    "storyboard_pending": ["extract_storyboard"],
    "storyboard_ready": ["generate_storyboard_images", "open_storyboard", "rewrite_script"],
    "images_pending": ["generate_storyboard_images", "generate_video", "open_storyboard"],
    "images_ready": ["generate_video", "open_storyboard", "generate_storyboard_images"],
    "videos_pending": ["generate_video", "open_storyboard"],
    "videos_ready": ["open_storyboard", "generate_video"],
}


def script_empty_actions(script_draft: str) -> List[Dict[str, Any]]:
    return [
        _action("save_script", "保存剧本", {"script_draft": script_draft}),
        _action("rewrite_script", "继续完善现有剧本", {"script_draft": script_draft}),
        _action("extract_assets", "开始角色与场景设计"),
    ]


def script_ready_actions(script_draft: str) -> List[Dict[str, Any]]:
    return [
        _action("save_script", "保存剧本", {"script_draft": script_draft}),
        _action("rewrite_script", "继续完善现有剧本", {"script_draft": script_draft}),
        _action("extract_assets", "开始角色与场景设计"),
    ]


def post_save_script_actions(script_draft: str) -> List[Dict[str, Any]]:
    return [
        _action("extract_assets", "开始角色与场景设计"),
        _action("rewrite_script", "继续完善现有剧本", {"script_draft": script_draft}),
    ]


def assets_missing_actions() -> List[Dict[str, Any]]:
    return [
        _action("extract_assets", "提取资产"),
    ]


def asset_reference_generation_actions() -> List[Dict[str, Any]]:
    return [
        _action("generate_asset_images", "一键生成全部资产参考图", {"generation_scope": "all"}),
        _action("generate_asset_images", "仅生成人物参考图", {"generation_scope": "character"}),
        _action("generate_asset_images", "仅生成场景参考图", {"generation_scope": "scene"}),
        _action("generate_asset_images", "仅生成道具参考图", {"generation_scope": "prop"}),
        _action("extract_storyboard", "先规划分镜"),
        _action("open_assets_upload", "我自己上传资产参考图"),
        _action("open_assets_create", "我自己添加资产"),
    ]


def assets_ready_actions() -> List[Dict[str, Any]]:
    return asset_reference_generation_actions()


def asset_reference_followup_actions(completed_scope: Optional[str] = None) -> List[Dict[str, Any]]:
    normalized_scope = str(completed_scope or "").strip().lower()
    actions = asset_reference_generation_actions()
    if normalized_scope not in {"all", "character", "scene", "prop"}:
        return actions
    filtered: List[Dict[str, Any]] = []
    for item in actions:
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        scope = str(payload.get("generation_scope") or "").strip().lower()
        if item.get("type") == "generate_asset_images" and scope == normalized_scope:
            continue
        if normalized_scope == "all" and item.get("type") == "generate_asset_images":
            continue
        filtered.append(item)
    return filtered


def storyboard_pending_actions() -> List[Dict[str, Any]]:
    return [
        _action("extract_storyboard", "先规划分镜"),
    ]


def storyboard_image_generation_actions(pending_sequences: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    normalized_sequences: List[int] = []
    for item in pending_sequences or []:
        try:
            value = int(item)
        except Exception:
            continue
        if value > 0 and value not in normalized_sequences:
            normalized_sequences.append(value)

    if not normalized_sequences:
        return [
            _action("generate_storyboard_images", "一键生成全部分镜图"),
        ]

    actions: List[Dict[str, Any]] = [
        _action(
            "generate_storyboard_images",
            "一键生成全部分镜图",
            {"selected_panel_sequences": normalized_sequences},
        )
    ]
    if len(normalized_sequences) >= 2:
        preview_sequences = normalized_sequences[:3]
        start = preview_sequences[0]
        end = preview_sequences[-1]
        preview_label = (
            f"先生成第{start}-{end}分镜图"
            if len(preview_sequences) > 1
            else f"先生成第{start}镜分镜图"
        )
        actions.append(
            _action(
                "generate_storyboard_images",
                preview_label,
                {"selected_panel_sequences": preview_sequences},
            )
        )
    first_sequence = normalized_sequences[0]
    actions.append(
        _action(
            "generate_storyboard_images",
            f"先生成第{first_sequence}镜分镜图",
            {"panel_sequence": first_sequence},
        )
    )
    return actions


def storyboard_ready_actions(pending_sequences: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    return [
        *storyboard_image_generation_actions(pending_sequences),
        _action("open_storyboard", "打开分镜表"),
        _action("rewrite_script", "按我的需求继续调整分镜"),
    ]


def images_pending_actions(pending_sequences: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    return [
        *storyboard_image_generation_actions(pending_sequences),
        _action("generate_video", "生成视频"),
        _action("open_storyboard", "打开分镜表"),
    ]


def images_ready_actions(pending_sequences: Optional[List[int]] = None) -> List[Dict[str, Any]]:
    return [
        _action("generate_video", "生成视频"),
        _action("open_storyboard", "打开分镜表"),
        *storyboard_image_generation_actions(pending_sequences),
    ]


def videos_pending_actions() -> List[Dict[str, Any]]:
    return [
        _action("generate_video", "生成视频"),
        _action("open_storyboard", "打开分镜表"),
    ]


def videos_ready_actions() -> List[Dict[str, Any]]:
    return [
        _action("open_storyboard", "打开分镜表"),
        _action("generate_video", "继续生成视频"),
    ]
