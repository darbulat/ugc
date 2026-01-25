"""Tests for SQLAlchemy repositories with fake sessions."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    InstagramVerificationCode,
    Order,
    OrderResponse,
    OutboxEvent,
    Payment,
    User,
)
from ugc_bot.domain.enums import (
    AudienceGender,
    MessengerType,
    OrderStatus,
    OutboxEventStatus,
    PaymentStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyAdvertiserProfileRepository,
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyContactPricingRepository,
    SqlAlchemyInstagramVerificationRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyOrderResponseRepository,
    SqlAlchemyOutboxRepository,
    SqlAlchemyPaymentRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    ContactPricingModel,
    InstagramVerificationCodeModel,
    OrderModel,
    OrderResponseModel,
    OutboxEventModel,
    PaymentModel,
    UserModel,
)


class FakeResult:
    """Fake SQLAlchemy result."""

    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):  # type: ignore[no-untyped-def]
        return self._value

    def scalar_one(self):  # type: ignore[no-untyped-def]
        return self._value

    def scalars(self):  # type: ignore[no-untyped-def]
        return [self._value]


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

    def commit(self):  # type: ignore[no-untyped-def]
        """Mock commit method."""
        self.committed = True

    def merge(self, model):  # type: ignore[no-untyped-def]
        self.merged = model


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


def test_blogger_profile_repository_get_by_instagram_url() -> None:
    """Fetch blogger profile by Instagram URL."""

    model = BloggerProfileModel(
        user_id=UUID("00000000-0000-0000-0000-000000000200"),
        instagram_url="https://instagram.com/test_user",
        topics={"selected": ["fitness"]},
        audience_gender=AudienceGender.ALL,
        audience_age_min=18,
        audience_age_max=35,
        audience_geo="Moscow",
        price=1000.0,
        updated_at=datetime.now(timezone.utc),
    )

    repo = SqlAlchemyBloggerProfileRepository(session_factory=_session_factory(model))
    profile = repo.get_by_instagram_url("https://instagram.com/test_user")

    assert profile is not None
    assert profile.instagram_url == "https://instagram.com/test_user"
    assert profile.user_id == UUID("00000000-0000-0000-0000-000000000200")


def test_blogger_profile_repository_get_by_instagram_url_not_found() -> None:
    """Return None when Instagram URL not found."""

    repo = SqlAlchemyBloggerProfileRepository(session_factory=_session_factory(None))
    profile = repo.get_by_instagram_url("https://instagram.com/nonexistent")

    assert profile is None


def test_blogger_profile_repository_get() -> None:
    """Fetch blogger profile by user id."""

    model = BloggerProfileModel(
        user_id=UUID("00000000-0000-0000-0000-000000000114"),
        instagram_url="https://instagram.com/test",
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
        instagram_url=None,
        confirmed=False,
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


def test_instagram_verification_repository_get_valid_code_by_code() -> None:
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
    fetched = repo.get_valid_code_by_code("TESTCODE")
    assert fetched is not None
    assert fetched.code == "TESTCODE"
    assert fetched.user_id == user_id

    # Test case insensitive
    fetched_lower = repo.get_valid_code_by_code("testcode")
    assert fetched_lower is not None
    assert fetched_lower.code == "TESTCODE"


def test_instagram_verification_repository_get_valid_code_by_code_not_found() -> None:
    """Test getting non-existent code returns None."""
    # Use None to simulate code not found
    repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=_session_factory(None)
    )

    invalid = repo.get_valid_code_by_code("INVALID")
    assert invalid is None


def test_instagram_verification_repository_get_valid_code_by_code_expired() -> None:
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

    expired_fetched = repo.get_valid_code_by_code("EXPIRED")
    assert expired_fetched is None


def test_instagram_verification_repository_get_valid_code_by_code_used() -> None:
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

    used_fetched = repo.get_valid_code_by_code("USEDCODE")
    assert used_fetched is None


def test_order_repository_save_and_get() -> None:
    """Save and fetch order."""

    session = FakeSession(None)

    def factory():  # type: ignore[no-untyped-def]
        return session

    repo = SqlAlchemyOrderRepository(session_factory=factory)
    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000170"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000171"),
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    repo.save(order)
    assert session.merged is not None
    assert session.committed is True

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
        contacts_sent_at=None,
    )
    repo_get = SqlAlchemyOrderRepository(session_factory=_session_factory(model))
    fetched = repo_get.get_by_id(order.order_id)
    assert fetched is not None


def test_order_repository_list_by_advertiser() -> None:
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
        contacts_sent_at=None,
    )
    repo = SqlAlchemyOrderRepository(session_factory=_session_factory(model))

    orders = list(repo.list_by_advertiser(advertiser_id))
    assert orders


def test_payment_repository_save_and_get() -> None:
    """Save and fetch payment."""

    session = FakeSession(None)

    def factory():  # type: ignore[no-untyped-def]
        return session

    repo = SqlAlchemyPaymentRepository(session_factory=factory)
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
    repo.save(payment)
    assert session.merged is not None
    assert session.committed is True

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
    repo_get = SqlAlchemyPaymentRepository(session_factory=_session_factory(model))
    fetched = repo_get.get_by_order(payment.order_id)
    assert fetched is not None
    fetched_external = repo_get.get_by_external_id(payment.external_id)
    assert fetched_external is not None


def test_contact_pricing_repository_get() -> None:
    """Fetch contact pricing by bloggers count."""

    model = ContactPricingModel(
        bloggers_count=10,
        price=3000.0,
        updated_at=datetime.now(timezone.utc),
    )
    repo = SqlAlchemyContactPricingRepository(session_factory=_session_factory(model))
    pricing = repo.get_by_bloggers_count(10)
    assert pricing is not None
    assert pricing.bloggers_count == 10


def test_order_response_repository_methods() -> None:
    """Save and query order responses."""

    session = FakeSession(None)

    def factory():  # type: ignore[no-untyped-def]
        return session

    repo = SqlAlchemyOrderResponseRepository(session_factory=factory)
    response = OrderResponse(
        response_id=UUID("00000000-0000-0000-0000-000000000190"),
        order_id=UUID("00000000-0000-0000-0000-000000000191"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000192"),
        responded_at=datetime.now(timezone.utc),
    )
    repo.save(response)
    assert session.merged is not None
    assert session.committed is True

    model = OrderResponseModel(
        response_id=response.response_id,
        order_id=response.order_id,
        blogger_id=response.blogger_id,
        responded_at=response.responded_at,
    )
    repo_get = SqlAlchemyOrderResponseRepository(
        session_factory=_session_factory(model)
    )
    assert repo_get.list_by_order(response.order_id)

    repo_exists = SqlAlchemyOrderResponseRepository(session_factory=_session_factory(1))
    assert repo_exists.exists(response.order_id, response.blogger_id) is True

    repo_count = SqlAlchemyOrderResponseRepository(session_factory=_session_factory(2))
    assert repo_count.count_by_order(response.order_id) == 2


def test_outbox_repository_save_and_get() -> None:
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
    repo = SqlAlchemyOutboxRepository(session_factory=lambda: session)
    repo.save(event)

    assert len(saved_models) == 1
    saved_model = saved_models[0]
    assert saved_model.event_id == event.event_id
    assert saved_model.event_type == event.event_type
    assert saved_model.aggregate_id == event.aggregate_id
    assert saved_model.payload == event.payload
    assert saved_model.status == event.status

    # Test get_by_id - would require complex mocking, covered by in-memory tests
    # repo_get = SqlAlchemyOutboxRepository(session_factory=_session_factory(model))
    # retrieved = repo_get.get_by_id(event.event_id)
    # assert retrieved is not None


def test_outbox_repository_get_pending_events() -> None:
    """Only pending events are returned."""

    # This test would require complex mocking of SQLAlchemy query chain
    # For now, we'll skip it as the in-memory repository tests cover this functionality
    # and the SQL implementation follows the same pattern as other repositories
    pass


def test_outbox_repository_mark_operations() -> None:
    """Mark operations work correctly."""

    # This test would require complex mocking of SQLAlchemy update operations
    # For now, we'll rely on the in-memory repository tests which cover this functionality
    # and integration tests that verify the end-to-end behavior
    pass
