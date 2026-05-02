from __future__ import annotations

from typing import Any, Callable, Dict, Type

from services.provider_adapters.runninghub_image import RunningHubImageAdapter
from services.provider_adapters.grsai_image import GrsaiImageAdapter
from services.provider_adapters.suchuang_image import SuchuangImageAdapter
from services.provider_adapters.runninghub_video import RunningHubVideoAdapter
from services.provider_adapters.suchuang_video import SuchuangVideoAdapter
from services.provider_adapters.minimax_audio import MinimaxAudioAdapter


def _estimate_fixed(points: int) -> Callable[[dict], int]:
    return lambda _: points


# model_code -> {adapter_cls, adapter_kwargs, queue, task_type, task_category, estimate_fn, completion_mode, provider_key}
MODEL_REGISTRY: Dict[str, Dict[str, Any]] = {
    # --- image ---
    "rh-v2-text2img": {
        "adapter_cls": RunningHubImageAdapter,
        "adapter_kwargs": {"channel": "rh-v2-text2img"},
        "queue": "media",
        "task_type": "gen.image",
        "task_category": "media",
        "estimate_fn": _estimate_fixed(10),
        "completion_mode": "webhook",
        "provider_key": "runninghub-image",
    },
    "rh-v2-official-text2img": {
        "adapter_cls": RunningHubImageAdapter,
        "adapter_kwargs": {"channel": "rh-v2-official-text2img"},
        "queue": "media",
        "task_type": "gen.image",
        "task_category": "media",
        "estimate_fn": _estimate_fixed(10),
        "completion_mode": "webhook",
        "provider_key": "runninghub-image",
    },
    "grsai-flux": {
        "adapter_cls": GrsaiImageAdapter,
        "adapter_kwargs": {"model": "flux-kontext-pro"},
        "queue": "media",
        "task_type": "gen.image",
        "task_category": "media",
        "estimate_fn": _estimate_fixed(8),
        "completion_mode": "poll",
        "provider_key": "grsai-image",
    },
    "suchuang-nb-pro": {
        "adapter_cls": SuchuangImageAdapter,
        "adapter_kwargs": {"model": "nanoBanana_pro"},
        "queue": "media",
        "task_type": "gen.image",
        "task_category": "media",
        "estimate_fn": _estimate_fixed(8),
        "completion_mode": "poll",
        "provider_key": "suchuang-image",
    },
    "suchuang-nb2": {
        "adapter_cls": SuchuangImageAdapter,
        "adapter_kwargs": {"model": "nanoBanana2"},
        "queue": "media",
        "task_type": "gen.image",
        "task_category": "media",
        "estimate_fn": _estimate_fixed(5),
        "completion_mode": "poll",
        "provider_key": "suchuang-image",
    },
    # --- video ---
    "rh-vidu-q2-pro": {
        "adapter_cls": RunningHubVideoAdapter,
        "adapter_kwargs": {"model": "vidu_q2_pro"},
        "queue": "media",
        "task_type": "gen.video",
        "task_category": "media",
        "estimate_fn": _estimate_fixed(50),
        "completion_mode": "webhook",
        "provider_key": "runninghub-video",
    },
    "rh-vidu-q3-pro": {
        "adapter_cls": RunningHubVideoAdapter,
        "adapter_kwargs": {"model": "vidu_q3_pro"},
        "queue": "media",
        "task_type": "gen.video",
        "task_category": "media",
        "estimate_fn": _estimate_fixed(80),
        "completion_mode": "webhook",
        "provider_key": "runninghub-video",
    },
    "suchuang-veo3-pro": {
        "adapter_cls": SuchuangVideoAdapter,
        "adapter_kwargs": {"model": "veo3_1_pro"},
        "queue": "media",
        "task_type": "gen.video",
        "task_category": "media",
        "estimate_fn": _estimate_fixed(60),
        "completion_mode": "poll",
        "provider_key": "suchuang-video",
    },
    "suchuang-veo3-fast": {
        "adapter_cls": SuchuangVideoAdapter,
        "adapter_kwargs": {"model": "veo3_1_fast"},
        "queue": "media",
        "task_type": "gen.video",
        "task_category": "media",
        "estimate_fn": _estimate_fixed(30),
        "completion_mode": "poll",
        "provider_key": "suchuang-video",
    },
    # --- audio ---
    "minimax-audio": {
        "adapter_cls": MinimaxAudioAdapter,
        "adapter_kwargs": {},
        "queue": "audio",
        "task_type": "gen.audio",
        "task_category": "audio",
        "estimate_fn": _estimate_fixed(5),
        "completion_mode": "poll",
        "provider_key": "minimax-audio",
    },
}
