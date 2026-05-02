from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

from fastapi import BackgroundTasks, HTTPException
from sqlmodel import Session

from core.security import decode_id
from database import engine
from models import CanvasNode, CanvasWorkspace, Episode, Panel, Script, Team, TeamMemberLink, User
from routers.ai_director import parse_story_segments_v3
from routers.generate import generate_image_v2
from routers.resource import extract_script_assets
from schemas import CANVAS_NODE_TYPE_ASSET_TABLE, CANVAS_NODE_TYPE_IMAGE, CANVAS_NODE_TYPE_SCRIPT, CANVAS_NODE_TYPE_STORYBOARD_TABLE, ExtractScriptAssetsRequest, GenerateImageV2Request, ParseScriptV2Request
from services.canvas_service import _json_dump, _json_load, find_workspace_nodes_by_type, mark_downstream_nodes_needs_refresh, refresh_node_snapshot, update_node_meta, upsert_image_node_for_panel
from services.task_job_service import get_task_job, task_status_for_legacy
from services.task_registry import resource_extract_tasks


async def _wait_for_registry_task(registry, task_id: str, timeout_seconds: int = 240) -> Dict[str, object]:
    elapsed = 0
    while elapsed < timeout_seconds:
        task = registry.get(task_id)
        if task and task.get("status") in {"completed", "failed"}:
            return task
        await asyncio.sleep(1)
        elapsed += 1
    raise HTTPException(status_code=504, detail="画布节点动作执行超时")


async def _wait_for_task_job(task_id: str, timeout_seconds: int = 240) -> Dict[str, object]:
    elapsed = 0
    while elapsed < timeout_seconds:
        job = get_task_job(task_id)
        if job:
            legacy_status = task_status_for_legacy(job.status)
            if legacy_status in {"completed", "failed", "cancelled"}:
                return {
                    "status": legacy_status,
                    "msg": job.message,
                    "charged_points": int(job.charged_points or 0),
                    "actual_points": int(job.actual_points or 0),
                    "actual_cost_cny": float(job.actual_cost_cny or 0.0),
                    "points_status": str(job.points_status or "free"),
                }
        await asyncio.sleep(1)
        elapsed += 1
    raise HTTPException(status_code=504, detail="鐢诲竷鑺傜偣鍔ㄤ綔鎵ц瓒呮椂")


async def _wait_for_panel_image(panel_id: int, task_id: str, timeout_seconds: int = 240) -> Panel:
    elapsed = 0
    while elapsed < timeout_seconds:
        with Session(engine) as poll_session:
            panel = poll_session.get(Panel, panel_id)
            if panel and str(panel.task_id or "") == str(task_id or "") and str(panel.status or "").lower() in {"completed", "failed"}:
                return panel
        await asyncio.sleep(2)
        elapsed += 2
    raise HTTPException(status_code=504, detail="图片生成超时，请稍后查看结果")


def _script_id(node: CanvasNode) -> str:
    data = _json_load(node.data_json, {})
    return str(data.get("scriptId") or data.get("projectId") or "")


def _episode_id(node: CanvasNode) -> str:
    data = _json_load(node.data_json, {})
    return str(data.get("episodeId") or "")


def _storyboard_rows(node: CanvasNode) -> List[dict]:
    data = _json_load(node.data_json, {})
    return data.get("rows") if isinstance(data.get("rows"), list) else []


def _find_storyboard_row(node: CanvasNode, row_id: str) -> dict:
    return next((row for row in _storyboard_rows(node) if str(row.get("id") or "") == str(row_id)), {})


