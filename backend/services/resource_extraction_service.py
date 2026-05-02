from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from openai import APITimeoutError, OpenAI
from sqlmodel import Session, select

from core.config import settings
from services.deepseek_hybrid_router import estimate_text_tokens, resolve_deepseek_agent_route
from services.deepseek_model_policy import normalize_deepseek_model, normalize_deepseek_request_kwargs
from database import engine
from models import ResourceTypeEnum, SharedResource

SYSTEM_PROMPT = """
你是影视项目的结构化资产提取助手。
请从用户提供的剧本文本中提取可复用的角色、场景和道具资产，并只返回 JSON 对象。
JSON 结构必须是：
{
  "characters": [{"name": "...", "description": "...", "trigger_word": "..."}],
  "scenes": [{"name": "...", "description": "..."}],
  "props": [{"name": "...", "description": "..."}]
}
要求：
1. 仅输出合法 JSON，不要输出任何解释。
2. 去重，避免泛化项。
3. scenes.description 要写成适合场景参考图生成的环境描述，突出空间结构、光线、天气、材质与氛围。
4. props.description 要写成适合单物参考图生成的描述，突出造型、材质、纹理、颜色与可识别细节。
5. characters.description 必须写成角色基础设定说明，使用叙事式自然语言段落，不要写关键词列表。
6. characters.description 要尽量覆盖：年龄、性别、种族或外貌归属、身高或体态比例、脸型与五官特征、发型发色、肤色、常规站姿气质、服装结构、材质、配色、固定饰物、整体身份感。
7. characters.description 只能写角色的稳定设定，不能写当前剧情里的临时状态。
8. 禁止写入：被绑、悬挂、受伤、流血、哭泣、绝望、愤怒、战斗、奔跑、跪地、手持道具、身处具体场景、与某物互动、命运结局。
9. 禁止把角色描述写成“漂亮少女 / 冷酷男主 / 古风女子 / 黑发红衣”这类空泛标签堆砌。
10. trigger_word 继续保持简短，适合插入提示词；description 则写成完整自然语言。
11. characters.description 应尽量适合后续生成“单角色、无文字、无杂物、自然表情、正常站立”的单人照与三视图。
12. 无法确定时宁缺毋滥。
"""

CHARACTER_ENRICH_PROMPT = """
你是影视角色设定整理助手。请根据剧本文本，为给定角色补全更完整的叙事式外观描述，并只返回 JSON 对象。
JSON 结构必须是：
{
  "characters": [
    {
      "name": "...",
      "description": "...",
      "trigger_word": "..."
    }
  ]
}
要求：
1. 只处理输入里给出的角色名称，不新增角色。
2. description 必须写成完整自然语言段落，不要写关键词列表。
3. description 要尽量接近专业角色设定说明，覆盖：年龄、性别、种族或外貌归属、身高或体态比例、脸型与五官特征、发型发色、肤色、常规站姿气质、服装结构、材质、配色、固定饰物、整体身份感。
4. 禁止写成“漂亮少女 / 冷酷男主 / 古风女子 / 黑发红衣”这类空泛标签堆砌。
5. 只能写角色的基础设定，不得写当前剧情里的临时状态，例如：被绑、悬挂、受伤、流血、哭泣、绝望、愤怒、战斗、奔跑、跪地、与道具互动、身处具体场景。
6. 如果剧本信息不足，也要尽量写成相对完整、可用于角色参考图生成的自然语言描述，但不要编造明显超出文本设定的身份背景。
7. trigger_word 保持简短，适合插入提示词；若已有 trigger_word 合理可沿用。
8. description 尽量控制在 90 到 180 个中文字符之间，至少形成 2 到 4 句连贯描述。
9. 参考这种写法风格：“20岁左右的东亚年轻女子，身形修长纤细，肩窄腰细，整体体态轻而挺拔。她有窄鹅蛋脸，眉形细长平直，眼睛狭长清冷，肤色偏冷白，黑色长直发自然垂落。服装以素净古装为主，层次清晰、材质真实，整体气质克制安静，适合作为角色标准参考图设定。”
10. 只返回合法 JSON，不要输出解释。
"""

SCENE_ENRICH_PROMPT = """
你是影视场景资产整理助手。请根据剧本文本，为给定场景补全更适合“场景参考图生成”的自然语言描述，并只返回 JSON 对象。
JSON 结构必须是：
{
  "scenes": [
    {
      "name": "...",
      "description": "..."
    }
  ]
}
要求：
1. 只处理输入里的场景，不新增场景。
2. description 要像环境参考图描述，突出空间结构、地貌/建筑、光线、天气、材质、氛围、景别感与可识别构图特征。
3. 不要写人物当前动作，不要写某一镜头瞬时状态。
4. 要保持可复用，适合后续生成无人物或弱人物干扰的场景参考图。
5. 只返回合法 JSON，不要输出解释。
"""

PROP_ENRICH_PROMPT = """
你是影视道具资产整理助手。请根据剧本文本，为给定道具补全更适合“单物参考图生成”的自然语言描述，并只返回 JSON 对象。
JSON 结构必须是：
{
  "props": [
    {
      "name": "...",
      "description": "..."
    }
  ]
}
要求：
1. 只处理输入里的道具，不新增道具。
2. description 要像单物参考图描述，突出外形结构、材质、颜色、纹理、磨损、纹样、识别性细节。
3. 不要写人物如何使用它，不要写当前镜头的一次性动作状态。
4. 要保持可复用，适合后续生成白底或干净背景的单道具参考图。
5. 只返回合法 JSON，不要输出解释。
"""


def _style_prefix(style_prompt: str, style_label: str) -> str:
    prompt = str(style_prompt or "").strip()
    label = str(style_label or "").strip()
    if prompt:
        return f"当前剧本风格详细提示词：{prompt}"
    if label:
        return f"当前剧本风格标签：{label}"
    return ""


