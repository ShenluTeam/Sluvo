from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, runtime_checkable


@dataclass
class ProviderResult:
    is_done: bool
    is_failed: bool
    output_url: Optional[str] = None
    error: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = None


@runtime_checkable
class ProviderAdapter(Protocol):
    async def submit(self, payload: dict) -> str: ...
    async def query(self, upstream_task_id: str) -> ProviderResult: ...
    def supports_webhook(self) -> bool: ...
    def build_submit_payload(self, payload: dict) -> dict: ...
    def parse_callback(self, request_body: Dict[str, Any], headers: Dict[str, Any]) -> ProviderResult: ...
