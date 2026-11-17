"""Authenticated directory and profile flows on an isolated PostGIS database."""

import os
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine, delete, insert
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import require_test_database
from ugc_bot.domain.enums import (
    AudienceGender,
    AuditAction,
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    RaterRole,
    UserStatus,
    WorkFormat,
)
from ugc_bot.domain.social import SELF_REPORTED_FOLLOWERS
from ugc_bot.infrastructure.db.messenger_attribution import OFFER_CHANNELS
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    AuditLogModel,
    BloggerProfileModel,
    BloggerRatingModel,
    ComplaintModel,
    InteractionModel,
    NpsResponseModel,
    OfferDispatchModel,
    OrderModel,
    UserModel,
    UserReferralBindingModel,
)
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    BOT_UNAVAILABLE_EVENT,
)
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


@pytest.fixture
def people_records(request):
    database = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not database or not os.environ.get("E2E_BASE_URL"):
        pytest.skip("Requires a synthetic admin server with PostGIS")
    engine = create_engine(require_test_database(database))
    customer_id, creator_id, other_id, paused_id, inviter_id, order_id = [
        uuid4() for _ in range(6)
    ]
    now = datetime.now(timezone.utc)
    telegram_ready_sample = getattr(request, "param", False)
    confirmed_profiles = (creator_id, other_id) if telegram_ready_sample else ()
    token = creator_id.hex[:8]
    brand = f"Марка & Партнёры {token}"
    city = f"Казань {token}"
    instagram = f"city_creator_{token}"
    order_title = f"Кампания {token}"
    creator_name = f"Мария {token}"
    users = [
        UserModel(
            user_id=user_id,
            username=name,
            telegram=handle,
            telegram_id=str(user_id.int % 10**12 + 1)
            if user_id == other_id or user_id in confirmed_profiles
            else None,
            messenger_type=MessengerType.TELEGRAM,
            status=status,
        )
        for user_id, name, handle, status in [
            (customer_id, f"Анна {token}", f"anna_{token}", UserStatus.ACTIVE),
            (creator_id, creator_name, f"maria_{token}", UserStatus.ACTIVE),
            (other_id, f"Ирина {token}", None, UserStatus.ACTIVE),
            (paused_id, f"Ольга {token}", None, UserStatus.PAUSE),
            (
                inviter_id,
                f"Менеджер {token}",
                f"manager_{token}",
                UserStatus.ACTIVE,
            ),
        ]
    ]
    with Session(engine) as session, session.begin():
        session.add_all(users)
        session.flush()
        blocked = [(other_id, now)]
        if telegram_ready_sample:
            blocked.append((creator_id, now - timedelta(minutes=2)))
        session.add_all(
            AuditLogModel(
                entity_type=BOT_UNAVAILABLE_EVENT,
                entity_id=user_id,
                action=AuditAction.CREATE,
                new_values={"platform": "telegram"},
                changed_at=blocked_at,
            )
            for user_id, blocked_at in blocked
        )
        session.add(
            UserReferralBindingModel(
                referrer_user_id=inviter_id, referred_user_id=other_id
            )
        )
        session.add(
            AdvertiserProfileModel(
                user_id=customer_id,
                contact="synthetic",
                brand=brand,
                site_link=f"https://example.com/{token}",
            )
        )
        for user_id, handle, followers in [
            (creator_id, instagram, 7500),
            (other_id, f"other_{token}", 800),
            (paused_id, f"paused_{token}", 900),
        ]:
            session.add(
                BloggerProfileModel(
                    user_id=user_id,
                    instagram_url=f"https://instagram.com/{handle}",
                    city=(
                        f"Томск {token}"
                        if telegram_ready_sample and user_id == paused_id
                        else f" {city.lower()} "
                        if user_id == creator_id
                        else city
                    ),
                    confirmed=user_id in confirmed_profiles,
                    agreement_confirmed_at=now
                    if user_id in confirmed_profiles
                    else None,
                    topics={"beauty": True},
                    audience_gender=AudienceGender.ALL,
                    audience_age_min=18,
                    audience_age_max=35,
                    audience_geo="RU",
                    price=2000,
                    instagram_followers_count=followers,
                )
            )
        for user_id, platform, url, handle, followers in (
            (
                creator_id,
                "tiktok",
                f"https://www.tiktok.com/@{instagram}",
                instagram,
                None,
            ),
            (
                creator_id,
                "youtube",
                f"https://www.youtube.com/@{instagram}",
                instagram,
                20000,
            ),
            (
                creator_id,
                "dzen",
                f"https://dzen.ru/{instagram}",
                instagram,
                None,
            ),
            (
                creator_id,
                "other",
                "https://www.twitch.tv/synthetic",
                "Twitch",
                None,
            ),
            (
                other_id,
                "youtube",
                f"https://www.youtube.com/@other_{token}",
                f"other_{token}",
                1200,
            ),
            (
                other_id,
                "dzen",
                f"https://dzen.ru/other_{token}",
                f"other_{token}",
                None,
            ),
            (other_id, "rutube", "https://rutube.ru/channel/123/", "123", 0),
        ):
            session.add(
                SocialAccountModel(
                    account_id=uuid4(),
                    user_id=user_id,
                    platform=platform,
                    url=url,
                    handle=handle,
                    work_format=WorkFormat.UGC_ONLY,
                    followers_count=followers,
                    metrics_source=SELF_REPORTED_FOLLOWERS
                    if followers is not None
                    else None,
                    metrics_fetched_at=now if followers is not None else None,
                    created_at=now,
                    updated_at=now,
                )
            )
        session.add(
            OrderModel(
                order_id=order_id,
                advertiser_id=customer_id,
                status=OrderStatus.CLOSED,
                offer_text=order_title,
                product_link="https://example.com/product",
                bloggers_needed=1,
                price=2000,
            )
        )
        session.flush()
        session.add_all(
            [
                InteractionModel(
                    interaction_id=uuid4(),
                    order_id=order_id,
                    blogger_id=creator_id,
                    advertiser_id=customer_id,
                    status=InteractionStatus.OK,
                    from_advertiser="Уложились в срок",
                    from_blogger="Бриф был понятным",
                ),
                ComplaintModel(
                    complaint_id=uuid4(),
                    order_id=order_id,
                    reporter_id=creator_id,
                    reported_id=customer_id,
                    status=ComplaintStatus.PENDING,
                    reason="Ожидали ответ на уточнение",
                ),
                BloggerRatingModel(
                    rating_id=uuid4(),
                    blogger_id=creator_id,
                    order_id=order_id,
                    rater_id=customer_id,
                    rater_role=RaterRole.ADVERTISER,
                    score=5,
                    comment="Хорошо снято",
                    created_at=now,
                ),
                BloggerRatingModel(
                    rating_id=uuid4(),
                    blogger_id=creator_id,
                    order_id=order_id,
                    rater_id=other_id,
                    rater_role=RaterRole.MANAGER,
                    score=3,
                    created_at=now,
                ),
                NpsResponseModel(
                    user_id=creator_id, score=4, comment="Удобная платформа"
                ),
                OfferDispatchModel(
                    order_id=order_id, blogger_id=creator_id, accepted=True
                ),
            ]
        )
        if telegram_ready_sample:
            session.add(
                OfferDispatchModel(order_id=order_id, blogger_id=other_id)
            )
            session.flush()
            session.execute(
                insert(OFFER_CHANNELS),
                [
                    dict(
                        order_id=order_id,
                        blogger_id=user_id,
                        telegram_sent_at=now - timedelta(minutes=1),
                    )
                    for user_id in confirmed_profiles
                ],
            )
    try:
        yield brand, city, instagram, order_title, creator_name
    finally:
        with engine.begin() as db:
            db.execute(
                delete(AuditLogModel).where(
                    AuditLogModel.entity_id.in_((creator_id, other_id))
                )
            )
            db.execute(
                delete(OrderModel).where(OrderModel.order_id == order_id)
            )
            db.execute(
                delete(UserModel).where(
                    UserModel.user_id.in_(
                        [
                            customer_id,
                            creator_id,
                            other_id,
                            paused_id,
                            inviter_id,
                        ]
                    )
                )
            )
        engine.dispose()


