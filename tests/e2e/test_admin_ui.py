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
def test_login_redirects_unauthenticated(admin_server: str, page) -> None:
    """GET /admin/dashboard without session redirects to /admin/login."""
    page.goto(f"{admin_server}/admin/dashboard")
    page.wait_for_url(f"{admin_server}/admin/login", timeout=5000)
    assert "login" in page.url.lower()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_login_success(admin_server: str, page) -> None:
    """POST login with valid credentials redirects to dashboard."""
    _login(page, admin_server)
    page.wait_for_url(
        lambda url: "login" not in url,
        timeout=5000,
    )
    assert "login" not in page.url


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_login_invalid_credentials(admin_server: str, page) -> None:
    """Invalid password keeps user on login page."""
    _login(page, admin_server, password="wrong_password")
    page.wait_for_load_state("networkidle")
    assert "login" in page.url.lower()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_dashboard_loads(admin_server: str, page) -> None:
    """After login, admin index or dashboard loads."""
    _login(page, admin_server)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)
    page.goto(f"{admin_server}/admin/")
    page.wait_for_load_state("networkidle")
    assert page.url.rstrip("/").endswith("/admin") or "/admin/" in page.url


@pytest.mark.e2e
@pytest.mark.timeout(30)
@requires_postgres
def test_custom_dashboard_with_kpi(admin_server: str, page) -> None:
    """Custom dashboard loads with KPI cards (needs PostgreSQL)."""
    _login(page, admin_server)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)
    page.goto(f"{admin_server}/admin/dashboard")
    page.wait_for_load_state("networkidle")
    assert "Дашборд" in page.content()


@pytest.mark.e2e
@pytest.mark.timeout(30)
@requires_postgres
def test_dashboard_chart_range_and_values(admin_server: str, page) -> None:
    """Show all 30 calendar days and let the operator zoom in and reset."""
    from playwright.sync_api import expect

    # The daily table also works if the chart CDN is unavailable.
    page.route(
        "https://cdn.jsdelivr.net/npm/chart.js@*/**",
        lambda route: route.abort(),
    )
    _login(page, admin_server)
    response = page.goto(f"{admin_server}/admin/dashboard?period=30d")
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
    payouts = page.locator("#payout-requests")
    expect(
        page.locator("summary").filter(has_text="Заявки на вывод")
    ).to_have_count(1)
    if payouts.get_attribute("open") is None:
        payouts.locator("summary").click()
    expect(payouts).to_have_attribute("open", "")
    expect(
        payouts.get_by_role("link", name="Реферальные выплаты")
    ).to_be_visible()


@pytest.mark.e2e
@pytest.mark.timeout(30)
@requires_postgres
def test_navigation_creators(admin_server: str, page) -> None:
    """Creators page loads (requires PostgreSQL, blogger_profiles)."""
    _login(page, admin_server)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)
    page.goto(f"{admin_server}/admin/users/creators")
    page.wait_for_load_state("networkidle")
    assert "creators" in page.url or "Креаторы" in page.content()


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_navigation_advertisers_orders(admin_server: str, page) -> None:
    """Navigate between advertisers and orders sections."""
    _login(page, admin_server)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)

    page.goto(f"{admin_server}/admin/users/advertisers")
    page.wait_for_load_state("networkidle")
    assert "advertisers" in page.url

    page.goto(f"{admin_server}/admin/orders")
    page.wait_for_load_state("networkidle")
    assert "orders" in page.url


@pytest.mark.e2e
@pytest.mark.timeout(30)
def test_sqladmin_list_views(admin_server: str, page) -> None:
    """Access SQLAdmin list views after login."""
    _login(page, admin_server)
    page.wait_for_url(lambda url: "login" not in url, timeout=5000)

    response = page.goto(f"{admin_server}/admin/user-model/list")
    assert response is not None
    assert response.status in (200, 304)


