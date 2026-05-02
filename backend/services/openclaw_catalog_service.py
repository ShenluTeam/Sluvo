from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from core.config import settings


INVOKE_MODE_LABELS = {
    "direct_api": "direct_api",
    "agent_chat": "agent_chat",
    "agent_local": "agent_local",
    "not_public_yet": "not_public_yet",
    "skill_rule": "skill_rule",
}

CONFIGURE_SHENLU_SKILL_PROMPT = "帮我自动配置 Shenlu skill: {skill_url} ，然后根据 skill，协助我进行创作。"


def _base_url(base_url: Optional[str] = None) -> str:
    request_root = str(base_url or "").strip().rstrip("/")
    request_host = (urlparse(request_root).hostname or "").strip().lower()
    if request_host in {"localhost", "127.0.0.1", "0.0.0.0"}:
        return request_root or "http://localhost:8000"
    public_root = str(settings.OPENCLAW_PUBLIC_BASE_URL or "").strip().rstrip("/")
    if public_root:
        return public_root
    resolved = str(request_root or settings.SHENLU_AGENT_API_BASE_URL or "").strip().rstrip("/")
    return resolved or "http://localhost:8000"


def _api_base_url() -> str:
    return str(settings.OPENCLAW_API_BASE_URL or "https://api.shenlu.top").strip().rstrip("/")


def _build_agent_profiles(skill_url: str, help_url: str) -> List[Dict[str, Any]]:
    return [
        {
            "key": "openclaw",
            "label": "OpenClaw",
            "title": "OpenClaw 远程协作",
            "description": "适合把 Shenlu 当成外部创作执行面板，直接读取 skill、按步骤调接口，并在需要时把复杂创作动作交给 agent/chat。",
            "best_for": "远程多智能体协作、长期项目推进、需要稳定 API 编排",
            "setup_prompt": CONFIGURE_SHENLU_SKILL_PROMPT.format(skill_url=skill_url),
            "update_prompt": (
                f"请重新读取最新的 shenlu skill：{skill_url}，"
                "并用最新的 capability catalog 与帮助页说明继续协助我。"
            ),
            "recommended_flow": [
                "读取 /skill.md 或 /api/openclaw/capabilities",
                "先做 API Key 与 quota 预检",
                "先读项目事实，再调用生成或 agent/chat",
                "所有高成本动作先估价再执行",
            ],
            "help_url": help_url,
        },
        {
            "key": "hermes",
            "label": "Hermes",
            "title": "Hermes 任务编排模式",
            "description": "适合先让 Hermes 做任务拆解和本地推理，再由它调用 Shenlu 公开 API 或 agent/chat 推动项目。",
            "best_for": "任务拆解、长链路编排、把本地推理与云端创作分层",
            "setup_prompt": CONFIGURE_SHENLU_SKILL_PROMPT.format(skill_url=skill_url),
            "update_prompt": (
                f"请更新你对 shenlu skill 的理解，重新读取：{skill_url}，"
                "并按最新说明继续协助我。"
            ),
            "recommended_flow": [
                "本地拆解需求与改写剧本",
                "调用 Shenlu API 落库项目与分集",
                "把复杂平台内动作交给 agent/chat",
                "将 preview_url 下载回本地 workspace",
            ],
            "help_url": help_url,
        },
        {
            "key": "claude_code",
            "label": "Claude Code",
            "title": "Claude Code 本地工作流",
            "description": "适合在本地 workspace 中边整理素材边调用 Shenlu 平台能力，把外部 agent 的文本能力与 Shenlu 的创作能力组合起来。",
            "best_for": "本地 workspace 驱动、下载结果落盘、把平台结果回写到本地项目",
            "setup_prompt": CONFIGURE_SHENLU_SKILL_PROMPT.format(skill_url=skill_url),
            "update_prompt": (
                f"请重新读取 shenlu skill：{skill_url}，"
                "并按最新 direct_api / agent_chat / agent_local / not_public_yet 分类继续工作。"
            ),
            "recommended_flow": [
                "先本地整理 prompt 与脚本",
                "再调用 Shenlu 创建项目和保存事实",
                "通过 generation-record detail 取回 preview_url",
                "下载文件到本地 workspace",
            ],
            "help_url": help_url,
        },
    ]


