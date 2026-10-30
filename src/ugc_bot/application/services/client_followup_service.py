"""One active activity-anchored series per customer and purchase attempt."""

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
        observed = await self.repository.payment_observed_at(
            series["user_id"],
            series["created_at"],
            order_id=order_id or series["order_id"],
            fallback=utc(self.clock.now()),
            session=session,
        )
        if observed is not None:
            series["stop_reason"] = "paid"
            series["stopped_at"] = utc(observed)
            if order_id is not None and series["order_id"] is None:
                series["order_id"] = order_id
            await self.repository.save_series(series, session=session)

    async def _new_order_after_payment(
        self, series: dict, event: str, order_id: UUID | None, session: object
    ):
        if (
            series["stop_reason"] != "paid"
            or series["opted_out"]
            or event != "order_created"
            or order_id is None
            or series.get("stopped_at") is None
        ):
            return None
        created = await self.repository.order_created_at(
            series["user_id"], order_id, session=session
        )
        if created is None or utc(created) <= max(
            utc(series["stopped_at"]), utc(series["created_at"])
        ):
            return None
        if await self.repository.has_relevant_payment(
            series["user_id"], created, order_id=order_id, session=session
        ):
            return None
        return utc(created)

    async def _intent_context(
        self, user_id, event, order_id, intent_id, series, session
    ):
        if intent_id is None:
            return None, None, False
        known = await self.repository.intent_series(
            user_id, intent_id, session=session
        )
        linked_order = await self.repository.intent_order(
            user_id, intent_id, session=session
        )
        if series and known and known != series["series_id"]:
            if event != "order_created" or not order_id:
                return known, linked_order, True
            incoming_at = await self.repository.order_created_at(
                user_id, order_id, session=session
            )
            if incoming_at is None or incoming_at < series["created_at"]:
                return known, linked_order, True
        stale_link = bool(
            linked_order
            and not order_id
            and series
            and (known != series["series_id"] or series["stop_reason"])
        )
        return known, linked_order, stale_link

    async def _older_order(self, user_id, order_id, series, session):
        current_order = series["order_id"]
        if not order_id or order_id == current_order:
            return False
        incoming_at = await self.repository.order_created_at(
            user_id, order_id, session=session
        )
        if not current_order:
            if not await self.repository.has_older_paid_series(
                user_id, series["created_at"], session=session
            ):
                return False
            return incoming_at is None or incoming_at < series["created_at"]
        current_at = await self.repository.order_created_at(
            user_id, current_order, session=session
        )
        return incoming_at is None or (
            current_at is not None and incoming_at <= current_at
        )

    async def _restart_time(
        self,
        series,
        event,
        order_id,
        intent_id,
        known,
        linked_order,
        now,
        session,
    ):
        start_at = await self._new_order_after_payment(
            series, event, order_id, session
        )
        if start_at is not None:
            return start_at
        if (
            series["stop_reason"] == "paid"
            and not series["opted_out"]
            and event == "brief_opened"
            and intent_id
            and known is None
            and linked_order is None
            and series.get("stopped_at") is not None
            and now > max(utc(series["stopped_at"]), utc(series["created_at"]))
        ):
            opened_at = await self.repository.intent_opened_at(
                series["user_id"], intent_id, session=session
            )
            if opened_at is not None and utc(opened_at) <= utc(
                series["stopped_at"]
            ):
                return None
            return now
        return None

    async def _bind_intent(self, user_id, intent_id, series, now, session):
        if intent_id:
            await self.repository.bind_intent(
                user_id, intent_id, series["series_id"], now, session=session
            )

    @staticmethod
    def _validate_activity(event, intent_id):
        if event not in ACTIVITY_EVENTS:
            raise ValueError("followup_event_invalid")
        if intent_id is not None and (
            not isinstance(intent_id, UUID) or not intent_id.int
        ):
            raise ValueError("followup_intent_invalid")

    async def record_activity(
        self,
        user_id: UUID,
        event: str,
        order_id: UUID | None = None,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
        intent_id: UUID | None = None,
    ) -> dict:
        self._validate_activity(event, intent_id)
        async with self.transactions.transaction() as session:
            actor = await self.authorize(user_id, principal, session=session)
            if order_id:
                await self.require_order(user_id, order_id, session=session)
            series = await self.repository.series(user_id, session=session)
            now = utc(self.clock.now())
            known_intent, intent_order, stale = await self._intent_context(
                user_id, event, order_id, intent_id, series, session
            )
            if stale:
                assert series is not None
                await self._reconcile_paid(series, session)
                return series
            if intent_order and not order_id and series is None:
                order_id = intent_order
            if series and not series["stop_reason"] and not series["opted_out"]:
                if await self._older_order(user_id, order_id, series, session):
                    await self._reconcile_paid(series, session)
                    return series
                await self._reconcile_paid(series, session, order_id)
            start_at = None
            if series and (series["stop_reason"] or series["opted_out"]):
                start_at = await self._restart_time(
                    series,
                    event,
                    order_id,
                    intent_id,
                    known_intent,
                    intent_order,
                    now,
                    session,
                )
                if start_at is None:
                    if (
                        intent_id
                        and known_intent is None
                        and event == "order_created"
                        and series["order_id"] == order_id
                    ):
                        await self._bind_intent(
                            user_id, intent_id, series, now, session
                        )
                    return series
                series = None
            series = series or dict(
                series_id=uuid4(),
                user_id=user_id,
                generation=0,
                last_activity_at=now,
                created_at=start_at or now,
                order_id=None,
                channel=None,
                opted_out=False,
                stop_reason=None,
                stopped_at=None,
            )
            await self._reconcile_paid(series, session, order_id)
            if series["stop_reason"]:
                await self._bind_intent(
                    user_id, intent_id, series, now, session
                )
                return series
            series.update(
                generation=series["generation"] + 1,
                last_activity_at=now,
                order_id=order_id or series["order_id"],
                channel=principal.platform if principal else actor["channel"],
            )
            await self.repository.save_series(series, session=session)
            await self._bind_intent(user_id, intent_id, series, now, session)
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
                    stopped_at=now,
                )
            series.update(
                opted_out=True,
                stop_reason="optout",
                stopped_at=utc(self.clock.now()),
            )
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
            if series["stop_reason"] == "paid":
                return
            if not series["stop_reason"] and await self._older_order(
                user_id, order_id, series, session
            ):
                await self._reconcile_paid(series, session)
                return
            if (
                not series["stop_reason"]
                and series["order_id"]
                and series["order_id"] != order_id
                and not await self.repository.has_relevant_payment(
                    user_id, series["created_at"], session=session
                )
            ):
                return
            series["stop_reason"] = "paid"
            series["stopped_at"] = utc(self.clock.now())
            await self.repository.save_series(series, session=session)
