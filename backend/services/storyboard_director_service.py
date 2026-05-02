import json
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from openai import APITimeoutError, OpenAI
from sqlmodel import Session, select

from core.config import settings
from models import Episode, ResourceTypeEnum, Script, SharedResource
from schemas import (
    PANEL_TYPE_NINE_GRID,
    PANEL_TYPE_NORMAL,
    STORYBOARD_MODE_COMMENTARY,
    STORYBOARD_MODE_COMIC,
    normalize_grid_count,
    normalize_panel_type,
    normalize_storyboard_mode,
)
from services.storyboard_mode_service import normalize_panel_storyboard_payload
from services.deepseek_model_policy import normalize_deepseek_model, normalize_deepseek_request_kwargs
from services.workflow_preset_service import resolve_effective_workflow_profile

NARRATIVE_FUNCTIONS = ["铺垫", "冲突", "反转", "高潮", "收束"]

DIRECTOR_SYSTEM_PROMPT = """
你是短剧/漫剧导演工作台的分镜导演助手。

请把输入剧本文本拆成一个 JSON 对象，必须包含：
- segments: 剧情片段数组
- paragraphs: 段落数组
- shots: 镜头数组
- panel_drafts: 正式分镜数组

segments 每项包含：
- segment_no
- summary
- narrative_purpose
- emotion
- recommended_panel_type: normal/nine_grid
- reason

paragraphs 每项包含：
- paragraph_no
- summary
- scene
- characters: string[]
- emotion
- narrative_function: 铺垫/冲突/反转/高潮/收束
- shot_ids: string[]

shots 每项包含：
- shot_id
- sequence
- paragraph_no
- shot_type
- shot_size
- visual_content
- shot_purpose
- duration_seconds
- scene_refs: string[]
- character_refs: string[]
- prop_refs: string[]
- motion_prompt
- final_prompt_zh
- start_frame_prompt_zh
- end_frame_prompt_zh
- nine_grid_candidates: 长度尽量为 9
- recommended_candidates: 1-2 个

nine_grid_candidates 每项包含：
- grid_no
- shot_size
- angle
- subject_position
- composition_focus
- emotion_effect
- usage_note

recommended_candidates 每项包含：
- grid_no
- reason

panel_drafts 每项包含：
- sequence
- panel_type: normal/nine_grid
- segment_no
- segment_summary
- narrative_purpose
- panel_type_reason
- scene_refs: string[]
- character_refs: string[]
- prop_refs: string[]
- original_text
- image_framing
- video_prompt
- normal 分镜必须输出 prompt
- nine_grid 分镜必须输出 nine_grid_prompt，可附 prompt
- nine_grid_prompt 必须固定为九格格式：第一格：... 到 第九格：...
- nine_grid 分镜的 video_prompt 必须固定为时间轴格式：0-3s：... / 3-6s：... / 6-9s：... / 9-15s：...

硬约束：
- 不要按句子机械拆镜，先拆成完整叙事意义的剧情片段
- normal 适合过渡、特写、反应、强调、单一瞬间
- nine_grid 适合连续动作、情绪推进、多个小节点组成的完整剧情段
- 即使一个片段整体适合 nine_grid，也允许前后插入 normal 分镜
- 最终输出允许 normal 和 nine_grid 混合存在
- nine_grid 的九格内容必须共同讲述同一段完整剧情，保持角色、场景、服装、道具、时间一致
- nine_grid 的每一格都要体现剧情推进，不能只是同画面重复换角度
- nine_grid 的 video_prompt 必须承接九格内容，是同一剧情片段的连续推进，不是四个独立视频
- 九宫格是同一个镜头的 9 个候选构图，不是 9 段不同剧情
- 不允许改变角色身份、服装、场景、动作结果、剧情事实
- 正式提示词必须是中文，不要加入美术风格词
- 正式提示词结构固定：主体描述 + 环境/背景 + 动作/状态 + 技术参数（景别/角度/光影）
- 运动镜头可填写首帧/尾帧提示词，静态镜头可留空

只返回 JSON 对象，不要返回代码块和解释。
"""

class StorySegmentParseError(RuntimeError):
    def __init__(self, error_code: str, message: str, *, detail: Optional[str] = None) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.detail = detail or message


DEEPSEEK_MAX_CONTEXT_TOKENS = int(getattr(settings, "DEEPSEEK_MAX_CONTEXT_TOKENS", 1000000) or 1000000)
_LOCAL_DEEPSEEK_TOKENIZER = None
_LOCAL_DEEPSEEK_TOKENIZER_READY = False
_LOCAL_DEEPSEEK_TOKENIZER_FAILED = False


def _deepseek_tokenizer_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "deepseek_v3_tokenizer"


def _get_local_deepseek_tokenizer():
    global _LOCAL_DEEPSEEK_TOKENIZER
    global _LOCAL_DEEPSEEK_TOKENIZER_READY
    global _LOCAL_DEEPSEEK_TOKENIZER_FAILED

    if _LOCAL_DEEPSEEK_TOKENIZER_READY:
        return _LOCAL_DEEPSEEK_TOKENIZER
    if _LOCAL_DEEPSEEK_TOKENIZER_FAILED:
        return None

    tokenizer_dir = _deepseek_tokenizer_dir()
    if not tokenizer_dir.exists():
        _LOCAL_DEEPSEEK_TOKENIZER_FAILED = True
        return None

    try:
        import transformers  # type: ignore

        _LOCAL_DEEPSEEK_TOKENIZER = transformers.AutoTokenizer.from_pretrained(
            str(tokenizer_dir),
            trust_remote_code=True,
        )
        _LOCAL_DEEPSEEK_TOKENIZER_READY = True
        return _LOCAL_DEEPSEEK_TOKENIZER
    except Exception:
        _LOCAL_DEEPSEEK_TOKENIZER_FAILED = True
        return None


def estimate_deepseek_tokens(text: str) -> int:
    content = str(text or "")
    tokenizer = _get_local_deepseek_tokenizer()
    if tokenizer is not None:
        try:
            return len(tokenizer.encode(content))
        except Exception:
            pass
    # fallback: Chinese-heavy prompts are roughly close to char-count; keep it conservative
    return max(len(content), int(len(content.encode("utf-8")) / 2.5))


def _ensure_deepseek_prompt_budget(
    *,
    user_prompt: str,
    max_tokens: int,
    error_code: str,
    label: str,
) -> None:
    estimated_input_tokens = estimate_deepseek_tokens(user_prompt)
    if estimated_input_tokens + max_tokens > DEEPSEEK_MAX_CONTEXT_TOKENS:
        raise StorySegmentParseError(
            error_code,
            f"{label}输入过长，请缩短当前剧本或片段后重试",
            detail=f"estimated_input_tokens={estimated_input_tokens}, requested_output_tokens={max_tokens}",
        )


def _create_deepseek_chat_completion(
    client: OpenAI,
    *,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: int,
    json_output: bool = True,
    thinking_enabled: bool = False,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Dict[str, Any]] = None,
):
    model, thinking_enabled = normalize_deepseek_model(model, thinking_enabled=thinking_enabled)
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if json_output:
        kwargs["response_format"] = {"type": "json_object"}
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    kwargs = normalize_deepseek_request_kwargs(kwargs, thinking_enabled=thinking_enabled)
    return client.chat.completions.create(**kwargs)


def _response_usage_to_dict(response: Any) -> Dict[str, int]:
    if isinstance(response, dict):
        return {
            "prompt_tokens": int(response.get("prompt_tokens") or 0),
            "completion_tokens": int(response.get("completion_tokens") or 0),
            "prompt_cache_hit_tokens": int(response.get("prompt_cache_hit_tokens") or 0),
            "prompt_cache_miss_tokens": int(response.get("prompt_cache_miss_tokens") or 0),
        }
    usage = getattr(response, "usage", None)
    if usage is None:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "prompt_cache_hit_tokens": 0,
            "prompt_cache_miss_tokens": 0,
        }
    if hasattr(usage, "model_dump"):
        raw = usage.model_dump()
    elif hasattr(usage, "dict"):
        raw = usage.dict()
    elif isinstance(usage, dict):
        raw = usage
    else:
        raw = {}

    prompt_tokens = int(raw.get("prompt_tokens") or 0)
    completion_tokens = int(raw.get("completion_tokens") or 0)
    hit_tokens = int(
        raw.get("prompt_cache_hit_tokens")
        or ((raw.get("prompt_tokens_details") or {}).get("cached_tokens"))
        or 0
    )
    miss_tokens = int(raw.get("prompt_cache_miss_tokens") or max(prompt_tokens - hit_tokens, 0))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "prompt_cache_hit_tokens": hit_tokens,
        "prompt_cache_miss_tokens": miss_tokens,
    }


def _build_usage_fallback(*, prompt_text: str, output_text: str, usage: Optional[Dict[str, int]] = None) -> Dict[str, int]:
    normalized = dict(usage or {})
    prompt_tokens = int(normalized.get("prompt_tokens") or 0)
    completion_tokens = int(normalized.get("completion_tokens") or 0)
    hit_tokens = int(normalized.get("prompt_cache_hit_tokens") or 0)
    miss_tokens = int(normalized.get("prompt_cache_miss_tokens") or 0)

    if prompt_tokens <= 0:
        prompt_tokens = estimate_deepseek_tokens(prompt_text)
    if completion_tokens <= 0 and str(output_text or "").strip():
        completion_tokens = estimate_deepseek_tokens(output_text)
    if hit_tokens <= 0 and miss_tokens <= 0:
        miss_tokens = prompt_tokens

    return {
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "prompt_cache_hit_tokens": int(hit_tokens),
        "prompt_cache_miss_tokens": int(miss_tokens),
    }


def _extract_strict_tool_payload(response: Any, function_name: str) -> Dict[str, Any]:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ValueError("Empty model response")
    message = getattr(choices[0], "message", None)
    tool_calls = getattr(message, "tool_calls", None) or []
    for tool_call in tool_calls:
        function = getattr(tool_call, "function", None)
        if function is None and isinstance(tool_call, dict):
            function = tool_call.get("function")
        name = getattr(function, "name", None) if function is not None else None
        if name is None and isinstance(function, dict):
            name = function.get("name")
        if str(name or "") != str(function_name):
            continue
        arguments = getattr(function, "arguments", None) if function is not None else None
        if arguments is None and isinstance(function, dict):
            arguments = function.get("arguments")
        if not str(arguments or "").strip():
            raise ValueError("Strict tool call returned empty arguments")
        parsed = json.loads(arguments)
        if not isinstance(parsed, dict):
            raise ValueError("Strict tool call arguments are not a JSON object")
        return parsed
    raise ValueError("Strict tool call payload not found")


def extract_json_payload(content: str) -> Dict[str, Any]:
    text = (content or "").strip()
    if not text:
        raise ValueError("Empty model response")

    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    start_idx = min([idx for idx in [text.find("{"), text.find("[")] if idx != -1], default=-1)
    if start_idx == -1:
        raise ValueError("Cannot find JSON payload in model response")
    text = text[start_idx:]

    def _balanced_json_slice(raw_text: str) -> str:
        if not raw_text:
            return raw_text
        opening = raw_text[0]
        closing = "}" if opening == "{" else "]"
        depth = 0
        in_string = False
        escaped = False
        for idx, ch in enumerate(raw_text):
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == opening:
                depth += 1
            elif ch == closing:
                depth -= 1
                if depth == 0:
                    return raw_text[: idx + 1]
        return raw_text

    def _strip_trailing_commas(raw_text: str) -> str:
        return re.sub(r",(\s*[}\]])", r"\1", raw_text)

    def _parse_candidate(raw_text: str) -> Dict[str, Any]:
        parsed = json.loads(raw_text)
        if isinstance(parsed, list):
            return {"paragraphs": [], "shots": parsed}
        if not isinstance(parsed, dict):
            raise ValueError("Model output is not a JSON object")
        return parsed

    candidates: List[str] = []
    balanced = _balanced_json_slice(text)
    if balanced:
        candidates.append(balanced)
        stripped = _strip_trailing_commas(balanced)
        if stripped != balanced:
            candidates.append(stripped)
    if text not in candidates:
        candidates.append(text)

    last_error: Optional[Exception] = None
    for candidate in candidates:
        try:
            return _parse_candidate(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            snippet = candidate[max(0, exc.pos - 80): exc.pos + 80]
            print(
                "[director-json] "
                f"decode_error={exc.msg!r} "
                f"line={exc.lineno} col={exc.colno} pos={exc.pos} "
                f"context={snippet!r}"
            )
        except Exception as exc:
            last_error = exc

    raise ValueError(f"Invalid model JSON payload: {last_error}")


def call_director_model(user_text: str, api_key: str) -> Dict[str, Any]:
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=300.0)
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
            {"role": "user", "content": f"请拆解以下剧本文本：\n\n{user_text}"},
        ],
        extra_body={"thinking": {"type": "enabled"}},
    )
    return extract_json_payload(response.choices[0].message.content or "")


def to_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        parts = [item.strip() for item in value.replace("，", ",").split(",")]
        return [item for item in parts if item]
    return []


def normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(text.split())


def safe_int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except Exception:
        return fallback


def normalize_structured_asset_items(items: List[Dict[str, Any]], resource_type: str) -> List[Dict[str, Any]]:
    normalized: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue

        key = normalize_key(name)
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(
            {
                "name": name,
                "description": str(raw.get("description") or "").strip(),
                "trigger_word": str(raw.get("trigger_word") or "").strip() or None,
                "resource_type": resource_type,
                "source_status": str(raw.get("source_status") or "draft"),
            }
        )

    return normalized


