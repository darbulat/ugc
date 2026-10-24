"""Public work commands cannot impersonate scheduler or transport outcomes."""

from datetime import datetime
from typing import Literal, cast
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field

from ugc_bot.application.collaboration_ports import (
    CollaborationCommand,
    CollaborationRecord,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.collaboration_service import (
    CollaborationService,
)
from ugc_bot.miniapp.financial_principal import FinancialPrincipalResolver
from ugc_bot.miniapp.native_caller_errors import NoStoreCollaborationRoute
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class WorkCommandRequest(SignedMiniAppRequest):
    action: Literal[
        "assign",
        "start",
        "claim",
        "agree",
        "dispute",
        "extend_due",
        "request_confirmation",
    ]
    operation_key: str = Field(min_length=1, max_length=200)
    expected_version: int = Field(ge=0, strict=True)
    due_at: AwareDatetime | None = None
    expected_due_version: int | None = Field(default=None, ge=1, strict=True)
    terms_reference: str | None = Field(
        default=None, min_length=1, max_length=500
    )
    evidence: str | None = Field(default=None, min_length=1, max_length=4000)
    reason: str | None = Field(default=None, min_length=1, max_length=4000)


class WorkResponse(BaseModel):
    record: CollaborationRecord
    first_claim_deadline: datetime
    objection_deadline: datetime | None
    available_at: datetime | None
    actor_id: UUID
    allowed_actions: tuple[str, ...]
    is_current: bool

    @classmethod
    def from_record(
        cls,
        record: CollaborationRecord,
        actor_id: UUID,
        is_current: bool,
        actions: tuple[str, ...],
    ) -> "WorkResponse":
        work = record.collaboration
        return cls(
            record=record,
            first_claim_deadline=work.first_claim_deadline,
            objection_deadline=work.objection_deadline,
            available_at=work.available_at,
            actor_id=actor_id,
            allowed_actions=actions,
            is_current=is_current,
        )


async def _work_context(
    request: Request,
    body: SignedMiniAppRequest,
    resolve_principal: FinancialPrincipalResolver,
) -> tuple[
    AuthenticatedMessengerPrincipal, CollaborationService, TransactionManager
]:
    if request.query_params:
        raise HTTPException(422, "collaboration_request_invalid")
    principal = await resolve_principal(
        request, body.init_data, platform=body.platform
    )
    if not isinstance(principal, AuthenticatedMessengerPrincipal):
        raise HTTPException(401, "financial_session_invalid")
    config = request.app.state.config
    if not config.financial.core_enabled:
        raise HTTPException(status_code=503, detail="financial_disabled")
    dispatcher = request.app.state.dispatcher
    service = dispatcher.get("collaboration_service")
    transactions = dispatcher.get("transaction_manager")
    if service is None or transactions is None:
        raise HTTPException(status_code=503, detail="financial_unavailable")
    return (
        principal,
        cast(CollaborationService, service),
        cast(TransactionManager, transactions),
    )


def create_collaboration_router(
    resolve_principal: FinancialPrincipalResolver,
) -> APIRouter:
    router = APIRouter(
        prefix="/collaborations",
        route_class=NoStoreCollaborationRoute,
    )

    @router.post("/{assignment_id}/status")
    async def status(
        request: Request, assignment_id: UUID, body: SignedMiniAppRequest
    ) -> WorkResponse:
        principal, service, transactions = await _work_context(
            request, body, resolve_principal
        )
        async with transactions.transaction() as session:
            result = await service.get_authenticated(
                assignment_id,
                principal,
                session=session,
            )
            if result is None:
                raise HTTPException(404, "collaboration_not_found")
            record, is_current, actions = result
            return WorkResponse.from_record(
                record,
                principal.user_id,
                is_current,
                actions,
            )

    @router.post("/{assignment_id}/command")
    async def command(
        request: Request, assignment_id: UUID, body: WorkCommandRequest
    ) -> WorkResponse:
        principal, service, transactions = await _work_context(
            request, body, resolve_principal
        )
        value = CollaborationCommand(
            assignment_id=assignment_id,
            actor_id=principal.user_id,
            **body.model_dump(exclude={"init_data", "platform"}),
        )
        async with transactions.transaction() as session:
            record, is_current, actions = await service.execute_authenticated(
                value,
                principal,
                session=session,
            )
            return WorkResponse.from_record(
                record,
                principal.user_id,
                is_current,
                actions,
            )

    return router
