from __future__ import annotations

import json
import re
from typing import Any, Iterable

from sqlmodel import Session, select

from models import ResourceTypeEnum, SharedResource


def _normalize_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("，", ",")
    text = re.sub(r"\s+", "", text)
    return text


def _load_aliases(raw: Any | None) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set)):
        return [str(item).strip() for item in raw if str(item).strip()]
    if not isinstance(raw, str):
        raw = str(raw)
    raw = raw.strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass
    parts = [item.strip() for item in re.split(r"[,\|/、]+", raw) if item.strip()]
    return parts


def _build_resource_index(resources: Iterable[SharedResource]) -> list[dict[str, Any]]:
    indexed: list[dict[str, Any]] = []
    for res in resources:
        name = (res.name or "").strip()
        aliases = _load_aliases(getattr(res, "aliases", None))
        indexed.append(
            {
                "id": res.id,
                "name": name,
                "name_key": _normalize_key(name),
                "aliases": aliases,
                "alias_keys": {_normalize_key(a) for a in aliases if a},
                "created_at": res.created_at,
            }
        )
    indexed.sort(key=lambda item: (item["created_at"], item["id"]))
    return indexed


def _match_one(name: str, resources: list[dict[str, Any]]) -> dict[str, Any]:
    key = _normalize_key(name)
    if not key:
        return {"name": name, "asset_id": None, "match_type": "unmatched"}

    for res in resources:
        if key == res["name_key"]:
            return {"name": name, "asset_id": res["id"], "match_type": "exact"}

    for res in resources:
        if key in res["alias_keys"]:
            return {"name": name, "asset_id": res["id"], "match_type": "alias"}

    best = None
    best_score = -1
    for res in resources:
        res_key = res["name_key"]
        if not res_key:
            continue
        if key in res_key or res_key in key:
            score = max(len(res_key), len(key))
            if score > best_score:
                best_score = score
                best = res
    if best:
        return {"name": name, "asset_id": best["id"], "match_type": "fuzzy"}

    return {"name": name, "asset_id": None, "match_type": "unmatched"}


def _binding_status(items: list[dict[str, Any]], *, has_refs: bool) -> str:
    if not has_refs:
        return "unmatched"
    matched = [item for item in items if item.get("asset_id")]
    if matched and len(matched) == len(items):
        return "auto_matched"
    if matched:
        return "partial_matched"
    return "unmatched"


def bind_assets(
    session: Session,
    *,
    script_id: int,
    scene_refs: list[str],
    character_refs: list[str],
    prop_refs: list[str],
) -> dict[str, Any]:
    resources = session.exec(
        select(SharedResource).where(
            SharedResource.script_id == script_id,
            SharedResource.resource_type.in_(
                [
                    ResourceTypeEnum.SCENE_REF.value,
                    ResourceTypeEnum.CHARACTER_REF.value,
                    ResourceTypeEnum.PROP_REF.value,
                    ResourceTypeEnum.SCENE_REF,
                    ResourceTypeEnum.CHARACTER_REF,
                    ResourceTypeEnum.PROP_REF,
                ]
            ),
        )
    ).all()

    scenes = _build_resource_index([r for r in resources if str(r.resource_type) in {"scene", "SCENE_REF"}])
    characters = _build_resource_index([r for r in resources if str(r.resource_type) in {"character", "CHARACTER_REF"}])
    props = _build_resource_index([r for r in resources if str(r.resource_type) in {"prop", "PROP_REF"}])

    scene_items = [_match_one(name, scenes) for name in scene_refs]
    character_items = [_match_one(name, characters) for name in character_refs]
    prop_items = [_match_one(name, props) for name in prop_refs]

    has_refs = bool(scene_refs or character_refs or prop_refs)
    combined = scene_items + character_items + prop_items
    status = _binding_status(combined, has_refs=has_refs)

    return {
        "scenes": scene_items,
        "characters": character_items,
        "props": prop_items,
        "binding_status": status,
    }