def _extract_json_object(content: str) -> Dict[str, Any]:
    match = re.search(r"```json\s*(.*?)\s*```", content, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    start_idx = content.find("{")
    end_idx = content.rfind("}")
    if start_idx == -1 or end_idx == -1:
        raise ValueError("cannot find json object in model output")
    return json.loads(content[start_idx : end_idx + 1])


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").strip()).lower()


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _resource_type_value(resource_type: Any) -> str:
    return resource_type.value if hasattr(resource_type, "value") else str(resource_type)


def _is_weak_character_description(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return True
    if len(text) < 80:
        return True
    weak_markers = [
        "漂亮少女",
        "冷酷男主",
        "古风女子",
        "黑发红衣",
        "白衣男子",
        "长发女子",
        "英俊男子",
        "美丽女子",
    ]
    if any(marker in text for marker in weak_markers):
        return True
    if "，" not in text and "。" not in text:
        return True
    return False


def _is_weak_non_character_description(value: str) -> bool:
    text = _clean_text(value)
    if not text:
        return True
    if len(text) < 24:
        return True
    if "，" not in text and "。" not in text and "、" not in text and "；" not in text:
        return True
    return False


def _strip_dynamic_character_state(text: str) -> str:
    value = _clean_text(text)
    if not value:
        return ""
    patterns = [
        r"因[^，。；]*?[，。；]",
        r"被[^，。；]*?[，。；]",
        r"身处[^，。；]*?[，。；]",
        r"处于[^，。；]*?[，。；]",
        r"双臂[^，。；]*?[，。；]",
        r"长发凌乱[^，。；]*?[，。；]",
        r"目光[^，。；]*?[，。；]",
        r"眼神[^，。；]*?[，。；]",
        r"气质[^，。；]*绝望[^，。；]*?[，。；]",
        r"透露出[^，。；]*?[，。；]",
        r"作为[^，。；]*?[，。；]",
        r"被迫[^，。；]*?[，。；]",
        r"悬挂[^，。；]*?[，。；]",
        r"反绑[^，。；]*?[，。；]",
        r"麻绳[^，。；]*?[，。；]",
        r"悬崖[^，。；]*?[，。；]",
    ]
    cleaned = value
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"[，。；]{2,}", "。", cleaned)
    cleaned = cleaned.strip("，。； ")
    return cleaned


def _expand_character_description_fallback(name: str, seed: str) -> str:
    seed_text = _strip_dynamic_character_state(seed)
    if not seed_text:
        return (
            f"{name}是一位年轻的东亚角色，整体体态自然匀称，面部轮廓清晰，五官协调，发型与服装风格稳定统一。"
            f"她或他在静止状态下神情平静克制，适合作为角色参考图和后续分镜一致性设定。"
        )
    seed_text = seed_text.replace("、", "，").replace("/", "，").replace("|", "，")
    return (
        f"{name}给人的第一印象与“{seed_text}”高度相关，整体形象应当在年龄、体态、面部特征与服装层次上保持统一可辨识。"
        f"请将其理解为一个处于自然状态中的角色：外貌细节清晰，发型和服饰有连续性，气质与神态稳定，不依赖夸张标签也能成立。"
    )


def load_structured_assets_from_shared_resources(session: Session, script_id: int) -> Dict[str, List[Dict[str, str]]]:
    resources = session.exec(select(SharedResource).where(SharedResource.script_id == script_id)).all()
    payload = {"characters": [], "scenes": [], "props": []}

    for resource in resources:
        resource_type = _resource_type_value(resource.resource_type).strip().lower()
        item = {
            "name": _clean_text(resource.name),
            "description": _clean_text(resource.description),
        }
        if resource_type == ResourceTypeEnum.CHARACTER_REF.value:
            item["trigger_word"] = _clean_text(resource.trigger_word)
            payload["characters"].append(item)
        elif resource_type == ResourceTypeEnum.SCENE_REF.value:
            payload["scenes"].append(item)
        elif resource_type == ResourceTypeEnum.PROP_REF.value:
            payload["props"].append(item)

    return {
        "characters": _dedupe_items(payload["characters"], include_trigger_word=True),
        "scenes": _dedupe_items(payload["scenes"], include_trigger_word=False),
        "props": _dedupe_items(payload["props"], include_trigger_word=False),
    }


def _dedupe_items(items: List[Any], *, include_trigger_word: bool) -> List[Dict[str, str]]:
    result: List[Dict[str, str]] = []
    seen: Set[str] = set()

    for raw in items:
        if not isinstance(raw, dict):
            continue

        name = _clean_text(raw.get("name"))
        if not name:
            continue

        normalized_name = _normalize_name(name)
        if not normalized_name or normalized_name in seen:
            continue
        seen.add(normalized_name)

        payload = {
            "name": name,
            "description": _clean_text(raw.get("description")),
        }
        if include_trigger_word:
            payload["trigger_word"] = _clean_text(raw.get("trigger_word"))
        result.append(payload)

    return result


GENERIC_CHARACTER_NAMES = {
    "刽子手",
    "侍卫",
    "士兵",
    "路人",
    "众人",
    "百姓",
}

HEURISTIC_PROP_KEYWORDS = [
    "麻绳",
    "金钱镖",
    "圣旨",
    "战马",
    "长剑",
    "佩剑",
    "匕首",
    "令牌",
    "药瓶",
    "玉佩",
    "书信",
    "卷轴",
]


def _sanitize_character_name(name: str) -> str:
    text = _clean_text(name)
    while len(text) > 2 and text[:1] in {"着", "把", "将", "向", "让", "与", "和", "从", "在", "对", "被", "给"}:
        text = text[1:]
    return text


def _build_scene_description_fallback(name: str) -> str:
    return f"{name}是剧中可复用的主要环境空间，整体场域稳定清晰，具备明确的地貌或建筑特征，并包含可持续复用的空间结构、光线氛围和视觉锚点，适合作为后续场景参考图与分镜背景设定。"


def _build_prop_description_fallback(name: str) -> str:
    return f"{name}是剧中具有识别价值的关键物件，外形特征明确，材质与颜色稳定，可作为后续单物参考图、角色绑定和分镜视觉锚点使用。"


def _heuristic_extract_assets_from_script(source_text: str) -> Dict[str, List[Dict[str, str]]]:
    text = _clean_text(source_text)
    if not text:
        return {"characters": [], "scenes": [], "props": []}

    character_names: List[str] = []
    for pattern in [
        re.compile(r"([一-龥]{2,4})（\d{1,2}岁"),
        re.compile(r"[·・]([一-龥]{2,4})】"),
        re.compile(r"^([一-龥]{2,4})(?:（[^）]{0,12}）)?[：:]", re.MULTILINE),
    ]:
        for match in pattern.findall(text):
            name = _sanitize_character_name(match)
            if not name or name in GENERIC_CHARACTER_NAMES:
                continue
            if name not in character_names:
                character_names.append(name)

    scene_names: List[str] = []
    for line in text.splitlines():
        stripped = _clean_text(line)
        if not stripped:
            continue
        match = re.match(r"^\d+\s*[-—－]\s*\d+\s*[：:：]?\s*([^\n。·]+)", stripped)
        if not match:
            continue
        name = _clean_text(match.group(1))
        if not name:
            continue
        if name not in scene_names:
            scene_names.append(name)

    prop_names: List[str] = []
    for keyword in HEURISTIC_PROP_KEYWORDS:
        if keyword in text and keyword not in prop_names:
            prop_names.append(keyword)

    return {
        "characters": [
            {
                "name": name,
                "description": _expand_character_description_fallback(name, ""),
                "trigger_word": name,
            }
            for name in character_names
        ],
        "scenes": [
            {
                "name": name,
                "description": _build_scene_description_fallback(name),
            }
            for name in scene_names
        ],
        "props": [
            {
                "name": name,
                "description": _build_prop_description_fallback(name),
            }
            for name in prop_names
        ],
    }


def _apply_resource_updates(
    resource: SharedResource,
    *,
    description: str,
    trigger_word: Optional[str] = None,
) -> bool:
    changed = False

    if description and description != (resource.description or "").strip():
        resource.description = description
        changed = True

    if trigger_word is not None and trigger_word and trigger_word != (resource.trigger_word or "").strip():
        resource.trigger_word = trigger_word
        changed = True

    return changed


def extract_script_assets_structured(
    source_text: str,
    api_key: str,
    style_prompt: str = "",
    style_label: str = "",
) -> Dict[str, List[Dict[str, str]]]:
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=300.0)
    style_prefix = _style_prefix(style_prompt, style_label)
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{style_prefix}\n\n" if style_prefix else ""
                ) + (
                    "请提取下面剧本中的角色、场景和道具资产。"
                    "角色描述要适合后续生成单人主参考照和三视图；"
                    "场景描述要适合后续生成环境参考图；"
                    "道具描述要适合后续生成单物参考图。\n\n"
                    f"{source_text}"
                ),
            },
        ],
        extra_body={"thinking": {"type": "enabled"}},
    )
    content = response.choices[0].message.content or ""
    parsed_data = _extract_json_object(content)
    if not isinstance(parsed_data, dict):
        raise ValueError("model output is not a JSON object")

    characters = _dedupe_items(parsed_data.get("characters") or [], include_trigger_word=True)
    scenes = _dedupe_items(parsed_data.get("scenes") or [], include_trigger_word=False)
    props = _dedupe_items(parsed_data.get("props") or [], include_trigger_word=False)
    characters = _enrich_character_descriptions(
        source_text,
        characters,
        api_key,
        style_prompt=style_prompt,
        style_label=style_label,
    )
    scenes = _enrich_non_character_descriptions(
        source_text,
        scenes,
        api_key,
        kind="scene",
        style_prompt=style_prompt,
        style_label=style_label,
    )
    props = _enrich_non_character_descriptions(
        source_text,
        props,
        api_key,
        kind="prop",
        style_prompt=style_prompt,
        style_label=style_label,
    )

    return {
        "characters": characters,
        "scenes": scenes,
        "props": props,
    }


