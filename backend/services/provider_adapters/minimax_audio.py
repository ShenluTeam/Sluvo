from __future__ import annotations

import asyncio
from . import ProviderResult
from services.minimax_audio_service import MiniMaxAudioService

_svc = MiniMaxAudioService()


class MinimaxAudioAdapter:
    provider_key = "minimax-audio"

    async def submit(self, payload: dict) -> str:
        resp = await asyncio.to_thread(_svc.submit_long_narration, payload)
        return str(resp["task_id"])

    async def query(self, upstream_task_id: str) -> ProviderResult:
        resp = await asyncio.to_thread(_svc.query_long_narration, upstream_task_id)
        status = resp.get("status", "")
        if status == "Success":
            url = resp.get("file_id") or resp.get("audio_file")
            return ProviderResult(is_done=True, is_failed=False, output_url=url, raw_payload=resp)
        if status in ("Failed", "Expired"):
            return ProviderResult(is_done=True, is_failed=True, error=resp.get("base_resp", {}).get("status_msg"), raw_payload=resp)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=resp)

    def supports_webhook(self) -> bool:
        return False

    def build_submit_payload(self, payload: dict) -> dict:
        return payload

    def parse_callback(self, request_body: dict, headers: dict) -> ProviderResult:
        return ProviderResult(is_done=False, is_failed=False, raw_payload=request_body)
