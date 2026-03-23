"""Tests for audit log event listener."""

from datetime import datetime, timezone
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


class TestAuditBeforeFlush:
    def test_create_payment_generates_audit_entry(self, db_session):
        payment_id = uuid4()
        order_id = uuid4()
        now = datetime.now(tz=timezone.utc)
        payment = PaymentModel(
            payment_id=payment_id,
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PENDING,
            amount=100.0,
            currency="RUB",
            external_id="ext-1",
            created_at=now,
            updated_at=now,
        )
        db_session.add(payment)
        db_session.flush()

        entries = db_session.query(AuditLogModel).all()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.entity_type == "payment"
        assert entry.entity_id == payment_id
        assert entry.action == AuditAction.CREATE
        assert entry.old_values is None
        assert entry.new_values["status"] == "pending"
        assert entry.new_values["amount"] == 100.0

    def test_update_payment_generates_audit_entry(self, db_session):
        payment_id = uuid4()
        order_id = uuid4()
        now = datetime.now(tz=timezone.utc)
        payment = PaymentModel(
            payment_id=payment_id,
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PENDING,
            amount=100.0,
            currency="RUB",
            external_id="ext-2",
            created_at=now,
            updated_at=now,
        )
        db_session.add(payment)
        db_session.flush()

        # Update status
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
        assert entry.entity_type == "payment"
        assert entry.entity_id == payment_id
        assert entry.old_values["status"] == "pending"
        assert entry.new_values["status"] == "paid"

    def test_delete_payment_generates_audit_entry(self, db_session):
        payment_id = uuid4()
        order_id = uuid4()
        now = datetime.now(tz=timezone.utc)
        payment = PaymentModel(
            payment_id=payment_id,
            order_id=order_id,
            provider="test",
            status=PaymentStatus.PENDING,
            amount=100.0,
            currency="RUB",
            external_id="ext-3",
            created_at=now,
            updated_at=now,
        )
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
        assert entry.entity_id == payment_id
        assert entry.old_values["status"] == "pending"
        assert entry.new_values == {}

    def test_audit_actor_is_recorded(self, db_session):
        actor_id = uuid4()
        db_session.info["audit_actor"] = actor_id

        payment_id = uuid4()
        now = datetime.now(tz=timezone.utc)
        payment = PaymentModel(
            payment_id=payment_id,
            order_id=uuid4(),
            provider="test",
            status=PaymentStatus.PENDING,
            amount=50.0,
            currency="RUB",
            external_id="ext-4",
            created_at=now,
            updated_at=now,
        )
        db_session.add(payment)
        db_session.flush()

        entry = db_session.query(AuditLogModel).one()
        assert entry.changed_by == actor_id

    def test_audit_disabled_skips_logging(self, db_session):
        db_session.info["audit_enabled"] = False

        payment = PaymentModel(
            payment_id=uuid4(),
            order_id=uuid4(),
            provider="test",
            status=PaymentStatus.PENDING,
            amount=50.0,
            currency="RUB",
            external_id="ext-5",
            created_at=datetime.now(tz=timezone.utc),
            updated_at=datetime.now(tz=timezone.utc),
        )
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
        # Only the manually added entry, no recursive audit
        assert len(entries) == 1
