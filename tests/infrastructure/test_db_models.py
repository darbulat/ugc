"""Tests for _GeometryOrText TypeDecorator in infrastructure/db/models.py."""

from unittest.mock import MagicMock

from ugc_bot.infrastructure.db.models import _GeometryOrText

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dialect(name: str) -> MagicMock:
    """Return a minimal SQLAlchemy dialect mock with the given name."""
    dialect = MagicMock()
    dialect.name = name
    return dialect


# ---------------------------------------------------------------------------
# load_dialect_impl
# ---------------------------------------------------------------------------


def test_load_dialect_impl_postgresql_returns_geometry() -> None:
    """load_dialect_impl returns a Geometry impl for the postgresql dialect.

    This covers line 54 of models.py:
        return Geometry(geometry_type=self.geometry_type, srid=self.srid)
    """
    col_type = _GeometryOrText(geometry_type="MULTIPOINT", srid=4326)
    dialect = _make_dialect("postgresql")

    # SQLAlchemy's TypeDecorator.load_dialect_impl delegates to impl_instance
    # by default, but _GeometryOrText overrides it.  We call it directly.
    result = col_type.load_dialect_impl(dialect)

    # The result must be a Geometry instance (geoalchemy2)
    from geoalchemy2 import Geometry

    assert isinstance(result, Geometry)
    assert result.geometry_type == "MULTIPOINT"
    assert result.srid == 4326


def test_load_dialect_impl_non_postgresql_returns_text() -> None:
    """load_dialect_impl returns Text impl for non-postgresql dialects."""
    from sqlalchemy import Text

    col_type = _GeometryOrText(geometry_type="POINT", srid=4326)
    dialect = _make_dialect("sqlite")

    result = col_type.load_dialect_impl(dialect)
    assert isinstance(result, Text)


# ---------------------------------------------------------------------------
# process_bind_param — non-postgresql dialect with hasattr(value, "desc")
# ---------------------------------------------------------------------------


def test_process_bind_param_non_pg_with_desc_attribute_returns_desc() -> None:
    """process_bind_param returns value.desc for non-pg when value has .desc.

    This covers lines 67-68 of models.py:
        if hasattr(value, "desc"):
            return value.desc
    """
    col_type = _GeometryOrText(geometry_type="POINT", srid=4326)
    dialect = _make_dialect("sqlite")

    # Simulate a WKTElement (or any object) that exposes a .desc attribute
    fake_wkt_element = MagicMock()
    fake_wkt_element.desc = "POINT(37.6 55.75)"

    result = col_type.process_bind_param(fake_wkt_element, dialect)
    assert result == "POINT(37.6 55.75)"


def test_process_bind_param_non_pg_without_desc_returns_value_as_is() -> None:
    """process_bind_param returns raw value for non-pg when no .desc."""
    col_type = _GeometryOrText(geometry_type="POINT", srid=4326)
    dialect = _make_dialect("sqlite")

    wkt_string = "POINT(37.6 55.75)"
    result = col_type.process_bind_param(wkt_string, dialect)
    assert result == wkt_string


def test_process_bind_param_none_returns_none() -> None:
    """process_bind_param returns None when value is None (any dialect)."""
    col_type = _GeometryOrText(geometry_type="POINT", srid=4326)

    for dialect_name in ("postgresql", "sqlite"):
        dialect = _make_dialect(dialect_name)
        assert col_type.process_bind_param(None, dialect) is None


def test_process_bind_param_postgresql_string_returns_wkt_element() -> None:
    """process_bind_param wraps a plain string in WKTElement for postgresql."""
    from geoalchemy2.elements import WKTElement

    col_type = _GeometryOrText(geometry_type="POINT", srid=4326)
    dialect = _make_dialect("postgresql")

    result = col_type.process_bind_param("POINT(37.6 55.75)", dialect)
    assert isinstance(result, WKTElement)


def test_process_bind_param_postgresql_non_string_returned_as_is() -> None:
    """process_bind_param returns non-string values unchanged for postgresql."""
    col_type = _GeometryOrText(geometry_type="POINT", srid=4326)
    dialect = _make_dialect("postgresql")

    fake_element = object()
    result = col_type.process_bind_param(fake_element, dialect)
    assert result is fake_element
