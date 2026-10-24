"""Intake writes and quote share one caller-owned PostgreSQL transaction."""

from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import insert, select, text

from ugc_bot.domain.order_intake import (
    AccompanimentLead,
    IntakeClient,
    IntakeItem,
    OrderIntakeReceipt,
    OrderIntakeResult,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    CountryModel,
    FinancialPolicyVersionModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_intake_models import (
    ACCOMPANIMENT_LEADS,
    INTAKE_RECEIPTS,
    LEAD_OUTBOX,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


def canonical(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    return value


def result_from_payload(payload: dict[str, Any]) -> OrderIntakeResult:
    return OrderIntakeResult(
        UUID(payload["request_id"]),
        UUID(payload["order_id"]),
        datetime.fromisoformat(payload["requested_at"]),
        payload["currency"],
        payload["policy_version"],
        datetime.fromisoformat(payload["selection_due_at"]),
        payload["terms_reference"],
        tuple(
            IntakeItem(
                UUID(item["paid_item_id"]),
                item["ordinal"],
                item["selection_minor"],
                item["accompaniment_minor"],
            )
            for item in payload["items"]
        ),
        UUID(payload["lead_id"]) if payload["lead_id"] else None,
        payload["honorarium_payment"],
    )


class SqlAlchemyOrderIntakeRepository:
    async def policy_versions(
        self, at: datetime, *, session: object
    ) -> tuple[str, ...]:
        return tuple(
            (
                await _session(session).scalars(
                    select(FinancialPolicyVersionModel.version)
                    .where(
                        FinancialPolicyVersionModel.effective_from <= at,
                        FinancialPolicyVersionModel.approved_at
                        <= FinancialPolicyVersionModel.effective_from,
                    )
                    .order_by(
                        FinancialPolicyVersionModel.effective_from.desc(),
                        FinancialPolicyVersionModel.version,
                    )
                )
            ).all()
        )

    async def lock_client(
        self, client_id: UUID, *, session: object
    ) -> IntakeClient | None:
        db = _session(session)
        user = (
            await db.execute(
                select(
                    UserModel.user_id,
                    UserModel.status,
                    UserModel.country,
                    UserModel.telegram_id,
                    UserModel.max_id,
                )
                .where(UserModel.user_id == client_id)
                .with_for_update(key_share=True)
            )
        ).one_or_none()
        if user is None:
            return None
        advertiser = await db.scalar(
            select(AdvertiserProfileModel.user_id)
            .where(
                AdvertiserProfileModel.user_id == client_id,
            )
            .with_for_update(read=True)
        )
        currency = (
            await db.scalar(
                select(CountryModel.currency_code).where(
                    CountryModel.code == user.country,
                )
            )
            if user.country
            else ""
        )
        return IntakeClient(
            client_id,
            user.status,
            advertiser is not None,
            currency or "",
            user.telegram_id,
            user.max_id,
        )

    async def lock_operation(
        self, client_id: UUID, operation_key: str, *, session: object
    ) -> None:
        await _session(session).execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"intake:{client_id}:{len(operation_key)}:{operation_key}"},
        )

    async def get_receipt(
        self, client_id: UUID, operation_key: str, *, session: object
    ) -> OrderIntakeReceipt | None:
        row = (
            (
                await _session(session).execute(
                    select(INTAKE_RECEIPTS).where(
                        INTAKE_RECEIPTS.c.client_id == client_id,
                        INTAKE_RECEIPTS.c.operation_key == operation_key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return OrderIntakeReceipt(
            client_id,
            operation_key,
            row["payload_hash"],
            result_from_payload(row["result"]),
        )

    async def save(
        self,
        receipt: OrderIntakeReceipt,
        lead: AccompanimentLead | None,
        *,
        session: object,
    ) -> None:
        db = _session(session)
        result = receipt.result
        await db.execute(
            insert(INTAKE_RECEIPTS).values(
                request_id=result.request_id,
                order_id=result.order_id,
                client_id=receipt.client_id,
                operation_key=receipt.operation_key,
                payload_hash=receipt.payload_hash,
                requested_at=result.requested_at,
                result=canonical(asdict(result)),
            )
        )
        if lead is not None:
            values = asdict(lead)
            values["selected_ordinals"] = list(lead.selected_ordinals)
            await db.execute(insert(ACCOMPANIMENT_LEADS).values(**values))
            await db.execute(
                insert(LEAD_OUTBOX).values(
                    lead_id=lead.lead_id,
                    order_id=lead.order_id,
                    created_at=lead.requested_at,
                )
            )
