"""Exercise creator filters through the admin route against recorded counts."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

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


def test_creator_filters_distinguish_unknown_zero_and_missing_link(
    financial_pg_engine, monkeypatch
):
    entries = (
        ("Creator Reported", UserStatus.BOT_BLOCKED, 1250, 80),
        ("Creator Zero", UserStatus.BOT_BLOCKED, 0, 2000),
        ("Creator Unknown", UserStatus.BOT_BLOCKED, None, None),
        ("Creator No Link", UserStatus.BOT_BLOCKED, None, None),
        ("Creator Active", UserStatus.ACTIVE, 5000, 5000),
        ("Unrelated", UserStatus.BOT_BLOCKED, 5000, 5000),
    )
    now = datetime.now(timezone.utc)
    recorded = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    with Session(financial_pg_engine) as db, db.begin():
        for name, status, _, _ in entries:
            db.add(
                UserModel(
                    username=name,
                    messenger_type=MessengerType.TELEGRAM,
                    status=status,
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
                        created_at=now,
                        updated_at=now,
                    )
                )

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

    with TestClient(create_admin_app()) as client:

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