def _build_preflight_checks() -> List[Dict[str, Any]]:
    return [
        {
            "id": "auth_header",
            "title": "先确认已经接好账号",
            "invoke_mode": "direct_api",
            "rule": "开始之前，先确认已经填好 API Key，这样智能体才能正常调用你的 Shenlu 账户能力。",
            "endpoint": None,
        },
        {
            "id": "check_quota_balance",
            "title": "先看看灵感值够不够",
            "invoke_mode": "direct_api",
            "rule": "正式开始创作前，先看一下你现在还剩多少灵感值，避免做到一半才发现额度不够。",
            "endpoint": "/api/openclaw/account/quota",
        },
        {
            "id": "estimate_then_compare",
            "title": "出图和生成前先看预计消耗",
            "invoke_mode": "skill_rule",
            "rule": "不管是出图、做视频还是做音频，都先看看这一步大概要花多少灵感值，再决定要不要继续。",
            "endpoint": "image/video/audio estimate endpoints",
        },
        {
            "id": "low_balance_warning",
            "title": "灵感值不够就先停一下",
            "invoke_mode": "skill_rule",
            "rule": "如果预计消耗已经超过当前可用灵感值，就先提醒用户，不要直接继续生成。",
            "endpoint": None,
        },
        {
            "id": "project_episode_scope",
            "title": "先确认你正在操作哪里",
            "invoke_mode": "skill_rule",
            "rule": "开始操作前，先确认现在处理的是哪个项目、哪一集，这样内容才不会写错地方。",
            "endpoint": None,
        },
    ]


