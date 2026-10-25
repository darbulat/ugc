"""Real correction evidence graph, with no compensation or bank sender."""

from ugc_bot.application.services.correction_service import CorrectionService
from ugc_bot.application.services.correction_view_service import (
    CorrectionViewService,
)
from ugc_bot.application.services.financial_ledger_service import (
    FinancialLedgerService,
)
from ugc_bot.application.services.refund_compensation_service import (
    SelectionRefundCompensationService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.correction_views import (
    SqlAlchemyCorrectionViewRepository,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
)
from ugc_bot.infrastructure.db.repositories.physical_proofs import (
    SqlAlchemyPhysicalProofRepository,
)


def build_correction_services(config, transactions, session_factory):
    if transactions is None or session_factory is None:
        raise ValueError("correction_database_required")
    clock = SystemClock()
    repository = SqlAlchemyCorrectionViewRepository()
    ledger = FinancialLedgerService(SqlAlchemyFinancialLedgerRepository())
    service = CorrectionService(
        repository,
        SqlAlchemyPhysicalProofRepository(
            config.financial.manual_bank_source_id,
            config.financial.manual_bank_account_id,
            clock,
        ),
        clock,
        compensation=SelectionRefundCompensationService(
            repository,
            ledger,
            original_assessment=_original_client_assessment(
                ledger, clock, session_factory
            ),
        ),
    )
    return service, CorrectionViewService(
        repository, service, clock, config.financial
    )


def _original_client_assessment(ledger, clock, session_factory):
    """Explicit correction path; ordinary consumers keep their live guard."""
    from ugc_bot.application.services.client_entitlement_service import (
        ClientEntitlementService,
    )
    from ugc_bot.application.services.creator_identity_history_service import (
        CreatorIdentityHistoryService,
    )
    from ugc_bot.application.services.work_financial_guard import (
        WorkFinancialGuard,
    )
    from ugc_bot.infrastructure.db.repositories import (
        selection_delivery_funding,
    )
    from ugc_bot.infrastructure.db.repositories.identity_history import (
        SqlAlchemyCreatorIdentityHistoryRepository,
    )
    from ugc_bot.infrastructure.db.repositories.rate_overrides import (
        SqlAlchemyRateOverrideRepository,
    )
    from ugc_bot.infrastructure.db.repositories.work_entitlements import (
        SqlAlchemyWorkEntitlementRepository,
    )

    return ClientEntitlementService(
        selection_delivery_funding.SqlAlchemySelectionFundingRepository(),
        ledger,
        CreatorIdentityHistoryService(
            SqlAlchemyCreatorIdentityHistoryRepository(session_factory)
        ),
        SqlAlchemyRateOverrideRepository(),
        clock,
        work_guard=WorkFinancialGuard(SqlAlchemyWorkEntitlementRepository()),
    )


def build_accompaniment_refund_service(config, transactions, session_factory):
    from ugc_bot.application.services.accompaniment_refund_service import (
        AccompanimentRefundService,
    )
    from ugc_bot.application.services.collaboration_service import (
        CollaborationService,
    )
    from ugc_bot.application.services.obligation_compensation_service import (
        ObligationCompensationService,
    )
    from ugc_bot.infrastructure.db.repositories.accompaniment_refunds import (
        SqlAlchemyAccompanimentRefundRepository,
    )
    from ugc_bot.infrastructure.db.repositories.collaborations import (
        SqlAlchemyCollaborationRepository,
    )

    if transactions is None or session_factory is None:
        raise ValueError("correction_database_required")
    clock = SystemClock()
    ledger = FinancialLedgerService(SqlAlchemyFinancialLedgerRepository())
    return AccompanimentRefundService(
        SqlAlchemyAccompanimentRefundRepository(),
        ledger,
        SqlAlchemyPhysicalProofRepository(
            config.financial.manual_bank_source_id,
            config.financial.manual_bank_account_id,
            clock,
        ),
        ObligationCompensationService(ledger),
        clock,
        lifecycle=CollaborationService(
            SqlAlchemyCollaborationRepository(), clock
        ),
    )
