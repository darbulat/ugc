"""Tests for SQLAlchemy repositories with fake sessions."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import pytest

from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    Complaint,
    InstagramStats,
    InstagramVerificationCode,
    Interaction,
    Order,
    OutboxEvent,
    Payment,
    PayoutRequest,
    ReferralIncomeEntry,
    User,
    UserReferralBinding,
    UserReferralPending,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    BloggerGender,
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    OutboxEventStatus,
    PaymentStatus,
    PayoutRequestStatus,
    ReferralIncomeType,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ComplaintModel,
    ContactPricingModel,
    InstagramStatsModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    OfferDispatchModel,
    OrderModel,
    OutboxEventModel,
    PaymentModel,
    PayoutRequestModel,
    UserModel,
    UserReferralBindingModel,
    UserReferralPendingModel,
)
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyComplaintRepository,
    SqlAlchemyContactPricingRepository,
    SqlAlchemyInstagramStatsRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyNpsRepository,
    SqlAlchemyOfferDispatchRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyPayoutRequestRepository,
    SqlAlchemyReferralIncomeEntryRepository,
    SqlAlchemyUserReferralBindingRepository,
    SqlAlchemyUserReferralPendingRepository,
    SqlAlchemyUserRepository,
    _geometry_to_wkt,
    _wkt_to_geometry_element,
)


class FakeScalarResult:
    """Fake ScalarResult with all() and iteration for list queries."""

    def __init__(self, value) -> None:
        self._value = value

    def all(self):  # type: ignore[no-untyped-def]
        if self._value is None:
            return []
        if isinstance(self._value, list):
            return self._value
        return [self._value]

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self.all())


class FakeResult:
    """Fake SQLAlchemy result."""

    def __init__(self, value, rowcount: int | None = None) -> None:
        self._value = value
        self.rowcount = rowcount

    def all(self):  # type: ignore[no-untyped-def]
        """Return all rows (e.g. for multi-column select)."""
        if self._value is None:
            return []
        if isinstance(self._value, list):
            return self._value
        return [self._value]

    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return self._value

    def scalar_one(self):  # type: ignore[no-untyped-def]
        return self._value

    def scalar(self):  # type: ignore[no-untyped-def]
        """Return first column of first row (e.g. for count queries)."""
        if isinstance(self._value, list) and self._value:
            return self._value[0]
        return self._value

    def scalars(self):  # type: ignore[no-untyped-def]
        return FakeScalarResult(self._value)


class FakeSession:
    """Fake session supporting async context manager."""

    def __init__(self, result) -> None:
        self._result = result
        self.merged = None
        self.committed = False
        self.deleted = None

    async def __aenter__(self):  # type: ignore[no-untyped-def]
        return self

    async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
        return False

    async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
        return FakeResult(self._result)

    async def get(self, _model, _key):  # type: ignore[no-untyped-def]
        return self._result

    def query(self, model):  # type: ignore[no-untyped-def]
        """Mock query method for outbox repository."""

        class MockQuery:
            def __init__(self, result):
                self._result = result

            def filter(self, *args, **kwargs):
                return self

            def first(self):
                return self._result

            def update(self, *args, **kwargs):
                if hasattr(self._result, "__dict__"):
                    for key, value in kwargs.items():
                        setattr(self._result, key, value)
                return self

        return MockQuery(self._result)

    def add(self, obj):  # type: ignore[no-untyped-def]
        """Mock add method."""
        pass

    async def commit(self):  # type: ignore[no-untyped-def]
        """Mock commit method."""
        self.committed = True

    async def rollback(self):  # type: ignore[no-untyped-def]
        """Mock rollback method."""
        pass

    async def close(self):  # type: ignore[no-untyped-def]
        """Mock close method."""
        pass

    async def merge(self, model):  # type: ignore[no-untyped-def]
        self.merged = model

    async def delete(self, model):  # type: ignore[no-untyped-def]
        """Mock delete."""
        self.deleted = model


def _session_factory(result):
    """Create a fake async session factory."""

    class FakeAsyncSessionMaker:
        def __init__(self, result):
            self._result = result

        def __call__(self):
            return FakeSession(self._result)

    return FakeAsyncSessionMaker(result)


def _repo_session(repo):  # type: ignore[no-untyped-def]
    """Create a fake session for a repository call."""

    return repo.session_factory()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_user_repository_get_by_external() -> None:
    """Fetch user by external id."""

    model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000111"),
        external_id="123",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyUserRepository(session_factory=_session_factory(model))

    user = await repo.get_by_external(
        "123", MessengerType.TELEGRAM, session=_repo_session(repo)
    )
    assert user is not None
    assert user.external_id == "123"


@pytest.mark.asyncio
async def test_user_repository_get_by_id() -> None:
    """Fetch user by id."""

    model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000115"),
        external_id="321",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyUserRepository(session_factory=_session_factory(model))

    user = await repo.get_by_id(model.user_id, session=_repo_session(repo))
    assert user is not None
    assert user.user_id == model.user_id


@pytest.mark.asyncio
async def test_user_repository_get_by_ids() -> None:
    """Fetch users by ids (batch)."""
    model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000116"),
        external_id="get_by_ids",
        messenger_type=MessengerType.TELEGRAM,
        username="bob",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyUserRepository(session_factory=_session_factory([model]))
    users = await repo.get_by_ids([model.user_id], session=_repo_session(repo))
    assert model.user_id in users
    assert users[model.user_id].username == "bob"
    empty = await repo.get_by_ids([], session=_repo_session(repo))
    assert empty == {}


@pytest.mark.asyncio
async def test_user_repository_save() -> None:
    """Save user via repository."""

    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyUserRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000112"),
        external_id="555",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )

    await repo.save(user, session=session)
    assert session.merged is not None
    assert session.committed is False


@pytest.mark.asyncio
async def test_blogger_profile_repository_save() -> None:
    """Save blogger profile via repository."""

    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyBloggerProfileRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    profile = BloggerProfile(
        user_id=UUID("00000000-0000-0000-0000-000000000113"),
        instagram_url="https://instagram.com/test",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )

    await repo.save(profile, session=session)
    assert session.merged is not None
    assert session.committed is False


@pytest.mark.asyncio
async def test_blogger_profile_repository_get_by_instagram_url() -> None:
    """Fetch blogger profile by Instagram URL."""

    model = BloggerProfileModel(
        user_id=UUID("00000000-0000-0000-0000-000000000200"),
        instagram_url="https://instagram.com/test_user",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )

    repo = SqlAlchemyBloggerProfileRepository(
        session_factory=_session_factory(model)
    )
    profile = await repo.get_by_instagram_url(
        "https://instagram.com/test_user", session=_repo_session(repo)
    )

    assert profile is not None
    assert profile.instagram_url == "https://instagram.com/test_user"
    assert profile.user_id == UUID("00000000-0000-0000-0000-000000000200")


@pytest.mark.asyncio
async def test_blogger_profile_repository_get_by_instagram_url_not_found() -> (
    None
):
    """Return None when Instagram URL not found."""

    repo = SqlAlchemyBloggerProfileRepository(
        session_factory=_session_factory(None)
    )
    profile = await repo.get_by_instagram_url(
        "https://instagram.com/nonexistent", session=_repo_session(repo)
    )

    assert profile is None


@pytest.mark.asyncio
async def test_blogger_profile_repository_get() -> None:
    """Fetch blogger profile by user id."""

    model = BloggerProfileModel(
        user_id=UUID("00000000-0000-0000-0000-000000000114"),
        instagram_url="https://instagram.com/test",
        confirmed=False,
        city="Moscow",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyBloggerProfileRepository(
        session_factory=_session_factory(model)
    )

    profile = await repo.get_by_user_id(
        model.user_id, session=_repo_session(repo)
    )
    assert profile is not None
    assert profile.instagram_url.endswith("test")


@pytest.mark.asyncio
async def test_blogger_profile_repository_get_with_string_blogger_gender() -> (
    None
):
    """get_by_user_id maps blogger_gender string to enum (e.g. from SQLite)."""
    user_id = UUID("00000000-0000-0000-0000-000000000115")
    updated_at = datetime.now(timezone.utc)
    model = SimpleNamespace(
        user_id=user_id,
        instagram_url="https://instagram.com/g",
        confirmed=True,
        city="Moscow",
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=updated_at,
        blogger_gender="m",  # DB stores enum value
    )
    repo = SqlAlchemyBloggerProfileRepository(
        session_factory=_session_factory(model)
    )
    profile = await repo.get_by_user_id(user_id, session=_repo_session(repo))
    assert profile is not None
    assert profile.blogger_gender == BloggerGender.MALE


@pytest.mark.asyncio
async def test_advertiser_profile_repository_save_and_get() -> None:
    """Save and fetch advertiser profile."""

    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyAdvertiserProfileRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    profile = AdvertiserProfile(
        user_id=UUID("00000000-0000-0000-0000-000000000116"),
        phone="@contact",
        brand="Brand",
    )
    await repo.save(profile, session=session)
    assert session.merged is not None
    assert session.committed is False

    repo_get = SqlAlchemyAdvertiserProfileRepository(
        session_factory=_session_factory(
            AdvertiserProfileModel(
                user_id=profile.user_id,
                contact=profile.phone,
                brand=profile.brand,
            )
        )
    )
    fetched = await repo_get.get_by_user_id(
        profile.user_id, session=_repo_session(repo_get)
    )
    assert fetched is not None
    assert fetched.phone == "@contact"
    assert fetched.brand == "Brand"


@pytest.mark.asyncio
async def test_instagram_verification_repository_save_and_get() -> None:
    """Save and fetch verification code."""

    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    code = InstagramVerificationCode(
        code_id=UUID("00000000-0000-0000-0000-000000000117"),
        user_id=UUID("00000000-0000-0000-0000-000000000118"),
        code="ABC123",
        expires_at=datetime.now(timezone.utc),
        used=False,
        created_at=datetime.now(timezone.utc),
    )
    await repo.save(code, session=session)
    assert session.merged is not None
    assert session.committed is False

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
    fetched = await repo_get.get_valid_code(
        code.user_id, code.code, session=_repo_session(repo_get)
    )
    assert fetched is not None


@pytest.mark.asyncio
async def test_instagram_verification_repository_get_invalid() -> None:
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
    assert (
        await repo.get_valid_code(
            expired_model.user_id,
            expired_model.code,
            session=_repo_session(repo),
        )
        is None
    )

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
    assert (
        await repo_used.get_valid_code(
            used_model.user_id,
            used_model.code,
            session=_repo_session(repo_used),
        )
        is None
    )


@pytest.mark.asyncio
async def test_instagram_verification_repository_mark_used() -> None:
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

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    await repo.mark_used(model.code_id, session=session)
    assert model.used is True


@pytest.mark.asyncio
async def test_instagram_verification_repository_get_valid_code_by_code() -> (
    None
):
    """Test getting valid code by code string."""
    user_id = UUID("00000000-0000-0000-0000-000000000144")
    valid_model = InstagramVerificationCodeModel(
        code_id=UUID("00000000-0000-0000-0000-000000000145"),
        user_id=user_id,
        code="TESTCODE",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        used=False,
        created_at=datetime.now(timezone.utc),
    )

    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(valid_model)
    )

    # Test getting valid code
    fetched = await repo.get_valid_code_by_code(
        "TESTCODE", session=_repo_session(repo)
    )
    assert fetched is not None
    assert fetched.code == "TESTCODE"
    assert fetched.user_id == user_id

    # Test case insensitive
    fetched_lower = await repo.get_valid_code_by_code(
        "testcode", session=_repo_session(repo)
    )
    assert fetched_lower is not None
    assert fetched_lower.code == "TESTCODE"


@pytest.mark.asyncio
async def test_instagram_verification_repo_get_valid_code_not_found() -> None:
    """Test getting non-existent code returns None."""
    # Use None to simulate code not found
    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(None)
    )

    invalid = await repo.get_valid_code_by_code(
        "INVALID", session=_repo_session(repo)
    )
    assert invalid is None


@pytest.mark.asyncio
async def test_instagram_verification_repo_get_valid_code_expired() -> None:
    """Test getting expired code by code string returns None."""
    expired_model = InstagramVerificationCodeModel(
        code_id=UUID("00000000-0000-0000-0000-000000000146"),
        user_id=UUID("00000000-0000-0000-0000-000000000147"),
        code="EXPIRED",
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        used=False,
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(expired_model)
    )

    expired_fetched = await repo.get_valid_code_by_code(
        "EXPIRED", session=_repo_session(repo)
    )
    assert expired_fetched is None


@pytest.mark.asyncio
async def test_instagram_verification_repo_get_valid_code_used() -> None:
    """Test getting used code by code string returns None."""
    used_model = InstagramVerificationCodeModel(
        code_id=UUID("00000000-0000-0000-0000-000000000148"),
        user_id=UUID("00000000-0000-0000-0000-000000000149"),
        code="USEDCODE",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        used=True,
        created_at=datetime.now(timezone.utc),
    )

    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(used_model)
    )

    used_fetched = await repo.get_valid_code_by_code(
        "USEDCODE", session=_repo_session(repo)
    )
    assert used_fetched is None


@pytest.mark.asyncio
async def test_instagram_get_valid_code_none_when_no_result() -> None:
    """get_valid_code returns None when execute returns no row."""
    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(None)
    )
    out = await repo.get_valid_code(
        UUID("00000000-0000-0000-0000-000000000152"),
        "nocode",
        session=_repo_session(repo),
    )
    assert out is None


@pytest.mark.asyncio
async def test_instagram_get_valid_code_used_returns_none() -> None:
    """get_valid_code(user_id, code) returns None when code is used."""
    used_model = InstagramVerificationCodeModel(
        code_id=UUID("00000000-0000-0000-0000-000000000150"),
        user_id=UUID("00000000-0000-0000-0000-000000000151"),
        code="USED",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        used=True,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(used_model)
    )
    out = await repo.get_valid_code(
        used_model.user_id,
        used_model.code,
        session=_repo_session(repo),
    )
    assert out is None


@pytest.mark.asyncio
async def test_order_repository_save_and_get() -> None:
    """Save and fetch order."""

    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyOrderRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000170"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000171"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    await repo.save(order, session=session)
    assert session.merged is not None
    assert session.committed is False

    model = OrderModel(
        order_id=order.order_id,
        advertiser_id=order.advertiser_id,
        product_link=order.product_link,
        offer_text=order.offer_text,
        barter_description=None,
        price=order.price,
        bloggers_needed=order.bloggers_needed,
        status=order.status,
        created_at=order.created_at,
        completed_at=None,
    )
    repo_get = SqlAlchemyOrderRepository(
        session_factory=_session_factory(model)
    )
    fetched = await repo_get.get_by_id(
        order.order_id, session=_repo_session(repo_get)
    )
    assert fetched is not None


@pytest.mark.asyncio
async def test_user_repository_list_pending_role_reminders() -> None:
    """List users pending role reminder."""

    user_model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000160"),
        external_id="160",
        messenger_type=MessengerType.TELEGRAM,
        username="alice",
        status=UserStatus.ACTIVE,
        issue_count=0,
        role_chosen_at=None,
        last_role_reminder_at=None,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyUserRepository(
        session_factory=_session_factory([user_model])
    )
    cutoff = datetime.now(timezone.utc)
    users = list(
        await repo.list_pending_role_reminders(
            cutoff, session=_repo_session(repo)
        )
    )
    assert len(users) == 1
    assert users[0].username == "alice"


@pytest.mark.asyncio
async def test_user_repository_list_admins() -> None:
    """List admin users."""

    admin_model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000161"),
        external_id="161",
        messenger_type=MessengerType.TELEGRAM,
        username="admin_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    admin_model.admin = True
    repo = SqlAlchemyUserRepository(
        session_factory=_session_factory([admin_model])
    )
    admins = list(await repo.list_admins(session=_repo_session(repo)))
    assert len(admins) == 1
    assert admins[0].username == "admin_user"


@pytest.mark.asyncio
async def test_user_repository_list_admins_with_messenger_type() -> None:
    """List admin users filtered by messenger type."""

    admin_model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000162"),
        external_id="162",
        messenger_type=MessengerType.TELEGRAM,
        username="tg_admin",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    admin_model.admin = True
    repo = SqlAlchemyUserRepository(
        session_factory=_session_factory([admin_model])
    )
    admins = list(
        await repo.list_admins(
            messenger_type=MessengerType.TELEGRAM, session=_repo_session(repo)
        )
    )
    assert len(admins) == 1
    assert admins[0].username == "tg_admin"


@pytest.mark.asyncio
async def test_order_repository_list_active() -> None:
    """List active orders."""

    order_model = OrderModel(
        order_id=UUID("00000000-0000-0000-0000-000000000174"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000175"),
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    repo = SqlAlchemyOrderRepository(
        session_factory=_session_factory([order_model])
    )
    orders = list(await repo.list_active(session=_repo_session(repo)))
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.ACTIVE


@pytest.mark.asyncio
async def test_order_repository_get_by_id_for_update() -> None:
    """Fetch order by id for update (with row lock)."""

    order_model = OrderModel(
        order_id=UUID("00000000-0000-0000-0000-000000000176"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000177"),
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    session = FakeSession(order_model)

    class FakeSessionMaker:
        def __call__(self):
            return session

    repo = SqlAlchemyOrderRepository(session_factory=FakeSessionMaker())
    order = await repo.get_by_id_for_update(
        order_model.order_id, session=session
    )
    assert order is not None
    assert order.order_id == order_model.order_id


@pytest.mark.asyncio
async def test_order_repository_list_completed_before() -> None:
    """List orders completed before cutoff."""

    cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
    order_model = OrderModel(
        order_id=UUID("00000000-0000-0000-0000-000000000178"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000179"),
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        completed_at=datetime(2025, 5, 15, tzinfo=timezone.utc),
    )
    repo = SqlAlchemyOrderRepository(
        session_factory=_session_factory([order_model])
    )
    orders = list(
        await repo.list_completed_before(cutoff, session=_repo_session(repo))
    )
    assert len(orders) == 1
    assert orders[0].completed_at is not None


@pytest.mark.asyncio
async def test_order_repository_count_by_advertiser() -> None:
    """Count orders by advertiser."""

    advertiser_id = UUID("00000000-0000-0000-0000-00000000017a")
    repo = SqlAlchemyOrderRepository(session_factory=_session_factory(2))
    count = await repo.count_by_advertiser(
        advertiser_id, session=_repo_session(repo)
    )
    assert count == 2


@pytest.mark.asyncio
async def test_order_repository_list_by_advertiser() -> None:
    """List orders by advertiser."""

    advertiser_id = UUID("00000000-0000-0000-0000-000000000172")
    model = OrderModel(
        order_id=UUID("00000000-0000-0000-0000-000000000173"),
        advertiser_id=advertiser_id,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )
    repo = SqlAlchemyOrderRepository(session_factory=_session_factory(model))

    orders_iter = await repo.list_by_advertiser(
        advertiser_id, session=_repo_session(repo)
    )
    orders = list(orders_iter)
    assert orders


@pytest.mark.asyncio
async def test_payment_repository_save_and_get() -> None:
    """Save and fetch payment."""

    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyPaymentRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    payment = Payment(
        payment_id=UUID("00000000-0000-0000-0000-000000000180"),
        order_id=UUID("00000000-0000-0000-0000-000000000181"),
        provider="mock",
        status=PaymentStatus.PAID,
        amount=1000.0,
        currency="RUB",
        external_id="mock:1",
        created_at=datetime.now(timezone.utc),
        paid_at=datetime.now(timezone.utc),
    )
    await repo.save(payment, session=session)
    assert session.merged is not None
    assert session.committed is False

    model = PaymentModel(
        payment_id=payment.payment_id,
        order_id=payment.order_id,
        provider=payment.provider,
        status=payment.status,
        amount=payment.amount,
        currency=payment.currency,
        external_id=payment.external_id,
        created_at=payment.created_at,
        paid_at=payment.paid_at,
    )
    repo_get = SqlAlchemyPaymentRepository(
        session_factory=_session_factory(model)
    )
    sess = _repo_session(repo_get)
    fetched = await repo_get.get_by_order(payment.order_id, session=sess)
    assert fetched is not None
    fetched_external = await repo_get.get_by_external_id(
        payment.external_id, session=sess
    )
    assert fetched_external is not None


@pytest.mark.asyncio
async def test_payment_repository_uses_session_factory_when_no_session() -> (
    None
):
    """Payment repo uses session_factory when no session."""

    saved_models: list = []

    class TrackingSession(FakeSession):
        async def merge(self, model):  # type: ignore[no-untyped-def]
            saved_models.append(model)
            return model

    repo = SqlAlchemyPaymentRepository(
        session_factory=lambda: TrackingSession(None)
    )
    payment = Payment(
        payment_id=UUID("00000000-0000-0000-0000-000000000182"),
        order_id=UUID("00000000-0000-0000-0000-000000000183"),
        provider="mock",
        status=PaymentStatus.PAID,
        amount=1000.0,
        currency="RUB",
        external_id="mock:2",
        created_at=datetime.now(timezone.utc),
        paid_at=datetime.now(timezone.utc),
    )
    await repo.save(payment)
    assert len(saved_models) == 1


@pytest.mark.asyncio
async def test_contact_pricing_repository_get() -> None:
    """Fetch contact pricing by bloggers count."""

    model = ContactPricingModel(
        bloggers_count=10,
        price=3000.0,
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyContactPricingRepository(
        session_factory=_session_factory(model)
    )
    pricing = await repo.get_by_bloggers_count(10, session=_repo_session(repo))
    assert pricing is not None
    assert pricing.bloggers_count == 10


@pytest.mark.asyncio
async def test_offer_dispatch_repository_record_sent_and_response() -> None:
    """record_sent and record_response merge/update offer dispatch."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    order_id = UUID("00000000-0000-0000-0000-000000000191")
    blogger_id = UUID("00000000-0000-0000-0000-000000000192")
    await repo.record_sent(order_id, blogger_id, session=session)
    assert session.merged is not None

    await repo.record_response(
        order_id, blogger_id, accepted=True, in_offer=True, session=session
    )
    # record_response uses execute(update(...)); merge already asserted above
    assert session.merged is not None


