"""SQLAlchemy event listener for automatic audit logging."""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session
from sqlalchemy.orm.base import ATTR_EMPTY, NO_VALUE

from ugc_bot.domain.enums import AuditAction
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    PaymentModel,
    PayoutRequestModel,
)

logger = logging.getLogger(__name__)

# Tracked models: model class -> (entity_type, pk_attr)
_TRACKED: dict[type, tuple[str, str]] = {
    PaymentModel: ("payment", "payment_id"),
    PayoutRequestModel: ("payout_request", "request_id"),
}

# Attributes to skip (internal / never useful in audit)
_SKIP_ATTRS = frozenset({"_sa_instance_state"})


def _serialize_value(value: Any) -> Any:
    """Convert value to JSON-compatible type."""
    if value is None:
        return None
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (str, int, float, bool)):
        return value
    logger.warning(
        "Audit: converting %s value to str for serialization",
        type(value).__name__,
    )
    return str(value)


def _get_changes(
    insp: Any,
) -> dict[str, tuple[Any, Any]]:
    """Return {attr: (old, new)} for actually changed attributes."""
    changes: dict[str, tuple[Any, Any]] = {}
    for attr in insp.attrs:
        if attr.key in _SKIP_ATTRS:
            continue
        hist = attr.history
        if hist.has_changes():
            old = _serialize_value(hist.deleted[0] if hist.deleted else None)
            new = _serialize_value(hist.added[0] if hist.added else None)
            if old != new:
                changes[attr.key] = (old, new)
    return changes


def _get_all_values(
    obj: Any, skip: frozenset[str] = _SKIP_ATTRS
) -> dict[str, Any]:
    """Return all column values for an object (including None)."""
    insp = inspect(obj)
    result: dict[str, Any] = {}
    for attr in insp.attrs:
        if attr.key in skip:
            continue
        val = attr.loaded_value
        if val is NO_VALUE or val is ATTR_EMPTY:
            val = None
        result[attr.key] = _serialize_value(val)
    return result


def _before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    """Capture changes to tracked models before they are flushed."""
    if not session.info.get("audit_enabled", True):
        return

    try:
        _collect_audit_entries(session)
    except Exception:
        logger.exception(
            "Audit log listener failed; audit entries skipped. "
            "Business transaction will proceed without audit record."
        )


def _collect_audit_entries(session: Session) -> None:
    """Collect and add audit entries for tracked model changes."""
    actor = session.info.get("audit_actor")
    entries: list[AuditLogModel] = []

    for obj in session.new:
        cfg = _TRACKED.get(type(obj))
        if cfg is None:
            continue
        entity_type, pk_attr = cfg
        entity_id = getattr(obj, pk_attr)
        if entity_id is None:
            logger.warning(
                "Audit: skipping CREATE for %s — %s is None "
                "(server-generated PK not yet available before flush)",
                entity_type,
                pk_attr,
            )
            continue
        new_values = _get_all_values(obj)
        entries.append(
            AuditLogModel(
                entity_type=entity_type,
                entity_id=entity_id,
                action=AuditAction.CREATE,
                old_values=None,
                new_values=new_values,
                changed_by=actor,
            )
        )

    for obj in session.dirty:
        cfg = _TRACKED.get(type(obj))
        if cfg is None:
            continue
        entity_type, pk_attr = cfg
        insp = inspect(obj)
        changes = _get_changes(insp)
        if not changes:
            continue
        entries.append(
            AuditLogModel(
                entity_type=entity_type,
                entity_id=getattr(obj, pk_attr),
                action=AuditAction.UPDATE,
                old_values={k: v[0] for k, v in changes.items()},
                new_values={k: v[1] for k, v in changes.items()},
                changed_by=actor,
            )
        )

    for obj in session.deleted:
        cfg = _TRACKED.get(type(obj))
        if cfg is None:
            continue
        entity_type, pk_attr = cfg
        old_values = _get_all_values(obj)
        entries.append(
            AuditLogModel(
                entity_type=entity_type,
                entity_id=getattr(obj, pk_attr),
                action=AuditAction.DELETE,
                old_values=old_values,
                new_values={},
                changed_by=actor,
            )
        )

    for entry in entries:
        session.add(entry)


_registered = False


def register_audit_listener() -> None:
    """Register the audit listener on all Sessions (class-level, once)."""
    global _registered  # noqa: PLW0603
    if _registered:
        return
    _registered = True
    event.listen(Session, "before_flush", _before_flush)
