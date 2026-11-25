"""One read-only snapshot for order, assignments, queue and accepted facts."""

from dataclasses import dataclass
from uuid import UUID

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.selection_view_ports import SelectionViewRepository
from ugc_bot.domain.browser_checkout import (
    consultation_payment_url,
    order_payment_url,
)


@dataclass
class SelectionViewService:
    repository: SelectionViewRepository
    transactions: TransactionManager
    public_base_url: str = ""

    async def view(
        self,
        order_id: UUID,
        actor_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict:
        if principal is not None and (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.user_id != actor_id
        ):
            raise ValueError("financial_principal_changed")
        async with self.transactions.transaction() as session:
            await self.repository.begin_snapshot(session=session)
            result = await self.repository.view(
                order_id, actor_id, session=session, principal=principal
            )
        token = result.pop("consultation_token", None)
        if token is not None:
            result["consultation_url"] = consultation_payment_url(
                self.public_base_url, token
            )
        checkout_token = result.pop("checkout_token", None)
        if checkout_token is not None:
            result["checkout_url"] = order_payment_url(
                self.public_base_url, checkout_token
            )
        return result
