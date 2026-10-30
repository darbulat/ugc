"""Customer journeys on production templates and synthetic signed APIs."""

import time
from urllib.parse import urlparse

import pytest
from playwright.sync_api import expect

from tests.e2e.test_miniapp_design_system import open_app, screenshot
from tests.e2e.test_miniapp_selection_ui import (
    ORDER,
    SIGNED,
    SelectionNetwork,
    fill,
)

pytestmark = [pytest.mark.e2e, pytest.mark.timeout(30)]


class CustomerNetwork(SelectionNetwork):
    def __init__(self):
        super().__init__()
        self.customer_posts = []
        self.fail_support = False
        self.orders = None
        self.has_completed_work = False
        self.fail_completion = False

    def route(self, route):
        path = urlparse(route.request.url).path
        if "/customer/" in path:
            body = route.request.post_data_json
            self.customer_posts.append((path, body))
            if path.endswith("/catalog"):
                data = {
                    "services": [
                        {
                            "code": "result",
                            "title": "Оплата за результат",
                            "mode": "assessment",
                        },
                        {
                            "code": "regular_search",
                            "title": "Регулярный поиск",
                            "mode": "lead",
                        },
                    ]
                }
            elif path.endswith("/completion"):
                route.fulfill(
                    status=503 if self.fail_completion else 200,
                    json={"has_completed_work": self.has_completed_work},
                )
                return
            elif path.endswith("/ratings"):
                data = {
                    "authors": [
                        {
                            "blogger_id": ORDER,
                            "display_name": "Автор Анна",
                            "rating_eligible": True,
                            "score": None,
                            "comment": None,
                        }
                    ]
                }
            elif path.endswith("/support/list"):
                data = {
                    "requests": [
                        {
                            "state": "in_progress",
                            "payload": {"reason": "Ранее отправленный вопрос"},
                        }
                    ]
                }
            elif path.endswith("/followups/state"):
                data = {
                    "next_action": "orders",
                    "order_id": ORDER,
                    "opted_out": False,
                    "stop_reason": None,
                }
            elif path.endswith("/support") and self.fail_support:
                route.abort()
                return
            else:
                data = {"request_id": ORDER, "opted_out": True}
            route.fulfill(json=data)
            return
        if path.endswith("/orders/list"):
            if self.orders is not None:
                body = route.request.post_data_json
                rows = [
                    o
                    for o in self.orders
                    if not body.get("status") or o["status"] == body["status"]
                ]
                start = body.get("page", 0) * body.get("limit", 10)
                limit = body.get("limit", 10)
                route.fulfill(
                    json={
                        "orders": rows[start : start + limit],
                        "total": len(rows),
                        "has_more": start + limit < len(rows),
                    }
                )
                return
            route.fulfill(
                json={
                    "orders": [
                        {
                            "order_id": ORDER,
                            "public_title": "Кофе — заказ №1042",
                            "status": "closed",
                            "created_at": "2026-10-30T10:00:00Z",
                            "financial_version": "v1",
                            "bloggers_needed": 10,
                        }
                    ]
                }
            )
            return
        if path.endswith("/admin/partners/context"):
            route.fulfill(json={"capabilities": ["manage"]})
            return
        if path.endswith("/ratings"):
            self.customer_posts.append((path, route.request.post_data_json))
            route.fulfill(json={"score": 5})
            return
        super().route(route)


class IntentTrackingNetwork(CustomerNetwork):
    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/financial/orders/policies"):
            route.fulfill(
                json={
                    "writes_paused": False,
                    "currency": "RUB",
                    "policies": self.policies,
                    "funnel_tracking": True,
                }
            )
            return
        if path.endswith("/financial/orders/funnel/stage"):
            route.fulfill(json={"ok": True})
            return
        if path.endswith("/customer/followups/register-brief"):
            self.customer_posts.append((path, route.request.post_data_json))
            route.fulfill(
                json={"intent_id": "e0000000-0000-4000-8000-000000000001"}
            )
            return
        super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_new_brief_and_created_order_share_followup_intent(page, platform):
    network = IntentTrackingNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    with page.expect_request(
        lambda request: (
            request.url.endswith("/customer/followups/activity")
            and request.post_data_json.get("event") == "brief_opened"
            and request.post_data_json.get("intent_id")
        ),
        timeout=5000,
    ) as opened:
        page.locator("#btn-show-create-order").click()
    intent = opened.value.post_data_json["intent_id"]
    registration = [
        body
        for path, body in network.customer_posts
        if path.endswith("/customer/followups/register-brief")
    ]
    assert registration and intent == "e0000000-0000-4000-8000-000000000001"
    fill(page)
    with page.expect_request(
        lambda request: (
            request.url.endswith("/customer/followups/activity")
            and request.post_data_json.get("event") == "order_created"
        )
    ) as created:
        page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert network.creates[0]["funnel_id"] == intent
    assert created.value.post_data_json["intent_id"] == intent


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_unavailable_followup_registration_does_not_block_order(page, platform):
    class UnavailableRegistration(IntentTrackingNetwork):
        def route(self, route):
            if urlparse(route.request.url).path.endswith(
                "/customer/followups/register-brief"
            ):
                route.fulfill(status=503, json={"error": "unavailable"})
                return
            super().route(route)

    network = UnavailableRegistration()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#form-umc-intake")).to_be_visible()
    fill(page)
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    assert len(network.creates) == 1
    assert not [
        body
        for path, body in network.customer_posts
        if path.endswith("/customer/followups/activity")
        and body.get("event") in {"brief_opened", "brief_changed"}
        and body.get("intent_id")
    ]


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_reopening_saved_brief_preserves_server_intent(page, platform):
    network = IntentTrackingNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#form-umc-intake")).to_be_visible()
    page.locator("#intake-brief").fill("Saved before payment")
    page.evaluate("() => UMCIntakeProgress.flush()")
    page.reload()
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#intake-brief")).to_have_value("Saved before payment")
    expect(page.locator("#screen-intake")).to_have_attribute(
        "aria-busy", "false"
    )
    registrations = [
        body
        for path, body in network.customer_posts
        if path.endswith("/customer/followups/register-brief")
    ]
    assert len(registrations) == 1


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_late_registration_response_does_not_start_followups(page, platform):
    class SlowRegistration(IntentTrackingNetwork):
        def route(self, route):
            if urlparse(route.request.url).path.endswith(
                "/customer/followups/register-brief"
            ):
                time.sleep(3.5)
                route.fulfill(
                    json={"intent_id": "e0000000-0000-4000-8000-000000000001"}
                )
                return
            super().route(route)

    network = SlowRegistration()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    expect(page.locator("#form-umc-intake")).to_be_visible()
    page.locator("#intake-brief").fill("This brief remains usable")
    page.wait_for_timeout(600)
    assert not [
        body
        for path, body in network.customer_posts
        if path.endswith("/customer/followups/activity")
        and body.get("intent_id")
    ]


