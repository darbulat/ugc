"""Delivered authors are historical people, not current billable slots."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import exists, func, inspect, select, union, update

from ugc_bot.domain.creator_invites import instagram_handle
from ugc_bot.domain.enums import OrderStatus, UserStatus
from ugc_bot.domain.financial import utc
from ugc_bot.infrastructure.db.creator_transfer_models import TRANSFERS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ItemAssignmentModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    UserModel,
)
from ugc_bot.infrastructure.db.paid_selection_models import INTERESTS
from ugc_bot.infrastructure.db.replacement_models import TABLES as REPLACEMENTS
from ugc_bot.infrastructure.db.selection_delivery_models import (
    ACCEPTED,
    ATTEMPTS,
)


async def _table_available(db, name):
    if db.get_bind().dialect.name != "postgresql":
        return await db.run_sync(
            lambda sync: inspect(sync.get_bind()).has_table(name)
        )
    return bool(await db.scalar(select(func.to_regclass(name).is_not(None))))


async def transfers_installed(db):
    return await _table_available(db, TRANSFERS.name)


def delivered_authors(order_id):
    client = (
        select(OrderModel.advertiser_id)
        .where(OrderModel.order_id == order_id)
        .scalar_subquery()
    )
    allocations, contacts = (
        REPLACEMENTS["allocations"],
        REPLACEMENTS["contacts"],
    )
    return union(
        select(ACCEPTED.c.creator_id).where(
            ACCEPTED.c.order_id == order_id, ACCEPTED.c.client_id == client
        ),
        select(ItemAssignmentModel.creator_id)
        .join(
            allocations,
            allocations.c.assignment_id == ItemAssignmentModel.assignment_id,
        )
        .join(
            contacts, contacts.c.replacement_id == allocations.c.replacement_id
        )
        .join(
            OrderItemModel,
            OrderItemModel.paid_item_id == allocations.c.paid_item_id,
        )
        .join(OrderModel, OrderModel.order_id == OrderItemModel.order_id)
        .where(
            OrderModel.order_id == order_id,
            contacts.c.actor_id == OrderModel.advertiser_id,
        ),
        select(TRANSFERS.c.creator_id).where(
            TRANSFERS.c.order_id == order_id,
            TRANSFERS.c.state == "sent",
            TRANSFERS.c.client_id == client,
        ),
    ).subquery()


async def delivered_count(db, order_id):
    if not await transfers_installed(db):
        return len(await delivery_history(db, order_id))
    return (
        await db.scalar(
            select(func.count()).select_from(delivered_authors(order_id))
        )
        or 0
    )


async def delivery_history(db, order_id):
    """Retain original contacts after profile and assignment changes."""
    result = {}
    installed = await transfers_installed(db)
    if not installed and not await _table_available(db, ACCEPTED.name):
        return []
    client = (
        select(OrderModel.advertiser_id)
        .where(OrderModel.order_id == order_id)
        .scalar_subquery()
    )
    paid = (
        await db.execute(
            select(
                ACCEPTED.c.creator_id, ACCEPTED.c.accepted_at, ATTEMPTS.c.source
            )
            .join(ATTEMPTS, ATTEMPTS.c.attempt_id == ACCEPTED.c.attempt_id)
            .where(
                ACCEPTED.c.order_id == order_id, ACCEPTED.c.client_id == client
            )
        )
    ).all()
    for creator, at, source in paid:
        contact = dict(source.get("creator_contact") or {})
        contact["instagram"] = source["instagram_url"]
        contact["name"] = contact.get("username")
        result[creator] = dict(
            creator_id=creator,
            sent_at=at,
            contact=contact,
            source="selection",
            feedback=None,
            requested_price=None,
        )
    allocations, contacts = (
        REPLACEMENTS["allocations"],
        REPLACEMENTS["contacts"],
    )
    replaced = []
    if installed or await _table_available(db, allocations.name):
        replaced = (
            await db.execute(
                select(
                    ItemAssignmentModel.creator_id,
                    contacts.c.recorded_at,
                    contacts.c.contact,
                )
                .join(
                    allocations,
                    allocations.c.assignment_id
                    == ItemAssignmentModel.assignment_id,
                )
                .join(
                    contacts,
                    contacts.c.replacement_id == allocations.c.replacement_id,
                )
                .join(
                    OrderItemModel,
                    OrderItemModel.paid_item_id == allocations.c.paid_item_id,
                )
                .join(
                    OrderModel, OrderModel.order_id == OrderItemModel.order_id
                )
                .where(
                    OrderModel.order_id == order_id,
                    contacts.c.actor_id == OrderModel.advertiser_id,
                )
                .order_by(contacts.c.recorded_at)
            )
        ).all()
    for creator, at, contact in replaced:
        contact = dict(
            name=contact.get("display_name"),
            instagram=contact.get("instagram_url"),
            telegram=contact.get("telegram"),
            phone=contact.get("phone"),
        )
        result.setdefault(
            creator,
            dict(
                creator_id=creator,
                sent_at=at,
                contact=contact,
                source="replacement",
                feedback=None,
                requested_price=None,
            ),
        )
    if not await transfers_installed(db):
        return sorted(
            result.values(),
            key=lambda r: (utc(r["sent_at"]), str(r["creator_id"])),
        )
    extra = (
        (
            await db.execute(
                select(TRANSFERS).where(
                    TRANSFERS.c.order_id == order_id,
                    TRANSFERS.c.state == "sent",
                    TRANSFERS.c.client_id == client,
                )
            )
        )
        .mappings()
        .all()
    )
    for row in extra:
        result.setdefault(
            row["creator_id"],
            {
                key: row[key]
                for key in (
                    "creator_id",
                    "sent_at",
                    "contact",
                    "source",
                    "requested_price",
                    "currency",
                    "feedback",
                )
            },
        )
    return sorted(
        result.values(), key=lambda r: (utc(r["sent_at"]), str(r["creator_id"]))
    )


class SqlCreatorTransfers:
    async def _order(self, db, order_id, creator_id):
        client_id = await db.scalar(
            select(OrderModel.advertiser_id).where(
                OrderModel.order_id == order_id
            )
        )
        if client_id is None or client_id == creator_id:
            raise ValueError("transfer_order_unavailable")
        # Paid commands acquire users before the order. Follow the same order.
        await db.execute(
            select(UserModel.user_id)
            .where(UserModel.user_id.in_((client_id, creator_id)))
            .order_by(UserModel.user_id)
            .with_for_update()
        )
        order = await db.scalar(
            select(OrderModel)
            .where(OrderModel.order_id == order_id)
            .with_for_update()
        )
        if (
            order is None
            or order.advertiser_id != client_id
            or not order.financial_version
            or order.complimentary
            or order.status not in (OrderStatus.ACTIVE, OrderStatus.CLOSED)
        ):
            raise ValueError("transfer_order_unavailable")
        if not await db.scalar(
            select(
                exists().where(
                    OrderItemModel.order_id == order_id,
                    OrderItemModel.captured_at.is_not(None),
                )
            )
        ):
            raise ValueError("transfer_order_unavailable")
        if not await transfers_installed(db):
            raise ValueError("transfer_history_unavailable")
        return order, client_id

    async def _source(self, db, order, creator_id, client_id):  # noqa: C901
        order_id = order.order_id
        offer = await db.scalar(
            select(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == creator_id,
            )
            .with_for_update()
        )
        interest = (
            (
                await db.execute(
                    select(INTERESTS).where(
                        INTERESTS.c.order_id == order_id,
                        INTERESTS.c.creator_id == creator_id,
                        INTERESTS.c.client_id == client_id,
                        INTERESTS.c.accepted.is_(False),
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        profile = await db.scalar(
            select(BloggerProfileModel)
            .where(BloggerProfileModel.user_id == creator_id)
            .with_for_update()
        )
        creator = await db.scalar(
            select(UserModel)
            .where(UserModel.user_id == creator_id)
            .with_for_update()
        )
        client = await db.scalar(
            select(UserModel)
            .where(UserModel.user_id == order.advertiser_id)
            .with_for_update()
        )
        if (
            creator is None
            or creator.status != UserStatus.ACTIVE
            or not profile
            or not profile.confirmed
            or not profile.instagram_user_id
            or not profile.instagram_user_id.strip()
        ):
            raise ValueError("transfer_creator_unavailable")
        if (
            not client
            or client.status != UserStatus.ACTIVE
            or not client.telegram_id
            or not str(client.telegram_id).isdigit()
        ):
            raise ValueError("transfer_customer_unavailable")
        reserve = bool(
            offer
            and offer.accepted is True
            and not offer.in_offer
            and interest
            and interest["instagram_user_id"] == profile.instagram_user_id
            and interest["instagram_url"] == profile.instagram_url
        )
        counteroffer = bool(
            offer
            and offer.accepted is False
            and offer.desired_price is not None
        )
        if not reserve and not counteroffer:
            raise ValueError("transfer_candidate_required")
        try:
            handle = instagram_handle(profile.instagram_url)
        except ValueError as exc:
            raise ValueError("transfer_creator_unavailable") from exc
        contact = dict(
            name=creator.username or "Креатор",
            instagram=f"https://instagram.com/{handle}/",
            telegram=creator.telegram,
            phone=profile.phone,
        )
        price = offer.desired_price if counteroffer else order.price
        return contact, price, counteroffer, client

    async def prepare(self, db, order_id, creator_id, operator, at):
        order, client_id = await self._order(db, order_id, creator_id)
        existing = (
            (
                await db.execute(
                    select(TRANSFERS)
                    .where(
                        TRANSFERS.c.order_id == order_id,
                        TRANSFERS.c.creator_id == creator_id,
                    )
                    .with_for_update()
                )
            )
            .mappings()
            .one_or_none()
        )
        if existing and existing["state"] in {"sent", "unknown", "sending"}:
            state = existing["state"]
            if state == "sending" and at >= utc(
                existing["started_at"]
            ) + timedelta(minutes=2):
                state = "unknown"
                await db.execute(
                    update(TRANSFERS)
                    .where(TRANSFERS.c.transfer_id == existing["transfer_id"])
                    .values(state=state, last_error="delivery_result_unknown")
                )
            return state, None
        ids = delivered_authors(order_id)
        if await db.scalar(
            select(ids.c.creator_id).where(ids.c.creator_id == creator_id)
        ):
            return "sent", None
        assigned = await db.scalar(
            select(ItemAssignmentModel.assignment_id)
            .join(
                OrderItemModel,
                OrderItemModel.paid_item_id == ItemAssignmentModel.paid_item_id,
            )
            .where(
                OrderItemModel.order_id == order_id,
                ItemAssignmentModel.creator_id == creator_id,
                ItemAssignmentModel.valid_to.is_(None),
            )
        )
        if assigned:
            raise ValueError("transfer_already_assigned")
        contact, price, counteroffer, client = await self._source(
            db, order, creator_id, client_id
        )
        payload = dict(
            transfer_id=existing["transfer_id"] if existing else uuid4(),
            order_id=order_id,
            creator_id=creator_id,
            client_id=client.user_id,
            operator=operator,
            source="counteroffer" if counteroffer else "reserve",
            state="sending",
            attempt_token=uuid4(),
            started_at=at,
            contact=contact,
            requested_price=price,
            currency=order.currency,
            last_error=None,
        )
        if existing:
            await db.execute(
                update(TRANSFERS)
                .where(TRANSFERS.c.transfer_id == existing["transfer_id"])
                .values(**payload)
            )
        else:
            await db.execute(TRANSFERS.insert().values(**payload))
        return "sending", dict(
            payload,
            address=client.telegram_id,
            title=(order.creator_offer_card or {}).get("title")
            or order.offer_text[:120],
            needed=order.bloggers_needed,
        )

    async def finish(self, db, attempt, state, at, reference=None, reason=None):
        result = await db.execute(
            update(TRANSFERS)
            .where(
                TRANSFERS.c.transfer_id == attempt["transfer_id"],
                TRANSFERS.c.attempt_token == attempt["attempt_token"],
                TRANSFERS.c.state.in_(("sending", "unknown")),
            )
            .values(
                state=state,
                sent_at=at if state == "sent" else None,
                provider_reference=reference,
                last_error=reason,
            )
        )
        return bool(result.rowcount)