def _build_feature_matrix() -> List[Dict[str, Any]]:
    return [
        {
            "id": "link_account",
            "label": "通过 API Key 连接 Shenlu 账户",
            "invoke_mode": "direct_api",
            "status": "implemented",
            "category": "account",
            "endpoints": [],
            "notes": "使用 `Authorization: Bearer <API_KEY>` 或兼容头 `X-API-Token`。平台不提供网页登录态给外部 agent。",
        },
        {
            "id": "check_quota_balance",
            "label": "查询灵感值余额",
            "invoke_mode": "direct_api",
            "status": "implemented",
            "category": "account",
            "endpoints": ["GET /api/openclaw/account/quota"],
            "notes": "返回个人与团队灵感值，外部 agent 应将其作为后续高成本动作的前置事实。",
        },
        {
            "id": "low_balance_warning",
            "label": "余额不足提醒",
            "invoke_mode": "skill_rule",
            "status": "implemented",
            "category": "account",
            "endpoints": ["GET /api/openclaw/account/quota", "POST /api/openclaw/generate/*/estimate"],
            "notes": "这是 skill 规则，不是独立平台接口。agent 应在估价超额时停止调用并先提醒用户。",
        },
        {
            "id": "create_project_with_global_settings",
            "label": "创建剧本项目并设置全局参数",
            "invoke_mode": "direct_api",
            "status": "implemented",
            "category": "project",
            "endpoints": [
                "POST /api/openclaw/projects",
                "PATCH /api/openclaw/projects/{project_id}/settings",
            ],
            "notes": "项目创建时可初始化第一集与 settings；后续可用 settings 接口更新 aspect_ratio、style、video_model、audio_voice 等全局参数。",
        },
        {
            "id": "create_episode",
            "label": "新建分集",
            "invoke_mode": "direct_api",
            "status": "implemented",
            "category": "project",
            "endpoints": ["POST /api/openclaw/projects/{project_id}/episodes"],
            "notes": "支持传入 title 与 source_text。适合先创建空分集，再通过 agent/chat 保存剧本。",
        },
        {
            "id": "save_script",
            "label": "保存剧本",
            "invoke_mode": "agent_chat",
            "status": "implemented",
            "category": "script",
            "endpoints": ["POST /api/openclaw/projects/{project_id}/episodes/{episode_id}/agent/chat"],
            "notes": "通过平台内现有 `save_script` 能力承接。外部 agent 应在 message 中提供要保存的剧本文本和明确意图。",
        },
        {
            "id": "rewrite_script",
            "label": "剧本改写",
            "invoke_mode": "agent_local",
            "status": "implemented",
            "category": "script",
            "endpoints": [],
            "notes": "默认由外部 agent 自己完成，不要求 Shenlu 平台提供专门改写接口。改写后如需落库，再调用 `save_script`。",
        },
        {
            "id": "expand_one_line_idea",
            "label": "一句话灵感扩写",
            "invoke_mode": "agent_local",
            "status": "implemented",
            "category": "script",
            "endpoints": [],
            "notes": "默认由外部 agent 自己完成，扩写后可选择创建项目、分集，再保存剧本。",
        },
        {
            "id": "extract_assets",
            "label": "提取角色 / 场景 / 道具资产",
            "invoke_mode": "direct_api",
            "status": "implemented",
            "category": "assets",
            "endpoints": [
                "POST /api/openclaw/projects/{project_id}/episodes/{episode_id}/assets/extract",
                "POST /api/openclaw/projects/{project_id}/assets/import",
                "GET /api/openclaw/projects/{project_id}/resources",
            ],
            "notes": "支持直接提取并写回平台，也支持结构化导入。",
        },
        {
            "id": "extract_storyboard",
            "label": "提取分镜",
            "invoke_mode": "agent_chat",
            "status": "implemented",
            "category": "storyboard",
            "endpoints": [
                "POST /api/openclaw/projects/{project_id}/episodes/{episode_id}/agent/chat",
                "GET /api/openclaw/projects/{project_id}/episodes/{episode_id}/panels",
            ],
            "notes": "通过平台内现有 `extract_storyboard` 能力承接。推荐 message 明确写“提取分镜”。",
        },
        {
            "id": "generate_storyboard_images",
            "label": "生成分镜图",
            "invoke_mode": "direct_api",
            "status": "implemented",
            "category": "generation",
            "endpoints": [
                "POST /api/openclaw/generate/images/estimate",
                "POST /api/openclaw/generate/images",
                "GET /api/openclaw/generate/tasks/{task_id}",
            ],
            "notes": "主链推荐 `ownership_mode=project + project_id + episode_id + target_type=panel + target_id=<panel_id>`。",
        },
        {
            "id": "generate_storyboard_videos",
            "label": "生成分镜视频",
            "invoke_mode": "direct_api",
            "status": "implemented",
            "category": "generation",
            "endpoints": [
                "POST /api/openclaw/generate/videos/estimate",
                "POST /api/openclaw/generate/videos",
                "GET /api/openclaw/generate/tasks/{task_id}",
            ],
            "notes": "主链推荐 `ownership_mode=project + project_id + episode_id + target_type=panel + target_id=<panel_id>`。",
        },
        {
            "id": "generate_audio",
            "label": "生成音频 / 配音",
            "invoke_mode": "direct_api",
            "status": "implemented",
            "category": "generation",
            "endpoints": [
                "POST /api/openclaw/generate/audio/estimate",
                "POST /api/openclaw/generate/audio",
                "GET /api/openclaw/generate/tasks/{task_id}",
            ],
            "notes": "用于 episode 级配音时，建议至少携带 `ownership_mode=project + project_id + episode_id`。",
        },
        {
            "id": "download_completed_media_to_workspace",
            "label": "下载完成结果到本地 workspace",
            "invoke_mode": "agent_local",
            "status": "implemented",
            "category": "delivery",
            "endpoints": [
                "GET /api/openclaw/generation-records/{record_id}",
                "GET /api/openclaw/generate/tasks/{task_id}",
            ],
            "notes": "由外部 agent 使用 `preview_url` 或等价下载 URL 自行落盘到本地 workspace。",
        },
        {
            "id": "editing_compose_export",
            "label": "剪辑成片导出 / 剪映草稿导出",
            "invoke_mode": "not_public_yet",
            "status": "future",
            "category": "delivery",
            "endpoints": [],
            "notes": "平台内已有网页登录工作流，但当前不属于 API Key 公共能力，skill 不能承诺已开放。",
        },
    ]