def _enrich_character_descriptions(
    source_text: str,
    characters: List[Dict[str, str]],
    api_key: str,
    *,
    style_prompt: str = "",
    style_label: str = "",
) -> List[Dict[str, str]]:
    weak_items = [item for item in characters if _is_weak_character_description(item.get("description") or "")]
    if not weak_items:
        return characters

    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=300.0)
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": CHARACTER_ENRICH_PROMPT},
            {
                "role": "user",
                "content": (
                    f"{_style_prefix(style_prompt, style_label)}\n\n" if _style_prefix(style_prompt, style_label) else ""
                ) + (
                    "请只补全下面这些角色的 description，并尽量保留已有 trigger_word。\n\n"
                    f"角色列表：\n{json.dumps(weak_items, ensure_ascii=False, indent=2)}\n\n"
                    f"剧本文本：\n{source_text}"
                ),
            },
        ],
        extra_body={"thinking": {"type": "enabled"}},
    )
    content = response.choices[0].message.content or ""
    parsed = _extract_json_object(content)
    enriched_items = _dedupe_items(parsed.get("characters") or [], include_trigger_word=True)
    enriched_map = {
        _normalize_name(item.get("name") or ""): item
        for item in enriched_items
        if _normalize_name(item.get("name") or "")
    }

    merged: List[Dict[str, str]] = []
    for item in characters:
        key = _normalize_name(item.get("name") or "")
        enriched = enriched_map.get(key)
        if enriched:
            enriched_description = _strip_dynamic_character_state(enriched.get("description") or item.get("description") or "")
            if _is_weak_character_description(enriched_description):
                enriched_description = _expand_character_description_fallback(
                    item.get("name") or enriched.get("name") or "",
                    enriched_description or item.get("description") or "",
                ) or enriched_description
            merged.append(
                {
                    "name": item.get("name") or enriched.get("name") or "",
                    "description": enriched_description,
                    "trigger_word": enriched.get("trigger_word") or item.get("trigger_word") or "",
                }
            )
        else:
            fallback_description = _strip_dynamic_character_state(item.get("description") or "")
            if _is_weak_character_description(fallback_description):
                fallback_description = _expand_character_description_fallback(
                    item.get("name") or "",
                    fallback_description,
                ) or fallback_description
            merged.append({ **item, "description": fallback_description })
    return merged


def _enrich_non_character_descriptions(
    source_text: str,
    items: List[Dict[str, str]],
    api_key: str,
    *,
    kind: str,
    style_prompt: str = "",
    style_label: str = "",
) -> List[Dict[str, str]]:
    weak_items = [item for item in items if _is_weak_non_character_description(item.get("description") or "")]
    if not weak_items:
        return items

    system_prompt = SCENE_ENRICH_PROMPT if kind == "scene" else PROP_ENRICH_PROMPT
    result_key = "scenes" if kind == "scene" else "props"
    kind_label = "场景" if kind == "scene" else "道具"
    style_prefix = _style_prefix(style_prompt, style_label)
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com", timeout=300.0)
    response = client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"{style_prefix}\n\n" if style_prefix else ""
                ) + (
                    f"请只补全下面这些{kind_label}的 description。\n\n"
                    f"{kind_label}列表：\n{json.dumps(weak_items, ensure_ascii=False, indent=2)}\n\n"
                    f"剧本文本：\n{source_text}"
                ),
            },
        ],
        extra_body={"thinking": {"type": "enabled"}},
    )
    content = response.choices[0].message.content or ""
    parsed = _extract_json_object(content)
    enriched_items = _dedupe_items(parsed.get(result_key) or [], include_trigger_word=False)
    enriched_map = {
        _normalize_name(item.get("name") or ""): item
        for item in enriched_items
        if _normalize_name(item.get("name") or "")
    }

    merged: List[Dict[str, str]] = []
    for item in items:
        key = _normalize_name(item.get("name") or "")
        enriched = enriched_map.get(key)
        if enriched and _clean_text(enriched.get("description")):
            merged.append({
                **item,
                "description": _clean_text(enriched.get("description")),
            })
        else:
            merged.append(item)
    return merged


ASSET_SYNC_CALLBACK = Optional[Callable[[str, Dict[str, Any]], None]]


def _serialize_synced_resource(resource: SharedResource) -> Dict[str, Any]:
    return {
        "id": resource.id,
        "script_id": resource.script_id,
        "resource_type": _resource_type_value(resource.resource_type),
        "name": _clean_text(resource.name),
        "file_url": _clean_text(resource.file_url),
        "thumbnail_url": _clean_text(getattr(resource, "thumbnail_url", None)),
        "trigger_word": _clean_text(getattr(resource, "trigger_word", None)),
        "description": _clean_text(getattr(resource, "description", None)),
        "updated_at": getattr(resource, "updated_at", None),
    }


