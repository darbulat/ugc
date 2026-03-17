"""Service for currency conversion with lazy-cached exchange rates."""

import logging
from decimal import ROUND_HALF_UP, Decimal

from ugc_bot.application.ports import ExchangeRateCache, ExchangeRateProvider

logger = logging.getLogger(__name__)
_BASE = "USD"


class ExchangeRateService:
    """Convert amounts between currencies using cached exchange rates."""

    def __init__(
        self, provider: ExchangeRateProvider, cache: ExchangeRateCache
    ) -> None:
        self.provider = provider
        self.cache = cache

    async def _get_rates(self) -> dict[str, Decimal] | None:
        rates = await self.cache.get_rates(_BASE)
        if rates is not None:
            return rates
        try:
            rates = await self.provider.fetch_rates(_BASE)
        except Exception:
            logger.warning("Exchange rate API unavailable", exc_info=True)
            return None
        await self.cache.set_rates(_BASE, rates)
        return rates

    async def get_rate(
        self, from_currency: str, to_currency: str
    ) -> Decimal | None:
        if from_currency == to_currency:
            return Decimal("1")
        rates = await self._get_rates()
        if rates is None:
            return None
        from_rate = rates.get(from_currency)
        to_rate = rates.get(to_currency)
        if from_rate is None or to_rate is None or from_rate == 0:
            return None
        return (to_rate / from_rate).quantize(
            Decimal("0.000001"), rounding=ROUND_HALF_UP
        )

    async def convert(
        self, amount: Decimal, from_currency: str, to_currency: str
    ) -> Decimal | None:
        rate = await self.get_rate(from_currency, to_currency)
        if rate is None:
            return None
        return (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    async def convert_many(
        self, amounts: dict[str, Decimal], to_currency: str
    ) -> Decimal | None:
        total = Decimal("0")
        for currency, amount in amounts.items():
            converted = await self.convert(amount, currency, to_currency)
            if converted is None:
                return None
            total += converted
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