class FullServiceCatalogNetwork(CustomerNetwork):
    def route(self, route):
        if urlparse(route.request.url).path.endswith(
            "/customer/services/catalog"
        ):
            route.fulfill(
                json={
                    "services": [
                        {
                            "code": "selection",
                            "title": "Автоподбор",
                            "mode": "order",
                        },
                        {
                            "code": "accompaniment",
                            "title": "Подбор под ключ",
                            "mode": "order",
                        },
                        {
                            "code": "regular_search",
                            "title": "Регулярный поиск",
                            "mode": "lead",
                        },
                        {
                            "code": "ambassadors",
                            "title": "Ведение амбассадоров",
                            "mode": "lead",
                        },
                        {
                            "code": "result",
                            "title": "Оплата за результат",
                            "mode": "assessment",
                        },
                    ]
                }
            )
            return
        super().route(route)


class DelayedSupportOrdersNetwork(CustomerNetwork):
    def __init__(self):
        super().__init__()
        self.hold_orders = False
        self.pending_orders = []

    def route(self, route):
        if self.hold_orders and urlparse(route.request.url).path.endswith(
            "/orders/list"
        ):
            self.pending_orders.append(route)
            return
        super().route(route)


class PaidFollowupNetwork(CustomerNetwork):
    def __init__(self):
        super().__init__()
        self.paid = False
        self.hold_next_followup = False
        self.pending_followups = []
        self.hold_optout = False
        self.pending_optouts = []

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/checkout-status"):
            route.fulfill(
                json={
                    "order_id": ORDER,
                    "invoice_state": "ready",
                    "capture_state": "confirmed"
                    if self.paid
                    else "not_recorded",
                    "writes_paused": False,
                    "can_open": False,
                }
            )
            return
        if path.endswith("/customer/followups/state"):
            if self.hold_next_followup:
                self.hold_next_followup = False
                self.pending_followups.append(route)
                return
            route.fulfill(
                json={
                    "order_id": ORDER,
                    "next_action": "orders",
                    "opted_out": False,
                    "stop_reason": "paid" if self.paid else None,
                }
            )
            return
        if path.endswith("/customer/followups/optout") and self.hold_optout:
            self.pending_optouts.append(route)
            return
        super().route(route)


class CreatedOrderFollowupNetwork(CustomerNetwork):
    def __init__(self):
        super().__init__()
        self.followup_order = None
        self.pending_creation_activity = []

    def route(self, route):
        path = urlparse(route.request.url).path
        if path.endswith("/customer/followups/state"):
            route.fulfill(
                json={
                    "order_id": self.followup_order,
                    "next_action": "orders",
                    "opted_out": False,
                    "stop_reason": None,
                }
            )
            return
        if path.endswith("/customer/followups/activity"):
            body = route.request.post_data_json
            if body["event"] == "order_created":
                self.pending_creation_activity.append(route)
                return
            route.fulfill(json={"ok": True})
            return
        super().route(route)


class NewOrderDashboardNetwork(CustomerNetwork):
    def __init__(self):
        super().__init__()
        self.orders = []

    def route(self, route):
        if urlparse(route.request.url).path == "/miniapp/api/financial/orders":
            self.orders = [
                {
                    "order_id": ORDER,
                    "public_title": "New order",
                    "status": "new",
                    "created_at": "2026-10-30T10:00:00Z",
                    "financial_version": "v1",
                }
            ]
        super().route(route)


class DelayedDashboardCountNetwork(NewOrderDashboardNetwork):
    def __init__(self):
        super().__init__()
        self.pending_old_count = []

    def route(self, route):
        if (
            urlparse(route.request.url).path.endswith("/orders/list")
            and not self.orders
        ):
            self.pending_old_count.append(route)
            return
        super().route(route)


class InitialMenuFollowupNetwork(CreatedOrderFollowupNetwork):
    def __init__(self):
        super().__init__()
        self.menu_saved = False
        self.pending_menu = []

    def route(self, route):
        path = urlparse(route.request.url).path
        if (
            path.endswith("/customer/followups/activity")
            and route.request.post_data_json["event"] == "menu"
        ):
            self.pending_menu.append(route)
            return
        if path.endswith("/customer/followups/state") and not self.menu_saved:
            route.fulfill(body="null", content_type="application/json")
            return
        super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("financial_version", [None, "v1"])
