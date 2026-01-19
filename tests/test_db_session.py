"""Tests for database session helpers."""

from sqlalchemy.engine import Engine

from ugc_bot.infrastructure.db.session import create_db_engine, create_session_factory


def test_create_db_engine() -> None:
    """Create database engine."""

    engine = create_db_engine("sqlite:///:memory:")
    assert isinstance(engine, Engine)


def test_create_session_factory() -> None:
    """Create session factory."""

    factory = create_session_factory("sqlite:///:memory:")
    session = factory()
    assert session is not None
    session.close()