@pytest.mark.e2e
@pytest.mark.timeout(60)
def test_directory_filters_and_profile_history(
    admin_server, page, people_records
):
    from tests.e2e.test_admin_ui import _login

    brand, city, instagram, order_title, creator_name = people_records
    base_url = admin_server
    _login(page, base_url)
    page.goto(f"{base_url}/admin/users/advertisers")
    page.get_by_label("Поиск", exact=True).fill(brand)
    page.locator("#people-activity").select_option("without_orders")
    page.get_by_role("button", name="Найти", exact=True).last.click()
    expect(
        page.get_by_text("Заказчики не найдены.", exact=False)
    ).to_be_visible()
    page.locator("#people-activity").select_option("with_orders")
    page.get_by_label("С жалобами").check()
    page.get_by_role("button", name="Найти", exact=True).last.click()
    expect(page.get_by_text("Найдено 1")).to_be_visible()
    page.get_by_role("link", name="Последний заказ").click()
    filtered = page.url
    page.get_by_role("link", name=brand, exact=True).click()
    expect(
        page.locator("#orders").get_by_role("link", name=order_title)
    ).to_be_visible()
    expect(
        page.locator("#feedback").get_by_text("Бриф был понятным")
    ).to_be_visible()
    expect(page.locator("#ratings").get_by_text("Хорошо снято")).to_be_visible()
    expect(
        page.locator("#complaints").get_by_text("Ожидали ответ на уточнение")
    ).to_be_visible()
    page.get_by_role("link", name="Назад к списку").click()
    assert page.url == filtered

    page.goto(f"{base_url}/admin/users/creators")
    page.locator("#people-city").select_option(city.lower())
    page.locator("#people-followers").select_option("5000")
    page.get_by_role("button", name="Найти", exact=True).last.click()
    expect(page.get_by_text("Найдено 1")).to_be_visible()
    page.get_by_label("Поиск", exact=True).fill(f"@{instagram}")
    page.get_by_role("button", name="Найти", exact=True).last.click()
    row = page.get_by_role("row").filter(has_text=creator_name)
    expect(row).to_contain_text("5,0")
    expect(
        row.get_by_role("link", name=f"Instagram @{instagram}")
    ).to_be_visible()
    row.get_by_role("link", name=creator_name).click()
    expect(
        page.locator("#feedback").get_by_text("Уложились в срок")
    ).to_be_visible()
    expect(
        page.locator("#nps").get_by_text("Удобная платформа")
    ).to_be_visible()
    expect(
        page.locator("#complaints").get_by_text("Подал жалобу на")
    ).to_be_visible()
    page.get_by_text("Служебные данные").click()
    expect(page.get_by_text("ID пользователя", exact=True)).to_be_visible()

    for width in (1440, 768, 390, 320):
        page.set_viewport_size({"width": width, "height": 880})
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        )
        page.get_by_role("link", name="Назад к списку").click()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= innerWidth"
        )
        page.get_by_role("link", name=creator_name).click()


