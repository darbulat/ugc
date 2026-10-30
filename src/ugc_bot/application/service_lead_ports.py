"""Service inquiry persistence contract."""

from ugc_bot.application.customer_workflow_ports import (
    CustomerWorkflowRepository as ServiceLeadRepository,
)

__all__ = ["ServiceLeadRepository"]
