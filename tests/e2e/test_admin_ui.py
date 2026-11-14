"""E2E tests for Admin UI with Playwright."""

import os

import pytest

requires_postgres = pytest.mark.skipif(
    not os.environ.get("E2E_BASE_URL"),
    reason="Dashboard/creators need PostgreSQL; run via make e2e-docker",
)


def _login(
    page,
    base_url: str,
    username: str | None = None,
    password: str | None = None,
) -> None:
    """Perform admin login via form.

    Uses E2E_ADMIN_USERNAME / E2E_ADMIN_PASSWORD from env when not passed.
    """
    user = (
        username
        if username is not None
        else os.environ.get("E2E_ADMIN_USERNAME", "test_admin")
    )
    pwd = (
        password
        if password is not None
        else os.environ.get("E2E_ADMIN_PASSWORD", "test_pass")
    )
    page.goto(f"{base_url}/admin/login")
    page.locator('input[name="username"]').fill(user)
    page.locator('input[name="password"]').fill(pwd)
    page.get_by_role("button", name="Login").click()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_login_redirects_unauthenticated(admin_server, page, base_url) -> None:
    """GET /admin/dashboard without session redirects to /admin/login."""
    page.goto(f"{base_url}/admin/dashboard")
    page.wait_for_url(f"{base_url}/admin/login", timeout=5000)
    assert "login" in page.url.lower()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_login_success(admin_server, page, base_url) -> None:
    """POST login with valid credentials redirects to dashboard."""
    _login(page, base_url)
    page.wait_for_url(
        lambda url: "login" not in url,
        timeout=5000,
    )
    assert "login" not in page.url


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_login_invalid_credentials(admin_server, page, base_url) -> None:
    """Invalid password keeps user on login page."""
    _login(page, base_url, password="wrong_password")
    page.wait_for_load_state("networkidle")
    assert "login" in page.url.lower()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_dashboard_loads(admin_server, page, base_url) -> None:
    """After login, admin index or dashboard loads."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)
    page.goto(f"{base_url}/admin/")
    page.wait_for_load_state("networkidle")
    assert page.url.rstrip("/").endswith("/admin") or "/admin/" in page.url


@pytest.mark.e2e
@pytest.mark.timeout(30)
@requires_postgres
def test_custom_dashboard_with_kpi(admin_server, page, base_url) -> None:
    """Custom dashboard loads with KPI cards (needs PostgreSQL)."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)
    page.goto(f"{base_url}/admin/dashboard")
    page.wait_for_load_state("networkidle")
    assert "Дашборд" in page.content()


@pytest.mark.e2e
@pytest.mark.timeout(30)
@requires_postgres
def test_dashboard_chart_range_and_values(admin_server, page, base_url) -> None:
    """Show all 30 calendar days and let the operator zoom in and reset."""
    from playwright.sync_api import expect

    # The daily table also works if the chart CDN is unavailable.
    page.route(
        "https://cdn.jsdelivr.net/npm/chart.js@*/**",
        lambda route: route.abort(),
    )
    _login(page, base_url)
    response = page.goto(f"{base_url}/admin/dashboard?period=30d")
    assert response is not None and response.ok
    page.locator('[data-chart="orders"] .chart-expand').click()
    detail = page.get_by_role("dialog")
    expect(detail).to_be_visible()
    rows = detail.locator("tbody tr")
    expect(rows).to_have_count(30)
    detail.get_by_role("button", name="Последние 7 дней").click()
    expect(rows).to_have_count(7)
    detail.get_by_role("button", name="Весь период").click()
    expect(rows).to_have_count(30)
    page.keyboard.press("Escape")
    expect(detail).not_to_be_visible()
    page.locator(".payout-jump").click()
    expect(page.locator("#payout-requests details")).to_have_attribute(
        "open", ""
    )


@pytest.mark.e2e
@pytest.mark.timeout(30)
@requires_postgres
def test_navigation_creators(admin_server, page, base_url) -> None:
    """Creators page loads (requires PostgreSQL, blogger_profiles)."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)
    page.goto(f"{base_url}/admin/users/creators")
    page.wait_for_load_state("networkidle")
    assert "creators" in page.url or "Креаторы" in page.content()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_navigation_advertisers_orders(admin_server, page, base_url) -> None:
    """Navigate between advertisers and orders sections."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)

    page.goto(f"{base_url}/admin/users/advertisers")
    page.wait_for_load_state("networkidle")
    assert "advertisers" in page.url

    page.goto(f"{base_url}/admin/orders")
    page.wait_for_load_state("networkidle")
    assert "orders" in page.url


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_sqladmin_list_views(admin_server, page, base_url) -> None:
    """Access SQLAdmin list views after login."""
    _login(page, base_url)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)

    response = page.goto(f"{base_url}/admin/user-model/list")
    assert response is not None
    assert response.status in (200, 304)


