import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import storyboard_task_service


def test_run_parse_story_segments_v3_task_falls_back_to_job_context(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        storyboard_task_service,
        "get_task_job",
        lambda task_id: SimpleNamespace(user_id=88, team_id=9),
    )
    monkeypatch.setattr(
        storyboard_task_service,
        "run_storyboard_split_runtime",
        lambda **kwargs: captured.update(kwargs),
    )

    storyboard_task_service.run_parse_story_segments_v3_task(
        "task-1",
        {
            "episode_id": 123,
            "text": "测试剧本文本",
            "storyboard_mode": "comic",
        },
    )

    assert captured["task_id"] == "task-1"
    assert captured["episode_id"] == 123
    assert captured["user_id"] == 88
    assert captured["team_id"] == 9
