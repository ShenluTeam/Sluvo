import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.security import encode_id
from routers import panel


def test_normalize_entity_bindings_decodes_hash_asset_ids():
    resource_id = 123
    bindings = {
        "scenes": [{"name": "教室", "asset_id": encode_id(resource_id), "match_type": "manual"}],
        "characters": [{"name": "罗峰", "asset_id": resource_id}],
        "props": [{"name": "粉笔", "asset_id": str(resource_id)}],
        "binding_status": "manual_fixed",
    }

    normalized = panel._normalize_entity_bindings_asset_ids(bindings)

    assert normalized["scenes"][0]["asset_id"] == resource_id
    assert normalized["characters"][0]["asset_id"] == resource_id
    assert normalized["props"][0]["asset_id"] == resource_id
    assert normalized["binding_status"] == "manual_fixed"


def test_build_refs_falls_back_to_binding_names():
    class DummyPanel:
        scene = ""
        character = ""
        prop = ""
        entity_bindings_json = (
            '{"scenes":[{"name":"教室"}],'
            '"characters":[{"name":"罗峰"}],'
            '"props":[{"name":"粉笔"}]}'
        )

    assert panel._build_refs(DummyPanel()) == (["教室"], ["罗峰"], ["粉笔"])
