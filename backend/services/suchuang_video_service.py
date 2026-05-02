import os
import aiohttp
import json
from typing import Optional, Dict, Any, List
from core.config import settings

class SuChuangVideoService:
    def __init__(self):
        self.api_key = settings.SUCHUANG_KEY
        if not self.api_key:
            print("Warning: SUCHUANG_KEY not set in environment.")
        
        self.headers = {
            "Content-Type": "application/x-www-form-urlencoded;charset:utf-8;",
            "Authorization": f"{self.api_key}"
        }
        self.base_url = "https://api.wuyinkeji.com/api/async"
        self.query_url = "https://api.wuyinkeji.com/api/async/detail"

    async def generate_veo3_1_fast(self, prompt: str, first_frame_url: Optional[str] = None, last_frame_url: Optional[str] = None, urls: Optional[List[str]] = None, aspect_ratio: str = "16:9", size: str = "720p") -> Dict[str, Any]:
        """
        调用速创 veo 3.1 fast 视频生成。
        支持 'prompt' 为必填。
        如果指定了参考图像 'urls'，绝对不能与 first/last_frame_url 混用。
        """
        url = f"{self.base_url}/video_veo3.1_fast?key={self.api_key}"
        
        payload = {
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "size": size
        }
        
        if first_frame_url:
            payload["firstFrameUrl"] = first_frame_url
            if last_frame_url:
                payload["lastFrameUrl"] = last_frame_url
        elif urls and len(urls) > 0:
            payload["urls"] = json.dumps(urls)  # 文档里说是array, application/x-www-form-urlencoded传array通常需要转json string
            
        return await self._post_url_encoded(url, payload)

    async def generate_veo3_1_pro(self, prompt: str, first_frame_url: Optional[str] = None, last_frame_url: Optional[str] = None, aspect_ratio: str = "16:9", size: str = "720p") -> Dict[str, Any]:
        """
        调用速创 veo 3.1 pro 视频生成。带声音，效果最强。
        """
        url = f"{self.base_url}/video_veo3.1_pro?key={self.api_key}"
        
        payload = {
            "prompt": prompt,
            "aspectRatio": aspect_ratio,
            "size": size
        }
        
        if first_frame_url:
            payload["firstFrameUrl"] = first_frame_url
            if last_frame_url:
                payload["lastFrameUrl"] = last_frame_url
                
        return await self._post_url_encoded(url, payload)

    async def generate_digital_human(self, video_name: str, video_url: str, audio_url: str) -> Dict[str, Any]:
        """
        调用速创数字人生成 API (需要实名认证)
        """
        url = f"{self.base_url}/video_digital_humans?key={self.api_key}"
        
        payload = {
            "videoName": video_name,
            "videoUrl": video_url,
            "audioUrl": audio_url
        }
        
        return await self._post_url_encoded(url, payload)

    async def query_task(self, task_id: str) -> Dict[str, Any]:
        """
        通用查询：速创通过提供 id 查询各种任务，API 假设统一为一个 query_url
        如果实际的 video query 接口不一致，则需要按照实际微调。
        对于标准生图 API 我们用的 query 是 /api/async/query?key=...&id=xxx
        """
        url = f"{self.query_url}?key={self.api_key}&id={task_id}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return await response.json()
        raise Exception("SuChuang api query failed")

    async def _post_url_encoded(self, url: str, payload: dict) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=self.headers, data=payload) as response:
                try:
                    data = await response.json()
                except Exception as e:
                    text_res = await response.text()
                    raise Exception(f"Failed to parse suchuang video response: {text_res}")
                
                if data.get("code") != 200:
                    raise Exception(f"速创视频 API 报错: {data.get('msg')}")
                
                return data
        raise Exception("SuChuang api post failed")

suchuang_video_service = SuChuangVideoService()