@pytest.mark.asyncio
async def test_outbox_repository_save_and_get() -> None:
    """Outbox event is saved and retrieved correctly."""

    event = OutboxEvent(
        event_id=UUID("00000000-0000-0000-0000-000000000001"),
        event_type="order.activated",
        aggregate_id="order-123",
        aggregate_type="order",
        payload={"key": "value"},
        status=OutboxEventStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        processed_at=None,
        retry_count=0,
        last_error=None,
    )

    model = OutboxEventModel(
        event_id=event.event_id,
        event_type=event.event_type,
        aggregate_id=event.aggregate_id,
        aggregate_type=event.aggregate_type,
        payload=event.payload,
        status=event.status,
        created_at=event.created_at,
        processed_at=event.processed_at,
        retry_count=event.retry_count,
        last_error=event.last_error,
    )

    # Test save - create a session that captures the saved model
    saved_models = []

    class CapturingSession(FakeSession):
        def add(self, obj):  # type: ignore[no-untyped-def]
            saved_models.append(obj)

    session = CapturingSession(model)

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyOutboxRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    await repo.save(event, session=session)

    assert len(saved_models) == 1
    saved_model = saved_models[0]
    assert saved_model.event_id == event.event_id
    assert saved_model.event_type == event.event_type
    assert saved_model.aggregate_id == event.aggregate_id
    assert saved_model.payload == event.payload
    assert saved_model.status == event.status

    # Test get_by_id - would require complex mocking, covered by in-memory tests
    # repo_get = SqlAlchemyOutboxRepository(
    #     session_factory=_session_factory(model))
    # retrieved = repo_get.get_by_id(event.event_id)
    # assert retrieved is not None