def test_completed_author_can_be_rated_before_order_closes(
    page, platform, financial_version
):
    network = CustomerNetwork()
    network.orders = [
        {
            "order_id": ORDER,
            "public_title": "Active order",
            "status": "active",
            "created_at": "2026-10-30T10:00:00Z",
            "financial_version": financial_version,
            "progress": {"completed": 1, "assigned": 2, "total": 10},
        }
    ]
    open_app(page, network, platform, init_data=SIGNED, query="?screen=orders")
    card = page.locator(f'[data-order-id="{ORDER}"]')
    expect(card.get_by_role("button", name="Оценить автора")).to_be_visible()
    card.get_by_role("button", name="Оценить автора").click()
    ratings = page.locator("#screen-customer-ratings")
    expect(ratings).to_be_visible()
    expect(ratings.locator("form")).to_have_count(1)
    ratings.locator("select").select_option("4")
    ratings.locator('button[type="submit"]').click()
    expect(ratings).to_contain_text("Оценка сохранена")
    posted = [
        body
        for path, body in network.customer_posts
        if path.endswith("/ratings")
    ]
    assert any(body.get("order_id") == ORDER for body in posted)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("status", ["new", "active"])
def test_order_without_completed_work_does_not_offer_rating(
    page, platform, status
):
    network = CustomerNetwork()
    network.orders = [
        {
            "order_id": ORDER,
            "public_title": "Order without completed work",
            "status": status,
            "created_at": "2026-10-30T10:00:00Z",
            "financial_version": None,
            "progress": {"completed": 0, "assigned": 2, "total": 10},
        }
    ]
    open_app(page, network, platform, init_data=SIGNED, query="?screen=orders")
    card = page.locator(f'[data-order-id="{ORDER}"]')
    expect(card).to_be_visible()
    expect(card.get_by_role("button", name="Оценить автора")).to_have_count(0)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_closed_legacy_order_keeps_manager_rating_visible(page, platform):
    class HistoricalRatingNetwork(CustomerNetwork):
        def route(self, route):
            if urlparse(route.request.url).path.endswith(
                "/customer/orders/ratings"
            ):
                route.fulfill(
                    json={
                        "authors": [
                            {
                                "blogger_id": ORDER,
                                "display_name": "Автор Анна",
                                "rating_eligible": False,
                                "ratings": [
                                    {
                                        "rater_role": "manager",
                                        "score": 4,
                                        "comment": "Историческая оценка",
                                    }
                                ],
                            }
                        ]
                    }
                )
                return
            super().route(route)

    network = HistoricalRatingNetwork()
    network.orders = [
        {
            "order_id": ORDER,
            "public_title": "Closed legacy order",
            "status": "closed",
            "created_at": "2026-10-30T10:00:00Z",
            "financial_version": None,
            "progress": {"completed": 0, "assigned": 1, "total": 10},
        }
    ]
    open_app(page, network, platform, init_data=SIGNED, query="?screen=orders")
    card = page.locator(f'[data-order-id="{ORDER}"]')
    expect(card.get_by_role("button", name="Оценить автора")).to_be_visible()
    card.get_by_role("button", name="Оценить автора").click()
    ratings = page.locator("#screen-customer-ratings")
    expect(ratings).to_contain_text("Оценка менеджера")
    expect(ratings).to_contain_text("Историческая оценка")
    expect(ratings.locator("form")).to_have_count(0)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("payment_state", ["unpaid", "pending", "failed"])
