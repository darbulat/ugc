"""Exercise order-list queries and actions through the authenticated admin."""

import re
from datetime import datetime, timedelta, timezone
from html import unescape
from unittest.mock import AsyncMock
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import SendMessage
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.helpers.sqlite_schema import legacy_sqlite_tables
from ugc_bot.admin.app import create_admin_app
from ugc_bot.admin.dashboard_service import (
    AdminDashboardService,
    DelayThresholds,
    PeriodWindow,
)
from ugc_bot.domain.enums import (
    AuditAction,
    ComplaintStatus,
    MessengerType,
    OrderStatus,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    ComplaintModel,
    ManagerOrderModel,
    OfferDispatchModel,
    OrderItemModel,
    OrderModel,
    PaymentModel,
    UserModel,
)

LIST = "/admin/order-model/list"


@pytest.fixture
def worklist(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'worklist.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("BOT_TOKEN", "123456:test-token")
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


@pytest.mark.asyncio
async def test_dashboard_average_check_uses_paid_totals_by_currency(worklist):
    _, engine, ids = worklist
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        for key, currency, amount, status in (
            ("Active example", "RUB", 401, PaymentStatus.PAID),
            ("Draft example", "USD", 7, PaymentStatus.PAID),
            ("Financial example", "USD", 99, PaymentStatus.PENDING),
        ):
            payment = _payment(ids[key])
            payment.currency = currency
            payment.amount = amount
            payment.status = status
            session.add(payment)
    database = create_async_engine(
        engine.url.set(drivername="sqlite+aiosqlite")
    )
    sessions = async_sessionmaker(database)
    service = AdminDashboardService(
        sessions, "UTC", DelayThresholds(3, 24, 48, 7)
    )
    window = PeriodWindow(
        now - timedelta(days=1), now + timedelta(days=1), now, now
    )
    try:
        async with sessions() as session:
            totals = await service._paid_totals(session, window)
    finally:
        await database.dispose()

    assert totals == [
        {
            "currency": "RUB",
            "count": 2,
            "amount": "601.00",
            "average_check": "300.50",
        },
        {
            "currency": "USD",
            "count": 1,
            "amount": "7.00",
            "average_check": "7.00",
        },
    ]


@pytest.mark.asyncio
async def test_dashboard_selection_timing_uses_captured_payment_and_deadline(
    worklist,
):
    _, engine, ids = worklist
    now = datetime.now(timezone.utc)
    paid_at = now - timedelta(days=4)
    deadline = paid_at + timedelta(days=7)
    with Session(engine) as session, session.begin():
        for title in ("Paid example", "Financial example", "Active example"):
            session.get(OrderModel, ids[title]).created_at = now - timedelta(
                days=9
            )
        payment = session.scalar(select(PaymentModel))
        payment.paid_at = paid_at
        for ordinal, due in enumerate(
            (deadline - timedelta(days=1), deadline), 1
        ):
            session.add(
                OrderItemModel(
                    order_id=ids["Financial example"],
                    ordinal=ordinal,
                    currency="RUB",
                    selection_minor=100,
                    accompaniment_minor=0,
                    policy_version="v1",
                    selection_due_at=due,
                    captured_at=paid_at,
                    quote_key="test",
                    quote_payload={},
                )
            )

    database = create_async_engine(
        engine.url.set(drivername="sqlite+aiosqlite")
    )
    sessions = async_sessionmaker(database)
    service = AdminDashboardService(
        sessions, "UTC", DelayThresholds(3, 24, 48, 7)
    )
    try:
        async with sessions() as session:
            attention = await service._get_order_attention(session)
    finally:
        await database.dispose()

    by_id = {row["order_id"]: row for row in attention["delayed"]}
    financial = by_id[str(ids["Financial example"])]
    assert financial["days_since_payment"] == pytest.approx(4, abs=0.01)
    assert financial["selection_days"] == 7
    legacy = by_id[str(ids["Paid example"])]
    assert legacy["days_since_payment"] == pytest.approx(4, abs=0.01)
    assert (
        legacy["selection_days"] is None
        and legacy["selection_target_days"] == 3
    )
    assert by_id[str(ids["Active example"])]["days_since_payment"] is None
    assert attention["active"] == 3


def test_worklist_filters_search_and_pagination(worklist):
    client, _, ids = worklist
    _login(client)
    response = client.get(LIST)
    assert response.status_code == 200
    html = response.text
    assert html.index("География") < html.index("Заказчик / компания")
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


def test_search_by_order_and_customer_words_in_both_views(worklist):
    client, engine, ids = worklist
    _login(client)
    with Session(engine) as session, session.begin():
        order = session.get(OrderModel, ids["Active example"])
        advertiser_id = order.advertiser_id
        order.offer_text = "Съёмка обзора товара"
        session.get(
            AdvertiserProfileModel, advertiser_id
        ).brand = "Северный Ветер"
        user = session.get(UserModel, advertiser_id)
        user.username = "Анна Петрова"
        user.telegram = "anna_pet"

    # Match a partial brand, contact name, or offer, and combine words in
    # any order, even when the order and customer hold different words.
    for term, count in (
        ("еверный", 3),
        ("етрова", 3),
        ("обзора", 1),
        ("Ветер  Северный", 3),
        ("Петрова обзора", 1),
        ("Съемка", 1),
        ("@anna_pet", 3),
        ("Петрова отсутствует", 0),
    ):
        params = {
            "group": "all",
            "status": "active",
            "no_manager": "1",
            "search": term,
        }
        flat = client.get(LIST, params=params)
        grouped = client.get(
            LIST,
            params={
                **params,
                "view": "companies",
                "company": str(advertiser_id),
            },
        )
        assert flat.status_code == grouped.status_code == 200
        assert f"Всего заказов: {count}" in flat.text, term
        assert flat.text.count('title="Редактировать"') == count, term
        assert grouped.text.count('title="Редактировать"') == count, term
        if count:
            assert "Найдено компаний: 1" in grouped.text, term
            assert f"Заказов: {count}" in grouped.text, term
            assert (
                "Съёмка обзора товара" in flat.text
                and "Съёмка обзора товара" in grouped.text
            )
        else:
            assert "Заказы не найдены" in grouped.text, term


def test_company_view_filters_before_pagination_and_expansion(worklist):
    client, engine, ids = worklist
    _login(client)
    with Session(engine) as session:
        company_id = session.get(
            OrderModel, ids["Active example"]
        ).advertiser_id

    params = {"view": "companies", "group": "all", "pageSize": 1}
    first = client.get(LIST, params=params)
    assert first.status_code == 200
    assert "Найдено компаний: 2" in first.text
    assert "Northwind" in first.text
    assert "Active example" not in first.text
    assert "Closed example" not in first.text
    assert first.text.count('aria-expanded="false"') == 1

    second = client.get(LIST, params={**params, "page": 2})
    assert "Найдено компаний: 2" in second.text
    assert "Northwind" not in second.text
    assert second.text.count('aria-expanded="false"') == 1

    params |= {
        "company": str(company_id),
        "status": "active",
        "search": "example",
        "sortBy": "offer_text",
        "sort": "asc",
    }
    expanded = client.get(LIST, params=params)
    assert expanded.status_code == 200
    assert "Найдено компаний: 1" in expanded.text
    assert "Заказов: 3" in expanded.text
    assert 'aria-expanded="true"' in expanded.text
    assert "Active example" in expanded.text
    assert "Draft example" not in expanded.text
    assert "Closed example" not in expanded.text
    assert "companyPage=2" in expanded.text

    next_orders = client.get(LIST, params={**params, "companyPage": 2})
    assert "Financial example" in next_orders.text
    assert "Active example" not in next_orders.text

    only_kazan = client.get(LIST, params={**params, "search": "Казань"})
    assert "Заказов: 1" in only_kazan.text
    assert "Active example" in only_kazan.text

    empty = client.get(LIST, params={**params, "search": "no matching orders"})
    assert "Заказы не найдены" in empty.text


def test_quick_filters_use_activity_and_assignments_before_pagination(worklist):
    client, engine, ids = worklist
    _login(client)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=8)
    with Session(engine) as session, session.begin():
        for name in (
            "Active example",
            "Closed example",
            "Dispatch example",
            "Draft example",
            "Financial example",
            "Paid example",
        ):
            order = session.get(OrderModel, ids[name])
            order.created_at = old
            order.updated_at = old
        quiet = session.get(OrderModel, ids["Active example"])
        advertiser_id = quiet.advertiser_id
        session.get(OrderModel, ids["Closed example"]).completed_at = now
        session.get(OrderModel, ids["Draft example"]).updated_at = now
        dispatch = session.scalars(select(OfferDispatchModel)).one()
        dispatch.manager_id = dispatch.blogger_id
        session.add(
            ManagerOrderModel(
                order_id=ids["Financial example"],
                user_id=advertiser_id,
                created_at=old,
            )
        )
        session.add(
            OrderModel(
                order_id=uuid4(),
                advertiser_id=advertiser_id,
                status=OrderStatus.ACTIVE,
                offer_text="Quiet second order",
                product_link="https://example.test",
                price=200,
                bloggers_needed=4,
                created_at=old,
                updated_at=old,
            )
        )

    response = client.get(LIST, params={"group": "all", "no_manager": "1"})
    assert response.status_code == 200
    assert "Active example" in response.text and "Paid example" in response.text
    assert "Financial example" not in response.text
    assert "Dispatch example" not in response.text

    response = client.get(LIST, params={"group": "all", "inactive": "1"})
    assert response.status_code == 200
    assert (
        "Financial example" in response.text
        and "Active example" in response.text
    )
    for title in (
        "Dispatch example",
        "Paid example",
        "Draft example",
        "Closed example",
    ):
        assert title not in response.text

    filters = {
        "no_manager": "1",
        "inactive": "1",
        "status": "active",
        "advertiser_id": str(advertiser_id),
        "search": "Northwind",
        "pageSize": 1,
    }
    seen = set()
    for page in (1, 2):
        response = client.get(LIST, params={**filters, "page": page})
        assert response.status_code == 200
        assert "Всего заказов: 2" in response.text
        assert response.text.count('title="Редактировать"') == 1
        seen.update(
            title
            for title in ("Active example", "Quiet second order")
            if title in response.text
        )
    assert seen == {"Active example", "Quiet second order"}


