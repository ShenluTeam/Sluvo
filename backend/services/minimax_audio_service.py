from __future__ import annotations

import base64
import binascii
import json
from typing import Any, Dict, Optional

import requests

from core.config import settings


class MiniMaxAudioService:
    def __init__(self) -> None:
        self.base_url = "https://api.minimaxi.com"

    def _headers(self) -> Dict[str, str]:
        if not settings.MINIMAX_API_KEY:
            raise RuntimeError("MINIMAX_API_KEY not configured")
        return {
            "Authorization": "Bearer {0}".format(settings.MINIMAX_API_KEY),
            "Content-Type": "application/json",
        }

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        response = requests.request(
            method,
            "{0}{1}".format(self.base_url, path),
            headers=self._headers(),
            json=json_body,
            params=params,
            timeout=timeout,
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw_text": response.text[:500]}
        if not response.ok:
            raise RuntimeError(json.dumps(data, ensure_ascii=False))
        base_resp = data.get("base_resp") if isinstance(data, dict) else None
        if isinstance(base_resp, dict) and int(base_resp.get("status_code") or 0) != 0:
            raise RuntimeError(json.dumps(data, ensure_ascii=False))
        return data

    def upload_file(self, *, content: bytes, filename: str, purpose: str = "voice_clone") -> Dict[str, Any]:
        if not settings.MINIMAX_API_KEY:
            raise RuntimeError("MINIMAX_API_KEY not configured")
        files = {"file": (filename, content)}
        data = {"purpose": purpose}
        response = requests.post(
            "{0}/v1/files/upload".format(self.base_url),
            headers={"Authorization": "Bearer {0}".format(settings.MINIMAX_API_KEY)},
            files=files,
            data=data,
            timeout=120,
        )
        try:
            payload = response.json()
        except Exception:
            payload = {"raw_text": response.text[:500]}
        if not response.ok:
            raise RuntimeError(json.dumps(payload, ensure_ascii=False))
        base_resp = payload.get("base_resp") if isinstance(payload, dict) else None
        if isinstance(base_resp, dict) and int(base_resp.get("status_code") or 0) != 0:
            raise RuntimeError(json.dumps(payload, ensure_ascii=False))
        return payload

    def retrieve_file_content(self, file_id: str) -> bytes:
        if not settings.MINIMAX_API_KEY:
            raise RuntimeError("MINIMAX_API_KEY not configured")
        response = requests.get(
            "{0}/v1/files/retrieve_content".format(self.base_url),
            headers={"Authorization": "Bearer {0}".format(settings.MINIMAX_API_KEY)},
            params={"file_id": file_id},
            timeout=120,
        )
        response.raise_for_status()
        return response.content

    def synthesize_realtime(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json("POST", "/v1/t2a_v2", json_body=payload, timeout=180)

    def submit_long_narration(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json("POST", "/v1/t2a_async_v2", json_body=payload, timeout=180)

    def query_long_narration(self, task_id: str) -> Dict[str, Any]:
        return self._request_json(
            "GET",
            "/v1/query/t2a_async_query_v2",
            params={"task_id": task_id},
            timeout=60,
        )

    def design_voice(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json("POST", "/v1/voice_design", json_body=payload, timeout=180)

    def clone_voice(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return self._request_json("POST", "/v1/voice_clone", json_body=payload, timeout=180)

    def get_voices(self, voice_type: str = "all") -> Dict[str, Any]:
        return self._request_json("POST", "/v1/get_voice", json_body={"voice_type": voice_type}, timeout=60)

    def delete_voice(self, *, voice_type: str, voice_id: str) -> Dict[str, Any]:
        return self._request_json(
            "POST",
            "/v1/delete_voice",
            json_body={"voice_type": voice_type, "voice_id": voice_id},
            timeout=60,
        )


def decode_hex_audio(data: str) -> bytes:
    source = str(data or "").strip()
    if not source:
        return b""
    try:
        return bytes.fromhex(source)
    except ValueError:
        pass
    if "," in source:
        source = source.split(",", 1)[1]
    try:
        return base64.b64decode(source, validate=True)
    except (ValueError, binascii.Error):
        return b""


minimax_audio_service = MiniMaxAudioService()
