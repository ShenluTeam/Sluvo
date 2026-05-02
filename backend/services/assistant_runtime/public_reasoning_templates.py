from __future__ import annotations

import random
import re
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple


PUBLIC_REASONING_PHASES = ("understand_request", "check_project_state", "prepare_result")
PUBLIC_REASONING_RECENT_LIMIT = 6

PHASE_META = {
    "understand_request": {
        "active_index": 0,
        "variant": "my_understanding",
        "detail": "正在理解创作需求",
        "title": "理解需求",
    },
    "check_project_state": {
        "active_index": 1,
        "variant": "my_plan",
        "detail": "正在核对项目条件",
        "title": "核对条件",
    },
    "prepare_result": {
        "active_index": 2,
        "variant": "my_judgment",
        "detail": "正在整理下一步",
        "title": "整理建议",
    },
}

INTENT_PERSONAS = {
    "next_step_advice": "总导演",
    "script_writing": "编剧专家",
    "script_rewrite": "编剧专家",
    "extract_assets": "资产设计师",
    "generate_asset_images": "资产设计师",
    "extract_storyboard": "分镜导演",
    "generate_storyboard_images": "图片助手",
    "generate_video": "视频助手",
    "rewrite_generation_prompts": "提示词导演",
    "generate_audio": "配音配乐专家",
    "failure_recovery": "现场救场",
    "general_project_question": "总导演",
}

