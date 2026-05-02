from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, Tuple


logger = logging.getLogger(__name__)

DEEPSEEK_V4_FLASH_MODEL = "deepseek-v4-flash"
LEGACY_CHAT_MODEL = "deepseek-chat"
LEGACY_REASONER_MODEL = "deepseek-reasoner"

INPUT_CACHE_HIT_CNY_PER_MTOKEN = Decimal("0.2")
INPUT_CACHE_MISS_CNY_PER_MTOKEN = Decimal("1")
OUTPUT_CNY_PER_MTOKEN = Decimal("2")


def normalize_deepseek_model(model: Any, *, thinking_enabled: bool = False) -> Tuple[str, bool]:
    raw_model = str(model or "").strip()
    normalized = raw_model.lower()
    requested_thinking = bool(thinking_enabled)

    if normalized == LEGACY_CHAT_MODEL:
        logger.warning("%s is deprecated; using %s with thinking disabled", LEGACY_CHAT_MODEL, DEEPSEEK_V4_FLASH_MODEL)
        return DEEPSEEK_V4_FLASH_MODEL, False
    if normalized == LEGACY_REASONER_MODEL:
        logger.warning("%s is deprecated; using %s with thinking enabled", LEGACY_REASONER_MODEL, DEEPSEEK_V4_FLASH_MODEL)
        return DEEPSEEK_V4_FLASH_MODEL, True
    if normalized.startswith("deepseek-"):
        if normalized != DEEPSEEK_V4_FLASH_MODEL:
            logger.warning("%s is not part of the default Shenlu V4 flash policy; using %s", raw_model, DEEPSEEK_V4_FLASH_MODEL)
        return DEEPSEEK_V4_FLASH_MODEL, requested_thinking
    return DEEPSEEK_V4_FLASH_MODEL, requested_thinking


def deepseek_extra_body(*, thinking_enabled: bool, existing: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        **dict(existing or {}),
        "thinking": {"type": "enabled" if thinking_enabled else "disabled"},
    }


def normalize_deepseek_request_kwargs(request_kwargs: Dict[str, Any], *, thinking_enabled: bool = False) -> Dict[str, Any]:
    model, enabled = normalize_deepseek_model(request_kwargs.get("model"), thinking_enabled=thinking_enabled)
    normalized = dict(request_kwargs)
    normalized["model"] = model
    normalized["extra_body"] = deepseek_extra_body(
        thinking_enabled=enabled,
        existing=normalized.get("extra_body") if isinstance(normalized.get("extra_body"), dict) else None,
    )
    return normalized


def calculate_deepseek_v4_flash_usage_cost_cny(usage: Dict[str, int]) -> Decimal:
    hit_tokens = int(usage.get("prompt_cache_hit_tokens") or 0)
    miss_tokens = int(usage.get("prompt_cache_miss_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    return (
        (Decimal(hit_tokens) / Decimal(1_000_000)) * INPUT_CACHE_HIT_CNY_PER_MTOKEN
        + (Decimal(miss_tokens) / Decimal(1_000_000)) * INPUT_CACHE_MISS_CNY_PER_MTOKEN
        + (Decimal(completion_tokens) / Decimal(1_000_000)) * OUTPUT_CNY_PER_MTOKEN
    )
