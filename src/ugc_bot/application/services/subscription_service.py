"""Manual subscriptions with immutable tariffs and reviewed payment evidence."""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.subscription_ports import SubscriptionRepository
from ugc_bot.domain.campaigns import digest
from ugc_bot.domain.financial import utc
from ugc_bot.domain.subscriptions import (
    SubscriptionTariff,
    evidence_hash,
    required_text,
    subscription_period,
)

TARIFF_FIELDS = {
    "version",
    "title",
    "price_minor",
    "duration_days",
    "campaign_limit",
    "recipient_limit",
    "terms_reference",
}
PAYMENT_FIELDS = {
    "member_id",
    "tariff_version",
    "amount_minor",
    "currency",
    "paid_at",
    "payment_reference",
    "evidence_reference",
    "evidence_hash",
    "reason",
    "pilot",
}
FIELDS = {
    "publish": TARIFF_FIELDS | {"reason"},
    "accept_payment": PAYMENT_FIELDS,
    "cancel": {"reason"},
    "enable_automation": {"reason", "evidence_reference", "evidence_hash"},
}


def state(events: list[dict], member_id: UUID, at: datetime) -> dict:
    owned = [e for e in events if e["member_id"] == str(member_id)]
    payments = [e for e in owned if e["action"] == "accept_payment"]
    if not payments:
        return {"state": "unpaid", "scope": "own_consented_network"}
    latest = payments[-1]
    cancellations = [e for e in owned if e["action"] == "cancel"]
    last_cancel = max((e["sequence"] for e in cancellations), default=0)
    periods = [e for e in payments if e["sequence"] > last_cancel]
    live = [
        e
        for e in periods
        if datetime.fromisoformat(e["result"]["starts_at"])
        <= at
        < datetime.fromisoformat(e["result"]["until"])
    ]
    current = live[-1] if live else latest
    result = dict(current["result"])
    result["period_until"] = result["until"]
    result["state"] = "active" if live else "expired"
    if last_cancel > latest["sequence"]:
        result["state"] = "cancelled"
    elif live:
        result["until"] = max(e["result"]["until"] for e in periods)

    return result


def pilot_facts(events: list[dict]) -> dict:
    paid = Counter(
        e["member_id"]
        for e in events
        if e["action"] == "accept_payment" and e["payload"]["pilot"]
    )
    return dict(
        paid_pilot_managers=len(paid),
        paid_renewals=sum(max(0, count - 1) for count in paid.values()),
    )


