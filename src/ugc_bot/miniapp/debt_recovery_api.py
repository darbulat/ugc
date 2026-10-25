"""Current-admin review separates the bank fact from debt recovery."""

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import AwareDatetime, BeforeValidator, Field

from ugc_bot.application.debt_recovery_ports import (
    ApplyDebtRecovery,
    RecordDebtRepayment,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.miniapp.correction_api import NoStoreCorrectionRoute
from ugc_bot.miniapp.correction_wire import (
    correction_to_wire,
    parse_observed_minor,
)
from ugc_bot.miniapp.principal import SignedMiniAppRequest


class Page(SignedMiniAppRequest):
    page: int = Field(default=0, ge=0, le=100000, strict=True)
    limit: int = Field(default=25, ge=1, le=100, strict=True)


class Evidence(SignedMiniAppRequest):
    operation_key: str = Field(min_length=1, max_length=256)
    case_id: UUID
    reason: str = Field(min_length=1, max_length=4000)
    evidence_reference: str = Field(min_length=1, max_length=4000)
    evidence_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class Observe(Evidence):
    recipient_id: UUID
    amount_minor: Annotated[int, BeforeValidator(parse_observed_minor)]
    currency: Literal["RUB"]
    bank_account_label: str = Field(min_length=1, max_length=256)
    bank_reference: str = Field(min_length=1, max_length=4000)
    occurred_at: AwareDatetime


class Apply(Evidence):
    observation_id: UUID
    business_key: str = Field(min_length=1, max_length=4000)
    expected_debt_minor: Annotated[
        int, BeforeValidator(parse_observed_minor)
    ] = Field(
        description="Outstanding case debt for this recipient and currency"
    )


class DebtRecoveryApi:
    def __init__(self, resolve):
        self.resolve = resolve

    async def _invoke(self, request, body, constructor=None, method="context"):
        if request.query_params:
            raise HTTPException(422, "correction_request_invalid")
        actor = await self.resolve(
            request, body.init_data, platform=body.platform
        )
        if not isinstance(actor, AuthenticatedMessengerPrincipal):
            raise HTTPException(401, "financial_session_invalid")
        dispatcher = request.app.state.dispatcher
        service = dispatcher.get("debt_recovery_service")
        transactions = dispatcher.get("transaction_manager")
        if service is None or transactions is None:
            raise HTTPException(503, "correction_unavailable")
        if (
            method == "apply"
            and not request.app.state.config.financial.core_enabled
        ):
            raise HTTPException(503, "financial_corrections_disabled")
        try:
            values = body.model_dump(exclude={"init_data", "platform"})
            async with transactions.transaction() as session:
                if constructor is None:
                    result = await service.context(
                        actor.user_id,
                        principal=actor,
                        session=session,
                        **values,
                    )
                else:
                    result = await getattr(service, method)(
                        constructor(actor_id=actor.user_id, **values),
                        session=session,
                        principal=actor,
                    )
                return jsonable_encoder(correction_to_wire(result))
        except PermissionError:
            raise HTTPException(
                403, "correction_active_admin_required"
            ) from None
        except ValueError as error:
            code = "repayment_operation_rejected"
            if str(error) == "financial_principal_changed":
                raise HTTPException(
                    403, "financial_principal_changed"
                ) from None
            raise HTTPException(409, code) from None

    async def context(self, request: Request, body: Page):
        return await self._invoke(request, body)

    async def observe(self, request: Request, body: Observe):
        return await self._invoke(request, body, RecordDebtRepayment, "observe")

    async def apply(self, request: Request, body: Apply):
        return await self._invoke(request, body, ApplyDebtRecovery, "apply")


def create_debt_recovery_router(resolve):
    router = APIRouter(
        prefix="/financial/debts/admin", route_class=NoStoreCorrectionRoute
    )
    api = DebtRecoveryApi(resolve)
    for path, handler in (
        ("/context", api.context),
        ("/observe", api.observe),
        ("/apply", api.apply),
    ):
        router.add_api_route(path, handler, methods=["POST"])
    return router