@pytest.mark.e2e
@pytest.mark.timeout(60)
def test_creator_social_links_and_bot_status(
    admin_server, page, people_records
):
    from tests.e2e.test_admin_ui import _login

    _, city, instagram, _, creator_name = people_records
    base_url = admin_server
    _login(page, base_url)
    page.goto(f"{base_url}/admin/users/creators")
    page.get_by_role("link", name="Креаторы с недоступным ботом").click()
    expect(page.locator("#people-status")).to_have_value("bot_blocked")
    page.locator("#people-city").select_option(city.lower())
    page.locator("#people-platform").select_option("instagram")
    page.locator(".people-filters").get_by_role("button", name="Найти").click()
    expect(page.get_by_text("Найдено 1")).to_be_visible()
    row = page.locator(".people-table tbody tr")
    expect(row).to_contain_text("Бот недоступен")
    token = instagram.removeprefix("city_creator_")
    inviter_name = f"Менеджер {token}"
    inviter_link = row.get_by_role("link", name=inviter_name)
    expect(inviter_link).to_be_visible()
    expect(
        row.get_by_role("link", name=f"Telegram @manager_{token}")
    ).to_be_visible()
    inviter_href = inviter_link.get_attribute("href")
    inviter_link.click()
    expect(page.get_by_role("heading", name=inviter_name)).to_be_visible()
    page.go_back()
    row.locator(".people-name").click()
    expect(page.get_by_role("link", name=inviter_name)).to_have_attribute(
        "href", inviter_href
    )
    expect(page.locator(".people-heading .people-pill")).to_have_text(
        "Бот недоступен"
    )
    expect(page.get_by_role("link", name="TikTok", exact=True)).to_have_count(0)
    page.get_by_role("link", name="Назад к списку").click()
    expect(page.locator("#people-status")).to_have_value("bot_blocked")
    page.locator("#people-status").select_option("limited")
    page.locator(".people-filters").get_by_role("button", name="Найти").click()
    expect(page.get_by_text("Найдено 1")).to_be_visible()
    expect(row).to_contain_text("Ограничен")
    expect(row).to_contain_text("Без привязки")
    expect(row).not_to_contain_text("Бот недоступен")

    page.goto(f"{base_url}/admin/users/creators?q={instagram}")
    page.get_by_role("link", name=creator_name, exact=True).click()
    for label, host in (
        ("TikTok", "www.tiktok.com"),
        ("YouTube", "www.youtube.com"),
    ):
        link = page.get_by_role("link", name=label, exact=True)
        expect(link).to_be_visible()
        expect(link).to_have_attribute("href", f"https://{host}/@{instagram}")