def sync_structured_assets_into_shared_resources(
    script_id: int,
    structured_assets: Dict[str, List[Dict[str, str]]],
    *,
    sync_callback: ASSET_SYNC_CALLBACK = None,
) -> Dict[str, int]:
    characters = _dedupe_items(structured_assets.get("characters") or [], include_trigger_word=True)
    scenes = _dedupe_items(structured_assets.get("scenes") or [], include_trigger_word=False)
    props = _dedupe_items(structured_assets.get("props") or [], include_trigger_word=False)

    created_count = 0
    updated_count = 0

    with Session(engine) as session:
        existing_resources = session.exec(select(SharedResource).where(SharedResource.script_id == script_id)).all()
        existing_map = {
            (_resource_type_value(resource.resource_type), _normalize_name(resource.name)): resource
            for resource in existing_resources
            if resource.resource_type
            in {
                ResourceTypeEnum.CHARACTER_REF.value,
                ResourceTypeEnum.SCENE_REF.value,
                ResourceTypeEnum.PROP_REF.value,
                ResourceTypeEnum.CHARACTER_REF,
                ResourceTypeEnum.SCENE_REF,
                ResourceTypeEnum.PROP_REF,
            }
        }

        def _emit_sync_event(action: str, resource: SharedResource) -> None:
            if sync_callback is None:
                return
            sync_callback(action, _serialize_synced_resource(resource))

        for item in characters:
            key = (ResourceTypeEnum.CHARACTER_REF.value, _normalize_name(item["name"]))
            resource = existing_map.get(key)
            if resource:
                if _apply_resource_updates(resource, description=item["description"], trigger_word=item.get("trigger_word") or None):
                    session.add(resource)
                    session.commit()
                    session.refresh(resource)
                    updated_count += 1
                    _emit_sync_event("updated", resource)
                continue

            resource = SharedResource(
                script_id=script_id,
                resource_type=ResourceTypeEnum.CHARACTER_REF.value,
                name=item["name"],
                file_url="",
                trigger_word=item.get("trigger_word") or None,
                description=item["description"] or None,
            )
            session.add(resource)
            session.commit()
            session.refresh(resource)
            existing_map[key] = resource
            created_count += 1
            _emit_sync_event("created", resource)

        for item in scenes:
            key = (ResourceTypeEnum.SCENE_REF.value, _normalize_name(item["name"]))
            resource = existing_map.get(key)
            if resource:
                if _apply_resource_updates(resource, description=item["description"]):
                    session.add(resource)
                    session.commit()
                    session.refresh(resource)
                    updated_count += 1
                    _emit_sync_event("updated", resource)
                continue

            resource = SharedResource(
                script_id=script_id,
                resource_type=ResourceTypeEnum.SCENE_REF.value,
                name=item["name"],
                file_url="",
                description=item["description"] or None,
            )
            session.add(resource)
            session.commit()
            session.refresh(resource)
            existing_map[key] = resource
            created_count += 1
            _emit_sync_event("created", resource)

        for item in props:
            key = (ResourceTypeEnum.PROP_REF.value, _normalize_name(item["name"]))
            resource = existing_map.get(key)
            if resource:
                if _apply_resource_updates(resource, description=item["description"]):
                    session.add(resource)
                    session.commit()
                    session.refresh(resource)
                    updated_count += 1
                    _emit_sync_event("updated", resource)
                continue

            resource = SharedResource(
                script_id=script_id,
                resource_type=ResourceTypeEnum.PROP_REF.value,
                name=item["name"],
                file_url="",
                description=item["description"] or None,
            )
            session.add(resource)
            session.commit()
            session.refresh(resource)
            existing_map[key] = resource
            created_count += 1
            _emit_sync_event("created", resource)

    return {
        "character_count": len(characters),
        "scene_count": len(scenes),
        "prop_count": len(props),
        "created_count": created_count,
        "updated_count": updated_count,
    }


def extract_script_assets_into_shared_resources(
    script_id: int,
    source_text: str,
    api_key: str,
    *,
    style_prompt: str = "",
    style_label: str = "",
) -> Dict[str, int]:
    structured_assets = extract_script_assets_structured(
        source_text,
        api_key,
        style_prompt=style_prompt,
        style_label=style_label,
    )
    return sync_structured_assets_into_shared_resources(script_id, structured_assets)


logger = logging.getLogger(__name__)

ASSET_EXTRACTION_STAGE_CALLBACK = Optional[Callable[[str, int, str, Optional[Dict[str, Any]]], None]]
ASSET_USAGE_CALLBACK = Optional[Callable[[str, str, Dict[str, int]], None]]
ASSET_DYNAMIC_STATE_MARKERS = [
    "被绑", "捆绑", "悬吊", "悬挂", "受伤", "流血", "哭泣", "绝望", "愤怒", "怒视", "战斗", "奔跑", "逃跑",
    "跪地", "手持", "挥剑", "落泪", "麻绳", "悬崖", "濒死", "昏迷", "受困",
]
ASSET_LOW_INFO_CHARACTER_MARKERS = [
    "漂亮少女", "冷酷男主", "古风女子", "长发女子", "黑发红衣", "白衣男子", "英俊男子", "美丽女子",
]
ASSET_LOW_INFO_GENERIC_MARKERS = [
    "一个场景", "一把武器", "一个道具", "某个地方", "某个人", "主角", "配角",
]
ASSET_REUSABILITY_BLACKLIST = ["突然", "此时", "正在", "当下", "这一刻", "镜头里", "画面中"]


def _asset_progress_callback(callback: ASSET_EXTRACTION_STAGE_CALLBACK, stage: str, progress: int, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
    if callback is None:
        return
    callback(stage, progress, message, extra)


def _asset_usage_to_dict(response: Any) -> Dict[str, int]:
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
    hit_tokens = int(
        raw.get("prompt_cache_hit_tokens")
        or ((raw.get("prompt_tokens_details") or {}).get("cached_tokens"))
        or 0
    )
    miss_tokens = int(raw.get("prompt_cache_miss_tokens") or max(prompt_tokens - hit_tokens, 0))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": int(raw.get("completion_tokens") or 0),
        "prompt_cache_hit_tokens": hit_tokens,
        "prompt_cache_miss_tokens": miss_tokens,
    }


def _asset_usage_with_fallback(prompt_text: str, output_text: str, response: Any) -> Dict[str, int]:
    usage = _asset_usage_to_dict(response)
    if any(int(usage.get(key) or 0) for key in usage):
        return usage
    prompt_tokens = max(int(len(prompt_text.encode("utf-8")) / 3), 1)
    completion_tokens = max(int(len(str(output_text or "").encode("utf-8")) / 3), 0)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": prompt_tokens,
    }


def _log_asset_usage(phase: str, model: str, usage: Dict[str, int], *, duration_ms: Optional[int] = None, item_count: Optional[int] = None) -> None:
    logger.info(
        "asset_extraction phase=%s model=%s duration_ms=%s prompt_tokens=%s completion_tokens=%s prompt_cache_hit_tokens=%s prompt_cache_miss_tokens=%s item_count=%s",
        phase,
        model,
        duration_ms if duration_ms is not None else -1,
        int(usage.get("prompt_tokens") or 0),
        int(usage.get("completion_tokens") or 0),
        int(usage.get("prompt_cache_hit_tokens") or 0),
        int(usage.get("prompt_cache_miss_tokens") or 0),
        item_count if item_count is not None else -1,
    )


def _make_openai_client(*, api_key: str, beta: bool = False) -> OpenAI:
    return OpenAI(
        api_key=api_key,
        base_url="https://api.deepseek.com/beta" if beta else "https://api.deepseek.com",
        timeout=300.0,
    )


def _create_deepseek_completion(
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


def _asset_extract_parameters_schema() -> Dict[str, Any]:
    base_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["name", "description"],
    }
    character_item = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "name": {"type": "string"},
            "description": {"type": "string"},
            "trigger_word": {"type": "string"},
        },
        "required": ["name", "description", "trigger_word"],
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "characters": {"type": "array", "items": character_item},
            "scenes": {"type": "array", "items": base_item},
            "props": {"type": "array", "items": base_item},
        },
        "required": ["characters", "scenes", "props"],
    }


