"""Exchange rate infrastructure: API provider and Redis cache."""

import json
import logging
from decimal import Decimal

from ugc_bot.application.ports import ExchangeRateCache, ExchangeRateProvider

logger = logging.getLogger(__name__)
_API_URL = "https://open.er-api.com/v6/latest/{base}"


class OpenERApiProvider(ExchangeRateProvider):
    """Fetch rates from open.er-api.com (free, no API key)."""

    def __init__(self, session) -> None:  # type: ignore[type-arg]
        self._session = session

    async def fetch_rates(self, base_currency: str) -> dict[str, Decimal]:
        url = _API_URL.format(base=base_currency)
        async with self._session.get(url) as resp:
            resp.raise_for_status()
            data = await resp.json()
        if data.get("result") != "success":
            raise RuntimeError(f"Exchange rate API error: {data}")
        return {code: Decimal(str(rate)) for code, rate in data["rates"].items()}


class RedisExchangeRateCache(ExchangeRateCache):
    """Redis-backed cache for exchange rates."""

    def __init__(self, redis, ttl_seconds: int = 86400) -> None:  # type: ignore[type-arg]
        self._redis = redis
        self._ttl = ttl_seconds

    async def get_rates(self, base_currency: str) -> dict[str, Decimal] | None:
        raw = await self._redis.get(f"exchange_rates:{base_currency}")
        if raw is None:
            return None
        data = json.loads(raw)
        return {code: Decimal(val) for code, val in data.items()}

    async def set_rates(self, base_currency: str, rates: dict[str, Decimal]) -> None:
        data = {code: str(val) for code, val in rates.items()}
        await self._redis.set(
            f"exchange_rates:{base_currency}",
            json.dumps(data),
            ex=self._ttl,
        )