INTENT_BODIES = {
    "next_step_advice": {
        "understand_request": [
            "我先看一眼片场进度。",
            "先把当前项目盘一遍。",
            "我来确认下一步该推哪环。",
            "先看看哪条线最该开拍。",
        ],
        "check_project_state": [
            "正在核对剧本、资产和分镜。",
            "我看下图片和视频缺口。",
            "正在确认哪些物料已就绪。",
            "先把当前完成度对齐一下。",
        ],
        "prepare_result": [
            "马上给你排下一步路线。",
            "我来整理最省来回的动作。",
            "马上给出可点击的推进项。",
            "给你收成一条清楚路线。",
        ],
    },
    "script_writing": {
        "understand_request": [
            "我先抓住这一集的故事钩子。",
            "先看主角这场戏想要什么。",
            "我来捋一下冲突和情绪点。",
            "先把剧情目标拎出来。",
        ],
        "check_project_state": [
            "正在对照已有设定和人物关系。",
            "我看下节奏有没有接住。",
            "正在确认人物动机不跑偏。",
            "先检查前后剧情能否衔接。",
        ],
        "prepare_result": [
            "马上整理可继续打磨的草稿。",
            "我把剧情收成一版可用稿。",
            "马上给你一版更顺的写法。",
            "正在把台词和节奏压实。",
        ],
    },
    "script_rewrite": {
        "understand_request": [
            "我先看哪里需要加戏。",
            "先找节奏卡顿的地方。",
            "我来检查冲突够不够有劲。",
            "先把要保留的骨架稳住。",
        ],
        "check_project_state": [
            "正在对照原文和改写目标。",
            "我看下台词能不能更入戏。",
            "正在找更顺的情绪转折。",
            "先确认改写不偏离主线。",
        ],
        "prepare_result": [
            "马上整理改写方向。",
            "我给你收成可继续推进的版本。",
            "马上给出更顺的一版。",
            "正在把修改点整理清楚。",
        ],
    },
    "extract_assets": {
        "understand_request": [
            "我先给角色和道具点名。",
            "先看看谁必须进入资产库。",
            "我来认领这场戏的关键物件。",
            "先把场景和人物分出来。",
        ],
        "check_project_state": [
            "正在核对资产库避免重复。",
            "我看下角色有没有换名登场。",
            "正在确认场景能否复用。",
            "先检查道具有没有漏掉。",
        ],
        "prepare_result": [
            "马上整理可复用资产设定。",
            "我把角色场景道具归好档。",
            "马上给资产库补齐清单。",
            "正在把设定整理成可出图版本。",
        ],
    },
    "generate_asset_images": {
        "understand_request": [
            "我先看看谁还缺定妆照。",
            "先给缺图资产排个队。",
            "我来确认哪些资产该上镜。",
            "先看角色场景道具的图缺口。",
        ],
        "check_project_state": [
            "正在核对资产设定描述。",
            "我看下已有参考图够不够。",
            "正在确认每个资产的视觉锚点。",
            "先检查提示词是否能出图。",
        ],
        "prepare_result": [
            "马上整理参考图生成任务。",
            "我把缺图资产送去上妆。",
            "马上给资产补一轮参考图。",
            "正在收拢可生成的资产范围。",
        ],
    },
    "extract_storyboard": {
        "understand_request": [
            "我先判断这次是排练，还是正式开拍。",
            "先给这场戏切成几段，别一口气拍到喘。",
            "我来抓这一版规划哪里需要加戏。",
            "先把确认前的剧情节奏顺一顺。",
        ],
        "check_project_state": [
            "正在核对剧本、资产和上一版规划。",
            "我检查这次调整会不会把镜头顺序带跑偏。",
            "正在确认对白和预计时长够不够喘气。",
            "先看当前规划能否支撑正式拆分。",
        ],
        "prepare_result": [
            "马上整理剧情片段规划表。",
            "我把规划版本和总时长收一下尾。",
            "马上给你确认或继续修改的入口。",
            "正在准备正式拆分的进度展示。",
        ],
    },
    "generate_storyboard_images": {
        "understand_request": [
            "我先检查哪些分镜还没出图。",
            "先给待出图镜头排个队。",
            "我来看看哪几镜可以开拍。",
            "先确认这批分镜图范围。",
        ],
        "check_project_state": [
            "正在核对提示词和参考图。",
            "我看下画幅比例是否一致。",
            "正在确认关键资产都带上。",
            "先检查镜头画面描述够不够。",
        ],
        "prepare_result": [
            "马上整理分镜图片任务。",
            "我把待出图镜头送进片场。",
            "马上提交这一批分镜图。",
            "正在整理后续视频建议。",
        ],
    },
    "generate_video": {
        "understand_request": [
            "我先看哪些镜头可以动起来。",
            "先确认这批视频镜头范围。",
            "我来检查画面能不能接成戏。",
            "先看镜头运动该怎么收着来。",
        ],
        "check_project_state": [
            "正在核对已有分镜图和时长。",
            "我看下动作节奏是否顺。",
            "正在确认参考图是否可用。",
            "先检查每镜的视频提示。",
        ],
        "prepare_result": [
            "马上整理视频生成任务。",
            "我把可动的镜头排好队。",
            "马上给你提交视频任务。",
            "正在整理需要补齐的镜头。",
        ],
    },
    "rewrite_generation_prompts": {
        "understand_request": [
            "我先看这次要给提示词加哪味调料。",
            "先确认是改画面，还是改镜头运动。",
            "我来抓住这次提示词要变的重点。",
            "先把用户想要的画风和动作收准。",
        ],
        "check_project_state": [
            "正在核对当前分镜和参考资产。",
            "我看下哪些 @资产 不能乱改。",
            "正在确认图片和视频提示词结构。",
            "先检查这次改写会不会跑剧情。",
        ],
        "prepare_result": [
            "马上整理改写预览。",
            "我把新旧提示词摆在一张表里。",
            "马上给你确认保存和生成入口。",
            "正在把改写结果收成可保存版本。",
        ],
    },
    "generate_audio": {
        "understand_request": [
            "我先听一下这场戏的情绪。",
            "先看对白和旁白怎么分工。",
            "我来找该留呼吸的地方。",
            "先把声音节奏捋顺。",
        ],
        "check_project_state": [
            "正在核对文本和角色声音。",
            "我看下已有音频结果。",
            "正在确认旁白和台词边界。",
            "先检查情绪起伏是否清楚。",
        ],
        "prepare_result": [
            "马上整理音频生成任务。",
            "我把配音段落排好队。",
            "马上给声音部分收个版。",
            "正在整理后续剪辑建议。",
        ],
    },
    "failure_recovery": {
        "understand_request": [
            "刚才这一步卡住了，我来接住。",
            "我先确认卡点在哪里。",
            "先别急，我把可继续的拎出来。",
            "我来拆一下哪里没跑通。",
        ],
        "check_project_state": [
            "正在核对缺的是前置还是结果。",
            "我看下能不能直接重试。",
            "正在确认哪些内容已经保住。",
            "先找一条不绕路的补救线。",
        ],
        "prepare_result": [
            "马上给你补救路线。",
            "我把能继续的步骤排出来。",
            "马上整理可重试的动作。",
            "给你一条稳一点的恢复方案。",
        ],
    },
    "general_project_question": {
        "understand_request": [
            "我先理解你的问题。",
            "先把问题放回当前项目里看。",
            "我来对照一下现有进度。",
            "先确认你问的是哪一环。",
        ],
        "check_project_state": [
            "正在核对项目已有内容。",
            "我看下剧本资产分镜状态。",
            "正在确认哪些信息能直接回答。",
            "先把当前阶段对齐一下。",
        ],
        "prepare_result": [
            "马上整理清楚回复。",
            "我把答案和下一步一起收好。",
            "马上给你一个可执行答复。",
            "正在整理可继续推进的动作。",
        ],
    },
}


