"""Real correction evidence graph, with no compensation or bank sender."""

from ugc_bot.application.services.correction_service import CorrectionService
from ugc_bot.application.services.correction_view_service import (
    CorrectionViewService,
)
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.correction_views import (
    SqlAlchemyCorrectionViewRepository,
)
from ugc_bot.infrastructure.db.repositories.physical_proofs import (
    SqlAlchemyPhysicalProofRepository,
)


def build_correction_services(config, transactions, session_factory):
    if transactions is None or session_factory is None:
        raise ValueError("correction_database_required")
    clock = SystemClock()
    repository = SqlAlchemyCorrectionViewRepository()
    service = CorrectionService(
        repository,
        SqlAlchemyPhysicalProofRepository(
            config.financial.manual_bank_source_id,
            config.financial.manual_bank_account_id,
            clock,
        ),
        clock,
    )
    return service, CorrectionViewService(
        repository, service, clock, config.financial
    )