@pytest.mark.e2e
@pytest.mark.timeout(60)
def test_creator_platform_filter_combines_with_search_and_filters(
    admin_server, page, people_records
):
    from tests.e2e.test_admin_ui import _login

    _, city, instagram, _, creator_name = people_records
    _login(page, admin_server)
    page.goto(f"{admin_server}/admin/users/creators")
    form = page.locator(".people-filters")
    submit = form.get_by_role("button", name="Найти")
    platform = form.get_by_label("Есть ссылка на площадку")
    form.get_by_label("Поиск").fill(creator_name)
    form.get_by_label("Город").select_option(city.lower())
    form.get_by_label("Статус").select_option("active")
    form.get_by_label("Подписчики Instagram").select_option("5000")
    form.get_by_label("Регистрация").select_option("7d")

    for value, label in [
        ("youtube", "YouTube"),
        ("dzen", "Дзен"),
        ("other", "Twitch"),
    ]:
        platform.select_option(value)
        submit.click()
        expect(page.get_by_text("Найдено 1", exact=True)).to_be_visible()
        page.get_by_role("link", name=creator_name, exact=True).click()
        expect(page.get_by_role("link", name=label, exact=True)).to_be_visible()
        page.get_by_role("link", name="Назад к списку").click()
        expect(platform).to_have_value(value)

    form.get_by_label("С жалобами").check()
    submit.click()
    expect(page.get_by_text("Найдено 0", exact=True)).to_be_visible()
    form.get_by_label("С жалобами").uncheck()
    platform.select_option("vk")
    submit.click()
    expect(page.get_by_text("Найдено 0", exact=True)).to_be_visible()

    form.get_by_role("link", name="Сбросить").click()
    expect(platform).to_have_value("")
    expect(form.get_by_label("Поиск")).to_have_value("")
    form.get_by_label("Поиск").fill(
        f"@other_{instagram.removeprefix('city_creator_')}"
    )
    platform.select_option("instagram")
    submit.click()
    expect(page.get_by_text("Найдено 1", exact=True)).to_be_visible()
    expect(page.locator(".people-table tbody tr")).to_contain_text(
        "Бот недоступен"
    )


