"""One caller transaction persists the requested service before any send."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid5

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.order_intake_ports import OrderIntakeRepository
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyReader,
    FinancialPolicyService,
)
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.config import FinancialConfig
from ugc_bot.domain.financial import utc
from ugc_bot.domain.order_intake import (
    AccompanimentLead,
    EligibleOrderPolicies,
    EligibleOrderPolicy,
    IntakeItem,
    OrderIntakeCommand,
    OrderIntakeReceipt,
    OrderIntakeResult,
)


@dataclass
class OrderIntakeService:
    repository: OrderIntakeRepository
    orders: OrderService
    policies: FinancialPolicyReader
    transactions: TransactionManager
    clock: Clock
    config: FinancialConfig

    async def eligible_policies(
        self,
        client_id: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> EligibleOrderPolicies:
        async with self.transactions.transaction() as session:
            client = await self.repository.lock_client(
                client_id, session=session
            )
            require_current_principal(
                principal,
                client_id,
                client.client_id if client else None,
                client.telegram_id if client else None,
                client.max_id if client else None,
            )
            if (
                client is None
                or client.status != "active"
                or not client.is_advertiser
            ):
                raise PermissionError("active_advertiser_required")
            paused = (
                not self.config.core_enabled
                or not self.config.new_orders_enabled
            )
            if paused or client.currency != "RUB":
                return EligibleOrderPolicies(client.currency, paused, ())
            now = utc(self.clock.now())
            gate = FinancialPolicyService(self.config)
            result = []
            for version in await self.repository.policy_versions(
                now, session=session
            ):
                try:
                    policy = await self.policies.load(version, session=session)
                    approved = gate.validate_for_capture(
                        policy=policy,
                        client_id=client_id,
                        order_created_at=now,
                        financial_version=version,
                        # Eligibility checks no customer deadline or quote.
                        # Actual creation independently validates supplied due.
                        selection_due_at=now + timedelta(seconds=1),
                        currency=client.currency,
                        captured_at=now,
                    )
                except ValueError:
                    continue
                assert approved.effective_from is not None
                assert approved.selection_refund_window is not None
                assert approved.terms_reference is not None
                result.append(
                    EligibleOrderPolicy(
                        approved.version,
                        approved.terms_reference,
                        utc(approved.effective_from),
                        int(approved.selection_refund_window.total_seconds()),
                    )
                )
            return EligibleOrderPolicies(client.currency, paused, tuple(result))

    async def create(
        self,
        command: OrderIntakeCommand,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> OrderIntakeResult:
        if not self.config.core_enabled:
            raise ValueError("financial_disabled")
        repo = self.repository
        async with self.transactions.transaction() as session:
            client = await repo.lock_client(command.client_id, session=session)
            require_current_principal(
                principal,
                command.client_id,
                client.client_id if client else None,
                client.telegram_id if client else None,
                client.max_id if client else None,
            )
            if (
                client is None
                or client.status != "active"
                or not client.is_advertiser
            ):
                raise PermissionError("active_advertiser_required")
            await repo.lock_operation(
                command.client_id, command.operation_key, session=session
            )
            previous = await repo.get_receipt(
                command.client_id, command.operation_key, session=session
            )
            if previous is not None:
                if previous.payload_hash != command.payload_hash:
                    raise ValueError("idempotency_payload_conflict")
                return previous.result
            if not self.config.new_orders_enabled:
                raise ValueError("financial_disabled")
            if client.currency != "RUB":
                raise ValueError("unpublished_currency")
            now = utc(self.clock.now())
            policy = await self.policies.load(
                command.policy_version, session=session
            )
            _, quote = await self.orders.create_financial_order(
                order_id=command.order_id,
                advertiser_id=command.client_id,
                order_type=command.order_type,
                product_link=command.product_link,
                offer_text=command.offer_text,
                barter_description=command.barter_description,
                price=float(command.honorarium),
                policy=policy,
                order_created_at=now,
                now=now,
                selection_due_at=command.selection_due_at,
                currency=client.currency,
                accompaniment_ordinals=command.accompaniment_ordinals
                or frozenset(),
                client_contact_reference=command.contact_reference,
                idempotency_key=command.operation_key,
                session=session,
            )
            lead_id = (
                uuid5(command.request_id, "accompaniment")
                if command.accompaniment_ordinals
                else None
            )
            result = OrderIntakeResult(
                command.request_id,
                quote.order_id,
                now,
                quote.currency,
                quote.policy_version,
                quote.selection_due_at,
                quote.terms_reference,
                tuple(
                    IntakeItem(
                        i.paid_item_id,
                        i.ordinal,
                        i.selection_minor,
                        i.accompaniment_minor,
                    )
                    for i in quote.items
                ),
                lead_id,
            )
            lead = (
                AccompanimentLead(
                    lead_id,
                    command.request_id,
                    quote.order_id,
                    command.client_id,
                    now,
                    command.contact_reference,
                    tuple(sorted(command.accompaniment_ordinals or ())),
                )
                if lead_id
                else None
            )
            await repo.save(
                OrderIntakeReceipt(
                    command.client_id,
                    command.operation_key,
                    command.payload_hash,
                    result,
                ),
                lead,
                session=session,
            )
            return result
