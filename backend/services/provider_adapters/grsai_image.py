from __future__ import annotations

import asyncio
import requests
from core.config import settings
from . import ProviderResult

_HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.NANO_API_KEY}"}


class GrsaiImageAdapter:
    def __init__(self, model: str = "flux-kontext-pro"):
        self.model = model
        self.provider_key = "grsai-image"

    async def submit(self, payload: dict) -> str:
        resp = await asyncio.to_thread(
            lambda: requests.post(settings.NANO_API_URL, json={**payload, "model": self.model, "webHook": "-1"}, headers=_HEADERS, timeout=30).json()
        )
        return str(resp["data"]["id"])

    async def query(self, upstream_task_id: str) -> ProviderResult:
        resp = await asyncio.to_thread(
            lambda: requests.post(settings.NANO_RESULT_URL, json={"id": upstream_task_id}, headers=_HEADERS, timeout=30).json()
        )
        data = resp.get("data", {})
        status = data.get("status", "")
        if status == "succeeded":
            url = (data.get("results") or [{}])[0].get("url")
            return ProviderResult(is_done=True, is_failed=False, output_url=url, raw_payload=resp)
        if status in ("failed", "error"):
            return ProviderResult(is_done=True, is_failed=True, error=data.get("error"), raw_payload=resp)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=resp)

    def supports_webhook(self) -> bool:
        return False

    def build_submit_payload(self, payload: dict) -> dict:
        return payload

    def parse_callback(self, request_body: dict, headers: dict) -> ProviderResult:
        return ProviderResult(is_done=False, is_failed=False, raw_payload=request_body)
