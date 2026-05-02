import requests
import time
from sqlmodel import Session

from core.config import settings
from database import engine
from models import Panel
from services.runninghub_service import _mark_panel_success_and_oss, _mark_panel_failed

def dispatch_suchuang_task_v2(panel_id: int, our_task_id: str, req):
    """提交任务到速创 (无音) API"""
    import threading
    
    def internal_suchuang_worker():
        try:
            print(f"🔄 [SuChuang v2] 提交任务...")
            if req.channel == "suchuang-nanobanana2":
                url = f"https://api.wuyinkeji.com/api/async/image_nanoBanana2?key={settings.SUCHUANG_KEY}"
            else:
                url = f"https://api.wuyinkeji.com/api/async/image_nanoBanana_pro?key={settings.SUCHUANG_KEY}"
            
            # 必填参数
            payload = {
                "prompt": req.prompt,
            }
            # 可选参数
            if req.resolution:
                payload["size"] = req.resolution.upper()
            if req.aspectRatio:
                payload["aspectRatio"] = req.aspectRatio
            if req.imageUrls:
                for i, img_url in enumerate(req.imageUrls):
                    if i >= 14: break
                    payload[f"urls[{i}]"] = img_url
            
            resp = requests.post(url, data=payload, timeout=30).json()
            
            if resp.get("code") != 200:
                _mark_panel_failed(panel_id, our_task_id, f"速创提交错误: {resp.get('msg', resp)}")
                return
            
            data = resp.get("data", {})
            if isinstance(data, dict):
                sc_task_id = data.get("id", "")
            else:
                sc_task_id = str(data)
            
            if not sc_task_id:
                _mark_panel_failed(panel_id, our_task_id, f"未返回速创 Task ID: {resp}")
                return
            
            _poll_suchuang_task_v2(sc_task_id, our_task_id, panel_id, settings.SUCHUANG_KEY)
        except Exception as e:
            _mark_panel_failed(panel_id, our_task_id, str(e))
            
    threading.Thread(target=internal_suchuang_worker, daemon=True).start()

def _poll_suchuang_task_v2(sc_task_id: str, our_task_id: str, panel_id: int, api_key: str):
    """轮询速创异步结果"""
    url = f"https://api.wuyinkeji.com/api/async/detail?key={api_key}&id={sc_task_id}"
    for i in range(200):
        try:
            time.sleep(3)
            resp = requests.get(url, timeout=30).json()
            data = resp.get("data", {})
            
            if not isinstance(data, dict):
                continue
            status = data.get("status", 0) # 0初始 1执行 2成功 3失败
            
            if status == 2:
                result = data.get("result", [])
                if result and isinstance(result, list):
                    image_url = result[0] if isinstance(result[0], str) else str(result[0])
                else:
                    image_url = ""
                if image_url:
                    _mark_panel_success_and_oss(panel_id, our_task_id, image_url)
                else:
                    _mark_panel_failed(panel_id, our_task_id, f"速创成功但无图片 URL: {data}")
                return
            elif status == 3:
                msg = data.get("message", "速创平台返回任务失败")
                _mark_panel_failed(panel_id, our_task_id, msg)
                return
        except Exception as e:
            pass
    _mark_panel_failed(panel_id, our_task_id, "速创轮询超时")