def test_unpaid_order_offers_payment_continuation(
    page, platform, payment_state
):
    network = CustomerNetwork()
    network.orders = [
        {
            "order_id": ORDER,
            "public_title": "New order",
            "status": "new",
            "payment_state": payment_state,
            "created_at": "2026-10-30T10:00:00Z",
            "financial_version": "v1",
        }
    ]
    open_app(page, network, platform, init_data=SIGNED, query="?screen=orders")
    card = page.locator(f'[data-order-id="{ORDER}"]')
    expect(card).to_contain_text("Ожидает оплаты")
    expect(
        card.get_by_role("button", name="Продолжить оформление")
    ).to_be_visible()
    if payment_state != "unpaid":
        expect(card).not_to_contain_text(payment_state)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,awaiting,continue_order",
    [
        ("ru", "Ожидает оплаты", "Продолжить оформление"),
        ("en", "Awaiting payment", "Continue your order"),
        ("kk", "Төлем күтілуде", "Тапсырысты жалғастыру"),
        ("be", "Чакае аплаты", "Працягнуць афармленне"),
        ("uz", "To‘lov kutilmoqda", "Buyurtmani davom ettirish"),
    ],
)
def test_pending_payment_is_localized(
    page, platform, locale, awaiting, continue_order
):
    network = CustomerNetwork()
    network.locale = locale
    network.orders = [
        {
            "order_id": ORDER,
            "public_title": "New order",
            "status": "new",
            "payment_state": "pending",
            "created_at": "2026-10-30T10:00:00Z",
            "financial_version": "v1",
        }
    ]
    open_app(page, network, platform, init_data=SIGNED, query="?screen=orders")
    card = page.locator(f'[data-order-id="{ORDER}"]')
    expect(card).to_contain_text(awaiting)
    expect(card.get_by_role("button", name=continue_order)).to_be_visible()
    expect(card.get_by_text(awaiting, exact=True)).to_have_count(1)
    expect(card).not_to_contain_text("pending")


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("status", ["closed", "deleted"])
def test_finished_order_does_not_offer_payment_continuation(
    page, platform, status
):
    network = CustomerNetwork()
    network.orders = [
        {
            "order_id": ORDER,
            "public_title": "Finished order",
            "status": status,
            "payment_state": "unpaid",
            "created_at": "2026-10-30T10:00:00Z",
            "financial_version": "v1",
        }
    ]
    open_app(page, network, platform, init_data=SIGNED, query="?screen=orders")
    card = page.locator(f'[data-order-id="{ORDER}"]')
    expect(card).to_contain_text("Не оплачено")
    expect(card.get_by_role("button", name="Открыть заказ")).to_be_visible()
    expect(
        card.get_by_role("button", name="Продолжить оформление")
    ).to_have_count(0)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_initial_followup_appears_after_menu_activity_is_saved(page, platform):
    network = InitialMenuFollowupNetwork()
    with page.expect_request(
        lambda request: (
            request.url.endswith("/customer/followups/activity")
            and request.post_data_json["event"] == "menu"
        )
    ):
        open_app(page, network, platform, init_data=SIGNED)
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    assert len(network.pending_menu) == 1
    network.menu_saved = True
    with page.expect_response("**/customer/followups/activity"):
        network.pending_menu.pop().fulfill(json={"ok": True})
    expect(page.locator("#customer-followup")).to_have_count(1)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_dashboard_order_count_updates_after_creation(page, platform):
    network = NewOrderDashboardNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    orders = page.locator("#btn-show-orders-list")
    expect(orders).to_have_text("Мои заказы · 0")
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    page.locator("#btn-intake-back").click()
    expect(orders).to_have_text("Мои заказы · 1")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_late_old_dashboard_count_cannot_replace_new_count(page, platform):
    network = DelayedDashboardCountNetwork()
    with page.expect_request("**/orders/list"):
        open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    page.locator("#btn-intake-back").click()
    orders = page.locator("#btn-show-orders-list")
    expect(orders).to_have_text("Мои заказы · 1")
    assert len(network.pending_old_count) == 1
    with page.expect_response("**/orders/list"):
        network.pending_old_count.pop().fulfill(
            json={"orders": [], "total": 0, "has_more": False}
        )
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame("
        "() => requestAnimationFrame(resolve)))"
    )
    expect(orders).to_have_text("Мои заказы · 1")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_followup_resumes_new_order_after_activity_is_saved(page, platform):
    network = CreatedOrderFollowupNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    expect(page.locator("#customer-followup")).to_have_count(1)
    page.locator("#btn-show-create-order").click()
    fill(page)
    with page.expect_request(
        lambda request: (
            request.url.endswith("/customer/followups/activity")
            and request.post_data_json["event"] == "order_created"
        )
    ):
        page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-result")).to_be_visible()
    page.locator("#btn-intake-back").click()
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    # Until the saved order reaches the server-side series, an old button
    # must not start an unrelated order when it says to continue.
    expect(page.locator("#customer-followup")).to_have_count(0)
    assert len(network.pending_creation_activity) == 1
    network.followup_order = ORDER
    with page.expect_response("**/customer/followups/activity"):
        network.pending_creation_activity.pop().fulfill(json={"ok": True})
    expect(page.locator("#customer-followup")).to_have_count(1)
    with page.expect_response(
        lambda response: response.url.endswith(
            f"/financial/orders/{ORDER}/selection"
        )
    ) as selection:
        page.locator("#customer-followup").get_by_role(
            "button", name="Продолжить оформление"
        ).click()
    assert selection.value.status == 200
    expect(page.locator("#screen-selection")).to_be_visible()


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_confirmed_checkout_removes_pending_followup_from_dashboard(
    page, platform
):
    network = PaidFollowupNetwork()
    open_app(
        page,
        network,
        platform,
        init_data=SIGNED,
        query=f"?selection={ORDER}",
    )
    expect(page.locator("#customer-followup")).to_have_count(1)
    network.paid = True
    page.locator("#umc-checkout-refresh").click()
    expect(page.locator("#umc-checkout-status")).to_have_attribute(
        "data-state", "confirmed"
    )
    expect(page.locator("#customer-followup")).to_have_count(0)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_late_unpaid_followup_does_not_reappear_after_payment(page, platform):
    network = PaidFollowupNetwork()
    open_app(
        page,
        network,
        platform,
        init_data=SIGNED,
        query=f"?selection={ORDER}",
    )
    expect(page.locator("#customer-followup")).to_have_count(1)
    network.hold_next_followup = True
    page.evaluate("document.dispatchEvent(new Event('umc:app-ready'))")
    for _ in range(100):
        if network.pending_followups:
            break
        page.wait_for_timeout(10)
    assert len(network.pending_followups) == 1
    network.paid = True
    with page.expect_response("**/customer/followups/state"):
        page.locator("#umc-checkout-refresh").click()
    expect(page.locator("#customer-followup")).to_have_count(0)
    with page.expect_response("**/customer/followups/state"):
        network.pending_followups.pop().fulfill(
            json={
                "order_id": ORDER,
                "next_action": "orders",
                "opted_out": False,
                "stop_reason": None,
            }
        )
    page.evaluate(
        "() => new Promise(resolve => requestAnimationFrame("
        "() => requestAnimationFrame(resolve)))"
    )
    expect(page.locator("#customer-followup")).to_have_count(0)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_optout_confirmation_updates_followup_after_screen_refresh(
    page, platform
):
    network = PaidFollowupNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    box = page.locator("#customer-followup")
    expect(box).to_be_visible()
    original = box.element_handle()
    network.hold_optout = True
    with page.expect_request("**/customer/followups/optout"):
        box.get_by_role("button", name="Отключить напоминания").click()
    page.evaluate("document.dispatchEvent(new Event('umc:app-ready'))")
    page.wait_for_function("old => !old.isConnected", arg=original)
    expect(
        box.get_by_role("button", name="Отключить напоминания")
    ).to_be_visible()
    with page.expect_response("**/customer/followups/optout"):
        network.pending_optouts.pop().fulfill(json={"opted_out": True})
    expect(box).to_contain_text("Напоминания отключены")


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,selection_label,legacy_label",
    [
        ("ru", "Согласованный срок подбора", "Срок"),
        ("en", "Agreed selection due date", "Due date"),
        ("kk", "Келісілген іріктеу мерзімі", "Мерзімі"),
        ("be", "Узгоднены тэрмін падбору", "Тэрмін"),
        ("uz", "Kelishilgan tanlov muddati", "Muddati"),
    ],
)
def test_order_list_displays_saved_selection_and_legacy_deadlines(
    page, platform, locale, selection_label, legacy_label
):
    legacy_id = "22000000-0000-4000-8000-000000000007"
    due = "2031-04-12T12:30:00+00:00"
    network = CustomerNetwork()
    network.locale = locale
    network.orders = [
        {
            "order_id": ORDER,
            "public_title": "Current order",
            "status": "new",
            "created_at": "2026-10-30T10:00:00Z",
            "financial_version": "v1",
            "selection_due_at": due,
            "deadlines": None,
        },
        {
            "order_id": legacy_id,
            "public_title": "Legacy order",
            "status": "new",
            "created_at": "2026-10-30T10:00:00Z",
            "financial_version": None,
            "selection_due_at": None,
            "deadlines": "7 days",
        },
    ]
    open_app(page, network, platform, init_data=SIGNED, query="?screen=orders")
    formatted = page.evaluate(
        "([date, locale]) => new Date(date).toLocaleString(locale)",
        [due, locale],
    )
    expect(page.locator(f'[data-order-id="{ORDER}"]')).to_contain_text(
        f"{selection_label}: {formatted}"
    )
    expect(page.locator(f'[data-order-id="{legacy_id}"]')).to_contain_text(
        f"{legacy_label}: 7 days"
    )


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_order_support_can_be_submitted_while_order_list_is_loading(
    page, platform
):
    network = DelayedSupportOrdersNetwork()
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-orders-list").click()
    card = page.locator(f'[data-order-id="{ORDER}"]')
    expect(card).to_be_visible()
    network.hold_orders = True
    with page.expect_request("**/orders/list"):
        card.get_by_role("button", name="Сообщить о проблеме").click()
    support = page.locator("#screen-customer-support")
    expect(support.locator("select")).to_have_value(ORDER)
    support.locator('[name="reason"]').fill("Нужна помощь по заказу")
    support.locator('[name="contact"]').fill("@customer")
    support.locator('button[type="submit"]').click()
    expect(support).to_contain_text("Заявка сохранена")
    sent = [b for p, b in network.customer_posts if p.endswith("/support")]
    assert sent[0]["order_id"] == ORDER
    assert len(network.pending_orders) == 1
    network.hold_orders = False
    with page.expect_response("**/orders/list"):
        network.route(network.pending_orders.pop())
    expect(support.locator(f'option[value="{ORDER}"]')).to_have_count(1)
    expect(support.locator("select")).to_have_value(ORDER)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,result_hint",
    [
        ("ru", "просмотры, заявки или продажи"),
        ("en", "views, leads or sales"),
        ("kk", "қаралым, өтінім немесе сату"),
        ("be", "прагляды, заяўкі або продажы"),
        ("uz", "ko‘rishlar, arizalar yoki savdo"),
    ],
)
def test_service_catalog_explains_choices_and_links_to_details(
    page, platform, locale, result_hint
):
    page.set_viewport_size({"width": 320, "height": 740})
    network = FullServiceCatalogNetwork()
    network.locale = locale
    open_app(page, network, platform, init_data=SIGNED)
    page.locator(
        "#screen-advertiser-dashboard [data-customer-services]"
    ).click()
    cards = page.locator("#screen-customer-services article")
    expect(cards).to_have_count(5)
    for index, url in enumerate(
        [
            "https://usemycontent.ru/pricing",
            "https://usemycontent.ru/business#pod-klyuch",
            "https://usemycontent.ru/barter",
            "https://usemycontent.ru/barter",
            "https://usemycontent.ru/rezultat",
        ]
    ):
        expect(cards.nth(index).locator("p")).not_to_be_empty()
        link = cards.nth(index).locator("a")
        expect(link).to_have_attribute("href", url)
        expect(link).to_have_attribute("rel", "noopener noreferrer")
    expect(cards.nth(4).locator("p")).to_contain_text(result_hint)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_customer_navigation_support_and_services(page, platform):
    page.set_viewport_size({"width": 320, "height": 740})
    network = CustomerNetwork()
    errors = open_app(page, network, platform, init_data=SIGNED)
    expect(page.locator("#btn-show-create-order")).to_have_text(
        "Подобрать блогеров"
    )
    expect(
        page.locator("#screen-advertiser-dashboard [data-corrections-open]")
    ).to_have_count(0)
    page.locator("#btn-show-orders-list").click()
    expect(page.locator("#screen-customer-orders")).to_be_visible()
    page.get_by_role("button", name="Сообщить о проблеме", exact=True).filter(
        visible=True
    ).first.click()
    page.locator('[name="reason"]').fill("Нет ответа от автора")
    page.locator('[name="contact"]').fill("@customer")
    network.fail_support = True
    page.locator("#screen-customer-support button[type=submit]").click()
    expect(
        page.locator("#screen-customer-support button[type=submit]")
    ).to_have_text("Повторить отправку")
    network.fail_support = False
    page.locator("#screen-customer-support button[type=submit]").click()
    expect(page.locator("#screen-customer-support")).to_contain_text(
        "Заявка сохранена"
    )
    posts = [b for p, b in network.customer_posts if p.endswith("/support")]
    assert len(posts) == 2 and posts[0] == posts[1]
    page.evaluate("UMCCustomer.services()")
    page.locator("#screen-customer-services article").first.get_by_role(
        "button"
    ).click()
    for key in [
        "name",
        "telegram",
        "company",
        "niche",
        "product",
        "expected_benefit",
        "contact",
    ]:
        page.locator(f'#screen-customer-services [name="{key}"]').fill(
            "Проверка"
        )
    page.locator("#screen-customer-services input[type=checkbox]").check()
    page.locator("#screen-customer-services button[type=submit]").click()
    expect(page.locator("#screen-customer-services")).to_contain_text(
        "Заявка сохранена"
    )
    assert not errors
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, platform + "-customer-services-320")