@pytest.mark.asyncio
async def test_outbox_repository_uses_session_factory_when_no_session() -> None:
    """Outbox repo uses session_factory when no session."""

    event = OutboxEvent(
        event_id=UUID("00000000-0000-0000-0000-000000000010"),
        event_type="order.activated",
        aggregate_id="order-999",
        aggregate_type="order",
        payload={"key": "value"},
        status=OutboxEventStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        processed_at=None,
        retry_count=0,
        last_error=None,
    )
    repo = SqlAlchemyOutboxRepository(session_factory=lambda: FakeSession(None))
    # Should not raise RuntimeError — session_factory opens own session
    await repo.save(event)


@pytest.mark.asyncio
async def test_repo_uses_session_factory_when_no_session() -> None:
    """Calling repo method without session uses session_factory to open one."""
    model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000199"),
        external_id="199",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyUserRepository(session_factory=_session_factory(model))
    user = await repo.get_by_id(model.user_id)
    assert user is not None
    assert user.external_id == "199"


@pytest.mark.asyncio
async def test_offer_dispatch_repository_list_responses_by_blogger() -> None:
    """list_responses_by_blogger returns dispatches where blogger responded."""
    blogger_id = UUID("00000000-0000-0000-0000-000000000193")
    model = OfferDispatchModel(
        order_id=UUID("00000000-0000-0000-0000-000000000195"),
        blogger_id=blogger_id,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        accepted=True,
        in_offer=True,
    )
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory([model])
    )
    responses = list(
        await repo.list_responses_by_blogger(
            blogger_id, session=_repo_session(repo)
        )
    )
    assert len(responses) == 1
    assert responses[0].blogger_id == blogger_id
    assert responses[0].accepted is True


@pytest.mark.asyncio
async def test_offer_dispatch_repository_list_responses_by_order() -> None:
    """list_responses_by_order returns dispatches for order."""
    order_id = UUID("00000000-0000-0000-0000-000000000194")
    model = OfferDispatchModel(
        order_id=order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000195"),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        accepted=True,
        in_offer=True,
    )
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory([model])
    )
    responses = list(
        await repo.list_responses_by_order(
            order_id, session=_repo_session(repo)
        )
    )
    assert len(responses) == 1
    assert responses[0].order_id == order_id


@pytest.mark.asyncio
async def test_offer_dispatch_repository_exists_responded() -> None:
    """exists_responded returns True when blogger responded."""
    order_id = UUID("00000000-0000-0000-0000-000000000196")
    blogger_id = UUID("00000000-0000-0000-0000-000000000197")
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory(1)  # count = 1
    )
    out = await repo.exists_responded(
        order_id, blogger_id, session=_repo_session(repo)
    )
    assert out is True


@pytest.mark.asyncio
async def test_offer_dispatch_repository_exists_responded_false() -> None:
    """exists_responded returns False when count is 0."""
    order_id = UUID("00000000-0000-0000-0000-000000000198")
    blogger_id = UUID("00000000-0000-0000-0000-000000000199")
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory(0)
    )
    out = await repo.exists_responded(
        order_id, blogger_id, session=_repo_session(repo)
    )
    assert out is False


@pytest.mark.asyncio
async def test_offer_dispatch_repository_count_by_order() -> None:
    """count_by_order returns number of dispatches for order."""
    order_id = UUID("00000000-0000-0000-0000-00000000019a")
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory(3)
    )
    count = await repo.count_by_order(order_id, session=_repo_session(repo))
    assert count == 3


@pytest.mark.asyncio
async def test_offer_dispatch_repository_count_accepted_by_order() -> None:
    """count_accepted_by_order returns number with in_offer=True."""
    order_id = UUID("00000000-0000-0000-0000-00000000019b")
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory(2)
    )
    count = await repo.count_accepted_by_order(
        order_id, session=_repo_session(repo)
    )
    assert count == 2


@pytest.mark.asyncio
async def test_offer_dispatch_repository_count_completed_orders_empty() -> None:
    """count_completed_orders_by_blogger_ids returns {} for empty list."""
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory([])
    )
    out = await repo.count_completed_orders_by_blogger_ids(
        [], session=_repo_session(repo)
    )
    assert out == {}


@pytest.mark.asyncio
async def test_offer_dispatch_repository_count_completed_orders() -> None:
    """count_completed_orders_by_blogger_ids returns counts per blogger."""
    blogger_id = UUID("00000000-0000-0000-0000-00000000019c")
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory(
            [
                SimpleNamespace(blogger_id=blogger_id, cnt=2),
            ]
        )
    )
    out = await repo.count_completed_orders_by_blogger_ids(
        [blogger_id], session=_repo_session(repo)
    )
    assert out == {blogger_id: 2}