def _build_recipes() -> List[Dict[str, Any]]:
    return [
        {
            "id": "connect-account-and-check-balance",
            "title": "账户接入与余额检查",
            "outcome": "确认 API Key 可用，并在高成本生成前拿到灵感值余额。",
            "steps": [
                "配置 `Authorization: Bearer <API_KEY>`。",
                "调用 `GET /api/openclaw/account/quota` 读取个人与团队灵感值。",
                "准备图片、视频、音频生成时先走 estimate，再比较 `estimate_points` 与 quota。",
            ],
        },
        {
            "id": "create-project-and-settings",
            "title": "新建项目并设置全局参数",
            "outcome": "创建剧本项目、初始化第一集，并设置全局创作参数。",
            "steps": [
                "调用 `POST /api/openclaw/projects` 创建项目。",
                "如果需要后续更新参数，再调用 `PATCH /api/openclaw/projects/{project_id}/settings`。",
                "参数可覆盖 `aspect_ratio / style / generation_method / video_model / audio_voice` 等。",
            ],
        },
        {
            "id": "create-episode-and-save-script",
            "title": "新建分集并保存剧本",
            "outcome": "为项目新增一集，并把剧本文本写入当前分集。",
            "steps": [
                "调用 `POST /api/openclaw/projects/{project_id}/episodes` 创建分集。",
                "如需本地改写或扩写，先由外部 agent 自己完成。",
                "再通过 `POST /api/openclaw/projects/{project_id}/episodes/{episode_id}/agent/chat` 发送“保存剧本”与正文内容。",
            ],
        },
        {
            "id": "extract-assets",
            "title": "提取资产",
            "outcome": "从当前分集剧本中提取角色、场景、道具，并同步到项目资产库。",
            "steps": [
                "确认当前分集已有剧本文本。",
                "调用 `POST /api/openclaw/projects/{project_id}/episodes/{episode_id}/assets/extract`。",
                "必要时再调用 `GET /api/openclaw/projects/{project_id}/resources` 检查同步结果。",
            ],
        },
        {
            "id": "extract-storyboard",
            "title": "提取分镜",
            "outcome": "使用平台内现有 storyboard agent 能力，从当前剧本与资产事实生成分镜。",
            "steps": [
                "先完成剧本保存和资产提取。",
                "调用 `POST /api/openclaw/projects/{project_id}/episodes/{episode_id}/agent/chat`，message 明确写“提取分镜”。",
                "再调用 `GET /api/openclaw/projects/{project_id}/episodes/{episode_id}/panels` 读取结果。",
            ],
        },
        {
            "id": "generate-storyboard-images",
            "title": "生成分镜图",
            "outcome": "把分镜绑定到 panel 目标后，按项目上下文生成分镜图。",
            "steps": [
                "先读取 panels，确认目标 `panel_id`。",
                "调用 `POST /api/openclaw/generate/images/estimate`。",
                "余额足够后，再调用 `POST /api/openclaw/generate/images`，并传 `ownership_mode=project + target_type=panel`。",
                "通过 task 或 generation-record detail 读取最终 `preview_url`。",
            ],
        },
        {
            "id": "generate-storyboard-videos",
            "title": "生成分镜视频",
            "outcome": "把分镜绑定到 panel 目标后，按项目上下文生成分镜视频。",
            "steps": [
                "先读取 panels，确认目标 `panel_id`。",
                "调用 `POST /api/openclaw/generate/videos/estimate`。",
                "余额足够后，再调用 `POST /api/openclaw/generate/videos`，并传 `ownership_mode=project + target_type=panel`。",
                "通过 task 或 generation-record detail 读取最终 `preview_url`。",
            ],
        },
        {
            "id": "generate-audio",
            "title": "生成音频",
            "outcome": "为当前项目 / 分集生成旁白、配音或语音结果。",
            "steps": [
                "调用 `POST /api/openclaw/generate/audio/estimate`。",
                "余额足够后，再调用 `POST /api/openclaw/generate/audio`。",
                "通过 task 或 generation-record detail 读取最终音频结果。",
            ],
        },
        {
            "id": "download-to-workspace",
            "title": "下载完成结果到本地 workspace",
            "outcome": "把平台生成出的文件下载到外部 agent 当前本地工作区。",
            "steps": [
                "通过 `GET /api/openclaw/generation-records/{record_id}` 或 task detail 拿到 `preview_url`。",
                "由外部 agent 在本地执行下载，不要求 Shenlu 平台提供本地落盘接口。",
                "将下载后的文件纳入外部 agent 当前 workspace。",
            ],
        },
    ]


