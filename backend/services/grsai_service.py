import json
import time

import requests
from sqlmodel import Session, select

from core.config import settings
from database import engine
from models import Panel, TaskStatusEnum
from services.runninghub_service import _mark_panel_failed, _mark_panel_success_and_oss
from services.task_registry import nano_tasks, standalone_tasks


def poll_standalone_task(nano_task_id: str, our_task_id: str):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}
    for _ in range(200):
        try:
            time.sleep(3)
            resp = requests.post(settings.NANO_RESULT_URL, json={"id": nano_task_id}, headers=headers, timeout=30)
            data = resp.json()
            result_data = data.get("data", data)
            status = result_data.get("status", "")
            if status == "succeeded":
                results = result_data.get("results", [])
                url = results[0]["url"] if results else ""
                standalone_tasks.set(our_task_id, {"status": "completed", "url": url, "error": ""})
                return
            if status in ("failed", "error"):
                standalone_tasks.set(our_task_id, {"status": "failed", "url": "", "error": "生成失败"})
                return
        except Exception:
            pass
    standalone_tasks.set(our_task_id, {"status": "failed", "url": "", "error": "轮询超时"})


def poll_nano_task_v1(nano_task_id: str, our_task_id: str, episode_id: int, prompt: str):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}
    for _ in range(200):
        try:
            time.sleep(3)
            resp = requests.post(settings.NANO_RESULT_URL, json={"id": nano_task_id}, headers=headers, timeout=30)
            data = resp.json()
            result_data = data.get("data", data)
            status = result_data.get("status", "")
            progress = result_data.get("progress", 0)
            if nano_tasks.get(our_task_id):
                nano_tasks.update(our_task_id, progress=progress)
            if status == "succeeded":
                results = result_data.get("results", [])
                url = results[0]["url"] if results else ""
                with Session(engine) as session:
                    last_panel = session.exec(
                        select(Panel).where(Panel.episode_id == episode_id).order_by(Panel.sequence_num.desc())
                    ).first()
                    next_seq = (last_panel.sequence_num + 1) if last_panel else 1
                    new_panel = Panel(
                        episode_id=episode_id,
                        sequence_num=next_seq,
                        panel_type="normal",
                        task_id=our_task_id,
                        prompt=prompt,
                        status=TaskStatusEnum.COMPLETED,
                        image_url=url,
                        transfer_status=1,
                        history_urls_json=json.dumps([url]) if url else "[]",
                    )
                    session.add(new_panel)
                    session.commit()
                    session.refresh(new_panel)
                    panel_db_id = new_panel.id
                nano_tasks.set(our_task_id, {"status": "completed", "url": url, "progress": 100, "error": ""})
                if url:
                    from services.oss_service import _async_upload_to_oss
                    import threading

                    threading.Thread(target=_async_upload_to_oss, args=(panel_db_id, url), daemon=True).start()
                return
            if status == "failed":
                reason = result_data.get("failure_reason", "") or result_data.get("error", "未知错误")
                nano_tasks.set(our_task_id, {"status": "failed", "url": "", "progress": 0, "error": reason})
                return
        except Exception:
            continue
    nano_tasks.set(our_task_id, {"status": "failed", "url": "", "progress": 0, "error": "轮询超时"})


def dispatch_grsai_task_v2(panel_id: int, our_task_id: str, req):
    import threading

    def internal_grsai_worker():
        try:
            payload = {
                "model": req.channel,
                "prompt": req.prompt,
                "aspectRatio": req.aspectRatio,
                "imageSize": req.resolution.upper(),
                "urls": req.imageUrls,
                "webHook": "-1",
            }
            resp = requests.post(
                settings.NANO_API_URL,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"},
                json=payload,
                timeout=30,
            ).json()
            grsai_task_id = resp.get("data", {}).get("id", "")
            if not grsai_task_id:
                _mark_panel_failed(panel_id, our_task_id, f"平台未返回ID: {resp}")
                return
            _poll_nano_task_v2(grsai_task_id, our_task_id, panel_id)
        except Exception as exc:
            _mark_panel_failed(panel_id, our_task_id, str(exc))

    threading.Thread(target=internal_grsai_worker, daemon=True).start()


def _poll_nano_task_v2(grsai_task_id: str, our_task_id: str, panel_id: int):
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}
    for _ in range(200):
        try:
            time.sleep(3)
            resp = requests.post(settings.NANO_RESULT_URL, json={"id": grsai_task_id}, headers=headers, timeout=30)
            data = resp.json()
            result_data = data.get("data", data)
            status = result_data.get("status", "")
            if status == "succeeded":
                results = result_data.get("results", [])
                url = results[0]["url"] if results else ""
                if url:
                    _mark_panel_success_and_oss(panel_id, our_task_id, url)
                return
            if status in ("failed", "error"):
                reason = (
                    result_data.get("error", "")
                    or result_data.get("message", "")
                    or result_data.get("msg", "")
                    or result_data.get("failure_reason", "")
                    or data.get("message", "")
                    or data.get("msg", "")
                )
                if not reason or reason in ("error", "failed"):
                    reason = f"达卡平台返回错误 (完整响应: {str(data)[:300]})"
                _mark_panel_failed(panel_id, our_task_id, reason)
                return
        except Exception:
            continue
    _mark_panel_failed(panel_id, our_task_id, "Grsai 轮询超时")