@pytest.mark.asyncio
async def test_interaction_repository_list_due_for_feedback() -> None:
    """list_due_for_feedback returns interactions due for feedback."""
    cutoff = datetime.now(timezone.utc)
    model = InteractionModel(
        interaction_id=UUID("00000000-0000-0000-0000-000000000196"),
        order_id=UUID("00000000-0000-0000-0000-000000000197"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000198"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000199"),
        status=InteractionStatus.PENDING,
        next_check_at=cutoff - timedelta(minutes=1),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyInteractionRepository(
        session_factory=_session_factory([model])
    )
    interactions = list(
        await repo.list_due_for_feedback(cutoff, session=_repo_session(repo))
    )
    assert len(interactions) == 1
    assert interactions[0].status == InteractionStatus.PENDING


@pytest.mark.asyncio
async def test_interaction_repository_list_by_status() -> None:
    """list_by_status returns interactions by status."""
    model = InteractionModel(
        interaction_id=UUID("00000000-0000-0000-0000-000000000200"),
        order_id=UUID("00000000-0000-0000-0000-000000000201"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000202"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000203"),
        status=InteractionStatus.PENDING,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyInteractionRepository(
        session_factory=_session_factory([model])
    )
    interactions = list(
        await repo.list_by_status(
            InteractionStatus.PENDING, session=_repo_session(repo)
        )
    )
    assert len(interactions) == 1
    assert interactions[0].status == InteractionStatus.PENDING


@pytest.mark.asyncio
async def test_interaction_repository_list_blogger_ids_with_unfulfilled() -> (
    None
):
    """Unfulfilled interaction blogger_ids (PENDING or ISSUE) returned."""
    blogger_pending = UUID("00000000-0000-0000-0000-000000000220")
    blogger_issue = UUID("00000000-0000-0000-0000-000000000221")
    blogger_ok = UUID("00000000-0000-0000-0000-000000000222")
    # Fake session returns list of UUIDs (as from select(blogger_id).distinct())
    result_ids = [blogger_pending, blogger_issue]
    repo = SqlAlchemyInteractionRepository(
        session_factory=_session_factory(result_ids)
    )
    result = await repo.list_blogger_ids_with_unfulfilled_interaction(
        session=_repo_session(repo)
    )
    result_set = set(result)
    assert blogger_pending in result_set
    assert blogger_issue in result_set
    assert blogger_ok not in result_set


@pytest.mark.asyncio
async def test_interaction_repository_update_next_check_at() -> None:
    """update_next_check_at executes update."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyInteractionRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    interaction_id = UUID("00000000-0000-0000-0000-000000000204")
    next_check = datetime.now(timezone.utc) + timedelta(hours=1)
    await repo.update_next_check_at(interaction_id, next_check, session=session)


@pytest.mark.asyncio
async def test_complaint_repository_list_by_reporter() -> None:
    """list_by_reporter returns complaints by reporter."""
    reporter_id = UUID("00000000-0000-0000-0000-000000000205")
    model = ComplaintModel(
        complaint_id=UUID("00000000-0000-0000-0000-000000000206"),
        reporter_id=reporter_id,
        reported_id=UUID("00000000-0000-0000-0000-000000000207"),
        order_id=UUID("00000000-0000-0000-0000-000000000208"),
        reason="test",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyComplaintRepository(
        session_factory=_session_factory([model])
    )
    complaints = list(
        await repo.list_by_reporter(reporter_id, session=_repo_session(repo))
    )
    assert len(complaints) == 1
    assert complaints[0].reporter_id == reporter_id


@pytest.mark.asyncio
async def test_complaint_repository_exists() -> None:
    """exists returns True when complaint exists."""
    repo = SqlAlchemyComplaintRepository(session_factory=_session_factory(1))
    order_id = UUID("00000000-0000-0000-0000-000000000209")
    reporter_id = UUID("00000000-0000-0000-0000-000000000210")
    result = await repo.exists(
        order_id, reporter_id, session=_repo_session(repo)
    )
    assert result is True


@pytest.mark.asyncio
async def test_complaint_repository_list_by_status() -> None:
    """list_by_status returns complaints by status."""
    model = ComplaintModel(
        complaint_id=UUID("00000000-0000-0000-0000-000000000211"),
        reporter_id=UUID("00000000-0000-0000-0000-000000000212"),
        reported_id=UUID("00000000-0000-0000-0000-000000000213"),
        order_id=UUID("00000000-0000-0000-0000-000000000214"),
        reason="test",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyComplaintRepository(
        session_factory=_session_factory([model])
    )
    complaints = list(
        await repo.list_by_status(
            ComplaintStatus.PENDING, session=_repo_session(repo)
        )
    )
    assert len(complaints) == 1
    assert complaints[0].status == ComplaintStatus.PENDING


@pytest.mark.asyncio
async def test_outbox_repository_mark_as_processing() -> None:
    """mark_as_processing executes update."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyOutboxRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    event_id = UUID("00000000-0000-0000-0000-000000000215")
    await repo.mark_as_processing(event_id, session=session)


@pytest.mark.asyncio
async def test_outbox_repository_mark_as_published() -> None:
    """mark_as_published executes update."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyOutboxRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    event_id = UUID("00000000-0000-0000-0000-000000000216")
    processed_at = datetime.now(timezone.utc)
    await repo.mark_as_published(event_id, processed_at, session=session)


@pytest.mark.asyncio
async def test_outbox_repository_mark_as_failed() -> None:
    """mark_as_failed executes update."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyOutboxRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    event_id = UUID("00000000-0000-0000-0000-000000000217")
    await repo.mark_as_failed(event_id, "error", 1, session=session)


@pytest.mark.asyncio
async def test_outbox_repository_delete_processed_events_retention_zero() -> (
    None
):
    """delete_processed_events returns 0 when retention_days is 0."""

    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyOutboxRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    deleted = await repo.delete_processed_events(
        retention_days=0, batch_size=1000, session=session
    )
    assert deleted == 0


@pytest.mark.asyncio
async def test_outbox_repository_delete_processed_events_returns_count() -> (
    None
):
    """delete_processed_events returns rowcount from execute result."""

    class FakeSessionWithRowcount(FakeSession):
        async def execute(self, *_args, **_kwargs):  # type: ignore[no-untyped-def]
            return FakeResult(None, rowcount=3)

    session_with_rowcount = FakeSessionWithRowcount(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyOutboxRepository(
        session_factory=FakeAsyncSessionMaker(session_with_rowcount)
    )
    deleted = await repo.delete_processed_events(
        retention_days=7, batch_size=1000, session=session_with_rowcount
    )
    assert deleted == 3


class FakeAsyncSessionCompat(FakeSession):
    """FakeSession passing isinstance(session, AsyncSession) when patched."""


@pytest.mark.asyncio
async def test_blogger_repository_list_confirmed_user_ids() -> None:
    """list_confirmed_user_ids returns confirmed blogger user ids."""
    user_id_1 = UUID("00000000-0000-0000-0000-000000000220")
    session = FakeAsyncSessionCompat([user_id_1])
    with patch(
        "ugc_bot.infrastructure.db.repositories.profiles.AsyncSession",
        FakeAsyncSessionCompat,
    ):
        repo = SqlAlchemyBloggerProfileRepository(
            session_factory=lambda: session  # type: ignore[return-value]
        )
        result = await repo.list_confirmed_user_ids(session=session)
    assert result == [user_id_1]


@pytest.mark.asyncio
async def test_blogger_repository_list_confirmed_user_ids_with_geometry() -> (
    None
):
    """list_confirmed_user_ids with location_geometry_wkt uses PostGIS."""
    user_id_1 = UUID("00000000-0000-0000-0000-000000000221")
    session = FakeAsyncSessionCompat([user_id_1])
    session.sync_session = SimpleNamespace(
        get_bind=lambda: SimpleNamespace(
            dialect=SimpleNamespace(name="postgresql")
        )
    )
    with patch(
        "ugc_bot.infrastructure.db.repositories.profiles.AsyncSession",
        FakeAsyncSessionCompat,
    ):
        repo = SqlAlchemyBloggerProfileRepository(
            session_factory=lambda: session  # type: ignore[return-value]
        )
        result = await repo.list_confirmed_user_ids(
            session=session,
            location_geometry_wkt="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        )
    assert result == [user_id_1]


@pytest.mark.asyncio
async def test_blogger_repo_list_confirmed_ids_geometry_attr_err_skipped() -> (
    None
):
    """When get_bind raises AttributeError, geometry filter skipped."""
    user_id_1 = UUID("00000000-0000-0000-0000-000000000222")
    session = FakeAsyncSessionCompat([user_id_1])

    def get_bind_raises():  # noqa: B902
        raise AttributeError("no bind")

    session.sync_session = SimpleNamespace(get_bind=get_bind_raises)
    with patch(
        "ugc_bot.infrastructure.db.repositories.profiles.AsyncSession",
        FakeAsyncSessionCompat,
    ):
        repo = SqlAlchemyBloggerProfileRepository(
            session_factory=lambda: session  # type: ignore[return-value]
        )
        result = await repo.list_confirmed_user_ids(
            session=session,
            location_geometry_wkt="POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))",
        )
    assert result == [user_id_1]


@pytest.mark.asyncio
async def test_blogger_repo_list_confirmed_with_instagram_id_no_filter() -> (
    None
):
    """list_confirmed_with_instagram_id without stats_older_than."""
    user_id_1 = UUID("00000000-0000-0000-0000-000000000223")
    model = BloggerProfileModel(
        user_id=user_id_1,
        instagram_url="https://instagram.com/u2",
        confirmed=True,
        city="moscow",
        region="moscow",
        country="russia",
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=Decimal("1000"),
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        instagram_user_id="456",
        instagram_stats_fetched_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyBloggerProfileRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.list_confirmed_with_instagram_id(
        limit=10,
        session=_repo_session(repo),
    )
    assert len(result) == 1
    assert result[0].user_id == user_id_1


@pytest.mark.asyncio
async def test_blogger_repo_list_confirmed_instagram_stats_older_than() -> None:
    """list_confirmed_with_instagram_id with stats_older_than (outerjoin)."""
    older_than = datetime.now(timezone.utc) - timedelta(days=1)
    user_id_1 = UUID("00000000-0000-0000-0000-000000000222")
    model = BloggerProfileModel(
        user_id=user_id_1,
        instagram_url="https://instagram.com/u",
        confirmed=True,
        city="moscow",
        region="moscow",
        country="russia",
        topics={"selected": ["tech"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=Decimal("1000"),
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        instagram_user_id="123",
        instagram_stats_fetched_at=older_than - timedelta(hours=1),
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyBloggerProfileRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.list_confirmed_with_instagram_id(
        limit=10,
        stats_older_than=older_than,
        session=_repo_session(repo),
    )
    assert len(result) == 1
    assert result[0].user_id == user_id_1


@pytest.mark.asyncio
async def test_instagram_stats_repository_get_by_user_id() -> None:
    """Instagram stats repository get_by_user_id returns entity."""
    user_id = UUID("00000000-0000-0000-0000-000000000223")
    model = InstagramStatsModel(
        user_id=user_id,
        raw_response={"followers": 100},
        fetched_at=datetime.now(timezone.utc),
        followers_count=100,
        follows_count=50,
        media_count=10,
        instagram_username="user",
        biography="Bio",
        provider="rapid_api",
        instagram_id="ig123",
    )
    repo = SqlAlchemyInstagramStatsRepository(
        session_factory=_session_factory(model)
    )
    stats = await repo.get_by_user_id(user_id, session=_repo_session(repo))
    assert stats is not None
    assert stats.user_id == user_id
    assert stats.followers_count == 100
    assert stats.instagram_username == "user"


@pytest.mark.asyncio
async def test_instagram_stats_repository_save() -> None:
    """Instagram stats repository save merges model."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, sess):  # type: ignore[no-untyped-def]
            self._session = sess

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyInstagramStatsRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    stats = InstagramStats(
        user_id=UUID("00000000-0000-0000-0000-000000000224"),
        raw_response={"data": {}},
        fetched_at=datetime.now(timezone.utc),
        followers_count=200,
        follows_count=100,
        media_count=20,
        instagram_username="saved",
        biography="",
        provider="rapid_api",
        instagram_id=None,
    )
    await repo.save(stats, session=session)
    assert session.merged is not None
    assert getattr(session.merged, "user_id", None) == stats.user_id


@pytest.mark.asyncio
async def test_interaction_repository_list_by_order() -> None:
    """list_by_order returns interactions for order."""
    order_id = UUID("00000000-0000-0000-0000-000000000221")
    model = InteractionModel(
        interaction_id=UUID("00000000-0000-0000-0000-000000000222"),
        order_id=order_id,
        blogger_id=UUID("00000000-0000-0000-0000-000000000223"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000224"),
        status=InteractionStatus.PENDING,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyInteractionRepository(
        session_factory=_session_factory([model])
    )
    interactions = list(
        await repo.list_by_order(order_id, session=_repo_session(repo))
    )
    assert len(interactions) == 1
    assert interactions[0].order_id == order_id


@pytest.mark.asyncio
async def test_interaction_repository_save() -> None:
    """save persists interaction via merge."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyInteractionRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    interaction = Interaction(
        interaction_id=UUID("00000000-0000-0000-0000-000000000225"),
        order_id=UUID("00000000-0000-0000-0000-000000000226"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000227"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000228"),
        status=InteractionStatus.PENDING,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    await repo.save(interaction, session=session)
    assert session.merged is not None


@pytest.mark.asyncio
async def test_interaction_repository_get_by_id() -> None:
    """get_by_id returns interaction when found."""
    interaction_id = UUID("00000000-0000-0000-0000-000000000229")
    model = InteractionModel(
        interaction_id=interaction_id,
        order_id=UUID("00000000-0000-0000-0000-000000000230"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000231"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000232"),
        status=InteractionStatus.PENDING,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyInteractionRepository(
        session_factory=_session_factory(model)
    )
    interaction = await repo.get_by_id(
        interaction_id, session=_repo_session(repo)
    )
    assert interaction is not None
    assert interaction.interaction_id == interaction_id
    assert interaction.status == InteractionStatus.PENDING


@pytest.mark.asyncio
async def test_instagram_verification_repository_get_valid_code_mismatch() -> (
    None
):
    """get_valid_code returns None when code or user_id does not match."""
    user_id = UUID("00000000-0000-0000-0000-000000000228")
    model = InstagramVerificationCodeModel(
        code_id=UUID("00000000-0000-0000-0000-000000000229"),
        user_id=user_id,
        code="MATCH",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        used=False,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(model)
    )
    assert (
        await repo.get_valid_code(user_id, "WRONG", session=_repo_session(repo))
        is None
    )
    assert (
        await repo.get_valid_code(
            UUID("00000000-0000-0000-0000-000000000999"),
            "MATCH",
            session=_repo_session(repo),
        )
        is None
    )


@pytest.mark.asyncio
async def test_instagram_verification_repository_mark_used_model_none() -> None:
    """mark_used is no-op when model is not found."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    code_id = UUID("00000000-0000-0000-0000-000000000229")
    await repo.mark_used(code_id, session=session)
    assert session.merged is None


@pytest.mark.asyncio
async def test_nps_repository_save() -> None:
    """NpsRepository save adds model to session."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyNpsRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    user_id = UUID("00000000-0000-0000-0000-000000000230")
    await repo.save(user_id, 9, "Great!", session=session)


@pytest.mark.asyncio
async def test_nps_repository_exists_for_user() -> None:
    """exists_for_user returns True when user has NPS response."""
    repo = SqlAlchemyNpsRepository(session_factory=_session_factory(1))
    user_id = UUID("00000000-0000-0000-0000-000000000231")
    result = await repo.exists_for_user(user_id, session=_repo_session(repo))
    assert result is True


@pytest.mark.asyncio
async def test_outbox_repository_get_pending_events() -> None:
    """get_pending_events returns pending events."""
    model = OutboxEventModel(
        event_id=UUID("00000000-0000-0000-0000-000000000232"),
        event_type="order_activation",
        aggregate_id=UUID("00000000-0000-0000-0000-000000000233"),
        aggregate_type="order",
        payload={},
        status=OutboxEventStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyOutboxRepository(session_factory=_session_factory([model]))
    events = await repo.get_pending_events(
        limit=10, session=_repo_session(repo)
    )
    assert len(events) == 1
    assert events[0].event_type == "order_activation"


@pytest.mark.asyncio
async def test_outbox_repository_claim_pending_events() -> None:
    """claim_pending_events returns pending events and marks them PROCESSING."""
    model_1 = OutboxEventModel(
        event_id=UUID("00000000-0000-0000-0000-000000000244"),
        event_type="order.activated",
        aggregate_id=UUID("00000000-0000-0000-0000-000000000245"),
        aggregate_type="order",
        payload={},
        status=OutboxEventStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    model_2 = OutboxEventModel(
        event_id=UUID("00000000-0000-0000-0000-000000000246"),
        event_type="order.activated",
        aggregate_id=UUID("00000000-0000-0000-0000-000000000247"),
        aggregate_type="order",
        payload={},
        status=OutboxEventStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyOutboxRepository(
        session_factory=_session_factory([model_1, model_2])
    )
    session = _repo_session(repo)
    events = await repo.claim_pending_events(limit=10, session=session)
    assert len(events) == 2
    assert events[0].event_id == model_1.event_id
    assert events[1].event_id == model_2.event_id


@pytest.mark.asyncio
async def test_outbox_repository_mark_for_retry() -> None:
    """mark_for_retry updates event status to PENDING for retry."""
    event_id = UUID("00000000-0000-0000-0000-000000000248")
    session = FakeSession(None)
    repo = SqlAlchemyOutboxRepository(session_factory=_session_factory(None))
    await repo.mark_for_retry(
        event_id, error="temp failure", retry_count=1, session=session
    )


@pytest.mark.asyncio
async def test_complaint_repository_save() -> None:
    """save persists complaint via merge."""
    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):  # type: ignore[no-untyped-def]
            self._session = session

        def __call__(self):  # type: ignore[no-untyped-def]
            return self._session

    repo = SqlAlchemyComplaintRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    complaint = Complaint(
        complaint_id=UUID("00000000-0000-0000-0000-000000000234"),
        reporter_id=UUID("00000000-0000-0000-0000-000000000235"),
        reported_id=UUID("00000000-0000-0000-0000-000000000236"),
        order_id=UUID("00000000-0000-0000-0000-000000000237"),
        reason="test",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        reviewed_at=None,
    )
    await repo.save(complaint, session=session)
    assert session.merged is not None


@pytest.mark.asyncio
async def test_interaction_repository_get_by_participants() -> None:
    """get_by_participants returns interaction by order/blogger/advertiser."""
    order_id = UUID("00000000-0000-0000-0000-000000000238")
    blogger_id = UUID("00000000-0000-0000-0000-000000000239")
    advertiser_id = UUID("00000000-0000-0000-0000-000000000240")
    model = InteractionModel(
        interaction_id=UUID("00000000-0000-0000-0000-000000000241"),
        order_id=order_id,
        blogger_id=blogger_id,
        advertiser_id=advertiser_id,
        status=InteractionStatus.PENDING,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyInteractionRepository(
        session_factory=_session_factory(model)
    )
    interaction = await repo.get_by_participants(
        order_id, blogger_id, advertiser_id, session=_repo_session(repo)
    )
    assert interaction is not None
    assert interaction.order_id == order_id
    assert interaction.blogger_id == blogger_id
    assert interaction.advertiser_id == advertiser_id


@pytest.mark.asyncio
async def test_outbox_repository_get_by_id() -> None:
    """get_by_id returns outbox event when found."""
    event_id = UUID("00000000-0000-0000-0000-000000000242")
    model = OutboxEventModel(
        event_id=event_id,
        event_type="order_activation",
        aggregate_id=UUID("00000000-0000-0000-0000-000000000243"),
        aggregate_type="order",
        payload={},
        status=OutboxEventStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyOutboxRepository(session_factory=_session_factory(model))
    event = await repo.get_by_id(event_id, session=_repo_session(repo))
    assert event is not None
    assert event.event_id == event_id


@pytest.mark.asyncio
async def test_complaint_repository_get_by_id() -> None:
    """get_by_id returns complaint when found."""
    complaint_id = UUID("00000000-0000-0000-0000-000000000244")
    model = ComplaintModel(
        complaint_id=complaint_id,
        reporter_id=UUID("00000000-0000-0000-0000-000000000245"),
        reported_id=UUID("00000000-0000-0000-0000-000000000246"),
        order_id=UUID("00000000-0000-0000-0000-000000000247"),
        reason="test",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyComplaintRepository(
        session_factory=_session_factory(model)
    )
    complaint = await repo.get_by_id(complaint_id, session=_repo_session(repo))
    assert complaint is not None
    assert complaint.complaint_id == complaint_id


@pytest.mark.asyncio
async def test_complaint_repository_list_by_order() -> None:
    """list_by_order returns complaints for order."""
    order_id = UUID("00000000-0000-0000-0000-000000000248")
    model = ComplaintModel(
        complaint_id=UUID("00000000-0000-0000-0000-000000000249"),
        reporter_id=UUID("00000000-0000-0000-0000-000000000250"),
        reported_id=UUID("00000000-0000-0000-0000-000000000251"),
        order_id=order_id,
        reason="test",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyComplaintRepository(
        session_factory=_session_factory([model])
    )
    complaints = list(
        await repo.list_by_order(order_id, session=_repo_session(repo))
    )
    assert len(complaints) == 1
    assert complaints[0].order_id == order_id


@pytest.mark.asyncio
async def test_user_repository_get_by_referral_code() -> None:
    """get_by_referral_code returns user when found."""
    model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000301"),
        external_id="ext",
        messenger_type=MessengerType.TELEGRAM,
        username="u",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        referral_code="refcode1",
    )
    repo = SqlAlchemyUserRepository(session_factory=_session_factory(model))
    user = await repo.get_by_referral_code(
        "refcode1", session=_repo_session(repo)
    )
    assert user is not None
    assert user.referral_code == "refcode1"


def test_geometry_to_wkt_none_returns_none() -> None:
    """_geometry_to_wkt(None) returns None."""
    assert _geometry_to_wkt(None) is None


def test_geometry_to_wkt_str_returns_str() -> None:
    """_geometry_to_wkt with str returns as-is."""
    assert _geometry_to_wkt("POINT(1 2)") == "POINT(1 2)"


def test_geometry_to_wkt_wkt_element_returns_wkt() -> None:
    """_geometry_to_wkt with WKTElement returns WKT via shape.to_shape."""
    from geoalchemy2.elements import WKTElement

    el = WKTElement("POINT(37.6 55.75)", srid=4326)
    result = _geometry_to_wkt(el)
    assert result is not None
    assert "37.6" in result and "55.75" in result


def test_geometry_to_wkt_invalid_returns_none() -> None:
    """_geometry_to_wkt with invalid object returns None."""
    assert _geometry_to_wkt(object()) is None


def test_wkt_to_geometry_element_empty_returns_none() -> None:
    """_wkt_to_geometry_element with empty or whitespace returns None."""
    assert _wkt_to_geometry_element("") is None
    assert _wkt_to_geometry_element("   ") is None
    assert _wkt_to_geometry_element(None) is None


def test_wkt_to_geometry_element_valid_returns_element() -> None:
    """_wkt_to_geometry_element with valid WKT returns WKTElement."""
    from geoalchemy2.elements import WKTElement

    result = _wkt_to_geometry_element("POINT(1 2)")
    assert result is not None
    assert isinstance(result, WKTElement)


@pytest.mark.asyncio
async def test_user_repository_get_by_telegram_empty_returns_none() -> None:
    """get_by_telegram with empty or whitespace returns None."""
    repo = SqlAlchemyUserRepository(session_factory=_session_factory(None))
    session = _repo_session(repo)
    assert await repo.get_by_telegram("", session=session) is None
    assert await repo.get_by_telegram("  ", session=session) is None


@pytest.mark.asyncio
async def test_user_repository_get_by_telegram() -> None:
    """get_by_telegram returns user (case-insensitive, @ stripped)."""
    model = UserModel(
        user_id=UUID("00000000-0000-0000-0000-000000000302"),
        external_id="ext2",
        messenger_type=MessengerType.TELEGRAM,
        username="u2",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram="john_doe",
    )
    repo = SqlAlchemyUserRepository(session_factory=_session_factory(model))
    user = await repo.get_by_telegram("john_doe", session=_repo_session(repo))
    assert user is not None
    assert user.telegram == "john_doe"
    user2 = await repo.get_by_telegram("@John_Doe", session=_repo_session(repo))
    assert user2 is not None
    assert user2.user_id == user.user_id


@pytest.mark.asyncio
async def test_user_referral_binding_repository_save() -> None:
    """UserReferralBinding repo save merges model."""
    ref_id = UUID("00000000-0000-0000-0000-000000000400")
    referred_id = UUID("00000000-0000-0000-0000-000000000401")
    now = datetime.now(timezone.utc)
    binding = UserReferralBinding(
        referrer_user_id=ref_id,
        referred_user_id=referred_id,
        created_at=now,
    )
    repo = SqlAlchemyUserReferralBindingRepository(
        session_factory=_session_factory(None)
    )
    await repo.save(binding, session=_repo_session(repo))


@pytest.mark.asyncio
async def test_user_referral_binding_repository_save_and_get() -> None:
    """UserReferralBinding repo get_by_referred_user."""
    ref_id = UUID("00000000-0000-0000-0000-000000000401")
    referred_id = UUID("00000000-0000-0000-0000-000000000402")
    now = datetime.now(timezone.utc)
    model = UserReferralBindingModel(
        referrer_user_id=ref_id,
        referred_user_id=referred_id,
        created_at=now,
    )
    repo = SqlAlchemyUserReferralBindingRepository(
        session_factory=_session_factory(model)
    )
    binding = await repo.get_by_referred_user(
        referred_id, session=_repo_session(repo)
    )
    assert binding is not None
    assert binding.referrer_user_id == ref_id
    assert binding.referred_user_id == referred_id


@pytest.mark.asyncio
async def test_user_referral_binding_repository_list_by_referrer() -> None:
    """list_by_referrer returns bindings for referrer."""
    ref_id = UUID("00000000-0000-0000-0000-000000000403")
    referred_id = UUID("00000000-0000-0000-0000-000000000404")
    now = datetime.now(timezone.utc)
    model = UserReferralBindingModel(
        referrer_user_id=ref_id,
        referred_user_id=referred_id,
        created_at=now,
    )
    repo = SqlAlchemyUserReferralBindingRepository(
        session_factory=_session_factory([model])
    )
    bindings = list(
        await repo.list_by_referrer(ref_id, session=_repo_session(repo))
    )
    assert len(bindings) == 1
    assert bindings[0].referrer_user_id == ref_id


@pytest.mark.asyncio
async def test_user_referral_binding_repository_count_by_referrer() -> None:
    """count_by_referrer returns count."""
    repo = SqlAlchemyUserReferralBindingRepository(
        session_factory=_session_factory(2)
    )
    ref_id = UUID("00000000-0000-0000-0000-000000000405")
    count = await repo.count_by_referrer(ref_id, session=_repo_session(repo))
    assert count == 2


@pytest.mark.asyncio
async def test_user_referral_pending_repository_save() -> None:
    """UserReferralPending repo save merges model."""
    user_id = UUID("00000000-0000-0000-0000-000000000500")
    ref_id = UUID("00000000-0000-0000-0000-000000000501")
    now = datetime.now(timezone.utc)
    pending = UserReferralPending(
        user_id=user_id,
        referrer_user_id=ref_id,
        created_at=now,
    )
    repo = SqlAlchemyUserReferralPendingRepository(
        session_factory=_session_factory(None)
    )
    await repo.save(pending, session=_repo_session(repo))


@pytest.mark.asyncio
async def test_user_referral_pending_repository_get_by_user() -> None:
    """UserReferralPending repo get_by_user."""
    user_id = UUID("00000000-0000-0000-0000-000000000501")
    ref_id = UUID("00000000-0000-0000-0000-000000000502")
    now = datetime.now(timezone.utc)
    model = UserReferralPendingModel(
        user_id=user_id,
        referrer_user_id=ref_id,
        created_at=now,
    )
    repo = SqlAlchemyUserReferralPendingRepository(
        session_factory=_session_factory(model)
    )
    pending = await repo.get_by_user(user_id, session=_repo_session(repo))
    assert pending is not None
    assert pending.referrer_user_id == ref_id


@pytest.mark.asyncio
async def test_user_referral_pending_repository_delete_by_user() -> None:
    """UserReferralPending repo delete_by_user executes delete."""
    repo = SqlAlchemyUserReferralPendingRepository(
        session_factory=_session_factory(None)
    )
    user_id = UUID("00000000-0000-0000-0000-000000000503")
    await repo.delete_by_user(user_id, session=_repo_session(repo))


@pytest.mark.asyncio
async def test_user_referral_pending_repository_list_by_referrer() -> None:
    """UserReferralPending repo list_by_referrer returns pending by referrer."""
    referrer_id = UUID("00000000-0000-0000-0000-000000000504")
    user_id = UUID("00000000-0000-0000-0000-000000000505")
    now = datetime.now(timezone.utc)
    model = UserReferralPendingModel(
        user_id=user_id,
        referrer_user_id=referrer_id,
        created_at=now,
    )
    repo = SqlAlchemyUserReferralPendingRepository(
        session_factory=_session_factory([model])
    )
    items = list(
        await repo.list_by_referrer(
            referrer_id, offset=0, limit=100, session=_repo_session(repo)
        )
    )
    assert len(items) == 1
    assert items[0].referrer_user_id == referrer_id
    assert items[0].user_id == user_id


@pytest.mark.asyncio
async def test_user_referral_pending_repository_count_by_referrer() -> None:
    """UserReferralPending repo count_by_referrer returns count."""
    referrer_id = UUID("00000000-0000-0000-0000-000000000506")
    repo = SqlAlchemyUserReferralPendingRepository(
        session_factory=_session_factory(3)
    )
    count = await repo.count_by_referrer(
        referrer_id, session=_repo_session(repo)
    )
    assert count == 3


@pytest.mark.asyncio
async def test_payout_request_repository_save() -> None:
    """PayoutRequest repo save adds model."""
    request_id = UUID("00000000-0000-0000-0000-000000000600")
    user_id = UUID("00000000-0000-0000-0000-000000000601")
    now = datetime.now(timezone.utc)
    request = PayoutRequest(
        request_id=request_id,
        user_id=user_id,
        requested_at=now,
        status=PayoutRequestStatus.PENDING,
    )
    repo = SqlAlchemyPayoutRequestRepository(
        session_factory=_session_factory(None)
    )
    await repo.save(request, session=_repo_session(repo))


@pytest.mark.asyncio
async def test_payout_request_repository_list_by_user() -> None:
    """PayoutRequest repo list_by_user."""
    user_id = UUID("00000000-0000-0000-0000-000000000601")
    request_id = UUID("00000000-0000-0000-0000-000000000602")
    now = datetime.now(timezone.utc)
    model = PayoutRequestModel(
        request_id=request_id,
        user_id=user_id,
        requested_at=now,
        status=PayoutRequestStatus.PENDING,
    )
    repo = SqlAlchemyPayoutRequestRepository(
        session_factory=_session_factory([model])
    )
    requests = list(
        await repo.list_by_user(user_id, session=_repo_session(repo))
    )
    assert len(requests) == 1
    assert requests[0].user_id == user_id


@pytest.mark.asyncio
async def test_payout_request_repository_list_by_user_ids() -> None:
    """PayoutRequest repo list_by_user_ids (batch) returns requests."""
    user_id_1 = UUID("00000000-0000-0000-0000-000000000605")
    user_id_2 = UUID("00000000-0000-0000-0000-000000000606")
    now = datetime.now(timezone.utc)
    model_1 = PayoutRequestModel(
        request_id=UUID("00000000-0000-0000-0000-000000000607"),
        user_id=user_id_1,
        requested_at=now,
        status=PayoutRequestStatus.PENDING,
    )
    model_2 = PayoutRequestModel(
        request_id=UUID("00000000-0000-0000-0000-000000000608"),
        user_id=user_id_2,
        requested_at=now,
        status=PayoutRequestStatus.PAID,
        amount=Decimal("50.00"),
    )
    repo = SqlAlchemyPayoutRequestRepository(
        session_factory=_session_factory([model_1, model_2])
    )
    requests = list(
        await repo.list_by_user_ids(
            [user_id_1, user_id_2], session=_repo_session(repo)
        )
    )
    assert len(requests) == 2
    assert {r.user_id for r in requests} == {user_id_1, user_id_2}


@pytest.mark.asyncio
async def test_payout_request_repository_list_by_user_ids_empty() -> None:
    """list_by_user_ids with empty list returns [] without query."""
    repo = SqlAlchemyPayoutRequestRepository(
        session_factory=_session_factory(None)
    )
    requests = list(
        await repo.list_by_user_ids([], session=_repo_session(repo))
    )
    assert requests == []


@pytest.mark.asyncio
async def test_payout_request_repository_get_by_id() -> None:
    """get_by_id returns payout request when found."""
    request_id = UUID("00000000-0000-0000-0000-000000000603")
    user_id = UUID("00000000-0000-0000-0000-000000000604")
    model = PayoutRequestModel(
        request_id=request_id,
        user_id=user_id,
        requested_at=datetime.now(timezone.utc),
        status=PayoutRequestStatus.PENDING,
    )
    repo = SqlAlchemyPayoutRequestRepository(
        session_factory=_session_factory(model)
    )
    request = await repo.get_by_id(request_id, session=_repo_session(repo))
    assert request is not None
    assert request.request_id == request_id


@pytest.mark.asyncio
async def test_payout_request_repository_update_status() -> None:
    """update_status updates row and returns True when rowcount > 0."""
    request_id = UUID("00000000-0000-0000-0000-000000000609")

    class FakeSessionWithRowcount(FakeSession):
        async def execute(self, *_args, **_kwargs):
            return FakeResult(None, rowcount=1)

    session = FakeSessionWithRowcount(None)

    class FakeAsyncSessionMaker:
        def __init__(self, sess):
            self._session = sess

        def __call__(self):
            return self._session

    repo = SqlAlchemyPayoutRequestRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    updated = await repo.update_status(
        request_id,
        PayoutRequestStatus.PAID,
        session=session,
    )
    assert updated is True


@pytest.mark.asyncio
async def test_offer_dispatch_repository_record_sent() -> None:
    """OfferDispatch repo record_sent merges model."""
    order_id = UUID("00000000-0000-0000-0000-000000000701")
    blogger_id = UUID("00000000-0000-0000-0000-000000000702")
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory(None)
    )
    await repo.record_sent(order_id, blogger_id, session=_repo_session(repo))


@pytest.mark.asyncio
async def test_offer_dispatch_repository_list_blogger_ids_sent_for_order() -> (
    None
):
    """list_blogger_ids_sent_for_order returns blogger ids."""
    order_id = UUID("00000000-0000-0000-0000-000000000703")
    blogger_id = UUID("00000000-0000-0000-0000-000000000704")
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory([blogger_id])
    )
    ids = await repo.list_blogger_ids_sent_for_order(
        order_id, session=_repo_session(repo)
    )
    assert ids == [blogger_id]


@pytest.mark.asyncio
async def test_sql_referral_order_income_loader_returns_rows() -> None:
    """SqlReferralOrderIncomeLoader returns mapped rows."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4

    from ugc_bot.domain.entities import ReferralOrderIncomeRow
    from ugc_bot.infrastructure.db.repositories import (
        SqlReferralOrderIncomeLoader,
    )

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    row_data = SimpleNamespace(
        creator_created_at=now,
        order_completed_at=now,
        payment_amount=100.0,
        bloggers_needed=2,
        order_id=order_id,
    )
    session = FakeSession([row_data])
    loader = SqlReferralOrderIncomeLoader(session_factory=lambda: session)
    rows = await loader.load_referral_order_income_rows(
        referrer_id, limit=10, session=session
    )
    assert len(rows) == 1
    assert isinstance(rows[0], ReferralOrderIncomeRow)
    assert rows[0].payment_amount == 100.0
    assert rows[0].bloggers_needed == 2
    assert rows[0].order_id == order_id


@pytest.mark.asyncio
async def test_sql_referral_order_income_loader_advertisers_returns_rows() -> (
    None
):
    """Advertiser loader returns rows with bloggers_needed=1."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4

    from ugc_bot.domain.entities import ReferralOrderIncomeRow
    from ugc_bot.infrastructure.db.repositories import (
        SqlReferralOrderIncomeLoader,
    )

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    row_data = SimpleNamespace(
        creator_created_at=now,
        order_completed_at=now,
        payment_amount=300.0,
        bloggers_needed=1,
        order_id=order_id,
    )
    session = FakeSession([row_data])
    loader = SqlReferralOrderIncomeLoader(session_factory=lambda: session)
    rows = await loader.load_referral_order_income_rows_advertisers(
        referrer_id, limit=10, session=session
    )
    assert len(rows) == 1
    assert isinstance(rows[0], ReferralOrderIncomeRow)
    assert rows[0].payment_amount == 300.0
    assert rows[0].bloggers_needed == 1
    assert rows[0].order_id == order_id


@pytest.mark.asyncio
async def test_sql_referral_order_income_loader_combined_returns_rows() -> None:
    """SqlReferralOrderIncomeLoader.load_referral_order_income_rows_combined."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4

    from ugc_bot.domain.entities import ReferralOrderIncomeRow
    from ugc_bot.infrastructure.db.repositories import (
        SqlReferralOrderIncomeLoader,
    )

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    row_data = SimpleNamespace(
        creator_created_at=now,
        order_completed_at=now,
        payment_amount=50.0,
        bloggers_needed=1,
        order_id=order_id,
    )
    session = FakeSession([row_data])
    loader = SqlReferralOrderIncomeLoader(session_factory=lambda: session)
    rows = await loader.load_referral_order_income_rows_combined(
        referrer_id, limit=10, session=session
    )
    assert len(rows) == 1
    assert isinstance(rows[0], ReferralOrderIncomeRow)
    assert rows[0].payment_amount == 50.0
    assert rows[0].order_id == order_id


@pytest.mark.asyncio
async def test_sql_referral_order_income_loader_combined_batch() -> None:
    """SqlReferralOrderIncomeLoader.load_referral_order_income_rows_combined_batch."""
    from datetime import datetime, timezone
    from types import SimpleNamespace
    from uuid import uuid4

    from ugc_bot.domain.entities import ReferralOrderIncomeRow
    from ugc_bot.infrastructure.db.repositories import (
        SqlReferralOrderIncomeLoader,
    )

    referrer_id = uuid4()
    order_id = uuid4()
    now = datetime.now(timezone.utc)
    row_data = SimpleNamespace(
        referrer_user_id=referrer_id,
        creator_created_at=now,
        order_completed_at=now,
        payment_amount=50.0,
        bloggers_needed=1,
        order_id=order_id,
    )
    session = FakeSession([row_data])
    loader = SqlReferralOrderIncomeLoader(
        session_factory=lambda: FakeSession(None)
    )
    rows = await loader.load_referral_order_income_rows_combined_batch(
        [referrer_id], limit=None, session=session
    )
    assert len(rows) == 1
    assert rows[0][0] == referrer_id
    assert isinstance(rows[0][1], ReferralOrderIncomeRow)
    assert rows[0][1].payment_amount == 50.0
    assert rows[0][1].order_id == order_id


@pytest.mark.asyncio
async def test_sql_referral_order_income_loader_combined_batch_empty() -> None:
    """combined_batch with empty referrer_user_ids returns []."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlReferralOrderIncomeLoader,
    )

    loader = SqlReferralOrderIncomeLoader(
        session_factory=lambda: FakeSession(None)
    )
    rows = await loader.load_referral_order_income_rows_combined_batch(
        [], limit=None, session=FakeSession(None)
    )
    assert rows == []


@pytest.mark.asyncio
async def test_sqlalchemy_country_repo_list_enabled() -> None:
    """list_enabled returns enabled countries from the session."""
    from ugc_bot.infrastructure.db.models import CountryModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyCountryRepository,
    )

    model = CountryModel()
    model.code = "ru"
    model.name_native = "Россия"
    model.currency_code = "RUB"
    model.currency_symbol = "₽"
    model.enabled = True

    session = FakeSession([model])
    repo = SqlAlchemyCountryRepository(session_factory=_session_factory(None))
    result = await repo.list_enabled(session=session)
    assert len(result) == 1
    assert result[0].code == "ru"
    assert result[0].currency_code == "RUB"


@pytest.mark.asyncio
async def test_sqlalchemy_country_repo_get_by_code_found() -> None:
    """get_by_code returns country when found."""
    from ugc_bot.infrastructure.db.models import CountryModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyCountryRepository,
    )

    model = CountryModel()
    model.code = "ge"
    model.name_native = "საქართველო"
    model.currency_code = "GEL"
    model.currency_symbol = "₾"
    model.enabled = True

    session = FakeSession(model)
    repo = SqlAlchemyCountryRepository(session_factory=_session_factory(None))
    result = await repo.get_by_code("ge", session=session)
    assert result is not None
    assert result.code == "ge"
    assert result.currency_symbol == "₾"


@pytest.mark.asyncio
async def test_sqlalchemy_country_repo_get_by_code_not_found() -> None:
    """get_by_code returns None when country not found."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyCountryRepository,
    )

    session = FakeSession(None)
    repo = SqlAlchemyCountryRepository(session_factory=_session_factory(None))
    result = await repo.get_by_code("zz", session=session)
    assert result is None


@pytest.mark.asyncio
async def test_sqlalchemy_language_repo_list_enabled() -> None:
    """list_enabled returns enabled languages from the session."""
    from ugc_bot.infrastructure.db.models import LanguageModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyLanguageRepository,
    )

    model = LanguageModel()
    model.code = "ru"
    model.name_native = "Русский"
    model.enabled = True

    session = FakeSession([model])
    repo = SqlAlchemyLanguageRepository(session_factory=_session_factory(None))
    result = await repo.list_enabled(session=session)
    assert len(result) == 1
    assert result[0].code == "ru"
    assert result[0].name_native == "Русский"


@pytest.mark.asyncio
async def test_sqlalchemy_language_repo_get_by_code_found() -> None:
    """get_by_code returns language when found."""
    from ugc_bot.infrastructure.db.models import LanguageModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyLanguageRepository,
    )

    model = LanguageModel()
    model.code = "en"
    model.name_native = "English"
    model.enabled = True

    session = FakeSession(model)
    repo = SqlAlchemyLanguageRepository(session_factory=_session_factory(None))
    result = await repo.get_by_code("en", session=session)
    assert result is not None
    assert result.code == "en"
    assert result.name_native == "English"


@pytest.mark.asyncio
async def test_sqlalchemy_language_repo_get_by_code_not_found() -> None:
    """get_by_code returns None when language not found."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyLanguageRepository,
    )

    session = FakeSession(None)
    repo = SqlAlchemyLanguageRepository(session_factory=_session_factory(None))
    result = await repo.get_by_code("zz", session=session)
    assert result is None


@pytest.mark.asyncio
async def test_sqlalchemy_language_repo_list_enabled_no_session() -> None:
    """list_enabled uses session_factory when no session is provided."""
    from ugc_bot.infrastructure.db.models import LanguageModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyLanguageRepository,
    )

    model = LanguageModel()
    model.code = "en"
    model.name_native = "English"
    model.enabled = True

    repo = SqlAlchemyLanguageRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.list_enabled(session=None)
    assert len(result) == 1
    assert result[0].code == "en"


# ---------------------------------------------------------------------------
# SqlAlchemyManagerOrderRepository tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manager_order_repo_list_by_order_returns_entities() -> None:
    """list_by_order maps ORM models to ManagerOrder entities."""
    from ugc_bot.domain.entities import ManagerOrder
    from ugc_bot.infrastructure.db.models import ManagerOrderModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    order_id = UUID("00000000-0000-0000-0000-000000000001")
    user_id = UUID("00000000-0000-0000-0000-000000000002")
    now = datetime.now(timezone.utc)
    model = ManagerOrderModel(
        user_id=user_id,
        order_id=order_id,
        created_at=now,
        updated_at=None,
    )
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.list_by_order(order_id, session=_repo_session(repo))
    assert len(result) == 1
    assert isinstance(result[0], ManagerOrder)
    assert result[0].order_id == order_id
    assert result[0].user_id == user_id


@pytest.mark.asyncio
async def test_manager_order_repo_list_by_order_empty() -> None:
    """list_by_order returns empty list when there are no assignments."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    order_id = UUID("00000000-0000-0000-0000-000000000010")
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory([])
    )
    result = await repo.list_by_order(order_id, session=_repo_session(repo))
    assert result == []


@pytest.mark.asyncio
async def test_manager_order_repo_list_by_order_no_session() -> None:
    """list_by_order uses session_factory when no session is provided."""
    from ugc_bot.domain.entities import ManagerOrder
    from ugc_bot.infrastructure.db.models import ManagerOrderModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    order_id = UUID("00000000-0000-0000-0000-000000000003")
    user_id = UUID("00000000-0000-0000-0000-000000000004")
    now = datetime.now(timezone.utc)
    model = ManagerOrderModel(
        user_id=user_id,
        order_id=order_id,
        created_at=now,
        updated_at=None,
    )
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.list_by_order(order_id, session=None)
    assert len(result) == 1
    assert isinstance(result[0], ManagerOrder)


@pytest.mark.asyncio
async def test_manager_order_repo_list_by_user_returns_entities() -> None:
    """list_by_user maps ORM models to ManagerOrder entities."""
    from ugc_bot.domain.entities import ManagerOrder
    from ugc_bot.infrastructure.db.models import ManagerOrderModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000005")
    order_id = UUID("00000000-0000-0000-0000-000000000006")
    now = datetime.now(timezone.utc)
    model = ManagerOrderModel(
        user_id=user_id,
        order_id=order_id,
        created_at=now,
        updated_at=now,
    )
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.list_by_user(user_id, session=_repo_session(repo))
    assert len(result) == 1
    assert isinstance(result[0], ManagerOrder)
    assert result[0].user_id == user_id
    assert result[0].updated_at == now


@pytest.mark.asyncio
async def test_manager_order_repo_list_by_user_empty() -> None:
    """list_by_user returns empty list when no assignments exist for user."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000020")
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory([])
    )
    result = await repo.list_by_user(user_id, session=_repo_session(repo))
    assert result == []


@pytest.mark.asyncio
async def test_manager_order_repo_list_order_ids_by_user() -> None:
    """list_order_ids_by_user returns a list of UUID order IDs."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    order_id = UUID("00000000-0000-0000-0000-000000000007")
    user_id = UUID("00000000-0000-0000-0000-000000000008")
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory([order_id])
    )
    result = await repo.list_order_ids_by_user(
        user_id, session=_repo_session(repo)
    )
    assert result == [order_id]


@pytest.mark.asyncio
async def test_manager_order_repo_list_order_ids_by_user_empty() -> None:
    """list_order_ids_by_user returns empty list when no assignments exist."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000030")
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory([])
    )
    result = await repo.list_order_ids_by_user(
        user_id, session=_repo_session(repo)
    )
    assert result == []


@pytest.mark.asyncio
async def test_manager_order_repo_count_by_user_nonzero() -> None:
    """count_by_user returns the integer count from the scalar result."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000009")
    repo = SqlAlchemyManagerOrderRepository(session_factory=_session_factory(3))
    count = await repo.count_by_user(user_id, session=_repo_session(repo))
    assert count == 3


@pytest.mark.asyncio
async def test_manager_order_repo_count_by_user_zero() -> None:
    """count_by_user returns 0 when no assignments exist."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000040")
    repo = SqlAlchemyManagerOrderRepository(session_factory=_session_factory(0))
    count = await repo.count_by_user(user_id, session=_repo_session(repo))
    assert count == 0


@pytest.mark.asyncio
async def test_manager_order_repo_save_merges_model() -> None:
    """save merges a ManagerOrderModel into the session."""
    from ugc_bot.domain.entities import ManagerOrder
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000011")
    order_id = UUID("00000000-0000-0000-0000-000000000012")
    now = datetime.now(timezone.utc)
    entity = ManagerOrder(
        user_id=user_id,
        order_id=order_id,
        created_at=now,
        updated_at=None,
    )
    session = FakeSession(None)
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory(None)
    )
    await repo.save(entity, session=session)
    assert session.merged is not None
    assert session.merged.user_id == user_id
    assert session.merged.order_id == order_id
    assert session.merged.created_at == now
    assert session.merged.updated_at is None


@pytest.mark.asyncio
async def test_manager_order_repo_save_with_updated_at() -> None:
    """save persists updated_at when it is set on the entity."""
    from ugc_bot.domain.entities import ManagerOrder
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000013")
    order_id = UUID("00000000-0000-0000-0000-000000000014")
    now = datetime.now(timezone.utc)
    updated = now + timedelta(hours=1)
    entity = ManagerOrder(
        user_id=user_id,
        order_id=order_id,
        created_at=now,
        updated_at=updated,
    )
    session = FakeSession(None)
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory(None)
    )
    await repo.save(entity, session=session)
    assert session.merged.updated_at == updated


