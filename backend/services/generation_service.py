from __future__ import annotations

from services.task_registry import nano_tasks, parse_tasks, standalone_tasks, video_tasks


def create_video_task(task_id: str) -> dict:
    return video_tasks.create(task_id, status="processing", url="", progress=0, error="")


def update_video_task(task_id: str, **payload) -> dict | None:
    return video_tasks.update(task_id, **payload)


def get_video_task(task_id: str) -> dict | None:
    return video_tasks.get(task_id)


def pop_video_task(task_id: str) -> dict | None:
    return video_tasks.pop(task_id)


def get_nano_task(task_id: str) -> dict | None:
    return nano_tasks.get(task_id)


def pop_nano_task(task_id: str) -> dict | None:
    return nano_tasks.pop(task_id)


def get_standalone_task(task_id: str) -> dict | None:
    return standalone_tasks.get(task_id)


def pop_standalone_task(task_id: str) -> dict | None:
    return standalone_tasks.pop(task_id)


def get_parse_task(task_id: str) -> dict | None:
    return parse_tasks.get(task_id)
