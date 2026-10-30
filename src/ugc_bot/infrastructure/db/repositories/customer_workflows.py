"""Caller-transaction workflow repository.

leases never surround provider I/O."""

import json
from datetime import datetime, timedelta
from uuid import UUID, uuid4, uuid5

from sqlalchemy import and_, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.infrastructure.db.customer_workflow_models import (
    JOBS,
    REQUESTS,
    SERIES,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    InteractionModel,
    OrderModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


class SqlAlchemyCustomerWorkflowRepository:
    async def actor(self, user_id: UUID, *, session: object) -> dict:
        db = _session(session)
        user = (
            (
                await db.execute(
                    select(UserModel.__table__)
                    .where(UserModel.user_id == user_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if user is None:
            return {}
        advertiser = await db.scalar(
            select(AdvertiserProfileModel.user_id).where(
                AdvertiserProfileModel.user_id == user_id
            )
        )
        return dict(user) | {
            "advertiser": advertiser is not None,
            "channel": str(user["messenger_type"]),
        }

    async def owns_order(
        self, user_id: UUID, order_id: UUID, *, session: object
    ) -> bool:
        return (
            await _session(session).scalar(
                select(OrderModel.order_id).where(
                    OrderModel.order_id == order_id,
                    OrderModel.advertiser_id == user_id,
                )
            )
            is not None
        )

    async def blogger_on_order(
        self, blogger_id: UUID, order_id: UUID, *, session: object
    ) -> bool:
        return (
            await _session(session).scalar(
                select(InteractionModel.interaction_id)
                .where(
                    InteractionModel.order_id == order_id,
                    InteractionModel.blogger_id == blogger_id,
                )
                .limit(1)
            )
            is not None
        )

    async def request(
        self, user_id: UUID, kind: str, key: str, *, session: object
    ) -> dict | None:
        row = (
            (
                await _session(session).execute(
                    select(REQUESTS).where(
                        REQUESTS.c.user_id == user_id,
                        REQUESTS.c.kind == kind,
                        REQUESTS.c.operation_key == key,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def save_request(self, values: dict, *, session: object) -> None:
        # expanded_at NULL is the durable notification intent, same transaction.
        await _session(session).execute(insert(REQUESTS).values(**values))

    async def requests(
        self, user_id: UUID, order_id: UUID, *, session: object
    ) -> list[dict]:
        rows = (
            (
                await _session(session).execute(
                    select(REQUESTS)
                    .where(
                        REQUESTS.c.user_id == user_id,
                        REQUESTS.c.order_id == order_id,
                        REQUESTS.c.kind == "support",
                    )
                    .order_by(REQUESTS.c.created_at.desc())
                    .limit(100)
                )
            )
            .mappings()
            .all()
        )
        return [dict(row) for row in rows]

    async def support_status(
        self, request_id: UUID, state: str, *, session: object
    ) -> None:
        found = await _session(session).scalar(
            update(REQUESTS)
            .where(
                REQUESTS.c.request_id == request_id,
                REQUESTS.c.kind == "support",
            )
            .values(state=state)
            .returning(REQUESTS.c.request_id)
        )
        if found is None:
            raise ValueError("customer_request_not_found")

    async def series(self, user_id: UUID, *, session: object) -> dict | None:
        row = (
            (
                await _session(session).execute(
                    select(SERIES)
                    .where(SERIES.c.user_id == user_id)
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def next_followup(
        self, series_id: UUID, *, session: object
    ) -> dict | None:
        row = (
            (
                await _session(session).execute(
                    select(JOBS.c.stage, JOBS.c.due_at)
                    .where(
                        JOBS.c.series_id == series_id, JOBS.c.state == "ready"
                    )
                    .order_by(JOBS.c.stage)
                    .limit(1)
                )
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None

    async def has_relevant_payment(
        self,
        user_id: UUID,
        since: datetime,
        *,
        order_id: UUID | None = None,
        session: object,
    ) -> bool:
        # A payment for this order or a payment during the current series.
        # This operational snapshot never changes financial rights.
        relevant_payment = [
            PaymentModel.paid_at >= since,
            and_(
                PaymentModel.paid_at.is_(None),
                PaymentModel.created_at >= since,
            ),
        ]
        if order_id is not None:
            relevant_payment.append(OrderModel.order_id == order_id)
        return (
            await _session(session).scalar(
                select(PaymentModel.payment_id)
                .join(OrderModel, OrderModel.order_id == PaymentModel.order_id)
                .where(
                    OrderModel.advertiser_id == user_id,
                    PaymentModel.status == "paid",
                    or_(*relevant_payment),
                )
                .limit(1)
            )
            is not None
        )

    async def save_series(self, values: dict, *, session: object) -> None:
        await _session(session).execute(
            insert(SERIES)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["user_id"],
                set_={
                    key: value
                    for key, value in values.items()
                    if key not in ("series_id", "user_id", "created_at")
                },
            )
        )

    async def schedule(self, series: dict, *, session: object) -> None:
        db = _session(session)
        for stage, hours in enumerate((1, 24, 72), 1):
            values = dict(
                job_id=uuid5(series["series_id"], str(stage)),
                series_id=series["series_id"],
                recipient_id=series["user_id"],
                stage=stage,
                generation=series["generation"],
                due_at=series["last_activity_at"] + timedelta(hours=hours),
                state="ready",
            )
            await db.execute(
                insert(JOBS)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=["series_id", "stage"],
                    set_={key: values[key] for key in ("generation", "due_at")},
                    where=JOBS.c.state == "ready",
                )
            )

    async def expand_admin(self, at: datetime, *, session: object) -> None:
        db = _session(session)
        admins = (
            await db.scalars(
                select(UserModel.user_id).where(
                    UserModel.admin.is_(True), UserModel.status == "active"
                )
            )
        ).all()
        if not admins:
            return
        sources = (
            (
                await db.execute(
                    select(REQUESTS)
                    .where(REQUESTS.c.expanded_at.is_(None))
                    .limit(100)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        for source in sources:
            body = (
                (
                    "Обращение"
                    if source["kind"] == "support"
                    else "Заявка на услугу"
                )
                + f" #{source['request_id']}\n"
                + json.dumps(source["payload"], ensure_ascii=False, indent=2)
            )
            chunks = [
                body[index : index + 1500]
                for index in range(0, len(body), 1500)
            ]
            for admin in admins:
                for part, chunk in enumerate(chunks):
                    await db.execute(
                        insert(JOBS)
                        .values(
                            job_id=uuid5(
                                source["request_id"], f"{admin}:{part}"
                            ),
                            request_id=source["request_id"],
                            recipient_id=admin,
                            part=part,
                            text=f"{part + 1}/{len(chunks)}\n{chunk}",
                            due_at=at,
                            state="ready",
                        )
                        .on_conflict_do_nothing(
                            index_elements=[
                                "request_id",
                                "recipient_id",
                                "part",
                            ]
                        )
                    )
            await db.execute(
                update(REQUESTS)
                .where(REQUESTS.c.request_id == source["request_id"])
                .values(expanded_at=at)
            )

    async def claim(
        self,
        at: datetime,
        lease_seconds: int,
        *,
        session: object,
        include_followups: bool = True,
    ) -> dict | None:
        db = _session(session)
        # A crashed send may have reached the provider. Expiration
        # quarantines it.
        await db.execute(
            update(JOBS)
            .where(
                JOBS.c.state == "sending",
                JOBS.c.lease_until <= at,
            )
            .values(state="unknown", reason="delivery_lease_expired")
        )
        expired = (
            (
                await db.execute(
                    select(JOBS)
                    .where(JOBS.c.state == "leased", JOBS.c.lease_until <= at)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .all()
        )
        for stale in expired:
            await self.retry_preparation(dict(stale), at, session=session)
        row = (
            (
                await db.execute(
                    select(JOBS)
                    .where(
                        JOBS.c.state == "ready",
                        JOBS.c.due_at <= at,
                        true()
                        if include_followups
                        else JOBS.c.request_id.is_not(None),
                    )
                    .order_by(JOBS.c.due_at, JOBS.c.job_id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        job = dict(row)
        job.update(
            state="leased",
            lease_token=uuid4(),
            lease_until=at + timedelta(seconds=lease_seconds),
        )
        await db.execute(
            update(JOBS)
            .where(JOBS.c.job_id == job["job_id"])
            .values(
                state="leased",
                lease_token=job["lease_token"],
                lease_until=job["lease_until"],
            )
        )
        return job

    async def _followup(
        self, job: dict, at: datetime, *, session: object
    ) -> dict | None:
        db = _session(session)
        series = (
            (
                await db.execute(
                    select(SERIES).where(SERIES.c.series_id == job["series_id"])
                )
            )
            .mappings()
            .one()
        )
        if (
            series["stop_reason"]
            or series["opted_out"]
            or series["generation"] != job["generation"]
        ):
            return None
        if await self.has_relevant_payment(
            series["user_id"],
            series["created_at"],
            order_id=series["order_id"],
            session=session,
        ):
            await db.execute(
                update(SERIES)
                .where(SERIES.c.series_id == series["series_id"])
                .values(stop_reason="paid")
            )
            return None
        profile = await db.scalar(
            select(AdvertiserProfileModel.user_id).where(
                AdvertiserProfileModel.user_id == series["user_id"]
            )
        )
        if profile is None or job["due_at"] > at:
            return None
        return dict(series)

    async def _lease_current(
        self, current: dict, job: dict, at: datetime, *, session: object
    ) -> bool:
        if (
            current["state"] != "leased"
            or current["lease_token"] != job["lease_token"]
        ):
            return False
        if current["lease_until"] <= at:
            await self.retry_preparation(dict(current), at, session=session)
            return False
        return True

    async def eligible(
        self,
        job: dict,
        at: datetime,
        *,
        session: object,
        mark_sending: bool = True,
    ) -> dict | None:
        db = _session(session)
        # Activity takes series before delivery rows. Keep the same lock order.
        if job["series_id"]:
            await db.execute(
                select(SERIES.c.series_id)
                .where(SERIES.c.series_id == job["series_id"])
                .with_for_update()
            )
        current = (
            (
                await db.execute(
                    select(JOBS)
                    .where(JOBS.c.job_id == job["job_id"])
                    .with_for_update()
                )
            )
            .mappings()
            .one()
        )
        if not await self._lease_current(
            dict(current), job, at, session=session
        ):
            return None
        user = (
            (
                await db.execute(
                    select(UserModel.__table__).where(
                        UserModel.user_id == job["recipient_id"]
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if not user or user["status"] != "active":
            if job["series_id"]:
                await db.execute(
                    update(SERIES)
                    .where(SERIES.c.series_id == job["series_id"])
                    .values(stop_reason="blocked")
                )
            return None
        result = dict(job)
        if job["request_id"]:
            if not user["admin"]:
                return None
            source = (
                (
                    await db.execute(
                        select(REQUESTS).where(
                            REQUESTS.c.request_id == job["request_id"]
                        )
                    )
                )
                .mappings()
                .one()
            )
            result["payload"] = source["payload"]
            result["kind"] = source["kind"]
            result["order_id"] = source["order_id"]
            channel = str(user["messenger_type"])
        else:
            series = await self._followup(job, at, session=session)
            if series is None:
                return None
            result["order_id"] = series["order_id"]
            result["user_id"] = series["user_id"]
            channel = series["channel"]
        address = (
            user["telegram_id"]
            if channel == "telegram"
            else (user["max_chat_id"] or user["max_id"])
        )
        if channel not in ("telegram", "max") or not address:
            return None
        if mark_sending:
            await db.execute(
                update(JOBS)
                .where(JOBS.c.job_id == job["job_id"])
                .values(state="sending")
            )
        return result | dict(
            channel=channel,
            address=address,
            address_kind="user_id"
            if channel == "max" and not user["max_chat_id"]
            else "chat_id",
            language=user["language"] or "ru",
        )

    async def retry_preparation(
        self,
        job: dict,
        at: datetime,
        *,
        session: object,
        retry_after_seconds: int = 0,
    ) -> None:
        reason = job.get("reason") or ""
        try:
            attempt = (
                int(reason.removeprefix("preparation_retry:")) + 1
                if reason.startswith("preparation_retry:")
                else 1
            )
        except ValueError:
            attempt = 1
        await _session(session).execute(
            update(JOBS)
            .where(
                JOBS.c.job_id == job["job_id"],
                JOBS.c.state == "leased",
                JOBS.c.lease_token == job["lease_token"],
            )
            .values(
                state="failed" if attempt >= 3 else "ready",
                reason=f"preparation_retry:{attempt}",
                due_at=at
                + timedelta(seconds=max(30 * attempt, retry_after_seconds)),
                lease_token=None,
                lease_until=None,
            )
        )

    async def retry_before_transport(
        self,
        job: dict,
        at: datetime,
        *,
        session: object,
        retry_after_seconds: int = 0,
    ) -> None:
        # Called in the transaction that marked sending, before any provider
        # call. Revert atomically so preparation retries remain bounded.
        await _session(session).execute(
            update(JOBS)
            .where(
                JOBS.c.job_id == job["job_id"],
                JOBS.c.state == "sending",
                JOBS.c.lease_token == job["lease_token"],
            )
            .values(state="leased")
        )
        await self.retry_preparation(
            job, at, session=session, retry_after_seconds=retry_after_seconds
        )

    async def finish(
        self,
        job: dict,
        state: str,
        reference: str | None,
        reason: str | None,
        *,
        session: object,
    ) -> None:
        db = _session(session)
        if state == "obsolete" and job["series_id"]:
            series = (
                (
                    await db.execute(
                        select(SERIES).where(
                            SERIES.c.series_id == job["series_id"]
                        )
                    )
                )
                .mappings()
                .one()
            )
            if (
                not series["stop_reason"]
                and not series["opted_out"]
                and series["generation"] != job["generation"]
            ):
                await db.execute(
                    update(JOBS)
                    .where(
                        JOBS.c.job_id == job["job_id"],
                        JOBS.c.state == "leased",
                        JOBS.c.lease_token == job["lease_token"],
                    )
                    .values(
                        state="ready",
                        generation=series["generation"],
                        due_at=series["last_activity_at"]
                        + timedelta(hours=(1, 24, 72)[job["stage"] - 1]),
                        lease_token=None,
                        lease_until=None,
                    )
                )
                return
        await db.execute(
            update(JOBS)
            .where(
                JOBS.c.job_id == job["job_id"],
                JOBS.c.state
                == ("leased" if state == "obsolete" else "sending"),
                JOBS.c.lease_token == job["lease_token"],
            )
            .values(state=state, provider_reference=reference, reason=reason)
        )