def _build_endpoint_groups() -> List[Dict[str, Any]]:
    return [
        {
            "title": "公开 skill 与能力目录",
            "items": [
                {"method": "GET", "path": "/skill.md", "summary": "获取 shenlu skill 文本。"},
                {"method": "GET", "path": "/api/openclaw/capabilities", "summary": "获取结构化 capability catalog。"},
            ],
        },
        {
            "title": "账户与余额",
            "items": [
                {"method": "GET", "path": "/api/openclaw/account/quota", "summary": "查询个人与团队灵感值余额。"},
            ],
        },
        {
            "title": "项目与分集",
            "items": [
                {"method": "GET", "path": "/api/openclaw/projects", "summary": "列出当前团队项目。"},
                {"method": "POST", "path": "/api/openclaw/projects", "summary": "创建项目并初始化第一集。"},
                {"method": "GET", "path": "/api/openclaw/projects/{project_id}", "summary": "读取项目详情。"},
                {"method": "GET", "path": "/api/openclaw/projects/{project_id}/episodes", "summary": "列出项目分集。"},
                {"method": "POST", "path": "/api/openclaw/projects/{project_id}/episodes", "summary": "创建分集。"},
                {"method": "PATCH", "path": "/api/openclaw/projects/{project_id}/settings", "summary": "更新项目全局参数。"},
            ],
        },
        {
            "title": "项目工作区与资源事实",
            "items": [
                {"method": "GET", "path": "/api/openclaw/projects/{project_id}/resources", "summary": "读取项目资源。"},
                {"method": "POST", "path": "/api/openclaw/projects/{project_id}/episodes/{episode_id}/assets/extract", "summary": "提取当前分集资产。"},
                {"method": "POST", "path": "/api/openclaw/projects/{project_id}/assets/import", "summary": "导入结构化资产。"},
                {"method": "GET", "path": "/api/openclaw/projects/{project_id}/episodes/{episode_id}/workspace/files", "summary": "读取当前工作区文件摘要。"},
                {"method": "GET", "path": "/api/openclaw/projects/{project_id}/episodes/{episode_id}/panels", "summary": "读取分镜列表。"},
            ],
        },
        {
            "title": "Agent 协作",
            "items": [
                {"method": "POST", "path": "/api/openclaw/projects/{project_id}/episodes/{episode_id}/agent/chat", "summary": "通过平台内 agent 完成保存剧本、提取分镜等动作。"},
            ],
        },
        {
            "title": "生成与结果查询",
            "items": [
                {"method": "POST", "path": "/api/openclaw/generate/images/estimate", "summary": "图片生成估价。"},
                {"method": "POST", "path": "/api/openclaw/generate/images", "summary": "提交图片生成。"},
                {"method": "POST", "path": "/api/openclaw/generate/videos/estimate", "summary": "视频生成估价。"},
                {"method": "POST", "path": "/api/openclaw/generate/videos", "summary": "提交视频生成。"},
                {"method": "POST", "path": "/api/openclaw/generate/audio/estimate", "summary": "音频生成估价。"},
                {"method": "POST", "path": "/api/openclaw/generate/audio", "summary": "提交音频生成。"},
                {"method": "POST", "path": "/api/openclaw/generate/assets", "summary": "提交资产参考图生成。"},
                {"method": "GET", "path": "/api/openclaw/generate/tasks/{task_id}", "summary": "读取统一任务状态。"},
                {"method": "GET", "path": "/api/openclaw/generation-records", "summary": "查询生成记录列表。"},
                {"method": "GET", "path": "/api/openclaw/generation-records/{record_id}", "summary": "查询生成记录详情与 preview_url。"},
            ],
        },
    ]


