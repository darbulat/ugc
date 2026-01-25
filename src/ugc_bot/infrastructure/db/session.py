"""Database session factory and transaction helpers."""

from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_db_engine(database_url: str) -> Engine:
    """Create a SQLAlchemy engine."""

    return create_engine(database_url, pool_pre_ping=True)


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    """Create a configured session factory."""

    engine = create_db_engine(database_url)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


class SessionTransactionManager:
    """Transaction manager for SQLAlchemy sessions."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    @contextmanager
    def transaction(self):
        """Provide a transactional session scope."""
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
