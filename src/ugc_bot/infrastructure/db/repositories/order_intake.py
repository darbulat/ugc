"""Intake writes and quote share one caller-owned PostgreSQL transaction."""

from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ugc_bot.domain.order_intake import (
    AccompanimentLead,
    IntakeClient,
    IntakeItem,
    OrderIntakeReceipt,
    OrderIntakeResult,
)
from ugc_bot.domain.order_targeting import OrderTargeting
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    CountryModel,
    FinancialPolicyVersionModel,
    UserModel,
)
from ugc_bot.infrastructure.db.order_funnel_models import FUNNEL
from ugc_bot.infrastructure.db.order_intake_models import (
    ACCOMPANIMENT_LEADS,
    INTAKE_RECEIPTS,
    LEAD_OUTBOX,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


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
        payload.get("targeting"),
    )


class SqlAlchemyOrderIntakeRepository:
    async def exact_city_for_order(
        self, order_id, *, session, for_update=False
    ):
        statement = select(INTAKE_RECEIPTS.c.result).where(
            INTAKE_RECEIPTS.c.order_id == order_id
        )
        if for_update:
            statement = statement.with_for_update()
        result = await _session(session).scalar(statement)
        targeting = result.get("targeting") if result else None
        city = targeting.get("city") if targeting else None
        if city is not None and (not isinstance(city, str) or not city.strip()):
            raise ValueError("invalid_targeting_city")
        return city.strip() if city is not None else None

    async def filter_candidates(self, order_id, creator_ids, *, session):
        db = _session(session)
        result = await db.scalar(
            select(INTAKE_RECEIPTS.c.result).where(
                INTAKE_RECEIPTS.c.order_id == order_id
            )
        )
        if not result or not result.get("targeting"):
            return creator_ids
        values = dict(result["targeting"])
        values["platforms"] = tuple(values.get("platforms", ()))
        criteria = OrderTargeting(**values)
        statement = select(BloggerProfileModel.user_id).where(
            BloggerProfileModel.user_id.in_(creator_ids)
        )
        if criteria.city:
            statement = statement.where(
                func.lower(func.trim(BloggerProfileModel.city))
                == criteria.city.casefold()
            )
        if criteria.platforms:
            statement = statement.where(
                select(SocialAccountModel.account_id)
                .where(
                    SocialAccountModel.user_id == BloggerProfileModel.user_id,
                    SocialAccountModel.platform.in_(criteria.platforms),
                )
                .exists()
            )
        matched = set(await db.scalars(statement))
        return [identity for identity in creator_ids if identity in matched]

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
                    UserModel.admin,
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
            user.admin,
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

    async def record_funnel(
        self, client_id, funnel_id, stage, at, *, order_id=None, session
    ):
        await _session(session).execute(
            pg_insert(FUNNEL)
            .values(
                client_id=client_id,
                funnel_id=funnel_id,
                stage=stage,
                recorded_at=at,
                order_id=order_id,
            )
            .on_conflict_do_nothing(
                index_elements=["client_id", "funnel_id", "stage"]
            )
        )

    async def funnel_report(self, *, session):
        db = _session(session)
        rows = await db.execute(
            select(FUNNEL.c.stage, func.count()).group_by(FUNNEL.c.stage)
        )
        actual = await db.scalar(
            select(func.count()).select_from(INTAKE_RECEIPTS)
        )
        captured = await db.scalar(
            text(
                "SELECT count(*) FROM order_intake_receipts r "
                "JOIN payments p ON p.order_id=r.order_id "
                "WHERE p.status='paid' AND p.financial_version IS NOT NULL"
            )
        )
        return dict(
            stages={stage: count for stage, count in rows},
            actual_orders=int(actual or 0),
            captured_orders=int(captured or 0),
            client_stages_are_observations=True,
        )