@pytest.mark.e2e
@pytest.mark.timeout(90)
def test_order_worklist_search_hide_and_restore(
    admin_server: str, page, test_database
):
    """Check the layout, saved edits, and confirmed actions on isolated data."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    from playwright.sync_api import expect
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
    from ugc_bot.infrastructure.db.models import (
        AdvertiserProfileModel,
        ManagerOrderModel,
        OfferDispatchModel,
        OrderModel,
        UserModel,
    )
    from ugc_bot.infrastructure.db.social_models import SocialAccountModel

    if not test_database:
        pytest.skip("Requires the isolated local browser test database")

    engine = create_engine(test_database)
    now = datetime.now(timezone.utc)
    user_id, order_id, managed_id, creator_id, manager_id = (
        uuid4() for _ in range(5)
    )
    brand = f"Workbench-{order_id.hex[:8]}"
    managed_title = f"Отклик и работа менеджера {managed_id.hex[:8]}"
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
        session.add_all(
            UserModel(
                user_id=uid,
                username=name,
                telegram=telegram,
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.BOT_BLOCKED,
                created_at=now,
                updated_at=now,
            )
            for uid, name, telegram in (
                (creator_id, "Тестовый креатор", "browser_creator"),
                (manager_id, "Тестовый менеджер", None),
            )
        )
        session.add(
            OrderModel(
                order_id=managed_id,
                advertiser_id=user_id,
                status=OrderStatus.ACTIVE,
                offer_text=managed_title,
                product_link="https://example.test/product",
                brief_link="https://example.test/brief",
                price=1850,
                bloggers_needed=5,
                created_at=now - timedelta(days=7),
                updated_at=now - timedelta(days=7),
            )
        )
        session.add(
            ManagerOrderModel(
                user_id=manager_id,
                order_id=managed_id,
                created_at=now,
            )
        )
        session.add(
            OfferDispatchModel(
                order_id=managed_id,
                blogger_id=creator_id,
                accepted=True,
                in_offer=True,
                created_at=now,
                ugc_video_url="https://example.test/ugc",
            )
        )
        session.add(
            SocialAccountModel(
                account_id=uuid4(),
                user_id=creator_id,
                platform="instagram",
                url="https://www.instagram.com/browser_creator/",
                handle="browser_creator",
                work_format="ugc_only",
                created_at=now,
                updated_at=now,
            )
        )
    engine.dispose()

    # This job has no external server or assets. The admin's assets are local.
    page.route(
        "**/*",
        lambda route: (
            route.continue_()
            if route.request.url.startswith(f"{admin_server}/")
            else route.abort()
        ),
    )
    _login(page, admin_server)
    page.goto(f"{admin_server}/admin/order-model/list")
    page.get_by_label("Поиск", exact=True).fill(brand)
    page.locator(".order-worklist").get_by_role("button", name="Найти").click()
    expect(page.get_by_role("row").filter(has_text=brand)).to_have_count(2)
    page.get_by_label("Поиск", exact=True).fill("Браузерный тест черновика")
    page.locator(".order-worklist").get_by_role("button", name="Найти").click()
    row = page.get_by_role("row").filter(has_text="Браузерный тест черновика")
    expect(row).to_have_count(1)
    expect(row).to_contain_text("1 850,00 RUB")
    filtered_list = page.url
    row.get_by_role("link", name="Открыть", exact=True).click()
    expect(
        page.get_by_role("heading", name="Браузерный тест черновика")
    ).to_be_visible()
    page.get_by_role("link", name="Назад к списку").click()
    assert page.url == filtered_list
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(
        "Браузерный тест черновика"
    )
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
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(
        "Браузерный тест черновика"
    )
    expect(page.get_by_text("Заказы не найдены")).to_be_visible()

    page.get_by_role("link", name="Скрытые").click()
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(
        "Браузерный тест черновика"
    )
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
    for width in (1440, 390):
        page.set_viewport_size({"width": width, "height": 800})
        assert page.locator(".order-editor").evaluate(
            """editor => {
              const [top, nav, brief] = ['.order-editor__top',
                '.order-editor__bar', '#order-edit-brief'].map(
                part => editor.querySelector(part).getBoundingClientRect()
              );
              return top.bottom <= nav.top && nav.bottom <= brief.top &&
                Math.abs(top.width - brief.width) <= 1 &&
                document.documentElement.scrollWidth <= window.innerWidth;
            }"""
        )
    page.set_viewport_size({"width": 1440, "height": 800})
    expect(page.get_by_role("link", name="Дублировать заказ")).to_be_visible()
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

    page.goto(f"{admin_server}/admin/order-model/list?search={managed_id}")
    managed_row = page.get_by_role("row").filter(has_text=managed_title)
    expect(managed_row).to_contain_text("Тестовый менеджер")
    expect(managed_row).to_contain_text("1 / 5")
    expect(managed_row).to_contain_text("Осталось 4")
    expect(managed_row).to_contain_text("Мало подобрано")
    expect(managed_row).to_contain_text("Активность")
    managed_row.get_by_role("link", name="Открыть", exact=True).click()
    expect(page.get_by_role("link", name="Тестовый креатор")).to_be_visible()
    expect(
        page.get_by_role("link", name="Instagram @browser_creator")
    ).to_have_attribute("href", "https://www.instagram.com/browser_creator")
    expect(
        page.get_by_role("link", name="Telegram @browser_creator")
    ).to_have_attribute("href", "https://t.me/browser_creator")
    expect(page.get_by_role("link", name="Открыть ТЗ")).to_have_attribute(
        "href", "https://example.test/brief"
    )
    expect(page.get_by_role("link", name="Открыть видео")).to_have_attribute(
        "href", "https://example.test/ugc"
    )
    page.set_viewport_size({"width": 390, "height": 800})
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    page.set_viewport_size({"width": 1440, "height": 800})
    page.get_by_role("link", name="Назад к списку").click()
    page.once("dialog", confirm)
    managed_row.get_by_role("button", name="Это тест", exact=True).click()
    page.get_by_role("link", name="Тестовые", exact=True).click()
    expect(managed_row).to_contain_text(
        "Нельзя удалить: есть рассылка или отклики"
    )
    expect(
        managed_row.get_by_role("button", name="Удалить заказ", exact=True)
    ).to_have_count(0)
    archive = managed_row.get_by_role(
        "button", name="Удалить из списка", exact=True
    )
    page.once("dialog", lambda dialog: dialog.dismiss())
    archive.click()
    expect(managed_row).to_be_visible()
    page.once("dialog", confirm)
    archive.click()
    expect(page.get_by_role("status")).to_contain_text(
        "Заказ удалён из списка."
    )
    expect(managed_row).to_have_count(0)
    page.get_by_role("link", name="Удалённые", exact=True).click()
    expect(managed_row).to_contain_text("Активный")
    page.once("dialog", confirm)
    managed_row.get_by_role("button", name="Вернуть заказ в список").click()
    expect(page.get_by_role("status")).to_have_text(
        "Заказ возвращён из удалённых."
    )
    expect(managed_row).to_have_count(0)
    page.get_by_role("link", name="Тестовые", exact=True).click()
    expect(managed_row).to_be_visible()