def _asset_enrich_parameters_schema(kind: str) -> Dict[str, Any]:
    include_trigger_word = kind == "character"
    item_properties: Dict[str, Any] = {
        "name": {"type": "string"},
        "description": {"type": "string"},
    }
    required = ["name", "description"]
    if include_trigger_word:
        item_properties["trigger_word"] = {"type": "string"}
        required.append("trigger_word")
    key = f"{kind}s" if kind != "character" else "characters"
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            key: {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": item_properties,
                    "required": required,
                },
            }
        },
        "required": [key],
    }


def _extract_tool_payload(response: Any, function_name: str) -> Dict[str, Any]:
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise ValueError("empty model response")
    message = getattr(choices[0], "message", None)
    tool_calls = getattr(message, "tool_calls", None) or []
    for tool_call in tool_calls:
        function = getattr(tool_call, "function", None)
        if not function:
            continue
        if str(getattr(function, "name", "")).strip() != function_name:
            continue
        arguments = getattr(function, "arguments", None)
        if not arguments:
            continue
        parsed = json.loads(arguments)
        if isinstance(parsed, dict):
            return parsed
    raise ValueError(f"strict tool payload missing: {function_name}")


def _call_asset_model(
    *,
    api_key: str,
    model: str,
    phase: str,
    system_prompt: str,
    user_prompt: str,
    function_name: str,
    function_description: str,
    parameters_schema: Dict[str, Any],
    max_tokens: int,
    metrics: List[Dict[str, Any]],
    thinking_enabled: bool = False,
    usage_callback: ASSET_USAGE_CALLBACK = None,
) -> Dict[str, Any]:
    started_at = time.perf_counter()
    prompt_text = f"{system_prompt}\n\n{user_prompt}"
    model, thinking_enabled = normalize_deepseek_model(model, thinking_enabled=thinking_enabled)
    if settings.DEEPSEEK_ASSET_USE_STRICT_SCHEMA:
        try:
            client = _make_openai_client(api_key=api_key, beta=True)
            response = _create_deepseek_completion(
                client,
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=max_tokens,
                json_output=False,
                thinking_enabled=thinking_enabled,
                tools=[{
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "description": function_description,
                        "strict": True,
                        "parameters": parameters_schema,
                    },
                }],
                tool_choice={"type": "function", "function": {"name": function_name}},
            )
            payload = _extract_tool_payload(response, function_name)
            usage = _asset_usage_with_fallback(prompt_text, json.dumps(payload, ensure_ascii=False), response)
            usage["thinking_enabled"] = int(bool(thinking_enabled))
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            _log_asset_usage(phase, model, usage, duration_ms=duration_ms)
            metrics.append({"phase": phase, "model": model, "duration_ms": duration_ms, **usage})
            if usage_callback is not None:
                usage_callback(phase, model, usage)
            return payload
        except APITimeoutError:
            raise
        except Exception as exc:
            logger.warning("asset_extraction strict schema failed, falling back to json mode: phase=%s model=%s error=%s", phase, model, exc)

    client = _make_openai_client(api_key=api_key, beta=False)
    response = _create_deepseek_completion(
        client,
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=max_tokens,
        json_output=True,
        thinking_enabled=thinking_enabled,
    )
    content = getattr((getattr(response, "choices", [None])[0]), "message", None)
    content_text = getattr(content, "content", "") or ""
    payload = _extract_json_object(content_text)
    usage = _asset_usage_with_fallback(prompt_text, content_text, response)
    usage["thinking_enabled"] = int(bool(thinking_enabled))
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    _log_asset_usage(phase, model, usage, duration_ms=duration_ms)
    metrics.append({"phase": phase, "model": model, "duration_ms": duration_ms, **usage})
    if usage_callback is not None:
        usage_callback(phase, model, usage)
    return payload


def _asset_extract_prompt() -> str:
    return """你是 AI 漫剧资产策划专家，也是高级角色资产总监和角色一致性控制负责人。请从剧本文本中提取可复用、可入库、可服务后续分镜与生成的人物、场景、道具资产，并输出标准化、结构化、视觉化、生成友好、生产可用的资产方案。

输出要求：
1. 只返回合法 JSON。
2. 顶层必须包含 `characters`、`scenes`、`props` 三个数组。
3. `characters` 中每项必须包含 `name`、`description`、`trigger_word`。
4. `scenes` 和 `props` 中每项必须包含 `name`、`description`。

提取原则：
1. 人物只提取稳定角色，不提取一次性群演，除非该人物对后续剧情有持续价值。
2. 场景只提取可复用空间，不提取一次性事件描述。
3. 道具只提取关键可识别物件，不提取抽象概念。
4. 去重，同一实体不要重复落入不同类型。
5. description 要适合后续参考图和资产库使用，写清稳定外观、环境或物件特征。
6. 不能把受伤、被绑、悬挂、哭泣、战斗等临时状态写成资产本体设定。

人物 description 要尽量覆盖年龄感、性别气质、体态、脸部特征、发型发色、肤色、常规穿着、固定饰物、身份感。
场景 description 要突出空间结构、光线、天气、材质、氛围和视觉锚点。
道具 description 要突出外形、材质、颜色、纹理、磨损和可识别细节。

如果某类没有可提取结果，就返回空数组。"""


def _character_enrich_prompt() -> str:
    return """你是资深角色设定专家，负责角色统一性和后续生成一致性。请只补全给定角色的稳定设定，不新增角色，不改变角色身份。

要求：
1. 只返回合法 JSON。
2. 顶层必须包含 `characters` 数组。
3. 每个角色都必须保留原始 `name`，并补全 `description` 和 `trigger_word`。
4. description 要适合角色参考图、角色卡和后续一致性生成。
5. 不要写当前剧情中的临时动作、情绪、受伤、被绑、悬挂等状态。"""


def _scene_enrich_prompt() -> str:
    return """你是资深场景资产分析专家，也是场景统筹顾问。请只补全给定场景的稳定环境描述，不新增场景，不改名。

要求：
1. 只返回合法 JSON。
2. 顶层必须包含 `scenes` 数组。
3. 每个场景都必须保留原始 `name`，并补全 `description`。
4. description 要突出空间结构、光线、天气、材质、氛围和视觉锚点。
5. 不要写人物动作，不要写临时剧情事件。"""


def _prop_enrich_prompt() -> str:
    return """你是资深道具资产分析专家，负责提炼物件的视觉锚点和生产可用设定。请只补全给定道具的稳定物件描述，不新增道具，不改名。

要求：
1. 只返回合法 JSON。
2. 顶层必须包含 `props` 数组。
3. 每个道具都必须保留原始 `name`，并补全 `description`。
4. description 要突出外形、材质、颜色、纹理、磨损和可识别细节。
5. 不要写人物如何使用它，不要写一次性剧情状态。"""


def _asset_repair_prompt(kind: str) -> str:
    kind_label = {"character": "角色", "scene": "场景", "prop": "道具"}[kind]
    return f"""你是影视{kind_label}资产修复助手。请只修复给定条目，不新增其它资产，也不要改动资产名称。

要求：
1. 只返回合法 JSON。
2. 只修复给定列表中的条目。
3. 只围绕报错项修复 description，以及角色的 trigger_word。
4. 保持资产身份边界稳定，不要把临时动作、情绪或剧情事件写进资产设定。"""


