"""One persistent activity-anchored series per customer; payment is terminal."""

from uuid import UUID, uuid4

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.customer_workflow_common import (
    CustomerWorkflowService,
)
from ugc_bot.domain.financial import utc

ACTIVITY_EVENTS = frozenset(
    {"menu", "brief_opened", "brief_changed", "order_created"}
)


class ClientFollowupService(CustomerWorkflowService):
    async def _reconcile_paid(
        self, series: dict, session: object, order_id: UUID | None = None
    ) -> None:
        if series["stop_reason"] or series["opted_out"]:
            return
        if await self.repository.has_relevant_payment(
            series["user_id"],
            series["created_at"],
            order_id=order_id or series["order_id"],
            session=session,
        ):
            series["stop_reason"] = "paid"
            if order_id is not None:
                series["order_id"] = order_id
            await self.repository.save_series(series, session=session)

    async def record_activity(
        self,
        user_id: UUID,
        event: str,
        order_id: UUID | None = None,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict:
        if event not in ACTIVITY_EVENTS:
            raise ValueError("followup_event_invalid")
        async with self.transactions.transaction() as session:
            actor = await self.authorize(user_id, principal, session=session)
            if order_id:
                await self.require_order(user_id, order_id, session=session)
            series = await self.repository.series(user_id, session=session)
            if series and series["stop_reason"]:
                return series
            now = utc(self.clock.now())
            series = series or dict(
                series_id=uuid4(),
                user_id=user_id,
                generation=0,
                last_activity_at=now,
                created_at=now,
                order_id=None,
                channel=None,
                opted_out=False,
                stop_reason=None,
            )
            await self._reconcile_paid(series, session, order_id)
            if series["stop_reason"]:
                return series
            series.update(
                generation=series["generation"] + 1,
                last_activity_at=now,
                order_id=order_id or series["order_id"],
                channel=principal.platform if principal else actor["channel"],
            )
            await self.repository.save_series(series, session=session)
            await self.repository.schedule(series, session=session)
            return series

    async def state(
        self,
        user_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict | None:
        async with self.transactions.transaction() as session:
            await self.authorize(user_id, principal, session=session)
            series = await self.repository.series(user_id, session=session)
            if series is None:
                return None
            await self._reconcile_paid(series, session)
            next_step = (
                None
                if series["stop_reason"]
                else await self.repository.next_followup(
                    series["series_id"], session=session
                )
            )
            return series | {
                "next_stage": next_step["stage"] if next_step else None,
                "next_due_at": next_step["due_at"] if next_step else None,
                "next_action": "services"
                if next_step and next_step["stage"] == 3
                else "orders",
            }

    async def optout(
        self,
        user_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> None:
        async with self.transactions.transaction() as session:
            actor = await self.authorize(user_id, principal, session=session)
            series = await self.repository.series(user_id, session=session)
            if series is None:
                now = utc(self.clock.now())
                series = dict(
                    series_id=uuid4(),
                    user_id=user_id,
                    generation=1,
                    last_activity_at=now,
                    created_at=now,
                    order_id=None,
                    channel=actor["channel"],
                    opted_out=True,
                    stop_reason="optout",
                )
            series.update(opted_out=True, stop_reason="optout")
            await self.repository.save_series(series, session=session)

    async def record_paid(
        self, user_id: UUID, order_id: UUID, *, session: object | None = None
    ) -> None:
        if session is None:
            async with self.transactions.transaction() as owned:
                await self.record_paid(user_id, order_id, session=owned)
            return
        # Trusted server event. It never creates or alters a financial record.
        await self.require_order(user_id, order_id, session=session)
        series = await self.repository.series(user_id, session=session)
        if series:
            series["stop_reason"] = "paid"
            await self.repository.save_series(series, session=session)
