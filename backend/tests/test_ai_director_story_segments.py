import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import ai_director
from schemas import ParseScriptV2Request


def test_parse_story_segments_v3_uses_task_job_queue(monkeypatch):
    captured = {}
    episode = SimpleNamespace(script_id=42, storyboard_mode="comic", title="第3集")
    script = SimpleNamespace(
        id=42,
        default_storyboard_mode="commentary",
        workflow_settings_json={"default_storyboard_mode": "comic", "profiles": {"commentary": {}, "comic": {}}},
        aspect_ratio="16:9",
        style_preset="默认写实",
    )
    team = SimpleNamespace(id=9)
    member = SimpleNamespace(user_id=88)

    monkeypatch.setattr(ai_director, "decode_id", lambda value: 123)
    monkeypatch.setattr(ai_director, "require_episode_team_access", lambda session, team_obj, episode_id: episode)
    monkeypatch.setattr(ai_director.settings, "DEEPSEEK_API_KEY", "test-key")
    monkeypatch.setattr(ai_director, "_require_split_assets", lambda session, script_id: None)
    monkeypatch.setattr(ai_director.uuid, "uuid4", lambda: "abcdef1234567890")
    monkeypatch.setattr(ai_director, "Script", object())

    def _fake_create_task_job(session, **kwargs):
        captured["kwargs"] = kwargs
        return SimpleNamespace(task_id=kwargs["task_id"], queue_name=kwargs["queue_name"])

    def _fake_enqueue(job):
        captured["enqueued"] = job.task_id
        return True

    session = SimpleNamespace(get=lambda model, script_id: script)
    monkeypatch.setattr(ai_director, "create_task_job", _fake_create_task_job)
    monkeypatch.setattr(ai_director, "enqueue_task_job", _fake_enqueue)

    result = ai_director.parse_story_segments_v3(
        "episode-hash",
        ParseScriptV2Request(text="测试文本", storyboard_mode="commentary"),
        _=member,
        team=team,
        session=session,
    )

    assert result == {"task_id": "abcdef123456", "status": "submitted"}
    assert captured["kwargs"]["task_type"] == "storyboard.parse_v3"
    assert captured["kwargs"]["team_id"] == 9
    assert captured["kwargs"]["user_id"] == 88
    assert captured["kwargs"]["payload"]["storyboard_mode"] == "comic"
    assert captured["kwargs"]["payload"]["team_id"] == 9
    assert captured["kwargs"]["payload"]["user_id"] == 88
    assert captured["enqueued"] == "abcdef123456"


def test_get_parse_story_segments_v3_status_reads_task_job_only(monkeypatch):
    job = SimpleNamespace()
    monkeypatch.setattr(ai_director, "get_task_job", lambda task_id: job)
    monkeypatch.setattr(
        ai_director,
        "serialize_task_job",
        lambda task_job: {
            "legacy_status": "processing",
            "message": "正在规划剧情片段",
            "progress": 12,
            "stage": "planning_segments",
            "result": {"current_segment": 0, "segment_count": 4},
            "error": None,
            "billing": {"actual_cost_cny": 0.0},
            "charged_points": 0,
            "actual_points": 0,
            "actual_cost_cny": 0.0,
            "points_status": "free",
        },
    )

    result = ai_director.get_parse_story_segments_v3_status("task-1")

    assert result["task_id"] == "task-1"
    assert result["status"] == "processing"
    assert result["stage"] == "planning_segments"
    assert result["segment_count"] == 4
