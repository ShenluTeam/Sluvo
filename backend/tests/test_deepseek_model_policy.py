import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.deepseek_model_policy import calculate_deepseek_v4_flash_usage_cost_cny, normalize_deepseek_request_kwargs


def test_deepseek_v4_flash_usage_cost_uses_flash_rates():
    cost = calculate_deepseek_v4_flash_usage_cost_cny(
        {
            "prompt_cache_hit_tokens": 1_000_000,
            "prompt_cache_miss_tokens": 1_000_000,
            "completion_tokens": 1_000_000,
        }
    )

    assert cost == Decimal("3.2")


def test_normalize_deepseek_request_kwargs_maps_legacy_chat_to_flash_without_thinking():
    request = normalize_deepseek_request_kwargs(
        {"model": "deepseek-chat", "messages": []},
        thinking_enabled=True,
    )

    assert request["model"] == "deepseek-v4-flash"
    assert request["extra_body"]["thinking"]["type"] == "disabled"


def test_normalize_deepseek_request_kwargs_maps_legacy_reasoner_to_flash_with_thinking():
    request = normalize_deepseek_request_kwargs(
        {"model": "deepseek-reasoner", "messages": []},
        thinking_enabled=False,
    )

    assert request["model"] == "deepseek-v4-flash"
    assert request["extra_body"]["thinking"]["type"] == "enabled"