@dataclass
class SubscriptionService:
    repository: SubscriptionRepository
    transactions: TransactionManager
    clock: Clock

    @staticmethod
    def _principal(ctx, actor_id, principal):
        require_current_principal(
            principal,
            actor_id,
            actor_id if ctx["actor_active"] else None,
            ctx.get("telegram_id"),
            ctx.get("max_id"),
        )
        if not ctx["actor_active"]:
            raise PermissionError("subscription_active_account_required")

    async def _pilot_facts(self, events, session):
        facts = pilot_facts(events)
        first_paid = {}
        for event in events:
            if (
                event["action"] != "accept_payment"
                or not event["payload"]["pilot"]
            ):
                continue
            member = UUID(event["member_id"])
            at = utc(datetime.fromisoformat(event["payload"]["paid_at"]))
            first_paid[member] = min(at, first_paid.get(member, at))
        uses = await self.repository.pilot_reuse(first_paid, session=session)
        grouped = {}
        for use in uses:
            if use.member_id in first_paid:
                grouped.setdefault(use.member_id, {}).setdefault(
                    use.campaign_id, use
                )
        reused = next(
            (
                grouped[member]
                for member in sorted(grouped, key=str)
                if len(grouped[member]) >= 2
            ),
            {},
        )
        evidence = [
            dict(
                member_id=str(use.member_id),
                campaign_id=str(use.campaign_id),
                outcome_id=str(use.outcome_id),
            )
            for _, use in sorted(reused.items(), key=lambda row: str(row[0]))[
                :2
            ]
        ]
        return facts | dict(
            repeated_paid_use=bool(evidence), reuse_evidence=evidence
        )

    async def view(
        self,
        actor_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict:
        async with self.transactions.transaction() as session:
            ctx = await self.repository.context(
                actor_id, actor_id, session=session
            )
            self._principal(ctx, actor_id, principal)
            events = await self.repository.events(session=session)
            tariffs = [e["result"] for e in events if e["action"] == "publish"]
            result = dict(
                actor_id=str(actor_id),
                can_admin=ctx["admin"],
                can_manage=ctx["manager"],
                tariffs=tariffs,
                subscription=state(events, actor_id, utc(self.clock.now())),
                automation_enabled=any(
                    e["action"] == "enable_automation" for e in events
                ),
                automatic_billing=False,
            )
            if ctx["admin"]:
                result.update(await self._pilot_facts(events, session))
                result["payments"] = [
                    dict(
                        e["result"],
                        member_id=e["member_id"],
                        payment_reference=e["payload"]["payment_reference"],
                        evidence_reference=e["payload"]["evidence_reference"],
                    )
                    for e in events
                    if e["action"] == "accept_payment"
                ]
            return result

    async def execute(
        self,
        actor_id: UUID,
        action: str,
        operation_key: str,
        payload: dict,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> dict:
        required_text(operation_key, 256)
        if action not in FIELDS:
            raise ValueError("subscription_unknown_action")
        member_id = (
            UUID(payload["member_id"])
            if action == "accept_payment" and payload.get("member_id")
            else actor_id
        )
        async with self.transactions.transaction() as session:
            ctx = await self.repository.context(
                actor_id, member_id, session=session
            )
            self._principal(ctx, actor_id, principal)
            if action != "cancel" and not ctx["admin"]:
                raise PermissionError("subscription_current_admin_required")
            if set(payload) != FIELDS[action]:
                raise ValueError("subscription_unexpected_fields")
            required_text(payload["reason"], 4000)
            await self.repository.lock(session=session)
            events = await self.repository.events(session=session)
            fingerprint = digest(dict(action=action, payload=payload))
            previous = next(
                (
                    e
                    for e in events
                    if e["actor_id"] == str(actor_id)
                    and e["operation_key"] == operation_key
                ),
                None,
            )
            if previous:
                if previous["payload_hash"] != fingerprint:
                    raise ValueError(
                        "subscription_idempotency_payload_conflict"
                    )
                return previous["result"]
            at = utc(self.clock.now())
            facts = (
                await self._pilot_facts(events, session)
                if action == "enable_automation"
                else None
            )
            result = self._apply(
                action, member_id, ctx, payload, events, at, facts
            )
            event = dict(
                event_id=str(uuid4()),
                sequence=len(events) + 1,
                actor_id=str(actor_id),
                member_id=str(member_id),
                operation_key=operation_key,
                action=action,
                payload_hash=fingerprint,
                payload=payload,
                result=result,
                recorded_at=at.isoformat(),
            )
            await self.repository.append(event, session=session)
            return result

    def _apply(self, action, member_id, ctx, payload, events, at, facts=None):
        if action == "publish":
            tariff = SubscriptionTariff(
                **{k: payload[k] for k in TARIFF_FIELDS}
            )
            if any(
                e["action"] == "publish"
                and e["result"]["version"] == tariff.version
                for e in events
            ):
                raise ValueError("subscription_tariff_version_immutable")
            return tariff.to_document()
        if action == "accept_payment":
            return self._payment(member_id, ctx, payload, events, at)
        if action == "cancel":
            previous = state(events, member_id, at)
            if previous["state"] not in ("active", "cancelled"):
                raise ValueError("subscription_active_period_required")
            return dict(
                state="cancelled",
                cancelled_at=at.isoformat(),
                automatic_billing=False,
            )
        evidence_hash(payload["evidence_hash"])
        required_text(payload["evidence_reference"], 4000)
        if facts is None:
            raise ValueError("subscription_pilot_evidence_required")
        if facts["paid_pilot_managers"] < 3:
            raise ValueError("subscription_three_paid_pilots_required")
        if not facts["repeated_paid_use"]:
            raise ValueError("subscription_actual_paid_reuse_required")
        return facts | dict(automation_enabled=True, automatic_billing=False)

    @staticmethod
    def _payment(member_id, ctx, payload, events, at):
        if not ctx["member_active"] or not ctx["manager"]:
            raise PermissionError("subscription_active_manager_required")
        evidence_hash(payload["evidence_hash"])
        required_text(payload["evidence_reference"], 4000)
        reference = required_text(payload["payment_reference"], 1000)
        if any(
            e["action"] == "accept_payment"
            and e["payload"]["payment_reference"] == reference
            for e in events
        ):
            raise ValueError("subscription_payment_reference_already_used")
        tariff = next(
            (
                e["result"]
                for e in events
                if e["action"] == "publish"
                and e["result"]["version"] == payload["tariff_version"]
            ),
            None,
        )
        if not tariff:
            raise ValueError("subscription_published_tariff_required")
        if (
            type(payload["amount_minor"]) is not int
            or payload["amount_minor"] != tariff["price_minor"]
            or payload["currency"] != "RUB"
        ):
            raise ValueError("subscription_exact_tariff_amount_required")
        if type(payload["pilot"]) is not bool:
            raise ValueError("subscription_pilot_boolean_required")
        paid_at = utc(datetime.fromisoformat(payload["paid_at"]))
        if paid_at > at:
            raise ValueError("subscription_future_payment_forbidden")
        previous = state(events, member_id, at)
        prior_until = (
            datetime.fromisoformat(previous["until"])
            if previous["state"] == "active"
            else None
        )
        start, until = subscription_period(
            paid_at, prior_until, tariff["duration_days"]
        )
        return dict(
            tariff_version=tariff["version"],
            price_minor=tariff["price_minor"],
            currency="RUB",
            scope=tariff["scope"],
            campaign_limit=tariff["campaign_limit"],
            recipient_limit=tariff["recipient_limit"],
            starts_at=start.isoformat(),
            until=until.isoformat(),
            accepted_at=at.isoformat(),
            automatic_billing=False,
        )
