import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agent_stage_service import build_creative_stage_read_model, get_next_stage_after_action


class _FakeResult:
    def __init__(self, items):
        self._items = list(items)

    def all(self):
        return list(self._items)

    def first(self):
        return self._items[0] if self._items else None


class _FakeSession:
    def __init__(self, *, script, episode=None, resources=None, panels=None):
        self.script = script
        self.episode = episode
        self.resources = list(resources or [])
        self.panels = list(panels or [])

    def get(self, model, object_id):
        model_name = getattr(model, "__name__", "")
        if model_name == "Script":
            return self.script if self.script and self.script.id == object_id else None
        if model_name == "Episode":
            return self.episode if self.episode and self.episode.id == object_id else None
        return None

    def exec(self, statement):
        lowered = str(statement).lower()
        if "from episode" in lowered:
            return _FakeResult([self.episode] if self.episode else [])
        if "from sharedresource" in lowered:
            return _FakeResult(self.resources)
        if "from panel" in lowered:
            return _FakeResult(self.panels)
        return _FakeResult([])


def test_stage_script_empty_maps_to_director_agent():
    script = SimpleNamespace(id=1, name="测试项目", source_text="")
    episode = SimpleNamespace(id=10, title="第1集", source_text="")
    session = _FakeSession(script=script, episode=episode, resources=[], panels=[])
    result = build_creative_stage_read_model(session, script_id=1, episode_id=10)
    assert result["creative_stage"] == "script_empty"
    assert result["active_agent"] == "director_agent"


def test_stage_storyboard_pending_maps_to_storyboard_agent():
    script = SimpleNamespace(id=1, name="测试项目", source_text="主角回到旧宅。")
    episode = SimpleNamespace(id=10, title="第1集", source_text="主角回到旧宅。")
    resources = [
        SimpleNamespace(id=1, resource_type="character", file_url="https://example.com/char.png"),
        SimpleNamespace(id=2, resource_type="scene", file_url="https://example.com/scene.png"),
    ]
    session = _FakeSession(script=script, episode=episode, resources=resources, panels=[])
    result = build_creative_stage_read_model(session, script_id=1, episode_id=10)
    assert result["creative_stage"] == "storyboard_pending"
    assert result["active_agent"] == "storyboard_agent"


def test_action_stage_transition_rules():
    assert get_next_stage_after_action(action_type="save_script", current_stage="script_empty") == "assets_pending"
    assert get_next_stage_after_action(action_type="save_assets", current_stage="assets_pending") == "assets_ready"
    assert get_next_stage_after_action(action_type="save_storyboard", current_stage="storyboard_pending") == "storyboard_ready"
    assert get_next_stage_after_action(action_type="generate_video", current_stage="images_ready") == "videos_pending"