@pytest.mark.parametrize("count", [10, 20, 30, 50, 100, 200])
def test_variable_quote_stories_and_saved_totals(page, count):
    network = CustomerNetwork()
    errors = open_app(page, network, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page, manager=True)
    page.locator("#intake-count").fill(str(count))
    page.locator("#intake-order-type").select_option("stories")
    page.locator("#intake-platform-telegram").check()
    page.locator("#btn-intake-create").click()
    expect(page.locator("#intake-total")).to_have_attribute(
        "data-minor", str(count * 170000)
    )
    assert network.creates[0]["position_count"] == count
    assert network.creates[0]["order_type"] == "stories"
    assert network.creates[0]["targeting"]["platforms"] == ["telegram"]
    assert ORDER not in page.locator("#intake-result").inner_text()
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_image_upload_blocks_submit_and_account_change_discards_token(
    page, platform
):
    network = CustomerNetwork()
    pending = []
    errors = open_app(page, network, platform, init_data=SIGNED)
    page.route("**/orders/images", lambda route: pending.append(route))
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-image").set_input_files(
        {
            "name": "brief.jpg",
            "mimeType": "image/jpeg",
            "buffer": b"synthetic JPEG boundary",
        }
    )
    expect(page.locator("#btn-intake-create")).to_be_disabled()
    page.wait_for_function(
        "document.getElementById('intake-image-error').textContent.length>0"
    )
    page.evaluate(
        "window._me.user_id='33000000-0000-4000-8000-000000000001';"
        "document.dispatchEvent(new Event('umc:app-ready'))"
    )
    for route in pending:
        route.fulfill(json={"image_token": "old-account-token"})
    expect(page.locator("#intake-image-token")).to_have_value("")
    expect(page.locator("#intake-image-preview")).to_be_hidden()
    assert network.creates == []
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("dark", [False, True])
def test_ratings_followup_optout_and_responsive_order_list(
    page, platform, dark
):
    page.set_viewport_size({"width": 320 if dark else 1280, "height": 800})
    network = CustomerNetwork()
    errors = open_app(
        page, network, platform, init_data=SIGNED, query="?screen=orders"
    )
    page.evaluate(
        "window.__host.wa.colorScheme="
        + repr("dark" if dark else "light")
        + ";window.__host.events.themeChanged()"
    )
    expect(page.locator("#screen-customer-orders")).to_be_visible()
    page.locator("#screen-customer-orders article").get_by_role(
        "button", name="Оценить автора"
    ).click()
    expect(page.locator("#screen-customer-ratings")).to_contain_text(
        "Автор Анна"
    )
    page.locator("#screen-customer-ratings select").select_option("4")
    page.locator("#screen-customer-ratings textarea").fill("Хорошая работа")
    page.locator("#screen-customer-ratings button[type=submit]").click()
    expect(page.locator("#screen-customer-ratings")).to_contain_text(
        "Оценка сохранена"
    )
    assert (
        next(
            body
            for path, body in network.customer_posts
            if path == "/miniapp/api/ratings"
        )["score"]
        == 4
    )
    page.evaluate("__umcAppBridge.showScreen('screen-advertiser-dashboard')")
    page.locator("#customer-followup").get_by_role(
        "button", name="Отключить напоминания"
    ).click()
    expect(page.locator("#customer-followup")).to_contain_text(
        "Напоминания отключены"
    )
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(
        page,
        f"{platform}-customer-home-"
        + ("dark-320" if dark else "light-desktop"),
    )
    assert not errors


