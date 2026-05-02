import json
import asyncio
from typing import Optional, Dict, Any, List

import aiohttp

from core.config import settings


class RunningHubVideoService:
    def __init__(self):
        self.api_key = settings.RUNNINGHUB_API_KEY
        if not self.api_key:
            print("Warning: RUNNINGHUB_API_KEY not set in environment.")

        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        self.base_url = "https://www.runninghub.cn/openapi/v2/vidu"
        self.openapi_base_url = "https://www.runninghub.cn/openapi/v2"
        self.query_url = "https://www.runninghub.cn/openapi/v2/query"

    async def submit_task(self, endpoint: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        endpoint_text = str(endpoint or "").strip()
        if not endpoint_text.startswith("/"):
            endpoint_text = f"/{endpoint_text}"
        return await self._post_request(f"{self.openapi_base_url}{endpoint_text}", payload)

    async def generate_vidu_q3_pro(
        self,
        prompt: str,
        image_urls: List[str],
        duration: str = "5",
        resolution: str = "1080p",
        audio: bool = False,
        webhook_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        RunningHub Vidu Q3 Pro：当前只开放单图生视频
        """
        url = f"{self.base_url}/image-to-video-q3-pro"

        if not image_urls or len(image_urls) == 0:
            raise ValueError("Vidu Q3 Pro 必须提供至少 1 张首帧图")

        payload = {
            "prompt": prompt,
            "imageUrl": image_urls[0],
            "duration": str(duration),
            "resolution": resolution,
            "audio": audio,
        }

        if webhook_url:
            payload["webhookUrl"] = webhook_url

        return await self._post_request(url, payload)

    async def generate_vidu_q2_pro(
        self,
        prompt: str,
        image_urls: List[str],
        duration: str = "5",
        resolution: str = "1080p",
        movement_amplitude: str = "auto",
        bgm: bool = False,
        webhook_url: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
        video_urls: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        RunningHub Vidu Q2 Pro：
        - 单图时走 image-to-video-q2-pro
        - 多图 / 首尾帧 / 参考视频时走 reference-to-video-q2-pro
        """
        image_urls = [u for u in (image_urls or []) if u]
        video_urls = [u for u in (video_urls or []) if u]

        if not image_urls:
            raise ValueError("Vidu Q2 Pro 至少需要 1 张参考图")

        # 有多张图或参考视频时，走参考生视频接口
        if len(image_urls) > 1 or len(video_urls) > 0:
            return await self.generate_vidu_q2_reference(
                prompt=prompt,
                image_urls=image_urls,
                video_urls=video_urls,
                duration=duration,
                resolution=resolution,
                movement_amplitude=movement_amplitude,
                webhook_url=webhook_url,
                aspect_ratio=aspect_ratio,
            )

        # 单图普通模式
        url = f"{self.base_url}/image-to-video-q2-pro"
        payload = {
            "prompt": prompt,
            "imageUrl": image_urls[0],
            "duration": str(duration),
            "resolution": resolution,
            "movementAmplitude": movement_amplitude,
            "bgm": bgm,
        }

        if webhook_url:
            payload["webhookUrl"] = webhook_url

        return await self._post_request(url, payload)

    async def generate_vidu_q2_reference(
        self,
        prompt: str,
        image_urls: List[str],
        video_urls: Optional[List[str]] = None,
        duration: str = "5",
        resolution: str = "1080p",
        movement_amplitude: str = "auto",
        webhook_url: Optional[str] = None,
        aspect_ratio: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        RunningHub 官方 reference-to-video-q2-pro
        支持：
        - imageUrls: 最多 7 张
        - videos: 最多 2 段
        """
        url = f"{self.base_url}/reference-to-video-q2-pro"

        image_urls = [u for u in (image_urls or []) if u][:7]
        video_urls = [u for u in (video_urls or []) if u][:2]

        if not image_urls:
            raise ValueError("reference-to-video-q2-pro 至少需要 1 张参考图")

        payload = {
            "prompt": prompt,
            "imageUrls": image_urls,
            "duration": str(duration),
        }

        if resolution:
            payload["resolution"] = resolution
        if aspect_ratio:
            payload["aspectRatio"] = aspect_ratio
        if movement_amplitude:
            payload["movementAmplitude"] = movement_amplitude
        if video_urls:
            payload["videos"] = video_urls
        if webhook_url:
            payload["webhookUrl"] = webhook_url

        return await self._post_request(url, payload)

    async def query_task(self, task_id: str) -> Dict[str, Any]:
        payload = {"taskId": task_id}
        return await self._post_request(self.query_url, payload)

    async def _post_request(self, url: str, payload: dict) -> Dict[str, Any]:
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=30,
                ) as response:
                    text_res = await response.text()
                    try:
                        data = json.loads(text_res)
                    except json.JSONDecodeError:
                        raise Exception(f"Failed to decode RunningHub JSON: {text_res}")

                    if response.status != 200:
                        raise Exception(
                            f"RunningHub API Error {response.status}: "
                            f"{data.get('errorMessage', text_res)}"
                        )

                    if data.get("status") == "FAILED" or data.get("errorCode"):
                        raise Exception(
                            f"RunningHub 接口内部报错: {data.get('errorMessage', '')}"
                        )

                    return data
            except asyncio.TimeoutError:
                raise Exception(" API 请求超时")

        raise Exception(" API Failed to make request")


runninghub_video_service = RunningHubVideoService()