@pytest.mark.asyncio
async def test_manager_order_repo_delete_by_order_executes_delete() -> None:
    """delete_by_order executes a DELETE statement without raising."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    order_id = UUID("00000000-0000-0000-0000-000000000015")
    session = FakeSession(None)
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory(None)
    )
    # Should complete without error; FakeSession records execute calls.
    await repo.delete_by_order(order_id, session=session)


@pytest.mark.asyncio
async def test_manager_order_repo_delete_by_order_no_session() -> None:
    """delete_by_order uses session_factory when no session is provided."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    order_id = UUID("00000000-0000-0000-0000-000000000050")
    repo = SqlAlchemyManagerOrderRepository(
        session_factory=_session_factory(None)
    )
    await repo.delete_by_order(order_id, session=None)


@pytest.mark.asyncio
async def test_manager_order_repo_exists_for_user_true() -> None:
    """exists_for_user returns True when count > 0."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000016")
    repo = SqlAlchemyManagerOrderRepository(session_factory=_session_factory(2))
    exists = await repo.exists_for_user(user_id, session=_repo_session(repo))
    assert exists is True


@pytest.mark.asyncio
async def test_manager_order_repo_exists_for_user_false() -> None:
    """exists_for_user returns False when count is 0."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000017")
    repo = SqlAlchemyManagerOrderRepository(session_factory=_session_factory(0))
    exists = await repo.exists_for_user(user_id, session=_repo_session(repo))
    assert exists is False


