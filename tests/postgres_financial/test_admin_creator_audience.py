"""Exercise the social summary and creator filters against recorded counts."""

import re
from datetime import datetime, timezone
from html import unescape
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from ugc_bot.admin.app import create_admin_app
from ugc_bot.admin.auth import AdminAuth
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.domain.social import SELF_REPORTED_FOLLOWERS
from ugc_bot.infrastructure.db.models import BloggerProfileModel, UserModel
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


@pytest.fixture(scope="module")
def creator_audience_entries(financial_pg_engine):
    entries = (
        ("Creator Reported", UserStatus.BOT_BLOCKED, 1250, 80),
        ("Creator Zero", UserStatus.BOT_BLOCKED, 0, 2000),
        ("Creator Unknown", UserStatus.BOT_BLOCKED, None, None),
        ("Creator No Link", UserStatus.BOT_BLOCKED, None, -1),
        ("Creator Active", UserStatus.ACTIVE, 5000, 5000),
        ("Unrelated", UserStatus.BOT_BLOCKED, 5000, 5000),
    )
    recorded = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    registered = datetime(2024, 1, 1, tzinfo=timezone.utc)
    with Session(financial_pg_engine) as db, db.begin():
        for name, status, _, _ in entries:
            db.add(
                UserModel(
                    username=name,
                    messenger_type=MessengerType.TELEGRAM,
                    status=status,
                    created_at=registered,
                )
            )
        users = {user.username: user for user in db.new}
        db.flush()
        for idx, (name, _, youtube, instagram) in enumerate(entries):
            handle = "unrelated" if name == "Unrelated" else f"creator_{idx}"
            uid = users[name].user_id
            db.add(
                BloggerProfileModel(
                    user_id=uid,
                    instagram_url=f"https://instagram.com/{handle}",
                    instagram_followers_count=instagram,
                    instagram_stats_fetched_at=recorded
                    if instagram is not None
                    else None,
                    city="Test City",
                    topics={},
                    audience_gender=AudienceGender.ALL,
                    audience_age_min=18,
                    audience_age_max=65,
                    audience_geo="Test",
                    price=1,
                )
            )
            if name != "Creator No Link":
                db.add(
                    SocialAccountModel(
                        account_id=uuid4(),
                        user_id=uid,
                        platform="youtube",
                        url=f"https://youtube.com/@creator_{idx}",
                        handle=f"creator_{idx}",
                        work_format=WorkFormat.UGC_ONLY,
                        followers_count=youtube,
                        metrics_source=SELF_REPORTED_FOLLOWERS
                        if youtube is not None
                        else None,
                        metrics_fetched_at=recorded
                        if youtube is not None
                        else None,
                        created_at=registered,
                        updated_at=registered,
                    )
                )
        advertiser = UserModel(
            username="No Creator Profile",
            messenger_type=MessengerType.TELEGRAM,
            status=UserStatus.ACTIVE,
        )
        db.add(advertiser)
        db.flush()
        for user_id, platform, url in (
            (advertiser.user_id, "youtube", "https://youtube.com/@non_creator"),
            (users["Creator No Link"].user_id, "youtube", "   "),
            (
                users["Creator Reported"].user_id,
                "instagram",
                "https://instagram.com/creator_0",
            ),
            (users["Creator Active"].user_id, "dzen", "https://dzen.ru/active"),
        ):
            db.add(
                SocialAccountModel(
                    account_id=uuid4(),
                    user_id=user_id,
                    platform=platform,
                    url=url,
                    handle="test",
                    work_format=WorkFormat.UGC_ONLY,
                    created_at=registered,
                    updated_at=registered,
                )
            )
    return entries