@pytest.mark.e2e
@pytest.mark.timeout(60)
def test_selected_platform_audience_with_search_and_blocked_bot(
    admin_server, page, people_records
):
    from tests.e2e.test_admin_ui import _login

    _, city, instagram, _, active_name = people_records
    token = instagram.removeprefix("city_creator_")
    blocked_name = f"Ирина {token}"
    _login(page, admin_server)
    page.goto(f"{admin_server}/admin/users/creators")
    form = page.locator(".people-filters")
    table = page.locator(".people-table")
    platform = form.get_by_label("Есть ссылка на площадку")
    minimum = form.get_by_label("От N подписчиков")
    unknown = form.get_by_label("Число не указано")
    search = form.get_by_label("Поиск")
    submit = form.get_by_role("button", name="Найти")
    expect(minimum).to_be_disabled()
    expect(unknown).to_be_disabled()

    search.fill(token)
    form.get_by_label("Город").select_option(city.lower())
    platform.select_option("youtube")
    minimum.fill("1200")
    submit.click()
    expect(page.get_by_text("Найдено 2", exact=True)).to_be_visible()
    page.get_by_role("link", name="Креаторы с недоступным ботом").click()
    expect(form.get_by_label("Статус")).to_have_value("bot_blocked")
    expect(search).to_have_value(token)
    expect(platform).to_have_value("youtube")
    expect(minimum).to_have_value("1200")
    expect(table.get_by_role("link", name=active_name)).to_have_count(0)
    table.get_by_role("link", name=blocked_name).click()
    expect(
        page.get_by_text("со слов креатора", exact=False).first
    ).to_be_visible()
    page.get_by_role("link", name="Назад к списку").click()
    expect(minimum).to_have_value("1200")

    search.fill(active_name)
    submit.click()
    expect(page.get_by_text("Найдено 0", exact=True)).to_be_visible()
    search.fill(token)
    minimum.fill("1201")
    submit.click()
    expect(page.get_by_text("Найдено 0", exact=True)).to_be_visible()

    platform.select_option("dzen")
    unknown.check()
    expect(minimum).to_be_disabled()
    submit.click()
    expect(page.get_by_text("Найдено 1", exact=True)).to_be_visible()
    expect(table.get_by_role("link", name=blocked_name)).to_be_visible()
    expect(unknown).to_be_checked()

    for known_or_missing in ("youtube", "rutube", "vk"):
        platform.select_option(known_or_missing)
        submit.click()
        expect(page.get_by_text("Найдено 0", exact=True)).to_be_visible()

    platform.select_option("rutube")
    unknown.uncheck()
    minimum.fill("0")
    submit.click()
    expect(page.get_by_text("Найдено 1", exact=True)).to_be_visible()
    expect(minimum).to_have_value("0")

    platform.select_option("instagram")
    minimum.fill("800")
    submit.click()
    expect(page.get_by_text("Найдено 1", exact=True)).to_be_visible()
    minimum.fill("801")
    submit.click()
    expect(page.get_by_text("Найдено 0", exact=True)).to_be_visible()

    form.get_by_role("link", name="Сбросить").click()
    expect(platform).to_have_value("")
    expect(minimum).to_have_value("")
    expect(unknown).not_to_be_checked()
    expect(unknown).to_be_disabled()


