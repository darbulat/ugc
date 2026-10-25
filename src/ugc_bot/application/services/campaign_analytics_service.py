"""Audited manual marketing imports with explicit coverage and attribution."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ugc_bot.application.financial_ports import Clock
from ugc_bot.domain.campaign_analytics import (
    TWO_DECIMAL_CURRENCIES,
    AnalyticsSourceSpec,
    MetricEvent,
    analytics_report,
    integer,
    required,
)
from ugc_bot.domain.campaigns import CampaignConflict, digest
from ugc_bot.domain.financial import utc


@dataclass
class CampaignAnalyticsService:
    repository: Any
    clock: Clock

    async def _begin(
        self,
        actor_id,
        key,
        payload,
        subject_type,
        subject_id,
        principal,
        session,
    ):
        required(key, 256)
        owner = await self.repository.authorize(
            actor_id,
            subject_type,
            subject_id,
            admin=True,
            write=True,
            principal=principal,
            session=session,
        )
        fingerprint = digest(payload)
        previous = await self.repository.command(actor_id, key, session=session)
        if previous and previous["payload_hash"] != fingerprint:
            raise CampaignConflict("analytics_operation_conflict")
        return owner, fingerprint, previous["result"] if previous else None

    async def _save(self, actor_id, key, fingerprint, result, at, session):
        await self.repository.save_command(
            {
                "actor_id": actor_id,
                "operation_key": key,
                "payload_hash": fingerprint,
                "result": result,
                "recorded_at": at,
            },
            session=session,
        )
        return result

    async def publish(
        self, actor_id, key, spec: AnalyticsSourceSpec, *, principal, session
    ):
        if not isinstance(spec, AnalyticsSourceSpec):
            raise ValueError("analytics_source_required")
        document = spec.document()
        owner, fingerprint, previous = await self._begin(
            actor_id,
            key,
            {"action": "publish", **document},
            spec.subject_type,
            spec.subject_id,
            principal,
            session,
        )
        if previous is not None:
            return previous
        sources = await self.repository.sources(session=session)
        if any(
            s["subject_type"] == spec.subject_type
            and s["subject_id"] == spec.subject_id
            and s["document"]["currency"] != spec.currency
            for s in sources
        ):
            raise ValueError("analytics_currency_mismatch")
        voided = {
            a["source_id"]
            for a in await self.repository.actions(session=session)
            if a["action"] == "void"
        }
        if spec.marketing_spend_minor and any(
            s["source_id"] not in voided
            and s["document"]["marketing_spend_minor"]
            and (
                s["document"]["source_name"],
                s["document"]["account_label"],
                s["document"]["budget_reference"],
            )
            == (spec.source_name, spec.account_label, spec.budget_reference)
            for s in sources
        ):
            raise CampaignConflict("analytics_budget_reference_reused")
        at = utc(self.clock.now())
        source_id = uuid5(NAMESPACE_URL, f"ugc:analytics:{actor_id}:{key}")
        await self.repository.append(
            "source",
            {
                "source_id": source_id,
                "subject_type": spec.subject_type,
                "subject_id": spec.subject_id,
                "owner_id": owner,
                "actor_id": actor_id,
                "document": document,
                "recorded_at": at,
            },
            session=session,
        )
        return await self._save(
            actor_id,
            key,
            fingerprint,
            {"source_id": str(source_id), "state": "collecting"},
            at,
            session,
        )

    async def import_events(
        self, actor_id, key, source_id, events, *, principal, session
    ):
        if (
            type(events) is not tuple
            or not 1 <= len(events) <= 1000
            or any(not isinstance(e, MetricEvent) for e in events)
        ):
            raise ValueError("analytics_event_batch_required")
        source = await self.repository.source(source_id, session=session)
        spec = source["document"]
        _, fingerprint, previous = await self._begin(
            actor_id,
            key,
            {
                "action": "import",
                "source_id": str(source_id),
                "events": [e.document() for e in events],
            },
            source["subject_type"],
            source["subject_id"],
            principal,
            session,
        )
        if previous is not None:
            return previous
        actions = await self.repository.actions(session=session)
        if any(a["source_id"] == source_id for a in actions):
            raise CampaignConflict("analytics_source_closed")
        voided = {a["source_id"] for a in actions if a["action"] == "void"}
        rows = [
            row
            for row in await self.repository.events(
                source["subject_type"], source["subject_id"], session=session
            )
            if row["source_id"] not in voided
        ]
        imported = 0
        at = utc(self.clock.now())
        for event in events:
            document = event.document()
            event_hash = digest({"source_id": str(source_id), **document})
            existing = await self.repository.external(
                spec["source_name"],
                spec["account_label"],
                event.external_event_id,
                session=session,
            )
            if existing:
                if existing["payload_hash"] != event_hash:
                    raise CampaignConflict("analytics_event_conflict")
                continue
            self._validate_event(spec, event, rows, at)
            values = {
                "event_id": uuid5(source_id, event.external_event_id),
                "source_id": source_id,
                "source_name": spec["source_name"],
                "account_label": spec["account_label"],
                "external_event_id": event.external_event_id,
                "payload_hash": event_hash,
                "document": document,
                "recorded_at": at,
            }
            await self.repository.append("event", values, session=session)
            rows.append(values)
            imported += 1
        return await self._save(
            actor_id,
            key,
            fingerprint,
            {"source_id": str(source_id), "imported": imported},
            at,
            session,
        )

    def _validate_event(self, spec, event, rows, at):
        occurred = utc(event.occurred_at)
        if (
            not datetime.fromisoformat(spec["attribution_from"])
            <= occurred
            <= datetime.fromisoformat(spec["attribution_until"])
            or occurred > at
        ):
            raise ValueError("analytics_event_outside_attribution")
        coverage = {
            "view": "views",
            "click": "clicks",
            "lead": "leads",
            "sale": "sales",
            "refund": "sales",
        }
        if coverage[event.kind] not in spec["metrics"]:
            raise ValueError("analytics_metric_not_declared")
        documents = [row["document"] for row in rows]
        if event.kind in ("lead", "sale") and any(
            e["kind"] == event.kind and e["entity_id"] == event.entity_id
            for e in documents
        ):
            raise CampaignConflict("analytics_entity_already_recorded")
        if event.kind == "refund":
            sale_row = next(
                (
                    row
                    for row in rows
                    if row["document"]["kind"] == "sale"
                    and row["document"]["entity_id"] == event.entity_id
                ),
                None,
            )
            sale = sale_row["document"] if sale_row else None
            refunded = sum(
                e["amount_minor"]
                for e in documents
                if e["kind"] == "refund" and e["entity_id"] == event.entity_id
            )
            if (
                sale is None
                or (sale_row["source_name"], sale_row["account_label"])
                != (spec["source_name"], spec["account_label"])
                or occurred < datetime.fromisoformat(sale["occurred_at"])
                or refunded + event.amount_minor > sale["amount_minor"]
            ):
                raise ValueError("analytics_refund_evidence_required")

    async def close_source(
        self,
        actor_id,
        key,
        source_id,
        action,
        proof_reference,
        reason,
        *,
        principal,
        session,
    ):
        if action not in ("finalize", "void"):
            raise ValueError("analytics_action_required")
        required(proof_reference)
        required(reason)
        source = await self.repository.source(source_id, session=session)
        _, fingerprint, previous = await self._begin(
            actor_id,
            key,
            {
                "action": action,
                "source_id": str(source_id),
                "proof_reference": proof_reference,
                "reason": reason,
            },
            source["subject_type"],
            source["subject_id"],
            principal,
            session,
        )
        if previous is not None:
            return previous
        at = utc(self.clock.now())
        actions = await self.repository.actions(session=session)
        if any(
            a["source_id"] == source_id and a["action"] == "void"
            for a in actions
        ):
            raise CampaignConflict("analytics_source_closed")
        if (
            action == "finalize"
            and datetime.fromisoformat(source["document"]["attribution_until"])
            > at
        ):
            raise ValueError("analytics_future_coverage_unconfirmed")
        if not any(
            a["source_id"] == source_id and a["action"] == action
            for a in actions
        ):
            await self.repository.append(
                "action",
                {
                    "action_id": uuid5(source_id, action),
                    "source_id": source_id,
                    "actor_id": actor_id,
                    "action": action,
                    "proof_reference": proof_reference,
                    "reason": reason,
                    "recorded_at": at,
                },
                session=session,
            )
        return await self._save(
            actor_id,
            key,
            fingerprint,
            {"source_id": str(source_id), "state": action},
            at,
            session,
        )

    async def report(
        self, actor_id, subject_type, subject_id, *, principal, session
    ):
        await self.repository.snapshot(session=session)
        await self.repository.authorize(
            actor_id,
            subject_type,
            subject_id,
            admin=False,
            write=False,
            principal=principal,
            session=session,
        )
        sources = await self.repository.sources(
            subject_type, subject_id, session=session
        )
        actions = await self.repository.actions(session=session)
        voided = {a["source_id"] for a in actions if a["action"] == "void"}
        finalized = {
            a["source_id"] for a in actions if a["action"] == "finalize"
        }
        active = [s for s in sources if s["source_id"] not in voided]
        ids = {s["source_id"] for s in active}
        events = [
            e["document"]
            for e in await self.repository.events(
                subject_type, subject_id, session=session
            )
            if e["source_id"] in ids
        ]
        result = analytics_report(
            [s["document"] for s in active],
            events,
            complete=bool(active) and ids <= finalized,
        )
        pilots = await self.repository.pilots(session=session)
        return {
            **result,
            "subject_type": subject_type,
            "subject_id": str(subject_id),
            "currency": active[0]["document"]["currency"] if active else None,
            "sources": [
                {
                    "source_id": str(s["source_id"]),
                    "source_name": s["document"]["source_name"],
                    "provenance": "manual_import",
                    "finalized": s["source_id"] in finalized,
                }
                for s in active
            ],
            "paid_pilot_campaigns": len(pilots),
            "commercial_validation_confirmed": len(pilots) >= 2,
            "as_of": utc(self.clock.now()).isoformat(),
        }

    async def record_paid_pilot(
        self,
        actor_id,
        key,
        subject_type,
        subject_id,
        payment_reference,
        paid_minor,
        currency,
        proof_reference,
        *,
        principal,
        session,
    ):
        required(payment_reference, 256)
        required(proof_reference)
        integer(paid_minor, 1)
        if currency not in TWO_DECIMAL_CURRENCIES:
            raise ValueError("analytics_currency_required")
        payload = {
            "action": "paid_pilot",
            "subject_type": subject_type,
            "subject_id": str(subject_id),
            "payment_reference": payment_reference,
            "paid_minor": paid_minor,
            "currency": currency,
            "proof_reference": proof_reference,
        }
        _, fingerprint, previous = await self._begin(
            actor_id, key, payload, subject_type, subject_id, principal, session
        )
        if previous is not None:
            return previous
        if any(
            p["payment_reference"] == payment_reference
            or (p["subject_type"], p["subject_id"])
            == (subject_type, subject_id)
            for p in await self.repository.pilots(session=session)
        ):
            raise CampaignConflict("analytics_pilot_evidence_reused")
        at = utc(self.clock.now())
        await self.repository.append(
            "pilot",
            {
                "pilot_id": uuid5(
                    NAMESPACE_URL,
                    f"analytics-pilot:{subject_type}:{subject_id}",
                ),
                "subject_type": subject_type,
                "subject_id": subject_id,
                "actor_id": actor_id,
                "payment_reference": payment_reference,
                "paid_minor": paid_minor,
                "currency": currency,
                "proof_reference": proof_reference,
                "recorded_at": at,
            },
            session=session,
        )
        return await self._save(
            actor_id,
            key,
            fingerprint,
            {"subject_id": str(subject_id), "recorded": True},
            at,
            session,
        )
