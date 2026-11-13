"""Telegram review using the existing paid-position settlement rules."""

from datetime import timedelta
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from ugc_bot.application.collaboration_ports import (
    CollaborationCommand,
    record_from_payload,
)
from ugc_bot.application.replacement_ports import (
    ReplacementContact,
    ReplacementRequest,
)
from ugc_bot.application.services.customer_workflow_common import (
    CustomerWorkflowService,
)
from ugc_bot.domain.enums import OrderStatus
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db.models import OrderModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session

REASONS = {"no_answer", "refused", "not_done", "other"}
FINAL_WORK = {"success_final", "available", "rejected", "unconfirmed_expired"}
FEEDBACK_WINDOW = timedelta(days=7)
AUTO_REMINDER_DELAY = timedelta(days=3)


def position_resolved(row, at):
    if row["selection_state"] == "refunded" or row["work_state"] in FINAL_WORK:
        return True
    return (
        row["work_state"] is None
        and row["accompaniment_minor"] == 0
        and row["contact_at"] is not None
        and at
        >= max(row["selection_due_at"], row["contact_at"] + FEEDBACK_WINDOW)
    )


class OrderSummaryService(CustomerWorkflowService):
    def __init__(
        self,
        repository,
        transactions,
        clock,
        summaries,
        collaboration,
        replacement,
        maturity,
    ):
        super().__init__(repository, transactions, clock)
        self.summaries = summaries
        self.collaboration = collaboration
        self.replacement = replacement
        self.maturity = maturity

    def now(self):
        return utc(self.clock.now())

    async def _identity(self, principal, session):
        if principal.platform != "telegram":
            raise PermissionError("telegram_summary_required")
        await self.authorize(principal.user_id, principal, session=session)

    async def view(  # noqa: C901, PLR0912
        self,
        principal,
        order_id,
        *,
        action="open",
        draft_id=None,
        reason=None,
        confirmation=None,
        assignment_id=None,
        report_id=None,
    ):
        if action == "confirm":
            return await self.confirm(principal, order_id, confirmation)
        at, uid = self.now(), principal.user_id
        async with self.transactions.transaction() as session:
            await self._identity(principal, session)
            if order_id is None:
                order_id = (
                    await self.summaries.by_report(report_id, session=session)
                    if report_id
                    else await self.summaries.by_draft(
                        draft_id, session=session
                    )
                )
            # Financial commands share this order-before-item fence. Never hold
            # an item lock while calling the replacement/wallet workflow.
            await _session(session).execute(
                select(OrderModel.order_id)
                .where(OrderModel.order_id == order_id)
                .with_for_update(read=True, key_share=True)
            )
            order, card = await self.summaries.card(
                order_id, uid, at, session=session, lock=True
            )
            if card["closed_at"] and action != "open":
                raise ValueError("summary_order_closed")
            positions = await self.summaries.positions(
                order_id, session=session
            )
            draft = dict(card["draft"])
            if action in {"pick", "save", "discard"} and (
                draft_id is None or card["draft_id"] != draft_id
            ):
                raise ValueError("summary_draft_changed")
            message = None
            if action == "exceptions":
                if not card["draft_id"]:
                    card["draft_id"] = uuid4()
            elif action == "pick":
                row = next(
                    (
                        p
                        for p in positions
                        if p["assignment_id"] == assignment_id
                    ),
                    None,
                )
                if (
                    assignment_id is None
                    or reason not in REASONS
                    or not self.reportable(row)
                ):
                    raise ValueError("summary_position_changed")
                key = str(row["assignment_id"])
                if draft.get(key) == reason:
                    draft.pop(key)
                else:
                    draft[key] = reason
            elif action == "save":
                await self.summaries.lock_positions(order_id, session=session)
                positions = await self.summaries.positions(
                    order_id, session=session
                )
                for row in positions:
                    key = str(row["assignment_id"])
                    if key in draft and self.reportable(row):
                        await self.summaries.add_report(
                            order_id, uid, row, draft[key], at, session=session
                        )
                message = "Отметки сохранены. Статусы появятся в этой карточке."
                draft = {}
                card["draft_id"] = None
            elif action == "discard":
                draft = {}
                card["draft_id"] = None
            elif action in {"remind1", "remind3", "remind7"}:
                job = await self.summaries.add_job(
                    order_id,
                    uid,
                    "reminder",
                    at + timedelta(days=int(action[-1])),
                    requested=True,
                    session=session,
                )
                message = (
                    "Напоминание запланировано."
                    if job
                    else "Напоминание по этому заказу уже назначено."
                )
            elif action == "withdraw":
                await self._withdraw(
                    uid, order_id, positions, report_id, session
                )
                message = "Отметка снята."
            await self.summaries.patch_card(
                order_id,
                draft=draft,
                draft_id=card["draft_id"],
                updated_at=at,
                **({"responded_at": at} if action == "save" else {}),
                session=session,
            )
            return await self._snapshot(order, card, draft, message, session)

    async def _snapshot(self, order, card, draft, message, session):
        positions = await self.summaries.positions(
            order.order_id, session=session
        )
        used, closed, reminder = await self.summaries.counters(
            order.order_id, session=session
        )
        return dict(
            order_id=order.order_id,
            client_id=order.advertiser_id,
            positions=positions,
            used=used,
            limit=len(positions) // 5,
            closed=closed
            or order.status == OrderStatus.CLOSED
            or all(
                row["contact_delivered"] or row["selection_state"] == "refunded"
                for row in positions
            ),
            selection_closed=closed,
            work_closed=bool(card and card["closed_at"]),
            draft_id=card["draft_id"] if card else None,
            draft=draft,
            message_id=card["message_id"] if card else None,
            message=message,
            reminder=reminder,
        )

    async def read(self, order_id, client_id, *, session):
        order, card = await self.summaries.card(
            order_id, client_id, self.now(), session=session
        )
        return await self._snapshot(
            order, card, card["draft"] if card else {}, None, session
        )

    def is_resolved(self, data):
        return data["work_closed"] or all(
            position_resolved(row, self.now())
            and row["report_state"] not in {"queued", "waiting", "review"}
            for row in data["positions"]
        )

    async def record_card_delivery(
        self, order_id, client_id, message_id, *, session
    ):
        if await self.summaries.adopt_message(
            order_id, client_id, message_id, session=session
        ):
            await self.summaries.add_job(
                order_id,
                client_id,
                "reminder",
                self.now() + AUTO_REMINDER_DELAY,
                session=session,
            )

    async def close_if_resolved(self, order_id, client_id):  # noqa: C901
        # Reuse closure/settlement rules; never turn a feedback flag into proof.
        at = self.now()
        async with self.transactions.transaction() as session:
            claimed = await self.summaries.claim_closing(
                order_id, at, session=session
            )
            if not claimed:
                return
        async with self.transactions.transaction() as session:
            snapshot = await self.maturity.repository.load(
                order_id, session=session
            )
            if not all(item.resolved_at for item in snapshot.positions):
                order, card = await self.summaries.card(
                    order_id, client_id, at, session=session, lock=True
                )
                if not card["completion_notified_at"]:
                    positions = await self.summaries.positions(
                        order_id, session=session
                    )
                    unresolved = {
                        item.paid_item_id
                        for item in snapshot.positions
                        if not item.resolved_at
                    }
                    if positions and at >= max(
                        row["selection_due_at"] for row in positions
                    ):
                        await self.summaries.enqueue_review(
                            order_id,
                            client_id,
                            "selection-deadline",
                            [
                                {
                                    "paid_item_id": str(item_id),
                                    "reason": "contact_or_refund_unconfirmed",
                                }
                                for item_id in sorted(unresolved, key=str)
                            ],
                            at,
                            session=session,
                        )
                        await self.summaries.patch_card(
                            order_id,
                            completion_notified_at=at,
                            session=session,
                        )
                return
            rules = snapshot.policy.refund_rules
            if snapshot.policy.maturity_mode == "per_item_v1" or (
                rules is not None and rules.selection_closure_mode != "manual"
            ):
                await self.maturity.refresh(order_id, session=session)
        async with self.transactions.transaction() as session:
            db = _session(session)
            await self.maturity.repository.lock_order(order_id, session=session)
            order = await db.get(OrderModel, order_id, with_for_update=True)
            if (
                order is None
                or order.advertiser_id != client_id
                or order.status not in (OrderStatus.ACTIVE, OrderStatus.CLOSED)
            ):
                return
            locked = await self.summaries.lock_positions(
                order_id, session=session
            )
            current = await self.maturity.repository.load(
                order_id, session=session
            )
            refunded = {
                p.paid_item_id for p in current.positions if p.refunded_at
            }
            data = await self.read(order_id, client_id, session=session)
            if not all(p.resolved_at for p in current.positions) or any(
                row["paid_item_id"] not in refunded
                and (
                    not position_resolved(row, at)
                    or row["report_state"] in {"queued", "waiting", "review"}
                )
                for row in data["positions"]
            ):
                return
            if (
                rules is not None
                and rules.selection_closure_mode == "manual"
                and not data["selection_closed"]
            ):
                return
            for item_id in locked:
                if item_id not in refunded:
                    await self.replacement.repository.require_clear(
                        item_id, session=session
                    )
            if order.status == OrderStatus.ACTIVE:
                order.status = OrderStatus.CLOSED
                order.completed_at = at
                order.updated_at = at
                order.dispatch_stopped = True
            await self.summaries.patch_card(
                order_id, closed_at=at, session=session
            )

    async def replacement_order(self, principal, replacement_id):
        async with self.transactions.transaction() as session:
            await self._identity(principal, session)
            scope = await self.replacement.repository.allocation(
                replacement_id, session=session
            )
            if scope is None:
                raise ValueError("replacement_allocation_not_found")
            order_id = await self.summaries.order_for_position(
                scope["paid_item_id"], session=session
            )
            await self.summaries.card(
                order_id, principal.user_id, self.now(), session=session
            )
            return order_id

    @staticmethod
    def reportable(row):
        return (
            row is not None
            and row["assignment_id"] is not None
            and row["contact_delivered"]
            and row["report_state"] is None
            and row["work_state"]
            not in {"success_final", "available", "rejected"}
        )

    @staticmethod
    def confirmable(row, client_id):
        if row["work_state"] != "success_claimed" or row["report_state"] in {
            "queued",
            "waiting",
            "review",
        }:
            return False
        work = record_from_payload(row["record_payload"]).collaboration
        return (
            work.claimant_id == row["creator_id"]
            and work.claimant_id != client_id
        )

    def confirmation_key(self, positions, client_id):
        facts = "|".join(
            f"{row['assignment_id']}:{row['work_version']}"
            for row in positions
            if self.confirmable(row, client_id)
        )
        return sha256(facts.encode()).hexdigest()[:16]

    async def confirm(self, principal, order_id, confirmation):
        uid = principal.user_id
        data = await self.view(principal, order_id)
        if data["work_closed"]:
            raise ValueError("summary_order_closed")
        rows = data["positions"]
        if confirmation != self.confirmation_key(rows, uid):
            raise ValueError("summary_confirmation_changed")
        count = 0
        for row in rows:
            if not self.confirmable(row, uid):
                continue
            try:
                async with self.transactions.transaction() as session:
                    repo = self.collaboration.repository
                    scope = await repo.prepare_principal_scope(
                        row["assignment_id"], uid, principal, session=session
                    )
                    current = await self.summaries.assignment_report_state(
                        row["assignment_id"], session=session
                    )
                    if scope is None or current in {
                        "queued",
                        "waiting",
                        "review",
                    }:
                        continue
                    await self.collaboration.execute(
                        CollaborationCommand(
                            assignment_id=row["assignment_id"],
                            action="agree",
                            operation_key=f"telegram-summary:agree:{row['work_version']}",
                            expected_version=row["work_version"],
                            actor_id=uid,
                        ),
                        expected_scope=scope,
                        session=session,
                    )
                count += 1
            except (ValueError, PermissionError):
                # The position changed after the customer opened the preview.
                continue
        async with self.transactions.transaction() as session:
            await self.summaries.patch_card(
                order_id, responded_at=self.now(), session=session
            )
            return (await self.read(order_id, uid, session=session)) | {
                "message": f"Подтверждено результатов: {count}."
            }

    async def _withdraw(
        self, client_id, order_id, positions, report_id, session
    ):
        row = next((p for p in positions if p["report_id"] == report_id), None)
        if row is None or row["report_id"] is None:
            raise ValueError("summary_report_unavailable")
        report = await self.summaries.report(
            row["report_id"], lock=True, session=session
        )
        if (report["client_id"], report["order_id"]) != (
            client_id,
            order_id,
        ) or report["state"] not in {"queued", "waiting", "review", "answered"}:
            raise ValueError("summary_report_unavailable")
        await self.summaries.set_report(
            report["report_id"], state="withdrawn", session=session
        )

    async def contact(self, principal, replacement_id):
        order_id = await self.replacement_order(principal, replacement_id)
        async with self.transactions.transaction() as session:
            # ReplacementService takes the canonical user/wallet/order locks.
            result = await self.replacement.contact(
                ReplacementContact(
                    actor_id=principal.user_id,
                    replacement_id=replacement_id,
                    operation_key=f"telegram-summary-contact:{replacement_id}",
                    reason="Заказчик открыл контакт замены в Telegram.",
                    evidence_reference=f"telegram-order-summary:{replacement_id}",
                ),
                principal=principal,
                session=session,
            )
        contact = result["contact"]
        text = "\n".join(
            str(contact[key])
            for key in ("display_name", "telegram", "phone", "instagram_url")
            if contact.get(key)
        )
        return order_id, text

    async def creator_answer(self, principal, report_id):
        if principal.platform != "telegram":
            raise PermissionError("telegram_summary_required")
        async with self.transactions.transaction() as session:
            user = await self.summaries.user(principal.user_id, session=session)
            report = await self.summaries.report(
                report_id, lock=True, session=session
            )
            if (
                user is None
                or user.telegram_id != principal.external_id
                or report is None
                or report["creator_id"] != principal.user_id
            ):
                raise PermissionError("summary_report_unavailable")
            at = self.now()
            due = report["answer_due_at"]
            if report["state"] in {"queued", "waiting", "review"} and (
                due is None or at < due
            ):
                await self.summaries.set_report(
                    report_id, state="answered", answered_at=at, session=session
                )
                return True
            return report["state"] == "answered"

    async def replace_report(self, report):  # noqa: C901
        if report["state"] != "waiting":
            await self.mark_review(report, "delivery_unconfirmed")
            return
        try:
            async with self.transactions.transaction() as session:
                scope = await self.replacement.repository.load_scope(
                    report["paid_item_id"], session=session
                )
                if scope.assignment_id != report["assignment_id"]:
                    raise ValueError("replacement_assignment_obsolete")
                if scope.replacement_count >= scope.original_paid_pool // 5:
                    raise ValueError("replacement_reserve_limit_reached")
                candidates = (
                    await self.replacement.repository.automatic_candidates(
                        scope.order_id, session=session
                    )
                )
            for candidate in candidates:
                try:
                    async with self.transactions.transaction() as session:
                        await self.replacement.replace_unresponsive(
                            ReplacementRequest(
                                actor_id=scope.client_id,
                                paid_item_id=scope.paid_item_id,
                                expected_assignment_version=scope.assignment_version,
                                candidate_interest_id=candidate,
                                reason_code="lost_contact",
                                reason=(
                                    "Нет ответа в течение 24 часов "
                                    "после уведомления в Telegram."
                                ),
                                evidence_reference=f"telegram-order-exception:{report['report_id']}",
                                operation_key=f"telegram-auto-replace:{report['report_id']}",
                            ),
                            report["report_id"],
                            session=session,
                        )
                    return
                except ValueError as exc:
                    if str(exc) == "replacement_confirmed_reserve_required":
                        continue
                    if str(exc) == "financial_scope_changed_retry_required":
                        return
                    raise
            raise ValueError("replacement_reserve_empty")
        except (PermissionError, ValueError) as exc:
            await self.mark_review(report, str(exc))
        except DBAPIError as exc:
            # A competing assignment or an authority check may have won.
            if getattr(exc.orig, "sqlstate", "") in {"23505", "23514"}:
                await self.mark_review(
                    report, "replacement_requires_financial_review"
                )
            else:
                raise

    async def mark_review(self, report, reason):
        async with self.transactions.transaction() as session:
            current = await self.summaries.report(
                report["report_id"], lock=True, session=session
            )
            if current["state"] == report["state"]:
                await self.summaries.set_report(
                    report["report_id"],
                    state="review",
                    review_reason=reason[:150],
                    session=session,
                )
