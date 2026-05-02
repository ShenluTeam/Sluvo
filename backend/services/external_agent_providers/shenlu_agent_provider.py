from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import requests
from fastapi import HTTPException

from core.config import settings
from schemas import EXTERNAL_PROVIDER_SHENLU_AGENT
from services.external_agent_providers.base import ExternalAgentProvider


class ShenluAgentProvider(ExternalAgentProvider):
    provider_key = EXTERNAL_PROVIDER_SHENLU_AGENT

    def __init__(self) -> None:
        configured_base_url = settings.SHENLU_AGENT_API_BASE_URL.rstrip("/")
        if configured_base_url.endswith("zopia.ai") or "://zopia.ai" in configured_base_url:
            configured_base_url = "https://ai.shenlu.top"
        self.base_url = configured_base_url
        self.local_stub_mode = bool(settings.SHENLU_AGENT_LOCAL_STUB_MODE)

    def _headers(self, token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, token: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(method, url, headers=self._headers(token), timeout=180, **kwargs)
        except requests.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"AI导演助理服务不可用: {exc}")

        try:
            payload = response.json()
        except Exception:
            payload = {"raw_text": (response.text or "")[:500]}

        if response.status_code >= 400:
            detail = payload.get("message") or payload.get("detail") or payload.get("error") or "AI导演助理调用失败"
            raise HTTPException(status_code=response.status_code, detail=detail)
        return payload

    def _is_missing_endpoint(self, exc: HTTPException) -> bool:
        return int(getattr(exc, "status_code", 0) or 0) == 404

    def _fallback_base_id(self) -> str:
        return f"base_{uuid.uuid4().hex[:12]}"

    def _fallback_episode_id(self) -> str:
        return f"episode_{uuid.uuid4().hex[:12]}"

    def _fallback_session_id(self) -> str:
        return f"session_{uuid.uuid4().hex[:16]}"

    def create_project(self, token: str, *, name: Optional[str]) -> Dict[str, Any]:
        if self.local_stub_mode:
            base_id = self._fallback_base_id()
            episode_id = self._fallback_episode_id()
            return {
                "base_id": base_id,
                "base_name": name or "未命名项目",
                "provider_episode_id": episode_id,
                "raw": {
                    "success": True,
                    "fallback_mode": "local_stub",
                    "data": {
                        "baseId": base_id,
                        "baseName": name or "未命名项目",
                        "episodeId": episode_id,
                    },
                },
            }
        try:
            payload = self._request("POST", "/api/base/create", token, json={"baseName": name} if name else {})
            data = payload.get("data") or {}
            return {
                "base_id": data.get("baseId") or "",
                "base_name": data.get("baseName") or name or "",
                "provider_episode_id": data.get("episodeId") or "",
                "raw": payload,
            }
        except HTTPException as exc:
            if not self._is_missing_endpoint(exc):
                raise
            base_id = self._fallback_base_id()
            episode_id = self._fallback_episode_id()
            return {
                "base_id": base_id,
                "base_name": name or "未命名项目",
                "provider_episode_id": episode_id,
                "raw": {
                    "success": True,
                    "fallback_mode": "local_stub",
                    "data": {
                        "baseId": base_id,
                        "baseName": name or "未命名项目",
                        "episodeId": episode_id,
                    },
                },
            }

    def save_settings(self, token: str, *, base_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        if self.local_stub_mode:
            return settings
        try:
            payload = self._request("POST", "/api/base/settings", token, json={"base_id": base_id, "settings": settings})
            return payload.get("settings") or settings
        except HTTPException as exc:
            if not self._is_missing_endpoint(exc):
                raise
            return settings

    def get_settings(self, token: str, *, base_id: str) -> Dict[str, Any]:
        if self.local_stub_mode:
            return {}
        try:
            payload = self._request("GET", f"/api/base/settings?base_id={base_id}", token)
            return payload.get("settings") or {}
        except HTTPException as exc:
            if not self._is_missing_endpoint(exc):
                raise
            return {}

    def chat(
        self,
        token: str,
        *,
        base_id: str,
        provider_episode_id: str,
        message: str,
        session_id: Optional[str],
    ) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "base_id": base_id,
            "episode_id": provider_episode_id,
            "message": message,
        }
        if session_id:
            body["session_id"] = session_id
        if self.local_stub_mode:
            next_session_id = session_id or self._fallback_session_id()
            return {
                "session_id": next_session_id,
                "reply": {
                    "agent": "shenlu_agent",
                    "text": "当前环境正在使用神鹿本地 OpenClaw 联调模式，已保留项目与剧集绑定。后续可继续推进 settings、剧集管理和工作区接入。",
                },
                "actions": [],
                "workspace": {"files": []},
                "base_id": base_id,
                "base_url": "",
                "raw": {"success": True, "fallback_mode": "local_stub", "request": body},
            }
        try:
            payload = self._request("POST", "/api/v1/agent/chat", token, json=body)
            return {
                "session_id": payload.get("session_id") or session_id or "",
                "reply": payload.get("reply") or {},
                "actions": payload.get("actions") or [],
                "workspace": payload.get("workspace") or {},
                "base_id": payload.get("base_id") or base_id,
                "base_url": payload.get("base_url") or "",
                "raw": payload,
            }
        except HTTPException as exc:
            if not self._is_missing_endpoint(exc):
                raise
            next_session_id = session_id or self._fallback_session_id()
            return {
                "session_id": next_session_id,
                "reply": {
                    "agent": "shenlu_agent",
                    "text": "当前环境未接入独立 Agent 对话服务，已保留项目与剧集绑定。你可以先继续保存设置、管理剧集，后续再接入完整对话能力。",
                },
                "actions": [],
                "workspace": {"files": []},
                "base_id": base_id,
                "base_url": "",
                "raw": {"success": True, "fallback_mode": "local_stub"},
            }

    def get_project_detail(self, token: str, *, base_id: str, provider_episode_id: str) -> Dict[str, Any]:
        if self.local_stub_mode:
            return {"success": True, "workspace": {"files": []}}
        try:
            payload = self._request("GET", f"/api/base/{base_id}?episode_id={provider_episode_id}", token)
            return payload or {}
        except HTTPException as exc:
            if not self._is_missing_endpoint(exc):
                raise
            return {"success": True, "workspace": {"files": []}}

    def list_episodes(self, token: str, *, base_id: str) -> List[Dict[str, Any]]:
        if self.local_stub_mode:
            return []
        try:
            payload = self._request("GET", f"/api/episode/list?base_id={base_id}", token)
            return (payload.get("data") or []) if isinstance(payload, dict) else []
        except HTTPException as exc:
            if not self._is_missing_endpoint(exc):
                raise
            return []

    def create_episode(self, token: str, *, base_id: str) -> Dict[str, Any]:
        if self.local_stub_mode:
            episode_id = self._fallback_episode_id()
            return {
                "provider_episode_id": episode_id,
                "name": "",
                "order": "",
                "raw": {"success": True, "fallback_mode": "local_stub", "data": {"episode": {"id": episode_id}}},
            }
        try:
            payload = self._request("POST", f"/api/episode/create?base_id={base_id}", token)
            data = payload.get("data") or {}
            episode = data.get("episode") or {}
            return {
                "provider_episode_id": episode.get("id") or "",
                "name": episode.get("name") or "",
                "order": episode.get("order") or "",
                "raw": payload,
            }
        except HTTPException as exc:
            if not self._is_missing_endpoint(exc):
                raise
            episode_id = self._fallback_episode_id()
            return {
                "provider_episode_id": episode_id,
                "name": "",
                "order": "",
                "raw": {"success": True, "fallback_mode": "local_stub", "data": {"episode": {"id": episode_id}}},
            }

    def get_balance(self, token: str) -> Dict[str, Any]:
        if self.local_stub_mode:
            return {
                "accounts": [],
                "summary": {
                    "status": "local_stub",
                    "message": "当前环境未接入独立额度查询服务",
                },
            }
        try:
            payload = self._request("GET", "/api/billing/getBalance", token)
            return payload if isinstance(payload, dict) else {}
        except HTTPException as exc:
            if not self._is_missing_endpoint(exc):
                raise
            return {
                "accounts": [],
                "summary": {
                    "status": "unavailable",
                    "message": "当前环境未接入独立额度查询服务",
                },
            }

    def list_workspace_files(
        self,
        token: str,
        *,
        base_id: str,
        provider_episode_id: str,
        workspace_snapshot: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        files = ((workspace_snapshot or {}).get("files") or [])
        if files:
            return files
        detail = self.get_project_detail(token, base_id=base_id, provider_episode_id=provider_episode_id)
        return ((detail.get("workspace") or {}).get("files") or [])
