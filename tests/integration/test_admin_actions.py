"""Integration tests for admin actions through SQLAdmin interface."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ugc_bot.admin.app import create_admin_app
from ugc_bot.config import AppConfig
from ugc_bot.domain.entities import Complaint, Interaction, Order, User
from ugc_bot.domain.enums import (
    ComplaintStatus,
    InteractionStatus,
    OrderStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.base import Base


@pytest.fixture(scope="function")
def test_db_engine():
    """Create in-memory SQLite engine for admin tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)

    # Exclude tables with JSONB (not compatible with SQLite)
    tables_to_exclude = {"outbox_events", "blogger_profiles", "fsm_drafts"}
    tables_to_create = [
        table
        for table in Base.metadata.tables.values()
        if table.name not in tables_to_exclude
    ]
    Base.metadata.create_all(bind=engine, tables=tables_to_create)
    return engine


@pytest.fixture(scope="function")
def admin_config(test_db_engine):
    """Test configuration for admin."""
    return AppConfig.model_validate(
        {
            "BOT_TOKEN": "test_token_123",
            "DATABASE_URL": str(test_db_engine.url),
            "KAFKA_ENABLED": False,
            "ADMIN_USERNAME": "test_admin",
            "ADMIN_PASSWORD": "test_pass",
            "ADMIN_SECRET": "test_secret",
            "TELEGRAM_PROVIDER_TOKEN": "test_provider_token",
        }
    )


@pytest.fixture(scope="function")
def admin_client(admin_config):
    """FastAPI test client for admin app."""
    app = create_admin_app()
    return TestClient(app)