async def run_canvas_node_action(
    session: Session,
    *,
    workspace: CanvasWorkspace,
    node: CanvasNode,
    action_name: str,
    payload: Dict[str, object],
    team: Team,
    member_link: TeamMemberLink,
    user: User,
) -> Dict[str, object]:
    script = session.get(Script, workspace.script_id)
    if not script:
        raise HTTPException(status_code=404, detail="关联剧本不存在")

    action = str(action_name or "").strip().lower()
    updated_nodes: List[CanvasNode] = []
    suggested_actions: List[dict] = []

    if node.type == CANVAS_NODE_TYPE_SCRIPT and action == "extract-assets":
        data = _json_load(node.data_json, {})
        response = await extract_script_assets(
            script_id=_script_id(node),
            payload=ExtractScriptAssetsRequest(source_text=str(data.get("content") or "").strip() or None),
            _=member_link,
            session=session,
            team=team,
        )
        task = await _wait_for_registry_task(resource_extract_tasks, response["task_id"])
        if task.get("status") != "completed":
            raise HTTPException(status_code=500, detail=task.get("msg") or "资产提取失败")
        updated_nodes.append(update_node_meta(session, node, {"lastAction": "extract-assets", "lastActionStatus": "success"}))
        for asset_node in find_workspace_nodes_by_type(session, workspace.id, CANVAS_NODE_TYPE_ASSET_TABLE):
            updated_nodes.append(refresh_node_snapshot(session, workspace, asset_node, force_clean=True))
        mark_downstream_nodes_needs_refresh(session, workspace.id, [node.id], "资产已更新，建议刷新分镜")
        return {"status": "success", "node": updated_nodes[0], "updated_nodes": updated_nodes, "suggested_actions": suggested_actions}

    if node.type == CANVAS_NODE_TYPE_SCRIPT and action == "generate-storyboard":
        data = _json_load(node.data_json, {})
        storyboard_nodes = find_workspace_nodes_by_type(session, workspace.id, CANVAS_NODE_TYPE_STORYBOARD_TABLE)
        if not storyboard_nodes:
            raise HTTPException(status_code=400, detail="当前工作区没有分镜节点")
        explicit_episode_id = str(payload.get("episodeId") or payload.get("episode_id") or "").strip()
        target_storyboard = storyboard_nodes[0]
        if explicit_episode_id:
            explicit_episode_raw = decode_id(explicit_episode_id)
            target_storyboard = next((item for item in storyboard_nodes if int(item.source_id or 0) == explicit_episode_raw), storyboard_nodes[0])
        episode_id = explicit_episode_id or _episode_id(target_storyboard)
        response = parse_story_segments_v3(
            episode_id=episode_id,
            req=ParseScriptV2Request(text=str(data.get("content") or "").strip()),
            _=member_link,
            team=team,
            session=session,
        )
        task = await _wait_for_task_job(response["task_id"])
        if task.get("status") != "completed":
            raise HTTPException(status_code=500, detail=task.get("msg") or "结构化分镜生成失败")
        updated_nodes.append(update_node_meta(session, node, {"lastAction": "generate-storyboard", "lastActionStatus": "success"}))
        updated_nodes.append(refresh_node_snapshot(session, workspace, target_storyboard, force_clean=True))
        mark_downstream_nodes_needs_refresh(session, workspace.id, [target_storyboard.id], "分镜已更新，建议刷新图片")
        suggested_actions.append({"type": "suggested_run", "action": "generate-image", "nodeId": target_storyboard.id, "reason": "分镜已更新，可以继续生成图片"})
        return {"status": "success", "node": updated_nodes[0], "updated_nodes": updated_nodes, "suggested_actions": suggested_actions}

    if node.type == CANVAS_NODE_TYPE_STORYBOARD_TABLE and action == "generate-image":
        episode_id = _episode_id(node)
        if not episode_id:
            raise HTTPException(status_code=400, detail="分镜节点缺少 episode 绑定")
        rows = _storyboard_rows(node)
        row_ids = payload.get("rowIds") if isinstance(payload.get("rowIds"), list) else []
        if not row_ids:
            single = str(payload.get("rowId") or "").strip()
            row_ids = [single] if single else ([rows[0].get("id")] if rows else [])
        episode = session.get(Episode, int(node.source_id or 0)) if node.source_id else None
        if not episode:
            raise HTTPException(status_code=404, detail="目标剧集不存在")
        for row_id in row_ids:
            row = _find_storyboard_row(node, str(row_id))
            if not row:
                continue
            response = await generate_image_v2(
                episode_id=episode_id,
                req=GenerateImageV2Request(prompt=str(row.get("imagePrompt") or row.get("scriptSegment") or "").strip(), resolution=str(payload.get("resolution") or "2k"), aspectRatio=str(payload.get("aspectRatio") or payload.get("aspect_ratio") or "16:9"), model_code=str(payload.get("model") or "nano-banana-pro"), imageUrls=list(payload.get("referenceImages") or []), panel_id=str(row_id)),
                background_tasks=BackgroundTasks(),
                _=member_link,
                user=user,
                team=team,
                session=session,
            )
            panel = await _wait_for_panel_image(int(decode_id(str(row_id))), response.get("task_id") or "")
            with Session(engine) as refresh_session:
                fresh_panel = refresh_session.get(Panel, panel.id)
                if fresh_panel:
                    updated_nodes.append(upsert_image_node_for_panel(refresh_session, workspace, script, episode, fresh_panel, node))
        updated_nodes.insert(0, update_node_meta(session, node, {"lastAction": "generate-image", "lastActionStatus": "success"}))
        updated_nodes.append(refresh_node_snapshot(session, workspace, node))
        return {"status": "success", "node": updated_nodes[0], "updated_nodes": updated_nodes, "suggested_actions": suggested_actions}

    if node.type == CANVAS_NODE_TYPE_IMAGE and action in {"regenerate-image", "regenerate_with_latest_prompt"}:
        data = _json_load(node.data_json, {})
        episode_id = str(data.get("episodeId") or "")
        panel_id = str(data.get("sourcePanelId") or "")
        if not episode_id or not panel_id:
            raise HTTPException(status_code=400, detail="图片节点缺少来源分镜")
        response = await generate_image_v2(
            episode_id=episode_id,
            req=GenerateImageV2Request(prompt=str(payload.get("prompt") or data.get("prompt") or "").strip(), resolution=str(payload.get("resolution") or (data.get("params") or {}).get("quality") or "2k"), aspectRatio=str(payload.get("aspectRatio") or (data.get("params") or {}).get("aspectRatio") or "16:9"), model_code=str(payload.get("model") or data.get("model") or "nano-banana-pro"), imageUrls=list(payload.get("referenceImages") or data.get("referenceImages") or []), panel_id=panel_id),
            background_tasks=BackgroundTasks(),
            _=member_link,
            user=user,
            team=team,
            session=session,
        )
        await _wait_for_panel_image(int(decode_id(panel_id)), response.get("task_id") or "")
        updated_nodes.append(update_node_meta(session, node, {"lastAction": action, "lastActionStatus": "success"}))
        updated_nodes.append(refresh_node_snapshot(session, workspace, node))
        return {"status": "success", "node": updated_nodes[0], "updated_nodes": updated_nodes, "suggested_actions": suggested_actions}

    if node.type == CANVAS_NODE_TYPE_IMAGE and action == "refresh_prompt_from_source":
        updated_nodes.append(update_node_meta(session, node, {"lastAction": "refresh_prompt_from_source", "lastActionStatus": "success"}))
        updated_nodes.append(refresh_node_snapshot(session, workspace, node, force_clean=True))
        return {"status": "success", "node": updated_nodes[0], "updated_nodes": updated_nodes, "suggested_actions": suggested_actions}

    if node.type == CANVAS_NODE_TYPE_IMAGE and action == "relink_source_row":
        new_panel_id = str(payload.get("panelId") or payload.get("panel_id") or "").strip()
        new_episode_id = str(payload.get("episodeId") or payload.get("episode_id") or "").strip()
        if not new_panel_id or not new_episode_id:
            raise HTTPException(status_code=400, detail="缺少新的分镜目标")
        data = _json_load(node.data_json, {})
        data["episodeId"] = new_episode_id
        data["sourcePanelId"] = new_panel_id
        data["sourceStoryboardRowId"] = new_panel_id
        node.source_id = decode_id(new_episode_id)
        node.source_sub_id = decode_id(new_panel_id)
        node.data_json = _json_dump(data, "{}")
        session.add(node)
        session.commit()
        updated_nodes.append(update_node_meta(session, node, {"lastAction": "relink_source_row", "lastActionStatus": "success"}))
        updated_nodes.append(refresh_node_snapshot(session, workspace, node, force_clean=True))
        return {"status": "success", "node": updated_nodes[0], "updated_nodes": updated_nodes, "suggested_actions": suggested_actions}

    raise HTTPException(status_code=400, detail="当前节点不支持该动作")
