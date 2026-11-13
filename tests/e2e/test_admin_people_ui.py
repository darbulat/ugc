"""Authenticated directory and profile flows on an isolated PostGIS database."""

import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from playwright.sync_api import expect
from sqlalchemy import create_engine, delete
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import require_test_database
from ugc_bot.domain.enums import (
    AudienceGender,
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    RaterRole,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    BloggerRatingModel,
    ComplaintModel,
    InteractionModel,
    NpsResponseModel,
    OfferDispatchModel,
    OrderModel,
    UserModel,
)


@pytest.fixture
def people_records():
    database = os.environ.get("FINANCIAL_TEST_DATABASE_URL")
    if not database or not os.environ.get("E2E_BASE_URL"):
        pytest.skip("Requires a synthetic admin server with PostGIS")
    engine = create_engine(require_test_database(database))
    customer_id, creator_id, other_id, order_id = [uuid4() for _ in range(4)]
    now = datetime.now(timezone.utc)
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
            messenger_type=MessengerType.TELEGRAM,
            status=UserStatus.ACTIVE,
        )
        for user_id, name, handle in [
            (customer_id, f"Анна {token}", f"anna_{token}"),
            (creator_id, creator_name, f"maria_{token}"),
            (other_id, f"Ирина {token}", None),
        ]
    ]
    with Session(engine) as session, session.begin():
        session.add_all(users)
        session.flush()
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
        ]:
            session.add(
                BloggerProfileModel(
                    user_id=user_id,
                    instagram_url=f"https://instagram.com/{handle}",
                    city=f" {city.lower()} " if user_id == creator_id else city,
                    topics={"beauty": True},
                    audience_gender=AudienceGender.ALL,
                    audience_age_min=18,
                    audience_age_max=35,
                    audience_geo="RU",
                    price=2000,
                    instagram_followers_count=followers,
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
    try:
        yield brand, city, instagram, order_title, creator_name
    finally:
        with engine.begin() as db:
            db.execute(
                delete(OrderModel).where(OrderModel.order_id == order_id)
            )
            db.execute(
                delete(UserModel).where(
                    UserModel.user_id.in_([customer_id, creator_id, other_id])
                )
            )
        engine.dispose()


@pytest.mark.e2e
@pytest.mark.timeout(60)
def test_directory_filters_and_profile_history(
    admin_server, base_url, page, people_records
):
    from tests.e2e.test_admin_ui import _login

    brand, city, instagram, order_title, creator_name = people_records
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
