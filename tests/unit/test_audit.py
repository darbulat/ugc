"""Tests for audit log event listener."""

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from ugc_bot.domain.enums import AuditAction, PaymentStatus
from ugc_bot.infrastructure.db.audit import _serialize_value
from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import AuditLogModel, PaymentModel


class TestSerializeValue:
    def test_uuid(self):
        uid = uuid4()
        assert _serialize_value(uid) == str(uid)

    def test_datetime(self):
        dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert _serialize_value(dt) == "2026-01-01T12:00:00+00:00"

    def test_date(self):
        d = date(2026, 1, 1)
        assert _serialize_value(d) == "2026-01-01"

    def test_decimal(self):
        assert _serialize_value(Decimal("10.50")) == "10.50"

    def test_enum(self):
        assert _serialize_value(PaymentStatus.PAID) == "paid"
        assert _serialize_value(AuditAction.CREATE) == "create"

    def test_none(self):
        assert _serialize_value(None) is None

    def test_string(self):
        assert _serialize_value("hello") == "hello"

    def test_int(self):
        assert _serialize_value(42) == 42

    def test_float(self):
        assert _serialize_value(3.14) == 3.14

    def test_bool(self):
        assert _serialize_value(True) is True

    def test_unknown_type_falls_back_to_str(self):
        """Unknown types are converted to str with a warning log."""
        result = _serialize_value(b"bytes-data")
        assert result == "b'bytes-data'"


@pytest.fixture()
def db_session():
    """Create an in-memory SQLite database with audit tables."""
    from ugc_bot.infrastructure.db.audit import register_audit_listener

    register_audit_listener()
    engine = create_engine("sqlite:///:memory:")
    tables = [
        Base.metadata.tables["payments"],
        Base.metadata.tables["audit_log"],
    ]
    Base.metadata.create_all(bind=engine, tables=tables)
    with Session(engine) as session:
        yield session


def _make_payment(**overrides) -> PaymentModel:
    """Helper to create a PaymentModel with defaults."""
    now = datetime.now(tz=timezone.utc)
    defaults = {
        "payment_id": uuid4(),
        "order_id": uuid4(),
        "provider": "test",
        "status": PaymentStatus.PENDING,
        "amount": 100.0,
        "currency": "RUB",
        "external_id": f"ext-{uuid4().hex[:8]}",
        "created_at": now,
        "updated_at": now,
    }
    defaults.update(overrides)
    return PaymentModel(**defaults)


class TestAuditBeforeFlush:
    def test_create_payment_generates_audit_entry(self, db_session):
        payment = _make_payment()
        db_session.add(payment)
        db_session.flush()

        entries = db_session.query(AuditLogModel).all()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.entity_type == "payment"
        assert entry.entity_id == payment.payment_id
        assert entry.action == AuditAction.CREATE
        assert entry.old_values is None
        assert entry.new_values["status"] == "pending"
        assert entry.new_values["amount"] == 100.0

    def test_create_includes_none_values(self, db_session):
        """None-valued fields (e.g. paid_at) are included in audit snapshot."""
        payment = _make_payment()
        db_session.add(payment)
        db_session.flush()

        entry = db_session.query(AuditLogModel).one()
        assert "paid_at" in entry.new_values
        assert entry.new_values["paid_at"] is None

    def test_update_payment_generates_audit_entry(self, db_session):
        payment = _make_payment()
        db_session.add(payment)
        db_session.flush()

        now = datetime.now(tz=timezone.utc)
        payment.status = PaymentStatus.PAID
        payment.paid_at = now
        db_session.flush()

        entries = (
            db_session.query(AuditLogModel)
            .filter(AuditLogModel.action == AuditAction.UPDATE)
            .all()
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry.old_values["status"] == "pending"
        assert entry.new_values["status"] == "paid"
        assert "paid_at" in entry.new_values

    def test_noop_update_produces_no_audit_entry(self, db_session):
        """Setting attribute to same value should not create audit entry."""
        payment = _make_payment()
        db_session.add(payment)
        db_session.flush()

        # Set status to same value
        payment.status = PaymentStatus.PENDING
        db_session.flush()

        update_entries = (
            db_session.query(AuditLogModel)
            .filter(AuditLogModel.action == AuditAction.UPDATE)
            .all()
        )
        assert len(update_entries) == 0

    def test_delete_payment_generates_audit_entry(self, db_session):
        payment = _make_payment()
        db_session.add(payment)
        db_session.flush()

        db_session.delete(payment)
        db_session.flush()

        entries = (
            db_session.query(AuditLogModel)
            .filter(AuditLogModel.action == AuditAction.DELETE)
            .all()
        )
        assert len(entries) == 1
        entry = entries[0]
        assert entry.entity_type == "payment"
        assert entry.entity_id == payment.payment_id
        assert entry.old_values["status"] == "pending"
        assert entry.new_values == {}

    def test_audit_actor_is_recorded(self, db_session):
        actor_id = uuid4()
        db_session.info["audit_actor"] = actor_id

        payment = _make_payment()
        db_session.add(payment)
        db_session.flush()

        entry = db_session.query(AuditLogModel).one()
        assert entry.changed_by == actor_id

    def test_audit_disabled_skips_logging(self, db_session):
        db_session.info["audit_enabled"] = False

        payment = _make_payment()
        db_session.add(payment)
        db_session.flush()

        entries = db_session.query(AuditLogModel).all()
        assert len(entries) == 0

    def test_untracked_model_ignored(self, db_session):
        """AuditLogModel itself should not trigger audit entries."""
        audit_entry = AuditLogModel(
            entity_type="test",
            entity_id=uuid4(),
            action=AuditAction.CREATE,
            old_values=None,
            new_values={"test": True},
        )
        db_session.add(audit_entry)
        db_session.flush()

        entries = db_session.query(AuditLogModel).all()
        assert len(entries) == 1

    def test_multiple_entities_in_single_flush(self, db_session):
        """Multiple tracked objects in one flush produce separate entries."""
        p1 = _make_payment()
        p2 = _make_payment()
        db_session.add_all([p1, p2])
        db_session.flush()

        entries = db_session.query(AuditLogModel).all()
        assert len(entries) == 2
        entity_ids = {e.entity_id for e in entries}
        assert entity_ids == {p1.payment_id, p2.payment_id}

    def test_register_audit_listener_idempotent(self, db_session):
        """Multiple register calls don't duplicate entries."""
        from ugc_bot.infrastructure.db.audit import register_audit_listener

        register_audit_listener()
        register_audit_listener()

        payment = _make_payment()
        db_session.add(payment)
        db_session.flush()

        entries = db_session.query(AuditLogModel).all()
        assert len(entries) == 1