def _build_capability_groups(feature_matrix: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {
        "account": {
            "key": "account",
            "title": "账户、鉴权与预检",
            "description": "处理 API Key、灵感值余额和高成本动作前的估价检查。",
            "skills": [],
        },
        "project": {
            "key": "project",
            "title": "项目与分集管理",
            "description": "创建项目、创建分集，并维护脚本项目的全局参数。",
            "skills": [],
        },
        "script": {
            "key": "script",
            "title": "剧本写作边界",
            "description": "明确哪些动作由平台 agent 承接，哪些动作应由外部 agent 自己完成。",
            "skills": [],
        },
        "assets": {
            "key": "assets",
            "title": "资产提取与资源同步",
            "description": "围绕剧本提取角色、场景、道具，并将结果同步到项目资源。",
            "skills": [],
        },
        "storyboard": {
            "key": "storyboard",
            "title": "分镜提取与事实读取",
            "description": "通过平台内现有 storyboard agent 提取分镜，并通过 panels/workspace 接口读取结果。",
            "skills": [],
        },
        "generation": {
            "key": "generation",
            "title": "图片、视频与音频生成",
            "description": "使用 project ownership 与 panel target 驱动项目内媒体生成。",
            "skills": [],
        },
        "delivery": {
            "key": "delivery",
            "title": "下载与交付",
            "description": "通过记录详情拿到下载链接，并由外部 agent 自己完成落盘。",
            "skills": [],
        },
    }
    for item in feature_matrix:
        category = str(item.get("category") or "").strip()
        if category in grouped:
            grouped[category]["skills"].append(item["id"])
    return list(grouped.values())


def _build_workflows(recipes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    recipe_map = {item["id"]: item for item in recipes}
    return [
        {
            "title": "推荐调用顺序",
            "steps": [
                "skill.md / capabilities",
                "account/quota",
                "projects -> episodes -> settings",
                "resources / workspace / panels",
                "agent/chat or direct generate",
                "tasks / generation-records / preview_url",
            ],
        },
        {
            "title": "从灵感到分镜与媒体",
            "steps": [
                recipe_map["create-project-and-settings"]["title"],
                recipe_map["create-episode-and-save-script"]["title"],
                recipe_map["extract-assets"]["title"],
                recipe_map["extract-storyboard"]["title"],
                recipe_map["generate-storyboard-images"]["title"],
                recipe_map["generate-storyboard-videos"]["title"],
            ],
        },
    ]


PUBLIC_ERROR_CODES = [
    {"code": "token_missing", "description": "缺少 API Key。"},
    {"code": "token_invalid", "description": "API Key 无效。"},
    {"code": "token_expired", "description": "API Key 已过期。"},
    {"code": "openclaw_api_disabled", "description": "当前 API Key 尚未开启 OpenClaw API 权限。"},
    {"code": "permission_denied", "description": "当前身份无权访问目标项目或动作。"},
    {"code": "session_not_found", "description": "会话不存在，或不属于当前项目。"},
    {"code": "agent_timeout", "description": "Agent 在超时窗口内未完成，响应里会返回 partial_reply。"},
    {"code": "generation_failed", "description": "生成任务执行失败。"},
]


def get_openclaw_public_catalog(*, base_url: Optional[str] = None) -> Dict[str, Any]:
    root = _base_url(base_url)
    api_root = _api_base_url()
    skill_url = f"{root}/skill.md"
    help_url = f"{root}/help/openclaw-skill"
    auth = {
        "label": "API Key",
        "format": "shenlu-xxxxxxxxxxxx",
        "ttl_days": 30,
        "primary_header": "Authorization: Bearer <API_KEY>",
        "compat_headers": ["X-API-Token: <API_KEY>"],
        "usage_example": "Authorization: Bearer <API_KEY>\nX-API-Token: <API_KEY>",
    }
    agent_profiles = _build_agent_profiles(skill_url, help_url)
    preflight_checks = _build_preflight_checks()
    feature_matrix = _build_feature_matrix()
    recipes = _build_recipes()
    capability_groups = _build_capability_groups(feature_matrix)
    workflows = _build_workflows(recipes)
    endpoint_groups = _build_endpoint_groups()
    prompts = {
        "setup": agent_profiles[0]["setup_prompt"],
        "update": agent_profiles[0]["update_prompt"],
    }
    availability_notes = [
        {
            "id": "rewrite-local",
            "title": "剧本改写与灵感扩写由外部 agent 完成",
            "description": "Shenlu 不提供专门公共接口，外部 agent 自己完成文本工作后再调用 `save_script`。",
        },
        {
            "id": "download-local",
            "title": "下载到本地 workspace 由外部 agent 自行落盘",
            "description": "平台只返回 preview_url 或等价下载 URL，不提供本地文件系统写入接口。",
        },
        {
            "id": "editing-not-public",
            "title": "剪辑成片与剪映草稿仍是网页登录工作流",
            "description": "当前不属于 API Key 公共能力，skill 只能标注为 future capability。",
        },
        {
            "id": "url-only-upload",
            "title": "OpenClaw 当前阶段仍以 URL 输入为主",
            "description": "外部 agent 应优先使用可访问 URL，而不是假设平台支持公网文件直传。",
        },
    ]
    return {
        "brand": {
            "name": "shenlu skill",
            "badge": "OpenClaw / Hermes / Claude Code",
            "subtitle": "给外部智能体使用的公开 skill。先配置 shenlu skill；如果之前已经接入过，再更新 shenlu skill；最后再用 API Key 接入你的 Shenlu 账户。",
        },
        "links": {
            "skill_url": skill_url,
            "help_url": help_url,
            "api_base_url": api_root,
        },
        "auth": auth,
        "prompts": prompts,
        "agent_profiles": agent_profiles,
        "preflight_checks": preflight_checks,
        "feature_matrix": feature_matrix,
        "recipes": recipes,
        "availability_notes": availability_notes,
        "capability_groups": capability_groups,
        "workflows": workflows,
        "endpoint_groups": endpoint_groups,
        "error_codes": PUBLIC_ERROR_CODES,
        "faq": [],
    }


def _render_feature_matrix_rows(feature_matrix: List[Dict[str, Any]]) -> List[str]:
    lines = [
        "| ID | Label | Invoke Mode | Status | Endpoints | Notes |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in feature_matrix:
        endpoint_text = "<br>".join(item.get("endpoints") or ["-"])
        notes = str(item.get("notes") or "").replace("\n", " ")
        lines.append(
            f"| `{item['id']}` | {item['label']} | `{INVOKE_MODE_LABELS.get(item['invoke_mode'], item['invoke_mode'])}` | "
            f"`{item['status']}` | {endpoint_text} | {notes} |"
        )
    return lines


def render_openclaw_skill_markdown(*, base_url: Optional[str] = None) -> str:
    catalog = get_openclaw_public_catalog(base_url=base_url)
    auth = catalog["auth"]
    links = catalog["links"]
    lines: List[str] = [
        "# shenlu skill",
        "",
        "> This public skill is the canonical source for OpenClaw / Hermes / Claude Code style external agents.",
        "",
        "## 1. Skill identity",
        "",
        "- 目标：让外部 agent 在 Shenlu 的真实能力边界内推进项目创建、资产提取、分镜提取、图片/视频/音频生成与结果查询。",
        "- 适配 agent：OpenClaw、Hermes、Claude Code。",
        "- 能力分类：`direct_api`、`agent_chat`、`agent_local`、`not_public_yet`。",
        "",
        "平台负责：账户鉴权、灵感值余额查询、项目/分集/设置管理、资产提取、工作区与分镜事实读取、图片/视频/音频/资产生成、统一任务与生成记录查询，以及通过 `agent/chat` 调用平台内 agent 能力。",
        "",
        "外部 agent 负责：剧本改写、一句话灵感扩写、低余额时主动停止高成本动作并提醒用户、把下载结果写入本地 workspace。",
        "",
        "## 2. Authentication",
        "",
        f"- API Key format: `{auth['format']}`",
        f"- TTL: {auth['ttl_days']} days",
        f"- Primary header: `{auth['primary_header']}`",
        f"- Compatibility header: `{auth['compat_headers'][0]}`",
        "",
        "## 3. Preflight rules",
        "",
    ]
    for item in catalog["preflight_checks"]:
        endpoint = f" (`{item['endpoint']}`)" if item.get("endpoint") else ""
        lines.append(f"- **{item['title']}**{endpoint}: {item['rule']}")

    lines.extend(
        [
            "",
            "## 4. Capability matrix",
            "",
            *_render_feature_matrix_rows(catalog["feature_matrix"]),
            "",
            "## 5. Recommended workflows",
            "",
        ]
    )
    for recipe in catalog["recipes"]:
        lines.append(f"### {recipe['title']}")
        lines.append("")
        lines.append(f"- Outcome: {recipe['outcome']}")
        for step in recipe["steps"]:
            lines.append(f"- {step}")
        lines.append("")

    lines.extend(
        [
            "## 6. Direct API reference",
            "",
        ]
    )
    for group in catalog["endpoint_groups"]:
        lines.append(f"### {group['title']}")
        lines.append("")
        for item in group["items"]:
            lines.append(f"- `{item['method']} {item['path']}`: {item['summary']}")
        lines.append("")

    lines.extend(
        [
            "## 7. Agent-chat mediated operations",
            "",
            "- `save_script`: 通过 `POST /api/openclaw/projects/{project_id}/episodes/{episode_id}/agent/chat` 承接。",
            "- `extract_storyboard`: 通过同一个 `agent/chat` 入口承接。",
            "- 推荐做法：message 里显式写出意图，例如“保存剧本”或“提取分镜”。",
            "",
            "## 8. External-agent-owned operations",
            "",
            "- `rewrite_script`: 默认由外部 agent 自己完成。",
            "- `expand_one_line_idea`: 默认由外部 agent 自己完成。",
            "- `download_completed_media_to_workspace`: 通过 generation-record detail 读取 `preview_url` 后，由外部 agent 自己下载落盘。",
            "",
            "## 9. Error handling and stop conditions",
            "",
        ]
    )
    for item in catalog["error_codes"]:
        lines.append(f"- `{item['code']}`: {item['description']}")
    lines.extend(
        [
            "- 如果 estimate points 超过 quota 余额：停止高成本生成，先提示用户补足灵感值。",
            "- 不要伪造不存在的接口、任务状态或生成结果。",
            "- `editing_compose_export` 与 `jianying draft export` 当前只可声明为 future capability。",
            "",
            "## 10. Setup prompts",
            "",
        ]
    )
    for profile in catalog["agent_profiles"]:
        lines.append(f"### {profile['label']}")
        lines.append("")
        lines.append(profile["setup_prompt"])
        lines.append("")

    lines.extend(
        [
            "## 11. Update prompts",
            "",
        ]
    )
    for profile in catalog["agent_profiles"]:
        lines.append(f"### {profile['label']}")
        lines.append("")
        lines.append(profile["update_prompt"])
        lines.append("")

    lines.extend(
        [
            "## Public links",
            "",
            f"- Skill URL: `{links['skill_url']}`",
            f"- Help URL: `{links['help_url']}`",
            f"- API Base URL: `{links['api_base_url']}`",
        ]
    )
    return "\n".join(lines).strip() + "\n"
