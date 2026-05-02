from __future__ import annotations

import asyncio
import requests
import re
from typing import Any

from core.config import settings
from . import ProviderResult

_HEADERS = {"Content-Type": "application/json", "Authorization": f"Bearer {settings.RUNNINGHUB_API_KEY}"}
_QUERY_URL = "https://www.runninghub.cn/openapi/v2/query"

_CHANNEL_MAP = {
    "rh-v2-text2img": "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash/text-to-image",
    "rh-v2-img2img": "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash/image-to-image",
    "rh-v2-official-text2img": "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash-official/text-to-image",
    "rh-v2-official-img2img": "https://www.runninghub.cn/openapi/v2/rhart-image-n-g31-flash-official/image-to-image",
}


def _safe_response_dict(resp: requests.Response) -> dict:
    try:
        data = resp.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"data": data}
    try:
        text = resp.text or ""
    except Exception:
        text = ""
    return {"_raw_text": text}


def _extract_first_http_url(value: str) -> str:
    match = re.search(r"https?://[^\s\"']+", value or "")
    return match.group(0) if match else ""


def _extract_output_url(data: dict) -> str:
    candidates = []
    if isinstance(data.get("results"), list):
        candidates.append(data.get("results"))
    nested = data.get("data")
    if isinstance(nested, dict) and isinstance(nested.get("results"), list):
        candidates.append(nested.get("results"))
    for results in candidates:
        for item in results or []:
            if not isinstance(item, dict):
                continue
            for key in ("url", "fileUrl", "download_url"):
                candidate = str(item.get(key) or "").strip()
                if candidate:
                    return candidate
            candidate = _extract_first_http_url(str(item.get("text") or ""))
            if candidate:
                return candidate
    raw_text = str(data.get("_raw_text") or "").strip()
    return _extract_first_http_url(raw_text)


def _extract_status(data: dict) -> str:
    status = str(data.get("status") or "").strip()
    if status:
        return status.upper()
    nested = data.get("data")
    if isinstance(nested, dict):
        nested_status = str(nested.get("status") or nested.get("taskStatus") or "").strip()
        if nested_status:
            return nested_status.upper()
    raw_text = str(data.get("_raw_text") or "")
    match = re.search(r'"status"\s*:\s*"([A-Za-z_]+)"', raw_text)
    return str(match.group(1) or "").upper() if match else ""


def _extract_error(data: dict) -> str:
    for key in ("errorMessage", "failedReason", "message"):
        value = str(data.get(key) or "").strip()
        if value:
            return value
    nested = data.get("data")
    if isinstance(nested, dict):
        for key in ("errorMessage", "failedReason", "message"):
            value = str(nested.get(key) or "").strip()
            if value:
                return value
    return str(data.get("_raw_text") or "").strip()[:300]


class RunningHubImageAdapter:
    def __init__(self, channel: str = "rh-v2-text2img"):
        self.channel = channel
        self.provider_key = "runninghub-image"

    async def submit(self, payload: dict) -> str:
        url = _CHANNEL_MAP[self.channel]
        resp = await asyncio.to_thread(
            lambda: requests.post(url, json=payload, headers=_HEADERS, timeout=30)
        )
        data = _safe_response_dict(resp)
        task_id = str(data.get("taskId") or "")
        if task_id:
            return task_id
        raise RuntimeError(_extract_error(data) or "RunningHub 未返回 taskId")

    async def query(self, upstream_task_id: str) -> ProviderResult:
        response = await asyncio.to_thread(
            lambda: requests.post(_QUERY_URL, json={"taskId": upstream_task_id}, headers=_HEADERS, timeout=30)
        )
        resp = _safe_response_dict(response)
        status = _extract_status(resp)
        if status == "SUCCESS":
            url = _extract_output_url(resp)
            return ProviderResult(is_done=True, is_failed=False, output_url=url, raw_payload=resp)
        if status == "FAILED":
            return ProviderResult(is_done=True, is_failed=True, error=_extract_error(resp), raw_payload=resp)
        url = _extract_output_url(resp)
        if url:
            return ProviderResult(is_done=True, is_failed=False, output_url=url, raw_payload=resp)
        if not response.ok:
            return ProviderResult(is_done=True, is_failed=True, error=_extract_error(resp) or "RunningHub 查询失败", raw_payload=resp)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=resp)

    def supports_webhook(self) -> bool:
        return True

    def build_submit_payload(self, payload: dict) -> dict:
        next_payload = dict(payload or {})
        webhook_url = str(next_payload.pop("webhook_url", "") or "").strip()
        if webhook_url:
            next_payload["webhookUrl"] = webhook_url
        return next_payload

    def parse_callback(self, request_body: dict, headers: dict) -> ProviderResult:
        status = _extract_status(request_body)
        if status == "SUCCESS":
            url = _extract_output_url(request_body)
            return ProviderResult(is_done=True, is_failed=False, output_url=url or None, raw_payload=request_body)
        if status == "FAILED":
            return ProviderResult(is_done=True, is_failed=True, error=_extract_error(request_body), raw_payload=request_body)
        url = _extract_output_url(request_body)
        if url:
            return ProviderResult(is_done=True, is_failed=False, output_url=url, raw_payload=request_body)
        return ProviderResult(is_done=False, is_failed=False, raw_payload=request_body)
