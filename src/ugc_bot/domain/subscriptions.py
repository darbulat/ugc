"""Published own-network tariffs and paid calendar periods, without a wallet."""

import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta

from ugc_bot.domain.financial import MAX_MINOR, utc


def required_text(value: str, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("subscription_provenance_required")
    return value.strip()


def positive_integer(value: int, maximum: int) -> int:
    if type(value) is not int or not 1 <= value <= maximum:
        raise ValueError("subscription_positive_integer_required")
    return value


@dataclass(frozen=True, slots=True)
class SubscriptionTariff:
    version: str
    title: str
    price_minor: int
    duration_days: int
    campaign_limit: int
    recipient_limit: int
    terms_reference: str

    def __post_init__(self) -> None:
        for name in ("version", "title", "terms_reference"):
            object.__setattr__(self, name, required_text(getattr(self, name)))
        positive_integer(self.price_minor, MAX_MINOR)
        positive_integer(self.duration_days, 365)
        positive_integer(self.campaign_limit, 1000000)
        positive_integer(self.recipient_limit, 10000000)

    def to_document(self) -> dict:
        return asdict(self) | {
            "currency": "RUB",
            "scope": "own_consented_network",
        }


def subscription_period(
    paid_at: datetime, previous_until: datetime | None, duration_days: int
) -> tuple[datetime, datetime]:
    paid_at = utc(paid_at)
    positive_integer(duration_days, 365)
    start = max(paid_at, utc(previous_until)) if previous_until else paid_at
    return start, start + timedelta(days=duration_days)


def evidence_hash(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("subscription_evidence_hash_required")
    return value
