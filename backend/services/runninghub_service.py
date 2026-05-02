import requests
import json
import uuid
import time
from sqlmodel import Session, select
from datetime import datetime

from core.config import settings
from database import engine
from models import Panel, Episode, TaskStatusEnum
from services.oss_service import _async_upload_to_oss

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {settings.RUNNINGHUB_API_KEY}"
}


def _is_probable_media_url(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith("ERROR:"):
        return False
    return text.startswith(("http://", "https://", "data:", "blob:", "/"))

# ----------------- v1 通道 (旧版直接调工作流) -----------------
def upload_base64_to_runninghub(base64_data: str) -> str:
    payload = {"data": base64_data}
    resp = requests.post(settings.UPLOAD_URL, json=payload, headers=HEADERS).json()
    if resp.get("code") == 0:
        return resp["data"]["url"]
    raise Exception(f"上传底图到 RunningHub 失败: {resp}")

def poll_runninghub_task(panel_id: int, prompt: str):
    """(向后兼容V1) 查询普通文生图任务"""
    import services.billing_service as bs
    payload = {"input": {"prompt": prompt}}
    try:
        resp = requests.post(settings.RUNNINGHUB_URL, json=payload, headers=HEADERS).json()
        if resp.get("code") != 0:
            with Session(engine) as session:
                panel = session.get(Panel, panel_id)
                if panel:
                    panel.status = TaskStatusEnum.FAILED
                    session.add(panel)
                    session.commit()
            return
        
        task_id = resp["data"]["taskId"]
        with Session(engine) as session:
            panel = session.get(Panel, panel_id)
            if panel:
                panel.task_id = task_id
                session.add(panel)
                session.commit()
                
        _poll_task_status(task_id, panel_id)
    except Exception as e:
        print(f"调取 RunningHub 出错: {e}")

def poll_runninghub_img2img(panel_id: int, prompt: str, ref_images: list, ratio: str, resolution: str):
    """(向后兼容V1) 图生图任务"""
    import services.billing_service as bs
    payload = {
        "input": {
            "prompt": prompt,
            "ref_images": ref_images,
            "ratio": ratio,
            "resolution": resolution
        }
    }
    try:
        resp = requests.post(settings.RUNNINGHUB_URL, json=payload, headers=HEADERS).json()
        if resp.get("code") != 0:
            with Session(engine) as session:
                panel = session.get(Panel, panel_id)
                if panel:
                    panel.status = TaskStatusEnum.FAILED
                    session.add(panel)
                    session.commit()
            return
        
        task_id = resp["data"]["taskId"]
        with Session(engine) as session:
            panel = session.get(Panel, panel_id)
            if panel:
                panel.task_id = task_id
                session.add(panel)
                session.commit()
                
        _poll_task_status(task_id, panel_id)
    except Exception as e:
        print(f"调取 RunningHub 图生图出错: {e}")

def _poll_task_status(rh_task_id: str, panel_id: int):
    """(向后兼容V1) 后台循环查询任务结果"""
    payload = {"taskId": rh_task_id}
    
    for _ in range(60): 
        time.sleep(3)
        try:
            resp = requests.post(settings.QUERY_URL, json=payload, headers=HEADERS).json()
            if resp.get("code") == 0:
                status = resp["data"]["status"]
                
                if status == "SUCCESS":
                    outputs = resp.get("data", {}).get("outputs", [])
                    image_url = ""
                    for out in outputs:
                        if out.get("outputType") == "image":
                            image_url = out.get("fileUrl")
                            break
                    
                    with Session(engine) as session:
                        panel = session.get(Panel, panel_id)
                        if panel:
                            panel.status = TaskStatusEnum.COMPLETED
                            panel.image_url = image_url
                            
                            # 将生成的图片的最新 URL 插入到历史记录中最前面 [V1旧版核心特性同步保留]
                            history = json.loads(panel.history_urls_json) if panel.history_urls_json else []
                            if image_url and image_url not in history:
                                history.insert(0, image_url)
                            panel.history_urls_json = json.dumps(history)
                            
                            panel.transfer_status = 1
                            session.add(panel)
                            session.commit()
                            
                    # 触发 OSS 异步转存 
                    if image_url:
                        import threading
                        threading.Thread(target=_async_upload_to_oss, args=(panel_id, image_url), daemon=True).start()
                    return
                    
                elif status == "FAILED":
                    with Session(engine) as session:
                        panel = session.get(Panel, panel_id)
                        if panel:
                            panel.status = TaskStatusEnum.FAILED
                            session.add(panel)
                            session.commit()
                    return
        except Exception:
            pass

# ----------------- v2 通道 (大统一生图路由转发) -----------------
# 通道 ID → RunningHub 标准模型 API 端点映射表
RH_V2_CHANNEL_MAP = {
    # 全能图片V2 (Flash 版)
    "rh-v2-text2img": "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash/text-to-image",
    "rh-v2-img2img": "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash/image-to-image",
    # 全能图片V2 (官方版)
    "rh-v2-official-text2img": "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash-official/text-to-image",
    "rh-v2-official-img2img": "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash-official/image-to-image",
}

def dispatch_runninghub_task_v2(panel_id: int, our_task_id: str, req):
    """提交任务到 RunningHub 标准模型 API（支持 4 个全能图片V2 通道）"""
    import threading
    
    def internal_rh_worker():
        try:
            channel = req.channel
            print(f"🔄 [RunningHub v2] 提交任务: {channel}...")
            
            # 1. 根据通道 ID 查找对应的 API 端点
            url = RH_V2_CHANNEL_MAP.get(channel)
            if not url:
                _mark_panel_failed(panel_id, our_task_id, f"未知的 RunningHub 通道: {channel}")
                return
            
            # 2. 构建请求体：图生图通道必须带 imageUrls
            is_img2img = "img2img" in channel
            if is_img2img:
                if not req.imageUrls:
                    _mark_panel_failed(panel_id, our_task_id, "图生图通道必须提供参考图 imageUrls")
                    return
                payload = {
                    "prompt": req.prompt,
                    "imageUrls": req.imageUrls,
                    "resolution": req.resolution or "1k",
                }
            else:
                payload = {
                    "prompt": req.prompt,
                    "resolution": req.resolution or "1k",
                }
            
            # 3. aspectRatio 是可选参数，有则加
            if req.aspectRatio:
                payload["aspectRatio"] = req.aspectRatio
            
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=30).json()
            print(f"📡 [RunningHub v2] 提交响应: {resp}")
            
            rh_task_id = resp.get("taskId", "")
            if not rh_task_id:
                error_msg = resp.get("errorMessage", "") or resp.get("message", "") or str(resp)
                _mark_panel_failed(panel_id, our_task_id, f"RH 未返回 taskId: {error_msg}")
                return
            
            print(f"🔄 [RunningHub v2] 任务已提交, taskId: {rh_task_id}")
            _poll_runninghub_task_v2(rh_task_id, our_task_id, panel_id)
        except Exception as e:
            _mark_panel_failed(panel_id, our_task_id, str(e))
            
    threading.Thread(target=internal_rh_worker, daemon=True).start()

