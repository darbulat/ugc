"""Project only contacts already released to the order owner."""

from sqlalchemy import and_, select

from ugc_bot.domain.creator_invites import instagram_handle
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_handoff_models import STAFF_DELIVERIES
from ugc_bot.infrastructure.db.repositories.invite_handoff import (
    handoff_installed,
    public_telegram,
)
from ugc_bot.infrastructure.db.selection_delivery_models import ATTEMPTS


def contact_position(ordinal, instagram, telegram):
    try:
        instagram = "@" + instagram_handle(instagram or "")
    except ValueError:
        instagram = None
    return dict(
        ordinal=ordinal, instagram=instagram, telegram=public_telegram(telegram)
    )


async def confirmed_contacts(db, order, items, assignments, deliveries):
    if order["status"] not in ("active", "closed"):
        return []
    ordinals = {
        item["paid_item_id"]: item["ordinal"]
        for item in items
        if item["captured_at"] is not None
        and item["selection_state"] not in ("refunded", "cancelled")
    }
    attempts = {
        delivery["attempt_id"]: ordinals[delivery["paid_item_id"]]
        for delivery in deliveries
        if delivery["paid_item_id"] in ordinals
    }
    contacts = []
    if attempts:
        rows = await db.execute(
            select(
                ATTEMPTS.c.attempt_id,
                ATTEMPTS.c.source["instagram_url"].as_string(),
                ATTEMPTS.c.source["creator_contact"]["telegram"].as_string(),
            ).where(
                ATTEMPTS.c.order_id == order["order_id"],
                ATTEMPTS.c.attempt_id.in_(attempts),
            )
        )
        contacts.extend(
            dict(
                ordinal=attempts[attempt_id],
                instagram=instagram,
                telegram=public_telegram(telegram),
            )
            for attempt_id, instagram, telegram in rows
        )

    # A manually entered contact follows the existing receipt flow. Reading
    # this card must not create the receipt or release a pending contact.
    unassigned = ordinals.keys() - assignments.keys()
    if unassigned and await handoff_installed(db):
        rows = await db.execute(
            select(
                STAFF_DELIVERIES.c.paid_item_id,
                INVITES.c.instagram,
                INVITES.c.telegram,
            )
            .join_from(
                STAFF_DELIVERIES,
                INVITES,
                and_(
                    INVITES.c.id == STAFF_DELIVERIES.c.delivery_id,
                    INVITES.c.item_id == STAFF_DELIVERIES.c.paid_item_id,
                    INVITES.c.order_id == STAFF_DELIVERIES.c.order_id,
                ),
            )
            .where(
                STAFF_DELIVERIES.c.order_id == order["order_id"],
                STAFF_DELIVERIES.c.client_id == order["advertiser_id"],
                STAFF_DELIVERIES.c.paid_item_id.in_(unassigned),
                INVITES.c.reported_at.is_not(None),
            )
        )
        contacts.extend(
            contact_position(ordinals[item_id], instagram, telegram)
            for item_id, instagram, telegram in rows
        )

    return sorted(
        (row for row in contacts if row["instagram"] or row["telegram"]),
        key=lambda row: row["ordinal"],
    )