def build_panel_binding_suggestions(
    session: Session,
    script_id: int,
    *,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
    structured_assets: Dict[str, Any],
) -> Dict[str, Any]:
    existing_resources = session.exec(
        select(SharedResource).where(
            SharedResource.script_id == script_id,
            SharedResource.resource_type.in_(
                [
                    ResourceTypeEnum.SCENE_REF.value,
                    ResourceTypeEnum.CHARACTER_REF.value,
                    ResourceTypeEnum.PROP_REF.value,
                ]
            ),
        )
    ).all()

    def make_candidates(resource_type: str, draft_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []

        for resource in existing_resources:
            if str(resource.resource_type) != resource_type:
                continue
            candidates.append(
                {
                    "id": resource.id,
                    "name": resource.name or "",
                    "key": normalize_key(resource.name),
                    "source": "existing",
                    "created_at": resource.created_at or datetime.utcnow(),
                }
            )

        for item in draft_items:
            if item.get("resource_type") != resource_type:
                continue
            candidates.append(
                {
                    "id": None,
                    "name": item.get("name") or "",
                    "key": normalize_key(item.get("name")),
                    "source": "draft",
                    "created_at": datetime.utcnow(),
                }
            )

        candidates.sort(key=lambda item: (item["created_at"], str(item["id"] or item["name"])))
        return candidates

    scene_candidates = make_candidates("scene", structured_assets.get("scenes") or [])
    character_candidates = make_candidates("character", structured_assets.get("characters") or [])
    prop_candidates = make_candidates("prop", structured_assets.get("props") or [])

    def match_name(name: str, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        key = normalize_key(name)
        if not key:
            return {"name": name, "asset_id": None, "match_type": "unmatched"}

        for item in candidates:
            if key == item["key"]:
                return {
                    "name": name,
                    "asset_id": item["id"],
                    "match_type": "exact" if item["source"] == "existing" else "draft_exact",
                }

        best = None
        best_score = -1
        for item in candidates:
            candidate_key = item["key"]
            if not candidate_key:
                continue
            if key in candidate_key or candidate_key in key:
                score = max(len(candidate_key), len(key))
                if score > best_score:
                    best_score = score
                    best = item

        if best:
            return {
                "name": name,
                "asset_id": best["id"],
                "match_type": "fuzzy" if best["source"] == "existing" else "draft_fuzzy",
            }

        return {"name": name, "asset_id": None, "match_type": "unmatched"}

    scene_items = [match_name(name, scene_candidates) for name in scene_refs]
    character_items = [match_name(name, character_candidates) for name in character_refs]
    prop_items = [match_name(name, prop_candidates) for name in prop_refs]

    all_items = scene_items + character_items + prop_items
    matched_existing = [item for item in all_items if item.get("asset_id")]
    matched_any = [item for item in all_items if item.get("match_type") != "unmatched"]

    if not all_items:
        status = "unmatched"
    elif len(matched_existing) == len(all_items):
        status = "auto_matched"
    elif len(matched_any) == len(all_items):
        status = "draft_ready"
    elif matched_any:
        status = "partial_matched"
    else:
        status = "unmatched"

    return {
        "scenes": scene_items,
        "characters": character_items,
        "props": prop_items,
        "binding_status": status,
    }


def normalize_narrative_function(value: Any, fallback: str = "铺垫") -> str:
    text = str(value or "").strip()
    if text in NARRATIVE_FUNCTIONS:
        return text

    mapping = {
        "铺陈": "铺垫",
        "铺设": "铺垫",
        "起": "铺垫",
        "起因": "冲突",
        "对抗": "冲突",
        "爆点": "高潮",
        "爆发": "高潮",
        "结尾": "收束",
        "结束": "收束",
    }
    for key, mapped in mapping.items():
        if key in text:
            return mapped
    return fallback if fallback in NARRATIVE_FUNCTIONS else "铺垫"


def build_candidate_summary(candidates: List[Dict[str, Any]]) -> str:
    parts = []
    for candidate in candidates:
        parts.append(
            "格{grid_no}:{shot_size}/{angle}/{subject_position}/{composition_focus}".format(
                grid_no=candidate.get("grid_no") or 0,
                shot_size=candidate.get("shot_size") or "未知景别",
                angle=candidate.get("angle") or "未知角度",
                subject_position=candidate.get("subject_position") or "主体居中",
                composition_focus=candidate.get("composition_focus") or "主体动作",
            )
        )
    return " | ".join(parts)


def build_recommended_summary(recommendations: List[Dict[str, Any]]) -> str:
    parts = []
    for item in recommendations:
        parts.append(f"推荐格{item.get('grid_no') or 0}:{item.get('reason') or '更符合叙事重点'}")
    return "；".join(parts)


def build_final_prompt(shot: Dict[str, Any], candidate: Dict[str, Any], paragraph: Optional[Dict[str, Any]] = None) -> str:
    paragraph = paragraph or {}
    subject = "、".join(shot.get("character_refs") or paragraph.get("characters") or []) or "主体人物"
    scene = "、".join(shot.get("scene_refs") or []) or paragraph.get("scene") or "当前场景"
    action = shot.get("visual_content") or shot.get("shot_purpose") or paragraph.get("summary") or "关键动作瞬间"
    tech = "，".join(
        [
            candidate.get("shot_size") or shot.get("shot_size") or "中景",
            candidate.get("angle") or "平视",
            candidate.get("composition_focus") or "主体动作",
        ]
    )
    return f"{subject}，{scene}，{action}，{tech}"


def build_motion_prompt(shot: Dict[str, Any]) -> str:
    direct = str(shot.get("motion_prompt") or "").strip()
    if direct:
        return direct
    start_frame = str(shot.get("start_frame_prompt_zh") or "").strip()
    end_frame = str(shot.get("end_frame_prompt_zh") or "").strip()
    if start_frame and end_frame:
        return f"首帧：{start_frame}；尾帧：{end_frame}"
    return ""


def _placeholder_candidate(grid_no: int, shot: Dict[str, Any], paragraph: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "grid_no": grid_no,
        "shot_size": str(shot.get("shot_size") or "中景"),
        "angle": "平视",
        "subject_position": "主体居中",
        "composition_focus": str(shot.get("shot_purpose") or shot.get("visual_content") or paragraph.get("summary") or "主体动作"),
        "emotion_effect": str(shot.get("emotion_effect") or paragraph.get("emotion") or "保持当前情绪"),
        "usage_note": "模型未完整返回该候选，已使用保底构图占位。",
    }


def build_default_panel_type_reason(panel_type: str, segment: Dict[str, Any]) -> str:
    if panel_type == PANEL_TYPE_NINE_GRID:
        return str(segment.get("reason") or "该剧情片段包含连续动作或多节点推进，更适合由一个九宫格分镜承载。")
    return str(segment.get("reason") or "该剧情片段更适合用单一瞬间、反应或强调镜头表达。")


def build_default_nine_grid_prompt(
    panel: Dict[str, Any],
    segment: Dict[str, Any],
    variant: Optional[Dict[str, Any]] = None,
) -> str:
    return build_standard_nine_grid_prompt(panel, segment, variant)


def _build_panel_draft_defaults(
    *,
    sequence: int,
    segment_no: int,
    panel_type: str,
    segment: Dict[str, Any],
    raw: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw = raw or {}
    return {
        "sequence": sequence,
        "panel_type": panel_type,
        "segment_no": segment_no,
        "segment_summary": str(raw.get("segment_summary") or segment.get("summary") or ""),
        "narrative_purpose": str(raw.get("narrative_purpose") or segment.get("narrative_purpose") or "推动叙事"),
        "panel_type_reason": str(raw.get("panel_type_reason") or segment.get("reason") or build_default_panel_type_reason(panel_type, segment)),
        "scene_refs": [],
        "character_refs": [],
        "prop_refs": [],
        "prompt": "",
        "prompt_zh": "",
        "video_prompt": "",
        "nine_grid_prompt": "",
        "image_framing": "",
        "original_text": "",
    }


def _debug_panel_draft_state(segment_no: int, panel_type: str, fields: Dict[str, Any]) -> None:
    print(
        "[director-draft] "
        f"segment_no={segment_no} "
        f"panel_type={panel_type} "
        f"prompt_empty={not bool(str(fields.get('prompt') or '').strip())} "
        f"video_prompt_empty={not bool(str(fields.get('video_prompt') or '').strip())} "
        f"nine_grid_prompt_empty={not bool(str(fields.get('nine_grid_prompt') or '').strip())}"
    )


NINE_GRID_IMAGE_LABELS = [
    "第一格",
    "第二格",
    "第三格",
    "第四格",
    "第五格",
    "第六格",
    "第七格",
    "第八格",
    "第九格",
]

NINE_GRID_VIDEO_LABELS = ["0-3s", "3-6s", "6-9s", "9-15s"]


def _clean_prompt_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _collect_nine_grid_subject(panel: Dict[str, Any]) -> str:
    names = to_list(panel.get("character_refs")) or to_list(panel.get("character"))
    return "、".join(names) if names else "主体人物"


def _collect_nine_grid_scene(panel: Dict[str, Any], segment: Dict[str, Any]) -> str:
    scenes = to_list(panel.get("scene_refs")) or to_list(panel.get("scene"))
    if scenes:
        return "、".join(scenes)
    return _clean_prompt_text(segment.get("summary"), "当前场景")


def _collect_nine_grid_props(panel: Dict[str, Any]) -> str:
    props = to_list(panel.get("prop_refs")) or to_list(panel.get("prop"))
    return "、".join(props)


def _build_nine_grid_context(
    panel: Dict[str, Any],
    segment: Dict[str, Any],
    variant: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    variant = variant or {}
    summary = _clean_prompt_text(panel.get("original_text"), _clean_prompt_text(segment.get("summary"), "当前剧情片段"))
    purpose = _clean_prompt_text(
        panel.get("narrative_purpose"),
        _clean_prompt_text(segment.get("narrative_purpose"), "推进叙事"),
    )
    subject = _collect_nine_grid_subject(panel)
    scene = _collect_nine_grid_scene(panel, segment)
    props = _collect_nine_grid_props(panel)
    prompt = _clean_prompt_text(panel.get("prompt"))
    composition = _clean_prompt_text(variant.get("composition_prompt"), prompt or summary)
    camera_angle = _clean_prompt_text(variant.get("camera_angle"), "平视")
    shot_size = _clean_prompt_text(variant.get("shot_size"), "中景")
    focus = _clean_prompt_text(variant.get("focus"), purpose or "主体动作")
    emotion = _clean_prompt_text(segment.get("emotion"), "情绪持续推进")
    return {
        "summary": summary,
        "purpose": purpose,
        "subject": subject,
        "scene": scene,
        "props": props,
        "prompt": prompt,
        "composition": composition,
        "camera_angle": camera_angle,
        "shot_size": shot_size,
        "focus": focus,
        "emotion": emotion,
    }


def is_standard_nine_grid_prompt(value: Any) -> bool:
    text = str(value or "").strip()
    return all(f"{label}：" in text for label in NINE_GRID_IMAGE_LABELS)


def is_standard_nine_grid_video_prompt(value: Any) -> bool:
    text = str(value or "").strip()
    return all(f"{label}：" in text for label in NINE_GRID_VIDEO_LABELS)


def build_standard_nine_grid_prompt(
    panel: Dict[str, Any],
    segment: Dict[str, Any],
    variant: Optional[Dict[str, Any]] = None,
) -> str:
    ctx = _build_nine_grid_context(panel, segment, variant)
    phase_actions = [
        "建立人物与环境关系，作为连续剧情的起始画面",
        "角色开始关键动作，承接上一格进入推进状态",
        "动作被放大呈现，突出连续变化的第一层升级",
        "镜头压近主体反应，让情绪开始明显外露",
        "画面进入剧情重心，突出本段最强冲突或转折节点",
        "动作后续继续推进，交代结果正在形成",
        "补充关系、道具或环境反馈，连接前后格逻辑",
        "情绪或动作进入收束前的最后提升",
        "给出本段结果画面，完成完整剧情闭环",
        "当前镜头聚焦主体动作、表情或关键状态变化",
        "画面聚焦当前关键动作、反应或状态变化",
    ]
    lines: List[str] = []
    for idx, label in enumerate(NINE_GRID_IMAGE_LABELS):
        props_text = f"，道具为{ctx['props']}" if ctx["props"] else ""
        lines.append(
            f"{label}：{ctx['subject']}，位于{ctx['scene']}{props_text}，"
            f"{phase_actions[idx]}；当前剧情为“{ctx['summary']}”，"
            f"构图重点是{ctx['focus']}，采用{ctx['shot_size']}、{ctx['camera_angle']}，"
            f"情绪氛围保持{ctx['emotion']}，并与前后格形成连续推进。"
        )
    return "\n".join(lines)


def build_standard_nine_grid_video_prompt(
    panel: Dict[str, Any],
    segment: Dict[str, Any],
    variant: Optional[Dict[str, Any]] = None,
) -> str:
    ctx = _build_nine_grid_context(panel, segment, variant)
    stages = [
        "建立场景和人物站位，镜头缓慢进入剧情片段，作为九宫格图板的起始节奏",
        "角色动作与情绪持续升级，镜头承接上一段推进核心事件",
        "围绕关键动作和关系变化继续推进，强化连续叙事和画面重心",
        "收束到本段结果或情绪落点，完成同一剧情片段的闭环",
    ]
    lines: List[str] = []
    for label, stage in zip(NINE_GRID_VIDEO_LABELS, stages):
        lines.append(
            f"{label}：{ctx['subject']}在{ctx['scene']}中围绕“{ctx['summary']}”展开，"
            f"{stage}；镜头保持{ctx['camera_angle']}与{ctx['shot_size']}基调，"
            f"突出{ctx['focus']}，情绪持续呈现{ctx['emotion']}并与前后时间段连贯衔接。"
        )
    return "\n".join(lines)


def build_default_image_framing(panel_type: str, panel: Dict[str, Any]) -> str:
    framing = str(panel.get("image_framing") or "").strip()
    if framing:
        return framing
    if panel_type == PANEL_TYPE_NINE_GRID:
        return "九宫格连续叙事 / 平视 / 多节点推进"
    return "中景 / 平视 / 主体居中"


def synthesize_shot_from_panel_draft(panel_draft: Dict[str, Any]) -> Dict[str, Any]:
    framing = str(panel_draft.get("image_framing") or "").strip()
    shot_size = framing.split("/")[0].strip() if framing and "/" in framing else framing or ("九宫格连续叙事" if normalize_panel_type(panel_draft.get("panel_type")) == PANEL_TYPE_NINE_GRID else "中景")
    return {
        "shot_id": f"panel-{panel_draft.get('sequence') or 0}",
        "sequence": int(panel_draft.get("sequence") or 0),
        "paragraph_no": int(panel_draft.get("segment_no") or 0),
        "shot_type": "九宫格分镜" if normalize_panel_type(panel_draft.get("panel_type")) == PANEL_TYPE_NINE_GRID else "普通分镜",
        "shot_size": shot_size,
        "visual_content": panel_draft.get("original_text") or "",
        "shot_purpose": panel_draft.get("narrative_purpose") or "",
        "duration_seconds": 3,
        "scene_refs": panel_draft.get("scene_refs") or [],
        "character_refs": panel_draft.get("character_refs") or [],
        "prop_refs": panel_draft.get("prop_refs") or [],
        "motion_prompt": panel_draft.get("video_prompt") or None,
        "final_prompt_zh": panel_draft.get("prompt_zh") or panel_draft.get("prompt") or "",
        "start_frame_prompt_zh": None,
        "end_frame_prompt_zh": None,
        "nine_grid_candidates": [],
        "recommended_candidates": [],
        "recommended_summary": "",
        "candidate_summary": "",
        "warnings": [],
    }


def normalize_story_segment_payload_v2(
    payload: Dict[str, Any],
    *,
    episode: Episode,
    structured_assets: Dict[str, Any],
    session: Session,
    storyboard_mode: Optional[str] = None,
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode or getattr(episode, "storyboard_mode", None))
    script = session.get(Script, episode.script_id) if getattr(episode, "script_id", None) else None
    effective_profile = resolve_effective_workflow_profile(script, episode=episode, storyboard_mode=normalized_mode) if script else {}
    effective_aspect_ratio = str(
        effective_profile.get("aspect_ratio")
        or ("16:9" if normalized_mode == STORYBOARD_MODE_COMIC else "9:16")
    ).strip()
    story_segments = payload.get("story_segments") or []
    warnings: List[str] = list(payload.get("warnings") or [])
    normalized_segments: List[Dict[str, Any]] = []

    for index, raw_segment in enumerate(story_segments, start=1):
        if not isinstance(raw_segment, dict):
            continue
        sequence_num = safe_int(raw_segment.get("sequence_num"), index)
        summary = str(raw_segment.get("summary") or raw_segment.get("title") or f"剧情片段{sequence_num}").strip()
        character_refs = to_list(raw_segment.get("character_refs"))
        scene_refs = to_list(raw_segment.get("scene_refs"))
        prop_refs = to_list(raw_segment.get("prop_refs"))
        continuity_note = str(raw_segment.get("continuity_note") or "").strip()
        text_span = raw_segment.get("text_span") if isinstance(raw_segment.get("text_span"), dict) else {}
        text_span = {
            "source_excerpt": str(text_span.get("source_excerpt") or summary).strip(),
            "start_offset": text_span.get("start_offset"),
            "end_offset": text_span.get("end_offset"),
        }
        scene_constraint = str(raw_segment.get("scene_constraint") or "").strip() or build_segment_scene_constraint(
            summary=summary,
            scene_refs=scene_refs,
            character_refs=character_refs,
            prop_refs=prop_refs,
            continuity_note=continuity_note,
        )

        binding_suggestions = build_panel_binding_suggestions(
            session,
            episode.script_id,
            scene_refs=scene_refs,
            character_refs=character_refs,
            prop_refs=prop_refs,
            structured_assets=structured_assets,
        )
        scene_refs = _bound_ref_names(binding_suggestions, "scenes")
        character_refs = _bound_ref_names(binding_suggestions, "characters")
        prop_refs = _bound_ref_names(binding_suggestions, "props")
        reference_assets = [
            {
                "resource_type": resource_type[:-1] if resource_type.endswith("s") else resource_type,
                "asset_id": item.get("asset_id"),
                "name": item.get("name") or "",
                "match_type": item.get("match_type") or "unmatched",
            }
            for resource_type in ("scenes", "characters", "props")
            for item in (binding_suggestions.get(resource_type) or [])
            if isinstance(item, dict) and (item.get("name") or item.get("asset_id") is not None)
        ]

        effective_duration_seconds = clamp_segment_total_duration(
            safe_int(raw_segment.get("recommended_duration_seconds"), 6),
            len(raw_segment.get("grid_cells") or []) or normalize_grid_count(raw_segment.get("grid_count")),
        )
        effective_grid_count = constrain_segment_grid_count(
            effective_duration_seconds,
            raw_segment.get("grid_count"),
        )
        grid_cells: List[Dict[str, Any]] = []
        raw_cells = (raw_segment.get("grid_cells") or [])[:effective_grid_count]
        for cell_index, raw_cell in enumerate(raw_cells, start=1):
            if not isinstance(raw_cell, dict):
                continue
            shot_description = str(raw_cell.get("shot_description") or raw_cell.get("visual_content") or "").strip()
            if _is_low_information_text(shot_description):
                shot_description = ""
            action_description = str(raw_cell.get("action_description") or raw_cell.get("action") or "").strip()
            if _is_low_information_text(action_description):
                action_description = ""
            dialogue_excerpt = str(raw_cell.get("dialogue_excerpt") or raw_cell.get("dialogue_text") or "").strip()
            if _is_low_information_text(dialogue_excerpt):
                dialogue_excerpt = ""
            speech_items = _normalize_speech_items(raw_cell.get("speech_items") or [])
            if not speech_items and dialogue_excerpt:
                speech_items = _speech_items_from_dialogue_excerpt(dialogue_excerpt)
            if speech_items:
                dialogue_excerpt = _speech_items_to_dialogue_excerpt(speech_items) or dialogue_excerpt
            shot_type = normalize_shot_type_label(raw_cell.get("shot_type") or raw_cell.get("shot_size") or "中景")
            camera_motion = normalize_camera_motion_label(raw_cell.get("camera_motion") or "静止")
            composition = str(raw_cell.get("composition") or raw_cell.get("composition_focus") or "").strip()
            if _is_low_information_text(composition):
                composition = ""
            lighting = str(raw_cell.get("lighting") or "").strip()
            if _is_low_information_text(lighting):
                lighting = ""
            ambiance = str(raw_cell.get("ambiance") or "").strip()
            if _is_low_information_text(ambiance):
                ambiance = ""
            image_prompt_structured = raw_cell.get("image_prompt_structured") if isinstance(raw_cell.get("image_prompt_structured"), dict) else build_gridcell_image_prompt_structured(
                shot_description=shot_description,
                shot_type=shot_type,
                lighting=lighting,
                ambiance=ambiance,
                composition=composition,
            )
            video_prompt_structured = raw_cell.get("video_prompt_structured") if isinstance(raw_cell.get("video_prompt_structured"), dict) else build_gridcell_video_prompt_structured(
                action_description=action_description,
                camera_motion=camera_motion,
                dialogue_excerpt=dialogue_excerpt,
                speech_items=speech_items,
                ambiance_audio=str(raw_cell.get("ambiance_audio") or "").strip(),
            )
            source_texts = [
                shot_description,
                action_description,
                dialogue_excerpt,
                *[str(item.get("text") or "").strip() for item in speech_items],
                composition,
                raw_cell.get("image_prompt"),
                raw_cell.get("video_prompt"),
            ]
            explicit_character_refs = [name for name in to_list(raw_cell.get("character_refs")) if name in character_refs]
            explicit_scene_refs = [name for name in to_list(raw_cell.get("scene_refs")) if name in scene_refs]
            explicit_prop_refs = [name for name in to_list(raw_cell.get("prop_refs")) if name in prop_refs]
            cell_character_refs = explicit_character_refs or _infer_cell_refs_from_text(source_texts, character_refs, fallback=character_refs[:1] if len(character_refs) == 1 else [])
            cell_scene_refs = explicit_scene_refs or _infer_cell_refs_from_text(source_texts, scene_refs, fallback=scene_refs[:1] if scene_refs else [])
            cell_prop_refs = explicit_prop_refs or _infer_cell_refs_from_text(source_texts, prop_refs, fallback=[])
            grid_cells.append(
                {
                    "cell_index": safe_int(raw_cell.get("cell_index"), cell_index),
                    "start_second": _safe_float(raw_cell.get("start_second"), 0.0) or 0.0,
                    "end_second": _safe_float(raw_cell.get("end_second"), 0.0) or 0.0,
                    "duration_seconds": _safe_float(raw_cell.get("duration_seconds"), 0.0) or 0.0,
                    "shot_description": shot_description or (text_span["source_excerpt"] if not _is_low_information_text(text_span["source_excerpt"]) else summary),
                    "action_description": action_description if not _is_low_information_text(action_description) else (shot_description or ""),
                    "dialogue_excerpt": dialogue_excerpt or text_span["source_excerpt"],
                    "speech_items": speech_items,
                    "performance_focus": (
                        None
                        if _is_low_information_text(raw_cell.get("performance_focus"))
                        else (str(raw_cell.get("performance_focus") or "").strip() or None)
                    ) or infer_performance_focus(speech_items, storyboard_mode=normalized_mode),
                    "mouth_sync_required": bool(raw_cell.get("mouth_sync_required") if raw_cell.get("mouth_sync_required") is not None else any(item.get("mouth_sync_required") for item in speech_items)),
                    "shot_type": shot_type,
                    "camera_motion": camera_motion,
                    "composition": composition,
                    "lighting": str(image_prompt_structured.get("composition", {}).get("lighting") or lighting).strip(),
                    "ambiance": str(image_prompt_structured.get("composition", {}).get("ambiance") or ambiance).strip(),
                    "camera_position": None if _is_low_information_text(raw_cell.get("camera_position")) else (str(raw_cell.get("camera_position") or "").strip() or None),
                    "camera_direction": None if _is_low_information_text(raw_cell.get("camera_direction")) else (str(raw_cell.get("camera_direction") or "").strip() or None),
                    "shot_purpose": None if _is_low_information_text(raw_cell.get("shot_purpose")) else (str(raw_cell.get("shot_purpose") or "").strip() or None),
                    "image_prompt_structured": image_prompt_structured,
                    "video_prompt_structured": video_prompt_structured,
                    "image_prompt": str(raw_cell.get("image_prompt") or "").strip(),
                    "video_prompt": str(raw_cell.get("video_prompt") or "").strip(),
                    "character_refs": cell_character_refs,
                    "scene_refs": cell_scene_refs,
                    "prop_refs": cell_prop_refs,
                    "asset_status": str(raw_cell.get("asset_status") or "idle"),
                    "binding_suggestions": binding_suggestions,
                    "segment_grid_count": effective_grid_count,
                    "storyboard_mode": normalized_mode,
                }
            )

        min_segment_duration = max(
            effective_duration_seconds,
            _ceil_timing_seconds(sum(estimate_cell_min_duration_seconds(cell, storyboard_mode=normalized_mode) for cell in grid_cells), 4),
        ) if grid_cells else effective_duration_seconds
        effective_duration_seconds = clamp_segment_total_duration(
            min_segment_duration,
            len(grid_cells) or effective_grid_count,
        )
        effective_grid_count = constrain_segment_grid_count(
            effective_duration_seconds,
            max(effective_grid_count, len(grid_cells) or effective_grid_count),
        )

        normalized_segments.append(
            {
                "sequence_num": sequence_num,
                "title": str(raw_segment.get("title") or summary[:40] or f"片段{sequence_num}").strip(),
                "summary": summary,
                "text_span": text_span,
                "recommended_duration_seconds": effective_duration_seconds,
                "grid_count": effective_grid_count,
                "pacing": str(raw_segment.get("pacing") or "").strip() or None,
                "rhythm": str(raw_segment.get("rhythm") or "").strip() or None,
                "scene_constraint": scene_constraint,
                "scene_prompt": str(raw_segment.get("scene_prompt") or "").strip(),
                "continuity_note": continuity_note or scene_constraint,
                "transition_to_next": str(raw_segment.get("transition_to_next") or "").strip() or "cut",
                "character_refs": character_refs,
                "scene_refs": scene_refs,
                "prop_refs": prop_refs,
                "reference_assets": reference_assets,
                "reference_images": [str(item.get("asset_id")) for item in reference_assets if item.get("asset_id") is not None],
                "auto_asset_reference_enabled": bool(raw_segment.get("auto_asset_reference_enabled", True)),
                "segment_prompt_summary": "" if _is_low_information_text(raw_segment.get("segment_prompt_summary")) else str(raw_segment.get("segment_prompt_summary") or summary).strip(),
                "beat_ids": [str(beat_id or "").strip() for beat_id in (raw_segment.get("beat_ids") or []) if str(beat_id or "").strip()],
                "speech_density": str(raw_segment.get("speech_density") or "medium").strip().lower() or "medium",
                "language_focus_summary": str(raw_segment.get("language_focus_summary") or "").strip(),
                "speech_coverage_targets": [
                    str(item or "").strip()
                    for item in (raw_segment.get("speech_coverage_targets") or [])
                    if str(item or "").strip()
                ],
                "multi_shot_prompt": str(raw_segment.get("multi_shot_prompt") or "").strip(),
                "multi_shot_video_prompt": str(raw_segment.get("multi_shot_video_prompt") or "").strip(),
                "generation_status": str(raw_segment.get("generation_status") or "idle"),
                "binding_suggestions": binding_suggestions,
                "grid_cells": grid_cells or [
                    {
                        "cell_index": 1,
                        "start_second": 0.0,
                        "end_second": 0.0,
                        "duration_seconds": 0.0,
                        "shot_description": text_span["source_excerpt"] if not _is_low_information_text(text_span["source_excerpt"]) else summary,
                        "action_description": "" if _is_low_information_text(raw_segment.get("segment_prompt_summary")) else str(raw_segment.get("segment_prompt_summary") or "").strip(),
                        "dialogue_excerpt": text_span["source_excerpt"],
                        "speech_items": _speech_items_from_dialogue_excerpt(text_span["source_excerpt"]),
                        "performance_focus": None,
                        "mouth_sync_required": False,
                        "shot_type": "中景",
                        "camera_motion": "静止",
                        "composition": scene_constraint,
                        "lighting": "",
                        "ambiance": "",
                        "camera_position": None,
                        "camera_direction": None,
                        "shot_purpose": None,
                        "image_prompt_structured": build_gridcell_image_prompt_structured(
                            shot_description=summary,
                            shot_type="中景",
                            lighting="按当前场景的真实光线氛围呈现主体",
                            ambiance=scene_constraint,
                            composition=scene_constraint,
                        ),
                        "video_prompt_structured": build_gridcell_video_prompt_structured(
                            action_description=str(raw_segment.get("segment_prompt_summary") or summary).strip(),
                            camera_motion="静止",
                            dialogue_excerpt=text_span["source_excerpt"],
                            speech_items=_speech_items_from_dialogue_excerpt(text_span["source_excerpt"]),
                        ),
                        "image_prompt": "",
                        "video_prompt": "",
                        "character_refs": character_refs,
                        "scene_refs": scene_refs,
                        "prop_refs": prop_refs,
                        "asset_status": "idle",
                        "binding_suggestions": binding_suggestions,
                        "segment_grid_count": effective_grid_count,
                        "storyboard_mode": normalized_mode,
                    }
                ],
            }
        )
        current_segment = normalized_segments[-1]
        timing_rows = normalize_segment_timing(
            current_segment["grid_cells"],
            current_segment["recommended_duration_seconds"],
            storyboard_mode=normalized_mode,
        )
        for idx, timing in enumerate(timing_rows):
            current_segment["grid_cells"][idx]["start_second"] = timing["start_second"]
            current_segment["grid_cells"][idx]["end_second"] = timing["end_second"]
            current_segment["grid_cells"][idx]["duration_seconds"] = timing["duration_seconds"]
            current_segment["grid_cells"][idx]["segment_grid_count"] = current_segment["grid_count"]
            next_cell = current_segment["grid_cells"][idx + 1] if idx + 1 < len(current_segment["grid_cells"]) else None
            current_segment["grid_cells"][idx]["video_prompt_structured"] = resolve_gridcell_video_prompt_structured(
                current_segment["grid_cells"][idx],
                next_cell=next_cell,
                transition_to_next=current_segment["transition_to_next"] if idx == len(current_segment["grid_cells"]) - 1 else "cut",
            )
            if not str(current_segment["grid_cells"][idx].get("image_prompt") or "").strip():
                current_segment["grid_cells"][idx]["image_prompt"] = render_gridcell_image_prompt(current_segment["grid_cells"][idx])
            if not str(current_segment["grid_cells"][idx].get("video_prompt") or "").strip():
                current_segment["grid_cells"][idx]["video_prompt"] = (
                    _render_comic_seedance_video_line(current_segment["grid_cells"][idx]["video_prompt_structured"])
                    if normalized_mode == STORYBOARD_MODE_COMIC
                    else render_gridcell_video_prompt(
                        current_segment["grid_cells"][idx],
                        next_cell=next_cell,
                        transition_to_next=current_segment["transition_to_next"] if idx == len(current_segment["grid_cells"]) - 1 else "cut",
                    )
                )
        current_segment["scene_prompt"] = current_segment["scene_prompt"] or render_segment_scene_prompt(
            summary=summary,
            scene_constraint=scene_constraint,
            scene_refs=scene_refs,
            character_refs=character_refs,
            prop_refs=prop_refs,
            prompt_locks=build_segment_prompt_locks(
                current_segment,
                aspect_ratio=effective_aspect_ratio,
                storyboard_mode=normalized_mode,
            ),
        )
        current_segment["multi_shot_prompt"] = current_segment["multi_shot_prompt"] or render_segment_multi_shot_prompt(
            current_segment["scene_prompt"],
            current_segment["grid_cells"],
            layout_spec=build_segment_layout_spec(
                grid_count=current_segment["grid_count"],
                aspect_ratio=effective_aspect_ratio,
                storyboard_mode=normalized_mode,
            ),
        )
        current_segment["multi_shot_video_prompt"] = current_segment["multi_shot_video_prompt"] or render_segment_video_timeline_prompt(
            current_segment["grid_cells"],
            transition_to_next=current_segment["transition_to_next"],
            storyboard_mode=normalized_mode,
        )

    _apply_story_segment_consistency(normalized_segments, warnings, storyboard_mode=normalized_mode)
    for segment in normalized_segments:
        _apply_asset_whitelist_to_segment(segment, warnings)
        continuity_state = segment.get("continuity_state") or {}
        prompt_locks = build_segment_prompt_locks(
            segment,
            aspect_ratio=effective_aspect_ratio,
            storyboard_mode=normalized_mode,
        )
        layout_spec = prompt_locks.get("layout_spec") or build_segment_layout_spec(
            grid_count=segment.get("grid_count"),
            aspect_ratio=effective_aspect_ratio,
            storyboard_mode=normalized_mode,
        )
        segment["prompt_locks"] = prompt_locks
        segment["layout_spec"] = layout_spec
        anchor_parts = [str(continuity_state.get("scene_anchor") or "").strip()] + list(continuity_state.get("carry_forward") or [])
        anchor_text = "；".join(_dedupe_texts([item for item in anchor_parts if str(item or "").strip()]))
        segment["scene_prompt"] = render_segment_scene_prompt(
            summary=segment.get("summary") or "",
            scene_constraint=anchor_text or segment.get("scene_constraint") or "",
            scene_refs=segment.get("scene_refs") or [],
            character_refs=segment.get("character_refs") or [],
            prop_refs=segment.get("prop_refs") or [],
            binding_suggestions=segment.get("binding_suggestions"),
            prompt_locks=prompt_locks,
        )
        segment["multi_shot_prompt"] = render_segment_multi_shot_prompt(
            segment["scene_prompt"],
            segment.get("grid_cells") or [],
            layout_spec=layout_spec,
        )
        segment["multi_shot_video_prompt"] = (
            _render_comic_segment_video_prompt(
                segment.get("grid_cells") or [],
                transition_to_next=segment.get("transition_to_next") or "cut",
            )
            if normalized_mode == STORYBOARD_MODE_COMIC
            else render_segment_video_timeline_prompt(
                segment.get("grid_cells") or [],
                transition_to_next=segment.get("transition_to_next") or "cut",
                storyboard_mode=normalized_mode,
            )
        )
        if segment.get("warnings"):
            segment["note"] = "连续性检查：" + "；".join(_dedupe_texts([str(item or "").strip() for item in segment.get("warnings") or [] if str(item or "").strip()]))

    return {
        "storyboard_mode": normalized_mode,
        "story_segments": normalized_segments,
        "warnings": warnings,
    }


def _deprecated_normalize_director_draft_payload(
    payload: Dict[str, Any],
    *,
    episode: Episode,
    structured_assets: Dict[str, Any],
    session: Session,
) -> Dict[str, Any]:
    raw_segments = payload.get("segments") or []
    raw_paragraphs = payload.get("paragraphs") or []
    raw_shots = payload.get("shots") or []
    raw_panel_drafts = payload.get("panel_drafts") or []
    warnings: List[str] = []

    if not raw_shots and isinstance(payload.get("data"), list):
        raw_shots = payload.get("data") or []

    normalized_segments: List[Dict[str, Any]] = []
    segment_lookup: Dict[int, Dict[str, Any]] = {}

    for idx, raw in enumerate(raw_segments, start=1):
        segment_no = safe_int(raw.get("segment_no") or raw.get("paragraph_no"), idx)
        segment = {
            "segment_no": segment_no,
            "summary": str(raw.get("summary") or f"剧情片段{segment_no}"),
            "narrative_purpose": str(raw.get("narrative_purpose") or raw.get("narrative_function") or "推进叙事"),
            "emotion": str(raw.get("emotion") or ""),
            "recommended_panel_type": normalize_panel_type(raw.get("recommended_panel_type")),
            "reason": str(raw.get("reason") or ""),
        }
        normalized_segments.append(segment)
        segment_lookup[segment_no] = segment

    if not normalized_segments and raw_paragraphs:
        for idx, raw in enumerate(raw_paragraphs, start=1):
            segment_no = safe_int(raw.get("paragraph_no") or raw.get("segment_no"), idx)
            segment = {
                "segment_no": segment_no,
                "summary": str(raw.get("summary") or raw.get("paragraph_summary") or f"剧情片段{segment_no}"),
                "narrative_purpose": str(raw.get("narrative_function") or "推进叙事"),
                "emotion": str(raw.get("emotion") or ""),
                "recommended_panel_type": normalize_panel_type(raw.get("recommended_panel_type")),
                "reason": str(raw.get("reason") or ""),
            }
            normalized_segments.append(segment)
            segment_lookup[segment_no] = segment

    if not normalized_segments and raw_panel_drafts:
        for idx, raw in enumerate(raw_panel_drafts, start=1):
            segment_no = safe_int(raw.get("segment_no"), idx)
            if segment_no in segment_lookup:
                continue
            segment = {
                "segment_no": segment_no,
                "summary": str(raw.get("segment_summary") or raw.get("original_text") or f"剧情片段{segment_no}"),
                "narrative_purpose": str(raw.get("narrative_purpose") or "推进叙事"),
                "emotion": str(raw.get("emotion") or ""),
                "recommended_panel_type": normalize_panel_type(raw.get("panel_type")),
                "reason": str(raw.get("panel_type_reason") or ""),
            }
            normalized_segments.append(segment)
            segment_lookup[segment_no] = segment

    if not normalized_segments and raw_shots:
        segment = {
            "segment_no": 1,
            "summary": "剧情片段1",
            "narrative_purpose": "推进叙事",
            "emotion": "",
            "recommended_panel_type": PANEL_TYPE_NINE_GRID,
            "reason": "",
        }
        normalized_segments.append(segment)
        segment_lookup[1] = segment

    normalized_paragraphs: List[Dict[str, Any]] = []
    paragraph_lookup: Dict[int, Dict[str, Any]] = {}

    if raw_paragraphs:
        for idx, raw in enumerate(raw_paragraphs, start=1):
            paragraph_no = safe_int(raw.get("paragraph_no") or raw.get("segment_no"), idx)
            segment = segment_lookup.get(paragraph_no)
            paragraph = {
                "paragraph_no": paragraph_no,
                "summary": str(raw.get("summary") or raw.get("paragraph_summary") or (segment or {}).get("summary") or f"段落{paragraph_no}"),
                "scene": str(raw.get("scene") or ""),
                "characters": to_list(raw.get("characters")),
                "emotion": str(raw.get("emotion") or (segment or {}).get("emotion") or ""),
                "narrative_function": normalize_narrative_function(raw.get("narrative_function"), "铺垫"),
                "shot_ids": [],
                "warnings": [],
            }
            normalized_paragraphs.append(paragraph)
            paragraph_lookup[paragraph_no] = paragraph
    else:
        for segment in normalized_segments:
            paragraph_no = segment["segment_no"]
            paragraph = {
                "paragraph_no": paragraph_no,
                "summary": segment["summary"],
                "scene": "",
                "characters": [],
                "emotion": segment["emotion"],
                "narrative_function": normalize_narrative_function(segment["narrative_purpose"], "铺垫"),
                "shot_ids": [],
                "warnings": [],
            }
            normalized_paragraphs.append(paragraph)
            paragraph_lookup[paragraph_no] = paragraph

    normalized_shots: List[Dict[str, Any]] = []
    panel_drafts: List[Dict[str, Any]] = []

    for idx, raw in enumerate(raw_shots, start=1):
        paragraph_no = safe_int(raw.get("paragraph_no") or raw.get("segment_no"), 1)
        if paragraph_no not in paragraph_lookup:
            segment = segment_lookup.get(paragraph_no) or {
                "segment_no": paragraph_no,
                "summary": f"剧情片段{paragraph_no}",
                "narrative_purpose": "推进叙事",
                "emotion": "",
                "recommended_panel_type": PANEL_TYPE_NORMAL,
                "reason": "",
            }
            if paragraph_no not in segment_lookup:
                segment_lookup[paragraph_no] = segment
                normalized_segments.append(segment)
                warnings.append(f"剧情片段{paragraph_no}缺少原始定义，已自动补齐。")
            paragraph = {
                "paragraph_no": paragraph_no,
                "summary": segment["summary"],
                "scene": "",
                "characters": [],
                "emotion": segment["emotion"],
                "narrative_function": normalize_narrative_function(segment["narrative_purpose"], "铺垫"),
                "shot_ids": [],
                "warnings": ["模型未返回该段落定义，已自动补段。"],
            }
            normalized_paragraphs.append(paragraph)
            paragraph_lookup[paragraph_no] = paragraph

        paragraph = paragraph_lookup[paragraph_no]
        segment = segment_lookup.get(paragraph_no) or {
            "segment_no": paragraph_no,
            "summary": paragraph["summary"],
            "narrative_purpose": "推进叙事",
            "emotion": paragraph["emotion"],
            "recommended_panel_type": PANEL_TYPE_NINE_GRID,
            "reason": "",
        }
        shot_id = str(raw.get("shot_id") or f"shot-{idx}")
        candidate_warnings: List[str] = []

        raw_candidates = raw.get("nine_grid_candidates") or []
        normalized_candidates: List[Dict[str, Any]] = []
        for candidate_index, candidate_raw in enumerate(raw_candidates[:9], start=1):
            normalized_candidates.append(
                {
                    "grid_no": safe_int(candidate_raw.get("grid_no"), candidate_index),
                    "shot_size": str(candidate_raw.get("shot_size") or raw.get("shot_size") or "中景"),
                    "angle": str(candidate_raw.get("angle") or "平视"),
                    "subject_position": str(candidate_raw.get("subject_position") or "主体居中"),
                    "composition_focus": str(candidate_raw.get("composition_focus") or raw.get("shot_purpose") or raw.get("visual_content") or "主体动作"),
                    "emotion_effect": str(candidate_raw.get("emotion_effect") or paragraph.get("emotion") or "保持当前情绪"),
                    "usage_note": str(candidate_raw.get("usage_note") or "适合同一镜头的构图备选。"),
                }
            )

        if len(normalized_candidates) < 9:
            candidate_warnings.append(f"镜头 {shot_id} 九宫格候选不足 9 个，已用保底模板补齐。")
            for grid_no in range(len(normalized_candidates) + 1, 10):
                normalized_candidates.append(_placeholder_candidate(grid_no, raw, paragraph))

        recommendations = raw.get("recommended_candidates") or []
        normalized_recommendations: List[Dict[str, Any]] = []
        for item in recommendations[:2]:
            normalized_recommendations.append(
                {
                    "grid_no": safe_int(item.get("grid_no"), 0),
                    "reason": str(item.get("reason") or "更适合当前叙事重点。"),
                }
            )
        if not normalized_recommendations:
            normalized_recommendations.append({"grid_no": 1, "reason": "模型未返回推荐结果，默认使用首个候选。"})
            if len(normalized_candidates) > 1:
                normalized_recommendations.append({"grid_no": 2, "reason": "保底补充第二推荐位，便于人工比较。"})
            candidate_warnings.append(f"镜头 {shot_id} 缺少推荐结果，已自动补默认推荐。")

        recommended_candidate = next(
            (candidate for candidate in normalized_candidates if candidate["grid_no"] == normalized_recommendations[0]["grid_no"]),
            normalized_candidates[0],
        )
        final_prompt_zh = str(raw.get("final_prompt_zh") or "").strip()
        if not final_prompt_zh:
            final_prompt_zh = build_final_prompt(raw, recommended_candidate, paragraph)
            candidate_warnings.append(f"镜头 {shot_id} 缺少正式提示词，已按固定模板补齐。")

        start_frame_prompt = str(raw.get("start_frame_prompt_zh") or "").strip() or None
        end_frame_prompt = str(raw.get("end_frame_prompt_zh") or "").strip() or None
        motion_prompt = build_motion_prompt(
            {
                **raw,
                "start_frame_prompt_zh": start_frame_prompt,
                "end_frame_prompt_zh": end_frame_prompt,
            }
        )

        scene_refs = to_list(raw.get("scene_refs")) or to_list(paragraph.get("scene"))
        character_refs = to_list(raw.get("character_refs")) or paragraph.get("characters") or []
        prop_refs = to_list(raw.get("prop_refs"))
        panel_type = normalize_panel_type(raw.get("panel_type") or segment.get("recommended_panel_type") or PANEL_TYPE_NINE_GRID)
        panel_type_reason = str(raw.get("panel_type_reason") or segment.get("reason") or build_default_panel_type_reason(panel_type, segment))

        normalized_shot = {
            "shot_id": shot_id,
            "sequence": safe_int(raw.get("sequence"), idx),
            "paragraph_no": paragraph_no,
            "shot_type": str(raw.get("shot_type") or ("九宫格分镜" if panel_type == PANEL_TYPE_NINE_GRID else "普通分镜")),
            "shot_size": str(raw.get("shot_size") or recommended_candidate.get("shot_size") or "中景"),
            "visual_content": str(raw.get("visual_content") or raw.get("shot_content") or paragraph.get("summary") or f"镜头{idx}"),
            "shot_purpose": str(raw.get("shot_purpose") or segment.get("narrative_purpose") or "推动叙事"),
            "duration_seconds": float(raw.get("duration_seconds") or 3),
            "scene_refs": scene_refs,
            "character_refs": character_refs,
            "prop_refs": prop_refs,
            "motion_prompt": motion_prompt or None,
            "final_prompt_zh": final_prompt_zh,
            "start_frame_prompt_zh": start_frame_prompt,
            "end_frame_prompt_zh": end_frame_prompt,
            "nine_grid_candidates": normalized_candidates,
            "recommended_candidates": normalized_recommendations,
            "recommended_summary": build_recommended_summary(normalized_recommendations),
            "candidate_summary": build_candidate_summary(normalized_candidates),
            "warnings": candidate_warnings,
        }
        normalized_shots.append(normalized_shot)
        paragraph["shot_ids"].append(shot_id)
        paragraph["warnings"].extend(candidate_warnings)

        if not raw_panel_drafts:
            image_framing = " / ".join(
                [
                    recommended_candidate.get("shot_size") or "中景",
                    recommended_candidate.get("angle") or "平视",
                    recommended_candidate.get("composition_focus") or "主体动作",
                ]
            )
            panel_seed = {
                "original_text": normalized_shot["visual_content"],
                "narrative_purpose": normalized_shot["shot_purpose"],
                "scene_refs": scene_refs,
                "character_refs": character_refs,
                "prop_refs": prop_refs,
                "prompt": normalized_shot["final_prompt_zh"],
                "image_framing": image_framing,
            }
            normalized_nine_grid_prompt = None
            normalized_video_prompt = motion_prompt
            if panel_type == PANEL_TYPE_NINE_GRID:
                normalized_nine_grid_prompt = build_standard_nine_grid_prompt(panel_seed, segment, recommended_candidate)
                normalized_video_prompt = build_standard_nine_grid_video_prompt(panel_seed, segment, recommended_candidate)
            video_prompt = str(raw.get("video_prompt") or "").strip() or None
            if panel_type == PANEL_TYPE_NINE_GRID:
                formatter_seed = {
                    "original_text": normalized_shot["visual_content"],
                    "narrative_purpose": str(raw.get("narrative_purpose") or segment.get("narrative_purpose") or ""),
                    "scene_refs": scene_refs,
                    "character_refs": character_refs,
                    "prop_refs": prop_refs,
                    "prompt": normalized_shot["final_prompt_zh"],
                    "image_framing": image_framing,
                }
                nine_grid_prompt = normalized_nine_grid_prompt
                if not nine_grid_prompt or not is_standard_nine_grid_prompt(nine_grid_prompt):
                    nine_grid_prompt = build_standard_nine_grid_prompt(formatter_seed, segment)
                    warnings.append(f"分镜草稿{normalized_shot['sequence']}的 nine_grid_prompt 已按九格图板格式统一补齐。")
                if not video_prompt or not is_standard_nine_grid_video_prompt(video_prompt):
                    video_prompt = build_standard_nine_grid_video_prompt(formatter_seed, segment)
                    warnings.append(f"分镜草稿{normalized_shot['sequence']}的 video_prompt 已按时间轴格式统一补齐。")
            panel_draft = {
                "sequence": normalized_shot["sequence"],
                "panel_type": panel_type,
                "segment_no": paragraph_no,
                "segment_summary": segment.get("summary") or paragraph.get("summary") or "",
                "narrative_purpose": normalized_shot["shot_purpose"],
                "panel_type_reason": panel_type_reason,
                "scene_refs": scene_refs,
                "character_refs": character_refs,
                "prop_refs": prop_refs,
                "prompt": normalized_shot["final_prompt_zh"],
                "prompt_zh": normalized_shot["final_prompt_zh"],
                "nine_grid_prompt": f"{normalized_shot['recommended_summary']}；{normalized_shot['candidate_summary']}" if panel_type == PANEL_TYPE_NINE_GRID else None,
                "video_prompt": motion_prompt,
                "image_framing": image_framing,
                "original_text": normalized_shot["visual_content"],
                "binding_suggestions": build_panel_binding_suggestions(
                    session,
                    episode.script_id,
                    scene_refs=scene_refs,
                    character_refs=character_refs,
                    prop_refs=prop_refs,
                    structured_assets=structured_assets,
                ),
            }
            if panel_type == PANEL_TYPE_NINE_GRID:
                panel_draft["nine_grid_prompt"] = normalized_nine_grid_prompt
                panel_draft["video_prompt"] = normalized_video_prompt
            panel_drafts.append(panel_draft)

    if raw_panel_drafts:
        for idx, raw in enumerate(raw_panel_drafts, start=1):
            sequence = safe_int(raw.get("sequence"), idx)
            segment_no = safe_int(raw.get("segment_no") or raw.get("paragraph_no"), idx)
            if segment_no not in segment_lookup:
                segment = {
                    "segment_no": segment_no,
                    "summary": f"剧情片段{segment_no}",
                    "narrative_purpose": "推进叙事",
                    "emotion": "",
                    "recommended_panel_type": PANEL_TYPE_NORMAL,
                    "reason": "",
                }
                segment_lookup[segment_no] = segment
                normalized_segments.append(segment)
                warnings.append(f"剧情片段{segment_no}缺少原始定义，已按分镜草稿补齐。")
            segment = segment_lookup[segment_no]
            panel_type = normalize_panel_type(raw.get("panel_type") or segment.get("recommended_panel_type"))
            scene_refs = to_list(raw.get("scene_refs")) or to_list(raw.get("scene"))
            character_refs = to_list(raw.get("character_refs")) or to_list(raw.get("character"))
            prop_refs = to_list(raw.get("prop_refs")) or to_list(raw.get("prop"))
            original_text = str(raw.get("original_text") or raw.get("visual_content") or segment.get("summary") or f"分镜{sequence}")
            prompt = str(raw.get("prompt") or raw.get("prompt_zh") or "").strip()
            if not prompt:
                prompt = build_final_prompt(
                    {
                        "visual_content": original_text,
                        "shot_size": raw.get("shot_size"),
                        "scene_refs": scene_refs,
                        "character_refs": character_refs,
                    },
                    {"shot_size": "中景", "angle": "平视", "composition_focus": "主体动作"},
                    {"summary": segment.get("summary"), "scene": "", "characters": character_refs},
                )
                warnings.append(f"分镜草稿{sequence}缺少正式提示词，已自动补齐。")
            image_framing = build_default_image_framing(panel_type, raw)
            nine_grid_prompt = str(raw.get("nine_grid_prompt") or "").strip() or None
            if panel_type == PANEL_TYPE_NINE_GRID and not nine_grid_prompt:
                nine_grid_prompt = build_default_nine_grid_prompt(
                    {
                        "original_text": original_text,
                        "narrative_purpose": raw.get("narrative_purpose"),
                    },
                    segment,
                )
                warnings.append(f"分镜草稿{sequence}为九宫格分镜但缺少 nine_grid_prompt，已自动补齐。")

            panel_draft = {
                "sequence": sequence,
                "panel_type": panel_type,
                "segment_no": segment_no,
                "segment_summary": str(raw.get("segment_summary") or segment.get("summary") or ""),
                "narrative_purpose": str(raw.get("narrative_purpose") or segment.get("narrative_purpose") or "推进叙事"),
                "panel_type_reason": str(raw.get("panel_type_reason") or segment.get("reason") or build_default_panel_type_reason(panel_type, segment)),
                "scene_refs": scene_refs,
                "character_refs": character_refs,
                "prop_refs": prop_refs,
                "prompt": prompt,
                "prompt_zh": str(raw.get("prompt_zh") or prompt),
                "nine_grid_prompt": nine_grid_prompt if panel_type == PANEL_TYPE_NINE_GRID else (str(raw.get("nine_grid_prompt") or "").strip() or None),
                "video_prompt": video_prompt,
                "image_framing": image_framing,
                "original_text": original_text,
                "binding_suggestions": build_panel_binding_suggestions(
                    session,
                    episode.script_id,
                    scene_refs=scene_refs,
                    character_refs=character_refs,
                    prop_refs=prop_refs,
                    structured_assets=structured_assets,
                ),
            }
            panel_drafts.append(panel_draft)

        if not normalized_shots:
            normalized_shots = [synthesize_shot_from_panel_draft(item) for item in panel_drafts]

    normalized_shots.sort(key=lambda item: item["sequence"])
    panel_drafts.sort(key=lambda item: item["sequence"])
    normalized_segments.sort(key=lambda item: item["segment_no"])
    normalized_paragraphs.sort(key=lambda item: item["paragraph_no"])

    for panel_draft in panel_drafts:
        paragraph_no = safe_int(panel_draft.get("segment_no"), 0)
        paragraph = paragraph_lookup.get(paragraph_no)
        if paragraph:
            shot_id = f"panel-{panel_draft.get('sequence') or 0}"
            if shot_id not in paragraph["shot_ids"]:
                paragraph["shot_ids"].append(shot_id)

    for shot in normalized_shots:
        warnings.extend(shot.get("warnings") or [])

    if not normalized_shots and panel_drafts:
        normalized_shots = [synthesize_shot_from_panel_draft(item) for item in panel_drafts]

    if not normalized_shots:
        raise ValueError("No valid shots were extracted from the script.")

    if not panel_drafts:
        raise ValueError("No valid panel drafts were derived from the director draft.")

    return {
        "director_draft": {
            "segments": normalized_segments,
            "paragraphs": normalized_paragraphs,
            "shots": normalized_shots,
            "summary": {
                "paragraph_count": len(normalized_paragraphs),
                "shot_count": len(normalized_shots),
                "recommended_count": sum(len(item.get("recommended_candidates") or []) for item in normalized_shots),
                "warning_count": len(warnings),
            },
        },
        "panel_drafts": panel_drafts,
        "warnings": warnings,
    }


_legacy_normalize_director_draft_payload = _deprecated_normalize_director_draft_payload
# Backward-compatible export for old ai_director/router imports during mixed-version deploys.
normalize_director_draft_payload = _deprecated_normalize_director_draft_payload


def _resolve_storyboard_mode_raw_map(items: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    result: Dict[int, Dict[str, Any]] = {}
    for index, item in enumerate(items or [], start=1):
        result[safe_int(item.get("sequence"), index)] = item
    return result


def _build_storyboard_mode_text_fields(
    mode: str,
    draft: Dict[str, Any],
    raw_source: Dict[str, Any],
) -> Dict[str, Any]:
    narration_text = (
        raw_source.get("narration_text")
        or draft.get("narration_text")
        or (draft.get("original_text") if mode == STORYBOARD_MODE_COMMENTARY else "")
    )
    dialogue_text = (
        raw_source.get("dialogue_text")
        or draft.get("dialogue_text")
        or (draft.get("original_text") if mode == STORYBOARD_MODE_COMIC else "")
    )
    return {
        "narration_text": str(narration_text or "").strip() or None,
        "dialogue_text": str(dialogue_text or "").strip() or None,
    }


def _enrich_panel_drafts_by_storyboard_mode(
    panel_drafts: List[Dict[str, Any]],
    *,
    shots: List[Dict[str, Any]],
    raw_panel_drafts: List[Dict[str, Any]],
    storyboard_mode: str,
) -> List[Dict[str, Any]]:
    shot_raw_map = _resolve_storyboard_mode_raw_map(shots)
    draft_raw_map = _resolve_storyboard_mode_raw_map(raw_panel_drafts)
    previous_segment_no: Optional[int] = None
    enriched: List[Dict[str, Any]] = []

    for draft in sorted(panel_drafts or [], key=lambda item: safe_int(item.get("sequence"), 0)):
        sequence = safe_int(draft.get("sequence"), 0)
        segment_no = safe_int(draft.get("segment_no"), 0)
        raw_source = draft_raw_map.get(sequence) or shot_raw_map.get(sequence) or {}
        text_fields = _build_storyboard_mode_text_fields(storyboard_mode, draft, raw_source)

        inferred_segment_break = storyboard_mode != STORYBOARD_MODE_COMIC
        if storyboard_mode == STORYBOARD_MODE_COMIC:
            inferred_segment_break = previous_segment_no is None or previous_segment_no != segment_no

        next_payload = {
            **draft,
            **text_fields,
            "storyboard_mode": storyboard_mode,
            "segment_break": (
                bool(raw_source.get("segment_break"))
                if raw_source.get("segment_break") is not None
                else bool(draft.get("segment_break")) or inferred_segment_break
            ),
            "shot_type": str(raw_source.get("shot_type") or draft.get("shot_type") or "").strip() or None,
            "camera_motion": str(
                raw_source.get("camera_motion")
                or raw_source.get("motion_prompt")
                or draft.get("camera_motion")
                or draft.get("video_prompt")
                or ""
            ).strip() or None,
            "composition": (
                raw_source.get("composition")
                or raw_source.get("composition_focus")
                or draft.get("composition")
                or ""
            ),
            "transition_to_next": (
                str(
                    raw_source.get("transition_to_next")
                    or draft.get("transition_to_next")
                    or ("承接上一镜继续推进" if storyboard_mode == STORYBOARD_MODE_COMIC and not inferred_segment_break else "")
                ).strip()
                or None
            ),
        }
        normalized = normalize_panel_storyboard_payload(
            next_payload,
            fallback_mode=storyboard_mode,
            force_mode=storyboard_mode,
        )
        normalized["sequence"] = sequence
        normalized["segment_no"] = segment_no
        normalized["scene_refs"] = draft.get("scene_refs") or []
        normalized["character_refs"] = draft.get("character_refs") or []
        normalized["prop_refs"] = draft.get("prop_refs") or []
        normalized["prompt"] = str(draft.get("prompt") or "")
        normalized["prompt_zh"] = str(draft.get("prompt_zh") or draft.get("prompt") or "")
        normalized["video_prompt"] = str(draft.get("video_prompt") or normalized.get("video_prompt") or "")
        normalized["nine_grid_prompt"] = str(draft.get("nine_grid_prompt") or "")
        normalized["segment_summary"] = str(draft.get("segment_summary") or "")
        normalized["narrative_purpose"] = str(draft.get("narrative_purpose") or "")
        normalized["panel_type_reason"] = str(draft.get("panel_type_reason") or "")
        normalized["binding_suggestions"] = draft.get("binding_suggestions")
        enriched.append(normalized)
        previous_segment_no = segment_no

    return enriched


def build_commentary_segment_prompt() -> str:
    """解说模式分镜拆分提示词

    核心原则：
    - 保留原文，不改编、不删减、不添加小说原文内容
    - 朗读节奏：每片段约 4 秒（约 20-24 个中文字）
    - 在自然断句处拆分（。！？…段落边界）
    - segment_break=True：时间跳跃、空间转换、情节转折
    - 生成 narration_text（原样保留原文）
    - shot_type/camera_motion/composition 参考 ArcReel
    """
    return """【解说模式分割规则】

你的任务是为竖屏解说视频生成分镜剧本。请仔细遵循以下指示：

**重要：所有输出内容必须使用中文。仅 JSON 键名和枚举值使用英文。**

1. 分段规则：
   - 每片段时长：4、6 或 8 秒
   - 在自然断句处拆分（句号、问号、感叹号、省略号、段落边界）
   - segment_break=True：时间跳跃、空间转换、情节转折
   - segment_break=False：同一连续场景内

2. 为每个片段生成：
   - narration_text：原样复制小说原文，不做任何修改
   - characters_in_segment：列出本片段中出场的角色
   - shot_type：镜头类型（Extreme Close-up/Close-up/Medium Close-up/Medium Shot/Medium Long Shot/Long Shot/Extreme Long Shot/Over-the-shoulder/Point-of-view）
   - camera_motion：镜头运动（Static/Pan Left/Pan Right/Tilt Up/Tilt Down/Zoom In/Zoom Out/Tracking Shot）
   - composition：包含 lighting 和 ambiance 的场景氛围描述
   - video_prompt：动作和音效的视频生成提示词

3. 输出格式（JSON）：
{
  "segments": [
    {
      "segment_id": "E{集}S{序号}",
      "duration_seconds": 4,
      "segment_break": false,
      "narration_text": "裴与出征后的第二年...",
      "characters_in_segment": ["裴将军", "小兵"],
      "shot_type": "Medium Shot",
      "camera_motion": "Static",
      "composition": {
        "lighting": "自然光源，正面光",
        "ambiance": "战场氛围，黄昏时分"
      },
      "video_prompt": {
        "action": "裴将军骑马巡视战场",
        "camera_motion": "Tracking Shot",
        "ambiance_audio": "风声、马蹄声"
      }
    }
  ]
}"""


def build_comic_segment_prompt() -> str:
    """漫剧模式分镜拆分提示词

    核心原则：
    - 以角色对话和动作为主
    - 每场景 8 秒
    - 对话内容完整保留
    - 需要建立分镜间依赖（通过 dependency_panel_id）
    - segment_break=True：场景切换，打断依赖链
    """
    return """【漫剧模式分割规则】

你的任务是为横屏漫剧视频生成分镜剧本。请仔细遵循以下指示：

**重要：所有输出内容必须使用中文。仅 JSON 键名和枚举值使用英文。**

1. 分段规则：
   - 每场景时长：8 秒
   - segment_break=True：场景切换，打断依赖链
   - segment_break=False：同一连续场景，角色动作保持连贯
   - 需要建立分镜间依赖关系

2. 为每个场景生成：
   - dialogue_text：角色对话原文，完整保留
   - characters_in_scene：出场的角色
   - shot_type：镜头类型
   - camera_motion：镜头运动
   - composition：场景氛围描述
   - transition_to_next：场景切换方式（cut/fade/dissolve）

3. 输出格式（JSON）：
{
  "scenes": [
    {
      "scene_id": "E{集}S{序号}",
      "duration_seconds": 8,
      "segment_break": false,
      "dialogue_text": "角色A：今天天气真好！\\n角色B：是啊，适合出游。",
      "characters_in_scene": ["角色A", "角色B"],
      "shot_type": "Medium Shot",
      "camera_motion": "Static",
      "composition": {
        "lighting": "自然光源，温暖色调",
        "ambiance": "户外公园，阳光明媚"
      },
      "transition_to_next": "cut",
      "video_prompt": {
        "action": "两人边走边聊",
        "camera_motion": "Tracking Shot"
      }
    }
  ]
}"""


def build_story_segment_asset_guardrail(structured_assets: Dict[str, Any]) -> str:
    def _names(rows: List[Dict[str, Any]]) -> List[str]:
        return [str(item.get("name") or "").strip() for item in rows or [] if str(item.get("name") or "").strip()]

    characters = _names(structured_assets.get("characters") or [])
    scenes = _names(structured_assets.get("scenes") or [])
    props = _names(structured_assets.get("props") or [])

    return (
        "可用资产清单（只有这些名字允许使用 @ 引用；不在清单里的对象只能写普通文本，不能加 @）：\n"
        f"- 人物资产：{'、'.join(characters) if characters else '无'}\n"
        f"- 场景资产：{'、'.join(scenes) if scenes else '无'}\n"
        f"- 道具资产：{'、'.join(props) if props else '无'}\n"
        "如果想引用某个对象，但它不在以上资产清单中，就只能输出普通中文名称，绝对不要写成 @对象。\n"
        "严禁新造 @资产；未命中清单的对象不能带 @，只能保留为普通中文描述。"
    )


ASSET_MENTION_RE = re.compile(r"@([^\s@，。；：、“”\"'（）()\[\]\n\r]+)")
CONTINUITY_BODY_KEYWORDS = [
    "反绑", "被绑", "绑在", "捆住", "悬吊", "悬挂", "吊在", "吊于", "跪地", "跪着", "跪伏",
    "湿透", "淋湿", "受伤", "流血", "勒住", "昏迷", "倒地", "落水", "骑马", "勒马", "持剑", "持刀", "持枪", "抱着"
]
CONTINUITY_COSTUME_KEYWORDS = [
    "囚衣", "白衣", "素白囚衣", "素衣", "嫁衣", "宫装", "长袍", "披风", "战甲", "铠甲", "甲胄", "官服", "太监服", "战袍"
]
STATE_RESET_MARKERS = [
    "不再", "未绑", "解绑", "松开", "绳索已断", "绳子已断", "脱困", "获救", "被救上来", "上岸", "换装", "换衣", "脱下"
]


def _split_continuity_clauses(*values: Any) -> List[str]:
    clauses: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        for item in re.split(r"[，。；：\n\r]+", text):
            clause = str(item or "").strip()
            if clause:
                clauses.append(clause)
    return clauses


def _dedupe_texts(values: List[str]) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalize_asset_name(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("@"):
        text = text[1:].strip()
    return text


def _normalize_asset_name_list(values: List[str]) -> List[str]:
    rows: List[str] = []
    seen: Set[str] = set()
    for value in values or []:
        text = _normalize_asset_name(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(text)
    return rows


def _clean_prompt_clause(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"【[^】]+】", "", text)
    text = re.sub(r"\s+", " ", text).strip("；;，,。 ")
    return text


def _compact_prompt_clauses(values: List[str], *, limit: int = 2) -> List[str]:
    rows: List[str] = []
    seen: Set[str] = set()
    for value in values or []:
        for item in re.split(r"[；;。]+", str(value or "").strip()):
            text = _clean_prompt_clause(item)
            if not text or _is_low_information_text(text):
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(text)
            if len(rows) >= limit:
                return rows
    return rows


def _sanitize_asset_mentions_text(text: str, allowed_names: List[str]) -> tuple[str, List[str]]:
    allowed = {str(name or "").strip() for name in allowed_names if str(name or "").strip()}
    missing: List[str] = []

    def _replace(match: re.Match[str]) -> str:
        raw_name = str(match.group(1) or "").strip()
        if raw_name in allowed:
            return f"@{raw_name}"
        missing.append(raw_name)
        return raw_name

    normalized = ASSET_MENTION_RE.sub(_replace, str(text or "").strip())
    return normalized, _dedupe_texts(missing)


def _sanitize_asset_mentions_list(values: List[str], allowed_names: List[str]) -> tuple[List[str], List[str]]:
    sanitized: List[str] = []
    missing: List[str] = []
    for value in values or []:
        next_value, current_missing = _sanitize_asset_mentions_text(str(value or "").strip(), allowed_names)
        if next_value:
            sanitized.append(next_value)
        missing.extend(current_missing)
    return _dedupe_texts(sanitized), _dedupe_texts(missing)


def _infer_cell_refs_from_text(texts: List[str], refs: List[str], *, fallback: Optional[List[str]] = None) -> List[str]:
    available = [str(item or "").strip() for item in refs or [] if str(item or "").strip()]
    matched: List[str] = []
    for ref in available:
        patterns = [f"@{ref}", ref]
        haystack = "\n".join([str(item or "") for item in texts])
        if any(pattern in haystack for pattern in patterns):
            matched.append(ref)
    if matched:
        return _dedupe_texts(matched)
    return list(fallback or [])


def _extract_character_state_clauses(character_name: str, texts: List[str], keywords: List[str], *, allow_global: bool = False) -> List[str]:
    clauses = []
    for clause in _split_continuity_clauses(*texts):
        if not any(keyword in clause for keyword in keywords):
            continue
        if character_name and (character_name in clause or f"@{character_name}" in clause):
            clauses.append(clause)
        elif allow_global:
            clauses.append(clause)
    return _dedupe_texts(clauses)


def _build_segment_continuity_state(segment: Dict[str, Any], *, previous_state: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    characters = [str(item or "").strip() for item in segment.get("character_refs") or [] if str(item or "").strip()]
    scenes = [str(item or "").strip() for item in segment.get("scene_refs") or [] if str(item or "").strip()]
    props = [str(item or "").strip() for item in segment.get("prop_refs") or [] if str(item or "").strip()]
    segment_texts = [
        segment.get("summary"),
        segment.get("scene_constraint"),
        segment.get("scene_prompt"),
        segment.get("continuity_note"),
        segment.get("segment_prompt_summary"),
        (segment.get("text_span") or {}).get("source_excerpt"),
    ]
    for cell in segment.get("grid_cells") or []:
        if not isinstance(cell, dict):
            continue
        segment_texts.extend([
            cell.get("shot_description"),
            cell.get("action_description"),
            cell.get("dialogue_excerpt"),
            cell.get("composition"),
            cell.get("image_prompt"),
            cell.get("video_prompt"),
        ])

    costume_state: Dict[str, List[str]] = {}
    body_state: Dict[str, List[str]] = {}
    allow_global = len(characters) == 1
    for character in characters:
        costume_state[character] = _extract_character_state_clauses(character, segment_texts, CONTINUITY_COSTUME_KEYWORDS, allow_global=allow_global)
        body_state[character] = _extract_character_state_clauses(character, segment_texts, CONTINUITY_BODY_KEYWORDS, allow_global=allow_global)

    prop_state: List[str] = []
    for prop in props:
        for clause in _split_continuity_clauses(*segment_texts):
            if prop in clause or f"@{prop}" in clause:
                prop_state.append(clause)
    prop_state = _dedupe_texts(prop_state)

    carry_forward = _dedupe_texts(
        [item for values in costume_state.values() for item in values]
        + [item for values in body_state.values() for item in values]
        + prop_state
    )

    scene_anchor = str(segment.get("scene_constraint") or "").strip()
    if not scene_anchor:
        scene_anchor = _join_asset_tokens(scenes, "")
    if not scene_anchor and previous_state:
        scene_anchor = str(previous_state.get("scene_anchor") or "").strip()

    return {
        "scene_anchor": scene_anchor,
        "characters": characters,
        "costume_state": {key: value for key, value in costume_state.items() if value},
        "body_state": {key: value for key, value in body_state.items() if value},
        "prop_state": prop_state,
        "carry_forward": carry_forward,
    }


def _continuity_state_summary(state: Optional[Dict[str, Any]]) -> str:
    if not state:
        return ""
    parts: List[str] = []
    if str(state.get("scene_anchor") or "").strip():
        parts.append(f"场景锚点：{str(state.get('scene_anchor') or '').strip()}")
    if state.get("characters"):
        parts.append("出镜人物：" + "、".join(state.get("characters") or []))
    carry = [str(item or "").strip() for item in state.get("carry_forward") or [] if str(item or "").strip()]
    if carry:
        parts.append("必须延续：" + "；".join(carry))
    return "\n".join(parts)


def _segment_declares_explicit_state_change(segment: Dict[str, Any]) -> bool:
    text = "\n".join(_split_continuity_clauses(
        segment.get("summary"),
        segment.get("continuity_note"),
        segment.get("segment_prompt_summary"),
        (segment.get("text_span") or {}).get("source_excerpt"),
    ))
    return any(marker in text for marker in STATE_RESET_MARKERS)


def _apply_asset_whitelist_to_segment(segment: Dict[str, Any], warnings: List[str]) -> None:
    allowed_names = list(segment.get("scene_refs") or []) + list(segment.get("character_refs") or []) + list(segment.get("prop_refs") or [])
    illegal_mentions: List[str] = []
    for key in ("summary", "scene_constraint", "scene_prompt", "continuity_note", "segment_prompt_summary", "multi_shot_prompt", "multi_shot_video_prompt"):
        next_text, missing = _sanitize_asset_mentions_text(segment.get(key) or "", allowed_names)
        segment[key] = next_text
        illegal_mentions.extend(missing)
    text_span = segment.get("text_span") if isinstance(segment.get("text_span"), dict) else {}
    next_excerpt, missing = _sanitize_asset_mentions_text(text_span.get("source_excerpt") or "", allowed_names)
    text_span["source_excerpt"] = next_excerpt
    segment["text_span"] = text_span
    illegal_mentions.extend(missing)
    for cell in segment.get("grid_cells") or []:
        if not isinstance(cell, dict):
            continue
        for key in ("shot_description", "action_description", "dialogue_excerpt", "composition", "image_prompt", "video_prompt"):
            next_text, missing = _sanitize_asset_mentions_text(cell.get(key) or "", allowed_names)
            cell[key] = next_text
            illegal_mentions.extend(missing)
    if illegal_mentions:
        segment.setdefault("warnings", [])
        warning_text = "非法 @资产已降级为普通文本：" + "、".join(_dedupe_texts(illegal_mentions))
        segment["warnings"] = _dedupe_texts(list(segment.get("warnings") or []) + [warning_text])
        warnings.append(warning_text)


def build_segment_layout_spec(
    *,
    grid_count: Any,
    aspect_ratio: Optional[str],
    storyboard_mode: Optional[str],
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    safe_grid_count = normalize_grid_count(grid_count)
    safe_aspect_ratio = str(aspect_ratio or "").strip()
    if safe_aspect_ratio not in {"16:9", "9:16"}:
        safe_aspect_ratio = "16:9" if normalized_mode == STORYBOARD_MODE_COMIC else "9:16"

    if safe_grid_count <= 1:
        return {
            "grid_count": 1,
            "aspect_ratio": safe_aspect_ratio,
            "layout_code": "single",
            "layout_label": "单图",
            "layout_prompt": "输出为一张单图，不要分格，不要拼板。",
            "layout_requirements": [],
            "border_style": "narrow_black",
            "is_multigrid": False,
        }

    if safe_grid_count == 2:
        is_horizontal = safe_aspect_ratio == "16:9"
        layout_code = "grid_1x2" if is_horizontal else "grid_2x1"
        layout_label = "横向 1x2" if is_horizontal else "纵向 2x1"
        layout_prompt = (
            "输出为一张严格双宫格拼板图。"
            + ("双宫格在当前画幅下采用 1x2 横向并列布局。" if is_horizontal else "双宫格在当前画幅下采用 2x1 纵向上下布局。")
        )
    elif safe_grid_count == 4:
        layout_code = "grid_2x2"
        layout_label = "2x2"
        layout_prompt = "输出为一张严格 2x2 四宫格拼板图。"
    elif safe_grid_count == 6:
        layout_code = "grid_2x3"
        layout_label = "2x3"
        layout_prompt = "输出为一张严格 2x3 六宫格拼板图。"
    else:
        layout_code = "grid_3x3"
        layout_label = "3x3"
        layout_prompt = "输出为一张严格 3x3 九宫格拼板图。"

    return {
        "grid_count": safe_grid_count,
        "aspect_ratio": safe_aspect_ratio,
        "layout_code": layout_code,
        "layout_label": layout_label,
        "layout_prompt": layout_prompt,
        "layout_requirements": [
            "所有宫格必须完整占位，整张图片只能是一张固定拼板图。",
            "所有宫格统一极窄黑边、统一外边距、统一格间距。",
            "禁止自由拼贴、禁止瀑布流、禁止不规则构图替代宫格。",
            "严格禁止任何文字、字幕、景别标签、对白气泡、注释、水印、logo 或说明文字出现在宫格内外。",
        ],
        "border_style": "narrow_black",
        "is_multigrid": True,
    }


def build_segment_prompt_locks(
    segment: Dict[str, Any],
    *,
    aspect_ratio: Optional[str],
    storyboard_mode: Optional[str],
) -> Dict[str, Any]:
    continuity_state = segment.get("continuity_state") if isinstance(segment.get("continuity_state"), dict) else _build_segment_continuity_state(segment)
    layout_spec = build_segment_layout_spec(
        grid_count=segment.get("grid_count"),
        aspect_ratio=aspect_ratio,
        storyboard_mode=storyboard_mode,
    )
    scene_refs = _normalize_asset_name_list(segment.get("scene_refs") or [])
    character_refs = _normalize_asset_name_list(segment.get("character_refs") or [])
    prop_refs = _normalize_asset_name_list(segment.get("prop_refs") or [])
    costume_state = continuity_state.get("costume_state") if isinstance(continuity_state.get("costume_state"), dict) else {}
    body_state = continuity_state.get("body_state") if isinstance(continuity_state.get("body_state"), dict) else {}
    prop_state = continuity_state.get("prop_state") if isinstance(continuity_state.get("prop_state"), list) else []

    character_lock: List[str] = []
    for character in character_refs or _normalize_asset_name_list(continuity_state.get("characters") or []):
        rows = _compact_prompt_clauses(list(costume_state.get(character) or []) + list(body_state.get(character) or []), limit=2)
        if rows:
            character_lock.append(f"{_asset_token(character)}：{'；'.join(rows)}")
        else:
            character_lock.append(f"{_asset_token(character)}：保持人物外观、服装与表情连续")

    scene_lock: List[str] = []
    scene_anchor = _clean_prompt_clause(continuity_state.get("scene_anchor") or "")
    if scene_anchor:
        scene_lock.append(resolve_segment_asset_mentions(scene_anchor, scene_refs=scene_refs, character_refs=character_refs, prop_refs=prop_refs))
    elif scene_refs:
        scene_lock.append(f"{_join_asset_tokens(scene_refs)}保持场景空间方向、背景关系与光线基调稳定。")
    scene_lock = _dedupe_texts(scene_lock)

    prop_lock: List[str] = []
    for prop in prop_refs:
        matched = [item for item in prop_state if _normalize_asset_name(prop) in _normalize_asset_name(str(item or ""))]
        rows = _compact_prompt_clauses(matched, limit=2)
        if rows:
            prop_lock.append(f"{_asset_token(prop)}：{'；'.join(rows)}")
        else:
            prop_lock.append(f"{_asset_token(prop)}：保持关键道具状态连续")

    base_summary = resolve_segment_asset_mentions(
        str(segment.get("scene_constraint") or segment.get("summary") or "").strip(),
        scene_refs=scene_refs,
        character_refs=character_refs,
        prop_refs=prop_refs,
    )
    global_constraints = [item for item in [_clean_prompt_clause(base_summary)] if item]
    global_constraints.append("保持同一分镜内所有宫格共享同一组角色、场景和道具锁定，不允许任何宫格自行漂移。")
    if layout_spec.get("is_multigrid"):
        global_constraints.append("所有宫格必须共同讲述同一段连续剧情，不允许把单格画成互不相关的独立场景。")
        global_constraints.append("严格去掉所有可见文字元素，不允许在宫格内外出现汉字、字幕、标签、水印、logo 或英文字母。")

    return {
        "character_lock": _dedupe_texts(character_lock),
        "scene_lock": scene_lock,
        "prop_lock": _dedupe_texts(prop_lock),
        "global_constraints": _dedupe_texts(global_constraints),
        "continuity_state": continuity_state,
        "layout_spec": layout_spec,
    }

def _apply_story_segment_consistency(
    story_segments: List[Dict[str, Any]],
    warnings: List[str],
    *,
    storyboard_mode: str,
    initial_previous_state: Optional[Dict[str, Any]] = None,
) -> None:
    previous_state: Optional[Dict[str, Any]] = initial_previous_state
    for index, segment in enumerate(story_segments, start=1):
        segment.setdefault("warnings", [])
        current_state = _build_segment_continuity_state(segment, previous_state=previous_state)
        if previous_state and not _segment_declares_explicit_state_change(segment):
            missing_clauses = []
            current_text = "\n".join(_split_continuity_clauses(
                segment.get("summary"),
                segment.get("continuity_note"),
                segment.get("scene_prompt"),
                segment.get("segment_prompt_summary"),
                (segment.get("text_span") or {}).get("source_excerpt"),
            ))
            for clause in previous_state.get("carry_forward") or []:
                text = str(clause or "").strip()
                if not text:
                    continue
                if text in current_text:
                    continue
                keyword_hit = any(keyword in current_text for keyword in CONTINUITY_BODY_KEYWORDS + CONTINUITY_COSTUME_KEYWORDS)
                if keyword_hit and not any(keyword in text for keyword in CONTINUITY_BODY_KEYWORDS + CONTINUITY_COSTUME_KEYWORDS):
                    continue
                missing_clauses.append(text)
            if missing_clauses:
                merged_note = "；".join(_dedupe_texts([segment.get("continuity_note") or ""] + missing_clauses)).strip("；")
                segment["continuity_note"] = merged_note
                warning_text = f"分镜{index}已自动补入连续性约束：{'；'.join(_dedupe_texts(missing_clauses))}"
                segment["warnings"] = _dedupe_texts(list(segment.get("warnings") or []) + [warning_text])
                warnings.append(warning_text)
                current_state = _build_segment_continuity_state(segment, previous_state=previous_state)

        if storyboard_mode == STORYBOARD_MODE_COMIC:
            continuity_anchor_parts = []
            if current_state.get("scene_anchor"):
                continuity_anchor_parts.append(str(current_state.get("scene_anchor") or "").strip())
            continuity_anchor_parts.extend(current_state.get("carry_forward") or [])
            if continuity_anchor_parts:
                anchor_text = "；".join(_dedupe_texts([item for item in continuity_anchor_parts if str(item or "").strip()]))
                if anchor_text and anchor_text not in str(segment.get("scene_constraint") or ""):
                    segment["scene_constraint"] = anchor_text

        segment["continuity_state"] = current_state
        previous_state = current_state


def build_commentary_story_segment_prompt_v2() -> str:
    return """【解说模式 · 多宫格剧情片段拆分规则】
你是短剧/漫剧 AI 导演，需要把输入文本拆成 story_segments 数组。
重要要求：
1. 使用中文输出，JSON 键名除外。
2. 必须先拆连续剧情片段，再给每个片段分配 grid_count。
3. commentary 模式优先按自然朗读边界、原文信息密度、推荐时长来决定片段。
4. 画面描述必须只写“此刻镜头可见的事实”，禁止抽象比喻、跨时间跳跃、多场景并列。
5. 视频动作描述要克制，聚焦单一缓慢动作、气氛变化或情绪推进。
6. grid_count 只能是 1 / 2 / 4 / 6 / 9。

返回 JSON 对象：
{
  "story_segments": [
    {
      "sequence_num": 1,
      "title": "片段标题",
      "summary": "片段摘要",
      "text_span": {
        "source_excerpt": "原文摘录",
        "start_offset": null,
        "end_offset": null
      },
      "recommended_duration_seconds": 4,
      "grid_count": 2,
      "pacing": "slow|medium|fast",
      "rhythm": "朗读节奏说明",
      "scene_constraint": "这一片段中空间关系、人物位置、道具关系、气氛的统一约束",
      "continuity_note": "与前后片段的衔接说明",
      "transition_to_next": "cut|fade|dissolve",
      "character_refs": [],
      "scene_refs": [],
      "prop_refs": [],
      "segment_prompt_summary": "这一片段的主视觉摘要",
      "grid_cells": [
        {
          "cell_index": 1,
          "shot_description": "当前格可见画面描述",
          "action_description": "当前格动作/变化",
          "dialogue_excerpt": "当前格对应解说摘录",
          "shot_type": "景别",
          "camera_motion": "运镜",
          "composition": "构图",
          "lighting": "光线",
          "ambiance": "氛围",
          "image_prompt_structured": {
            "scene": "当前格可见画面事实",
            "composition": {
              "shot_type": "景别",
              "lighting": "光线",
              "ambiance": "氛围"
            }
          },
          "video_prompt_structured": {
            "action": "单一连续动作或氛围变化",
            "camera_motion": "运镜",
            "ambiance_audio": "仅画内音，不含 BGM",
            "dialogue": []
          },
          "character_refs": [],
          "scene_refs": [],
          "prop_refs": []
        }
      ]
    }
  ]
}
只返回 JSON，不要代码块，不要解释。"""


def build_comic_story_segment_prompt_v2() -> str:
    return """【漫剧模式 · 多宫格剧情片段拆分规则】
你是漫剧 AI 导演，需要先定义 Scene 级连续剧情片段，再把每个片段拆成 GridCell 镜头节点。
重要要求：
1. 使用中文输出，JSON 键名除外。
2. 先拆连续剧情片段，再给每个片段分配 grid_count。
3. comic 模式优先按动作推进、人物状态变化、对白节奏、情绪爆点决定片段。
4. 同一片段内所有宫格共享一个 Scene 总场景约束：人物位置、场景状态、道具关系、朝向要连续。
5. 单个 GridCell 只允许一个主动作焦点、一个主 camera motion。
6. 禁止输出 panel_type / recommended_panel_type / nine_grid_prompt / panel_type_reason。
7. grid_count 只能是 1 / 2 / 4 / 6 / 9。

返回 JSON 对象：
{
  "story_segments": [
    {
      "sequence_num": 1,
      "title": "片段标题",
      "summary": "剧情片段摘要",
      "text_span": {
        "source_excerpt": "对白或动作原文摘录",
        "start_offset": null,
        "end_offset": null
      },
      "recommended_duration_seconds": 8,
      "grid_count": 4,
      "pacing": "slow|medium|fast",
      "rhythm": "动作与对白节奏说明",
      "scene_constraint": "这一片段中空间关系、人物位置、道具关系、朝向、气氛的统一约束",
      "continuity_note": "与前后片段的动作/状态衔接说明",
      "transition_to_next": "cut|fade|dissolve",
      "character_refs": [],
      "scene_refs": [],
      "prop_refs": [],
      "segment_prompt_summary": "这一片段的主视觉和主动作摘要",
      "grid_cells": [
        {
          "cell_index": 1,
          "shot_description": "当前格拍到什么",
          "action_description": "主体动作 + 表演",
          "dialogue_excerpt": "当前格对白",
          "shot_type": "景别",
          "camera_motion": "运镜",
          "camera_position": "机位",
          "camera_direction": "朝向",
          "shot_purpose": "镜头功能",
          "composition": "构图",
          "lighting": "光线",
          "ambiance": "氛围",
          "image_prompt_structured": {
            "scene": "当前格可见画面事实",
            "composition": {
              "shot_type": "景别",
              "lighting": "光线",
              "ambiance": "氛围"
            }
          },
          "video_prompt_structured": {
            "action": "当前格主动作",
            "camera_motion": "运镜",
            "ambiance_audio": "仅画内音，不含 BGM",
            "dialogue": []
          },
          "character_refs": [],
          "scene_refs": [],
          "prop_refs": []
        }
      ]
    }
  ]
}
只返回 JSON，不要代码块，不要解释。"""


def build_segment_scene_constraint(
    *,
    summary: str,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
    continuity_note: str = "",
) -> str:
    scene_text = "、".join(scene_refs) if scene_refs else "当前场景"
    character_text = "、".join(character_refs) if character_refs else "主体人物"
    prop_text = f"，涉及道具：{'、'.join(prop_refs)}" if prop_refs else ""
    continuity_text = f"；连续性要求：{continuity_note}" if continuity_note else ""
    return f"{scene_text}中，{character_text}围绕“{summary or '当前剧情片段'}”展开连续表演{prop_text}{continuity_text}。"


def _split_dialogue_lines(value: str) -> List[Dict[str, str]]:
    results: List[Dict[str, str]] = []
    for raw_line in str(value or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "：" in line:
            speaker, content = line.split("：", 1)
            if speaker.strip() and content.strip():
                results.append({"speaker": speaker.strip(), "line": content.strip()})
                continue
        if ":" in line:
            speaker, content = line.split(":", 1)
            if speaker.strip() and content.strip():
                results.append({"speaker": speaker.strip(), "line": content.strip()})
    return results


VALID_SPEECH_TYPES = {"spoken", "inner_monologue", "narration", "offscreen_voice"}
VALID_LANGUAGE_BEAT_TYPES = {
    "spoken_dialogue",
    "inner_monologue",
    "narration",
    "offscreen_voice",
    "action_reaction",
    "reveal",
}
VALID_SPEECH_INTENSITIES = {"low", "medium", "high"}
VALID_VISUAL_PRIORITIES = {"low", "medium", "high"}
VALID_SPLIT_RECOMMENDATIONS = {
    "prefer_new_cell",
    "prefer_new_segment",
    "keep_with_prev",
    "keep_with_next",
}
SPEECH_RATE_CHARS_PER_SECOND = {
    "spoken": 4.2,
    "inner_monologue": 4.8,
    "narration": 5.2,
    "offscreen_voice": 5.2,
}
LIGHT_PAUSE_CHARACTERS = "，,、；;：:"
HEAVY_PAUSE_CHARACTERS = "。！？!?…"
MOUTH_SYNC_OPEN_BUFFER_SECONDS = 0.3
MOUTH_SYNC_CLOSE_BUFFER_SECONDS = 0.25
NON_MOUTH_SYNC_CLOSE_BUFFER_SECONDS = 0.15
TIMING_INTER_ITEM_BUFFER_SECONDS = 0.1
TIMING_MAX_BEAT_SECONDS_BEFORE_SPLIT = 7.5
ACTION_REACTION_EVENT_TYPES = {"action_reaction", "reveal"}
ACTION_TIMING_HINTS = ("抬", "看", "冲", "抓", "推", "拉", "跑", "扑", "转身", "停住", "后退", "抖", "摔", "砸", "指", "逼近")


def _normalize_speech_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in VALID_SPEECH_TYPES else "spoken"


def _round_timing_seconds(value: Any) -> float:
    try:
        return round(max(float(value or 0.0), 0.0), 1)
    except Exception:
        return 0.0


def _ceil_timing_seconds(value: Any, minimum: int = 0) -> int:
    try:
        return max(int(math.ceil(float(value or 0.0))), minimum)
    except Exception:
        return minimum


def _speech_text_units(value: Any) -> int:
    text = re.sub(r"\s+", "", str(value or ""))
    return len(text)


def _estimate_pause_seconds(text: str) -> float:
    light_pauses = sum(1 for char in text if char in LIGHT_PAUSE_CHARACTERS)
    heavy_pauses = sum(1 for char in text if char in HEAVY_PAUSE_CHARACTERS)
    return (light_pauses * 0.15) + (heavy_pauses * 0.35)


def _language_beat_to_speech_type(event_type: Any) -> Optional[str]:
    normalized = str(event_type or "").strip().lower()
    if normalized == "spoken_dialogue":
        return "spoken"
    if normalized in VALID_SPEECH_TYPES:
        return normalized
    return None


def estimate_speech_item_timing_meta(item: Dict[str, Any]) -> Dict[str, float]:
    speech_type = _normalize_speech_type(item.get("speech_type"))
    text = str(item.get("text") or item.get("line") or "").strip()
    intensity = str(item.get("intensity") or "medium").strip().lower()
    if intensity not in VALID_SPEECH_INTENSITIES:
        intensity = "medium"
    mouth_sync_required = bool(
        item.get("mouth_sync_required")
        if item.get("mouth_sync_required") is not None
        else speech_type == "spoken"
    )
    units = _speech_text_units(text)
    speech_seconds = (units / SPEECH_RATE_CHARS_PER_SECOND.get(speech_type, 4.8)) if units > 0 else 0.0
    pause_seconds = _estimate_pause_seconds(text)
    performance_seconds = 0.0
    if units > 0:
        if mouth_sync_required:
            performance_seconds += MOUTH_SYNC_OPEN_BUFFER_SECONDS + MOUTH_SYNC_CLOSE_BUFFER_SECONDS
        else:
            performance_seconds += NON_MOUTH_SYNC_CLOSE_BUFFER_SECONDS
        if speech_type == "spoken":
            performance_seconds += 0.1
        if intensity == "high":
            performance_seconds += 0.3
        elif intensity == "low":
            performance_seconds += 0.05
    total = speech_seconds + pause_seconds + performance_seconds
    if units > 0:
        total = max(total, 0.8 if mouth_sync_required else 0.6)
    return {
        "estimated_speech_seconds": _round_timing_seconds(speech_seconds + pause_seconds),
        "estimated_performance_seconds": _round_timing_seconds(performance_seconds),
        "estimated_total_seconds": _round_timing_seconds(total),
    }


def estimate_speech_items_min_duration_seconds(items: Any) -> float:
    normalized_items = _normalize_speech_items(items)
    if not normalized_items:
        return 0.0
    total = 0.0
    for index, item in enumerate(normalized_items):
        total += estimate_speech_item_timing_meta(item)["estimated_total_seconds"]
        if index > 0:
            total += TIMING_INTER_ITEM_BUFFER_SECONDS
    return _round_timing_seconds(total)


def _estimate_visual_floor_seconds(cell: Dict[str, Any], normalized_mode: str) -> float:
    shot_type = str(cell.get("shot_type") or "").lower()
    action = str(cell.get("action_description") or "").strip()
    performance_focus = str(cell.get("performance_focus") or "").strip()
    duration = 1.2 if normalized_mode == STORYBOARD_MODE_COMMENTARY else 1.0
    if any(token in shot_type for token in ["wide", "long", "establish", "全景", "远景"]):
        duration += 0.6
    elif any(token in shot_type for token in ["close", "特写", "近景"]):
        duration += 0.1
    if any(token in action for token in ACTION_TIMING_HINTS):
        duration += 0.2
    if performance_focus and any(token in performance_focus for token in ["反应", "揭示", "独白", "对白"]):
        duration += 0.2
    return max(min(_round_timing_seconds(duration), 4.0), 0.8)


def estimate_cell_min_duration_seconds(cell: Dict[str, Any], *, storyboard_mode: Optional[str]) -> float:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    speech_items = _normalize_speech_items(cell.get("speech_items") or [])
    if not speech_items and str(cell.get("dialogue_excerpt") or "").strip():
        speech_items = _speech_items_from_dialogue_excerpt(str(cell.get("dialogue_excerpt") or "").strip())
    speech_total = estimate_speech_items_min_duration_seconds(speech_items)
    visual_floor = _estimate_visual_floor_seconds(cell, normalized_mode)
    return _round_timing_seconds(max(speech_total, visual_floor))


def estimate_language_beat_timing_meta(beat: Dict[str, Any]) -> Dict[str, float]:
    event_type = str(beat.get("event_type") or "").strip().lower()
    mapped_speech_type = _language_beat_to_speech_type(event_type)
    if mapped_speech_type:
        return estimate_speech_item_timing_meta(
            {
                "speech_type": mapped_speech_type,
                "text": beat.get("text") or beat.get("source_excerpt") or "",
                "intensity": beat.get("intensity") or "medium",
                "mouth_sync_required": beat.get("mouth_sync_required"),
            }
        )

    intensity = str(beat.get("intensity") or "medium").strip().lower()
    if intensity not in VALID_SPEECH_INTENSITIES:
        intensity = "medium"
    visual_priority = str(beat.get("visual_priority") or "medium").strip().lower()
    if visual_priority not in VALID_VISUAL_PRIORITIES:
        visual_priority = "medium"
    performance_seconds = 1.0
    if event_type == "reveal":
        performance_seconds += 0.3
    if intensity == "high":
        performance_seconds += 0.3
    elif intensity == "low":
        performance_seconds -= 0.1
    if visual_priority == "high":
        performance_seconds += 0.2
    elif visual_priority == "low":
        performance_seconds -= 0.1
    total = max(performance_seconds, 0.8)
    return {
        "estimated_speech_seconds": 0.0,
        "estimated_performance_seconds": _round_timing_seconds(total),
        "estimated_total_seconds": _round_timing_seconds(total),
    }


def estimate_language_beat_min_duration_seconds(beat: Dict[str, Any]) -> float:
    return estimate_language_beat_timing_meta(beat)["estimated_total_seconds"]


def annotate_language_beats_with_timing(beats: Any) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in beats or []:
        if not isinstance(item, dict):
            continue
        timing_meta = estimate_language_beat_timing_meta(item)
        rows.append({**item, **timing_meta})
    return rows


def _split_text_into_timing_clauses(value: Any) -> List[str]:
    text = str(value or "").strip()
    if not text:
        return []
    chunks = re.findall(r"[^，,、；;：。！？!?…]+[，,、；;：。！？!?…]*", text)
    return [chunk.strip() for chunk in chunks if chunk.strip()]


def expand_language_beats_for_timing(beats: Any, *, max_beat_seconds: float = TIMING_MAX_BEAT_SECONDS_BEFORE_SPLIT) -> List[Dict[str, Any]]:
    expanded: List[Dict[str, Any]] = []
    for beat in annotate_language_beats_with_timing(beats):
        event_type = str(beat.get("event_type") or "").strip().lower()
        text = str(beat.get("text") or "").strip()
        clauses = _split_text_into_timing_clauses(text)
        estimated_total = float(beat.get("estimated_total_seconds") or 0.0)
        if event_type not in {"spoken_dialogue", "inner_monologue", "narration", "offscreen_voice"} or len(clauses) < 2 or estimated_total <= max_beat_seconds:
            expanded.append(beat)
            continue
        for clause_index, clause in enumerate(clauses, start=1):
            split_item = {
                **beat,
                "beat_id": f"{str(beat.get('beat_id') or 'LB').strip()}_{clause_index}",
                "source_excerpt": clause,
                "text": clause,
                "split_recommendation": "prefer_new_cell",
            }
            expanded.append({**split_item, **estimate_language_beat_timing_meta(split_item)})
    return expanded


def infer_performance_focus(speech_items: Any, *, storyboard_mode: Optional[str]) -> Optional[str]:
    normalized_items = _normalize_speech_items(speech_items)
    if not normalized_items:
        return None
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    spoken_count = sum(1 for item in normalized_items if _normalize_speech_type(item.get("speech_type")) == "spoken")
    if spoken_count:
        return "张嘴对白落点" if normalized_mode == STORYBOARD_MODE_COMIC else "对白信息落点"
    if any(_normalize_speech_type(item.get("speech_type")) == "inner_monologue" for item in normalized_items):
        return "内心独白承载"
    if any(_normalize_speech_type(item.get("speech_type")) == "offscreen_voice" for item in normalized_items):
        return "画外音承载"
    if any(_normalize_speech_type(item.get("speech_type")) == "narration" for item in normalized_items):
        return "旁白承载"
    return "反应表演落点"


def _normalize_speech_items(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: List[Dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or item.get("line") or "").strip()
        speaker_name = str(item.get("speaker_name") or item.get("speaker") or "").strip()
        speaker_ref = str(item.get("speaker_ref") or "").strip()
        speech_type = _normalize_speech_type(item.get("speech_type"))
        emotion = str(item.get("emotion") or "").strip()
        intensity = str(item.get("intensity") or "medium").strip().lower()
        if intensity not in VALID_SPEECH_INTENSITIES:
            intensity = "medium"
        mouth_sync_required = bool(
            item.get("mouth_sync_required")
            if item.get("mouth_sync_required") is not None
            else speech_type == "spoken"
        )
        if not text and not speaker_name and not speaker_ref:
            continue
        rows.append(
            {
                "speaker_name": speaker_name or "",
                "speaker_ref": speaker_ref or "",
                "speech_type": speech_type,
                "text": text,
                "emotion": emotion or "",
                "intensity": intensity,
                "mouth_sync_required": mouth_sync_required,
            }
        )
    return rows


def _speech_items_from_dialogue_excerpt(dialogue_excerpt: str) -> List[Dict[str, Any]]:
    return [
        {
            "speaker_name": str(item.get("speaker") or "").strip(),
            "speaker_ref": "",
            "speech_type": "spoken",
            "text": str(item.get("line") or "").strip(),
            "emotion": "",
            "intensity": "medium",
            "mouth_sync_required": True,
        }
        for item in _split_dialogue_lines(dialogue_excerpt)
        if str(item.get("line") or "").strip()
    ]


def _speech_item_prefix(item: Dict[str, Any]) -> str:
    speech_type = _normalize_speech_type(item.get("speech_type"))
    speaker = str(item.get("speaker_name") or item.get("speaker_ref") or "").strip()
    if speech_type == "inner_monologue":
        return f"OS：{speaker}" if speaker else "OS"
    if speech_type == "narration":
        return f"旁白：{speaker}" if speaker else "旁白"
    if speech_type == "offscreen_voice":
        return f"画外音：{speaker}" if speaker else "画外音"
    return speaker


def _speech_items_to_dialogue_excerpt(value: Any) -> str:
    rows: List[str] = []
    for item in _normalize_speech_items(value):
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        prefix = _speech_item_prefix(item)
        rows.append(f"{prefix}：{text}" if prefix else text)
    return "\n".join(rows).strip()


def _storyboard_director_persona_block(identity_label: str, stage_role: str, mode_focus: str) -> str:
    return (
        f"你是神鹿平台的{identity_label}，也是服务于 AI 漫剧、动态漫画、剧情视频生产链路的资深{stage_role}。\n"
        "你擅长把剧本理解、资产绑定、分镜拆解、图片提示词、视频提示词和镜头节奏控制串成可直接生产的结构化结果。\n"
        "你不是剧情总结助手，而是生产型分镜专家；你必须输出可执行、可生成、可落地的镜头方案，而不是空泛描述。\n"
        "你会优先绑定已有角色、场景、道具资产，保持人物外观、服装、空间关系和叙事连续性稳定。\n"
        "你会从剧情推进、人物关系、情绪变化、语言节拍和镜头语言共同判断分镜密度，避免片段过粗或信息过载。\n"
        "你的最高目标是：让后续图片生成、视频生成、角色一致性控制和连续镜头生产都能直接使用你的结果。\n"
        f"当前阶段焦点：{mode_focus}。"
    )


def _storyboard_prompt_blacklist_block() -> str:
    return (
        "禁止输出空泛占位句，例如“按当前场景最佳机位呈现主体动作”“人物围绕剧情展开连续表演”“自然光线，画面清晰”。\n"
        "禁止输出 markdown、解释文字、代码块、额外字段或未在 schema 中声明的包装层。\n"
        "禁止伪造 @资产；未命中资产清单时只能保留普通中文名称。"
    )


def build_gridcell_image_prompt_structured(
    *,
    shot_description: str,
    shot_type: str,
    lighting: str,
    ambiance: str,
    composition: str = "",
) -> Dict[str, Any]:
    scene = str(shot_description or composition or "").strip()
    return {
        "scene": scene,
        "composition": {
            "shot_type": normalize_shot_type_label(shot_type),
            "lighting": str(lighting or "按当前场景的真实光线氛围呈现主体").strip(),
            "ambiance": str(ambiance or composition or "保留当前场景的压迫感、空间关系与情绪气氛").strip(),
        },
    }


def build_gridcell_video_prompt_structured(
    *,
    action_description: str,
    camera_motion: str,
    dialogue_excerpt: str = "",
    speech_items: Optional[List[Dict[str, Any]]] = None,
    ambiance_audio: str = "",
    subject_focus: str = "",
    scene_context: str = "",
    camera_language: str = "",
    style_aesthetics: str = "",
    continuity_notes: str = "",
    transition_to_next: str = "",
    reference_strategy: str = "",
    negative_constraints: str = "",
) -> Dict[str, Any]:
    normalized_speech_items = _normalize_speech_items(speech_items) if speech_items is not None else _speech_items_from_dialogue_excerpt(dialogue_excerpt)
    return {
        "action": str(action_description or "主体动作继续推进，情绪或状态发生明确变化").strip(),
        "camera_motion": normalize_camera_motion_label(camera_motion),
        "ambiance_audio": str(ambiance_audio or "保留当前场景画内音，不含背景音乐").strip(),
        "dialogue": [
            {
                "speaker": str(item.get("speaker_name") or item.get("speaker_ref") or "").strip(),
                "line": str(item.get("text") or "").strip(),
            }
            for item in normalized_speech_items
            if _normalize_speech_type(item.get("speech_type")) == "spoken" and str(item.get("text") or "").strip()
        ],
        "speech_items": normalized_speech_items,
        "subject_focus": str(subject_focus or "").strip(),
        "scene_context": str(scene_context or "").strip(),
        "camera_language": str(camera_language or "").strip(),
        "style_aesthetics": str(style_aesthetics or "").strip(),
        "continuity_notes": str(continuity_notes or "").strip(),
        "transition_to_next": str(transition_to_next or "").strip(),
        "reference_strategy": str(reference_strategy or "").strip(),
        "negative_constraints": str(negative_constraints or "").strip(),
    }


def render_image_prompt_from_structured(
    structured: Dict[str, Any],
    *,
    style: str = "",
    style_description: str = "",
    aspect_ratio: Optional[str] = None,
) -> str:
    structured = structured or {}
    composition = structured.get("composition") or {}
    style_lines = []
    if style:
        style_lines.append(f"Style: {style}")
    if style_description:
        style_lines.append(f"Visual style: {style_description}")
    prefix = "\n".join(style_lines)
    body = [
        f"scene: {str(structured.get('scene') or '').strip()}",
        "composition:",
        f"  shot_type: {str(composition.get('shot_type') or '').strip()}",
        f"  lighting: {str(composition.get('lighting') or '').strip()}",
        f"  ambiance: {str(composition.get('ambiance') or '').strip()}",
    ]
    ratio_suffix = ""
    if aspect_ratio == "9:16":
        ratio_suffix = "竖屏构图。"
    elif aspect_ratio == "16:9":
        ratio_suffix = "横屏构图。"
    parts = []
    if prefix:
        parts.append(prefix)
    parts.append("\n".join(body))
    if ratio_suffix:
        parts.append(ratio_suffix)
    return "\n\n".join([item for item in parts if item]).strip()


def render_video_prompt_from_structured(structured: Dict[str, Any]) -> str:
    structured = structured or {}
    lines: List[str] = []
    if str(structured.get("subject_focus") or "").strip():
        lines.append(f"主体：{str(structured.get('subject_focus') or '').strip()}")
    if str(structured.get("scene_context") or "").strip():
        lines.append(f"场景：{str(structured.get('scene_context') or '').strip()}")
    lines.append(f"动作：{str(structured.get('action') or '').strip()}")
    if str(structured.get("camera_language") or "").strip():
        lines.append(f"镜头语言：{str(structured.get('camera_language') or '').strip()}")
    lines.append(f"运镜：{str(structured.get('camera_motion') or '').strip()}")
    if str(structured.get("style_aesthetics") or "").strip():
        lines.append(f"风格氛围：{str(structured.get('style_aesthetics') or '').strip()}")
    lines.append(f"画内音：{str(structured.get('ambiance_audio') or '').strip()}")
    dialogue_items = structured.get("dialogue") or []
    if dialogue_items:
        dialogue_lines = []
        for item in dialogue_items:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("speaker") or "").strip()
            line = str(item.get("line") or "").strip()
            if speaker and line:
                dialogue_lines.append(f"- {speaker}：{line}")
        if dialogue_lines:
            lines.append("对白：")
            lines.extend(dialogue_lines)
    if str(structured.get("continuity_notes") or "").strip():
        lines.append(f"连续性：{str(structured.get('continuity_notes') or '').strip()}")
    if str(structured.get("transition_to_next") or "").strip():
        lines.append(f"切镜：{str(structured.get('transition_to_next') or '').strip()}")
    if str(structured.get("reference_strategy") or "").strip():
        lines.append(f"参考策略：{str(structured.get('reference_strategy') or '').strip()}")
    if str(structured.get("negative_constraints") or "").strip():
        lines.append(f"约束：{str(structured.get('negative_constraints') or '').strip()}")
    return "\n".join([item for item in lines if item]).strip()


def render_video_prompt_from_structured(structured: Dict[str, Any]) -> str:
    structured = structured or {}
    lines: List[str] = []
    if str(structured.get("subject_focus") or "").strip():
        lines.append(f"主体：{str(structured.get('subject_focus') or '').strip()}")
    if str(structured.get("scene_context") or "").strip():
        lines.append(f"场景：{str(structured.get('scene_context') or '').strip()}")
    lines.append(f"动作：{str(structured.get('action') or '').strip()}")
    if str(structured.get("camera_language") or "").strip():
        lines.append(f"镜头语言：{str(structured.get('camera_language') or '').strip()}")
    lines.append(f"运镜：{str(structured.get('camera_motion') or '').strip()}")
    if str(structured.get("style_aesthetics") or "").strip():
        lines.append(f"风格氛围：{str(structured.get('style_aesthetics') or '').strip()}")
    lines.append(f"画内音：{str(structured.get('ambiance_audio') or '').strip()}")

    speech_items = _normalize_speech_items(structured.get("speech_items") or [])
    dialogue_items = structured.get("dialogue") or [
        {
            "speaker": str(item.get("speaker_name") or item.get("speaker_ref") or "").strip(),
            "line": str(item.get("text") or "").strip(),
        }
        for item in speech_items
        if _normalize_speech_type(item.get("speech_type")) == "spoken" and str(item.get("text") or "").strip()
    ]
    if dialogue_items:
        dialogue_lines = []
        for item in dialogue_items:
            if not isinstance(item, dict):
                continue
            speaker = str(item.get("speaker") or "").strip()
            line = str(item.get("line") or "").strip()
            if speaker and line:
                dialogue_lines.append(f"- {speaker}：{line}")
            elif line:
                dialogue_lines.append(f"- {line}")
        if dialogue_lines:
            lines.append("对白：")
            lines.extend(dialogue_lines)

    os_lines = []
    for item in speech_items:
        speech_type = _normalize_speech_type(item.get("speech_type"))
        if speech_type not in {"inner_monologue", "narration", "offscreen_voice"}:
            continue
        prefix = _speech_item_prefix(item)
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        os_lines.append(f"- {prefix}：{text}" if prefix else f"- {text}")
    if os_lines:
        lines.append("OS/旁白：")
        lines.extend(os_lines)

    if str(structured.get("continuity_notes") or "").strip():
        lines.append(f"连续性：{str(structured.get('continuity_notes') or '').strip()}")
    if str(structured.get("transition_to_next") or "").strip():
        lines.append(f"切镜：{str(structured.get('transition_to_next') or '').strip()}")
    if str(structured.get("reference_strategy") or "").strip():
        lines.append(f"参考策略：{str(structured.get('reference_strategy') or '').strip()}")
    if str(structured.get("negative_constraints") or "").strip():
        lines.append(f"约束：{str(structured.get('negative_constraints') or '').strip()}")
    return "\n".join([item for item in lines if item]).strip()


def _safe_float(value: Any, fallback: Optional[float] = None) -> Optional[float]:
    try:
        return float(value)
    except Exception:
        return fallback


def _asset_token(name: str) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    return text if text.startswith("@") else f"@{text}"


def _bound_ref_names(binding_suggestions: Optional[Dict[str, Any]], key: str) -> List[str]:
    if not isinstance(binding_suggestions, dict):
        return []
    rows = binding_suggestions.get(key) or []
    if not isinstance(rows, list):
        return []
    names: List[str] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get("asset_id") is None:
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _resolve_mentionable_refs(
    payload: Dict[str, Any],
    *,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
) -> tuple[List[str], List[str], List[str]]:
    bindings = payload.get("binding_suggestions") if isinstance(payload, dict) else None
    return (
        _bound_ref_names(bindings, "scenes") or list(scene_refs or []),
        _bound_ref_names(bindings, "characters") or list(character_refs or []),
        _bound_ref_names(bindings, "props") or list(prop_refs or []),
    )


SHOT_TYPE_ZH_MAP = {
    "extreme close-up": "大特写",
    "close-up": "特写",
    "medium close-up": "近景",
    "medium shot": "中景",
    "medium long shot": "中远景",
    "long shot": "远景",
    "extreme long shot": "大全景",
    "over-the-shoulder": "越肩镜头",
    "point-of-view": "主观镜头",
    "wide shot": "远景",
    "full shot": "全景",
}

CAMERA_MOTION_ZH_MAP = {
    "static": "静止",
    "pan left": "左摇",
    "pan right": "右摇",
    "tilt up": "上摇",
    "tilt down": "下摇",
    "zoom in": "推进",
    "zoom out": "拉远",
    "tracking shot": "跟拍",
    "dolly in": "推轨",
    "dolly out": "拉轨",
    "handheld": "手持",
}

TRANSITION_ZH_MAP = {
    "cut": "直接切镜",
    "hard cut": "直接切镜",
    "direct cut": "直接切镜",
    "fade": "淡入淡出",
    "fade in": "淡入淡出",
    "fade out": "淡入淡出",
    "dissolve": "溶解",
    "cross dissolve": "溶解",
    "wipe": "擦除",
    "match cut": "动作匹配切",
}


def normalize_shot_type_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "中景"
    lowered = text.lower()
    return SHOT_TYPE_ZH_MAP.get(lowered, text)


def normalize_camera_motion_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "静止"
    lowered = text.lower()
    return CAMERA_MOTION_ZH_MAP.get(lowered, text)


def normalize_transition_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "直接切镜"
    lowered = text.lower()
    return TRANSITION_ZH_MAP.get(lowered, text)


def _is_low_information_text(value: Any) -> bool:
    text = str(value or "").strip()
    if not text:
        return True
    if "当前镜头聚焦主体动作、表情或关键状态变化" in text:
        return True
    if "画面聚焦当前关键动作、反应或状态变化" in text:
        return True
    low_info_markers = [
        "剧情片段",
        "剧情分镜摘要",
        "当前场景",
        "主体人物围绕",
        "连续表演",
        "按当前场景最佳机位",
        "自然光线，画面清晰",
        "当前格主动作推进",
        "当前格可见画面",
        "当前镜头可见画面",
    ]
    return any(marker in text for marker in low_info_markers)


def _clean_low_information_text(value: Any) -> str:
    text = str(value or "").strip()
    return "" if _is_low_information_text(text) else text


def _should_use_compiled_prompt(raw_prompt: Any) -> bool:
    text = str(raw_prompt or "").strip()
    if not text:
        return True
    if _is_low_information_text(text):
        return True
    if "【" in text or "[" in text:
        return True
    if text.count("；") >= 4 or text.count(";") >= 4:
        return True
    if len(text) >= 180:
        return True
    if "@@" in text:
        return True
    return False


def clamp_segment_total_duration(total_duration: Any, cell_count: int) -> int:
    safe_count = max(int(cell_count or 0), 1)
    try:
        desired = int(round(float(total_duration or 0)))
    except Exception:
        desired = 0
    return max(min(max(desired, safe_count, 4), 15), 4)


def constrain_segment_grid_count(total_duration: Any, requested_grid_count: Any) -> int:
    duration = clamp_segment_total_duration(total_duration, 1)
    requested = normalize_grid_count(requested_grid_count)

    if duration <= 5:
        max_allowed = 2
    elif duration <= 10:
        max_allowed = 4
    elif duration <= 13:
        max_allowed = 6
    else:
        max_allowed = 9

    allowed = [count for count in (1, 2, 4, 6, 9) if count <= max_allowed]
    return requested if requested in allowed else max(allowed)


def _join_asset_tokens(names: List[str], fallback: str = "") -> str:
    rows = [_asset_token(name) for name in names or [] if str(name or "").strip()]
    return "、".join([item for item in rows if item]) or fallback


def _compact_text(value: Any, *, limit: int = 28) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 1)].rstrip() + "..."


def _build_cell_visual_fact(
    cell: Dict[str, Any],
    *,
    scene_refs: Optional[List[str]] = None,
    character_refs: Optional[List[str]] = None,
    prop_refs: Optional[List[str]] = None,
) -> str:
    scene_refs = list(scene_refs if scene_refs is not None else (cell.get("scene_refs") or []))
    character_refs = list(character_refs if character_refs is not None else (cell.get("character_refs") or []))
    prop_refs = list(prop_refs if prop_refs is not None else (cell.get("prop_refs") or []))
    scene_text = _join_asset_tokens(scene_refs)
    character_text = _join_asset_tokens(character_refs)
    prop_text = _join_asset_tokens(prop_refs)
    shot_type = normalize_shot_type_label(cell.get("shot_type") or "中景")
    shot_purpose = _clean_low_information_text(cell.get("shot_purpose"))

    if character_text and scene_text:
        return f"{shot_type}中呈现{character_text}在{scene_text}中的关键状态变化"
    if character_text and prop_text:
        return f"{shot_type}中呈现{character_text}与{prop_text}相关的关键动作"
    if character_text:
        return f"{shot_type}中呈现{character_text}的动作、神态或状态变化"
    if prop_text and scene_text:
        return f"{shot_type}中呈现{scene_text}里的{prop_text}细节和状态"
    if scene_text:
        return f"{shot_type}中呈现{scene_text}的环境特征和现场气氛"
    if prop_text:
        return f"{shot_type}中呈现{prop_text}的造型、细节或变化"
    if shot_purpose:
        return f"{shot_type}中围绕{shot_purpose}组织当前镜头信息"
    return f"{shot_type}中呈现当前镜头的关键视觉事实"


def _dialogue_lines_to_text(dialogue_items: Any) -> str:
    rows: List[str] = []
    for item in dialogue_items or []:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker") or "").strip()
        line = str(item.get("line") or "").strip()
        if not line:
            continue
        rows.append(f"{speaker}：{line}" if speaker else line)
    return " / ".join(rows)


def _non_spoken_speech_lines_to_text(speech_items: Any) -> str:
    rows: List[str] = []
    for item in _normalize_speech_items(speech_items):
        speech_type = _normalize_speech_type(item.get("speech_type"))
        if speech_type not in {"inner_monologue", "narration", "offscreen_voice"}:
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        prefix = _speech_item_prefix(item)
        rows.append(f"{prefix}：{text}" if prefix else text)
    return " / ".join(rows)


def _build_video_subject_focus(
    *,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
    shot_description: str,
    action_description: str,
) -> str:
    if character_refs:
        return _join_asset_tokens(character_refs)
    if prop_refs:
        return _join_asset_tokens(prop_refs)
    if scene_refs:
        return _join_asset_tokens(scene_refs)
    return _compact_text(action_description or shot_description or "当前主体", limit=18)


def _build_video_scene_context(cell: Dict[str, Any], *, scene_refs: List[str]) -> str:
    parts: List[str] = []
    scene_text = _join_asset_tokens(scene_refs)
    if scene_text:
        parts.append(scene_text)
    composition = _clean_low_information_text(cell.get("composition"))
    lighting = _clean_low_information_text(cell.get("lighting"))
    ambiance = _clean_low_information_text(cell.get("ambiance"))
    if composition:
        parts.append(composition)
    if lighting:
        parts.append(lighting)
    if ambiance and ambiance not in parts:
        parts.append(ambiance)
    return "，".join([item for item in parts if item]).strip("，")


def _build_video_camera_language(cell: Dict[str, Any], *, shot_type: str, camera_motion: str) -> str:
    parts: List[str] = [shot_type]
    camera_position = _clean_low_information_text(cell.get("camera_position"))
    camera_direction = _clean_low_information_text(cell.get("camera_direction"))
    if camera_position and camera_direction:
        parts.append(f"机位{camera_position}，朝向{camera_direction}")
    elif camera_position:
        parts.append(f"机位{camera_position}")
    elif camera_direction:
        parts.append(f"朝向{camera_direction}")
    parts.append(f"运镜{camera_motion}")
    return "，".join([item for item in parts if item]).strip("，")


def _build_video_style_aesthetics(cell: Dict[str, Any]) -> str:
    parts: List[str] = []
    lighting = _clean_low_information_text(cell.get("lighting"))
    ambiance = _clean_low_information_text(cell.get("ambiance"))
    composition = _clean_low_information_text(cell.get("composition"))
    if lighting:
        parts.append(lighting)
    if ambiance and ambiance not in parts:
        parts.append(ambiance)
    if composition and composition not in parts and len(parts) < 2:
        parts.append(composition)
    return "，".join([item for item in parts if item]).strip("，")


def _build_video_continuity_notes(cell: Dict[str, Any]) -> str:
    parts: List[str] = []
    shot_purpose = _clean_low_information_text(cell.get("shot_purpose"))
    note = _clean_low_information_text(cell.get("note"))
    if shot_purpose:
        parts.append(shot_purpose)
    if note and note not in parts:
        parts.append(note)
    return "；".join([item for item in parts if item]).strip("；")


def _build_video_reference_strategy(
    *,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
    has_dialogue: bool,
) -> str:
    parts: List[str] = []
    if character_refs:
        parts.append(f"优先用{_join_asset_tokens(character_refs)}锁定人物身份、服装与面部一致性")
    if scene_refs:
        parts.append(f"用{_join_asset_tokens(scene_refs)}维持场景空间关系与背景连续性")
    if prop_refs:
        parts.append(f"用{_join_asset_tokens(prop_refs)}保持关键道具位置与状态一致")
    if has_dialogue:
        parts.append("对白与环境声只服务当前镜头，不额外改写主体动作")
    return "；".join([item for item in parts if item]).strip("；")


def _build_transition_phrase(
    cell: Dict[str, Any],
    *,
    next_cell: Optional[Dict[str, Any]],
    transition_to_next: str,
) -> str:
    del cell
    if next_cell:
        next_shot_type = normalize_shot_type_label(next_cell.get("shot_type") or "中景")
        next_focus = _compact_text(
            _clean_low_information_text(next_cell.get("action_description"))
            or _clean_low_information_text(next_cell.get("shot_description")),
            limit=20,
        )
        target = f"下一镜的{next_shot_type}"
        if next_focus:
            target = f"{target}，继续{next_focus}"
        return f"结尾直接切到{target}"

    label = normalize_transition_label(transition_to_next)
    if label == "直接切镜":
        return "结尾直接切到下一分镜"
    if label == "淡入淡出":
        return "结尾以淡入淡出衔接下一分镜"
    if label == "溶解":
        return "结尾以溶解转场衔接下一分镜"
    if label == "擦除":
        return "结尾以擦除转场切入下一分镜"
    if label == "动作匹配切":
        return "结尾以动作匹配切衔接下一分镜"
    return f"结尾以{label}衔接下一分镜"


SEEDANCE_SUBMIT_MENTION_RE = re.compile(r"@([^\s@，。；：、“”\"'（）()\[\]\n\r]+)")
SEEDANCE_ASSET_ID_RE = re.compile(r"\[(?:asset|resource)-[^\]]+\]", re.IGNORECASE)
SEEDANCE_IMAGE_REF_ROLE_ORDER = {"semantic": 0, "auxiliary": 1, "storyboard_board": 2}


def _normalize_seedance_reference_label(value: Any, fallback: str = "") -> str:
    text = str(value or fallback or "").strip()
    text = re.sub(r"^@+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _build_seedance_submit_token(prefix: str, index: int, label: str) -> str:
    clean_label = _normalize_seedance_reference_label(label, f"{prefix}{index}")
    return f"{prefix}{index}（{clean_label}）" if clean_label else f"{prefix}{index}"


def _normalize_seedance_reference_entry(
    raw: Any,
    *,
    media_type: str,
    default_label: str,
    default_role: str = "auxiliary",
) -> Optional[Dict[str, str]]:
    if not isinstance(raw, dict):
        return None
    url = str(raw.get("url") or raw.get("file_url") or "").strip()
    if not url:
        return None
    label = _normalize_seedance_reference_label(
        raw.get("label")
        or raw.get("name")
        or raw.get("title")
        or default_label
    )
    if not label:
        return None
    item = {"url": url, "label": label}
    if media_type == "image":
        role = str(raw.get("role") or default_role or "auxiliary").strip().lower()
        item["role"] = role if role in SEEDANCE_IMAGE_REF_ROLE_ORDER else "auxiliary"
    return item


def _sort_seedance_image_entries(entries: List[Dict[str, str]]) -> List[Dict[str, str]]:
    return sorted(
        entries,
        key=lambda item: (
            SEEDANCE_IMAGE_REF_ROLE_ORDER.get(str(item.get("role") or "auxiliary"), SEEDANCE_IMAGE_REF_ROLE_ORDER["auxiliary"]),
        ),
    )


def build_seedance_reference_index(
    *,
    reference_assets: Optional[List[Dict[str, Any]]] = None,
    reference_images: Optional[List[str]] = None,
    image_refs: Optional[List[str]] = None,
    video_refs: Optional[List[str]] = None,
    audio_refs: Optional[List[str]] = None,
    image_labels: Optional[List[str]] = None,
    video_labels: Optional[List[str]] = None,
    audio_labels: Optional[List[str]] = None,
    image_ref_entries: Optional[List[Dict[str, Any]]] = None,
    video_ref_entries: Optional[List[Dict[str, Any]]] = None,
    audio_ref_entries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    display_mapping: List[Dict[str, str]] = []
    submit_mapping: List[Dict[str, str]] = []
    image_token_map: Dict[str, str] = {}
    video_token_map: Dict[str, str] = {}
    audio_token_map: Dict[str, str] = {}

    def _dedupe_labels(values: List[str]) -> List[str]:
        rows: List[str] = []
        seen: Set[str] = set()
        for value in values:
            label = _normalize_seedance_reference_label(value)
            if not label:
                continue
            key = label.lower()
            if key in seen:
                continue
            seen.add(key)
            rows.append(label)
        return rows

    resolved_image_entries: List[Dict[str, str]] = []
    seen_image_urls: Set[str] = set()
    for index, item in enumerate(image_ref_entries or [], start=1):
        normalized = _normalize_seedance_reference_entry(
            item,
            media_type="image",
            default_label=f"参考图{index}",
            default_role="auxiliary",
        )
        if not normalized or normalized["url"] in seen_image_urls:
            continue
        seen_image_urls.add(normalized["url"])
        resolved_image_entries.append(normalized)
    if resolved_image_entries:
        resolved_image_entries = _sort_seedance_image_entries(resolved_image_entries)
    else:
        resolved_image_labels: List[str] = []
        if isinstance(reference_assets, list):
            for item in reference_assets:
                if not isinstance(item, dict):
                    continue
                label = _normalize_seedance_reference_label(
                    item.get("name")
                    or item.get("title")
                    or item.get("asset_name")
                    or item.get("label")
                    or item.get("trigger_word")
                    or ""
                )
                if label:
                    resolved_image_labels.append(label)
        resolved_image_labels.extend([_normalize_seedance_reference_label(item) for item in (image_labels or [])])
        resolved_image_labels = _dedupe_labels(resolved_image_labels)
        image_count = max(
            len(resolved_image_labels),
            len(reference_images or []),
            len(image_refs or []),
        )
        while len(resolved_image_labels) < image_count:
            resolved_image_labels.append(f"参考图{len(resolved_image_labels) + 1}")
        resolved_image_entries = [{"label": label, "role": "auxiliary"} for label in resolved_image_labels if label]

    def _build_entries(
        raw_entries: Optional[List[Dict[str, Any]]],
        *,
        labels: Optional[List[str]],
        urls: Optional[List[str]],
        media_type: str,
        default_prefix: str,
    ) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        seen_urls: Set[str] = set()
        for index, item in enumerate(raw_entries or [], start=1):
            normalized = _normalize_seedance_reference_entry(
                item,
                media_type=media_type,
                default_label=f"{default_prefix}{index}",
                default_role="auxiliary",
            )
            if not normalized or normalized["url"] in seen_urls:
                continue
            seen_urls.add(normalized["url"])
            rows.append(normalized)
        if rows:
            return rows
        resolved_labels = _dedupe_labels([
            _normalize_seedance_reference_label(item)
            for item in (labels or [])
        ])
        count = max(len(resolved_labels), len(urls or []))
        while len(resolved_labels) < count:
            resolved_labels.append(default_prefix if len(resolved_labels) == 0 else f"{default_prefix}{len(resolved_labels) + 1}")
        return [{"label": label} for label in resolved_labels if label]

    resolved_video_entries = _build_entries(
        video_ref_entries,
        labels=video_labels,
        urls=video_refs,
        media_type="video",
        default_prefix="动作参考",
    )
    resolved_audio_entries = _build_entries(
        audio_ref_entries,
        labels=audio_labels,
        urls=audio_refs,
        media_type="audio",
        default_prefix="环境音参考",
    )

    def _append_entries(prefix: str, media_type: str, entries: List[Dict[str, str]], token_map: Dict[str, str]) -> None:
        for index, entry in enumerate(entries, start=1):
            label = _normalize_seedance_reference_label(entry.get("label") or "", f"{prefix}{index}")
            mention = _asset_token(label)
            token = _build_seedance_submit_token(prefix, index, label)
            token_map[mention] = token
            display_mapping.append({
                "media_type": media_type,
                "mention": mention,
                "label": label,
                "token": token,
                "role": str(entry.get("role") or "").strip(),
            })
            submit_mapping.append({
                "media_type": media_type,
                "label": label,
                "token": token,
                "role": str(entry.get("role") or "").strip(),
            })

    _append_entries("图片", "image", resolved_image_entries, image_token_map)
    _append_entries("视频", "video", resolved_video_entries, video_token_map)
    _append_entries("音频", "audio", resolved_audio_entries, audio_token_map)

    return {
        "display_mapping": display_mapping,
        "submit_mapping": submit_mapping,
        "image_token_map": image_token_map,
        "video_token_map": video_token_map,
        "audio_token_map": audio_token_map,
        "image_entries": resolved_image_entries,
        "video_entries": resolved_video_entries,
        "audio_entries": resolved_audio_entries,
    }


def compile_seedance_display_prompt(prompt: str) -> str:
    cleaned = SEEDANCE_ASSET_ID_RE.sub("", str(prompt or ""))
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def compile_seedance_submit_prompt(
    prompt: str,
    *,
    reference_assets: Optional[List[Dict[str, Any]]] = None,
    reference_images: Optional[List[str]] = None,
    image_refs: Optional[List[str]] = None,
    video_refs: Optional[List[str]] = None,
    audio_refs: Optional[List[str]] = None,
    image_labels: Optional[List[str]] = None,
    video_labels: Optional[List[str]] = None,
    audio_labels: Optional[List[str]] = None,
    image_ref_entries: Optional[List[Dict[str, Any]]] = None,
    video_ref_entries: Optional[List[Dict[str, Any]]] = None,
    audio_ref_entries: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    display_prompt = compile_seedance_display_prompt(prompt)
    index_bundle = build_seedance_reference_index(
        reference_assets=reference_assets,
        reference_images=reference_images,
        image_refs=image_refs,
        video_refs=video_refs,
        audio_refs=audio_refs,
        image_labels=image_labels,
        video_labels=video_labels,
        audio_labels=audio_labels,
        image_ref_entries=image_ref_entries,
        video_ref_entries=video_ref_entries,
        audio_ref_entries=audio_ref_entries,
    )
    submit_prompt = display_prompt
    merged_token_map = {
        **index_bundle.get("image_token_map", {}),
        **index_bundle.get("video_token_map", {}),
        **index_bundle.get("audio_token_map", {}),
    }
    for mention, token in sorted(merged_token_map.items(), key=lambda item: len(item[0]), reverse=True):
        submit_prompt = submit_prompt.replace(mention, token)

    warnings: List[str] = []

    def _replace_leftover(match: re.Match[str]) -> str:
        raw_label = _normalize_seedance_reference_label(match.group(1))
        if not raw_label:
            return ""
        if raw_label.startswith(("图片", "视频", "音频")):
            return raw_label
        warnings.append(raw_label)
        return raw_label

    submit_prompt = SEEDANCE_SUBMIT_MENTION_RE.sub(_replace_leftover, submit_prompt)
    submit_prompt = re.sub(r"[ \t]{2,}", " ", submit_prompt)
    submit_prompt = re.sub(r"\n{3,}", "\n\n", submit_prompt)

    return {
        **index_bundle,
        "display_prompt": display_prompt,
        "submit_prompt": submit_prompt.strip(),
        "warnings": list(dict.fromkeys(warnings)),
    }


def _build_comic_seedance_reference_strategy(
    *,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
    has_dialogue: bool,
) -> str:
    parts: List[str] = []
    if character_refs:
        parts.append(f"{_asset_token(character_refs[0])}锁定人物外观与服装一致性")
    if scene_refs:
        parts.append(f"{_asset_token(scene_refs[0])}锁定场景空间关系")
    if prop_refs:
        parts.append(f"{_asset_token(prop_refs[0])}锁定关键道具状态")
    if has_dialogue:
        parts.append("音频仅控制环境声与台词氛围")
    return "；".join([item for item in parts if item]).strip("；")


def _build_comic_seedance_reference_mapping(
    *,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
    has_dialogue: bool,
) -> str:
    lines: List[str] = []
    bundle = build_seedance_reference_index(audio_labels=["环境音参考"] if has_dialogue else [])
    for item in bundle.get("submit_mapping", []):
        media_type = str(item.get("media_type") or "")
        token = str(item.get("token") or "").strip()
        if not token:
            continue
        if media_type == "audio":
            lines.append(f"{token}：控制环境音或台词氛围，不改写主体动作。")
    return "\n".join(lines).strip()


def _build_comic_seedance_negative_constraints(
    *,
    has_character: bool,
    has_scene: bool,
    has_prop: bool,
) -> str:
    constraints = [
        "保持人物脸部、发型、服装和体型稳定，不要跳脸或突然换装",
        "每个镜头只保留一个主动作焦点和一个主运镜，不要混合多个冲突运镜",
        "不要新增无关人物、无关道具或随机背景元素",
    ]
    if has_scene:
        constraints.append("保持场景空间方向、机位轴线和背景关系稳定，不要突然换景")
    if has_prop:
        constraints.append("保持关键道具的数量、位置、持握关系和状态连续，不要穿模")
    if has_character:
        constraints.append("保持人物站位、朝向、视线和动作接力连续，不要随机跳切")
    return "；".join(constraints)


def _render_comic_seedance_video_line(structured: Dict[str, Any]) -> str:
    structured = structured or {}
    subject_focus = str(structured.get("subject_focus") or "").strip()
    scene_context = str(structured.get("scene_context") or "").strip()
    action = str(structured.get("action") or "").strip()
    camera_language = str(structured.get("camera_language") or "").strip()
    style_aesthetics = str(structured.get("style_aesthetics") or "").strip()
    reference_strategy = str(structured.get("reference_strategy") or "").strip()
    negative_constraints = str(structured.get("negative_constraints") or "").strip()
    transition_phrase = str(structured.get("transition_to_next") or "").strip()
    dialogue_text = _dialogue_lines_to_text(structured.get("dialogue") or [])
    os_text = _non_spoken_speech_lines_to_text(structured.get("speech_items") or [])
    ambiance_audio = str(structured.get("ambiance_audio") or "").strip()
    continuity_notes = str(structured.get("continuity_notes") or "").strip()

    visual_parts: List[str] = []
    if subject_focus and scene_context and action:
        visual_parts.append(f"{subject_focus}在{scene_context}中{action}")
    elif subject_focus and action:
        visual_parts.append(f"{subject_focus}{action}")
    elif scene_context and action:
        visual_parts.append(f"在{scene_context}中{action}")
    elif action:
        visual_parts.append(action)

    camera_parts = [item for item in [camera_language, style_aesthetics] if item]
    audio_parts: List[str] = []
    if dialogue_text:
        audio_parts.append(f"对白 {dialogue_text}")
    if os_text:
        audio_parts.append(f"OS/旁白 {os_text}")
    if ambiance_audio:
        audio_parts.append(ambiance_audio)

    control_parts: List[str] = []
    if reference_strategy:
        control_parts.append(reference_strategy)
    if continuity_notes:
        control_parts.append(continuity_notes)
    if transition_phrase:
        control_parts.append(transition_phrase)
    if negative_constraints:
        first_constraint = str(negative_constraints).split("；", 1)[0].strip()
        if first_constraint:
            control_parts.append(first_constraint)

    parts: List[str] = []
    if visual_parts:
        parts.append("，".join(visual_parts))
    if camera_parts:
        parts.append("，".join(camera_parts))
    if audio_parts:
        parts.append("；".join(audio_parts))
    if control_parts:
        parts.append("；".join(control_parts))
    return "；".join([item for item in parts if item]).strip("；")


def resolve_gridcell_video_prompt_structured(
    cell: Dict[str, Any],
    *,
    next_cell: Optional[Dict[str, Any]] = None,
    transition_to_next: str = "cut",
) -> Dict[str, Any]:
    structured = cell.get("video_prompt_structured") if isinstance(cell.get("video_prompt_structured"), dict) else {}
    normalized_mode = normalize_storyboard_mode(cell.get("storyboard_mode") or cell.get("storyboard_mode_hint") or STORYBOARD_MODE_COMMENTARY)
    scene_refs, character_refs, prop_refs = _resolve_mentionable_refs(
        cell,
        scene_refs=cell.get("scene_refs") or [],
        character_refs=cell.get("character_refs") or [],
        prop_refs=cell.get("prop_refs") or [],
    )
    shot_type = normalize_shot_type_label(cell.get("shot_type") or "中景")
    camera_motion = normalize_camera_motion_label(cell.get("camera_motion") or "静止")
    shot_description = resolve_segment_asset_mentions(
        _clean_low_information_text(cell.get("shot_description")),
        scene_refs=scene_refs,
        character_refs=character_refs,
        prop_refs=prop_refs,
    )
    action_description = resolve_segment_asset_mentions(
        _clean_low_information_text(structured.get("action"))
        or _clean_low_information_text(cell.get("action_description"))
        or shot_description
        or _build_cell_visual_fact(
            cell,
            scene_refs=scene_refs,
            character_refs=character_refs,
            prop_refs=prop_refs,
        ),
        scene_refs=scene_refs,
        character_refs=character_refs,
        prop_refs=prop_refs,
    )
    speech_items = _normalize_speech_items(structured.get("speech_items") or cell.get("speech_items") or [])
    if not speech_items:
        speech_items = _speech_items_from_dialogue_excerpt(str(cell.get("dialogue_excerpt") or "").strip())
    dialogue_items = [
        {
            "speaker": str(item.get("speaker_name") or item.get("speaker_ref") or "").strip(),
            "line": str(item.get("text") or "").strip(),
        }
        for item in speech_items
        if _normalize_speech_type(item.get("speech_type")) == "spoken" and str(item.get("text") or "").strip()
    ]
    scene_context = str(structured.get("scene_context") or "").strip() or _build_video_scene_context(cell, scene_refs=scene_refs)
    camera_language = str(structured.get("camera_language") or "").strip() or _build_video_camera_language(cell, shot_type=shot_type, camera_motion=camera_motion)
    style_aesthetics = str(structured.get("style_aesthetics") or "").strip() or _build_video_style_aesthetics(cell)
    continuity_notes = str(structured.get("continuity_notes") or "").strip() or _build_video_continuity_notes(cell)
    transition_phrase = str(structured.get("transition_to_next") or "").strip() or _build_transition_phrase(
        cell,
        next_cell=next_cell,
        transition_to_next=transition_to_next,
    )
    ambiance_audio = str(structured.get("ambiance_audio") or "").strip()
    if not ambiance_audio:
        ambiance_audio = "保留现场环境音与人物对白" if dialogue_items else "保留现场环境音"
    return {
        **structured,
        "subject_focus": str(structured.get("subject_focus") or "").strip()
        or _build_video_subject_focus(
            scene_refs=scene_refs,
            character_refs=character_refs,
            prop_refs=prop_refs,
            shot_description=shot_description,
            action_description=action_description,
        ),
        "scene_context": scene_context,
        "action": action_description,
        "camera_language": camera_language,
        "camera_motion": camera_motion,
        "style_aesthetics": style_aesthetics,
        "ambiance_audio": ambiance_audio,
        "dialogue": dialogue_items,
        "speech_items": speech_items,
        "continuity_notes": continuity_notes,
        "transition_to_next": transition_phrase,
        "transition_label": normalize_transition_label(transition_to_next if not next_cell else "cut"),
        "reference_strategy": (
            str(structured.get("reference_strategy") or "").strip()
            or (
                _build_comic_seedance_reference_strategy(
                    scene_refs=scene_refs,
                    character_refs=character_refs,
                    prop_refs=prop_refs,
                    has_dialogue=bool(dialogue_items),
                )
                if normalized_mode == STORYBOARD_MODE_COMIC
                else _build_video_reference_strategy(
                    scene_refs=scene_refs,
                    character_refs=character_refs,
                    prop_refs=prop_refs,
                    has_dialogue=bool(dialogue_items),
                )
            )
        ),
        "negative_constraints": (
            str(structured.get("negative_constraints") or "").strip()
            or (
                _build_comic_seedance_negative_constraints(
                    has_character=bool(character_refs),
                    has_scene=bool(scene_refs),
                    has_prop=bool(prop_refs),
                )
                if normalized_mode == STORYBOARD_MODE_COMIC
                else ""
            )
        ),
    }


def render_video_control_line_from_structured(structured: Dict[str, Any]) -> str:
    structured = structured or {}
    parts: List[str] = []
    subject_focus = str(structured.get("subject_focus") or "").strip()
    scene_context = str(structured.get("scene_context") or "").strip()
    action = str(structured.get("action") or "").strip()
    if subject_focus and scene_context and action:
        parts.append(f"{subject_focus}在{scene_context}中{action}")
    elif subject_focus and action:
        parts.append(f"{subject_focus}{action}")
    elif scene_context and action:
        parts.append(f"在{scene_context}中{action}")
    elif action:
        parts.append(action)
    camera_language = str(structured.get("camera_language") or "").strip()
    if camera_language:
        parts.append(f"镜头语言：{camera_language}")
    style_aesthetics = str(structured.get("style_aesthetics") or "").strip()
    if style_aesthetics:
        parts.append(f"光影氛围：{style_aesthetics}")
    ambiance_audio = str(structured.get("ambiance_audio") or "").strip()
    if ambiance_audio:
        parts.append(f"画内音：{ambiance_audio}")
    dialogue_text = _dialogue_lines_to_text(structured.get("dialogue") or [])
    if dialogue_text:
        parts.append(f"对白：{dialogue_text}")
    continuity_notes = str(structured.get("continuity_notes") or "").strip()
    if continuity_notes:
        parts.append(f"衔接重点：{continuity_notes}")
    transition_phrase = str(structured.get("transition_to_next") or "").strip()
    if transition_phrase:
        parts.append(f"切镜：{transition_phrase}")
    reference_strategy = str(structured.get("reference_strategy") or "").strip()
    if reference_strategy:
        parts.append(f"参考策略：{reference_strategy}")
    negative_constraints = str(structured.get("negative_constraints") or "").strip()
    if negative_constraints:
        parts.append(f"约束：{negative_constraints}")
    return "；".join([item for item in parts if item]).strip("；")


def resolve_segment_asset_mentions(
    text: str,
    *,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    for name in list(scene_refs or []) + list(character_refs or []) + list(prop_refs or []):
        clean_name = str(name or "").strip()
        if not clean_name:
            continue
        raw = raw.replace(f"[@{clean_name}]", _asset_token(clean_name))
        raw = re.sub(rf"(?<!@)\b{re.escape(clean_name)}\b", _asset_token(clean_name), raw)
    return raw


def _default_cell_duration(cell: Dict[str, Any], normalized_mode: str) -> float:
    shot_type = str(cell.get("shot_type") or "").lower()
    duration = 1.4 if normalized_mode == STORYBOARD_MODE_COMMENTARY else 1.2
    if any(token in shot_type for token in ["wide", "long", "establish", "全景", "远景"]):
        duration += 0.6
    elif any(token in shot_type for token in ["close", "特写", "近景"]):
        duration += 0.1
    action = str(cell.get("action_description") or "").strip()
    dialogue = str(cell.get("dialogue_excerpt") or "").strip()
    if len(dialogue) >= 12:
        duration += 0.4
    if any(token in action for token in ["冲", "奔", "勒马", "挥", "撞", "跌", "转身", "扑", "冲破", "怒吼"]):
        duration += 0.2
    return max(min(duration, 4.0), 0.8)


def normalize_segment_timing(
    cells: List[Dict[str, Any]],
    total_duration: float,
    *,
    storyboard_mode: str,
) -> List[Dict[str, float]]:
    if not cells:
        return []
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    target_total = clamp_segment_total_duration(total_duration, len(cells))
    raw_durations: List[float] = []
    for cell in cells:
        duration = _safe_float(cell.get("duration_seconds"))
        start = _safe_float(cell.get("start_second"))
        end = _safe_float(cell.get("end_second"))
        if duration is None and start is not None and end is not None and end > start:
            duration = end - start
        if duration is None or duration <= 0:
            duration = _default_cell_duration(cell, normalized_mode)
        raw_durations.append(max(min(float(duration), 4.0), 0.8))

    current_total = sum(raw_durations) or float(len(cells))
    scaled = [item * (target_total / current_total) for item in raw_durations]

    durations = [1 for _ in cells]
    remaining = max(target_total - len(cells), 0)
    if remaining > 0:
        weights = [max(item - 1.0, 0.0) for item in scaled]
        weight_total = sum(weights)
        if weight_total <= 0:
            weights = [1.0 for _ in cells]
            weight_total = float(len(cells))
        exact_extras = [(remaining * weight / weight_total) for weight in weights]
        extra_ints = [int(item) for item in exact_extras]
        leftover = remaining - sum(extra_ints)
        if leftover > 0:
            order = sorted(
                range(len(cells)),
                key=lambda idx: (exact_extras[idx] - extra_ints[idx], weights[idx]),
                reverse=True,
            )
            for idx in order[:leftover]:
                extra_ints[idx] += 1
        durations = [1 + extra for extra in extra_ints]

    result: List[Dict[str, float]] = []
    cursor = 0
    for duration in durations:
        start = int(cursor)
        end = int(cursor + duration)
        result.append(
            {
                "start_second": float(start),
                "end_second": float(end),
                "duration_seconds": float(duration),
            }
        )
        cursor = end
    return result


def _default_cell_duration(cell: Dict[str, Any], normalized_mode: str) -> float:
    return estimate_cell_min_duration_seconds(cell, storyboard_mode=normalized_mode)


def normalize_segment_timing(
    cells: List[Dict[str, Any]],
    total_duration: float,
    *,
    storyboard_mode: str,
) -> List[Dict[str, float]]:
    if not cells:
        return []
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    target_total = float(clamp_segment_total_duration(total_duration, len(cells)))
    raw_durations: List[float] = []
    min_durations: List[float] = []
    for cell in cells:
        duration = _safe_float(cell.get("duration_seconds"))
        start = _safe_float(cell.get("start_second"))
        end = _safe_float(cell.get("end_second"))
        if duration is None and start is not None and end is not None and end > start:
            duration = end - start
        min_duration = estimate_cell_min_duration_seconds(cell, storyboard_mode=normalized_mode)
        min_durations.append(min_duration)
        if duration is None or duration <= 0:
            duration = min_duration
        raw_durations.append(max(float(duration), min_duration))

    min_total = _round_timing_seconds(sum(min_durations))
    target_total = max(target_total, min_total)
    current_total = sum(raw_durations) or float(len(cells))
    if current_total <= 0:
        current_total = float(len(cells))
    scaled = [item * (target_total / current_total) for item in raw_durations]
    durations = [max(min_durations[idx], _round_timing_seconds(scaled[idx])) for idx in range(len(cells))]
    running_total = _round_timing_seconds(sum(durations))

    if running_total < target_total:
        deficit_steps = int(round((target_total - running_total) * 10))
        if deficit_steps > 0:
            weights = [max(raw_durations[idx], min_durations[idx], 0.1) for idx in range(len(cells))]
            order = sorted(range(len(cells)), key=lambda idx: (weights[idx], idx), reverse=True)
            for step in range(deficit_steps):
                idx = order[step % len(order)]
                durations[idx] = _round_timing_seconds(durations[idx] + 0.1)
    elif running_total > target_total:
        overflow_steps = int(round((running_total - target_total) * 10))
        if overflow_steps > 0:
            slack = [max(_round_timing_seconds(durations[idx] - min_durations[idx]), 0.0) for idx in range(len(cells))]
            order = sorted(range(len(cells)), key=lambda idx: (slack[idx], raw_durations[idx]), reverse=True)
            for _ in range(overflow_steps):
                adjusted = False
                for idx in order:
                    if durations[idx] - 0.1 >= min_durations[idx] - 1e-6:
                        durations[idx] = _round_timing_seconds(durations[idx] - 0.1)
                        adjusted = True
                        break
                if not adjusted:
                    break

    final_total = _round_timing_seconds(sum(durations))
    correction = _round_timing_seconds(target_total - final_total)
    if abs(correction) >= 0.1:
        durations[-1] = _round_timing_seconds(max(min_durations[-1], durations[-1] + correction))

    result: List[Dict[str, float]] = []
    cursor = 0.0
    for duration in durations:
        start = _round_timing_seconds(cursor)
        end = _round_timing_seconds(cursor + duration)
        result.append(
            {
                "start_second": float(start),
                "end_second": float(end),
                "duration_seconds": _round_timing_seconds(end - start),
            }
        )
        cursor = end
    return result

def render_segment_scene_prompt(
    *,
    summary: str,
    scene_constraint: str,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
    binding_suggestions: Optional[Dict[str, Any]] = None,
    prompt_locks: Optional[Dict[str, Any]] = None,
) -> str:
    if isinstance(prompt_locks, dict):
        sections: List[str] = ["分镜设定："]
        section_map = [
            ("角色锁定", prompt_locks.get("character_lock") or []),
            ("场景锁定", prompt_locks.get("scene_lock") or []),
            ("道具锁定", prompt_locks.get("prop_lock") or []),
            ("统一画面约束", prompt_locks.get("global_constraints") or []),
        ]
        for title, rows in section_map:
            clean_rows = _compact_prompt_clauses(rows, limit=3 if title == "统一画面约束" else 2)
            if not clean_rows:
                continue
            sections.append(f"【{title}】")
            sections.extend([_sanitize_double_at(row) for row in clean_rows])
        return "\n".join(sections).strip()

    mention_scene_refs = _normalize_asset_name_list(_bound_ref_names(binding_suggestions, "scenes"))
    mention_character_refs = _normalize_asset_name_list(_bound_ref_names(binding_suggestions, "characters"))
    mention_prop_refs = _normalize_asset_name_list(_bound_ref_names(binding_suggestions, "props"))
    parts: List[str] = []
    if mention_character_refs:
        parts.append(f"{_join_asset_tokens(mention_character_refs)}保持人物外观、服装与表情连续")
    if mention_prop_refs:
        parts.append(f"{_join_asset_tokens(mention_prop_refs)}保持关键道具状态连续")
    if mention_scene_refs:
        parts.append(f"{_join_asset_tokens(mention_scene_refs)}保持场景空间方向与背景关系稳定")
    if scene_constraint and not _is_low_information_text(scene_constraint):
        parts.append(resolve_segment_asset_mentions(scene_constraint, scene_refs=mention_scene_refs, character_refs=mention_character_refs, prop_refs=mention_prop_refs))
    elif summary:
        parts.append(resolve_segment_asset_mentions(summary, scene_refs=mention_scene_refs, character_refs=mention_character_refs, prop_refs=mention_prop_refs))
    body = "；".join(_compact_prompt_clauses(parts, limit=4)).strip("；")
    return f"分镜设定：\n{body}" if body else "分镜设定："


def render_gridcell_image_prompt(cell: Dict[str, Any]) -> str:
    cell_index = int(cell.get("cell_index") or 1)
    segment_grid_count = normalize_grid_count(cell.get("segment_grid_count"))
    shot_type = normalize_shot_type_label(cell.get("shot_type") or "中景")
    camera_motion = normalize_camera_motion_label(cell.get("camera_motion") or "静止")
    camera_setup = "，".join(
        [
            item for item in [
                str(cell.get("camera_position") or "").strip(),
                str(cell.get("camera_direction") or "").strip(),
            ] if item
        ]
    )
    shot_description = resolve_segment_asset_mentions(
        _clean_low_information_text(cell.get("shot_description")),
        scene_refs=cell.get("scene_refs") or [],
        character_refs=cell.get("character_refs") or [],
        prop_refs=cell.get("prop_refs") or [],
    )
    action_description = resolve_segment_asset_mentions(
        _clean_low_information_text(cell.get("action_description")),
        scene_refs=cell.get("scene_refs") or [],
        character_refs=cell.get("character_refs") or [],
        prop_refs=cell.get("prop_refs") or [],
    )
    composition = _clean_low_information_text(cell.get("composition"))
    lighting = _clean_low_information_text(cell.get("lighting"))
    ambiance = _clean_low_information_text(cell.get("ambiance"))
    shot_purpose = _clean_low_information_text(cell.get("shot_purpose"))
    block_label = "宫格" if segment_grid_count > 1 else "镜头"
    lines = [f"[{block_label}{cell_index}]"]
    lines.append(f"【当前动作】{action_description or shot_description or '当前宫格聚焦主体动作、表情或关键状态变化'}")
    lines.append(f"【机位与朝向】{camera_setup or '镜头位于主体动作前方或侧前方，朝向当前动作焦点'}")
    lines.append(f"【景别】{shot_type}")
    if (
        shot_description
        and shot_description != action_description
        and shot_description not in str(action_description or "")
        and not _is_low_information_text(shot_description)
    ):
        lines.append(f"【局部补充】{shot_description}")
    lines.append(f"【构图】{composition or '主体明确位于视觉焦点，前后景关系清晰，空间方向可读'}")
    lines.append(f"【运镜】{camera_motion}")
    lines.append(f"【镜头功能】{shot_purpose or '交代当前动作推进、情绪变化或关键叙事信息'}")
    if lighting:
        lines.append(f"【局部光线】{lighting}")
    if ambiance:
        lines.append(f"【局部氛围】{ambiance}")
    return "\n".join(lines).strip()


def render_gridcell_video_prompt(
    cell: Dict[str, Any],
    *,
    next_cell: Optional[Dict[str, Any]] = None,
    transition_to_next: str = "cut",
) -> str:
    structured = resolve_gridcell_video_prompt_structured(
        cell,
        next_cell=next_cell,
        transition_to_next=transition_to_next,
    )
    return render_video_control_line_from_structured(structured) or "画面聚焦当前关键动作、反应或状态变化"


def render_segment_multi_shot_prompt(scene_prompt: str, cells: List[Dict[str, Any]], *, layout_spec: Optional[Dict[str, Any]] = None) -> str:
    parts = [str(scene_prompt or "").strip()]
    if isinstance(layout_spec, dict) and layout_spec.get("is_multigrid"):
        layout_lines = ["版式要求：", str(layout_spec.get("layout_prompt") or "").strip()]
        layout_lines.extend([str(item or "").strip() for item in (layout_spec.get("layout_requirements") or []) if str(item or "").strip()])
        parts.append("\n".join([item for item in layout_lines if item]))
    for cell in cells:
        raw_prompt = str(cell.get("image_prompt") or "").strip()
        prompt = render_gridcell_image_prompt(cell) if _should_use_compiled_prompt(raw_prompt) else raw_prompt
        if prompt:
            parts.append(prompt)
    return "\n\n".join([item for item in parts if item]).strip()


def render_segment_video_timeline_prompt(cells: List[Dict[str, Any]], transition_to_next: str = "cut", storyboard_mode: Optional[str] = None) -> str:
    lines: List[str] = []
    total = len(cells)
    for index, cell in enumerate(cells):
        start = int(round(float(cell.get("start_second") or 0.0)))
        end = int(round(float(cell.get("end_second") or 0.0)))
        if end <= start:
            continue
        raw_prompt = str(cell.get("video_prompt") or "").strip()
        next_cell = cells[index + 1] if index + 1 < total else None
        effective_transition = transition_to_next if index == total - 1 else "cut"
        content = render_gridcell_video_prompt(
            cell,
            next_cell=next_cell,
            transition_to_next=effective_transition,
        ) if _should_use_compiled_prompt(raw_prompt) else raw_prompt
        if not content:
            continue
        start_text = f"{start}"
        end_text = f"{end}"
        lines.append(f"{start_text}-{end_text}秒：{content}")
    return "\n".join(lines).strip()


def _render_comic_segment_video_prompt(payloads: List[Dict[str, Any]], *, transition_to_next: str = "cut") -> str:
    if not payloads:
        return ""
    structured_rows = []
    total = len(payloads)
    for index, payload in enumerate(payloads):
        structured_rows.append(
            resolve_gridcell_video_prompt_structured(
                {
                    **payload,
                    "storyboard_mode": STORYBOARD_MODE_COMIC,
                },
                next_cell=payloads[index + 1] if index + 1 < total else None,
                transition_to_next=transition_to_next if index == total - 1 else "cut",
            )
        )

    section_lines: List[str] = []
    scene_context = next((str(item.get("scene_context") or "").strip() for item in structured_rows if str(item.get("scene_context") or "").strip()), "")
    style_aesthetics = next((str(item.get("style_aesthetics") or "").strip() for item in structured_rows if str(item.get("style_aesthetics") or "").strip()), "")
    segment_setting_parts: List[str] = []
    merged_character_refs = list(dict.fromkeys([
        str(name or "").strip()
        for payload in payloads
        for name in (payload.get("character_refs") or [])
        if str(name or "").strip()
    ]))
    merged_prop_refs = list(dict.fromkeys([
        str(name or "").strip()
        for payload in payloads
        for name in (payload.get("prop_refs") or [])
        if str(name or "").strip()
    ]))
    merged_scene_refs = list(dict.fromkeys([
        str(name or "").strip()
        for payload in payloads
        for name in (payload.get("scene_refs") or [])
        if str(name or "").strip()
    ]))
    merged_character_refs = _normalize_asset_name_list(merged_character_refs)
    merged_prop_refs = _normalize_asset_name_list(merged_prop_refs)
    merged_scene_refs = _normalize_asset_name_list(merged_scene_refs)
    if merged_character_refs:
        segment_setting_parts.append(f"{_join_asset_tokens(merged_character_refs)}保持人物外观、服装与表情连续")
    if merged_prop_refs:
        segment_setting_parts.append(f"{_join_asset_tokens(merged_prop_refs)}保持关键道具状态连续")
    if merged_scene_refs:
        segment_setting_parts.append(f"{_join_asset_tokens(merged_scene_refs)}保持场景空间方向稳定")
    if scene_context:
        segment_setting_parts.append(scene_context)
    if style_aesthetics:
        segment_setting_parts.append(style_aesthetics)
    continuity_anchor = next((str(item.get("continuity_notes") or "").strip() for item in structured_rows if str(item.get("continuity_notes") or "").strip()), "")
    if continuity_anchor and continuity_anchor not in segment_setting_parts:
        segment_setting_parts.append(continuity_anchor)
    segment_setting = "；".join([item for item in segment_setting_parts if item])
    if segment_setting:
        section_lines.append("分镜设定：" + segment_setting)

    reference_mapping = _build_comic_seedance_reference_mapping(
        scene_refs=merged_scene_refs,
        character_refs=merged_character_refs,
        prop_refs=merged_prop_refs,
        has_dialogue=any(bool(item.get("dialogue")) for item in structured_rows),
    )
    if reference_mapping:
        section_lines.append("参考映射：\n" + reference_mapping)

    section_lines.append("时间轴：")
    for index, payload in enumerate(payloads):
        start = int(round(float(payload.get("start_second") or 0.0)))
        end = int(round(float(payload.get("end_second") or 0.0)))
        if end <= start:
            continue
        structured = structured_rows[index]
        content = str(payload.get("video_prompt") or "").strip()
        if not content or _is_low_information_text(content):
            content = _render_comic_seedance_video_line(structured)
        if not content:
            continue
        section_lines.append(f"{start}-{end}秒：{content}")

    quality_constraints = "；".join(
        dict.fromkeys([str(item.get("negative_constraints") or "").strip() for item in structured_rows if str(item.get("negative_constraints") or "").strip()])
    )
    if quality_constraints:
        section_lines.append("质量约束：" + quality_constraints)

    return "\n".join([item for item in section_lines if item]).strip()


def _sanitize_double_at(text: Any) -> str:
    return re.sub(r"@{2,}", "@", str(text or "").strip())


def _asset_token(name: str) -> str:
    text = _sanitize_double_at(name)
    if not text:
        return ""
    return text if text.startswith("@") else f"@{text}"


def _join_asset_tokens(names: List[str], fallback: str = "") -> str:
    rows = [_asset_token(name) for name in names or [] if str(name or "").strip()]
    return "、".join([item for item in rows if item]) or fallback


def build_segment_prompt_locks(
    segment: Dict[str, Any],
    *,
    aspect_ratio: Optional[str],
    storyboard_mode: Optional[str],
) -> Dict[str, Any]:
    continuity_state = segment.get("continuity_state") if isinstance(segment.get("continuity_state"), dict) else _build_segment_continuity_state(segment)
    layout_spec = build_segment_layout_spec(
        grid_count=segment.get("grid_count"),
        aspect_ratio=aspect_ratio,
        storyboard_mode=storyboard_mode,
    )
    scene_refs = _normalize_asset_name_list(segment.get("scene_refs") or [])
    character_refs = _normalize_asset_name_list(segment.get("character_refs") or [])
    prop_refs = _normalize_asset_name_list(segment.get("prop_refs") or [])
    costume_state = continuity_state.get("costume_state") if isinstance(continuity_state.get("costume_state"), dict) else {}
    body_state = continuity_state.get("body_state") if isinstance(continuity_state.get("body_state"), dict) else {}
    prop_state = continuity_state.get("prop_state") if isinstance(continuity_state.get("prop_state"), list) else []

    character_lock: List[str] = []
    for character in character_refs or _normalize_asset_name_list(continuity_state.get("characters") or []):
        rows = _compact_prompt_clauses(list(costume_state.get(character) or []) + list(body_state.get(character) or []), limit=2)
        if rows:
            character_lock.append(f"{_asset_token(character)}：{'；'.join(rows)}")
        else:
            character_lock.append(f"{_asset_token(character)}：保持人物外观、服装与表情连续")

    scene_lock: List[str] = []
    scene_anchor = _clean_prompt_clause(continuity_state.get("scene_anchor") or "")
    if scene_anchor:
        scene_lock.append(resolve_segment_asset_mentions(scene_anchor, scene_refs=scene_refs, character_refs=character_refs, prop_refs=prop_refs))
    elif scene_refs:
        scene_lock.append(f"{_join_asset_tokens(scene_refs)}保持场景空间方向、背景关系与光线基调稳定。")
    scene_lock = _dedupe_texts(scene_lock)

    prop_lock: List[str] = []
    for prop in prop_refs:
        matched = [item for item in prop_state if _normalize_asset_name(prop) in _normalize_asset_name(str(item or ""))]
        rows = _compact_prompt_clauses(matched, limit=2)
        if rows:
            prop_lock.append(f"{_asset_token(prop)}：{'；'.join(rows)}")
        else:
            prop_lock.append(f"{_asset_token(prop)}：保持关键道具状态连续")

    base_summary = resolve_segment_asset_mentions(
        str(segment.get("scene_constraint") or segment.get("summary") or "").strip(),
        scene_refs=scene_refs,
        character_refs=character_refs,
        prop_refs=prop_refs,
    )
    global_constraints = [item for item in [_clean_prompt_clause(base_summary)] if item]
    global_constraints.append("保持同一分镜内所有宫格共享同一组角色、场景和道具锁定，不允许任何宫格自行漂移。")
    if layout_spec.get("is_multigrid"):
        global_constraints.append("所有宫格必须共同讲述同一段连续剧情，不允许把单格画成互不相关的独立场景。")
        global_constraints.append("严格去掉所有可见文字元素，不允许在宫格内外出现汉字、字幕、标签、水印、logo 或英文字母。")

    return {
        "character_lock": _dedupe_texts(character_lock),
        "scene_lock": scene_lock,
        "prop_lock": _dedupe_texts(prop_lock),
        "global_constraints": _dedupe_texts(global_constraints),
        "continuity_state": continuity_state,
        "layout_spec": layout_spec,
    }


def render_segment_scene_prompt(
    *,
    summary: str,
    scene_constraint: str,
    scene_refs: List[str],
    character_refs: List[str],
    prop_refs: List[str],
    binding_suggestions: Optional[Dict[str, Any]] = None,
    prompt_locks: Optional[Dict[str, Any]] = None,
) -> str:
    if prompt_locks:
        sections: List[str] = ["分镜设定："]
        groups = [
            ("角色锁定", prompt_locks.get("character_lock") or []),
            ("场景锁定", prompt_locks.get("scene_lock") or []),
            ("道具锁定", prompt_locks.get("prop_lock") or []),
            ("统一画面约束", prompt_locks.get("global_constraints") or []),
        ]
        for title, rows in groups:
            clean_rows = _compact_prompt_clauses(rows, limit=3 if title == "统一画面约束" else 2)
            if not clean_rows:
                continue
            sections.append(f"【{title}】")
            sections.extend([_sanitize_double_at(row) for row in clean_rows])
        return "\n".join([item for item in sections if item]).strip()

    mention_scene_refs = _normalize_asset_name_list(_bound_ref_names(binding_suggestions, "scenes"))
    mention_character_refs = _normalize_asset_name_list(_bound_ref_names(binding_suggestions, "characters"))
    mention_prop_refs = _normalize_asset_name_list(_bound_ref_names(binding_suggestions, "props"))
    parts: List[str] = []
    if mention_character_refs:
        parts.append(f"{_join_asset_tokens(mention_character_refs)}保持人物外观、服装与表情连续")
    if mention_prop_refs:
        parts.append(f"{_join_asset_tokens(mention_prop_refs)}保持关键道具状态连续")
    if mention_scene_refs:
        parts.append(f"{_join_asset_tokens(mention_scene_refs)}保持场景空间方向与背景关系稳定")
    if scene_constraint and not _is_low_information_text(scene_constraint):
        parts.append(resolve_segment_asset_mentions(scene_constraint, scene_refs=mention_scene_refs, character_refs=mention_character_refs, prop_refs=mention_prop_refs))
    elif summary:
        parts.append(resolve_segment_asset_mentions(summary, scene_refs=mention_scene_refs, character_refs=mention_character_refs, prop_refs=mention_prop_refs))
    body = "；".join(_compact_prompt_clauses(parts, limit=4)).strip("；")
    body = _sanitize_double_at(body)
    return f"分镜设定：\n{body}" if body else "分镜设定："


def render_gridcell_image_prompt(cell: Dict[str, Any]) -> str:
    cell_index = int(cell.get("cell_index") or 1)
    segment_grid_count = normalize_grid_count(cell.get("segment_grid_count"))
    shot_type = normalize_shot_type_label(cell.get("shot_type") or "中景")
    camera_motion = normalize_camera_motion_label(cell.get("camera_motion") or "固定")
    camera_setup = "，".join(
        [
            item for item in [
                str(cell.get("camera_position") or "").strip(),
                str(cell.get("camera_direction") or "").strip(),
            ] if item
        ]
    )
    shot_description = resolve_segment_asset_mentions(
        _clean_low_information_text(cell.get("shot_description")),
        scene_refs=cell.get("scene_refs") or [],
        character_refs=cell.get("character_refs") or [],
        prop_refs=cell.get("prop_refs") or [],
    )
    action_description = resolve_segment_asset_mentions(
        _clean_low_information_text(cell.get("action_description")),
        scene_refs=cell.get("scene_refs") or [],
        character_refs=cell.get("character_refs") or [],
        prop_refs=cell.get("prop_refs") or [],
    )
    composition = _clean_low_information_text(cell.get("composition"))
    lighting = _clean_low_information_text(cell.get("lighting"))
    ambiance = _clean_low_information_text(cell.get("ambiance"))
    shot_purpose = _clean_low_information_text(cell.get("shot_purpose"))
    block_label = "宫格" if segment_grid_count > 1 else "镜头"
    lines = [f"[{block_label}{cell_index}]"]
    lines.append(f"【当前动作】{_sanitize_double_at(action_description or shot_description or '聚焦当前宫格的主体动作、表情或关键状态变化')}")
    lines.append(f"【机位与朝向】{_sanitize_double_at(camera_setup or '镜头位于主体动作前方或侧前方，朝向当前动作焦点')}")
    lines.append(f"【景别】{shot_type}")
    if shot_description and shot_description != action_description and shot_description not in str(action_description or "") and not _is_low_information_text(shot_description):
        lines.append(f"【局部补充】{_sanitize_double_at(shot_description)}")
    lines.append(f"【构图】{_sanitize_double_at(composition or '主体明确位于视觉焦点，前后景关系清晰，空间方向可读')}")
    lines.append(f"【运镜】{camera_motion}")
    lines.append(f"【镜头功能】{_sanitize_double_at(shot_purpose or '交代当前动作推进、情绪变化或关键叙事信息')}")
    if lighting:
        lines.append(f"【局部光线】{_sanitize_double_at(lighting)}")
    if ambiance:
        lines.append(f"【局部氛围】{_sanitize_double_at(ambiance)}")
    return "\n".join(lines).strip()


def render_gridcell_video_prompt(
    cell: Dict[str, Any],
    *,
    next_cell: Optional[Dict[str, Any]] = None,
    transition_to_next: str = "cut",
) -> str:
    structured = resolve_gridcell_video_prompt_structured(
        cell,
        next_cell=next_cell,
        transition_to_next=transition_to_next,
    )
    return _sanitize_double_at(render_video_control_line_from_structured(structured) or "画面聚焦当前关键动作、反应或状态变化")


def render_segment_multi_shot_prompt(scene_prompt: str, cells: List[Dict[str, Any]], *, layout_spec: Optional[Dict[str, Any]] = None) -> str:
    parts = [_sanitize_double_at(str(scene_prompt or "").strip())]
    if isinstance(layout_spec, dict) and layout_spec.get("is_multigrid"):
        layout_lines = ["版式要求：", str(layout_spec.get("layout_prompt") or "").strip()]
        layout_lines.extend([str(item or "").strip() for item in (layout_spec.get("layout_requirements") or []) if str(item or "").strip()])
        parts.append("\n".join([_sanitize_double_at(item) for item in layout_lines if item]))
    for cell in cells:
        raw_prompt = str(cell.get("image_prompt") or "").strip()
        prompt = render_gridcell_image_prompt(cell) if _should_use_compiled_prompt(raw_prompt) else _sanitize_double_at(raw_prompt)
        if prompt:
            parts.append(prompt)
    return "\n\n".join([item for item in parts if item]).strip()


def render_segment_video_timeline_prompt(cells: List[Dict[str, Any]], transition_to_next: str = "cut", storyboard_mode: Optional[str] = None) -> str:
    lines: List[str] = []
    total = len(cells)
    for index, cell in enumerate(cells):
        start = int(round(float(cell.get("start_second") or 0.0)))
        end = int(round(float(cell.get("end_second") or 0.0)))
        if end <= start:
            continue
        raw_prompt = str(cell.get("video_prompt") or "").strip()
        next_cell = cells[index + 1] if index + 1 < total else None
        effective_transition = transition_to_next if index == total - 1 else "cut"
        content = render_gridcell_video_prompt(
            cell,
            next_cell=next_cell,
            transition_to_next=effective_transition,
        ) if _should_use_compiled_prompt(raw_prompt) else _sanitize_double_at(raw_prompt)
        if not content:
            continue
        lines.append(f"{start}-{end}秒：{content}")
    return "\n".join(lines).strip()


def _render_comic_segment_video_prompt(payloads: List[Dict[str, Any]], *, transition_to_next: str = "cut") -> str:
    if not payloads:
        return ""
    structured_rows = []
    total = len(payloads)
    for index, payload in enumerate(payloads):
        structured_rows.append(
            resolve_gridcell_video_prompt_structured(
                {
                    **payload,
                    "storyboard_mode": STORYBOARD_MODE_COMIC,
                },
                next_cell=payloads[index + 1] if index + 1 < total else None,
                transition_to_next=transition_to_next if index == total - 1 else "cut",
            )
        )

    merged_character_refs = _normalize_asset_name_list([
        str(name or "").strip()
        for payload in payloads
        for name in (payload.get("character_refs") or [])
        if str(name or "").strip()
    ])
    merged_prop_refs = _normalize_asset_name_list([
        str(name or "").strip()
        for payload in payloads
        for name in (payload.get("prop_refs") or [])
        if str(name or "").strip()
    ])
    merged_scene_refs = _normalize_asset_name_list([
        str(name or "").strip()
        for payload in payloads
        for name in (payload.get("scene_refs") or [])
        if str(name or "").strip()
    ])

    section_lines: List[str] = []
    segment_setting_parts: List[str] = []
    if merged_character_refs:
        segment_setting_parts.append(f"{_join_asset_tokens(merged_character_refs)}保持人物外观、服装与表情连续")
    if merged_prop_refs:
        segment_setting_parts.append(f"{_join_asset_tokens(merged_prop_refs)}保持关键道具状态连续")
    if merged_scene_refs:
        segment_setting_parts.append(f"{_join_asset_tokens(merged_scene_refs)}保持场景空间方向稳定")

    scene_context = next((str(item.get("scene_context") or "").strip() for item in structured_rows if str(item.get("scene_context") or "").strip()), "")
    style_aesthetics = next((str(item.get("style_aesthetics") or "").strip() for item in structured_rows if str(item.get("style_aesthetics") or "").strip()), "")
    continuity_anchor = next((str(item.get("continuity_notes") or "").strip() for item in structured_rows if str(item.get("continuity_notes") or "").strip()), "")
    for extra in (scene_context, style_aesthetics, continuity_anchor):
        extra = _sanitize_double_at(extra)
        if extra and extra not in segment_setting_parts:
            segment_setting_parts.append(extra)
    if segment_setting_parts:
        section_lines.append("分镜设定：" + "；".join([item for item in segment_setting_parts if item]))

    reference_mapping = _build_comic_seedance_reference_mapping(
        scene_refs=merged_scene_refs,
        character_refs=merged_character_refs,
        prop_refs=merged_prop_refs,
        has_dialogue=any(bool(item.get("dialogue")) for item in structured_rows),
    )
    if reference_mapping:
        section_lines.append("参考映射：\n" + _sanitize_double_at(reference_mapping))

    section_lines.append("时间轴：")
    for index, payload in enumerate(payloads):
        start = int(round(float(payload.get("start_second") or 0.0)))
        end = int(round(float(payload.get("end_second") or 0.0)))
        if end <= start:
            continue
        structured = structured_rows[index]
        content = str(payload.get("video_prompt") or "").strip()
        if not content or _is_low_information_text(content):
            content = _render_comic_seedance_video_line(structured)
        content = _sanitize_double_at(content)
        if not content:
            continue
        section_lines.append(f"{start}-{end}秒：{content}")

    quality_constraints = "；".join(
        dict.fromkeys([_sanitize_double_at(str(item.get("negative_constraints") or "").strip()) for item in structured_rows if str(item.get("negative_constraints") or "").strip()])
    )
    if quality_constraints:
        section_lines.append("质量约束：" + quality_constraints)

    return "\n".join([item for item in section_lines if item]).strip()


def build_commentary_story_segment_prompt_v3() -> str:
    return """你是 AIdrama 解说模式分镜导演。请把输入文本拆成 story_segments 数组，并只返回 JSON。
要求：
1. 一个 story_segment 就是一个分镜，一个分镜内部再拆成多个 grid_cells。
2. 先按自然朗读边界拆分，再决定 recommended_duration_seconds 与 grid_count。
3. grid_count 只能是 1/2/4/6/9。
4. 每个 grid_cell 都要给出 start_second、end_second、duration_seconds，时间连续且总和等于分镜总时长。
5. 每个 grid_cell 都必须明确写出：shot_type、camera_motion、camera_position、camera_direction、shot_purpose、composition、lighting、ambiance。
6. 禁止输出英文景别和英文运镜；只能使用中文，如“远景 / 中景 / 近景 / 特写”“静止 / 推进 / 拉远 / 跟拍 / 左摇 / 右摇”。
7. 禁止使用空泛占位语，如“按当前场景最佳机位呈现主体动作”“主体人物围绕剧情片段展开连续表演”“自然光线，画面清晰”。
8. 画面描述只写当前镜头可见事实，不写跨时间跳跃。
9. 若命中资产，请优先使用 @人物 / @场景 / @道具 名称。
10. scene_prompt 用于“分镜设定”，grid_cells 用于“镜头1/镜头2...”。
11. 每个 grid_cell 都必须输出 `video_prompt_structured`，显式包含主体焦点、镜头语言、参考策略和限制条件。
返回 JSON 对象，结构示例：
{
  "story_segments": [
    {
      "sequence_num": 1,
      "title": "分镜标题",
      "summary": "分镜摘要",
      "text_span": {"source_excerpt": "原文摘录", "start_offset": null, "end_offset": null},
      "recommended_duration_seconds": 6,
      "grid_count": 2,
      "pacing": "slow|medium|fast",
      "rhythm": "节奏说明",
      "scene_constraint": "统一场景约束",
      "scene_prompt": "分镜设定：...",
      "continuity_note": "衔接说明",
      "transition_to_next": "cut|fade|dissolve",
      "character_refs": [],
      "scene_refs": [],
      "prop_refs": [],
      "segment_prompt_summary": "主视觉摘要",
      "grid_cells": [
        {
          "cell_index": 1,
          "start_second": 0.0,
          "end_second": 3.0,
          "duration_seconds": 3.0,
          "shot_description": "当前镜头可见画面",
          "action_description": "单一动作或气氛变化",
          "dialogue_excerpt": "解说摘录",
          "shot_type": "远景|中景|近景|特写",
          "camera_motion": "静止|推进|拉远|跟拍|左摇|右摇",
          "camera_position": "机位",
          "camera_direction": "朝向",
          "shot_purpose": "镜头功能",
          "composition": "构图",
          "lighting": "光线",
          "ambiance": "氛围",
          "video_prompt_structured": {
            "subject_focus": "主体焦点",
            "action": "当前镜头动作",
            "scene_context": "场景上下文",
            "camera_language": "镜头语言",
            "style_aesthetics": "风格氛围",
            "ambiance_audio": "画内音",
            "dialogue": [],
            "continuity_notes": "连续性要求",
            "transition_to_next": "切到下一镜的方式",
            "reference_strategy": "参考图/参考视频/参考音频各自控制什么",
            "negative_constraints": "限制条件"
          },
          "character_refs": [],
          "scene_refs": [],
          "prop_refs": []
        }
      ]
    }
  ]
}
只返回 JSON。"""


def build_comic_story_segment_prompt_v3() -> str:
    return """你是 AIdrama 漫剧模式分镜导演。请把输入文本拆成 story_segments 数组，并只返回 JSON。
要求：
1. 一个 story_segment 就是一个分镜，一个分镜内部再拆成多个 grid_cells。
2. 先按连续动作与剧情推进拆分，再决定 recommended_duration_seconds 与 grid_count。
3. grid_count 只能是 1/2/4/6/9。
4. 每个 grid_cell 都要给出 start_second、end_second、duration_seconds，时间连续且总和等于分镜总时长。
5. 每个 grid_cell 都必须明确写出：shot_type、camera_motion、camera_position、camera_direction、shot_purpose、composition、lighting、ambiance。
6. 禁止输出英文景别和英文运镜；只能使用中文，如“远景 / 中景 / 近景 / 特写”“静止 / 推进 / 拉远 / 跟拍 / 左摇 / 右摇”。
7. 禁止使用空泛占位语，如“按当前场景最佳机位呈现主体动作”“主体人物围绕剧情片段展开连续表演”“自然光线，画面清晰”。
8. 每个 grid_cell 只允许一个主动作焦点和一个主运镜，不要输出 panel_type、recommended_panel_type、nine_grid_prompt、panel_type_reason。
9. 若命中资产，请优先使用 @人物 / @场景 / @道具 名称。
10. scene_prompt 用于“分镜设定”，grid_cells 用于“镜头1/镜头2...”。
11. 每个 grid_cell 都必须输出 `video_prompt_structured`，显式包含主体焦点、镜头语言、参考策略和限制条件。
返回 JSON 对象，结构示例：
{
  "story_segments": [
    {
      "sequence_num": 1,
      "title": "分镜标题",
      "summary": "分镜摘要",
      "text_span": {"source_excerpt": "原文摘录", "start_offset": null, "end_offset": null},
      "recommended_duration_seconds": 6,
      "grid_count": 2,
      "pacing": "slow|medium|fast",
      "rhythm": "节奏说明",
      "scene_constraint": "统一场景约束",
      "scene_prompt": "分镜设定：...",
      "continuity_note": "衔接说明",
      "transition_to_next": "cut|fade|dissolve",
      "character_refs": [],
      "scene_refs": [],
      "prop_refs": [],
      "segment_prompt_summary": "主视觉摘要",
      "grid_cells": [
        {
          "cell_index": 1,
          "start_second": 0.0,
          "end_second": 3.0,
          "duration_seconds": 3.0,
          "shot_description": "当前镜头可见画面",
          "action_description": "单一动作推进",
          "dialogue_excerpt": "对白摘录",
          "shot_type": "远景|中景|近景|特写",
          "camera_motion": "静止|推进|拉远|跟拍|左摇|右摇",
          "camera_position": "机位",
          "camera_direction": "朝向",
          "shot_purpose": "镜头功能",
          "composition": "构图",
          "lighting": "光线",
          "ambiance": "氛围",
          "video_prompt_structured": {
            "subject_focus": "主体焦点",
            "action": "当前镜头动作",
            "scene_context": "场景上下文",
            "camera_language": "镜头语言",
            "style_aesthetics": "风格氛围",
            "ambiance_audio": "画内音",
            "dialogue": [],
            "continuity_notes": "连续性要求",
            "transition_to_next": "切到下一镜的方式",
            "reference_strategy": "参考图/参考视频/参考音频各自控制什么",
            "negative_constraints": "限制条件"
          },
          "character_refs": [],
          "scene_refs": [],
          "prop_refs": []
        }
      ]
    }
  ]
}
只返回 JSON。"""


def build_commentary_story_segment_prompt_v2() -> str:
    return """你是 AIdrama 解说模式分镜导演。请把输入文本拆成 story_segments 数组，并使用中文内容输出。
要求：
1. 一个 story_segment 就是一个分镜，一个分镜内部再拆成多个 grid_cells。
2. 先按自然朗读边界拆分，再决定 recommended_duration_seconds 与 grid_count。
3. grid_count 只能是 1/2/4/6/9。
4. 每个 grid_cell 都要给出 start_second、end_second、duration_seconds，时间连续且总和等于分镜总时长。
5. 每个 grid_cell 只描述当前镜头可见事实，不写跨时间跳跃内容。
6. 优先输出人物/场景/道具引用，若命中资产请直接使用对应名称。
7. scene_prompt 用于“分镜设定”，grid_cells 用于“镜头1/镜头2...”。
返回 JSON 对象：
{
  "story_segments": [
    {
      "sequence_num": 1,
      "title": "分镜标题",
      "summary": "分镜摘要",
      "text_span": {"source_excerpt": "原文摘录", "start_offset": null, "end_offset": null},
      "recommended_duration_seconds": 6,
      "grid_count": 2,
      "pacing": "slow|medium|fast",
      "rhythm": "节奏说明",
      "scene_constraint": "统一场景约束",
      "scene_prompt": "分镜设定：...",
      "continuity_note": "衔接说明",
      "transition_to_next": "cut|fade|dissolve",
      "character_refs": [],
      "scene_refs": [],
      "prop_refs": [],
      "segment_prompt_summary": "主视觉摘要",
      "grid_cells": [
        {
          "cell_index": 1,
          "start_second": 0.0,
          "end_second": 3.0,
          "duration_seconds": 3.0,
          "shot_description": "当前镜头可见画面",
          "action_description": "单一动作或气氛变化",
          "dialogue_excerpt": "解说摘录",
          "shot_type": "远景|中景|近景|特写",
          "camera_motion": "静止|推镜|拉镜|跟拍",
          "camera_position": "机位",
          "camera_direction": "朝向",
          "shot_purpose": "镜头功能",
          "composition": "构图",
          "lighting": "光线",
          "ambiance": "氛围",
          "character_refs": [],
          "scene_refs": [],
          "prop_refs": []
        }
      ]
    }
  ]
}
只返回 JSON。"""


def build_comic_story_segment_prompt_v2() -> str:
    return """你是 AIdrama 漫剧模式分镜导演。请把输入文本拆成 story_segments 数组，并使用中文内容输出。
要求：
1. 一个 story_segment 就是一个分镜，一个分镜内部再拆成多个 grid_cells。
2. 先按连续动作与剧情推进拆分，再决定 recommended_duration_seconds 与 grid_count。
3. grid_count 只能是 1/2/4/6/9。
4. 每个 grid_cell 都要给出 start_second、end_second、duration_seconds，时间连续且总和等于分镜总时长。
5. 每个 grid_cell 只允许一个主动作焦点和一个主运镜。
6. 不要输出 panel_type、recommended_panel_type、nine_grid_prompt、panel_type_reason。
7. scene_prompt 用于“分镜设定”，grid_cells 用于“镜头1/镜头2...”。
返回 JSON 对象，字段结构与 commentary 相同，但 action_description、dialogue_excerpt、continuity_note 要更强调动作、对白和状态延续。
只返回 JSON。"""


def _story_segment_skeleton_prompt(storyboard_mode: str) -> str:
    mode_name = "漫剧" if storyboard_mode == STORYBOARD_MODE_COMIC else "解说"
    return f"""
你是 AIdrama 的 {mode_name} 模式剧情片段拆分器。
你只能返回一个 JSON 对象，顶层键必须是 `story_segments`。

只输出分镜结构骨架，不要输出完整图片提示词、完整视频提示词、multi_shot_prompt、multi_shot_video_prompt、scene_prompt、panel_drafts、nine_grid_prompt。

每个 story_segment 只允许这些字段：
- sequence_num
- title
- summary
- text_span
- recommended_duration_seconds
- grid_count
- pacing
- rhythm
- scene_constraint
- continuity_note
- transition_to_next
- character_refs
- scene_refs
- prop_refs
- segment_prompt_summary
- grid_cells

每个 grid_cell 只允许这些字段：
- cell_index
- start_second
- end_second
- duration_seconds
- shot_description
- action_description
- dialogue_excerpt
- shot_type
- camera_motion
- camera_position
- camera_direction
- shot_purpose
- composition
- lighting
- ambiance
- character_refs
- scene_refs
- prop_refs

硬规则：
1. recommended_duration_seconds 必须是 4 到 15 的整数。
2. start_second / end_second / duration_seconds 必须全部是整数秒，不允许 1.5 这类小数。
3. grid_count 只能是 1 / 2 / 4 / 6 / 9。
4. 每个 grid_cell 必须写当前镜头可见事实，不能写空泛占位句。
5. 每个 grid_cell 只能有一个主动作焦点和一个主运镜。
6. 如果命中项目资产，优先使用 @人物 / @场景 / @道具 名称。
7. 不要输出任何解释，不要输出 markdown，不要输出代码块。
""".strip()


def _story_segment_few_shot_example() -> str:
    return (
        "{\n"
        "  \"story_segments\": [\n"
        "    {\n"
        "      \"sequence_num\": 1,\n"
        "      \"title\": \"\\u5723\\u65e8\\u5230\\u573a\",\n"
        "      \"summary\": \"\\u5371\\u6025\\u5173\\u5934\\uff0c\\u592a\\u76d1\\u5e26\\u7740\\u5723\\u65e8\\u8d76\\u5230\\u3002\",\n"
        "      \"text_span\": {\"source_excerpt\": \"\\u592a\\u76d1\\u5c55\\u5f00\\u5723\\u65e8\\uff0c\\u6ee1\\u6bbf\\u5bc2\\u9759\\u3002\", \"start_offset\": null, \"end_offset\": null},\n"
        "      \"recommended_duration_seconds\": 6,\n"
        "      \"grid_count\": 2,\n"
        "      \"pacing\": \"medium\",\n"
        "      \"rhythm\": \"\\u5148\\u5efa\\u7acb\\u538b\\u8feb\\uff0c\\u518d\\u5207\\u5165\\u5ba3\\u65e8\\u52a8\\u4f5c\",\n"
        "      \"scene_constraint\": \"@\\u91d1\\u92ae\\u6bbf \\u5185\\u666f\\uff0c\\u4eba\\u7269\\u7ad9\\u4f4d\\u7a33\\u5b9a\",\n"
        "      \"continuity_note\": \"\\u4e0a\\u4e00\\u955c\\u7684\\u7d27\\u5f20\\u6c14\\u6c1b\\u5ef6\\u7eed\\u5230\\u5ba3\\u65e8\\u65f6\\u523b\",\n"
        "      \"transition_to_next\": \"cut\",\n"
        "      \"character_refs\": [\"@\\u592a\\u76d1\"],\n"
        "      \"scene_refs\": [\"@\\u91d1\\u92ae\\u6bbf\"],\n"
        "      \"prop_refs\": [\"@\\u5723\\u65e8\"],\n"
        "      \"segment_prompt_summary\": \"\\u538b\\u8feb\\u6c1b\\u56f4\\u4e2d\\u7684\\u5ba3\\u65e8\\u52a8\\u4f5c\",\n"
        "      \"grid_cells\": [\n"
        "        {\n"
        "          \"cell_index\": 1,\n"
        "          \"start_second\": 0,\n"
        "          \"end_second\": 3,\n"
        "          \"duration_seconds\": 3,\n"
        "          \"shot_description\": \"@\\u91d1\\u92ae\\u6bbf \\u5185\\u666f\\uff0c@\\u592a\\u76d1 \\u5feb\\u6b65\\u8d70\\u5411\\u6bbf\\u4e2d\\u3002\",\n"
        "          \"action_description\": \"@\\u592a\\u76d1 \\u6367\\u7740 @\\u5723\\u65e8 \\u8fdb\\u5165\\u753b\\u9762\\u4e2d\\u592e\\u3002\",\n"
        "          \"dialogue_excerpt\": \"\",\n"
        "          \"shot_type\": \"\\u4e2d\\u666f\",\n"
        "          \"camera_motion\": \"\\u8ddf\\u62cd\",\n"
        "          \"camera_position\": \"\\u6bbf\\u4e2d\\u4eba\\u7fa4\\u540e\\u4fa7\",\n"
        "          \"camera_direction\": \"\\u671d\\u5411\\u6bbf\\u4e2d\\u592e\",\n"
        "          \"shot_purpose\": \"\\u628a\\u53d9\\u4e8b\\u7126\\u70b9\\u4ece\\u51b2\\u7a81\\u8f6c\\u5230\\u5723\\u65e8\\u5230\\u573a\",\n"
        "          \"composition\": \"\\u524d\\u666f\\u7fa4\\u81e3\\u865a\\u5316\\uff0c\\u4e2d\\u666f\\u4fdd\\u7559 @\\u592a\\u76d1 \\u52a8\\u4f5c\\u8def\\u5f84\",\n"
        "          \"lighting\": \"\\u6bbf\\u5185\\u6696\\u8272\\u70db\\u5149\",\n"
        "          \"ambiance\": \"\\u538b\\u6291\\u3001\\u8083\\u9759\",\n"
        "          \"character_refs\": [\"@\\u592a\\u76d1\"],\n"
        "          \"scene_refs\": [\"@\\u91d1\\u92ae\\u6bbf\"],\n"
        "          \"prop_refs\": [\"@\\u5723\\u65e8\"]\n"
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ]\n"
        "}"
    )


def _repair_story_segment_json_payload(
    raw_content: str,
    *,
    api_key: str,
    storyboard_mode: str,
    timeout_seconds: Optional[float],
    schema_prompt: Optional[str] = None,
    example_prompt: Optional[str] = None,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> Dict[str, Any]:
    if not str(raw_content or "").strip():
        raise StorySegmentParseError("provider_invalid_json", "模型返回为空")

    repair_user_prompt = (
        f"{schema_prompt or _story_segment_skeleton_prompt(storyboard_mode)}\n\n"
        "你上一次返回的内容不是合法 JSON。\n"
        "请严格按照上面的 schema 和示例，把内容修复成一个合法 JSON 对象。\n\n"
        f"{example_prompt or _story_segment_few_shot_example()}\n\n"
        "待修复内容：\n"
        f"{raw_content}"
    )
    prompt_text = "\n".join([
        "修复 JSON，只返回合法 JSON 对象。",
        repair_user_prompt,
    ])
    _ensure_deepseek_prompt_budget(
        user_prompt=repair_user_prompt,
        max_tokens=settings.DEEPSEEK_JSON_FIX_MAX_TOKENS,
        error_code="json_fix_failed",
        label="JSON 修复",
    )

    client_timeout = None if timeout_seconds in (None, 0) else max(float(timeout_seconds), 1.0)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=client_timeout)
    response = _create_deepseek_chat_completion(
        client,
        model=settings.DEEPSEEK_JSON_FIX_MODEL,
        messages=[
            {"role": "system", "content": "修复 JSON，只返回合法 JSON 对象。"},
            {"role": "user", "content": repair_user_prompt},
        ],
        max_tokens=settings.DEEPSEEK_JSON_FIX_MAX_TOKENS,
    )
    if usage_callback is not None:
        usage_callback(
            "json_fix",
            settings.DEEPSEEK_JSON_FIX_MODEL,
            {
                **_build_usage_fallback(
                    prompt_text=prompt_text,
                    output_text=str(response.choices[0].message.content or ""),
                    usage=_response_usage_to_dict(response),
                ),
                "thinking_enabled": 0,
            },
        )
    try:
        return extract_json_payload(response.choices[0].message.content or "")
    except Exception as exc:
        raise StorySegmentParseError("json_fix_failed", "模型返回的 JSON 修复结果仍然非法", detail=str(exc)) from exc


def _call_json_model_with_repair(
    *,
    api_key: str,
    model: str,
    provider_timeout_seconds: Optional[float],
    json_fix_timeout_seconds: Optional[float],
    max_tokens: int,
    system_prompt: str,
    user_prompt: str,
    repair_storyboard_mode: str,
    repair_schema_prompt: Optional[str],
    repair_example_prompt: Optional[str],
    provider_timeout_code: str,
    provider_timeout_message: str,
    provider_error_code: str,
    provider_error_message: str,
    invalid_json_code: str,
    invalid_json_message: str,
    on_json_fix_start: Optional[Callable[[], None]] = None,
    on_json_fix_end: Optional[Callable[[], None]] = None,
    thinking_enabled: bool = False,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
    usage_phase: Optional[str] = None,
    strict_function_name: Optional[str] = None,
    strict_function_description: Optional[str] = None,
    strict_parameters_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    _ensure_deepseek_prompt_budget(
        user_prompt=user_prompt,
        max_tokens=max_tokens,
        error_code=provider_timeout_code,
        label="DeepSeek 请求",
    )
    if settings.DEEPSEEK_STORY_SEGMENT_USE_STRICT_SCHEMA and strict_function_name and strict_parameters_schema:
        try:
            return _call_strict_tool_completion(
                api_key=api_key,
                model=model,
                provider_timeout_seconds=provider_timeout_seconds,
                function_name=strict_function_name,
                function_description=strict_function_description or strict_function_name,
                parameters_schema=strict_parameters_schema,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                thinking_enabled=thinking_enabled,
                usage_callback=usage_callback,
                usage_phase=usage_phase,
                max_tokens=max_tokens,
            )
        except APITimeoutError as exc:
            raise StorySegmentParseError(provider_timeout_code, provider_timeout_message, detail=str(exc)) from exc
        except Exception:
            pass

    def _alternate_story_segment_model(value: str) -> str:
        normalized = str(value or "").strip()
        model_source = settings.DEEPSEEK_AGENT_DEFAULT_MODEL if "reasoner" in normalized.lower() else settings.DEEPSEEK_AGENT_REASONER_MODEL
        alternate_model, _ = normalize_deepseek_model(model_source, thinking_enabled="reasoner" not in normalized.lower())
        return alternate_model

    client_timeout = None if provider_timeout_seconds in (None, 0) else max(float(provider_timeout_seconds), 1.0)
    models_to_try = [str(model or "").strip()]
    alternate_model = _alternate_story_segment_model(model)
    if alternate_model and alternate_model not in models_to_try:
        models_to_try.append(alternate_model)
    try:
        max_json_attempts = int(getattr(settings, "DEEPSEEK_STORY_SEGMENT_JSON_RETRY_ATTEMPTS", 4) or 4)
    except Exception:
        max_json_attempts = 4
    max_json_attempts = max(2, min(max_json_attempts, 8))
    expanded_models_to_try: List[str] = []
    while len(expanded_models_to_try) < max_json_attempts:
        for candidate_model in models_to_try:
            expanded_models_to_try.append(candidate_model)
            if len(expanded_models_to_try) >= max_json_attempts:
                break

    last_error: Optional[StorySegmentParseError] = None
    for attempt_index, attempt_model in enumerate(expanded_models_to_try):
        attempt_model, attempt_thinking = normalize_deepseek_model(attempt_model, thinking_enabled=thinking_enabled)
        client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com",
            timeout=client_timeout,
        )
        try:
            response = _create_deepseek_chat_completion(
                client,
                model=attempt_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                thinking_enabled=attempt_thinking,
            )
        except APITimeoutError as exc:
            raise StorySegmentParseError(provider_timeout_code, provider_timeout_message, detail=str(exc)) from exc
        except Exception as exc:
            raise StorySegmentParseError(provider_error_code, provider_error_message, detail=str(exc)) from exc

        raw_content = response.choices[0].message.content or ""
        if usage_callback is not None:
            usage_callback(
                usage_phase or "json",
                attempt_model,
                {
                    **_build_usage_fallback(
                        prompt_text="\n".join([system_prompt, user_prompt]),
                        output_text=raw_content,
                        usage=_response_usage_to_dict(response),
                    ),
                    "thinking_enabled": int(bool(attempt_thinking)),
                },
            )

        if not str(raw_content or "").strip():
            last_error = StorySegmentParseError(invalid_json_code, invalid_json_message, detail=f"empty_response:{attempt_model}")
            if attempt_index < len(expanded_models_to_try) - 1:
                continue
            raise last_error

        try:
            return extract_json_payload(raw_content)
        except Exception:
            if on_json_fix_start:
                on_json_fix_start()
            try:
                repaired = _repair_story_segment_json_payload(
                    raw_content,
                    api_key=api_key,
                    storyboard_mode=repair_storyboard_mode,
                    timeout_seconds=json_fix_timeout_seconds,
                    schema_prompt=repair_schema_prompt,
                    example_prompt=repair_example_prompt,
                    usage_callback=usage_callback,
                )
            except StorySegmentParseError as exc:
                if exc.error_code in {"provider_invalid_json", "json_fix_failed"}:
                    last_error = StorySegmentParseError(
                        invalid_json_code,
                        invalid_json_message,
                        detail=getattr(exc, "detail", None) or str(exc),
                    )
                    if attempt_index < len(expanded_models_to_try) - 1:
                        continue
                    raise last_error from exc
                raise
            except Exception as exc:
                raise StorySegmentParseError(invalid_json_code, invalid_json_message, detail=str(exc)) from exc
            if on_json_fix_end:
                on_json_fix_end()
            return repaired

    if last_error is not None:
        raise last_error
    raise StorySegmentParseError(invalid_json_code, invalid_json_message)


def call_story_segment_planner(
    user_text: str,
    api_key: str,
    structured_assets: Optional[Dict[str, Any]] = None,
    storyboard_mode: Optional[str] = None,
    *,
    model: Optional[str] = None,
    thinking_enabled: bool = False,
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
    on_json_fix_start: Optional[Callable[[], None]] = None,
    on_json_fix_end: Optional[Callable[[], None]] = None,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
    previous_chunk_continuity_summary: str = "",
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    prompt = _story_segment_planner_prompt(normalized_mode)
    asset_guardrail = build_story_segment_asset_guardrail(structured_assets or {})
    payload = _call_json_model_with_repair(
        api_key=api_key,
        model=model or settings.DEEPSEEK_STORY_SEGMENT_PLANNER_MODEL,
        provider_timeout_seconds=provider_timeout_seconds,
        json_fix_timeout_seconds=json_fix_timeout_seconds,
        max_tokens=settings.DEEPSEEK_PLANNER_MAX_TOKENS,
        system_prompt="你是剧情片段规划器，只返回合法 JSON。",
        user_prompt=f"{prompt}\n\n{asset_guardrail}\n\n{_story_segment_planner_example()}\n\nScript:\n\n{user_text}",
        repair_storyboard_mode=normalized_mode,
        repair_schema_prompt=prompt,
        repair_example_prompt=_story_segment_planner_example(),
        provider_timeout_code="planner_timeout",
        provider_timeout_message="剧情片段规划超时，请稍后重试",
        provider_error_code="provider_error",
        provider_error_message="剧情片段规划失败，请稍后重试",
        invalid_json_code="planner_invalid_json",
        invalid_json_message="剧情片段规划返回了非法 JSON",
        on_json_fix_start=on_json_fix_start,
        on_json_fix_end=on_json_fix_end,
        thinking_enabled=thinking_enabled,
        usage_callback=usage_callback,
        usage_phase="planner",
        strict_function_name="emit_story_segments",
        strict_function_description="Emit the structured story_segments plan for the current script.",
        strict_parameters_schema=_strict_story_segments_parameters_schema(),
    )
    return {
        "story_segments": [
            {
                "sequence_num": item.get("sequence_num"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "text_span": item.get("text_span"),
                "recommended_duration_seconds": clamp_segment_total_duration(item.get("recommended_duration_seconds"), 1),
                "grid_count": constrain_segment_grid_count(
                    item.get("recommended_duration_seconds"),
                    item.get("grid_count"),
                ),
                "pacing": item.get("pacing"),
                "rhythm": item.get("rhythm"),
                "scene_constraint": item.get("scene_constraint"),
                "continuity_note": item.get("continuity_note"),
                "transition_to_next": item.get("transition_to_next"),
                "character_refs": item.get("character_refs") or [],
                "scene_refs": item.get("scene_refs") or [],
                "prop_refs": item.get("prop_refs") or [],
                "segment_prompt_summary": item.get("segment_prompt_summary"),
            }
            for item in (payload.get("story_segments") or [])
            if isinstance(item, dict)
        ]
    }


def call_story_grid_expander(
    segment_plan: Dict[str, Any],
    api_key: str,
    *,
    structured_assets: Optional[Dict[str, Any]] = None,
    storyboard_mode: Optional[str] = None,
    segment_text: str = "",
    model: Optional[str] = None,
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
    on_json_fix_start: Optional[Callable[[], None]] = None,
    on_json_fix_end: Optional[Callable[[], None]] = None,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
    previous_chunk_continuity_summary: str = "",
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    prompt = _story_grid_expander_prompt(normalized_mode)
    asset_guardrail = build_story_segment_asset_guardrail(structured_assets or {})
    normalized_segment_plan = {
        **(segment_plan or {}),
        "recommended_duration_seconds": clamp_segment_total_duration(
            (segment_plan or {}).get("recommended_duration_seconds"),
            1,
        ),
        "grid_count": constrain_segment_grid_count(
            (segment_plan or {}).get("recommended_duration_seconds"),
            (segment_plan or {}).get("grid_count"),
        ),
    }
    continuity_summary = _continuity_state_summary(normalized_segment_plan.get("continuity_state") or {})
    previous_continuity_summary = str(normalized_segment_plan.get("previous_continuity_summary") or "").strip()
    user_prompt = (
        f"{prompt}\n\n"
        f"{asset_guardrail}\n\n"
        f"{_story_grid_expander_example()}\n\n"
        f"当前片段规划：\n{json.dumps(normalized_segment_plan, ensure_ascii=False)}\n\n"
        f"上一分镜连续性摘要：\n{previous_continuity_summary or '无'}\n\n"
        f"当前分镜连续性要求：\n{continuity_summary or '无'}\n\n"
        f"当前片段原文：\n{segment_text or (normalized_segment_plan.get('text_span') or {}).get('source_excerpt') or normalized_segment_plan.get('summary') or ''}"
    )
    payload = _call_json_model_with_repair(
        api_key=api_key,
        model=model or settings.DEEPSEEK_STORY_GRID_EXPANDER_MODEL,
        provider_timeout_seconds=provider_timeout_seconds,
        json_fix_timeout_seconds=json_fix_timeout_seconds,
        max_tokens=settings.DEEPSEEK_GRID_EXPANDER_MAX_TOKENS,
        system_prompt="你是多宫格镜头细化器，只返回合法 JSON。",
        user_prompt=user_prompt,
        repair_storyboard_mode=normalized_mode,
        repair_schema_prompt=prompt,
        repair_example_prompt=_story_grid_expander_example(),
        provider_timeout_code="grid_timeout",
        provider_timeout_message="片段多宫格细化超时，请稍后重试",
        provider_error_code="provider_error",
        provider_error_message="片段多宫格细化失败，请稍后重试",
        invalid_json_code="grid_invalid_json",
        invalid_json_message="片段多宫格细化返回了非法 JSON",
        on_json_fix_start=on_json_fix_start,
        on_json_fix_end=on_json_fix_end,
        usage_callback=usage_callback,
        usage_phase="expander",
        strict_function_name="emit_grid_cells",
        strict_function_description="Emit the structured grid_cells for the current story segment only.",
        strict_parameters_schema=_strict_grid_cells_parameters_schema(),
    )
    return {
        "grid_cells": [item for item in (payload.get("grid_cells") or []) if isinstance(item, dict)]
    }


def call_story_segment_model_v2(
    user_text: str,
    api_key: str,
    structured_assets: Optional[Dict[str, Any]] = None,
    storyboard_mode: Optional[str] = None,
    *,
    model: Optional[str] = None,
    thinking_enabled: bool = False,
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    asset_guardrail = build_story_segment_asset_guardrail(structured_assets or {})
    user_prompt = (
        f"{_story_segment_skeleton_prompt(normalized_mode)}\n\n"
        f"{asset_guardrail}\n\n"
        f"{_story_segment_few_shot_example()}\n\n"
        f"Script:\n\n{user_text}"
    )
    _ensure_deepseek_prompt_budget(
        user_prompt=user_prompt,
        max_tokens=settings.DEEPSEEK_GRID_EXPANDER_MAX_TOKENS,
        error_code="provider_timeout",
        label="\u5206\u955c\u751f\u6210",
    )
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com",
        timeout=None if provider_timeout_seconds in (None, 0) else max(float(provider_timeout_seconds), 1.0),
    )
    try:
        response = _create_deepseek_chat_completion(
            client,
            model=model or settings.DEEPSEEK_STORY_SEGMENT_MODEL,
            messages=[
                {"role": "system", "content": "\u4f60\u662f\u5206\u955c\u5bfc\u6f14\u52a9\u624b\uff0c\u53ea\u8fd4\u56de\u5408\u6cd5 JSON\u3002"},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=settings.DEEPSEEK_GRID_EXPANDER_MAX_TOKENS,
            thinking_enabled=thinking_enabled,
        )
    except APITimeoutError as exc:
        raise StorySegmentParseError("provider_timeout", "\u5206\u955c\u751f\u6210\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5", detail=str(exc)) from exc
    except Exception as exc:
        raise StorySegmentParseError("provider_error", "\u5206\u955c\u751f\u6210\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5", detail=str(exc)) from exc

    raw_content = response.choices[0].message.content or ""
    if usage_callback is not None:
        usage_callback(
            "direct",
            model or settings.DEEPSEEK_STORY_SEGMENT_MODEL,
            _build_usage_fallback(
                prompt_text="\n".join(["\u4f60\u662f\u5206\u955c\u5bfc\u6f14\u52a9\u624b\uff0c\u53ea\u8fd4\u56de\u5408\u6cd5 JSON\u3002", user_prompt]),
                output_text=raw_content,
                usage=_response_usage_to_dict(response),
            ),
        )
    try:
        return extract_json_payload(raw_content)
    except Exception:
        print("[story-segment] json-fix-start")
        try:
            repaired = _repair_story_segment_json_payload(
                raw_content,
                api_key=api_key,
                storyboard_mode=normalized_mode,
                timeout_seconds=json_fix_timeout_seconds,
                usage_callback=usage_callback,
            )
            print("[story-segment] json-fix-done")
            return repaired
        except StorySegmentParseError:
            raise
        except APITimeoutError as repair_exc:
            raise StorySegmentParseError(
                "json_fix_failed",
                "\u5206\u955c\u751f\u6210\u8fd4\u56de\u4e86\u975e\u6cd5 JSON\uff0c\u4e14 JSON \u4fee\u590d\u8d85\u65f6",
                detail=str(repair_exc),
            ) from repair_exc
        except Exception as repair_exc:
            raise StorySegmentParseError(
                "json_fix_failed",
                "\u5206\u955c\u751f\u6210\u8fd4\u56de\u4e86\u975e\u6cd5 JSON\uff0c\u4e14\u4fee\u590d\u5931\u8d25",
                detail=str(repair_exc),
            ) from repair_exc


def repair_story_segments_semantically(
    *,
    story_segments: List[Dict[str, Any]],
    validation_errors: List[str],
    api_key: str,
    storyboard_mode: Optional[str],
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    error_text = "\n".join(f"- {item}" for item in validation_errors if str(item or "").strip())
    empty_error_text = "- \u65e0"
    user_prompt = (
        f"{_story_segment_skeleton_prompt(normalized_mode)}\n\n"
        "\u4f60\u662f\u5206\u955c\u8bed\u4e49\u4fee\u590d\u5668\u3002\u4e0b\u9762\u7ed9\u4f60\u5f53\u524d\u5df2\u7ecf\u751f\u6210\u7684 story_segments \u548c\u672c\u5730\u6821\u9a8c\u9519\u8bef\u5217\u8868\u3002"
        "\u4f60\u53ea\u80fd\u4fee\u590d\u4e0e\u9519\u8bef\u5217\u8868\u76f4\u63a5\u76f8\u5173\u7684\u95ee\u9898\uff0c\u4e0d\u8981\u91cd\u5199\u5267\u60c5\uff0c\u4e0d\u8981\u65b0\u589e\u65e0\u5173\u7247\u6bb5\uff0c\u4e0d\u8981\u5220\u9664\u65e0\u5173\u5b57\u6bb5\u3002\n\n"
        f"\u5f53\u524d\u6821\u9a8c\u9519\u8bef\uff1a\n{error_text or empty_error_text}\n\n"
        f"\u5f53\u524d story_segments\uff1a\n{json.dumps({'story_segments': story_segments}, ensure_ascii=False)}"
    )
    return _call_json_model_with_repair(
        api_key=api_key,
        model=settings.DEEPSEEK_STORY_SEGMENT_CRITIC_MODEL,
        provider_timeout_seconds=provider_timeout_seconds,
        json_fix_timeout_seconds=json_fix_timeout_seconds,
        max_tokens=settings.DEEPSEEK_PLANNER_MAX_TOKENS,
        system_prompt="\u4f60\u662f\u5206\u955c\u8bed\u4e49\u4fee\u590d\u5668\uff0c\u53ea\u8fd4\u56de\u5408\u6cd5 JSON\uff0c\u5bf9 story_segments \u505a\u6700\u5c0f\u5fc5\u8981\u4fee\u6b63\u3002",
        user_prompt=user_prompt,
        repair_storyboard_mode=normalized_mode,
        repair_schema_prompt=_story_segment_skeleton_prompt(normalized_mode),
        repair_example_prompt=_story_segment_few_shot_example(),
        provider_timeout_code="critic_timeout",
        provider_timeout_message="\u5206\u955c\u8bed\u4e49\u4fee\u590d\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5",
        provider_error_code="provider_error",
        provider_error_message="\u5206\u955c\u8bed\u4e49\u4fee\u590d\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5",
        invalid_json_code="critic_invalid_json",
        invalid_json_message="\u5206\u955c\u8bed\u4e49\u4fee\u590d\u8fd4\u56de\u4e86\u975e\u6cd5 JSON",
        usage_callback=usage_callback,
        usage_phase="critic",
    )


def _nullable_string_schema() -> Dict[str, Any]:
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "null"},
        ]
    }


def _strict_story_language_beats_parameters_schema() -> Dict[str, Any]:
    string_list = {"type": "array", "items": {"type": "string"}}
    beat_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "beat_id": {"type": "string"},
            "source_excerpt": {"type": "string"},
            "event_type": {"type": "string"},
            "speaker_name": _nullable_string_schema(),
            "speaker_ref": _nullable_string_schema(),
            "listener_refs": string_list,
            "text": {"type": "string"},
            "emotion": _nullable_string_schema(),
            "intensity": _nullable_string_schema(),
            "mouth_sync_required": {"type": "boolean"},
            "visual_priority": _nullable_string_schema(),
            "split_recommendation": _nullable_string_schema(),
        },
        "required": [
            "beat_id",
            "source_excerpt",
            "event_type",
            "speaker_name",
            "speaker_ref",
            "listener_refs",
            "text",
            "emotion",
            "intensity",
            "mouth_sync_required",
            "visual_priority",
            "split_recommendation",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"language_beats": {"type": "array", "items": beat_item}},
        "required": ["language_beats"],
    }


def _normalize_language_beats(beats: Any, *, structured_assets: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    asset_names = {
        str(item.get("name") or "").strip()
        for group in ((structured_assets or {}).get("characters") or [])
        for item in ([group] if isinstance(group, dict) else [])
    }
    normalized: List[Dict[str, Any]] = []
    if not isinstance(beats, list):
        return normalized
    for index, item in enumerate(beats, start=1):
        if not isinstance(item, dict):
            continue
        event_type = str(item.get("event_type") or "").strip().lower()
        if event_type not in VALID_LANGUAGE_BEAT_TYPES:
            event_type = "action_reaction"
        speaker_name = str(item.get("speaker_name") or "").strip()
        speaker_ref = str(item.get("speaker_ref") or "").strip()
        if not speaker_ref and speaker_name and speaker_name in asset_names:
            speaker_ref = _asset_token(speaker_name)
        listener_refs = [str(ref or "").strip() for ref in (item.get("listener_refs") or []) if str(ref or "").strip()]
        intensity = str(item.get("intensity") or "medium").strip().lower()
        if intensity not in VALID_SPEECH_INTENSITIES:
            intensity = "medium"
        visual_priority = str(item.get("visual_priority") or "medium").strip().lower()
        if visual_priority not in VALID_VISUAL_PRIORITIES:
            visual_priority = "medium"
        split_recommendation = str(item.get("split_recommendation") or "prefer_new_cell").strip().lower()
        if split_recommendation not in VALID_SPLIT_RECOMMENDATIONS:
            split_recommendation = "prefer_new_cell"
        mouth_sync_required = bool(
            item.get("mouth_sync_required")
            if item.get("mouth_sync_required") is not None
            else event_type == "spoken_dialogue"
        )
        normalized.append(
            {
                "beat_id": str(item.get("beat_id") or f"LB{index:02d}").strip() or f"LB{index:02d}",
                "source_excerpt": str(item.get("source_excerpt") or item.get("text") or "").strip(),
                "event_type": event_type,
                "speaker_name": speaker_name,
                "speaker_ref": speaker_ref,
                "listener_refs": listener_refs,
                "text": str(item.get("text") or item.get("source_excerpt") or "").strip(),
                "emotion": str(item.get("emotion") or "").strip(),
                "intensity": intensity,
                "mouth_sync_required": mouth_sync_required,
                "visual_priority": visual_priority,
                "split_recommendation": split_recommendation,
            }
        )
    return normalized


def _story_language_beat_extractor_prompt(storyboard_mode: str) -> str:
    mode_name = "漫剧" if storyboard_mode == STORYBOARD_MODE_COMIC else "解说"
    mode_focus = (
        "更重视张嘴对白、反应镜头和口型覆盖"
        if storyboard_mode == STORYBOARD_MODE_COMIC
        else "更重视旁白、OS 和信息表达，不强制每句都张嘴"
    )
    return (
        f"{_storyboard_director_persona_block(f'神鹿{mode_name}语言事件抽取师', '语言节拍提取专家', mode_focus)}\n\n"
        "你现在只负责输出 `language_beats`，用于决定后续分镜密度、推荐时长和表演落点。\n"
        "请优先提取会影响镜头拆分的语言/表演事件：spoken_dialogue、inner_monologue、narration、offscreen_voice、action_reaction、reveal。\n\n"
        "抽取规则：\n"
        "1. 只抓会改变分镜密度和表演调度的节拍，不要为了变多而机械拆分。\n"
        "2. 出现说话人切换、张嘴开口、内心独白、旁白插入、情绪反转、信息揭示、动作反应落点时，优先提取。\n"
        "3. `spoken_dialogue` 默认 `mouth_sync_required=true`，其余默认 `false`。\n"
        "4. `speaker_ref` 只有在确实命中已有角色资产时才输出，否则保留 `speaker_name` 纯文本。\n"
        "5. `split_recommendation` 默认偏向 `prefer_new_cell`；只有场景切换、主要动作阶段切换或重大揭示时才使用 `prefer_new_segment`。\n"
        "6. `visual_priority` 和 `intensity` 只能是 `low / medium / high`。\n"
        "7. 保留完整原句，不要改写对白内容；长句可以保留整句，后续系统会再按时长细分。\n\n"
        f"{_storyboard_prompt_blacklist_block()}\n\n"
        "只返回 JSON。"
    )


def _story_language_beat_extractor_example() -> str:
    return (
        "{\n"
        "  \"language_beats\": [\n"
        "    {\n"
        "      \"beat_id\": \"LB01\",\n"
        "      \"source_excerpt\": \"\\u5979\\u538b\\u4f4e\\u58f0\\u97f3\\u8bf4\\uff1a\\u4f60\\u7ec8\\u4e8e\\u6765\\u4e86\\u3002\",\n"
        "      \"event_type\": \"spoken_dialogue\",\n"
        "      \"speaker_name\": \"\\u5979\",\n"
        "      \"speaker_ref\": \"@\\u5979\",\n"
        "      \"listener_refs\": [\"@\\u4ed6\"],\n"
        "      \"text\": \"\\u4f60\\u7ec8\\u4e8e\\u6765\\u4e86\\u3002\",\n"
        "      \"emotion\": \"\\u514b\\u5236\\u4f46\\u7d27\\u5f20\",\n"
        "      \"intensity\": \"medium\",\n"
        "      \"mouth_sync_required\": true,\n"
        "      \"visual_priority\": \"high\",\n"
        "      \"split_recommendation\": \"prefer_new_cell\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )


def call_story_language_beat_extractor(
    user_text: str,
    api_key: str,
    structured_assets: Optional[Dict[str, Any]] = None,
    storyboard_mode: Optional[str] = None,
    *,
    model: Optional[str] = None,
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    prompt = _story_language_beat_extractor_prompt(normalized_mode)
    asset_guardrail = build_story_segment_asset_guardrail(structured_assets or {})
    payload = _call_json_model_with_repair(
        api_key=api_key,
        model=model or settings.DEEPSEEK_STORY_SEGMENT_PLANNER_MODEL,
        provider_timeout_seconds=provider_timeout_seconds,
        json_fix_timeout_seconds=json_fix_timeout_seconds,
        max_tokens=settings.DEEPSEEK_PLANNER_MAX_TOKENS,
        system_prompt="\u4f60\u662f\u8bed\u8a00\u4e8b\u4ef6\u63d0\u53d6\u5668\uff0c\u53ea\u8fd4\u56de\u5408\u6cd5 JSON\u3002",
        user_prompt=f"{prompt}\n\n{asset_guardrail}\n\n{_story_language_beat_extractor_example()}\n\nScript:\n\n{user_text}",
        repair_storyboard_mode=normalized_mode,
        repair_schema_prompt=prompt,
        repair_example_prompt=_story_language_beat_extractor_example(),
        provider_timeout_code="language_beats_timeout",
        provider_timeout_message="\u8bed\u8a00\u4e8b\u4ef6\u63d0\u53d6\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5",
        provider_error_code="provider_error",
        provider_error_message="\u8bed\u8a00\u4e8b\u4ef6\u63d0\u53d6\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5",
        invalid_json_code="language_beats_invalid_json",
        invalid_json_message="\u8bed\u8a00\u4e8b\u4ef6\u63d0\u53d6\u8fd4\u56de\u4e86\u975e\u6cd5 JSON",
        usage_callback=usage_callback,
        usage_phase="language_beats",
        strict_function_name="emit_language_beats",
        strict_function_description="Emit the structured language_beats extracted from the script.",
        strict_parameters_schema=_strict_story_language_beats_parameters_schema(),
    )
    return {"language_beats": _normalize_language_beats(payload.get("language_beats") or [], structured_assets=structured_assets)}


def _planner_language_beat_digest(language_beats: Optional[List[Dict[str, Any]]]) -> str:
    rows: List[str] = []
    for item in language_beats or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            json.dumps(
                {
                    "beat_id": item.get("beat_id"),
                    "event_type": item.get("event_type"),
                    "speaker_name": item.get("speaker_name"),
                    "speaker_ref": item.get("speaker_ref"),
                    "text": item.get("text"),
                    "emotion": item.get("emotion"),
                    "intensity": item.get("intensity"),
                    "mouth_sync_required": item.get("mouth_sync_required"),
                    "visual_priority": item.get("visual_priority"),
                    "split_recommendation": item.get("split_recommendation"),
                    "estimated_speech_seconds": item.get("estimated_speech_seconds"),
                    "estimated_performance_seconds": item.get("estimated_performance_seconds"),
                    "estimated_total_seconds": item.get("estimated_total_seconds"),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(rows[:24])


def _select_language_beats_for_segment(segment_plan: Dict[str, Any], language_beats: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    if not language_beats:
        return []
    beat_ids = {
        str(item or "").strip()
        for item in (segment_plan.get("beat_ids") or [])
        if str(item or "").strip()
    }
    if beat_ids:
        return [item for item in language_beats if str(item.get("beat_id") or "").strip() in beat_ids]
    source_excerpt = str((segment_plan.get("text_span") or {}).get("source_excerpt") or "").strip()
    if source_excerpt:
        matched = [item for item in language_beats if str(item.get("source_excerpt") or "").strip() and str(item.get("source_excerpt") or "").strip() in source_excerpt]
        if matched:
            return matched
    return []


def _nullable_string_schema() -> Dict[str, Any]:
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "null"},
        ]
    }


def _nullable_number_schema() -> Dict[str, Any]:
    return {
        "anyOf": [
            {"type": "number"},
            {"type": "null"},
        ]
    }


def _strict_story_segments_parameters_schema() -> Dict[str, Any]:
    string_list = {"type": "array", "items": {"type": "string"}}
    text_span = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "source_excerpt": {"type": "string"},
            "start_offset": _nullable_number_schema(),
            "end_offset": _nullable_number_schema(),
        },
        "required": ["source_excerpt", "start_offset", "end_offset"],
    }
    segment_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sequence_num": {"type": "integer"},
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "text_span": text_span,
            "recommended_duration_seconds": {"type": "integer"},
            "grid_count": {"type": "integer"},
            "pacing": _nullable_string_schema(),
            "rhythm": _nullable_string_schema(),
            "scene_constraint": _nullable_string_schema(),
            "continuity_note": _nullable_string_schema(),
            "transition_to_next": _nullable_string_schema(),
            "character_refs": string_list,
            "scene_refs": string_list,
            "prop_refs": string_list,
            "segment_prompt_summary": _nullable_string_schema(),
            "beat_ids": string_list,
            "speech_density": _nullable_string_schema(),
            "language_focus_summary": _nullable_string_schema(),
        },
        "required": [
            "sequence_num",
            "title",
            "summary",
            "text_span",
            "recommended_duration_seconds",
            "grid_count",
            "pacing",
            "rhythm",
            "scene_constraint",
            "continuity_note",
            "transition_to_next",
            "character_refs",
            "scene_refs",
            "prop_refs",
            "segment_prompt_summary",
            "beat_ids",
            "speech_density",
            "language_focus_summary",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"story_segments": {"type": "array", "items": segment_item}},
        "required": ["story_segments"],
    }


def _strict_grid_cells_parameters_schema() -> Dict[str, Any]:
    string_list = {"type": "array", "items": {"type": "string"}}
    speech_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "speaker_name": _nullable_string_schema(),
            "speaker_ref": _nullable_string_schema(),
            "speech_type": {"type": "string"},
            "text": {"type": "string"},
            "emotion": _nullable_string_schema(),
            "intensity": _nullable_string_schema(),
            "mouth_sync_required": {"type": "boolean"},
        },
        "required": [
            "speaker_name",
            "speaker_ref",
            "speech_type",
            "text",
            "emotion",
            "intensity",
            "mouth_sync_required",
        ],
    }
    cell_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "cell_index": {"type": "integer"},
            "start_second": {"type": "number"},
            "end_second": {"type": "number"},
            "duration_seconds": {"type": "number"},
            "shot_description": {"type": "string"},
            "action_description": {"type": "string"},
            "dialogue_excerpt": {"type": "string"},
            "speech_items": {"type": "array", "items": speech_item},
            "performance_focus": _nullable_string_schema(),
            "mouth_sync_required": {"type": "boolean"},
            "shot_type": {"type": "string"},
            "camera_motion": {"type": "string"},
            "camera_position": {"type": "string"},
            "camera_direction": {"type": "string"},
            "shot_purpose": {"type": "string"},
            "composition": {"type": "string"},
            "lighting": {"type": "string"},
            "ambiance": {"type": "string"},
            "character_refs": string_list,
            "scene_refs": string_list,
            "prop_refs": string_list,
        },
        "required": [
            "cell_index",
            "start_second",
            "end_second",
            "duration_seconds",
            "shot_description",
            "action_description",
            "dialogue_excerpt",
            "speech_items",
            "performance_focus",
            "mouth_sync_required",
            "shot_type",
            "camera_motion",
            "camera_position",
            "camera_direction",
            "shot_purpose",
            "composition",
            "lighting",
            "ambiance",
            "character_refs",
            "scene_refs",
            "prop_refs",
        ],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"grid_cells": {"type": "array", "items": cell_item}},
        "required": ["grid_cells"],
    }


def _strict_grid_segments_parameters_schema() -> Dict[str, Any]:
    cell_schema = _strict_grid_cells_parameters_schema()["properties"]["grid_cells"]["items"]
    segment_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sequence_num": {"type": "integer"},
            "grid_cells": {"type": "array", "items": cell_schema},
        },
        "required": ["sequence_num", "grid_cells"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {"grid_segments": {"type": "array", "items": segment_item}},
        "required": ["grid_segments"],
    }


def _story_segment_planner_prompt(storyboard_mode: str) -> str:
    mode_name = "漫剧" if storyboard_mode == STORYBOARD_MODE_COMIC else "解说"
    mode_focus = (
        "更强调张嘴对白镜头、反应镜头、口型和表演落点"
        if storyboard_mode == STORYBOARD_MODE_COMIC
        else "更强调旁白、OS 和信息表达，不强制每句都做开口镜头"
    )
    return (
        f"{_storyboard_director_persona_block(f'神鹿{mode_name}剧情片段规划器', '片段切分导演', mode_focus)}\n\n"
        "你现在只负责规划 `story_segments`，不负责细化 `grid_cells`。\n"
        "输入里除了原文和资产引用外，还有结构化 `language_beats`，其中包含语言节拍、表演属性和估算时长。\n\n"
        "每个 story_segment 必须输出：\n"
        "- sequence_num\n"
        "- title\n"
        "- summary\n"
        "- text_span\n"
        "- recommended_duration_seconds\n"
        "- grid_count\n"
        "- pacing\n"
        "- rhythm\n"
        "- scene_constraint\n"
        "- continuity_note\n"
        "- transition_to_next\n"
        "- character_refs\n"
        "- scene_refs\n"
        "- prop_refs\n"
        "- segment_prompt_summary\n"
        "- beat_ids\n"
        "- speech_density\n"
        "- language_focus_summary\n\n"
        "拆分规则：\n"
        "1. 先按戏剧节拍和语言节拍拆，不要只按大剧情块粗切。\n"
        "2. 说话人切换、`spoken -> inner_monologue` 切换、明显情绪反转、动作落点与语言落点分离时，优先新增 cell，不要机械切 segment。\n"
        "3. 只有场景切换、主要动作阶段切换、重大信息揭示、或单段语言时长过长时，才新增 segment。\n"
        "4. 短对白不要一人一句就单独切 segment，但可以通过更多 cell 保留表演和反应。\n"
        "5. `recommended_duration_seconds` 必须覆盖本 segment 对应 beat 说完所需的总时长；如果超过 15 秒，应改成更多 segment，而不是强塞在一个 segment 里。\n"
        "6. 优先使用 4 宫格或 6 宫格来承载中等复杂度片段；尽量少用“单宫格 + 长时长”，也不要轻易上 9 宫格。\n"
        "7. 中等时长优先落在 6-10 秒；除非剧情非常短促，否则不要把片段压得过短。\n"
        "8. 只要当前片段里出现人物对白、内心独白、旁白或画外音，就必须在该片段规划里保留这些语言层，不得在后续细化时丢失。\n"
        "9. `beat_ids` 只能引用当前输入里的 `language_beats`；`language_focus_summary` 要概括本片段的语言/心理/信息焦点。\n"
        "10. `speech_density` 只能是 `low / medium / high`。\n"
        "11. 禁止提前输出 `grid_cells`、完整图片提示词、完整视频提示词、`scene_prompt`、`multi_shot_prompt`、`multi_shot_video_prompt`。\n\n"
        f"{_storyboard_prompt_blacklist_block()}\n\n"
        "只返回 JSON。"
    )


def _story_grid_expander_prompt(storyboard_mode: str) -> str:
    mode_name = "漫剧" if storyboard_mode == STORYBOARD_MODE_COMIC else "解说"
    mode_focus = (
        "优先把 spoken 语句拆成开口、反应、听者落点的合理组合，保证口型覆盖"
        if storyboard_mode == STORYBOARD_MODE_COMIC
        else "允许旁白、OS、画外音承载在反应镜头或静态叙事镜头上，不强制张嘴"
    )
    return (
        f"{_storyboard_director_persona_block(f'神鹿{mode_name}多宫格镜头细化器', '镜头细化导演', mode_focus)}\n\n"
        "你现在只负责输出当前片段的 `grid_cells`。\n"
        "输入里会给你当前 segment 规划、对应的 `language_beats` 及其估算时长、连续性要求和原文。\n\n"
        "每个 grid_cell 必须输出：\n"
        "- cell_index\n"
        "- start_second\n"
        "- end_second\n"
        "- duration_seconds\n"
        "- shot_description\n"
        "- action_description\n"
        "- dialogue_excerpt\n"
        "- speech_items\n"
        "- performance_focus\n"
        "- mouth_sync_required\n"
        "- shot_type\n"
        "- camera_motion\n"
        "- camera_position\n"
        "- camera_direction\n"
        "- shot_purpose\n"
        "- composition\n"
        "- lighting\n"
        "- ambiance\n"
        "- character_refs\n"
        "- scene_refs\n"
        "- prop_refs\n\n"
        "细化规则：\n"
        "1. 单个 grid_cell 只承载一个主要画面信息，或一个主要动作/情绪变化。\n"
        "2. `speech_items` 是语言真相层；`dialogue_excerpt` 只是兼容层，但也必须与 `speech_items` 一致。\n"
        "3. 每个 cell 的 `duration_seconds` 必须覆盖该格里语言内容说完所需时长，可以使用 0.1 秒精度。\n"
        "4. `performance_focus` 要明确写成当前镜头是张嘴对白格、反应格、内心独白承载格、旁白/画外音承载格或信息揭示格。\n"
        "5. 当前 segment 如果规划里带有 `speech_coverage_targets`，你必须确保这些 speech type 都至少在一个 cell 的 `speech_items` 中被覆盖到。\n"
        "6. comic 模式下，spoken 语句优先拆成反应预备 / 开口对白 / 听者反应中的合理组合；commentary 模式下，旁白和 OS 可以挂在反应镜头上。\n"
        "7. 优先把当前 segment 细化成 4 宫格或 6 宫格的中等密度布局；除非时长特别短且信息极少，否则不要做成长时长单宫格；除非时长很长且事件很多，否则不要做 9 宫格。\n"
        "8. 每个 cell 的角色、场景、道具关系都要清楚，不能让一个镜头塞入过多信息。\n"
        "9. 时间必须连续，所有 cell 总时长必须等于当前 segment 总时长。\n\n"
        f"{_storyboard_prompt_blacklist_block()}\n\n"
        "只返回 JSON。"
    )


def _story_grid_batch_expander_prompt(storyboard_mode: str) -> str:
    return (
        f"{_story_grid_expander_prompt(storyboard_mode)}\n\n"
        "整版拆分要求：\n"
        "1. 这次输入会给出完整剧本、完整剧情片段规划和每段对应的 language_beats。\n"
        "2. 必须一次性返回 `grid_segments`，每个元素包含 `sequence_num` 和该段的 `grid_cells`。\n"
        "3. `grid_segments` 必须覆盖输入中的每一个 `sequence_num`，不能漏段、合并段或新增段。\n"
        "4. 相邻片段如果剧情概述相同，也要按 `sequence_num`、对白、source_excerpt 和 language_focus_summary 区分节拍；无对白延展段不要重复上一段对白。\n"
        "5. 可以利用完整上下文保持角色、场景、道具、情绪和镜头节奏连续，但每段的 grid_cells 仍只服务该段。\n"
        "6. 每个 segment 的 `start_second` / `end_second` / `duration_seconds` 必须使用段内相对时间轴：从 0 开始，到该段 `recommended_duration_seconds` 结束；不要使用整集累计时间轴。\n"
        "7. 每段所有 cell 的 `duration_seconds` 之和必须等于该段 `recommended_duration_seconds`，不要把相邻段或整版时长累加进单段。\n"
        "8. 不输出图片提示词、视频提示词或内部推理，只输出合法 JSON。"
    )


def _story_segment_planner_example() -> str:
    return (
        "{\n"
        "  \"story_segments\": [\n"
        "    {\n"
        "      \"sequence_num\": 1,\n"
        "      \"title\": \"\\u5bf9\\u5cd9\\u5f00\\u53e3\",\n"
        "      \"summary\": \"\\u5148\\u7528\\u53cd\\u5e94\\u955c\\u5934\\u5efa\\u7acb\\u538b\\u8feb\\u611f\\uff0c\\u518d\\u843d\\u5230\\u771f\\u6b63\\u5f00\\u53e3\\u7684\\u5bf9\\u767d\\u955c\\u5934\\u3002\",\n"
        "      \"text_span\": {\"source_excerpt\": \"\\u5979\\u538b\\u4f4e\\u58f0\\u97f3\\u8bf4\\uff1a\\u4f60\\u7ec8\\u4e8e\\u6765\\u4e86\\u3002\", \"start_offset\": null, \"end_offset\": null},\n"
        "      \"recommended_duration_seconds\": 6,\n"
        "      \"grid_count\": 2,\n"
        "      \"pacing\": \"medium\",\n"
        "      \"rhythm\": \"\\u5148\\u5bf9\\u89c6\\u538b\\u4f4f\\uff0c\\u518d\\u8ba9\\u8bf4\\u8bdd\\u4eba\\u5f00\\u53e3\\u3002\",\n"
        "      \"scene_constraint\": \"@\\u623f\\u95f4\\u5185\\u666f\\uff0c\\u4e24\\u4eba\\u5bf9\\u7acb\\u7ad9\\u4f4d\\u660e\\u786e\\u3002\",\n"
        "      \"continuity_note\": \"\\u4e0a\\u4e00\\u7247\\u6bb5\\u7684\\u7d27\\u5f20\\u6c14\\u6c1b\\u5ef6\\u7eed\\u5230\\u5f00\\u53e3\\u524d\\u3002\",\n"
        "      \"transition_to_next\": \"cut\",\n"
        "      \"character_refs\": [\"@\\u5979\"],\n"
        "      \"scene_refs\": [\"@\\u623f\\u95f4\"],\n"
        "      \"prop_refs\": [],\n"
        "      \"segment_prompt_summary\": \"\\u538b\\u8feb\\u5bf9\\u5cd9\\u4e2d\\u7684\\u5f00\\u53e3\\u8bd5\\u63a2\",\n"
        "      \"beat_ids\": [\"LB01\", \"LB02\"],\n"
        "      \"speech_density\": \"high\",\n"
        "      \"language_focus_summary\": \"\\u5148\\u7ed9\\u53cd\\u5e94\\u538b\\u529b\\uff0c\\u518d\\u7ed9\\u5f20\\u5634\\u5bf9\\u767d\\u3002\"\n"
        "    }\n"
        "  ]\n"
        "}"
    )


def _story_grid_expander_example() -> str:
    return (
        "{\n"
        "  \"grid_cells\": [\n"
        "    {\n"
        "      \"cell_index\": 1,\n"
        "      \"start_second\": 0,\n"
        "      \"end_second\": 3,\n"
        "      \"duration_seconds\": 3,\n"
        "      \"shot_description\": \"悬崖全景，阴云压顶，怒江在崖底奔腾。\",\n"
        "      \"action_description\": \"先建立环境压迫感，为主角出场做铺垫。\",\n"
        "      \"dialogue_excerpt\": \"\",\n"
        "      \"speech_items\": [],\n"
        "      \"performance_focus\": \"环境建立镜头，突出危险氛围\",\n"
        "      \"mouth_sync_required\": false,\n"
        "      \"shot_type\": \"远景\",\n"
        "      \"camera_motion\": \"缓慢推进\",\n"
        "      \"camera_position\": \"高位俯视\",\n"
        "      \"camera_direction\": \"正对悬崖\",\n"
        "      \"shot_purpose\": \"建立场景与情绪基调\",\n"
        "      \"composition\": \"悬崖占据主体，怒江置于下方形成纵深\",\n"
        "      \"lighting\": \"阴天冷光\",\n"
        "      \"ambiance\": \"压抑、危险、肃杀\",\n"
        "      \"character_refs\": [],\n"
        "      \"scene_refs\": [\"@大燕江边悬崖\"],\n"
        "      \"prop_refs\": []\n"
        "    },\n"
        "    {\n"
        "      \"cell_index\": 2,\n"
        "      \"start_second\": 3,\n"
        "      \"end_second\": 6,\n"
        "      \"duration_seconds\": 3,\n"
        "      \"shot_description\": \"伊雪儿被麻绳悬在峭壁前，长发凌乱，脸色苍白。\",\n"
        "      \"action_description\": \"镜头落到主角身上，突出她濒死却克制的状态。\",\n"
        "      \"dialogue_excerpt\": \"OS：这就是结局吗……\",\n"
        "      \"speech_items\": [\n"
        "        {\n"
        "          \"speaker_name\": \"伊雪儿\",\n"
        "          \"speaker_ref\": \"@伊雪儿\",\n"
        "          \"speech_type\": \"inner_monologue\",\n"
        "          \"text\": \"这就是结局吗……\",\n"
        "          \"emotion\": \"死寂\",\n"
        "          \"intensity\": \"medium\",\n"
        "          \"mouth_sync_required\": false\n"
        "        }\n"
        "      ],\n"
        "      \"performance_focus\": \"内心独白承载镜头，突出绝望与克制\",\n"
        "      \"mouth_sync_required\": false,\n"
        "      \"shot_type\": \"中近景\",\n"
        "      \"camera_motion\": \"轻微晃动\",\n"
        "      \"camera_position\": \"平视偏上\",\n"
        "      \"camera_direction\": \"正对人物\",\n"
        "      \"shot_purpose\": \"建立主角状态\",\n"
        "      \"composition\": \"人物居中，麻绳和岩壁形成压迫线条\",\n"
        "      \"lighting\": \"冷色逆光\",\n"
        "      \"ambiance\": \"死寂、绝望\",\n"
        "      \"character_refs\": [\"@伊雪儿\"],\n"
        "      \"scene_refs\": [\"@大燕江边悬崖\"],\n"
        "      \"prop_refs\": [\"@麻绳\"]\n"
        "    }\n"
        "  ]\n"
        "}"
    )


def call_story_segment_planner(
    user_text: str,
    api_key: str,
    structured_assets: Optional[Dict[str, Any]] = None,
    storyboard_mode: Optional[str] = None,
    *,
    language_beats: Optional[List[Dict[str, Any]]] = None,
    model: Optional[str] = None,
    thinking_enabled: bool = False,
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
    on_json_fix_start: Optional[Callable[[], None]] = None,
    on_json_fix_end: Optional[Callable[[], None]] = None,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
    previous_chunk_continuity_summary: str = "",
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    prompt = _story_segment_planner_prompt(normalized_mode)
    asset_guardrail = build_story_segment_asset_guardrail(structured_assets or {})
    beat_text = _planner_language_beat_digest(language_beats)
    payload = _call_json_model_with_repair(
        api_key=api_key,
        model=model or settings.DEEPSEEK_STORY_SEGMENT_PLANNER_MODEL,
        provider_timeout_seconds=provider_timeout_seconds,
        json_fix_timeout_seconds=json_fix_timeout_seconds,
        max_tokens=settings.DEEPSEEK_PLANNER_MAX_TOKENS,
        system_prompt="\u4f60\u662f\u5267\u60c5\u7247\u6bb5\u89c4\u5212\u5668\uff0c\u53ea\u8fd4\u56de\u5408\u6cd5 JSON\u3002",
        user_prompt=(
            f"{prompt}\n\n{asset_guardrail}\n\n{_story_segment_planner_example()}\n\n"
            f"Language beats:\n{beat_text or '[]'}\n\n"
            f"上一分段连续性摘要：\n{previous_chunk_continuity_summary or '无'}\n\n"
            f"Script:\n\n{user_text}"
        ),
        repair_storyboard_mode=normalized_mode,
        repair_schema_prompt=prompt,
        repair_example_prompt=_story_segment_planner_example(),
        provider_timeout_code="planner_timeout",
        provider_timeout_message="\u5267\u60c5\u7247\u6bb5\u89c4\u5212\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5",
        provider_error_code="provider_error",
        provider_error_message="\u5267\u60c5\u7247\u6bb5\u89c4\u5212\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5",
        invalid_json_code="planner_invalid_json",
        invalid_json_message="\u5267\u60c5\u7247\u6bb5\u89c4\u5212\u8fd4\u56de\u4e86\u975e\u6cd5 JSON",
        on_json_fix_start=on_json_fix_start,
        on_json_fix_end=on_json_fix_end,
        thinking_enabled=thinking_enabled,
        usage_callback=usage_callback,
        usage_phase="planner",
        strict_function_name="emit_story_segments",
        strict_function_description="Emit the structured story_segments plan for the current script.",
        strict_parameters_schema=_strict_story_segments_parameters_schema(),
    )
    return {
        "story_segments": [
            {
                "sequence_num": item.get("sequence_num"),
                "title": item.get("title"),
                "summary": item.get("summary"),
                "text_span": item.get("text_span"),
                "recommended_duration_seconds": clamp_segment_total_duration(item.get("recommended_duration_seconds"), 1),
                "grid_count": constrain_segment_grid_count(
                    item.get("recommended_duration_seconds"),
                    item.get("grid_count"),
                ),
                "pacing": item.get("pacing"),
                "rhythm": item.get("rhythm"),
                "scene_constraint": item.get("scene_constraint"),
                "continuity_note": item.get("continuity_note"),
                "transition_to_next": item.get("transition_to_next"),
                "character_refs": item.get("character_refs") or [],
                "scene_refs": item.get("scene_refs") or [],
                "prop_refs": item.get("prop_refs") or [],
                "segment_prompt_summary": item.get("segment_prompt_summary"),
                "beat_ids": [str(beat_id or "").strip() for beat_id in (item.get("beat_ids") or []) if str(beat_id or "").strip()],
                "speech_density": str(item.get("speech_density") or "medium").strip().lower() or "medium",
                "language_focus_summary": str(item.get("language_focus_summary") or "").strip(),
            }
            for item in (payload.get("story_segments") or [])
            if isinstance(item, dict)
        ]
    }


def call_story_grid_expander(
    segment_plan: Dict[str, Any],
    api_key: str,
    *,
    structured_assets: Optional[Dict[str, Any]] = None,
    storyboard_mode: Optional[str] = None,
    segment_text: str = "",
    language_beats: Optional[List[Dict[str, Any]]] = None,
    model: Optional[str] = None,
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
    on_json_fix_start: Optional[Callable[[], None]] = None,
    on_json_fix_end: Optional[Callable[[], None]] = None,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    prompt = _story_grid_expander_prompt(normalized_mode)
    asset_guardrail = build_story_segment_asset_guardrail(structured_assets or {})
    normalized_segment_plan = {
        **(segment_plan or {}),
        "recommended_duration_seconds": clamp_segment_total_duration(
            (segment_plan or {}).get("recommended_duration_seconds"),
            1,
        ),
        "grid_count": constrain_segment_grid_count(
            (segment_plan or {}).get("recommended_duration_seconds"),
            (segment_plan or {}).get("grid_count"),
        ),
    }
    continuity_summary = _continuity_state_summary(normalized_segment_plan.get("continuity_state") or {})
    previous_continuity_summary = str(normalized_segment_plan.get("previous_continuity_summary") or "").strip()
    selected_beats = _select_language_beats_for_segment(normalized_segment_plan, language_beats)
    none_text = "\u65e0"
    user_prompt = (
        f"{prompt}\n\n"
        f"{asset_guardrail}\n\n"
        f"{_story_grid_expander_example()}\n\n"
        f"\u5f53\u524d\u7247\u6bb5\u89c4\u5212\uff1a\n{json.dumps(normalized_segment_plan, ensure_ascii=False)}\n\n"
        f"\u8bed\u8a00\u8282\u62cd / \u8868\u6f14\u4e8b\u4ef6\uff1a\n{json.dumps({'language_beats': selected_beats}, ensure_ascii=False)}\n\n"
        f"\u4e0a\u4e00\u5206\u955c\u8fde\u7eed\u6027\u6458\u8981\uff1a\n{previous_continuity_summary or none_text}\n\n"
        f"\u5f53\u524d\u5206\u955c\u8fde\u7eed\u6027\u8981\u6c42\uff1a\n{continuity_summary or none_text}\n\n"
        f"\u5f53\u524d\u7247\u6bb5\u539f\u6587\uff1a\n{segment_text or (normalized_segment_plan.get('text_span') or {}).get('source_excerpt') or normalized_segment_plan.get('summary') or ''}"
    )
    payload = _call_json_model_with_repair(
        api_key=api_key,
        model=model or settings.DEEPSEEK_STORY_GRID_EXPANDER_MODEL,
        provider_timeout_seconds=provider_timeout_seconds,
        json_fix_timeout_seconds=json_fix_timeout_seconds,
        max_tokens=settings.DEEPSEEK_GRID_EXPANDER_MAX_TOKENS,
        system_prompt="\u4f60\u662f\u591a\u5bab\u683c\u955c\u5934\u7ec6\u5316\u5668\uff0c\u53ea\u8fd4\u56de\u5408\u6cd5 JSON\u3002",
        user_prompt=user_prompt,
        repair_storyboard_mode=normalized_mode,
        repair_schema_prompt=prompt,
        repair_example_prompt=_story_grid_expander_example(),
        provider_timeout_code="grid_timeout",
        provider_timeout_message="\u7247\u6bb5\u591a\u5bab\u683c\u7ec6\u5316\u8d85\u65f6\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5",
        provider_error_code="provider_error",
        provider_error_message="\u7247\u6bb5\u591a\u5bab\u683c\u7ec6\u5316\u5931\u8d25\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5",
        invalid_json_code="grid_invalid_json",
        invalid_json_message="\u7247\u6bb5\u591a\u5bab\u683c\u7ec6\u5316\u8fd4\u56de\u4e86\u975e\u6cd5 JSON",
        on_json_fix_start=on_json_fix_start,
        on_json_fix_end=on_json_fix_end,
        usage_callback=usage_callback,
        usage_phase="expander",
        strict_function_name="emit_grid_cells",
        strict_function_description="Emit the structured grid_cells for the current story segment only.",
        strict_parameters_schema=_strict_grid_cells_parameters_schema(),
    )
    grid_cells: List[Dict[str, Any]] = []
    for item in (payload.get("grid_cells") or []):
        if not isinstance(item, dict):
            continue
        speech_items = _normalize_speech_items(item.get("speech_items") or [])
        dialogue_excerpt = _speech_items_to_dialogue_excerpt(speech_items) or str(item.get("dialogue_excerpt") or "").strip()
        grid_cells.append(
            {
                **item,
                "dialogue_excerpt": dialogue_excerpt,
                "speech_items": speech_items,
                "performance_focus": (
                    str(item.get("performance_focus") or "").strip()
                    or infer_performance_focus(speech_items, storyboard_mode=normalized_mode)
                ),
                "mouth_sync_required": bool(item.get("mouth_sync_required") if item.get("mouth_sync_required") is not None else any(row.get("mouth_sync_required") for row in speech_items)),
            }
        )
    return {"grid_cells": grid_cells}


def _normalize_grid_cells_payload(items: Any, *, storyboard_mode: str) -> List[Dict[str, Any]]:
    grid_cells: List[Dict[str, Any]] = []
    for item in (items or []):
        if not isinstance(item, dict):
            continue
        speech_items = _normalize_speech_items(item.get("speech_items") or [])
        dialogue_excerpt = _speech_items_to_dialogue_excerpt(speech_items) or str(item.get("dialogue_excerpt") or "").strip()
        grid_cells.append(
            {
                **item,
                "dialogue_excerpt": dialogue_excerpt,
                "speech_items": speech_items,
                "performance_focus": (
                    str(item.get("performance_focus") or "").strip()
                    or infer_performance_focus(speech_items, storyboard_mode=storyboard_mode)
                ),
                "mouth_sync_required": bool(item.get("mouth_sync_required") if item.get("mouth_sync_required") is not None else any(row.get("mouth_sync_required") for row in speech_items)),
            }
        )
    return grid_cells


def call_story_grid_batch_expander(
    segment_plans: List[Dict[str, Any]],
    api_key: str,
    *,
    structured_assets: Optional[Dict[str, Any]] = None,
    storyboard_mode: Optional[str] = None,
    full_text: str = "",
    language_beats: Optional[List[Dict[str, Any]]] = None,
    model: Optional[str] = None,
    provider_timeout_seconds: Optional[float] = None,
    json_fix_timeout_seconds: Optional[float] = None,
    on_json_fix_start: Optional[Callable[[], None]] = None,
    on_json_fix_end: Optional[Callable[[], None]] = None,
    usage_callback: Optional[Callable[[str, str, Any], None]] = None,
) -> Dict[str, Any]:
    normalized_mode = normalize_storyboard_mode(storyboard_mode)
    prompt = _story_grid_batch_expander_prompt(normalized_mode)
    asset_guardrail = build_story_segment_asset_guardrail(structured_assets or {})
    normalized_segments: List[Dict[str, Any]] = []
    for index, segment_plan in enumerate(segment_plans or [], start=1):
        normalized_segment_plan = {
            **(segment_plan or {}),
            "sequence_num": int((segment_plan or {}).get("sequence_num") or index),
            "recommended_duration_seconds": clamp_segment_total_duration(
                (segment_plan or {}).get("recommended_duration_seconds"),
                1,
            ),
            "grid_count": constrain_segment_grid_count(
                (segment_plan or {}).get("recommended_duration_seconds"),
                (segment_plan or {}).get("grid_count"),
            ),
        }
        selected_beats = _select_language_beats_for_segment(normalized_segment_plan, language_beats)
        normalized_segments.append(
            {
                "segment_plan": normalized_segment_plan,
                "language_beats": selected_beats,
                "previous_continuity_summary": str(normalized_segment_plan.get("previous_continuity_summary") or "").strip(),
                "continuity_summary": _continuity_state_summary(normalized_segment_plan.get("continuity_state") or {}),
            }
        )
    payload = _call_json_model_with_repair(
        api_key=api_key,
        model=model or settings.DEEPSEEK_STORY_GRID_EXPANDER_MODEL,
        provider_timeout_seconds=provider_timeout_seconds,
        json_fix_timeout_seconds=json_fix_timeout_seconds,
        max_tokens=int(getattr(settings, "DEEPSEEK_BATCH_GRID_EXPANDER_MAX_TOKENS", 16000) or 16000),
        system_prompt="你是整版多宫格镜头细化器，只返回合法 JSON。",
        user_prompt=(
            f"{prompt}\n\n"
            f"{asset_guardrail}\n\n"
            f"{_story_grid_expander_example()}\n\n"
            f"完整剧情片段规划与语言节拍：\n{json.dumps({'segments': normalized_segments}, ensure_ascii=False)}\n\n"
            f"完整剧本上下文：\n{full_text or ''}"
        ),
        repair_storyboard_mode=normalized_mode,
        repair_schema_prompt=prompt,
        repair_example_prompt=_story_grid_expander_example(),
        provider_timeout_code="grid_batch_timeout",
        provider_timeout_message="整版多宫格细化超时，请稍后重试",
        provider_error_code="provider_error",
        provider_error_message="整版多宫格细化失败，请稍后重试",
        invalid_json_code="grid_batch_invalid_json",
        invalid_json_message="整版多宫格细化返回了非法 JSON",
        on_json_fix_start=on_json_fix_start,
        on_json_fix_end=on_json_fix_end,
        usage_callback=usage_callback,
        usage_phase="batch_expander",
        strict_function_name="emit_grid_segments",
        strict_function_description="Emit structured grid_cells for all story segments in the confirmed plan.",
        strict_parameters_schema=_strict_grid_segments_parameters_schema(),
    )
    grid_segments: List[Dict[str, Any]] = []
    for item in (payload.get("grid_segments") or []):
        if not isinstance(item, dict):
            continue
        try:
            sequence_num = int(item.get("sequence_num") or 0)
        except Exception:
            sequence_num = 0
        if sequence_num <= 0:
            continue
        grid_segments.append(
            {
                "sequence_num": sequence_num,
                "grid_cells": _normalize_grid_cells_payload(item.get("grid_cells") or [], storyboard_mode=normalized_mode),
            }
        )
    return {"grid_segments": grid_segments}

