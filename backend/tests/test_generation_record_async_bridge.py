import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.generation_record_service import _run_async_blocking


async def _sample_async_value():
    await asyncio.sleep(0)
    return "ok"


def test_run_async_blocking_without_running_loop():
    assert _run_async_blocking(_sample_async_value()) == "ok"


def test_run_async_blocking_inside_running_loop():
    async def _runner():
        return _run_async_blocking(_sample_async_value())

    assert asyncio.run(_runner()) == "ok"
