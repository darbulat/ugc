"""One row per creator; delivery history stays distinct from paid work."""

from collections import Counter
from contextlib import suppress
from unicodedata import normalize
from uuid import UUID

from sqlalchemy import func, select

from ugc_bot.admin.order_summary import (
    financial_positions,
    order_creator_contacts,
)
from ugc_bot.domain.creator_invites import instagram_handle
from ugc_bot.domain.social import SocialPlatform, normalize_social_url
from ugc_bot.infrastructure.db.models import OfferDispatchModel, OrderModel

WORK_LABELS = {
    "assigned": "Назначен",
    "in_progress": "В работе",
    "success_claimed": "Ждёт подтверждения",
    "disputed": "Спор",
    "success_final": "Завершено",
    "unconfirmed_expired": "Истёк срок подтверждения",
    "available": "Можно заменить",
    "rejected": "Отклонён",
}
FILTERS = (
    ("all", "Все"),
    ("delivered", "Переданы"),
    ("reserve", "Резерв"),
    ("price", "Новая цена"),
    ("declined", "Отказы"),
    ("selected", "Подобраны"),
)


async def load_order_responses(session, order):
    """Reuse the existing paid-assignment projection without money writes."""
    models = (
        (
            await session.execute(
                select(OfferDispatchModel)
                .where(OfferDispatchModel.order_id == order.order_id)
                .order_by(
                    func.coalesce(
                        OfferDispatchModel.updated_at,
                        OfferDispatchModel.created_at,
                    ).desc(),
                    OfferDispatchModel.blogger_id,
                )
            )
        )
        .scalars()
        .all()
    )
    responses = [
        dict(
            blogger_id=str(row.blogger_id),
            responded_at=row.updated_at or row.created_at,
            accepted=row.accepted,
            in_offer=row.in_offer,
            ugc_video_url=row.ugc_video_url,
        )
        for row in models
        if row.accepted is not None and (row.in_offer or row.accepted is True)
    ]
    picked = None
    if order.financial_version is not None and not order.complimentary:
        positions = (
            await session.execute(financial_positions([order.order_id]))
        ).all()
        picked = len(positions)
        for item in responses:
            item["in_offer"] = False
        by_creator = {item["blogger_id"]: item for item in responses}
        assigned = [
            dict(
                by_creator.get(str(position.creator_id), {}),
                blogger_id=str(position.creator_id),
                in_offer=True,
                assigned_at=position.valid_from,
                work_state=position.state,
            )
            for position in positions
        ]
        assigned_ids = {item["blogger_id"] for item in assigned}
        responses = assigned + [
            item for item in responses if item["blogger_id"] not in assigned_ids
        ]
    contacts = await order_creator_contacts(
        session, [UUID(item["blogger_id"]) for item in responses]
    )
    for item in responses:
        item.update(contacts.get(item["blogger_id"], {}))
    return responses, picked