@pytest.mark.asyncio
async def test_manager_order_repo_exists_for_user_no_session() -> None:
    """exists_for_user uses session_factory when no session is provided."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyManagerOrderRepository,
    )

    user_id = UUID("00000000-0000-0000-0000-000000000060")
    repo = SqlAlchemyManagerOrderRepository(session_factory=_session_factory(1))
    exists = await repo.exists_for_user(user_id, session=None)
    assert exists is True


# ---------------------------------------------------------------------------
# _resolve_session, _require_session, _get_async_session helpers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_session_rollback_on_error() -> None:
    """_resolve_session rolls back and closes on error."""
    from ugc_bot.infrastructure.db.repositories import _resolve_session

    class ErrorSession(FakeSession):
        rollback_called = False
        close_called = False

        async def rollback(self) -> None:  # type: ignore[override]
            self.rollback_called = True

        async def close(self) -> None:  # type: ignore[override]
            self.close_called = True

    sess = ErrorSession(None)
    with pytest.raises(ValueError):
        async with _resolve_session(lambda: sess) as _:
            raise ValueError("test error")
    assert sess.rollback_called
    assert sess.close_called


@pytest.mark.asyncio
async def test_require_session_still_raises() -> None:
    """_require_session raises RuntimeError when session is None."""
    from ugc_bot.infrastructure.db.repositories import _require_session

    with pytest.raises(RuntimeError, match="session is required"):
        _require_session(None)


@pytest.mark.asyncio
async def test_get_async_session_none_raises() -> None:
    """_get_async_session raises RuntimeError when session is None."""
    from ugc_bot.infrastructure.db.repositories import _get_async_session

    with pytest.raises(RuntimeError):
        _get_async_session(None)


# ---------------------------------------------------------------------------
# Coverage gap fill: existing repos missing tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_blogger_profile_repo_get_by_user_ids_nonempty() -> None:
    """get_by_user_ids returns a dict keyed by user_id."""
    user_id = UUID("00000000-0000-0000-0000-000000000701")
    model = BloggerProfileModel(
        user_id=user_id,
        instagram_url="https://instagram.com/u1",
        confirmed=False,
        city="Moscow",
        topics={"selected": []},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=500.0,
        barter=False,
        work_format=WorkFormat.UGC_ONLY,
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyBloggerProfileRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.get_by_user_ids([user_id], session=_repo_session(repo))
    assert user_id in result
    assert result[user_id].instagram_url == "https://instagram.com/u1"


@pytest.mark.asyncio
async def test_instagram_stats_repo_get_by_user_ids_nonempty() -> None:
    """get_by_user_ids returns a dict of InstagramStats keyed by user_id."""
    user_id = UUID("00000000-0000-0000-0000-000000000702")
    model = InstagramStatsModel(
        user_id=user_id,
        raw_response={},
        fetched_at=datetime.now(timezone.utc),
        followers_count=1000,
        follows_count=200,
        media_count=50,
        provider="rapid_api",
    )
    repo = SqlAlchemyInstagramStatsRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.get_by_user_ids([user_id], session=_repo_session(repo))
    assert user_id in result
    assert result[user_id].followers_count == 1000


@pytest.mark.asyncio
async def test_order_repo_get_by_ids_nonempty() -> None:
    """get_by_ids returns a list of Order entities in IDs order."""
    order_id = UUID("00000000-0000-0000-0000-000000000703")
    model = OrderModel(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000704"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Test",
        barter_description="Barter",
        price=0.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyOrderRepository(session_factory=_session_factory([model]))
    result = await repo.get_by_ids([order_id], session=_repo_session(repo))
    assert len(result) == 1
    assert result[0].order_id == order_id


@pytest.mark.asyncio
async def test_bot_texts_repo_get_returns_value() -> None:
    """get returns the text value when key and locale match."""
    from ugc_bot.infrastructure.db.models import BotTextModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyBotTextsRepository,
    )

    model = BotTextModel(
        key="welcome",
        locale="ru",
        value="Добро пожаловать",
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyBotTextsRepository(session_factory=_session_factory(model))
    value = await repo.get("welcome", "ru", session=_repo_session(repo))
    assert value == "Добро пожаловать"


@pytest.mark.asyncio
async def test_bot_texts_repo_get_returns_none_when_missing() -> None:
    """get returns None when no row is found."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyBotTextsRepository,
    )

    repo = SqlAlchemyBotTextsRepository(session_factory=_session_factory(None))
    value = await repo.get("nonexistent", "en", session=_repo_session(repo))
    assert value is None