def test_dashboard_shortcuts_count_the_same_orders_as_the_list(
    worklist, monkeypatch
):
    client, engine, ids = worklist
    _login(client)
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=8)
    with Session(engine) as session, session.begin():
        for order in session.scalars(select(OrderModel)):
            order.created_at = order.updated_at = old
        advertiser = session.get(
            OrderModel, ids["Active example"]
        ).advertiser_id
        session.add(
            ManagerOrderModel(
                user_id=advertiser,
                order_id=ids["Active example"],
                created_at=old,
            )
        )
        for title, entity_type, flag in (
            ("Draft example", "order_worklist_visibility", {"visible": False}),
            ("Financial example", "order_worklist_archive", {"archived": True}),
            ("Paid example", "order_test_marker", {"test": True}),
        ):
            session.add(
                AuditLogModel(
                    entity_type=entity_type,
                    entity_id=ids[title],
                    action=AuditAction.UPDATE,
                    new_values=flag,
                    changed_at=now,
                )
            )

    # The charts and historical metrics also use PostgreSQL-only tables.
    monkeypatch.setattr(
        AdminDashboardService,
        "get_dashboard",
        AsyncMock(
            return_value={
                "problems": {"open_complaints": 0},
                "registrations": {
                    "creators": {"count": 0},
                    "advertisers": {"count": 0},
                },
                "payout_requests": [],
            }
        ),
    )
    dashboard = client.get("/admin/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.text.count("attention-queue--shortcut") == 2
    for key, title in (
        ("no_manager", "Dispatch example"),
        ("inactive", "Active example"),
    ):
        link = re.search(
            rf'href="([^"]*{key}=1)"[^>]*>[^<]*<span>.*?</span>\s*<strong>(\d+)</strong>',
            dashboard.text,
            re.DOTALL,
        )
        assert link is not None and link[2] == "1"
        result = client.get(unescape(link[1]))
        assert result.status_code == 200
        assert "Всего заказов: 1" in result.text
        assert {name for name in ids if name in result.text} == {title}


def test_order_links_preserve_list_search_and_reject_external_return(worklist):
    client, _, ids = worklist
    _login(client)
    oid = ids["Draft example"]
    query = urlencode({"group": "all", "search": "Draft example", "page": 1})
    source = f"{LIST}?{query}"
    page = client.get(source)
    link = re.search(r'href="([^"]*/admin/orders/[^"]+)"', page.text)
    assert link is not None
    detail = client.get(unescape(link[1]))
    assert detail.status_code == 200
    assert "Назад к списку" in detail.text and source in unescape(detail.text)
    assert "Редактировать заказ" in detail.text and "from_order=" in detail.text
    external = "https://example.com/admin/order-model/list"
    denied = client.get(
        f"/admin/orders/{oid}",
        params={"return_to": external},
    )
    assert f'href="{external}"' not in denied.text


def test_customer_history_filters_by_account_and_keeps_search(worklist):
    client, engine, ids = worklist
    _login(client)
    with Session(engine) as session:
        customer = session.get(OrderModel, ids["Draft example"]).advertiser_id
    params = {"group": "all", "advertiser_id": customer}
    page = client.get(LIST, params=params)
    assert "Заказы заказчика" in page.text and "Northwind" in page.text
    assert "Всего заказов: 5" in page.text
    assert "Closed example" not in page.text
    found = client.get(LIST, params={**params, "search": "Draft"})
    assert "Draft example" in found.text
    empty = client.get(LIST, params={**params, "search": "Closed"})
    assert "Заказы не найдены" in empty.text
    assert (
        client.get(LIST, params={"advertiser_id": "wrong"}).status_code == 400
    )


def test_unpaid_queue_keeps_search_and_excludes_ineligible_orders(worklist):
    client, engine, ids = worklist
    _login(client)
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        draft = session.get(OrderModel, ids["Draft example"])
        draft.created_at = now - timedelta(hours=26)
        new_ids = {}
        for title, age in (
            ("Older unpaid", 52),
            ("Fresh unpaid", 2),
            ("Paid new", 30),
            ("Captured new", 34),
            ("Hidden unpaid", 32),
            ("Test unpaid", 36),
        ):
            order = OrderModel(
                order_id=uuid4(),
                advertiser_id=draft.advertiser_id,
                offer_text=title,
                product_link="https://example.com",
                price=1200,
                bloggers_needed=4,
                created_at=now - timedelta(hours=age),
                updated_at=now,
                status=OrderStatus.NEW,
            )
            session.add(order)
            new_ids[title] = order.order_id
        session.add(_payment(new_ids["Paid new"]))
        captured = _payment(new_ids["Captured new"])
        captured.status = PaymentStatus.PENDING
        captured.paid_at = None
        captured.captured_minor = 20000
        session.add(captured)
        for title, entity, values in (
            ("Hidden unpaid", "order_worklist_visibility", {"visible": False}),
            ("Test unpaid", "order_test_marker", {"test": True}),
        ):
            session.add(
                AuditLogModel(
                    entity_type=entity,
                    entity_id=new_ids[title],
                    action=AuditAction.UPDATE,
                    new_values=values,
                )
            )
    page = client.get(LIST, params={"group": "unpaid"})
    assert page.status_code == 200 and "Всего заказов: 2" in page.text
    assert page.text.index("Older unpaid") < page.text.index("Draft example")
    for title in (
        "Fresh unpaid",
        "Paid new",
        "Captured new",
        "Hidden unpaid",
        "Test unpaid",
    ):
        assert title not in page.text
    query = urlencode({"group": "unpaid", "search": "Draft"})
    source = f"{LIST}?{query}"
    filtered = client.get(source)
    assert "Всего заказов: 1" in filtered.text
    link = re.search(r'href="([^"]*/admin/orders/[^"]+)"', filtered.text)
    assert link is not None
    detail = client.get(unescape(link[1]))
    assert detail.status_code == 200 and source in unescape(detail.text)


def test_advertiser_recency_uses_visible_order_history(worklist):
    client, engine, ids = worklist
    _login(client)
    newer = datetime(2025, 2, 12, 12, tzinfo=timezone.utc)
    older = datetime(2025, 1, 10, 10, tzinfo=timezone.utc)
    with Session(engine) as session, session.begin():
        other = session.get(OrderModel, ids["Closed example"])
        other.created_at = newer
        session.add(
            AdvertiserProfileModel(
                user_id=other.advertiser_id,
                contact="synthetic",
                brand="Newest customer",
                created_at=older,
                updated_at=older,
            )
        )
        owner = session.get(OrderModel, ids["Draft example"]).advertiser_id
        for order in session.scalars(
            select(OrderModel).where(OrderModel.advertiser_id == owner)
        ):
            if order.status != OrderStatus.DELETED:
                order.created_at = older

    url = "/admin/users/advertisers"
    params = {"sort": "last_order_at", "order": "desc"}
    descending = client.get(url, params=params)
    assert (
        descending.status_code == 200 and "Последний заказ" in descending.text
    )
    assert descending.text.index("Newest customer") < descending.text.index(
        "Northwind"
    )
    assert "12.02.2025, 15:00" in descending.text
    assert "10.01.2025, 13:00" in descending.text
    ascending = client.get(url, params={**params, "order": "asc"})
    assert ascending.text.index("Northwind") < ascending.text.index(
        "Newest customer"
    )


def test_test_order_requires_marker_and_keeps_audit(worklist):
    client, engine, ids = worklist
    _login(client)
    draft_id = ids["Draft example"]
    csrf = re.search(
        r'name="csrf_token" value="([^"]+)"', client.get(LIST).text
    )[1]

    def post(order_id, operation, token=csrf):
        return client.post(
            f"/admin/order-worklist/{order_id}/{operation}?group=test",
            data={"csrf_token": token},
        )

    assert post(draft_id, "mark-test", "").status_code == 403
    assert "Удалить можно только" in post(draft_id, "delete-test").text
    paid = ids["Paid example"]
    assert "Заказ отмечен" in post(paid, "mark-test").text
    test_list = client.get(LIST, params={"group": "test"})
    assert "Paid example" in test_list.text
    assert "Paid example" not in client.get(LIST).text
    assert "Удалить можно только" in post(paid, "delete-test").text
    assert "Тестовая отметка снята" in post(paid, "unmark-test").text
    assert "Заказ отмечен" in post(draft_id, "mark-test").text
    assert "Заказ отмечен" in post(draft_id, "mark-test").text
    assert "Удалить заказ" in client.get(LIST, params={"group": "test"}).text
    assert "Тестовая отметка снята" in post(draft_id, "unmark-test").text
    assert "Удалить можно только" in post(draft_id, "delete-test").text
    assert "Заказ отмечен" in post(draft_id, "mark-test").text
    assert "Тестовый заказ удалён" in post(draft_id, "delete-test").text
    assert "Draft example" not in client.get(LIST, params={"group": "all"}).text
    with Session(engine) as session:
        order = session.get(OrderModel, draft_id)
        assert order.status == OrderStatus.DELETED and order.dispatch_stopped
        events = session.scalars(
            select(AuditLogModel).where(AuditLogModel.entity_id == draft_id)
        ).all()
        marker_events = [
            event
            for event in events
            if event.entity_type == "order_test_marker"
        ]
        assert [
            event.new_values["test"]
            for event in sorted(
                marker_events, key=lambda event: event.changed_at
            )
        ] == [True, False, True]
        assert len(events) == 4
        assert any(
            event.new_values == {"status": "deleted", "test": True}
            for event in events
        )
        assert (
            session.get(OrderModel, ids["Paid example"]).status
            == OrderStatus.ACTIVE
        )


def test_delete_marked_draft_from_card_without_touching_related_orders(
    worklist,
):
    client, engine, ids = worklist
    _login(client)
    draft_id = ids["Draft example"]
    source = f"{LIST}?group=all&search=Draft"
    edit = f"/admin/order-model/edit/{draft_id}"
    detail = f"/admin/orders/{draft_id}"
    with Session(engine) as session, session.begin():
        draft = session.get(OrderModel, draft_id)
        draft.status = OrderStatus.PENDING_MODERATION
        draft.financial_version = "v1"

    page = client.get(LIST)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    action = f"/admin/order-worklist/{draft_id}/delete-test"
    assert ">Удалить заказ</button>" not in client.get(detail).text
    assert (
        "Удалить можно только"
        in client.post(action, data={"csrf_token": token}).text
    )
    assert (
        "Заказ отмечен"
        in client.post(
            f"/admin/order-worklist/{draft_id}/mark-test",
            data={"csrf_token": token},
        ).text
    )
    for url in (edit, detail):
        page = client.get(url, params={"return_to": source})
        assert page.status_code == 200
        assert ">Удалить заказ</button>" in page.text
    assert (
        ">Удалить заказ</button>"
        not in client.get(f"/admin/orders/{ids['Paid example']}").text
    )
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    assert client.post(action).status_code == 403
    for name in ("Paid example", "Active example", "Dispatch example"):
        denied = client.post(
            f"/admin/order-worklist/{ids[name]}/delete-test",
            data={"csrf_token": token},
        )
        assert "Удалить можно только" in denied.text
    removed = client.post(
        action,
        params={"return_to": source},
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert removed.status_code == 303 and removed.headers["location"] == source
    assert client.get(detail).status_code == 404
    assert client.get(edit).status_code == 404
    with Session(engine) as session:
        draft = session.get(OrderModel, draft_id)
        assert draft.status == OrderStatus.DELETED and draft.dispatch_stopped
        event = session.scalars(
            select(AuditLogModel).where(
                AuditLogModel.entity_id == draft_id,
                AuditLogModel.action == AuditAction.DELETE,
            )
        ).one()
        assert event.old_values == {"status": "pending_moderation"}
        assert event.new_values == {"status": "deleted", "test": True}


def test_assign_manager_from_filtered_list_preserves_order_and_audit(worklist):
    client, engine, ids = worklist
    order_id = ids["Paid example"]
    action = f"/admin/order-worklist/{order_id}/assign-manager"
    params = {"group": "work", "search": str(order_id), "no_manager": "1"}
    manager_id, other_manager_id = uuid4(), uuid4()
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        session.add_all(
            UserModel(
                user_id=user_id,
                username=label,
                telegram=handle,
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.ACTIVE,
                created_at=now,
                updated_at=now,
            )
            for user_id, label, handle in (
                (manager_id, "Manager One", "manager_one"),
                (other_manager_id, "Manager Two", "manager_two"),
            )
        )
        session.add(
            ManagerOrderModel(
                order_id=ids["Financial example"],
                user_id=other_manager_id,
                created_at=now,
            )
        )

    assert client.get(action, follow_redirects=False).status_code == 404
    assert client.post(action).status_code == 401
    _login(client)
    assert (
        client.post(
            action, data={"manager_telegram": "manager_one"}
        ).status_code
        == 403
    )
    assert client.get(action).status_code == 404
    page = client.get(LIST, params=params)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    assert "Назначить менеджера" in page.text
    assert '<option value="@manager_two">' in page.text
    assert '<option value="@manager_one">' not in page.text

    invalid = client.post(
        action,
        params=params,
        data={
            "csrf_token": token,
            "manager_telegram": "@missing_user",
        },
    )
    assert "не найден в боте" in invalid.text and "Paid example" in invalid.text

    saved = client.post(
        action,
        params=params,
        data={"csrf_token": token, "manager_telegram": " @Manager_One "},
    )
    assert "Менеджер @manager_one назначен." in saved.text
    assert "Paid example" not in saved.text
    assert "Всего заказов: 0" in saved.text
    assert saved.url.params["no_manager"] == "1"
    assert saved.url.params["search"] == str(order_id)
    listing = client.get(LIST, params={"search": str(order_id)})
    assert "Paid example" in listing.text and "Manager One" in listing.text

    stale = client.post(
        action,
        params=params,
        data={
            "csrf_token": token,
            "manager_telegram": "manager_two",
        },
    )
    assert "У заказа уже есть менеджер" in stale.text
    closed = client.post(
        f"/admin/order-worklist/{ids['Closed example']}/assign-manager",
        data={"csrf_token": token, "manager_telegram": "manager_two"},
    )
    assert "Заказ недоступен для назначения менеджера" in closed.text

    with Session(engine) as session:
        assignments = session.scalars(
            select(ManagerOrderModel).where(
                ManagerOrderModel.order_id.in_(
                    [order_id, ids["Closed example"]]
                )
            )
        ).all()
        assert [(m.order_id, m.user_id) for m in assignments] == [
            (order_id, manager_id)
        ]
        assert session.get(OrderModel, order_id).status == OrderStatus.ACTIVE
        payment = session.scalars(
            select(PaymentModel).where(PaymentModel.order_id == order_id)
        ).one()
        assert payment.status == PaymentStatus.PAID and payment.amount == 200
        event = session.scalars(
            select(AuditLogModel).where(
                AuditLogModel.entity_id == order_id,
                AuditLogModel.entity_type == "order_manager_assignment",
            )
        ).one()
        assert event.old_values == {"manager_id": None}
        assert event.new_values == {"manager_id": str(manager_id)}


@pytest.mark.parametrize("notice", ["sent", "blocked", "test"])
def test_replace_manager_in_list_and_notify_only_new_manager(
    worklist, monkeypatch, notice
):
    from ugc_bot.admin import app as admin_app

    client, engine, ids = worklist
    order_id = ids["Paid example"]
    action = f"/admin/order-worklist/{order_id}/assign-manager"
    previous, target, teammate = (uuid4() for _ in range(3))
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        order = session.get(OrderModel, order_id)
        customer = session.get(UserModel, order.advertiser_id)
        customer.telegram_id = "10005"
        for uid, name, chat_id in (
            (previous, "previous_manager", "10002"),
            (target, "target_manager", "10003"),
            (teammate, "other_manager", "10004"),
        ):
            session.add(
                UserModel(
                    user_id=uid,
                    username=name,
                    telegram=name,
                    telegram_id=chat_id,
                    status=UserStatus.ACTIVE,
                    messenger_type=MessengerType.TELEGRAM,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.add_all(
            ManagerOrderModel(order_id=order_id, user_id=uid, created_at=now)
            for uid in (previous, teammate)
        )
        session.add(
            OfferDispatchModel(
                order_id=order_id,
                blogger_id=customer.user_id,
                manager_id=previous,
                accepted=True,
                in_offer=True,
                created_at=now,
            )
        )
        if notice == "test":
            session.add(
                AuditLogModel(
                    entity_id=order_id,
                    entity_type="order_test_marker",
                    action=AuditAction.UPDATE,
                    new_values={"test": True},
                )
            )

    def check_saved_assignment(*, chat_id, text, request_timeout):
        assert chat_id == 10003
        assert "Paid example" in text and "Мои заказы" in text
        assert request_timeout == 5
        with Session(engine) as session:
            assert (
                session.get(ManagerOrderModel, (target, order_id)) is not None
            )
            assert session.get(ManagerOrderModel, (previous, order_id)) is None
        if notice == "blocked":
            raise TelegramForbiddenError(
                SendMessage(chat_id=chat_id, text=text), "blocked"
            )

    send = AsyncMock(side_effect=check_saved_assignment)
    monkeypatch.setattr(admin_app.Bot, "send_message", send)
    _login(client)
    params = {
        "group": "test" if notice == "test" else "work",
        "search": str(order_id),
    }
    page = client.get(LIST, params=params)
    assert "Сменить менеджера" in page.text and "Кого заменить" in page.text
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    data = {
        "csrf_token": token,
        "previous_manager": str(previous),
        "manager_telegram": "@TARGET_MANAGER",
    }
    missing_confirmation = client.post(action, params=params, data=data)
    assert "Подтвердите замену менеджера" in missing_confirmation.text
    send.assert_not_awaited()
    saved = client.post(action, params=params, data={**data, "confirmed": "1"})
    assert "Менеджер заменён на @target_manager." in saved.text
    assert saved.url.params["search"] == str(order_id)
    assert "other_manager" in saved.text
    if notice == "sent":
        assert "отправлено сообщение в Telegram" in saved.text
    elif notice == "blocked":
        assert "не удалось подтвердить" in saved.text
    assert send.await_count == (0 if notice == "test" else 1)
    stale = client.post(action, params=params, data={**data, "confirmed": "1"})
    assert "Менеджер уже изменился" in stale.text
    assert send.await_count == (0 if notice == "test" else 1)

    with Session(engine) as session:
        managers = session.scalars(
            select(ManagerOrderModel.user_id).where(
                ManagerOrderModel.order_id == order_id
            )
        ).all()
        assert set(managers) == {target, teammate}
        dispatch = session.scalars(
            select(OfferDispatchModel).where(
                OfferDispatchModel.order_id == order_id
            )
        ).one()
        assert (
            dispatch.manager_id == target
            and dispatch.accepted
            and dispatch.in_offer
        )
        assert session.get(OrderModel, order_id).status == OrderStatus.ACTIVE
        payment = session.scalars(
            select(PaymentModel).where(PaymentModel.order_id == order_id)
        ).one()
        assert payment.status == PaymentStatus.PAID and payment.amount == 200
        event = session.scalars(
            select(AuditLogModel).where(
                AuditLogModel.entity_id == order_id,
                AuditLogModel.entity_type == "order_manager_assignment",
            )
        ).one()
        assert event.old_values == {
            "manager_id": str(previous),
            "telegram": "previous_manager",
        }
        assert event.new_values == {
            "manager_id": str(target),
            "telegram": "target_manager",
        }


def test_archive_paid_order_preserves_status_payment_and_audit(worklist):
    client, engine, ids = worklist
    _login(client)
    order_id = ids["Paid example"]
    actions = f"/admin/order-worklist/{order_id}"
    params = {"search": str(order_id)}
    page = client.get(LIST, params=params)
    token = re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1]
    assert "Удалить из списка" in page.text
    assert client.post(f"{actions}/archive-order").status_code == 403
    for _ in range(2):
        response = client.post(
            f"{actions}/archive-order",
            params=params,
            data={"csrf_token": token},
        )
        assert "Заказ удалён из списка" in response.text
        assert "Paid example" not in response.text
    assert (
        "Paid example"
        not in client.get(LIST, params={**params, "group": "all"}).text
    )
    removed_params = {**params, "group": "removed"}
    assert "Paid example" in client.get(LIST, params=removed_params).text

    with Session(engine) as session:
        order = session.get(OrderModel, order_id)
        assert order.status == OrderStatus.ACTIVE and not order.dispatch_stopped
        payment = session.scalars(
            select(PaymentModel).where(PaymentModel.order_id == order_id)
        ).one()
        assert payment.status == PaymentStatus.PAID and payment.amount == 200

    response = client.post(
        f"{actions}/restore-archived",
        params=removed_params,
        data={"csrf_token": token},
    )
    assert "Заказ возвращён из удалённых" in response.text
    assert "Paid example" not in response.text
    assert "Paid example" in client.get(LIST, params=params).text
    with Session(engine) as session:
        events = session.scalars(
            select(AuditLogModel)
            .where(AuditLogModel.entity_id == order_id)
            .order_by(AuditLogModel.changed_at)
        ).all()
        assert [row.entity_type for row in events] == [
            "order_worklist_archive"
        ] * 2
        assert [row.old_values for row in events] == [
            {"archived": False},
            {"archived": True},
        ]
        assert [row.new_values for row in events] == [
            {"archived": True},
            {"archived": False},
        ]


def test_order_editor_rejects_new_overflow_and_preserves_legacy_text(worklist):
    client, engine, ids = worklist
    _login(client)
    oid = ids["Draft example"]
    edit = f"/admin/order-model/edit/{oid}"
    legacy = "Старый регион, " * 25
    with Session(engine) as session, session.begin():
        session.get(OrderModel, oid).geography = legacy
    data = {
        "order_type": "ugc_only",
        "product_link": "https://example.com",
        "offer_text": "Draft example",
        "barter_description": "я" * 4001,
        "price": "1200",
        "bloggers_needed": "4",
        "status": "new",
        "geography": legacy,
        "save": "Save and continue editing",
    }
    invalid = client.post(edit, data=data)
    assert invalid.status_code == 400
    assert "Максимум 4000 символов. Сейчас 4001." in invalid.text
    assert "Максимум 200 символов." not in invalid.text
    saved = client.post(edit, data={**data, "barter_description": "Билеты"})
    assert saved.status_code == 200 and "Билеты" in saved.text
    with Session(engine) as session:
        order = session.get(OrderModel, oid)
        assert order.geography == legacy
        assert order.barter_description == "Билеты"


def test_complaint_read_search_and_close_without_measures(worklist):
    client, engine, ids = worklist
    complaint_id = uuid4()
    reason = "Подробности обращения\n\n" + "x" * 300
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        order = session.get(OrderModel, ids["Active example"])
        reporter = session.get(OrderModel, ids["Closed example"]).advertiser_id
        session.add(
            ComplaintModel(
                complaint_id=complaint_id,
                order_id=order.order_id,
                reporter_id=reporter,
                reported_id=order.advertiser_id,
                reason=reason,
                status=ComplaintStatus.PENDING,
                created_at=now,
                updated_at=now,
            )
        )
    url = "/admin/complaint-model/list"
    close = f"/admin/complaints/{complaint_id}/close"
    assert client.post(close).status_code == 401
    _login(client)
    assert client.post(close).status_code == 403
    listing = client.get(url, params={"search": "client_name"})
    assert listing.status_code == 200
    assert "Подробности обращения" in listing.text
    assert "client_name" in listing.text and "Active example" in listing.text
    assert "Жалобы не найдены" in client.get(url, params={"search": "%"}).text
    detail = client.get(
        f"/admin/complaint-model/details/{complaint_id}",
        params={"return_to": f"{url}?status=open"},
    )
    assert detail.status_code == 200 and reason in detail.text
    assert "Закрыть без мер" in detail.text and "К жалобам" in detail.text
    assert re.search(r"admin-shell\.css\?v=[0-9a-f]{12}", detail.text)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', detail.text)[1]
    closed = client.post(close, data={"csrf_token": csrf})
    assert "Жалоба закрыта без мер" in closed.text
    assert "Подробности обращения" not in closed.text
    retry = client.post(close, data={"csrf_token": csrf})
    assert "Жалоба уже закрыта" in retry.text
    history = client.get(
        url, params={"status": "closed", "search": str(complaint_id)}
    )
    assert (
        "Подробности обращения" in history.text
        and "Закрыта без мер" in history.text
    )
    with Session(engine) as session:
        complaint = session.get(ComplaintModel, complaint_id)
        assert complaint.status == ComplaintStatus.DISMISSED
        assert complaint.reviewed_at is not None
        assert (
            session.get(UserModel, complaint.reported_id).status
            == UserStatus.ACTIVE
        )
        event = session.scalars(
            select(AuditLogModel).where(AuditLogModel.entity_id == complaint_id)
        ).one()
        assert event.old_values == {"status": "pending"}
        assert event.new_values == {"status": "dismissed"}


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
    assert (
        "Draft example" not in client.get(LIST, params={"group": "hidden"}).text
    )


def test_restore_legacy_hidden_order_keeps_visibility_history(worklist):
    client, engine, ids = worklist
    order_id = ids["Draft example"]
    # The first event uses the production format before restore was introduced.
    # A timestamp ahead of the app clock must still sort before the new event.
    with Session(engine) as session, session.begin():
        session.add(
            AuditLogModel(
                entity_type="order_worklist_visibility",
                entity_id=order_id,
                action=AuditAction.UPDATE,
                old_values={"visible": True},
                new_values={"visible": False},
                changed_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            )
        )
    _login(client)
    hidden = {"group": "hidden", "search": str(order_id)}
    hidden_page = client.get(LIST, params=hidden)
    assert "Draft example" in hidden_page.text
    assert "Вернуть в список" in hidden_page.text
    assert "Draft example" not in client.get(LIST).text
    assert (
        "Dispatch example"
        not in client.get(LIST, params={"group": "hidden"}).text
    )
    token = re.search(r'name="csrf_token" value="([^"]+)"', hidden_page.text)
    assert token is not None
    restore_url = f"/admin/order-worklist/{order_id}/restore"
    assert client.post(restore_url, params=hidden).status_code == 403
    restored = client.post(
        restore_url, params=hidden, data={"csrf_token": token[1]}
    )
    assert "Заказ возвращён в список." in restored.text
    assert "Draft example" not in restored.text
    assert "Draft example" in client.get(LIST).text
    client.post(restore_url, params=hidden, data={"csrf_token": token[1]})

    def history():
        with Session(engine) as session:
            order = session.get(OrderModel, order_id)
            assert order.status == OrderStatus.NEW
            assert order.completed_at is None
            events = session.scalars(
                select(AuditLogModel)
                .where(AuditLogModel.entity_id == order_id)
                .order_by(AuditLogModel.changed_at)
            )
            return [
                (event.old_values["visible"], event.new_values["visible"])
                for event in events
            ]

    assert history() == [(True, False), (False, True)]
    client.post(
        f"/admin/order-worklist/{order_id}/hide",
        data={"csrf_token": token[1]},
    )
    assert "Draft example" in client.get(LIST, params=hidden).text
    assert history() == [(True, False), (False, True), (True, False)]


def test_worklist_pause_and_resume_keep_active_order(worklist, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from sqlalchemy import insert

    from ugc_bot.container import Container
    from ugc_bot.infrastructure.db.dispatch_control import CONTROLS

    resume = AsyncMock()
    publisher = SimpleNamespace(resume_order_dispatch=resume)
    monkeypatch.setattr(
        Container, "build_outbox_publisher", lambda self: publisher
    )
    client, engine, ids = worklist
    order_id = ids["Active example"]
    with Session(engine) as session, session.begin():
        session.execute(
            insert(CONTROLS).values(
                order_id=order_id,
                run=1,
                paused=False,
                audience_ready=False,
            )
        )
    _login(client)
    html = client.get(LIST).text
    assert html.count("Пауза рассылки") == 1
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', html)[1]
    url = f"/admin/order-worklist/{order_id}"
    assert client.post(f"{url}/pause").status_code == 403
    paused = client.post(f"{url}/pause", data={"csrf_token": csrf}).text
    assert "Возобновить рассылку" in paused
    with Session(engine) as session:
        assert session.get(OrderModel, order_id).status == OrderStatus.ACTIVE
    resume.assert_not_awaited()
    for _ in range(2):
        resumed = client.post(f"{url}/resume", data={"csrf_token": csrf})
        assert resumed.status_code == 200
    assert "Пауза рассылки" in resumed.text
    resume.assert_awaited_once()
    order, run = resume.await_args.args
    assert order.order_id == order_id and run == 2


def test_customer_directory_search_and_filters(worklist):
    client, engine, ids = worklist
    _login(client)
    order_id = ids["Active example"]
    now = datetime.now(timezone.utc)
    with Session(engine) as session, session.begin():
        customer_id = session.get(OrderModel, order_id).advertiser_id
        creator_id = session.get(
            OrderModel, ids["Closed example"]
        ).advertiser_id
        customer = session.get(AdvertiserProfileModel, customer_id)
        customer.brand = "Марка & Партнёры"
        customer.site_link = "https://example.com/client_site"
        session.add_all(
            [
                ComplaintModel(
                    complaint_id=uuid4(),
                    order_id=order_id,
                    reporter_id=creator_id,
                    reported_id=customer_id,
                    reason="Долгий ответ",
                    status=ComplaintStatus.PENDING,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )

    url = "/admin/users/advertisers"
    for query in (
        "Марка & Партнёры",
        "client_name",
        "client_site",
        str(customer_id),
    ):
        response = client.get(
            url,
            params={
                "q": query,
                "activity": "with_orders",
                "with_complaints": "true",
                "period": "7d",
            },
        )
        assert response.status_code == 200
        assert "Найдено 1" in response.text
    for query in ("clientXsite", "%", "_"):
        response = client.get(url, params={"q": query})
        if query == "_":
            # The literal underscore is present in the stored name and site.
            assert "Найдено 1" in response.text
        else:
            assert "Заказчики не найдены" in response.text
    response = client.get(url, params={"activity": "without_orders"})
    assert "Заказчики не найдены" in response.text