def _build_rows() -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for intent, phases in INTENT_BODIES.items():
        persona = INTENT_PERSONAS[intent]
        for phase in PUBLIC_REASONING_PHASES:
            for index, body in enumerate(phases.get(phase) or [], start=1):
                rows.append(
                    {
                        "intent": intent,
                        "persona": persona,
                        "phase": phase,
                        "template_id": f"{intent}.{phase}.{index:02d}",
                        "title": PHASE_META[phase]["title"],
                        "body": body,
                    }
                )
    return rows


PUBLIC_REASONING_TEMPLATE_ROWS = _build_rows()
PUBLIC_REASONING_TEMPLATES: Dict[str, Dict[str, List[Dict[str, str]]]] = defaultdict(lambda: defaultdict(list))
for _row in PUBLIC_REASONING_TEMPLATE_ROWS:
    PUBLIC_REASONING_TEMPLATES[_row["intent"]][_row["phase"]].append(_row)

FORBIDDEN_PUBLIC_REASONING_TERMS = (
    "系统提示词",
    "工具调用",
    "JSON",
    "provider",
    "token",
    "cost",
    "参数",
    "DeepSeek",
    "RunningHub",
    "SuChuang",
    "GRSAI",
    "Nano",
)

SKILL_INTENT_MAP = {
    "save_script": "script_writing",
    "rewrite_script": "script_rewrite",
    "split_episode_source": "extract_storyboard",
    "parse_story_segments": "extract_storyboard",
    "parse_storyboard_draft": "extract_storyboard",
    "extract_storyboard": "extract_storyboard",
    "save_storyboard": "extract_storyboard",
    "extract_project_assets": "extract_assets",
    "extract_assets": "extract_assets",
    "save_assets": "extract_assets",
    "generate_asset_images": "generate_asset_images",
    "generate_panel_image": "generate_storyboard_images",
    "generate_storyboard_images": "generate_storyboard_images",
    "generate_panel_video": "generate_video",
    "generate_video": "generate_video",
    "rewrite_generation_prompts": "rewrite_generation_prompts",
    "generate_episode_dubbing": "generate_audio",
    "generate_audio": "generate_audio",
    "failure_recovery": "failure_recovery",
}

NEXT_STEP_QUERY_TOKENS = (
    "下一步",
    "接下来",
    "然后呢",
    "做什么",
    "怎么推进",
    "继续",
    "进度",
    "状态",
    "到哪一步",
    "做到哪",
)


def public_reasoning_phase_key_for_length(length: int) -> str:
    if int(length or 0) < 60:
        return "understand_request"
    if int(length or 0) < 180:
        return "check_project_state"
    return "prepare_result"


def normalize_public_reasoning_intent(
    *,
    content: str = "",
    skill_hint: Optional[Dict[str, Any]] = None,
    fallback: str = "general_project_question",
) -> str:
    text = str(content or "").strip().lower()
    if any(token in text for token in NEXT_STEP_QUERY_TOKENS):
        return "next_step_advice"

    skill_id = str((skill_hint or {}).get("id") or "").strip()
    if skill_id in SKILL_INTENT_MAP:
        return SKILL_INTENT_MAP[skill_id]

    label = str((skill_hint or {}).get("label") or "")
    if "改写" in label or "润色" in label:
        return "script_rewrite"
    if "剧本" in label or "编剧" in label:
        return "script_writing"
    if "资产" in label or "角色" in label or "道具" in label:
        return "extract_assets"
    if "分镜图" in label or "出图" in label:
        return "generate_storyboard_images"
    if "分镜" in label:
        return "extract_storyboard"
    if "视频" in label:
        return "generate_video"
    if "配音" in label or "音频" in label or "声音" in label:
        return "generate_audio"
    return fallback if fallback in INTENT_PERSONAS else "general_project_question"


def public_reasoning_template_by_id(template_id: str) -> Optional[Dict[str, str]]:
    normalized = str(template_id or "").strip()
    if not normalized:
        return None
    for row in PUBLIC_REASONING_TEMPLATE_ROWS:
        if row["template_id"] == normalized:
            return dict(row)
    return None