def _resolve_asset_extractor_model(source_text: str = "") -> str:
    route = resolve_deepseek_agent_route(
        {
            "task_kind": "structured_extract",
            "estimated_text_tokens": estimate_text_tokens(source_text),
            "segment_count": 0,
            "character_count": 0,
            "expected_tool_calls": 0,
            "user_intent_flags": [],
            "previous_failures": 0,
            "json_mode_enabled": True,
            "strict_tools_enabled": False,
        }
    )
    model, _ = normalize_deepseek_model(route["model"] or settings.DEEPSEEK_AGENT_DEFAULT_MODEL, thinking_enabled=bool(route.get("thinking_enabled")))
    return model


def _resolve_asset_enrich_model(kind: str, *, escalate_reasoner: bool = False) -> str:
    if kind == "character":
        base_model, _ = normalize_deepseek_model(settings.DEEPSEEK_AGENT_REASONER_MODEL or settings.DEEPSEEK_ASSET_CHARACTER_ENRICH_MODEL, thinking_enabled=True)
        if escalate_reasoner and settings.DEEPSEEK_ASSET_CHARACTER_REASONER_FALLBACK:
            return base_model
        return base_model
    if kind == "scene":
        base_model, _ = normalize_deepseek_model(settings.DEEPSEEK_AGENT_DEFAULT_MODEL or settings.DEEPSEEK_ASSET_SCENE_ENRICH_MODEL)
        if escalate_reasoner and settings.DEEPSEEK_ASSET_SCENE_PROP_REASONER_FALLBACK:
            fallback_model, _ = normalize_deepseek_model(settings.DEEPSEEK_AGENT_REASONER_MODEL, thinking_enabled=True)
            return fallback_model
        return base_model
    base_model, _ = normalize_deepseek_model(settings.DEEPSEEK_AGENT_DEFAULT_MODEL or settings.DEEPSEEK_ASSET_PROP_ENRICH_MODEL)
    if escalate_reasoner and settings.DEEPSEEK_ASSET_SCENE_PROP_REASONER_FALLBACK:
        fallback_model, _ = normalize_deepseek_model(settings.DEEPSEEK_AGENT_REASONER_MODEL, thinking_enabled=True)
        return fallback_model
    return base_model


def _build_asset_extraction_user_prompt(source_text: str, style_prompt: str, style_label: str) -> str:
    style_prefix = _style_prefix(style_prompt, style_label)
    return (
        (f"{style_prefix}\n\n" if style_prefix else "")
        + "请从下面剧本文本中提取可复用的人物、场景、道具资产。\n\n"
        + source_text
    )


def _build_asset_enrich_user_prompt(kind: str, source_text: str, items: List[Dict[str, str]], style_prompt: str, style_label: str) -> str:
    key = "characters" if kind == "character" else f"{kind}s"
    style_prefix = _style_prefix(style_prompt, style_label)
    return (
        (f"{style_prefix}\n\n" if style_prefix else "")
        + f"请只补全下面这些 {key} 的 description"
        + (" 和 trigger_word" if kind == "character" else "")
        + "，不要新增资产。\n\n"
        + f"{json.dumps({key: items}, ensure_ascii=False, indent=2)}\n\n"
        + f"剧本文本：\n{source_text}"
    )


def _build_asset_repair_user_prompt(kind: str, source_text: str, items: List[Dict[str, str]], validation_errors: List[str], style_prompt: str, style_label: str) -> str:
    key = "characters" if kind == "character" else f"{kind}s"
    style_prefix = _style_prefix(style_prompt, style_label)
    return (
        (f"{style_prefix}\n\n" if style_prefix else "")
        + "请只修复以下资产，不要新增资产，也不要改变 name。\n"
        + "错误列表：\n"
        + "\n".join(f"- {item}" for item in validation_errors[:12])
        + "\n\n待修复项目：\n"
        + f"{json.dumps({key: items}, ensure_ascii=False, indent=2)}\n\n"
        + f"剧本文本：\n{source_text}"
    )


def _validate_character_item(item: Dict[str, str]) -> List[str]:
    errors: List[str] = []
    description = _clean_text(item.get("description"))
    if len(description) < 80:
        errors.append(f"character `{item.get('name')}` description too short")
    if any(marker in description for marker in ASSET_DYNAMIC_STATE_MARKERS):
        errors.append(f"character `{item.get('name')}` contains dynamic state")
    if any(marker in description for marker in ASSET_LOW_INFO_CHARACTER_MARKERS):
        errors.append(f"character `{item.get('name')}` contains low-information label")
    return errors


def _validate_scene_item(item: Dict[str, str]) -> List[str]:
    errors: List[str] = []
    description = _clean_text(item.get("description"))
    if len(description) < 24:
        errors.append(f"scene `{item.get('name')}` description too short")
    if any(marker in description for marker in ASSET_REUSABILITY_BLACKLIST):
        errors.append(f"scene `{item.get('name')}` contains non-reusable event wording")
    if any(marker in description for marker in ASSET_LOW_INFO_GENERIC_MARKERS):
        errors.append(f"scene `{item.get('name')}` contains low-information wording")
    return errors


def _validate_prop_item(item: Dict[str, str]) -> List[str]:
    errors: List[str] = []
    description = _clean_text(item.get("description"))
    if len(description) < 24:
        errors.append(f"prop `{item.get('name')}` description too short")
    if any(marker in description for marker in ASSET_REUSABILITY_BLACKLIST):
        errors.append(f"prop `{item.get('name')}` contains action/event wording")
    if any(marker in description for marker in ASSET_LOW_INFO_GENERIC_MARKERS):
        errors.append(f"prop `{item.get('name')}` contains low-information wording")
    return errors


def _validate_extracted_assets(assets: Dict[str, List[Dict[str, str]]]) -> Dict[str, List[str]]:
    errors: Dict[str, List[str]] = {"characters": [], "scenes": [], "props": [], "global": []}
    seen_names: Dict[str, str] = {}
    seen_trigger_words: Dict[str, str] = {}

    for kind_key, validator in (
        ("characters", _validate_character_item),
        ("scenes", _validate_scene_item),
        ("props", _validate_prop_item),
    ):
        for item in assets.get(kind_key) or []:
            normalized_name = _normalize_name(item.get("name") or "")
            if not normalized_name:
                errors[kind_key].append(f"{kind_key[:-1]} missing name")
                continue
            owner = seen_names.get(normalized_name)
            if owner and owner != kind_key:
                errors["global"].append(f"name conflict across categories: `{item.get('name')}` in {owner} and {kind_key}")
            else:
                seen_names[normalized_name] = kind_key
            if kind_key == "characters":
                trigger_word = _clean_text(item.get("trigger_word"))
                normalized_trigger = _normalize_name(trigger_word)
                if normalized_trigger:
                    owner = seen_trigger_words.get(normalized_trigger)
                    if owner and owner != normalized_name:
                        errors["global"].append(f"trigger_word conflict: `{trigger_word}`")
                    else:
                        seen_trigger_words[normalized_trigger] = normalized_name
            errors[kind_key].extend(validator(item))
    return {key: value for key, value in errors.items() if value}