@pytest.mark.parametrize("count", [0, 1, 2, 3, 5, 10, 23])
def test_multiple_orders_paging_filter_and_back_context(page, count):
    network = CustomerNetwork()
    network.orders = [
        {
            "order_id": ORDER,
            "public_title": "Одинаковый товар с длинным названием " * 4,
            "status": "active" if n % 2 else "closed",
            "created_at": "2026-10-30T10:00:00Z",
            "financial_version": "v1",
            "bloggers_needed": 10,
            "payment_state": "paid",
            "progress": {"assigned": 8, "completed": 3, "total": 10},
        }
        for n in range(count)
    ]
    errors = open_app(page, network, init_data=SIGNED, query="?screen=orders")
    expect(page.locator("#screen-customer-orders article")).to_have_count(
        min(count, 10)
    )
    if count > 10:
        page.locator("#btn-customer-more").click()
        expect(page.locator("#screen-customer-orders article")).to_have_count(
            20
        )
        page.locator("#btn-customer-more").click()
        expect(page.locator("#screen-customer-orders article")).to_have_count(
            23
        )
    page.locator("#screen-customer-orders > select").select_option("closed")
    expect(page.locator("#screen-customer-orders article")).to_have_count(
        min((count + 1) // 2, 10)
    )
    if count:
        page.locator("#screen-customer-orders article button").first.click()
        expect(page.locator("#screen-selection")).to_be_visible()
        page.locator("#btn-selection-back").click()
        expect(page.locator("#screen-customer-orders")).to_be_visible()
        expect(page.locator("#screen-customer-orders > select")).to_have_value(
            "closed"
        )
    assert not errors


def test_service_request_survives_reload_with_same_operation(page):
    network = CustomerNetwork()
    errors = open_app(page, network, init_data=SIGNED, query="#services")
    page.locator("#screen-customer-services article").first.get_by_role(
        "button"
    ).click()
    for key in [
        "name",
        "telegram",
        "company",
        "niche",
        "product",
        "expected_benefit",
        "contact",
    ]:
        page.locator(f'#screen-customer-services [name="{key}"]').fill(
            "Проверка"
        )
    page.locator("#screen-customer-services input[type=checkbox]").check()
    sent = []

    def abort(route):
        sent.append(route.request.post_data_json)
        route.abort()

    page.route("**/api/customer/services", abort)
    page.locator("#screen-customer-services button[type=submit]").click()
    expect(
        page.locator("#screen-customer-services button[type=submit]")
    ).to_have_text("Повторить отправку")
    page.reload()
    page.locator("#screen-customer-services article").first.get_by_role(
        "button"
    ).click()
    expect(
        page.locator('#screen-customer-services [name="product"]')
    ).to_be_disabled()
    page.locator("#screen-customer-services button[type=submit]").click()
    expect(
        page.locator("#screen-customer-services button[type=submit]")
    ).to_be_enabled()
    assert len(sent) == 2 and sent[0] == sent[1]
    assert not errors


@pytest.mark.parametrize(
    "locale,title",
    [
        ("ru", "Мои заказы"),
        ("en", "My orders"),
        ("kk", "Менің тапсырыстарым"),
        ("be", "Мае заказы"),
        ("uz", "Buyurtmalarim"),
    ],
)
def test_customer_locale_and_service_links(page, locale, title):
    network = CustomerNetwork()
    network.locale = locale
    errors = open_app(page, network, init_data=SIGNED, query="?screen=orders")
    expect(page.locator("#screen-customer-orders h1")).to_have_text(title)
    page.evaluate("UMCCustomer.services()")
    expect(
        page.locator(
            '#screen-customer-services a[href="https://usemycontent.ru/materials/"]'
        )
    ).to_be_visible()
    assert not errors


def test_late_admin_capability_cannot_enable_entry_for_next_account(page):
    network = CustomerNetwork()
    held = []
    open_app(page, network, init_data=SIGNED)
    expect(page.locator("#screen-advertiser-dashboard")).to_be_visible()
    page.route("**/admin/partners/context", lambda route: held.append(route))
    page.evaluate("document.dispatchEvent(new Event('umc:app-ready'))")
    page.wait_for_timeout(50)
    page.unroute("**/admin/partners/context")
    page.route(
        "**/admin/partners/context",
        lambda route: route.fulfill(status=403, json={"detail": "forbidden"}),
    )
    page.evaluate(
        "window._me.user_id='44000000-0000-4000-8000-000000000001';"
        "document.dispatchEvent(new Event('umc:app-ready'))"
    )
    for route in held:
        route.fulfill(json={"capabilities": {"review_leads": True}})
    expect(page.locator("[data-admin-tools]")).to_have_count(0)
    expect(
        page.locator("#screen-advertiser-dashboard [data-finance-open]")
    ).to_have_count(0)


def test_original_jpeg_preview_saved_receipt_and_reopened_order(page):
    import base64
    import io

    from PIL import Image

    data = io.BytesIO()
    Image.new("RGB", (1080, 1080), (220, 180, 120)).save(data, format="JPEG")
    encoded = base64.b64encode(data.getvalue()).decode()
    network = CustomerNetwork()
    errors = open_app(page, network, init_data=SIGNED)
    page.route(
        "**/orders/images",
        lambda route: route.fulfill(json={"image_token": ORDER}),
    )
    page.route(
        "**/orders/images/content",
        lambda route: route.fulfill(
            json={"image_base64": encoded, "content_type": "image/jpeg"}
        ),
    )
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-image").set_input_files(
        {
            "name": "brief.jpg",
            "mimeType": "image/jpeg",
            "buffer": data.getvalue(),
        }
    )
    expect(page.locator("#intake-image-preview")).to_be_visible()
    expect(page.locator("#btn-intake-create")).to_be_enabled()
    page.locator("#btn-intake-create").click()
    expect(
        page.locator("#intake-result [data-order-image-view]")
    ).to_be_visible()
    assert network.creates[0]["image_token"] == ORDER
    page.route(
        "**/financial/orders/*/selection",
        lambda route: route.fulfill(
            json={
                "order_id": ORDER,
                "public_number": "UMC-00000001",
                "positions": [],
                "waitlist_count": 0,
                "writes_paused": False,
                "image_token": ORDER,
            }
        ),
    )
    page.locator("#btn-intake-selection").click()
    expect(
        page.locator("#screen-selection [data-order-image-view]")
    ).to_be_visible()
    assert (
        page.locator("#screen-selection [data-order-image-view]").evaluate(
            "(img)=>img.naturalWidth"
        )
        == 1080
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_russian_selection_controls_remain_localized(page, platform):
    network = CustomerNetwork()
    errors = open_app(
        page,
        network,
        platform,
        init_data=SIGNED,
        query=f"?selection={ORDER}",
    )
    screen = page.locator("#screen-selection")
    expect(screen).to_be_visible()
    for title in ["Сообщить о проблеме", "Оценить автора", "Все услуги"]:
        expect(
            screen.get_by_role("button", name=title, exact=True)
        ).to_be_visible()
    assert not errors
    screenshot(page, f"checkout-{platform}-ru-localized-controls")


class DeepLinkNetwork(CustomerNetwork):
    def __init__(self, *, denied=False):
        super().__init__()
        self.denied = denied
        self.owner_reads = []
        self.detail = {
            "order_id": ORDER,
            "status": "closed",
            "financial_version": "v1",
            "offer_text": "Проверенный кофе",
            "product_link": "https://example.test/coffee",
            "geography": "Казань",
        }

    def route(self, route):
        if urlparse(route.request.url).path.endswith("/orders/get"):
            self.owner_reads.append(route.request.post_data_json)
            route.fulfill(
                status=404 if self.denied else 200,
                json={"detail": "Not found"} if self.denied else self.detail,
            )
            return
        super().route(route)


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("destination", ["orders", "services", "ratings"])
def test_owned_order_deep_link_preserves_destination_and_context(
    page, platform, destination
):
    network = DeepLinkNetwork()
    errors = open_app(
        page,
        network,
        platform,
        init_data=SIGNED,
        query=f"?screen={destination}&order_id={ORDER}",
    )
    target = (
        "selection" if destination == "orders" else "customer-" + destination
    )
    expect(page.locator(f"#screen-{target}")).to_be_visible()
    assert network.owner_reads and network.owner_reads[0]["order_id"] == ORDER
    assert network.owner_reads[0]["init_data"] == SIGNED
    if destination == "orders":
        expect(
            page.locator("#selection-positions article").first
        ).to_be_visible()
        page.reload()
        expect(page.locator("#screen-selection")).to_be_visible()
        expect(
            page.locator("#selection-positions article").first
        ).to_be_visible()
        screenshot(page, f"deeplink-{platform}-owned-checkout")
        page.locator("#btn-selection-back").click()
        expect(page.locator("#screen-customer-orders")).to_be_visible()
        assert not network.creates
    elif destination == "services":
        page.locator("#screen-customer-services article").nth(1).get_by_role(
            "button"
        ).click()
        expect(page.locator('[name="product"]')).to_have_value(
            "Проверенный кофе"
        )
        expect(page.locator('[name="website"]')).to_have_value(
            "https://example.test/coffee"
        )
        page.locator('[name="contact"]').fill("@customer")
        page.locator("#screen-customer-services input[type=checkbox]").check()
        page.locator("#screen-customer-services button[type=submit]").click()
        expect(page.locator("#screen-customer-services")).to_contain_text(
            "Заявка сохранена"
        )
        sent = [b for p, b in network.customer_posts if p.endswith("/services")]
        assert sent[0]["order_id"] == ORDER
    else:
        expect(
            page.locator("#screen-customer-ratings article")
        ).to_contain_text("Автор Анна")
    screenshot(page, f"deeplink-{platform}-{destination}")
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize("destination", ["orders", "services", "ratings"])
@pytest.mark.parametrize("invalid", [False, True])
def test_order_deep_link_rejects_foreign_or_invalid_order(
    page, platform, destination, invalid
):
    network = DeepLinkNetwork(denied=True)
    value = "not-a-uuid" if invalid else ORDER
    errors = open_app(
        page,
        network,
        platform,
        init_data=SIGNED,
        query=f"?screen={destination}&order_id={value}",
    )
    expect(page.locator(f"#screen-customer-{destination}")).to_contain_text(
        "Не удалось"
    )
    assert len(network.owner_reads) == (0 if invalid else 1)
    assert not any(p.endswith("/selection") for p, _ in network.requests)
    assert not any(
        p.endswith(("/ratings", "/catalog")) for p, _ in network.customer_posts
    )
    assert not errors


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "locale,brief,code",
    [
        ("kk", "Тұрақты авторлар қажет", "regular_search"),
        ("be", "Патрэбны рэгулярны пошук аўтараў", "regular_search"),
        ("uz", "Muntazam mualliflarni qidirish", "regular_search"),
        ("kk", "Өнімнің сатылымын арттыру", "result"),
        ("be", "Павялічыць прагляды і продажы", "result"),
        ("uz", "Mahsulot sotuvlarini oshirish", "result"),
    ],
)
def test_service_recommendation_uses_customer_language_after_real_intake(
    page, platform, locale, brief, code
):
    network = CustomerNetwork()
    network.locale = locale
    open_app(page, network, platform, init_data=SIGNED)
    page.locator("#btn-show-create-order").click()
    fill(page)
    page.locator("#intake-brief").fill(brief)
    page.locator("#btn-intake-create").click()
    recommendation = page.locator(
        "#intake-result [data-service-recommendation]"
    )
    expect(recommendation).to_be_visible()
    recommendation.click()
    expect(page.locator(f"#customer-service-{code}-product")).to_have_value(
        brief
    )
    assert len(network.creates) == 1


