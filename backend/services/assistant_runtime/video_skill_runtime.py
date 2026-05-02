from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlmodel import select

from models import AssistantPendingQuestion, AssistantSession, Panel, User
from services.video_model_registry import GENERATION_TYPE_LABELS

from .service import _json_dumps, _utc_now
from .panel_selection import build_selected_panels_payload, format_selected_panel_display, resolve_panel_selection
from .video_model_selector import (
    build_model_unavailable_message,
    build_video_model_options,
    choose_video_model,
    infer_audio_enabled,
    infer_video_generation_type,
    resolve_explicit_video_model_request,
)
from .video_skill_planner import build_video_execution_plan_payload, build_video_generation_field_options
from .video_task_executor import (
    attachment_media_urls,
    coerce_bool,
    derive_panel_video_prompt,
    panel_has_video,
    panel_latest_image,
    panel_video_duration,
    submit_panel_video_generation_tasks,
)


def create_panel_video_wizard_v2(
    service,
    *,
    session_obj: AssistantSession,
    title: str,
    description: str,
    panels: List[Panel],
    candidates: List[Panel],
    selected_panels: List[Panel],
    prompt_required: bool,
    generation_type: str,
    audio_enabled: bool,
    default_model_choice: Optional[Dict[str, Any]],
    attachment_image_urls: Optional[List[str]] = None,
    attachment_video_urls: Optional[List[str]] = None,
) -> Dict[str, Any]:
    selectable_panels = candidates or panels
    default_panel = (selected_panels[0] if selected_panels else None) or (selectable_panels[0] if selectable_panels else None)
    selected_display = format_selected_panel_display(selected_panels)
    attachment_image_urls = [str(item).strip() for item in (attachment_image_urls or []) if str(item).strip()]
    attachment_video_urls = [str(item).strip() for item in (attachment_video_urls or []) if str(item).strip()]
    default_model = (default_model_choice or {}).get("model") or {}
    default_model_code = str(default_model.get("model_code") or "").strip() or "veo_31_fast"
    field_options = build_video_generation_field_options(default_model_code, generation_type)
    duration_default = str(field_options["defaults"].get("duration") or (panel_video_duration(default_panel) if default_panel else 6))
    resolution_default = str(field_options["defaults"].get("resolution") or "720p").strip().lower() or "720p"
    latest_image = panel_latest_image(default_panel) if default_panel else ""

    inferred_generation_types = ["text_to_video"]
    if latest_image or attachment_image_urls:
        inferred_generation_types.append("image_to_video")
    if len(attachment_image_urls) >= 2:
        inferred_generation_types.extend(["reference_to_video", "start_end_to_video"])
    if attachment_video_urls and (attachment_image_urls or latest_image):
        inferred_generation_types.append("reference_to_video")
    generation_type_options = [
        {"value": item, "label": GENERATION_TYPE_LABELS.get(item, item)}
        for item in dict.fromkeys([generation_type] + inferred_generation_types)
    ]
    model_options = build_video_model_options(
        generation_type=generation_type,
        audio_enabled=audio_enabled,
    )
    model_option_map = {
        str(option.get("value") or ""): option
        for option in model_options
        if str(option.get("value") or "").strip()
    }
    model_options_by_generation_type = {}
    for option in generation_type_options:
        option_value = str(option.get("value") or "").strip()
        if not option_value:
            continue
        scoped_options = build_video_model_options(
            generation_type=option_value,
            audio_enabled=audio_enabled,
        )
        model_options_by_generation_type[option_value] = scoped_options
    candidate_model_codes = [str(item.get("value") or item.get("model_code") or "").strip() for item in model_options if str(item.get("value") or item.get("model_code") or "").strip()]
    video_field_matrix = {}
    for model_code in candidate_model_codes:
        video_field_matrix[model_code] = {}
        for option in generation_type_options:
            option_value = str(option.get("value") or "").strip()
            if not option_value:
                continue
            video_field_matrix[model_code][option_value] = build_video_generation_field_options(model_code, option_value)

    steps: List[Dict[str, Any]] = []
    if not selected_panels:
        steps.append(
            {
                "id": "panel_scope",
                "label": "分镜范围",
                "description": "支持 2-4、2,3,5、前3镜、最后2镜、偶数镜、当前无视频的分镜。",
                "type": "text",
                "required": True,
                "default": "",
                "placeholder": "例如：2-4",
            }
        )

    steps.extend(
        [
            {
                "id": "generation_type",
                "label": "生成方式",
                "description": "会根据参考图、参考视频和当前分镜素材自动推荐，也可以手动切换。",
                "type": "select",
                "required": True,
                "default": generation_type,
                "options": generation_type_options,
            },
            {
                "id": "prompt_override",
                "label": "补充视频提示词",
                "description": "可补充动作、镜头运动、表演节奏；留空则继续使用分镜现有视频提示词。",
                "type": "textarea",
                "required": bool(prompt_required),
                "placeholder": "例如：人物缓慢转身，镜头轻推近，衣摆和发丝随风摆动",
                "default": "",
            },
            {
                "id": "model_code",
                "label": "视频模型",
                "description": "模型列表来自神鹿当前真实接入的视频模型注册表。",
                "type": "select",
                "required": True,
                "default": default_model_code,
                "options": model_options,
            },
            {
                "id": "audio_enabled",
                "label": "保留音频",
                "description": "仅支持音频的模型会在模型选项中显示对应标签。",
                "type": "boolean",
                "required": False,
                "default": bool(audio_enabled),
            },
            {
                "id": "duration",
                "label": "视频时长",
                "description": "时长选项按当前模型能力与价格规则生成。",
                "type": "select",
                "required": True,
                "default": duration_default,
                "options": field_options["duration_options"],
            },
            {
                "id": "resolution",
                "label": "分辨率",
                "description": "分辨率选项按当前模型能力与价格规则生成。",
                "type": "select",
                "required": True,
                "default": resolution_default,
                "options": field_options["resolution_options"],
            },
        ]
    )

    question = AssistantPendingQuestion(
        session_id=session_obj.id,
        question_type="wizard",
        status="pending",
        title=title,
        prompt_text=description,
        payload_json=_json_dumps(
            {
                "preview": {
                    "total_panels": len(panels),
                    "panels_without_videos": len(candidates),
                    "selected_panel_count": len(selected_panels),
                    "selected_panel_display": selected_display or None,
                    "selected_panels": build_selected_panels_payload(selected_panels),
                    "generation_type": generation_type,
                    "generation_type_label": GENERATION_TYPE_LABELS.get(generation_type, generation_type),
                },
                "wizard": {
                    "title": title,
                    "description": description,
                    "submit_label": "提交视频任务",
                    "cancel_label": "取消",
                    "steps": steps,
                },
                "metadata": {
                    "source": "assistant_generate_panel_video",
                    "selected_panel_sequences": [int(item.sequence_num or 0) for item in selected_panels if int(item.sequence_num or 0) > 0],
                    "selected_panel_display": selected_display,
                    "generation_type": generation_type,
                    "audio_enabled": bool(audio_enabled),
                    "attachment_image_urls": attachment_image_urls,
                    "attachment_video_urls": attachment_video_urls,
                    "default_model_code": default_model_code,
                    "model_options_by_generation_type": model_options_by_generation_type,
                    "selection_reason": str((default_model_choice or {}).get("selection_reason") or "").strip(),
                    "selection_mode": str((default_model_choice or {}).get("selection_mode") or "").strip(),
                    "video_field_matrix": video_field_matrix,
                },
            }
        ),
        answer_json=_json_dumps({}),
        created_at=_utc_now(),
        updated_at=_utc_now(),
    )
    service.session.add(question)
    service.session.flush()

    assistant_turn = service._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": "生成视频",
                "description": description,
                "task_type": "generate_panel_video",
                "status": "pending",
                "preview": {
                    "total_panels": len(panels),
                    "panels_without_videos": len(candidates),
                    "selected_panel_count": len(selected_panels),
                    "selected_panel_display": selected_display or None,
                    "generation_type": GENERATION_TYPE_LABELS.get(generation_type, generation_type),
                },
            },
            {
                "id": uuid.uuid4().hex,
                "type": "question",
                "question_id": question.question_key,
                "question_type": "wizard",
                "title": title,
                "prompt": description,
                "options": [],
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
    )
    service._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    service.session.commit()
    service.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "question_event": {
            "type": "question",
            "question": {
                "question_id": question.question_key,
                "question_type": "wizard",
            },
        },
        "pending_question_wizard": service._serialize_pending_question(question),
        "project_changes": [],
    }