@pytest.mark.e2e
@pytest.mark.timeout(60)
def test_order_worklist_search_hide_and_restore(
    admin_server, page, base_url, test_database
):
    """Long geography stays in the table and visibility can be changed."""
    from datetime import datetime, timezone
    from uuid import uuid4

    from playwright.sync_api import expect
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
    from ugc_bot.infrastructure.db.models import (
        AdvertiserProfileModel,
        OrderModel,
        UserModel,
    )

    if not test_database:
        pytest.skip("Requires the isolated local browser test database")

    engine = create_engine(test_database)
    now = datetime.now(timezone.utc)
    user_id, order_id = uuid4(), uuid4()
    brand = f"Workbench-{order_id.hex[:8]}"
    geography = "Новосибирская область, Свердловская область, " * 20
    with Session(engine) as session, session.begin():
        session.add(
            UserModel(
                user_id=user_id,
                username="test-merchant",
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
                brand=brand,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            OrderModel(
                order_id=order_id,
                advertiser_id=user_id,
                status=OrderStatus.NEW,
                offer_text="Браузерный тест черновика",
                product_link="https://example.com",
                geography=geography,
                price=1850,
                bloggers_needed=5,
                created_at=now,
                updated_at=now,
            )
        )
    engine.dispose()

    _login(page, base_url)
    page.goto(f"{base_url}/admin/order-model/list")
    page.get_by_label("Поиск", exact=True).fill(brand)
    page.locator(".order-worklist").get_by_role("button", name="Найти").click()
    row = page.get_by_role("row").filter(has_text=brand)
    expect(row).to_have_count(1)
    expect(row).to_contain_text("1 850,00 RUB")
    filtered_list = page.url
    row.get_by_role("link", name="Открыть", exact=True).click()
    expect(
        page.get_by_role("heading", name="Браузерный тест черновика")
    ).to_be_visible()
    page.get_by_role("link", name="Назад к списку").click()
    assert page.url == filtered_list
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(brand)
    geography_cell = row.locator("td").first.locator("span")
    for width in (1440, 820):
        page.set_viewport_size({"width": width, "height": 800})
        assert geography_cell.evaluate(
            "(cell) => getComputedStyle(cell).webkitLineClamp === '2' "
            "&& cell.scrollHeight > cell.clientHeight"
        )
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
    hide = row.get_by_role("button", name="Убрать из списка")
    page.once("dialog", lambda dialog: dialog.dismiss())
    hide.click()
    expect(row).to_be_visible()
    messages = []

    def confirm(dialog):
        messages.append(dialog.message)
        dialog.accept()

    page.once("dialog", confirm)
    hide.click()
    expect(page.get_by_role("status")).to_have_text("Заказ убран из списка.")
    assert messages and order_id.hex[:8] in messages[0]
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(brand)
    expect(page.get_by_text("Заказы не найдены")).to_be_visible()

    page.get_by_role("link", name="Скрытые").click()
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(brand)
    restore = row.get_by_role("button", name="Вернуть в список")
    page.once("dialog", lambda dialog: dialog.dismiss())
    restore.click()
    expect(row).to_be_visible()
    page.once("dialog", confirm)
    restore.click()
    expect(page.get_by_role("status")).to_have_text("Заказ возвращён в список.")
    assert len(messages) == 2 and order_id.hex[:8] in messages[1]
    expect(row).to_have_count(0)
    page.get_by_role("link", name="В работе").click()
    expect(row).to_be_visible()

    row.get_by_role("link", name="Редактировать", exact=True).click()
    expect(page.get_by_role("heading", name="Бриф заказа")).to_be_visible()
    expect(page.get_by_role("heading", name="Подбор креаторов")).to_be_visible()
    expect(page.get_by_role("link", name=brand)).to_be_visible()
    barter = page.get_by_label("Описание бартера", exact=True)
    barter.fill("я" * 4001)
    expect(page.locator("#barter_description-count")).to_contain_text(
        "4001 / 4000"
    )
    assert barter.evaluate("(field) => !field.validity.valid")
    barter.fill("Билеты")
    page.get_by_label("География", exact=True).fill("Казань")
    expect(page.locator("#order-audience-dirty")).to_be_visible()
    page.get_by_role(
        "button", name="Сохранить и продолжить", exact=True
    ).click()
    expect(page.get_by_label("География", exact=True)).to_have_value("Казань")
    expect(page.locator("#order-audience-dirty")).to_be_hidden()
    page.get_by_role("link", name="← Назад к списку").click()
    marker = row.get_by_role("button", name="Это тест", exact=True)
    page.once("dialog", confirm)
    marker.click()
    expect(row).to_have_count(0)
    page.get_by_role("link", name="Тестовые", exact=True).click()
    expect(row).to_be_visible()
    row.get_by_role("link", name="Открыть", exact=True).click()
    delete = page.get_by_role("button", name="Удалить заказ", exact=True)
    page.once("dialog", lambda dialog: dialog.dismiss())
    delete.click()
    expect(delete).to_be_visible()
    page.once("dialog", confirm)
    delete.click()
    expect(page.get_by_role("status")).to_have_text("Тестовый заказ удалён.")
    expect(row).to_have_count(0)
