"""Compose the invitation flow without a background sending transport."""

from ugc_bot.application.services.creator_invite_service import (
    CreatorInviteService,
)
from ugc_bot.application.services.paid_selection_delivery import (
    PaidSelectionDelivery,
)
from ugc_bot.application.services.paid_selection_interest import (
    PaidSelectionInterestService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.paid_selection import (
    SqlAlchemyPaidSelectionRepository,
)
from ugc_bot.infrastructure.db.repositories.paid_selection_delivery import (
    SqlAlchemyPaidSelectionDeliveryRepository,
)


def build_creator_invites(transactions):
    clock = SystemClock()
    return CreatorInviteService(
        PaidSelectionInterestService(
            SqlAlchemyPaidSelectionRepository(),
            transactions,
            clock,
            enabled=True,
        ),
        PaidSelectionDelivery(
            SqlAlchemyPaidSelectionDeliveryRepository(),
            transactions,
            None,
            clock,
        ),
        transactions,
        clock,
    )
