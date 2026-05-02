from __future__ import annotations

import argparse
import asyncio

from database import create_db_and_tables
from services.task_job_service import build_worker_id
from services.task_worker_service import run_worker_async


async def _async_main() -> None:
    parser = argparse.ArgumentParser(description="AIdrama task worker")
    parser.add_argument("--queues", default="storyboard,resource,media,audio")
    parser.add_argument("--name", default="worker")
    args = parser.parse_args()
    queues = [item.strip() for item in str(args.queues or "").split(",") if item.strip()]
    create_db_and_tables()
    await run_worker_async(queues=queues, worker_id=build_worker_id(args.name))


if __name__ == "__main__":
    asyncio.run(_async_main())