@pytest.mark.asyncio
async def test_bot_texts_repo_get_all_returns_tuples() -> None:
    """get_all returns list of (key, locale, value) tuples."""
    from ugc_bot.infrastructure.db.models import BotTextModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyBotTextsRepository,
    )

    model = BotTextModel(
        key="greeting",
        locale="en",
        value="Hello",
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyBotTextsRepository(
        session_factory=_session_factory([model])
    )
    rows = await repo.get_all(session=_repo_session(repo))
    assert rows == [("greeting", "en", "Hello")]


@pytest.mark.asyncio
async def test_offer_dispatch_repo_list_responses_in_offer_only() -> None:
    """list_responses_by_blogger with in_offer_only=True appends the filter."""
    blogger_id = UUID("00000000-0000-0000-0000-000000000705")
    model = OfferDispatchModel(
        order_id=UUID("00000000-0000-0000-0000-000000000706"),
        blogger_id=blogger_id,
        created_at=datetime.now(timezone.utc),
        accepted=True,
        in_offer=True,
    )
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.list_responses_by_blogger(
        blogger_id, session=_repo_session(repo), in_offer_only=True
    )
    assert len(result) == 1
    assert result[0].in_offer is True


@pytest.mark.asyncio
async def test_offer_dispatch_repo_list_responses_by_order_and_manager() -> (
    None
):
    """list_responses_by_order_and_manager returns mapped entities."""
    order_id = UUID("00000000-0000-0000-0000-000000000707")
    manager_id = UUID("00000000-0000-0000-0000-000000000708")
    blogger_id = UUID("00000000-0000-0000-0000-000000000709")
    now = datetime.now(timezone.utc)
    model = OfferDispatchModel(
        order_id=order_id,
        blogger_id=blogger_id,
        created_at=now,
        accepted=True,
        in_offer=True,
        manager_id=manager_id,
    )
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.list_responses_by_order_and_manager(
        order_id=order_id,
        manager_id=manager_id,
        in_offer=True,
        session=_repo_session(repo),
    )
    assert len(result) == 1
    assert result[0].order_id == order_id
    assert result[0].manager_id == manager_id


@pytest.mark.asyncio
async def test_offer_dispatch_repo_list_responses_by_manager_none() -> None:
    """list_responses_by_order_and_manager with manager_id=None returns all."""
    order_id = UUID("00000000-0000-0000-0000-000000000710")
    blogger_id = UUID("00000000-0000-0000-0000-000000000711")
    model = OfferDispatchModel(
        order_id=order_id,
        blogger_id=blogger_id,
        created_at=datetime.now(timezone.utc),
        accepted=True,
        in_offer=False,
    )
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory([model])
    )
    result = await repo.list_responses_by_order_and_manager(
        order_id=order_id,
        manager_id=None,
        in_offer=False,
        session=_repo_session(repo),
    )
    assert len(result) == 1


