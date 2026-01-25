"""Integration tests for SQLAdmin page rendering."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from ugc_bot.admin.app import create_admin_app
from ugc_bot.config import AppConfig
from ugc_bot.infrastructure.db.base import Base


@pytest.fixture(scope="function")
def test_db_engine():
    """Create in-memory SQLite engine for admin tests."""
    engine = create_engine("sqlite:///:memory:", echo=False)

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


def test_admin_app_creation(admin_config):
    """Test that admin app can be created without errors."""
    from ugc_bot.admin.app import create_admin_app

    # Проверяем, что приложение создается без ошибок (включая SQLAdmin инициализацию)
    app = create_admin_app()

    # Проверяем, что приложение создано
    assert app is not None

    # Проверяем, что есть маршрут админки
    admin_routes = [
        route
        for route in app.routes
        if hasattr(route, "path") and "/admin" in str(route.path)
    ]
    assert len(admin_routes) > 0

    print("✅ Admin app creation test passed!")


def test_sqladmin_models_initialization(admin_config):
    """Test that SQLAdmin models can be initialized without column_filters errors."""
    from ugc_bot.admin.app import (
        UserAdmin,
        InteractionAdmin,
        ComplaintAdmin,
        BloggerProfileAdmin,
        AdvertiserProfileAdmin,
        OrderAdmin,
    )

    # Проверяем, что все админ-классы могут быть созданы без ошибок
    # Это проверяет, что column_list, form_columns и другие атрибуты корректны
    try:
        UserAdmin()
        InteractionAdmin()
        ComplaintAdmin()
        BloggerProfileAdmin()
        AdvertiserProfileAdmin()
        OrderAdmin()
    except Exception as e:
        pytest.fail(f"Failed to create admin classes: {e}")

    # Проверяем, что у классов есть необходимые атрибуты
    assert hasattr(UserAdmin, "column_list")
    assert hasattr(InteractionAdmin, "column_list")
    assert hasattr(ComplaintAdmin, "column_list")

    # Проверяем, что column_filters не вызывает ошибок (мы убрали проблемные фильтры)
    # Проверка что классы могут быть созданы - это главное

    print("✅ SQLAdmin models initialization test passed!")
