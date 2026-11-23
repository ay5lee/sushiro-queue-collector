from __future__ import annotations

import asyncio
import logging

from .client import SushiPassClient
from .config import Settings
from .db import Database
from .logging_util import setup_logging, log_extra
from .poller import QueuePoller


async def _amain() -> None:
    settings = Settings.from_env()
    setup_logging(settings.log_level, settings.log_json)
    logger = logging.getLogger("poller")
    log_extra(
        logger,
        logging.INFO,
        "poller_starting",
        sweep_interval_seconds=settings.sweep_interval_seconds,
        concurrency=settings.concurrency,
        force_poll=settings.force_poll,
        default_open=settings.default_open_time,
        default_close=settings.default_close_time,
    )

    db = Database(settings.database_url)
    client = SushiPassClient(settings)
    poller = QueuePoller(settings, db, client)
    try:
        await poller.run_forever()
    finally:
        await client.aclose()
        db.close()


def main() -> None:
    asyncio.run(_amain())


if __name__ == "__main__":
    main()
