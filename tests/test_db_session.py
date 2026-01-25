"""Tests for database session helpers."""

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from ugc_bot.infrastructure.db.session import (
    SessionTransactionManager,
    create_db_engine,
    create_session_factory,
)


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


def test_transaction_manager_commit() -> None:
    """Transaction manager commits changes."""

    factory = create_session_factory("sqlite:///:memory:")
    manager = SessionTransactionManager(factory)

    with manager.transaction() as session:
        session.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)"))
        session.execute(text("INSERT INTO items (value) VALUES ('a')"))

    with factory() as session:
        count = session.execute(text("SELECT count(*) FROM items")).scalar_one()
    assert count == 1


def test_transaction_manager_rollback() -> None:
    """Transaction manager rolls back on error."""

    factory = create_session_factory("sqlite:///:memory:")
    manager = SessionTransactionManager(factory)

    with factory() as session:
        session.execute(text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)"))
        session.commit()

    with pytest.raises(RuntimeError):
        with manager.transaction() as session:
            session.execute(text("INSERT INTO items (value) VALUES ('a')"))
            raise RuntimeError("boom")

    with factory() as session:
        count = session.execute(text("SELECT count(*) FROM items")).scalar_one()
    assert count == 0
