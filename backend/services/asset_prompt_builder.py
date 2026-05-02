from __future__ import annotations

import re
from typing import Any, Dict, Optional

from services.workflow_preset_service import build_style_prompt


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _unique_lines(*values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _sanitize_character_description(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    patterns = [
        r"被[^，。；]*[，。；]?",
        r"处于[^，。；]*[，。；]?",
        r"身处[^，。；]*[，。；]?",
        r"双臂[^，。；]*[，。；]?",
        r"长发凌乱[^，。；]*[，。；]?",
        r"目光[^，。；]*[，。；]?",
        r"眼神[^，。；]*[，。；]?",
        r"悬挂[^，。；]*[，。；]?",
        r"悬吐[^，。；]*[，。；]?",
        r"反绑[^，。；]*[，。；]?",
        r"麻绳[^，。；]*[，。；]?",
        r"悬崖[^，。；]*[，。；]?",
        r"绝望[^，。；]*[，。；]?",
        r"哭泣[^，。；]*[，。；]?",
    ]
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned)
    cleaned = re.sub(r"[，。；]{2,}", "。", cleaned)
    return cleaned.strip("，。； ")


def _normalize_script_context(script: Any = None, episode: Any = None) -> str:
    return "\n".join(
        item
        for item in [
            _clean_text(getattr(episode, "source_text", None)),
            _clean_text(getattr(script, "source_text", None)),
            _clean_text(getattr(script, "description", None)),
            _clean_text(getattr(script, "name", None)),
        ]
        if item
    )


def _detect_era_context(script: Any = None, episode: Any = None, asset_description: str = "") -> str:
    text = "\n".join(
        item for item in [_normalize_script_context(script, episode), _clean_text(asset_description)] if item
    ).lower()
    if not text:
        return "时代背景：严格服从剧本原始时代与世界观，不混入无关时代元素。"
    if re.search(r"(仙侠|修仙|宗门|上仙|魔尊|灵力|飞升|秘境|法器|渡劫)", text):
        return "时代背景：仙侠玄幻语境，人物服装、材质、道具与场景细节必须服从东方仙侠世界观，不混入现代生活元素。"
    if re.search(r"(古风|王爷|皇帝|太监|宫女|嫡女|金銮殿|将军|侯府|王府|郡主|国公|圣旨|长安|江湖)", text):
        return "时代背景：古代东方语境，资产描述必须符合古风叙事下的服装结构、器物材质、空间风貌与身份等级，不混入现代元素。"
    if re.search(r"(民国|洋楼|旗袍|军阀|报馆|租界|少帅|小姐|先生|怀表|车站月台)", text):
        return "时代背景：民国近代语境，资产描述必须符合民国时期的服饰、建筑、器物与城市气质，不混入当代或古代元素。"
    if re.search(r"(校园|高中|大学|社团|教室|宿舍|校服|高考|学长|学妹|青春)", text):
        return "时代背景：校园青春语境，资产描述要符合当代校园生活、学生服饰与学习场景的真实质感。"
    if re.search(r"(赛博|机甲|星际|未来|人工智能|芯片|实验舱|太空|量子|机械义肢|全息)", text):
        return "时代背景：未来科幻语境，资产描述必须符合科幻叙事下的技术感、材质语言和空间设计逻辑，不混入传统古典元素。"
    if re.search(r"(都市|总裁|别墅|酒吧|写字楼|办公室|豪门|直播|热搜|跑车|公寓)", text):
        return "时代背景：现代都市语境，资产描述要符合当代城市生活、职业身份、服装审美与空间气质。"
    return "时代背景：严格服从剧本原始时代与世界观，不混入无关时代元素。"


def _build_character_prompt(resource: Any, *, script: Any = None, episode: Any = None, workflow_profile: Optional[Dict[str, Any]] = None) -> str:
    style_prompt = build_style_prompt((workflow_profile or {}).get("style"), fallback=_clean_text(getattr(script, "style_preset", None)))
    name = _clean_text(getattr(resource, "name", None))
    trigger_word = _clean_text(getattr(resource, "trigger_word", None))
    description = _sanitize_character_description(getattr(resource, "description", None))
    sections = _unique_lines(
        f"风格基线：{style_prompt}" if style_prompt else "",
        f"角色名称：{name}" if name else "",
        f"角色触发词：{trigger_word}" if trigger_word and trigger_word != name else "",
        f"角色设定：{description}" if description else "",
        _detect_era_context(script=script, episode=episode, asset_description=description),
        "仅允许出现这一个角色本人。",
        "人物必须为单人全身照，从头到脚完整入镜，四肢与服装轮廓完整可见。",
        "人物采用自然直立站姿，面部保持自然平静的中性表情，不做夸张动作。",
        "背景必须是纯色背景，优先纯白、浅灰或干净单色摄影棚背景。",
        "无文字、无水印、无字幕、无杂物、无其他人物、无道具干扰。",
        "画面要求：生成角色标准单人主参考照，正面为主，构图稳定，全身完整，服装、发型、材质与配色清晰可辨，适合作为后续三视图、角色卡和一致性控制参考。",
    )
    return "\n\n".join(sections)


def _build_scene_prompt(resource: Any, *, script: Any = None, episode: Any = None, workflow_profile: Optional[Dict[str, Any]] = None) -> str:
    style_prompt = build_style_prompt((workflow_profile or {}).get("style"), fallback=_clean_text(getattr(script, "style_preset", None)))
    name = _clean_text(getattr(resource, "name", None))
    description = _clean_text(getattr(resource, "description", None))
    sections = _unique_lines(
        f"风格基线：{style_prompt}" if style_prompt else "",
        f"场景设定：{name}，{description}" if name and description else name or description,
        _detect_era_context(script=script, episode=episode, asset_description=description),
        "画面要求：生成环境参考图，突出空间结构、地貌或建筑、光线、天气、材质和整体氛围。",
        "尽量无人物干扰；如必须出现人物，只能作为极小比例环境点缀，不能抢占主体。",
        "无文字、无水印、无额外 UI 元素。",
    )
    return "\n\n".join(sections)


def _build_prop_prompt(resource: Any, *, script: Any = None, episode: Any = None, workflow_profile: Optional[Dict[str, Any]] = None) -> str:
    style_prompt = build_style_prompt((workflow_profile or {}).get("style"), fallback=_clean_text(getattr(script, "style_preset", None)))
    name = _clean_text(getattr(resource, "name", None))
    description = _clean_text(getattr(resource, "description", None))
    sections = _unique_lines(
        f"风格基线：{style_prompt}" if style_prompt else "",
        f"道具设定：{name}，{description}" if name and description else name or description,
        _detect_era_context(script=script, episode=episode, asset_description=description),
        "画面要求：生成单物参考图，主体居中，突出外形结构、材质、颜色、纹理、磨损或纹样细节。",
        "背景必须是纯色背景，优先纯白、浅灰或干净单色背景。",
        "不出现人物手持，不出现人物互动，不出现额外杂物。",
        "无文字、无水印、无额外杂物。",
    )
    return "\n\n".join(sections)


def build_default_asset_reference_prompt(
    resource: Any,
    *,
    script: Any = None,
    episode: Any = None,
    workflow_profile: Optional[Dict[str, Any]] = None,
) -> str:
    resource_type = _clean_text(getattr(resource, "resource_type", None)).lower()
    if resource_type == "scene":
        return _build_scene_prompt(resource, script=script, episode=episode, workflow_profile=workflow_profile)
    if resource_type == "prop":
        return _build_prop_prompt(resource, script=script, episode=episode, workflow_profile=workflow_profile)
    return _build_character_prompt(resource, script=script, episode=episode, workflow_profile=workflow_profile)


def default_asset_reference_aspect_ratio(resource: Any) -> str:
    resource_type = _clean_text(getattr(resource, "resource_type", None)).lower()
    if resource_type == "scene":
        return "16:9"
    if resource_type == "prop":
        return "1:1"
    return "9:16"
