"""Integration test fixtures for full user flows."""

import asyncio
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram import Bot, Dispatcher
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.infrastructure.db.session import SessionTransactionManager


@pytest.fixture(scope="session")
def test_database_url(tmp_path_factory) -> str:
    """SQLite database URL for tests."""
    # Use a file-based database to ensure tables persist across connections
    db_path = tmp_path_factory.mktemp("test_db") / "test.db"
    return f"sqlite:///{db_path}"


@pytest.fixture(scope="session")
def engine(test_database_url: str):
    """Create SQLAlchemy engine for tests."""
    # Import all models to ensure metadata is populated
    from ugc_bot.infrastructure.db import models  # noqa: F401

    engine = create_engine(test_database_url, echo=False)

    # Create all tables except those with JSONB fields (not compatible with SQLite)
    tables_to_exclude = {"outbox_events", "blogger_profiles"}
    tables_to_create = [
        table
        for table in Base.metadata.tables.values()
        if table.name not in tables_to_exclude
    ]
    Base.metadata.create_all(bind=engine, tables=tables_to_create)
    return engine


@pytest.fixture(scope="function")
def session_factory(
    engine, request: pytest.FixtureRequest
) -> Generator[object, None, None]:
    """Create session factory for tests."""
    session_factory = create_session_factory(str(engine.url))
    async_engine = session_factory.kw["bind"]

    def _dispose_engine() -> None:
        # Ensure any `aiosqlite` worker threads are stopped before interpreter shutdown.
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(async_engine.dispose())
        finally:
            loop.close()

    request.addfinalizer(_dispose_engine)
    yield session_factory


@pytest.fixture(scope="function")
def session(session_factory) -> Generator[Session, None, None]:
    """Create database session for tests."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def mock_bot() -> Bot:
    """Mock Bot instance for tests."""
    bot = MagicMock(spec=Bot)
    bot.send_message = AsyncMock()
    bot.send_invoice = AsyncMock()
    bot.answer = AsyncMock()
    return bot


@pytest.fixture(scope="function")
def config(test_database_url: str) -> AppConfig:
    """Test configuration."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token_123",
            "DATABASE_URL": test_database_url,
            "KAFKA_ENABLED": False,
            "FEEDBACK_ENABLED": False,
            "ADMIN_USERNAME": "test_admin",
            "ADMIN_PASSWORD": "test_pass",
            "ADMIN_SECRET": "test_secret",
            "TELEGRAM_PROVIDER_TOKEN": "test_provider_token",
        }
    )