@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("width", [320, 1440])
@pytest.mark.parametrize("people_records", [True], indirect=True)
def test_telegram_ready_combines_with_city_platform_and_followers(
    admin_server, page, people_records, width
):
    from tests.e2e.test_admin_ui import _login

    _, city, instagram, _, creator = people_records
    other_city = f"томск {instagram.removeprefix('city_creator_')}"
    page.set_viewport_size({"width": width, "height": 900})
    _login(page, admin_server)
    page.goto(f"{admin_server}/admin/users/creators")
    form = page.locator(".people-filters")
    city_filter = form.get_by_label("Город")
    platform = form.get_by_label("Есть ссылка на площадку")
    minimum = form.get_by_label("От N подписчиков")
    submit = form.get_by_role("button", name="Найти")
    ready = page.get_by_role(
        "link", name="Готовы к подбору в Telegram", exact=True
    )
    remove_ready = page.get_by_role(
        "link", name="Снять фильтр «Готовы к подбору в Telegram»"
    )

    city_filter.select_option(city.lower())
    platform.select_option("youtube")
    minimum.fill("1200")
    submit.click()
    expect(page.get_by_text("Найдено 2", exact=True)).to_be_visible()
    ready.click()
    expect(remove_ready).to_have_attribute("aria-current", "true")
    expect(city_filter).to_have_value(city.lower())
    expect(platform).to_have_value("youtube")
    expect(minimum).to_have_value("1200")
    expect(page.get_by_text("Найдено 1", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name=creator, exact=True)).to_be_visible()

    for city_value, channel, threshold, count in (
        (other_city, "youtube", "1200", 0),
        (city.lower(), "tiktok", "1200", 0),
        (city.lower(), "youtube", "20001", 0),
        (city.lower(), "youtube", "20000", 1),
        (city.lower(), "youtube", "1200", 1),
    ):
        city_filter.select_option(city_value)
        platform.select_option(channel)
        minimum.fill(threshold)
        submit.click()
        expect(page.get_by_text(f"Найдено {count}", exact=True)).to_be_visible()
        expect(remove_ready).to_be_visible()

    instagram_minimum = form.get_by_label("Подписчики Instagram")
    instagram_minimum.select_option("10000")
    submit.click()
    expect(page.get_by_text("Найдено 0", exact=True)).to_be_visible()
    instagram_minimum.select_option("")
    platform.select_option("dzen")
    unknown = form.get_by_label("Число не указано")
    unknown.check()
    submit.click()
    expect(page.get_by_text("Найдено 1", exact=True)).to_be_visible()
    expect(remove_ready).to_be_visible()

    unknown.uncheck()
    platform.select_option("youtube")
    minimum.fill("1200")
    submit.click()
    remove_ready.click()
    expect(ready).to_be_visible()
    expect(city_filter).to_have_value(city.lower())
    expect(platform).to_have_value("youtube")
    expect(minimum).to_have_value("1200")
    expect(page.get_by_text("Найдено 2", exact=True)).to_be_visible()


@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("width", [320, 360, 768, 1024, 1152, 1440])
def test_platform_audience_sort_and_layout(
    admin_server, page, people_records, width
):
    from tests.e2e.test_admin_ui import _login

    _, city, instagram, _, active_name = people_records
    token = instagram.removeprefix("city_creator_")
    blocked_name = f"Ирина {token}"
    page.set_viewport_size({"width": width, "height": 900})
    _login(page, admin_server)
    page.goto(f"{admin_server}/admin/users/creators")
    form = page.locator(".people-filters")
    form.get_by_label("Поиск").fill(token)
    form.get_by_label("Город").select_option(city.lower())
    form.get_by_label("Есть ссылка на площадку").select_option("youtube")
    form.get_by_label("От N подписчиков").fill("1000")
    form.get_by_role("button", name="Найти").click()
    table = page.locator(".people-table")
    names = table.locator(".people-name")
    mobile_menu = page.locator(".people-mobile-sort")
    label = "Подписчики · YouTube"
    mobile = width <= 1088
    if mobile:
        expect(mobile_menu).to_be_visible()
        expect(table.locator("thead")).to_be_hidden()
        expect(table.locator("tbody tr").first).to_have_css("display", "grid")
    else:
        expect(mobile_menu).to_be_hidden()
        expect(table.locator("thead")).to_be_visible()

    def sort_audience():
        if mobile:
            mobile_menu.locator("summary").click()
            mobile_menu.get_by_role("link", name=label, exact=True).click()
        else:
            table.get_by_role("columnheader", name=label).get_by_role(
                "link"
            ).click()

    sort_audience()
    expect(names).to_have_text([active_name, blocked_name])
    audience = table.locator(".people-audience").nth(1)
    expect(audience).to_contain_text("1 200")
    expect(audience).to_contain_text("Со слов креатора")
    expect(audience).to_contain_text(re.compile(r"\d{2}\.\d{2}\.\d{4}"))

    sort_audience()
    expect(names).to_have_text([blocked_name, active_name])
    page.get_by_role("link", name="Креаторы с недоступным ботом").click()
    expect(names).to_have_text([blocked_name])
    expect(form.get_by_label("Поиск")).to_have_value(token)
    expect(form.get_by_label("Статус")).to_have_value("bot_blocked")
    expect(form.get_by_label("От N подписчиков")).to_have_value("1000")
    assert "sort=followers" in page.url and "order=asc" in page.url
    names.first.click()
    page.get_by_role("link", name="Назад к списку").click()
    expect(names).to_have_text([blocked_name])

    assert page.evaluate(
        "document.documentElement.scrollWidth === window.innerWidth"
    )
    container = page.locator(".people-scroll")
    assert container.evaluate(
        "(element) => element.scrollWidth <= element.clientWidth"
    )


