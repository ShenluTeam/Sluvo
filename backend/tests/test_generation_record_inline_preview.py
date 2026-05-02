import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from models import GenerationRecord
from services.generation_record_service import serialize_generation_record


def test_serialize_generation_record_uses_inline_preview_cache(monkeypatch):
    monkeypatch.setattr(
        "services.generation_record_service._get_inline_preview_cache",
        lambda record_id: "data:image/png;base64,AAAA" if record_id == 1 else None,
    )

    record = GenerationRecord(
        id=1,
        user_id=1,
        team_id=1,
        record_type="image",
        ownership_mode="standalone",
        status="completed",
        preview_url="",
        thumbnail_url="",
        prompt="test",
        params_internal_json="{}",
        params_public_json="{}",
    )

    session = SimpleNamespace(get=lambda *args, **kwargs: None)
    payload = serialize_generation_record(session, record)
    assert payload["preview_url"] == "data:image/png;base64,AAAA"