def submit_panel_video_generation_v2(
    service,
    *,
    session_obj: AssistantSession,
    user: User,
    selected_panels: List[Panel],
    prompt_override: Optional[str] = None,
    model_choice: Optional[Dict[str, Any]] = None,
    duration: Optional[Any] = None,
    resolution: Optional[str] = None,
    generation_type: Optional[str] = None,
    audio_enabled: bool = False,
    attachments: Optional[List[Dict[str, Any]]] = None,
    selection_reason: str = "",
    selection_mode: str = "auto",
    resume_hint: str = "",
) -> Dict[str, Any]:
    submit_result = submit_panel_video_generation_tasks(
        service,
        session_obj=session_obj,
        user=user,
        selected_panels=selected_panels,
        prompt_override=prompt_override,
        model_choice=model_choice,
        duration=duration,
        resolution=resolution,
        generation_type=generation_type,
        audio_enabled=audio_enabled,
        attachments=attachments,
        selection_reason=selection_reason,
        selection_mode=selection_mode,
        resume_hint=resume_hint,
    )

    task_items = submit_result["task_items"]
    selected_display = submit_result["selected_display"]
    selected_panel_payload = submit_result["selected_panel_payload"]
    resolved_model = submit_result["resolved_model"]
    resolved_generation_type = submit_result["resolved_generation_type"]
    refresh_hints = submit_result["refresh_hints"]
    execution_plan = submit_result["execution_plan"]

    tool_use_id = uuid.uuid4().hex
    model_name = str(resolved_model.get("model_name") or resolved_model.get("model_code") or "")
    summary = "已为 {0} 提交 {1} 个视频任务，当前使用 {2}。".format(selected_display, len(task_items), model_name)
    assistant_turn = service._build_turn(
        role="assistant",
        blocks=[
            {
                "id": uuid.uuid4().hex,
                "type": "text",
                "text": "{0} 你可以在任务面板里继续跟进进度。".format(summary),
            },
            {
                "id": tool_use_id,
                "type": "tool_use",
                "tool_name": "generate_panel_video",
                "title": "提交视频生成任务",
                "status": "completed",
                "description": "已完成分镜范围解析、视频模型选择与任务冻结，并提交到视频生成队列。",
            },
            {
                "id": uuid.uuid4().hex,
                "type": "task_progress",
                "title": "视频任务已提交",
                "description": summary,
                "task_type": "generate_panel_video",
                "status": "running",
                "preview": {
                    "selected_panel_display": selected_display,
                    "selected_panel_count": len(task_items),
                    "generation_type": GENERATION_TYPE_LABELS.get(resolved_generation_type, resolved_generation_type),
                    "model_name": model_name,
                },
            },
            {
                "id": uuid.uuid4().hex,
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "tool_name": "generate_panel_video",
                "summary": summary,
                "result": {
                    "tasks": task_items,
                    "selection_reason": selection_reason,
                    "selected_panels": selected_panel_payload,
                    "resolved_model_choice": execution_plan.get("resolved_model_choice"),
                    "refresh_hints": refresh_hints,
                },
            },
        ],
        metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
    )
    service._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
    service.session.commit()
    service.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
    return {
        "assistant_turn": assistant_turn,
        "project_changes": [
            {
                "block_id": tool_use_id,
                "tool_name": "generate_panel_video",
                "summary": summary,
                "refresh_hints": refresh_hints,
            }
        ],
        "execution_plan": execution_plan,
    }