@pytest.mark.asyncio
async def test_offer_dispatch_repo_count_responses_by_order_and_manager() -> (
    None
):
    """count_responses_by_order_and_manager returns scalar count."""
    order_id = UUID("00000000-0000-0000-0000-000000000712")
    manager_id = UUID("00000000-0000-0000-0000-000000000713")
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory(5)
    )
    count = await repo.count_responses_by_order_and_manager(
        order_id=order_id,
        manager_id=manager_id,
        in_offer=True,
        session=_repo_session(repo),
    )
    assert count == 5


@pytest.mark.asyncio
async def test_offer_dispatch_repo_count_responses_manager_none() -> None:
    """count_responses_by_order_and_manager with manager_id=None counts all."""
    order_id = UUID("00000000-0000-0000-0000-000000000714")
    repo = SqlAlchemyOfferDispatchRepository(
        session_factory=_session_factory(3)
    )
    count = await repo.count_responses_by_order_and_manager(
        order_id=order_id,
        manager_id=None,
        in_offer=False,
        session=_repo_session(repo),
    )
    assert count == 3


@pytest.mark.asyncio
async def test_outbox_repo_reset_stale_processing_returns_count() -> None:
    """reset_stale_processing_events returns the rowcount from execute."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyOutboxRepository,
    )

    class RowcountResult:
        rowcount = 3

    class RowcountSession(FakeSession):
        async def execute(self, *_args, **_kwargs):
            return RowcountResult()

    sess = RowcountSession(None)
    repo = SqlAlchemyOutboxRepository(session_factory=_session_factory(None))
    result = await repo.reset_stale_processing_events(
        stale_after_minutes=15, session=sess
    )
    assert result == 3


@pytest.mark.asyncio
async def test_outbox_repo_reset_stale_processing_no_rowcount() -> None:
    """reset_stale_processing_events returns 0 when rowcount is absent."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyOutboxRepository,
    )

    class NoRowcountResult:
        pass

    class NoRowcountSession(FakeSession):
        async def execute(self, *_args, **_kwargs):
            return NoRowcountResult()

    sess = NoRowcountSession(None)
    repo = SqlAlchemyOutboxRepository(session_factory=_session_factory(None))
    result = await repo.reset_stale_processing_events(
        stale_after_minutes=15, session=sess
    )
    assert result == 0


@pytest.mark.asyncio
async def test_country_repo_get_by_currency_code_found() -> None:
    """get_by_currency_code returns Country when a matching row exists."""
    from ugc_bot.infrastructure.db.models import CountryModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyCountryRepository,
    )

    model = CountryModel()
    model.code = "RU"
    model.name_native = "Россия"
    model.currency_code = "RUB"
    model.currency_symbol = "₽"
    model.locale = "ru"
    model.enabled = True

    repo = SqlAlchemyCountryRepository(session_factory=_session_factory(model))
    result = await repo.get_by_currency_code("RUB", session=_repo_session(repo))
    assert result is not None
    assert result.currency_code == "RUB"
    assert result.code == "RU"


@pytest.mark.asyncio
async def test_country_repo_get_by_currency_code_not_found() -> None:
    """get_by_currency_code returns None when no matching country."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyCountryRepository,
    )

    repo = SqlAlchemyCountryRepository(session_factory=_session_factory(None))
    result = await repo.get_by_currency_code("XYZ", session=_repo_session(repo))
    assert result is None


@pytest.mark.asyncio
async def test_country_repo_execute_in_session_no_session() -> None:
    """_execute_in_session uses session_factory when session=None."""
    from ugc_bot.infrastructure.db.models import CountryModel
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyCountryRepository,
    )

    model = CountryModel()
    model.code = "GE"
    model.name_native = "Georgia"
    model.currency_code = "GEL"
    model.currency_symbol = "₾"
    model.locale = "en"
    model.enabled = True

    repo = SqlAlchemyCountryRepository(session_factory=_session_factory(model))
    # Passing session=None forces _execute_in_session to use session_factory
    result = await repo.get_by_currency_code("GEL", session=None)
    assert result is not None
    assert result.code == "GE"


@pytest.mark.asyncio
async def test_payout_request_get_paid_totals_by_currency() -> None:
    """get_paid_totals_by_currency returns dict keyed by currency."""
    user_id = UUID("00000000-0000-0000-0000-000000000800")
    result = [
        ("RUB", Decimal("100.00")),
        ("GEL", Decimal("50.00")),
    ]
    repo = SqlAlchemyPayoutRequestRepository(
        session_factory=_session_factory(result)
    )
    totals = await repo.get_paid_totals_by_currency(
        user_id, session=_repo_session(repo)
    )
    assert totals == {
        "RUB": Decimal("100.00"),
        "GEL": Decimal("50.00"),
    }


@pytest.mark.asyncio
async def test_payout_request_get_pending_totals_by_currency() -> None:
    """get_pending_totals_by_currency returns dict keyed by currency."""
    user_id = UUID("00000000-0000-0000-0000-000000000801")
    result = [
        ("RUB", Decimal("200.00")),
        ("USD", Decimal("75.00")),
    ]
    repo = SqlAlchemyPayoutRequestRepository(
        session_factory=_session_factory(result)
    )
    totals = await repo.get_pending_totals_by_currency(
        user_id, session=_repo_session(repo)
    )
    assert totals == {
        "RUB": Decimal("200.00"),
        "USD": Decimal("75.00"),
    }


@pytest.mark.asyncio
async def test_payout_request_has_request_today_by_currency() -> None:
    """has_request_today_by_currency returns dict of currency -> True."""
    user_id = UUID("00000000-0000-0000-0000-000000000802")
    result = [("RUB",), ("USD",)]
    repo = SqlAlchemyPayoutRequestRepository(
        session_factory=_session_factory(result)
    )
    today = await repo.has_request_today_by_currency(
        user_id, session=_repo_session(repo)
    )
    assert today == {"RUB": True, "USD": True}


@pytest.mark.asyncio
async def test_referral_income_entry_save() -> None:
    """ReferralIncomeEntry repo save executes without error."""
    entry_id = UUID("00000000-0000-0000-0000-000000000803")
    referrer_id = UUID("00000000-0000-0000-0000-000000000804")
    referred_id = UUID("00000000-0000-0000-0000-000000000805")
    order_id = UUID("00000000-0000-0000-0000-000000000806")
    now = datetime.now(timezone.utc)
    entry = ReferralIncomeEntry(
        entry_id=entry_id,
        referrer_user_id=referrer_id,
        referred_user_id=referred_id,
        order_id=order_id,
        income_type=ReferralIncomeType.CREATOR,
        currency="RUB",
        platform_revenue=Decimal("1000"),
        commission_rate=Decimal("0.10"),
        commission_amount=Decimal("100"),
        created_at=now,
    )
    repo = SqlAlchemyReferralIncomeEntryRepository(
        session_factory=_session_factory(None)
    )
    await repo.save(entry, session=_repo_session(repo))


@pytest.mark.asyncio
async def test_referral_income_entry_get_totals_by_currency() -> None:
    """get_totals_by_currency returns dict keyed by currency."""
    referrer_id = UUID("00000000-0000-0000-0000-000000000807")
    result = [("RUB", Decimal("500.00"))]
    repo = SqlAlchemyReferralIncomeEntryRepository(
        session_factory=_session_factory(result)
    )
    totals = await repo.get_totals_by_currency(
        referrer_id, session=_repo_session(repo)
    )
    assert totals == {"RUB": Decimal("500.00")}


@pytest.mark.asyncio
async def test_referral_income_entry_get_orders_count_by_currency() -> None:
    """get_orders_count_by_currency returns dict keyed by currency."""
    referrer_id = UUID("00000000-0000-0000-0000-000000000808")
    result = [("RUB", 3), ("GEL", 1)]
    repo = SqlAlchemyReferralIncomeEntryRepository(
        session_factory=_session_factory(result)
    )
    counts = await repo.get_orders_count_by_currency(
        referrer_id, session=_repo_session(repo)
    )
    assert counts == {"RUB": 3, "GEL": 1}


@pytest.mark.asyncio
async def test_referral_income_entry_get_current_month_totals() -> None:
    """get_current_month_totals_by_currency returns dict keyed by currency."""
    referrer_id = UUID("00000000-0000-0000-0000-000000000809")
    result = [("RUB", Decimal("200.00"))]
    repo = SqlAlchemyReferralIncomeEntryRepository(
        session_factory=_session_factory(result)
    )
    totals = await repo.get_current_month_totals_by_currency(
        referrer_id, session=_repo_session(repo)
    )
    assert totals == {"RUB": Decimal("200.00")}
