"""Payout read graph keeps the writer's explicit crypto startup contract."""

from ugc_bot.application.services.payout_view_service import PayoutViewService
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.payout_views import (
    SqlAlchemyPayoutViewRepository,
)
from ugc_bot.infrastructure.secure_requisites import PayoutRequisitesCrypto


def build_payout_view_service(config, session_factory):
    if session_factory is None:
        raise ValueError("payout_database_required")
    financial = config.financial
    key = financial.requisites_key.get_secret_value()
    crypto = (
        PayoutRequisitesCrypto(key, financial.requisites_key_id)
        if key or financial.requisites_key_id
        else None
    )
    return PayoutViewService(
        SqlAlchemyPayoutViewRepository(session_factory),
        SystemClock(),
        financial,
        crypto,
    )
