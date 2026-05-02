from __future__ import annotations

import asyncio
import requests
from core.config import settings
from . import ProviderResult

_KEY = settings.SUCHUANG_KEY
_SUBMIT_URLS = {
    "nanoBanana2": f"https://api.wuyinkeji.com/api/async/image_nanoBanana2?key={_KEY}",
    "nanoBanana_pro": f"https://api.wuyinkeji.com/api/async/image_nanoBanana_pro?key={_KEY}",
}
_QUERY_URL = f"https://api.wuyinkeji.com/api/async/detail?key={_KEY}"


class SuchuangImageAdapter:
    def __init__(self, model: str = "nanoBanana_pro"):
        self.submit_url = _SUBMIT_URLS.get(model, _SUBMIT_URLS["nanoBanana_pro"])
        self.provider_key = "suchuang-image"

    async def submit(self, payload: dict) -> str:
        resp = await asyncio.to_thread(
            lambda: requests.post(self.submit_url, data=payload, timeout=30).json()
        )
        return str(resp["data"]["id"])

    async def query(self, upstream_task_id: str) -> ProviderResult:
        resp = await asyncio.to_thread(
            lambda: requests.get(f"{_QUERY_URL}&id={upstream_task_id}", timeout=30).json()
        )
        data = resp.get("data", {})
        status = data.get("status", 0)
        if status == 2:
            return ProviderResult(is_done=True, is_failed=False, output_url=data.get("result", [None])[0], raw_payload=resp)
        if status == 3:
            return ProviderResult(is_done=True, is_failed=True, error=data.get("message"), raw_payload=resp)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=resp)

    def supports_webhook(self) -> bool:
        return False

    def build_submit_payload(self, payload: dict) -> dict:
        return payload

    def parse_callback(self, request_body: dict, headers: dict) -> ProviderResult:
        return ProviderResult(is_done=False, is_failed=False, raw_payload=request_body)
