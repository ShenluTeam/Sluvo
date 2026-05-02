from __future__ import annotations

import asyncio

from database import create_db_and_tables
from services.provider_poll_service import run_poller_loop


def main() -> None:
    create_db_and_tables()
    asyncio.run(run_poller_loop())


if __name__ == "__main__":
    main()
