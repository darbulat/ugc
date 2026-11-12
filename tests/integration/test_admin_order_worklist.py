"""Exercise order-list queries and actions through the authenticated admin."""

import re
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from tests.helpers.sqlite_schema import legacy_sqlite_tables
from ugc_bot.admin.app import create_admin_app
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    OfferDispatchModel,
    OrderModel,
    PaymentModel,
    UserModel,
)

LIST = "/admin/order-model/list"


@pytest.fixture
def worklist(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'worklist.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    Base.metadata.create_all(engine, tables=legacy_sqlite_tables(Base.metadata))
    user_id, other_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        for uid, username in [(user_id, "client_name"), (other_id, "other")]:
            session.add(
                UserModel(
                    user_id=uid,
                    username=username,
                    messenger_type=MessengerType.TELEGRAM,
                    status=UserStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.add(
            AdvertiserProfileModel(
                user_id=user_id,
                contact="test-contact",
                brand="Northwind",
                created_at=now,
                updated_at=now,
            )
        )
        orders = {
            name: OrderModel(
                order_id=uuid4(),
                advertiser_id=user_id if name != "Closed example" else other_id,
                status=status,
                offer_text=name,
                product_link="https://example.com",
                geography="Казань" if name == "Active example" else None,
                price=1200,
                bloggers_needed=4,
                created_at=now,
                updated_at=now,
                financial_version="v1" if name == "Financial example" else None,
            )
            for name, status in {
                "Active example": OrderStatus.ACTIVE,
                "Closed example": OrderStatus.CLOSED,
                "Financial example": OrderStatus.ACTIVE,
                "Draft example": OrderStatus.NEW,
                "Paid example": OrderStatus.ACTIVE,
                "Dispatch example": OrderStatus.NEW,
                "Deleted example": OrderStatus.DELETED,
            }.items()
        }
        ids = {name: order.order_id for name, order in orders.items()}
        session.add_all(orders.values())
        session.add(
            OfferDispatchModel(
                order_id=ids["Dispatch example"],
                blogger_id=other_id,
                created_at=now,
                in_offer=True,
            )
        )
        session.add(_payment(ids["Paid example"]))

    with TestClient(create_admin_app()) as client:
        yield client, engine, ids
    engine.dispose()


def _payment(order_id):
    now = datetime.now(timezone.utc)
    return PaymentModel(
        payment_id=uuid4(),
        order_id=order_id,
        provider="test",
        status=PaymentStatus.PAID,
        amount=200,
        currency="RUB",
        external_id=str(order_id),
        created_at=now,
        updated_at=now,
        paid_at=now,
    )


def _login(client):
    response = client.post(
        "/admin/login",
        data={"username": "test_admin", "password": "test_pass"},
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_worklist_filters_search_and_pagination(worklist):
    client, _, ids = worklist
    _login(client)
    response = client.get(LIST)
    assert response.status_code == 200
    html = response.text
    assert html.index("География") < html.index("Компания / бренд")
    assert "1 200,00 RUB" in html
    assert "Closed example" not in html
    assert "Deleted example" not in html
    assert "Closed example" in client.get(LIST, params={"group": "closed"}).text
    assert "Closed example" in client.get(LIST, params={"group": "all"}).text

    for term in (
        "Казань",
        "client_name",
        "northwind",
        str(ids["Active example"]),
    ):
        result = client.get(LIST, params={"search": term})
        assert "Active example" in result.text
        assert "Closed example" not in result.text
    assert "Заказы не найдены" in client.get(LIST, params={"search": "%"}).text
    params = {"group": "all", "status": "active", "pageSize": 1}
    first = client.get(LIST, params=params)
    second = client.get(LIST, params={**params, "page": 2})
    assert "Всего заказов: 3" in first.text
    assert "Всего заказов: 3" in second.text
    assert first.text.count('title="Редактировать"') == 1
    assert second.text.count('title="Редактировать"') == 1
    past_end = client.get(
        LIST, params={**params, "page": 4}, follow_redirects=False
    )
    assert (
        past_end.status_code == 302 and "page=3" in past_end.headers["location"]
    )
    assert {name for name in ids if name in first.text} != {
        name for name in ids if name in second.text
    }


def test_worklist_actions_preserve_records_and_protect_payments(worklist):
    client, engine, ids = worklist

    def post(name, operation, token=None, **kwargs):
        return client.post(
            f"/admin/order-worklist/{ids[name]}/{operation}",
            data={"csrf_token": token or ""},
            **kwargs,
        )

    assert (
        post("Active example", "close", follow_redirects=False).status_code
        == 401
    )
    _login(client)
    token = re.search(
        r'name="csrf_token" value="([^"]+)"', client.get(LIST).text
    )
    assert token is not None
    csrf = token[1]
    assert post("Active example", "close").status_code == 403
    assert post("Active example", "close", "incorrect").status_code == 403
    assert "Заказ закрыт" in post("Active example", "close", csrf).text
    assert "Active example" not in client.get(LIST).text
    assert "Active example" in client.get(LIST, params={"group": "closed"}).text

    for name in ("Paid example", "Financial example"):
        assert (
            "только активный заказ без оплаты" in post(name, "close", csrf).text
        )
    assert "Скрытие недоступно" in post("Dispatch example", "hide", csrf).text
    assert "Заказ убран из списка" in post("Draft example", "hide", csrf).text
    post(
        "Draft example", "hide", csrf
    )  # Retrying must not duplicate the audit.
    assert "Draft example" not in client.get(LIST, params={"group": "all"}).text
    detail = client.get(f"/admin/order-model/details/{ids['Draft example']}")
    assert detail.status_code == 200 and "Draft example" in detail.text

    with Session(engine) as session, session.begin():
        closed = session.get(OrderModel, ids["Active example"])
        hidden = session.get(OrderModel, ids["Draft example"])
        paid = session.get(OrderModel, ids["Paid example"])
        assert closed.status == OrderStatus.CLOSED and closed.completed_at
        assert hidden.status == OrderStatus.NEW and hidden.completed_at is None
        assert paid.status == OrderStatus.ACTIVE
        audit = session.scalars(
            select(AuditLogModel).where(
                AuditLogModel.entity_id.in_([closed.order_id, hidden.order_id])
            )
        ).all()
        assert {entry.entity_type: entry.new_values for entry in audit} == {
            "order": {"status": "closed"},
            "order_worklist_visibility": {"visible": False},
        }
        assert len(audit) == 2
        session.add(_payment(hidden.order_id))
    assert "Draft example" in client.get(LIST).text