@pytest.fixture(scope="function")
def dispatcher(session_factory, mock_bot: Bot, config: AppConfig) -> Dispatcher:
    """Create dispatcher with real services for integration tests."""
    # Build dispatcher without calling `build_dispatcher`, to avoid creating
    # an extra async engine / session_factory that is hard to dispose in tests.
    from aiogram.fsm.storage.memory import MemoryStorage

    storage = MemoryStorage()
    dispatcher = Dispatcher(storage=storage)
    dispatcher["config"] = config

    # Provide repositories/services wired to the test `session_factory`
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyUserRepository,
        SqlAlchemyOrderRepository,
        SqlAlchemyOrderResponseRepository,
        SqlAlchemyInteractionRepository,
        SqlAlchemyPaymentRepository,
        SqlAlchemyContactPricingRepository,
        SqlAlchemyComplaintRepository,
        SqlAlchemyOutboxRepository,
        SqlAlchemyBloggerProfileRepository,
        SqlAlchemyAdvertiserProfileRepository,
        SqlAlchemyInstagramVerificationRepository,
        NoopOfferBroadcaster,
    )

    # Replace session factories in all services
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    blogger_repo = SqlAlchemyBloggerProfileRepository(session_factory=session_factory)
    advertiser_repo = SqlAlchemyAdvertiserProfileRepository(
        session_factory=session_factory
    )
    instagram_repo = SqlAlchemyInstagramVerificationRepository(
        session_factory=session_factory
    )
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    order_response_repo = SqlAlchemyOrderResponseRepository(
        session_factory=session_factory
    )
    interaction_repo = SqlAlchemyInteractionRepository(session_factory=session_factory)
    payment_repo = SqlAlchemyPaymentRepository(session_factory=session_factory)
    pricing_repo = SqlAlchemyContactPricingRepository(session_factory=session_factory)
    complaint_repo = SqlAlchemyComplaintRepository(session_factory=session_factory)
    outbox_repo = SqlAlchemyOutboxRepository(session_factory=session_factory)

    transaction_manager = SessionTransactionManager(session_factory)
    dispatcher["transaction_manager"] = transaction_manager

    from ugc_bot.application.services.user_role_service import UserRoleService
    from ugc_bot.application.services.blogger_registration_service import (
        BloggerRegistrationService,
    )
    from ugc_bot.application.services.advertiser_registration_service import (
        AdvertiserRegistrationService,
    )
    from ugc_bot.application.services.instagram_verification_service import (
        InstagramVerificationService,
    )
    from ugc_bot.application.services.order_service import OrderService
    from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
    from ugc_bot.application.services.offer_response_service import OfferResponseService
    from ugc_bot.application.services.interaction_service import InteractionService
    from ugc_bot.application.services.payment_service import PaymentService
    from ugc_bot.application.services.contact_pricing_service import (
        ContactPricingService,
    )
    from ugc_bot.application.services.profile_service import ProfileService
    from ugc_bot.application.services.complaint_service import ComplaintService
    from ugc_bot.application.services.outbox_publisher import OutboxPublisher

    dispatcher["user_role_service"] = UserRoleService(
        user_repo=user_repo, transaction_manager=transaction_manager
    )
    dispatcher["blogger_registration_service"] = BloggerRegistrationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        transaction_manager=transaction_manager,
    )
    dispatcher["advertiser_registration_service"] = AdvertiserRegistrationService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        transaction_manager=transaction_manager,
    )
    dispatcher["instagram_verification_service"] = InstagramVerificationService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        verification_repo=instagram_repo,
        transaction_manager=transaction_manager,
    )
    dispatcher["order_service"] = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        transaction_manager=transaction_manager,
    )
    dispatcher["offer_dispatch_service"] = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
        transaction_manager=transaction_manager,
    )
    dispatcher["offer_response_service"] = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=transaction_manager,
    )
    dispatcher["interaction_service"] = InteractionService(
        interaction_repo=interaction_repo,
        transaction_manager=transaction_manager,
    )
    outbox_publisher = OutboxPublisher(outbox_repo=outbox_repo, order_repo=order_repo)
    dispatcher["payment_service"] = PaymentService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
        payment_repo=payment_repo,
        broadcaster=NoopOfferBroadcaster(),
        outbox_publisher=outbox_publisher,
        transaction_manager=transaction_manager,
    )
    dispatcher["contact_pricing_service"] = ContactPricingService(
        pricing_repo=pricing_repo,
        transaction_manager=transaction_manager,
    )
    dispatcher["profile_service"] = ProfileService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        advertiser_repo=advertiser_repo,
        transaction_manager=transaction_manager,
    )
    dispatcher["complaint_service"] = ComplaintService(
        complaint_repo=complaint_repo, transaction_manager=transaction_manager
    )

    # Add repositories for easier testing
    dispatcher["user_repo"] = user_repo
    dispatcher["advertiser_repo"] = advertiser_repo
    dispatcher["blogger_repo"] = blogger_repo
    dispatcher["order_repo"] = order_repo
    dispatcher["interaction_repo"] = interaction_repo

    dispatcher.bot = mock_bot
    return dispatcher


@pytest.fixture(scope="function")
async def user_context(dispatcher):
    """Context for user interactions in tests."""
    # This fixture provides access to all services through dispatcher
    return dispatcher


# Helper functions for creating test data
@pytest.fixture(scope="function")
def create_test_user(session):
    """Helper to create test user."""

    def _create_user(external_id: str, messenger_type: str = "telegram"):
        from ugc_bot.domain.entities import User
        from ugc_bot.domain.enums import MessengerType, UserStatus
        from datetime import datetime, timezone

        user = User(
            user_id=None,  # Will be set by repo
            external_id=external_id,
            messenger_type=MessengerType.TELEGRAM,
            username=f"user_{external_id}",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=datetime.now(timezone.utc),
        )
        return user

    return _create_user


@pytest.fixture(scope="function")
def create_test_blogger_profile(session):
    """Helper to create test blogger profile."""

    def _create_profile(user_id, **kwargs):
        from ugc_bot.domain.entities import BloggerProfile
        from ugc_bot.domain.enums import AudienceGender
        from datetime import datetime, timezone

        defaults = {
            "instagram_url": "https://instagram.com/test_blogger",
            "audience_gender": AudienceGender.ALL,
            "audience_age_min": 18,
            "audience_age_max": 35,
            "audience_geo": "Russia",
            "confirmation_code": "ABC123",
            "confirmed": True,
            "price": 5000.0,
            "updated_at": datetime.now(timezone.utc),
        }
        defaults.update(kwargs)

        profile = BloggerProfile(user_id=user_id, **defaults)
        return profile

    return _create_profile


@pytest.fixture(scope="function")
def create_test_order(session):
    """Helper to create test order."""

    def _create_order(advertiser_id, **kwargs):
        from ugc_bot.domain.entities import Order
        from ugc_bot.domain.enums import OrderStatus
        from datetime import datetime, timezone
        from uuid import uuid4

        defaults = {
            "order_id": uuid4(),
            "product_link": "https://example.com/product",
            "offer_text": "Test offer",
            "bloggers_needed": 3,
            "price": 15000.0,
            "status": OrderStatus.NEW,
            "created_at": datetime.now(timezone.utc),
        }
        defaults.update(kwargs)

        order = Order(**defaults)
        return order

    return _create_order
