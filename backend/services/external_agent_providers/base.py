from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class ExternalAgentProvider(ABC):
    provider_key: str

    @abstractmethod
    def create_project(self, token: str, *, name: Optional[str]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def save_settings(self, token: str, *, base_id: str, settings: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_settings(self, token: str, *, base_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def chat(
        self,
        token: str,
        *,
        base_id: str,
        provider_episode_id: str,
        message: str,
        session_id: Optional[str],
    ) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get_project_detail(self, token: str, *, base_id: str, provider_episode_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def list_workspace_files(
        self,
        token: str,
        *,
        base_id: str,
        provider_episode_id: str,
        workspace_snapshot: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError
