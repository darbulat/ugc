"""Shared session management and geometry helpers for repositories."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Optional, Union
from typing import cast as typing_cast

from geoalchemy2 import shape
from geoalchemy2.elements import WKBElement, WKTElement
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


def _geometry_to_wkt(geom: object | None) -> Optional[str]:
    """Convert GeoAlchemy2 geometry column value to WKT string.

    Requires geoalchemy2[shapely] for WKBElement/WKTElement from PostgreSQL.
    """
    if geom is None:
        return None
    if isinstance(geom, str):
        return geom if geom.strip() else None
    try:
        return shape.to_shape(
            typing_cast(Union[WKBElement, WKTElement], geom)
        ).wkt
    except Exception as exc:
        logger.warning(
            "Failed to convert geometry to WKT",
            extra={"geom_type": type(geom).__name__, "error": str(exc)},
        )
        return None


def _wkt_to_geometry_element(
    wkt: Optional[str], srid: int = 4326
) -> object | None:
    """Convert WKT string to GeoAlchemy2 WKTElement for insert/update."""
    if not wkt or not wkt.strip():
        return None
    return WKTElement(wkt, srid=srid)


def _require_session(session: AsyncSession | None) -> AsyncSession:
    """Ensure an AsyncSession is provided.

    We keep `session: object | None` in repository ports to support in-memory
    repositories in unit tests. SQLAlchemy repositories must always operate
    with an explicit session provided by a higher-level transaction boundary
    (e.g., transaction manager).
    """
    if session is None:
        raise RuntimeError(
            "Database session is required. Use a transaction boundary and pass "
            "the session explicitly (e.g., via transaction manager)."
        )
    return session


def _get_async_session(session: object | None) -> AsyncSession:
    """Return a session-like object or raise with a clear error.

    We intentionally avoid strict `isinstance(..., AsyncSession)` checks to keep
    repository unit tests fast (they use lightweight fake sessions).
    """
    if session is None:
        return _require_session(None)
    # At runtime, we only require that the object behaves like an AsyncSession.
    return session  # type: ignore[return-value]


@asynccontextmanager
async def _resolve_session(
    session_factory: Any,
    session: object | None = None,
) -> AsyncIterator[AsyncSession]:
    """Use the provided session or open a new auto-committing one.

    When *session* is given (e.g., from a transaction manager), it is yielded
    as-is — the caller owns the transaction.  When *session* is ``None``, a
    fresh session is created from *session_factory*, committed on success,
    rolled back on error, and closed on exit.
    """
    if session is not None:
        yield session  # type: ignore[misc]
    else:
        new_session = session_factory()
        try:
            yield new_session
            await new_session.commit()
        except Exception:
            await new_session.rollback()
            raise
        finally:
            await new_session.close()
