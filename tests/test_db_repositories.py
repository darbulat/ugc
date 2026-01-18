"""Tests for SQLAlchemy repositories with fake sessions."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    InstagramVerificationCode,
    User,
)
from ugc_bot.domain.enums import AudienceGender, MessengerType, UserRole, UserStatus
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    InstagramVerificationCodeModel,
    UserModel,
)


class FakeResult:
    """Fake SQLAlchemy result."""

    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return self._value


class FakeSession:
    """Fake session supporting context manager."""

    def __init__(self, result) -> None:
        self._result = result
        self.merged = None
        self.committed = False

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
        return False

    def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return FakeResult(self._result)

    def get(self, _model, _key):  # type: ignore[no-untyped-def]
        return self._result

    def merge(self, model):  # type: ignore[no-untyped-def]
        self.merged = model

    def commit(self):  # type: ignore[no-untyped-def]
        self.committed = True


def _session_factory(result):
    """Create a fake session factory."""

    def factory():  # type: ignore[no-untyped-def]
        return FakeSession(result)

    return factory


def test_user_repository_get_by_external() -> None:
    """Fetch user by external id."""

    model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000111"),
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyUserRepository(session_factory=_session_factory(model))

    user = repo.get_by_external("123", MessengerType.TELEGRAM)
    assert user is not None
    assert user.external_id == "123"


def test_user_repository_get_by_id() -> None:
    """Fetch user by id."""

    model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000115"),
        external_id="321",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        role=UserRole.BLOGGER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyUserRepository(session_factory=_session_factory(model))

    user = repo.get_by_id(model.user_id)
    assert user is not None
    assert user.user_id == model.user_id


def test_user_repository_save() -> None:
    """Save user via repository."""

    session = FakeSession(None)

    def factory():  # type: ignore[no-untyped-def]
        return session

    repo = SqlAlchemyUserRepository(session_factory=factory)
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000112"),
        external_id="555",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        role=UserRole.ADVERTISER,
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )

    repo.save(user)
    assert session.merged is not None
    assert session.committed is True


def test_blogger_profile_repository_save() -> None:
    """Save blogger profile via repository."""

    session = FakeSession(None)

    def factory():  # type: ignore[no-untyped-def]
        return session

    repo = SqlAlchemyBloggerProfileRepository(session_factory=factory)
    profile = BloggerProfile(
        user_id=UUID("00000000-0000-0000-0000-000000000113"),
        instagram_url="https://instagram.com/test",
        confirmed=False,
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        updated_at=datetime.now(timezone.utc),
    )

    repo.save(profile)
    assert session.merged is not None
    assert session.committed is True


def test_blogger_profile_repository_get() -> None:
    """Fetch blogger profile by user id."""

    model = BloggerProfileModel(
        user_id=UUID("00000000-0000-0000-0000-000000000114"),
        instagram_url="https://instagram.com/test",
        confirmed=False,
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyBloggerProfileRepository(session_factory=_session_factory(model))

    profile = repo.get_by_user_id(model.user_id)
    assert profile is not None
    assert profile.instagram_url.endswith("test")


def test_advertiser_profile_repository_save_and_get() -> None:
    """Save and fetch advertiser profile."""

    session = FakeSession(None)

    def factory():  # type: ignore[no-untyped-def]
        return session

    repo = SqlAlchemyAdvertiserProfileRepository(session_factory=factory)
    profile = AdvertiserProfile(
        user_id=UUID("00000000-0000-0000-0000-000000000116"),
        contact="@contact",
    )
    repo.save(profile)
    assert session.merged is not None
    assert session.committed is True

    repo_get = SqlAlchemyAdvertiserProfileRepository(
        session_factory=_session_factory(
            AdvertiserProfileModel(
                user_id=profile.user_id,
                contact=profile.contact,
            )
        )
    )
    fetched = repo_get.get_by_user_id(profile.user_id)
    assert fetched is not None
    assert fetched.contact == "@contact"


def test_instagram_verification_repository_save_and_get() -> None:
    """Save and fetch verification code."""

    session = FakeSession(None)

    def factory():  # type: ignore[no-untyped-def]
        return session

    repo = SqlAlchemyInstagramVerificationRepository(session_factory=factory)
    code = InstagramVerificationCode(
        code_id=UUID("00000000-0000-0000-0000-000000000117"),
        user_id=UUID("00000000-0000-0000-0000-000000000118"),
        code="ABC123",
        expires_at=datetime.now(timezone.utc),
        used=False,
        created_at=datetime.now(timezone.utc),
    )
    repo.save(code)
    assert session.merged is not None
    assert session.committed is True

    model = InstagramVerificationCodeModel(
        code_id=code.code_id,
        user_id=code.user_id,
        code=code.code,
        expires_at=code.expires_at + timedelta(minutes=5),
        used=False,
        created_at=code.created_at,
    )
    repo_get = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(model)
    )
    fetched = repo_get.get_valid_code(code.user_id, code.code)
    assert fetched is not None


def test_instagram_verification_repository_get_invalid() -> None:
    """Return None for used or expired codes."""

    expired_model = InstagramVerificationCodeModel(
        code_id=UUID("00000000-0000-0000-0000-000000000140"),
        user_id=UUID("00000000-0000-0000-0000-000000000141"),
        code="OLD123",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        used=False,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(expired_model)
    )
    assert repo.get_valid_code(expired_model.user_id, expired_model.code) is None

    used_model = InstagramVerificationCodeModel(
        code_id=UUID("00000000-0000-0000-0000-000000000142"),
        user_id=UUID("00000000-0000-0000-0000-000000000143"),
        code="USED123",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        used=True,
        created_at=datetime.now(timezone.utc),
    )
    repo_used = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(used_model)
    )
    assert repo_used.get_valid_code(used_model.user_id, used_model.code) is None


def test_instagram_verification_repository_mark_used() -> None:
    """Mark verification code as used."""

    model = InstagramVerificationCodeModel(
        code_id=UUID("00000000-0000-0000-0000-000000000119"),
        user_id=UUID("00000000-0000-0000-0000-000000000120"),
        code="ABC999",
        expires_at=datetime.now(timezone.utc),
        used=False,
        created_at=datetime.now(timezone.utc),
    )
    session = FakeSession(model)

    def factory():  # type: ignore[no-untyped-def]
        return session

    repo = SqlAlchemyInstagramVerificationRepository(session_factory=factory)
    repo.mark_used(model.code_id)
    assert model.used is True
