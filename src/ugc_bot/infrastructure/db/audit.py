"""SQLAlchemy event listener for automatic audit logging."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from ugc_bot.domain.enums import AuditAction
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    PaymentModel,
    PayoutRequestModel,
)

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
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    return value


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


def _get_all_values(obj: Any, skip: frozenset[str] = _SKIP_ATTRS) -> dict[str, Any]:
    """Return all column values for a new object."""
    insp = inspect(obj)
    result: dict[str, Any] = {}
    for attr in insp.attrs:
        if attr.key in skip:
            continue
        val = attr.loaded_value
        if val is not None:
            result[attr.key] = _serialize_value(val)
    return result


def _before_flush(session: Session, flush_context: Any, instances: Any) -> None:
    """Capture changes to tracked models before they are flushed."""
    actor = session.info.get("audit_actor")
    entries: list[AuditLogModel] = []

    for obj in session.new:
        cfg = _TRACKED.get(type(obj))
        if cfg is None:
            continue
        entity_type, pk_attr = cfg
        new_values = _get_all_values(obj)
        entries.append(
            AuditLogModel(
                entity_type=entity_type,
                entity_id=getattr(obj, pk_attr),
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


def register_audit_listener(engine: Any) -> None:
    """Register the audit listener on the given engine's Session."""
    event.listen(Session, "before_flush", _before_flush)