def select_public_reasoning_template(
    *,
    content: str = "",
    skill_hint: Optional[Dict[str, Any]] = None,
    phase: str,
    runtime_state: Optional[Dict[str, Any]] = None,
    rng: Any = None,
    fallback_intent: str = "general_project_question",
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    state = dict(runtime_state or {})
    intent = normalize_public_reasoning_intent(content=content, skill_hint=skill_hint, fallback=fallback_intent)
    phase_key = phase if phase in PUBLIC_REASONING_PHASES else "understand_request"
    selected_id = str(state.get("public_reasoning_template_id") or "").strip()
    if (
        state.get("public_reasoning_intent") == intent
        and state.get("public_reasoning_phase") == phase_key
        and selected_id
    ):
        existing = public_reasoning_template_by_id(selected_id)
        if existing:
            return _phase_payload(existing), {}

    recent_ids = [
        str(item or "").strip()
        for item in list(state.get("public_reasoning_recent_template_ids") or [])
        if str(item or "").strip()
    ][:PUBLIC_REASONING_RECENT_LIMIT]
    previous_id = selected_id
    candidates = [dict(item) for item in PUBLIC_REASONING_TEMPLATES[intent].get(phase_key, [])]
    if not candidates and intent != "general_project_question":
        intent = "general_project_question"
        candidates = [dict(item) for item in PUBLIC_REASONING_TEMPLATES[intent].get(phase_key, [])]

    preferred = [item for item in candidates if item["template_id"] not in set(recent_ids + [previous_id])]
    pool = preferred or candidates
    if not pool:
        pool = [
            {
                "intent": "general_project_question",
                "persona": INTENT_PERSONAS["general_project_question"],
                "phase": phase_key,
                "template_id": f"general_project_question.{phase_key}.fallback",
                "title": PHASE_META[phase_key]["title"],
                "body": "我先把问题放回项目里看。",
            }
        ]

    chooser = rng.choice if rng is not None and hasattr(rng, "choice") else random.choice
    selected = dict(chooser(pool))
    next_recent_ids = [selected["template_id"]] + [item for item in recent_ids if item != selected["template_id"]]
    next_recent_ids = next_recent_ids[:PUBLIC_REASONING_RECENT_LIMIT]
    return _phase_payload(selected), {
        "public_reasoning_intent": selected["intent"],
        "public_reasoning_phase": phase_key,
        "public_reasoning_template_id": selected["template_id"],
        "public_reasoning_recent_template_ids": next_recent_ids,
    }


def _phase_payload(row: Dict[str, str]) -> Dict[str, Any]:
    meta = PHASE_META[row["phase"]]
    return {
        "detail": meta["detail"],
        "active_index": meta["active_index"],
        "variant": meta["variant"],
        "intent": row["intent"],
        "phase": row["phase"],
        "template_id": row["template_id"],
        "title": row["title"] or meta["title"],
        "persona": row["persona"],
        "body": row["body"],
    }


def validate_public_reasoning_templates(rows: Optional[Iterable[Dict[str, str]]] = None) -> List[str]:
    errors: List[str] = []
    items = list(rows or PUBLIC_REASONING_TEMPLATE_ROWS)
    ids = [str(item.get("template_id") or "") for item in items]
    duplicated = sorted({item for item in ids if ids.count(item) > 1})
    for template_id in duplicated:
        errors.append(f"duplicate template_id: {template_id}")

    pattern = re.compile(r"^[a-z_]+\.(understand_request|check_project_state|prepare_result)\.\d{2}$")
    grouped: Dict[Tuple[str, str], List[Dict[str, str]]] = defaultdict(list)
    for item in items:
        template_id = str(item.get("template_id") or "")
        intent = str(item.get("intent") or "")
        phase = str(item.get("phase") or "")
        body = str(item.get("body") or "")
        grouped[(intent, phase)].append(item)
        if not pattern.match(template_id):
            errors.append(f"invalid template_id: {template_id}")
        if visible_text_length(body) > 34:
            errors.append(f"template too long: {template_id}")
        for term in FORBIDDEN_PUBLIC_REASONING_TERMS:
            if term.lower() in body.lower():
                errors.append(f"forbidden term {term}: {template_id}")

    for intent in INTENT_PERSONAS:
        for phase in PUBLIC_REASONING_PHASES:
            if len(grouped[(intent, phase)]) < 4:
                errors.append(f"missing templates: {intent}.{phase}")
    return errors


def visible_text_length(value: str) -> int:
    return len(re.sub(r"\s+", "", str(value or "")))
