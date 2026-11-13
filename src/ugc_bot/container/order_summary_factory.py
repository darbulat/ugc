"""Compose Telegram order summaries from the existing financial services."""

from ugc_bot.application.services.collaboration_service import (
    CollaborationService,
)
from ugc_bot.application.services.order_summary_service import (
    OrderSummaryService,
)
from ugc_bot.application.services.selection_maturity_service import (
    SelectionMaturityService,
)
from ugc_bot.container.replacement_factory import build_replacement_service
from ugc_bot.infrastructure.clock import SystemClock
from ugc_bot.infrastructure.db.repositories.collaborations import (
    SqlAlchemyCollaborationRepository,
)
from ugc_bot.infrastructure.db.repositories.customer_workflows import (
    SqlAlchemyCustomerWorkflowRepository,
)
from ugc_bot.infrastructure.db.repositories.order_summary import SqlOrderSummary
from ugc_bot.infrastructure.db.repositories.selection_maturity import (
    SqlAlchemySelectionMaturityRepository,
)


def build_order_summary(config, transactions):
    if (
        transactions is None
        or not config.financial.core_enabled
        or not config.order.customer_workflows_enabled
    ):
        return None
    clock = SystemClock()
    replacement = build_replacement_service(config)
    return OrderSummaryService(
        SqlAlchemyCustomerWorkflowRepository(),
        transactions,
        clock,
        SqlOrderSummary(),
        CollaborationService(SqlAlchemyCollaborationRepository(), clock),
        replacement,
        SelectionMaturityService(
            SqlAlchemySelectionMaturityRepository(), replacement.ledger, clock
        ),
    )
