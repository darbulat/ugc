"""Current refund/case authority under the caller's existing source locks."""

from ugc_bot.application.services.correction_funding_guard import (
    LiveCorrectionFundingGuard,
)
from ugc_bot.infrastructure.db.repositories.corrections import (
    SqlAlchemyCorrectionRepository,
)


async def require_forward_clear(paid_item_id, *, session):
    await LiveCorrectionFundingGuard(
        SqlAlchemyCorrectionRepository()
    ).require_forward_clear(
        paid_item_id, session=session, components=("selection",)
    )
