"""Append-only correction storage and immutable original source loading.

No command service, bank authority, live runtime guard or ledger producer is
installed here. All methods require their caller's existing transaction.
"""

from contextlib import asynccontextmanager
from dataclasses import asdict, replace
from dataclasses import fields as dataclass_fields
from uuid import UUID

from sqlalchemy import insert, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ugc_bot.application.correction_ports import (
    CorrectionActor,
    CorrectionFact,
    CorrectionFacts,
    CorrectionReadAuthority,
    CorrectionScope,
    RecordManualRefundObservation,
    RequestSelectionRefund,
    correction_command_id,
)
from ugc_bot.domain.corrections import (
    CapturedSelectionComponent,
    ComponentFunding,
    CorrectionEvent,
    CorrectionState,
    SelectionRefundBundle,
    replay_correction_events,
)
from ugc_bot.domain.entities import OutboxEvent
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.correction_approval_models import (
    TABLE_MAP as APPROVAL_TABLE_MAP,
)
from ugc_bot.infrastructure.db.correction_models import TABLE_MAP
from ugc_bot.infrastructure.db.identity_history_schema import (
    HISTORY_SNAPSHOT_LOCK_SQL,
)
from ugc_bot.infrastructure.db.repositories.financial_capture import intent_id
from ugc_bot.infrastructure.db.repositories.financial_items import (
    SqlAlchemyFinancialItemRepository,
    _session,
)
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    SqlAlchemyFinancialLedgerRepository,
    _canonical,
    payload_hash,
)
from ugc_bot.infrastructure.db.repositories.selection_delivery_funding import (
    SqlAlchemySelectionFundingRepository,
)


async def _rows(db, name, **where):
    table = Base.metadata.tables[name]
    return (await db.execute(select(table).filter_by(**where))).mappings().all()


def _state(value):
    return CorrectionState(
        **(
            value
            | {
                "case_id": UUID(value["case_id"]),
                "observation_ids": tuple(
                    UUID(i) for i in value["observation_ids"]
                ),
                "blockers": tuple(value["blockers"]),
            }
        )
    )


