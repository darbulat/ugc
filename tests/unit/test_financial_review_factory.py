"""Production reviews share the authoritative compensation journal."""

from types import SimpleNamespace

from ugc_bot.application.services.financial_review_service import (
    FinancialReviewService,
)
from ugc_bot.container.financial_review_factory import build_financial_review
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_reviews import (
    SqlAlchemyFinancialReviewRepository,
)


def test_review_factory_uses_same_production_ledger_without_external_senders():
    service = build_financial_review(SimpleNamespace())
    assert isinstance(service, FinancialReviewService)
    assert isinstance(service.repository, SqlAlchemyFinancialReviewRepository)
    assert isinstance(
        service.ledger.repository, SqlAlchemyFinancialLedgerRepository
    )
    assert service.compensation.ledger is service.ledger
