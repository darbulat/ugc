"""Wrappers for Instagram stats provider clients (e.g. for tests)."""

import asyncio
import logging
from typing import List, Optional, Tuple

from ugc_bot.application.ports import (
    InstagramRapidApiClient,
    InstagramStatsProviderClient,
    RapidApiRateLimitError,
)
from ugc_bot.infrastructure.instagram.delays import random_delay_seconds

logger = logging.getLogger(__name__)


class SingleProviderWrapper(InstagramStatsProviderClient):
    """Wraps one client and returns stats with fixed provider id."""

    def __init__(
        self,
        client: InstagramRapidApiClient,
        provider_id: str = "scrapecreators",
    ) -> None:
        self._client = client
        self._provider_id = provider_id

    async def get_profile_stats_with_provider(
        self, username: str
    ) -> Tuple[Optional[dict], str]:
        """Call underlying client; return (data, provider_id)."""
        data = await self._client.get_profile_stats_by_username(username)
        return (data, self._provider_id)


class MultiProviderInstagramStatsClient(InstagramStatsProviderClient):
    """Tries multiple providers in order; on 429 waits then uses next."""

    def __init__(
        self,
        clients_with_ids: List[Tuple[InstagramRapidApiClient, str]],
        fallback_delay_seconds: float = 2.0,
    ) -> None:
        """Initialize with list of (client, provider_id) and delay after 429."""
        self._clients = clients_with_ids
        self._fallback_delay = max(0.0, float(fallback_delay_seconds))

    async def get_profile_stats_with_provider(
        self, username: str
    ) -> Tuple[Optional[dict], str]:
        """Try each provider; on RapidApiRateLimitError wait then try next."""
        last_provider = ""
        for i, (client, provider_id) in enumerate(self._clients):
            last_provider = provider_id
            try:
                data = await client.get_profile_stats_by_username(username)
                return (data, provider_id)
            except RapidApiRateLimitError:
                logger.info(
                    "Rate limit, trying next provider",
                    extra={"provider": provider_id, "username": username},
                )
                if self._fallback_delay > 0 and i < len(self._clients) - 1:
                    await asyncio.sleep(
                        random_delay_seconds(self._fallback_delay)
                    )
                continue
        return (None, last_provider)
