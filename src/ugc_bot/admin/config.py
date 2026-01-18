"""Admin configuration helpers."""

from __future__ import annotations

from sqlalchemy.engine import make_url


def build_async_database_url(database_url: str, override_url: str = "") -> str:
    """Build an async database URL for admin panel."""

    source = override_url.strip() or database_url.strip()
    if not source:
        raise ValueError("ADMIN_DATABASE_URL or DATABASE_URL is required.")

    url = make_url(source)
    drivername = url.drivername
    if drivername.startswith("postgresql+psycopg"):
        drivername = "postgresql+asyncpg"
    elif drivername == "postgresql":
        drivername = "postgresql+asyncpg"
    return str(url.set(drivername=drivername))