def _apply_local_asset_description_fallbacks(
    assets: Dict[str, List[Dict[str, str]]]
) -> Dict[str, List[Dict[str, str]]]:
    """Keep extraction usable when source text only names an asset."""
    quality_warnings: List[Dict[str, str]] = list(assets.get("_asset_quality_warnings") or [])

    def _append_quality_warning(kind: str, name: str, issue: str, suggestion: str) -> None:
        quality_warnings.append(
            {
                "kind": kind,
                "name": name,
                "issue": issue,
                "suggestion": suggestion,
            }
        )

    characters: List[Dict[str, str]] = []
    for item in assets.get("characters") or []:
        next_item = dict(item)
        name = _clean_text(next_item.get("name"))
        if name and _validate_character_item(next_item):
            seed = _strip_dynamic_character_state(next_item.get("description") or "")
            next_item["description"] = _expand_character_description_fallback(name, seed)
            next_item["trigger_word"] = _clean_text(next_item.get("trigger_word")) or name
            _append_quality_warning(
                "character",
                name,
                "原文信息较少，已生成临时人物设定。",
                "建议到资产页面补充外貌、年龄感、服装、表情和可识别细节。",
            )
        characters.append(next_item)

    scenes: List[Dict[str, str]] = []
    for item in assets.get("scenes") or []:
        next_item = dict(item)
        name = _clean_text(next_item.get("name"))
        if name and _validate_scene_item(next_item):
            next_item["description"] = _build_scene_description_fallback(name)
            _append_quality_warning(
                "scene",
                name,
                "原文信息较少，已生成临时场景设定。",
                "建议到资产页面补充空间结构、光线、材质、氛围和视觉锚点。",
            )
        scenes.append(next_item)

    props: List[Dict[str, str]] = []
    for item in assets.get("props") or []:
        next_item = dict(item)
        name = _clean_text(next_item.get("name"))
        if name and _validate_prop_item(next_item):
            next_item["description"] = _build_prop_description_fallback(name)
            _append_quality_warning(
                "prop",
                name,
                "原文信息较少，已生成临时道具设定。",
                "建议到资产页面补充外形、材质、颜色、磨损和可识别细节。",
            )
        props.append(next_item)

    return {
        "characters": characters,
        "scenes": scenes,
        "props": props,
        "_asset_quality_warnings": quality_warnings,
    }


def _repair_asset_items(
    *,
    kind: str,
    source_text: str,
    items: List[Dict[str, str]],
    validation_errors: List[str],
    api_key: str,
    style_prompt: str,
    style_label: str,
    metrics: List[Dict[str, Any]],
    usage_callback: ASSET_USAGE_CALLBACK = None,
) -> List[Dict[str, str]]:
    if not items:
        return items
    model, _ = normalize_deepseek_model(settings.DEEPSEEK_ASSET_CRITIC_MODEL, thinking_enabled=True)
    payload = _call_asset_model(
        api_key=api_key,
        model=model,
        phase=f"repair_{kind}",
        system_prompt=_asset_repair_prompt(kind),
        user_prompt=_build_asset_repair_user_prompt(kind, source_text, items, validation_errors, style_prompt, style_label),
        function_name=f"emit_{kind}_repair",
        function_description=f"Emit repaired {kind} assets only.",
        parameters_schema=_asset_enrich_parameters_schema(kind),
        max_tokens=int(settings.DEEPSEEK_ASSET_REPAIR_MAX_TOKENS),
        metrics=metrics,
        thinking_enabled=True,
        usage_callback=usage_callback,
    )
    key = "characters" if kind == "character" else f"{kind}s"
    return _dedupe_items(payload.get(key) or [], include_trigger_word=(kind == "character"))


def _merge_asset_items(existing: List[Dict[str, str]], updates: List[Dict[str, str]], *, include_trigger_word: bool) -> List[Dict[str, str]]:
    update_map = {_normalize_name(item.get("name") or ""): item for item in updates if _normalize_name(item.get("name") or "")}
    merged: List[Dict[str, str]] = []
    for item in existing:
        normalized_name = _normalize_name(item.get("name") or "")
        replacement = update_map.get(normalized_name)
        if replacement:
            next_item = {
                "name": item.get("name") or replacement.get("name") or "",
                "description": _clean_text(replacement.get("description") or item.get("description")),
            }
            if include_trigger_word:
                next_item["trigger_word"] = _clean_text(replacement.get("trigger_word") or item.get("trigger_word"))
            merged.append(next_item)
        else:
            merged.append(item)
    return _dedupe_items(merged, include_trigger_word=include_trigger_word)


