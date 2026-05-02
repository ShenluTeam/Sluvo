from __future__ import annotations

from datetime import datetime
from threading import Lock
from typing import Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


class InMemoryTaskRegistry:
    def __init__(self) -> None:
        self._tasks: Dict[str, dict] = {}
        self._lock = Lock()

    def create(self, task_id: str, **payload) -> dict:
        now = _utc_now_iso()
        data = {
            "task_id": task_id,
            "created_at": payload.get("created_at") or now,
            "updated_at": payload.get("updated_at") or now,
            **payload,
        }
        with self._lock:
            self._tasks[task_id] = data
        return data

    def set(self, task_id: str, payload: dict) -> dict:
        now = _utc_now_iso()
        with self._lock:
            self._tasks[task_id] = {
                "task_id": task_id,
                "created_at": payload.get("created_at") or now,
                "updated_at": payload.get("updated_at") or now,
                **payload,
            }
            return self._tasks[task_id]

    def update(self, task_id: str, **payload) -> Optional[dict]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            task.update(payload)
            task["updated_at"] = payload.get("updated_at") or _utc_now_iso()
            return task

    def get(self, task_id: str) -> Optional[dict]:
        with self._lock:
            task = self._tasks.get(task_id)
            return dict(task) if task else None

    def list(self) -> List[dict]:
        with self._lock:
            return [dict(task) for task in self._tasks.values()]

    def pop(self, task_id: str) -> Optional[dict]:
        with self._lock:
            task = self._tasks.pop(task_id, None)
            return dict(task) if task else None

    def cancel(self, task_id: str, *, msg: Optional[str] = None) -> Optional[dict]:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            if str(task.get("status") or "").lower() in {"completed", "failed", "cancelled"}:
                return dict(task)
            task["status"] = "cancelled"
            task["cancel_requested"] = True
            if msg:
                task["msg"] = msg
            task["updated_at"] = _utc_now_iso()
            return dict(task)

    def is_cancel_requested(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            return bool(task and task.get("cancel_requested"))


video_tasks = InMemoryTaskRegistry()
nano_tasks = InMemoryTaskRegistry()
standalone_tasks = InMemoryTaskRegistry()
parse_tasks = InMemoryTaskRegistry()
parse_tasks_v2 = InMemoryTaskRegistry()
resource_extract_tasks = InMemoryTaskRegistry()
resource_generate_tasks = InMemoryTaskRegistry()
