import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.audio_model_registry import (
    ABILITY_NARRATION,
    MINIMAX_MODEL_HD,
    build_audio_catalog,
    normalize_audio_request,
    normalize_minimax_speech_tags,
)
from services.generation_record_service import _build_audio_async_request


def test_normalize_minimax_speech_tags_maps_chinese_aliases_to_provider_tags():
    text = (
        "\u771f\u6b63\u7684\u5371\u9669\u4e0d\u662f\u8ba1\u7b97\u673a\u5f00\u59cb"
        "\u50cf\u4eba\u4e00\u6837\u601d\u8003\uff08\u53f9\u6c14\uff09\uff0c"
        "\u800c\u662f\u4eba\u5f00\u59cb\u50cf\u8ba1\u7b97\u673a\u4e00\u6837\u601d\u8003\u3002"
        "(\u7b11\u58f0)"
    )

    assert normalize_minimax_speech_tags(text, MINIMAX_MODEL_HD) == (
        "\u771f\u6b63\u7684\u5371\u9669\u4e0d\u662f\u8ba1\u7b97\u673a\u5f00\u59cb"
        "\u50cf\u4eba\u4e00\u6837\u601d\u8003(sighs)\uff0c"
        "\u800c\u662f\u4eba\u5f00\u59cb\u50cf\u8ba1\u7b97\u673a\u4e00\u6837\u601d\u8003\u3002"
        "(laughs)"
    )


def test_audio_request_normalization_preserves_real_speech_tags_for_async_narration():
    normalized = normalize_audio_request(
        {
            "ability_type": ABILITY_NARRATION,
            "tier_code": "hd",
            "voice_id": "audiobook_male_1",
            "script_text": "\u4ed6\u8bf4\uff08\u6e05\u55d3\u5b50\uff09\uff1a\u51c6\u5907\u5f00\u59cb\u3002(pant)",
        }
    )

    assert normalized["model_code"] == MINIMAX_MODEL_HD
    assert normalized["script_text"] == "\u4ed6\u8bf4(clear-throat)\uff1a\u51c6\u5907\u5f00\u59cb\u3002(pant)"


def test_audio_catalog_exposes_minimax_text_controls():
    catalog = build_audio_catalog()

    controls = catalog["text_controls"]
    assert MINIMAX_MODEL_HD in controls["speech_tag_models"]
    assert {"value": "(sighs)", "label": "\u53f9\u6c14", "alias": ["\u53f9\u6c14"]} in controls["speech_tags"]
    assert {"value": "<#0.5#>", "label": "0.5s"} in controls["pause_tags"]
    assert any(tier["supports_speech_tags"] for ability in catalog["abilities"] for tier in ability["tiers"])


def test_audio_async_request_uses_minimax_async_sample_rate_field():
    payload = _build_audio_async_request(
        {
            "model_code": MINIMAX_MODEL_HD,
            "voice_id": "audiobook_male_1",
            "audio_format": "mp3",
            "sample_rate": 44100,
            "bitrate": 128000,
            "channel_count": 2,
            "script_text": "hello(sighs)",
            "text_file_url": "",
            "speed": None,
            "volume": None,
            "pitch": None,
            "language_boost": "auto",
        }
    )

    assert payload["audio_setting"]["audio_sample_rate"] == 44100
    assert "sample_rate" not in payload["audio_setting"]