class SqlAlchemyCorrectionRepository:
    async def read_authority(self, scope, *, operation_key=None, session):
        db, bindings, action = _session(session), {}, None
        current_client_id = None
        if scope.order_id is not None:
            table = Base.metadata.tables["orders"]
            current_client_id = await db.scalar(
                select(table.c.advertiser_id).where(
                    table.c.order_id == scope.order_id
                )
            )
        if scope.case_id is not None:
            for name, prefix in (("requests", "request"), ("cases", "case")):
                table = TABLE_MAP[name]
                row = (
                    (
                        await db.execute(
                            select(table.c.client_id, table.c.order_id).where(
                                table.c.case_id == scope.case_id
                            )
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if row is not None:
                    bindings.update(
                        {
                            f"{prefix}_{key}": row[key]
                            for key in ("client_id", "order_id")
                        }
                    )
        if operation_key is not None:
            table = TABLE_MAP["commands"]
            action = await db.scalar(
                select(table.c.action).where(
                    table.c.actor_id == scope.actor_id,
                    table.c.operation_key == operation_key,
                )
            )
        return CorrectionReadAuthority(
            current_client_id=current_client_id,
            action=action,
            **bindings,
        )

    async def actor(self, actor_id, *, session):
        rows = await _rows(_session(session), "users", user_id=actor_id)
        if not rows:
            return None
        return CorrectionActor(
            **{
                key: rows[0][key]
                for key in (
                    "user_id",
                    "telegram_id",
                    "max_id",
                    "status",
                    "admin",
                )
            }
        )

    async def discover_case_scope(self, actor_id, case_id, *, session):
        db = _session(session)
        requests = (
            await _rows(db, TABLE_MAP["requests"].name, case_id=case_id)
            if case_id
            else ()
        )
        cases = (
            await _rows(db, TABLE_MAP["cases"].name, case_id=case_id)
            if case_id
            else ()
        )
        order_id = (
            requests[0]["order_id"]
            if requests
            else (cases[0]["order_id"] if cases else None)
        )
        selected = (
            tuple(UUID(i) for i in requests[0]["paid_item_ids"])
            if requests
            else ()
        )
        return await self._discover(actor_id, order_id, case_id, selected, db)

    async def discover_operation_scope(
        self, actor_id, operation_key, *, session
    ):
        table = TABLE_MAP["commands"]
        case = await _session(session).scalar(
            select(table.c.result["case_id"].as_string()).where(
                table.c.actor_id == actor_id,
                table.c.operation_key == operation_key,
            )
        )
        case_id = UUID(case) if case else None
        return await self.discover_case_scope(
            actor_id, case_id, session=session
        )

    async def facts(self, scope, *, session):
        db, records = _session(session), []
        command_ids = set()
        if scope.case_id is not None:
            for kind in (
                "cases",
                "requests",
                "intents",
                "observations",
                "matches",
                "events",
            ):
                for row in await _rows(
                    db, TABLE_MAP[kind].name, case_id=scope.case_id
                ):
                    records.append(CorrectionFact.from_values(kind, row))
                    command_ids.add(row["command_id"])
            approval_records, approval_commands = await self._approval_facts(
                scope.case_id, db
            )
            records.extend(approval_records)
            command_ids.update(approval_commands)
        for command_id in sorted(command_ids):
            for row in await _rows(
                db, TABLE_MAP["commands"].name, command_id=command_id
            ):
                records.append(CorrectionFact.from_values("commands", row))
        if scope.payment_id is not None:
            for row in await _rows(db, "payments", payment_id=scope.payment_id):
                records.append(
                    CorrectionFact.from_values(
                        "payments",
                        {
                            key: row[key]
                            for key in (
                                "payment_id",
                                "order_id",
                                "provider",
                                "status",
                                "external_id",
                                "currency",
                                "captured_minor",
                                "paid_at",
                            )
                        },
                    )
                )
        if scope.intent_id is not None:
            for row in await _rows(
                db, "outbox_events", event_id=scope.intent_id
            ):
                records.append(
                    CorrectionFact.from_values(
                        "invoice",
                        {
                            key: row[key]
                            for key in (
                                "event_id",
                                "event_type",
                                "aggregate_id",
                                "aggregate_type",
                                "payload",
                            )
                        },
                    )
                )
        return CorrectionFacts(records=tuple(records))

    @staticmethod
    async def _approval_facts(case_id, db):
        records, commands = [], set()
        for row in await _rows(
            db, APPROVAL_TABLE_MAP["approvals"].name, case_id=case_id
        ):
            records.append(CorrectionFact.from_values("approvals", row))
            commands.add(row["command_id"])
        links, matches = (
            APPROVAL_TABLE_MAP["match_approvals"],
            TABLE_MAP["matches"],
        )
        linked = (
            (
                await db.execute(
                    select(links)
                    .join(matches, matches.c.match_id == links.c.match_id)
                    .where(matches.c.case_id == case_id)
                )
            )
            .mappings()
            .all()
        )
        records.extend(
            CorrectionFact.from_values("match_approvals", row) for row in linked
        )
        return records, commands

    async def _routing(self, command, db):
        if isinstance(command, RequestSelectionRefund):
            return (
                command.order_id,
                command.existing_case_id,
                command.paid_item_ids,
            )
        case_id = command.case_id
        requests = (
            await _rows(db, TABLE_MAP["requests"].name, case_id=case_id)
            if case_id
            else ()
        )
        if requests:
            request = requests[0]
            return (
                request["order_id"],
                case_id,
                tuple(UUID(i) for i in request["paid_item_ids"]),
            )
        if isinstance(command, RecordManualRefundObservation):
            order_id = command.known_order_id
            if order_id is None and command.known_capture_intent_id is not None:
                rows = await _rows(
                    db,
                    "outbox_events",
                    event_id=command.known_capture_intent_id,
                )
                if rows and rows[0]["event_type"] == "financial.capture_intent":
                    order_id = UUID(rows[0]["aggregate_id"])
            return order_id, case_id, ()
        return None, case_id, ()

    async def discover_scope(self, command, *, session):
        db = _session(session)
        order_id, case_id, selected = await self._routing(command, db)
        scope = await self._discover(
            command.actor_id, order_id, case_id, selected, db
        )
        if isinstance(
            command, RequestSelectionRefund
        ) and scope.client_id not in (None, command.actor_id):
            return replace(
                scope, unavailable_reason="correction_own_client_required"
            )
        return scope

    async def _discover(self, actor_id, order_id, case_id, selected, db):
        fields = dict(
            actor_id=actor_id,
            prospective_user_ids=(actor_id,),
            wallet_user_ids=(),
            source_hash=None,
            order_id=order_id,
            case_id=case_id,
            selected_paid_item_ids=selected,
        )
        cases = (
            await _rows(db, TABLE_MAP["cases"].name, case_id=case_id)
            if case_id
            else ()
        )
        requests = (
            await _rows(db, TABLE_MAP["requests"].name, case_id=case_id)
            if case_id
            else ()
        )
        request_source = [
            {
                key: row[key]
                for key in (
                    "request_id",
                    "order_id",
                    "client_id",
                    "paid_item_ids",
                    "source_hash",
                    "bundle",
                )
            }
            for row in requests
        ]
        case_source = [
            {key: row[key] for key in ("case_id", "order_id", "client_id")}
            for row in cases
        ]
        fields.update(
            prospective_user_ids=tuple(
                sorted(
                    {
                        actor_id,
                        *(
                            row["client_id"]
                            for row in cases
                            if row["client_id"] is not None
                        ),
                    }
                )
            ),
            source_hash=payload_hash(
                dict(cases=case_source, requests=request_source)
            )
            if cases or requests
            else None,
        )
        orders = (
            await _rows(db, "orders", order_id=order_id) if order_id else ()
        )
        if not orders:
            return CorrectionScope(
                **fields, unavailable_reason="correction_order_missing"
            )
        order = orders[0]
        fields["client_id"] = order["advertiser_id"]
        items = await _rows(db, "order_items", order_id=order_id)
        items = sorted(items, key=lambda row: row["ordinal"])
        ids = {i["paid_item_id"] for i in items}
        assignments = await self._item_rows(db, "item_assignments", ids)
        deliveries = await self._item_rows(
            db, "paid_selection_accepted_deliveries", ids
        )
        grounds = await self._item_rows(db, "financial_obligations", ids)
        users = {*fields["prospective_user_ids"], order["advertiser_id"]}
        wallets = {ground["recipient_id"] for ground in grounds}
        for assignment in assignments:
            users.update(
                i
                for i in (assignment["creator_id"], assignment["manager_id"])
                if i
            )
        managers = await _rows(db, "manager_orders", order_id=order_id)
        users.update(manager["user_id"] for manager in managers)
        captures = await _rows(
            db,
            "outbox_events",
            aggregate_id=str(order_id),
            event_type="financial.client_snapshot_requested",
        )
        if captures:
            referrer = captures[0]["payload"].get("client_referrer_id")
            if referrer:
                wallets.add(UUID(referrer))
        users.update(wallets)
        fields.update(
            prospective_user_ids=tuple(sorted(users)),
            wallet_user_ids=tuple(sorted(wallets)),
            ground_ids=tuple(ground["id"] for ground in grounds),
        )
        if not selected:
            fields["source_hash"] = payload_hash(
                dict(
                    order={
                        key: order[key]
                        for key in (
                            "order_id",
                            "advertiser_id",
                            "financial_version",
                        )
                    },
                    cases=case_source,
                    requests=request_source,
                    items=[dict(row) for row in items],
                    assignments=[dict(row) for row in assignments],
                    deliveries=[dict(row) for row in deliveries],
                    grounds=[dict(row) for row in grounds],
                    managers=[
                        {key: row[key] for key in ("user_id", "order_id")}
                        for row in managers
                    ],
                    captures=[
                        {
                            key: row[key]
                            for key in (
                                "event_id",
                                "event_type",
                                "aggregate_id",
                                "aggregate_type",
                                "payload",
                            )
                        }
                        for row in captures
                    ],
                )
            )
        if not selected or not set(selected) <= ids:
            return CorrectionScope(
                **fields,
                unavailable_reason="correction_selected_routing_unavailable",
            )
        if len(captures) != 1:
            return CorrectionScope(
                **fields, unavailable_reason="correction_capture_unavailable"
            )
        try:
            source = OutboxEvent(
                **{
                    field.name: captures[0][field.name]
                    for field in dataclass_fields(OutboxEvent)
                }
            )
            capture = await SqlAlchemySelectionFundingRepository().load_capture(
                source, session=db
            )
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            return CorrectionScope(
                **fields,
                unavailable_reason="correction_gross_source_unavailable:"
                + type(error).__name__,
            )
        allocations = await _rows(
            db, "payment_item_allocations", payment_id=capture.payment_id
        )
        intake = await _rows(db, "order_intake_receipts", order_id=order_id)
        selected_rows = [i for i in items if i["paid_item_id"] in selected]
        components = []
        for item in selected_rows:
            allocation = next(
                a
                for a in allocations
                if a["paid_item_id"] == item["paid_item_id"]
                and a["component"] == "selection"
            )
            due_hash = self._due_hash(item, intake, order)
            components.append(
                CapturedSelectionComponent(
                    allocation_key=allocation["allocation_key"],
                    payment_id=capture.payment_id,
                    paid_item_id=item["paid_item_id"],
                    gross_minor=allocation["amount_minor"],
                    currency=allocation["currency"],
                    selection_due_at=item["selection_due_at"],
                    due_evidence_hash=due_hash,
                    assignment_ids=tuple(
                        a["assignment_id"]
                        for a in assignments
                        if a["paid_item_id"] == item["paid_item_id"]
                    ),
                    accepted_delivery_ids=tuple(
                        d["delivery_id"]
                        for d in deliveries
                        if d["paid_item_id"] == item["paid_item_id"]
                    ),
                )
            )
        bundle = SelectionRefundBundle(components=tuple(components))
        digest = payload_hash(
            dict(
                capture_source_hash=capture.source_hash,
                selected_items=[dict(i) for i in selected_rows],
                bundle=asdict(bundle),
                assignments=[
                    dict(a)
                    for a in assignments
                    if a["paid_item_id"] in selected
                ],
                deliveries=[
                    dict(d) for d in deliveries if d["paid_item_id"] in selected
                ],
                grounds=[
                    dict(g) for g in grounds if g["paid_item_id"] in selected
                ],
                intake=[dict(i) for i in intake],
            )
        )
        fields.update(
            intent_id=intent_id(order_id),
            capture_id=capture.event_id,
            payment_id=capture.payment_id,
            captured_at=capture.captured_at,
            quote_key=items[0]["quote_key"],
            terms_reference=items[0]["quote_payload"].get("terms_reference"),
            bundle=bundle,
            source_hash=digest,
        )
        reason = self._source_refusal(components, grounds, selected)
        return CorrectionScope(**fields, unavailable_reason=reason)

    @staticmethod
    def _source_refusal(components, grounds, selected):
        if any(c.due_evidence_hash is None for c in components):
            return "correction_due_agreement_unavailable"
        if any(
            g["kind"] != "client_referral" and g["paid_item_id"] in selected
            for g in grounds
        ):
            return "correction_creator_manager_ground_unsupported"
        return None

    @staticmethod
    async def _item_rows(db, name, ids):
        table = Base.metadata.tables[name]
        return (
            (
                await db.execute(
                    select(table)
                    .where(table.c.paid_item_id.in_(ids))
                    .order_by(table.c.paid_item_id)
                )
            )
            .mappings()
            .all()
        )

    @staticmethod
    def _due_hash(item, intake, order):
        if len(intake) != 1:
            return None
        receipt = intake[0]
        result = receipt["result"]
        quote = item["quote_payload"]
        if (
            receipt["client_id"] != order["advertiser_id"]
            or result.get("selection_due_at")
            != utc(item["selection_due_at"]).isoformat()
            or quote.get("selection_due_at") != result.get("selection_due_at")
            or result.get("terms_reference") != quote.get("terms_reference")
            or result.get("policy_version") != item["policy_version"]
            or len(result.get("items", ())) != 30
        ):
            return None
        return payload_hash(
            dict(
                receipt=dict(receipt), quote=quote, due=item["selection_due_at"]
            )
        )

    async def load_scope(self, scope, *, session):
        if not scope.selected_paid_item_ids and scope.available:
            raise ValueError("correction_selected_routing_unavailable")
        current = await self._discover(
            scope.actor_id,
            scope.order_id,
            scope.case_id,
            scope.selected_paid_item_ids,
            _session(session),
        )
        if current != scope:
            raise ValueError("correction_scope_changed_retry_required")
        return current

    async def prepare_users(self, scope, *, session):
        await SqlAlchemyFinancialLedgerRepository().lock_recipients(
            scope.prospective_user_ids, session=_session(session)
        )

    async def lock_scope(self, scope, *, session):
        await self.prepare_users(scope, session=session)
        await self.lock_prepared_scope(scope, session=session)

    async def lock_prepared_scope(self, scope, *, session):
        db = _session(session)
        await SqlAlchemyFinancialLedgerRepository().lock_wallets(
            tuple((user, "RUB") for user in scope.wallet_user_ids), session=db
        )
        await self.load_scope(scope, session=db)
        if scope.order_id is not None:
            await SqlAlchemyFinancialItemRepository().lock_order(
                scope.order_id, session=db
            )
            for name, key, identity in (
                ("orders", "order_id", scope.order_id),
                ("payments", "payment_id", scope.payment_id),
            ):
                if identity is not None:
                    table = Base.metadata.tables[name]
                    await db.execute(
                        select(table)
                        .where(table.c[key] == identity)
                        .with_for_update()
                    )
        await db.execute(text(HISTORY_SNAPSHOT_LOCK_SQL))
        if scope.selected_paid_item_ids:
            table = Base.metadata.tables["order_items"]
            await db.execute(
                select(table)
                .where(table.c.paid_item_id.in_(scope.selected_paid_item_ids))
                .order_by(table.c.paid_item_id)
                .with_for_update()
            )
        if scope.case_id is not None:
            table = TABLE_MAP["cases"]
            await db.execute(
                select(table)
                .where(table.c.case_id == scope.case_id)
                .with_for_update()
            )
        await self.load_scope(scope, session=db)

    async def command(self, actor_id, operation_key, *, session):
        rows = await _rows(
            _session(session),
            TABLE_MAP["commands"].name,
            actor_id=actor_id,
            operation_key=operation_key,
        )
        return dict(rows[0]) if rows else None

    async def save_command(self, command, payload_hash, result, *, session):
        await _session(session).execute(
            insert(TABLE_MAP["commands"]).values(
                command_id=correction_command_id(command),
                actor_id=command.actor_id,
                operation_key=command.operation_key,
                action=type(command).__name__,
                payload_hash=payload_hash,
                result=_canonical(result),
                recorded_at=text("CURRENT_TIMESTAMP"),
            )
        )

    async def append_fact(self, name, values, *, session):
        if name in ("commands", "events", "states"):
            raise ValueError("correction_fact_writer_required")
        await _session(session).execute(
            insert(
                (
                    APPROVAL_TABLE_MAP
                    if name in APPROVAL_TABLE_MAP
                    else TABLE_MAP
                )[name]
            ).values(**values)
        )

    @asynccontextmanager
    async def application_savepoint(self, *, session):
        db = _session(session)
        async with db.begin_nested():
            yield session
            await db.execute(
                text("SET CONSTRAINTS correction_application_guard IMMEDIATE")
            )
            await db.execute(
                text("SET CONSTRAINTS correction_application_guard DEFERRED")
            )

    async def state_authority(self, case_id, *, session):
        db = _session(session)
        events = await _rows(db, TABLE_MAP["events"].name, case_id=case_id)
        projections = await _rows(db, TABLE_MAP["states"].name, case_id=case_id)
        if not events:
            return None, not projections
        try:
            replayed = replay_correction_events(
                tuple(
                    CorrectionEvent(
                        **(
                            dict(e)
                            | {"result_state": _state(e["result_state"])}
                        )
                    )
                    for e in sorted(events, key=lambda e: e["version"])
                )
            )
            valid = (
                bool(projections)
                and _state(projections[0]["result_state"]) == replayed
                and projections[0]["version"] == replayed.version
                and projections[0]["result_state_hash"] == replayed.payload_hash
                and projections[0]["event_id"]
                == max(events, key=lambda e: e["version"])["event_id"]
            )
            return replayed, valid
        except (ValueError, TypeError, KeyError):
            return None, False

    async def append_event(self, event, *, session):
        db = _session(session)
        previous, valid = await self.state_authority(event.case_id, session=db)
        if (
            not valid
            or event.version != (previous.version + 1 if previous else 1)
            or event.previous_state_hash
            != (previous.payload_hash if previous else None)
        ):
            raise ValueError("correction_state_unavailable")
        await db.execute(
            insert(TABLE_MAP["events"]).values(
                **(
                    asdict(event)
                    | {"result_state": _canonical(asdict(event.result_state))}
                )
            )
        )
        values = dict(
            case_id=event.case_id,
            event_id=event.event_id,
            version=event.version,
            result_state=_canonical(asdict(event.result_state)),
            result_state_hash=event.result_state_hash,
        )
        await db.execute(
            pg_insert(TABLE_MAP["states"])
            .values(**values)
            .on_conflict_do_update(index_elements=["case_id"], set_=values)
        )

    async def live_funding(self, paid_item_id, *, session):
        db = _session(session)
        allocations = await _rows(
            db, "payment_item_allocations", paid_item_id=paid_item_id
        )
        result = []
        blockers = {}
        for allocation in allocations:
            applied = await _rows(
                db,
                TABLE_MAP["components"].name,
                allocation_key=allocation["allocation_key"],
            )
            order_id = allocation["order_id"]
            if order_id not in blockers:
                blockers[order_id] = await self._funding_blockers(
                    order_id, paid_item_id, db
                )
            unresolved, cases, consistent = blockers[order_id]
            refunded = sum(row["refund_minor"] for row in applied)
            result.append(
                ComponentFunding(
                    allocation_key=allocation["allocation_key"],
                    payment_id=allocation["payment_id"],
                    paid_item_id=paid_item_id,
                    component=allocation["component"],
                    currency=allocation["currency"],
                    gross_minor=allocation["amount_minor"],
                    cumulative_refund_minor=refunded,
                    net_minor=allocation["amount_minor"] - refunded
                    if consistent
                    else None,
                    unresolved_observation_ids=tuple(unresolved),
                    unresolved_case_ids=tuple(cases),
                    state_consistent=consistent,
                )
            )
        return tuple(result)

    async def _funding_blockers(self, order_id, paid_item_id, db):
        """A retained request narrows routing; report hints cannot widen it.

        Early reports with no requested subset retain their actual order or
        invoice scope. Rejection clears only a case with no unapplied report.
        This reader acquires no additional User, wallet or source locks.
        """
        requests = await _rows(
            db, TABLE_MAP["requests"].name, order_id=order_id
        )
        allocations = await _rows(
            db, "payment_item_allocations", order_id=order_id
        )
        item_ids = {row["paid_item_id"] for row in allocations}
        invoice = Base.metadata.tables["outbox_events"]
        invoice_ids = tuple(
            (
                await db.scalars(
                    select(invoice.c.event_id).where(
                        invoice.c.event_type == "financial.capture_intent",
                        invoice.c.aggregate_id == str(order_id),
                    )
                )
            ).all()
        )
        observation = TABLE_MAP["observations"]
        request = TABLE_MAP["requests"]
        case = TABLE_MAP["cases"]
        reports = (
            (
                await db.execute(
                    select(
                        observation,
                        request.c.order_id.label("request_order_id"),
                        request.c.paid_item_ids.label("request_paid_item_ids"),
                        case.c.order_id.label("case_order_id"),
                    )
                    .outerjoin(
                        request, observation.c.case_id == request.c.case_id
                    )
                    .outerjoin(case, observation.c.case_id == case.c.case_id)
                    .where(
                        or_(
                            request.c.order_id == order_id,
                            case.c.order_id == order_id,
                            observation.c.known_order_id == order_id,
                            observation.c.known_capture_intent_id.in_(
                                invoice_ids
                            ),
                        )
                    )
                )
            )
            .mappings()
            .all()
        )
        relevant = []
        cases = set()
        consistent = True
        for row in requests:
            selected = self._funding_selection(row["paid_item_ids"], item_ids)
            if selected is None or paid_item_id in selected:
                cases.add(row["case_id"])
                consistent = consistent and selected is not None
        for row in reports:
            correlated, valid = self._funding_report_scope(
                row, order_id, paid_item_id, item_ids, invoice_ids
            )
            if not correlated:
                continue
            consistent = consistent and valid
            relevant.append(row)
            if row["case_id"] is not None:
                cases.add(row["case_id"])
            else:
                consistent = False
        matched = TABLE_MAP["matches"]
        application = TABLE_MAP["applications"]
        completed = set(
            (
                await db.scalars(
                    select(matched.c.observation_id)
                    .join(
                        application,
                        application.c.match_id == matched.c.match_id,
                    )
                    .where(
                        matched.c.observation_id.in_(
                            tuple(row["observation_id"] for row in relevant)
                        )
                    )
                )
            ).all()
        )
        unresolved = tuple(
            row["observation_id"]
            for row in relevant
            if row["observation_id"] not in completed
        )
        blocked_cases = set()
        for case_id in cases:
            state, valid = await self.state_authority(case_id, session=db)
            valid = valid and state is not None
            consistent = consistent and valid
            own = [row for row in relevant if row["case_id"] == case_id]
            if (
                not valid
                or any(row["observation_id"] not in completed for row in own)
                or (not own and state.review_status != "rejected")
                or state.application_status == "unavailable"
            ):
                blocked_cases.add(case_id)
        return unresolved, tuple(blocked_cases), consistent

    @classmethod
    def _funding_report_scope(
        cls, row, order_id, paid_item_id, item_ids, invoices
    ):
        if row["request_order_id"] is not None:
            if row["request_order_id"] != order_id:
                return False, True
            selected = cls._funding_selection(
                row["request_paid_item_ids"], item_ids
            )
            if selected is None:
                return True, False
            return paid_item_id in selected, True
        if row["case_order_id"] is not None:
            return row["case_order_id"] == order_id, True
        return (
            row["known_order_id"] == order_id
            or row["known_capture_intent_id"] in invoices,
            True,
        )

    @staticmethod
    def _funding_selection(values, item_ids):
        try:
            if type(values) is not list or not 1 <= len(values) <= 30:
                return None
            selected = tuple(UUID(value) for value in values)
            if (
                len(set(selected)) != len(selected)
                or not set(selected) <= item_ids
            ):
                return None
            return selected
        except (ValueError, TypeError, AttributeError):
            return None
