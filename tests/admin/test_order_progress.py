"""Delivery counts stay unique and batched, without inflating paid positions."""

from uuid import uuid4

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Uuid,
    create_engine,
    event,
)
from sqlalchemy.orm import Session

from ugc_bot.admin.order_progress import OrderProgress, load_order_progress
from ugc_bot.infrastructure.db.creator_transfer_models import TRANSFERS
from ugc_bot.infrastructure.db.models import (
    ItemAssignmentModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
)
from ugc_bot.infrastructure.db.replacement_models import TABLES as REPLACEMENTS
from ugc_bot.infrastructure.db.selection_delivery_models import ACCEPTED


@pytest.fixture
def delivery_db():
    metadata = MetaData()

    def table(name, **columns):
        return Table(
            name,
            metadata,
            *(Column(key, kind) for key, kind in columns.items()),
        )

    tables = dict(
        offers=table(
            OfferDispatchModel.__tablename__,
            order_id=Uuid,
            blogger_id=Uuid,
            in_offer=Boolean,
        ),
        orders=table(
            OrderModel.__tablename__,
            order_id=Uuid,
            advertiser_id=Uuid,
            financial_version=Integer,
            complimentary=Boolean,
        ),
        items=table(
            OrderItemModel.__tablename__, paid_item_id=Uuid, order_id=Uuid
        ),
        assignments=table(
            ItemAssignmentModel.__tablename__,
            assignment_id=Uuid,
            creator_id=Uuid,
            paid_item_id=Uuid,
            valid_to=DateTime,
        ),
        accepted=table(
            ACCEPTED.name, order_id=Uuid, creator_id=Uuid, client_id=Uuid
        ),
        transfers=table(
            TRANSFERS.name,
            order_id=Uuid,
            creator_id=Uuid,
            client_id=Uuid,
            state=String,
        ),
        allocations=table(
            REPLACEMENTS["allocations"].name,
            replacement_id=Uuid,
            assignment_id=Uuid,
            paid_item_id=Uuid,
        ),
        contacts=table(
            REPLACEMENTS["contacts"].name, replacement_id=Uuid, actor_id=Uuid
        ),
    )
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    with Session(engine) as session:
        yield session, tables
    engine.dispose()


def add_order(session, tables, *, financial=True):
    order, client = uuid4(), uuid4()
    session.execute(
        tables["orders"]
        .insert()
        .values(
            order_id=order,
            advertiser_id=client,
            financial_version=1 if financial else None,
            complimentary=False,
        )
    )
    return order, client


def test_batch_counts_deduplicate_original_replacement_and_manual_contacts(
    delivery_db,
):
    session, t = delivery_db
    first, client = add_order(session, t)
    second, second_client = add_order(session, t)
    empty, _ = add_order(session, t)
    legacy, legacy_client = add_order(session, t, financial=False)
    creators = [uuid4() for _ in range(7)]
    session.execute(
        t["accepted"].insert(),
        [
            dict(order_id=first, client_id=client, creator_id=creators[0]),
            dict(
                order_id=second, client_id=second_client, creator_id=creators[0]
            ),
            dict(
                order_id=legacy, client_id=legacy_client, creator_id=creators[6]
            ),
        ],
    )
    for creator in creators[:2]:
        item, assignment, replacement = uuid4(), uuid4(), uuid4()
        session.execute(
            t["items"].insert().values(paid_item_id=item, order_id=first)
        )
        session.execute(
            t["assignments"]
            .insert()
            .values(
                assignment_id=assignment, creator_id=creator, paid_item_id=item
            )
        )
        session.execute(
            t["allocations"]
            .insert()
            .values(
                replacement_id=replacement,
                assignment_id=assignment,
                paid_item_id=item,
            )
        )
        session.execute(
            t["contacts"]
            .insert()
            .values(replacement_id=replacement, actor_id=client)
        )
    session.execute(
        t["transfers"].insert(),
        [
            dict(
                order_id=first,
                client_id=client,
                creator_id=creator,
                state="sent",
            )
            for creator in creators[:3]
        ]
        + [
            dict(
                order_id=first,
                client_id=client,
                creator_id=creator,
                state=state,
            )
            for creator, state in zip(
                creators[3:6], ("failed", "sending", "unknown"), strict=True
            )
        ]
        + [
            dict(
                order_id=first,
                client_id=second_client,
                creator_id=creators[6],
                state="sent",
            )
        ],
    )
    assert load_order_progress(session, [first, second, empty, legacy]) == {
        first: OrderProgress(2, 3),
        second: OrderProgress(0, 1),
        empty: OrderProgress(0, 0),
    }
    assert load_order_progress(session, [second]) == {
        second: OrderProgress(0, 1)
    }


def test_missing_history_schema_keeps_legacy_fallback(delivery_db):
    session, t = delivery_db
    order, _ = add_order(session, t)
    t["transfers"].drop(session.connection())
    assert load_order_progress(session, [order]) == {}


def test_visible_order_batch_uses_constant_query_count(delivery_db):
    session, t = delivery_db
    orders = [add_order(session, t)[0] for _ in range(50)]
    calls = []

    def count(*args):
        calls.append(1)

    event.listen(session.get_bind(), "before_cursor_execute", count)
    try:
        assert load_order_progress(session, orders) == dict.fromkeys(
            orders, OrderProgress(0, 0)
        )
        assert len(calls) == 2
        calls.clear()
        assert load_order_progress(session, []) == {} and not calls
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", count)