def creator_workspace(
    responses, activity=None, transfers=None, contacts=None, offer_price=None
):
    """Merge overlapping projections by identity, never by display name."""
    rows = {}

    def row_for(creator_id):
        key = str(creator_id)
        if key not in rows:
            rows[key] = dict(
                creator_id=key,
                profile_id=key,
                manual=False,
                ordinal=None,
                name="Профиль креатора",
                contact={},
                response="—",
                reason=None,
                price=None,
                price_proposed=False,
                delivered_price=None,
                responded_at=None,
                in_offer=False,
                work=None,
                video=None,
                delivered=False,
                state=None,
                can_send=False,
                source=None,
                sent_at=None,
                feedback=None,
                group="selected",
                current_contact=None,
                search_contact=None,
            )
        return rows[key]

    for response in responses:
        row = row_for(response["blogger_id"])
        row.update(
            name=response.get("name") or row["name"],
            contact={
                key: response.get(key) for key in ("instagram", "telegram")
            },
            response="Согласен" if response.get("accepted") else "Назначен",
            responded_at=response.get("responded_at")
            or response.get("assigned_at"),
            in_offer=bool(response.get("in_offer")),
            work=WORK_LABELS.get(response.get("work_state")),
            video=response.get("ugc_video_url"),
            group="selected" if response.get("in_offer") else "reserve",
        )
    for refusal in (activity or {}).get("refused", []):
        row = row_for(refusal["creator_id"])
        row.update(
            name=refusal.get("name") or row["name"],
            response="Новая цена"
            if refusal.get("price") is not None
            else "Отказ",
            reason=refusal.get("reason"),
            price=refusal.get("price"),
            price_proposed=refusal.get("price") is not None,
            group="price" if refusal.get("price") is not None else "declined",
        )
    for candidate in (transfers or {}).get("candidates", []):
        row = row_for(candidate["creator_id"])
        state = candidate.get("state")
        row.update(
            name=candidate.get("name") or row["name"],
            state=state,
            can_send=bool(transfers["can_send"])
            and state in (None, "failed")
            and not row["in_offer"],
        )
        if candidate["source"] == "Новая цена":
            row.update(
                response="Новая цена",
                price=candidate.get("price"),
                price_proposed=True,
                group="price",
            )
        elif not row["in_offer"]:
            row.update(response="Согласен", group="reserve")
    for creator_id, contact in (contacts or {}).items():
        row = row_for(creator_id)
        row["name"] = contact.get("name") or row["name"]
        row["contact"] = contact
    for item in (transfers or {}).get("history", []):
        _apply_history(row_for(item["creator_id"]), item)
    counts = Counter(row["group"] for row in rows.values())
    groups = {key: index for index, (key, _) in enumerate(FILTERS)}
    items = sorted(
        rows.values(),
        key=lambda row: (
            groups[row["group"]],
            row["name"].casefold(),
            row["creator_id"],
        ),
    )
    return dict(
        rows=items,
        filters=[
            dict(
                key=key,
                label=label,
                count=len(items) if key == "all" else counts[key],
            )
            for key, label in FILTERS
        ],
        transfer_count=transfers["count"] if transfers else None,
        manual_count=transfers.get("manual_count", 0) if transfers else 0,
        needed=transfers["needed"] if transfers else None,
        currency=(activity or {}).get("currency", "RUB"),
        offer_price=offer_price,
    )


def _apply_history(row, item):
    snapshot = item["contact"]
    current = dict(row["contact"])
    saved_name = snapshot.get("name") or snapshot.get("username")
    if row["name"] != "Профиль креатора":
        current["name"] = row["name"]
    row["search_contact"] = current
    saved = dict(snapshot, name=saved_name or row["name"])
    row["current_contact"] = {
        key: current[key]
        for key in ("name", "instagram", "telegram")
        if current.get(key)
        and _contact_identity(key, current[key])
        != _contact_identity(key, saved.get(key))
    } or None
    row.update(
        name=saved_name or row["name"],
        contact=snapshot,
        delivered=True,
        state="sent",
        can_send=False,
        group="delivered",
        source=item.get("source"),
        sent_at=item.get("sent_at"),
        feedback=item.get("feedback"),
        delivered_price=item.get("requested_price"),
        manual=bool(item.get("manual")),
        ordinal=item.get("ordinal"),
    )
    if "profile_id" in item:
        row["profile_id"] = item["profile_id"]
    if row["price"] is None and item.get("requested_price") is not None:
        row["price"] = item["requested_price"]
        row["price_proposed"] = item.get("source") == "counteroffer"
    if row["response"] == "—":
        row["response"] = (
            "Новая цена" if item.get("source") == "counteroffer" else "Согласен"
        )


def _contact_identity(key, value):
    cleaned = normalize("NFC", " ".join((value or "").split()))
    if key == "instagram":
        with suppress(ValueError):
            return instagram_handle(cleaned)
    elif key == "telegram":
        url = (
            cleaned
            if "://" in cleaned
            else (
                "https://" + cleaned
                if cleaned.startswith(("t.me/", "telegram.me/"))
                else "https://t.me/" + cleaned.lstrip("@")
            )
        )
        with suppress(ValueError):
            return normalize_social_url(SocialPlatform.TELEGRAM, url)[
                1
            ].casefold()
    return cleaned.casefold()


async def load_creator_workspace(session, order_id, activity, transfers):
    order = await session.get(OrderModel, order_id)
    responses, _ = await load_order_responses(session, order)
    known = {row["blogger_id"] for row in responses}
    extra = {
        str(row["creator_id"]) for row in (activity or {}).get("refused", [])
    } | {
        str(row["creator_id"])
        for row in (transfers or {}).get("history", [])
        + (transfers or {}).get("candidates", [])
    }
    user_ids = []
    for key in extra - known:
        with suppress(ValueError):
            user_ids.append(UUID(key))
    contacts = await order_creator_contacts(session, user_ids)
    return creator_workspace(
        responses, activity, transfers, contacts, offer_price=order.price
    )