def answer_generate_panel_video_question_v2(
    service,
    *,
    session_obj: AssistantSession,
    user: User,
    action: str,
    question_payload: Dict[str, Any],
    answers: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    metadata = question_payload.get("metadata") or {}
    answer_data = answers or {}
    selected_sequences = [
        int(item)
        for item in (metadata.get("selected_panel_sequences") or [])
        if str(item).strip()
    ]

    if action == "reject":
        turn = service._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "interrupt_notice",
                    "text": "已取消本次视频任务，不会继续提交生成。",
                }
            ],
        )
        service._insert_turn_event(session_obj=session_obj, turn=turn)
        session_obj.status = "completed"
        session_obj.updated_at = _utc_now()
        service.session.add(session_obj)
        service.session.commit()
        service.publish_event(session_obj.id, {"type": "patch", "turn": turn})
        return {
            "snapshot": service.get_snapshot(session_obj=session_obj),
            "execution_plan": build_video_execution_plan_payload(
                execution_stage="canceled",
                selected_panels=[],
                selection_reason="已取消本次视频任务。",
                resume_hint="重新发起请求时可以继续指定分镜范围和模型。",
            ),
        }

    if not session_obj.episode_id:
        raise HTTPException(status_code=400, detail="请先进入具体剧集，再让 AI 帮你生成视频")

    panels = service.session.exec(
        select(Panel)
        .where(Panel.episode_id == session_obj.episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    if not panels:
        raise HTTPException(status_code=400, detail="当前剧集还没有分镜，请先拆分或编写分镜")

    candidates = [panel for panel in panels if not panel_has_video(panel)]
    if not selected_sequences:
        selection_text = str(answer_data.get("panel_scope") or "").strip()
        selection = resolve_panel_selection(selection_text, panels, panels_without_videos=candidates, fallback_when_single=True)
        if not selection or not selection.get("panel_sequences"):
            raise HTTPException(status_code=400, detail="请用 2-4、2,3,5、前3镜 这类格式指定分镜范围")
        selected_sequences = [int(item) for item in selection["panel_sequences"]]

    selected_panels = [
        panel for panel in panels
        if int(panel.sequence_num or 0) in set(selected_sequences)
    ]
    if not selected_panels:
        raise HTTPException(status_code=404, detail="目标分镜不存在或已被删除")

    attachment_image_urls = [str(item).strip() for item in (metadata.get("attachment_image_urls") or []) if str(item).strip()]
    attachment_video_urls = [str(item).strip() for item in (metadata.get("attachment_video_urls") or []) if str(item).strip()]
    default_latest_image = panel_latest_image(selected_panels[0]) if selected_panels and all(panel_latest_image(panel) for panel in selected_panels) else ""
    resolved_generation_type = str(
        answer_data.get("generation_type")
        or metadata.get("generation_type")
        or infer_video_generation_type(
            content="",
            latest_image=default_latest_image,
            attachment_image_urls=attachment_image_urls,
            attachment_video_urls=attachment_video_urls,
        )
    ).strip().lower()
    resolved_audio_enabled = coerce_bool(answer_data.get("audio_enabled"), bool(metadata.get("audio_enabled")))
    explicit_model_code = str(answer_data.get("model_code") or metadata.get("default_model_code") or "").strip()
    explicit_request = None
    if explicit_model_code:
        explicit_request = resolve_explicit_video_model_request(explicit_model_code) or {
            "requested_text": explicit_model_code,
            "model_code": explicit_model_code,
            "connected": True,
            "model_name": explicit_model_code,
        }

    model_choice = choose_video_model(
        content="",
        generation_type=resolved_generation_type,
        duration=int(answer_data.get("duration") or panel_video_duration(selected_panels[0])),
        audio_enabled=resolved_audio_enabled,
        image_ref_count=len(attachment_image_urls),
        video_ref_count=len(attachment_video_urls),
        explicit_request=explicit_request,
    )
    if not model_choice.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=build_model_unavailable_message(
                reason=str(model_choice.get("reason") or "当前没有可用的视频模型。"),
                alternatives=model_choice.get("alternatives") or [],
            ),
        )

    result = submit_panel_video_generation_v2(
        service,
        session_obj=session_obj,
        user=user,
        selected_panels=selected_panels,
        prompt_override=answer_data.get("prompt_override"),
        model_choice=model_choice,
        duration=answer_data.get("duration"),
        resolution=answer_data.get("resolution"),
        generation_type=resolved_generation_type,
        audio_enabled=resolved_audio_enabled,
        attachments=[
            *({"type": "image", "url": url} for url in attachment_image_urls),
            *({"type": "video", "url": url} for url in attachment_video_urls),
        ],
        selection_reason=str(model_choice.get("selection_reason") or metadata.get("selection_reason") or "").strip(),
        selection_mode=str(model_choice.get("selection_mode") or metadata.get("selection_mode") or "explicit").strip(),
        resume_hint="已按 {0} 继续提交视频任务。".format(format_selected_panel_display(selected_panels)),
    )
    session_obj.status = "completed"
    session_obj.updated_at = _utc_now()
    service.session.add(session_obj)
    service.session.commit()
    return {"snapshot": service.get_snapshot(session_obj=session_obj), **result}


def execute_generate_panel_video_skill_v2(
    service,
    *,
    session_obj: AssistantSession,
    user: User,
    content: str,
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not session_obj.episode_id:
        assistant_turn = service._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "请先选中一个具体剧集，我才能按当前分镜范围为你提交视频任务。",
                }
            ],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        service._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        service.session.commit()
        service.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {"assistant_turn": assistant_turn, "project_changes": []}

    panels = service.session.exec(
        select(Panel)
        .where(Panel.episode_id == session_obj.episode_id)
        .order_by(Panel.sequence_num.asc(), Panel.id.asc())
    ).all()
    if not panels:
        assistant_turn = service._build_turn(
            role="assistant",
            blocks=[
                {
                    "id": uuid.uuid4().hex,
                    "type": "text",
                    "text": "当前剧集还没有分镜，先拆分分镜或写分镜后，我再帮你做视频。",
                }
            ],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        service._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        service.session.commit()
        service.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {"assistant_turn": assistant_turn, "project_changes": []}

    candidates = [panel for panel in panels if not panel_has_video(panel)]
    selection = resolve_panel_selection(content, panels, panels_without_videos=candidates, fallback_when_single=True)
    selected_panels = []
    if selection and selection.get("panel_sequences"):
        selected_sequences = {int(item) for item in selection["panel_sequences"]}
        selected_panels = [panel for panel in panels if int(panel.sequence_num or 0) in selected_sequences]

    attachment_urls = attachment_media_urls(attachments)
    attachment_image_urls = attachment_urls["image_urls"]
    attachment_video_urls = attachment_urls["video_urls"]
    latest_image = panel_latest_image(selected_panels[0]) if selected_panels and all(panel_latest_image(panel) for panel in selected_panels) else ""
    generation_type = infer_video_generation_type(
        content=content,
        latest_image=latest_image,
        attachment_image_urls=attachment_image_urls,
        attachment_video_urls=attachment_video_urls,
    )
    audio_enabled = infer_audio_enabled(content)
    explicit_request = resolve_explicit_video_model_request(content)
    duration_hint = panel_video_duration(selected_panels[0]) if selected_panels else (6 if candidates else panel_video_duration(panels[0]))
    model_choice = choose_video_model(
        content=content,
        generation_type=generation_type,
        duration=duration_hint,
        audio_enabled=audio_enabled,
        image_ref_count=len(attachment_image_urls),
        video_ref_count=len(attachment_video_urls),
        explicit_request=explicit_request,
    )

    if explicit_request and not model_choice.get("ok"):
        reason_text = build_model_unavailable_message(
            reason=str(model_choice.get("reason") or "当前没有可用的视频模型。"),
            alternatives=model_choice.get("alternatives") or [],
        )
        assistant_turn = service._build_turn(
            role="assistant",
            blocks=[{"id": uuid.uuid4().hex, "type": "text", "text": reason_text}],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        service._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        service.session.commit()
        service.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {
            "assistant_turn": assistant_turn,
            "project_changes": [],
            "execution_plan": build_video_execution_plan_payload(
                execution_stage="needs_model_change",
                selected_panels=selected_panels,
                selection_reason=reason_text,
                resume_hint=(selection or {}).get("resume_hint") or "换成可用模型后可继续执行。",
            ),
        }

    if not model_choice.get("ok"):
        reason_text = str(model_choice.get("reason") or "当前没有可用的视频模型。")
        assistant_turn = service._build_turn(
            role="assistant",
            blocks=[{"id": uuid.uuid4().hex, "type": "text", "text": reason_text}],
            metadata={"source": "assistant_skill", "skill": "generate_panel_video"},
        )
        service._insert_turn_event(session_obj=session_obj, turn=assistant_turn)
        service.session.commit()
        service.publish_event(session_obj.id, {"type": "patch", "turn": assistant_turn})
        return {
            "assistant_turn": assistant_turn,
            "project_changes": [],
            "execution_plan": build_video_execution_plan_payload(
                execution_stage="needs_model_change",
                selected_panels=selected_panels,
                selection_reason=reason_text,
                resume_hint=(selection or {}).get("resume_hint") or "请调整生成方式、音频要求或模型偏好后重试。",
            ),
        }

    prompt_required = bool(selected_panels) and any(not derive_panel_video_prompt(panel) for panel in selected_panels)
    if selected_panels and not prompt_required:
        return submit_panel_video_generation_v2(
            service,
            session_obj=session_obj,
            user=user,
            selected_panels=selected_panels,
            model_choice=model_choice,
            duration=duration_hint,
            resolution=None,
            generation_type=generation_type,
            audio_enabled=audio_enabled,
            attachments=attachments,
            selection_reason=str(model_choice.get("selection_reason") or "").strip(),
            selection_mode=str(model_choice.get("selection_mode") or "auto").strip(),
            resume_hint=(selection or {}).get("resume_hint") or "已直接按当前解析结果提交视频任务。",
        )

    pending_count = len(candidates)
    selected_display = format_selected_panel_display(selected_panels)
    if selected_panels and prompt_required:
        description = "已解析到 {0}，但其中至少有一个分镜缺少视频提示词，请补充后继续。".format(selected_display)
    elif selected_panels:
        description = "已解析到 {0}，你也可以在继续前手动调整生成方式、模型和时长。".format(selected_display)
    else:
        description = (
            "当前剧集共有 {0} 个分镜，其中 {1} 个还没有视频。请补充分镜范围和生成参数后继续。".format(len(panels), pending_count)
            if pending_count
            else "当前剧集的分镜都已有视频；如需重做，请指定分镜范围和生成参数。"
        )

    wizard_result = create_panel_video_wizard_v2(
        service,
        session_obj=session_obj,
        title="补充分镜视频参数",
        description=description,
        panels=panels,
        candidates=candidates,
        selected_panels=selected_panels,
        prompt_required=prompt_required,
        generation_type=generation_type,
        audio_enabled=audio_enabled,
        default_model_choice=model_choice,
        attachment_image_urls=attachment_image_urls,
        attachment_video_urls=attachment_video_urls,
    )
    wizard_result["execution_plan"] = build_video_execution_plan_payload(
        execution_stage="awaiting_video_parameters",
        selected_panels=selected_panels,
        model_choice=model_choice,
        selection_reason=str(model_choice.get("selection_reason") or "").strip(),
        resume_hint=(selection or {}).get("resume_hint") or "补齐参数后会继续按当前范围提交视频任务。",
    )
    return wizard_result
