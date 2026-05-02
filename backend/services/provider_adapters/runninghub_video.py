from __future__ import annotations

from core.config import settings
from . import ProviderResult
from services.runninghub_video_service import RunningHubVideoService

_svc = RunningHubVideoService()


class RunningHubVideoAdapter:
    def __init__(self, model: str = "vidu_q2_pro"):
        self.model = model
        self.provider_key = "runninghub-video"

    async def submit(self, payload: dict) -> str:
        if self.model == "vidu_q3_pro":
            resp = await _svc.generate_vidu_q3_pro(**payload)
        else:
            resp = await _svc.generate_vidu_q2_pro(**payload)
        return resp["taskId"]

    async def query(self, upstream_task_id: str) -> ProviderResult:
        resp = await _svc.query_task(upstream_task_id)
        status = resp.get("status", "")
        if status == "SUCCESS":
            url = (resp.get("results") or [{}])[0].get("url")
            return ProviderResult(is_done=True, is_failed=False, output_url=url, raw_payload=resp)
        if status == "FAILED":
            return ProviderResult(is_done=True, is_failed=True, error=resp.get("errorMessage"), raw_payload=resp)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=resp)

    def supports_webhook(self) -> bool:
        return True

    def build_submit_payload(self, payload: dict) -> dict:
        return payload

    def parse_callback(self, request_body: dict, headers: dict) -> ProviderResult:
        status = str(request_body.get("status") or "").strip().upper()
        if status == "SUCCESS":
            url = (request_body.get("results") or [{}])[0].get("url")
            return ProviderResult(is_done=True, is_failed=False, output_url=url, raw_payload=request_body)
        if status == "FAILED":
            return ProviderResult(is_done=True, is_failed=True, error=request_body.get("errorMessage") or request_body.get("failedReason"), raw_payload=request_body)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=request_body)