def extract_script_assets_structured(
    source_text: str,
    api_key: str,
    style_prompt: str = "",
    style_label: str = "",
    *,
    stage_callback: ASSET_EXTRACTION_STAGE_CALLBACK = None,
    usage_callback: ASSET_USAGE_CALLBACK = None,
    sync_callback: Optional[Callable[[str, Dict[str, List[Dict[str, str]]]], None]] = None,
) -> Dict[str, List[Dict[str, str]]]:
    def _emit_sync(stage: str, characters_payload: List[Dict[str, str]], scenes_payload: List[Dict[str, str]], props_payload: List[Dict[str, str]]) -> None:
        if sync_callback is None:
            return
        sync_callback(
            stage,
            {
                "characters": list(characters_payload or []),
                "scenes": list(scenes_payload or []),
                "props": list(props_payload or []),
            },
        )

    metrics: List[Dict[str, Any]] = []
    _asset_progress_callback(stage_callback, "extracting", 10, "AI 正在抽取角色、场景、道具资产...")
    extract_payload = _call_asset_model(
        api_key=api_key,
        model=_resolve_asset_extractor_model(source_text),
        phase="extract",
        system_prompt=_asset_extract_prompt(),
        user_prompt=_build_asset_extraction_user_prompt(source_text, style_prompt, style_label),
        function_name="emit_extracted_assets",
        function_description="Emit the structured reusable characters, scenes and props extracted from the script.",
        parameters_schema=_asset_extract_parameters_schema(),
        max_tokens=int(settings.DEEPSEEK_ASSET_EXTRACT_MAX_TOKENS),
        metrics=metrics,
        thinking_enabled=False,
        usage_callback=usage_callback,
    )

    characters = _dedupe_items(extract_payload.get("characters") or [], include_trigger_word=True)
    scenes = _dedupe_items(extract_payload.get("scenes") or [], include_trigger_word=False)
    props = _dedupe_items(extract_payload.get("props") or [], include_trigger_word=False)
    if not characters and not scenes and not props:
        heuristic_assets = _heuristic_extract_assets_from_script(source_text)
        characters = _dedupe_items(heuristic_assets.get("characters") or [], include_trigger_word=True)
        scenes = _dedupe_items(heuristic_assets.get("scenes") or [], include_trigger_word=False)
        props = _dedupe_items(heuristic_assets.get("props") or [], include_trigger_word=False)
    _emit_sync("extracting", characters, scenes, props)

    weak_characters = [item for item in characters if _is_weak_character_description(item.get("description") or "")]
    if weak_characters:
        _asset_progress_callback(stage_callback, "enriching_characters", 35, f"正在补全 {len(weak_characters)} 个角色描述...")
        enriched_characters = _call_asset_model(
            api_key=api_key,
            model=_resolve_asset_enrich_model("character"),
            phase="enrich_characters",
            system_prompt=_character_enrich_prompt(),
            user_prompt=_build_asset_enrich_user_prompt("character", source_text, weak_characters, style_prompt, style_label),
            function_name="emit_character_descriptions",
            function_description="Emit enriched character descriptions for the provided characters only.",
            parameters_schema=_asset_enrich_parameters_schema("character"),
            max_tokens=int(settings.DEEPSEEK_ASSET_ENRICH_MAX_TOKENS),
            metrics=metrics,
            thinking_enabled=True,
            usage_callback=usage_callback,
        )
        characters = _merge_asset_items(
            characters,
            _dedupe_items(enriched_characters.get("characters") or [], include_trigger_word=True),
            include_trigger_word=True,
        )
        _emit_sync("enriching_characters", characters, scenes, props)

    weak_scenes = [item for item in scenes if _is_weak_non_character_description(item.get("description") or "")]
    if weak_scenes:
        _asset_progress_callback(stage_callback, "enriching_scenes", 50, f"正在补全 {len(weak_scenes)} 个场景描述...")
        enriched_scenes = _call_asset_model(
            api_key=api_key,
            model=_resolve_asset_enrich_model("scene"),
            phase="enrich_scenes",
            system_prompt=_scene_enrich_prompt(),
            user_prompt=_build_asset_enrich_user_prompt("scene", source_text, weak_scenes, style_prompt, style_label),
            function_name="emit_scene_descriptions",
            function_description="Emit enriched scene descriptions for the provided scenes only.",
            parameters_schema=_asset_enrich_parameters_schema("scene"),
            max_tokens=int(settings.DEEPSEEK_ASSET_ENRICH_MAX_TOKENS),
            metrics=metrics,
            thinking_enabled=False,
            usage_callback=usage_callback,
        )
        scenes = _merge_asset_items(
            scenes,
            _dedupe_items(enriched_scenes.get("scenes") or [], include_trigger_word=False),
            include_trigger_word=False,
        )
        _emit_sync("enriching_scenes", characters, scenes, props)

    weak_props = [item for item in props if _is_weak_non_character_description(item.get("description") or "")]
    if weak_props:
        _asset_progress_callback(stage_callback, "enriching_props", 65, f"正在补全 {len(weak_props)} 个道具描述...")
        enriched_props = _call_asset_model(
            api_key=api_key,
            model=_resolve_asset_enrich_model("prop"),
            phase="enrich_props",
            system_prompt=_prop_enrich_prompt(),
            user_prompt=_build_asset_enrich_user_prompt("prop", source_text, weak_props, style_prompt, style_label),
            function_name="emit_prop_descriptions",
            function_description="Emit enriched prop descriptions for the provided props only.",
            parameters_schema=_asset_enrich_parameters_schema("prop"),
            max_tokens=int(settings.DEEPSEEK_ASSET_ENRICH_MAX_TOKENS),
            metrics=metrics,
            thinking_enabled=False,
            usage_callback=usage_callback,
        )
        props = _merge_asset_items(
            props,
            _dedupe_items(enriched_props.get("props") or [], include_trigger_word=False),
            include_trigger_word=False,
        )
        _emit_sync("enriching_props", characters, scenes, props)

    assets = {"characters": characters, "scenes": scenes, "props": props}
    validation_errors = _validate_extracted_assets(assets)
    if validation_errors:
        _asset_progress_callback(stage_callback, "repairing", 80, "正在修复质量校验失败的资产...")
        if validation_errors.get("characters"):
            repaired = _repair_asset_items(
                kind="character",
                source_text=source_text,
                items=characters,
                validation_errors=validation_errors["characters"],
                api_key=api_key,
                style_prompt=style_prompt,
                style_label=style_label,
                metrics=metrics,
                usage_callback=usage_callback,
            )
            characters = _merge_asset_items(characters, repaired, include_trigger_word=True)
            _emit_sync("repairing_characters", characters, scenes, props)
        if validation_errors.get("scenes"):
            repaired = _repair_asset_items(
                kind="scene",
                source_text=source_text,
                items=scenes,
                validation_errors=validation_errors["scenes"],
                api_key=api_key,
                style_prompt=style_prompt,
                style_label=style_label,
                metrics=metrics,
                usage_callback=usage_callback,
            )
            scenes = _merge_asset_items(scenes, repaired, include_trigger_word=False)
            _emit_sync("repairing_scenes", characters, scenes, props)
        if validation_errors.get("props"):
            repaired = _repair_asset_items(
                kind="prop",
                source_text=source_text,
                items=props,
                validation_errors=validation_errors["props"],
                api_key=api_key,
                style_prompt=style_prompt,
                style_label=style_label,
                metrics=metrics,
                usage_callback=usage_callback,
            )
            props = _merge_asset_items(props, repaired, include_trigger_word=False)
            _emit_sync("repairing_props", characters, scenes, props)
        assets = {"characters": characters, "scenes": scenes, "props": props}
        assets = _apply_local_asset_description_fallbacks(assets)
        characters = assets["characters"]
        scenes = assets["scenes"]
        props = assets["props"]
        _emit_sync("repairing_local_fallbacks", characters, scenes, props)
        validation_errors = _validate_extracted_assets(assets)
        if validation_errors:
            raise ValueError("asset extraction semantic validation failed: " + "; ".join(
                list(validation_errors.get("global") or [])
                + list(validation_errors.get("characters") or [])[:3]
                + list(validation_errors.get("scenes") or [])[:3]
                + list(validation_errors.get("props") or [])[:3]
            ))

    assets["_metrics"] = metrics
    assets["_validation_errors"] = []
    _emit_sync("finalizing", characters, scenes, props)
    return assets


def extract_script_assets_into_shared_resources(
    script_id: int,
    source_text: str,
    api_key: str,
    *,
    style_prompt: str = "",
    style_label: str = "",
    stage_callback: ASSET_EXTRACTION_STAGE_CALLBACK = None,
    usage_callback: ASSET_USAGE_CALLBACK = None,
    sync_callback: Optional[Callable[[str, Dict[str, List[Dict[str, str]]]], None]] = None,
) -> Dict[str, int]:
    aggregate_counts = {"created_count": 0, "updated_count": 0}

    def _sync_partial_assets(_: str, partial_assets: Dict[str, List[Dict[str, str]]]) -> None:
        partial_result = sync_structured_assets_into_shared_resources(script_id, partial_assets)
        aggregate_counts["created_count"] += int(partial_result.get("created_count") or 0)
        aggregate_counts["updated_count"] += int(partial_result.get("updated_count") or 0)
        if sync_callback is not None:
            sync_callback(_, partial_assets)

    structured_assets = extract_script_assets_structured(
        source_text,
        api_key,
        style_prompt=style_prompt,
        style_label=style_label,
        stage_callback=stage_callback,
        usage_callback=usage_callback,
        sync_callback=_sync_partial_assets,
    )
    _asset_progress_callback(stage_callback, "syncing_resources", 92, "正在同步资产到共享资源库...")
    result = {
        "character_count": len(structured_assets.get("characters") or []),
        "scene_count": len(structured_assets.get("scenes") or []),
        "prop_count": len(structured_assets.get("props") or []),
        "created_count": int(aggregate_counts["created_count"]),
        "updated_count": int(aggregate_counts["updated_count"]),
    }
    result["metrics"] = structured_assets.get("_metrics") or []
    result["validation_errors"] = structured_assets.get("_validation_errors") or []
    result["asset_quality_warnings"] = structured_assets.get("_asset_quality_warnings") or []
    return result
