"""Create a private two-position invitation rehearsal by explicit order ID."""

import argparse
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ugc_bot.config import load_config
from ugc_bot.container import Container
from ugc_bot.domain.enums import AuditAction, OrderStatus
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    FinancialPolicyVersionModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    OutboxEventModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    free_positions,
    order_for_invite,
)


def provision(db, order_id, telegram):
    at = datetime.now(timezone.utc)
    owner = db.scalars(
        select(UserModel)
        .join(
            AdvertiserProfileModel,
            AdvertiserProfileModel.user_id == UserModel.user_id,
        )
        .where(
            func.lower(func.ltrim(UserModel.telegram, "@")) == telegram,
            UserModel.status == "active",
            UserModel.telegram_id.op("~")(r"^[1-9][0-9]*$"),
        )
        .with_for_update(of=UserModel)
    ).one()
    order = db.get(OrderModel, order_id)
    if order is None:
        policy = db.scalar(
            select(FinancialPolicyVersionModel)
            .where(FinancialPolicyVersionModel.effective_from <= at)
            .order_by(FinancialPolicyVersionModel.effective_from.desc())
            .limit(1)
        )
        if not policy:
            raise ValueError("No published policy for the item foreign key")
        db.add(
            OrderModel(
                order_id=order_id,
                advertiser_id=owner.user_id,
                status=OrderStatus.ACTIVE,
                product_link="https://usemycontent.ru/",
                offer_text=(
                    "ТЕСТ · Приглашения креаторов. Проверка двух сценариев. "
                    "Публикация и оплата не предусмотрены."
                ),
                price=0,
                bloggers_needed=2,
                complimentary=True,
                dispatch_stopped=True,
                created_at=at,
                updated_at=at,
            )
        )
        db.flush()
        db.add(
            AuditLogModel(
                entity_type="order_test_marker",
                entity_id=order_id,
                action=AuditAction.UPDATE,
                changed_by=owner.user_id,
                new_values={"test": True, "invite_preview": True},
            )
        )
        for ordinal in (1, 2):
            db.add(
                OrderItemModel(
                    paid_item_id=uuid5(order_id, str(ordinal)),
                    order_id=order_id,
                    ordinal=ordinal,
                    currency="RUB",
                    # The database requires the tariff even before capture.
                    # This value creates neither a payment nor a ledger entry.
                    selection_minor=int(
                        policy.rules.get("selection_minor", 50000)
                    ),
                    accompaniment_minor=0,
                    policy_version=policy.version,
                    selection_due_at=at + timedelta(days=30),
                    quote_key=str(order_id),
                    quote_payload={"invite_preview": True},
                )
            )
        db.flush()
    ready = order_for_invite(db, order_id)
    if (
        ready is None
        or ready.advertiser_id != owner.user_id
        or not ready.complimentary
        or not ready.dispatch_stopped
        or ready.financial_version is not None
    ):
        raise ValueError("Unexpected existing order for this ID")
    positions = db.scalars(free_positions(order_id)).all()
    if sorted(item.ordinal for item in positions) != [1, 2]:
        raise ValueError("The rehearsal does not have two available positions")
    for query in (
        select(PaymentModel.payment_id).where(
            PaymentModel.order_id == order_id
        ),
        select(OfferDispatchModel.order_id).where(
            OfferDispatchModel.order_id == order_id
        ),
        select(OutboxEventModel.event_id).where(
            OutboxEventModel.aggregate_id == str(order_id)
        ),
    ):
        if db.scalar(query.exists().select()):
            raise ValueError("Unexpected payment, offer or event")
    return ready.order_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", required=True, type=UUID)
    parser.add_argument(
        "--owner", required=True, help="Existing advertiser Telegram handle"
    )
    parser.add_argument("--commit", action="store_true")
    args = parser.parse_args()
    engine = Container(load_config()).get_admin_engine()
    with Session(engine) as db:
        identity = provision(db, args.order_id, args.owner.lstrip("@").lower())
        if args.commit:
            db.commit()
            print(f"{identity} active, 2 positions, no payment or offers")
        else:
            db.rollback()
            print(f"{identity} verified inside a rolled-back transaction")


if __name__ == "__main__":
    main()