@pytest.mark.parametrize("platform", ["telegram", "max"])
@pytest.mark.parametrize(
    "status,completed",
    [("closed", False), ("active", False), ("active", True), ("closed", True)],
)
def test_ambassadors_recommendation_reads_owned_completion_on_fresh_entry(
    page, platform, status, completed
):
    network = DeepLinkNetwork()
    network.detail["status"] = status
    network.has_completed_work = completed
    open_app(
        page, network, platform, init_data=SIGNED, query=f"?selection={ORDER}"
    )
    expect(page.locator("#selection-positions article").first).to_be_visible()
    page.wait_for_function(
        "() => document.querySelector('#screen-selection')"
        ".dataset.recommendationChecked === 'true'"
    )
    recommendation = page.locator(
        "#screen-selection [data-service-recommendation]"
    )
    expect(recommendation).to_have_count(1 if completed else 0)
    assert network.owner_reads and network.owner_reads[-1]["order_id"] == ORDER
    if completed:
        recommendation.click()
        expect(
            page.locator("#customer-service-ambassadors-product")
        ).to_have_value("Проверенный кофе")


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_ambassadors_recommendation_fails_closed_when_completion_unavailable(
    page, platform
):
    network = DeepLinkNetwork()
    network.fail_completion = True
    open_app(
        page, network, platform, init_data=SIGNED, query=f"?selection={ORDER}"
    )
    expect(page.locator("#selection-positions article").first).to_be_visible()
    page.wait_for_function(
        "() => document.querySelector('#screen-selection')"
        ".dataset.recommendationChecked === 'true'"
    )
    expect(
        page.locator("#screen-selection [data-service-recommendation]")
    ).to_have_count(0)


@pytest.mark.parametrize("platform", ["telegram", "max"])
def test_duplicate_order_deep_link_never_fetches_private_order(page, platform):
    network = DeepLinkNetwork()
    open_app(
        page,
        network,
        platform,
        init_data=SIGNED,
        query=f"?screen=ratings&order_id={ORDER}&order_id={ORDER}",
    )
    expect(page.locator("#screen-customer-ratings")).to_contain_text(
        "Не удалось"
    )
    assert not network.owner_reads
