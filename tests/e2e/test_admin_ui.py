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
    response = page.goto(f"{admin_server}/admin/dashboard?period=all")
    assert response is not None and response.ok
    assert page.get_by_role("heading", name="Дашборд", exact=True).is_visible()
    assert page.get_by_text("Последние 7 дней к предыдущим 7 дням").is_visible()
    assert page.get_by_role(
        "heading", name="Запуски админом без оплаты"
    ).is_visible()
    assert page.get_by_text("Участвовали за всё время").is_visible()
    assert page.get_by_text("Участвовали за период").count() == 0

    cohorts = page.get_by_role("region", name="Активация и повторные заказы")
    assert cohorts.get_by_text("Первый заказ за 30 дней").is_visible()
    assert cohorts.get_by_text("Первая оплата за 30 дней").is_visible()
    assert cohorts.get_by_text("Создали второй заказ").is_visible()
    assert cohorts.get_by_text("Оплатили второй заказ").is_visible()
    assert cohorts.get_by_text("Оплатили второй за 90 дней").is_visible()

    page.get_by_role("navigation", name="Период аналитики").get_by_role(
        "link", name="7 дней"
    ).click()
    assert cohorts.get_by_text("За всё время").is_visible()
    assert page.get_by_text("Участвовали впервые").is_visible()
    assert page.get_by_text("Участвовали повторно").is_visible()
    page.get_by_text("Как считаем участие").click()
    assert page.get_by_text("Начали платное сотрудничество").is_visible()

    cohorts.get_by_role("link").filter(has_text="плативших").click()
    assert page.get_by_role("heading", name="Повторные заявки").is_visible()
    group = page.get_by_role("navigation", name="Группы заказов")
    assert (
        group.get_by_role("link", name="Повторные", exact=True).get_attribute(
            "aria-current"
        )
        == "page"
    )


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
    from urllib.parse import parse_qs, urlsplit
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
    handle = "browser_manager_" + manager_id.hex[:9]
    customer_name = f"Анна Петрова {order_id.hex[:8]}"
    geography = "Новосибирская область, Свердловская область, " * 20
    with Session(engine) as session, session.begin():
        session.add(
            UserModel(
                user_id=user_id,
                username=customer_name,
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
                created_at=now - timedelta(days=8),
                updated_at=now - timedelta(days=8),
            )
        )
        session.add_all(
            UserModel(
                user_id=uid,
                username=name,
                telegram=telegram,
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.ACTIVE
                if uid == manager_id
                else UserStatus.BOT_BLOCKED,
                created_at=now,
                updated_at=now,
            )
            for uid, name, telegram in (
                (creator_id, "Тестовый креатор", "browser_creator"),
                (manager_id, "Тестовый менеджер", handle),
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
    partial_brand = brand.removeprefix("Work")
    page.get_by_label("Поиск", exact=True).fill(f"Петрова {partial_brand}")
    page.locator(".order-worklist").get_by_role("button", name="Найти").click()
    expect(page.get_by_role("row").filter(has_text=brand)).to_have_count(2)
    page.get_by_label("Поиск", exact=True).fill(brand)
    page.locator(".order-worklist").get_by_role("button", name="Найти").click()
    expect(page.get_by_role("row").filter(has_text=brand)).to_have_count(2)
    page.get_by_role("link", name="По компаниям", exact=True).click()
    company = page.get_by_role("link", name=f"{brand} Заказов: 2")
    expect(company).to_have_attribute("aria-expanded", "false")
    expect(page.get_by_role("row").filter(has_text=brand)).to_have_count(0)
    company.click()
    expect(company).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_role("row").filter(has_text=brand)).to_have_count(2)
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(brand)
    expanded_list = page.url
    page.get_by_role("row").filter(has_text=managed_title).get_by_role(
        "link", name="Открыть", exact=True
    ).click()
    page.get_by_role("link", name="Назад к списку").click()
    assert page.url.split("#", 1)[0] == expanded_list.split("#", 1)[0]
    expect(company).to_have_attribute("aria-expanded", "true")
    company.click()
    expect(company).to_have_attribute("aria-expanded", "false")
    page.get_by_role("link", name="Списком", exact=True).click()
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(brand)
    matching_rows = page.get_by_role("row").filter(has_text=brand)
    expect(matching_rows).to_have_count(2)
    quick = page.get_by_role("navigation", name="Быстрые фильтры")
    no_manager = quick.get_by_role("link", name="Без менеджера")
    inactive = quick.get_by_role("link", name="Давно без активности")
    no_manager.click()
    page.get_by_role("link", name="По компаниям", exact=True).click()
    filtered_company = page.get_by_role("link", name=f"{brand} Заказов: 1")
    filtered_company.click()
    expect(matching_rows).to_have_count(1)
    expect(matching_rows).to_contain_text("Браузерный тест черновика")
    page.get_by_role("link", name="Списком", exact=True).click()
    expect(matching_rows).to_have_count(1)
    expect(matching_rows).to_contain_text("Браузерный тест черновика")
    inactive.click()
    expect(matching_rows).to_have_count(1)
    expect(no_manager).to_contain_text("снять фильтр")
    expect(inactive).to_contain_text("снять фильтр")
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(brand)
    page.get_by_label("Статус").select_option("active")
    page.locator(".order-worklist").get_by_role("button", name="Найти").click()
    expect(matching_rows).to_have_count(0)
    expect(no_manager).to_contain_text("снять фильтр")
    expect(inactive).to_contain_text("снять фильтр")
    page.get_by_role("link", name="Сбросить", exact=True).click()
    assert not {"inactive", "no_manager"} & set(
        parse_qs(urlsplit(page.url).query)
    )
    expect(matching_rows).to_have_count(2)
    page.get_by_label("Поиск", exact=True).fill("черновика")
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
    expect(page.get_by_label("Поиск", exact=True)).to_have_value("черновика")
    for width in (1440, 820):
        page.set_viewport_size({"width": width, "height": 800})
        page.wait_for_function(
            """() => {
              const cell = document.querySelector(
                ".order-worklist-table tbody tr td .order-clamp"
              );
              return cell && getComputedStyle(cell).webkitLineClamp === "2" &&
                cell.scrollHeight > cell.clientHeight &&
                document.documentElement.scrollWidth <= window.innerWidth;
            }"""
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
    expect(page.get_by_label("Поиск", exact=True)).to_have_value("черновика")
    expect(page.get_by_text("Заказы не найдены")).to_be_visible()

    page.get_by_role("link", name="Скрытые").click()
    expect(page.get_by_label("Поиск", exact=True)).to_have_value("черновика")
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

    # A separate unmanaged order keeps the existing deletion scenario intact.
    assign_id = uuid4()
    assign_title = f"Назначение менеджера {assign_id.hex[:8]}"
    engine = create_engine(test_database)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                OrderModel(
                    order_id=assign_id,
                    advertiser_id=user_id,
                    status=OrderStatus.NEW,
                    offer_text=assign_title,
                    product_link="https://example.test",
                    price=100,
                    bloggers_needed=1,
                    created_at=now,
                    updated_at=now,
                )
            )
    finally:
        engine.dispose()

    page.goto(
        f"{admin_server}/admin/order-model/list?no_manager=1&search={assign_id}"
    )
    assign_row = page.get_by_role("row").filter(has_text=assign_title)
    expect(
        assign_row.get_by_text("Назначить менеджера", exact=True)
    ).to_be_visible()
    page.set_viewport_size({"width": 390, "height": 800})
    assign_row.get_by_text("Назначить менеджера", exact=True).click()
    field = assign_row.get_by_label("Telegram-ник менеджера")
    expect(field).to_be_visible()
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    expect(
        page.locator(f'#worklist-managers option[value="@{handle}"]')
    ).to_have_count(1)
    field.fill("@" + handle.upper())
    assign_row.get_by_role("button", name="Назначить", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text(
        f"Менеджер @{handle} назначен."
    )
    expect(assign_row).to_have_count(0)
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(str(assign_id))
    page.get_by_role("link", name="Без менеджера").click()
    expect(
        assign_row.get_by_role("link", name="Тестовый менеджер")
    ).to_be_visible()

    replacement = "browser_new_" + assign_id.hex[:8]
    engine = create_engine(test_database)
    try:
        with Session(engine) as session, session.begin():
            session.add(
                UserModel(
                    user_id=uuid4(),
                    username="Новый тестовый менеджер",
                    telegram=replacement,
                    messenger_type=MessengerType.TELEGRAM,
                    status=UserStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
            )
    finally:
        engine.dispose()

    css = page.locator('link[href*="order-worklist.css"]')
    expect(css).to_have_count(1)
    page.wait_for_function(
        "Array.from(document.styleSheets).some(sheet => "
        "sheet.href?.includes('order-worklist.css'))"
    )
    assign_row.get_by_text("Сменить менеджера", exact=True).click()
    field.fill("@" + replacement)
    assert page.evaluate(
        "document.documentElement.scrollWidth <= window.innerWidth"
    )
    replace = assign_row.get_by_role("button", name="Заменить", exact=True)
    page.once("dialog", lambda dialog: dialog.dismiss())
    replace.click()
    expect(
        assign_row.get_by_role("link", name="Тестовый менеджер", exact=True)
    ).to_be_visible()
    prompts = []

    def confirm_replacement(dialog):
        prompts.append(dialog.message)
        dialog.accept()

    page.once("dialog", confirm_replacement)
    field.press("Enter")
    expect(page.get_by_role("status")).to_contain_text(
        f"Менеджер заменён на @{replacement}."
    )
    assert prompts == [
        f"Заменить менеджера «Тестовый менеджер» на @{replacement}?"
    ]
    expect(
        assign_row.get_by_role(
            "link", name="Новый тестовый менеджер", exact=True
        )
    ).to_be_visible()
    expect(page.get_by_label("Поиск", exact=True)).to_have_value(str(assign_id))


@pytest.mark.e2e
@pytest.mark.timeout(60)
def test_manual_order_closure_requires_and_displays_reason(
    admin_server: str, page, test_database
):
    from datetime import datetime, timezone
    from uuid import uuid4

    from playwright.sync_api import expect
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from ugc_bot.domain.enums import MessengerType, OrderStatus, UserStatus
    from ugc_bot.infrastructure.db.models import OrderModel, UserModel

    if not test_database:
        pytest.skip("Requires the isolated local browser test database")

    engine = create_engine(test_database)
    now = datetime.now(timezone.utc)
    user_id, quick_id, editor_id = (uuid4() for _ in range(3))
    try:
        with Session(engine) as session, session.begin():
            session.add(
                UserModel(
                    user_id=user_id,
                    username="Тестовый заказчик",
                    messenger_type=MessengerType.TELEGRAM,
                    status=UserStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add_all(
                OrderModel(
                    order_id=order_id,
                    advertiser_id=user_id,
                    status=OrderStatus.ACTIVE,
                    offer_text=title,
                    product_link="https://example.test",
                    price=100,
                    bloggers_needed=1,
                    created_at=now,
                    updated_at=now,
                )
                for order_id, title in (
                    (quick_id, "Проверка закрытия из списка"),
                    (editor_id, "Проверка закрытия из редактора"),
                )
            )
    finally:
        engine.dispose()

    _login(page, admin_server)
    listing = f"{admin_server}/admin/order-model/list"
    page.goto(f"{listing}?search={quick_id}")
    row = page.get_by_role("row").filter(has_text="Проверка закрытия из списка")
    close = row.get_by_role("button", name="Закрыть", exact=True)
    close.click()
    dialog = page.get_by_role("dialog", name="Закрыть заказ")
    reason = dialog.get_by_label("Причина закрытия")
    expect(reason).to_be_focused()
    dialog.get_by_role("button", name="Закрыть заказ").click()
    assert reason.evaluate("(field) => field.validity.valueMissing")
    dialog.get_by_role("button", name="Отмена").click()
    expect(dialog).to_be_hidden()
    expect(row.get_by_text("Активный", exact=True)).to_be_visible()
    close.click()
    reason.fill("Клиент перенёс запуск")
    dialog.get_by_role("button", name="Закрыть заказ").click()
    expect(row.get_by_text("Закрытый", exact=True)).to_be_visible()
    expect(row.get_by_text("Клиент перенёс запуск", exact=True)).to_be_visible()
    expect(page).to_have_url(f"{listing}?group=closed&search={quick_id}")

    page.goto(f"{admin_server}/admin/order-model/edit/{editor_id}")
    reason = page.get_by_label("Причина закрытия")
    expect(reason).to_be_hidden()
    page.locator("#status").select_option("closed")
    expect(reason).to_be_visible()
    assert reason.evaluate("(field) => field.validity.valueMissing")
    reason.fill("Клиент отменил заказ")
    page.get_by_role("button", name="Сохранить изменения", exact=True).click()
    expect(page.get_by_text("Клиент отменил заказ", exact=True)).to_be_visible()
    page.goto(f"{listing}?group=closed&search={editor_id}")
    row = page.get_by_role("row").filter(
        has_text="Проверка закрытия из редактора"
    )
    expect(row.get_by_text("Клиент отменил заказ", exact=True)).to_be_visible()