@pytest.fixture
def creator_audience_app(
    financial_pg_engine, creator_audience_entries, monkeypatch
):
    env = {
        "BOT_TOKEN": "test-token",
        "ADMIN_USERNAME": "test_admin",
        "ADMIN_PASSWORD": "test-admin-password",
        "ADMIN_SECRET": "test-admin-session-secret",
        "ADMIN_DASHBOARD_TIMEZONE": "Europe/Moscow",
        "DATABASE_URL": financial_pg_engine.url.render_as_string(
            hide_password=False
        ),
        "REDIS_URL": "",
        "USE_REDIS_STORAGE": "false",
        "KAFKA_ENABLED": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(AdminAuth, "authenticate", AsyncMock(return_value=True))

    return create_admin_app()


def test_creator_filters_distinguish_unknown_zero_and_missing_link(
    creator_audience_app, creator_audience_entries
):
    entries = creator_audience_entries

    with TestClient(creator_audience_app) as client:

        def matches(expected, *, total=None, **params):
            response = client.get(
                "/admin/users/creators",
                params={"q": "Creator", "status": "bot_blocked", **params},
            )
            assert response.status_code == 200
            assert (
                f"Найдено {len(expected) if total is None else total}</span>"
                in response.text
            )
            assert {
                name for name, *_ in entries if f">{name}</a>" in response.text
            } == expected

            return response.text

        reported = matches(
            {"Creator Reported"},
            platform="youtube",
            platform_followers_min=1250,
        )
        assert "Подписчики · YouTube" in reported
        assert "1 250" in reported and "Со слов креатора" in reported
        assert "14.11.2026, 15:00" in reported
        matches(set(), platform="youtube", platform_followers_min=1251)
        matches(
            {"Creator Reported", "Creator Zero"},
            platform="youtube",
            platform_followers_min=0,
        )
        matches(
            {"Creator Unknown"},
            platform="youtube",
            platform_followers_unknown="true",
        )
        matches(
            {"Creator Unknown", "Creator No Link"},
            platform="instagram",
            platform_followers_unknown="true",
        )
        matches(
            {"Creator Zero"}, platform="instagram", platform_followers_min=2000
        )
        matches(
            {
                "Creator Reported",
                "Creator Zero",
                "Creator Unknown",
                "Creator No Link",
            },
            platform_followers_unknown="true",
        )

        # The YouTube order is the reverse of the Instagram order. Check that
        # PostgreSQL applies it before pagination and leaves unknowns last.
        filters = {"platform": "youtube", "sort": "followers", "per_page": 1}
        for page, name in enumerate(
            ("Creator Reported", "Creator Zero", "Creator Unknown"), 1
        ):
            matches({name}, total=3, page=page, order="desc", **filters)
        matches({"Creator Zero"}, total=3, order="asc", **filters)
        unknown = matches(
            {"Creator Unknown"}, total=3, order="asc", page=3, **filters
        )
        assert "Не указано" in unknown and "Со слов креатора" not in unknown

        instagram = matches(
            {"Creator Zero"},
            platform="instagram",
            sort="followers",
            order="desc",
            per_page=1,
            total=4,
        )
        assert "14.11.2026, 15:00" in instagram
        assert "Со слов креатора" not in instagram


def test_dashboard_social_counts_link_to_matching_creators(
    creator_audience_app, creator_audience_entries
):
    with TestClient(creator_audience_app) as client:
        response = client.get("/admin/dashboard?period=today")
        assert response.status_code == 200
        assert "Соцсети креаторов" in response.text

        all_names = {name for name, *_ in creator_audience_entries}
        cases = (
            ("YouTube", "есть ссылка", all_names - {"Creator No Link"}),
            (
                "YouTube",
                "подписчики указаны",
                all_names - {"Creator No Link", "Creator Unknown"},
            ),
            ("YouTube", "подписчики не указаны", {"Creator Unknown"}),
            ("Instagram", "есть ссылка", all_names),
            (
                "Instagram",
                "подписчики указаны",
                all_names - {"Creator No Link", "Creator Unknown"},
            ),
            (
                "Instagram",
                "подписчики не указаны",
                {"Creator No Link", "Creator Unknown"},
            ),
            ("Дзен", "есть ссылка", {"Creator Active"}),
            ("TikTok", "есть ссылка", set()),
        )
        for label, metric, expected in cases:
            link_name = f"{label}, {metric}: {len(expected)}"
            link = re.search(
                rf'<a href="([^"]+)" aria-label="{re.escape(link_name)}">'
                rf"{len(expected)}</a>",
                response.text,
            )
            assert link is not None, link_name
            directory = client.get(unescape(link[1]))
            assert directory.status_code == 200
            assert f"Найдено {len(expected)}</span>" in directory.text
            assert {
                name for name in all_names if f">{name}</a>" in directory.text
            } == expected