@pytest.fixture(scope="function")
def db_session(test_db_engine):
    """Database session for tests."""
    SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=test_db_engine
    )
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def sample_user(db_session: Session):
    """Create a sample user for testing."""
    from ugc_bot.infrastructure.db.repositories import SqlAlchemyUserRepository

    user_repo = SqlAlchemyUserRepository(lambda: db_session)
    user = User(
        user_id=None,
        external_id="test_user_123",
        messenger_type="telegram",
        username="testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    saved_user = user_repo.save(user)
    db_session.commit()
    return saved_user


@pytest.fixture(scope="function")
def sample_order(db_session: Session, sample_user: User):
    """Create a sample order for testing."""
    from ugc_bot.infrastructure.db.repositories import SqlAlchemyOrderRepository

    order_repo = SqlAlchemyOrderRepository(lambda: db_session)
    order = Order(
        order_id=uuid4(),
        advertiser_id=sample_user.user_id,
        product_link="https://example.com/product",
        offer_text="Test offer",
        bloggers_needed=3,
        price=15000.0,
        status=OrderStatus.NEW,
        created_at=datetime.now(timezone.utc),
    )
    saved_order = order_repo.save(order)
    db_session.commit()
    return saved_order


@pytest.fixture(scope="function")
def sample_interaction(
    db_session: Session, sample_order: Order, sample_user: User
):
    """Create a sample interaction for testing."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyInteractionRepository,
    )

    interaction_repo = SqlAlchemyInteractionRepository(lambda: db_session)
    interaction = Interaction(
        interaction_id=None,
        order_id=sample_order.order_id,
        blogger_id=sample_user.user_id,
        advertiser_id=sample_user.user_id,  # Для простоты тот же пользователь
        status=InteractionStatus.ISSUE,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    saved_interaction = interaction_repo.save(interaction)
    db_session.commit()
    return saved_interaction


@pytest.fixture(scope="function")
def sample_complaint(
    db_session: Session, sample_order: Order, sample_user: User
):
    """Create a sample complaint for testing."""
    from ugc_bot.infrastructure.db.repositories import (
        SqlAlchemyComplaintRepository,
    )

    complaint_repo = SqlAlchemyComplaintRepository(lambda: db_session)
    complaint = Complaint(
        complaint_id=None,
        reporter_id=sample_user.user_id,
        reported_id=sample_user.user_id,  # Для простоты тот же пользователь
        order_id=sample_order.order_id,
        reason="Мошенничество",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        reviewed_at=None,
    )
    saved_complaint = complaint_repo.save(complaint)
    db_session.commit()
    return saved_complaint


def test_admin_action_methods_exist():
    """Test that admin classes have the required action methods."""
    from ugc_bot.admin.app import ComplaintAdmin, InteractionAdmin, UserAdmin

    # Проверяем, что у админ-классов есть методы update_model
    assert hasattr(UserAdmin, "update_model")
    assert hasattr(InteractionAdmin, "update_model")
    assert hasattr(ComplaintAdmin, "update_model")

    # Проверяем, что это асинхронные методы
    import inspect

    assert inspect.iscoroutinefunction(UserAdmin.update_model)
    assert inspect.iscoroutinefunction(InteractionAdmin.update_model)
    assert inspect.iscoroutinefunction(ComplaintAdmin.update_model)

    print("✅ Admin action methods exist test passed!")


@pytest.mark.asyncio
async def test_admin_update_model_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Smoke-test custom update_model hooks don't crash.

    We mock SQLAdmin update_model and async session to exercise the
    branch logic without requiring a real AsyncSession/DB.
    """

    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from uuid import UUID

    from ugc_bot.admin import app as admin_app
    from ugc_bot.admin.app import ComplaintAdmin, InteractionAdmin, UserAdmin
    from ugc_bot.domain.enums import (
        ComplaintStatus,
        InteractionStatus,
        UserStatus,
    )

    async def _noop_update_model(self, request, pk: str, data: dict) -> None:  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(admin_app.ModelView, "update_model", _noop_update_model)

    class DummySession:
        """Minimal async session stub for update_model hooks."""

        def __init__(self, objects: list[object]) -> None:
            self._objects = objects
            self._idx = 0

        async def get(self, model_cls, pk):  # type: ignore[no-untyped-def]
            obj = self._objects[self._idx]
            self._idx += 1
            return obj

    def make_session_maker(dummy: DummySession):
        """Session maker yielding dummy session as context manager."""

        @asynccontextmanager
        async def _cm():
            yield dummy

        return lambda **kwargs: _cm()

    pk = "00000000-0000-0000-0000-000000000001"

    user_admin = UserAdmin()
    user_admin.is_async = True  # type: ignore[attr-defined]
    user_admin.session_maker = make_session_maker(  # type: ignore[attr-defined]
        DummySession(
            [
                SimpleNamespace(status=UserStatus.ACTIVE),
                SimpleNamespace(status=UserStatus.BLOCKED),
            ]
        )
    )
    await user_admin.update_model(object(), pk, {"status": UserStatus.BLOCKED})

    interaction_admin = InteractionAdmin()
    interaction_admin.is_async = True  # type: ignore[attr-defined]
    interaction_admin.session_maker = make_session_maker(  # type: ignore[attr-defined]
        DummySession(
            [
                SimpleNamespace(status=InteractionStatus.ISSUE),
                SimpleNamespace(status=InteractionStatus.OK),
            ]
        )
    )
    await interaction_admin.update_model(
        object(), pk, {"status": InteractionStatus.OK}
    )

    reported_id = UUID("00000000-0000-0000-0000-000000000002")
    complaint_admin = ComplaintAdmin()
    complaint_admin.is_async = True  # type: ignore[attr-defined]
    complaint_admin.session_maker = make_session_maker(  # type: ignore[attr-defined]
        DummySession(
            [
                SimpleNamespace(
                    status=ComplaintStatus.PENDING, reported_id=reported_id
                ),
                SimpleNamespace(
                    status=ComplaintStatus.ACTION_TAKEN, reported_id=reported_id
                ),
            ]
        )
    )
    await complaint_admin.update_model(
        object(), pk, {"status": ComplaintStatus.ACTION_TAKEN}
    )