@pytest.mark.e2e
@pytest.mark.timeout(60)
@pytest.mark.parametrize("width", [320, 768, 1440])
def test_dashboard_social_summary_links_and_layout(
    admin_server, page, people_records, width
):
    from tests.e2e.test_admin_ui import _login

    _, _, _, _, creator_name = people_records
    page.set_viewport_size({"width": width, "height": 900})
    _login(page, admin_server)
    page.goto(f"{admin_server}/admin/dashboard?period=today")
    section_ids = page.locator("main section[aria-labelledby]").evaluate_all(
        "(sections) => sections.map(section => "
        "section.getAttribute('aria-labelledby'))"
    )
    assert section_ids[:6] == [
        "attention-heading",
        "period-heading",
        "creators-heading",
        "charts-heading",
        "cohorts-heading",
        "creator-social-heading",
    ]
    goal = page.get_by_role("region", name="Цели дашборда")
    expect(goal.locator("xpath=following-sibling::*[1]")).to_have_attribute(
        "aria-labelledby", "attention-heading"
    )
    for name, target in (
        ("Завершили заказ", "1000"),
        ("Получили назначение", "1000"),
        ("Откликнулись на оффер", "1000"),
        ("Менеджеры", "100"),
    ):
        expect(goal.get_by_role("progressbar", name=name)).to_have_attribute(
            "aria-valuemax", target
        )
    layout = goal.evaluate(
        """(goal) => {
          const bounds = goal.getBoundingClientRect();
          const columns = getComputedStyle(goal).gridTemplateColumns;
          const parent = getComputedStyle(goal.parentElement);
          const padding = parseFloat(parent.paddingLeft)
            + parseFloat(parent.paddingRight);
          return {
            left: bounds.left, right: bounds.right, height: bounds.height,
            columns: columns.split(' ').length,
            overflow: goal.scrollWidth - goal.clientWidth,
            width: bounds.width,
            available: goal.parentElement.clientWidth - padding,
          };
        }"""
    )
    assert 0 <= layout["left"] < layout["right"] <= width, layout
    assert abs((layout["left"] + layout["right"]) / 2 - width / 2) < 24, layout
    assert abs(layout["width"] - layout["available"]) < 1, layout
    assert layout["columns"] == {320: 1, 768: 2, 1440: 4}[width], layout
    assert layout["height"] < (100 if width == 1440 else 200), layout
    assert layout["overflow"] <= 0, layout
    assert page.locator(".creator-funnel").evaluate(
        "funnel => funnel.scrollWidth <= funnel.clientWidth"
    )
    telegram = page.get_by_role("group", name="Telegram", exact=True)
    expect(telegram.get_by_role("link")).to_have_count(3)
    assert telegram.evaluate("group => group.scrollWidth <= group.clientWidth")
    summary = page.get_by_role("table", name="Соцсети креаторов")
    youtube = summary.get_by_role("row").filter(has_text="YouTube")
    expect(youtube.get_by_role("link")).to_have_text(["2", "2", "0"])
    assert summary.evaluate(
        "(table) => table.getBoundingClientRect().right <= window.innerWidth"
    )
    youtube.get_by_role("link", name="YouTube, подписчики указаны: 2").click()
    expect(page.get_by_label("Есть ссылка на площадку")).to_have_value(
        "youtube"
    )
    expect(page.get_by_label("От N подписчиков")).to_have_value("0")
    expect(
        page.get_by_role("link", name=creator_name, exact=True)
    ).to_be_visible()

    page.go_back()
    dzen = summary.get_by_role("row").filter(has_text="Дзен")
    dzen.get_by_role("link", name="Дзен, подписчики не указаны: 2").click()
    expect(page.get_by_label("Есть ссылка на площадку")).to_have_value("dzen")
    expect(page.get_by_label("Число не указано")).to_be_checked()
    expect(
        page.get_by_role("link", name=creator_name, exact=True)
    ).to_be_visible()


