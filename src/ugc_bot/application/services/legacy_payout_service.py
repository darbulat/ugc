"""Transport-independent result of an actual protected legacy request commit."""

from enum import StrEnum

from sqlalchemy.exc import IntegrityError

from ugc_bot.application.errors import LegacyPayoutBlockedError
from ugc_bot.application.ports import (
    PayoutRequestRepository,
    TransactionManager,
)
from ugc_bot.domain.entities import PayoutRequest
from ugc_bot.infrastructure.db.session import with_optional_tx


class LegacyPayoutResult(StrEnum):
    CREATED = "created"
    DISPUTED = "disputed"
    DUPLICATE = "duplicate"


async def create_legacy_payout_request(
    request: PayoutRequest,
    repository: PayoutRequestRepository,
    transaction_manager: TransactionManager | None,
) -> LegacyPayoutResult:
    """Return CREATED only after the guard and request transaction commit."""

    async def _save(session: object | None) -> None:
        await repository.save(request, session=session)

    try:
        await with_optional_tx(transaction_manager, _save)
    except LegacyPayoutBlockedError:
        return LegacyPayoutResult.DISPUTED
    except (IntegrityError, ValueError):
        return LegacyPayoutResult.DUPLICATE
    return LegacyPayoutResult.CREATED
