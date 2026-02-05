"""Tests for SQLAlchemy repositories with fake sessions."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import UUID

import pytest

from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    Complaint,
    FsmDraft,
    InstagramVerificationCode,
    Interaction,
    Order,
    OrderResponse,
    OutboxEvent,
    Payment,
    User,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    ComplaintStatus,
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    OutboxEventStatus,
    PaymentStatus,
    UserStatus,
    WorkFormat,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ComplaintModel,
    ContactPricingModel,
    FsmDraftModel,
    InstagramVerificationCodeModel,
    InteractionModel,
    OrderModel,
    OrderResponseModel,
    OutboxEventModel,
    PaymentModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyComplaintRepository,
    SqlAlchemyContactPricingRepository,
    SqlAlchemyFsmDraftRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyInteractionRepository,
    SqlAlchemyNpsRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOrderResponseRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyUserRepository,
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

    def __init__(self, value) -> None:
        self._value = value

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

    async def merge(self, model):  # type: ignore[no-untyped-def]
        self.merged = model

    async def delete(self, model):  # type: ignore[no-untyped-def]
        """Mock delete for FSM draft repo."""
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
async def test_fsm_draft_repository_get_returns_draft() -> None:
    """Fetch FSM draft by user_id and flow_type returns deserialized draft."""

    user_id = UUID("00000000-0000-0000-0000-000000000501")
    model = FsmDraftModel(
        user_id=user_id,
        flow_type="blogger_registration",
        state_key="BloggerRegistrationStates:city",
        data={"user_id": str(user_id), "nickname": "alice"},
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyFsmDraftRepository(session_factory=_session_factory(model))
    draft = await repo.get(
        user_id=user_id,
        flow_type="blogger_registration",
        session=_repo_session(repo),
    )
    assert draft is not None
    assert isinstance(draft, FsmDraft)
    assert draft.state_key == "BloggerRegistrationStates:city"
    assert draft.data.get("nickname") == "alice"


@pytest.mark.asyncio
async def test_fsm_draft_repository_get_returns_none() -> None:
    """Fetch FSM draft when none exists returns None."""

    user_id = UUID("00000000-0000-0000-0000-000000000502")
    repo = SqlAlchemyFsmDraftRepository(session_factory=_session_factory(None))
    draft = await repo.get(
        user_id=user_id,
        flow_type="order_creation",
        session=_repo_session(repo),
    )
    assert draft is None


@pytest.mark.asyncio
async def test_fsm_draft_repository_save_merges() -> None:
    """Save FSM draft merges model into session."""

    session = FakeSession(None)
    repo = SqlAlchemyFsmDraftRepository(
        session_factory=type(
            "Maker",
            (),
            {"__call__": lambda self: session},
        )()
    )
    user_id = UUID("00000000-0000-0000-0000-000000000503")
    await repo.save(
        user_id=user_id,
        flow_type="order_creation",
        state_key="OrderCreationStates:product_link",
        data={"user_id": user_id, "product_link": "https://x.com"},
        session=session,
    )
    assert session.merged is not None
    assert session.merged.user_id == user_id
    assert session.merged.flow_type == "order_creation"
    assert session.merged.data.get("product_link") == "https://x.com"


@pytest.mark.asyncio
async def test_fsm_draft_repository_delete_deletes_model() -> None:
    """Delete FSM draft calls session.delete when draft exists."""

    user_id = UUID("00000000-0000-0000-0000-000000000504")
    model = FsmDraftModel(
        user_id=user_id,
        flow_type="edit_profile",
        state_key="EditProfileStates:choosing_field",
        data={"edit_user_id": str(user_id)},
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyFsmDraftRepository(session_factory=_session_factory(model))
    session = _repo_session(repo)
    await repo.delete(
        user_id=user_id,
        flow_type="edit_profile",
        session=session,
    )
    assert session.deleted is not None
    assert session.deleted.flow_type == "edit_profile"


@pytest.mark.asyncio
async def test_fsm_draft_repository_delete_no_op_when_none() -> None:
    """Delete FSM draft does not call delete when no draft exists."""

    user_id = UUID("00000000-0000-0000-0000-000000000505")
    repo = SqlAlchemyFsmDraftRepository(session_factory=_session_factory(None))
    session = _repo_session(repo)
    await repo.delete(
        user_id=user_id,
        flow_type="order_creation",
        session=session,
    )
    assert session.deleted is None


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
        ugc_requirements=None,
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
        ugc_requirements=None,
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
        ugc_requirements=None,
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
        ugc_requirements=None,
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
        ugc_requirements=None,
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
        ugc_requirements=None,
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
async def test_payment_repository_rejects_invalid_session() -> None:
    """Payment repository rejects invalid session type."""

    repo = SqlAlchemyPaymentRepository(
        session_factory=lambda: FakeSession(None)
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
    with pytest.raises(RuntimeError):
        await repo.save(payment)


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
async def test_order_response_repository_methods() -> None:
    """Save and query order responses."""

    session = FakeSession(None)

    class FakeAsyncSessionMaker:
        def __init__(self, session):
            self._session = session

        def __call__(self):
            return self._session

    repo = SqlAlchemyOrderResponseRepository(
        session_factory=FakeAsyncSessionMaker(session)
    )
    response = OrderResponse(
        response_id=UUID("00000000-0000-0000-0000-000000000190"),
        order_id=UUID("00000000-0000-0000-0000-000000000191"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000192"),
        responded_at=datetime.now(timezone.utc),
    )
    await repo.save(response, session=session)
    assert session.merged is not None
    assert session.committed is False

    model = OrderResponseModel(
        response_id=response.response_id,
        order_id=response.order_id,
        blogger_id=response.blogger_id,
        responded_at=response.responded_at,
    )
    repo_get = SqlAlchemyOrderResponseRepository(
        session_factory=_session_factory(model)
    )
    responses = await repo_get.list_by_order(
        response.order_id, session=_repo_session(repo_get)
    )
    assert list(responses)

    repo_exists = SqlAlchemyOrderResponseRepository(
        session_factory=_session_factory(1)
    )
    assert (
        await repo_exists.exists(
            response.order_id,
            response.blogger_id,
            session=_repo_session(repo_exists),
        )
        is True
    )

    repo_count = SqlAlchemyOrderResponseRepository(
        session_factory=_session_factory(2)
    )
    assert (
        await repo_count.count_by_order(
            response.order_id, session=_repo_session(repo_count)
        )
        == 2
    )


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
async def test_outbox_repository_rejects_invalid_session() -> None:
    """Outbox repository rejects invalid session type."""

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
    with pytest.raises(RuntimeError):
        await repo.save(event)


@pytest.mark.asyncio
async def test_require_session_raises_when_no_session() -> None:
    """Calling repo method without session raises RuntimeError."""
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
    with pytest.raises(RuntimeError, match="session is required"):
        await repo.get_by_id(model.user_id)


@pytest.mark.asyncio
async def test_order_response_repository_list_by_blogger() -> None:
    """list_by_blogger returns responses for the blogger."""
    blogger_id = UUID("00000000-0000-0000-0000-000000000193")
    model = OrderResponseModel(
        response_id=UUID("00000000-0000-0000-0000-000000000194"),
        order_id=UUID("00000000-0000-0000-0000-000000000195"),
        blogger_id=blogger_id,
        responded_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyOrderResponseRepository(
        session_factory=_session_factory([model])
    )
    responses = list(
        await repo.list_by_blogger(blogger_id, session=_repo_session(repo))
    )
    assert len(responses) == 1
    assert responses[0].blogger_id == blogger_id


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


class FakeAsyncSessionCompat(FakeSession):
    """FakeSession passing isinstance(session, AsyncSession) when patched."""


@pytest.mark.asyncio
async def test_blogger_repository_list_confirmed_user_ids() -> None:
    """list_confirmed_user_ids returns confirmed blogger user ids."""
    user_id_1 = UUID("00000000-0000-0000-0000-000000000220")
    session = FakeAsyncSessionCompat([user_id_1])
    with patch(
        "ugc_bot.infrastructure.db.repositories.AsyncSession",
        FakeAsyncSessionCompat,
    ):
        repo = SqlAlchemyBloggerProfileRepository(
            session_factory=lambda: session  # type: ignore[return-value]
        )
        result = await repo.list_confirmed_user_ids(session=session)
    assert result == [user_id_1]


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
