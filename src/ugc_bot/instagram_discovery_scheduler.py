"""Rare enrichment with separate credentials and scheduled starts only."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from ugc_bot.infrastructure.db.repositories.instagram_discovery import (
    DiscoveryRepository,
)
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.infrastructure.instagram.discovery_client import (
    STOP_OUTCOMES,
    DiscoveryClient,
    DiscoveryCredential,
)

LOG = logging.getLogger(__name__)


async def scheduled_batch(repository, lease, client, *, now, sleep):
    outcome = "complete"
    try:
        for _ in range(150):
            target = await repository.prepare(lease, now())
            if target is None:
                break
            result = await client.fetch(target.username)
            outcome = await repository.finish(
                target, result, client.credential.context, now()
            )
            if result.outcome in STOP_OUTCOMES or result.usage_percent >= 50:
                break
            await sleep(60)
    finally:
        await repository.release(lease, outcome)
    return outcome


async def run():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sessions = create_session_factory(os.environ["DATABASE_URL"])
    repository = DiscoveryRepository(
        sessions, os.environ["INSTAGRAM_IDENTITY_CONTEXT"]
    )
    path = Path(
        os.environ.get(
            "INSTAGRAM_DISCOVERY_CREDENTIAL_FILE", "/discovery/credential.json"
        )
    )

    def now():
        Path("/tmp/discovery-heartbeat").touch()
        return datetime.now(timezone.utc)

    async with httpx.AsyncClient(trust_env=False) as http:
        while True:
            try:
                # Validate before claiming; expired files never make calls.
                credential = DiscoveryCredential.load(path)
                lease = await repository.claim(now())
                if lease is not None:
                    outcome = await scheduled_batch(
                        repository,
                        lease,
                        DiscoveryClient(http, credential),
                        now=now,
                        sleep=asyncio.sleep,
                    )
                    LOG.info("Discovery scheduled batch finished: %s", outcome)
                Path("/tmp/discovery-heartbeat").touch()
            except Exception as exc:
                # Errors, validation inputs and SQL parameters may hold secrets.
                LOG.error("Discovery scheduler paused (%s)", type(exc).__name__)
            await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(run())