def _poll_runninghub_task_v2(rh_task_id: str, our_task_id: str, panel_id: int):
    """后台轮询 RunningHub 查询接口"""
    url = "https://www.runninghub.cn/openapi/v2/query"
    payload = {"taskId": rh_task_id}
    
    for _ in range(200):
        try:
            time.sleep(3)
            resp = requests.post(url, json=payload, headers=HEADERS, timeout=30).json()
            task_status = resp.get("status", "")
            
            if task_status == "SUCCESS":
                results = resp.get("results", [])
                image_url = results[0].get("url", "") if results else ""
                if image_url:
                    _mark_panel_success_and_oss(panel_id, our_task_id, image_url)
                else:
                    _mark_panel_failed(panel_id, our_task_id, "RH 成功但无图片 URL")
                return
            elif task_status == "FAILED":
                msg = resp.get("errorMessage", "") or str(resp.get("failedReason", "任务失败"))
                _mark_panel_failed(panel_id, our_task_id, msg)
                return
        except Exception:
            pass
    _mark_panel_failed(panel_id, our_task_id, "RunningHub 轮询超时")


# ----------------- V2 内部共享底层状态更新 -----------------
def _mark_panel_success_and_oss(panel_id: int, our_task_id: str, image_url: str):
    """更新 Panel 为成功，并触发 OSS 转移"""
    try:
        with Session(engine) as s:
            panel = s.get(Panel, panel_id)
            if panel:
                panel.status = TaskStatusEnum.COMPLETED
                panel.image_url = image_url
                panel.transfer_status = 1
                
                # 更新历史记录数组的最前列
                history = json.loads(panel.history_urls_json) if panel.history_urls_json else []
                if image_url not in history:
                    history.insert(0, image_url)
                panel.history_urls_json = json.dumps(history)
                
                s.add(panel)
                s.commit()
                print(f"🎉 [生图平台返回成功] Task: {our_task_id}")
        import threading
        threading.Thread(target=_async_upload_to_oss, args=(panel_id, image_url), daemon=True).start()
    except Exception as e:
        print(f"保存结果失败: {e}")

def _mark_panel_failed(panel_id: int, our_task_id: str, reason: str):
    """更新 Panel 为失败"""
    try:
        with Session(engine) as s:
            panel = s.get(Panel, panel_id)
            if panel:
                panel.status = TaskStatusEnum.FAILED
                # 借助 image_url 暂时存一下报错信息供查阅
                if not _is_probable_media_url(panel.image_url):
                    panel.image_url = None
                s.add(panel)
                s.commit()
                print(f"❌ [生图流转失败] Task: {our_task_id} Reason: {reason}")
    except Exception:
        pass