@pytest.mark.e2e
@pytest.mark.timeout(60)
def test_creator_base_opens_filtered_directory(
    admin_server, page, people_records
):
    from tests.e2e.test_admin_ui import _login

    _login(page, admin_server)
    page.goto(f"{admin_server}/admin/dashboard?period=7d")
    section = page.get_by_role("region", name="Состояние базы")
    expect(section).to_be_visible()

    def check_counts(links):
        for link in links.all():
            count = link.locator(".metric__value").inner_text()
            formatted = r"\s*".join(count)
            link.click()
            expect(page.locator(".people-count")).to_have_text(
                re.compile(rf"^Найдено {formatted}$")
            )
            page.go_back(wait_until="domcontentloaded")

    overview = section.locator(
        ":scope > .dashboard-metrics .creator-base-metric"
    )
    expect(overview).to_have_count(16)
    check_counts(overview)
    funnel = section.locator(".creator-funnel")
    expect(funnel.get_by_role("heading")).to_have_text(
        "Воронка регистрации · 7 дней"
    )
    check_counts(funnel.get_by_role("link"))
    activity = section.get_by_role("group", name="Все каналы").get_by_role(
        "link"
    )
    telegram = section.get_by_role(
        "group", name="Telegram", exact=True
    ).get_by_role("link")
    expect(activity).to_have_count(4)
    expect(telegram).to_have_count(3)
    periods = page.get_by_role("navigation", name="Период аналитики")
    for label, key in (
        ("Сегодня", "today"),
        ("Вчера", "yesterday"),
        ("7 дней", "7d"),
        ("30 дней", "30d"),
        ("Все", "all"),
    ):
        option = periods.get_by_role("link", name=label, exact=True)
        option.click()
        expect(option).to_have_attribute("aria-current", "page")
        expect(
            section.get_by_role("heading", name=f"Участие в заказах · {label}")
        ).to_be_visible()
        expect(activity.first).to_have_attribute(
            "href", re.compile(f"work_period={key}$")
        )
        for link in telegram.all():
            expect(link).to_have_attribute(
                "href", re.compile(f"work_period={key}$")
            )
        check_counts(activity.first)
        check_counts(telegram)

    periods.get_by_role("link", name="Вчера", exact=True).click()
    expect(
        section.get_by_role("link", name=re.compile("только в MAX за период"))
    ).to_have_count(0)
    section.get_by_text("Охват MAX", exact=True).click()
    max_only = section.get_by_role(
        "link", name=re.compile("только в MAX за период")
    )
    count = max_only.locator(".metric__value").inner_text()
    max_only.click()
    expect(page.locator(".people-count")).to_have_text(f"Найдено {count}")
    expect(page.locator('input[name="work_period"]')).to_have_value("yesterday")
    page.go_back(wait_until="domcontentloaded")

    section.get_by_role(
        "link", name=re.compile("^Получили предложение [0-9]")
    ).click()
    expect(
        page.get_by_role("link", name="Получили предложение · Вчера")
    ).to_have_attribute("href", re.compile(r"period=yesterday#creator-base$"))
    page.locator("#people-query").fill("не существует")
    page.locator(".people-filters").get_by_role("button", name="Найти").click()
    expect(page.locator('input[name="work_period"]')).to_have_value("yesterday")
    expect(page.locator(".people-count")).to_contain_text("Найдено 0")
    page.get_by_role("link", name="Сбросить").click()
    expect(page.locator('input[name="base_segment"]')).to_have_count(0)
