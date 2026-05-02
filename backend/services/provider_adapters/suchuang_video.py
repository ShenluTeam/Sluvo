from __future__ import annotations

from . import ProviderResult
from services.suchuang_video_service import SuChuangVideoService

_svc = SuChuangVideoService()


class SuchuangVideoAdapter:
    def __init__(self, model: str = "veo3_1_pro"):
        self.model = model
        self.provider_key = "suchuang-video"

    async def submit(self, payload: dict) -> str:
        if self.model == "veo3_1_fast":
            resp = await _svc.generate_veo3_1_fast(**payload)
        else:
            resp = await _svc.generate_veo3_1_pro(**payload)
        return str(resp["data"]["id"])

    async def query(self, upstream_task_id: str) -> ProviderResult:
        resp = await _svc.query_task(upstream_task_id)
        data = resp.get("data", {})
        status = data.get("status", 0)
        if status == 2:
            url = data.get("url") or data.get("videoUrl")
            return ProviderResult(is_done=True, is_failed=False, output_url=url, raw_payload=resp)
        if status == 3:
            return ProviderResult(is_done=True, is_failed=True, error=data.get("message"), raw_payload=resp)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=resp)

    def supports_webhook(self) -> bool:
        return False

    def build_submit_payload(self, payload: dict) -> dict:
        return payload

    def parse_callback(self, request_body: dict, headers: dict) -> ProviderResult:
        return ProviderResult(is_done=False, is_failed=False, raw_payload=request_body)
